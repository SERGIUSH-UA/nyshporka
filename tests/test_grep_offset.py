"""`text grep`: гортання, рання зупинка, чесний підсумок і обрив.

Еталон — той самий `store.grep` із повним обходом (`count_all`) і великим
лімітом: сторінки видачі, зшиті підряд, мусять дати рівно його хіти — без
дублів і без дір — і в серійному обході, і пачками, і справжніми процесами.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from test_grep_fast import PAGES, space  # noqa: F401  (фікстура простору)

from nyshporka.search import store as ST

RUNS = [*PAGES, "немає-такого"]
PATTERNS = ["Ковальчинск", r"\d{2,4}", "(Ков|Кав)альчинск", "Тих[ії]", "і"]


def _key(h: dict[str, Any]) -> tuple[str, str, int]:
    return h["name"], h["page"], h["line_no"]


def _everything(pattern: str) -> dict[str, Any]:
    return ST.grep(pattern, RUNS, limit=10_000, context=1, count_all=True)


def _walk(pattern: str, limit: int, *, by_cursor: bool) -> list[dict[str, Any]]:
    """Уся видача сторінками по `limit` — через `next_offset` або `next_cursor`."""
    out: list[dict[str, Any]] = []
    offset, cursor = 0, ""
    for _ in range(1000):
        got = ST.grep(pattern, RUNS, limit=limit, context=1, count_all=False,
                      offset=0 if by_cursor else offset, cursor=cursor if by_cursor else "")
        assert not got.get("error"), got
        out.extend(got["hits"])
        if not got["more"]:
            return out
        assert got["hits"], "more без жодного хіта — гортання стоїть на місці"
        offset, cursor = got["next_offset"], got["next_cursor"]
    raise AssertionError("гортання не закінчилось")


@pytest.fixture(params=["serial", "chunked", "processes"])
def mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "chunked":
        monkeypatch.setattr(ST, "GREP_PARALLEL_PAGES", 1)
        monkeypatch.setattr(ST, "GREP_SEQ_PAGES", 1)
        monkeypatch.setattr(ST, "GREP_CHUNK_PAGES", 2)
        monkeypatch.setenv(ST.SWEEP_WORKERS_ENV, "1")
    elif request.param == "processes":
        monkeypatch.setattr(ST, "GREP_PARALLEL_PAGES", 1)
        monkeypatch.setattr(ST, "GREP_SEQ_PAGES", 1)
        monkeypatch.setattr(ST, "GREP_CHUNK_PAGES", 1)
        monkeypatch.setenv(ST.SWEEP_WORKERS_ENV, "2")
    return str(request.param)


@pytest.mark.usefixtures("space")
@pytest.mark.parametrize("pattern", PATTERNS)
def test_pages_stitch_into_one_big_answer(pattern: str, mode: str) -> None:
    if mode == "processes" and pattern not in PATTERNS[:2]:
        pytest.skip("процеси — старт пулу на кожну сторінку; досить двох регексів")
    big = _everything(pattern)["hits"]
    assert big, pattern
    limits = (1, 3) if mode == "processes" else (1, 2, 3, 7)
    for limit in limits:
        for by_cursor in (False, True):
            got = _walk(pattern, limit, by_cursor=by_cursor)
            assert [_key(h) for h in got] == [_key(h) for h in big], (pattern, limit, by_cursor)
            assert got == big
    # довільний зсув — той самий зріз
    for offset in (0, 1, len(big) // 2, len(big) - 1, len(big), len(big) + 5):
        got = ST.grep(pattern, RUNS, limit=2, context=1, count_all=False, offset=offset)
        assert got["hits"] == big[offset:offset + 2], (pattern, offset)


@pytest.mark.usefixtures("space")
def test_early_stop_says_so_and_under_limit_does_not() -> None:
    full = _everything("Ковальчинск")
    n = full["total"]
    assert n >= 4
    got = ST.grep("Ковальчинск", RUNS, limit=2, context=1, count_all=False)
    assert got["more"] is True and got["stopped_early"] is True
    assert got["interrupted"] is False
    assert got["total"] is None                      # повного числа ніхто не рахував
    assert got["total_at_least"] == 3                # видача + проба
    assert got["next_offset"] == 2 and got["next_cursor"]
    assert got["pages_scanned"] < full["pages_scanned"]
    assert got["stopped_at"] and got["stopped_at"]["name"] in PAGES
    # під лімітом — як доти: повний обхід, точне число, без «є ще»
    for limit in (n, n + 1, 1000):
        under = ST.grep("Ковальчинск", RUNS, limit=limit, context=1, count_all=False)
        assert under["more"] is False and under["stopped_early"] is False
        assert under["total"] == n and under["next_offset"] is None
        assert under["next_cursor"] is None and under["stopped_at"] is None
        assert under["pages_scanned"] == full["pages_scanned"]
    # count_all: точне число й «є ще» разом
    counted = ST.grep("Ковальчинск", RUNS, limit=2, context=1, count_all=True)
    assert counted["total"] == n and counted["more"] is True
    assert counted["stopped_early"] is False and counted["next_offset"] == 2


@pytest.mark.usefixtures("space")
@pytest.mark.parametrize("pattern", PATTERNS)
def test_total_never_lies(pattern: str, mode: str) -> None:
    if mode == "processes":
        pytest.skip("процеси — у тесті зшивання")
    true_total = _everything(pattern)["total"]
    for limit in (1, 2, 5, 100):
        for offset in (0, 1, 3):
            got = ST.grep(pattern, RUNS, limit=limit, count_all=False, offset=offset)
            if got["total"] is not None:
                assert got["total"] == true_total
                assert not got["stopped_early"]
            assert got["total_at_least"] <= true_total
            assert got["more"] == (offset + limit < true_total)
    # з курсором повного числа немає, навіть якщо обхід дійшов до кінця
    first = ST.grep(pattern, RUNS, limit=1, count_all=False)
    if first["more"]:
        rest = ST.grep(pattern, RUNS, limit=10_000, count_all=False, cursor=first["next_cursor"])
        assert rest["total"] is None and rest["total_at_least"] == true_total - 1


@pytest.mark.usefixtures("space")
def test_bad_cursor_is_an_error_not_a_full_scan() -> None:
    got = ST.grep("Ковальчинск", RUNS, cursor="кудись")
    assert got["error"] and not got["hits"]


@pytest.mark.usefixtures("space")
def test_ctrl_c_mid_scan_returns_found_and_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    """М'який обрив у серійному обході: знайдене віддається, курсор веде далі."""
    big = _everything(r"\d{2,4}|Ковальчинск")["hits"]
    real = ST._page_rows
    state = {"n": 0}

    def flaky(conn: Any, pids: list[int], run_set: set[int]) -> Any:
        for row in real(conn, pids, run_set):
            state["n"] += 1
            if state["n"] == 5:
                raise KeyboardInterrupt
            yield row

    monkeypatch.setattr(ST, "_page_rows", flaky)
    got = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=100, context=1, count_all=False)
    monkeypatch.setattr(ST, "_page_rows", real)
    assert got["interrupted"] is True and got["stopped_early"] is True
    assert got["more"] is True and got["total"] is None
    assert 0 < len(got["hits"]) < len(big)
    assert got["hits"] == big[:len(got["hits"])]           # чесний префікс
    assert got["pages_scanned"] == 4
    rest = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=100, context=1, count_all=False,
                   cursor=got["next_cursor"])
    assert got["hits"] + rest["hits"] == big
    again = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=100, context=1, count_all=False,
                    offset=got["next_offset"])
    assert again["hits"] == rest["hits"]


