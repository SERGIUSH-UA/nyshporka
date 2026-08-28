"""🧩 Секції: те, що вимкнено, мусить бути вимкнено всюди.

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
    """🔴 Набір, що дорівнює пресету, зберігається іменем пресету.

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

    Демон резолвить простір один раз на старті й живе годинами, а
    `nysh sections` — окремий процес, який міняє файл. Зі знімком у пам'яті
    браузер показував вимкнене як увімкнене доти, доки застосунок не
    перезапустять: налаштування «не діяли», і зрозуміти чому не було звідки.
    """
    from fastapi.testclient import TestClient

    from nyshporka.core import workspace as W
    from nyshporka.daemon.app import create_app

    client = TestClient(create_app(W.workspace(), token="t0ken"),
                        base_url="http://127.0.0.1:8788")
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
    не проходячи через реєстр. Фільтр, який стоїть тільки в `call()`, пропустив
    би саме найдорожчі операції — читання справи й завантаження з архіву.
    """
    from fastapi.testclient import TestClient

    from nyshporka.core import workspace as W
    from nyshporka.daemon.app import create_app

    W.set_sections(["core"])
    app = create_app(W.workspace(), token="t0ken")
    client = TestClient(app, base_url="http://127.0.0.1:8788")
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
    client = TestClient(create_app(W.workspace(), token="t0ken"),
                        base_url="http://127.0.0.1:8788")

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

    Пак довідників лежить окремим релізом: він оновлюється, коли архів виклав
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


def _without_functions(text: str, names: set[str]) -> str:
    """Текст скрипта без тіл названих функцій (лічильник фігурних дужок)."""
    import re

    pattern = re.compile(r"function\s+(?:" + "|".join(map(re.escape, names)) + r")\b")
    out, i = [], 0
    while True:
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:m.start()])
        j, depth = text.index("{", m.end()), 0
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


def test_windows_installer_never_merges_native_stderr() -> None:
    """🔴 `2>&1` над рідною командою вбиває інсталятор на ПЕРШОМУ ж запуску.

    Windows PowerShell 5.1 обгортає кожен рядок, який exe написав у stderr, у
    ErrorRecord `NativeCommandError`, а `$ErrorActionPreference = 'Stop'` на
    початку скрипта робить його ТЕРМІНАЛЬНИМ. Тобто установлення помирає від
    ІНФОРМАЦІЙНОГО повідомлення.

    Це не гіпотеза. `& $uv tool update-shell 2>&1 | Out-Null` стояв рівно в
    тій гілці, яка виконується, коли теки з командою ще немає в PATH, — тобто
    на КОЖНІЙ чистій машині. uv друкував «Updated PATH to include executable
    directory …» (успіх), скрипт обривався перед `nysh init`, `doctor` і
    ярликом, і людина бачила червону стіну там, де насправді все завантажилось
    (звіт користувача 28.08.2026).

    ⚠ `2>$null` не рятує — перевірено окремо: гасне ВИВІД, а не ErrorRecord.
    Рятує тільки тимчасово послаблена преференція, тому перенаправлення
    дозволене виключно всередині помічників, які її знімають.
    """
    root = Path(__file__).resolve().parents[1] / "install"
    text = (root / "windows.ps1").read_text(encoding="utf-8")

    helpers = {"Invoke-Muted", "Get-NativeLine"}
    for name in helpers:
        assert f"function {name}" in text, (
            f"помічник {name} зник — перенаправлення нема куди сховати")

    body = _without_functions(text, helpers)
    guilty = [ln.strip() for ln in body.splitlines()
              if not ln.lstrip().startswith("#")
              and ("2>&1" in ln or "2>$null" in ln)]
    assert not guilty, (
        "перенаправлення stderr рідної команди поза помічниками — "
        "інсталятор упаде на першому ж інформаційному рядку uv:\n  "
        + "\n  ".join(guilty))


