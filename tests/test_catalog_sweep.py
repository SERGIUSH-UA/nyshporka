"""🔎 Пошук по каталогах: джерела разом, поступ поіменно, зупинка; обхід кнопкою.

Холодний прохід 07.10.2026: «Хвилинку…» 55 с на «Липовеньке» — джерела
опитувались поспіль, і Internet Archive (черга до archive.org) сам брав 38 с.
Поруч зі знахідками ARCHIUM стояло «обходу немає — пошук недоступний», а
лікувати пропонувалось командою терміналу, якої людині з браузера нема куди
набрати.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

import nyshporka.ops_builtin as ob
from nyshporka.core import progress as P
from nyshporka.ops_builtin import (
    CatalogSearchArgs,
    CrawlArgs,
    _catalog_basis,
    catalog_crawl,
    catalog_search,
)
from nyshporka.sources.base import Hit, SourceError


class _Src:
    caps = frozenset({"search"})

    def __init__(self, sid: str, *, delay: float = 0.0, hits: int = 1,
                 gate: threading.Event | None = None, boom: Exception | None = None) -> None:
        self.id = sid
        self.label = sid.upper()
        self.delay = delay
        self.hits = hits
        self.gate = gate
        self.boom = boom

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        if self.gate is not None:
            self.gate.wait(5)
        time.sleep(self.delay)
        if self.boom is not None:
            raise self.boom
        return [Hit(source=self.id, ref=f"{self.id}:{i}", title=f"{q} {i}")
                for i in range(self.hits)]


class _Reg:
    def __init__(self, *srcs: Any) -> None:
        self.srcs = list(srcs)

    def with_cap(self, cap: str) -> list[Any]:
        return list(self.srcs)

    def get(self, sid: str) -> Any:
        return next((s for s in self.srcs if s.id == sid), None)

    def all(self) -> list[Any]:
        return list(self.srcs)


def _search(monkeypatch: pytest.MonkeyPatch, *srcs: Any, **kw: Any) -> Any:
    monkeypatch.setattr(ob, "_registry", lambda: _Reg(*srcs))
    return catalog_search(CatalogSearchArgs(q="Липовеньке", by_address=False, **kw))


def test_sources_are_asked_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Три джерела по 0.4 с — разом це 0.4 с, а не 1.2."""
    t0 = time.monotonic()
    env = _search(monkeypatch, *(_Src(f"s{i}", delay=0.4) for i in range(3)))
    took = time.monotonic() - t0
    assert env.ok and len(env.data["hits"]) == 3
    assert took < 1.0, f"джерела опитано поспіль: {took:.2f} с"


