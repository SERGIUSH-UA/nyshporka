"""🎨 Спільний шар: усе, що дві морди беруть з одного місця, мусить зійтися.

Тут перевіряються стики — місця, де дані з `brand.yaml`, розмітка спрайта, JS і
CSS мусять збігтися іменами. Кожен такий стик ламається мовчки:

* `<use>` на неіснуючий символ не дає ні помилки, ні попередження — просто
  порожнє місце там, де мав бути значок;
* бейдж рушія без правила форми лишається квадратом, тобто втрачає одну з трьох
  ознак, заради яких його заведено;
* літера, що розійшлася з `brand.yaml`, називає той самий рушій по-різному в
  двох вікнах — і саме тоді, коли колір недоступний і перевірити нічим.

🔴 Тому приймач звіряє множини імен, а не вигляд: вигляд довелося б відкривати
браузером, а браузера в CI немає.
"""
from __future__ import annotations

import re

from _front import front_js

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
    """Вибір теми мусить діяти до малювання сторінки.

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


def test_hotkeys_call_actions_that_exist() -> None:
    """⚠ Клавіша, прив'язана до знятої дії, мовчить.

    Кнопку, що зникла, видно; клавішу — ні: вона просто перестає працювати, і
    з'ясовується це тоді, коли на неї вже звикли покладатись. Тому прив'язки
    звіряються з реєстром дій так само, як `data-act` у розмітці.

    Заразом — екрани: клавіші, приписані екранові, якого немає в навігації,
    лишились би від колишньої розкладки й нічим себе не виказували.
    """
    # 🔴 Склейка всіх модулів фронту: сам роутер клавіш лишився у вході, а дії
    # й порядок навігації переїхали в модулі. Читаючи один файл, ця перевірка
    # не бачила б жодної оголошеної дії — і впала б на кожній клавіші.
    app = front_js()
    block = re.search(r"const KEYS = \{(.*?)\n\};", app, re.S)
    assert block, "роутер клавіш не знайдено — змінилась форма запису?"
    called = set(re.findall(r"ACTIONS\['([\w.]+)'\]", block.group(1)))
    declared = set(re.findall(r"^  '?([\w.]+)'?:\s*(?:async\s*)?\(", app, re.M))
    missing = sorted(called - declared)
    assert not missing, f"клавіші кличуть дії, яких немає: {missing}"

    screens = set(re.findall(r"^  (\w+): \{", block.group(1), re.M))
    order = re.search(r"const NAV_ORDER = \[(.*?)\];", app, re.S)
    known = set(re.findall(r"'(\w+)'", order.group(1)))
    stray = sorted(screens - known)
    assert not stray, f"клавіші приписані екранам поза навігацією: {stray}"


def test_forms_only_react_to_submit() -> None:
    """🔴 Дія форми не сміє спрацьовувати від події поля всередині неї.

    ⚠ Це вже ламало все. Слухач `change` на документі знаходив через
    `closest('[data-act]')` саме форму, а `ev.target` лишався полем — і кожна
    дія форми, яка робить `new FormData(ev.target)`, падала
    `TypeError: parameter 1 is not of type 'HTMLFormElement'`. Досить було
    вибрати пункт у будь-якому `<select>` на Газетирі, Пошуку, Фондах.

    Гірший бік тієї ж вади був давніший і тихіший: клік по чекбоксу всередині
    форми діставав `ev.preventDefault()` від її дії, і браузер скасовував
    перемикання — галочку «узяти теку під облік» неможливо було поставити
    взагалі, і виглядало це як мертвий чекбокс, а не як помилка.
    """
    # Сам диспетчер лишився у вході, а форми переїхали в модулі екранів — тож
    # другий бік межі (`new FormData(…)`) шукається по склейці всього фронту.
    app = front_js()
    guard = re.search(r"function dispatch\(ev\)\s*\{(.*?)\n\}", app, re.S)
    assert guard, "диспетчер не знайдено"
    body = guard.group(1)
    assert "ev.type !== 'submit'" in body and "'FORM'" in body, (
        "у диспетчері немає межі «форма реагує лише на submit» — подія з поля "
        "знову покличе дію форми з чужим `ev.target`")

    # Другий бік тієї самої межі: дія форми мусить брати дані з `ev.target`
    # лише там, де подія справді `submit`.
    for m in re.finditer(r"new FormData\((\w+(?:\.\w+)*)\)", app):
        assert m.group(1) in ("ev.target", "elm"), (
            f"FormData зібрано з «{m.group(1)}» — джерело має бути формою")


# ── бейдж рушія: ідентичність, а не вид ──────────────────────────────────────
def test_engine_badge_is_built_from_the_model_identity() -> None:
    """🔴🔴 Бейдж робиться з `engine_id`, а не з `engine`. Це різні поняття.

    `engine` — вид рушія (`kraken` · `parseq`): ним боронять теки від
    змішування. `engine_id` — ідентичність моделі (`pysar` · `diak` ·
    `skryba`), і саме нею ключована таблиця бейджів. Одного виду замало навіть
    для показу: `kraken` буває двох письм — латинський Скриба й кириличний
    Дяк, — і бейдж із виду назвав би їх однаково рівно там, де різниця
    вирішує.

    ⚠ Вада, від якої стоїть цей приймач, була живою й абсолютно мовчазною:
    розбір знахідок передавав у `eng()` поле `engine`, збігу з таблицею не було
    ніколи, а `<use>` на неіснуючий символ не помиляється — бейдж просто не
    з'являвся жодного разу, і виглядало це як «тут нічого не показують».
    """
    js = front_js()
    calls = set(re.findall(r"\beng\(\s*([\w.]+)", js))
    bad = sorted(c for c in calls
                 if c.endswith(".engine") or re.fullmatch(r"engine", c))
    assert not bad, (
        f"бейдж робиться з виду рушія, а не з ідентичності моделі: {bad}. "
        "Таблиця бейджів ключована `pysar`/`diak`/`skryba`, тож збігу не буде "
        "й значок мовчки не з'явиться")
    assert calls, "жодного виклику бейджа — перевірка втратила сенс"


def test_engine_ids_the_store_hands_out_have_badges() -> None:
    """Ідентичності з прогонів мусять існувати в таблиці бейджів.

    Інакше маємо ту саму тишу з іншого боку: сховище віддає `engine_id`, якого
    вікно не знає, і замість позначки лишається порожнє місце.
    """
    from nyshporka.htr import manifest as M

    known = set(re.findall(r"^  (\w+): \{", ICONS_JS, re.M))
    for e in M.active().engines:
        assert e.id in known, (
            f"рушій «{e.id}» є в маніфесті, а бейджа для нього немає")


def test_every_icon_call_names_a_real_symbol() -> None:
    """🔴 `ic()` сам додає префікс `i-`, тож `ic('i-alert')` дає `#i-i-alert`.

    `<use>` на неіснуючий id не кидає помилки й не пише в консоль — значок
    просто зникає. Саме так одного разу пропало вісім значків у газетирі, і
    помітили це очима, а не перевіркою.
    """
    used = set(re.findall(r"\bic\('([\w-]+)'", front_js()))
    assert used, "жодного виклику значка — перевірка втратила сенс"
    missing = sorted(used - SYMBOLS)
    assert not missing, (
        f"ic() кличе символи, яких немає у спрайті: {missing}. "
        "Префікс `i-` додається всередині — передавайте голе ім'я")
