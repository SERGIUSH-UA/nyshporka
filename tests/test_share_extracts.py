"""Справа, прочитана вирізками з плівки: село = окрема тека зі своєю сторінкою 1.

🔴 Сценарій із запиту 16.10.2026: катаграфії Бессарабії (ANRM ф.134 оп.2)
читано село за селом, кожне — окремим PDF, вирізаним із плівки FamilySearch.
656 читань лягають у 108 справ; одна справа буває на двох плівках, а на
одній плівці лежить кілька справ. Звичайний внесок на село давав у пулі
«прочитано» найбільшого села, а не суму, а сегменти за абеткою міняли ключі
й набір щоразу, коли додавалось село.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import workspace as W
from nyshporka.share import bundle, publish, segment

KEY = "ANRM/134/2/257"
SHIFRA = "ANRM 134-2-257"
OPYS = {"title": "Catagrafia ţinutului Orhei", "years": [1850, 1850]}

#: (село, плівка, кадри на плівці, аркуші)
SELA = [("Lipceni", "2362453", (670, 674), "35-55"),
        ("Lalova", "2362453", (710, 713), "56-79"),
        ("Recea", "2376761", (5, 7), "120-130")]

RANGE = [{"fs_film": "2362453", "from": 600, "to": 900, "src": "passport", "certain": True},
         {"fs_film": "2376761", "from": 1, "to": 400, "src": "passport", "certain": True}]


@pytest.fixture(autouse=True)
def _prostir_nazad():
    yield
    W.reset()


def _prostir(root: Path) -> Path:
    W.use(W.Workspace(root=root, name=root.name, origin="test"))
    return root


def _selo(root: Path, i: int, name: str, film: str, rng: tuple[int, int], folios: str,
          *, declare: bool = True, frames: int | None = None,
          models: tuple[str, ...] = ("pysar_cyr_v21.pt",)) -> list[Path]:
    n = frames if frames is not None else rng[1] - rng[0] + 1
    d = root / "data" / "raw" / "anrm_134" / f"257-{name}"
    d.mkdir(parents=True)
    for k in range(1, n + 1):
        (d / f"{k:04d}.jpg").write_bytes(b"JPEG" + bytes([i, k % 256]) * 8)
    (d / "_source.json").write_text(json.dumps({"shifra": SHIFRA}), encoding="utf-8")
    if declare:
        segment.declare(d, film=film, frames_on_film=f"{rng[0]}-{rng[1]}",
                        folios=folios, village=name)
    runs = []
    for j, model in enumerate(models):
        r = root / "reports" / "htr" / (f"cat257-{name}" + ("" if j == 0 else f"-v{j}"))
        r.mkdir(parents=True)
        for k in range(1, n + 1):
            (r / f"{k:04d}.txt").write_text(f"{name} {k}\nIon Negru\n", encoding="utf-8")
            (r / f"{k:04d}.lines.json").write_text(
                json.dumps({"size": [100, 200], "boxes": [[1, 2, 3, 4]], "polys": []}),
                encoding="utf-8")
        meta = {"version": 3, "case_key": KEY, "model": model, "script": "cyrillic",
                "engine": "parseq", "frames_total": n, "case_dir": str(d),
                "pages": {f"{k:04d}.jpg": {"lines": 2, "conf": 0.8} for k in range(1, n + 1)}}
        (r / bundle.META_NAME).write_text(json.dumps(meta), encoding="utf-8")
        runs.append(r)
    return runs


def _sela(root: Path, which: list[int] | None = None, **kw: Any) -> list[Path]:
    runs: list[Path] = []
    for i in which if which is not None else range(len(SELA)):
        runs += _selo(root, i + 1, *SELA[i], **kw)
    return runs


def _pakuvaty(monkeypatch: pytest.MonkeyPatch, runs: list[Path], out: Path, *,
              rng: list[dict[str, Any]] | None = RANGE, **kw: Any) -> dict[str, Any]:
    info = {"key": KEY, "shifra": SHIFRA, "kind": "case", "rows": []}
    monkeypatch.setattr(publish, "resolve_runs", lambda scope, skip=(): (runs, dict(info)))
    monkeypatch.setattr(publish, "case_range", lambda shifra, home: list(rng or []))
    kw["card_fields"] = {**OPYS, **(kw.get("card_fields") or {})}
    kw.setdefault("remember_card", False)
    return publish.pack_segments(KEY, out, license_text="CC0-1.0", **kw)


# ── паспорт вирізки ──────────────────────────────────────────────────────────

def test_declare_i_part_passport(tmp_path: Path) -> None:
    _prostir(tmp_path)
    _selo(tmp_path, 1, *SELA[0])
    d = tmp_path / "data" / "raw" / "anrm_134" / "257-Lipceni"
    got = segment.part_passport(d)
    assert got["fs_film"] == "2362453"
    assert (got["frame_from"], got["frame_to"], got["frames"]) == (670, 674, 5)
    assert got["folios"] == "35-55" and got["village"] == "Lipceni"
    assert got["src"]["frame_from"] == "cli"
    side = json.loads((d / "_source.json").read_text(encoding="utf-8"))
    assert side["shifra"] == SHIFRA, "паспорт справи не перетерто"
    # «-» стирає поле; порожнє — не чіпає.
    segment.declare(d, folios="-")
    assert "folios" not in segment.part_passport(d)
    assert segment.part_passport(d)["frame_from"] == 670


def test_declare_bez_pasporta_vidmova(tmp_path: Path) -> None:
    d = tmp_path / "x"
    d.mkdir()
    with pytest.raises(segment.PartError, match="паспорта"):
        segment.declare(d, film="1")


def test_frames_range_zavantazhuvacha_chytaietsia(tmp_path: Path) -> None:
    """`nysh get --frames 12-80` пише `frames_range` — тепер його хтось читає."""
    d = tmp_path / "f"
    d.mkdir()
    (d / "_source.json").write_text(json.dumps(
        {"shifra": SHIFRA, "film": "2362453", "frames_range": "12-80"}), encoding="utf-8")
    got = segment.part_passport(d)
    assert (got["fs_film"], got["frame_from"], got["frame_to"]) == ("2362453", 12, 80)
    assert got["src"]["fs_film"] == "passport"


def test_bez_mistsia_na_plivtsi_ne_vyrizka(tmp_path: Path) -> None:
    d = tmp_path / "f"
    d.mkdir()
    (d / "_source.json").write_text(json.dumps({"shifra": SHIFRA}), encoding="utf-8")
    assert segment.part_passport(d) is None


# ── поділ ────────────────────────────────────────────────────────────────────

def test_selo_odyn_segment_kliuch_za_plivkoiu(tmp_path: Path) -> None:
    runs = _sela(_prostir(tmp_path))
    parts = segment.with_extracts(segment.parts_of(runs))
    assert segment.is_extract_case(parts)
    segs = segment.plan_extracts(parts)
    assert [s.pieces[0].part.extract["village"] for s in segs] == ["Lipceni", "Lalova", "Recea"]
    assert segs[0].key == "x-2362453-00670-00674"


def test_kliuch_ne_zalezhyt_vid_susidiv(tmp_path: Path) -> None:
    root = _prostir(tmp_path)
    runs = _sela(root, [0, 2])
    one = {s.key for s in segment.plan_extracts(segment.with_extracts(segment.parts_of(runs)))}
    runs += _selo(root, 2, *SELA[1])
    two = {s.key for s in segment.plan_extracts(segment.with_extracts(segment.parts_of(runs)))}
    assert one < two, "додане село не міняє ключів уже відданих"
    assert segment.set_id_extracts(KEY) == segment.set_id_extracts(KEY)


# ── межі справи на плівці ────────────────────────────────────────────────────

def _parts(root: Path, **kw: Any) -> list[segment.Part]:
    return segment.with_extracts(segment.parts_of(_sela(root, **kw)))


def test_vyrizka_za_mezhamy_spravy_vidmova(tmp_path: Path) -> None:
    parts = _parts(_prostir(tmp_path))
    rng = [{**RANGE[0], "to": 700}, RANGE[1]]
    bad, _ = segment.check_extracts(parts, rng)
    assert any("Lalova" in b and "сусідній справі" in b for b in bad)


def test_plivka_ne_tsiiei_spravy_vidmova(tmp_path: Path) -> None:
    parts = _parts(_prostir(tmp_path))
    bad, _ = segment.check_extracts(parts, [RANGE[0]])
    assert any("Recea" in b and "інша справа" in b for b in bad)


def test_otsineni_mezhi_lyshe_poperedzhennia(tmp_path: Path) -> None:
    parts = _parts(_prostir(tmp_path))
    rng = [{**RANGE[0], "to": 700, "certain": False, "src": "index"},
           {**RANGE[1], "certain": False, "src": "index"}]
    bad, warn = segment.check_extracts(parts, rng)
    assert not bad
    assert any("Lalova" in w and "оцінено" in w for w in warn)


def test_cross_case_poiasneno(tmp_path: Path) -> None:
    root = _prostir(tmp_path)
    parts = _parts(root)
    lalova = next(p for p in parts if "Lalova" in p.label)
    segment.declare(lalova.frames_dir, cross_case="арк. 79 — початок сусідньої справи")
    lalova.extract = segment.part_passport(lalova.frames_dir)
    bad, warn = segment.check_extracts(parts, [{**RANGE[0], "to": 700}, RANGE[1]])
    assert not bad and any("сусідньої" in w for w in warn)


def test_kadry_ne_zbihaiutsia_z_diapazonom(tmp_path: Path) -> None:
    root = _prostir(tmp_path)
    _selo(root, 1, *SELA[0], frames=4)          # оголошено 5 кадрів, у теці 4
    parts = segment.with_extracts(segment.parts_of(
        [root / "reports" / "htr" / "cat257-Lipceni"]))
    bad, _ = segment.check_extracts(parts, RANGE)
    assert any("в теці 4" in b for b in bad)


def test_perekryttia_vidmova(tmp_path: Path) -> None:
    root = _prostir(tmp_path)
    runs = _selo(root, 1, *SELA[0]) + _selo(root, 2, "Lalova", "2362453", (672, 676), "56-79")
    bad, _ = segment.check_extracts(segment.with_extracts(segment.parts_of(runs)), RANGE)
    assert any("перекриваються" in b for b in bad)


# ── пакування ────────────────────────────────────────────────────────────────

def test_pack_vyrizky_tekst_i_ramky(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _sela(_prostir(tmp_path))
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out")
    assert got["mode"] == "extract"
    assert got["frames_total"] == 301 + 400 and got["frames_source"] == "паспорт справи"
    segs = got["segments"]
    assert len(segs) == 3
    sets = set()
    for s in segs:
        p = Path(s["path"])
        assert not bundle.inventory(p).problems
        m = bundle.read_manifest(p)
        assert m.schema == segment.SCHEMA_EXTRACT
        seg = m.case["segment"]
        assert seg["mode"] == "extract" and seg["case_range"]
        assert seg["extract"]["fs_film"] in ("2362453", "2376761")
        assert m.case["frames_total"] == 701
        assert m.frames_total == m.pages, "знаменник сегмента — його кадри"
        assert m.voices[0]["geometry"] is True
        sets.add(seg["set"])
        g = bundle.geom_path(p)
        assert g.is_file(), "рамки рядків їдуть окремим пакетом поруч"
        assert s["geom"]["path"] == str(g)
        # Посилання на зйомку — плівка цього села, а не першого.
        assert any(seg["extract"]["fs_film"] in r["ref"] for r in m.refs)
    assert len(sets) == 1


def test_frames_jsonl_nese_kadr_na_plivtsi(tmp_path: Path) -> None:
    runs = _sela(_prostir(tmp_path), [0])
    parts = segment.with_extracts(segment.parts_of(runs))
    seg = segment.plan_extracts(parts)[0]
    rows = segment.extract_frames_for(seg)
    assert [r["film_frame"] for r in rows] == [670, 671, 672, 673, 674]
    assert {r["film"] for r in rows} == {"2362453"}


def test_tekst_toi_samyi_z_ramkamy_i_bez(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Рамки — окремий пакет: хеш змісту тексту від них не змінюється."""
    runs = _sela(_prostir(tmp_path), [0])
    a = _pakuvaty(monkeypatch, runs, tmp_path / "a")
    b = _pakuvaty(monkeypatch, runs, tmp_path / "b", geometry=False)
    ma = bundle.read_manifest(Path(a["segments"][0]["path"]))
    mb = bundle.read_manifest(Path(b["segments"][0]["path"]))
    assert ma.decode["content_sha256"] == mb.decode["content_sha256"]
    assert "geom" not in b["segments"][0]


