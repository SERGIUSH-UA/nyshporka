"""Читання опису в пакеті: номери ланцюжком, таблиця з цілих сторінок, пачки нормалізації,
робоча тека пакета, рендер сторінок (nyshporka.opysy.numbering / ruled / norm_batches / pack_dir /
pages). Синтетичні дані; рівність із Майстернею на справжньому описі — перевірка поза пакетом."""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from nyshporka.opysy import gates as G
from nyshporka.opysy import norm_batches as NB
from nyshporka.opysy import numbering as NU
from nyshporka.opysy import pack_dir as PD
from nyshporka.opysy import pages as PG
from nyshporka.opysy import ruled as RU
from nyshporka.opysy import schema as S


def _rec(no_read: str, title: str = "Дело о чем-то", page: str = "0001") -> dict:
    return {"page": page, "part": 0, "row": 0, "y": "10-20", "no_read": no_read, "title": title,
            "year": "", "end": "", "folios": "", "cont": False}


def test_number_anchors_fill_gaps_and_merge_extra() -> None:
    """Якорі — прочитані номери ланцюжком; хибне «7» між 2 і 4 не якір; рівний проміжок —
    `between`; зайвий рядок без номера з малої — злито з попередньою справою."""
    recs = [_rec("1"), _rec("2"), _rec("7"), _rec("4"), _rec(""), _rec("", "продолжение"), _rec("6")]
    out = NU.number(recs)
    assert [r["no"] for r in out] == [1, 2, 3, 4, 5, 6]
    assert [r["confirmed"] for r in out] == ["neighbors", "neighbors", "between", "neighbors", "", ""]
    assert out[4]["title"].endswith("продолжение")  # злито, і проміжок уже не `between`
    assert NU.num("85.") == 85 and NU.num("бит") is None
    assert NU.join(["Подоль-", "ской губ."]) == "Подольской губ."  # перенос між рядками зливається


