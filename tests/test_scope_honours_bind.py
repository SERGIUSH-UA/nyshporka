"""Прив'язку, поставлену людиною (`cases.bind`), пошук бачить так само, як реєстр.

Після переїзду теки справи мета прогону несе мертвий `case_dir` і порожній
`case_key`. `cases.bind` пише рішення в `overrides.json`; реєстр його читав
(«нерозв'язаних 0»), а область пошуку будувалась лише з мети — і `search --case`
на тій самій справі казав «жодного прогону» (issue #20).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.pagestore.store import CaseRef

KEY = "DAHMO/R-100/1/7"
RUNS = [
    # переїхала тека: ключа в меті немає, шлях мертвий
    {"name": "проба-фонд-Р", "case_key": "", "case_dir": "D:/gone/R-100-1-7",
     "pages_done": 12},
    # чужа справа, але мета помилково вказує на нашу теку
    {"name": "чужий", "case_key": "", "case_dir": "data/raw/dahmo_R-100/spr-7",
     "pages_done": 5},
    # ключ у меті правильний — працювало й доти
    {"name": "свій", "case_key": KEY, "case_dir": "", "pages_done": 3},
]


@pytest.fixture
def scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    # 🔴 Свій простір ДО імпорту `htr_store`: той читає `workspace()` на рівні
    # модуля, і після тесту, що скинув простір (`test_pack_scope`), імпорт
    # падав на «простір не знайдено» — тест залежав від порядку файлів.
    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    from nyshporka import htr_store as S

    S._canon_case_key.cache_clear()
    from nyshporka.cases import resolve as R
    from nyshporka.pagestore import store as PS

    monkeypatch.setattr(R, "overrides_path", lambda: tmp_path / "overrides.json")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in RUNS])
    monkeypatch.setattr(S, "find_runs_for_case", lambda p: [
        dict(r) for r in RUNS if r["case_dir"] == p])
    ref = CaseRef(key=KEY, repo="DAHMO", fond="R-100", spr="7", opys="1",
                  shifra="ДАХмО R-100-1-7", path="data/raw/dahmo_R-100/spr-7")

    def _resolve(v: str, *, claim: bool = True) -> CaseRef:
        # Лише тестова справа: чужий ключ резолвер не сміє звести до неї,
        # інакше прив'язка «деінде» тихо стала б прив'язкою сюди.
        if v in (KEY, "ДАХмО R-100-1-7"):
            return ref
        raise ValueError(f"не розпізнав {v}")

    monkeypatch.setattr(PS, "resolve_case", _resolve)
    S._canon_case_key.cache_clear()
    yield S, R
    S._canon_case_key.cache_clear()
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    S._canon_case_key.cache_clear()
    W.reset()


def _names(sc: dict[str, Any]) -> set[str]:
    return {r["name"] for r in sc["rows"]}


def test_bound_run_is_in_the_case_scope(scope: Any) -> None:
    S, R = scope
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == {"свій"}
    R.bind_run("проба-фонд-Р", KEY, "теку перенесено", force=True)
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == {"свій", "проба-фонд-Р"}


def test_run_scope_reports_the_bound_key(scope: Any) -> None:
    S, R = scope
    R.bind_run("проба-фонд-Р", KEY, "теку перенесено", force=True)
    assert S.runs_for_scope("проба-фонд-Р")["key"] == KEY


def test_override_elsewhere_beats_meta_key(scope: Any) -> None:
    """Рішення людини сильніше за ключ мети — як у `resolve_run`."""
    S, R = scope
    R.bind_run("свій", "DAHMO/315/8433", "насправді інша книга", force=True)
    assert "свій" not in _names(S.runs_for_scope("ДАХмО R-100-1-7"))


def test_unbound_run_is_not_taken_by_case_dir(scope: Any, tmp_path: Path) -> None:
    """`key: null` — прогін свідомо нічий, хоч мета й вказує на теку справи."""
    S, R = scope
    (tmp_path / "overrides.json").write_text(
        '{"runs": {"свій": {"key": "DAHMO/315/8433"}, "чужий": {"key": null}}}',
        encoding="utf-8")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    # без збігу за ключем пошук іде в резерв за текою — і там «чужий» відсікається
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == set()


def test_shyfra_v_case_key_tezh_svoia(scope: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Старий прогін несе в `case_key` шифру, а не ключ — і лишається своїм.

    Інакше справа, прочитана повністю, для пошуку й пакувальника «без прогонів».
    """
    S, _ = scope
    S._canon_case_key.cache_clear()
    rows = [*RUNS, {"name": "старий", "case_key": "ДАХмО R-100-1-7",
                    "case_dir": "E:/elsewhere/spr-7", "pages_done": 26}]
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in rows])
    try:
        assert "старий" in _names(S.runs_for_scope("ДАХмО R-100-1-7"))
    finally:
        S._canon_case_key.cache_clear()