def test_installers_put_the_tool_binaries_on_path() -> None:
    """🔴 Установити команду й не дати її набрати — це не встановлення.

    `uv tool install` кладе `nysh` у власну теку, і в PATH її може не бути.
    `uv tool update-shell` дописує теку в PATH КОРИСТУВАЧА, тобто для вікон,
    які відкриють ПІСЛЯ; поточне про це не дізнається ніколи. А останнє, що
    друкує інсталятор, — «Готово. Далі: nysh serve», і набирає це людина саме
    в поточному вікні. Обидва наші користувачі 28.08.2026 вперлись сюди:
    `nysh init …` → «не розпізнано як імʼя командлета».

    Тому обидва скрипти мусять правити PATH ПРОЦЕСУ, а теку — питати в uv, а
    не вгадувати: вона налаштовується (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`), і
    здогад про `~/.local/bin` збігається лише з типовим випадком.
    """
    root = Path(__file__).resolve().parents[1] / "install"
    for name, mutation in (("windows.ps1", "$env:PATH = \"$binDir;$env:PATH\""),
                           ("unix.sh", 'PATH="$BIN:$PATH"')):
        text = (root / name).read_text(encoding="utf-8")
        assert "tool dir --bin" in text, (
            f"{name}: теку з командою вгадують замість спитати в uv")
        assert mutation in text, (
            f"{name}: PATH поточного процесу не правиться — підказки в кінці "
            f"установлення не спрацюють у тому ж вікні")
        assert "update-shell" in text, (
            f"{name}: PATH не закріплюється для наступних сеансів")


def test_installers_survive_having_no_file_of_their_own() -> None:
    """🔴 Однорядковий запуск означає, що в скрипта НЕМАЄ теки й немає файла.

    `irm … | iex` і `curl … | sh` — те, що дають агентові й людині без клону
    репозиторію (скарга 28.08.2026: «гітхаб не віддав вміст через доступні
    інструменти»). У такому запуску `$PSScriptRoot` порожній, а `$0` дорівнює
    імені оболонки. Обидва скрипти шукають поруч із собою пак довідників —
    і без явної умови роблять це «поруч» з нізвідки: PowerShell мовчки нічого
    не знаходить (правильно, але випадково), а `dirname "$0"` дає ПОТОЧНУ
    теку, тобто пак шукався б там, де людина просто стоїть.
    """
    root = Path(__file__).resolve().parents[1] / "install"
    win = (root / "windows.ps1").read_text(encoding="utf-8")
    nix = (root / "unix.sh").read_text(encoding="utf-8")

    assert "if ($PSScriptRoot)" in win, (
        "windows.ps1: пошук пака довідників не захищено від порожнього "
        "$PSScriptRoot — при запуску через `irm | iex` теки просто немає")
    assert 'if [ -f "$0" ]; then' in nix, (
        'unix.sh: пошук пака довідників не захищено від `curl | sh` — '
        '`dirname "$0"` дасть поточну теку, а не теку інсталятора')


def test_install_surfaces_tell_people_to_reopen_the_terminal() -> None:
    """🔴 Фраза мусить бути КОРОТКА і стояти ПЕРЕД переліком команд.

    Це не стилістика. Користувач 28.08.2026, отримавши після встановлення
    «nysh init …» → «не розпізнано як імʼя командлета», написав дослівно:
    «Побачив єдине знайоме слово "перезапустити" і надіслав комп'ютер
    перезапускатися. Ніби допомогло». Пояснення про PATH він не прочитав —
    прочиталась дія. Тому обидва інсталятори й README кажуть саме дію, а
    в інсталяторах вона стоїть до списку команд, а не після нього.
    """
    root = Path(__file__).resolve().parents[1]
    surfaces = {
        "windows.ps1": (root / "install" / "windows.ps1").read_text(encoding="utf-8"),
        "unix.sh": (root / "install" / "unix.sh").read_text(encoding="utf-8"),
        "README.md": (root / "README.md").read_text(encoding="utf-8"),
    }
    for name, text in surfaces.items():
        assert "перезапустіть комп'ютер" in text, (
            f"{name}: немає запасної поради на випадок, коли нове вікно не "
            f"допомогло — саме це слово людина й упізнає")
        # Обрізано до кореня навмисно: «нове вікно» й «новий термінал» —
        # той самий припис, і рід іменника тут нічого не вирішує.
        assert "відкрийте нов" in text.lower(), (
            f"{name}: не сказано найдешевшої дії — відкрити нове вікно")

    for name in ("windows.ps1", "unix.sh"):
        text = surfaces[name]
        hint = text.lower().index("відкрийте нов")
        listing = text.index("nysh serve            відкрити застосунок")
        assert hint < listing, (
            f"{name}: підказка про перезапуск стоїть ПІСЛЯ переліку команд — "
            f"тобто після того, як людина вже спробувала їх набрати")


