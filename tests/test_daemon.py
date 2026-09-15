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


def test_every_gui_op_is_reachable(client: TestClient, ws: Workspace) -> None:
    """Перелік дій береться з реєстру, а не переписується в роутері.

    Переписаний перелік відстає мовчки: дія є в CLI й в агента, а в браузері її
    немає — і ніхто цього не бачить, бо помилки не виникає.

    Порівнюється з реєстром у межах УВІМКНЕНИХ секцій: операції лабораторії
    (`train.*`) існують у реєстрі, але з профілем за замовчуванням у браузер не
    їдуть — і це поведінка секцій, а не переписаний перелік.
    """
    got = {o["name"] for o in client.get("/api/ops").json()["ops"]}
    want = {o.name for o in O.for_sections(ws.sections)}
    assert got == want
    assert "catalog.search" in got
    assert not any(n.startswith("train.") for n in got), "лабораторія ввімкнена без профілю"


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


#: Операції, що беруть шлях файлової системи від клієнта: пишуть за `out` або
#: читають довільну теку. Такий шлях — не публічне читання.
PATH_OPS = ("text.crop", "text.sheet", "train.view", "case.show",
            "catalog.browse", "catalog.manifest", "read.plan")


def test_ops_that_take_a_filesystem_path_need_the_page_token(client: TestClient,
                                                            ws: Workspace) -> None:
    """🔴 Без токена ці операції писали файл куди завгодно (`out`) чи розкривали
    будь-яку теку диска — на петлі їх тримала лише перевірка імені й `Origin`."""
    for name in PATH_OPS:
        op = O.get(name)
        assert op is not None and op.private, f"{name} — шлях від клієнта без токена"
    enabled = {o.name for o in O.for_sections(ws.sections)}
    for name in (n for n in PATH_OPS if n in enabled):
        assert client.post(f"/api/op/{name}", json={}).status_code == 403, name


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
    # Сторінка допуску мережевого режиму — під тими самими правилами, і без
    # жодного inline-скрипта: вона віддається пристрою, який ще нічого не довів.
    gate_html = (static / "access.html").read_text(encoding="utf-8")
    gate_js = (static / "access.js").read_text(encoding="utf-8")
    assert "onclick" not in gate_html and "onsubmit" not in gate_html
    assert "<script>" not in gate_html
    assert "window." not in gate_js


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


