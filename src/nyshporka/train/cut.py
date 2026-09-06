"""✂️ Кропи рядків із прогону — набір для розмітки без окремої сегментації.

Прогін уже знає геометрію кожного рядка (`<стор>.lines.json`: рамки й
полігони, вирівняні з рядками `<стор>.txt`). Тому набір робиться З ПРОГОНУ,
а не з нової нарізки: індекс кропа = індекс рядка прогону, і текст прогону
стає першим голосом задарма, без копіювання.

Два способи вирізати, за спаданням довіри:

1. **Кеш сегментації** через гостя `guest/cut_runner.py` у середовищі рушіїв —
   той самий `extract_polygons` з випрямленням рядка, що й на інференсі.
   Приймач — поштучний збіг рамок із `.lines.json`.
2. **Полігон** самим пакетом (PIL): маска полігону на білому тлі, вирізка за
   рамкою. Кроп трохи інший, ніж бачив рушій (без випрямлення), і мета це
   каже (`crop_source: "poly"`), а збірник корпусу — попереджає про частку.

🔴 Розмір зображення звіряється з `size` у `.lines.json`: рамки лежать у
координатах того зображення, яке читав прогін, і рендер PDF іншої ширини дав
би кроп сусіднього рядка — помилку, якої око не ловить.
"""
from __future__ import annotations

import json
import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, WorkspaceError, workspace
from nyshporka.htr import layout as HL
from nyshporka.train import sets as S
from nyshporka.utils.atomic import read_json, write_json

CUT_META_VERSION = 3

#: Нижче цієї частки медіани сторінка вважається провалом сегментації —
#: калібровано на сповідних розписах, де 7 рядків замість 82 виявились лише
#: після нарізки й з'їли очний прохід.
SEG_FAIL_RATIO = 0.45
SEG_LOW_RATIO = 0.70
#: Менше стільки рядків — титулка, підсумок або порожній аркуш.
MIN_LINES = 25
#: Скільки перших кадрів пропускати при автовідборі: обкладинка, титул, опис.
SKIP_FIRST = 8


class CutError(ValueError):
    """Нема з чого різати або нема куди."""


@dataclass
class PageCut:
    page: str
    key: str = ""             # ключ сторінки в меті прогону (ім'я файла)
    n: int = 0
    source: str = ""          # seg_cache | poly
    size: list[int] = field(default_factory=list)
    orient: int = 0
    boxes: list[Any] = field(default_factory=list)
    polys: list[Any] = field(default_factory=list)
    widths: list[int] = field(default_factory=list)
    src: str = ""
    error: str = ""
    note: str = ""

    def as_meta(self) -> dict[str, Any]:
        return {"n_lines": self.n if not self.error else -1, "key": self.key or self.page,
                "crop_source": self.source,
                "size": self.size, "orient": self.orient, "boxes": self.boxes,
                "polys": self.polys, "widths": self.widths, "src": self.src,
                "error": self.error, "note": self.note}


# ── прогін як джерело ────────────────────────────────────────────────────────
def run_dir(run: str, ws: Workspace | None = None) -> Path:
    w = ws if ws is not None else workspace()
    base = w.htr_reports
    if not run or "/" in run or "\\" in run or run.startswith("."):
        raise CutError(f"неприпустиме ім'я прогону: {run!r}")
    d = (base / run).resolve()
    if d.parent != base.resolve() or not d.is_dir():
        raise CutError(f"прогону «{run}» немає в {base}")
    return d


def run_meta(run: str, ws: Workspace | None = None) -> dict[str, Any]:
    got = read_json(run_dir(run, ws) / "_htr_meta.json", default=None)
    if not isinstance(got, dict):
        raise CutError(f"прогін «{run}» без _htr_meta.json — це не прогін Нишпорки")
    return got


def page_text(run: str, page: str, ws: Workspace | None = None) -> list[str] | None:
    f = run_dir(run, ws) / f"{page}.txt"
    if not f.is_file():
        return None
    return f.read_text(encoding="utf-8", errors="replace").splitlines()


def page_geometry(run: str, page: str, ws: Workspace | None = None) -> dict[str, Any] | None:
    """`.lines.json` сторінки — своєї теки або основного прогону гілки голосу."""
    f, _why = HL.resolve_geometry(run_dir(run, ws), page)
    if f is None:
        return None
    got = read_json(f, default=None)
    return got if isinstance(got, dict) and got.get("boxes") else None


