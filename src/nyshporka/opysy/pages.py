"""Сторінки опису з PDF → сірі JPEG під читання цілими сторінками (`nysh read <тека>`).

Висота рендера — `TARGET_H`: на ній заміряно таблицю цілих сторінок (`ruled`), і місце справи
(`y`) рахується в пікселях саме цього кадру. Готові сторінки не перерендерюються;
дописуються лише відсутні, запис атомарний.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TARGET_H = 3100


#: Зображення в теці-джерелі (архів публікує опис кадрами, а не одним файлом).
OBRAZY = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


def _pryrodnyi(p: Path) -> tuple[Any, ...]:
    """Ключ природного порядку: `2.jpg` перед `10.jpg`; числові фрагменти — числа, текст — без регістру.

    Для імен з однаковою кількістю цифр порядок той самий, що й за простим іменем."""
    chastyny = re.split(r"(\d+)", p.name.lower())
    return (*(int(c) if i % 2 else c for i, c in enumerate(chastyny)), p.name)


def obrazy(teka: Path) -> list[Path]:
    """Кадри теки-джерела в природному порядку імен (без підтек)."""
    return sorted((p for p in Path(teka).iterdir() if p.is_file() and p.suffix.lower() in OBRAZY),
                  key=_pryrodnyi)


def _do_8bit(im: Any) -> Any:
    """Сірий 8-бітний кадр; 16-бітні (`I;16*`, `I`) масштабуються, а не обрізаються."""
    import numpy as np
    from PIL import Image

    if im.mode.startswith("I;16") or im.mode in ("I", "F"):
        a = np.asarray(im).astype("float64")
        top = 65535.0 if a.max() <= 65535.0 else float(a.max())
        if im.mode in ("I", "F") and a.max() <= 255.0:
            top = 255.0
        return Image.fromarray(np.clip(a * 255.0 / top, 0, 255).round().astype("uint8"), "L")
    return im.convert("L")


def _zberehty(im: Any, out: Path, target_h: int | None = None) -> None:
    """JPEG через тимчасовий файл і `replace`: перерваний запис не лишає напівготової сторінки."""
    from PIL import Image

    if target_h is not None:
        w, h = im.size
        im = im.resize((max(1, round(w * target_h / h)), target_h), Image.Resampling.LANCZOS)
    tmp = out.with_name(f".{out.stem}.tmp")
    try:
        im.save(tmp, format="JPEG", quality=88)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)


def render(pdf: Path, out_dir: Path, *, target_h: int = TARGET_H, force: bool = False) -> dict[str, Any]:
    """PDF чи тека кадрів → `<out_dir>/NNNN.jpg` (з 1).

    Готове пропускається, лише коли є рівно стільки сторінок, скільки в джерелі; інакше дописуються
    відсутні (`force` — усі). У результаті `warnings` (якщо є): багатосторінковий TIFF, зайві файли."""
    import pypdfium2 as pdfium

    d = Path(out_dir)
    ye_stor = {int(p.stem) for p in d.glob("*.jpg") if p.stem.isdigit()} if d.exists() else set()
    warnings: list[str] = []
    if Path(pdf).is_dir():
        from PIL import Image, ImageOps

        kadry = obrazy(Path(pdf))
        n = len(kadry)
        if not force and ye_stor == set(range(1, n + 1)) and len(list(d.glob("*.jpg"))) == n:
            return {"skip": "сторінки вже є", "pages": n}
        d.mkdir(parents=True, exist_ok=True)
        for i, k in enumerate(kadry, 1):
            if i in ye_stor and not force:
                continue
            with Image.open(k) as raw:
                nf = int(getattr(raw, "n_frames", 1))
                if nf > 1:
                    warnings.append(f"{k.name}: {nf} кадрів у файлі, взято перший")
                im = _do_8bit(ImageOps.exif_transpose(raw))
            _zberehty(im, d / f"{i:04d}.jpg", target_h)
        res: dict[str, Any] = {"pages": n, "mode": "images"}
    else:
        doc = pdfium.PdfDocument(str(pdf))
        try:
            n = len(doc)
            if not force and ye_stor == set(range(1, n + 1)) and len(list(d.glob("*.jpg"))) == n:
                return {"skip": "сторінки вже є", "pages": n}
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                if i + 1 in ye_stor and not force:
                    continue
                pg = doc[i]
                _, h = pg.get_size()
                im = pg.render(scale=target_h / h).to_pil().convert("L")
                pg.close()
                _zberehty(im, d / f"{i + 1:04d}.jpg")
        finally:
            doc.close()
        res = {"pages": n, "mode": "page"}
    zaivi = len(list(d.glob("*.jpg"))) - n
    if zaivi > 0:
        warnings.append(f"у {d} на {zaivi} jpg більше, ніж сторінок у джерелі (лишилось від іншого джерела?)")
    if warnings:
        res["warnings"] = warnings
    return res
