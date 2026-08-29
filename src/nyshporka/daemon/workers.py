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
import contextlib
import time
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nyshporka.core.jobs import JobBus, JobRecord
    from nyshporka.core.workspace import Workspace


#: 🔴 Живі задачі тримаються за посилання. `asyncio` зберігає лише слабке
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

#: 🔴🔴 Читання йдуть ПО ОДНОМУ. Не з обережності — інакше вони одне одного
#: завалюють.
#:
#: `idempotency_key` захищав лише від повторного запуску ТІЄЇ САМОЇ справи: дві
#: різні справи давали два `out_dir`, два завдання і два негайні
#: `create_task` — тобто на одній карті одночасно йшли два проходи сегментації.
#: Ціна названа в докстрінгу `htr.run.Plan.shards`: «`--shard` без спільного
#: `--gpu-lock` на одній карті не сповільнює прогін — він його ЗАВАЛЮЄ». Гірше
#: за просте падіння те, що число шардів кожен прогін рахує з ВІЛЬНОЇ пам'яті
#: карти, вважаючи карту своєю: другий міряє її до того, як перший завантажив
#: моделі, і обидва беруть по N (звіт користувача 29.08.2026 — дві справи
#: почались паралельно замість того, щоб стати в чергу).
#:
#: ⚠ Семафор, а не лок: очікування мусить лишати завдання в черзі ВИДИМИМ, з
#: підписом «чекає на карту». Слово «черга» в застосунку вже стояло
#: (`JobState.QUEUED`), і людина обґрунтовано чекала від нього черги — стан був,
#: а стримувати нікого не стримував.
#: ⚠ Семафор створюється ЛІНИВО й тримається за самим циклом подій, а не
#: константою модуля. `asyncio.Semaphore` прив'язується до першого циклу, який
#: його торкнувся, і в другому падає «bound to a different event loop» — тобто
#: гейт, який мусить рятувати прогін, сам би його й завалив.
#:
#: 🔴 Ключ — ОБ'ЄКТ циклу у `WeakKeyDictionary`, а не `id(loop)`. Словник за
#: числовим id не тримає циклу живим, CPython переInter'ретовує адресу, і
#: наступний цикл дістає семафор, прив'язаний до мертвого. Виявилось би це
#: лише під навантаженням: `Semaphore.acquire` не питає циклу, доки лічильник
#: більший за нуль, тож падало б рівно тоді, коли два читання таки зійшлись —
#: у ситуації, заради якої гейт і існує. А виняток у голому `create_task`
#: лишив би завдання назавжди в черзі, без жодного сліду на екрані.
_READ_GATES: weakref.WeakKeyDictionary[Any, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _read_gate() -> asyncio.Semaphore:
    """Гейт карти для ЧИННОГО циклу подій."""
    loop = asyncio.get_running_loop()
    gate = _READ_GATES.get(loop)
    if gate is None:
        gate = _READ_GATES[loop] = asyncio.Semaphore(1)
    return gate

#: Підпис завдання, яке стоїть у черзі за картою. Окремою константою — його
#: шукає приймач, а людина читає з нього, ЧОМУ нічого не відбувається.
WAITING_FOR_GPU = "чекає на карту"


def _keep(task: asyncio.Task[Any]) -> None:
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
    if op_name == "pick.ask":
        return await _start_pick(bus, payload)
    return await _start_generic(bus, op_name, payload)


async def _start_pick(bus: JobBus, payload: dict[str, Any]) -> JobRecord:
    """Системне вікно вибору — з тим, чим його закрити.

    🔴 Власний виконавець потрібен рівно заради одного рядка: реєстрації
    гасителя. Загальний виконавець крутить тіло операції в потоці й гасителя не
    реєструє, тож «Скасувати» над такою роботою міняє стан у черзі й нічого не
    зупиняє. Для читання справи це прикро, для системного вікна — неприйнятно:
    воно лишається висіти на екрані, а закрити його зі сторінки неможливо в
    принципі. Тобто без цих рядків кнопка скасування обіцяє те, чого не робить.

    ⚠ Гаситься слот, а не процес: слот знає сама операція, і в ньому може вже
    стояти інше вікно того самого поля.
    """
    job = await _start_generic(bus, "pick.ask", payload)

    from nyshporka.picker import native

    slot = str((payload or {}).get("purpose") or (payload or {}).get("mode") or "dir")
    def _shut() -> None:
        native.close(slot)

    bus.on_stop(job.id, _shut)
    return job


async def _start_generic(bus: JobBus, op_name: str,
                         payload: dict[str, Any]) -> JobRecord:
    """Довга операція без власного виконавця — тілом самої операції, у потоці.

    🔴 Це закриває клас дефекту, а не два випадки. `long=True` означає «не
    тримай на ній HTTP-запит», а не «десь мусить бути окремо написаний
    виконавець»; доти будь-яка помічена так операція без запису в диспетчері
    відповідала браузеру 400 «не має виконавця». Саме це й сталося з
    `registry.collect` і `registry.merge`: у переліку `/api/ops` вони були,
    кнопка малювалась, а виклик відмовляв — тобто дефект був не в тому, що
    роботу не зроблено, а в тому, що вхід у неї вів у глухий кут.

    ⚠ Поступ тут буває, але не завжди: тіло операції звітує через
    `core.progress.report`, якщо має що сказати. Мовчазна операція
    показується як «іде», а не смугою — це чесніше за смугу, яка не рухається.
    """
    from nyshporka import ops as O
    from nyshporka.core.jobs import JobState

    op = O.get(op_name)
    if op is None:
        raise ValueError(f"невідома операція «{op_name}»")
    cfg = dict(payload or {})
    # 🔴 Другий однаковий прохід не заводиться, і це не косметика. Через цю
    # гілку йдуть `registry.collect` і `registry.merge` — обидві мутують той
    # самий реєстр фонду й ту саму чергу розбіжностей. Запис там тепер
    # атомарний (`fonds/merge/write._write_tsv`), тож обрізаного файлу вже не
    # буде, але два одночасні злиття все одно дали б результат «хто останній»,
    # а приводу шукати не треба — вистачає подвійного кліку по кнопці.
    #
    # ⚠ Шукається активна робота, а не ключ ідемпотентності. Ключ жив би ще
    # кілька хвилин після завершення й віддавав би старий готовий запис — а
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
    from nyshporka.core import progress
    from nyshporka.core.jobs import JobState, Progress

    await bus.update(job.id, state=JobState.RUNNING)

    # 🔴 Тіло операції крутиться в окремому потоці, а черга живе в циклі подій.
    # Переносить це на себе приймач, а не той, хто звітує: інакше кожна
    # операція мусила б знати про цикл, тобто про демона.
    loop = asyncio.get_running_loop()
    last = 0.0

    def _tick(i: int, n: int, note: str) -> None:
        nonlocal last
        now = time.monotonic()
        # Тротлінг: без нього тисяча прогонів дасть тисячу подій у журналі, і
        # він витіснить усе інше. Урок уже засвоєний на завантажувачі.
        if now - last < 0.25 and i != n:
            return
        last = now
        loop.call_soon_threadsafe(
            lambda: _keep(asyncio.create_task(bus.update(
                job.id, progress=Progress(i=i, n=n, basis=note or "кроків")))))

    def _work() -> Any:
        with progress.sink(_tick):
            return O.call(op_name, dict(payload or {}))

    try:
        env = await asyncio.to_thread(_work)
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    # 🔴 Невдача операції — це невдача роботи, а не успіх із полем `ok: false`
    # усередині. Інакше в черзі вона світилась би зеленим, і причину побачив би
    # лише той, хто розгорнув результат.
    if not env.ok:
        await bus.update(job.id, state=JobState.ERROR, error=env.error or "не вийшло")
        return
    got = env.as_dict()
    await bus.update(job.id, state=JobState.DONE, result=got.get("data"),
                     warnings=got.get("warnings") or [],
                     next=got.get("next") or [])


async def _start_build(bus: JobBus, payload: dict[str, Any]) -> JobRecord:
    """Перезбірка реєстру справ.

    🔴 Захист тут — від другого одночасного проходу, а не від другої
    перезбірки взагалі, і різниця принципова. Два паралельні проходи писали б
    у ту саму базу й у той самий файл бібліотеки. Але ключ ідемпотентності
    живе десять хвилин і після завершення роботи віддавав би старий готовий
    запис — а натискають цю кнопку саме тому, що щойно щось змінилось:
    людина побачила б «готово» з числами до своєї зміни й повірила б їм.

    Тому шукається активна робота, а не ключ: поки перезбірка йде, повторні
    натискання чіпляються до неї; щойно вона завершилась — нове натискання дає
    новий прохід.
    """
    from nyshporka.core.jobs import JobState

    rescan = bool(payload.get("rescan", True))
    # Перевірка «чи вже йде» і постановка мусять бути неподільні: між ними є
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

    # 🔴 Маніфест береться до постановки в чергу: питання «скільки це» мусить
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
                       total: int | None) -> None:
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
        # ⚠ Джерело буває без знаменника (Commons не знає числа сторінок
        # для одинарного скана). Поступ тоді рахується від зробленого, а
        # не від обіцяного, — і саме тому число тут не вигадується.
        progress=Progress(i=total or res.frames, n=total or res.frames,
                          done=res.frames,
                          skipped=res.skipped, failed=len(res.errors),
                          basis="кадр"))