def page_keys(meta: dict[str, Any]) -> dict[str, str]:
    """Стем сторінки → ключ у меті прогону.

    🔴 Мета прогону ключує сторінки ІМЕНЕМ ФАЙЛА (`0003.JPG`), а текст і рамки
    лежать за стемом (`0003.txt`, `0003.lines.json`). Набір живе стемами — так
    названо теки кропів і так люди звуть сторінки, — а до мети й до скана
    ходить через цю мапу.
    """
    return {Path(k).stem: k for k in (meta.get("pages") or {})}


def image_key(cut_page: dict[str, Any], page: str) -> str:
    """Ключ сторінки для показу зображення — з мети нарізки або сам стем."""
    return str((cut_page or {}).get("key") or page)


def pick_pages(meta: dict[str, Any], n: int, *, skip_first: int = SKIP_FIRST) -> list[str]:
    """Автовідбір сторінок під розмітку — за числом символів у прогоні.

    Той самий принцип, що відбір за чорнилом у дослідницькому конвеєрі, але
    без зображень: символи в декоді вже порахував прогін. Беруться сторінки з
    70–97-го процентиля (щільні, але не таблиці-простирадла), рознесені по
    обсягу справи, з пропуском перших кадрів (обкладинка, титул).
    """
    pages = meta.get("pages") or {}
    rows = [(Path(pg).stem, int((info or {}).get("chars") or 0),
             int((info or {}).get("lines") or 0))
            for pg, info in sorted(pages.items())]
    rows = [r for r in rows if r[2] >= MIN_LINES]
    body = rows[skip_first:] if len(rows) > skip_first + n else rows
    if not body:
        return []
    ys = sorted(r[1] for r in body)
    lo, hi = ys[int(0.70 * (len(ys) - 1))], ys[int(0.97 * (len(ys) - 1))]
    ok = [r for r in body if lo <= r[1] <= hi] or body
    if n >= len(ok):
        return [r[0] for r in ok]
    step = len(ok) / n
    return [ok[int(i * step)][0] for i in range(n)]


# ── вирізка ──────────────────────────────────────────────────────────────────
def crop_by_poly(im: Any, box: list[int], poly: list[list[int]] | None) -> Any:
    """Вирізка рядка полігоном; без полігону — рамкою.

    🔴 Поза полігоном — ЧОРНЕ, а не біле: так ріже kraken (`extract_polygons`),
    на таких кропах учились бойові ваги, і так само рахує частку чорнила
    `gate.ink_fraction` (чорне тло виключається). Біле тло дало б кроп, якого
    рушій на читанні не бачить.
    """
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = (int(v) for v in box[:4])
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.width, max(x1, x0 + 1)), min(im.height, max(y1, y0 + 1))
    crop = im.crop((x0, y0, x1, y1))
    if not poly or len(poly) < 3:
        return crop
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).polygon([(int(x) - x0, int(y) - y0) for x, y in poly], fill=255)
    black = Image.new(crop.mode, crop.size, "black")
    black.paste(crop, mask=mask)
    return black


def cut_page_poly(im: Any, geo: dict[str, Any], out: Path) -> PageCut:
    """Кропи всіх рядків сторінки полігоном — фолбек пакета без рушіїв."""
    boxes = geo.get("boxes") or []
    polys = geo.get("polys") or [None] * len(boxes)
    if len(polys) != len(boxes):
        polys = [None] * len(boxes)
    size = [int(v) for v in (geo.get("size") or [im.width, im.height])]
    if size != [im.width, im.height]:
        raise CutError(f"розмір зображення {[im.width, im.height]} не збігається з "
                       f"розміром у прогоні {size}: рамки не накладуться")
    out.mkdir(parents=True, exist_ok=True)
    widths: list[int] = []
    n = 0
    for i, (box, poly) in enumerate(zip(boxes, polys, strict=True)):
        if not box:
            widths.append(0)
            continue
        crop = crop_by_poly(im, box, poly)
        crop.save(out / f"line_{i:03d}.png")
        widths.append(crop.width)
        n += 1
    return PageCut(page=out.name, n=n, source="poly", size=size, boxes=boxes,
                   polys=polys, widths=widths)


