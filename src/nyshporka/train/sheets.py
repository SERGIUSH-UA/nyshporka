"""🗺 Аркуш сторінки з ПРОНУМЕРОВАНИМИ рамками рядків — для арбітра.

Зведення по одному кропу структурно сліпе до сторінки: на розвороті рядок,
що йде через корінець, стає двома кропами з несусідніми індексами, і
посмужковий арбітр склеїти його не може за побудовою. Тому зводити треба,
дивлячись на сторінку, — а щоб не шукати смужку вручну, кожен рядок обведено
рамкою з його номером (тим самим `line_NNN`, яким названо кроп).

🔴 Роздільність вирішує. Модель стискає зображення до ~1568 px по довгій
стороні, і ціла сторінка приходить у масштабі, на якому скоропис
розсипається. Нижче `min_scale` аркуш ріжеться СІТКОЮ на тайли з перекриттям;
межі шукаються по «долинах» між рамками, а вертикальний поділ скасовується,
якщо ріже понад чверть рамок (суцільний текст).

Номер рамки — на білій плашці при лівому верхньому куті своєї рамки, з
виноскою до кута: без сталого положення й лінії арбітр не міг зіставити id з
текстом по аркушу і йшов звіряти кожен рядок по кропу.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import sets as S

#: Довга сторона, до якої стискає модель. Нижче цього масштабу читати не варто.
VISION_LONG_SIDE = 1568
#: Понад стільки рамок на тайл номери зливаються при вписуванні у вікно.
MAX_BOXES_PER_TILE = 35
DEFAULT_MIN_SCALE = 0.55
DEFAULT_OVERLAP = 0.12

#: Кольори смуг, циклічні: сусідні фізичні рядки завжди різні, а половинки
#: одного рядка — однакові.
BAND_COLORS = [(220, 0, 0), (0, 110, 200), (0, 150, 60), (190, 90, 0),
               (150, 0, 190), (0, 150, 160), (120, 90, 0), (200, 0, 120)]


class SheetError(ValueError):
    """Немає рамок або зображення."""


def bands(boxes: list[Any]) -> dict[int, int]:
    """Номер горизонтальної смуги для кожної рамки.

    🔴 Порівнюємо з ЯКОРЕМ смуги, а не з попередньою рамкою: ланцюгове
    порівняння транзитивне, і рамки A–B–C з попарним перекриттям злились би в
    одну смугу, хоча A і C спільного не мають. Хибна склейка гірша за
    відсутню підказку, бо арбітр їй вірить.
    """
    idx = [(i, b) for i, b in enumerate(boxes) if b]
    idx.sort(key=lambda t: (t[1][1] + t[1][3]) / 2)
    out: dict[int, int] = {}
    band = 0
    anchor: Any = None
    for i, b in idx:
        if anchor is not None:
            lo, hi = max(anchor[1], b[1]), min(anchor[3], b[3])
            shorter = min(anchor[3] - anchor[1], b[3] - b[1]) or 1
            if (hi - lo) / shorter <= 0.5:
                band += 1
                anchor = b
        else:
            anchor = b
        out[i] = band
    return out


def _font() -> Any:
    from PIL import ImageFont

    for p in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            return ImageFont.truetype(p, 30)
        except OSError:
            continue
    return ImageFont.load_default()


def _label(d: Any, b: list[int], text: str, font: Any, others: list[Any],
           col: tuple[int, int, int]) -> None:
    x, y = b[0], b[1]
    tw, th = 54, 34
    for lx, ly in ((x - tw - 4, y - th), (x - tw - 4, y), (x, y - th), (x - tw - 4, y + 4)):
        if lx < 0 or ly < 0:
            continue
        if not any(o and o is not b and lx < o[2] and lx + tw > o[0]
                   and ly < o[3] and ly + th > o[1] for o in others):
            break
    else:
        lx, ly = max(0, x - tw - 4), max(0, y - th)
    d.line((lx + tw, ly + th // 2, x, y), fill=col, width=2)
    d.rectangle((lx, ly, lx + tw, ly + th), fill=(255, 255, 255), outline=col)
    d.text((lx + 4, ly + 2), text, fill=col, font=font)


def split_points(lo: int, hi: int, n: int, boxes: list[Any], axis: int) -> list[tuple[int, int]]:
    """Межі поділу, що ріжуть якнайменше рамок: `(координата, скільки розрізано)`."""
    out: list[tuple[int, int]] = []
    span = (hi - lo) / n
    for k in range(1, n):
        ideal = lo + span * k
        win = span * 0.18
        best, best_cut = None, int(ideal)
        for cand in range(int(ideal - win), int(ideal + win) + 1, 4):
            cut = sum(1 for b in boxes if b and b[axis] < cand < b[axis + 2])
            if best is None or cut < best:
                best, best_cut = cut, cand
        out.append((best_cut, best or 0))
    return out


def grid_for(block_w: int, block_h: int, boxes: list[Any], off: tuple[int, int],
             limit: float) -> tuple[list[int], list[int], int, int]:
    """Колонки і рядки сітки в координатах блоку, з відмовою від злого поділу."""
    shifted = [[b[0] - off[0], b[1] - off[1], b[2] - off[0], b[3] - off[1]]
               for b in boxes if b]
    n_boxes = max(1, len(shifted))
    xs, ys, cut_x, cut_y = [0, block_w], [0, block_h], 0, 0
    cols = max(1, math.ceil(block_w / limit))
    rows = max(1, math.ceil(block_h / limit))
    if cols > 1:
        pts = split_points(0, block_w, cols, shifted, 0)
        cut_x = max(c for _, c in pts)
        if cut_x <= n_boxes * 0.25:
            xs = [0, *[p for p, _ in pts], block_w]
        else:
            cols = 1
    while rows < 8:
        per = math.ceil(n_boxes / (rows * max(1, cols)))
        if per <= MAX_BOXES_PER_TILE:
            break
        rows += 1
    if rows > 1:
        pts = split_points(0, block_h, rows, shifted, 1)
        cut_y = max(c for _, c in pts)
        ys = [0, *[p for p, _ in pts], block_h]
    return xs, ys, cut_x, cut_y


def render_sheet(im: Any, boxes: list[Any], out: Path, page: str, *,
                 min_scale: float = DEFAULT_MIN_SCALE,
                 overlap: float = DEFAULT_OVERLAP) -> tuple[list[Path], str]:
    """Аркуш (або тайли) для однієї сторінки. Повертає файли й примітку."""
    from PIL import ImageDraw

    bs = [b for b in boxes if b]
    if not bs:
        raise SheetError("немає рамок")
    im = im.convert("RGB")
    d = ImageDraw.Draw(im)
    font = _font()
    band_of = bands(boxes)
    for i, b in enumerate(boxes):
        if not b:
            continue
        col = BAND_COLORS[band_of[i] % len(BAND_COLORS)]
        d.rectangle(tuple(int(v) for v in b[:4]), outline=col, width=2)
        _label(d, b, f"{i:03d}", font, boxes, col)
    pad = 30
    x0 = max(0, min(b[0] for b in bs) - pad - 46)
    y0 = max(0, min(b[1] for b in bs) - pad)
    x1 = min(im.width, max(b[2] for b in bs) + pad)
    y1 = min(im.height, max(b[3] for b in bs) + pad)
    block = im.crop((x0, y0, x1, y1))
    scale = min(1.0, VISION_LONG_SIDE / max(block.size))
    out.mkdir(parents=True, exist_ok=True)
    if scale >= min_scale:
        f = out / f"{page}.png"
        block.save(f)
        return [f], f"{block.size[0]}×{block.size[1]}, масштаб {scale:.2f}× — одним аркушем"
    limit = VISION_LONG_SIDE / min_scale
    xs, ys, cut_x, cut_y = grid_for(block.width, block.height, boxes, (x0, y0), limit)
    cols, rows = len(xs) - 1, len(ys) - 1
    ovx = int(block.width / cols * overlap)
    ovy = int(block.height / rows * overlap)
    files: list[Path] = []
    worst = 0
    k = 0
    for r in range(rows):
        for c in range(cols):
            tx0 = max(0, xs[c] - (ovx if c else 0))
            tx1 = min(block.width, xs[c + 1] + (ovx if c + 1 < cols else 0))
            ty0 = max(0, ys[r] - (ovy if r else 0))
            ty1 = min(block.height, ys[r + 1] + (ovy if r + 1 < rows else 0))
            k += 1
            worst = max(worst, tx1 - tx0, ty1 - ty0)
            f = out / f"{page}_t{k}.png"
            block.crop((tx0, ty0, tx1, ty1)).save(f)
            files.append(f)
    tscale = min(1.0, VISION_LONG_SIDE / max(1, worst))
    note = (f"сітка {cols}×{rows} = {k} тайлів, найбільший бік {worst}px ({tscale:.2f}×), "
            f"рамок розрізано {cut_x}/{cut_y}")
    if cols == 1 and block.width > limit:
        note += " ⚠ рядки суцільні — вертикально не ділив, масштаб нижчий за поріг"
    return files, note


@dataclass
class SheetReport:
    pages: dict[str, list[Path]] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def make_sheets(name: str, pages: list[str], out: Path, *, ws: Workspace | None = None,
                image_of: Any = None, min_scale: float = DEFAULT_MIN_SCALE,
                overlap: float = DEFAULT_OVERLAP) -> SheetReport:
    """Аркуші для сторінок набору + `<page>.drafts.txt` із голосами поруч."""
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    cut_meta = reg.cut_meta(spec).get("pages") or {}
    if image_of is None:
        from nyshporka.htr import view as V

        image_of = V._page_image
    rep = SheetReport()
    voices = spec.voices()
    for page in pages:
        boxes = (cut_meta.get(page) or {}).get("boxes") or []
        if not any(boxes):
            rep.warnings.append(f"{page}: у меті нарізки немає рамок — аркуша не буде")
            continue
        try:
            from nyshporka.train.cut import image_key

            im = image_of(spec.source_run, image_key(cut_meta.get(page) or {}, page))
        except Exception as exc:
            rep.warnings.append(f"{page}: зображення: {exc}")
            continue
        size = (cut_meta.get(page) or {}).get("size")
        if size and [int(v) for v in size] != [im.width, im.height]:
            rep.warnings.append(f"{page}: розмір зображення {[im.width, im.height]} не той, "
                                f"що при нарізці {size} — рамки не накладуться")
            continue
        try:
            files, note = render_sheet(im, boxes, out, page, min_scale=min_scale,
                                       overlap=overlap)
        except SheetError as exc:
            rep.warnings.append(f"{page}: {exc}")
            continue
        rep.pages[page] = files
        rep.notes[page] = note
        cols = [(d.id, reg.draft_lines(spec, d, page) or []) for d in voices]
        if any(c for _, c in cols):
            n = max(len(c) for _, c in cols)
            lines = [f"# {page} — голоси ({', '.join(i for i, _ in cols)})"]
            for i in range(n):
                vals = [(c[i].strip() if i < len(c) else "") for _, c in cols]
                if any(vals):
                    lines.append(f"{i:03d} | " + " | ".join(vals))
            (out / f"{page}.drafts.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rep
