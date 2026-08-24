"""🐾 Айдентика: те, що названо один раз, мусить лишитись однаковим ВСЮДИ.

Бренд розкиданий по чотирьох поверхнях — фронт, командний рядок, README, сайт
документації, — і розходяться вони тихо: нічого не падає, просто через півроку
це виглядає як три різні продукти. Тому кожен зв'язок нижче доводиться числом.

Окремо стоять два виміри, які око не бере:

* **контраст** — палітру задають на доброму екрані, а читають на ноутбуці в
  читальній залі. Саме вимірювач знайшов, що чинний колір другорядного тексту
  давав 4.48 при порозі 4.5 — тобто був нечитабельний рівно на межі;
* **тоновий розрив** рушіїв — бо кольори трьох рушіїв навмисно однакові за
  яскравістю (щоб рівно читатись на полотні), і контрастом їхню розрізненність
  міряти не можна.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from rich.markup import render

from nyshporka import brand as B
from nyshporka.brand import color as C
from nyshporka.brand import gen as GEN

ROOT = Path(__file__).resolve().parents[1]

#: Найвужчий допустимий тоновий розрив між рушіями, у градусах. 40° — межа, за
#: якою сусідні відтінки починають зливатись при дальтонізмі; чинний найгірший
#: розрив 50°, тобто запас є, але не такий, щоб колір можна було правити наосліп.
HUE_MIN = 40.0


def test_engine_styles_match_the_engines() -> None:
    """🔴 Множини рушіїв у двох файлах збігаються.

    Візуал живе в `brand.yaml`, а самі рушії — в `htr/data/engines.yaml`
    (маніфест середовища: піни, пакети, патчі kraken). Розділено навмисно:
    правка оформлення не має чіпати файл, від якого залежить, чи запуститься
    читання. Але розійтись їм не можна — новий рушій без стилю виходив би в
    інтерфейс безбарвним і безіменним, і виглядало б це як несправність.
    """
    from nyshporka.htr import manifest as M

    engines = {e.id for e in M.active().engines}
    styles = {e.id for e in B.active().engines}
    assert engines == styles, (
        f"рушії без стилю: {sorted(engines - styles)}; "
        f"стилі без рушія: {sorted(styles - engines)}")


def test_generated_css_is_not_stale() -> None:
    """🔴 Згенероване збігається з `brand.yaml`.

    Це той самий приймач, що `python -m nyshporka.brand.gen --check`. Він тут,
    а не лише в CI, бо протухання тихе: правку кольору роблять у brand.yaml,
    забувають перегенерувати, і фронт лишається зі старим — розбіжність
    видима тільки поряд.
    """
    stale = [rel for rel, flavour in GEN.targets().items()
             if (ROOT / rel).read_text(encoding="utf-8") != GEN.render(flavour)]
    assert not stale, (
        f"розійшлося з brand.yaml: {stale}; "
        "лікується: uv run python -m nyshporka.brand.gen")


@pytest.mark.parametrize("theme", B.THEMES)
def test_every_text_pair_passes_aa(theme: str) -> None:
    """🔴 Кожна пара «текст на тлі» проходить WCAG AA в ОБОХ темах.

    Порога 3.0 для великого тексту тут не існує: бейджі рушіїв і підказки
    набрані дрібним, тож пом'якшувати нема на чому.
    """
    b = B.active()
    v = b.css_vars(theme)
    pairs = [
        ("текст на полотні", v["fg"], v["bg"]),
        ("текст на картці", v["fg"], v["card"]),
        ("другорядне на полотні", v["muted"], v["bg"]),
        ("другорядне на картці", v["muted"], v["card"]),
        ("попередження", v["warn-fg"], v["warn-bg"]),
        ("відмова на полотні", v["err"], v["bg"]),
        # Кнопка: акцент тлом, полотно текстом. Пара симетрична, тож це ж
        # число покриває і «акцент як текст посилання».
        ("кнопка", v["bg"], v["accent"]),
    ]
    for e in b.engines_ordered():
        tone = v[f"engine-{e.id}"]
        pairs.append((f"рушій {e.id} на полотні", tone, v["bg"]))
        pairs.append((f"рушій {e.id} на картці", tone, v["card"]))

    weak = [(name, round(C.contrast(a, z), 2)) for name, a, z in pairs
            if C.contrast(a, z) < C.AA_TEXT]
    assert not weak, f"нижче AA {C.AA_TEXT} у темі «{theme}»: {weak}"


@pytest.mark.parametrize("theme", B.THEMES)
def test_engines_stay_apart_in_hue(theme: str) -> None:
    """Рушії розрізняються тоном — і не сходяться з відмовою чи попередженням.

    🔴 Бейдж, що збігся з червоним приймачем, читався б як помилка. Це не
    гіпотетично: `Скрибу` вже довелось зсувати з чистого фіолету, бо той стояв
    за 47° від синього `Писаря` — рівно та пара, яку зливає дейтеранопія.
    """
    b = B.active()
    v = b.css_vars(theme)
    es = b.engines_ordered()

    close = [(a.id, z.id, round(C.hue_gap(v[f"engine-{a.id}"], v[f"engine-{z.id}"])))
             for i, a in enumerate(es) for z in es[i + 1:]
             if C.hue_gap(v[f"engine-{a.id}"], v[f"engine-{z.id}"]) < HUE_MIN]
    assert not close, f"рушії зливаються тоном у «{theme}»: {close}"

    for e in es:
        for other in ("err", "warn-fg"):
            gap = C.hue_gap(v[f"engine-{e.id}"], v[other])
            assert gap >= HUE_MIN, (
                f"«{e.id}» стоїть за {gap:.0f}° від «{other}» у темі «{theme}» — "
                "бейдж читатиметься як стан")


def test_engine_badges_survive_without_colour() -> None:
    """🔴 Колір — прискорювач, а не носій.

    Прибираємо розмітку — і рушій має лишитись розрізнимим. Це стан `NO_COLOR`,
    чорно-білого термінала й будь-якого логу; якби носієм був колір, там усі три
    рушії стали б однаковими.
    """
    letters = set()
    for e in B.active().engines_ordered():
        plain = render(B.engine_tag(e.id)).plain
        assert plain.strip(), f"бейдж «{e.id}» без кольору порожній"
        letters.add(plain.strip())
    assert len(letters) == len(B.active().engines), f"літери не унікальні: {letters}"


def test_section_glyphs_cover_the_sections() -> None:
    """Знак є в кожної секції — і зайвих знаків немає.

    Навігацію будує фронт із `/api/sections`, тож знак, якого бракує, дає
    кнопку без іконки поряд із оформленими, а зайвий — мертвий рядок у даних.
    """
    from nyshporka.core import sections as S

    declared = {s.id for s in S.SECTIONS}
    glyphs = set(B.active().section_glyphs)
    assert declared == glyphs, (
        f"секції без знака: {sorted(declared - glyphs)}; "
        f"знаки без секції: {sorted(glyphs - declared)}")


def test_console_is_created_in_one_place() -> None:
    """🔴 `Console()` не створюється поза `brand/`.

    П'ять незалежних Console'ів уже давали розбіжність: лише один із них знав,
    що при перенаправленні виводу ширину треба задати вручну. Тест тримає межу,
    бо наступний модуль напишеться копіюванням сусіднього.
    """
    allowed = {Path("src/nyshporka/brand/console.py")}
    offenders = []
    for path in (ROOT / "src" / "nyshporka").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel in allowed:
            continue
        if re.search(r"\bConsole\s*\(", path.read_text(encoding="utf-8")):
            offenders.append(str(rel))
    assert not offenders, (
        f"свій Console замість brand.console(): {offenders}")


def test_marks_are_the_ones_agents_are_taught() -> None:
    """Словник позначок збігається з тим, що обіцяно агентові в `AGENTS.md`.

    ⚠ Позначки — не прикраса: на 🔴 і 🛑 в агента писана поведінка. Якби гліф
    розійшовся, інструкція посилалась би на знак, якого у виводі немає.
    """
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for m in B.active().marks:
        assert m.glyph in text, f"позначки «{m.glyph}» ({m.id}) немає в AGENTS.md"


def test_screen_glyphs_cover_the_screens() -> None:
    """Знак є в кожного екрана навігації — і зайвих немає.

    Джерело переліку — `core.sections.SCREENS` (сервер), а не список у фронті:
    саме сервер віддає знаки браузеру, і саме з ним вони мусять збігатись.
    """
    from nyshporka.core import sections as S

    screens = set(S.SCREENS)
    glyphs = set(B.active().screen_glyphs)
    assert screens == glyphs, (
        f"екрани без знака: {sorted(screens - glyphs)}; "
        f"знаки без екрана: {sorted(glyphs - screens)}")


def test_every_referenced_asset_exists() -> None:
    """Кожен асет, на який посилається поверхня, лежить на диску.

    ⚠ Биту картинку в шапці помічають не одразу: у розробника вона в кеші, а
    зникає вона в того, хто відкрив застосунок уперше.
    """
    surfaces = [
        ROOT / "src" / "nyshporka" / "daemon" / "static" / "index.html",
        ROOT / "src" / "nyshporka" / "daemon" / "static" / "app.css",
    ]
    missing = []
    for path in surfaces:
        for name in re.findall(r"/brand/([\w.-]+)", path.read_text(encoding="utf-8")):
            if not (B.ASSETS / name).exists():
                missing.append(f"{path.name} → {name}")
    assert not missing, f"посилання на асети, яких немає: {missing}"


def test_build_patterns_reach_into_subfolders() -> None:
    """🔴 Патерни збірки мусять переходити через `/`.

    `artifacts` має gitignore-семантику, де ОДНА зірочка через `/` не
    переходить. `daemon/static/*` уже стояв саме так — і перша ж підтека
    фронту тихо не потрапила б у колесо: локально й у тестах усе працює,
    ламається рівно в користувача, у якого немає репозиторію під рукою.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("artifacts = "))
    lone = re.findall(r'"([^"]*/\*)"', line)
    assert not lone, f"патерн не переходить через «/»: {lone}"


