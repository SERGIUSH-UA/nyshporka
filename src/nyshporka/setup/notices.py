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

#: Після збою мережі — повтор за годину, а не за добу: збій не новина.
RETRY_AFTER_FAIL = 3600

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


def _save(cache: dict[str, Any], keys: tuple[str, ...] | None = None) -> None:
    """Записати кеш. З `keys` — лише ці поля поверх СВІЖО прочитаного кешу.

    🔴 Перевірка триває секунди; позначка «прочитано», зроблена за цей час
    (`mark_read`), інакше затиралась би старим знімком (рев'ю 23.10.2026).
    """
    from nyshporka.core.workspace import state_set

    if keys is not None:
        cache = {**_cache(), **{k: cache[k] for k in keys if k in cache}}
        for k in keys:
            if k not in cache:
                cache.pop(k, None)
    state_set(**{KEY_CACHE: cache})


def _due(at: Any, every: int) -> bool:
    try:
        return time.time() - float(at) >= every
    except (TypeError, ValueError):
        return True


def _newer(a: str, b: str) -> bool:
    """Чи `a` новіша за `b` — з вирівнюванням довжини (`0.36` = `0.36.0`)."""
    from nyshporka.setup.update import _cmp_key

    x, y = _cmp_key(a, b)
    return x > y


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
    # «Усе» — явно (`all`): порожнє тіло портал читає як «нічого» (рев'ю 23.10.2026).
    body: dict[str, Any] = {"all": True} if ids is None else {"ids": list(ids)}
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
    mine: list[str] = []
    if force or (s["updates"] and _due(cache.get("releases_at"), EVERY_RELEASES)):
        rel = latest()
        mine += ["latest", "latest_why", "releases", "releases_why", "releases_at"]
        # 🔴 Збій PyPI не стирає відому нову версію й не відкладає повтор на добу:
        # «не дізнались» — не «новин немає» (рев'ю 23.10.2026).
        if rel.known:
            cache.update(latest=rel.latest, releases_at=now)
            cache.pop("latest_why", None)
        else:
            cache["latest_why"] = rel.why
            cache["releases_at"] = now - EVERY_RELEASES + RETRY_AFTER_FAIL
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
        mine += ["supriaha", "supriaha_why", "supriaha_at"]
        try:
            cache["supriaha"] = _notifications(lang)
            cache.pop("supriaha_why", None)
            cache["supriaha_at"] = now
        except Exception as exc:
            cache["supriaha_why"] = f"{type(exc).__name__}: {exc}"[:200]
            cache["supriaha_at"] = now - EVERY_SUPRIAHA + min(RETRY_AFTER_FAIL, EVERY_SUPRIAHA)
    _save(cache, tuple(mine))
    return {**_cache()}


def due() -> bool:
    """Чи пора фоновій перевірці (і чи вона взагалі дозволена)."""
    s = settings()
    cache = _cache()
    return bool((s["updates"] and _due(cache.get("releases_at"), EVERY_RELEASES))
                or (s["supriaha"] and logged_in()
                    and _due(cache.get("supriaha_at"), EVERY_SUPRIAHA)))


def refreshing() -> bool:
    """Чи йде зараз фонова перевірка (тоді консоль перечитає стан трохи згодом)."""
    return _LOCK.locked()


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


def last_update() -> dict[str, Any]:
    """Чим скінчилось останнє оновлення одним натиском — якщо воно було за добу.

    Пише його помічник (`setup/updater.py`), коли консоль уже закрита; нова
    консоль показує людині: «оновлено до X» або журнал, чому ні.
    """
    import json

    from nyshporka.core.workspace import _state_path

    sp = _state_path()
    if sp is None:
        return {}
    path = sp.parent / "update" / "result.json"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict) or time.time() - float(got.get("finished") or 0) > 86400:
        return {}
    if not got.get("ok"):
        import contextlib

        with contextlib.suppress(OSError):
            got["tail"] = path.with_name("update.log").read_text(encoding="utf-8")[-1500:]
    return got


def snapshot() -> dict[str, Any]:
    """Що показати: стан із кешу (без мережі) і число на дзвіночку."""
    cache = _cache()
    s = settings()
    latest = str(cache.get("latest") or "")
    newer = bool(latest) and _newer(latest, __version__)
    releases = [r for r in cache.get("releases") or []
                if _newer(str(r.get("version") or ""), __version__)]
    # Сховище ключів питаємо лише тоді, коли сповіщення ввімкнені: на macOS і
    # Linux воно може просити розблокування в людини, що їх і не вмикала.
    signed = logged_in() if s["supriaha"] else False
    sup = cache.get("supriaha") if isinstance(cache.get("supriaha"), dict) else {}
    if not (s["supriaha"] and signed):
        sup = {}  # вимкнено чи вийшли — ні в переліку, ні в числі на дзвіночку
    models = new_models()
    # 🔴 На дзвіночку — лише НОВІШІ версії вже поставлених моделей. Моделі, яких
    # людина не ставила взагалі (набір «каталог»), лишаються на екрані, але
    # крапки не запалюють: інакше дзвіночок світився б завжди.
    fresh_models = [m for m in models if m.get("reason") == "update"]
    badge = (1 if newer else 0) + (1 if fresh_models else 0) + int((sup or {}).get("unread") or 0)
    return {"installed": __version__, "latest": latest, "newer": newer,
            "releases": releases, "models": models, "models_newer": len(fresh_models),
            "supriaha": sup or {},
            "logged_in": signed, "settings": s, "badge": badge,
            "last_update": last_update(),
            "checked_at": cache.get("releases_at"), "why": {
                k: cache[k] for k in ("latest_why", "releases_why", "supriaha_why") if cache.get(k)}}
