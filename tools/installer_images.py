"""Картинки майстра Inno (`install/img/`) з растру бренду.

    python tools/installer_images.py

Бічна картинка першої й останньої сторінки — маскот, що вітається
(`ui/static/img/maskot-vitaie.webp`), на тлі світлої теми бренду; мала в шапці
решти сторінок — знак (`brand/data/assets/mark.png`). Тексту на них немає
навмисно: майстер семимовний, а напис на картинці не перекладається.

Розміри — ті, з яких Inno сам вибирає під масштаб екрана (100 %…250 %).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "install" / "img"
MASKOT = ROOT / "src" / "nyshporka" / "ui" / "static" / "img" / "maskot-vitaie.webp"
MARK = ROOT / "src" / "nyshporka" / "brand" / "data" / "assets" / "mark.png"
# `--bg` світлої теми (`ui/static/tokens.css`) — те саме тло, що на слайдах і порталі.
BG = (0xF5, 0xED, 0xDC)

SIDE = [(164, 314), (192, 386), (246, 459), (273, 556), (328, 604), (355, 700), (410, 797)]
SMALL = [(55, 55), (64, 68), (83, 80), (92, 97), (110, 106), (119, 123), (138, 140)]


def place(src: Image.Image, size: tuple[int, int], fill: float, bottom: float) -> Image.Image:
    """`src` на тлі BG: ширина — `fill` від полотна, низ — на `bottom` від верху."""
    w, h = size
    canvas = Image.new("RGB", size, BG)
    k = min(w * fill / src.width, h * 0.9 / src.height)
    im = src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS)
    x = (w - im.width) // 2
    y = max(0, round(h * bottom) - im.height)
    canvas.paste(im, (x, y), im)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    maskot = Image.open(MASKOT).convert("RGBA")
    mark = Image.open(MARK).convert("RGBA")
    for w, h in SIDE:
        place(maskot, (w, h), 0.86, 0.9).save(OUT / f"wizard-{w}x{h}.png", optimize=True)
    for w, h in SMALL:
        place(mark, (w, h), 0.9, 0.95).save(OUT / f"small-{w}x{h}.png", optimize=True)
    print(f"{len(SIDE) + len(SMALL)} файлів → {OUT}")


if __name__ == "__main__":
    main()
