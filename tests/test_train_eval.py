"""Метрики, вибір епохи по holdout (з підставленим інфером) і просування."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from nyshporka.core import workspace as W
from nyshporka.train import metrics as M
from nyshporka.train import promote as P
from nyshporka.train import select as SEL
from nyshporka.train import sets as S
from nyshporka.train import state as ST


def test_names_and_scores() -> None:
    assert M.names_of("Приходскій Священникъ Ѳедоръ Осановскій, Село Ходъ", ["Осановск"]) == ["Ѳедоръ"]
    assert M.name_score("Вишневскій", "иванъ вишневскій сынъ") >= 90
    assert M.name_score("Вишневскій", "иванъ петровъ") < 60
    m = M.measure([("Николай Ивановъ сынъ", "Николай Иванов сынъ"),
                   ("Марѳа Васильева", "Марфа Васильева")], mode="strip")
    assert m.n_ok == 2 and m.n_names == 4 and m.hit == 4 and m.cer > 0
    loose = M.measure([("Марѳа Васильева", "марфа васильева")], mode="loose")
    assert loose.cer == 0.0
    mi = M.micro({"a": m, "b": loose})
    assert 0 < mi["recall"] <= 1 and "cer" in mi
    assert M.macro({})["recall"] == 0.0


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    reg = S.registry(ws)
    for name, role, n in (("h1", "holdout", 3), ("h2", "holdout", 2), ("t", "train", 2)):
        spec = S.SetSpec(name=name, role=role, skip_names=["Осановск"])
        reg.save(spec)
        for i in range(n):
            p = reg.crops_of(spec) / "0001" / f"line_{i:03d}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.new("L", (200, 30), 255).save(p)
            reg.append_mark(name, "0001", i, f"Іоаннъ Петровъ {i} Осановскій", "ok")
    st = ST.RunState(run_id="v1__own__deadbeef", recipe="own",
                     corpus={"name": "v1", "sha256": "abc"})
    st.set_phase("fetched").save()
    out = st.out_dir()
    out.mkdir(parents=True)
    for ep in (1, 2):
        (out / f"parseq_ep{ep:02d}.pt").write_bytes(b"ep%d" % ep)
    (out / "parseq_best.pt").write_bytes(b"best")
    yield ws
    W.reset()


def _predictor(ckpt: Path, crops: list[Path]) -> list[str]:
    # ep02 читає імена, ep01 калічить, best — посередині
    good = ckpt.name == "parseq_ep02.pt"
    mid = ckpt.name == "parseq_best.pt"
    out = []
    for i, _ in enumerate(crops):
        if good:
            out.append(f"Іоаннъ Петровъ {i} Осановскій")
        elif mid:
            out.append(f"Іоаннъ Пертовъ {i} Осановскій")
        else:
            out.append(f"Иван Пыр {i} Осановскій")
    return out


def test_evaluate_ranks_by_recall_and_names_denominators(space: W.Workspace) -> None:
    rep = SEL.evaluate("v1__own__deadbeef", predictor=_predictor, ws=space)
    assert rep.sets == ["h1", "h2"] and rep.labels == ["ep01", "ep02", "best"]
    assert rep.winner_recall == "ep02" and rep.winner_cer == "ep02"
    assert rep.table["ep02"]["h1"]["recall"] == 1.0
    assert rep.table["ep01"]["h1"]["n_names"] == 6, "причт не виключено або назви не знайдено"
    assert any("<60" in w for w in rep.warnings)
    sel = SEL.load_select("v1__own__deadbeef", ws=space)
    assert sel and sel["winner_recall"] == "ep02"
    assert ST.load("v1__own__deadbeef", ws=space).phase == "evaluated"
    with pytest.raises(SEL.SelectError):
        SEL.evaluate("v1__own__deadbeef", sets=["nope"], predictor=_predictor, ws=space)
    with pytest.raises(SEL.SelectError):
        SEL.collect_ckpts(space.root / "nowhere", [], [])


def test_promote_writes_weights_card_and_production(space: W.Workspace) -> None:
    with pytest.raises(P.PromoteError, match=r"select\.json"):
        P.promote("v1__own__deadbeef", as_name="pysar_cyr_v18.pt", why="x", ws=space)
    SEL.evaluate("v1__own__deadbeef", predictor=_predictor, ws=space)
    with pytest.raises(P.PromoteError, match="why"):
        P.promote("v1__own__deadbeef", as_name="pysar_cyr_v18.pt", why=" ", ws=space)
    with pytest.raises(P.PromoteError, match="pysar_"):
        P.promote("v1__own__deadbeef", as_name="model.pt", why="x", ws=space)
    got = P.promote("v1__own__deadbeef", as_name="pysar_cyr_v18.pt",
                    why="recall 100% на h1+h2 проти 0 у ep01", ws=space)
    dest = Path(got["model"])
    assert dest.is_file() and dest.read_bytes() == b"ep2", "просунуто не переможця за recall"
    card = json.loads((dest.parent / "pysar_cyr_v18.json").read_text(encoding="utf-8"))
    assert card["checkpoint"] == "ep02" and card["license"] == P.LICENSE and card["eval"]
    prod = json.loads((dest.parent / "PRODUCTION.json").read_text(encoding="utf-8"))
    assert prod["production"]["cyrillic"]["model"] == "pysar_cyr_v18.pt"
    from nyshporka.htr import run as R

    assert R.production_choice().get("cyrillic") == "pysar_cyr_v18.pt"
    with pytest.raises(P.PromoteError, match="існує"):
        P.promote("v1__own__deadbeef", as_name="pysar_cyr_v18.pt", why="x", ws=space)
    got2 = P.promote("v1__own__deadbeef", as_name="pysar_cyr_v19.pt", why="інша", epoch=1,
                     ws=space)
    assert got2["previous"][0]["model"] == "pysar_cyr_v18.pt"
    prod = json.loads((dest.parent / "PRODUCTION.json").read_text(encoding="utf-8"))
    assert prod["production"]["cyrillic"]["_previous"][0]["model"] == "pysar_cyr_v18.pt"