# ── той самий ключ і поза пошуком: стор тексту й `share suggest` ─────────────
# Відгук 18.10.2026: після `cases bind` реєстр і Супряга показували справу
# правильно, а `share suggest` пропонував «справу без кадрів» зі старим ключем
# мети, і `text index --rebuild` писав у стор той самий старий ключ.

STALE = "DAHMO/R-1000/1/7"   # номер, що прилип до фонду, — як 800-1-8а → 10800-1-8


def test_run_key_takes_the_bind_over_the_meta(scope: Any) -> None:
    S, R = scope
    row = {"name": "проба-фонд-Р", "case_key": STALE, "case_dir": ""}
    assert S.run_key(row) != KEY
    R.bind_run("проба-фонд-Р", KEY, "номер у теці застарів", force=True)
    assert S.run_key(row) == KEY


def test_text_index_writes_the_bound_key(scope: Any) -> None:
    _, R = scope
    from nyshporka.search import store as ST

    R.bind_run("проба-фонд-Р", KEY, "номер у теці застарів", force=True)
    assert ST._run_key("проба-фонд-Р", {"case_key": STALE}) == KEY
    # нерозв'язаний прогін лишає ключ мети як був
    assert ST._run_key("нічий", {"case_key": STALE}) == STALE


def test_share_suggest_offers_the_bound_key(scope: Any, monkeypatch) -> None:
    S, R = scope
    from nyshporka.share import publish as PB
    from nyshporka.share import suggest as SG

    rows = [{"name": "проба-фонд-Р", "case_key": STALE, "case_dir": "D:/gone/x",
             "pages_done": 12}]
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in rows])
    monkeypatch.setattr(SG, "vidmovleni", lambda: set())
    monkeypatch.setattr(SG, "viddani", lambda: set())
    monkeypatch.setattr(SG, "_u_puli", lambda k: None)
    monkeypatch.setattr(SG, "_u_puli_poruch", lambda k, s: {})
    monkeypatch.setattr(PB, "znamennyk_spravy",
                        lambda k, s: {"total": 12 if k == KEY else 0, "unknown": ""})
    R.bind_run("проба-фонд-Р", KEY, "номер у теці застарів", force=True)

    got = SG.nepodileni()
    assert [r["case_key"] for r in got] == [KEY]
    assert got[0]["frames"] == 12, "справа з кадрами, а не «без кадрів»"


def test_meta_key_stale_only_by_opys_takes_the_library_key() -> None:
    """Літерний опис «5д» колись читався як «5»: тека — та сама справа."""
    from nyshporka import htr_store as S

    assert S._stale_opys("DADNO/6508/5/2", "DADNO/6508/5d/2") == "DADNO/6508/5d/2"
    # інший фонд чи номер — рішення людини, не здогад
    assert S._stale_opys("DAVIO/10800/1/8", "DAVIO/800/1/8a") == "DAVIO/10800/1/8"
    assert S._stale_opys("DAVIO/109/1/42", "DAVIO/109/1/56") == "DAVIO/109/1/42"
    assert S._stale_opys("DADNO/6508/5/2", "") == "DADNO/6508/5/2"


def test_a_run_with_the_old_opys_belongs_to_its_case(scope: Any) -> None:
    """Прогін справи «5д», записаний до виправлення опису, — при своїй справі:
    без цього він лишався нічиїм і вимагав `cases bind` на кожен прогін."""
    S, _ = scope
    row = S._decorate({"name": "5d-2", "case_key": "DADNO/6508/5/2",
                       "case_dir": "data/raw/dadno_6508/5d-2"},
                      lambda p: {"key": "DADNO/6508/5d/2", "shifra": "ДАДнО Р-6508-5д-2"})
    assert row["case_canon"] == "DADNO/6508/5d/2"
    assert S.run_key(row) == "DADNO/6508/5d/2"
