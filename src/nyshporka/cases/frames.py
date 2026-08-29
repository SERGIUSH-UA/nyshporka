"""🖼 Подивитись на справу — просто так, без жодного прогону.

Найпростіше, чого чекають від застосунку, і чого в ньому не було: відкрити
завантажену справу й погортати аркуші. Досі побачити скан можна було лише
через прогін: спершу прочитай справу рушієм — годину чи ніч, — і аж тоді
дивись. Тобто щоб глянути на те, що вже лежить на диску, треба було спершу
його обробити.

🔴 Прогін тут не потрібен, але й не забороняється. Межа проходить саме так:
перегляд мусить працювати на справі, якої ще ніхто не читав, — інакше
повертається та сама вада, від якої модуль написаний. А коли прочитане вже є,
ховати його безглуздо: кадр і сторінка прогону — це одне ім'я файлу, тож текст
лягає на аркуш без жодного зіставлення.

Тому перелік аркушів каже, чи є прогони, і лишає рішення викликачеві; сам він
тексту не тягне й без нього працює однаково.

Два роди матеріалу, і обидва трапляються самі по собі:

  **кадри**  — зображення в теці справи, як їх віддав архів;
  **PDF**    — той самий матеріал одним файлом (частина архівів інакше не дає).

Коли є і те, і те, показуються кадри: вони і є те, що читатиме рушій, а
сторінки PDF — інший рендер того самого, і плутати їх означає показувати не
той аркуш під тим самим номером.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Розширення, які вважаємо кадром. Той самий перелік, що в раннера: показувати
#: треба рівно те, що він читатиме.
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

#: Ширина показу за замовчуванням. Архівний скан буває 4000 px і важить
#: мегабайти; на екрані стільки не видно, а платить за них людина часом.
DEFAULT_WIDTH = 1400

#: Стеля запиту. Понад це ширина вже нічого не додає оку, зате рендер PDF
#: росте квадратично.
MAX_WIDTH = 3000


class FrameError(RuntimeError):
    """Показати нема чого — з поясненням, чому саме."""


@dataclass(frozen=True)
class Frame:
    """Один аркуш справи."""

    #: Чим його просити назад. Для кадру — ім'я файлу; для PDF — `pdf:N`,
    #: де N — наскрізний номер сторінки з одиниці.
    id: str
    label: str
    kind: str          # image | pdf


def case_dir(case: str) -> Path:
    """Тека справи з гардом шляху.

    🔴 Той самий гард, що й у решті застосунку (`htr_store.under_raw`): шлях
    приходить із запиту браузера, і без нього сюди можна попросити будь-що з
    диска. Дозволені корені оголошені простором, а не вгадуються.
    """
    from nyshporka import htr_store as S

    raw = (case or "").strip()
    if not raw:
        raise FrameError("не сказано, яку справу показувати")
    got = S.under_raw(raw)
    if got is None or not got.is_dir():
        # ⚠ Порада називає ЕКРАН, а не команду. Коренями справ керує розділ
        # «🌳 Корені справ» у налаштуваннях — кнопками, обома напрямками, — а
        # повідомлення про це мовчало й слало в термінал того, хто про термінал
        # і не знає.
        raise FrameError(
            f"теки «{raw}» немає серед матеріалів простору. Показувати можна "
            f"лише те, що лежить у `data/raw` або в оголошених коренях — "
            f"додати корінь можна в «Налаштування → Корені справ»")
    return got


def images(d: Path) -> list[Path]:
    """Кадри прямо в теці, у порядку імені.

    Підтеки не обходяться — так само, як їх не обходить раннер. Тека з
    підтеками для нього порожня, і показувати те, чого він не прочитає, було б
    обіцянкою, якої застосунок не дотримає.
    """
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir()
                   if p.is_file() and p.suffix.lower() in IMG_EXT),
                  key=lambda p: p.name)


def listing(case: str) -> dict[str, Any]:
    """Аркуші справи + чим вони є.

    Порожня відповідь тут завжди має причину: тека порожня, кадри в підтеках,
    або матеріал лише в PDF, який нічим відкрити.
    """
    from nyshporka.htr import pdfpage

    d = case_dir(case)
    imgs = images(d)
    if imgs:
        return {"case": str(d), "kind": "image", "total": len(imgs),
                "pdfs": [p.name for p in pdfpage.case_pdfs(d)],
                "runs": runs_for(case),
                "frames": [Frame(p.name, p.name, "image").__dict__ for p in imgs]}

    pdfs = pdfpage.case_pdfs(d)
    if not pdfs:
        nested = [x.name for x in d.iterdir() if x.is_dir()][:4] if d.is_dir() else []
        why = ("у теці немає ні кадрів, ні PDF")
        if nested:
            why += (f"; кадри можуть бути в підтеках ({', '.join(nested)}) — "
                    f"перегляд не рекурсивний, як і читання")
        raise FrameError(why)

    try:
        counts = pdfpage.page_counts(pdfs)
    except Exception as exc:
        raise FrameError(
            f"PDF справи не відкривається ({type(exc).__name__}: {exc}). "
            f"Малювати сторінки PDF нема чим — це окрема частина застосунку; "
            f"увімкніть її в «Налаштування → Частини застосунку»") from None

    frames: list[dict[str, Any]] = []
    no = 0
    for path, n in zip(pdfs, counts, strict=True):
        for i in range(n):
            no += 1
            label = f"{path.name} · {i + 1}" if len(pdfs) > 1 else f"{no}"
            frames.append(Frame(f"pdf:{no}", label, "pdf").__dict__)
    # 🔴 Прогонів тут немає навмисно, хоч вони могли й бути. Кадрів на диску
    # немає, сторінки PDF нумеруються наскрізно, а прогін адресує сторінки
    # іменами кадрів — прямого збігу не існує. Показати текст «на око» означало
    # б покласти чужий рядок на аркуш, і виглядало б це переконливо.
    return {"case": str(d), "kind": "pdf", "total": len(frames),
            "pdfs": [p.name for p in pdfs], "runs": [], "frames": frames}


def runs_for(case: str) -> list[dict[str, Any]]:
    """Прогони, що прочитали цю справу — найповніший перший.

    🔴 Кадр і сторінка прогону — це одне ім'я файлу, тож текст лягає на аркуш
    без жодного зіставлення. Саме тому перегляд справи може показати
    прочитане, не будуючи власної відповідності: її просто немає, збіг
    прямий.

    ⚠ Для справи-PDF це не так: там кадрів на диску немає, а сторінки
    нумеруються наскрізно. Тому виклик не обіцяє тексту всім — рішення
    лишається за викликачем, який знає вид матеріалу.
    """
    from nyshporka import htr_store as S

    try:
        runs = S.find_runs_for_case(case)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in runs:
        name = str(r.get("name") or "")
        if not name:
            continue
        try:
            alt = S.voice_pair(name)
        except Exception:
            alt = None
        out.append({"name": name, "engine_id": r.get("engine_id") or "",
                    "engine_ids": r.get("engine_ids") or [],
                    "model": r.get("model") or "",
                    "pages_done": int(r.get("pages_done") or 0),
                    "done": bool(r.get("done")),
                    # Другий голос рахується тут, а не в браузері: він
                    # тримається на тому, що обидва прогони ділять кеш
                    # сегментації, і знає це лише сховище.
                    "alt": alt or ""})
    # Найповніший першим: з двох прогонів однієї справи корисніший той, що
    # дочитав далі — саме він покриє більше аркушів текстом.
    out.sort(key=lambda r: (-r["pages_done"], r["name"]))
    return out


def _locate_pdf(d: Path, no: int) -> tuple[Path, int]:
    """Наскрізний номер сторінки → (файл, індекс у ньому)."""
    from nyshporka.htr import pdfpage

    pdfs = pdfpage.case_pdfs(d)
    counts = pdfpage.page_counts(pdfs)
    left = no
    for path, n in zip(pdfs, counts, strict=True):
        if left <= n:
            return path, left - 1
        left -= n
    raise FrameError(f"сторінки {no} у справі немає: усього {sum(counts)}")


def render(case: str, frame: str, width: int = DEFAULT_WIDTH) -> dict[str, Any]:
    """PNG аркуша + його розмір, готове для браузера.

    ⚠ Ширина обрізається, а не приймається як є: архівний скан буває 4000 px,
    і віддати його цілим означає пересилати мегабайти на кожен крок гортання.
    Збільшення робить браузер — для читання очима цього досить, а коли треба
    роздивитись, є окремий запит на повну ширину.
    """
    from PIL import Image

    d = case_dir(case)
    w = max(200, min(MAX_WIDTH, int(width or DEFAULT_WIDTH)))
    frame = (frame or "").strip()
    if not frame:
        raise FrameError("не сказано, який аркуш показувати")

    if frame.startswith("pdf:"):
        from nyshporka.htr import pdfpage

        try:
            no = int(frame.split(":", 1)[1])
        except ValueError:
            raise FrameError(f"незрозумілий аркуш «{frame}»") from None
        path, index = _locate_pdf(d, no)
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise FrameError(
                "сторінки PDF нічим відрендерити — цю частину застосунку "
                "не встановлено. «Налаштування → Частини застосунку»") from None
        doc = pdfium.PdfDocument(str(path))
        try:
            page = doc[index]
            scale = max(0.5, min(6.0, w / max(1.0, page.get_width())))
            im = page.render(scale=scale).to_pil().convert("RGB")
        finally:
            doc.close()
        _ = pdfpage  # тримаємо імпорт явним: він і резолвить перелік файлів
    else:
        # 🔴 Ім'я файлу, а не шлях: інакше сюди можна попросити будь-що з
        # диска, обійшовши гард теки. Порівнюємо з переліком, а не склеюємо.
        want = Path(frame).name
        src = next((p for p in images(d) if p.name == want), None)
        if src is None:
            raise FrameError(f"кадру «{want}» у справі немає")
        with Image.open(src) as raw:
            im = raw.convert("RGB")
        if im.width > w:
            im = im.resize((w, round(im.height * w / im.width)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=86, optimize=True)
    data = buf.getvalue()
    return {"frame": frame, "width": im.width, "height": im.height,
            "bytes": len(data),
            "image": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")}
