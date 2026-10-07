"""🇵🇱 Szukaj w Archiwach (`szukajwarchiwach.gov.pl`): одиниця, скан і бік сторінки.

Портал Національного цифрового архіву Польщі (NAC) виставляє скани державних
архівів Польщі: гродські й земські книги, метрики, нотаріат — зокрема фонди
Холмщини, Підляшшя, Перемишля, Любліна. Одиниця має сталу адресу
`https://www.szukajwarchiwach.gov.pl/jednostka/-/jednostka/<id>`, де `<id>` —
внутрішній номер порталу, а не сигнатура. Сигнатура — `35/12/0/1/5`:
архів / фонд (zespół) / підфонд / серія / одиниця; серія буває `-`.

🔴 Скан порталу часто — РОЗВОРОТ книги (гродські книги Красностава: 3500×3002,
дві сторінки). Ріже його той самий детектор згину, що в Сканотеки
(`sources.skanoteka.find_fold`), а карта `_szukaj.json` пов'язує кожну сторінку
з номером скана на порталі — без неї знахідку не повернути до оригіналу.

Ім'я файла в zip «Pobierz»: `<сигнатура через _>_<скан>_<id файла>.jpg`
(`35_12_0_1_5_12_112652371.jpg`, `56_2041_0_-_10_10_19542589.jpg`). Розбирається
справа наліво: останнє — id файла, передостаннє — номер скана, решта — сигнатура.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import urlparse

NAME = "Szukaj w Archiwach"
SOURCE = "szukaj"
HOST = "szukajwarchiwach.gov.pl"
BASE = f"https://www.{HOST}"
PHOTOS = f"https://photos.{HOST}"
#: Карта сканів, яку пише джерело (`sources.szukaj`).
MAP_NAME = "_szukaj.json"

SIDE = {"L": "ліва сторінка", "R": "права сторінка", "-": "кадр цілий"}

_HOST = re.compile(r"^(?:www\.)?szukajwarchiwach\.(?:gov\.)?pl$", re.I)
_UNIT_PATH = re.compile(r"/jednostka/-/jednostka/(\d+)")
_ZIP_NAME = re.compile(r"^(?P<sygn>.+)_(?P<scan>\d+)_(?P<plik>\d+)$")
_PAGE = re.compile(r"^(\d{1,5})(?:_([LR]))?$")


@dataclass(frozen=True)
class Unit:
    """Одиниця на порталі — за внутрішнім номером порталу."""

    id: str

    @property
    def ref(self) -> str:
        """Ідентифікатор зйомки для пулу: `jednostka:<id порталу>`.

        🔴 Та сама форма, що пише `share.publish` з адреси одиниці (05.10.2026
        так залито 18 книг АП Перемишль): інша форма тієї ж зйомки в пулі
        означала б дві різні зйомки, і чужий текст не впізнав би своїх кадрів.
        """
        return f"jednostka:{self.id}"

    @property
    def url(self) -> str:
        return f"{BASE}/jednostka/-/jednostka/{self.id}"

    def list_url(self, page: int, delta: int) -> str:
        """Сторінка переліку сканів: `delta` сканів на сторінку, `page` від 1."""
        return (f"{self.url}?_Jednostka_resetCur=false&_Jednostka_delta={delta}"
                f"&_Jednostka_cur={page}&_Jednostka_id_jednostki={self.id}")


def from_url(url: str) -> Unit | None:
    """Одиниця з адреси порталу; чужий хост чи сторінка фонду — None."""
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "https://" + raw)
    if not _HOST.match(p.netloc.lower()):
        return None
    m = _UNIT_PATH.search(p.path)
    return Unit(m.group(1)) if m else None


def from_ref(ref: str) -> Unit | None:
    """Назад з `jednostka:<id>` (і `unit:<id>`; з префіксом `szukaj:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    kind, _, ident = body.partition(":")
    if kind not in ("jednostka", "unit") or not ident.isdigit():
        return None
    return Unit(ident)


def photo_url(photo: str) -> str:
    """Оригінал скана. `_max` побайтово той самий файл, що в zip «Pobierz»
    (звірено 07.10.2026 на двох сканах книги 3500×3002)."""
    return f"{PHOTOS}/{photo}_max"


def scan_page(photo: str) -> str:
    """Сторінка одного скана на порталі — за хешем зображення (звірено 07.10.2026)."""
    return f"{BASE}/skan/-/skan/{photo}"


def stem(scan: int) -> str:
    """Стем сторінки за номером скана: `0012` — щоб порядок імен був порядком книги."""
    return f"{int(scan):04d}"


def parse_zip_name(name: str) -> tuple[str, int, str] | None:
    """(сигнатура, номер скана, id файла) з імені в zip «Pobierz»; чуже — None."""
    m = _ZIP_NAME.match(PurePath(str(name)).stem)
    if not m:
        return None
    return m.group("sygn").replace("_", "/"), int(m.group("scan")), m.group("plik")


def sygn_parts(sygn: str) -> dict[str, str]:
    """`35/12/0/1/5` → архів, фонд, підфонд, серія, одиниця. Не та форма — порожньо."""
    parts = str(sygn or "").strip().split("/")
    if len(parts) != 5:
        return {}
    return dict(zip(("archiwum", "zespol", "podzespol", "seria", "nr"), parts,
                    strict=True))


def read_map_raw(case_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((Path(case_dir) / MAP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dict(data) if is_map(data) else None


def is_map(data: Any) -> bool:
    return (isinstance(data, dict) and str(data.get("source") or "").lower() == HOST
            and isinstance(data.get("frames"), dict))


def write_map(case_dir: Path, data: dict[str, Any]) -> None:
    """Записати карту атомарно — обрив посеред запису не має лишити її битою."""
    from nyshporka.utils.atomic import write_json

    write_json(Path(case_dir) / MAP_NAME, data, indent=1)


def read_map(case_dir: Path) -> dict[str, tuple[str, str]]:
    """Карта сторінок справи: ім'я сторінки → (номер скана, бік). Карти немає — порожньо."""
    data = read_map_raw(case_dir)
    if data is None:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for key, rec in data["frames"].items():
        if not isinstance(rec, dict):
            continue
        scan = str(rec.get("scan") or key).lstrip("0") or "0"
        for name, page in (rec.get("pages") or {}).items():
            side = str((page or {}).get("side") or "-") if isinstance(page, dict) else "-"
            out[str(name)] = (scan, side if side in SIDE else "-")
    return out


def page_boxes(case_dir: Path) -> dict[str, list[int]]:
    """Межі кожної сторінки в скані (`[x0, y0, x1, y1]`, пікселі оригіналу).

    Як у Сканотеки (`core.skanoteka.page_boxes`): однакові імена ще не означають
    однакового різу, а без меж чужі рамки рядків лягли б зі зсувом.
    """
    data = read_map_raw(case_dir)
    if data is None:
        return {}
    out: dict[str, list[int]] = {}
    for rec in data["frames"].values():
        if not isinstance(rec, dict):
            continue
        for name, page in (rec.get("pages") or {}).items():
            box = page.get("box") if isinstance(page, dict) else None
            if isinstance(box, list) and len(box) == 4:
                out[str(name)] = [int(v) for v in box]
    return out


def page_scan(name: str) -> tuple[str, str] | None:
    """(номер скана, бік) з імені сторінки: `0012_R.jpg` → ("12", "R")."""
    m = _PAGE.match(PurePath(str(name)).stem)
    if not m:
        return None
    return m.group(1).lstrip("0") or "0", (m.group(2) or "-")


def cite(shifra: str, scan: str, side: str, url: str) -> str:
    """Рядок для документа: `APL 12-1-5, скан 12 (права сторінка) — <адреса>`.

    `url` — сторінка скана (`scan_page`), коли хеш відомий з карти, інакше
    адреса одиниці: номер скана тоді стоїть у тексті.
    """
    return f"{shifra}, скан {scan} ({SIDE.get(side, side)}) — {url}"
