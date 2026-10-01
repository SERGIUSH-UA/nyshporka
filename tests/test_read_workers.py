"""`nysh read --workers N`: кілька шардів на одній карті однією командою.

Доти шардувати з командного рядка можна було лише руками — N процесів із
`--shard k/n` і спільним `--gpu-lock`. У Docker це N контейнерів, тож
тестувальник із RTX 5060 міряв один шард і бачив карту, що здебільшого
простоює.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W
from nyshporka.htr import gpu as G
from nyshporka.htr import session as S

runner = CliRunner()


class _Plan:
    def __init__(self, case: Path, out: Path) -> None:
        self.case_dir = case
        self.out_dir = out
        self.frames = 2
        self.script = "cyrillic"
        self.model = Path("pysar_cyr_v17.pt")
        self.voice = None
        self.voices = ()
        self.gpu_lock = out.parent / "gpu.lock"
        self.seg_why = ""
        self.seg_ready = False


@pytest.fixture
def seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "skany").mkdir()
    out = tmp_path / "reports" / "htr" / "skany"

    from nyshporka.htr import run as HR

    monkeypatch.setattr(HR, "plan", lambda d, **_: _Plan(Path(d).resolve(), out))
    got: dict[str, Any] = {}

    def _read(plan: Any, **kw: Any) -> S.ReadResult:
        got.update(kw)
        return S.ReadResult(rc=0, done=2, frames=2, missing=0, partial=False,
                            stopped=False)

    monkeypatch.setattr(S, "read_case", _read)
    yield got
    W.reset()


def test_shardy_dokhodiat_do_chytannia_na_karti(seen, monkeypatch) -> None:
    monkeypatch.setattr(G, "detect_card", lambda **_: object())
    r = runner.invoke(app, ["read", "skany", "--workers", "3", "--case-key", "x"])
    assert r.exit_code == 0, r.output
    assert seen["workers"] == 3 and seen["device"] == "cuda"


def test_bez_karty_shardy_ne_vdaiut_kartu(seen, monkeypatch) -> None:
    # Без карти `Plan.shards` згортає до одного й каже чому — але лише якщо
    # пристрій не названо карткою.
    monkeypatch.setattr(G, "detect_card", lambda **_: None)
    r = runner.invoke(app, ["read", "skany", "--workers", "3", "--case-key", "x"])
    assert r.exit_code == 0, r.output
    assert seen["workers"] == 3 and seen["device"] == ""


def test_workers_i_shard_razom_vidmova(seen) -> None:
    r = runner.invoke(app, ["read", "skany", "--workers", "2", "--shard", "1/2"])
    assert r.exit_code == 2 and not seen
