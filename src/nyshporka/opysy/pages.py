"""Сторінки опису з PDF → сірі JPEG під читання цілими сторінками (`nysh read <тека>`).

Висота рендера — `TARGET_H`: на ній заміряно таблицю цілих сторінок (`ruled`), і місце справи
(`y`) рахується в пікселях саме цього кадру. Готові сторінки не перерендерюються.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TARGET_H = 3100


def render(pdf: Path, out_dir: Path, *, target_h: int = TARGET_H, force: bool = False) -> dict[str, Any]:
    """PDF → `<out_dir>/NNNN.jpg` (з 1); готове — пропустити, якщо не `force`."""
    import pypdfium2 as pdfium

    d = Path(out_dir)
    if d.exists() and any(d.glob("*.jpg")) and not force:
        return {"skip": "сторінки вже є", "pages": len(list(d.glob("*.jpg")))}
    d.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    try:
        n = len(doc)
        for i in range(n):
            out = d / f"{i + 1:04d}.jpg"
            if out.exists() and not force:
                continue
            pg = doc[i]
            _, h = pg.get_size()
            pg.render(scale=target_h / h).to_pil().convert("L").save(out, quality=88)
            pg.close()
    finally:
        doc.close()
    return {"pages": n, "mode": "page"}
