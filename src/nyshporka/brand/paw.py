"""🐾 Знак Нишпорки — лапка, що малюється з геометрії.

⚠ Модуль зветься `paw`, а не `mark`: у фасаді пакета вже є функція `mark()`
(позначка зі словника), і однойменний модуль вона б перекривала — імпорт
`from nyshporka.brand import mark` мовчки повертав би функцію.

Лапка описана даними в `brand.yaml`, а звідси виходять обидва представлення:

    SVG   застосунок, сайт документації, вкладка браузера
    PNG   README і обкладинка репозиторію — 🔴 обкладинку GitHub приймає лише
          растром, а в README різні рендерери поводяться з SVG по-різному

Намальовані окремо, вони розійшлися б при першій же правці — і показували б
різний знак у застосунку й на сторінці пакета, тобто рівно там, де людина
бачить продукт уперше.

Усе зведено до еліпсів навмисно: складніший силует не пережив би 16 px у
вкладці, а лупа зроблена НАСКРІЗНИМ отвором, щоб знак лягав на будь-яке тло.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.brand.manifest import BUILTIN


@dataclass(frozen=True)
class Geometry:
    """Геометрія лапки в системі координат `size × size`."""

    size: float
    toes: tuple[dict[str, float], ...]
    pad: dict[str, float]
    lens: dict[str, float]
    handle: dict[str, float]


def geometry(path: Path | None = None) -> Geometry:
    import yaml

    raw = yaml.safe_load((path or BUILTIN).read_text(encoding="utf-8")) or {}
    g: dict[str, Any] = raw.get("mark_geometry") or {}
    return Geometry(
        size=float(g.get("size") or 32),
        toes=tuple({k: float(v) for k, v in t.items()} for t in (g.get("toes") or [])),
        pad={k: float(v) for k, v in (g.get("pad") or {}).items()},
        lens={k: float(v) for k, v in (g.get("lens") or {}).items()},
        handle={k: float(v) for k, v in (g.get("handle") or {}).items()},
    )


# ── SVG ──────────────────────────────────────────────────────────────────────
def render_svg(*, handle: bool = True, colour: str = "currentColor",
               plate: str | None = None, geo: Geometry | None = None) -> str:
    """Знак у SVG.

    `plate` — колір підкладки-квадрата (для вкладки браузера); без нього знак
    прозорий і фарбується тим, що навколо. `handle=False` прибирає ручку лупи:
    на 16 px вона зливається в пляму.
    """
    g = geo or geometry()
    s = g.size
    lens, pad, h = g.lens, g.pad, g.handle

    # Отвір лупи робиться маскою, а не другим кольором: у масці чорне — це
    # діра, тож крізь неї видно те, на чому знак лежить.
    hole = [f'      <circle cx="{lens["cx"]}" cy="{lens["cy"]}" r="{lens["r"]}" fill="#000"/>']
    if handle:
        hole.append(
            f'      <line x1="{h["x1"]}" y1="{h["y1"]}" x2="{h["x2"]}" y2="{h["y2"]}"'
            f' stroke="#000" stroke-width="{h["w"]}" stroke-linecap="round"/>')

    toes = [
        f'    <ellipse cx="{t["cx"]}" cy="{t["cy"]}" rx="{t["rx"]}" ry="{t["ry"]}"'
        f' transform="rotate({t["rot"]} {t["cx"]} {t["cy"]})"/>'
        for t in g.toes
    ]

    rows = [
        "<!-- ⚠ ЗГЕНЕРОВАНО з `mark_geometry` у brand.yaml — руками не правити.",
        "     🐾 Лапка: слід у справі. Лупа в подушечці: те, що вона робить. -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s:g} {s:g}"',
        '     role="img" aria-label="Нишпорка">',
        "  <defs>",
        '    <mask id="lens">',
        f'      <rect width="{s:g}" height="{s:g}" fill="#fff"/>',
        *hole,
        "    </mask>",
        "  </defs>",
    ]
    if plate:
        rows.append(f'  <rect width="{s:g}" height="{s:g}" rx="{s / 4.6:.1f}" fill="{plate}"/>')
    rows.append(f'  <g fill="{colour}">')
    rows += toes
    rows.append(
        f'    <ellipse cx="{pad["cx"]}" cy="{pad["cy"]}" rx="{pad["rx"]}" ry="{pad["ry"]}"'
        ' mask="url(#lens)"/>')
    rows.append("  </g>")
    rows.append("</svg>")
    rows.append("")
    return "\n".join(rows)


# ── PNG ──────────────────────────────────────────────────────────────────────
#: У скільки разів малюється більше за потрібне, перш ніж зменшити. Растр без
#: цього дає драбину на краях еліпсів — а знак найчастіше бачать саме дрібним.
SUPERSAMPLE = 4


def render_png(px: int, *, colour: str, background: str | None = None,
               handle: bool = True, geo: Geometry | None = None) -> bytes:
    """Знак у PNG. `background` порожній — прозоре тло."""
    import io

    from PIL import Image, ImageDraw

    g = geo or geometry()
    k = px * SUPERSAMPLE / g.size
    side = px * SUPERSAMPLE

    img = Image.new("RGBA", (side, side), background or (0, 0, 0, 0))
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    def box(cx: float, cy: float, rx: float, ry: float) -> tuple[float, float, float, float]:
        return ((cx - rx) * k, (cy - ry) * k, (cx + rx) * k, (cy + ry) * k)

    # Кожна подушечка малюється на власному шарі й повертається: нахил дає
    # лапі живий силует, а Pillow повертати окремі фігури не вміє.
    for t in g.toes:
        toe = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(toe).ellipse(box(t["cx"], t["cy"], t["rx"], t["ry"]), fill=colour)
        layer.alpha_composite(toe.rotate(t["rot"], center=(t["cx"] * k, t["cy"] * k),
                                         resample=Image.Resampling.BICUBIC))

    draw.ellipse(box(g.pad["cx"], g.pad["cy"], g.pad["rx"], g.pad["ry"]), fill=colour)

    # 🔴 Отвір вибивається ПРОЗОРИМ, а не кольором тла: інакше знак працював би
    # лише на тому тлі, під яке його намалювали.
    lens, h = g.lens, g.handle
    draw.ellipse(box(lens["cx"], lens["cy"], lens["r"], lens["r"]), fill=(0, 0, 0, 0))
    if handle:
        draw.line([(h["x1"] * k, h["y1"] * k), (h["x2"] * k, h["y2"] * k)],
                  fill=(0, 0, 0, 0), width=round(h["w"] * k))

    img.alpha_composite(layer)
    out = img.resize((px, px), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_social(width: int, height: int, *, colour: str, background: str,
                  geo: Geometry | None = None) -> bytes:
    """Обкладинка репозиторію: знак на полотні, без тексту.

    ⚠ Тексту тут немає навмисно. Він вимагав би шрифту з машини складача, і
    обкладинка виходила б різною в кожного, хто її перезбирає; назва й опис
    репозиторію все одно друкуються поверх картки самим GitHub.
    """
    import io

    from PIL import Image

    mark_px = int(min(width, height) * 0.7)
    plate = Image.new("RGBA", (width, height), background)
    paw = Image.open(io.BytesIO(render_png(mark_px, colour=colour)))
    plate.alpha_composite(paw, ((width - mark_px) // 2, (height - mark_px) // 2))
    buf = io.BytesIO()
    plate.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