def test_a_foreign_page_cannot_call_ops_without_a_preflight(client: TestClient,
                                                            monkeypatch) -> None:
    """🔴 Чужа сторінка шле POST на петлю без жодного попереднього запиту.

    Тіло-`Blob` без типу їде БЕЗ `Content-Type`, тобто як «простий» запит, і
    браузер не питає дозволу. Старіші FastAPI (заміряно на 0.115) розбирають
    таке тіло як JSON, а залежність дозволяє `fastapi>=0.115` — отже операція, що не вимагає
    токена, виконувалась з аргументами чужого сайту. Серед таких є ті, що
    пишуть файл туди, куди вкаже `out` (`text.crop`, `text.sheet`), — тобто
    перезапис будь-якого файла людини з відкритої вкладки. Відсікати мусить
    сам застосунок, а не версія фреймворку.
    """
    from nyshporka.search import textops as T

    called: list[object] = []

    def fake_sheet(*a: object, **k: object) -> dict[str, object]:
        called.append(k.get("out"))
        return {"out": str(k.get("out")), "cards": 0}

    monkeypatch.setattr(T, "sheet", fake_sheet)
    body = b'{"q": "x", "case": "x", "out": "../../important.docx"}'
    r = client.post("/api/op/text.sheet", content=body,
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403, "операція з чужого origin пройшла"
    # `Origin: null` — сторінка з пісочниці чи з `file://`
    r = client.post("/api/op/text.sheet", content=body, headers={"Origin": "null"})
    assert r.status_code == 403, "операція зі сторінки без origin пройшла"
    # інша вкладка на тій самій петлі, але чужому порту — теж чужа сторінка
    r = client.post("/api/op/text.sheet", content=body,
                    headers={"Origin": "http://127.0.0.1:3000"})
    assert r.status_code == 403, "операція зі сторінки на іншому порту пройшла"
    r = client.post("/api/op/text.sheet", content=body,
                    headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403, "запит, позначений браузером як чужий, пройшов"
    assert not called, "операцію викликано з аргументами чужої сторінки"


def test_own_page_origin_still_works(client: TestClient) -> None:
    """Власна сторінка шле `Origin` свого ж адреса — її не можна відсікти."""
    r = client.post("/api/op/workspace.info", json={},
                    headers={"Origin": "http://127.0.0.1:8788"})
    assert r.status_code == 200
    # інструменти без браузера (`curl`, агент) `Origin` не шлють зовсім
    assert client.post("/api/op/workspace.info", json={}).status_code == 200


# ── мережевий режим (`nysh serve --host`) ────────────────────────────────────
LAN = "192.168.1.50"
PEER = ("192.168.1.9", 50000)
ACCESS = "access-for-tests-0123456789abcdefghijklmnop"


@pytest.fixture
def no_fail_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.daemon import app as A

    monkeypatch.setattr(A, "FAIL_DELAY_SEC", 0.0)


def _lan_app(ws: Workspace, **kw: object) -> object:
    return create_app(ws, token=TOKEN, host=LAN, access_key=ACCESS, **kw)  # type: ignore[arg-type]


def _lan(app: object, peer: tuple[str, int] = PEER, scheme: str = "http") -> TestClient:
    """Клієнт мережевого пристрою: з'єднання прийшло на LAN-адресу з іншої машини.

    ⚠ `client=` обов'язковий: дефолтний `testclient` — не IP.
    """
    return TestClient(app, base_url=f"{scheme}://{LAN}:8788", client=peer)  # type: ignore[arg-type]


def test_network_mode_without_a_key_is_not_built(ws: Workspace) -> None:
    """🔴 Мережевий режим без ключа — це архів, відкритий кожному в мережі."""
    with pytest.raises(ValueError):
        create_app(ws, token=TOKEN, host=LAN)


def test_network_device_without_access_sees_only_the_gate(ws: Workspace) -> None:
    """🔴 Токен у мережі не захищає: сторінку з ним отримує кожен.

    Тому до допуску пристрій не бачить ні консолі, ні читання — лише сторінку
    допуску й рівно те, що вона вантажить.
    """
    lan = _lan(_lan_app(ws))
    page = lan.get("/")
    assert page.status_code == 200
    assert "access.js" in page.text and TOKEN not in page.text
    for path in ("/api/health", "/openapi.json", "/api/ops", "/api/jobs",
                 "/api/jobs/wait?timeout_s=1", "/static/app.js", "/static/core/net.js"):
        assert lan.get(path).status_code == 401, path
    assert lan.post("/api/op/workspace.info", json={}).status_code == 401
    for path in ("/static/access.js", "/static/access.css", "/static/core/strings.js",
                 "/ui/tokens.css", "/ui/base.css", "/favicon.ico"):
        assert lan.get(path).status_code == 200, path


def test_websocket_from_a_network_device_is_closed(ws: Workspace) -> None:
    """Ворота стоять і перед websocket: `@app.middleware("http")` його пропускав би."""
    from starlette.testclient import WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    lan = _lan(_lan_app(ws), scheme="ws")
    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)), \
            lan.websocket_connect("/api/ws"):
        pass


def test_pairing_code_admits_one_device_once(ws: Workspace) -> None:
    app = _lan_app(ws)
    code = app.state.pair_code  # type: ignore[attr-defined]
    lan = _lan(app)
    res = lan.post("/api/access", json={"code": code})
    assert res.status_code == 200 and res.json()["ok"] is True
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=" in cookie
    assert ACCESS.lower() not in cookie, "у cookie сам ключ, а не похідне від нього"
    assert lan.get("/api/access").json()["data"]["valid"] is True
    assert TOKEN in lan.get("/").text
    assert lan.get("/api/health").status_code == 200
    # код одноразовий: другий пристрій із тим самим посиланням не проходить
    other = _lan(app, peer=("192.168.1.10", 50000))
    assert other.post("/api/access", json={"code": code}).status_code == 401


def test_expired_pairing_code_is_refused(ws: Workspace, no_fail_delay: None) -> None:
    app = _lan_app(ws)
    app.state.pair_expires = 0.0  # type: ignore[attr-defined]
    res = _lan(app).post("/api/access", json={"code": app.state.pair_code})  # type: ignore[attr-defined]
    assert res.status_code == 401


def test_the_access_key_admits_a_device(ws: Workspace) -> None:
    lan = _lan(_lan_app(ws))
    assert lan.post("/api/access", json={"key": ACCESS}).status_code == 200
    assert lan.get("/api/health").status_code == 200


