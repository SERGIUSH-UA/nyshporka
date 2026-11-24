"""`opysy.policy`: спершу сервер (його перелік ширший і каже, куди вести людину), без мережі —
вбудований перелік пакета; відмова `init` по закритому фонду підказує, де подробиці."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops_opysy as OO
from nyshporka.opysy import remote as R
from nyshporka.opysy import workdir as W


def test_policy_z_servera(monkeypatch: pytest.MonkeyPatch) -> None:
    def _server(repo: str, fond: str, **kw: Any) -> dict[str, Any]:
        return {"open": False, "why": "Описи веде інший проєкт: https://example.org",
                "link": "https://example.org"}

    monkeypatch.setattr(R, "policy", _server)
    env = OO.opysy_policy(OO.PolicyArgs(repo="ЦДІАК", fond="442"))
    assert env.data["open"] is False and env.data["link"] == "https://example.org"
    assert env.data["dzherelo"] == "server"


def test_policy_bez_merezhi_vbudovanyi(monkeypatch: pytest.MonkeyPatch) -> None:
    def _nema(repo: str, fond: str, **kw: Any) -> dict[str, Any]:
        raise OSError("немає мережі")

    monkeypatch.setattr(R, "policy", _nema)
    env = OO.opysy_policy(OO.PolicyArgs(repo="ЦДІАК", fond="442"))
    assert env.data["open"] is False and env.data["dzherelo"] == "paket" and env.data["why"]
    env2 = OO.opysy_policy(OO.PolicyArgs(repo="ДАОО", fond="445"))
    assert env2.data["open"] is True


def test_init_zakrytyi_fond_pidkazuie_policy(tmp_path: Path) -> None:
    pdf = tmp_path / "o.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(W.WorkdirError, match="nysh opys policy"):
        W.init(tmp_path / "w", pdf, repo="ЦДІАК", fond="442", opys="1", form="hand_ruled",
               url="https://example.org/o.pdf")
