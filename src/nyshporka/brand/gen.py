"""🐾 `brand.yaml` → файли. Генератор, а не набір стилів.

Два споживачі беруть ті самі токени й через це не можуть розійтися:

    daemon/static/tokens.css     застосунок (`nysh serve`)
    docs/stylesheets/brand.css   сайт документації (MkDocs Material)

🔴 Обидва файли ЗГЕНЕРОВАНІ й руками не правляться. Правка робиться в
`brand.yaml`, після чого:

    uv run python -m nyshporka.brand.gen          # переписати
    uv run python -m nyshporka.brand.gen --check  # чи не протухли (це і в CI)

Чому не збирати CSS у застосунку на льоту: сайт документації збирається
MkDocs'ом, який про наш пакет нічого не знає, а `tokens.css` мусить лежати
файлом, щоб потрапити в колесо. Генерація в репозиторій — єдиний спосіб мати
одне джерело для обох.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nyshporka.brand import paw
from nyshporka.brand.manifest import Brand, active

#: Шапка згенерованого файлу. Стоїть першою й каже, куди йти зі змінами:
#: без неї правка неминуче робиться в CSS, живе до наступного прогону
#: генератора й зникає без сліду.
HEADER = """/* ⚠ ЗГЕНЕРОВАНО з `src/nyshporka/brand/data/brand.yaml` — руками не правити.
   Правка тут живе рівно до наступного `python -m nyshporka.brand.gen`.
   Змінювати кольори — у brand.yaml; перевіряти — `--check` (він же в CI). */
"""


def _block(vars_: dict[str, str], indent: str = "  ") -> str:
    return "".join(f"{indent}--{k}: {v};\n" for k, v in vars_.items())


def render_app(brand: Brand) -> str:
    """Токени застосунку.

    Світла тема — базова, темна лише ПЕРЕВИЗНАЧАЄ: так будь-який колір, забутий
    у темному блоці, дає видимо неправильний вигляд замість порожнечі.
    """
    fonts = {
        "font-text": brand.type_text,
        "font-mono": brand.type_mono,
        "font-size": brand.type_size,
        "line-height": brand.type_leading,
    }
    out = [HEADER, "\n:root {\n", _block(brand.css_vars("light")), _block(fonts), "}\n"]
    out += [
        "\n/* Тема з системної налаштованості: застосунок відкривають на ноутбуці\n"
        "   в читальній залі, і біле полотно в темній залі читається гірше за скан. */\n",
        "@media (prefers-color-scheme: dark) {\n  :root {\n",
        _block(brand.css_vars("dark"), indent="    "),
        "  }\n}\n",
    ]
    # Прив'язка бейджа до рушія теж генерується: інакше новий рушій дістав би з
    # даних форму й літеру, а колір — ні, і вийшов би сірим серед кольорових.
    out.append("\n/* Бейджі рушіїв: колір під `data-engine`. Форма — в app.css. */\n")
    out += [f'.engine[data-engine="{e.id}"] {{ --engine: var(--engine-{e.id}); }}\n'
            for e in brand.engines_ordered()]
    return "".join(out)


def render_docs(brand: Brand) -> str:
    """Оформлення сайту документації.

    MkDocs Material має власні імена змінних, тож наші токени сюди
    ПЕРЕКЛАДАЮТЬСЯ. Перекладаються лише ті, що справді керують виглядом
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
        return f"{selector} {{\n{_block(md)}{_block(v)}}}\n"

    parts = [
        HEADER,
        "\n",
        scheme("light", '[data-md-color-scheme="default"]'),
        "\n",
        scheme("dark", '[data-md-color-scheme="slate"]'),
    ]
    return "".join(parts)


# ── бейджі рушіїв ────────────────────────────────────────────────────────────
# 🔴 Малюються ГЕНЕРАТОРОМ, а не руками. Бейдж несе колір, форму й літеру —
# три ознаки з `brand.yaml`, — і намальований файл розійшовся б із джерелом
# тихо: картинка лишилась би старою, а застосунок показував би новий колір.
#
# Форма — обведенням, літера — тим самим `currentColor`. Тобто бейдж не тягне
# другого кольору для тла й лягає і на полотно, і на картку, і на сепію.
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
    rows = [
        "<!-- ⚠ ЗГЕНЕРОВАНО з brand.yaml — руками не правити.",
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
        "src/nyshporka/daemon/static/tokens.css": "app",
        "docs/stylesheets/brand.css": "docs",
        "src/nyshporka/brand/data/assets/mark.svg": "mark",
        "src/nyshporka/brand/data/assets/favicon.svg": "favicon",
        # MkDocs бере логотип і фавіконку ЛИШЕ з `docs/`, тож вони й тут — але
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
        # Вкладка браузера: знак полотном на сепійній плитці, без ручки лупи.
        return paw.render_svg(handle=False, colour=b.color("paper").light,
                              plate=b.color("sepia").light)
    if flavour.startswith("badge:"):
        return render_badge(flavour.split(":", 1)[1], b)
    raise ValueError(f"немає різновиду «{flavour}»")


#: Растри. Живуть окремо від `--check` навмисно: побайтова рівність PNG між
#: версіями Pillow не гарантована, тож приймач «не протухло» давав би на них
#: хибні падіння в CI. Перезбираються командою, а звіряється лише наявність.
PNG_TARGETS: dict[str, tuple[str, int, int]] = {
    "src/nyshporka/brand/data/assets/mark.png": ("mark", 512, 512),
    "src/nyshporka/brand/data/assets/social-preview.png": ("social", 1280, 640),
}


def render_png(kind: str, width: int, height: int, brand: Brand | None = None) -> bytes:
    b = brand or active()
    if kind == "social":
        return paw.render_social(width, height, colour=b.color("sepia").light,
                                 background=b.color("paper").light)
    return paw.render_png(width, colour=b.color("sepia").light)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="brand.yaml → файли поверхонь")
    ap.add_argument("--check", action="store_true",
                    help="не писати, а перевірити, чи згенероване не протухло")
    ap.add_argument("--png", action="store_true",
                    help="перезібрати ще й растри (знак і обкладинку репозиторію)")
    ns = ap.parse_args(argv)

    root, stale = repo_root(), []
    if ns.png and not ns.check:
        for rel, (kind, w, h) in PNG_TARGETS.items():
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
