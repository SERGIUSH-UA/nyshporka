"""🇵🇱 Сервер сканів AGAD (`agadd2.home.net.pl/metrykalia`): книга Метрики Коронної.

Головний архів давніх актів у Варшаві (AGAD) виставляє скани Метрики Коронної
(zespół 4, seria 1, Księgi Wpisów) окремим сервером, без порталу: кожна книга —
тека `metrykalia/MK/<номер у 4 цифри>/` з переліком `dirindex.html`, кадр —
`PL_1_4_1-<книга>_<NNNN>.jpg`. Номер книги (`MK 183`) і є її сигнатурою, тож
зйомку називає саме він: `mk:183`.

🔴 Лише Метрика Коронна, і лише та форма адреси, яку звірено (07.10.2026, книги
MK 170–360). Інші серії на сервері не перевірялись, а вгадана форма склеїла б
у пулі зйомки різних книг.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

NAME = "AGAD, Metryka Koronna"
SOURCE = "agad"
HOST = "agadd2.home.net.pl"
BASE = f"http://{HOST}/metrykalia/MK"

_HOST = re.compile(r"^agadd2\.home\.net\.pl$", re.I)
_BOOK_PATH = re.compile(r"/metrykalia/MK/(\d{1,4})(?:/|$)")


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
