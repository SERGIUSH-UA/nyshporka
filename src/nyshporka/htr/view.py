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
_RENDER_CACHE: dict[tuple[str, str], bytes] = {}
_RENDER_CACHE_MAX = 4


def _cached_render(run: str, page: str,
                   make: Callable[[], bytes]) -> bytes:
    key = (run, page)
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
    orient = int((meta.get("pages") or {}).get(page, {}).get("orient") or 0)
    for case_dir in _case_dirs(run, meta):
        def make(d: Path = case_dir) -> bytes:
            return P.render(d, frames, page)

        try:
            png = _cached_render(run, page, make)
        except P.PdfPageError:
            continue                      # інша тека — інша спроба
        except Exception:
            continue
        with Image.open(io.BytesIO(png)) as raw:
            im = raw.convert("RGB")
        return im.rotate(-orient, expand=True) if orient else im

    raise ViewError(
        f"сторінку «{page}» показати нічим: готового скану немає, а зі справи "
        f"її не відтворити (немає PDF, або кількість сторінок не сходиться з "
        f"числом кадрів прогону). Показати не той аркуш гірше, ніж не показати.")


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
                    note="прогін не зберіг рамок рядків — показано всю сторінку")
    if not 0 <= line < len(boxes):
        raise ViewError(f"рядка {line} немає: у сторінці їх {len(boxes)}")

    x0, y0, x1, y1 = (int(v) for v in boxes[line][:4])
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


def _png(im: Any) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
