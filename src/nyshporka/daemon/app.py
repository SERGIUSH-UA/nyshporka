"""🖥 Демон: браузерне обличчя над тим самим реєстром операцій.

🔴 Тут НЕМАЄ окремих роутерів на кожну дію, і це головне рішення файлу. У
дослідницькому конвеєрі було 157 роутів проти 13 підключених скриптів — тобто
браузер і командний рядок описували роботу двічі, розійшлись, і побачили це
користувачі. Тому HTTP тут — тонка обгортка над `core.ops`: список операцій і
один виклик. Додати дію в браузер = оголосити `@op`, а не написати роут.

Три речі, які вирішені саме тут, а не в реєстрі:

1. **Один писар.** Демон тримає замок простору й ЄДИНИЙ має чергу завдань.
   Команда, запущена окремо, до черги не дістається — і чесно каже це замість
   того, щоб мовчки завести другу.
2. **Токен на мутаціях.** Порт локальний, але «локальний» не значить «нікому
   не доступний»: будь-яка сторінка у браузері вміє слати запити на localhost.
   Читання відкрите (там нічого не псується), мутації — за токеном, який
   віддається лише самій сторінці застосунку.
3. **Курсор замість стріму.** Той самий журнал подій живить і браузер, і
   агента; агент не тримає з'єднання, він приходить раз на хвилину.
"""
from __future__ import annotations

import contextlib
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from nyshporka.core.workspace import Workspace

#: Заголовок, у якому сторінка передає токен. Не cookie: cookie браузер шле сам,
#: і тоді захист від чужої вкладки зникає рівно там, де він потрібен.
TOKEN_HEADER = "X-Nysh-Token"

#: Дефолтний порт. 8788 — не 8000: на 8000 сидить половина dev-серверів, і
#: сплутати чужий застосунок зі своїм у браузері дуже легко.
DEFAULT_PORT = 8788
DEFAULT_HOST = "127.0.0.1"


