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


#: Замок навколо «чи вже йде перезбірка» + постановки. Див. `_start_build`.
_BUILD_GATE = asyncio.Lock()

#: Те саме для довгих операцій без власного виконавця. Окремий від `_BUILD_GATE`
#: навмисно: спільний змусив би перезбірку реєстру чекати на злиття фонду, хоч
#: вони не діляться нічим.
_GENERIC_GATE = asyncio.Lock()


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
    if op_name == "cases.build":
        return await _start_build(bus, payload)
    return await _start_generic(bus, op_name, payload)


async def _start_generic(bus: JobBus, op_name: str,
                         payload: dict[str, Any]) -> JobRecord:
    """Довга операція без власного виконавця — тілом самої операції, у потоці.

    🔴 Це закриває КЛАС дефекту, а не два випадки. `long=True` означає «не
    тримай на ній HTTP-запит», а не «десь мусить бути окремо написаний
    виконавець»; доти будь-яка помічена так операція без запису в диспетчері
    відповідала браузеру 400 «не має виконавця». Саме це й сталося з
    `registry.collect` і `registry.merge`: у переліку `/api/ops` вони були,
    кнопка малювалась, а виклик відмовляв — тобто дефект був не в тому, що
    роботу не зроблено, а в тому, що вхід у неї вів у глухий кут.

    ⚠ Прогресу тут немає й бути не може: тіло операції — звичайна функція, вона
    не звітує про кроки. Тому робота показується як «іде», а не смугою; це
    чесніше за смугу, яка не рухається.
    """
    from nyshporka import ops as O
    from nyshporka.core.jobs import JobState

    op = O.get(op_name)
    if op is None:
        raise ValueError(f"невідома операція «{op_name}»")
    cfg = dict(payload or {})
    # 🔴 Другий однаковий прохід не заводиться, і це не косметика. Через цю
    # гілку йдуть `registry.collect` і `registry.merge` — обидві МУТУЮТЬ, і
    # `fonds/merge/write.py` пише реєстр звичайним `open("w")`, без tmp+replace.
    # Тобто два паралельні злиття того самого фонду труть один одному і реєстр,
    # і чергу розбіжностей; достатнього приводу шукати не треба — вистачає
    # подвійного кліку по кнопці.
    #
    # ⚠ Шукається АКТИВНА робота, а не ключ ідемпотентності. Ключ жив би ще
    # кілька хвилин після завершення й віддавав би СТАРИЙ готовий запис — а
    # тиснуть цю кнопку саме тому, що щось щойно змінилось.
    async with _GENERIC_GATE:
        for j in bus.jobs():
            if (j.kind == op_name and j.cfg == cfg
                    and j.state in (JobState.QUEUED, JobState.RUNNING)):
                return j
        job, _ = await bus.enqueue(op_name, title=op.summary, cfg=cfg)
    _keep(asyncio.create_task(_run_generic(bus, job, op_name, payload)))
    return job


async def _run_generic(bus: JobBus, job: JobRecord, op_name: str,
                       payload: dict[str, Any]) -> None:
    from nyshporka import ops as O
    from nyshporka.core.jobs import JobState

    await bus.update(job.id, state=JobState.RUNNING)
    try:
        env = await asyncio.to_thread(O.call, op_name, dict(payload or {}))
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    # 🔴 Невдача операції — це невдача РОБОТИ, а не успіх із полем `ok: false`
    # усередині. Інакше в черзі вона світилась би зеленим, і причину побачив би
    # лише той, хто розгорнув результат.
    if not env.ok:
        await bus.update(job.id, state=JobState.ERROR, error=env.error or "не вийшло")
        return
    await bus.update(job.id, state=JobState.DONE, result=env.as_dict().get("data"))


async def _start_build(bus: JobBus, payload: dict[str, Any]) -> JobRecord:
    """Перезбірка реєстру справ.

    🔴 Захист тут — від ДРУГОГО ОДНОЧАСНОГО проходу, а не від другої
    перезбірки взагалі, і різниця принципова. Два паралельні проходи писали б
    у ту саму базу й у той самий файл бібліотеки. Але ключ ідемпотентності
    живе десять хвилин і після завершення роботи віддавав би СТАРИЙ готовий
    запис — а натискають цю кнопку саме тому, що щойно щось змінилось:
    людина побачила б «готово» з числами до своєї зміни й повірила б їм.

    Тому шукається активна робота, а не ключ: поки перезбірка йде, повторні
    натискання чіпляються до неї; щойно вона завершилась — нове натискання дає
    новий прохід.
    """
    from nyshporka.core.jobs import JobState

    rescan = bool(payload.get("rescan", True))
    # Перевірка «чи вже йде» і постановка мусять бути НЕПОДІЛЬНІ: між ними є
    # точка очікування (лок черги), і без цього замка двоє одночасних натискань
    # обидва бачили б «нічого не йде» й завели б два проходи.
    async with _BUILD_GATE:
        for j in bus.jobs():
            if j.kind == "build" and j.state in (JobState.QUEUED, JobState.RUNNING):
                return j
        job, _ = await bus.enqueue("build", title="перезбірка реєстру справ",
                                   cfg={"rescan": rescan})
    _keep(asyncio.create_task(_run_build(bus, job, rescan)))
    return job


async def _run_build(bus: JobBus, job: JobRecord, rescan: bool) -> None:
    from nyshporka.core.jobs import JobState, Progress

    await bus.update(job.id, state=JobState.RUNNING)

    def work() -> dict[str, Any]:
        out: dict[str, Any] = {}
        if rescan:
            from nyshporka.library import build_library, write_library

            entries = build_library()
            write_library(entries)
            out["library"] = len(entries)
        from nyshporka.cases import db

        return {**out, **db.build_index()}

    try:
        res = await asyncio.to_thread(work)
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    n = int(res.get("cases") or 0)
    await bus.update(job.id, state=JobState.DONE, result=res,
                     progress=Progress(i=n, n=n, done=n, basis="справа"))


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
    # 🔴 Шифра береться З ТЕКИ, коли її не передали. Прогін без шифри стає в
    # реєстрі «нічиїм»: він є, текст є, а до якої справи належить — невідомо,
    # і зшивати це потім доводиться правкою JSON руками. З консолі шифру ніхто
    # не вводить (форма читання питає лише теку), тож без цього КОЖЕН запуск
    # кнопкою давав нічию — при тому, що опис лежить у тій самій теці.
    case_key = str(payload.get("case_key") or "") or _key_from_folder(plan.case_dir)
    job, created = await bus.enqueue(
        "read",
        title=f"{plan.case_dir.name}: {plan.frames} кадрів, {plan.model.name}",
        cfg={**plan.as_dict(), "case_key": case_key},
        # Ключ — тека виходу: повторний запит на ту саму справу має віддати те
        # саме завдання, а не другий прогін, що б'ється з першим за карту.
        idempotency_key=f"read:{plan.out_dir}",
    )
    if created:
        _keep(asyncio.create_task(_run_read(bus, job, plan,
                                            str(payload.get("case_key") or ""))))
    return job


def _key_from_folder(case_dir: Path) -> str:
    """Шифра з опису, що лежить у теці справи.

    Опис їде В ТЕЦІ саме для таких випадків: усе, що треба знати про матеріал,
    подорожує разом із ним. Немає опису — повертаємо порожнє, і прогін чесно
    лишається нічиїм: вигадувати шифру з імені теки не можна, бо приписаний не
    тій справі текст гірший за неприписаний.
    """
    try:
        from nyshporka.cases.register import read_sidecar

        return str(read_sidecar(case_dir).get("shifra") or "")
    except Exception:
        return ""


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