def test_readme_installs_without_cloning_the_repository() -> None:
    """🔴 Два шляхи, жоден із яких не вимагає ходити сторінками GitHub.

    Скарга 28.08.2026: агент не зміг дістати вміст репозиторію доступними
    інструментами — а єдиний задокументований спосіб для Windows вимагав
    спершу мати клон. Тому README мусить нести (1) адресу самого скрипта на
    `raw.githubusercontent.com` і (2) установлення з PyPI, у якому GitHub не
    бере участі взагалі.
    """
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    raw = "https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install"

    for script in ("windows.ps1", "unix.sh"):
        assert f"{raw}/{script}" in readme, (
            f"README не дає прямої адреси {script} — без неї установлення "
            f"починається з клонування репозиторію")
        assert (root / "install" / script).exists(), (
            f"README посилається на install/{script}, якого немає")

    assert 'uv tool install "nyshporka[app,archives,htr]"' in readme, (
        "README не показує шляху з PyPI — єдиного, що обходиться без GitHub")


def test_agent_instructions_say_how_to_install() -> None:
    """🔴 Агентові, якому сказали «постав», мусить бути куди піти.

    `AGENTS.md` — єдиний документ, адресований агентові, і він починався з
    `nysh doctor`, тобто з уже встановленої Нишпорки. Слова «встановити» в
    ньому не було взагалі, як і в `docs/agents/**`. Тобто на прохання
    «постав за цим посиланням» агент або йшов читати README (500+ рядків
    прози для людини), або вигадував спосіб сам — а найпростіший вигаданий
    спосіб тут `pip install` у системний Python, який на робочій машині
    ламається тихо.

    Заразом перевіряємо, що інструкція несе саме РОБОЧУ форму: `irm … | iex`
    для цього файла не працює через BOM, і агент, який її звідси візьме,
    отримає десяток помилок розбору замість установлення (звід 0.5.2).
    """
    root = Path(__file__).resolve().parents[1]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    raw = "https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install"

    for script in ("windows.ps1", "unix.sh"):
        assert f"{raw}/{script}" in agents, (
            f"AGENTS.md не каже, звідки взяти {script} — агент почне з клону "
            f"репозиторію або вигадає свій спосіб")
    assert "-OutFile" in agents, (
        "AGENTS.md не дає робочої форми для Windows: спершу `-OutFile`, потім `-File`")
    assert "windows.ps1 | iex" not in agents, (
        "AGENTS.md радить форму з конвеєром — вона падає на BOM у шапці файла")
    assert 'uv tool install "nyshporka[app,archives,htr]"' in agents, (
        "AGENTS.md не показує шляху з PyPI — найкоротшого там, де Python уже є")
    assert "nysh doctor --json" in agents, (
        "в інструкції немає приймача: чим агент доведе, що встановлення вдалося")


def test_readme_points_agents_at_one_link() -> None:
    """⚠ Посилання мусить стояти ТАМ, де його шукають, — у «Установленні».

    Досі `AGENTS.md` згадувався єдиний раз, на 400-му з гаком рядку README, у
    розділі про роботу з агентом. Людина, яка хоче сказати «дай агентові
    посилання», доти його не дочитує.
    """
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    head = readme[readme.index("## Установлення"):readme.index("### Windows")]
    assert "AGENTS.md" in head, (
        "у шапці розділу «Установлення» немає посилання для агента")


