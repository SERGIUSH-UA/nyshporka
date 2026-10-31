"""Іменовані операції, які пул виконує на сервері: перелік, запуск, стан, скасування.

Клієнт нічого не знає про самі операції: назви, описи, підказки й причини
відмов приходять від сервера як є. Тут лише транспорт — запит, ключ
повторності й розбір відмови.

🔴 `pasport` у результаті — непрозорий словник від сервера. Клієнт пише його
цілком у `_supriaha_vyklyk.json` і не читає жодного поля, крім `pidkazka`
(текст для людини).
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from nyshporka.share import catalog as C


class Vidmova(C.PoolError):
    """Відмова сервера з текстом для людини (`povidomlennia`) і паузою (`retry_after`)."""

    def __init__(self, message: str, *, status: int | None = None,
                 retry_after: int | None = None) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after


def _vidmova(exc: Exception) -> Vidmova:
    """Відмова з тіла відповіді: `detail.povidomlennia`, `detail.retry_after`."""
    status = getattr(exc, "status", None)
    detail: Any = None
    try:
        detail = json.loads(str(getattr(exc, "body", "") or "")).get("detail")
    except (ValueError, AttributeError):
        detail = None
    tekst, pauza = "", None
    if isinstance(detail, dict):
        tekst = str(detail.get("povidomlennia") or "")
        if str(detail.get("retry_after") or "").isdigit():
            pauza = int(detail["retry_after"])
    elif isinstance(detail, str):
        tekst = detail
    return Vidmova(tekst or C.reason(exc), status=status, retry_after=pauza)


def _rozibraty(resp: Any) -> dict[str, Any]:
    try:
        got = json.loads(resp.text)
    except ValueError:
        raise C.PoolError("пул відповів не JSON") from None
    if not isinstance(got, dict):
        raise C.PoolError("пул відповів не тим, чого чекали")
    return got


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    from nyshporka.sources.http import HttpError

    try:
        resp = C._fetcher(url, accept_json=True).post(url, json_body=body)
    except HttpError as exc:
        if exc.status == 401:
            raise C.PotribenKliuch(C.KLIUCH_TEXT, status=401) from exc
        raise _vidmova(exc) from exc
    return _rozibraty(resp)


def _get(url: str) -> dict[str, Any]:
    """Як `catalog._get`, але відмова несе текст сервера."""
    from nyshporka.sources.http import HttpError

    try:
        resp = C._fetcher(url, accept_json=True).get(url)
    except HttpError as exc:
        if exc.status == 401:
            raise C.PotribenKliuch(C.KLIUCH_TEXT, status=401) from exc
        raise _vidmova(exc) from exc
    return _rozibraty(resp)


def novyi_kliuch() -> str:
    return secrets.token_hex(16)


def perelik(base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/perelik")


def dovidka(base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/dovidka")


def zapustyty(operatsiia: str, parametry: dict[str, str], kliuch: str = "",
              base: str = "") -> dict[str, Any]:
    """Новий виклик (201) або повтор за ключем (200). Ключ без вказівки — свій."""
    return _post(f"{C.base_url(base)}/m/vyklyky",
                 {"operatsiia": operatsiia, "parametry": parametry,
                  "kliuch": kliuch or novyi_kliuch()})


def stan(vid: int, base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/vyklyky/{vid}")


def skasuvaty(vid: int, base: str = "") -> dict[str, Any]:
    return _post(f"{C.base_url(base)}/m/vyklyky/{vid}/skasuvaty", {})
