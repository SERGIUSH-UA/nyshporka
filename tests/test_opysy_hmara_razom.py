"""Кілька описів — один захід у хмару (0.49.7).

27.11.2026 `nysh opys read` ставив окремий `cloud go` на кожну теку: 110 оренд на 429 сторінок,
$12 за 1000 сторінок — кожен захід несе ~$0.2 накладних незалежно від обсягу.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops_opysy as OO
from nyshporka.opysy import hmara as H


def _opys(tmp: Path, imia: str, kadriv: int = 3) -> tuple[Path, Path]:
    d = tmp / imia
    kadry = d / "pages_druk"
    kadry.mkdir(parents=True)
    (d / "opys.json").write_text(json.dumps({"repo": "DAPO", "fond": imia, "opys": "1"}), encoding="utf-8")
    for i in range(1, kadriv + 1):
        (kadry / f"{i:04d}.jpg").write_bytes(b"x")
    return d, kadry


class _Hmara:
    """Підміна `cloud go`: пише аргументи й відповідає справами черги, як справжній."""

    def __init__(self, *, launch: str = "", dropped: tuple[str, ...] = (), case_dir_inshyi: bool = False):
        self.calls: list[list[str]] = []
        self.launch, self.dropped, self.case_dir_inshyi = launch, dropped, case_dir_inshyi

    def __call__(self, args: list[str]) -> tuple[int, dict[str, Any], str]:
        self.calls.append(list(args))
        if self.launch == "needs_confirm":
            return 3, {"verdict": "refused", "launch": "needs_confirm", "fork_high": 1.5,
                       "why": "понад стелю"}, ""
        teky = [Path(a) for a in args if not a.startswith("-") and Path(a).is_dir()]
        cases, dropped = [], []
        for t in teky:
            if t.parent.parent.name in self.dropped:
                dropped.append({"case": str(t), "why": "кадри не пройшли перевірку"})
                continue
            cases.append({"run_id": f"{t.name}__abcd1234",
                          "case_dir": str(t) + ("-shrink" if self.case_dir_inshyi else ""),
                          "out_dir": str(t.parent / "vyhid" / t.name)})
        one = cases[0] if len(cases) == 1 and len(teky) == 1 else {}
        return 0, {"verdict": "detached", "run_id": one.get("run_id", ""), "out_dir": one.get("out_dir", ""),
                   "fork_high": 0.4, "budget_usd": 1.0, "cases": cases, "dropped": dropped}, ""


@pytest.fixture(autouse=True)
def _bez_reiestru(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "_reiestr", lambda run_id: None)


def test_try_teky_odyn_zakhid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Три описи — один `cloud go`, кожна тека — свій `run_id` і своя тека результату."""
    hm = _Hmara()
    monkeypatch.setattr(H, "_cloud_go", hm)
    zapyty = [{"d": d, "etap": "druk", "kadry": k, "script": "", "mitka": ""}
              for d, k in (_opys(tmp_path, n) for n in ("a", "b", "c"))]
    got = H.postavyty_razom(zapyty)
    assert len(hm.calls) == 1
    assert sum(1 for a in hm.calls[0] if not a.startswith("-") and Path(a).is_dir()) == 3
    run_ids = {v["run_id"] for v in got.values() if isinstance(v, dict)}
    assert len(run_ids) == 3
    for z in zapyty:
        st = H.stan(z["d"])["druk"]
        assert st["run_id"].startswith(H.slug(z["d"])) and st["razom"] == 3
        assert Path(st["out_dir"]).name == Path(st["teka"]).name


def test_zistavlennia_za_run_id_koly_shliakh_inshyi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`case_dir` у відповіді — інший шлях (стиснута копія): справа зіставляється за `run_id`."""
    monkeypatch.setattr(H, "_cloud_go", _Hmara(case_dir_inshyi=True))
    zapyty = [{"d": d, "etap": "druk", "kadry": k} for d, k in (_opys(tmp_path, n) for n in ("a", "b"))]
    got = H.postavyty_razom(zapyty)
    assert all(isinstance(v, dict) for v in got.values())


def test_ponad_stelyu_nichoho_po_odnomu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Відмова всього заходу — відмова всім; стану немає, повторних заходів «по одному» немає."""
    hm = _Hmara(launch="needs_confirm")
    monkeypatch.setattr(H, "_cloud_go", hm)
    zapyty = [{"d": d, "etap": "druk", "kadry": k} for d, k in (_opys(tmp_path, n) for n in ("a", "b"))]
    got = H.postavyty_razom(zapyty)
    assert len(hm.calls) == 1
    assert all(isinstance(v, H.HmaraError) and v.zghoda for v in got.values())
    assert all("druk" not in H.stan(z["d"]) for z in zapyty)


