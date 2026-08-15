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

    from nyshporka import ops as O
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
        if not given or not secrets.compare_digest(given, tok):
            raise HTTPException(status_code=403, detail="потрібен токен застосунку")

    # ── сторінка ─────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # Токен вшивається в сторінку, а не видається окремим запитом: інакше
        # його міг би попросити будь-хто, і сенс токена зникав би.
        return HTMLResponse(html.replace("{{TOKEN}}", tok))

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        return FileResponse(static_dir / "favicon.svg", media_type="image/svg+xml")

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
                         "schema": o.schema()}
                        for o in O.all_ops() if o.gui]}

    @app.post("/api/op/{name}")
    async def call_op(name: str, payload: dict[str, Any] | None = Body(default=None),
                      token_hdr: str | None = Header(default=None, alias=TOKEN_HEADER),
                      ) -> JSONResponse:
        op = O.get(name)
        if op is None:
            raise HTTPException(status_code=404, detail=f"немає операції «{name}»")
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
            print(f"Нишпорка: {url}\n  простір: {space.root}")
            if open_browser:
                import threading
                import webbrowser
                threading.Timer(1.0, lambda: webbrowser.open(url)).start()
            held.beat()
            uvicorn.run(app, host=host, port=port, log_level="warning")
    except LockBusy as busy:
        raise SystemExit(
            f"🔴 простір {space.root} уже зайнятий: {busy}. "
            f"Двоє писарів на один простір — це затерті нотатки, тож не піднімаю."
        ) from None