async def _start_read(bus: JobBus, ws: Workspace,
                      payload: dict[str, Any]) -> JobRecord:
    """Поставити читання справи. План рахується до черги.

    Так «чим будемо читати і скільки це кадрів» відомо до старту, а не через
    годину — і завдання, приречене впасти на відсутній моделі, у чергу взагалі
    не потрапляє.
    """
    from nyshporka.htr import run as R

    plan = R.plan(payload.get("case_dir") or "",
                  out_dir=payload.get("out_dir") or "",
                  script=str(payload.get("script") or ""),
                  second_voice=bool(payload.get("second_voice", True)))
    # 🔴 Шифра береться З опису, коли її не передали. Прогін без шифри стає в
    # реєстрі «нічиїм»: він є, текст є, а до якої справи належить — невідомо,
    # і зшивати це потім доводиться правкою JSON руками. З консолі шифру ніхто
    # не вводить (форма читання питає лише теку), тож без цього кожен запуск
    # кнопкою давав нічию — при тому, що опис лежить у тій самій теці.
    #
    # ⚠ Через спільний `case_key_for`, а не через власну гілку. Доти командний
    # рядок був розумніший за застосунок: після опису він пробував ще резолвер
    # за шляхом, а браузерний шлях — ні. Тобто найчастіший вхід мав найгіршу
    # прив'язку саме там, де його найважче помітити.
    case_key = str(payload.get("case_key") or "") or R.case_key_for(plan.case_dir)[0]

    limit = max(0, int(payload.get("limit") or 0))
    pages = str(payload.get("pages") or "")
    workers = max(1, min(8, int(payload.get("workers") or 1)))
    cmds, notes = plan.shards(
        workers, device=str(payload.get("device") or ""),
        case_key=case_key, limit=limit, pages=pages,
        seg_height=max(0, int(payload.get("seg_height") or 0)))

    title = f"{plan.case_dir.name}: {plan.frames} кадрів, {plan.model.name}"
    if len(cmds) > 1:
        title += f" · {len(cmds)} процеси"
    job, created = await bus.enqueue(
        "read",
        title=title,
        cfg={**plan.as_dict(), "case_key": case_key, "workers": len(cmds),
             "limit": limit, "pages": pages, "notes": notes,
             "gpu_lock": str(plan.gpu_lock or "")},
        # Ключ — тека виходу: повторний запит на ту саму справу має віддати те
        # саме завдання, а не другий прогін, що б'ється з першим за карту.
        # 🔴 N шардів — одне завдання: вони пишуть в одну теку й разом
        # становлять один прогін.
        idempotency_key=f"read:{plan.out_dir}",
    )
    if created:
        _keep(asyncio.create_task(
            _run_read(bus, job, plan, case_key, cmds,
                      partial=bool(limit or pages))))
    return job