@pytest.mark.usefixtures("space")
def test_ctrl_c_while_offset_still_skipping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обрив до того, як пропуск `offset` вичерпано: курсор несе решту пропуску."""
    big = _everything(r"\d{2,4}|Ковальчинск")["hits"]
    real = ST._page_rows
    state = {"n": 0}

    def flaky(conn: Any, pids: list[int], run_set: set[int]) -> Any:
        for row in real(conn, pids, run_set):
            state["n"] += 1
            if state["n"] == 3:
                raise KeyboardInterrupt
            yield row

    monkeypatch.setattr(ST, "_page_rows", flaky)
    off = len(big) - 2
    got = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=5, context=1, count_all=False, offset=off)
    monkeypatch.setattr(ST, "_page_rows", real)
    assert got["interrupted"] and not got["hits"] and got["next_offset"] == off
    rest = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=5, context=1, count_all=False,
                   cursor=got["next_cursor"])
    assert rest["hits"] == big[off:]


@pytest.mark.usefixtures("space")
def test_ctrl_c_in_processes_keeps_in_order_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обрив, поки працюють воркери: пул закрито, видано лише префікс у порядку."""
    monkeypatch.setattr(ST, "GREP_PARALLEL_PAGES", 1)
    monkeypatch.setattr(ST, "GREP_SEQ_PAGES", 1)
    monkeypatch.setattr(ST, "GREP_CHUNK_PAGES", 1)
    monkeypatch.setenv(ST.SWEEP_WORKERS_ENV, "2")
    big = _everything(r"\d{2,4}|Ковальчинск")["hits"]
    real = ST._GrepAcc.absorb
    state = {"n": 0}

    def flaky(self: Any, part: Any) -> None:
        state["n"] += 1
        if state["n"] == 4:
            raise KeyboardInterrupt
        real(self, part)

    monkeypatch.setattr(ST._GrepAcc, "absorb", flaky)
    got = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=100, context=1, count_all=False)
    monkeypatch.setattr(ST._GrepAcc, "absorb", real)
    assert got["interrupted"] is True and got["more"] is True
    assert got["hits"] == big[:len(got["hits"])]
    rest = ST.grep(r"\d{2,4}|Ковальчинск", RUNS, limit=100, context=1, count_all=False,
                   cursor=got["next_cursor"])
    assert got["hits"] + rest["hits"] == big


