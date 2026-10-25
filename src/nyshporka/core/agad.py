"""🇵🇱 Сервер сканів AGAD (`agadd2.home.net.pl/metrykalia`): книга Метрики Коронної.

Головний архів давніх актів у Варшаві (AGAD) виставляє скани Метрики Коронної
(zespół 4, seria 1, Księgi Wpisów) окремим сервером, без порталу: кожна книга —
тека `metrykalia/MK/<номер у 4 цифри>/` з переліком `dirindex.html`, кадр —
`PL_1_4_1-<книга>_<NNNN>.jpg`. Номер книги (`MK 183`) і є її сигнатурою, тож
зйомку називає саме він: `mk:183`.

🔴 Лише Метрика Коронна, і лише та форма адреси, яку звірено (07.10.2026, книги
MK 170–360). Інші серії на сервері не перевірялись, а вгадана форма склеїла б
у пулі зйомки різних книг.

🔵 Метричні зеспіли (`metrykalia/<зеспіл>/sygn. <N>/indeks.htm`, хости `agadd` і
`agadd2`): окрема форма адреси, зйомка називається `zespol:<зеспіл>:<N>`
(AGAD 301-0-57 → `zespol:301:57`). Метрика Коронна лишається своєю гілкою.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

NAME = "AGAD, Metryka Koronna"
SOURCE = "agad"
HOST = "agadd2.home.net.pl"
BASE = f"http://{HOST}/metrykalia/MK"

_HOST = re.compile(r"^agadd2\.home\.net\.pl$", re.I)
_BOOK_PATH = re.compile(r"/metrykalia/MK/(\d{1,4})(?:/|$)")
_ZESPOL_HOST = re.compile(r"^agadd2?\.home\.net\.pl$", re.I)
_ZESPOL_PATH = re.compile(
    r"/metrykalia/(\d{1,4})/sygn\.\s*(\d{1,6}[A-Za-z]?)(?:/|$)", re.I)


@dataclass(frozen=True)
class Zespol:
    """Одиниця метричного зеспілу на сервері сканів: зеспіл + сигнатура."""

    zespol: int
    sygn: str

    @property
    def ref(self) -> str:
        return f"zespol:{self.zespol}:{self.sygn}"

    @property
    def url(self) -> str:
        return (f"http://{HOST}/metrykalia/{self.zespol}/"
                f"sygn.%20{self.sygn}/indeks.htm")


@dataclass(frozen=True)
class Book:
    """Книга Метрики Коронної — за номером (`MK 183` → 183)."""

    n: int

    @property
    def ref(self) -> str:
        """Ідентифікатор зйомки для пулу: `mk:<номер книги>` без нулів попереду."""
        return f"mk:{self.n}"

    @property
    def url(self) -> str:
        return f"{BASE}/{self.n:04d}/dirindex.html"


def from_url(url: str) -> Book | None:
    """Книга з адреси сервера (тека, перелік чи кадр); чужий хост — None."""
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "http://" + raw)
    if not _HOST.match(p.netloc.lower()):
        return None
    m = _BOOK_PATH.search(p.path)
    return Book(int(m.group(1))) if m and int(m.group(1)) > 0 else None


def from_ref(ref: str) -> Book | None:
    """Назад з `mk:<номер>` (з префіксом `agad:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    kind, _, ident = body.partition(":")
    if kind != "mk" or not ident.isdigit() or int(ident) <= 0:
        return None
    return Book(int(ident))


def zespol_from_url(url: str) -> Zespol | None:
    """Одиниця метричного зеспілу з адреси (перелік чи кадр); чужий хост — None."""
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "http://" + raw)
    if not _ZESPOL_HOST.match(p.netloc.lower()):
        return None
    m = _ZESPOL_PATH.search(unquote(p.path))
    if not m or int(m.group(1)) <= 0:
        return None
    return Zespol(int(m.group(1)), m.group(2))


def zespol_from_ref(ref: str) -> Zespol | None:
    """Назад з `zespol:<зеспіл>:<N>` (з префіксом `agad:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    parts = body.split(":")
    if len(parts) != 3 or parts[0] != "zespol" or not parts[1].isdigit():
        return None
    if int(parts[1]) <= 0 or not re.fullmatch(r"\d{1,6}[A-Za-z]?", parts[2]):
        return None
    return Zespol(int(parts[1]), parts[2])