async def _run_read(bus: JobBus, job: JobRecord, plan: Any, case_key: str,
                    cmds: list[list[str]], *, partial: bool = False) -> None:
    """Вести N процесів раннера, зводячи їхній прогрес в одне завдання.

    🔴 Шарди — це не N робіт, а одна: вони пишуть в ту саму теку, ділять один
    лок карти й разом становлять прогін справи. Тому в черзі вони стоять одним
    рядком, а числа під ним — сумарні.
    """
    from nyshporka.core.jobs import JobState

    # 🔴 Чекаємо гейта ПЕРЕД тим, як стати `RUNNING`. Порядок тут і є той стан,
    # який людина читає: доки прогін чекає карти, він мусить лишатись у черзі,
    # а не вдавати роботу. Підпис міняється разом зі станом — «чекає на карту»
    # відповідає на питання «чому нічого не відбувається».
    # ⚠ Початковий підпис запам'ятовується ДО правки: `bus.update` міняє той
    # самий запис, тож «повернути як було» через `job.title` повернуло б уже
    # виправлений рядок — і завдання, яке вже читає, лишалось би підписане
    # «чекає на карту». Брехливий підпис гірший за його відсутність.
    was_title = job.title
    gate = _read_gate()
    if gate.locked():
        await bus.update(job.id, title=f"{was_title} · {WAITING_FOR_GPU}")
    async with gate:
        # 🔴🔴 Скасування, ухвалене ПОКИ завдання стояло в черзі, мусить
        # спрацювати тут. Стопер (`bus.on_stop`) реєструється аж усередині
        # `_run_read_locked`, коли процеси вже є, тож `cancel` на завданні в
        # черзі лише фарбує стан і нікого не спиняє. Без цієї перевірки
        # скасоване читання дочікувалось карти й СТАРТУВАЛО — на годину, з
        # написом «скасовано» в переліку й без рядка, на якому можна натиснути
        # «спинити». Тобто найгірший різновид привида: роботи не видно, а карту
        # вона тримає.
        if bus.cancelled(job.id):
            return
        await bus.update(job.id, state=JobState.RUNNING, title=was_title)
        await _run_read_locked(bus, job, plan, case_key, cmds, partial=partial)


