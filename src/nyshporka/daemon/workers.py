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
import json
import threading
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

#: job_id → задача виконавця загальної операції. Задача живе рівно стільки,
#: скільки потік із тілом операції, — тож саме вона, а не стан у черзі, каже,
#: чи робота ще йде. Див. `_start_generic`.
_GENERIC_RUNS: dict[str, asyncio.Task[None]] = {}

#: Що сказати людині, яка скасувала загальну операцію.
CANT_INTERRUPT = ("скасування цю операцію посередині не перериває: вона "
                  "доробляється у фоні, і повторний запуск стане можливим, "
                  "коли вона скінчиться")
FINISHED_AFTER_CANCEL = ("операцію скасовано, коли вона вже йшла, і вона "
                         "доробилась до кінця — результат нижче справжній")

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
#: Як часто читання з екрана дивиться, чи звільнили карту термінал або черга справ.
FOREIGN_POLL_SEC = 15.0


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
    #
    # 🔴 «Активна» — за живим потоком, а не за станом (аудит 29.09.2026).
    # Потік Python убити нема чим, тож «Скасувати» над такою роботою
    # перефарбовувало рядок у «скасовано», а `registry.merge` ішов далі. Гейт,
    # що дивився лише на стан, пропускав тоді другий клік — і два злиття того
    # самого реєстру йшли паралельно, тобто рівно те, від чого гейт ставили.
    async with _GENERIC_GATE:
        for j in bus.jobs():
            if j.kind != op_name or j.cfg != cfg:
                continue
            if j.state in (JobState.QUEUED, JobState.RUNNING):
                return j
            run = _GENERIC_RUNS.get(j.id)
            if run is not None and not run.done():
                raise ValueError(f"попереднє «{op.summary}» ще йде: {CANT_INTERRUPT}")
        job, _ = await bus.enqueue(op_name, title=op.summary, cfg=cfg)
        stop_ev = threading.Event()
        # Задача заводиться під гейтом: між постановкою й реєстрацією задачі
        # інакше було б вікно, у якому робота ще не має «живого потоку».
        task = asyncio.create_task(_run_generic(bus, job, op_name, payload, stop_ev))
        _keep(task)
        _GENERIC_RUNS[job.id] = task
        jid = job.id

        def _gone(_t: asyncio.Task[None]) -> None:
            _GENERIC_RUNS.pop(jid, None)

        task.add_done_callback(_gone)

    # 🔴 Скасування мусить сказати правду про себе. Гасителя в загальної
    # операції немає (кооперативної зупинки тіла операцій теж: перервати
    # злиття реєстру на випадковому кроці гірше, ніж дати йому дійти), тож
    # «гаситель» тут лише дописує до роботи, що вона ще йде. `pick.ask`
    # поверх цього реєструє справжнього — і той заміняє цей.
    def _say_cant_stop() -> None:
        note = {"code": "cant_interrupt", "text": CANT_INTERRUPT}
        _keep(asyncio.create_task(bus.update(job.id, warnings=[*job.warnings, note])))

    # Операція, що сама питає «чи не просили спинитись» (`progress.stopped`),
    # отримує справжнього гасителя; решта — чесне «перервати не можна».
    bus.on_stop(job.id, stop_ev.set if op_name in STOPPABLE_OPS else _say_cant_stop)
    return job


#: Загальні операції, що вміють спинитись посеред роботи: між кроками вони
#: питають `progress.stopped()`. Пошук по корпусу — хвилини, і перервати його
#: безпечно: він нічого не пише, крім кешу, який дописується блоками цілком.
#: Пошук по каталогах просто перестає чекати джерела; обхід каталогу
#: спиняється після записаного кроку й продовжується наступним запуском.
STOPPABLE_OPS = frozenset({"search.find", "catalog.sweep", "catalog.crawl"})


