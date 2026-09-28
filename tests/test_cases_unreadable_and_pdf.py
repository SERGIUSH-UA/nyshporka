"""🧾 Реєстр справ не мовчить про нечитане і не оголошує PDF дочитаним наосліп.

Аудит 29.09.2026 знайшов у збірці реєстру дві вади одного роду — обидві робили
неповний зріз схожим на відповідь:

  · битий файл шару (`_htr_meta.json`, `clan_hunt/state.json`, файл сховища
    сторінок) зникав мовчки, і реєстр казав «пошуку не було», «ока не було».
    Один пошкоджений `state.json` давав `fuzzy_stage=none` УСІМ справам;
  · для справи-PDF знаменником покриття був один кадр на ФАЙЛ, тож прогін,
    що зупинився на 50-й сторінці з 300, виглядав повним.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Порожній простір із підміненими шляхами модулів.

    🔴 Константи підмінюються поіменно (як у `test_case_volume`): `library`,
    `cases.db` і `cases.collect` заморожують шляхи на імпорті, і без цього
    збірка пішла б по справжньому простору розробника.
    """
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override", None, raising=False)
    W._cached.cache_clear()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L
    from nyshporka.cases import collect as C
    from nyshporka.cases import db as DB

    for mod, attr, value in (
        (L, "ROOT", tmp_path), (L, "RAW_DIR", tmp_path / "data" / "raw"),
        (L, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (L, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (C, "ROOT", tmp_path), (C, "HTR_ROOT", tmp_path / "reports" / "htr"),
        (C, "RAW_DIR", tmp_path / "data" / "raw"),
        (C, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (C, "CLAN_STATE", tmp_path / "data" / "clan_hunt" / "state.json"),
        (C, "DERIVED_DB", tmp_path / "data" / "derived" / "nyshporka.sqlite"),
        (DB, "ROOT", tmp_path),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)

    def _clear() -> None:
        for mod in (L, C, DB):
            for name in dir(mod):
                got = getattr(mod, name, None)
                if hasattr(got, "cache_clear"):
                    got.cache_clear()

    _clear()
    (tmp_path / "reports" / "htr").mkdir(parents=True)
    yield tmp_path
    _clear()


def _case(root: Path, *, jpgs: int = 0, pdf_pages: int | None = None,
          bad_pdf: bool = False) -> Path:
    """Справа ДАХмО 315-1-8433: кадри, або PDF на N сторінок, або битий PDF."""
    from nyshporka.cases import register as R

    d = root / "data" / "raw" / "справа"
    d.mkdir(parents=True)
    for i in range(1, jpgs + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"x")
    if pdf_pages:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument.new()
        for _ in range(pdf_pages):
            doc.new_page(100, 100)
        doc.save(str(d / "8433.pdf"))
        doc.close()
    if bad_pdf:
        # Не PDF зовсім: читач сторінок не відкриє його, і лишається лише
        # файловий лік — «1».
        (d / "8433.pdf").write_bytes(b"%PDF-1.4 obrizano")
    R.describe(d, shifra="ДАХмО 315-1-8433", title="Метрична книга")
    return d


def _run(root: Path, name: str, pages: list[str]) -> None:
    d = root / "reports" / "htr" / name
    d.mkdir(parents=True)
    (d / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": "data/raw/справа", "case_key": "DAHMO/315/8433",
        "model": "pysar_cyr_v17.pt", "updated": "2026-09-29T10:00:00",
        "pages": {p: {"chars": 100, "lines": 10} for p in pages},
    }, ensure_ascii=False), encoding="utf-8")


def _library() -> None:
    from nyshporka.library import build_library, write_library

    write_library(build_library())


def _only_case(rows: list[Any]) -> Any:
    got = [r for r in rows if r.key == "DAHMO/315/8433"]
    assert len(got) == 1, [r.key for r in rows]
    return got[0]


# ── 1. нечитані файли шарів ───────────────────────────────────────────────


def _corrupt_layers(root: Path) -> None:
    """Справа з прогоном і переглянутим аркушем + по битому файлу в кожному шарі."""
    _case(root, jpgs=3)
    _run(root, "spr-8433", ["0001.jpg", "0002.jpg", "0003.jpg"])
    broken_run = root / "reports" / "htr" / "spr-8433-bite"
    broken_run.mkdir()
    (broken_run / "_htr_meta.json").write_text("{obrizano", encoding="utf-8")

    pages = root / "data" / "pages" / "DAHMO"
    pages.mkdir(parents=True)
    (pages / "315-8433.json").write_text(json.dumps({
        "case": "DAHMO/315/8433",
        "pages": {"0001.jpg": {"status": "full"}}}), encoding="utf-8")
    (pages / "315-9999.json").write_text("[1, 2", encoding="utf-8")

    clan = root / "data" / "clan_hunt"
    clan.mkdir(parents=True)
    (clan / "state.json").write_text('{"runs": {', encoding="utf-8")


def test_unreadable_layer_files_are_reported_and_rest_survives(space: Path) -> None:
    """Битий файл іде в перелік, а решта справи збирається як була."""
    from nyshporka.cases.collect import collect_rows

    _corrupt_layers(space)
    _library()
    bad: list[dict[str, str]] = []
    rows, _ = collect_rows(unreadable=bad)

    paths = {b["path"] for b in bad}
    assert "data/clan_hunt/state.json" in paths, bad
    assert "reports/htr/spr-8433-bite/_htr_meta.json" in paths, bad
    assert "data/pages/DAHMO/315-9999.json" in paths, bad
    assert all(b["why"] for b in bad), "причина мусить бути названа"

    row = _only_case(rows)
    # Один битий файл не гасить сусідні: прогін і аркуш лишаються в справі.
    assert row.htr_runs == ["spr-8433"]
    assert row.htr_stage == "pysar"
    assert (row.pages_noted, row.pages_full) == (1, 1)


def test_non_object_pages_file_does_not_crash_build(space: Path) -> None:
    """JSON-список у сховищі сторінок раніше валив УСЮ збірку на `data.get`."""
    from nyshporka.cases.collect import collect_rows

    _case(space, jpgs=1)
    pages = space / "data" / "pages" / "DAHMO"
    pages.mkdir(parents=True)
    (pages / "315-8433.json").write_text("[]", encoding="utf-8")
    _library()
    bad: list[dict[str, str]] = []
    collect_rows(unreadable=bad)
    assert [b["path"] for b in bad] == ["data/pages/DAHMO/315-8433.json"]


def test_build_result_and_staleness_carry_unreadable(space: Path) -> None:
    """Збірка віддає перелік нагору, і кожне читання реєстру бачить неповноту."""
    from nyshporka.cases import db

    _corrupt_layers(space)
    _library()
    res = db.build_index()
    assert {b["path"] for b in res["unreadable"]} >= {"data/clan_hunt/state.json"}

    for quick in (False, True):
        st = db.staleness(quick=quick)
        assert st["stale"], f"неповний зріз не можна видавати за свіжий (quick={quick})"
        assert any("не прочитано" in r for r in st["reasons"]), st


def test_cli_build_prints_unreadable(space: Path) -> None:
    """`nysh cases build` каже про нечитане вголос і поіменно."""
    from typer.testing import CliRunner

    from nyshporka.cases.cli import app

    _corrupt_layers(space)
    _library()
    out = CliRunner().invoke(app, ["build"])
    assert out.exit_code == 0, out.output
    assert "НЕПОВНИЙ" in out.output
    assert "state.json" in out.output


def test_clean_build_reports_nothing(space: Path) -> None:
    """Без битих файлів — жодного застереження: вічно червоний прапор вимикають."""
    from nyshporka.cases import db

    _case(space, jpgs=1)
    _library()
    assert db.build_index()["unreadable"] == []
    assert not any("не прочитано" in r for r in db.staleness()["reasons"])


# ── 2. справа-PDF: знаменник — сторінки, а не файли ───────────────────────


def test_pdf_frames_are_pages_not_files(space: Path) -> None:
    """Лічильник кадрів для теки з PDF дає сторінки, а не «1 файл»."""
    from nyshporka.cases import collect as C

    _case(space, pdf_pages=5)
    C._FRAMES_INDEX = {}
    assert C._count_frames("data/raw/справа") == 5
    assert C._count_frames("data/raw/справа/8433.pdf") == 5
    C._FRAMES_INDEX = C._frames_index(C._raw_scans())
    assert C._count_frames("data/raw/справа") == 5


def test_pdf_case_with_partial_run_is_not_complete(space: Path) -> None:
    """Прогін на 2 сторінки з 5 у PDF — обірваний, а не «прочитано»."""
    from nyshporka.cases.collect import collect_rows

    _case(space, pdf_pages=5)
    _run(space, "spr-8433", ["0001.jpg", "0002.jpg"])
    _library()
    row = _only_case(collect_rows()[0])
    assert row.frames == 5
    assert row.htr_stage == "partial"


def test_uncountable_pdf_never_claims_complete(space: Path) -> None:
    """Сторінок PDF не порахувати — повноти не доведено, стан `partial`.

    Файловий лік дає знаменник «1», і прогін на одну сторінку виглядав би
    дочитаним — при тому, що в книзі їх може бути триста.
    """
    from nyshporka.cases.collect import collect_rows

    _case(space, bad_pdf=True)
    _run(space, "spr-8433", ["0001.jpg"])
    _library()
    row = _only_case(collect_rows()[0])
    assert row.htr_stage == "partial"


def test_image_case_complete_run_stays_complete(space: Path) -> None:
    """Контроль: справа з кадрами й повним прогоном лишається прочитаною."""
    from nyshporka.cases.collect import collect_rows

    _case(space, jpgs=2)
    _run(space, "spr-8433", ["0001.jpg", "0002.jpg"])
    _library()
    assert _only_case(collect_rows()[0]).htr_stage == "pysar"


def test_ordered_case_with_broken_passport_is_reported(space: Path) -> None:
    """Замовлена справа з битим паспортом не зникає мовчки (аудит 29.09.2026).

    Тека з карткою, але без кадрів — «замовлено, не завантажено». Нечитаний
    `_source.json` тут відкидався `except Exception: continue`, і справа
    просто випадала з реєстру.
    """
    from nyshporka.cases.collect import collect_rows

    ok = space / "data" / "raw" / "daoo" / "spr-1"
    ok.mkdir(parents=True)
    (ok / "_source.json").write_text(
        '{"shifra": "ДАОО 37-1-1", "title": "Метрична книга"}', encoding="utf-8")
    bad = space / "data" / "raw" / "daoo" / "spr-2"
    bad.mkdir(parents=True)
    (bad / "_source.json").write_text('{"shifra": "ДАОО 37-1-2", ', encoding="utf-8")
    listy = space / "data" / "raw" / "daoo" / "spr-3"
    listy.mkdir(parents=True)
    (listy / "_source.json").write_text("[1, 2]", encoding="utf-8")
    _library()
    got: list[dict[str, str]] = []
    rows, _ = collect_rows(unreadable=got)

    paths = {g["path"] for g in got}
    assert "data/raw/daoo/spr-2/_source.json" in paths, got
    assert "data/raw/daoo/spr-3/_source.json" in paths, got
    assert any(r.path == "data/raw/daoo/spr-1" and r.state == "ordered" for r in rows)
