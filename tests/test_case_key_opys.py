"""Опис у ключі кожної справи: дві книги одного номера — два ключі, завжди.

27.09.2026 «ДАДнО 193-1-213» (Катеринослав 1865–1867) і «ДАДнО 193-3-213»
(Нікополь 1899) мали один ключ `DADNO/193/213`: другу справу завести було
неможливо, і дослідниця назвала її «213b». Опис — фізично інший підрозділ
фонду, тож ключ несе його завжди, а невідомий опис пишеться `_`.

Старий ключ (до 0.22) читається через карту переїзду — його не пишуть.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

R: Any = None
L: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Порожній простір. Заморожені на імпорті шляхи підмінено поіменно —
    та сама причина, що в `test_register_and_notes.space`."""
    from nyshporka.core import legacy_key as K
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    K.reset()

    global R, L
    from nyshporka import library as lib
    from nyshporka.cases import db as DB
    from nyshporka.cases import register
    from nyshporka.pagestore import store as S

    R, L = register, lib
    for mod, attr, value in (
        (lib, "ROOT", tmp_path), (lib, "RAW_DIR", tmp_path / "data" / "raw"),
        (lib, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (lib, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)
    lib._sidecar_case.cache_clear()
    yield tmp_path
    K.reset()
    W.reset()


def _folder(root: Path, rel: str) -> Path:
    d = root / "data" / "raw" / rel
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"x")
    return d


def _rebuild() -> list[Any]:
    L._sidecar_case.cache_clear()
    entries = L.build_library()
    L.write_library(entries)
    return entries


def _passport(d: Path, shifra: str, opys: str) -> None:
    """Паспорт, який пише завантажувач (поле `opis`), а не реєстрація."""
    (d / "_source.json").write_text(json.dumps(
        {"shifra": shifra, "opis": opys}, ensure_ascii=False), encoding="utf-8")


def _two_books(root: Path) -> tuple[Path, Path]:
    kat = _folder(root, "катеринослав_1865")
    R.describe(kat, shifra="ДАДнО 193-1-213", title="Покровська ц. м. Катеринослава")
    nik = _folder(root, "нікополь_1899")
    R.describe(nik, shifra="ДАДнО 193-3-213", title="Нікополь")
    _rebuild()
    return kat, nik


# ── будова ключа ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("parts", "key"), [
    (("DAHMO", "315", "1", "8433"), "DAHMO/315/1/8433"),
    (("DAHMO", "0315", "01", "08433"), "DAHMO/315/1/8433"),
    (("DAVIO", "Р-6129", "24", "5а"), "DAVIO/R-6129/24/5a"),
    (("DAOO", "37", None, "1235"), "DAOO/37/_/1235"),
    (("ANRM", "211", None, "@fuzovka"), "ANRM/211/@fuzovka"),
    (("ANRM", "211", "11", "@razeni_goian"), "ANRM/211/11/@razeni_goian"),
    (("DAHMO", "315", "1", "7864_parish56_1846"), "DAHMO/315/1/7864_parish56_1846"),
])
def test_key_carries_the_opys_in_every_fond(parts: tuple[Any, ...], key: str) -> None:
    from nyshporka.core import casekey

    assert casekey.make(*parts) == key
    assert casekey.parse(key) is not None and casekey.parse(key).key == key


@pytest.mark.parametrize("old", ["DAHMO/315/8433", "DAHMO/196-8/712", "DAVIO/R-6129-24/5",
                                 "ANRM/211-11/@razeni_goian", "?/224/56"])
def test_a_three_part_key_is_always_the_old_form(old: str) -> None:
    """Нова форма трискладового рядка не породжує, тож старий ключ видно з
    першого погляду (збірка без опису — не стара: її форма не змінилась)."""
    from nyshporka.core import casekey

    assert casekey.parse(old) is None and casekey.is_legacy(old)
    assert not casekey.is_legacy("ANRM/211/@fuzovka")


