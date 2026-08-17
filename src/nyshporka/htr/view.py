"""👁 Гортач: показати, ЗВІДКИ взявся рядок тексту.

Правило, на якому тримається весь пошук роду: **виявити ≠ перевірити**. Машина
подає кандидата, вирішує око — і другий рушій тут не суддя, бо ознака в
пікселях. Доти, доки дивитись нічим, кожна знахідка лишається здогадом.

🔴 Вартість перегляду рахується ГЕОМЕТРІЄЮ, а не бажанням. Ціла сторінка для
моделі коштує близько 1550 токенів, рядок 1600×190 — близько 400. Різниця в
чотири рази на кожну звірку, а звірок за сеанс бувають десятки. Тому дефолт —
РЯДОК, а сторінка вимагає явного слова.

🔴 Рамка домальовується, коли беремо рядок із запасом. Без неї модель бачить
три рядки й не знає, який із них оцінює, — і чесно оцінює не той.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

Region = Literal["line", "page"]

#: Скільки пікселів навколо рядка лишати. Рядок скоропису має виносні елементи
#: (петлі «д», «р», «у»), і впритул обрізаний рядок читається гірше за оригінал.
DEFAULT_PAD = 24

#: Стеля ширини вирізки рядка. Ширше не робить читабельнішим, лише дорожчим.
LINE_MAX_W = 1600
#: Стеля сторони для повної сторінки.
PAGE_MAX = 1400


class ViewError(RuntimeError):
    """Показати нема чого — з поясненням, чому саме."""


@dataclass(frozen=True)
class Shot:
    """Готове зображення + що на ньому."""

    png: bytes
    width: int
    height: int
    region: Region
    line: int | None = None
    text: str = ""
    note: str = ""

    @property
    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode("ascii")

    def as_dict(self) -> dict[str, Any]:
        return {"region": self.region, "line": self.line, "width": self.width,
                "height": self.height, "text": self.text, "note": self.note}


def _open_rotated(src: Path, orient: int) -> Any:
    from PIL import Image

    with Image.open(src) as raw:
        im = raw.convert("RGB")
    if orient:
        # 🔴 Той самий кут, яким користувався OCR. Рамки рядків лежать у
        # координатах ПОВЕРНУТОГО зображення; показати неповернуте означає
        # покласти рамку на чуже місце — і виглядатиме це як «модель марить».
        im = im.rotate(-orient, expand=True)
    return im


#: Останні відрендерені сторінки: (run, page) → PNG.
#: 🔴 Кеш тут не оптимізація «про всяк випадок». Гортач кличуть ПОРЯДКОВО —
#: людина клацає рядок за рядком однієї сторінки, — а рендер сторінки з PDF на
#: 1200 аркушів коштує близько шести секунд. Без кешу перегляд двадцяти рядків
#: перетворюється на дві хвилини очікування, і ним просто не користуються.
#: Розмір навмисно малий: сторінка важить мегабайти.
_RENDER_CACHE: dict[tuple[str, str, str], bytes] = {}
_RENDER_CACHE_MAX = 4


def _cached_render(run: str, page: str, case_dir: str,
                   make: Callable[[], bytes]) -> bytes:
    # 🔴 Тека — ЧАСТИНА ключа. Справа часто лежить у кількох теках (оригінали,
    # зменшені копії для хмари, посторінковий рендер), і `_page_image` пробує їх
    # по черзі. Без теки в ключі друга ітерація дістала б із кешу сторінку
    # ПЕРШОЇ теки — тобто рівно те, від чого захищається весь цей модуль:
    # чужий аркуш під правильним підписом.
    key = (run, page, case_dir)
    hit = _RENDER_CACHE.get(key)
    if hit is not None:
        return hit
    png: bytes = make()
    if len(_RENDER_CACHE) >= _RENDER_CACHE_MAX:
        _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
    _RENDER_CACHE[key] = png
    return png


def _page_image(run: str, page: str) -> Any:
    """Зображення сторінки: готовий скан або рендер зі справи-PDF.

    🔴 Другий шлях не «про всяк випадок». Хмарний прогін розгортає PDF у кадри
    на орендованому боксі; на диску лишається текст, а кадрів немає ніде. Без
    рендера на вимогу гортач сліпий саме на найбільших справах — тих, які
    взагалі мають сенс читати машиною.
    """
    from PIL import Image

    from nyshporka import htr_store as S
    from nyshporka.htr import pdfpage as P

    got = S.resolve_scan(run, page)
    if got is not None:
        src, orient = got
        return _open_rotated(src, orient)

    meta = S.load_meta(run) or {}
    frames = list(meta.get("pages") or {})
    # Скільки кадрів мала СПРАВА, а не скільки прочитано. Частковий прогін без
    # цього знаменника не міг довести відповідність — див. `pdfpage.mapping`.
    total = meta.get("frames_total")
    total = int(total) if isinstance(total, (int, float, str)) and str(total).isdigit() else None
    orient = int((meta.get("pages") or {}).get(page, {}).get("orient") or 0)
    # 🔴 Причини відмови збираємо, а не ковтаємо. `mapping()` формулює чотири
    # РІЗНІ причини поіменно («немає PDF», «сторінок 3772, а кадрів 3771»,
    # «нумерація не щільна»), а до людини доїжджало одне узагальнене «або…, або…»
    # — тобто підказка, з якою нічого не зробиш. Ціна тут не косметична: за
    # кожною з причин стоїть інша дія (докласти PDF, перепрогнати, прив'язати
    # справу), і не назвати її означає лишити людину гадати.
    why: list[str] = []
    tried = 0
    for case_dir in _case_dirs(run, meta):
        tried += 1

        def make(d: Path = case_dir) -> bytes:
            return P.render(d, frames, page, total=total)

        try:
            png = _cached_render(run, page, str(case_dir), make)
        except P.PdfPageError as exc:
            why.append(f"{case_dir.name}: {exc}")
            continue                      # інша тека — інша спроба
        except Exception as exc:
            why.append(f"{case_dir.name}: {type(exc).__name__}: {exc}")
            continue
        with Image.open(io.BytesIO(png)) as raw:
            im = raw.convert("RGB")
        return im.rotate(-orient, expand=True) if orient else im

    if not tried:
        raise ViewError(
            f"сторінку «{page}» показати нічим: готового скану немає, і теки "
            f"справи цей прогін не називає (у меті або чужий шлях, або нічого). "
            f"Прив'язати прогін до справи: nysh cases bind {run} <ключ>")
    raise ViewError(
        f"сторінку «{page}» показати нічим: готового скану немає, а зі справи "
        f"її не відтворити. Показати не той аркуш гірше, ніж не показати.\n  "
        + "\n  ".join(why))


def _case_dirs(run: str, meta: dict[str, Any]) -> list[Path]:
    """Теки, де може лежати матеріал справи — з мети й з реєстру."""
    from nyshporka import htr_store as S

    out: list[Path] = []
    base = S.under_raw(meta.get("case_dir") or "")
    if base is not None and base.is_dir():
        out.append(base)
    for d in S._case_dirs_via_registry(run):
        if d not in out:
            out.append(d)
    return out


def shot(run: str, page: str, *, line: int | None = None,
         region: Region = "line", pad: int = DEFAULT_PAD,
         annotate: bool = True) -> Shot:
    """Зображення сторінки або одного її рядка.

    `line` — номер рядка в `.txt` прогону (з нуля); він же індекс рамки.
    """
    from PIL import ImageDraw

    from nyshporka import htr_store as S

    im = _page_image(run, page)

    geo = S.page_lines(run, page) or {}
    boxes = geo.get("boxes") or []
    # `read_page_text` віддає ГОТОВИЙ перелік рядків (ключ `lines`), а не один
    # рядок тексту. Індекс тут == індекс рамки: вирівнювання гарантує прогін.
    text_lines: list[str] = list((S.read_page_text(run, page) or {}).get("lines") or [])

    if region == "page" or line is None:
        note = ""
        if line is not None:
            note = "рамок рядків у цьому прогоні немає — показано всю сторінку"
        im.thumbnail((PAGE_MAX, PAGE_MAX))
        return Shot(png=_png(im), width=im.width, height=im.height,
                    region="page", line=line,
                    text="\n".join(text_lines), note=note)

    if not boxes:
        # Прогони до 2026-08-09 рамок не писали. Це не помилка — але й мовчки
        # віддати сторінку замість рядка не можна: вартість інша вчетверо.
        im.thumbnail((PAGE_MAX, PAGE_MAX))
        return Shot(png=_png(im), width=im.width, height=im.height,
                    region="page", line=line, text="\n".join(text_lines),
                    note=geo.get("why")
                    or "прогін не зберіг рамок рядків — показано всю сторінку")
    if not 0 <= line < len(boxes):
        raise ViewError(f"рядка {line} немає: у сторінці їх {len(boxes)}")

    # 🔴 Рамку МАСШТАБУЄМО під фактичне зображення, і це не запобіжник «на
    # всяк випадок». Рамки лежать у координатах того зображення, яке читав
    # прогін (`size` у `.lines.json`), а показуємо ми або той самий скан
    # (масштаб 1.0), або рендер із PDF — а він завжди виходить шириною
    # `pdfpage.DEFAULT_WIDTH`. Розійшлися ширини — і кроп рядка з'їжджає:
    # людина бачить сусідній рядок, вважаючи, що бачить свій. Тобто канал
    # «рендер із PDF» був коректний лише для цілої сторінки.
    kx, ky = _scale(geo.get("size"), im)
    x0, y0, x1, y1 = (int(v) for v in boxes[line][:4])
    x0, x1 = int(x0 * kx), int(x1 * kx)
    y0, y1 = int(y0 * ky), int(y1 * ky)
    box = (max(0, x0 - pad), max(0, y0 - pad),
           min(im.width, x1 + pad), min(im.height, y1 + pad))
    crop = im.crop(box)
    if annotate and pad:
        # 🔴 Без рамки модель бачить кілька рядків і не знає, який оцінює.
        # Саме тому `pad` і `annotate` йдуть парою.
        d = ImageDraw.Draw(crop)
        d.rectangle([x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]],
                    outline=(220, 40, 40), width=3)
    if crop.width > LINE_MAX_W:
        crop.thumbnail((LINE_MAX_W, LINE_MAX_W))
    txt = text_lines[line] if line < len(text_lines) else ""
    return Shot(png=_png(crop), width=crop.width, height=crop.height,
                region="line", line=line, text=txt)


def _scale(size: Any, im: Any) -> tuple[float, float]:
    """Коефіцієнти «координати прогону → пікселі показаного зображення».

    `size` — розмір зображення, на якому прогін рахував рамки. Немає його
    (старі `.lines.json`) — лишаємо 1.0: гадати масштаб не можна, а рівний
    масштаб хоча б відповідає найчастішому випадку, коли показуємо той самий
    скан, який і читали.
    """
    try:
        w, h = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        return 1.0, 1.0
    if w <= 0 or h <= 0:
        return 1.0, 1.0
    return im.width / w, im.height / h


def _png(im: Any) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