def test_answer_order_is_the_source_order_not_the_arrival_order(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Видача ріжеться стелею — порядок не сміє залежати від швидкості сервера."""
    slow = _Src("slow", delay=0.3, hits=2)
    fast = _Src("fast", hits=2)
    env = _search(monkeypatch, slow, fast, limit=3)
    assert [h["source"] for h in env.data["hits"]] == ["slow", "slow", "fast"]
    assert env.data["coverage"]["searched"] == ["slow", "fast"]


def test_failures_stay_named_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _search(monkeypatch, _Src("ok"), _Src("bad", boom=SourceError("каталогу немає")),
                  _Src("net", boom=OSError("таймаут")))
    un = {u["source"]: u["why"] for u in env.data["coverage"]["unavailable"]}
    assert un == {"bad": "каталогу немає", "net": "OSError: таймаут"}
    assert env.data["coverage"]["searched"] == ["ok"]


def test_progress_names_who_is_still_awaited(monkeypatch: pytest.MonkeyPatch) -> None:
    """«7 із 9» без імен не каже, чого чекаємо, — і виглядає як зависання."""
    gate = threading.Event()
    notes: list[tuple[int, int, str]] = []

    def sink(i: int, n: int, note: str) -> None:
        notes.append((i, n, note))
        gate.set()

    with P.sink(sink):
        _search(monkeypatch, _Src("fast"), _Src("ia", delay=0.8))
    assert any(n == 2 and "IA" in note and "FAST" not in note for _, n, note in notes), notes


def test_stop_returns_what_answered_and_names_the_rest(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Спинений пошук — не нуль: недочекані джерела названо, тривогою."""
    stop = threading.Event()
    stop.set()
    hang = threading.Event()             # ніколи не відпускаємо — джерело «висить»
    t0 = time.monotonic()
    with P.stop_scope(stop):
        env = _search(monkeypatch, _Src("fast"), _Src("ia", gate=hang))
    assert time.monotonic() - t0 < 3, "зупинка чекала джерело до кінця"
    hang.set()
    assert env.data["stopped"] is True
    assert [h["source"] for h in env.data["hits"]] == ["fast"]
    un = env.data["coverage"]["unavailable"]
    assert un and un[0]["source"] == "ia" and "спинено" in un[0]["why"]
    w = {x.code: x.level for x in env.warnings}
    assert w.get("catalog_stopped") == "alert"


def test_without_stop_the_slow_source_is_awaited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Термінал і агент зупинки не мають — повільне джерело дочікується."""
    env = _search(monkeypatch, _Src("fast"), _Src("ia", delay=0.7))
    assert "stopped" not in env.data
    assert env.data["coverage"]["searched"] == ["fast", "ia"]


# ── перелік джерел ───────────────────────────────────────────────────────────

class _Archium(_Src):
    live_fallback = True

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        return "none", {}

    def crawl(self, *a: Any, **k: Any) -> dict[str, int]:
        return {}


class _Blind(_Archium):
    live_fallback = False


class _FromFile(_Blind):
    def import_list(self, path: Any) -> dict[str, Any]:
        return {}


def test_live_fallback_is_not_blind_and_both_are_crawlable() -> None:
    live = _catalog_basis(_Archium("archium-cdiak"))
    blind = _catalog_basis(_Blind("babynyar"))
    assert live["live"] is True and live["crawlable"] is True
    assert blind["live"] is False and blind["crawlable"] is True
    # Команда лишається — для агента й терміналу; консоль її не показує.
    assert blind["fix"] == "nysh crawl babynyar"


def test_a_file_catalog_is_not_crawlable_by_button() -> None:
    assert _catalog_basis(_FromFile("volok"))["crawlable"] is False


def test_the_real_archium_declares_its_live_search() -> None:
    from nyshporka.sources.registry import _builtin

    by_id = {s.id: s for s in _builtin(None)}
    assert getattr(by_id["archium"], "live_fallback", False)
    assert not getattr(by_id["babynyar"], "live_fallback", False)


# ── обхід кнопкою ────────────────────────────────────────────────────────────

class _Crawler(_Src):
    def __init__(self, sid: str, steps: int = 5, short: int = 0) -> None:
        super().__init__(sid)
        self.steps = steps
        self.short = short
        self.written: list[int] = []
        self.resume: bool | None = None

    def crawl(self, groups: Any = None, *, on_progress: Any = None,
              resume: bool = True) -> dict[str, int]:
        self.resume = resume
        for i in range(1, self.steps + 1):
            self.written.append(i)               # крок записано ДО звіту
            if on_progress:
                on_progress(done=i, total=self.steps, unit="фонд", note=f"справ {i * 10}")
        return {"fonds": self.steps, "cases": self.steps * 10, "short": self.short}


def _crawl(monkeypatch: pytest.MonkeyPatch, src: Any, **kw: Any) -> Any:
    monkeypatch.setattr(ob, "_registry", lambda: _Reg(src))
    return catalog_crawl(CrawlArgs(source=src.id, **kw))


def test_crawl_reports_progress_and_resumes_by_default(
        monkeypatch: pytest.MonkeyPatch) -> None:
    src = _Crawler("babynyar")
    seen: list[tuple[int, int, str]] = []
    with P.sink(lambda i, n, note: seen.append((i, n, note))):
        env = _crawl(monkeypatch, src)
    assert env.ok and env.data["cases"] == 50
    assert src.resume is True
    assert seen[-1] == (5, 5, "фонд · справ 50")


def test_crawl_fresh_starts_over(monkeypatch: pytest.MonkeyPatch) -> None:
    src = _Crawler("babynyar")
    _crawl(monkeypatch, src, fresh=True)
    assert src.resume is False


def test_crawl_stops_after_a_written_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Зупинка — з приймача поступу, тобто після записаного кроку."""
    src = _Crawler("babynyar")
    stop = threading.Event()

    def sink(i: int, n: int, note: str) -> None:
        if i == 2:
            stop.set()

    with P.sink(sink), P.stop_scope(stop):
        env = _crawl(monkeypatch, src)
    assert src.written == [1, 2], "обхід пішов далі після зупинки"
    assert env.ok and env.data["stopped"] is True
    assert {w.code: w.level for w in env.warnings}.get("crawl_stopped") == "alert"


def test_short_inventories_are_an_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _crawl(monkeypatch, _Crawler("babynyar", short=3))
    assert {w.code: w.level for w in env.warnings}.get("crawl_short") == "alert"


def test_crawl_refuses_what_cannot_be_crawled(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not _crawl(monkeypatch, _FromFile("volok")).ok
    assert not _crawl(monkeypatch, _Src("duck")).ok
    monkeypatch.setattr(ob, "_registry", lambda: _Reg())
    assert not catalog_crawl(CrawlArgs(source="нема")).ok


def test_crawl_source_error_is_a_failure_not_a_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Down(_Crawler):
        def crawl(self, *a: Any, **k: Any) -> dict[str, int]:
            raise SourceError("сайт не відповів")

    env = _crawl(monkeypatch, _Down("babynyar"))
    assert not env.ok and "сайт не відповів" in env.error


def test_both_jobs_are_stoppable_in_the_console() -> None:
    from nyshporka.daemon.workers import STOPPABLE_OPS

    assert {"catalog.sweep", "catalog.crawl"} <= STOPPABLE_OPS