def test_dodane_selo_ne_zminiuie_vzhe_spakovanykh(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    root = _prostir(tmp_path)
    runs = _sela(root, [0, 2])
    out = tmp_path / "out"
    first = _pakuvaty(monkeypatch, runs, out)
    runs += _selo(root, 2, *SELA[1])
    second = _pakuvaty(monkeypatch, runs, out)
    assert first["set"] == second["set"]
    names1 = {Path(s["path"]).name for s in first["segments"]}
    names2 = {Path(s["path"]).name for s in second["segments"]}
    assert names1 < names2
    sha = {bundle.read_manifest(Path(s["path"])).decode["content_sha256"]
           for s in first["segments"]}
    sha2 = {bundle.read_manifest(Path(s["path"])).decode["content_sha256"]
            for s in second["segments"]}
    assert sha < sha2, "той самий зміст — пул упізнає відданий сегмент за хешем"
    assert all(bundle.geom_path(out / n).is_file() for n in names2), \
        "рамки не знесено прибиранням застарілого"


def test_znamennyk_ne_suma_vyrizok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _sela(_prostir(tmp_path))
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", rng=[], dry_run=True)
    assert got["frames_total"] == 0
    assert any("сума вирізок" in r for r in got["pack_refusals"])
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", rng=[], dry_run=True,
                    card_fields={"frames": 1180})
    assert got["frames_total"] == 1180 and not got.get("pack_refusals")


