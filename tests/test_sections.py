"""🧩 Секції: те, що вимкнено, мусить бути вимкнено ВСЮДИ.

Три речі, які тут закріплені, бо кожну легко зламати непомітно:

1. **Профіль переживає перечитування.** Записане в маркер має читатись назад
   тим самим — інакше налаштування «діє до перезапуску», і людина вважає, що
   застосунок її не слухає.
2. **Відмова однакова для трьох облич.** Фільтр стоїть у `core.ops.call()`, тож
   CLI, HTTP і агент не можуть розійтись у тому, що ввімкнено. Окремо
   перевіряється діра, через яку це майже сталось: довгі операції йдуть повз
   реєстр, у чергу демона.
3. **Порожня секція не потрапляє в UI.** Оголошена, але без жодної операції —
   це вкладка без вмісту, тобто обіцянка без входу.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path):
    """Простір із маркером на диску — саме в нього пишеться профіль."""
    from nyshporka.core import workspace as W

    root = tmp_path / "ws"
    (root / "data" / "derived").mkdir(parents=True)
    (root / "nyshporka.toml").write_text(
        '[workspace]\nschema = 1\nname = "тест"\n', encoding="utf-8")
    W.reset()
    W.use(root)
    yield root
    W.reset()


# ── чисті функції ────────────────────────────────────────────────────────────
def test_default_keeps_todays_behaviour() -> None:
    """🔴 Простір, який про секції нічого не знає, мусить бачити все, що бачив.

    Інакше оновлення пакета мовчки звузило б застосунок, і виглядало б це як
    зникла половина програми.
    """
    from nyshporka.core import sections as S

    assert S.resolve() == S.preset_sections(S.DEFAULT_PRESET)
    assert S.resolve() >= {"core", "material", "htr", "research"}


def test_required_section_is_always_present() -> None:
    from nyshporka.core import sections as S

    assert S.resolve(explicit=[]) == S.required_ids()
    assert "core" in S.resolve(explicit=["material"])


def test_unknown_names_are_loud() -> None:
    """Друкарська помилка мусить бути видною, а не тихо давати дефолт."""
    from nyshporka.core import sections as S

    with pytest.raises(S.SectionError):
        S.resolve(explicit=["htrr"])
    with pytest.raises(S.SectionError):
        S.preset_sections("advanced")


def test_every_screen_belongs_to_a_declared_section() -> None:
    from nyshporka.core import sections as S

    assert set(S.SCREENS.values()) <= S.ids()


def test_every_op_declares_a_known_section() -> None:
    from nyshporka import ops as O
    from nyshporka.core import sections as S

    for op in O.all_ops():
        assert op.section in S.ids(), f"{op.name}: секція «{op.section}»"


def test_empty_section_is_not_offered_as_a_tab() -> None:
    """Оголошена, але порожня секція не показується — вкладки без вмісту немає."""
    from nyshporka import ops as O
    from nyshporka.core import sections as S

    in_use = O.sections_in_use()
    empty = S.ids() - in_use
    for sid in empty:
        assert not S.screens_of(sid), (
            f"секція «{sid}» без жодної операції, але має екрани "
            f"{S.screens_of(sid)} — кнопка вела б у порожнечу")


# ── профіль у маркері ────────────────────────────────────────────────────────
def test_profile_survives_a_reread(space: Path) -> None:
    from nyshporka.core import workspace as W

    W.set_sections(["core", "material"])
    W.reset()
    W.use(space)
    assert W.workspace().sections == frozenset({"core", "material"})


def test_preset_is_stored_as_a_preset(space: Path) -> None:
    """🔴 Набір, що дорівнює пресету, зберігається ІМЕНЕМ пресету.

    Простір із записаним пресетом отримає секцію, додану в майбутній версії;
    простір із застиглим переліком — ні, і людина про це не дізнається.
    """
    from nyshporka.core import sections as S
    from nyshporka.core import workspace as W

    W.set_sections(S.preset_sections("amateur"))
    text = (space / "nyshporka.toml").read_text(encoding="utf-8")
    assert 'preset = "amateur"' in text
    assert "sections =" not in text, "поруч із пресетом лишився другий перелік"


def test_custom_set_clears_the_preset(space: Path) -> None:
    """Двох правд у файлі не лишається: записуючи одне, друге знімаємо."""
    from nyshporka.core import sections as S
    from nyshporka.core import workspace as W

    W.set_sections(S.preset_sections("amateur"))
    # Набір, якого немає серед пресетів: дослідження без матеріалів.
    custom = frozenset({"core", "research"})
    assert S.preset_of(custom) is None, "приклад перестав бути власним набором"
    W.set_sections(custom)
    text = (space / "nyshporka.toml").read_text(encoding="utf-8")
    assert "sections =" in text
    assert "preset =" not in text


def test_running_app_sees_a_profile_changed_from_outside(space: Path) -> None:
    """🔴 Знайдено на живому застосунку, а не в тесті.

    Демон резолвить простір ОДИН раз на старті й живе годинами, а
    `nysh sections` — окремий процес, який міняє файл. Зі знімком у пам'яті
    браузер показував вимкнене як увімкнене доти, доки застосунок не
    перезапустять: налаштування «не діяли», і зрозуміти чому не було звідки.
    """
    from fastapi.testclient import TestClient

    from nyshporka.core import workspace as W
    from nyshporka.daemon.app import create_app

    client = TestClient(create_app(W.workspace(), token="t0ken"))
    assert "search.run" in {o["name"] for o in client.get("/api/ops").json()["ops"]}

    # Правку робить хтось інший — прямо у файлі, повз цей процес.
    (space / "nyshporka.toml").write_text(
        '[workspace]\npreset = "catalog"\n', encoding="utf-8")

    names = {o["name"] for o in client.get("/api/ops").json()["ops"]}
    assert "search.run" not in names, "живий застосунок не побачив зміни профілю"
    res = client.post("/api/op/read.start", json={},
                      headers={"X-Nysh-Token": "t0ken"})
    assert res.status_code == 404


def test_broken_profile_does_not_break_the_app(space: Path) -> None:
    """🔴 Помилка в текстовому файлі не робить застосунок незапускним.

    Береться дефолт, а причина лишається на видноті — інакше одна друкарська
    помилка коштувала б людині всієї програми.
    """
    from nyshporka.core import sections as S
    from nyshporka.core import workspace as W

    (space / "nyshporka.toml").write_text(
        '[workspace]\nsections = ["core", "htrr"]\n', encoding="utf-8")
    W.reset()
    W.use(space)
    ws = W.workspace()
    assert ws.sections == S.resolve()
    assert "htrr" in ws.sections_problem


# ── відмова на трьох обличчях ────────────────────────────────────────────────
def test_disabled_section_refuses_in_the_registry(space: Path) -> None:
    from nyshporka import ops as O
    from nyshporka.core import workspace as W

    W.set_sections(["core"])
    env = O.call("search.run", {"q": "Іванов"})
    assert not env.ok
    assert "nysh sections enable research" in env.error


def test_required_section_still_works_when_all_else_is_off(space: Path) -> None:
    from nyshporka import ops as O
    from nyshporka.core import workspace as W

    W.set_sections(["core"])
    assert O.call("workspace.info").ok


def test_long_ops_are_filtered_too(space: Path) -> None:
    """🔴 Діра, через яку це майже сталось.

    `read.start` і `acquire.start` мають `long=True`: демон віддає їх у чергу,
    НЕ проходячи через реєстр. Фільтр, який стоїть тільки в `call()`, пропустив
    би саме найдорожчі операції — читання справи й завантаження з архіву.
    """
    from fastapi.testclient import TestClient

    from nyshporka.core import workspace as W
    from nyshporka.daemon.app import create_app

    W.set_sections(["core"])
    app = create_app(W.workspace(), token="t0ken")
    client = TestClient(app)
    for name in ("read.start", "acquire.start"):
        res = client.post(f"/api/op/{name}", json={},
                          headers={"X-Nysh-Token": "t0ken"})
        assert res.status_code == 404, f"{name}: {res.status_code}"
        assert "nysh sections enable" in res.json()["detail"]


def test_http_hides_disabled_ops_and_lists_sections(space: Path) -> None:
    from fastapi.testclient import TestClient

    from nyshporka.core import workspace as W
    from nyshporka.daemon.app import create_app

    W.set_sections(["core", "material"])
    client = TestClient(create_app(W.workspace(), token="t0ken"))

    names = {o["name"] for o in client.get("/api/ops").json()["ops"]}
    assert "catalog.search" in names
    assert "search.run" not in names, "операція вимкненої секції лишилась у списку"

    data = client.get("/api/sections").json()["data"]
    by_id = {s["id"]: s for s in data["sections"]}
    assert by_id["material"]["active"] and not by_id["research"]["active"]
    assert not by_id["lab"]["visible"], "порожня секція пропонується як вкладка"


def test_installer_extras_match_the_sections() -> None:
    """🔴 Інсталятор мусить ставити рівно те, що вмикає.

    Перелік extras у ньому неминуче дублює `core.sections.EXTRAS`: спитати в
    пакета, що ставити, можна лише після того, як його вже поставлено. Дублю
    дозволено бути — розходитись не дозволено, бо наслідок тихий: людина
    обирає «Читання», а рушіїв на диску немає, і дізнається вона про це
    посеред першої справи.
    """
    from nyshporka.core import sections as S

    root = Path(__file__).resolve().parents[1] / "install"
    texts = {p.name: p.read_text(encoding="utf-8")
             for p in (root / "windows.ps1", root / "unix.sh")}
    for preset in S.preset_names():
        target = S.install_target(preset)
        assert any(target in t for t in texts.values()), (
            f"пресет «{preset}» ставив би не те: жоден інсталятор не згадує "
            f"{target}")
    for name, text in texts.items():
        for preset in S.preset_names():
            assert preset in text, f"{name}: набір «{preset}» не пропонується"


def test_agent_surface_did_not_grow(space: Path) -> None:
    """Стеля агентських tool'ів не зрушила: керування секціями туди не йде."""
    from nyshporka import ops as O

    agent = {o.name for o in O.for_agent()}
    assert "sections.show" not in agent
    assert "sections.set" not in agent
    assert len(agent) <= 18, f"перелік виріс до {len(agent)}"


