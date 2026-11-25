"""Дочит колонки № і межі справ з чорнила (`opysy.dochyt`), метадані агента (`opysy.meta`), готові
рядки (`nysh read --whole-line`). Зображення синтетичні; заміри на справжніх описах — у Майстерні."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from nyshporka.opysy import dochyt as DC
from nyshporka.opysy import meta as M
from nyshporka.opysy import ruled as RU

# ── плями ────────────────────────────────────────────────────────────────────


def test_komponenty_finds_separate_blobs_with_4_connectivity() -> None:
    m = np.zeros((20, 20), bool)
    m[2:5, 2:5] = True               # квадрат 3×3
    m[10:12, 10:16] = True           # смужка
    m[5, 5] = True                   # торкається квадрата лише по діагоналі — окрема пляма
    got = sorted(DC._komponenty(m))
    assert [g[:4] for g in got] == [[2, 5, 2, 5], [5, 6, 5, 6], [10, 12, 10, 16]]
    assert [g[4] for g in got] == [9, 1, 12]


def _storinka_z_nomeramy(tmp: Path) -> np.ndarray:
    """Папір, друкована вертикаль на всю висоту й чотири «номери» біля неї; третій торкається лінії."""
    im = Image.new("L", (600, 1400), 235)
    d = ImageDraw.Draw(im)
    d.line((300, 0, 300, 1399), fill=30, width=3)                   # лінія бланка
    for k, y in enumerate((200, 450, 700, 950)):
        x0 = 230 if k != 2 else 262                                 # третій впритул до лінії
        for j in range(3):                                          # три «цифри» по 14×36
            d.rectangle((x0 + j * 13, y, x0 + j * 13 + 8, y + 36), fill=40)
    return np.asarray(im, dtype=np.float32)


def test_plyamy_finds_numbers_and_drops_the_rule_line(tmp_path: Path) -> None:
    g = _storinka_z_nomeramy(tmp_path)
    got = DC.plyamy(g, 150, 380, 100, hmed=90.0)
    assert len(got) == 4, got
    assert all(b[2] - b[0] < 120 for b in got), "лінія бланка злилась із номером"
    assert [b[1] // 50 for b in got] == [4, 9, 14, 19]


def test_plyamy_splits_two_numbers_stacked_close() -> None:
    im = Image.new("L", (400, 800), 235)
    d = ImageDraw.Draw(im)
    for y in (200, 262):                                            # два номери рядок у рядок
        for j in range(3):                                          # «цифри» штрихами, не заливкою
            d.rectangle((150 + j * 14, y, 156 + j * 14, y + 40), fill=40)
    d.line((153, 240, 153, 262), fill=40, width=2)                  # штрих, що їх з'єднує
    got = DC.plyamy(np.asarray(im, dtype=np.float32), 100, 300, 100, hmed=60.0)
    assert len(got) == 2, got


# ── схема ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("spraw,pidtv,sprav,ochik", [
    (1049, 574, 1565, "usi"),        # ф.445: повнота 67 %
    (462, 158, 441, "usi"),          # оп.52: підтверджено 34 %
    (217, 97, 207, "zlypli"),        # оп.101: повна, 45 %
    (593, 346, 591, "zlypli"),       # оп.738: повна, 58 %
    (300, 200, 0, "zlypli"),         # невідомо скільки справ, номери читаються
])
def test_skhema_matches_the_four_measured_descriptions(spraw: int, pidtv: int, sprav: int, ochik: str) -> None:
    assert DC.skhema(spraw, pidtv, sprav)[0] == ochik


# ── підстановка й межі без номера ───────────────────────────────────────────


def test_pidstavyty_replaces_number_lines_and_injects_blobs() -> None:
    lines = [(100, 100, 140, 160, "313"), (300, 100, 900, 160, "Дело о споре"),
             (110, 400, 150, 460, "за"), (300, 400, 900, 460, "Тоже крестьянина")]
    mapa = {"0077": {"nomery": [{"id": "0077__n000", "i": 0, "box": [100, 100, 140, 160]}],
                     "plyamy": [{"id": "0077__p000", "part": 0, "box": [90, 400, 160, 460], "xv": 90},
                                {"id": "0077__p001", "part": 0, "box": [90, 700, 160, 760], "xv": 90}]}}
    chyt = {"0077__n000": "1313", "0077__p000": "1314", "0077__p001": "•"}
    out, bez = DC.pidstavyty("0077", lines, mapa, chyt, plyamy_polovyn=[0])
    assert out[0][4] == "1313"
    assert (90, 400, 160, 460, "1314") in out and not any(ln[4] == "за" for ln in out)
    assert bez == [(0, 700)]
    # половина не вибрана — плями не ставляться
    out2, bez2 = DC.pidstavyty("0077", lines, mapa, chyt, plyamy_polovyn=[])
    assert bez2 == [] and any(ln[4] == "за" for ln in out2)


def test_half_cases_turns_numberless_blob_into_a_real_start() -> None:
    lines = [(100, 100, 140, 160, "1313"), (300, 100, 900, 160, "Дело о споре между"),
             (300, 400, 900, 460, "помещиками за хутор")]
    recs = RU.half_cases(lines, 0, 1000, "0077", 0, title_starts=True)
    assert len(recs) == 1
    recs = RU.half_cases(lines, 0, 1000, "0077", 0, title_starts=True, bez_nomera=[400])
    assert len(recs) == 2 and recs[1]["no_read"] == "" and recs[1]["title"] == "помещиками за хутор"


# ── метадані ────────────────────────────────────────────────────────────────


def test_meta_roundtrip_and_rules(tmp_path: Path) -> None:
    m = M.Meta(forma="blank", rozvorot=True, kolonky=("nomer", "pochatok", "nazva", "kinets"),
               sprav=441, sprav_dzherelo="засвідчувальний напис", storinky=(3, 34))
    M.save(tmp_path, m)
    back = M.load(tmp_path)
    assert back is not None and back.sprav == 441 and back.storinky == (3, 34)
    assert back.vuzko(0) and not M.Meta(kolonky=("nomer", "nazva")).vuzko(0)
    assert back.u_tablytsi("0003") and not back.u_tablytsi("0002") and not back.u_tablytsi("0035")


@pytest.mark.parametrize("m,why", [
    (M.Meta(forma="papirus"), "форма"),
    (M.Meta(kolonky=("nomer", "nazva", "data")), "роль"),
    (M.Meta(kolonky=("nazva", "nomer")), "правіше"),
    (M.Meta(sprav=10), "звідки"),
    (M.Meta(storinky=(5, 3)), "перша-остання"),
])
def test_meta_rejects_what_the_builder_cannot_use(m: M.Meta, why: str) -> None:
    with pytest.raises(M.MetaError, match=why):
        M.perevirka(m)


def test_kudy_hlianuty_names_table_middle_and_end() -> None:
    assert M.kudy_hlianuty(34) == [2, 17, 34]
    assert M.kudy_hlianuty(1) == [1]


# ── готові рядки до раннера ─────────────────────────────────────────────────


def test_whole_line_reaches_the_runner(tmp_path: Path) -> None:
    from nyshporka.htr.run import Plan

    p = Plan(case_dir=tmp_path, out_dir=tmp_path / "out", model=tmp_path / "m.pt", script="cyrillic",
             frames=3, python=tmp_path / "py.exe", runner=tmp_path / "runner.py", whole_line=True)
    assert "--whole-line" in p.command()
    p2 = Plan(case_dir=tmp_path, out_dir=tmp_path / "out", model=tmp_path / "m.pt", script="cyrillic",
              frames=3, python=tmp_path / "py.exe", runner=tmp_path / "runner.py")
    assert "--whole-line" not in p2.command()
