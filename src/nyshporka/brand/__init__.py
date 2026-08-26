"""🐾 Айдентика Нишпорки — одне джерело на всі поверхні.

Нишпорка — кіт, який приносить знайдене з архіву: лапка це слід у справі, лупа
в подушечці — те, що вона робить.

Тут лежать дані бренду й функції над ними; поверхні (фронт, командний рядок,
сайт документації, README) беруть їх звідси й через це не можуть розійтись.

    brand.yaml      палітра, типографіка, позначки, стилі рушіїв, знаки секцій
    manifest.py     розбір і питання до нього
    color.py        контраст і тон — арифметика для тестів
    css.py          brand.yaml → tokens.css і docs/stylesheets/brand.css
    console.py      brand.yaml → тема rich і спільний Console
    data/assets/    знак, favicon, бейджі рушіїв

🔴 Дві межі, які тримають усе решта:

* **знак не повідомляє результат замість тексту.** Стани знака описують процес
  (спокій · шукає · готово), а не висновок. «Сумного кота» на порожній видачі
  бути не може: нуль без знаменника — не результат, а картинка, яка каже
  «нічого немає», хибна рівно там, де хибне «немає» закриває напрям пошуку;
* **колір — прискорювач, а не носій.** Рушій розрізняється ще формою й
  літерою, бо вивід читають у чорно-білому терміналі, у логах і з
  дальтонізмом.
"""
from nyshporka.brand.console import (
    banner,
    console,
    engine_label,
    engine_tag,
    err,
    mark,
    theme,
)
from nyshporka.brand.manifest import (
    ASSETS,
    BUILTIN,
    THEMES,
    Brand,
    Color,
    EngineStyle,
    Mark,
    active,
    asset,
    load,
)

__all__ = [
    "ASSETS",
    "BUILTIN",
    "THEMES",
    "Brand",
    "Color",
    "EngineStyle",
    "Mark",
    "active",
    "asset",
    "banner",
    "console",
    "engine_label",
    "engine_tag",
    "err",
    "load",
    "mark",
    "theme",
]
