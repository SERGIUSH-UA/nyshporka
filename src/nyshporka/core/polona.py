"""🇵🇱 Polona (`polona.pl`): цифрова бібліотека Biblioteka Narodowa.

Друковані видання (джерельні серії на кшталт «Źródła dziejowe») і рукописи.
Зйомку називає UUID об'єкта: `polona.pl/preview/<uuid>` (картка) і
`polona.pl/item-view/<uuid>?page=N` (переглядач). У пулі — `object:<uuid>`.

Старі адреси (до 2023 р.) — `polona.pl/item/<назва>,<base64 старого ID>/<сторінка>`
і `polona.pl/item/<старий ID>/<сторінка>` — сайт сам переводить у UUID запитом
`/api/library-object-query/digital-objects/new-id/<старий ID>`. Без цього
перекладу та сама книга під старою й новою адресою стала б у пулі двома
зйомками, тому стара адреса без відповіді API зйомки не називає.

Маршрути й переклад звірено з бандлом сайту 23.11.2026 (охоронець `LEGACY_ITEM`):
`134805378` → `aca2e8b4-8b4f-472d-96ca-0130c4562be1`.
"""
from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import ParseResult, unquote, urlparse

NAME = "Polona"
SOURCE = "polona"
BASE = "https://polona.pl"
NEW_ID_API = f"{BASE}/api/library-object-query/digital-objects/new-id/{{old}}"

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RE = re.compile(rf"^{_UUID}$")
_HOST = re.compile(r"^(?:www\.)?polona\.pl$", re.I)
_NEW_PATH = re.compile(rf"^/(?:preview|item-view)/({_UUID})(?:/|$)", re.I)
# Ті самі два вирази, що в охоронці сайту: числовий ID і «назва,base64».
_OLD_NUM = re.compile(r"^/item/(\d+)(?:/|$)")
_OLD_B64 = re.compile(r"^/item/.*,([A-Za-z0-9]+)(?:/|$)")


@dataclass(frozen=True)
class Item:
    """Об'єкт Polona — за UUID."""

    uuid: str

    @property
    def ref(self) -> str:
        """Ідентифікатор зйомки для пулу: `object:<uuid>`."""
        return f"object:{self.uuid}"

    @property
    def url(self) -> str:
        return f"{BASE}/preview/{self.uuid}"


def _parse(url: str) -> ParseResult | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "https://" + raw)
    return p if _HOST.match(p.netloc) else None


def from_url(url: str) -> Item | None:
    """Об'єкт з нової адреси (`preview/`, `item-view/`); інше — None."""
    p = _parse(url)
    if p is None:
        return None
    m = _NEW_PATH.match(p.path)
    return Item(m.group(1).lower()) if m else None


def old_id(url: str) -> str | None:
    """Старий числовий ID зі старої адреси `item/…`; інше — None."""
    p = _parse(url)
    if p is None:
        return None
    path = unquote(p.path)
    m = _OLD_NUM.match(path)
    if m:
        return m.group(1)
    m = _OLD_B64.match(path)
    if not m:
        return None
    token = m.group(1)
    try:
        dec = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return dec if dec.isdigit() else None


def _fetch_new_id(old: str) -> str | None:
    import httpx

    r = httpx.get(NEW_ID_API.format(old=old), timeout=15.0,
                  headers={"Accept": "application/json"})
    if r.status_code != 200:
        return None
    got = r.json()
    return got if isinstance(got, str) else None


def resolve(url: str, fetch: Callable[[str], str | None] | None = None) -> Item | None:
    """Об'єкт з будь-якої адреси Polona; стару перекладає через API сайту.

    Мережа недоступна чи API не знає ID — None: вгаданий UUID склеїв би
    в пулі чужі зйомки.
    """
    item = from_url(url)
    if item is not None:
        return item
    old = old_id(url)
    if old is None:
        return None
    try:
        new = (fetch or _fetch_new_id)(old)
    except Exception:
        return None
    new = str(new or "").strip().lower()
    return Item(new) if _UUID_RE.match(new) else None


def from_ref(ref: str) -> Item | None:
    """Назад з `object:<uuid>` (з префіксом `polona:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    kind, _, ident = body.partition(":")
    if kind != "object" or not _UUID_RE.match(ident):
        return None
    return Item(ident)