def test_installers_point_where_the_catalogue_actually_lives() -> None:
    """🔴 Порада без адреси — половина поради, і саме тут вона найдорожча.

    Пак довідників лежить ОКРЕМИМ релізом: він оновлюється, коли архів виклав
    новий опис, а колесо — коли полагодили ваду. Тому поруч із інсталятором
    його не буває ніколи, і кожне чисте встановлення закінчується рядком
    «довідників поруч немає». Доти цей рядок не казав, звідки їх узяти, — і
    читався як «щось загубилось при встановленні», а `nysh find` мовчки
    лишався без каталогів, хоч README обіцяє відповідь одразу після
    встановлення.
    """
    from nyshporka.catalog import store

    root = Path(__file__).resolve().parents[1] / "install"
    for name in ("windows.ps1", "unix.sh"):
        text = (root / name).read_text(encoding="utf-8")
        assert store.RELEASES_URL in text, (
            f"{name}: порада про довідники не каже, звідки їх брати — "
            f"адреса має збігатися з `catalog.store.RELEASES_URL` "
            f"({store.RELEASES_URL})")


def test_installers_are_at_least_parseable() -> None:
    """🔴 Інсталятор мусить бодай розбиратись — інакше він падає на першому рядку.

    ⚠ Це не гіпотетично. Сусідній приймач вище перевіряє, що в скрипті є адреса
    релізів, і він лишався ЗЕЛЕНИМ, коли `$CatalogUrl = 'https://…` стояв без
    закривної лапки: адреса в тексті була, а сам скрипт не парсився взагалі —
    незакритий рядок з'їдав наступні тридцять і валив усе на `Unexpected token`.
    Тобто перевірка вмісту нічого не каже про те, чи запуститься файл.

    Приймач навмисно слабкий (синтаксис, не поведінка): запускати інсталятор у
    тестах не можна, а розбір ловить рівно той клас вад, який робить його
    непрацездатним цілком.
    """
    import os
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[1] / "install"

    # ⚠ Кожен скрипт перевіряється ТАМ, ДЕ ВІН ПРАЦЮЄ. `bash`, знайдений на
    # Windows, — це WSL: для нього диска `E:` не існує взагалі, і перевірка
    # падала б не на синтаксисі, а на шляху. Перекладати шлях у `/mnt/e/…`
    # означало б покладатись на здогад про те, який саме bash знайшовся.
    if os.name != "nt" and shutil.which("bash"):
        r = subprocess.run(["bash", "-n", str(root / "unix.sh")],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"unix.sh не розбирається:\n{r.stderr}"

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell недоступний — розбір windows.ps1 пропущено")
    # Парсер, а не запуск: `-File` виконав би скрипт, а нам треба лише розбір.
    check = (
        "$e=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{root / 'windows.ps1'}',[ref]$null,[ref]$e); "
        "if($e.Count){ $e[0].Extent.StartLineNumber; $e[0].Message; exit 1 }"
    )
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", check],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"windows.ps1 не розбирається:\n{r.stdout}{r.stderr}"