async def _run_read_locked(bus: JobBus, job: JobRecord, plan: Any, case_key: str,
                           cmds: list[list[str]], *, partial: bool = False) -> None:
    """Тіло читання під уже взятим гейтом карти."""
    import os

    from nyshporka.core.jobs import JobState, Progress
    from nyshporka.core.progress import split
    from nyshporka.htr import run as R

    env = {**os.environ, **R.shard_env(len(cmds)),
           "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    procs = [await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env) for cmd in cmds]

    # 🔴 «Спинити» має спиняти всі процеси. Доти стопер замикався на один — із
    # шардами це лишило б N−1 читати справу далі, годинами тримаючи карту, при
    # тому що завдання вже позначене скасованим.
    def _stop_all() -> None:
        for p in procs:
            _terminate(p)

    bus.on_stop(job.id, _stop_all)

    # 🔴 Хвіст людського виводу зберігається окремо, і З номером шарда. Коли
    # прогін падає, у завданні лишається код повернення — а причина написана
    # саме там, звичайним рядком; без номера її не відрізнити від сусідського
    # виводу, бо друкують усі одночасно.
    tail: list[str] = []
    #: Останній прогрес кожного шарда. Сумуються живі числа, а не події: подія
    #: приходить від одного процесу й нічого не каже про решту.
    st: list[dict[str, int]] = [{"i": 0, "n": 0, "done": 0, "skipped": 0,
                                 "failed": 0} for _ in cmds]
    last_push = 0.0

    async def pump(k: int, proc: Any) -> None:
        nonlocal last_push
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            ev, human = split(line)
            if ev is not None:
                st[k] = {"i": ev.i, "n": ev.n, "done": ev.done,
                         "skipped": ev.skipped, "failed": ev.failed}
                # ⏱ Тротлінг: N шардів × подія на сторінку дають N-кратну
                # щільність, і журнал робіт перестає читатись — цей урок уже
                # засвоєно на 991 події однієї плівки.
                now = asyncio.get_running_loop().time()
                if now - last_push < 0.25:
                    continue
                last_push = now
                await bus.update(job.id, progress=Progress(
                    # 🔴 `n` — сума, а не число з нульового шарда: кожен
                    # звітує розмір своєї вибірки після round-robin, тож узяти
                    # чуже означало б показувати 33% вічно.
                    i=sum(s["i"] for s in st), n=sum(s["n"] for s in st),
                    done=sum(s["done"] for s in st),
                    skipped=sum(s["skipped"] for s in st),
                    failed=sum(s["failed"] for s in st), basis="сторінка"))
            elif human:
                tail.append(human if len(cmds) == 1 else f"w{k + 1}| {human}")
                del tail[:-40]

    await asyncio.gather(*(pump(k, p) for k, p in enumerate(procs)))
    codes = [await p.wait() for p in procs]
    bus.drop_stopper(job.id)
    # Остання подія могла не пройти тротлінг — дописуємо підсумок.
    await bus.update(job.id, progress=Progress(
        i=sum(s["i"] for s in st), n=sum(s["n"] for s in st),
        done=sum(s["done"] for s in st), skipped=sum(s["skipped"] for s in st),
        failed=sum(s["failed"] for s in st), basis="сторінка"))

    # 🔴 Приймач повноти — диск, а не код повернення: є клас відмов, за якого
    # сторінка вбиває процес, лог обривається, перелік збоїв порожній, а код
    # успішний.
    #
    # 🔴 Шардинг тут не робить прогін частковим — на відміну від командного
    # рядка, де один процес справді читає свою частку. Тут завдання володіє
    # всіма шардами, тож їхнє об'єднання є повним прогоном; переплутати
    # означало б тихо прийняти третину справи як прочитану.
    comp: dict[str, Any] = R.completeness(plan.case_dir, plan.out_dir, partial=partial)
    missing, pages = int(comp["missing"]), int(comp["pages"])
    if bus.cancelled(job.id):
        # Скасоване лишається скасованим: перезаписати його на DONE/ERROR
        # означало б сказати, що робота дійшла до кінця. Скільки встигли
        # прочитати — записуємо, це знадобиться для `resume`.
        await bus.update(job.id, result={"out_dir": str(plan.out_dir),
                                         "pages": pages, "rc": codes,
                                         "tail": tail[-12:]})
        return
    bad = [f"w{k + 1}: код {c}" for k, c in enumerate(codes) if c]
    ok = not bad and missing == 0
    why = ""
    if bad and missing:
        why = f"{'; '.join(bad)}; без тексту лишилось {missing} сторінок"
    elif bad:
        # 🔴 Окреме формулювання: процес упав, але на диску все. Спільний текст
        # послав би шукати загублені сторінки там, де їх немає.
        why = f"{'; '.join(bad)} — але всі сторінки мають текст"
    elif missing:
        why = f"без тексту лишилось {missing} сторінок при успішному коді"
    await bus.update(
        job.id,
        state=JobState.DONE if ok else JobState.ERROR,
        error=why,
        result={"out_dir": str(plan.out_dir), "pages": pages,
                "missing": missing, "frames": comp["frames"],
                "partial": comp["partial"], "rc": codes, "tail": tail[-12:]})


def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Спинити раннер: спершу ввічливо, за 5 с — силою.

    ⚠ На Windows `terminate()` це `TerminateProcess`, тобто діти раннера
    (шарди) можуть пережити батька; ловить їх власний watchdog раннера, а тут
    важливо не лишити головний процес, який тримає відеокарту.
    """
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return

    async def _kill_later() -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    _keep(asyncio.create_task(_kill_later()))


def _safe(ref: str) -> str:
    """Адреса джерела → безпечне ім'я теки.

    Адреси несуть скісні, пробіли й кирилицю (`moldova/_2043433 …/2086525`);
    класти таке в шлях як є означало б і дерево тек із чужою структурою, і
    вихід за межі простору на першій же `..`.
    """
    import re

    out = re.sub(r"[^\w.\-]+", "_", ref.replace("/", "-").replace(":", "-"))
    return out.strip("_")[:120] or "case"
