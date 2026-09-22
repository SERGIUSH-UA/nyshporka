"""🌐 Веб-стек бренду: окремий блок, який НЕ ламає офлайнового застосунку.

Портал Супряги живе в іншому репозиторії й бере палітру звідси — імпортом
пакета, а не копією CSS. Копія тут уже коштувала один раз: `#7a4f2b` лежав
переписаним вручну, і три поверхні розійшлися тихо.

Тому приймач стереже рівно дві межі:

* різновид `web` **не змінює** нічого для застосунку — `type.text` і `type.mono`
  лишаються системними, бо в читальній залі мережі може не бути;
* і при цьому він **перевизначає** ті самі імена токенів, а не заводить другі:
  інакше верстка, написана під застосунок, на сайті мовчки діставала б
  системний стек.
"""
from __future__ import annotations

from nyshporka.brand import gen as GEN
from nyshporka.brand import manifest as M


def test_web_stack_does_not_touch_the_offline_app() -> None:
    """🔴 Застосунок лишається на системних стеках.

    Це головна причина, чому веб оформлено окремим блоком, а не правкою
    наявного: шрифт, який не приїхав, дає стрибок верстки саме там, де людина
    читає скан.
    """
    brand = M.active()
    assert "system-ui" in brand.type_text
    assert "ui-monospace" in brand.type_mono
    assert "Literata" not in brand.type_text
    assert "IBM Plex" not in brand.type_text

    app = GEN.render("app")
    assert "Literata" not in app, "веб-шрифт протік у токени застосунку"
    assert "IBM Plex" not in app


def test_web_flavour_only_appends() -> None:
    """Різновид `web` — це `app` плюс хвіст, а не окрема система.

    Якби він збирався сам, палітра існувала б двома складаннями, і розійтись
    вони могли б лише тихо: обидва віддають валідний CSS.
    """
    assert GEN.render("web").startswith(GEN.render("app"))


def test_web_redefines_names_instead_of_adding_new_ones() -> None:
    """🔴 Ті самі імена, не другий набір.

    `--font-text` і `--font-mono` мусять прийти повторно — саме тому, що вся
    наявна верстка звертається до них. `--font-serif` навпаки новий: у
    застосунку засічкової ролі немає взагалі.
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
