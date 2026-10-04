"""📚 Сканотека ПТГ (`*.genealodzy.pl`): одиниця, скан і бік сторінки.

Польське генеалогічне товариство виставляє на одному рушії кілька баз сканів:
`skanoteka` (загальна), `sadowe` (судові книги, зокрема ЦДІАК ф.2 — київські
гродські книги), `notariaty`, `meldunkowe`. Одиниця фонду має сталу адресу
`https://<база>.genealodzy.pl/id<фонд>-sy<одиниця>-se`, скан —
`index.php?op=pg&id=<фонд>&se=&sy=<одиниця>&kt=&plik=<NNN>.jpg`.
`metryki.genealodzy.pl` — інший сервіс з іншою адресацією, сюди не входить.

🔴 Кадр Сканотеки часто — РОЗВОРОТ книги. Завантажувач ріже його по згину на
дві сторінки (`185_L.jpg`, `185_R.jpg`) і пише карту «сторінка → скан, бік»
(`_split.json` у теці справи). Рушій читає половинки, а людина, яка хоче
звірити згадку з оригіналом, знає лише номер скана в Сканотеці. Без
зворотного переведення посилання на знахідку не відкрити й не перевірити.

⚠ Ім'я `_split.json` збігається з журналом `nysh cases split`. Карта
впізнається за вмістом (`read_map`), і `cases split` чужу карту не чіпає.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import parse_qs, urlparse

NAME = "Skanoteka ПТГ"
SOURCE = "skanoteka"
HOSTS = ("skanoteka", "sadowe", "notariaty", "meldunkowe")
MAP_NAME = "_split.json"

SIDE = {"L": "ліва сторінка", "R": "права сторінка", "-": "кадр цілий"}

_HOST = re.compile(r"^(?:www\.)?(" + "|".join(HOSTS) + r")\.genealodzy\.pl$", re.I)
_UNIT_PATH = re.compile(r"(?:^|/)id(\d+)-sy([0-9A-Za-z]+)(?:-|$)")
_TOKEN = re.compile(r"^[0-9A-Za-z]+$")
_PAGE = re.compile(r"^(\d{1,5})(?:_([LR]))?$")
_SRC = re.compile(r"^(\d{1,5})([LR])?$")


@dataclass(frozen=True)
class Unit:
    """Одиниця фонду в одній із баз Сканотеки."""

    host: str
    fond: str
    unit: str

    @property
    def ref(self) -> str:
        """Ідентифікатор зйомки для пулу: `unit:<база>/<фонд>/<одиниця>`."""
        return f"unit:{self.host}/{self.fond}/{self.unit}"

    @property
    def url(self) -> str:
        return f"https://{self.host}.genealodzy.pl/id{self.fond}-sy{self.unit}-se"

    def scan_url(self, scan: str) -> str:
        """Перегляд одного скана. `scan` — стем файла в Сканотеці (`185`, `001`)."""
        return (f"https://{self.host}.genealodzy.pl/index.php?op=pg&id={self.fond}"
                f"&se=&sy={self.unit}&kt=&plik={scan}.jpg")


def from_url(url: str) -> Unit | None:
    """Одиниця з адреси Сканотеки; чужий хост чи сторінка фонду — None.

    Сторінка фонду (`id1703` без `sy`) зйомкою не є: справ у фонді сотні.
    """
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "https://" + raw)
    m = _HOST.match(p.netloc.lower())
    if not m:
        return None
    host = m.group(1).lower()
    path = _UNIT_PATH.search(p.path)
    if path:
        return Unit(host, path.group(1), path.group(2))
    q = parse_qs(p.query)
    fond, unit = (q.get("id") or [""])[0], (q.get("sy") or [""])[0]
    if fond.isdigit() and unit and _TOKEN.match(unit):
        return Unit(host, fond, unit)
    return None


def from_ref(ref: str) -> Unit | None:
    """Назад з `unit:<база>/<фонд>/<одиниця>` (з префіксом `skanoteka:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    kind, _, ident = body.partition(":")
    parts = ident.split("/")
    if kind != "unit" or len(parts) != 3:
        return None
    host, fond, unit = parts
    if host not in HOSTS or not fond.isdigit() or not _TOKEN.match(unit):
        return None
    return Unit(host, fond, unit)


def unit_of(side: dict[str, Any]) -> Unit | None:
    """Одиниця з паспорта справи: `source.url` (вкладений) або `source_url`."""
    src = side.get("source")
    urls = []
    if isinstance(src, dict):
        urls += [src.get("url"), src.get("unit_url")]
    urls.append(side.get("source_url"))
    for url in urls:
        got = from_url(str(url or ""))
        if got is not None:
            return got
    return None


def read_map(case_dir: Path) -> dict[str, tuple[str, str]]:
    """Карта сторінок справи: ім'я сторінки → (скан, бік). Не карта — порожньо.

    Впізнається за вмістом, а не за іменем файла: `_split.json` пише й
    `nysh cases split` (журнал розбивки теки на справи).
    """
    try:
        data = json.loads((Path(case_dir) / MAP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not is_map(data):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for key, rec in data["frames"].items():
        if not isinstance(rec, dict):
            continue
        scan = PurePath(str(rec.get("src") or key)).stem
        for name, page in (rec.get("pages") or {}).items():
            side = str((page or {}).get("side") or "-") if isinstance(page, dict) else "-"
            out[str(name)] = (scan, side if side in SIDE else "-")
    return out


def is_map(data: Any) -> bool:
    """Чи це карта сканів Сканотеки (а не журнал `cases split`)."""
    return (isinstance(data, dict)
            and str(data.get("source") or "").lower().endswith("genealodzy.pl")
            and isinstance(data.get("frames"), dict))


def page_scan(name: str) -> tuple[str, str] | None:
    """(скан, бік) з імені сторінки, яке дає завантажувач: `185_R.jpg`, `001.jpg`.

    🔴 Лише коли вже відомо, що справа зі Сканотеки: ім'я `0042.jpg` в іншій
    теці — номер кадру справи, а не скана.
    """
    m = _PAGE.match(PurePath(str(name)).stem)
    if not m:
        return None
    return m.group(1), (m.group(2) or "-")


def src_of(scan: str, side: str) -> str:
    """id сторінки в джерелі для `frames.jsonl`: `185R`, `185L`, цілий кадр — `185`.

    Бік входить в id: дві половини одного скана — різні сторінки, а
    зіставлення кадрів (`share.align.page_names`) вимагає одного кадру на id.
    """
    return f"{scan}{side if side in ('L', 'R') else ''}"


def parse_src(src: str) -> tuple[str, str] | None:
    m = _SRC.match(str(src or ""))
    return (m.group(1), m.group(2) or "-") if m else None


def cite(shifra: str, scan: str, side: str, url: str) -> str:
    """Рядок для документа: `ЦДІАК 2-1-160, скан 185 (права сторінка) — <адреса>`."""
    return f"{shifra}, скан {scan} ({SIDE.get(side, side)}) — {url}"


def page_link(run: str, page: str) -> dict[str, str] | None:
    """Де сторінку прогону видно в Сканотеці; не зі Сканотеки чи не доведено — None.

    Своя справа: тека з мети прогону чи реєстру, одиниця з паспорта, скан — з
    карти (або з імені сторінки, коли карти немає). Прийнята з пулу: одиниця й
    скан — з того, що приніс пакет (`shared.refs`, `shared.page_src`).
    """
    from nyshporka import htr_store as S

    meta = S.load_meta(run) or {}
    shared = meta.get("shared") if isinstance(meta.get("shared"), dict) else {}
    if shared:
        unit = next((u for u in (from_ref(r.get("ref", "")) for r in shared.get("refs") or []
                                 if isinstance(r, dict) and r.get("source") == SOURCE)
                     if u is not None), None)
        got = parse_src((shared.get("page_src") or {}).get(page, ""))
        if unit is not None and got is not None:
            return _link(str(shared.get("shifra") or ""), unit, *got)
    from nyshporka.cases.register import read_sidecar
    from nyshporka.htr.view import _case_dirs

    dirs: list[Path] = []
    for d in _case_dirs(run, meta):
        # Кадри часто лежать у `<справа>/pages/`, а паспорт і карта — у самій справі.
        for cand in (d, d.parent) if d.name.lower() == "pages" else (d,):
            if cand not in dirs:
                dirs.append(cand)
    for case_dir in dirs:
        try:
            side = read_sidecar(case_dir)
        except Exception:
            continue
        unit = unit_of(side)
        if unit is None:
            continue
        mp = read_map(case_dir)
        got = mp.get(page) if mp else page_scan(page)
        if got is None:
            continue
        return _link(str(side.get("shifra") or ""), unit, *got)
    return None


def _link(shifra: str, unit: Unit, scan: str, side: str) -> dict[str, str]:
    url = unit.scan_url(scan)
    return {"source": SOURCE, "scan": scan, "side": side, "url": url,
            "cite": cite(shifra or unit.url, scan, side, url)}