def test_a_forged_cookie_is_refused(ws: Workspace) -> None:
    lan = _lan(_lan_app(ws))
    lan.cookies.set("nysh_access_8788", "0" * 64)
    assert lan.get("/api/health").status_code == 401


def test_access_does_not_replace_the_token_or_origin_check(ws: Workspace) -> None:
    """Cookie — лише допуск. Мутація й далі вимагає токена й власної сторінки."""
    lan = _lan(_lan_app(ws))
    lan.post("/api/access", json={"key": ACCESS})
    assert lan.post("/api/op/pick.browse", json={}).status_code == 403
    r = lan.post("/api/op/pick.browse", json={},
                 headers={TOKEN_HEADER: TOKEN, "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = lan.post("/api/op/pick.browse", json={},
                 headers={TOKEN_HEADER: TOKEN, "Origin": f"http://{LAN}:8788"})
    assert r.status_code == 200


def test_wrong_keys_block_the_address_for_a_while(ws: Workspace, no_fail_delay: None) -> None:
    app = _lan_app(ws)
    lan = _lan(app)
    for _ in range(10):
        assert lan.post("/api/access", json={"key": "не той"}).status_code == 401
    assert lan.post("/api/access", json={"key": ACCESS}).status_code == 429
    # блок — на адресу, а не на всіх
    assert _lan(app, peer=("192.168.1.11", 1)).post(
        "/api/access", json={"key": ACCESS}).status_code == 200


def test_a_stale_cookie_does_not_count_as_a_wrong_key(ws: Workspace,
                                                     no_fail_delay: None) -> None:
    """🔴 Після `--rotate-key` відкрита вкладка власника шле протухлу cookie
    десятками запитів — рахуй їх, і власник заблокував би сам себе."""
    lan = _lan(_lan_app(ws))
    lan.cookies.set("nysh_access_8788", "0" * 64)
    for _ in range(30):
        lan.get("/api/jobs")
    assert lan.post("/api/access", json={"key": ACCESS}).status_code == 200


def test_access_body_is_capped_by_bytes_not_by_content_length(ws: Workspace,
                                                              no_fail_delay: None) -> None:
    """🔴 Chunked-тіло заголовка довжини не має.

    Ліміт, що дивився лише на `Content-Length`, пропускав таке тіло цілим у
    пам'ять: пристрій без жодного допуску роздував демона сотнями мегабайтів.
    """
    lan = _lan(_lan_app(ws))
    padded = ('{"key": "' + ACCESS + '", "pad": "' + "x" * 8000 + '"}').encode()

    def chunks():  # type: ignore[no-untyped-def]
        for i in range(0, len(padded), 1000):
            yield padded[i:i + 1000]

    hdr = {"Content-Type": "application/json"}
    assert lan.post("/api/access", content=chunks(), headers=hdr).status_code == 413
    assert lan.post("/api/access", content=padded, headers=hdr).status_code == 413
    assert lan.post("/api/access", json={"key": ACCESS}).status_code == 200


def test_parallel_wrong_keys_cannot_outrun_the_limit(ws: Workspace,
                                                     no_fail_delay: None) -> None:
    """🔴 Спроба рахується до перевірки ключа.

    Доти паралельні запити з однієї адреси всі проходили перевірку блоку раніше,
    ніж зараховувався перший провал: сорок одночасних — сорок перевірок ключа.
    """
    import asyncio

    import httpx

    app = _lan_app(ws)

    async def slow_body(scope, receive, send):  # type: ignore[no-untyped-def]
        # Справжній клієнт шле тіло не миттєво: читання тіла віддає керування,
        # і саме в цей момент решта паралельних запитів проходила перевірку блоку.
        async def slow_receive():  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.01)
            return await receive()

        await app(scope, slow_receive, send)  # type: ignore[operator]

    async def burst() -> list[int]:
        transport = httpx.ASGITransport(app=slow_body, client=("192.168.1.77", 1))
        async with httpx.AsyncClient(transport=transport,
                                     base_url=f"http://{LAN}:8788") as cl:
            got = await asyncio.gather(*[cl.post("/api/access", json={"key": f"не той {i}"})
                                         for i in range(40)])
        return [r.status_code for r in got]

    codes = asyncio.run(burst())
    assert codes.count(401) <= 10, codes
    assert codes.count(429) >= 30, codes


