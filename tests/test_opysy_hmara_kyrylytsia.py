"""Відгук №28 (27.11.2026): хмара прочитала машинопис, а `read` результату не забрав.

Робоча тека з кирилицею (`описи\\ДАПО\\П-12-1`). Дочірній `nysh cloud go` писав підсумок у трубу
кодуванням консолі, кирилиця в `out_dir` ставала «?», теки результату не знаходилось — і `read`
стирав стан етапу, тобто наступний виклик поставив би платний захід удруге.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nyshporka import ops_opysy as OO
from nyshporka.opysy import hmara as H

#: Дитина пише так, як пише Python у трубу на Windows: кодування з `PYTHONIOENCODING`, інакше
#: ANSI-сторінка системи (тут cp1252, де кирилиці немає), і непридатне — «?» (`errors=replace`).
CHILD = (
    "import json, os, sys\n"
    "enc = os.environ.get('PYTHONIOENCODING') or 'cp1252'\n"
    "line = json.dumps({'verdict': 'detached', 'run_id': 'r1', "
    "'out_dir': r'C:\\описи\\ДАПО\\П-12-1\\hmara\\vyhid\\x'}, ensure_ascii=False)\n"
    "sys.stdout.buffer.write((line + '\\n').encode(enc, errors='replace'))\n"
)


def test_cloud_go_chytaie_kyrylytsiu_dytyny(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Підсумок дитини з кириличною адресою доходить цілим."""
    real = subprocess.run

    def fake(cmd: list[str], **kw: Any) -> Any:
        # Середовище машини без `PYTHONIOENCODING`; дитина дістає його, лише якщо поставив `_cloud_go`.
        passed = kw.pop("env", None) or {}
        env = {**_bez_io(), **{k: v for k, v in passed.items() if k == "PYTHONIOENCODING"}}
        return real([sys.executable, "-c", CHILD], env=env, **kw)

    monkeypatch.setattr(H.subprocess, "run", fake)
    _kod, res, _ = H._cloud_go(["x"])
    assert res["out_dir"] == r"C:\описи\ДАПО\П-12-1\hmara\vyhid\x"


def _bez_io() -> dict[str, str]:
    """Середовище тесту без власного `PYTHONIOENCODING`: його мусить поставити сам `_cloud_go`."""
    import os

    return {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}


def _opys(tmp: Path) -> Path:
    d = tmp / "описи" / "ДАПО" / "П-12-1"
    d.mkdir(parents=True)
    (d / "opys.json").write_text(json.dumps({"repo": "DAPO", "fond": "П-12", "opys": "1"}),
                                 encoding="utf-8")
    return d


def _druk(d: Path, *, kadriv: int, vyhid: int) -> tuple[Path, Path]:
    """Теки так, як їх лишили `postavyty` і наглядач: кадри етапу й вихід рушія друку."""
    teka = d / H.DIR / f"{H.slug(d)}-druk"
    teka.mkdir(parents=True)
    for i in range(1, kadriv + 1):
        (teka / f"{i:04d}.jpg").write_bytes(b"x")
    out = d / H.DIR / "vyhid" / teka.name
    out.mkdir(parents=True)
    for i in range(1, vyhid + 1):
        (out / f"{i:04d}.md").write_text("| 1 | Дело |", encoding="utf-8")
    return teka, out


def _reiestr(monkeypatch: pytest.MonkeyPatch, *runs: Any) -> None:
    from nyshporka.cloud import state as ST

    monkeypatch.setattr(ST, "all_runs", lambda: list(runs))
    monkeypatch.setattr(ST, "load", lambda rid: next((r for r in runs if r.run_id == rid), None))


def _run(teka: Path, out: Path, **kw: Any) -> SimpleNamespace:
    base = {"run_id": "opys-dapo-druk__4dc325fb", "phase": "done", "verdict": "ok",
            "case_dir": str(teka), "out_dir": str(out), "updated": 1.0, "why": ""}
    return SimpleNamespace(**{**base, **kw})


def _ne_staviaty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("новий платний захід не мав ставитись")

    monkeypatch.setattr(H, "_cloud_go", boom)
    monkeypatch.setattr(H, "postavyty", boom)


def test_stan_styrto_hotovyi_zakhid_pidkhopliuietsia(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Стан відгуку №28: `hmara.json` = {}, 74 виходи на диску, реєстр — done · ok.
    `read` забирає готове й не ставить заходу."""
    d = _opys(tmp_path)
    teka, out = _druk(d, kadriv=74, vyhid=74)
    H.zapysaty_stan(d, {})
    _reiestr(monkeypatch, _run(teka, out))
    _ne_staviaty(monkeypatch)
    kudy = d / "vl"
    stan, zap = OO._hmara_etap(d, "druk", teka, kudy, OO.ReadOpysArgs(dir=str(d), de="hmara"))
    assert stan == "gotovo" and zap.get("zabrano")
    assert len(list(kudy.glob("*.md"))) == 74


def test_nepovnyi_chuzhyi_zakhid_ne_pidkhopliuietsia(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Вихід покриває не всі кадри теки (інша мітка, обрив) — не береться."""
    d = _opys(tmp_path)
    teka, out = _druk(d, kadriv=3, vyhid=2)
    _reiestr(monkeypatch, _run(teka, out))
    assert H.pidkhopyty(d, "druk") is None
    _reiestr(monkeypatch, _run(teka, out, verdict="failed", phase="failed"))
    assert H.pidkhopyty(d, "druk") is None


def test_ziPsovana_adresa_v_stani_berEtsia_z_reiestru(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Стан пам'ятає захід, але `out_dir` у ньому з «?» — тека результату береться з реєстру."""
    d = _opys(tmp_path)
    teka, out = _druk(d, kadriv=3, vyhid=3)
    zipsovana = str(out).replace("описи", "?????")
    H.zapysaty_stan(d, {"druk": {"run_id": "opys-dapo-druk__4dc325fb", "out_dir": zipsovana,
                                 "teka": str(teka), "kadriv": 3}})
    _reiestr(monkeypatch, _run(teka, out))
    _ne_staviaty(monkeypatch)
    stan, zap = OO._hmara_etap(d, "druk", teka, d / "vl", OO.ReadOpysArgs(dir=str(d), de="hmara"))
    assert stan == "gotovo" and zap["out_dir"] == str(out)


def test_uspishnyi_zakhid_bez_vyhodu_ne_styraie_stanu(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Реєстр каже «прочитано», а теки результату немає ніде — відмова з адресою, стан лишається:
    стерти його означало б платний захід удруге."""
    d = _opys(tmp_path)
    teka, out = _druk(d, kadriv=3, vyhid=0)
    out.rmdir()
    H.zapysaty_stan(d, {"druk": {"run_id": "opys-dapo-druk__4dc325fb", "out_dir": str(out),
                                 "teka": str(teka), "kadriv": 3}})
    _reiestr(monkeypatch, _run(teka, out))
    _ne_staviaty(monkeypatch)
    with pytest.raises(H.HmaraError, match="не платити вдруге"):
        OO._hmara_etap(d, "druk", teka, d / "vl", OO.ReadOpysArgs(dir=str(d), de="hmara"))
    assert "druk" in H.stan(d)
