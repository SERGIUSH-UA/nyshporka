"""🖥 Поверхня HTTP: одна обгортка над реєстром, токен на мутаціях, курсор.

Що тут стережеться. Браузер, командний рядок і агент роблять ті самі речі; у
дослідницькому конвеєрі вони описували їх окремо й розійшлись — 157 роутів
проти 13 підключених скриптів. Тому тут перевіряється не «роут відповідає», а
що роут один і будується з реєстру: нову дію не можна забути виставити, і не
можна виставити те, чого в реєстрі немає.
"""
from __future__ import annotations

import sys
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
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    (tmp_path / "data" / "derived").mkdir(parents=True)
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    # 🔴 Реєстр справ адресується модульним `DB_PATH`, який зафіксувався при
    # першому імпорті — тобто на просторі іншого тесту. Свіжий простір без цієї
    # підміни показував би чужі справи, і перевірка «порожньо, а не помилка»
    # ловила б зразкову справу з сусіднього тесту.
    #
    # ⚠ Лише якщо модуль уже завантажений. Імпортувати його тут означало б
    # потягнути за собою резолвер простору — а простору в цю мить ще немає, і
    # фікстура падала б до першого рядка тесту.
    db = sys.modules.get("nyshporka.cases.db")
    if db is not None:
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "derived"
                            / "case_index.sqlite")
    return Workspace(root=tmp_path, name="тест", origin="test")


@pytest.fixture
def client(ws: Workspace) -> TestClient:
    # 🔴 Звертаємось на власне ім'я застосунку, а не на дефолтне `testserver`:
    # демон відповідає лише на петлю (захист від перев'язування імені), і клієнт
    # тесту мусить говорити з ним так само, як говорить браузер. Інакше тест
    # перевіряв би застосунок, якого в житті не буває.
    return TestClient(create_app(ws, token=TOKEN), base_url="http://127.0.0.1:8788")


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
    """Форми будуються зі схеми операції, а не з полів, переписаних у фронті.

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
    людині й не друкувалось у машинному виводі — тобто саме тому читачеві, який
    не помітить нічого поза даними.
    """
    r = client.post("/api/op/catalog.search", json={"q": "будь-що"})
    body = r.json()
    assert body["v"] == 1
    assert body["ok"] is True

    # 🔴 Перевіряється інваріант, а не конкретний код попередження: відповідь
    # не приходить без знаменника. Або сказано, чим шукали (`basis`), або
    # сказано, чому не шукали. Раніше тут стояв `no_denominator` — і тест
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

    Cookie браузер шле сам — і тоді чужа вкладка на localhost змогла б мутувати
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
    # ⚠ Заборона — на глобали, а не на всяку згадку `window`. Підписка на подію
    # вікна (історія навігації) нічого в глобальний простір не кладе й колізії
    # імен не створює; читання `window.location` — тим паче.
    stripped = js.replace("window.location", "").replace("window.addEventListener", "")
    assert "window." not in stripped


def test_rebuild_button_gives_one_job_for_two_clicks(client: TestClient,
                                                     monkeypatch) -> None:
    """🔴 Кнопку 🔄 натискають двічі — бо після першого натискання нічого не видно.

    Два проходи писали б у ту саму базу й у той самий файл бібліотеки. Захист
    тут — пошук активної роботи, а не ключ ідемпотентності: той живе десять
    хвилин і після завершення віддавав би старий готовий запис, а натискають
    цю кнопку саме тому, що щойно щось змінилось.
    """
    import time

    from nyshporka.cases import db

    # Перезбірку сповільнюємо, щоб робота гарантовано була ЩЕ активною на
    # момент другого натискання — інакше тест вимірював би швидкість диска.
    def slow_index(*_a: object, **_k: object) -> dict[str, object]:
        time.sleep(0.6)
        return {"cases": 0, "orphans": 0, "path": "тест"}

    monkeypatch.setattr(db, "build_index", slow_index)

    h = {TOKEN_HEADER: TOKEN}
    body = {"rescan": False}
    first = client.post("/api/op/cases.build", json=body, headers=h).json()
    second = client.post("/api/op/cases.build", json=body, headers=h).json()
    assert first["data"]["job_id"] == second["data"]["job_id"], \
        "друге натискання завело другий прохід по тій самій базі"