def test_readme_images_are_absolute() -> None:
    """🔴 Картинки в README — абсолютними URL.

    ⚠ README їде в метадані колеса й стає сторінкою пакета. Відносний шлях там
    нікуди не веде: у репозиторії картинка є, на PyPI на її місці — битий
    значок, і побачить його рівно той, хто прийшов подивитись, що це взагалі
    таке.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    relative = [src for src in re.findall(r'src="([^"]+)"', text)
                if not src.startswith("http")]
    relative += [src for src in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
                 if not src.startswith("http")]
    assert not relative, f"відносні шляхи в README: {relative}"


def test_readme_engine_table_matches_the_source() -> None:
    """Таблиця рушіїв у README не розійшлася з `brand.yaml`.

    Таблиця переписана руками — інакше й не буває в README, — тож ловити
    розходження мусить тест. Розходиться воно тихо: у застосунку бейдж один, на
    сторінці пакета інший, і повірять радше сторінці.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for e in B.active().engines_ordered():
        letter = f"`[{e.letter_uk}]`"
        assert letter in text, f"у README немає бейджа {letter} ({e.id})"


def test_mascot_never_reports_a_verdict() -> None:
    """🔴 Знак показує процес, а не висновок.

    Стан «шукає» дозволений; станів «знайшов» і «не знайшов» бути не може.
    Картинка, яка каже «нічого немає», бреше саме там, де хибне «немає»
    закриває напрям пошуку назавжди — а нуль без знаменника взагалі не
    результат. Тест тримає межу в CSS і в скрипті фронту.
    """
    static = ROOT / "src" / "nyshporka" / "daemon" / "static"
    forbidden = ("mark.found", "mark.empty", "mark.sad", "paw-found",
                 "paw-empty", "paw-sad", "is-found", "is-empty")
    hits = []
    for name in ("app.css", "app.js"):
        text = (static / name).read_text(encoding="utf-8")
        hits += [f"{name}: {token}" for token in forbidden if token in text]
    assert not hits, f"знак повідомляє результат замість тексту: {hits}"


