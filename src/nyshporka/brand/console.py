"""🐾 Командний рядок в айдентиці — спільний `Console` і тема з `brand.yaml`.

🔴 Console у пакеті один. Досі їх було п'ять, створених незалежно в `cli`,
`cases.cli`, `matching.review`, `pagestore.cli` і `fonds.cli`, — тобто
«однаковий вигляд» тримався на тому, чи згадає наступний автор скопіювати
аргументи. Один із п'яти вже розійшовся: лише `cases.cli` знав, що при
перенаправленні виводу ширину треба задати вручну, інакше таблиці ламаються об
стандартні 80 колонок. Тут це правило стало спільним.

⚠ JSON через `Console` не друкується — ні тут, ні в командах. Rich переносить
довгі рядки й підсвічує вивід, тож машинний формат він тихо псує; для нього в
командах стоїть `typer.echo`, і так має лишитись.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache

from rich.console import Console
from rich.theme import Theme

from nyshporka.brand.manifest import active

#: Змінна, якою вибирають половину палітри для терміналу.
#:
#: 🔴 Термінал не вміє сказати, який у нього фон, і надійного способу спитати
#: немає. Тому береться темна половина: переважна більшість терміналів темні, а
#: її кольори світліші й на білому тлі лишаються розбірливими (гірше за свої,
#: але читабельно). Зворотний вибір давав би на темному тлі темно-синій текст,
#: тобто нечитабельний.
#:
#: Хто хоче точно — `NYSH_THEME=light`. Але це прикраса, а не умова роботи:
#: носієм розрізнення рушіїв лишається літера, і при `NO_COLOR` вивід
#: залишається повним.
ENV_THEME = "NYSH_THEME"


def theme_name() -> str:
    want = (os.environ.get(ENV_THEME) or "").strip().lower()
    return want if want in ("light", "dark") else "dark"


def _for_rich(value: str) -> str | None:
    """Колір у формі, яку розуміє rich, — або порожньо, якщо не розуміє взагалі.

    ⚠ CSS приймає тришестнадцяткову форму, rich — ні: `Style.parse("#9ab")`
    падає `StyleSyntaxError`, і падає воно на імпорті `nyshporka.cli`, тобто
    валить геть усе, а не лише кольоровий вивід. У палітрі таких записів
    десятки (`#eee`, `#111`, `#222`), бо коротка форма — норма для верстки.

    🔴 Але коротким hex палітра не вичерпується. У ній є `#e040fb66` (колір із
    альфою), `rgba(28,28,28,.92)` і `transparent` — жодного з них rich не
    розбирає, а прозорості в терміналі не існує в принципі. Тому такий токен
    відкидається, а не підсовується як є: інакше перший семантичний стиль,
    наведений на нього, поклав би командний рядок цілком — рівно та відмова,
    заради якої ця функція й написана.

    🔴 Перетворення живе тут, а не в `brand.yaml`. Це не два різні значення, а
    один колір у формі, яку розуміє конкретний споживач, — рівно те саме, що
    робить `render_docs`, перекладаючи наші імена в материалівські.
    """
    v = value.strip()
    if len(v) == 4 and v.startswith("#"):
        return "#" + "".join(c * 2 for c in v[1:])
    if len(v) == 7 and v.startswith("#"):
        return v
    return None


def theme() -> Theme:
    """Іменовані стилі rich, зібрані з палітри.

    ⚠ Стиль, чий токен терміналу не по зубах (альфа, `rgba`, `transparent`),
    просто не оголошується. Rich на невідоме ім'я стилю не падає — він друкує
    текст без оформлення, а це саме та деградація, якої тут хочеться: втратити
    колір дешево, втратити командний рядок — ні.
    """
    b = active()
    raw = b.css_vars(theme_name())
    v = {k: c for k, c in ((k, _for_rich(x)) for k, x in raw.items()) if c}
    # 🔴 Імена семантичні, а не кольорові. Код друкує `[err]`, а не `[red]`:
    # інакше палітра лишається описом, якого ніхто не читає, — саме так у
    # пакеті й було, 236 кольорових літералів повз тему.
    want = {
        "muted": "muted",
        "accent": "accent",
        "warn": "warn-fg",
        "err": "err",
        "ok": "ok",
    }
    styles = {name: v[token] for name, token in want.items() if token in v}
    if "accent" in v:
        styles["brand"] = f"bold {v['accent']}"
    for e in b.engines_ordered():
        tone = v.get(f"engine-{e.id}")
        if tone:
            styles[f"engine.{e.id}"] = f"bold {tone}"
    return Theme(styles)


@lru_cache(maxsize=2)
def _make(stderr: bool) -> Console:
    # ⚠ Ширина при перенаправленні. Rich за замовчуванням бере 80 колонок для
    # не-термінала, і таблиці справ (шифр + заголовок + роки + аркуші) від
    # цього ламаються посеред слова — саме в тому виводі, який зберігають у
    # файл або читає агент.
    stream = sys.stderr if stderr else sys.stdout
    width = None if stream.isatty() else 150
    return Console(theme=theme(), stderr=stderr, width=width)


def console() -> Console:
    """Спільний вивід. `NO_COLOR` і не-термінал rich обробляє сам."""
    return _make(False)


def err() -> Console:
    return _make(True)


def mark(mid: str) -> str:
    """Позначка зі спільного словника: `mark("rule")` → 🔴."""
    return active().mark(mid).glyph


def engine_tag(engine_id: str, lang: str = "uk") -> str:
    """Бейдж рушія розміткою rich: `[П]` його кольором.

    🔴 Літера в дужках — не прикраса при кольорі, а носій. Вивід читають у
    чорно-білому терміналі, у логах і з `NO_COLOR`; там колір зникає цілком, а
    рушій мусить лишитись упізнаваним.
    """
    style = active().engine(engine_id)
    if style is None:
        return f"[{engine_id}]"
    # `\[` екранує квадратну дужку для rich: без цього розмітка з'їла б бейдж.
    return rf"[engine.{style.id}]\[{style.letter(lang)}][/]"


def engine_label(engine_id: str, name: str, lang: str = "uk") -> str:
    """Бейдж плюс ім'я: `[П] Писар`."""
    return f"{engine_tag(engine_id, lang)} {name}"


#: Знак у трьох рядках: чотири подушечки й основна з лупою.
#: Друкується тільки в `nysh info` і `--version`. У робочих командах його
#: немає: їхній вивід читає агент, і три рядки прикраси перед кожною відповіддю
#: коштували б контексту на кожному виклику.
PAW = r"""  ● ● ● ●
  ╭─ ◍ ─╮
  ╰─────╯"""


def banner(version: str, lang: str = "uk") -> str:
    """Знак, назва, версія й лінія бренду — розміткою rich."""
    b = active()
    right = (
        "",
        f"[brand]{b.name(lang)}[/] [muted]{version}[/]",
        f"[muted]{b.line(lang)}[/]",
    )
    rows = [
        f"[accent]{left}[/]   {text}".rstrip()
        for left, text in zip(PAW.splitlines(), right, strict=True)
    ]
    return "\n".join(rows)
