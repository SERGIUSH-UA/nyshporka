"""🎨 Спільний шар: усе, що дві морди беруть з одного місця, мусить зійтися.

Тут перевіряються стики — місця, де дані з `brand.yaml`, розмітка спрайта, JS і
CSS мусять збігтися ІМЕНАМИ. Кожен такий стик ламається мовчки:

* `<use>` на неіснуючий символ не дає ні помилки, ні попередження — просто
  порожнє місце там, де мав бути значок;
* бейдж рушія без правила форми лишається квадратом, тобто втрачає одну з трьох
  ознак, заради яких його заведено;
* літера, що розійшлася з `brand.yaml`, називає той самий рушій по-різному в
  двох вікнах — і саме тоді, коли колір недоступний і перевірити нічим.

🔴 Тому приймач звіряє МНОЖИНИ ІМЕН, а не вигляд: вигляд довелося б відкривати
браузером, а браузера в CI немає.
"""
from __future__ import annotations

import re

from nyshporka import ui
from nyshporka.brand import active

SPRITE = ui.sprite()
ICONS_JS = (ui.static_dir() / "icons.js").read_text(encoding="utf-8")
BASE_CSS = (ui.static_dir() / "base.css").read_text(encoding="utf-8")
INDEX = (ui.ROOT.parent / "daemon" / "static" / "index.html").read_text(encoding="utf-8")

#: Символи, які справді є у спрайті.
SYMBOLS = set(re.findall(r'<symbol id="i-([\w-]+)"', SPRITE))


def test_sprite_is_not_empty() -> None:
    """Порожній спрайт дав би сторінку без жодного значка — і без помилки."""
    assert len(SYMBOLS) > 50, f"у спрайті лише {len(SYMBOLS)} символів"


def test_every_toned_icon_exists_in_the_sprite() -> None:
    """Мапа тонів не сміє називати символів, яких немає.

    ⚠ Помилка друку тут не падає, а тихо дає порожнє місце: `<use>` на
    неіснуючий id мовчить. Тобто без цього приймача дефект виявляють очима, і
    лише якщо випадково відкриють ту вкладку.
    """
    named = set(re.findall(r"^\s*'?([\w-]+)'?\s*:\s*'\w+',", ICONS_JS, re.M))
    # У файлі є й інші об'єкти (`ENGINES`), тож беремо перетин із відомим
    # словником тонів, а не всі пари поспіль.
    tones = set(re.findall(r"[\s{,]'?([\w-]+)'?: '(?:gold|amber|orange|red|pink|violet"
                           r"|indigo|blue|sky|cyan|teal|green|mint|lime|sand|slate)'",
                           ICONS_JS))
    assert tones, "мапу тонів не розібрано — змінилась форма запису?"
    missing = sorted(tones - SYMBOLS)
    assert not missing, f"тон заданий значкам, яких немає у спрайті: {missing}"
    assert named  # словник узагалі розібрався


def test_navigation_icons_exist_in_the_sprite() -> None:
    """Знаки екранів і розділів із `brand.yaml` мусять існувати.

    Доданий екран без значка виглядав би зламаною кнопкою поряд з оформленими,
    а зайвий запис лишався б мертвим рядком у даних.
    """
    b = active()
    want = set(b.screen_icons.values()) | set(b.section_icons.values())
    missing = sorted(want - SYMBOLS)
    assert not missing, f"у brand.yaml названо значки, яких немає у спрайті: {missing}"