def test_windows_remote_install_downloads_the_file_first() -> None:
    """🔴 `irm … | iex` для цього інсталятора НЕ працює — і це не стиль.

    `windows.ps1` лежить із UTF-8 BOM, і не може не лежати: без BOM Windows
    PowerShell 5.1 читає файл як ANSI, і кирилиця ламається ще до першого
    рядка виводу (приймач — `test_windows_installer_is_utf8_with_bom`).
    А `Invoke-RestMethod` віддає той BOM першим символом рядка, після чого ні
    `iex`, ні `[scriptblock]::Create` вміст не розбирають: відмова виглядає як
    десяток помилок розбору всередині коментаря-шапки.

    Спіймано наскрізним прогоном одразу після випуску 0.5.1: у README поїхала
    саме форма з конвеєром, і команда, яку читач копіює першою, не працювала
    взагалі. Перевірено на 5.1: той самий текст без BOM розбирається, з BOM —
    ні, і не рятує ні перенос, ні пробіл, ні рядковий коментар перед шапкою.

    Тому документована форма — завантажити файл і запустити його як файл.
    """
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")

    win = readme[readme.index("## Установлення"):readme.index("### Де лежить")]
    assert "-OutFile" in win and "-File " in win, (
        "README не дає робочої форми віддаленого запуску для Windows: "
        "спершу `-OutFile`, потім `powershell -File`")
    for trap in ("windows.ps1 | iex", "[scriptblock]::Create((irm"):
        assert trap not in win, (
            f"README знову радить «{trap}» — ця форма падає на BOM, "
            f"і падає в шапці, тобто до будь-якого корисного виводу")


def test_installer_parses_exactly_as_it_is_served() -> None:
    """🔴 Розбираємо ті самі БАЙТИ, що лягають на диск користувача.

    Сусідній приймач вище розбирає файл через `ParseFile`, і цього виявилось
    замало: він читає файл із диска, де BOM знімає сам .NET. Дорога, якою
    файл приходить до людини, інша — завантажений і запущений як файл, — і
    саме на ній 0.5.1 і спіткнувся. Тут байти копіюються без жодної обробки,
    тобто перевіряється рівно те, що виконуватиметься.

    ⚠ Тільки Windows PowerShell 5.1: вада версійна, а `pwsh` 7 поводиться
    інакше й показав би зелене там, де в людини червоне.
    """
    import os
    import subprocess
    import tempfile

    if os.name != "nt":
        pytest.skip("вада специфічна для Windows PowerShell 5.1")
    ps51 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) \
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not ps51.exists():
        pytest.skip("Windows PowerShell 5.1 недоступний")

    src = Path(__file__).resolve().parents[1] / "install" / "windows.ps1"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "windows.ps1"
        copy.write_bytes(src.read_bytes())          # побайтово, разом із BOM
        check = (
            "$e=$null; $null=[System.Management.Automation.Language.Parser]"
            f"::ParseFile('{copy}',[ref]$null,[ref]$e); "
            "if($e.Count){ $e[0].Extent.StartLineNumber; $e[0].Message; exit 1 }"
        )
        r = subprocess.run([str(ps51), "-NoProfile", "-NonInteractive",
                            "-Command", check],
                           capture_output=True, text=True)
    assert r.returncode == 0, (
        "завантажений файл не розбирається під PowerShell 5.1 — саме в такому "
        f"вигляді він доходить до користувача:\n{r.stdout}{r.stderr}")


def test_installers_are_at_least_parseable() -> None:
    """🔴 Інсталятор мусить бодай розбиратись — інакше він падає на першому рядку.

    ⚠ Це не гіпотетично. Сусідній приймач вище перевіряє, що в скрипті є адреса
    релізів, і він лишався зеленим, коли `$CatalogUrl = 'https://…` стояв без
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

    # ⚠ Кожен скрипт перевіряється там, ДЕ він працює. `bash`, знайдений на
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
