"""🖥 Поверхня HTTP: одна обгортка над реєстром, токен на мутаціях, курсор.

Що тут стережеться. Браузер, командний рядок і агент роблять ті самі речі; у
дослідницькому конвеєрі вони описували їх окремо й розійшлись — 157 роутів
проти 13 підключених скриптів. Тому тут перевіряється не «роут відповідає», а
що роут ОДИН і будується з реєстру: нову дію не можна забути виставити, і не
можна виставити те, чого в реєстрі немає.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nyshporka import ops as O  # noqa: E402
from nyshporka.core.workspace import Workspace  # noqa: E402
from nyshporka.daemon.app import TOKEN_HEADER, create_app  # noqa: E402

# Токен їде в HTTP-заголовку, тобто мусить бути ASCII. Справжній такий за
# побудовою (`secrets.token_urlsafe`); тут це фіксується явно, щоб тест не
# перевіряв випадково інший клас помилок.
TOKEN = "test-token-abc123"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    (tmp_path / "data" / "derived").mkdir(parents=True)
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    return Workspace(root=tmp_path, name="тест", origin="test")


@pytest.fixture
def client(ws: Workspace) -> TestClient:
    return TestClient(create_app(ws, token=TOKEN))


def test_every_gui_op_is_reachable(client: TestClient) -> None:
    """Перелік дій береться з реєстру, а не переписується в роутері.

    Переписаний перелік відстає мовчки: дія є в CLI й в агента, а в браузері її
    немає — і ніхто цього не бачить, бо помилки не виникає.
    """
    got = {o["name"] for o in client.get("/api/ops").json()["ops"]}
    want = {o.name for o in O.all_ops() if o.gui}
    assert got == want
    assert "catalog.search" in got


def test_ops_carry_their_schemas(client: TestClient) -> None:
    """Форми будуються зі СХЕМИ операції, а не з полів, переписаних у фронті.

    Переписані розходяться: поле, яке більше не приймається, лишається на
    екрані й мовчки не діє.
    """
    ops = {o["name"]: o for o in client.get("/api/ops").json()["ops"]}
    schema = ops["catalog.search"]["schema"]
    assert "q" in schema["properties"]
    assert "limit" in schema["properties"]


def test_reading_needs_no_token(client: TestClient) -> None:
    """Читання відкрите: там нема чого псувати, а зайва перепона є завжди."""
    r = client.post("/api/op/workspace.info", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_mutation_without_token_is_refused(client: TestClient) -> None:
    """🔴 «Локальний порт» не означає «нікому не доступний».

    Будь-яка сторінка у браузері вміє слати запити на localhost. Токен віддано
    лише самій сторінці застосунку, і мутації без нього не проходять.
    """
    mutating = next(o for o in O.all_ops() if o.mutates and o.gui)
    r = client.post(f"/api/op/{mutating.name}", json={})
    assert r.status_code == 403


def test_unknown_op_is_404_not_silence(client: TestClient) -> None:
    assert client.post("/api/op/такої.немає", json={}).status_code == 404


def test_envelope_survives_the_wire(client: TestClient) -> None:
    """Попередження мусять доїхати до браузера полем, а не лише в лозі.

    Це та сама діра, що в дослідницькому реєстрі: «⚠ зріз застарів» друкувалось
    людині й НЕ друкувалось у машинному виводі — тобто саме тому читачеві, який
    не помітить нічого поза даними.
    """
    r = client.post("/api/op/catalog.search", json={"q": "будь-що"})
    body = r.json()
    assert body["v"] == 1
    assert body["ok"] is True

    # 🔴 Перевіряється ІНВАРІАНТ, а не конкретний код попередження: відповідь
    # не приходить без знаменника. Або сказано, ЧИМ шукали (`basis`), або
    # сказано, ЧОМУ не шукали. Раніше тут стояв `no_denominator` — і тест
    # почервонів, щойно в пакет доїхав вкладений зріз каталогу: шукати стало
    # де, тобто змінилась причина, а не правило.
    cov = body["data"]["coverage"]
    warns = body.get("warnings", [])
    assert cov["basis"] or cov["unavailable"] or warns, "відповідь без знаменника"
    if cov["searched"]:
        assert cov["basis"], "шукали, але не сказали чим саме"
    for u in cov["unavailable"]:
        assert u["why"], "джерело мовчки випало з пошуку"


def test_jobs_are_cursored(client: TestClient) -> None:
    """Курсор, а не підписка: агент приходить раз на хвилину й питає «що нового»."""
    first = client.get("/api/jobs?since=0").json()
    assert first["jobs"] == []
    assert "seq" in first
    again = client.get(f"/api/jobs?since={first['seq']}").json()
    assert again["events"] == []


def test_job_cancel_needs_token(client: TestClient) -> None:
    assert client.post("/api/jobs/невідоме/cancel").status_code == 403
    r = client.post("/api/jobs/невідоме/cancel", headers={TOKEN_HEADER: TOKEN})
    assert r.status_code == 404


def test_index_carries_the_token_not_a_cookie(client: TestClient) -> None:
    """🔴 Токен вшивається у сторінку.

    Cookie браузер шле САМ — і тоді чужа вкладка на localhost змогла б мутувати
    простір, тобто захист зникав би рівно там, де він потрібен.
    """
    html = client.get("/").text
    assert TOKEN in html
    assert "{{TOKEN}}" not in html
    assert not client.cookies


def test_health_names_the_workspace(client: TestClient, ws: Workspace) -> None:
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["workspace"] == str(ws.root)


def test_front_has_no_inline_handlers_or_globals() -> None:
    """🔴 Реєстр дій, а не `window` + `onclick`.

    Колізія імен між двома файлами не видна ні в дифі, ні в консолі: пізніший
    просто перекриває раніший, і кнопка починає робити чуже.
    """
    static = Path(__file__).resolve().parent.parent / "src" / "nyshporka" / "daemon" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    js = (static / "app.js").read_text(encoding="utf-8")
    assert "onclick" not in html and "onsubmit" not in html
    assert "data-act=" in html
    assert "window." not in js.replace("window.location", "")
