"""Тека справи крізь junction лишається в просторі (`cases.register`).

🔴 Архівні теки на цій авдиторії часто лежать на іншому диску й підключені в
`data/raw` junction'ом — саме так простір тримає сотні гігабайтів кадрів.
`Path.resolve()` такий зв'язок розкриває: тека `data/raw/bev_pdh/spr-1`
ставала `D:\\архів\\bev_pdh\\spr-1`, і заведення справи казало «тека лежить
поза простором», хоча бібліотека її бачить. А з позначкою «взяти під облік»
у `nyshporka.toml` лягав зайвий корінь — та сама тека вдруге, під іншим
шляхом.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _link(link: Path, target: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"зв'язок теки тут не створюється: {exc}")


@pytest.fixture
def linked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from nyshporka.core import workspace as W

    ws = tmp_path / "простір"
    (ws / "data" / "raw").mkdir(parents=True)
    monkeypatch.setattr(W, "_override", W._override)   # повернути простір після тесту
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    target = tmp_path / "архів" / "bev_pdh"
    (target / "spr-1").mkdir(parents=True)
    link = ws / "data" / "raw" / "bev_pdh"
    _link(link, target)
    return ws, link


def test_case_path_keeps_the_path_through_the_junction(linked: tuple[Path, Path]) -> None:
    from nyshporka.cases import register as R

    _, link = linked
    assert R.case_path(link / "spr-1") == link / "spr-1"
    assert R.case_path("data/raw/bev_pdh/spr-1") == link / "spr-1"


def test_case_behind_a_junction_is_reachable(linked: tuple[Path, Path]) -> None:
    from nyshporka.cases import register as R

    _, link = linked
    assert R.reachable(R.case_path(link / "spr-1"))