def _guest_cut(python: Path, image: Path, orient: int, seg_files: list[Path],
               lines_json: Path, out: Path, enhanced: str = "") -> dict[str, Any]:
    runner = Path(__file__).resolve().parents[1] / "htr" / "runner.py"
    guest = Path(__file__).resolve().parent / "guest" / "cut_runner.py"
    cmd = [str(python), str(guest), "--runner", str(runner), "--image", str(image),
           "--orient", str(orient), "--lines-json", str(lines_json), "--out", str(out)]
    if enhanced:
        cmd += ["--enhanced", enhanced]
    for f in seg_files:
        cmd += ["--seg", str(f)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "why": f"гість не запустився: {exc}"}
    last = (res.stdout or "").strip().splitlines()
    try:
        got = json.loads(last[-1]) if last else {}
    except ValueError:
        got = {}
    if not isinstance(got, dict) or "ok" not in got:
        return {"ok": False, "why": f"гість не відповів (rc={res.returncode}): "
                                    f"{(res.stderr or '')[-300:]}"}
    return got


def _engine_python() -> Path | None:
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    try:
        venv = doc.engine_venv()
    except WorkspaceError:
        return None
    py = E.venv_python(venv)
    return py if py.exists() else None


def _seg_candidates(seg_dir: Path | None, stem: str, orient: int) -> list[Path]:
    if seg_dir is None or not seg_dir.is_dir():
        return []
    return sorted(seg_dir.glob(f"{stem}.o{orient}*.seg.json.gz"))


# ── набір із прогону ─────────────────────────────────────────────────────────
@dataclass
class CutReport:
    set: str
    pages: list[PageCut]
    warnings: list[str] = field(default_factory=list)

    @property
    def n_lines(self) -> int:
        return sum(p.n for p in self.pages if not p.error)


def make_set(run: str, name: str, *, pages: list[str] | None = None, pick: int = 0,
             title: str = "", domain: str = "", case: str = "",
             prefer_engine: bool = True, ws: Workspace | None = None,
             image_of: Any = None) -> CutReport:
    """Нарізати кропи сторінок прогону в набір `name` і зареєструвати його.

    `image_of(run, page)` — постачальник зображення сторінки (тест підставляє
    свій; типово — `htr.view._page_image`, що вміє і скан, і рендер із PDF).
    Дорізати сторінки в наявний набір можна: мета доповнюється, а не
    переписується.
    """
    w = ws if ws is not None else workspace()
    meta = run_meta(run, w)
    reg = S.registry(w)
    if pages is None or not pages:
        if not pick:
            raise CutError("вкажіть сторінки (--pages) або скільки відібрати (--pick)")
        pages = pick_pages(meta, pick)
        if not pages:
            raise CutError(f"у прогоні «{run}» нема сторінок із ≥{MIN_LINES} рядками")
    known = meta.get("pages") or {}
    keys = page_keys(meta)
    pages = [Path(p).stem for p in pages]
    unknown = [p for p in pages if p not in keys]
    if unknown:
        raise CutError(f"прогін «{run}» не має сторінок: {', '.join(unknown[:6])}")

    if reg.exists(name):
        spec = reg.load(name)
        if spec.source_run and spec.source_run != run:
            raise CutError(f"набір «{name}» уже нарізаний з прогону "
                           f"«{spec.source_run}» — інший прогін дасть інші індекси")
    else:
        spec = S.SetSpec(name=name, title=title, case=case or str(meta.get("case_key") or ""),
                         script=str(meta.get("script") or "cyrillic"),
                         source_run=run, domain=domain,
                         drafts=[S.Draft(id=_voice_id(meta), run=run)])
    if title:
        spec.title = title
    if domain:
        spec.domain = domain
    spec.source_run = run
    reg.save(spec)

    crops_root = reg.crops_of(spec)
    crops_root.mkdir(parents=True, exist_ok=True)
    meta_f = crops_root / S.CUT_META_FILE
    cut_meta = read_json(meta_f, default=None)
    if not isinstance(cut_meta, dict) or not isinstance(cut_meta.get("pages"), dict):
        cut_meta = {"version": CUT_META_VERSION, "source_run": run,
                    "case_dir": str(meta.get("case_dir") or ""), "pages": {}}

    if image_of is None:
        from nyshporka.htr import view as V

        image_of = V._page_image
    py = _engine_python() if prefer_engine else None
    seg_dir: Path | None = None
    case_dir = str(meta.get("case_dir") or "")
    if py is not None and case_dir:
        from nyshporka.htr import run as R

        # 🔴 Стемп теки кешу рахується від АБСОЛЮТНОГО шляху справи (так його
        # рахував прогін), а мета прогону зберігає шлях відносно простору.
        # Відносний дав би інший стемп — і кеш «не знаходився б» мовчки.
        cpath = Path(case_dir)
        if not cpath.is_absolute():
            cpath = (w.root / cpath).resolve()
        seg_dir = R.seg_cache_dir(cpath, w.derived)

    rep = CutReport(set=name, pages=[])
    rdir = run_dir(run, w)
    for page in pages:
        key = keys[page]
        pc = PageCut(page=page, key=key,
                     orient=int((known.get(key) or {}).get("orient") or 0))
        geo = page_geometry(run, page, w)
        if geo is None:
            pc.error = "прогін не зберіг рамок рядків цієї сторінки"
            rep.pages.append(pc)
            continue
        try:
            im = image_of(run, key)
        except Exception as exc:
            pc.error = f"зображення: {exc}"
            rep.pages.append(pc)
            continue
        out = crops_root / page
        done = False
        if py is not None:
            geo_f, _ = HL.resolve_geometry(rdir, page)
            src_path = _source_path(run, key, w)
            cands = _seg_candidates(seg_dir, page, pc.orient)
            if geo_f is not None and src_path is not None and cands:
                got = _guest_cut(py, src_path, pc.orient, cands, geo_f, out,
                                 enhanced=str((known.get(key) or {}).get("enhanced") or ""))
                if got.get("ok"):
                    pc.n = int(got.get("n") or 0)
                    pc.source = "seg_cache"
                    pc.size = [int(v) for v in (got.get("size") or geo.get("size") or [])]
                    pc.boxes = geo.get("boxes") or []
                    pc.polys = geo.get("polys") or []
                    pc.widths = [int(b[2]) - int(b[0]) if b else 0 for b in pc.boxes]
                    pc.src = str(src_path)
                    done = True
                else:
                    pc.note = str(got.get("why") or "")
        if not done:
            try:
                got_pc = cut_page_poly(im, geo, out)
            except CutError as exc:
                pc.error = str(exc)
                rep.pages.append(pc)
                continue
            got_pc.page, got_pc.orient, got_pc.key = page, pc.orient, key
            got_pc.note = pc.note
            got_pc.src = pc.src
            pc = got_pc
        cut_meta["pages"][page] = pc.as_meta()
        rep.pages.append(pc)

    write_json(meta_f, cut_meta)
    _warn_on_segmentation(rep)
    poly = [p.page for p in rep.pages if not p.error and p.source == "poly"]
    if poly:
        why = ("середовища рушіїв немає" if py is None
               else "кеш сегментації не дав тих самих рамок")
        rep.warnings.append(f"{len(poly)} стор. вирізано полігоном, а не тим самим "
                            f"випрямленням, що на читанні ({why}); crop_source=poly")
    return rep