def test_a_blocked_address_is_not_released_by_crowding_the_counter(
        ws: Workspace, no_fail_delay: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Лічильник витісняв найстаріший запис — тобто саме блок нападника."""
    from nyshporka.daemon import app as A

    monkeypatch.setattr(A, "FAILS_TRACKED_MAX", 32)
    app = _lan_app(ws)
    victim = _lan(app, peer=("192.168.1.66", 1))
    for _ in range(10):
        victim.post("/api/access", json={"key": "не той"})
    for i in range(40):
        _lan(app, peer=(f"192.168.2.{i + 1}", 1)).post("/api/access", json={"key": "не той"})
    assert victim.post("/api/access", json={"key": ACCESS}).status_code == 429


def test_ipv6_neighbours_in_one_subnet_share_the_counter(ws: Workspace,
                                                         no_fail_delay: None) -> None:
    """IPv6-клієнт міняє адресу в межах /64 — лічильник на адресу нічого б не рахував."""
    app = _lan_app(ws)
    for i in range(10):
        _lan(app, peer=(f"2001:db8:1:2::{i + 1:x}", 1)).post(
            "/api/access", json={"key": "не той"})
    same_net = _lan(app, peer=("2001:db8:1:2::ff", 1))
    assert same_net.post("/api/access", json={"key": ACCESS}).status_code == 429
    other_net = _lan(app, peer=("2001:db8:1:3::1", 1))
    assert other_net.post("/api/access", json={"key": ACCESS}).status_code == 200


def test_a_shadowing_cookie_does_not_hide_real_access(ws: Workspace) -> None:
    """Однойменна cookie іншого сервісу на тому самому хості не відбиває допуск."""
    from nyshporka.daemon.app import _cookie_value

    lan = _lan(_lan_app(ws))
    hdr = {"Cookie": f"nysh_access_8788=junk; nysh_access_8788={_cookie_value(ACCESS)}"}
    assert lan.get("/api/health", headers=hdr).status_code == 200


def test_ipv6_link_survives_rich_markup(tmp_path: Path) -> None:
    """🔴 rich читав `[fd00::5]` як тег, а `:ab:` — як емодзі 🆎."""
    import io

    from rich.console import Console

    from nyshporka.daemon.app import _print_network_banner

    # ⚠ Власна консоль, а не `brand.console()`: та спільна, і підміна її `file`
    # (навіть із відкатом) прибивала вивід CLI до чужого потоку — наступні тести
    # бачили порожній вивід.
    buf = io.StringIO()
    out = Console(file=buf, width=200)
    _print_network_banner(out, "fd00:ab::5", 8790, scheme="http", pair_code="PAIR",
                          key_path=tmp_path / "k.key", show_secret=True,
                          rotated=False, tls=False)
    assert "http://[fd00:ab::5]:8790/#pair=PAIR" in buf.getvalue()


def test_access_key_is_written_where_hard_links_are_not_supported(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.daemon import app as A

    def no_link(*_a: object, **_k: object) -> None:
        raise PermissionError("hard links are not supported here")

    monkeypatch.setattr(A.sys, "platform", "linux")
    monkeypatch.setattr(A.os, "link", no_link)
    path = tmp_path / "k.key"
    A._write_access_key(path, replace=False)
    assert len(path.read_text(encoding="ascii")) >= 32


def test_loopback_connection_of_a_network_daemon_needs_no_key(ws: Workspace) -> None:
    """Вкладка на самій машині й тунелі приходять через петлю — як без `--host`."""
    local = TestClient(_lan_app(ws), base_url="http://127.0.0.1:8788")  # type: ignore[arg-type]
    assert TOKEN in local.get("/").text


def test_loopback_is_judged_by_the_address_not_by_its_spelling() -> None:
    from nyshporka.daemon.app import is_loopback_host

    assert is_loopback_host("::ffff:127.0.0.1"), "IPv4-mapped петля на dual-stack"
    assert is_loopback_host("[::1]") and is_loopback_host("localhost")
    assert not is_loopback_host(LAN)
    assert not is_loopback_host("testserver")


def test_network_host_header_must_name_the_connection_address(ws: Workspace) -> None:
    lan = _lan(_lan_app(ws))
    lan.post("/api/access", json={"key": ACCESS})
    assert lan.get("/api/health").status_code == 200
    for bad in ("evil.example", "0.0.0.0", "192.168.1.51"):
        assert lan.get("/api/health", headers={"Host": bad}).status_code == 403, bad


def test_loopback_no_longer_answers_to_zero_address(client: TestClient) -> None:
    """Сторінка з інтернету шле на `0.0.0.0` з `Host: 0.0.0.0` — своїм це ім'я не є."""
    assert client.get("/api/health", headers={"Host": "0.0.0.0:8788"}).status_code == 403


def test_native_dialog_is_not_opened_from_a_network_device(ws: Workspace) -> None:
    """🔴 Системне вікно з'явилось би на екрані сервера, а не пристрою."""
    lan = _lan(_lan_app(ws))
    lan.post("/api/access", json={"key": ACCESS})
    hdr = {TOKEN_HEADER: TOKEN}
    assert lan.post("/api/op/pick.ask", json={}, headers=hdr).status_code == 403
    assert lan.post("/api/op/pick.can", json={"deep": True}, headers=hdr).status_code == 403
    can = lan.post("/api/op/pick.can", json={}, headers=hdr).json()
    assert can["ok"] is True and can["data"]["can"] is False


def test_tls_makes_the_access_cookie_secure(ws: Workspace) -> None:
    lan = _lan(_lan_app(ws, tls=True), scheme="https")
    res = lan.post("/api/access", json={"key": ACCESS})
    cookie = res.headers["set-cookie"]
    assert cookie.startswith("__Host-nysh_access_8788=")
    assert "secure" in cookie.lower()


def test_access_key_is_persistent_rotates_and_lives_outside_the_space(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import platformdirs

    from nyshporka.daemon.app import load_access_key

    monkeypatch.setattr(platformdirs, "user_config_dir",
                        lambda *a, **k: str(tmp_path / "cfg"))
    root = tmp_path / "space"
    root.mkdir()
    key, path = load_access_key(root)
    assert root not in path.parents, "ключ простору не мусить лежати в просторі"
    assert load_access_key(root)[0] == key
    rotated = load_access_key(root, rotate=True)[0]
    assert rotated != key and load_access_key(root)[0] == rotated
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600


def test_broken_or_open_access_key_is_refused(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    import platformdirs

    from nyshporka.daemon.app import AccessKeyError, load_access_key

    monkeypatch.setattr(platformdirs, "user_config_dir",
                        lambda *a, **k: str(tmp_path / "cfg"))
    _, path = load_access_key(tmp_path)
    path.write_text("", encoding="ascii")
    with pytest.raises(AccessKeyError):
        load_access_key(tmp_path)
    if sys.platform != "win32":
        load_access_key(tmp_path, rotate=True)
        path.chmod(0o644)
        with pytest.raises(AccessKeyError):
            load_access_key(tmp_path)


def test_a_specific_address_is_bound_together_with_loopback() -> None:
    """🔴 Конкретний IP не розширюється до всіх інтерфейсів, а петля лишається."""
    from nyshporka.daemon.app import bind_addresses

    assert bind_addresses(LAN) == ["127.0.0.1", LAN]
    assert bind_addresses("0.0.0.0") == ["0.0.0.0"]
    assert bind_addresses("::") == ["0.0.0.0", "::"]


def test_wildcard_sockets_open(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from nyshporka.daemon.app import open_sockets

    socks = open_sockets("0.0.0.0", 0)
    try:
        assert len(socks) == 1
    finally:
        for s in socks:
            s.close()
    if not socket.has_ipv6:
        return
    monkeypatch.setattr("nyshporka.daemon.app.bind_addresses", lambda host: ["::"])
    try:
        socks = open_sockets("::", 0)
    except OSError:
        pytest.skip("IPv6 на цій машині недоступний")
    try:
        assert socks[0].getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for s in socks:
            s.close()


def test_network_host_takes_only_an_ip() -> None:
    from nyshporka.daemon.app import network_host

    assert network_host(" [::] ") == "::"
    for bad in ("mybox.local", "fe80::1", "", "::ffff:192.168.1.50"):
        with pytest.raises(ValueError):
            network_host(bad)


def test_serve_does_not_open_the_network_without_confirmation() -> None:
    """Програмний виклик теж не відкриває мережу мовчки."""
    from nyshporka.daemon.app import serve

    with pytest.raises(ValueError):
        serve(host=LAN)


# ── `nysh serve --host`: застереження й підтвердження ────────────────────────
@pytest.fixture
def serve_cli(ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CLI без справжнього сервера: що саме він передав би в `serve`."""
    import platformdirs

    import nyshporka.cli as C
    import nyshporka.core.workspace as W
    import nyshporka.daemon as D

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(D, "serve", lambda **kw: calls.append(kw))
    monkeypatch.setattr(W, "workspace", lambda: ws)
    monkeypatch.setattr(platformdirs, "user_config_dir",
                        lambda *a, **k: str(tmp_path / "cfg"))
    tty = {"in": False, "out": False}
    monkeypatch.setattr(C, "_stdin_is_tty", lambda: tty["in"])
    monkeypatch.setattr(C, "_stdout_is_tty", lambda: tty["out"])

    from typer.testing import CliRunner

    def run(args: list[str], stdin: str = "") -> object:
        return CliRunner().invoke(C.app, ["serve", "--no-browser", *args], input=stdin)

    return run, calls, tty


def test_serve_default_asks_nothing(serve_cli) -> None:
    run, calls, _ = serve_cli
    got = run([])
    assert got.exit_code == 0, got.output
    assert calls == [{"host": "127.0.0.1", "port": 8788, "open_browser": False}]


def test_serve_network_without_terminal_or_flags_is_refused(serve_cli) -> None:
    run, calls, _ = serve_cli
    got = run(["--host", LAN])
    assert got.exit_code == 1 and not calls
    assert "--confirm-host" in got.output
    assert "відкритим текстом" in got.output, "застереження не надруковано"


def test_serve_network_needs_the_address_typed(serve_cli) -> None:
    run, calls, tty = serve_cli
    tty["in"] = True
    assert run(["--host", LAN], stdin="192.168.1.51\n").exit_code == 1 and not calls
    got = run(["--host", LAN], stdin=f"{LAN}\n")
    assert got.exit_code == 0, got.output
    assert calls[0]["host"] == LAN and calls[0]["confirmed"] is True


def test_serve_all_interfaces_needs_the_phrase_too(serve_cli) -> None:
    from nyshporka.daemon.app import PUBLIC_PHRASE

    run, calls, tty = serve_cli
    tty["in"] = True
    assert run(["--host", "0.0.0.0"], stdin="0.0.0.0\n\n").exit_code == 1 and not calls
    got = run(["--host", "0.0.0.0"], stdin=f"0.0.0.0\n{PUBLIC_PHRASE}\n")
    assert got.exit_code == 0, got.output
    assert calls[0]["host"] == "0.0.0.0"


def test_serve_flags_confirm_without_terminal_and_hide_the_code(serve_cli) -> None:
    run, calls, _ = serve_cli
    assert run(["--host", LAN, "--confirm-host", "192.168.1.51"]).exit_code == 1
    assert run(["--host", "0.0.0.0", "--confirm-host", "0.0.0.0"]).exit_code == 1
    assert not calls
    got = run(["--host", LAN, "--confirm-host", LAN])
    assert got.exit_code == 0, got.output
    assert calls[0]["show_secret"] is False, "код сполучення пішов би в журнал служби"


def test_serve_tls_flags_are_checked_before_anything(serve_cli, tmp_path: Path) -> None:
    run, calls, _ = serve_cli
    cert = tmp_path / "cert.pem"
    cert.write_text("не сертифікат", encoding="utf-8")
    assert run(["--host", LAN, "--confirm-host", LAN, "--tls-cert", str(cert)]).exit_code == 1
    got = run(["--host", LAN, "--confirm-host", LAN,
               "--tls-cert", str(cert), "--tls-key", str(cert)])
    assert got.exit_code == 1 and "сертифікат" in got.output
    assert not calls


def test_serve_prints_ipv6_addresses_verbatim(serve_cli) -> None:
    """🔴 У застереженні й відмові rich друкував `fd00:ab::5` як «fd00🆎:5»."""
    run, calls, _ = serve_cli
    got = run(["--host", "fd00:ab::5"])
    assert got.exit_code == 1 and not calls
    assert "fd00:ab::5" in got.output and "🆎" not in got.output
    got = run(["--host", "[fd00::5]", "--confirm-host", "fd00::6"])
    assert got.exit_code == 1 and "[fd00::5]" in got.output


def test_serve_network_flags_need_a_network_host(serve_cli) -> None:
    run, calls, _ = serve_cli
    assert run(["--rotate-key"]).exit_code == 1
    assert run(["--confirm-host", "127.0.0.1"]).exit_code == 1
    assert not calls


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