@pytest.mark.usefixtures("space")
def test_on_hit_streams_and_keeps_answer_light() -> None:
    seen: list[dict[str, Any]] = []
    got = ST.grep("Ковальчинск", RUNS, limit=3, context=1, count_all=False, on_hit=seen.append)
    assert got["hits"] == [] and got["returned"] == 3
    assert seen == _everything("Ковальчинск")["hits"][:3]


_CHILD = textwrap.dedent("""
    import json, sys, threading, time
    from pathlib import Path


    def main():
        root = Path(sys.argv[1])
        from nyshporka import htr_store as S
        from nyshporka.core import workspace as W
        from nyshporka.search import store as ST
        W.use(W.Workspace(root=root, name="тест", origin="test"))
        S.case_base = lambda: root
        S.htr_root = lambda: root / "reports" / "htr"
        ST.GREP_PARALLEL_PAGES = 1
        ST.GREP_SEQ_PAGES = 1
        ST.GREP_CHUNK_PAGES = 1
        t = time.perf_counter()
        got = ST.grep("Кавальчинск", sys.argv[2:], limit=1, count_all=False)
        alive = [th.name for th in threading.enumerate()
                 if th is not threading.main_thread() and not th.daemon]
        print(json.dumps({"stopped": got["stopped_early"], "more": got["more"],
                          "hits": len(got["hits"]), "threads": alive,
                          "sec": time.perf_counter() - t}))


    if __name__ == "__main__":
        main()
""")



