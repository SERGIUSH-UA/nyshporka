"""🔔 Дзвіночок: типово мережі немає, вмикає людина; бейдж — версія, моделі, Супряга."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from nyshporka import __version__
from nyshporka import ops as O
from nyshporka.setup import notices as N
from nyshporka.setup import update as U


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Свій файл стану машини: тест не чіпає справжній `state.json`."""
    from nyshporka.core import workspace as W

    p = tmp_path / "state.json"
    monkeypatch.setattr(W, "_state_path", lambda: p)
    return p


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Підмінена мережа: лічить звернення, нікуди не ходить."""
    calls = {"pypi": 0, "releases": 0, "sup": 0}

    def latest(timeout: float = 3.0) -> U.Release:
        calls["pypi"] += 1
        return U.Release(installed=__version__, latest="99.0.0")

    def releases(since: str, lang: str) -> list[dict[str, Any]]:
        calls["releases"] += 1
        return [{"version": "99.0.0", "title": "Нове", "summary": "Речення", "date": "2026-10-23",
                 "url": "https://nyshporka.online/onovlennia/x", "release": ""},
                {"version": "0.0.1", "title": "Старе", "summary": "", "date": "2020-01-01",
                 "url": "", "release": ""}]

    def sup(lang: str) -> dict[str, Any]:
        calls["sup"] += 1
        return {"unread": 2, "items": [{"id": 1, "kind": "novyna", "title": "Т", "url": "https://x/",
                                        "count": 1, "alert": False, "at": "2026-10-23T10:00:00Z",
                                        "read": False}]}

    monkeypatch.setattr(U, "latest", latest)
    monkeypatch.setattr(N, "_releases", releases)
    monkeypatch.setattr(N, "_notifications", sup)
    monkeypatch.setattr(N, "new_models", lambda: [{"id": "m", "label": "Модель", "size": 1,
                                                   "script": "", "engine": "", "reason": "install"}])
    return calls


def test_off_by_default_no_network(state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIVACY.md: фонової активності немає — поки людина сама не ввімкне."""
    monkeypatch.setattr(N, "logged_in", lambda: True)
    assert N.settings() == {"updates": False, "supriaha": False}
    assert N.due() is False and N.refresh_later() is False
    env = O.call("notices.state", {})
    assert env.ok and env.data["refreshing"] is False
    assert net == {"pypi": 0, "releases": 0, "sup": 0}


def test_enabled_and_due_refreshes_and_badge_counts_three_sources(
        state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "logged_in", lambda: True)
    O.call("settings.net", {"updates": True, "supriaha": True})
    assert N.due() is True
    N.refresh()
    assert net == {"pypi": 1, "releases": 1, "sup": 1}
    snap = N.snapshot()
    assert snap["newer"] and snap["latest"] == "99.0.0"
    assert [r["version"] for r in snap["releases"]] == ["99.0.0"], "старші за поставлену — не новина"
    assert snap["badge"] == 1 + 1 + 2, "версія + моделі + непрочитані Супряги"
    assert N.due() is False, "щойно перевірили — наступна не раніше, ніж через добу/годину"


def test_check_now_works_even_when_off(state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    """«Перевірити зараз» — дія людини, вимикач фонової перевірки її не спиняє."""
    monkeypatch.setattr(N, "logged_in", lambda: False)
    env = O.call("notices.check", {})
    assert env.ok and env.data["newer"] is True
    assert net["pypi"] == 1 and net["releases"] == 1
    assert net["sup"] == 0, "без входу в Супрягу сповіщень не питаємо"


def test_supriaha_needs_login_even_if_enabled(state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "logged_in", lambda: False)
    N.set_settings(supriaha=True)
    assert N.due() is False
    N.refresh()
    assert net["sup"] == 0


def test_a_failing_source_does_not_hide_the_other(state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(since: str, lang: str) -> list[dict[str, Any]]:
        raise OSError("портал мовчить")

    monkeypatch.setattr(N, "_releases", boom)
    monkeypatch.setattr(N, "logged_in", lambda: False)
    N.refresh(force=True)
    snap = N.snapshot()
    assert snap["newer"] is True and "releases_why" in snap["why"], "версія з PyPI лишилась, причину названо"


def test_settings_persist_in_machine_state(state: Path) -> None:
    env = O.call("settings.net", {"updates": True})
    assert env.ok and env.data["updates"] is True and env.data["supriaha"] is False
    assert O.call("settings.net", {}).data["updates"] is True, "без аргументів — лише показує"
    assert '"net_updates": true' in state.read_text(encoding="utf-8")


def test_background_refresh_runs_once(state: Path, net: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "logged_in", lambda: False)
    N.set_settings(updates=True)
    assert N.refresh_later() is True
    for _ in range(100):
        if not N._LOCK.locked():
            break
        time.sleep(0.02)
    assert net["pypi"] == 1 and N.refresh_later() is False, "щойно перевірили — більше не питаємо"