def test_vypala_teka_bez_stanu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "_cloud_go", _Hmara(dropped=("b",)))
    zapyty = [{"d": d, "etap": "druk", "kadry": k} for d, k in (_opys(tmp_path, n) for n in ("a", "b"))]
    got = H.postavyty_razom(zapyty)
    assert isinstance(got[str(tmp_path / "a")], dict)
    assert isinstance(got[str(tmp_path / "b")], H.HmaraError)
    assert "кадри не пройшли" in str(got[str(tmp_path / "b")])
    assert "druk" not in H.stan(tmp_path / "b")


def test_odna_teka_ti_sami_arhumenty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Одна тека — рівно ті самі аргументи `cloud go`, що в 0.49.6 (свій `--out-root` у теці опису)."""
    hm = _Hmara()
    monkeypatch.setattr(H, "_cloud_go", hm)
    d, k = _opys(tmp_path, "a")
    zap = H.postavyty(d, "druk", k)
    teka = Path(zap["teka"])
    assert hm.calls == [[str(teka), "--allow-partial", "--print", "--not-an-edition", "--out-root",
                         str(d / H.DIR / "vyhid")]]
    assert "razom" not in zap


def _fake_read(a: OO.ReadOpysArgs) -> Any:
    """`opysy.read`, що одразу доходить до хмарного етапу машинопису."""
    d = Path(a.dir)
    try:
        stan, zap = OO._hmara_etap(d, "druk", d / "pages_druk", d / "vl", a)
    except H.HmaraError as exc:
        return OO.fail(str(exc))
    return OO._hmara_vidpovid(d, a, ["сторінки"], "druk", stan, zap)


def test_read_many_odyn_zakhid_i_povtor_bez_zakhodiv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hm = _Hmara()
    monkeypatch.setattr(H, "_cloud_go", hm)
    monkeypatch.setattr(OO, "opysy_read", _fake_read)
    dirs = [str(_opys(tmp_path, n)[0]) for n in ("a", "b", "c")]
    env = OO.opysy_read_many(OO.ReadManyArgs(dirs=dirs, de="hmara"))
    assert env.ok and len(hm.calls) == 1
    assert [r["stan"] for r in env.data["opysy"]] == ["postavleno"] * 3
    assert env.data["zakhody"][0]["tek"] == 3
    # повтор: захід іде — жодного нового `cloud go`
    monkeypatch.setattr(H, "skinchyvsia", lambda zap: False)
    env2 = OO.opysy_read_many(OO.ReadManyArgs(dirs=dirs, de="hmara"))
    assert len(hm.calls) == 1
    assert [r["stan"] for r in env2.data["opysy"]] == ["ide"] * 3


def test_read_many_ponad_stelyu_bez_zapasnoho_shliakhu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Стеля автозапуску — рішення людини: ні заходів по одному, ні читання тут."""
    hm = _Hmara(launch="needs_confirm")
    monkeypatch.setattr(H, "_cloud_go", hm)
    monkeypatch.setattr(OO, "opysy_read", _fake_read)
    dirs = [str(_opys(tmp_path, n)[0]) for n in ("a", "b")]
    env = OO.opysy_read_many(OO.ReadManyArgs(dirs=dirs, de="auto"))
    assert len(hm.calls) == 1
    assert [r["ok"] for r in env.data["opysy"]] == [False, False]
    assert all("--confirm" in r["how"] for r in env.data["opysy"])


def test_read_many_nova_teka_vidmova(tmp_path: Path) -> None:
    d, _ = _opys(tmp_path, "a")
    env = OO.opysy_read_many(OO.ReadManyArgs(dirs=[str(d), str(tmp_path / "nova")]))
    assert not env.ok and "по одній" in env.error