async def _run_generic(bus: JobBus, job: JobRecord, op_name: str,
                       payload: dict[str, Any],
                       stop_ev: threading.Event | None = None) -> None:
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
        with progress.sink(_tick), progress.stop_scope(stop_ev):
            return O.call(op_name, dict(payload or {}))

    try:
        env = await asyncio.to_thread(_work)
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    finally:
        # Потік скінчився — казати «ще доробляється» більше нема про що.
        bus.drop_stopper(job.id)
    # 🔴 Невдача операції — це невдача роботи, а не успіх із полем `ok: false`
    # усередині. Інакше в черзі вона світилась би зеленим, і причину побачив би
    # лише той, хто розгорнув результат.
    if not env.ok:
        await bus.update(job.id, state=JobState.ERROR, error=env.error or "не вийшло")
        return
    got = env.as_dict()
    warnings = list(got.get("warnings") or [])
    # 🔴 Скасована робота, що доробилась, лишається «скасованою» (див.
    # `JobBus.update`), але її результат записується — і людина мусить знати,
    # що це не обрізок, а повний результат (аудит 29.09.2026).
    if bus.cancelled(job.id) and op_name not in STOPPABLE_OPS:
        # Операція, що вміє спинитись, сама каже в своїх попередженнях, що
        # відповідь обрізана; решта доробила до кінця — і це треба сказати.
        warnings.append({"code": "finished_after_cancel",
                         "text": FINISHED_AFTER_CANCEL})
    await bus.update(job.id, state=JobState.DONE, result=got.get("data"),
                     warnings=warnings, next=got.get("next") or [])


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
        from nyshporka import pdfcount

        out: dict[str, Any] = {}
        with pdfcount.session() as sess:
            if rescan:
                from nyshporka.library import build_library, write_library

                entries = build_library()
                write_library(entries)
                out["library"] = len(entries)
            from nyshporka.cases import db

            out.update(db.build_index())
        out["cloud"] = {"files": len(sess.skipped), "bytes": sess.nbytes,
                        "skipped": dict(sess.skipped)}
        return out

    try:
        res = await asyncio.to_thread(work)
    except Exception as exc:
        await bus.update(job.id, state=JobState.ERROR,
                         error=f"{type(exc).__name__}: {exc}")
        return
    n = int(res.get("cases") or 0)
    warnings: list[dict[str, str]] = []
    if res["cloud"]["skipped"]:
        from nyshporka import pdfcount

        warnings.append({"code": "cloud_pdf",
                         "text": pdfcount.describe(res["cloud"]["skipped"])})
    await bus.update(job.id, state=JobState.DONE, result=res, warnings=warnings,
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
    # ⚠ Не `Path(x or "") or default`: `Path("")` — це `Path(".")`, а він
    # істинний завжди. Гілка з дефолтом була мертвою, і кадри без `dest`
    # лягали в поточну теку процесу демона, а не в `data/raw`.
    dest_raw = str(payload.get("dest") or "").strip()
    dest = Path(dest_raw) if dest_raw else ws.raw / source_id / _safe(ref)

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
    # 🔴 Той самий приймач, що в `nysh get` (аудит 29.09.2026): доти DONE
    # ставилось усьому, крім «самі збої й жодного кадру», — нуль кадрів без
    # збою чи 10 кадрів із 300 висіли в черзі завершеною роботою.
    # 🔴 Паспорт теки — той самий, що пише `nysh get` (`record_fetch`): доти
    # завантаження через застосунок лишало кадри без жодного запису «звідки,
    # скільки, чи повно».
    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import completeness

    try:
        verdict = await asyncio.to_thread(
            record_fetch, Path(res.dest), res, source=str(getattr(src, "id", "")),
            ref=ref, want=total)
    except OSError:
        verdict = completeness(res, total)
    said = verdict.message(res)
    why = "; ".join(x for x in (said, *res.errors[:3]) if x) if not verdict.ok else ""
    # Кадри на диску — ще не справа в обліку: без шифри тека не потрапить ні
    # в каталог, ні в читання. Кажемо одразу, з командою (`cases.chain`).
    dali = ""
    try:
        from nyshporka.cases.chain import after_fetch

        lanka = await asyncio.to_thread(after_fetch, Path(res.dest))
        if lanka is not None:
            dali = f"справу ще не зареєстровано ({lanka.why}) — {lanka.fix}"
    except Exception:
        dali = ""
    await bus.update(
        job.id,
        state=JobState.DONE if verdict.ok else JobState.ERROR,
        error=why,
        result={"dest": str(res.dest), "frames": res.frames,
                "skipped": res.skipped, "bytes": res.bytes,
                "errors": len(res.errors), "promised": verdict.want,
                "got": verdict.got, "complete": verdict.state,
                "next": dali,
                # «Повноту не доведено» — не збій, але й не мовчазний успіх.
                "note": said if verdict.ok else ""},
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

    🔴 Сам план рахується в потоці, а не в циклі подій (аудит 29.09.2026).
    `R.plan` запускає підпроцес на кожен пакет маніфесту (імпорт torch — до
    120 с кожен) і розкладає PDF у кадри; у циклі подій це заморожувало ВЕСЬ
    демон: жоден запит, навіть перелік робіт чи скасування, не отримував
    відповіді, і вкладка виглядала мертвою. Постановка в чергу лишається в
    циклі — лок черги прив'язаний до нього.
    """
    from nyshporka.htr import run as R

    limit = max(0, int(payload.get("limit") or 0))
    pages = str(payload.get("pages") or "")
    workers = max(1, min(8, int(payload.get("workers") or 1)))

    def _prepare() -> tuple[Any, str, list[list[str]], list[str]]:
        plan = R.plan(payload.get("case_dir") or "",
                      out_dir=payload.get("out_dir") or "",
                      script=str(payload.get("script") or ""),
                      second_voice=bool(payload.get("second_voice", True)),
                      # 🔴 `model` форма надсилала й раніше, але сюди він не
                      # доходив: поле на екрані було, а прогін ішов бойовою моделлю
                      model=str(payload.get("model") or ""),
                      also=[str(v) for v in payload.get("also") or [] if str(v).strip()],
                      # Шлях прийшов із браузера — лише корені справ (аудит 29.09.2026).
                      zone=True,
                      # Запуск, не план: бокові кадри PDF розгортаються тут.
                      fix_sideways=True)
        # 🔴 Шифра береться З опису, коли її не передали. Прогін без шифри стає
        # в реєстрі «нічиїм»: він є, текст є, а до якої справи належить —
        # невідомо, і зшивати це потім доводиться правкою JSON руками. З консолі
        # шифру ніхто не вводить (форма читання питає лише теку), тож без цього
        # кожен запуск кнопкою давав нічию — при тому, що опис лежить у тій
        # самій теці.
        #
        # ⚠ Через спільний `case_key_for`, а не через власну гілку. Доти
        # командний рядок був розумніший за застосунок: після опису він пробував
        # ще резолвер за шляхом, а браузерний шлях — ні. Тобто найчастіший вхід
        # мав найгіршу прив'язку саме там, де його найважче помітити.
        case_key = (str(payload.get("case_key") or "")
                    or R.case_key_for(plan.case_dir)[0])
        cmds, notes = plan.shards(
            workers, device=str(payload.get("device") or ""),
            case_key=case_key, limit=limit, pages=pages,
            seg_height=max(0, int(payload.get("seg_height") or 0)))
        return plan, case_key, cmds, notes

    plan, case_key, cmds, notes = await asyncio.to_thread(_prepare)

    title = f"{plan.case_dir.name}: {plan.frames} кадрів, {plan.model.name}"
    if len(plan.voices) > 1:
        title += f" + {len(plan.voices)} голоси"
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
        # 🔴 І те, ЩО саме читати (аудит 29.09.2026). Ключ із самої теки
        # віддавав на «сторінки 11-20» живе завдання «сторінки 1-10»: людина
        # бачила чужий прогін як свій, а просили її ніхто не виконував. Другий
        # прогін у ту саму теку тут не небезпечний — читання стоять у черзі за
        # гейтом карти, тож вони йдуть по одному.
        idempotency_key=_read_key(plan, limit=limit, pages=pages),
    )
    if created:
        _keep(asyncio.create_task(
            _run_read(bus, job, plan, case_key, cmds,
                      partial=bool(limit or pages))))
    return job


def _read_key(plan: Any, *, limit: int, pages: str) -> str:
    """Ключ ідемпотентності читання: тека виходу + що саме в неї читається.

    Кількість процесів у ключ не йде навмисно: це швидкість того самого
    прогону, а не інший прогін.
    """
    what = {"pages": pages, "limit": limit, "model": plan.model.name,
            "voices": [v.name for v in plan.voices]}
    return f"read:{plan.out_dir}:{json.dumps(what, ensure_ascii=False, sort_keys=True)}"


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
        # 🔴 Гейт бачить лише читання цього застосунку. Термінал (`nysh read`)
        # і черга справ (`nysh queue run`) ідуть повз нього, а карта в усіх
        # одна: без цього чекання читання з екрана стартувало поверх нічної
        # черги, і обидва міряли вільну пам'ять карти як свою.
        from nyshporka.htr import runs as live

        sprava = Path(str(getattr(plan, "case_dir", "") or "")).name
        while sprava and (busy := await asyncio.to_thread(live.others, sprava)):
            await bus.update(
                job.id, title=f"{was_title} · {WAITING_FOR_GPU}: {busy[0].label()}")
            await asyncio.sleep(FOREIGN_POLL_SEC)
            if bus.cancelled(job.id):
                return
        await bus.update(job.id, state=JobState.RUNNING, title=was_title)
        # 🔴 Виняток тут (немає інтерпретатора, зайнятий диск, збій звірки
        # повноти) інакше лишав завдання `running` назавжди: стопера ще немає,
        # ключ ідемпотентності повертає той самий «живий» запис, і перезапустити
        # читання неможливо до рестарту демона.
        try:
            await _run_read_locked(bus, job, plan, case_key, cmds, partial=partial)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            bus.drop_stopper(job.id)
            await bus.update(job.id, state=JobState.ERROR,
                             error=f"{type(exc).__name__}: {exc}")


async def _run_read_locked(bus: JobBus, job: JobRecord, plan: Any, case_key: str,
                           cmds: list[list[str]], *, partial: bool = False) -> None:
    """Тіло читання під уже взятим гейтом карти."""

    from nyshporka.core.jobs import JobState, Progress
    from nyshporka.core.progress import split
    from nyshporka.htr import run as R
    from nyshporka.htr.env import foreign_env

    env = foreign_env({**R.shard_env(len(cmds)), "PYTHONUNBUFFERED": "1",
                       "PYTHONIOENCODING": "utf-8"})
    from nyshporka.core.proctree import contain

    procs = [await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env) for cmd in cmds]
    # Кожен шард із нащадками — одне ціле (`core.proctree`): зупинка гасить
    # усіх, а падіння застосунку не лишає сиріт, які тримали б карту.
    trees = [contain(p.pid) for p in procs]
    pumps: list[asyncio.Task[None]] = []

    # 🔴 «Спинити» має спиняти всі процеси. Доти стопер замикався на один — із
    # шардами це лишило б N−1 читати справу далі, годинами тримаючи карту, при
    # тому що завдання вже позначене скасованим.
    def _stop_all() -> None:
        _keep(asyncio.create_task(_stop_reading(bus, job.id, procs, trees, pumps)))

    bus.on_stop(job.id, _stop_all)

    # У спільний реєстр живих прогонів — щоб термінал і черга справ бачили, що
    # карту читає застосунок. Запис мертвого процесу реєстр прибирає сам.
    from nyshporka.htr import runs as live

    for k, p in enumerate(procs):
        with contextlib.suppress(OSError):
            await asyncio.to_thread(
                live.register, p.pid, case=Path(str(plan.case_dir)).name,
                case_key=case_key,
                shard=f"{k + 1}/{len(procs)}" if len(procs) > 1 else "")

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
            if ev is not None and bus.cancelled(job.id):
                # Спиненому прогресу не дописуємо: рядок, що росте під
                # «спинено», читається як «не спинилось».
                continue
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

    pumps.extend(asyncio.create_task(pump(k, p)) for k, p in enumerate(procs))
    got = await asyncio.gather(*pumps, return_exceptions=True)
    # Канал, обірваний зупинкою (`_stop_reading`), — не збій; решта винятків
    # летить далі, як і до того.
    for res in got:
        if isinstance(res, BaseException) and not isinstance(res, asyncio.CancelledError):
            raise res
    codes = [await p.wait() for p in procs]
    bus.drop_stopper(job.id)
    for tree in trees:
        if tree is not None:
            tree.close()
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
    result: dict[str, Any] = {
        "out_dir": str(plan.out_dir), "pages": pages,
        "missing": missing, "frames": comp["frames"],
        "partial": comp["partial"], "rc": codes, "tail": tail[-12:]}
    await bus.update(
        job.id,
        state=JobState.DONE if ok else JobState.ERROR,
        error=why,
        result=result)

    # 🔴 Автовіддача — ПІСЛЯ того, як завдання вже оголошено виконаним.
    # Заливання пакета триває хвилини, і зроблене до оновлення стану
    # показувало б людині «ще читається» тоді, коли читання скінчилось.
    # Результат дописується другим заходом — там, де його побачить той, хто
    # дивиться на завдання; іншого місця в демона немає.
    if ok and not comp["partial"] and case_key:
        viddane = await _autoshare(case_key)
        if viddane:
            await bus.update(job.id, result={**result, "supriaha": viddane})


async def _autoshare(case_key: str) -> dict[str, Any] | None:
    """Віддати щойно прочитане, якщо профіль каже «завжди».

    🔴 Та сама операція, що й у командного рядка (`cli._supriaha_autoshare`),
    а не друга гілка з тими самими умовами. Режим «завжди» без цього мовчки
    не працював би саме в тих, хто користується застосунком, а не терміналом,
    тобто в більшості.

    🔴 Не кидає нічого назовні. Це хвіст успішного читання, і він не має
    права зробити з нього невдале: пакет лишиться на диску, і його видно в
    `share suggest`.
    """
    from nyshporka import ops as O

    try:
        env = await asyncio.to_thread(
            O.call, "share.autoshare", {"case": case_key, "complete": True})
    except Exception as exc:
        # Широко навмисно: сюди сходяться мережа, сховище ключів і чужий
        # сервер, і жодна з цих відмов не є приводом зіпсувати прочитане.
        return {"error": str(exc)}
    if not env.ok:
        # Операція впала всередині: `O.call` віддає відмову без даних, і
        # доти результат мовчки не писався — людина вважала справу відданою.
        return {"error": str(env.error or "автовіддача не спрацювала")}
    data = dict(env.data or {})
    if data.get("skipped"):
        return None
    # Попередження доходять завжди й першими: у режимі «завжди» людина на
    # результат не дивиться — вона на нього поклалась, — і «вважаю відданим,
    # а воно на диску» гірше, ніж не мати режиму зовсім.
    notes = [w.as_dict() for w in env.warnings]
    return {**data, "warnings": notes} if notes else data


#: Скільки чекати, доки канал виводу закриється після зупинки. Довше — значить
#: його тримає процес поза деревом, і чекати на нього означало б не віддати
#: карту наступному читанню.
STOP_DRAIN_SEC = 15.0


async def _stop_reading(bus: JobBus, job_id: str,
                        procs: list[asyncio.subprocess.Process], trees: list[Any],
                        pumps: list[asyncio.Task[None]]) -> None:
    """Спинити читання: усе дерево кожного шарда, і сказати, якщо не вийшло.

    🔴 Корінь НЕ гаситься першим. Доти тут ішло `proc.terminate()` одразу за
    запуском `kill_tree` у потоці: наглядач гинув раніше, ніж потік знімав його
    дітей, `psutil` не знаходив батька — і робочий процес читав далі. У людини
    06.10.2026 «спинено» дочитало ще 15 сторінок і не пустило до карти
    наступне читання.
    """
    from nyshporka.htr.session import kill_tree

    # Спершу дерево через батька — поки батько живий. Job Object лише слідом:
    # нащадок, народжений до `contain`, у нього не потрапив, а погашений
    # об'єктом корінь уже не видав би його `kill_tree`.
    survivors: list[int] = []
    for p in procs:
        if p.returncode is None:
            survivors += await asyncio.to_thread(kill_tree, p.pid)
    for tree in trees:
        if tree is not None:
            tree.kill()
    live = [t for t in pumps if not t.done()]
    if live:
        _done, hung = await asyncio.wait(live, timeout=STOP_DRAIN_SEC)
        for t in hung:
            t.cancel()
    if survivors:
        await bus.update(job_id, error=(
            f"не вдалося зупинити процеси {', '.join(map(str, survivors))} — "
            f"завершіть їх у диспетчері задач, інакше вони тримають карту"))


def _safe(ref: str) -> str:
    """Адреса джерела → безпечне ім'я теки.

    Адреси несуть скісні, пробіли й кирилицю (`moldova/_2043433 …/2086525`);
    класти таке в шлях як є означало б і дерево тек із чужою структурою, і
    вихід за межі простору на першій же `..`.
    """
    import re

    out = re.sub(r"[^\w.\-]+", "_", ref.replace("/", "-").replace(":", "-"))
    return out.strip("_")[:120] or "case"
