"""Справа сегментами: картотека, якої один пакет пулу не вміщує.

🔴 Сценарій зі звіту 15.10.2026: картки військовополонених, 272 288 кадрів у
десятках алфавітних підтек, два голоси. Пул приймає пакет до 20 000 файлів,
тож справа мусить їхати кількома пакетами одного внеску — і жоден із них не
сміє загубити літеру, злити підтеки докупи чи заступити сусідній сегмент.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import workspace as W
from nyshporka.share import accept, bundle, catalog, publish, segment

KEY = "DAHMO/315/8433"
SHIFRA = "ДАХмО 315-1-8433"
#: Алфавітні підтеки, як у справжньої картотеки.
LETTERS = ["Бан… - Бар…", "Бас… - Бая…", "Бд… - Без…", "Бей… - Бек…",
           "Бел… - Бело…", "Гам… - Гар…", "Дал… - Дам…", "Дан… - Дар…"]


@pytest.fixture(autouse=True)
def _prostir_nazad():
    yield
    W.reset()


def _prostir(root: Path) -> Path:
    W.use(W.Workspace(root=root, name=root.name, origin="test"))
    return root


def _kartoteka(root: Path, letters: list[str], pages: int | list[int] = 5,
               models: tuple[str, ...] = ("pysar_cyr_v21.pt", "diak_cyr_v7.safetensors"),
               ) -> list[Path]:
    """Підтеки кадрів і прогони: кожну підтеку читали всі `models`.

    🔴 Імена сторінок у кожній підтеці свої `0001…`: саме на цьому зливались
    частини, поки знаменник рахував лише імена.
    """
    per = pages if isinstance(pages, list) else [pages] * len(letters)
    runs: list[Path] = []
    for i, (letter, n) in enumerate(zip(letters, per, strict=True), 1):
        frames = root / "data" / "raw" / "kartoteka" / letter
        frames.mkdir(parents=True)
        for k in range(1, n + 1):
            (frames / f"{k:04d}.jpg").write_bytes(b"JPEG" + bytes([i, k % 256]) * 8)
        for j, model in enumerate(models):
            name = f"kart{i:02d}" + ("" if j == 0 else f"-v{j}")
            d = root / "reports" / "htr" / name
            d.mkdir(parents=True)
            for k in range(1, n + 1):
                (d / f"{k:04d}.txt").write_text(
                    f"Картка {letter} {k} голос {j}\nДмитренко Іван\n",
                    encoding="utf-8")
            meta = {"version": 3, "case_key": KEY, "model": model,
                    "script": "cyrillic", "engine": "parseq", "frames_total": n,
                    "case_dir": str(frames),
                    "pages": {f"{k:04d}.jpg": {"lines": 2, "conf": 0.8}
                              for k in range(1, n + 1)}}
            (d / bundle.META_NAME).write_text(json.dumps(meta, ensure_ascii=False),
                                              encoding="utf-8")
            runs.append(d)
    return runs


# ── поділ ────────────────────────────────────────────────────────────────────

def test_chastyny_za_tekamy_kadriv_holosy_razom(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS)
    parts = segment.parts_of(runs)
    assert [p.label for p in parts] == sorted(LETTERS)
    assert all(len(p.runs) == 2 for p in parts), "обидва голоси підтеки — одна частина"


def test_plan_u_steli_bez_vtrat_i_v_poriadku(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=20)
    parts = segment.parts_of(runs)
    segs = segment.plan(parts, max_files=100)
    assert len(segs) > 1
    assert all(s.files <= 100 for s in segs)
    covered = [p.part.label for s in segs for p in s.pieces]
    assert covered == sorted(LETTERS), "кожна підтека рівно раз, за абеткою"
    assert [s.n for s in segs] == list(range(1, len(segs) + 1))
    assert {s.of for s in segs} == {len(segs)}


def test_kliuch_segmenta_stabilnyi(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=20)
    a = [s.key for s in segment.plan(segment.parts_of(runs), max_files=100)]
    b = [s.key for s in segment.plan(segment.parts_of(list(reversed(runs))),
                                     max_files=100)]
    assert a == b


def test_pidteka_pereroslok_dilytsia_za_storinkamy(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS[:2], pages=[200, 5])
    segs = segment.plan(segment.parts_of(runs), max_files=120)
    big = [p for s in segs for p in s.pieces if p.part.label == LETTERS[0]]
    assert len(big) > 1 and all(p.n and p.of == len(big) for p in big)
    stems = [st for p in big for st in (p.stems or [])]
    assert stems == [f"{k:04d}" for k in range(1, 201)], "без пропусків і повторів"
    assert all(s.files <= 120 for s in segs)


# ── стейдж і знаменник ───────────────────────────────────────────────────────

def test_stage_odyn_prohin_na_model_imena_z_chastynoiu(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS[:3], pages=[4, 6, 5])
    seg = segment.plan(segment.parts_of(runs))[0]
    staged = segment.stage(seg, tmp_path / "stage")
    assert len(staged) == 2, "одна тека на модель, а не на підтеку"
    texts = {d.name: {p.name: p.read_text(encoding="utf-8")
                      for p in d.glob(bundle.PACKED_TEXT)} for d in staged}
    models = {d.name: bundle.voice_of(d).model for d in staged}
    got = bundle.tally(texts, models)
    # 🔴 Без префікса частини три підтеки з `0001…` дали б 6 сторінок, не 15.
    assert got["pages"] == 15
    names = next(iter(texts.values()))
    assert all(segment.SEP in n for n in names)
    assert all(segment.RUN_MARK in d.name for d in staged)


def test_kadry_segmenta_lyshe_ioho(tmp_path: Path) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=10)
    segs = segment.plan(segment.parts_of(runs), max_files=70)
    rows = segment.frames_for(segs[0])
    assert len(rows) == segs[0].pages
    assert [r["n"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(segment.SEP in r["name"] for r in rows)


def test_proba_ne_plutaiet_pidteky_odniiei_modeli(tmp_path: Path) -> None:
    """Менша літера тієї самої моделі — не проба більшої: кадри інші."""
    runs = _kartoteka(_prostir(tmp_path), LETTERS[:2], pages=[3, 9],
                      models=("pysar_cyr_v21.pt",))
    kept, skipped = publish.choose_voices(runs, KEY)
    assert len(kept) == 2, skipped


# ── пакування ────────────────────────────────────────────────────────────────

def _pakuvaty(monkeypatch: pytest.MonkeyPatch, runs: list[Path], out: Path,
              **kw: Any) -> dict[str, Any]:
    info = {"key": KEY, "shifra": SHIFRA, "kind": "case", "rows": []}
    monkeypatch.setattr(publish, "resolve_runs", lambda scope, skip=(): (runs, dict(info)))
    return publish.pack_segments(KEY, out, license_text="CC0-1.0", **kw)


def test_pack_segments_paket_na_segment(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=12)
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", max_files=80)
    segs = got["segments"]
    assert len(segs) > 1
    assert got["frames_total"] == 12 * len(LETTERS)
    pages = 0
    for s in segs:
        p = Path(s["path"])
        inv = bundle.inventory(p)
        assert not inv.problems, inv.problems
        m = bundle.read_manifest(p)
        assert m.schema == segment.SCHEMA_SEGMENT
        seg = m.case["segment"]
        assert seg["n"] == s["n"] and seg["of"] == len(segs) and seg["set"] == got["set"]
        assert m.case["frames_total"] == 12 * len(LETTERS)
        # Знаменник сегмента — його кадри, не 96 кадрів справи.
        assert m.frames_total == m.pages
        pages += m.pages
    assert pages == 12 * len(LETTERS), "сума сегментів — уся справа"


def test_pack_segments_dry_run_nichoho_ne_pyshe(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=12)
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", max_files=80, dry_run=True)
    assert got["dry_run"] and len(got["segments"]) > 1
    assert not (tmp_path / "out").exists()


def test_perepakuvannia_prybyraie_staryi_podil(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=12)
    out = tmp_path / "out"
    first = _pakuvaty(monkeypatch, runs, out, max_files=60)
    second = _pakuvaty(monkeypatch, runs, out, max_files=200)
    assert len(second["segments"]) < len(first["segments"])
    assert len(list(out.glob("*" + bundle.SUFFIX))) == len(second["segments"])


def test_zvychainyi_pack_vidmovliaie_ponad_steliu() -> None:
    why = publish._ponad_steliu(segment.POOL_MAX_MEMBERS)
    assert "--segments" in why
    assert publish._ponad_steliu(100) == ""
    assert "--segments" in publish._ponad_steliu(0, nbytes=segment.POOL_MAX_TEXT_BYTES + 1)


def test_zvychainyi_paket_lyshaietsia_na_skhemi_2() -> None:
    assert bundle.Manifest().schema == bundle.SCHEMA_PLAIN == 2
    assert bundle.SCHEMA == segment.SCHEMA_SEGMENT


# ── приймання й каталог ──────────────────────────────────────────────────────

def test_dva_segmenty_liahaiut_poruch(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _kartoteka(_prostir(tmp_path / "a"), LETTERS, pages=12)
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", max_files=80)
    _prostir(tmp_path / "b")
    names: set[str] = set()
    for s in got["segments"][:2]:
        taken = accept.accept(s["path"])
        names.update(taken["runs"])
    htr = W.workspace().htr_reports
    assert len(names) == 4, "два сегменти × два голоси, жоден не перетер інший"
    assert all((htr / n).is_dir() for n in names)


def _row(seg: str, n: int, label: str, models: str = "pysar_cyr_v21.pt") -> catalog.Row:
    return catalog.Row(shifra=SHIFRA, repo="DAHMO", fond="315", opys="1", spr="8433",
                       models=models, segment=seg, segment_label=label,
                       segment_n=str(n), segment_of="3", url=f"https://x/{seg}")


def test_best_per_case_bere_kozhen_segment() -> None:
    rows = [_row("a", 1, "Бан… - Бар…"), _row("b", 2, "Гам… - Гар…"),
            _row("c", 3, "Дал… - Дам…"), _row("c", 3, "Дал… - Дам…", models="x.pt")]
    best = catalog.best_per_case(rows)
    assert sorted(r.segment for r in best) == ["a", "b", "c"]


def test_pick_za_abetkoiu() -> None:
    rows = [_row("a", 1, "Бан… - Бар… — Бел… - Бело…"), _row("b", 2, "Гам… - Гар…"),
            _row("c", 3, "Дал… - Дам…")]
    assert [r.segment for r in segment.pick(rows, "Дмитренко")] == ["c"]
    assert [r.segment for r in segment.pick(rows, "Гамалій")] == ["b"]
    assert [r.segment for r in segment.pick(rows, "Бело")] == ["a"]


def test_vziatyi_segment_ne_blokuie_susidnii() -> None:
    from nyshporka.ops_share import _seen_here

    taken = segment.run_name("kart01", "Бан_-_Бар")
    local = {"DAHMO/315/1/8433": {"own": [], "taken": [taken]}}
    first = _row("Бан_-_Бар", 1, "Бан… - Бар…")
    second = _row("Гам_-_Гар", 2, "Гам… - Гар…")
    assert _seen_here(local, first, replace=False)[0] == "taken"
    assert _seen_here(local, second, replace=False)[0] == ""


def test_kartka_spravy_ne_pidminiaie_znamennyk_segmenta(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Число кадрів цілої справи з картки — у `case.frames_total`, не в сегмент."""
    runs = _kartoteka(_prostir(tmp_path), LETTERS, pages=12)
    got = _pakuvaty(monkeypatch, runs, tmp_path / "out", max_files=80,
                    card_fields={"frames": 272_288}, remember_card=False)
    assert got["frames_total"] == 272_288
    for s in got["segments"]:
        m = bundle.read_manifest(Path(s["path"]))
        assert m.case["frames_total"] == 272_288
        assert m.frames_total == m.pages
