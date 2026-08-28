"""🐾 `brand.yaml` → файли. Генератор, а не набір стилів.

Три споживачі беруть ті самі токени й через це не можуть розійтися:

    ui/static/tokens.css         спільний шар обох морд (`nysh serve` і консоль)
    docs/stylesheets/brand.css   сайт документації (MkDocs Material)
    brand/data/assets/*.svg      знак, фавіконка, бейджі рушіїв

🔴 Усі згенеровані файли руками не правляться. Правка робиться в `brand.yaml`,
після чого:

    uv run python -m nyshporka.brand.gen          # переписати
    uv run python -m nyshporka.brand.gen --check  # чи не протухли (це і в CI)

Чому не збирати CSS у застосунку на льоту: сайт документації збирається
MkDocs'ом, який про наш пакет нічого не знає, а `tokens.css` мусить лежати
файлом, щоб потрапити в колесо. Генерація в репозиторій — єдиний спосіб мати
одне джерело для обох.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from nyshporka.brand import paw
from nyshporka.brand.manifest import THEMES, Brand, Color, active

#: Шапка згенерованого файлу. Стоїть першою й каже, куди йти зі змінами:
#: без неї правка неминуче робиться в CSS, живе до наступного прогону
#: генератора й зникає без сліду.
HEADER = """/* ⚠ згенеровано з `src/nyshporka/brand/data/brand.yaml` — руками не правити.
   Правка тут живе рівно до наступного `python -m nyshporka.brand.gen`.
   Змінювати кольори — у brand.yaml; перевіряти — `--check` (він же в CI). */