def test_by_part_vymahaie_mistsia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _prostir(tmp_path)
    runs = _sela(root, [0]) + _selo(root, 2, *SELA[1], declare=False)
    auto = _pakuvaty(monkeypatch, runs, tmp_path / "out", dry_run=True)
    assert auto["mode"] == "alpha", "не всі теки оголошено — само не вмикається"
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", dry_run=True, by_part=True)
    assert any("Lalova" in r and "share part" in r for r in got["pack_refusals"])


def test_staryi_klient_vidkydaie_vyrizku() -> None:
    raw = {"schema": segment.SCHEMA_EXTRACT}
    assert bundle.Manifest.from_json(raw).schema == 4
    with pytest.raises(bundle.BundleError, match="оновити"):
        bundle.Manifest.from_json({"schema": segment.SCHEMA_EXTRACT + 1})


# ── одержувач ────────────────────────────────────────────────────────────────

def _apid(film: str, n: int) -> str:
    return f"{film}-{n:05d}"


def _z_apid(root: Path) -> None:
    """Кожне село знає FS apid своїх кадрів (сайдкар завантажувача)."""
    for name, film, rng, _ in SELA:
        d = root / "data" / "raw" / "anrm_134" / f"257-{name}"
        if not d.is_dir():
            continue
        side = {f"{k:04d}": {"apid": _apid(film, rng[0] + k - 1)}
                for k in range(1, rng[1] - rng[0] + 2)}
        (d / "_fs_meta.json").write_text(json.dumps(side), encoding="utf-8")