def _page(run: Path, stem: str, lines: list[tuple[int, int, int, int, str]], size=(1000, 1400)) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / f"{stem}.txt").write_text("\n".join(t for *_, t in lines), encoding="utf-8")
    with gzip.open(run / f"{stem}.lines.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"boxes": [list(b[:4]) for b in lines], "size": list(size)}, fh)


def _run(tmp: Path) -> Path:
    run = tmp / "run"
    _page(run, "0001", [
        # рушій читає номер і перший рядок назви одним рядком; рік і аркуші — праворуч
        (100, 100, 600, 140, "12. Дело о помещике Иванове"),
        (700, 104, 780, 140, "1856"), (850, 104, 900, 140, "14"),
        (200, 150, 600, 190, "и его крестьянах"),
        (100, 300, 600, 340, "13. Дело о наследстве"),
        (700, 304, 780, 340, "1857"),
        (200, 360, 600, 400, "Тоже о разделе земли"),           # № не прочитано — за назвою
    ])
    _page(run, "0002", [
        (200, 80, 600, 120, "в Балтском уезде"),                 # хвіст справи з першої сторінки
        (100, 200, 600, 240, "15. Дело об откупе"),
    ])
    (run / "_htr_meta.json").write_text(json.dumps({"model": "pysar_cyr_v31.pt"}), encoding="utf-8")
    return run


def test_ruled_build_cases_from_whole_pages(tmp_path: Path) -> None:
    run = _run(tmp_path)
    res = RU.build(run, tmp_path / "t.tsv", title_starts=True)
    assert res["cases"] == 4 and res["pages"] == 2 and res["bad_pages"] == 0
    rows = list(csv.DictReader((tmp_path / "t.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert [r["no"] for r in rows] == ["12", "13", "14", "15"]
    assert rows[0]["title"] == "Дело о помещике Иванове и его крестьянах"
    assert rows[0]["year"] == "1856" and rows[0]["folios"] == "14"
    assert rows[2]["no_src"] == "seq" and rows[2]["confirmed"] == "between"
    assert rows[2]["title"] == "Тоже о разделе земли в Балтском уезде"  # хвіст з другої сторінки
    assert [r["y"] for r in rows] == ["85-285", "285-345", "345-99999", "185-99999"]
    assert {r["confirmed"] for r in rows} == {"neighbors", "between"}


def test_norm_batches_roundtrip_and_strict_length(tmp_path: Path) -> None:
    run = _run(tmp_path)
    RU.build(run, tmp_path / "t.tsv", title_starts=True)
    d = tmp_path / "norm"
    got = NB.export(tmp_path / "t.tsv", d, source=NB.describe_source("DAOO", "445"), mova="ru")
    assert len(got) == 1
    b = json.loads(got[0].read_text(encoding="utf-8"))
    assert b["n"] == 4 and "фонд 445" in b["request"]
    norm = [t.replace("Дело", "Дело №") for t in b["titles"]]
    got[0].with_name("batch_000.out.txt").write_text(json.dumps(norm, ensure_ascii=False), encoding="utf-8")
    res = NB.collect(d, tmp_path / "norm.tsv")
    assert res["rows"] == 4 and not res["bad"] and not res["missing"]
    have = NB.known(tmp_path / "norm.tsv")
    assert len(have) == 4
    # усе нормалізовано — нових пачок немає
    assert NB.export(tmp_path / "t.tsv", d, source="x", have=have) == []
    # відповідь іншої довжини не приймається
    got[0].with_name("batch_000.out.txt").write_text(json.dumps(norm[:3], ensure_ascii=False),
                                                     encoding="utf-8")
    assert NB.collect(d, tmp_path / "norm2.tsv")["bad"]


def test_pack_dir_passes_gates(tmp_path: Path) -> None:
    """Робоча тека з прочитаного: два голоси сторінок, рядки з місцем і нормалізацією; ворота
    пакета пропускають."""
    run = _run(tmp_path)
    sib = tmp_path / "run-diak_v16"
    for p in run.glob("*.txt"):
        sib.mkdir(exist_ok=True)
        (sib / p.name).write_text(p.read_text(encoding="utf-8").upper(), encoding="utf-8")
    (sib / "_htr_meta.json").write_text("{}", encoding="utf-8")
    RU.build(run, tmp_path / "t.tsv", title_starts=True)
    d = tmp_path / "norm"
    b = NB.export(tmp_path / "t.tsv", d, source="x")[0]
    titles = json.loads(b.read_text(encoding="utf-8"))["titles"]
    b.with_name("batch_000.out.txt").write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
    NB.collect(d, tmp_path / "norm.tsv")

    voices = PD.run_voices(run)
    assert [v for v, _ in voices] == ["pysar_cyr_v31", "diak_v16"]
    sizes = {s: sz for s in ("0001", "0002") if (sz := PD.page_size(run, s))}
    pages = PD.pages_from_voices(voices, 2)
    rows = PD.rows_from_table(tmp_path / "t.tsv", sizes, PD.is_spread(sizes), NB.known(tmp_path / "norm.tsv"))
    assert len(rows) == 4 and rows[2]["regions"] == [{"page": 1, "half": None, "y0": round(345 / 1400, 4),
                                                       "y1": 1.0}]
    assert rows[0]["no_status"] == "neighbors" and rows[2]["no_status"] == "between"
    assert rows[0]["title_norm"] == rows[0]["title_raw"]
    src = {"kind": "archive_site", "url": "https://archive.example/0445_01.djvu", "sha256": "a" * 64,
           "label": "0445_01.djvu"}
    m = PD.manifest(repo="DAOO", fond="445", opys="1", language=PD.language(pages, "ru"), source=src,
                    pages=2, spread=False, engines=[v for v, _ in voices],
                    quality={"klass": "low", "form": "hand_ruled"}, tool="nysh opys build",
                    norm_model="agent-model", normalized=True)
    work = PD.write(tmp_path / "paket", m, pages, rows)
    man = S.Manifest(**json.loads((work / "manifest.json").read_text(encoding="utf-8")))
    pp = [S.Page(**json.loads(x)) for x in (work / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    rr = [S.Row(**json.loads(x)) for x in (work / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    v = G.check(man, pp, rr)
    assert v.passed, v.refusals


def test_manifest_needs_model_when_normalized() -> None:
    import pytest

    with pytest.raises(ValueError):
        PD.manifest(repo="DAOO", fond="445", opys="1", language="ru", source={}, pages=1, spread=False,
                    engines=[], quality={}, tool="t", normalized=True)


def test_render_pages_from_pdf(tmp_path: Path) -> None:
    from PIL import Image

    pdf = tmp_path / "o.pdf"
    Image.new("RGB", (400, 600), "white").save(pdf, save_all=True,
                                               append_images=[Image.new("RGB", (400, 600), "white")])
    res = PG.render(pdf, tmp_path / "pages", target_h=300)
    assert res["pages"] == 2
    im = Image.open(tmp_path / "pages" / "0001.jpg")
    assert im.size[1] == 300 and im.mode == "L"
    assert PG.render(pdf, tmp_path / "pages")["skip"]


def test_number_start_letter_only_lowercase_attached() -> None:
    """Літера номера — мала одразу за цифрами; велика літера після пробілу — початок назви."""
    m = RU.NUM_START.match("13 Дело о наследстве")
    assert m and (m.group(1), m.group(2), m.group(3)) == ("13", None, "Дело о наследстве")
    m = RU.NUM_START.match("136а. Тоже")
    assert m and (m.group(1), m.group(2), m.group(3)) == ("136", "а", "Тоже")
    m = RU.NUM_START.match("12аренды")  # слово, а не літера номера
    assert m and m.group(2) is None and m.group(3) == "аренды"


_FLOW = r"""
import gzip, json, sys
from pathlib import Path
from PIL import Image
from typer.testing import CliRunner
from nyshporka.cli import app

tmp = Path(sys.argv[1])
pdf = tmp / "opys.pdf"
Image.new("RGB", (1000, 1400), "white").save(pdf, save_all=True,
                                             append_images=[Image.new("RGB", (1000, 1400), "white")])
d = tmp / "opys"
r = CliRunner()
out = {}


def run(*args):
    res = r.invoke(app, ["opys", *map(str, args), "--json"])
    try:
        return json.loads(res.output)
    except ValueError:
        return {"ok": False, "raw": res.output[-3000:]}


out["init_closed"] = run("init", tmp / "x", "--pdf", pdf, "--repo", "ЦДІАК", "--fond", "442",
                         "--opys", "1", "--url", "https://commons.wikimedia.org/wiki/File:X.pdf")
out["init"] = run("init", d, "--pdf", pdf, "--repo", "ДАОО", "--fond", "445", "--opys", "9",
                  "--url", "https://upload.wikimedia.org/wikipedia/commons/a/ab/Opys_9.pdf")
out["pages"] = run("pages", d)
# що дав би `nysh read <тека>/pages --out <тека>/run`: текст і рамки рядків
run_d = d / "run"
run_d.mkdir()
(run_d / "_htr_meta.json").write_text(json.dumps({"model": "pysar_cyr_v31.pt"}), encoding="utf-8")
W, H = Image.open(d / "pages" / "0001.jpg").size
pages = {"0001": [(200, 300, 1500, 360, "1. Дело о помещике Иванове"), (300, 380, 1500, 440, "и его крестьянах"),
                  (200, 900, 1500, 960, "2. Дело о наследстве")],
         "0002": [(200, 300, 1500, 360, "3. Дело об откупе")]}
for stem, lines in pages.items():
    (run_d / f"{stem}.txt").write_text("\n".join(t for *_, t in lines), encoding="utf-8")
    with gzip.open(run_d / f"{stem}.lines.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"boxes": [list(b[:4]) for b in lines], "size": [W, H]}, fh)
out["table"] = run("table", d)
out["build_unnorm"] = run("build", d)
out["norm"] = run("norm", d)
for b in out["norm"]["data"]["batches"]:
    titles = json.loads(Path(b).read_text(encoding="utf-8"))["titles"]
    Path(b).with_name(Path(b).stem + ".out.txt").write_text(json.dumps(titles, ensure_ascii=False),
                                                           encoding="utf-8")
out["collect"] = run("norm", d, "--collect")
out["build_no_model"] = run("build", d)
out["build"] = run("build", d, "--norm-model", "agent-model")
out["pack"] = run("pack", d / "paket", "--out", d)
print("FLOW" + json.dumps(out, ensure_ascii=False))
"""


def test_participant_flow_pdf_to_bundle(tmp_path: Path) -> None:
    """Учасник з увімкненим флагом: PDF → паспорт → сторінки → (прочитане) → таблиця →
    нормалізація агентом → робоча тека → пакет, що пройшов ворота. Закритий фонд — відмова
    на першому кроці."""
    import os
    import subprocess
    import sys

    from nyshporka import features

    env = {**os.environ, features.OPYSY: "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    got = subprocess.run([sys.executable, "-c", _FLOW, str(tmp_path)], env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=180)
    line = next((x for x in got.stdout.splitlines() if x.startswith("FLOW")), "")
    assert line, got.stderr[-3000:]
    o = json.loads(line[len("FLOW"):])
    assert not o["init_closed"]["ok"]
    assert o["init"]["ok"], o["init"]
    src = o["init"]["data"]["source"]
    assert src["kind"] == "commons" and src["url"].startswith("https://commons.wikimedia.org/wiki/File:")
    assert src["page_link"].endswith("?page={page}") and len(src["sha256"]) == 64
    assert o["pages"]["data"]["pages"] == 2 and "nysh read" in o["pages"]["data"]["next"]
    assert o["table"]["data"]["cases"] == 3, o["table"]
    assert o["build_unnorm"]["ok"]  # без нормалізації тека складається; ворота відмовлять у pack
    assert len(o["norm"]["data"]["batches"]) == 1
    assert o["collect"]["data"]["rows"] == 3
    assert not o["build_no_model"]["ok"]
    assert o["build"]["data"]["normalized"] == 3
    assert o["pack"]["ok"], o["pack"]
    assert o["pack"]["data"]["file"].endswith(".nyshopys")
