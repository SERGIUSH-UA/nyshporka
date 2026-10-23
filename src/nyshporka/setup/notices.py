"""🔔 Новини консолі: нова версія, нові моделі, сповіщення Супряги.

Дзвіночок у шапці консолі світиться, коли вийшла новіша версія (з тим, що в
ній змінилось), коли застосунок знає моделі, яких на машині ще немає, і коли
в кабінеті Супряги є непрочитані сповіщення.

🔴 **Фонова перевірка — лише якщо людина її ввімкнула** (рішення дослідника
23.10.2026). `PRIVACY.md` обіцяє «фонової активності в мережі немає»; два
вимикачі тут — третій виняток того самого виду, що й два режими Супряги:
типово вимкнено, вмикає людина, і сказано, що йде і куди. Кнопка «Перевірити
зараз» — дія людини, вона йде й з вимкненими вимикачами.

Нові моделі рахуються локально, без мережі: маніфест паків їде з колесом, тож
нова модель «з'являється» разом з оновленням застосунку.
"""
from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlencode

from nyshporka import __version__

#: Ключі у файлі стану машини (`state.json`): про машину, а не про проєкт.
KEY_UPDATES = "net_updates"
KEY_SUPRIAHA = "net_supriaha_notices"
KEY_CACHE = "notices_cache"

#: Як часто перевіряти, коли ввімкнено: версія — раз на добу, сповіщення —
#: раз на годину (людина чекає відповіді на свій внесок того самого дня).
EVERY_RELEASES = 24 * 3600
EVERY_SUPRIAHA = 3600

#: Фонова перевірка — не більше однієї водночас.
_LOCK = threading.Lock()


def settings() -> dict[str, bool]:
    from nyshporka.core.workspace import state_all

    st = state_all()
    return {"updates": bool(st.get(KEY_UPDATES, False)),
            "supriaha": bool(st.get(KEY_SUPRIAHA, False))}


def set_settings(*, updates: bool | None = None, supriaha: bool | None = None) -> dict[str, bool]:
    from nyshporka.core.workspace import state_set

    fields: dict[str, Any] = {}
    if updates is not None:
        fields[KEY_UPDATES] = bool(updates)
    if supriaha is not None:
        fields[KEY_SUPRIAHA] = bool(supriaha)
    if fields:
        state_set(**fields)
    return settings()


def logged_in() -> bool:
    """Чи увійшла людина в Супрягу на цій машині (є ключ у сховищі)."""
    try:
        from nyshporka.share.upload import token

        return bool(token())
    except Exception:
        return False


def _cache() -> dict[str, Any]:
    from nyshporka.core.workspace import state_all

    got = state_all().get(KEY_CACHE)
    return dict(got) if isinstance(got, dict) else {}


def _save(cache: dict[str, Any]) -> None:
    from nyshporka.core.workspace import state_set

    state_set(**{KEY_CACHE: cache})


def _due(at: Any, every: int) -> bool:
    try:
        return time.time() - float(at) >= every
    except (TypeError, ValueError):
        return True


def _key(v: str) -> tuple[int, ...]:
    from nyshporka.setup.update import _key as k

    return k(v)


def _api(path: str, params: dict[str, str]) -> str:
    from nyshporka.share.catalog import base_url

    return f"{base_url()}{path}?{urlencode(params)}"


def _releases(since: str, lang: str) -> list[dict[str, Any]]:
    """Примітки випусків, новіших за `since`, з порталу. Ключ сюди не їде."""
    import json

    from nyshporka.share.catalog import _fetcher

    url = _api("/releases", {"since": since, "lang": lang})
    resp = _fetcher(url, auth="", accept_json=True).get(url)
    got = json.loads(resp.text if hasattr(resp, "text") else str(resp))
    items = got.get("items") if isinstance(got, dict) else None
    keep = ("version", "title", "summary", "date", "url", "release")
    return [{k: str(x.get(k) or "") for k in keep} for x in (items or []) if isinstance(x, dict)]


def _notifications(lang: str) -> dict[str, Any]:
    """Сповіщення кабінету — з ключем Супряги (лише на довірену адресу)."""
    import json

    from nyshporka.share.catalog import _fetcher

    url = _api("/notifications", {"lang": lang})
    resp = _fetcher(url, accept_json=True).get(url)
    got = json.loads(resp.text if hasattr(resp, "text") else str(resp))
    if not isinstance(got, dict):
        return {"unread": 0, "items": []}
    keep = ("id", "kind", "title", "url", "count", "alert", "at", "read")
    items = [{k: x.get(k) for k in keep} for x in (got.get("items") or []) if isinstance(x, dict)]
    return {"unread": int(got.get("unread") or 0), "items": items}


