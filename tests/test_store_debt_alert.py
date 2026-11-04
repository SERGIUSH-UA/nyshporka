"""Прочитане поза стором пошуку — тривога, а не сіра примітка.

04.11.2026: `text grep` по серії прочесав 9 прогонів із 328 і сказав «не
знайшлось»; «319 прогонів поза стором» стояло поряд сірою приміткою. Реєстр,
який перебудовують після кожної дії, про борг стору не казав нічого.
"""
from __future__ import annotations

from types import SimpleNamespace

from nyshporka import cli_emit
from nyshporka.cases import db
from nyshporka.core.envelope import ALERT, NOTE, ok
from nyshporka.ops_text import partial_store_alert


def test_partial_store_is_an_alert_with_the_fix_and_stale_mark() -> None:
    env = ok({})
    partial_store_alert(env, 319, 328, "11-2", zero=True)
    w = [x for x in env.warnings if x.code == "partial_store"]
    assert w and w[0].level == ALERT, "неповний стор мусить бути тривогою, не приміткою"
    assert "319 із 328" in w[0].text and "нуль нічого не доводить" in w[0].text
    assert 'nysh text index --case "11-2"' in w[0].text
    assert env.stale is not None and env.stale.is_stale, "відповідь мусить бути позначена застарілою"
    assert env.stale.fix == 'nysh text index --case "11-2"'
    nxt = [n for n in env.next if n.op == "text.index"]
    assert nxt and nxt[0].level == ALERT and nxt[0].args == {"case": ["11-2"]}


def test_partial_store_with_hits_says_incomplete_and_lists_every_case() -> None:
    env = ok({})
    partial_store_alert(env, 2, 0, ["A 1-2-3", "B 4-5-6"], zero=False)
    text = env.warnings[0].text
    assert "видача неповна" in text and "із" not in text.split("прогонів")[0]
    assert '--case "A 1-2-3" --case "B 4-5-6"' in text


def test_full_store_adds_nothing() -> None:
    env = ok({})
    partial_store_alert(env, 0, 328, "11-2", zero=True)
    assert not env.warnings and env.stale is None and not env.next


def test_terminal_shows_the_alert_first_and_not_greyed() -> None:
    env = ok({})
    env.warn("zero_with_denominator", "не знайшлось — прочесано прогонів: 9", level=NOTE)
    partial_store_alert(env, 319, 328, "11-2", zero=True)
    with cli_emit.console.capture() as cap:
        cli_emit.notes(env)
    out = cap.get()
    assert "🔴 319 із 328" in out, out
    assert out.index("🔴 319") < out.index("не знайшлось"), "тривога мусить стояти перед нулем"


def _fake_store(monkeypatch, stored: dict[str, str], now: dict[str, str],
                same_text: set[str] = frozenset()) -> None:
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    class _Conn:
        def execute(self, _sql: str):
            return list(stored.items())

        def close(self) -> None:
            pass

    def _restamp(runs: list[str]) -> int:
        tak = [r for r in runs if r in same_text]
        for r in tak:
            stored[r] = now[r]
        return len(tak)

    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "connect", lambda readonly=False, **_: _Conn())
    monkeypatch.setattr(ST, "restamp_meta_only", _restamp)
    monkeypatch.setattr(D, "stamps_of", lambda runs: {r: now.get(r, "") for r in runs})


def test_registry_counts_runs_outside_the_store(monkeypatch) -> None:
    _fake_store(monkeypatch, {"a": "s1", "b": "s2"}, {"a": "s1", "b": "s2"})
    rows = [SimpleNamespace(shifra="X 1-1-1", htr_runs=["a", "c"]),
            SimpleNamespace(shifra="Y 2-2-2", htr_runs='["d", "e"]'),
            SimpleNamespace(shifra="Z 3-3-3", htr_runs=[]),
            SimpleNamespace(shifra="W 4-4-4", htr_runs=["b"])]
    debt = db.store_debt(rows)
    assert debt == {"runs": 3, "stale": 0, "cases": 2, "examples": ["Y 2-2-2", "X 1-1-1"],
                    "restamped": 0}


def test_registry_counts_a_run_whose_meta_was_rewritten(monkeypatch) -> None:
    """03.11.2026: перенесення кадрів переписало мету прогонів — штамп
    змінився, і пошук перестав їх брати, хоча в сторі вони лежали."""
    _fake_store(monkeypatch, {"a": "s1", "b": "s2"}, {"a": "s1", "b": "s2-після-переносу"})
    debt = db.store_debt([SimpleNamespace(shifra="А 11-2-3", htr_runs=["a", "b"])])
    assert debt == {"runs": 1, "stale": 1, "cases": 1, "examples": ["А 11-2-3"],
                    "restamped": 0}


def test_registry_restamps_a_run_whose_text_is_the_same(monkeypatch) -> None:
    """Змінилась лише мета — штамп поновлено тут же, боргу немає; переіндексація не потрібна."""
    _fake_store(monkeypatch, {"a": "s1", "b": "s2"}, {"a": "s1", "b": "s2-нова-мета"},
                same_text={"b"})
    debt = db.store_debt([SimpleNamespace(shifra="А 11-2-3", htr_runs=["a", "b"])])
    assert debt == {"runs": 0, "stale": 0, "cases": 0, "examples": [], "restamped": 1}


def test_registry_without_a_store_reports_no_debt(monkeypatch) -> None:
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "exists", lambda: False)
    assert db.store_debt([SimpleNamespace(shifra="X", htr_runs=["a"])])["runs"] is None
