"""🔔 Операції дзвіночка: нова версія, нові моделі, сповіщення Супряги, вимикачі мережі.

Логіка — у `setup/notices.py`; тут лише конверти для консолі й агента.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

#: Мови консолі, якими портал віддає тексти (решта — основна).
LANGS = ("uk", "en", "pl", "ro", "fr", "de", "ru")


def _lang(v: str) -> str:
    v = (v or "").strip().lower()
    return v if v in LANGS else "uk"


class NetSettingsArgs(BaseModel):
    updates: bool | None = Field(default=None, description="фонова перевірка нової версії "
                                                           "(pypi.org і примітки на порталі)")
    supriaha: bool | None = Field(default=None, description="сповіщення кабінету Супряги "
                                                            "в консолі (з ключем Супряги)")

    def only_shows(self) -> bool:
        return self.updates is None and self.supriaha is None


@op("settings.net", summary="Вимикачі мережі консолі: перевірка оновлень і сповіщення Супряги",
    args=NetSettingsArgs, mutates=True, section="core",
    when="увімкнути чи вимкнути фонову перевірку оновлень і сповіщення Супряги")
def settings_net(a: NetSettingsArgs) -> Envelope:
    """Типово обидва вимкнені: фонової активності в мережі немає (PRIVACY.md)."""
    from nyshporka.setup import notices as N

    got = N.set_settings(updates=a.updates, supriaha=a.supriaha)
    return ok({**got, "logged_in": N.logged_in()})


class NoticesStateArgs(BaseModel):
    lang: str = Field(default="uk", description="мова текстів з порталу")


@op("notices.state", summary="Що нового: версія, моделі, сповіщення Супряги (з пам'яті)",
    args=NoticesStateArgs, mutates=False, section="core",
    when="чи вийшла нова версія, нові моделі чи є сповіщення Супряги")
def notices_state(a: NoticesStateArgs) -> Envelope:
    """Без мережі: показує збережене. Якщо людина ввімкнула фонову перевірку і
    настав час — запускає її у фоні й не чекає; наступний виклик покаже свіже."""
    from nyshporka.setup import notices as N

    started = N.refresh_later(_lang(a.lang))
    return ok({**N.snapshot(), "refreshing": started})


@op("notices.check", summary="Перевірити зараз: нова версія й сповіщення Супряги",
    args=NoticesStateArgs, mutates=True, section="core",
    when="перевірити оновлення й сповіщення зараз")
def notices_check(a: NoticesStateArgs) -> Envelope:
    """Явна дія людини — іде й з вимкненою фоновою перевіркою."""
    from nyshporka.setup import notices as N

    N.refresh(force=True, lang=_lang(a.lang))
    env = ok(N.snapshot())
    for code, text in (env.data.get("why") or {}).items():
        env.warn(code, f"не все вдалося спитати: {text}")
    return env


class NoticesReadArgs(BaseModel):
    ids: list[int] | None = Field(default=None, description="які сповіщення; порожньо — усі")
    lang: str = Field(default="uk")


@op("notices.read", summary="Позначити сповіщення Супряги прочитаними",
    args=NoticesReadArgs, mutates=True, section="core", private=True,
    when="позначити сповіщення Супряги прочитаними")
def notices_read(a: NoticesReadArgs) -> Envelope:
    from nyshporka.setup import notices as N

    if not N.logged_in():
        return fail("на цій машині не виконано вхід у Супрягу — сповіщень немає")
    try:
        sup = N.mark_read(a.ids, _lang(a.lang))
    except Exception as exc:
        return fail(f"портал не прийняв позначку: {type(exc).__name__}: {exc}")
    return ok({"supriaha": sup})


class ModelsGetArgs(BaseModel):
    ids: list[str] | None = Field(default=None, description="id паків; порожньо — усі, яких бракує")


@op("models.get", summary="Завантажити моделі, яких бракує (sha256 звіряється)",
    args=ModelsGetArgs, mutates=True, long=True, section="core",
    when="завантажити нові моделі читання")
def models_get(a: ModelsGetArgs) -> Envelope:
    """Те саме, що `nysh models get`: ваги з релізу, звірка sha256 завжди."""
    from nyshporka.core import progress
    from nyshporka.setup import packs

    known = [p for p in packs.catalog() if p.kind == "model" and not p.superseded]
    want = [p for p in known if (not a.ids or p.id in a.ids) and not packs.verify(p)]
    if not want:
        return ok({"got": [], "failed": [], "note": "усе на місці"})
    got: list[str] = []
    failed: list[dict[str, str]] = []
    for i, p in enumerate(want):
        progress.report(i, len(want), p.label or p.id)
        try:
            packs.fetch(p)
            got.append(p.id)
        except Exception as exc:
            failed.append({"id": p.id, "why": f"{type(exc).__name__}: {exc}"[:200]})
    progress.report(len(want), len(want), "")
    env = ok({"got": got, "failed": failed})
    for f in failed:
        env.warn("model_failed", f"{f['id']}: {f['why']}")
    return env