def test_unknown_opys_is_not_proof_of_another_book() -> None:
    from nyshporka.core import casekey

    assert casekey.compatible("CDIAK/2/_/169", "CDIAK/2/1/169")
    assert casekey.compatible("CDIAK/2/1/169", "CDIAK/2/1/169")
    assert not casekey.compatible("CDIAK/2/1/169", "CDIAK/2/2/169")
    assert not casekey.compatible("CDIAK/2/_/169", "DAHMO/2/_/169")


# ── дві книги одного номера ──────────────────────────────────────────────────

def test_two_opyses_are_two_cases_with_their_own_files(space: Path) -> None:
    from nyshporka.pagestore import store as S

    _two_books(space)
    old = S.resolve_case("ДАДнО 193-1-213")
    new = S.resolve_case("ДАДнО 193-3-213")
    assert (old.key, new.key) == ("DADNO/193/1/213", "DADNO/193/3/213")
    assert S.case_path(old).name == "193-1-213.json"
    assert S.case_path(new).name == "193-3-213.json"


def test_without_the_opys_two_books_are_a_refusal(space: Path) -> None:
    """🔴 Мовчки взяти першу-ліпшу = дописати аркуші в чужу книгу."""
    from nyshporka.pagestore import store as S

    _two_books(space)
    with pytest.raises(ValueError, match=r"193-1-213.*193-3-213"):
        S.resolve_case("DADNO/193/_/213")


def test_naming_the_opys_does_not_borrow_the_other_books_record(space: Path) -> None:
    """224-2-49 на диску; людина набирає «224-1-49» — не має отримати шифру,
    теку й облік чужої книги."""
    from nyshporka.pagestore import store as S

    d = _folder(space, "cdiak_224/spr-49")
    _passport(d, "ЦДІАК 224-2-49", "2")
    _rebuild()
    mine = S.resolve_case("ЦДІАК 224-1-49")
    theirs = S.resolve_case("ЦДІАК 224-2-49")
    assert mine.key == "CDIAK/224/1/49" and mine.path == ""
    assert theirs.key == "CDIAK/224/2/49" and theirs.path


def test_a_folder_of_another_opys_is_not_swallowed_as_a_second_shot(space: Path) -> None:
    """Тека `dadno_193/spr-213` (ім'я без опису) з паспортом оп. 3 поруч зі
    справою оп. 1 — окремий запис бібліотеки, а не «другий ракурс» чужої книги."""
    kat = _folder(space, "катеринослав_1865")
    R.describe(kat, shifra="ДАДнО 193-1-213")
    nik = _folder(space, "dadno_193/spr-213")
    _passport(nik, "ДАДнО 193-3-213", "3")
    entries = _rebuild()
    first = next(e for e in entries if e.path == kat.relative_to(space).as_posix())
    second = next(e for e in entries if e.path == nik.relative_to(space).as_posix())
    assert second.path not in first.extra_paths
    assert (first.key, second.key) == ("DADNO/193/1/213", "DADNO/193/3/213")


def test_a_folder_without_opys_takes_the_fond_default_not_the_only_other_book(
        space: Path) -> None:
    """🔴 `dahmo_230/spr-12` без опису — це 230-1-12 (опис за замовчуванням
    фонду), а не «ще один ракурс» справи 230-3-12, хоч та й єдина з номером 12."""
    third = _folder(space, "dahmo_230/op3-spr-12")
    plain = _folder(space, "dahmo_230/spr-12")
    entries = _rebuild()
    by_path = {e.path: e for e in entries}
    rel = lambda d: d.relative_to(space).as_posix()  # noqa: E731
    assert by_path[rel(third)].key == "DAHMO/230/3/12"
    assert by_path[rel(plain)].key == "DAHMO/230/1/12"


def test_a_folder_with_unknown_opys_joins_the_only_case(space: Path) -> None:
    """Невідомий опис — не колізія: друга тека тієї самої книги без опису в
    імені й паспорті приєднується до єдиної справи з цим номером."""
    first = _folder(space, "dadno_193/op3-spr-213")
    second = _folder(space, "dadno_193_render/spr-213")
    entries = _rebuild()
    keys = [e.key for e in entries if e.spr == "213"]
    assert keys == ["DADNO/193/3/213"], keys
    one = next(e for e in entries if e.spr == "213")
    assert one.path == first.relative_to(space).as_posix()
    assert second.relative_to(space).as_posix() in one.extra_paths


