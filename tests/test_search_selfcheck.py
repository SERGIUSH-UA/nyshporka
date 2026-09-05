"""🎯 Самоперевірка: чи бачить пошук те, що око вже знайшло.

🔴 Це третє з трьох чисел, без яких нуль не є відповіддю, і єдине, якого пакет
не вмів порахувати. Перевіряється воно незалежними даними — аркушами, де
прізвище виписала людина, дивлячись на скан.

🔴 Головне, що тут стережеться: **відмова замість нуля**. Порожній recall і
нульовий recall означають протилежне — «нема чим міряти» проти «пошук сліпий»,
— і зводити їх в одне число означає видати неміряне за поміряне.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()

CASE = "DAHMO/315/8433"


def _space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
           decode: str = "родился Сикорскій Иванъ\n") -> Path:
    from nyshporka.library import build_library, write_library
    from nyshporka.pagestore import query as PQ
    from nyshporka.pagestore import store as PS

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    # 🔴 Сховище сторінок бере корінь у мить ІМПОРТУ, а pytest імпортує все на
    # збиранні — тобто `PAGES_ROOT` заморожений на одній теці для всього
    # прогону. Без цієї підміни аркуші, занесені одним тестом, бачить наступний,
    # і знаменник recall накопичується через увесь файл.
    monkeypatch.setattr(PS, "PAGES_ROOT", tmp_path / "data" / "pages")
    PQ._CACHE.clear()

    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    for n in (106, 107):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    write_library(build_library())

    # Око: на 0106 прізвище бачили й виписали.
    runner.invoke(app, ["pages", "note", CASE, "0106.jpg", "--type", "birth",
                        "--status", "full", "--surnames", "Сікорський"])

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    (run / "0106.txt").write_text(decode, encoding="utf-8")
    (run / "0107.txt").write_text("того же села крестьянинъ\n", encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic", "case_key": CASE,
        "pages": {"0106.jpg": {"lines": 1}, "0107.jpg": {"lines": 1}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    return tmp_path


@pytest.fixture
def seeing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Декод, у якому прізвище читабельне — пошук мусить його бачити."""
    yield _space(tmp_path, monkeypatch)
    W.reset()


@pytest.fixture
def blind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Той самий аркуш, але рушій скалічив прізвище в нуль."""
    yield _space(tmp_path, monkeypatch, decode="родился Cкрсхнй Иванъ\n")
    W.reset()


def test_the_search_sees_the_page_the_eye_wrote_down(seeing) -> None:
    from nyshporka.search import selfcheck as SC

    rep = SC.run(CASE, "Сікорський")
    assert rep.measured, rep.why
    assert rep.denom == ["0106.jpg"]
    assert rep.found == ["0106.jpg"]
    assert rep.pct(rep.found) == 100


def test_a_blind_decode_is_named_by_number(blind) -> None:
    """🔴 Ось заради чого: нуль по решті справи на такому пошуку не будується."""
    from nyshporka.search import selfcheck as SC

    rep = SC.run(CASE, "Сікорський")
    assert rep.measured, rep.why
    assert rep.found == []
    assert rep.missed == ["0106.jpg"]


def test_no_positives_is_a_refusal_not_a_zero(seeing) -> None:
    """🔴 Порожній recall і нульовий recall означають протилежне."""
    from nyshporka.search import selfcheck as SC

    rep = SC.run(CASE, "Ковальський")
    assert not rep.measured
    assert rep.why, "мовчазний нуль тут гірший за відмову"
    assert rep.pct(rep.found) == 0


def test_a_page_the_engine_never_read_is_out_of_the_denominator(
        tmp_path, monkeypatch) -> None:
    """🔴 Інакше ми міряли б повноту декоду й називали б це якістю пошуку."""
    from nyshporka.search import selfcheck as SC

    _space(tmp_path, monkeypatch)
    try:
        runner.invoke(app, ["pages", "note", CASE, "0107.jpg", "--type", "birth",
                            "--status", "full", "--surnames", "Сікорський"])
        # 0107 занесено оком і воно ПРОЧИТАНЕ, тож у знаменнику двоє.
        rep = SC.run(CASE, "Сікорський")
        assert rep.denom == ["0106.jpg", "0107.jpg"]
        assert rep.eye == 2
    finally:
        W.reset()


def test_the_flag_puts_the_number_next_to_the_zero(blind) -> None:
    """Число мусить стояти там, де друкується нуль, — інакше ним нехтують."""
    from nyshporka.ops_builtin import SearchArgs, search_run

    env = search_run(SearchArgs(q="Сікорський", case=CASE, selfcheck=True))
    assert env.ok
    codes = [w["code"] for w in env.as_dict()["warnings"]]
    assert "recall_measured" in codes
    assert "recall_missed" in codes
    assert env.data["selfcheck"]["missed"] == ["0106.jpg"]


def test_the_flag_refuses_without_a_case(seeing) -> None:
    from nyshporka.ops_builtin import SearchArgs, search_run

    env = search_run(SearchArgs(q="Сікорський", selfcheck=True))
    assert not env.ok
    assert "case" in (env.error or "")