def mark_read(ids: list[int] | None, lang: str = "uk") -> dict[str, Any]:
    """Позначити сповіщення прочитаним на порталі й у кеші консолі."""
    import json

    from nyshporka.share.catalog import _fetcher

    url = _api("/notifications/read", {})
    body: dict[str, Any] = {} if ids is None else {"ids": list(ids)}
    resp = _fetcher(url, accept_json=True).post(url, json_body=body)
    got = json.loads(resp.text if hasattr(resp, "text") else str(resp))
    cache = _cache()
    sup = dict(cache.get("supriaha") or {})
    mine = set(ids or [])
    sup["items"] = [{**x, "read": True} if ids is None or x.get("id") in mine else x
                    for x in sup.get("items") or []]
    sup["unread"] = int((got or {}).get("unread") or 0)
    cache["supriaha"] = sup
    _save(cache)
    return sup


def refresh(*, force: bool = False, lang: str = "uk") -> dict[str, Any]:
    """Спитати те, що настав час спитати (або все — `force`), і покласти в кеш.

    Кожне джерело — окремо: мовчазний портал не гасить новину про версію з
    PyPI, і навпаки. Помилку записуємо поруч із джерелом, а не ковтаємо.
    """
    from nyshporka.setup.update import latest

    s = settings()
    cache = _cache()
    now = time.time()
    if force or (s["updates"] and _due(cache.get("releases_at"), EVERY_RELEASES)):
        rel = latest()
        cache.update(latest=rel.latest, latest_why=rel.why, releases_at=now)
        try:
            cache["releases"] = _releases(__version__, lang)
            cache.pop("releases_why", None)
        except Exception as exc:
            cache["releases_why"] = f"{type(exc).__name__}: {exc}"[:200]
    # 🔴 Сповіщення Супряги — лише з увімкненим вимикачем, і «Перевірити зараз»
    # його не обходить: ключ Супряги їде на сервер, а людина цього не дозволяла.
    # Доти «Перевірити» підтягувало сповіщення при вимкненому вимикачі, і
    # дзвіночок показував «2» над попапом «Новин немає» (знімок 23.10.2026).
    if s["supriaha"] and logged_in() and (force or _due(cache.get("supriaha_at"), EVERY_SUPRIAHA)):
        try:
            cache["supriaha"] = _notifications(lang)
            cache.pop("supriaha_why", None)
        except Exception as exc:
            cache["supriaha_why"] = f"{type(exc).__name__}: {exc}"[:200]
        cache["supriaha_at"] = now
    _save(cache)
    return cache


def due() -> bool:
    """Чи пора фоновій перевірці (і чи вона взагалі дозволена)."""
    s = settings()
    cache = _cache()
    return bool((s["updates"] and _due(cache.get("releases_at"), EVERY_RELEASES))
                or (s["supriaha"] and logged_in()
                    and _due(cache.get("supriaha_at"), EVERY_SUPRIAHA)))


def refresh_later(lang: str = "uk") -> bool:
    """Фонова перевірка, якщо дозволена й пора; не чекає. `True` — запущено."""
    if not due() or not _LOCK.acquire(blocking=False):
        return False

    def run() -> None:
        try:
            refresh(lang=lang)
        except Exception:
            pass
        finally:
            _LOCK.release()

    threading.Thread(target=run, name="nysh-notices", daemon=True).start()
    return True


def new_models() -> list[dict[str, Any]]:
    """Моделі з маніфесту, яких на машині ще немає (без мережі)."""
    try:
        from nyshporka.setup import packs

        return [{"id": p.id, "label": p.label or p.id, "size": p.size,
                 "script": p.script, "engine": p.engine,
                 "reason": packs.download_reason(p)[0]} for p in packs.missing("model")]
    except Exception:
        return []


def snapshot() -> dict[str, Any]:
    """Що показати: стан із кешу (без мережі) і число на дзвіночку."""
    cache = _cache()
    latest = str(cache.get("latest") or "")
    newer = bool(latest) and _key(latest) > _key(__version__)
    releases = [r for r in cache.get("releases") or []
                if _key(str(r.get("version") or "")) > _key(__version__)]
    sup = cache.get("supriaha") if isinstance(cache.get("supriaha"), dict) else {}
    if not (settings()["supriaha"] and logged_in()):
        sup = {}  # вимкнено чи вийшли — ні в переліку, ні в числі на дзвіночку
    models = new_models()
    badge = (1 if newer else 0) + (1 if models else 0) + int((sup or {}).get("unread") or 0)
    return {"installed": __version__, "latest": latest, "newer": newer,
            "releases": releases, "models": models, "supriaha": sup or {},
            "logged_in": logged_in(), "settings": settings(), "badge": badge,
            "checked_at": cache.get("releases_at"), "why": {
                k: cache[k] for k in ("latest_why", "releases_why", "supriaha_why") if cache.get(k)}}