def test_no_opys_anywhere_is_an_unknown_key(space: Path) -> None:
    _folder(space, "daoo_37/spr-1235")
    entries = _rebuild()
    assert [e.key for e in entries] == ["DAOO/37/_/1235"]


# ── старі ключі ──────────────────────────────────────────────────────────────

def test_an_old_key_leads_to_the_book_it_meant(space: Path) -> None:
    """Старий ключ без опису належав ПЕРШІЙ книзі (друга мала ключ з описом із
    реєстру колізій) — карта переїзду знає це, а не вгадує."""
    from nyshporka.core import legacy_key
    from nyshporka.pagestore import store as S

    _two_books(space)
    (space / "data" / "cases").mkdir(parents=True, exist_ok=True)
    (space / "data" / "cases" / "opys_keys.json").write_text(json.dumps({"cases": [
        {"repo": "DADNO", "fond": "193", "opys": "3", "spr": "213"}]}), encoding="utf-8")
    legacy_key.reset()
    assert S.resolve_case("DADNO/193/213").key == "DADNO/193/1/213"
    assert S.resolve_case("DADNO/193-3/213").key == "DADNO/193/3/213"
    assert legacy_key.current_key("DADNO/193/213") == "DADNO/193/1/213"


def test_an_old_key_of_a_case_not_in_the_library_takes_the_fond_default(
        space: Path) -> None:
    from nyshporka.core import legacy_key

    assert legacy_key.current_key("DAHMO/315/8433") == "DAHMO/315/1/8433"
    assert legacy_key.current_key("DAOO/37/1235") == "DAOO/37/_/1235"
    assert legacy_key.current_key("DAHMO/196-8/712") == "DAHMO/196/8/712"
    assert legacy_key.current_key("DAHMO/315/1/8433") == "DAHMO/315/1/8433"


