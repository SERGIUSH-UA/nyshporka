"""Розворот метричної книги → тайли, які vision-модель реально читає.

Проблема, заради якої модуль існує: скан 4000×3000 — це ПОВНИЙ розворот, і
один акт тягнеться горизонтально через обидві сторінки. Модель стискає
зображення до ~1568px по довшій стороні, тобто цілий скан бачиться з
коефіцієнтом 0.39× — рядок скоропису висотою 40px перетворюється на 15px і
розсипається. Саме так провалилась вичитка шлюбів 0461–0463 («[нерозбірл.]»
майже в кожному рядку).

Рішення — різати на горизонтальні смуги: смуга лівої половини має висоту
~800px замість 3000, тож після ресайзу модель бачить рядок практично в
натуральну величину.

Геометрія навмисно тупа й без детекції згину: половини беруться з перекриттям
(`SPLIT` + `SPLIT_OVERLAP`), смуги — теж (`overlap`). Евристика пошуку згину
ламається на різних сканах (де світла складка, а де темна зшивка), а зайве
перекриття коштує лише кілька мегабайт тимчасових файлів.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

# Pillow ріже великі скани як «бомбу» — архівні розвороти легально великі
Image.MAX_IMAGE_PIXELS = None

_IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# частка ширини, до якої тягнеться ліва половина (і від якої починається права)
SPLIT = 0.50
SPLIT_OVERLAP = 0.06        # ±6% ширини — щоб згин не з'їв крайній стовпчик
MARGIN = 0.015              # обрізати технічні краї скана

DEFAULT_ROWS = 6
DEFAULT_OVERLAP = 0.35      # частка висоти смуги, на яку смуги налазять
HEAD_FRAC = 0.16            # верхівка розвороту: друкований заголовок + рік
PREVIEW_MAX = 1600          # оглядовий тайл усього розвороту
# Модель стискає зображення до ~1568px по довшій стороні, тож більше за це
# віддавати марно, а менше — значить недобрати різкості на дрібному скорописі.
ZOOM_TARGET_PX = 1540


@dataclass(frozen=True)
class Tile:
    """Один вирізаний фрагмент: ім'я файлу + звідки взято (для звірки координат)."""

    name: str
    kind: str               # full / head / left / right
    box: tuple[int, int, int, int]
    size: tuple[int, int]
    hint: str = ""


def _prep(im: Image.Image) -> Image.Image:
    """Легке підняття контрасту. Свідомо стримане: агресивна обробка з'їдає
    бліде чорнило разом із фоном, а моделі краще віддати «як є, тільки ясніше»."""
    im = ImageOps.autocontrast(im, cutoff=1)
    return ImageEnhance.Sharpness(im).enhance(1.4)


def _stretch(im: Image.Image) -> Image.Image:
    """Агресивна нормалізація — для вицвілих аркушів, де зум сам по собі марний.

    На шлюбних аркушах 1875 р. чорнило й папір розділяє ~37 рівнів яскравості
    з 255: обмежує не роздільність, а контраст, і збільшення без розтягування
    діапазону нічого не додає. Відсікаємо по перцентилях, а не по мінімумі й
    максимуму, щоб поодинокі плями й діри в папері не з'їдали весь запас.
    """
    gray = ImageOps.grayscale(im)
    hist = gray.histogram()
    total = sum(hist)
    lo_t, hi_t = total * 0.02, total * 0.98
    acc, lo, hi = 0, 0, 255
    for v, n in enumerate(hist):
        acc += n
        if acc >= lo_t:
            lo = v
            break
    acc = 0
    for v, n in enumerate(hist):
        acc += n
        if acc >= hi_t:
            hi = v
            break
    if hi - lo < 8:                      # діапазон вироджений — не чіпаємо
        return ImageEnhance.Sharpness(im).enhance(1.6)
    scale = 255.0 / (hi - lo)
    im = im.point(lambda p: max(0, min(255, int((p - lo) * scale))))
    return ImageEnhance.Sharpness(im).enhance(1.6)


