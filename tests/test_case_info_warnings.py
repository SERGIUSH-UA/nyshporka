"""⚠ Розриви покриття на картці справи — зі словами, а не порожніми плашками."""
from __future__ import annotations

from typing import Any

import pytest


def _card(**over: Any) -> dict[str, Any]:
    card: dict[str, Any] = {
        "frames": 11, "script": "cyrillic", "script_trust": "fixed",
        "engines": [{"id": "pysar", "label": "Писар"}, {"id": "diak", "label": "Дяк"}],
        "covered": {}, "gaps": [
            {"kind": "missing", "engine": "pysar", "why": "цим рушієм справу ще не читали"},
            {"kind": "missing", "engine": "diak", "why": "цим рушієм справу ще не читали"}]}
    card.update(over)
    return card


def _warnings(monkeypatch: pytest.MonkeyPatch, card: dict[str, Any]) -> list[Any]:
    from nyshporka.htr import pick
    from nyshporka.ops_builtin import CaseInfoArgs, htr_case_info

    monkeypatch.setattr(pick, "case_info", lambda *_a, **_k: card)
    return list(htr_case_info(CaseInfoArgs(case_dir="x")).warnings)


def test_unread_case_has_no_per_engine_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не читали зовсім — про це вже каже рядок «уже прочитано»."""
    assert _warnings(monkeypatch, _card()) == []


def test_a_gap_names_the_engine_and_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    card = _card(covered={"pysar": {"model": "pysar_cyr_v19.pt"}},
                 gaps=[{"kind": "missing", "engine": "diak",
                        "why": "цим рушієм справу ще не читали"}])
    got = _warnings(monkeypatch, card)
    assert [w.text for w in got] == ["Дяк: цим рушієм справу ще не читали"]
    assert all(w.text.strip() for w in got), "порожня плашка ⚠ без слова"


def test_no_note_where_the_card_offers_add_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель для рушія є — на картці кнопка «Додати голос», примітка її не дублює."""
    card = _card(covered={"pysar": {"model": "pysar_cyr_v19.pt"}},
                 gaps=[{"kind": "missing", "engine": "diak",
                        "why": "цим рушієм справу ще не читали"}],
                 models={"pysar": "pysar_cyr_v19.pt", "diak": "diak_cyr_v6.safetensors"})
    assert _warnings(monkeypatch, card) == []

