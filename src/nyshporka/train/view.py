"""👁 Дивилка кропів для арбітра й людини: смужка, зум, контекст.

Три погляди, і кожен закриває вроджену ваду іншого:

* `strip` — кілька кропів підряд, кожен підписаний СВОЇМ індексом: видно й
  текст, і те, якому `line_NNN` він належить;
* `zoom` — шматок одного кропа в кратному збільшенні. Для власних назв:
  сторінковий масштаб їх систематично псує, а на ×4 видно штрих. Друкує
  ширину фрагмента — піксель-на-літеру проти сусіднього слова є дешевим
  арбітром там, де почерк не розрізняє літер;
* `ctx` — смуга зі СТОРІНКИ за рамкою рядка плюс поля. Єдиний спосіб
  перевірити, чи рамка не відрізала хвіст слова: усередині кропа цього не
  видно за побудовою.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import sets as S


class ViewError(ValueError):
    """Кропа або рамки немає."""


@dataclass(frozen=True)
class Shot:
    png: bytes
    width: int
    height: int
    note: str = ""

    @property
    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode("ascii")


def _png(im: Any) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def parse_lines(spec: str) -> list[int]:
    """«6-10,15,20» → [6,7,8,9,10,15,20]."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def strip(name: str, page: str, lines: list[int], *, ws: Workspace | None = None) -> Shot:
    from PIL import Image, ImageDraw

    reg = S.registry(ws if ws is not None else workspace())
    spec = reg.load(name)
    ims = []
    missing = []
    for i in lines:
        p = reg.crop_path(spec, page, i)
        if p is None:
            missing.append(i)
            continue
        with Image.open(p) as raw:
            ims.append((i, raw.convert("L")))
    if not ims:
        raise ViewError(f"жодного кропа сторінки {page} серед {lines}")
    pad = 66
    w = max(im.width for _, im in ims) + pad + 4
    h = sum(im.height + 14 for _, im in ims)
    sheet = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(sheet)
    y = 0
    for i, im in ims:
        d.text((4, y + im.height // 2 - 6), f"{i:03d}", fill=0)
        sheet.paste(im, (pad, y))
        y += im.height + 14
    note = f"{len(ims)} кропів" + (f"; немає: {missing}" if missing else "")
    return Shot(png=_png(sheet), width=sheet.width, height=sheet.height, note=note)


def zoom(name: str, page: str, line: int, *, frm: float = 0.0, to: float = 1.0,
         k: float = 4.0, ws: Workspace | None = None) -> Shot:
    from PIL import Image

    reg = S.registry(ws if ws is not None else workspace())
    p = reg.crop_path(reg.load(name), page, line)
    if p is None:
        raise ViewError(f"кропа {page}:{line} немає")
    with Image.open(p) as raw:
        im = raw.convert("L")
    x0, x1 = int(im.width * frm), int(im.width * to)
    x1 = max(x1, x0 + 1)
    box = im.crop((x0, 0, x1, im.height))
    box = box.resize((max(1, int(box.width * k)), max(1, int(box.height * k))),
                     Image.Resampling.LANCZOS)
    note = (f"фрагмент {x1 - x0}px з {im.width}px кропа → на 8 літер {(x1 - x0) / 8:.0f}px, "
            f"на 12 літер {(x1 - x0) / 12:.0f}px")
    return Shot(png=_png(box), width=box.width, height=box.height, note=note)


def ctx(name: str, page: str, line: int, *, pad: int = 200, k: float = 1.0,
        ws: Workspace | None = None, image_of: Any = None) -> Shot:
    from PIL import Image

    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    cut_page = (reg.cut_meta(spec).get("pages") or {}).get(page) or {}
    boxes = cut_page.get("boxes") or []
    if not 0 <= line < len(boxes) or not boxes[line]:
        raise ViewError(f"у рядка {page}:{line} немає рамки — контекст неможливий")
    if image_of is None:
        from nyshporka.htr import view as V

        image_of = V._page_image
    from nyshporka.train.cut import image_key

    im = image_of(spec.source_run, image_key(cut_page, page)).convert("L")
    x0, y0, x1, y1 = (int(v) for v in boxes[line][:4])
    crop = im.crop((max(0, x0 - pad), max(0, y0 - pad // 2),
                    min(im.width, x1 + pad), min(im.height, y1 + pad // 2)))
    if k != 1.0:
        crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))),
                           Image.Resampling.LANCZOS)
    edge = "ДОХОДИТЬ ДО КРАЮ" if x1 > im.width - 40 else "є поле праворуч"
    return Shot(png=_png(crop), width=crop.width, height=crop.height,
                note=f"рамка {boxes[line]}, сторінка {im.width}×{im.height} ({edge})")