def test_without_a_workspace_old_keys_still_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервер Супряги простору не має: карти переїзду там немає, ключ — за полями."""
    from nyshporka.core import legacy_key
    from nyshporka.core import workspace as W

    def nowhere() -> Any:
        raise W.WorkspaceError("немає")

    monkeypatch.setattr(W, "workspace", nowhere)
    legacy_key.reset()
    assert legacy_key.moves() == {}
    assert legacy_key.translate("DAHMO/315/8433") is None


def test_dict_stores_read_old_keys_before_the_move(space: Path) -> None:
    from nyshporka.core import legacy_key

    d = {"DAHMO/315/8433": {"verdict": "no_clan"}, "_comment": "x"}
    assert legacy_key.get(d, "DAHMO/315/1/8433") == {"verdict": "no_clan"}
    assert legacy_key.get(d, "DAHMO/315/8433") == {"verdict": "no_clan"}
    assert legacy_key.rekeyed(d) == {"DAHMO/315/1/8433": {"verdict": "no_clan"},
                                     "_comment": "x"}


# ── простір до переносу ──────────────────────────────────────────────────────

def test_an_unmoved_workspace_reads_the_old_file_and_refuses_to_write(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """До `nysh cases rekey` облік читається з файла під старим іменем, а
    запис відмовляє: новий файл поруч зі старим розділив би справу надвоє."""
    from dataclasses import replace

    from nyshporka.core import casekey
    from nyshporka.core import workspace as W
    from nyshporka.pagestore import store as S
    from nyshporka.pagestore.models import PageNote

    d = _folder(space, "dahmo_315/spr-8433")
    R.describe(d, shifra="ДАХмО 315-1-8433")
    _rebuild()
    pages = space / "data" / "pages" / "DAHMO"
    pages.mkdir(parents=True)
    (pages / "315-8433.json").write_text(json.dumps({
        "version": 1, "key": "DAHMO/315/8433", "repo": "DAHMO", "fond": "315",
        "spr": "8433", "opys": "1", "pages": {"0001.jpg": {
            "scan": "0001.jpg", "page_type": "birth", "surnames": ["Ковальскій"],
            "noted": "2026-09-01", "status": "full"}}, "records": []},
        ensure_ascii=False), encoding="utf-8")
    W.use(replace(W.workspace(), keys=1))

    ref = S.resolve_case("ДАХмО 315-1-8433")
    assert ref.key == "DAHMO/315/1/8433"
    st = S.case_status(ref, scans=["0001.jpg"])
    assert st["scans"][0]["noted"], "облік до переносу не читається"
    with pytest.raises(casekey.LegacyKeysError, match="nysh cases rekey"):
        S.annotate_pages(ref, [PageNote(scan="0002.jpg", page_type="birth")])
    assert not (pages / "315-1-8433.json").exists()


def test_doctor_names_unknown_opys_and_an_unmoved_workspace(space: Path) -> None:
    from dataclasses import replace

    from nyshporka.core import workspace as W
    from nyshporka.setup import doctor as D

    _folder(space, "daoo_37/spr-1235")
    _rebuild()
    got = D._case_keys()
    assert got.level == "warn" and "1 справ без опису" in got.detail, got.detail
    W.use(replace(W.workspace(), keys=1))
    assert "старих ключах" in D._case_keys().detail


# ── справа, з якої кадри знято ───────────────────────────────────────────────
def _passport_file(d: Path, shifra: str, **extra: Any) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "_source.json").write_text(json.dumps({"shifra": shifra, **extra},
                                               ensure_ascii=False), encoding="utf-8")


def test_a_case_whose_frames_were_dropped_keeps_its_passport_opys(space: Path) -> None:
    """Справу прочитано, кадри знято (`pages_dropped`), докази лишились копією
    в сторі цитат — без паспорта. Справа — тека з паспортом, з його описом;
    копія доказів — її другий шлях, а не окрема справа з `_`."""
    home = space / "data" / "raw" / "cdiak_2" / "spr-43"
    _passport_file(home, "ЦДІАК 2-1-43", pages_dropped={"when": "2026-09-23"})
    copy = _folder(space, "_citations/cdiak_2/spr-43")
    entries = _rebuild()
    got = [e for e in entries if e.spr == "43"]
    assert [e.key for e in got] == ["CDIAK/2/1/43"], [e.key for e in got]
    assert got[0].path == home.relative_to(space).as_posix()
    assert copy.relative_to(space).as_posix() in got[0].extra_paths


def test_an_offloaded_case_is_still_a_case(space: Path) -> None:
    home = space / "data" / "raw" / "dahmo_315" / "spr-8433"
    _passport_file(home, "ДАХмО 315-1-8433")
    (home / "_offloaded.json").write_text("{}", encoding="utf-8")
    assert [e.key for e in _rebuild()] == ["DAHMO/315/1/8433"]


def test_a_bare_card_without_frames_is_not_a_case(space: Path) -> None:
    """Порожня тека з паспортом, але без позначки знятих кадрів, — картка
    опису, а не справа: позначка мусить бути явною."""
    _passport_file(space / "data" / "raw" / "dahmo_315" / "spr-8433", "ДАХмО 315-1-8433")
    assert _rebuild() == []


def test_a_second_folder_with_a_passport_gives_the_case_its_opys(space: Path) -> None:
    """Першою обхід бачить копію без паспорта (справа без опису), другою —
    теку з паспортом: опис з паспорта переходить справі, а не губиться."""
    copy = _folder(space, "cdiak_2_render/spr-43")
    _passport_file(space / "data" / "raw" / "_kept" / "cdiak_2" / "spr-43", "ЦДІАК 2-1-43",
              pages_dropped={"when": "2026-09-23"})
    got = [e for e in _rebuild() if e.spr == "43"]
    assert [e.key for e in got] == ["CDIAK/2/1/43"], [e.key for e in got]
    assert got[0].path == copy.relative_to(space).as_posix()
    assert got[0].shifra == "ЦДІАК 2-1-43"