def _upscale(im: Image.Image, target_w: int) -> Image.Image:
    """Довести тайл до цільової ширини — саме те, чого раніше не робилось.

    Перша версія `--zoom` лише різала смугу навпіл і називала це збільшенням;
    масштаб лишався 1.000, а весь ефект зводився до того, що вужчий тайл не
    потрапляв під даунскейл моделі. Тепер збільшуємо явно, LANCZOS.
    """
    if im.width >= target_w:
        return im
    k = target_w / im.width
    return im.resize((target_w, max(1, int(im.height * k))), Image.Resampling.LANCZOS)


def _bands(height: int, top: int, rows: int, overlap: float) -> list[tuple[int, int]]:
    """Горизонтальні смуги з перекриттям, що покривають [top, height) без дір."""
    usable = height - top
    if rows < 1:
        return [(top, height)]
    step = usable / rows
    band_h = step * (1 + overlap)
    out: list[tuple[int, int]] = []
    for i in range(rows):
        y0 = int(top + i * step - (band_h - step) / 2)
        y1 = int(y0 + band_h)
        out.append((max(top, y0), min(height, y1)))
    return out


def cached_tiles(src: Path, out_dir: Path) -> list[Tile] | None:
    """Готова нарізка цього скана, якщо вона є і не застаріла.

    Нарізка — чистий детермінований похідний артефакт, і перерізати 476
    розворотів після кожного обриву сесії безглуздо. Кеш вважається дійсним,
    поки маніфест новіший за сам скан і всі перелічені файли на місці.
    """
    manifest = out_dir / "_tiles.json"
    if not manifest.is_file():
        return None
    try:
        if manifest.stat().st_mtime < src.stat().st_mtime:
            return None
        data = json.loads(manifest.read_text(encoding="utf-8"))
        tiles = [Tile(name=t["name"], kind=t["kind"], box=tuple(t["box"]),
                      size=tuple(t["size"]), hint=t.get("hint", ""))
                 for t in data.get("tiles", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not tiles or any(not (out_dir / t.name).is_file() for t in tiles):
        return None
    return tiles


def default_out_dir() -> Path:
    """Тайли — регенерований кеш: `<простір>/data/cache/tiles`.

    У просторі, а не в системному temp: нарізка великої книги — це гігабайти,
    і людина мусить бачити, де вони лежать і що їх можна прибрати. Кеш, бо
    `_tiles.json` звіряється з часом зміни скана, тож видалення теки коштує
    лише повторної нарізки.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        return workspace().data / "cache" / "tiles"
    except WorkspaceError:
        # Без простору (виклик із чужого коду чи тесту) лишається temp — але це
        # запасний шлях, а не місце, куди складають роботу.
        return Path(tempfile.gettempdir()) / "nyshporka" / "tiles"


def slice_scan(
    src: Path,
    out_dir: Path,
    rows: int | None = None,
    overlap: float | None = None,
    quality: int | None = None,
    zoom: bool | None = None,
    cfg: dict[str, Any] | None = None,
    refresh: bool = False,
    only: set[str] | None = None,
) -> list[Tile]:
    """Нарізати один скан. Повертає манифест тайлів (він же пишеться в `_tiles.json`).

    Геометрія береться з профілю (`cfg` — секція `tiles`), бо щільність рядків
    на аркуші сильно різна: у сповідному розписі їх утричі більше, ніж у
    метриці, і шести смуг там замало. Явні аргументи перекривають профіль.

    `zoom=True` додатково ділить кожну смугу лівої половини навпіл по ширині —
    для сторінок, де скоропис не дається на звичайному масштабі.

    `only={"head"}` ріже лише перелічені види тайлів. Мапі років потрібен сам
    заголовок і більше нічого — різати заради неї всі чотирнадцять тайлів
    означає вчетверо довшу нарізку й десятки зайвих гігабайтів на диску.
    """
    cfg = cfg or {}
    if not refresh:
        cached = cached_tiles(src, out_dir)
        if cached is not None:
            return cached
    rows = cfg.get("rows", DEFAULT_ROWS) if rows is None else rows
    overlap = cfg.get("overlap", DEFAULT_OVERLAP) if overlap is None else overlap
    quality = cfg.get("quality", 92) if quality is None else quality
    zoom = cfg.get("zoom", False) if zoom is None else zoom
    split = cfg.get("split", SPLIT)
    split_overlap = cfg.get("split_overlap", SPLIT_OVERLAP)
    margin = cfg.get("margin", MARGIN)
    head_frac = cfg.get("head_frac", HEAD_FRAC)
    preview_max = cfg.get("preview_max", PREVIEW_MAX)
    zoom_target = cfg.get("zoom_target_px", ZOOM_TARGET_PX)

    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as raw:
        im = _prep(raw.convert("RGB"))
    w, h = im.size
    mx, my = int(w * margin), int(h * margin)
    tiles: list[Tile] = []

    def save(img: Image.Image, name: str, kind: str,
             box: tuple[int, int, int, int], hint: str) -> None:
        if only and kind not in only:
            return
        img.save(out_dir / f"{name}.jpg", quality=quality, subsampling=0)
        tiles.append(Tile(name=f"{name}.jpg", kind=kind, box=box, size=img.size, hint=hint))

    # 1. оглядовий — рахувати записи й бачити структуру розвороту, не читати текст
    box = (mx, my, w - mx, h - my)
    prev = im.crop(box)
    prev.thumbnail((preview_max, preview_max))
    save(prev, "full", "full", box, "весь розворот: скільки актів, де межі, чи є підсумок")

    # 2. верхівка — друкований заголовок із дописаним від руки роком
    box = (mx, my, w - mx, int(h * head_frac))
    save(im.crop(box), "head", "head", box, "заголовок: рік і частина книги (Н/Ш/С)")

    lx1 = int(w * (split + split_overlap))
    rx0 = int(w * (split - split_overlap))
    top = int(h * head_frac * 0.75)

    for i, (y0, y1) in enumerate(_bands(h - my, top, rows, overlap), start=1):
        box = (mx, y0, lx1, y1)
        save(im.crop(box), f"L{i}", "left", box,
             "ліва сторінка: №, дати, ім'я, батьки, восприємники")
        if zoom:
            mid = mx + (lx1 - mx) // 2
            pad = (lx1 - mx) // 12
            for half, (x0, x1) in enumerate((
                    (mx, min(lx1, mid + pad)), (max(mx, mid - pad), lx1)), start=1):
                box_z = (x0, y0, x1, y1)
                save(_upscale(_stretch(im.crop(box_z)), zoom_target),
                     f"L{i}z{half}", "left", box_z,
                     "половина смуги, збільшена й з розтягнутим контрастом")
        box = (rx0, y0, w - mx, y1)
        save(im.crop(box), f"R{i}", "right", box,
             "права сторінка: причт, поручителі, рукоприкладство")

    (out_dir / "_tiles.json").write_text(
        json.dumps({"src": str(src), "size": [w, h],
                    "tiles": [asdict(t) for t in tiles]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    return tiles


def scan_files(case_dir: Path, scans: list[str] | None = None) -> list[Path]:
    """Файли сканів справи: усі або перелічені (голі імена, як у сховищі)."""
    if not case_dir.is_dir():
        raise FileNotFoundError(f"теки сканів немає: {case_dir}")
    if scans:
        out = []
        for s in scans:
            p = case_dir / s
            if not p.is_file():                       # дозволяємо «0022» без розширення
                cand = [q for q in case_dir.iterdir()
                        if q.stem == Path(s).stem and q.suffix.lower() in _IMG_EXT]
                if not cand:
                    raise FileNotFoundError(f"скана «{s}» немає в {case_dir}")
                p = cand[0]
            out.append(p)
        return out
    return sorted(p for p in case_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in _IMG_EXT)


def expand_range(spec: str) -> list[str]:
    """«0022-0024,0461» → ['0022','0023','0024','0461'] (ширина нулів зберігається)."""
    out: list[str] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if "-" in part and all(s.strip().isdigit() for s in part.split("-", 1)):
            a, b = (s.strip() for s in part.split("-", 1))
            width = max(len(a), len(b))
            out.extend(str(n).zfill(width) for n in range(int(a), int(b) + 1))
        else:
            out.append(part)
    return out
