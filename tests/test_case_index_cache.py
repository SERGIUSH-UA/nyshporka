"""🧠 Кеш індексу рядків (`htr_store._case_index`) має стелю.

10.11.2026 скан роду по 598 прогонах тримав у кеші весь їхній текст і дійшов до 19 ГБ. Кеш потрібен
повторному читанню того самого прогону в одному процесі, тож стеля — LRU: недавно читаний лишається,
давно читаний іде геть, і останній прогін не викидається навіть тоді, коли сам більший за стелю.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Чотири прогони; у прогоні `rN` — N+1 рядків тексту."""
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    root = tmp_path / "reports" / "htr"
    for n in range(4):
        run = root / f"r{n}"
        run.mkdir(parents=True)
        (run / "0001.txt").write_text("\n".join(f"Липовенька рядок {i}" for i in range(n + 1)) + "\n",
                                      encoding="utf-8")
        (run / "_htr_meta.json").write_text(json.dumps({"pages": {"0001.jpg": {"lines": n + 1}}}),
                                            encoding="utf-8")
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: root)
    S._CACHE.clear()
    yield S
    S._CACHE.clear()
    W.reset()


def test_cache_keeps_at_most_n_runs_dropping_least_recent(runs, monkeypatch) -> None:
    S = runs
    monkeypatch.setattr(S, "CASE_INDEX_CACHE_RUNS", 2)
    monkeypatch.setattr(S, "CASE_INDEX_CACHE_LINES", 10_000)
    first = S._case_index("r0")
    S._case_index("r1")
    assert S._case_index("r0") is first, "повторне читання мало прийти з кешу"
    S._case_index("r2")                      # r1 читали давніше за r0 → іде геть саме він
    assert list(S._CACHE) == ["r0", "r2"]


def test_cache_line_cap_evicts_but_keeps_the_last_run(runs, monkeypatch) -> None:
    S = runs
    monkeypatch.setattr(S, "CASE_INDEX_CACHE_RUNS", 10)
    monkeypatch.setattr(S, "CASE_INDEX_CACHE_LINES", 3)
    S._case_index("r0")                      # 1 рядок
    S._case_index("r1")                      # +2 = 3, ще вкладається
    assert list(S._CACHE) == ["r0", "r1"]
    S._case_index("r3")                      # 4 рядки — більше за всю стелю, лишається сам
    assert list(S._CACHE) == ["r3"]
    assert len(S._case_index("r3")) == 4


def test_cached_index_is_the_same_as_fresh(runs, monkeypatch) -> None:
    """Стеля не міняє вмісту: витіснений прогін читається знову тим самим."""
    S = runs
    monkeypatch.setattr(S, "CASE_INDEX_CACHE_RUNS", 1)
    before = list(S._case_index("r2"))
    S._case_index("r1")
    assert "r2" not in S._CACHE
    assert S._case_index("r2") == before