def _tsila_plivka(root: Path, film: str, n: int, *, apid: bool) -> Path:
    """Тека цілої плівки в отримувача: кадри 1..n, на ній кілька справ."""
    d = root / "data" / "raw" / "fsfilm" / film
    d.mkdir(parents=True)
    for k in range(1, n + 1):
        (d / f"{k:05d}.jpg").write_bytes(b"JPEG" + k.to_bytes(3, "big"))
    (d / "_source.json").write_text(json.dumps({"film": film}), encoding="utf-8")
    if apid:
        (d / "_fs_meta.json").write_text(json.dumps(
            {f"{k:05d}": {"apid": _apid(film, k)} for k in range(1, n + 1)}),
            encoding="utf-8")
    return d


def _vzialy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, apid: bool
            ) -> tuple[dict[str, Any], Path]:
    root = _prostir(tmp_path / "a")
    runs = _sela(root, [0])
    _z_apid(root)
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out")
    _prostir(tmp_path / "b")
    whole = _tsila_plivka(tmp_path / "b", "2362453", 900, apid=apid)
    from nyshporka.share import align

    monkeypatch.setattr(align, "film_dirs", lambda film: [whole] if film == "2362453" else [])
    monkeypatch.setattr(align, "case_dir_for", lambda key: None)
    return got["segments"][0], whole


