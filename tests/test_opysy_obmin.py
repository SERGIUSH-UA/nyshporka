"""Обмін нормалізацією — сторона учасника: `nysh opys obmin / vziaty / viddaty` (рішення дослідника
25.11.2026). Пул підмінено: перевіряється тека з пачками й те, що саме йде на сервер."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops_opysy as OO
from nyshporka.opysy import remote as R

ZAVDANNIA = {"obmin": 5, "vnesok": 9, "shyfra": "ДАОО 445-1", "do": "2026-11-27T10:00:00+00:00",
             "repo": "DAOO", "fond": "445", "opys": "1", "title": "Балтский уездный суд",
             "years": "1800-1870", "language": "ru",
             "riadky": [{"rk": f"r{i}", "page": 1, "half": 0, "no": i,
                         "title_raw": f"Дело о помещике Ибанове {i}",
                         "posylannia": "https://archive.example/o.djvu"} for i in range(25)]}


@pytest.fixture
def pul(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    st: dict[str, Any] = {"give": []}
    monkeypatch.setattr(R, "obmin_vziaty", lambda **kw: dict(ZAVDANNIA))
    monkeypatch.setattr(R, "obmin_cherha", lambda **kw: {"opysy": [{"vnesok": 9, "stan": "chekaie"}]})

    def _give(obmin_id: int, *, model: str, vidpovidi: list[dict[str, str]], **kw: Any) -> dict[str, Any]:
        st["give"].append((obmin_id, model, vidpovidi))
        return {"pryiniato": len(vidpovidi), "porozhni": 0, "avtora": 0, "poznachky": [],
                "stan": "v_roboti", "normalizovano": len(vidpovidi), "spravy": 25}

    monkeypatch.setattr(R, "obmin_viddaty", _give)
    return st


def test_vziaty_i_viddaty(tmp_path: Path, pul: dict[str, Any]) -> None:
    d = tmp_path / "vziate"
    assert OO.opysy_obmin(OO.ObminArgs()).data["opysy"][0]["stan"] == "chekaie"
    env = OO.opysy_vziaty(OO.VziatyArgs(dir=str(d)))
    assert env.ok and env.data["nazv"] == 25 and env.data["pachok"] == 2, env
    assert "nysh opys viddaty" in env.data["next"]
    # повтор `vziaty` (продовження оренди) не нарізає пачок удруге
    assert OO.opysy_vziaty(OO.VziatyArgs(dir=str(d))).data["novykh_pachok"] == 0
    pachky = sorted(d.glob("batch_*.json"))
    b0 = json.loads(pachky[0].read_text(encoding="utf-8"))
    assert "Балтский уездный суд" in b0["request"] and b0["keys"][0]["rk"] == "r0"
    # відповідь лише на першу пачку — віддається вона; друга чекає
    pachky[0].with_name(pachky[0].stem + ".out.txt").write_text(
        json.dumps([t.replace("Ибанове", "Иванове") for t in b0["titles"]], ensure_ascii=False),
        encoding="utf-8")
    got = OO.opysy_viddaty(OO.ViddatyArgs(dir=str(d), model="agent-model"))
    assert got.ok and got.data["pryiniato"] == 20 and got.data["pachok_bez_vidpovidi"] == 1, got
    obmin_id, model, vidp = pul["give"][-1]
    assert obmin_id == 5 and model == "agent-model" and vidp[0] == {
        "rk": "r0", "title_norm": "Дело о помещике Иванове 0"}
    # віддане вдруге не шлеться
    again = OO.opysy_viddaty(OO.ViddatyArgs(dir=str(d), model="agent-model"))
    assert not again.ok and len(pul["give"]) == 1


def test_bita_vidpovid_ne_shletsia(tmp_path: Path, pul: dict[str, Any]) -> None:
    d = tmp_path / "v"
    OO.opysy_vziaty(OO.VziatyArgs(dir=str(d)))
    p = sorted(d.glob("batch_*.json"))[0]
    p.with_name(p.stem + ".out.txt").write_text('["лише одна назва"]', encoding="utf-8")
    env = OO.opysy_viddaty(OO.ViddatyArgs(dir=str(d), model="m"))
    assert not env.ok and any(w.code == "norm_bad" for w in env.warnings) and not pul["give"]
