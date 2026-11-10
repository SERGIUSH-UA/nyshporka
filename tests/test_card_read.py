"""Картки зйомки, прочитані машиною: `nyshporka.cases.cardread`.

Тексти карток — дослівний вивід Windows OCR з обходу ANRM 10.11.2026. На
ньому стережеться те, що виявилось пасткою: літера номера відсунута пробілом
(«ДЕЛО 30 А»), російський двигун читає 16 як 46, а англійський — правильно;
дві картки справи можуть помилятись однаково, тож одиночне прочитання в карту
не йде.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.cases import cardread as CR

ITEM_RU = ("MICROFILMED ВУ ТНЕ GENEALOGICAL SOClETY NATIONAL ARCHlVE OF MOLDOVA ROLL NUMBER 1114 "
           "TITLE OF RECORD МЕТРИЧЕСКИЕ КНИГИ ЦЕРКВЕЙ Фонд 211 VOLUME/S ОПИСЬ 5 ДЕЛО 23 "
           "YEAR/S INCLUDEO 1819")
ITEM_EN = ("MICROFILMED BY THE GENEALOGICAL SOCIETY AT NATIONAL ARCHIVE OF REPUBLIC MOLDOVA "
           "QOHA 211 VOLUME'S onncs 5 AEno 23 YEAR'S INCLUDED 1819")
END_RU = ("END ОБ !ТЕМ РВОЈЕСТ NUMBER MLDv cHS- 1 ROLL NUMBER 1114 Фонд 211 VOLUME/S ОПИСЬ 5 "
          "ДЕЛО 23 YEAR/S INCLUDEO 1819")
END_EN = "END OF ITEM PROJECT NUMBER MLDv CHS- ROLL NUMBER 1114 211 VOLUME'S onncs 5 AEno 23 YEAR'S"


def test_item_card_fields() -> None:
    c = CR.parse("0004.jpg", ITEM_RU, ITEM_EN)
    assert (c.kind, c.shifra, c.years, c.contested) == ("item", "211-5-23", [1819], False)


def test_end_and_continued_kinds() -> None:
    assert CR.parse("x", END_RU, END_EN).kind == "end_item"
    assert CR.parse("x", "CONTlNUED РВОМ ANOTHER ROLL оо", "CONTINUED FROM ANOTHER ROLL 00").kind \
        == "cont_from"
    assert CR.parse("x", "CONTlNUED ОГ\\Ј ANOTHER ROLL оо", "CONTINUED ON ANOTHER ROLL").kind \
        == "cont_on"
    assert CR.parse("x", "END ор ROLL", "END OF ROLL").kind == "end_roll"
    assert CR.parse("x", "SHOULD MEASURE .25” АТ REDUCTION",
                    'SHOULD MEASURE .25" AT REDUCTION').kind == "target"


def test_letter_after_space_kept_and_stray_letter_dropped() -> None:
    a = CR.parse("x", "Фонд 151 - VOUJME ОПИСЬ 1 ДЕЛО 30 А YEAR!S INCLUDEO 1874",
                 "151 - VOLUME onncbl AEJIO 30 A YEAR/S INCLUDED 1874")
    assert a.shifra == "151-1-30А" and not a.contested
    # «Y» з розірваного «YEAR» — не літера номера
    b = CR.parse("x", "Фонд 2 ОПИСЬ 2 ДЕЛО 2 Y EAR/S 1813", "")
    assert b.shifra == "2-2-2"


def test_english_text_contests_misread_number() -> None:
    c = CR.parse("x", "Фонд 220 VOLUME/S ОПИСЬ 7 ДЕЛО 46 YEAR/S INCLUOEO 1797",
                 "-POAOCJIOBHAR- 220 VOLUME'S Onncb 7 AEJIO 16 YEAR'S INCLUDED 1797")
    assert c.shifra == "220-7-46" and c.contested


def test_garbled_delo_word_and_number_from_english() -> None:
    # «ДЕТ 249»: OCR загубив «ЛО», номер — і з рос., і з англ. тексту
    c = CR.parse("x", "ФОРМУЛЯРНЫЕ СПИСКИ Фонд 2 VOLUME ОПИСЬ 2 ДЕТ 249 УЕАВ 1914",
                 "OOHA 2 VOLUME onnCb 2 249 YEAR")
    assert c.shifra == "2-2-249" and not c.delo_from_en
    # рос. текст номера не дав зовсім — номер з англ., але позначений
    d = CR.parse("x", "Фонд 2 VOLUME ОПИСЬ 2 YEAR 1914", "OOHA 2 VOLUME onnCb 2 249 YEAR")
    assert d.shifra == "2-2-249" and d.delo_from_en
    # «ДЕТЕЙ» — не номер справи
    assert CR.parse("x", "МЕТРИКИ ДЕТЕЙ Фонд 2 ОПИСЬ 2", "").delo is None


def test_pair_from_english_numbers_alone_is_not_confirmed() -> None:
    names = _names(20)
    a = CR.Card("0002.jpg", "item", "946", "2", "2", delo_from_en=True)
    b = CR.Card("0010.jpg", "end_item", "946", "2", "2", delo_from_en=True)
    rows = [r for r in CR.build_rows(names, {a.name: a, b.name: b}) if r.kind == "case"]
    CR.confirm(rows, "ANRM", None)
    assert rows[0].spr == "?" and rows[0].ocr == "946-2-2"


def test_two_end_cards_close_one_case() -> None:
    names = _names(20)
    cards = {c.name: c for c in (
        _card("0002.jpg", "item", "136-1-303"), _card("0010.jpg", "end_item", "136-1-303"),
        _card("0011.jpg", "cont_on", "136-1-303"), _card("0012.jpg", "end_roll"))}
    rows = CR.build_rows(names, cards)
    case = [r for r in rows if r.kind == "case"]
    assert len(case) == 1 and (case[0].last, case[0].end_kind) == ("0011.jpg", "cont_on")


def test_same_case_restarted_without_end_merges() -> None:
    names = _names(30)
    cards = {c.name: c for c in (
        _card("0003.jpg", "item", "2-2-249"), _card("0010.jpg", "cont_from"),
        _card("0011.jpg", "item", "2-2-249"), _card("0020.jpg", "end_item", "2-2-249"))}
    case = [r for r in CR.build_rows(names, cards) if r.kind == "case"]
    assert [(r.first, r.last) for r in case] == [("0003.jpg", "0020.jpg")]


def test_selective_and_microfilm() -> None:
    assert CR.parse("x", "СПИСКИ ЖИТЕЛЕЙ -ВЫБОРОЧНО- Фонд 1 ОПИСЬ 1 ДЕЛО 3246", "").selective
    assert CR.parse("0001.jpg", "2103335", "2103335").microfilm == "2103335"
    # сім цифр на картці справи — не номер мікрофільму
    assert CR.parse("x", ITEM_RU + " 2103335", ITEM_EN).microfilm is None


def _names(n: int) -> list[str]:
    return [f"{i:04d}.jpg" for i in range(1, n + 1)]


def _card(name: str, kind: str, shifra: str | None = None, *, contested: bool = False,
          part: str | None = None) -> CR.Card:
    f, o, d = shifra.split("-") if shifra else (None, None, None)
    return CR.Card(name, kind, f, o, d, part=part, contested=contested)


def test_rows_follow_cards_and_leader_is_outside() -> None:
    names = _names(30)
    cards = {c.name: c for c in (
        _card("0001.jpg", "other"),
        _card("0003.jpg", "item", "211-5-23"), _card("0012.jpg", "end_item", "211-5-23"),
        _card("0013.jpg", "item", "211-5-24"), _card("0025.jpg", "cont_on", "211-5-24"),
        _card("0026.jpg", "target"), _card("0027.jpg", "end_roll"))}
    rows = CR.build_rows(names, cards)
    got = [(r.kind, r.first, r.last, r.ocr, r.end_kind) for r in rows]
    assert got == [
        ("-", "0001.jpg", "0002.jpg", "", ""),
        ("case", "0003.jpg", "0012.jpg", "211-5-23", "end_item"),
        ("case", "0013.jpg", "0025.jpg", "211-5-24", "cont_on"),
        ("-", "0026.jpg", "0030.jpg", "", ""),
    ]


def test_head_without_start_card_is_continuation() -> None:
    names = _names(20)
    cards = {c.name: c for c in (
        _card("0002.jpg", "cont_from"), _card("0003.jpg", "item", "88-1-2052"),
        _card("0010.jpg", "end_item", "88-1-2052"),
        _card("0011.jpg", "item", "88-1-2053"))}
    rows = CR.build_rows(names, cards)
    head = rows[1]
    assert head.cont_from and head.first == "0002.jpg" and head.ocr == "88-1-2052"
    rd = CR.Reading(Path("."), names, True, [], [], "ok", cards=cards, rows=rows)
    assert "continued_from" in [c for c, _ in CR.checks(rd, None)]


def test_volumes_of_one_case_merge() -> None:
    names = _names(20)
    cards = {c.name: c for c in (
        _card("0002.jpg", "item", "2-2-21", part="1"), _card("0008.jpg", "end_item", "2-2-21"),
        _card("0009.jpg", "item", "2-2-21", part="2"), _card("0015.jpg", "end_item", "2-2-21"))}
    rows = [r for r in CR.build_rows(names, cards) if r.kind == "case"]
    assert len(rows) == 1 and (rows[0].first, rows[0].last, rows[0].parts) == ("0002.jpg", "0015.jpg",
                                                                                  ["1", "2"])


def test_confirm_needs_passport_or_agreeing_pair() -> None:
    names = _names(40)
    cards = {c.name: c for c in (
        _card("0002.jpg", "item", "211-5-23"), _card("0010.jpg", "end_item", "211-5-23"),   # пара
        _card("0011.jpg", "item", "211-5-24"),                                             # одиночна
        _card("0020.jpg", "item", "220-7-46", contested=True),                             # спірна пара
        _card("0025.jpg", "end_item", "220-7-46"),
        _card("0026.jpg", "item", "211-5-50"))}                                            # = паспорт
    rows = [r for r in CR.build_rows(names, cards) if r.kind == "case"]
    CR.confirm(rows, "ANRM", "211-5-50")
    assert [(r.spr, r.confirmed) for r in rows] == [
        ("ANRM 211-5-23", "pair"), ("?", ""), ("?", ""), ("ANRM 211-5-50", "passport")]
    CR.confirm(rows, "ANRM", None, accept_ocr=True)
    assert rows[1].spr == "ANRM 211-5-24" and rows[1].confirmed == "ocr"


def test_dark_by_bytes_absolute_then_relative() -> None:
    bpp = {f"{i:04d}.jpg": 0.2 for i in range(1, 101)} | {"0010.jpg": 0.03, "0050.jpg": 0.04}
    dark, thr = CR.dark_by_bytes(bpp)
    assert sorted(dark) == ["0010.jpg", "0050.jpg"] and thr == CR.CARD_BPP
    grey = {f"{i:04d}.jpg": 0.2 for i in range(1, 101)} | {"0007.jpg": 0.09}
    dark, thr = CR.dark_by_bytes(grey)
    assert dark == ["0007.jpg"] and thr == pytest.approx(0.12)


def _remote_film(tmp_path: Path, n: int, dark: tuple[int, ...]) -> Path:
    d = tmp_path / "film-005783228"
    d.mkdir()
    frames = [{"name": f"{i:04d}.jpg", "w": 1000, "h": 1000,
               "size": 30_000 if i in dark else 200_000, "sha256": "0" * 64} for i in range(1, n + 1)]
    (d / "_r2_frames.json").write_text(json.dumps({
        "dgs": "005783228", "frames": frames,
        "parts": [{"key": "cases/x.tar", "frames": [f["name"] for f in frames]}]}), encoding="utf-8")
    (d / "_source.json").write_text(json.dumps({"repo": "ANRM", "fond": "2", "opys": "2",
                                                "spr": "film005783228"}), encoding="utf-8")
    return d


def test_remote_candidates_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CR, "run_pages", lambda *_a: {"0030.jpg": {"lines": 4, "chars": 20,
                                                                   "conf": 0.6}})
    d = _remote_film(tmp_path, 40, (5, 6, 20))
    c = CR.candidates(d)
    assert c.remote and c.dgs == "005783228" and c.by_run == ["0030.jpg"]
    assert c.want == ["0001.jpg", "0005.jpg", "0006.jpg", "0007.jpg", "0020.jpg", "0021.jpg",
                      "0030.jpg"]
    rd = CR.read(d)
    assert rd.missing == c.want and not rd.rows      # без кадрів карти немає


def _jpg(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (60, 40), 10).save(path, "JPEG")


def test_read_with_cached_ocr_builds_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CR, "run_pages", lambda *_a: {})
    d = _remote_film(tmp_path, 30, (5, 6, 20))
    texts = {"0001.jpg": ("2389664", "2389664"), "0005.jpg": (ITEM_RU, ITEM_EN),
             "0006.jpg": ("", ""), "0007.jpg": ("", ""),
             "0020.jpg": (END_RU, END_EN), "0021.jpg": ("END ор ROLL", "END OF ROLL")}
    for name in texts:
        _jpg(d / CR.CARDS_DIR / name)

    def fake_ocr(images: dict[str, Path], **_kw: object) -> dict[str, dict[str, str]]:
        return {n: {"ru": texts[n][0], "en": texts[n][1]} for n in images}

    monkeypatch.setattr(CR, "ocr", fake_ocr)
    rd = CR.read(d)
    assert rd.microfilm == "2389664" and rd.ocr_state == "ok"
    case = rd.cases[0]
    assert (case.first, case.last, case.spr, case.confirmed) == ("0005.jpg", "0020.jpg",
                                                                 "ANRM 211-5-23", "pair")
    saved = CR.save(rd)
    mp = json.loads(saved["map"].read_text(encoding="utf-8"))
    assert [r["spr"] for r in mp] == ["-", "ANRM 211-5-23", "-"]
    # другий виклик — з кешу, без OCR
    monkeypatch.setattr(CR, "ocr", lambda *_a, **_k: pytest.fail("кеш не спрацював"))
    assert CR.read(d).ocr_state == "cached"
    codes = [c for c, _ in rd.warnings]
    assert "several_cases" not in codes and "fill_numbers" not in codes


def test_no_ocr_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CR.os, "name", "posix")
    with pytest.raises(CR.OcrUnavailable):
        CR._powershell()


def test_op_names_missing_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O

    monkeypatch.setattr(CR, "run_pages", lambda *_a: {})
    d = _remote_film(tmp_path, 12, (4,))
    env = O.call("cases.cards", {"case_dir": str(d), "sheet_dir": str(tmp_path / "s")})
    assert env.ok and env.data["missing"] == ["0001.jpg", "0004.jpg", "0005.jpg"]
    assert "need_frames" in [w.code for w in env.warnings]
