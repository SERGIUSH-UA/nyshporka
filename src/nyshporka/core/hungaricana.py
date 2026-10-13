"""🇭🇺 Hungaricana (`library.hungaricana.hu`): том бібліотеки порталу.

Угорський портал культурної спадщини виставляє архівні томи переглядачем
`library.hungaricana.hu/<мова>/view/<ID>/`, де `<ID>` — ідентифікатор тому
(`KANepszaml_012_Nagybocsko_Nagybocsko__158_VelikijBicskiv-NagyBocsko` —
перепис Закарпаття 1921 р., Великий Бичків). Сторінки лежать на CDN окремими
PDF у теці тому `static-cdn.hungaricana.hu/pdf1/<колекція>/<ID>-<мітка>/`, і
ця тека називає той самий том. Зйомку називає `<ID>`: `view:<ID>`.

🔴 Лише бібліотека (`library.`) і лише ці дві форми адреси, звірені 13.10.2026
на колекції KarpataljaiNepszamlalas1921. Архівні бази порталу
(`archives.hungaricana.hu`) — інші сутності з іншими ідентифікаторами, і
вгадана форма склеїла б у пулі різні зйомки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

NAME = "Hungaricana"
SOURCE = "hungaricana"
BASE = "https://library.hungaricana.hu/hu/view"

_ID = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
_ID_RE = re.compile(rf"^{_ID}$")
_VIEW_HOST = re.compile(r"^library\.hungaricana\.hu$", re.I)
_VIEW_PATH = re.compile(rf"^/[a-z]{{2}}/view/({_ID})(?:/|$)")
_CDN_HOST = re.compile(r"^static-cdn\.hungaricana\.hu$", re.I)
# Тека тому на CDN: `<ID>-<мітка часу>`; мітка — лише цифри, сам `<ID>` теж
# буває з дефісами (`…-NagyBocsko`), тож відрізається саме цифровий хвіст.
_CDN_PATH = re.compile(rf"^/pdf\d*/[^/]+/({_ID})-\d{{6,}}(?:/|$)")


@dataclass(frozen=True)
class Volume:
    """Том бібліотеки Hungaricana — за ідентифікатором переглядача."""

    ident: str

    @property
    def ref(self) -> str:
        """Ідентифікатор зйомки для пулу: `view:<ID>`."""
        return f"view:{self.ident}"

    @property
    def url(self) -> str:
        return f"{BASE}/{self.ident}/"


def from_url(url: str) -> Volume | None:
    """Том з адреси переглядача чи теки на CDN; чужий хост чи інша форма — None."""
    raw = str(url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else "https://" + raw)
    host = p.netloc.lower()
    if _VIEW_HOST.match(host):
        m = _VIEW_PATH.match(p.path)
    elif _CDN_HOST.match(host):
        m = _CDN_PATH.match(p.path)
    else:
        return None
    return Volume(m.group(1)) if m else None


def from_ref(ref: str) -> Volume | None:
    """Назад з `view:<ID>` (з префіксом `hungaricana:` теж)."""
    body = str(ref or "").strip().removeprefix(SOURCE + ":")
    kind, _, ident = body.partition(":")
    if kind != "view" or not _ID_RE.match(ident):
        return None
    return Volume(ident)