"""

#: Ширина рядка-роздільника секції. Та сама, що в решті CSS проєкту.
_RULE = 78

#: Проза двох секцій, яких немає в `brand.yaml` як груп. Живе тут, а не в
#: даних, бо адресована тому, хто верстає: пояснює не бренд, а те, як цим
#: користуватись у CSS.
_ENGINES_NOTE = """Письмо задає родину: Писар і Дяк — сусідні холодні (два голоси одного
письма, їх і звіряють між собою), Скриба окремо — окреме письмо.
⚠ Колір тут прискорювач, а не носій: бейдж несе ще форму й літеру, бо
вивід читають і в чорно-білому, і з дальтонізмом."""

_ALIASES_NOTE = """🔴 Не другі кольори, а другі імена: `--card` каже, що це («підкладка
картки»), `--s-3` — який це щабель ярусу поверхонь. Тому аліас виходить
посиланням — перевернеться токен, перевернеться й він, і пари у світлому
блоці йому не треба."""


def _section(title: str, why: str = "", indent: str = "  ") -> str:
    """Заголовок секції коментарем — разом із прозою, якщо вона є."""
    dashes = "─" * max(3, _RULE - len(indent) - len(title) - 8)
    head = f"{indent}/* ── {title} {dashes}"
    lines = (why or "").splitlines()
    if not lines:
        return f"{head} */\n"
    body = [f"{indent}   {ln}".rstrip() for ln in lines]
    # `*/` дописується до останнього рядка прози, а не висить окремим: інакше
    # кожна секція коштує зайвого рядка, а їх тут два десятки.
    body[-1] += " */"
    return "\n".join([head, *body]) + "\n"


def _decls(rows: list[Color], theme: str, indent: str = "  ") -> list[str]:
    """Декларації однієї секції з хвостовими поясненнями У колонку.

    ⚠ Вирівнювання рахується по секції, а не по файлу: значення тут різної
    довжини (`#111` поруч із `cubic-bezier(.2,.7,.3,1)`), і спільна колонка на
    весь файл відсунула б половину пояснень за край екрана.
    """
    heads = [f"{indent}--{c.css}: {c.value(theme)};" for c in rows]
    width = max((len(h) for h, c in zip(heads, rows, strict=True) if c.why), default=0)
    return [f"{h.ljust(width)}   /* {c.why} */\n" if c.why else f"{h}\n"
            for h, c in zip(heads, rows, strict=True)]


def _theme_block(brand: Brand, theme: str, *, base: bool) -> str:
    """Тіло блока однієї теми.

    `base` — чи це базова тема. У базовій виходить усе; у перекритті лише те,
    що справді змінюється, бо повторений незмінний токен нічого не додає, зате
    ховає в шумі ті, що змінились.
    """
    out: list[str] = [f"  color-scheme: {theme};\n"]
    for g in brand.groups:
        cols = [c for c in g.colors if base or not c.same]
        if not cols:
            continue
        out.append("\n" + _section(g.title, g.why))
        out += _decls(cols, theme)

    out.append("\n" + _section("три голоси рушіїв", _ENGINES_NOTE))
    out += _decls([Color(css=f"engine-{e.id}", why=e.hue_uk, dark=e.dark, light=e.light)
                   for e in brand.engines_ordered()], theme)

    if base:
        out.append("\n" + _section("аліаси: друге ім'я того самого токена", _ALIASES_NOTE))
        # Аліас — посилання, а не значення, тож `_decls` тут не годиться:
        # у нього немає теми, і колонка рахується по власних рядках.
        heads = [f"  --{a.css}: var(--{a.of});" for a in brand.aliases]
        # ⚠ `default=0`: без нього порожній (або відсутній) розділ аліасів валить
        # генератор на `max() iterable argument is empty` — так само, як це вже
        # враховано в `_decls`.
        width = max((len(h) for h in heads), default=0)
        out += [f"{h.ljust(width)}   /* {a.why} */\n"
                for h, a in zip(heads, brand.aliases, strict=True)]

    if base:
        # 🔴 Тільки системні стеки. Жодного CDN і жодного зовнішнього шрифту:
        # застосунок працює офлайн — в архіві інтернету може не бути взагалі, а
        # шрифт, який не приїхав, дає стрибок верстки саме там, де читають скан.
        out.append("\n" + _section("типографіка"))
        out += _decls([
            Color(css="font-text", why="інтерфейс", dark=brand.type_text,
                  light=brand.type_text, same=True),
            Color(css="font-mono", why="шифри, декод, поля набору", dark=brand.type_mono,
                  light=brand.type_mono, same=True),
            Color(css="font-size", why="базовий кегль", dark=brand.type_size,
                  light=brand.type_size, same=True),
            Color(css="line-height", why="інтерліньяж", dark=brand.type_leading,
                  light=brand.type_leading, same=True),
        ], theme)

    for title, rows, themed in (
        ("контроли: значення, які кольором не є", brand.controls, True),
        ("радіуси", brand.radii, False),
        ("тіні", brand.shadows, True),
        ("рух: єдина крива на всю поверхню", brand.motion, False),
    ):
        if not rows or (not base and not themed):
            continue
        out.append("\n" + _section(title))
        out += _decls(list(rows), theme)
    return "".join(out)


def render_app(brand: Brand) -> str:
    """Токени спільного шару обох морд.

    🔴 Базова тема — темна, і вона в голому `:root`; світла перевизначає ті
    самі імена під `[data-theme="light"]`. Раніше було навпаки, і перевертання
    не косметичне: справу читають годинами, і полотно кольору паперу на весь
    екран стомлює рівно тоді, коли роботи найбільше.

    ⚠ Тема ставиться атрибутом, а не лише системною налаштованістю. Вибір
    користувача мусить переживати захід сонця, а `@media` цього не вміє:
    інакше о 20:00 ОС перемкнула б тему під людиною, яка щойно вибрала іншу.
    """
    # ⚠ Невідома тема інакше зникає тихо: `other` став би «dark», база
    # намалювалася б світлими значеннями під `color-scheme: <що завгодно>`, а
    # блок другої теми не з'явився б узагалі. Ні винятку, ні падіння `--check`.
    if brand.theme_default not in THEMES:
        raise ValueError(
            f"theme_default «{brand.theme_default}» невідома — очікується "
            f"одна з: {', '.join(THEMES)}")
    base = brand.theme_default
    other = "light" if base == "dark" else "dark"
    sel = f':root[data-theme="{other}"]'
    return "".join([
        HEADER,
        "\n:root {\n", _theme_block(brand, base, base=True), "}\n",
        "\n" + _section(f"{'світла' if other == 'light' else 'темна'} тема — "
                        "перевизначення тих самих імен, не окрема система",
                        "Ставиться атрибутом `data-theme` на <html>: інлайн-скрипт у <head>\n"
                        "плюс `theme.js`. Перевизначаються лише кольори — радіуси,\n"
                        "тривалості й криві однакові в обох темах за побудовою.",
                        indent=""),
        f"{sel} {{\n", _theme_block(brand, other, base=False), "}\n",
        "\n" + _section("менше руху — значить без руху, а не швидше", "", indent=""),
        "@media (prefers-reduced-motion: reduce) {\n"
        "  :root { " + " ".join(f"--{c.css}: 1ms;" for c in brand.motion
                                if c.css.startswith("dur-")) + " }\n"
        "  *, *::before, *::after {\n"
        "    animation-duration: 1ms !important;\n"
        "    animation-iteration-count: 1 !important;\n"
        "    transition-duration: 1ms !important;\n"
        "    scroll-behavior: auto !important;\n"
        "  }\n}\n",
        "\n" + _section("бейджі рушіїв: колір під `data-engine`; форма — у base.css",
                        "", indent=""),
        *[f'.engine[data-engine="{e.id}"] {{ --engine: var(--engine-{e.id}); }}\n'
          for e in brand.engines_ordered()],
    ])


def render_docs(brand: Brand) -> str:
    """Оформлення сайту документації.

    MkDocs Material має власні імена змінних, тож наші токени сюди
    перекладаються. Перекладаються лише ті, що справді керують виглядом
    сторінки; решта теми лишається материалівською — переписувати чужий
    дизайн цілком означало б підтримувати ще один.
    """
    def scheme(theme: str, selector: str) -> str:
        v = brand.css_vars(theme)
        md = {
            "md-primary-fg-color": v["accent"],
            "md-primary-bg-color": v["bg"],
            "md-accent-fg-color": v["accent"],
            "md-default-bg-color": v["bg"],
            "md-default-fg-color": v["fg"],
            "md-typeset-color": v["fg"],
            "md-typeset-a-color": v["accent"],
            "md-code-bg-color": v["card"],
            "md-footer-bg-color": v["card"],
        }
        rows = "".join(f"  --{k}: {x};\n" for k, x in md.items())
        rows += "".join(f"  --{k}: {x};\n" for k, x in v.items())
        return f"{selector} {{\n{rows}}}\n"

    return "".join([
        HEADER, "\n",
        scheme("light", '[data-md-color-scheme="default"]'), "\n",
        scheme("dark", '[data-md-color-scheme="slate"]'),
    ])


# ── бейджі рушіїв ────────────────────────────────────────────────────────────
# 🔴 Малюються генератором, а не руками. Бейдж несе колір, форму й літеру —
# три ознаки з `brand.yaml`, — і намальований файл розійшовся б із джерелом
# тихо: картинка лишилась би старою, а застосунок показував би новий колір.
#
# Форма — обведенням, літера — тим самим `currentColor`. Тобто бейдж не тягне
# другого кольору для тла й лягає і на полотно, і на картку, і на акцент.
SHAPES: dict[str, str] = {
    "circle": '<circle cx="16" cy="16" r="13.2" fill="none" '
              'stroke="currentColor" stroke-width="2"/>',
    "diamond": '<path d="M16 2.2 29.8 16 16 29.8 2.2 16Z" fill="none" '
               'stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "notched": '<path d="M4.4 3h15.2l8.4 8.4v17.2H4.4Z" fill="none" '
               'stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
}


def render_badge(engine_id: str, brand: Brand | None = None) -> str:
    """Бейдж одного рушія: форма плюс літера, усе на `currentColor`."""
    b = brand or active()
    style = b.engine(engine_id)
    if style is None:
        raise ValueError(f"немає стилю рушія «{engine_id}»")
    shape = SHAPES.get(style.shape)
    if shape is None:
        raise ValueError(f"немає форми «{style.shape}» — перелік у SHAPES")
    # ⚠ Лапки в стеку шрифтів («Segoe UI») довелось би екранувати в атрибуті,
    # тож вони йдуть сутністю: інакше SVG перестає бути валідним XML.
    font = b.type_text.replace(chr(34), "&quot;")
    # Колір статичного файлу береться зі світлої теми: асет лягає в README і на
    # сторінку пакета, тобто на біле тло, яке про наш перемикач не знає.
    rows = [
        "<!-- ⚠ згенеровано з brand.yaml — руками не правити.",
        f"     {style.id}: {style.role_uk} -->",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img"',
        f'     aria-label="{style.id}" style="color: {style.light}">',
        f"  {shape}",
        f'  <text x="16" y="16" fill="currentColor" font-family="{font}"',
        '        font-size="15" font-weight="700" text-anchor="middle"',
        f'        dominant-baseline="central">{style.letter_uk}</text>',
        "</svg>",
        "",
    ]
    return "\n".join(rows)


def targets() -> dict[str, str]:
    """Куди що лягає: шлях від кореня репозиторію → різновид.

    Функція, а не сталий словник: перелік бейджів росте разом із рушіями в
    `brand.yaml`, і зашитий тут список розійшовся б із ним при першому ж
    новому рушії.
    """
    out = {
        # ⚠ Токени лежать у спільному шарі, а не в теці демона: їх читає ще й
        # консоль дослідника, змонтувавши цю саму теку. Доти файл жив у
        # `daemon/static/`, і другий споживач мусив би тримати копію.
        "src/nyshporka/ui/static/tokens.css": "app",
        "docs/stylesheets/brand.css": "docs",
        "src/nyshporka/brand/data/assets/mark.svg": "mark",
        "src/nyshporka/brand/data/assets/favicon.svg": "favicon",
        # MkDocs бере логотип і фавіконку лише з `docs/`, тож вони й тут — але
        # генеруються з того самого джерела, а не копіюються: копія розійшлася б
        # тихо, і сайт показував би вчорашній знак.
        "docs/assets/mark.svg": "mark",
        "docs/assets/favicon.svg": "favicon",
    }
    for e in active().engines_ordered():
        out[f"src/nyshporka/brand/data/assets/engine-{e.id}.svg"] = f"badge:{e.id}"
    return out


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def render(flavour: str, brand: Brand | None = None) -> str:
    b = brand or active()
    if flavour == "app":
        return render_app(b)
    if flavour == "docs":
        return render_docs(b)
    if flavour == "mark":
        return paw.render_svg()
    if flavour == "favicon":
        # Вкладка браузера: знак полотном на акцентній плитці, без ручки лупи.
        # 🔴 Кольори — зі світлої теми, хоч базова тепер темна: фавіконку
        # малює браузер поруч зі своїми, на власному тлі, і вона мусить
        # лишатись упізнаваною незалежно від того, яку тему вибрали в застосунку.
        return paw.render_svg(handle=False, colour=b.color("bg").light,
                              plate=b.color("accent").light)
    if flavour.startswith("badge:"):
        return render_badge(flavour.split(":", 1)[1], b)
    raise ValueError(f"немає різновиду «{flavour}»")


#: Растри. Живуть окремо від `--check` навмисно: побайтова рівність PNG між
#: версіями Pillow не гарантована, тож приймач «не протухло» давав би на них
#: хибні падіння в CI. Перезбираються командою, а звіряється лише наявність.
RASTER_TARGETS: dict[str, tuple[str, int, int]] = {
    "src/nyshporka/brand/data/assets/mark.png": ("mark", 512, 512),
    "src/nyshporka/brand/data/assets/social-preview.png": ("social", 1280, 640),
    # 🪟 Іконка інсталятора й ярликів. Windows бере з `.ico` ту врізку, яка
    # пасує місцю: 16 px у заголовку вікна, 32 у списку «Програми та засоби»,
    # 256 на робочому столі з великими значками. Один розмір, розтягнутий
    # системою, у дрібних місцях перетворюється на кашу — а це те, що людина
    # бачить ще до першого запуску.
    "src/nyshporka/brand/data/assets/nyshporka.ico": ("icon", 256, 256),
}


def render_png(kind: str, width: int, height: int, brand: Brand | None = None) -> bytes:
    b = brand or active()
    if kind == "social":
        return paw.render_social(width, height, colour=b.color("accent").light,
                                 background=b.color("bg").light)
    if kind == "icon":
        return _render_ico(width, b)
    return paw.render_png(width, colour=b.color("accent").light)


#: Врізки, які Windows справді питає. Більше не кладемо: кожна додає вагу до
#: файлу, який людина качає перед тим, як побачила застосунок.
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def _render_ico(px: int, brand: Brand) -> bytes:
    """Знак → багаторозмірний `.ico`.

    🐾 Джерело те саме, що в `mark.png`, і це не економія: іконка інсталятора —
    перше, що бачить людина, і власний малюнок тут означав би, що бренд
    розходиться ще до встановлення. Той самий принцип, що й у лапки, яку
    звіряє `test_installers_print_the_same_paw`.

    Pillow збирає врізки сам із найбільшої; окремо рендерити кожну не треба.
    """
    import io

    from PIL import Image

    mark = Image.open(io.BytesIO(paw.render_png(px, colour=brand.color("accent").light)))
    buf = io.BytesIO()
    mark.save(buf, format="ICO", sizes=[(s, s) for s in ICO_SIZES if s <= px])
    return buf.getvalue()


def _speak_utf8() -> None:
    """Дозволити виводу нести ✅ і 🔴 там, де консоль цього не чекає.

    ⚠ Ловиться не локально. На Windows-раннері CI stdout приходить у cp1252, і
    голий `print("✅ …")` валить прогін `UnicodeEncodeError` — тобто приймач
    айдентики падає не тому, що айдентика протухла. Rich у застосунку це вміє
    сам, а тут `print` голий, бо модуль навмисно не тягне залежностей.

    `errors="replace"` навмисно: втратити позначку в лозі не страшно, зупинити
    через неї збірку — страшно.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:      # підмінений потік (напр. у тестах)
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _speak_utf8()
    ap = argparse.ArgumentParser(description="brand.yaml → файли поверхонь")
    ap.add_argument("--check", action="store_true",
                    help="не писати, а перевірити, чи згенероване не протухло")
    ap.add_argument("--png", action="store_true",
                    help="перезібрати ще й растри (знак, обкладинку, іконку)")
    ns = ap.parse_args(argv)

    root, stale = repo_root(), []
    if ns.png and not ns.check:
        for rel, (kind, w, h) in RASTER_TARGETS.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render_png(kind, w, h))
            print(f"переписано: {rel}")
    for rel, flavour in targets().items():
        path, text = root / rel, render(flavour)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if ns.check:
            stale.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"переписано: {rel}")

    if stale:
        print("🔴 згенероване розійшлося з brand.yaml:", file=sys.stderr)
        for rel in stale:
            print(f"   {rel}", file=sys.stderr)
        print("   лікується: uv run python -m nyshporka.brand.gen", file=sys.stderr)
        return 1
    if ns.check:
        print("✅ згенероване збігається з brand.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