def test_process_exits_after_early_stop_with_workers(space: Path, tmp_path: Path) -> None:  # noqa: F811
    """Рання зупинка з двома воркерами — і процес виходить сам, без висячих потоків."""
    import os

    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1")
    env[ST.SWEEP_WORKERS_ENV] = "2"
    src = str(Path(ST.__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, str(script), str(space), *PAGES],
                       capture_output=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    out = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    assert out["stopped"] is True and out["more"] is True and out["hits"] == 1
    assert out["threads"] == [], out


# ── операція й командний рядок ───────────────────────────────────────────────
@pytest.mark.usefixtures("space")
def test_op_pages_and_flags() -> None:
    from nyshporka import ops as O

    env = O.call("text.grep", {"pattern": "Ковальчинск", "limit": 2})
    assert env.ok, env.error
    d = env.data
    assert d["total"] is None and d["more"] and d["next_offset"] == 2
    assert d["total_at_least"] == 3 and d["coverage"]["stopped_early"] is True
    assert "stopped_early" in json.dumps(env.as_dict(), ensure_ascii=False, default=str)
    nxt = O.call("text.grep", {"pattern": "Ковальчинск", "limit": 2, "cursor": d["next_cursor"]})
    same = O.call("text.grep", {"pattern": "Ковальчинск", "limit": 2, "offset": 2})
    assert nxt.data["hits"] == same.data["hits"] and nxt.data["hits"]
    assert nxt.data["hits"][0]["line"] != d["hits"][-1]["line"] or \
        nxt.data["hits"][0]["page"] != d["hits"][-1]["page"]
    whole = O.call("text.grep", {"pattern": "Ковальчинск", "limit": 1000})
    assert whole.data["total"] == len(whole.data["hits"]) and whole.data["more"] is False
    assert whole.data["coverage"]["stopped_early"] is False
    # понад стелю конверта — лише з потоком у файл
    big = O.call("text.grep", {"pattern": "Ковальчинск", "limit": 5000})
    assert not big.ok and "--do" in (big.error or "")
    # шарам файлів гортання немає
    lay = O.call("text.grep", {"pattern": "Коваль", "where": "canon", "offset": 3})
    assert not lay.ok


def test_cli_prints_range_and_how_to_continue(space: Path) -> None:  # noqa: F811
    from typer.testing import CliRunner

    from nyshporka.cli import app

    res = CliRunner().invoke(app, ["text", "grep", "Ковальчинск", "--limit", "2"])
    assert res.exit_code == 0, res.output
    tail = [ln for ln in res.output.splitlines() if ln.startswith("декод:")]
    assert tail and "показано 1–2 із щонайменше 3" in tail[0], res.output
    assert "є ще: --offset 2" in res.output and "--cursor" in res.output
    res = CliRunner().invoke(app, ["text", "grep", "Ковальчинск", "--limit", "2", "--offset", "2"])
    assert "показано 3–4" in res.output, res.output
    res = CliRunner().invoke(app, ["text", "grep", "Ковальчинск", "--limit", "1000"])
    n = ST.grep("Ковальчинск", list(PAGES), limit=1000)["total"]
    assert f"декод: показано {n} із {n} ·" in res.output and "є ще" not in res.output


def test_cli_do_streams_jsonl_with_summary_last(space: Path) -> None:  # noqa: F811
    from typer.testing import CliRunner

    from nyshporka.cli import app

    out = space / "вивід" / "grep.jsonl"
    res = CliRunner().invoke(app, ["text", "grep", "Ковальчинск", "--limit", "3",
                                   "--do", str(out), "--json"])
    assert res.exit_code == 0, res.output
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["header"]["pattern"] == "Ковальчинск"
    assert "summary" in rows[-1] and rows[-1]["summary"]["more"] is True
    hits = rows[1:-1]
    assert len(hits) == 3 and all(h["line"] and "case_key" in h for h in hits)
    want = ST.grep("Ковальчинск", list(PAGES), limit=3, context=1)["hits"]
    assert [(h["name"], h["page"], h["line_no"]) for h in hits] == \
        [(h["name"], h["page"], h["line_no"]) for h in want]
    env = json.loads(res.output)
    assert env["data"]["hits"] == [] and env["data"]["streamed"] == 3
    # понад 2000 — можна, коли потоком
    res = CliRunner().invoke(app, ["text", "grep", "і", "--limit", "5000", "--do", str(out)])
    assert res.exit_code == 0 and "у файлі" in res.output, res.output


def test_cli_do_keeps_hits_when_interrupted(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Обрив посеред обходу: у файлі знайдене до обриву й підсумок з `interrupted`."""
    from typer.testing import CliRunner

    from nyshporka.cli import app

    real = ST._page_rows
    state = {"n": 0}

    def flaky(conn: Any, pids: list[int], run_set: set[int]) -> Any:
        for row in real(conn, pids, run_set):
            state["n"] += 1
            if state["n"] == 6:
                raise KeyboardInterrupt
            yield row

    monkeypatch.setattr(ST, "_page_rows", flaky)
    out = space / "g.jsonl"
    res = CliRunner().invoke(app, ["text", "grep", r"\d{2,4}|Ковальчинск", "--limit", "100",
                                   "--do", str(out)])
    assert res.exit_code == 0, res.output
    assert "перервано на" in res.output and "--offset" in res.output, res.output
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["summary"]["interrupted"] is True
    assert rows[-1]["summary"]["streamed"] == len(rows) - 2 > 0


def test_cli_do_hits_on_disk_before_hard_failure(space: Path,  # noqa: F811
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Жорсткий обрив (тут — MemoryError посеред обходу): збіги складених відрізків
    уже у файлі, а підсумку немає — файл сам каже, що неповний."""
    from typer.testing import CliRunner

    from nyshporka.cli import app

    monkeypatch.setattr(ST, "GREP_SEQ_PAGES", 2)
    real = ST._page_rows
    state = {"n": 0}

    def dying(conn: Any, pids: list[int], run_set: set[int]) -> Any:
        for row in real(conn, pids, run_set):
            state["n"] += 1
            if state["n"] == 7:
                raise MemoryError
            yield row

    monkeypatch.setattr(ST, "_page_rows", dying)
    out = space / "kill.jsonl"
    CliRunner().invoke(app, ["text", "grep", r"\d{2,4}|Ковальчинск|Тих", "--limit", "100",
                             "--do", str(out)])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert "header" in rows[0]
    assert not any("summary" in r for r in rows)
    hits = rows[1:]
    assert hits, "збіги перших відрізків мали лягти на диск до обриву"
    monkeypatch.setattr(ST, "_page_rows", real)
    want = ST.grep(r"\d{2,4}|Ковальчинск|Тих", list(PAGES), limit=100, context=1)["hits"]
    assert [h["line"] for h in hits] == [h["line"] for h in want[:len(hits)]]
