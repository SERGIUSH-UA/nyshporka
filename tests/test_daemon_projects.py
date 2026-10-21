"""🖥 Один демон на Майстерню: проєкт приходить у кожному запиті.

Помилка тут не падає голосно. Демон, що тримає проєкт на процес, віддає
відповідь про ІНШИЙ рід — і записує в нього: вкладка з одним родом ставила б
розділи, вердикти й нотатки в рід сусіднього проєкту, і жодна перевірка цього
не побачила б, бо кожна окрема відповідь виглядає правильною.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nyshporka.core import workspace as W  # noqa: E402
from nyshporka.core.envelope import ok  # noqa: E402
from nyshporka.core.ops import REGISTRY, NoArgs, Op  # noqa: E402
from nyshporka.daemon import app as D  # noqa: E402

TOKEN = "tok-w4-test"
BASE = "http://127.0.0.1:8788"


def _hub(tmp_path: Path, *, hub_only: bool = False) -> Path:
    hub = tmp_path / "hub"
    (hub / "data" / "derived").mkdir(parents=True)
    flag = "hub_only = true\n" if hub_only else ""
    (hub / W.MARKER).write_text(
        f'[workspace]\nname = "Майстерня"\nkeys = 2\npreset = "lab"\n{flag}',
        encoding="utf-8")
    return hub


def _project(hub: Path, pid: str) -> Path:
    root = hub / W.PROJECTS_DIR / pid
    root.mkdir(parents=True)
    (root / W.MARKER).write_text(f'[project]\nname = "Рід {pid}"\nkind = "family"\n',
                                 encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    W.reset()
    yield
    W.reset()


@pytest.fixture
def temp_op() -> Iterator[Any]:
    """Тимчасова оп у реєстрі: віддає корінь простору, у якому її виконали."""
    added: list[str] = []

    def add(name: str, *, long: bool = False, pause: float = 0.0) -> None:
        def body(_a: Any) -> Any:
            if pause:
                time.sleep(pause)
            return ok({"root": str(W.workspace().root)})

        REGISTRY.add(Op(name=name, fn=body, summary="тест", args=NoArgs,
                        long=long, mutates=False))
        added.append(name)

    yield add
    for name in added:
        REGISTRY.ops.pop(name, None)


@pytest.fixture
def two(tmp_path: Path) -> tuple[Path, Path, Path]:
    hub = _hub(tmp_path)
    return hub, _project(hub, "alpha"), _project(hub, "beta")


def _client(launch: Path) -> TestClient:
    return TestClient(D.create_app(W._build(launch, "test"), token=TOKEN), base_url=BASE)


def _info(c: TestClient, pid: str | None) -> dict[str, Any]:
    hdr = {D.PROJECT_HEADER: pid} if pid else {}
    r = c.post("/api/op/workspace.info", json={}, headers=hdr)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def test_project_comes_from_each_request(two: tuple[Path, Path, Path]) -> None:
    hub, alpha, beta = two
    with _client(alpha) as c:
        assert _info(c, None)["project"] == "alpha"      # без проєкту — проєкт запуску
        assert _info(c, "beta")["project"] == "beta"
        assert _info(c, "alpha")["project"] == "alpha"
        assert _info(c, "beta")["root"] == str(beta)
        # Корінь старого типу — теж проєкт («.»).
        assert _info(c, ".")["root"] == str(hub)


def test_parallel_requests_do_not_share_the_project(two: tuple[Path, Path, Path],
                                                    temp_op: Any) -> None:
    """🔴 Головне: простір процесу переписувався б сусіднім запитом посеред тіла."""
    _h, alpha, beta = two
    temp_op("test.where_slow", pause=0.4)
    got: dict[str, str] = {}
    with _client(alpha) as c:
        def ask(pid: str) -> None:
            r = c.post("/api/op/test.where_slow", json={},
                       headers={D.PROJECT_HEADER: pid})
            got[pid] = r.json()["data"]["root"]

        threads = [threading.Thread(target=ask, args=(p,)) for p in ("alpha", "beta")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert got == {"alpha": str(alpha), "beta": str(beta)}


def test_sections_written_in_one_project_stay_there(two: tuple[Path, Path, Path]) -> None:
    hub, alpha, beta = two
    with _client(alpha) as c:
        r = c.post("/api/op/sections.set", json={"preset": "catalog"},
                   headers={D.PROJECT_HEADER: "beta", D.TOKEN_HEADER: TOKEN})
        assert r.status_code == 200, r.text
        # Відповідь того самого запиту вже бачить нове (комірка оновлена), а
        # простір процесу — типовий для коду без запиту — лишився проєктом запуску.
        assert r.json()["data"]["preset"] == "catalog"
        assert W._override is not None and W._override.root == alpha
        assert 'preset = "catalog"' in (beta / W.MARKER).read_text(encoding="utf-8")
        assert "preset" not in (alpha / W.MARKER).read_text(encoding="utf-8")
        assert 'preset = "lab"' in (hub / W.MARKER).read_text(encoding="utf-8")
        ops_beta = {o["name"] for o in c.get(
            "/api/ops", headers={D.PROJECT_HEADER: "beta"}).json()["ops"]}
        ops_alpha = {o["name"] for o in c.get(
            "/api/ops", headers={D.PROJECT_HEADER: "alpha"}).json()["ops"]}
        # Лабораторія лишилась у проєкті запуску, а з каталогу її не видно.
        assert any(n.startswith("train.") for n in ops_alpha)
        assert not any(n.startswith("train.") for n in ops_beta)


def test_long_job_runs_in_the_project_it_was_queued_from(
        two: tuple[Path, Path, Path], temp_op: Any,
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.daemon import workers

    _h, alpha, beta = two
    temp_op("test.where_long", long=True, pause=0.3)
    # Читання й завантаження беруть простір аргументом (теку кадрів, `raw`) —
    # він мусить бути проєкту запиту, а не запуску демона.
    handed: list[Path] = []
    orig = workers.start

    async def spy(bus: Any, ws: Any, name: str, payload: Any) -> Any:
        handed.append(ws.root)
        return await orig(bus, ws, name, payload)

    monkeypatch.setattr(workers, "start", spy)
    with _client(alpha) as c:
        r = c.post("/api/op/test.where_long", json={},
                   headers={D.PROJECT_HEADER: "beta", D.TOKEN_HEADER: TOKEN})
        assert r.status_code == 200, r.text
        job_id = r.json()["data"]["job_id"]
        # Наступний запит — з іншого проєкту: робота не мусить перейти в нього.
        _info(c, "alpha")
        job: dict[str, Any] = {}
        for _ in range(100):
            job = next(j for j in c.get("/api/jobs").json()["jobs"] if j["id"] == job_id)
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.05)
    assert job["state"] == "done", job
    assert job["result"]["root"] == str(beta)
    assert job["project"] == "beta"
    assert handed == [beta]


def test_unknown_project_is_404(two: tuple[Path, Path, Path]) -> None:
    _h, alpha, _beta = two
    with _client(alpha) as c:
        r = c.post("/api/op/workspace.info", json={}, headers={D.PROJECT_HEADER: "gamma"})
        assert r.status_code == 404
        assert "gamma" in r.json()["error"]


def test_projects_listing(two: tuple[Path, Path, Path]) -> None:
    _h, alpha, beta = two
    # Колір і знак — для перемикача в шапці консолі.
    marker = beta / W.MARKER
    marker.write_text(marker.read_text(encoding="utf-8")
                      + 'color = "#112233"\nglyph = "Б"\n', encoding="utf-8")
    with _client(alpha) as c:
        got = c.get("/api/projects", headers={D.PROJECT_HEADER: "beta"}).json()
    assert [p["id"] for p in got["projects"]] == [".", "alpha", "beta"]
    assert (got["current"], got["default"]) == ("beta", "alpha")
    b = next(p for p in got["projects"] if p["id"] == "beta")
    assert (b["color"], b["glyph"]) == ("#112233", "Б")


def test_project_op_in_pure_hub_asks_to_choose(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    _project(hub, "alpha")
    with _client(hub) as c:
        r = c.post("/api/op/canon.next", json={})
        assert r.status_code == 400
        assert "Оберіть проєкт" in r.json()["error"]
        # Той самий виклик із проєктом проходить межу.
        r = c.post("/api/op/canon.next", json={}, headers={D.PROJECT_HEADER: "alpha"})
        assert "Оберіть проєкт" not in r.text
        listing = c.get("/api/projects").json()
    assert listing["hub_only"] is True and listing["current"] is None
    assert [p["id"] for p in listing["projects"]] == ["alpha"]


def test_site_prefix_serves_that_projects_site(two: tuple[Path, Path, Path]) -> None:
    from nyshporka.site.build import default_out

    _h, alpha, beta = two
    html = default_out(beta, False) / "html"
    (html / "osoby").mkdir(parents=True)
    (html / "index.html").write_text("рід beta", encoding="utf-8")
    (html / "osoby" / "index.html").write_text("особи beta", encoding="utf-8")
    with _client(alpha) as c:
        assert c.get("/p/beta/site/").text == "рід beta"
        r = c.get("/p/beta/site/osoby", follow_redirects=False)
        assert r.headers["location"] == "/p/beta/site/osoby/"
        assert c.get("/site/").status_code == 404   # у проєкту запуску сайту немає


def test_start_page_carries_the_project(two: tuple[Path, Path, Path]) -> None:
    hub, alpha, _beta = two
    assert D._start_page(W._build(alpha, "test"), "") == "?p=alpha"
    assert D._start_page(W._build(alpha, "test"), "site/") == "p/alpha/site/"
    # Корінь старого типу — адреса як до Майстерні.
    assert D._start_page(W._build(hub, "test"), "site/") == "site/"


def test_serve_locks_the_hub_not_the_project(two: tuple[Path, Path, Path],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Другий `serve` з іншого проєкту бачить замок першого, а не бере свій."""
    from nyshporka.core.lock import LOCK_NAME, LockBusy, WorkspaceLock

    hub, _alpha, beta = two
    W.use(W._build(beta, "test"))
    uvicorn = pytest.importorskip("uvicorn")

    def no_server(*_a: Any, **_k: Any) -> None:
        raise AssertionError("замок узято не той — сервер піднявся б поруч із першим")

    monkeypatch.setattr(uvicorn, "run", no_server)
    # `serve` вмикає знімок головної на процес — повернути після тесту, інакше
    # сусідні тести пульсу бачать кешовану головну.
    from nyshporka import ops_builtin as ob

    monkeypatch.setattr(ob, "PULSE_SNAPSHOT", ob.PULSE_SNAPSHOT)
    with WorkspaceLock(hub, port=8788).acquire():
        monkeypatch.setattr(D, "_alive", lambda _port: False)
        with pytest.raises(SystemExit) as exc:
            D.serve(open_browser=False)
        assert str(hub) in str(exc.value)
    assert not (beta / LOCK_NAME).exists()
    assert LockBusy  # імпорт — частина контракту модуля замка


def test_background_refresh_keeps_the_project(two: tuple[Path, Path, Path]) -> None:
    from nyshporka import ops_builtin as ob

    _h, alpha, beta = two
    seen: list[str] = []
    done = threading.Event()

    def fn() -> None:
        seen.append(str(W.workspace().root))
        done.set()

    with W.using(W._build(beta, "test")):
        ob._in_background("test-refresh", fn)
    assert done.wait(5)
    assert seen == [str(beta)]
    assert str(alpha) not in seen


def test_every_console_request_carries_the_project() -> None:
    """🔴 Голий `fetch` у консолі йде в проєкт запуску демона, а не вкладки.

    Новий екран із власним `fetch('/api/…')` писав би в чужий рід — тихо.
    Виняток — сторінка допуску (до неї проєкту ще немає) і сама обгортка.
    """
    import re

    static = Path(D.__file__).resolve().parent / "static"
    bare = re.compile(r"(?<![\w.])fetch\(")
    offenders = [
        f"{p.relative_to(static)}:{n}"
        for p in static.rglob("*.js")
        if "vendor" not in p.parts and p.name not in ("access.js", "net.js")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if bare.search(line) and not line.lstrip().startswith(("//", "*"))]
    assert offenders == []