def test_installers_print_the_same_paw() -> None:
    """🐾 Інсталятор показує ТОЙ САМИЙ знак, що й застосунок.

    Це найперша поверхня, яку бачить людина: власна лапка тут означала б, що
    бренд розходиться з першого ж екрана. Звіряється побайтово з `brand.PAW` —
    тим, що друкує `nysh info` і старт `nysh serve`.
    """
    from nyshporka.brand.console import PAW

    for name in ("unix.sh", "windows.ps1"):
        text = (ROOT / "install" / name).read_text(encoding="utf-8-sig")
        for row in PAW.splitlines():
            assert row in text, f"{name}: немає рядка знака «{row}»"
        assert "Читає рукопис" in text, f"{name}: немає лінії бренду"


def test_windows_installer_is_utf8_with_bom() -> None:
    """🔴 `windows.ps1` мусить лежати з BOM.

    Команда з README — `powershell -File install/windows.ps1`, тобто Windows
    PowerShell 5.1. Файл БЕЗ BOM він читає системною кодовою сторінкою, і вся
    кирилиця в інсталяторі перетворюється на кракозябри — на першій поверхні,
    яку бачить україномовний користувач, і ще до того, як щось встигло
    зламатись по-справжньому.
    """
    raw = (ROOT / "install" / "windows.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "windows.ps1 без UTF-8 BOM"
    assert "OutputEncoding" in raw.decode("utf-8-sig"), (
        "кодування консолі не виставлене — вивід лишиться в системній сторінці")