def _voice_id(meta: dict[str, Any]) -> str:
    model = str(meta.get("model") or "").strip()
    stem = Path(model).stem if model else ""
    return stem or "run"


def _source_path(run: str, page: str, ws: Workspace) -> Path | None:
    """Файл скану сторінки, якщо він є на диску (кешу сегментації без нього
    нема сенсу: рендер із PDF інший за розміром)."""
    try:
        from nyshporka import htr_store as HS

        got = HS.resolve_scan(run, page)
    except Exception:
        got = None
    if got is None:
        return None
    src, _orient = got
    return Path(src)


def _warn_on_segmentation(rep: CutReport) -> None:
    ns = [p.n for p in rep.pages if not p.error and p.n > 0]
    if not ns:
        return
    med = statistics.median(ns) or 1
    for p in rep.pages:
        if p.error:
            rep.warnings.append(f"{p.page}: {p.error}")
        elif p.n < MIN_LINES:
            rep.warnings.append(f"{p.page}: лише {p.n} рядків — титулка, підсумок або "
                                f"порожній аркуш; на розмітку не годиться")
        elif p.n / med < SEG_FAIL_RATIO:
            rep.warnings.append(f"{p.page}: {p.n} рядків при медіані {med:.0f} — схоже на "
                                f"провал сегментації, глянути аркуш перед розміткою")
        elif p.n / med < SEG_LOW_RATIO:
            rep.warnings.append(f"{p.page}: {p.n} рядків при медіані {med:.0f} — мало, "
                                f"глянути оком")
        if p.note and p.source == "poly":
            rep.warnings.append(f"{p.page}: кеш сегментації не підійшов ({p.note})")


__all__ = ["CutError", "CutReport", "PageCut", "crop_by_poly", "cut_page_poly",
           "make_set", "page_geometry", "page_text", "pick_pages", "run_meta"]