def test_engine_badges_match_the_manifest() -> None:
    """🔴 Літера й форма бейджа — ті самі, що в `brand.yaml`.

    Літера тут носій, а не прикраса: колір зникає при `NO_COLOR`, у чорно-білому
    логу й на друкованому скріншоті, а розрізняти рушії треба саме там. Форма —
    другий носій, для дальтонізму.
    """
    for e in active().engines_ordered():
        block = re.search(rf"{e.id}:\s*{{(.*?)}},", ICONS_JS, re.S)
        assert block, f"у icons.js немає бейджа «{e.id}»"
        body = block.group(1)
        letter = re.search(r"letter:\s*'([^']+)'", body)
        shape = re.search(r"shape:\s*'([^']+)'", body)
        assert letter and shape, f"бейдж «{e.id}» неповний"
        assert letter.group(1) == e.letter_uk, (
            f"«{e.id}»: у вікні «{letter.group(1)}», у brand.yaml «{e.letter_uk}»")
        assert shape.group(1) == e.shape, (
            f"«{e.id}»: форма «{shape.group(1)}» проти «{e.shape}» у brand.yaml")


def test_every_engine_shape_has_a_css_rule() -> None:
    """Форма без правила лишає бейдж квадратом — тобто без однієї з трьох ознак."""
    missing = [e.shape for e in active().engines_ordered()
               if f'[data-shape="{e.shape}"]' not in BASE_CSS]
    assert not missing, f"немає правил форми: {sorted(set(missing))}"


def test_page_asks_for_the_sprite() -> None:
    """Сторінка мусить мати місце, куди сервер кладе спрайт.

    ⚠ `with_sprite` мовчить, якщо плейсхолдера немає: падати через косметику не
    можна. Отже без цього приймача пропалий `{{SPRITE}}` виявився б лише як
    сторінка геть без значків.
    """
    assert ui.SPRITE_SLOT in INDEX, "у index.html немає місця під спрайт"


def test_page_loads_the_shared_layer_in_order() -> None:
    """Токени → примітиви → своє.

    Зворотний порядок лишив би перший кадр без кольорів, а власні правила — без
    змоги перебити базові, не піднімаючи специфічність.
    """
    order = [INDEX.index(x) for x in
             ("/ui/tokens.css", "/ui/base.css", "/static/app.css")]
    assert order == sorted(order), "порядок підключення стилів переплутано"


def test_theme_is_set_before_the_first_paint() -> None:
    """Вибір теми мусить діяти ДО малювання сторінки.

    Модуль `theme.js` виконується вже після парсингу `<head>`, тобто після
    першого кадру — при світлому виборі людина побачила б спалах темного. Дубль
    логіки в `<head>` свідомий, і ключ у ньому мусить збігатися з модулем.
    """
    key = re.search(r"THEME_KEY\s*=\s*'([^']+)'",
                    (ui.static_dir() / "theme.js").read_text(encoding="utf-8"))
    assert key, "у theme.js немає ключа теми"
    head = INDEX[:INDEX.index("</head>")]
    assert key.group(1) in head, (
        f"інлайн-скрипт у <head> не знає ключа «{key.group(1)}» — "
        "перший кадр буде іншої теми")


def test_every_long_op_can_actually_start() -> None:
    """🔴 Операція, помічена `long`, мусить мати вхід, а не глухий кут.

    ⚠ Так уже було з `registry.collect` і `registry.merge`: у переліку `/api/ops`
    вони стояли, кнопка малювалась, а виклик відмовляв 400 «не має виконавця».
    Дефект тут не в тому, що робота не зроблена, — а в тому, що вхід у неї веде
    в нікуди, і видно це лише натиснувши.

    Приймач звіряє намір із диспетчером: або в нього є гілка під цю операцію,
    або спрацьовує загальний виконавець, який виконує тіло операції в потоці.
    """
    import inspect

    from nyshporka import ops as O
    from nyshporka.daemon import workers

    src = inspect.getsource(workers.start)
    assert "_start_generic" in src, (
        "у диспетчера немає загального виконавця — кожна нова довга операція "
        "знову відповідатиме «не має виконавця»")
    for op in O.all_ops():
        if not op.long:
            continue
        # Тіло потрібне саме для загального шляху: без нього робота стала б у
        # чергу й одразу впала.
        assert callable(op.fn), f"довга операція «{op.name}» не має тіла"
