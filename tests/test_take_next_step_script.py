"""Підказка «далі» після `cases take` не радить рушій навмання.

01.10.2026 під кириличними книгами РАЦС 1930 і 1931 (ДАХмО Р-6380-1-215, -225)
`take` надрукував «родовідні 1802 — латинка/Скриба»: рядок був незмінним для
будь-якої справи. Письмо береться лише з паспорта справи; не названо — так і
сказати.
"""
from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.cases import cli
from nyshporka.cases import take as T

_PLAN = {"repo": "DAHMO", "fond": "R-6380", "opys": "1", "spr": "215",
         "channel": "commons", "why": "один файл", "ref": "file:x.pdf",
         "case_dir": "data/raw/dahmo_R-6380/spr-215", "opys_assumed": False}


def _run(monkeypatch: pytest.MonkeyPatch, script: str) -> str:
    def fake_take(key: str, **_: Any) -> dict[str, Any]:
        return {"pages": 435, "bytes": 2**20, "case_dir": _PLAN["case_dir"],
                "in_library": True, "shifra_needs_eye": "", "script": script}

    monkeypatch.setattr(T, "plan", lambda key: dict(_PLAN))
    monkeypatch.setattr(T, "take", fake_take)
    res = CliRunner().invoke(cli.app, ["take", "DAHMO/R-6380/1/215"])
    assert res.exit_code == 0, res.output
    return res.output


def test_bez_pysma_v_pasporti_ne_radyt_skrybu(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, "")
    assert "1802" not in out
    assert "паспорт не називає" in out


@pytest.mark.parametrize("script", ["cyrillic", "latin"])
def test_pysmo_z_pasporta_ide_v_komandu(monkeypatch: pytest.MonkeyPatch,
                                        script: str) -> None:
    out = " ".join(_run(monkeypatch, script).split())
    assert f"--script {script}" in out