def create_app(ws: Workspace | None = None, *, token: str = "") -> FastAPI:
    """Зібрати застосунок. `token` порожній — згенерувати новий."""
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Query
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover — extras `app`
        raise RuntimeError(
            "браузерна консоль потребує extras: pip install 'nyshporka[app]'"
        ) from exc

    class _NoCacheStatic(StaticFiles):
        """Статика, яку браузер зобов'язаний перепитати.

        🔴 Без цього фронт застряє В ПАМ'ЯТІ БРАУЗЕРА. Відколи консоль стала
        набором ES-модулів, сторінка тягне два десятки файлів, і жоден із них
        не має ні версії в імені, ні заголовка кешу: після оновлення
        застосунку людина бачить СТАРУ консоль проти нового бекенду. Виглядає
        це як «кнопка не працює» або «екран порожній», а не як застарілий кеш,
        і лікується жорстким перезавантаженням, про яке ніхто не здогадується.

        ⚠ Версія в запиті (`?v=…`) цього НЕ закриває: вона переписує посилання
        в розмітці, а `import` усередині самого модуля лишається без неї —
        тобто півміри, яка робить збій періодичним замість постійного. Тут
        коштує це відповіді 304 на кілька байтів по локальній петлі.

        ⚠ Клас оголошений ТУТ, а не на рівні модуля: `fastapi` —
        необов'язковий extra, і модульне успадкування від `StaticFiles`
        зробило б імпорт пакета неможливим у того, хто поставив його без
        застосунку.
        """

        async def get_response(self, path: str, scope):
            res = await super().get_response(path, scope)
            res.headers["Cache-Control"] = "no-cache, must-revalidate"
            return res

    from nyshporka import ops as O
    from nyshporka import ui
    from nyshporka.core.jobs import JobBus
    from nyshporka.core.workspace import use as _use
    from nyshporka.core.workspace import workspace as _workspace
    from nyshporka.daemon import workers
    from nyshporka.runtime import set_bus

    space = ws or _workspace()
    # 🔴 Простір ОГОЛОШУЄТЬСЯ на процес, а не лишається знанням цього об'єкта.
    # Операції резолвлять його самі (їх кличуть і з CLI, і з агента), тож демон,
    # який знає простір лише «для себе», віддавав би відповіді про ІНШИЙ
    # простір — той, що резолвиться від поточної теки. Помилки при цьому немає:
    # відповідь просто стосується не того архіву.
    _use(space)
    tok = token or secrets.token_urlsafe(24)
    bus = JobBus(space.derived / "jobs.json")
    bus.load()
    set_bus(bus)

    app = FastAPI(title="Нишпорка", docs_url=None, redoc_url=None)
    app.state.workspace = space
    app.state.token = tok
    app.state.bus = bus

    static_dir = Path(__file__).resolve().parent / "static"

    def require_token(given: str | None) -> None:
        # `compare_digest` навмисно: порівняння рядків «у лоб» витікає довжиною
        # збігу. Тут це параноя, але дешева.
        #
        # 🔴 Порівнюються БАЙТИ. На рядках `compare_digest` кидає `TypeError`,
        # щойно в них трапиться не-ASCII, — і замість чесної відмови 403
        # клієнт отримував 500 Internal Server Error. Токен приходить ззовні,
        # тобто будь-який зіпсований копіпаст перетворював відмову на збій
        # сервера, до якого фронт не має жодного пояснення.
        if not given or not secrets.compare_digest(given.encode("utf-8"),
                                                   tok.encode("utf-8")):
            raise HTTPException(status_code=403, detail="потрібен токен застосунку")

    # ── сторінка ─────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # Токен вшивається в сторінку, а не видається окремим запитом: інакше
        # його міг би попросити будь-хто, і сенс токена зникав би.
        #
        # 🔴 Спрайт значків вставляється В ТІЛО, а не підключається файлом:
        # `<use href>` до зовнішнього SVG забороняє успадкування currentColor у
        # Chrome, і всі значки стали б чорними — на темному полотні це просто
        # порожні місця. Та сама підстановка є в консолі дослідника.
        return HTMLResponse(ui.with_sprite(html.replace("{{TOKEN}}", tok)))

    app.mount("/static", _NoCacheStatic(directory=static_dir), name="static")

    # 🔴 Спільний шар обох морд: токени, примітиви, значки, компоненти. Лежить у
    # пакеті й монтується звідти, а не копіюється у фронт: консоль дослідника
    # монтує РІВНО цю саму теку, і копія розійшлася б із нею тихо.
    app.mount("/ui", _NoCacheStatic(directory=ui.static_dir()), name="ui")

    # 🔴 Асети бренду віддаються з `brand/data/assets`, а НЕ копіюються сюди.
    # Копія знака жила б у двох місцях і розходилась би тихо: у вкладці одна
    # лапка, у шапці інша. Ті самі файли йдуть у README й на сайт документації.
    from nyshporka.brand import ASSETS

    app.mount("/brand", StaticFiles(directory=ASSETS), name="brand")

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        # Ім'я `.ico` лишається історичним: браузери просять саме його, а
        # віддаємо SVG — він один на всі розміри вкладки.
        return FileResponse(ASSETS / "favicon.svg", media_type="image/svg+xml")

    # ── секції ───────────────────────────────────────────────────────────────
    def active_sections() -> frozenset[str]:
        """Ввімкнені секції ЗАРАЗ, а не на старті демона.

        `sections.set` міняє профіль на живому застосунку, тож знімок `space`,
        узятий при створенні, застарів би одразу після першої зміни — і
        навігація розходилась би з тим, що справді дозволено.
        """
        return _workspace().sections

    @app.get("/api/sections")
    def list_sections() -> dict[str, Any]:
        """Що ввімкнено — звідси фронт будує навігацію.

        Кнопки не зашиті в розмітку саме тому: другий перелік розходився б із
        цим тихо, і розходження виглядало б як зникла кнопка.
        """
        env = O.call("sections.show")
        return env.as_dict()

    # ── операції ─────────────────────────────────────────────────────────────
    @app.get("/api/ops")
    def list_ops() -> dict[str, Any]:
        """Перелік дій зі схемами.

        Фронт будує форми ЗВІДСИ, а не з переписаних вручну полів. Переписані
        розходяться з реальними — і розходяться тихо: поле, яке більше не
        приймається, лишається на екрані й мовчки не діє.
        """
        return {"ops": [{"name": o.name, "summary": o.summary,
                         "mutates": o.mutates, "long": o.long, "gui": o.gui,
                         "section": o.section, "schema": o.schema()}
                        for o in O.for_sections(active_sections())]}

    @app.post("/api/op/{name}")
    async def call_op(name: str, payload: dict[str, Any] | None = Body(default=None),
                      token_hdr: str | None = Header(default=None, alias=TOKEN_HEADER),
                      ) -> JSONResponse:
        op = O.get(name)
        if op is None:
            raise HTTPException(status_code=404, detail=f"немає операції «{name}»")
        # 🔴 Перевірка ТУТ, а не лише в `core.ops.call()`. Довгі операції йдуть
        # повз реєстр — у чергу демона (`workers.start` нижче), тож фільтр, який
        # стоїть тільки в `call()`, пропустив би саме найдорожчі з них: читання
        # справи й завантаження з архіву.
        from nyshporka.core import sections as S

        if op.section not in active_sections():
            sec = S.get(op.section)
            label = sec.label() if sec else op.section
            raise HTTPException(
                status_code=404,
                detail=(f"секція «{label}» вимкнена у профілі простору, тож "
                        f"«{name}» недоступна. Увімкнути: "
                        f"nysh sections enable {op.section}"))
        if op.mutates:
            require_token(token_hdr)
        if op.long:
            # 🔴 Причина відмови мусить дійти до людини. Постановка в чергу
            # робить справжню роботу ДО старту (шукає теку, рахує кадри, добирає
            # модель) — і саме там ловляться найчастіші перші помилки: не та
            # тека, порожня тека, немає ваг. Без цього перехоплення вони
            # прилітали як «Internal Server Error»: екран показував «Не вийшло»
            # без жодного слова про те, що саме, хоч слово було написане.
            try:
                job = await workers.start(bus, space, name, payload or {})
            except Exception as exc:
                text = str(exc) or type(exc).__name__
                return JSONResponse({"ok": False, "v": 1, "error": text,
                                     "warnings": [], "data": {}},
                                    status_code=400)
            return JSONResponse({"ok": True, "v": 1,
                                 "data": {"job_id": job.id, "state": str(job.state)}})
        env = O.call(name, payload or {})
        return JSONResponse(env.as_dict(), status_code=200 if env.ok else 400)

    # ── завдання ─────────────────────────────────────────────────────────────
    @app.get("/api/jobs")
    def jobs(since: int = Query(default=0)) -> dict[str, Any]:
        events, cursor = bus.since(since)
        return {"jobs": [j.as_dict() for j in bus.jobs()],
                "events": events, "seq": cursor}

    @app.get("/api/jobs/wait")
    async def jobs_wait(since: int = Query(default=0),
                        timeout_s: int = Query(default=25, ge=1, le=60),
                        ) -> dict[str, Any]:
        """Довге очікування на СЕРВЕРІ.

        Один виклик замість чотирьох порожніх опитувань — і для браузера, і для
        агента. Таймаут це нормальна відповідь «нічого не змінилось».
        """
        events, cursor = await bus.wait(since, timeout=float(timeout_s))
        return {"jobs": [j.as_dict() for j in bus.jobs()],
                "events": events, "seq": cursor}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str,
                         token_hdr: str | None = Header(default=None,
                                                        alias=TOKEN_HEADER),
                         ) -> dict[str, Any]:
        require_token(token_hdr)
        job = await bus.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"немає завдання {job_id}")
        return job.as_dict()

    # ── службове ─────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "workspace": str(space.root), "name": space.name,
                "jobs": len(bus.jobs())}

    return app


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *,
          open_browser: bool = True) -> None:
    """Підняти застосунок і взяти замок простору.

    🔴 Бінд на 127.0.0.1 жорсткий і параметром назовні не виводиться. Це
    застосунок з архівом однієї людини: канонічні дані про живих родичів,
    сканами й нотатками. Опція «слухати всюди» рано чи пізно буде ввімкнена
    «на хвилинку» — і лишиться.
    """
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover — extras `app`
        # Повідомлення мусить назвати ЩО поставити. «No module named uvicorn»
        # для генеалога зі сканами не є інструкцією.
        raise RuntimeError(
            "браузерна консоль потребує сервера: pip install 'nyshporka[app]'"
        ) from exc

    from nyshporka.core.lock import LockBusy, WorkspaceLock
    from nyshporka.core.workspace import workspace as _workspace

    space = _workspace()
    try:
        with WorkspaceLock(space.root, port=port).acquire() as held:
            app = create_app(space)
            url = f"http://{host}:{port}/"
            # Старт застосунку — те саме перше враження, що й `nysh info`, тож
            # знак і лінія бренду тут ті самі. Далі вивід перехоплює uvicorn.
            from nyshporka import __version__, brand

            out = brand.console()
            out.print(brand.banner(__version__))
            out.print(f"  [accent]{url}[/accent]")
            out.print(f"  [muted]простір: {space.root}[/muted]")
            if open_browser:
                import threading
                import webbrowser
                threading.Timer(1.0, lambda: webbrowser.open(url)).start()
            # 🔴 Серце мусить БИТИСЬ, а не вдаритись один раз. Тут стояв
            # єдиний `held.beat()` перед `uvicorn.run`, тобто через
            # `STALE_SEC` (45 с) замок живого демона виглядав покинутим.
            # Нитка — daemon=True: вона не тримає shutdown, а `uvicorn.run`
            # блокує потік до кінця життя процесу.
            import threading as _threading

            from nyshporka.core.lock import HEARTBEAT_SEC

            stop = _threading.Event()

            def _pulse() -> None:
                while not stop.wait(HEARTBEAT_SEC):
                    # диск смикнувся — наступний удар за 10 с
                    with contextlib.suppress(OSError):
                        held.beat()

            held.beat()
            hb = _threading.Thread(target=_pulse, name="nysh-lock-beat",
                                   daemon=True)
            hb.start()
            try:
                uvicorn.run(app, host=host, port=port, log_level="warning")
            finally:
                stop.set()
    except LockBusy as busy:
        raise SystemExit(
            f"🔴 простір {space.root} уже зайнятий: {busy}. "
            f"Двоє писарів на один простір — це затерті нотатки, тож не піднімаю."
        ) from None
