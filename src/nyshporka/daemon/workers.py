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
    if op_name == "acquire.start":
        return await _start_acquire(bus, ws, payload)
    if op_name == "read.start":
        return await _start_read(bus, ws, payload)
    raise ValueError(f"довга операція «{op_name}» не має виконавця")


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


async def _start_read(bus: JobBus, ws: Workspace,
                      payload: dict[str, Any]) -> JobRecord:
    """Поставити читання справи. План рахується ДО черги.

    Так «чим будемо читати і скільки це кадрів» відомо до старту, а не через
    годину — і завдання, приречене впасти на відсутній моделі, у чергу взагалі
    не потрапляє.
    """
    from nyshporka.htr import run as R

    plan = R.plan(payload.get("case_dir") or "",
                  out_dir=payload.get("out_dir") or "",
                  script=str(payload.get("script") or ""),
                  second_voice=bool(payload.get("second_voice", True)))
    job, created = await bus.enqueue(
        "read",
        title=f"{plan.case_dir.name}: {plan.frames} кадрів, {plan.model.name}",
        cfg={**plan.as_dict(), "case_key": payload.get("case_key") or ""},
        # Ключ — тека виходу: повторний запит на ту саму справу має віддати те
        # саме завдання, а не другий прогін, що б'ється з першим за карту.
        idempotency_key=f"read:{plan.out_dir}",
    )
    if created:
        _keep(asyncio.create_task(_run_read(bus, job, plan,
                                            str(payload.get("case_key") or ""))))
    return job


async def _run_read(bus: JobBus, job: JobRecord, plan: Any,
                    case_key: str) -> None:
    """Вести підпроцес раннера, переливаючи його канал прогресу в чергу."""
    from nyshporka.core.jobs import JobState, Progress
    from nyshporka.core.progress import split

    await bus.update(job.id, state=JobState.RUNNING)
    cmd = plan.command(progress_json=True, case_key=case_key)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    # 🔴 Хвіст ЛЮДСЬКОГО виводу зберігається окремо. Коли прогін падає, у
    # завданні лишається код повернення — а причина написана саме там, звичайним
    # рядком, і без нього діагностика починається з повторного прогону.
    tail: list[str] = []
    assert proc.stdout is not None
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", "replace").rstrip()
        ev, human = split(line)
        if ev is not None:
            await bus.update(job.id, progress=Progress(
                i=ev.i, n=ev.n, done=ev.done, skipped=ev.skipped,
                failed=ev.failed, basis="сторінка"))
        elif human:
            tail.append(human)
            del tail[:-40]
    rc = await proc.wait()

    # 🔴 Приймач повноти — ДИСК, а не код повернення. При шардингу тиха втрата
    # сторінок дає rc=0 і порожній перелік збоїв; єдине, що це ловить, — число
    # готових текстів проти числа кадрів.
    from nyshporka.htr import run as R

    done_pages = len(list(Path(plan.out_dir).glob("*.txt")))
    missing = max(0, R.count_frames(Path(plan.case_dir)) - done_pages)
    ok = rc == 0 and missing == 0
    await bus.update(
        job.id,
        state=JobState.DONE if ok else JobState.ERROR,
        error=("" if ok else
               (f"код {rc}" if rc else "") +
               (f"; без тексту лишилось {missing} сторінок" if missing else "")),
        result={"out_dir": str(plan.out_dir), "pages": done_pages,
                "missing": missing, "rc": rc, "tail": tail[-12:]})


def _safe(ref: str) -> str:
    """Адреса джерела → безпечне ім'я теки.

    Адреси несуть скісні, пробіли й кирилицю (`moldova/_2043433 …/2086525`);
    класти таке в шлях як є означало б і дерево тек із чужою структурою, і
    вихід за межі простору на першій же `..`.
    """
    import re

    out = re.sub(r"[^\w.\-]+", "_", ref.replace("/", "-").replace(":", "-"))
    return out.strip("_")[:120] or "case"