def test_tsila_plivka_z_apid_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import accept

    seg, whole = _vzialy(tmp_path, monkeypatch, apid=True)
    taken = accept.accept(seg["path"])
    assert taken["alignment"]["label"] == "exact"
    assert taken["alignment"]["case_dir"] == str(whole)
    assert taken["renamed"] == 5
    run = W.workspace().htr_reports / taken["runs"][0]
    assert sorted(p.name for p in run.glob("*.txt")) == [f"{k:05d}.txt" for k in range(670, 675)]
    meta = json.loads((run / bundle.META_NAME).read_text(encoding="utf-8"))
    assert meta["case_dir"] == str(whole).replace("\\", "/")
    assert meta["shared"]["extract"]["frame_from"] == 670
    assert meta["shared"]["page_film"]["00670"] == 670
    # Рамки рядків лягають під ті самі місцеві імена.
    geo = accept.accept_geometry(seg["geom"]["path"], reindex=False)
    assert geo["pages"] == 5
    assert sorted(p.name for p in run.glob("*.lines.json")) == \
        [f"{k:05d}.lines.json" for k in range(670, 675)]


def test_tsila_plivka_lyshe_nomer_kadru_by_position(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import accept

    seg, _whole = _vzialy(tmp_path, monkeypatch, apid=False)
    taken = accept.accept(seg["path"])
    assert taken["alignment"]["label"] == "by-position"
    assert taken["renamed"] == 0, "за позицією імен не переводимо"
    run = W.workspace().htr_reports / taken["runs"][0]
    meta = json.loads((run / bundle.META_NAME).read_text(encoding="utf-8"))
    assert meta["shared"]["page_film"]["257-Lipceni__0001"] == 670
    with pytest.raises(accept.AcceptError, match="by-position"):
        accept.accept_geometry(seg["geom"]["path"], reindex=False)


def test_bez_kadriv_text_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import accept, align

    root = _prostir(tmp_path / "a")
    got = _pakuvaty(monkeypatch, _sela(root, [2]), tmp_path / "out")
    _prostir(tmp_path / "b")
    monkeypatch.setattr(align, "film_dirs", lambda film: [])
    taken = accept.accept(got["segments"][0]["path"])
    assert taken["alignment"]["label"] == "text-only"


def test_vyrizka_z_pdf_bez_zobrazhen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Читали з PDF: у теці лише паспорт, кадрів-зображень немає."""
    root = _prostir(tmp_path)
    runs = _selo(root, 1, *SELA[0])
    d = root / "data" / "raw" / "anrm_134" / "257-Lipceni"
    for f in d.glob("*.jpg"):
        f.unlink()
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out")
    m = bundle.read_manifest(Path(got["segments"][0]["path"]))
    assert m.frames_total == 5, "знаменник вирізки — оголошений діапазон"
    rows = bundle.read_frames(Path(got["segments"][0]["path"]))
    assert [r["film_frame"] for r in rows] == [670, 671, 672, 673, 674]
