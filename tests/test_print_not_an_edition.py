"""Друк поза виданнями (`nysh cloud go --print --not-an-edition`).

Машинописний опис фонду, робоча збірка чи проба рушія читаються рушієм друку,
але не стають виданням: ключа `VYD/…` немає, у реєстр видань нічого не пишеться,
текст лягає в корінь, названий людиною, а після забору не збираються роки.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image


def _folder(root: Path, name: str, pages: int = 2) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for k in range(1, pages + 1):
        Image.new("L", (30, 20), 200).save(d / f"{k:04d}.jpg", "JPEG")
    return d


@pytest.fixture
def ws(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield W.workspace()
    W.reset()


def test_each_folder_is_its_own_run_under_the_named_root(ws: Any, tmp_path: Path) -> None:
    from nyshporka.cloud import go as GO
    from nyshporka.cloud import printed as PR

    a, b = _folder(tmp_path / "in", "r1_300"), _folder(tmp_path / "in", "r1_127")
    out = tmp_path / "out"
    cases, ed = GO._plain_cases((str(a), str(b)), vydannia="", book=0, case_key="",
                                out_root=str(out))

    assert cases == (str(a), str(b))
    assert ed["plain"] is True
    run = GO._issue_run(ed, str(a))
    assert isinstance(run, PR.PlainRun)
    assert (run.name, run.key, run.out_dir) == ("r1_300", "", out.resolve() / "r1_300")


def test_default_root_is_apart_from_editions(ws: Any, tmp_path: Path) -> None:
    from nyshporka.cloud import go as GO
    from nyshporka.cloud import printed as PR

    a = _folder(tmp_path, "opys")
    _, ed = GO._plain_cases((str(a),), vydannia="", book=0, case_key="", out_root="")

    assert GO._issue_run(ed, str(a)).out_dir == PR.plain_root() / "opys"
    assert PR.plain_root() != PR.out_root()


@pytest.mark.parametrize("kw", [{"vydannia": "KOLSELO"}, {"book": 1936},
                                {"case_key": "ЦДІАК/442/300"}])
def test_an_edition_code_or_key_is_refused(tmp_path: Path, kw: dict) -> None:
    from nyshporka.cloud import go as GO

    a = _folder(tmp_path, "opys")
    args = {"vydannia": "", "book": 0, "case_key": "", "out_root": "", **kw}
    with pytest.raises(GO.GoRefused, match="без коду видання"):
        GO._plain_cases((str(a),), **args)


def test_two_folders_with_one_name_are_refused(tmp_path: Path) -> None:
    from nyshporka.cloud import go as GO

    a, b = _folder(tmp_path / "x", "same"), _folder(tmp_path / "y", "same")
    with pytest.raises(GO.GoRefused, match="однаковим іменем"):
        GO._plain_cases((str(a), str(b)), vydannia="", book=0, case_key="", out_root="")


def test_a_folder_without_frames_is_refused(tmp_path: Path) -> None:
    from nyshporka.cloud import go as GO

    (tmp_path / "empty").mkdir()
    with pytest.raises(GO.GoRefused, match="немає кадрів"):
        GO._plain_cases((str(tmp_path / "empty"),), vydannia="", book=0, case_key="",
                        out_root="")


def test_plain_plan_has_no_key_and_writes_where_told(ws: Any, tmp_path: Path) -> None:
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import printed as PR

    a = _folder(tmp_path, "r1_300")
    plan = PL.build(a, backend="vast", script="print", out_name="r1_300",
                    out_dir=tmp_path / "out" / "r1_300", plain=True)

    assert (plan.script, plan.model.name, plan.case_key) == ("print", PR.MODEL, "")
    assert plan.out_dir == tmp_path / "out" / "r1_300"
    assert ws.htr_reports not in plan.out_dir.parents


def test_go_refuses_not_an_edition_without_print(tmp_path: Path) -> None:
    from nyshporka.cloud import go as GO

    a = _folder(tmp_path, "opys")
    res = GO.go(str(a), backend="vast", dry_run=True, script="cyrillic", not_an_edition=True)
    assert res.verdict == "refused" and "--print" in res.why
    res = GO.go(str(a), backend="vast", dry_run=True, script="print", out_root=str(tmp_path))
    assert res.verdict == "refused" and "--not-an-edition" in res.why


def test_plain_is_told_by_the_key() -> None:
    from nyshporka.cloud import printed as PR

    assert PR.is_plain("") and not PR.is_plain("VYD/KOLSELO_PYR/1936")