def test_rebuild_is_a_mutation_and_needs_a_token(client: TestClient) -> None:
    """Перезбірка переписує реєстр — чужа вкладка на localhost не має права."""
    assert client.post("/api/op/cases.build", json={}).status_code == 403


def test_a_long_op_that_cannot_start_says_why(client: TestClient) -> None:
    """🔴 Найперша помилка аматора — не та тека. Він мусить це прочитати.

    Постановка в чергу робить справжню роботу до старту: шукає теку, рахує
    кадри, добирає модель. Саме там ловляться найчастіші перші відмови — і без
    перехоплення вони прилітали як «Internal Server Error»: екран показував
    «Не вийшло» без жодного слова про причину, хоч причина була написана.
    """
    r = client.post("/api/op/read.start", json={"case_dir": "Ж:/нема-такої-теки"},
                    headers={TOKEN_HEADER: TOKEN})
    assert r.status_code == 400, "відмова прийшла як збій сервера"
    body = r.json()
    assert body["ok"] is False
    assert "теки" in body["error"], f"причина не дійшла: {body['error']!r}"


def test_an_unknown_source_is_named_not_swallowed(client: TestClient) -> None:
    r = client.post("/api/op/acquire.start", json={"source": "невідоме", "ref": "x"},
                    headers={TOKEN_HEADER: TOKEN})
    assert r.status_code == 400
    assert "невідоме" in r.json()["error"]


def test_fresh_workspace_shows_an_empty_list_not_a_failure(client: TestClient) -> None:
    """🔴 Перше, що бачить новачок, відкривши «Мої справи».

    Реєстру в щойно створеному просторі немає — і це нормальний стан, а не
    поламка. Відмова малювала червоне «Не вийшло» замість порожнього переліку,
    а екран на відмові не будувався взагалі — разом із кнопкою 🔄, якою це й
    лікується: вихід зникав саме тоді, коли був потрібен.
    """
    r = client.post("/api/op/cases.list", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["cases"] == []
    assert body["data"]["registry"] is False
    assert any(w["code"] == "no_registry_yet" for w in body["warnings"])
    assert body["stale"]["is"] is True and body["stale"]["fix"]


def test_listing_the_disk_needs_the_app_token(client: TestClient) -> None:
    """🔴 Гортач тек віддає розкладку диска — це читання, але не публічне.

    Токен вимагається не через `mutates`: позначити читання мутацією означало б
    збрехати одразу в трьох місцях (пульс «дані змінились», напис агентові
    «змінює стан», позначка правки в командному рядку) заради одного побічного
    ефекту. Для цього є окрема ознака, і саме її перевіряє цей тест.
    """
    res = client.post("/api/op/pick.browse", json={})
    assert res.status_code == 403, "вміст тек віддається без токена"
    res = client.post("/api/op/pick.browse", json={},
                      headers={TOKEN_HEADER: TOKEN})
    assert res.status_code == 200


def test_a_foreign_host_header_is_refused(client: TestClient) -> None:
    """🔴 Захист від перев'язування імені, а не від мережі.

    Бінд і так лише на петлю — але сайт із коротким часом життя запису спершу
    віддає свою адресу, а потім `127.0.0.1`, і для браузера це лишається той
    самий origin: ні перевірка походження, ні правила куків не спрацьовують.
    Далі його скрипт говорить із демоном як своя ж сторінка.
    """
    res = client.get("/api/health", headers={"Host": "evil.example"})
    assert res.status_code == 403
    assert "127.0.0.1" in res.json().get("error", "")


def test_the_page_token_never_leaves_under_another_name(client: TestClient) -> None:
    """🔴 Найдорожче в перев'язуванні імені — те, що токен віддається сам.

    Сторінка несе його вшитим (інакше його міг би попросити будь-хто), тож
    перший же запит чужого скрипта до кореня видавав би ключ від усього
    застосунку. Тобто без перевірки імені токенна схема трималась лише на тому,
    що ніхто не спробує.
    """
    res = client.get("/", headers={"Host": "evil.example"})
    assert res.status_code == 403
    assert TOKEN not in res.text
