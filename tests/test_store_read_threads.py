"""Блоби сторінок кількома з'єднаннями: та сама видача, що й одним, у тому самому порядку."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Стор з одного прогону на сім сторінок, рід — на кількох."""
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "reports" / "htr" / "проба"
    d.mkdir(parents=True)
    texts = {f"{i:04d}": (f"запис {i} родился Иванъ Вербищинскій\nвъ селѣ Вербівцахъ\n"
                          if i % 2 else f"восприемникъ {i} Павелъ Шевчукъ\n")
             for i in range(1, 8)}
    for stem, text in texts.items():
        (d / f"{stem}.txt").write_text(text, encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {f"{s}.jpg": {"lines": 2} for s in texts}}), encoding="utf-8")
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    assert list(ST.ensure_all(["проба"])) == ["проба"]
    yield tmp_path
    W.reset()


def _wanted() -> dict[int, set[int]]:
    from nyshporka.search import store as ST

    conn = ST.connect(readonly=True)
    try:
        return {int(pid): {0, 1, 2} for (pid,) in conn.execute("select id from pages")}
    finally:
        conn.close()


def _read(monkeypatch: pytest.MonkeyPatch, *, threads: bool) -> tuple[list, list[bool]]:
    from nyshporka.search import store as ST

    real = ST.connect
    opened: list[bool] = []

    def spy(**kw):
        opened.append(bool(kw.get("any_thread")))
        return real(**kw)

    with monkeypatch.context() as m:
        m.setattr(ST, "READ_CHUNK", 2)
        m.setattr(ST, "READ_PARALLEL_FROM", 3 if threads else 10**9)
        wanted = _wanted()
        m.setattr(ST, "connect", spy)
        conn = real(readonly=True)
        try:
            return list(ST._cands_batch(conn, wanted)), opened
        finally:
            conn.close()


def test_threads_give_the_same_lines_in_the_same_order(store: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    one, opened_one = _read(monkeypatch, threads=False)
    many, opened_many = _read(monkeypatch, threads=True)
    assert one, "перевірка беззмістовна: кандидатів немає"
    assert len({pid for pid, _no, _ns in one}) == 7
    assert many == one
    assert opened_one == []
    assert opened_many and all(opened_many), "потоки-читачі не вмикались"


def test_an_open_transaction_reads_on_its_own_connection(store: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """Чуже з'єднання не бачить незакоміченого — тоді читає викликач сам."""
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "READ_CHUNK", 2)
    monkeypatch.setattr(ST, "READ_PARALLEL_FROM", 3)
    wanted = _wanted()
    conn = ST.connect()
    try:
        pid = min(wanted)
        conn.execute("update pages set cands=null where id=?", (pid,))
        assert conn.in_transaction
        got = {p for p, _no, _ns in ST._cands_batch(conn, wanted)}
        conn.rollback()
    finally:
        conn.close()
    assert pid not in got and len(got) == 6


def test_lines_of_finds_what_a_full_parse_finds() -> None:
    """Пошук рядка за номером дає те саме, що розбір усього блоба, як було."""
    import random

    from nyshporka.search import store as ST

    def full(text: str, nos: set[int]) -> list[tuple[int, str]]:
        out = []
        for line in text.split("\n"):
            no_s, _sep, rest = line.partition("\t")
            if rest and int(no_s) in nos:
                out.append((int(no_s), rest))
        return out

    rnd = random.Random(5)
    for _ in range(300):
        nos_all = sorted(rnd.sample(range(1, 400), rnd.randint(1, 40)))
        text = "\n".join(f"{no}\t" + " ".join(
            rnd.choice(["ivan", "1", "12", "verbiscinskii", "x"]) for _ in range(rnd.randint(1, 5)))
            for no in nos_all)
        want = set(rnd.sample(range(0, 420), rnd.randint(0, 30))) | set(nos_all[:1] + nos_all[-1:])
        assert list(ST._lines_of(text, want)) == full(text, want)


def test_stop_ends_the_read_and_closes_the_readers(store: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "READ_CHUNK", 2)
    monkeypatch.setattr(ST, "READ_PARALLEL_FROM", 3)
    wanted = _wanted()
    real = ST.connect
    readers: list = []

    def spy(**kw):
        c = real(**kw)
        if kw.get("any_thread"):
            readers.append(c)
        return c

    monkeypatch.setattr(ST, "connect", spy)
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    conn = real(readonly=True)
    try:
        got = {p for p, _no, _ns in ST._cands_batch(conn, wanted, cancel=cancel)}
    finally:
        conn.close()
    assert 0 < len(got) < 7
    assert readers
    for c in readers:
        with pytest.raises(Exception, match="closed"):
            c.execute("select 1")
