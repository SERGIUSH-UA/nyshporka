"""🌐 Веб-стек бренду і шрифти застосунку.

Портал Супряги живе в іншому репозиторії й бере палітру звідси — імпортом
пакета, а не копією CSS. Копія тут уже коштувала один раз: `#7a4f2b` лежав
переписаним вручну, і три поверхні розійшлися тихо.

Застосунок набирається тими самими родинами, що й портал, і приймач стереже
дві межі:

* кожну родину, названу в токенах застосунку, роздає САМ ПАКЕТ (`fonts.css` +
  файли поруч): у читальній залі мережі може не бути, а шрифт, який не
  приїхав, дає стрибок верстки саме там, де людина читає скан;
* різновид `web` **перевизначає** ті самі імена токенів, а не заводить другі.
"""
from __future__ import annotations

import re
from pathlib import Path

from nyshporka.brand import gen as GEN
from nyshporka.brand import manifest as M

UI = Path(GEN.repo_root()) / "src" / "nyshporka" / "ui" / "static"


def _families(stack: str) -> list[str]:
    return re.findall(r'"([^"]+)"', stack)


def test_app_fonts_come_from_the_package_not_the_network() -> None:
    """🔴 Названа в токенах родина мусить бути оголошена в `fonts.css`, а її
    файли — лежати в пакеті. Інакше браузер мовчки бере запасний стек, і
    застосунок «наче на шрифтах порталу» виглядає інакше без жодної помилки.
    """
    brand = M.active()
    css = (UI / "fonts.css").read_text(encoding="utf-8")
    assert "http" not in css, "шрифт із мережі — офлайн у читальній залі його не буде"
    declared = set(re.findall(r'font-family:\s*"([^"]+)"', css))
    for stack in (brand.type_text, brand.type_mono, brand.type_serif):
        for fam in _families(stack):
            if fam in ("Segoe UI", "Times New Roman"):
                continue
            assert fam in declared, f"«{fam}» названа в токенах, але не оголошена в fonts.css"
    for src in re.findall(r'url\("([^"]+)"\)', css):
        assert (UI / src).is_file(), f"fonts.css посилається на відсутній файл {src}"


def test_every_app_stack_keeps_a_system_fallback() -> None:
    """Запас у стеку лишається: без нього недоїхалий файл дав би Times."""
    brand = M.active()
    assert "system-ui" in brand.type_text
    assert "ui-monospace" in brand.type_mono
    assert brand.type_serif.rstrip().endswith("serif")


def test_pages_load_the_fonts_before_the_tokens() -> None:
    """Обидві сторінки застосунку підключають `fonts.css` — інакше родини в
    токенах лишаються іменами без файлів."""
    static = UI.parent.parent / "daemon" / "static"
    for page in ("index.html", "access.html"):
        html = (static / page).read_text(encoding="utf-8")
        assert html.index("/ui/fonts.css") < html.index("/ui/tokens.css"), page


def test_web_flavour_only_appends() -> None:
    """Різновид `web` — це `app` плюс хвіст, а не окрема система.

    Якби він збирався сам, палітра існувала б двома складаннями, і розійтись
    вони могли б лише тихо: обидва віддають валідний CSS.
    """
    assert GEN.render("web").startswith(GEN.render("app"))


def test_web_redefines_names_instead_of_adding_new_ones() -> None:
    """🔴 Ті самі імена, не другий набір.

    `--font-text`, `--font-mono` і `--font-serif` приходять повторно — саме
    тому, що вся наявна верстка звертається до них.
    """
    web = GEN.render("web")
    tail = web[len(GEN.render("app")):]

    assert "--font-text:" in tail, "інтерфейсний стек сайту не перекрито"
    assert "--font-mono:" in tail, "моноширинний стек сайту не перекрито"
    assert "--font-serif:" in tail, "засічкової ролі немає"

    brand = M.active()
    assert brand.web_sans in tail
    assert brand.web_mono in tail
    assert brand.web_serif in tail


def test_web_is_not_generated_into_this_repository() -> None:
    """🔴 У переліку цілей різновиду немає — і це навмисно.

    Файл тут нікому не потрібен: його споживач ставить пакет піном на коміт і
    кличе функцію. Записаний у `targets()`, він завів би в цьому репозиторії
    мертвий CSS, який ніхто не читає, зате `--check` вимагав би тримати свіжим.
    """
    assert "web" not in GEN.targets().values()


def test_web_survives_a_brand_without_the_block() -> None:
    """Порожній `type.web` — не помилка, а «сайту тут немає».

    Генератор мусить віддати рівно токени застосунку: падіння на збірці
    коштувало б розгортання, а підстановка вигаданого стека — тихо неправильного
    вигляду.
    """
    brand = M.active()
    bare = type(brand)(**{**brand.__dict__, "web_serif": "", "web_sans": "",
                          "web_mono": "", "web_size": "", "web_leading": ""})
    assert GEN.render_web(bare) == GEN.render_app(bare)


def test_web_type_is_read_for_the_page_not_the_workbench() -> None:
    """⚠ Кегль сайту більший за кегль верстата, і це вибір, а не недогляд.

    Застосунок — щільна панель на весь екран; сайт читають у браузері з типовим
    масштабом, де 15px воює з усталеним 16.
    """
    brand = M.active()
    assert brand.type_size == "15px"
    assert brand.web_size == "16px"
