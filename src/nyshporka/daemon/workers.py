"""⚙️ Довгі роботи: завантаження й читання — у фоні, з прогресом у ту саму чергу.

🔴 Чому не «просто запустити й дочекатись». Справа буває на кілька гігабайтів і
на годину роботи; синхронна відповідь означала б, що вкладку не можна закрити,
а агент отримав би таймаут мережі й почав ретраїти те, що вже йде.

🔴 Чому прогрес іде в чергу, а не в лог. Черга — єдине місце, куди дивляться
всі троє: браузер (курсором), агент (курсором), людина (списком). Другий канал
прогресу неминуче розійшовся б із першим, і «скільки лишилось» стало б питанням
про те, кому вірити.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nyshporka.core.jobs import JobBus, JobRecord
    from nyshporka.core.workspace import Workspace


#: 🔴 Живі задачі тримаються за посилання. `asyncio` зберігає лише СЛАБКЕ
#: посилання на задачу, тож без цього набору складальник сміття може прибрати
#: закачку посеред роботи — і виглядатиме це як обірваний прогін без причини:
#: ні винятку, ні запису в журналі, просто зупинилось.
_ALIVE: set[asyncio.Task[None]] = set()


def _keep(task: asyncio.Task[None]) -> None:
    _ALIVE.add(task)
    task.add_done_callback(_ALIVE.discard)


def _parse_frames(spec: str) -> tuple[int, int] | None:
    spec = (spec or "").strip()
    if not spec:
        return None
    lo, _, hi = spec.partition("-")
    try:
        return (int(lo), int(hi or lo))
    except ValueError:
        raise ValueError(f"діапазон кадрів «{spec}» очікується як «12-80»") from None


async def start(bus: JobBus, ws: Workspace, op_name: str,
                payload: dict[str, Any]) -> JobRecord:
    """Поставити довгу операцію в чергу й запустити виконавця."""
    if op_name != "acquire.start":
        raise ValueError(f"довга операція «{op_name}» не має виконавця")
    return await _start_acquire(bus, ws, payload)


async def _start_acquire(bus: JobBus, ws: Workspace,
                         payload: dict[str, Any]) -> JobRecord:
    from nyshporka.sources import load

    source_id = str(payload.get("source") or "")
    ref = str(payload.get("ref") or "")
    frames = _parse_frames(str(payload.get("frames") or ""))
    src = load(ws.root).get(source_id)
    if src is None:
        raise ValueError(f"немає джерела «{source_id}»")

    # Тека призначення — у простір, під архів і адресу. Так завантажене одразу
    # лежить там, де його шукає бібліотека, а не «десь, де тоді було зручно».
    dest = Path(payload.get("dest") or "") or (
        ws.raw / source_id / _safe(ref))

    # 🔴 Маніфест береться ДО постановки в чергу: питання «скільки це» мусить
    # мати відповідь до початку, а не після. Заразом це перевірка, що адреса
    # взагалі жива — інакше в черзі висіло б завдання, приречене впасти.
    man = await asyncio.to_thread(src.manifest, ref)
    total = man.frames if frames is None else (frames[1] - frames[0] + 1)

    job, created = await bus.enqueue(
        "acquire",
        title=f"{src.label}: {man.title or ref}",
        cfg={"source": source_id, "ref": ref, "dest": str(dest),
             "frames": list(frames) if frames else None, "total": total},
        # Ключ — сама адреса й діапазон: ретрай після обриву мережі не має
        # заводити другу закачку тієї самої плівки.
        idempotency_key=f"acquire:{source_id}:{ref}:{frames}",
    )
    if created:
        _keep(asyncio.create_task(
            _run_acquire(bus, src, job, dest, ref, frames, total)))
    return job


async def _run_acquire(bus: JobBus, src: Any, job: JobRecord, dest: Path,
                       ref: str, frames: tuple[int, int] | None,
                       total: int) -> None:
    from nyshporka.core.jobs import JobState, Progress

    await bus.update(job.id, state=JobState.RUNNING)
    loop = asyncio.get_running_loop()
    last = {"done": -1}

    def on_progress(done: int = 0, total: int = 0, **_: Any) -> None:
        # Кожен кадр у чергу не пишемо: 991 подія на плівку зробила б журнал
        # непридатним для читання й витіснила б із нього все інше.
        if done - last["done"] < 10 and done != total:
            return
        last["done"] = done
        asyncio.run_coroutine_threadsafe(
            bus.update(job.id, progress=Progress(i=done, n=total, done=done,
                                                 basis="кадр")), loop)

    try:
        res = await asyncio.to_thread(src.fetch, ref, dest, frames=frames,
                                      on_progress=on_progress)
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    await bus.update(
        job.id,
        state=JobState.ERROR if res.errors and not res.frames else JobState.DONE,
        error="; ".join(res.errors[:3]),
        result={"dest": str(res.dest), "frames": res.frames,
                "skipped": res.skipped, "bytes": res.bytes,
                "errors": len(res.errors)},
        progress=Progress(i=total, n=total, done=res.frames,
                          skipped=res.skipped, failed=len(res.errors),
                          basis="кадр"))


def _safe(ref: str) -> str:
    """Адреса джерела → безпечне ім'я теки.

    Адреси несуть скісні, пробіли й кирилицю (`moldova/_2043433 …/2086525`);
    класти таке в шлях як є означало б і дерево тек із чужою структурою, і
    вихід за межі простору на першій же `..`.
    """
    import re

    out = re.sub(r"[^\w.\-]+", "_", ref.replace("/", "-").replace(":", "-"))
    return out.strip("_")[:120] or "case"
