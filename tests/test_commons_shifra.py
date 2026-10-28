"""📚 Шифра справи з назви файла Commons — для паспорта `nysh get`."""
from __future__ import annotations

import pytest

from nyshporka.sources.commons import shifra_of_ref, shifra_of_title


def _d(inv: str, spr: str, fond: str = "227") -> dict[str, str]:
    return {"archive": "DAHMO", "fond": fond, "inv": inv, "spr": spr}


@pytest.mark.parametrize("title,want", [
    ("ДАХмО 227-2д-905 Объявления о торгах (1899).pdf", _d("2д", "905")),
    ("ДАХмО 227-1-6563а Справи про щось.pdf", _d("1", "6563а")),
    ("ДАХмО 227-1d-356. 1851 рік. Метричні книги.pdf", _d("1д", "356")),
    ("ДАХмО Ф.227, о.2, с.6026 Списки мешканців.pdf", _d("2", "6026")),
    ("ДАХмО Ф. 227 О. 5доп С. 291 Статистичний опис.pdf", _d("5доп", "291")),
    ("1845 год. ДАХМО. Фонд 227, опись 6д, дело 34. Метрическая книга.pdf",
     _d("6д", "34")),
    ("ДАХмО 227-1-355а.pdf", _d("1", "355а")),
])
def test_shifra_z_nazvy(title, want):
    assert shifra_of_title(title) == want


@pytest.mark.parametrize("title", [
    "ДАХмО фонд 227 опис 1 том 1.pdf",          # опис фонду, не справа
    "ДАХмО 227-1-261Справа про призначення.pdf",  # злита назва — фантом справи 26
    "НЕВІДОМИЙ 227-1-5.pdf",                    # архів, якого пак не знає
    "Просто книга.pdf",
    "",
])
def test_ne_vygadue(title):
    assert shifra_of_title(title) == {}


def test_z_adresy_commons():
    ref = "file:ДАХмО 227-2д-905 Объявления (1899).pdf"
    assert shifra_of_ref("commons", ref) == _d("2д", "905")
    assert shifra_of_ref("commons", "https://commons.wikimedia.org/wiki/File:"
                         "ДАХмО_227-1-6563а_Справи.pdf") == _d("1", "6563а")
    assert shifra_of_ref("archium", ref) == {}
    assert shifra_of_ref("commons", "щось без префікса") == {}


def test_passport_gets_shifra(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    res = FetchResult(dest=tmp_path, frames=1)
    record_fetch(tmp_path, res, source="commons",
                 ref="file:ДАХмО 227-2д-905 Объявления (1899).pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert (meta["archive"], meta["fond"], meta["inv"], meta["spr"]) == (
        "DAHMO", "227", "2д", "905")


def test_passport_keeps_existing_shifra(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    (tmp_path / "meta.json").write_text(json.dumps(
        {"archive": "DAHMO", "fond": "230", "inv": "1", "spr": "1539"}),
        encoding="utf-8")
    record_fetch(tmp_path, FetchResult(dest=tmp_path, frames=1), source="commons",
                 ref="file:ДАХмО 227-2д-905 X.pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert (meta["fond"], meta["inv"], meta["spr"]) == ("230", "1", "1539")


def test_passport_without_shifra_writes_no_fields(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    record_fetch(tmp_path, FetchResult(dest=tmp_path, frames=1), source="commons",
                 ref="file:ДАХмО фонд 227 опис 1 том 1.pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert not {"archive", "fond", "inv", "spr"} & meta.keys()


# ── ключ справи з літерним описом (`cases take DAHMO/227/1д/406`) ────────────

@pytest.fixture
def _ws(tmp_path_factory):
    from nyshporka.core import workspace as W

    root = tmp_path_factory.mktemp("простір")
    (root / "data" / "raw").mkdir(parents=True)
    W.use(W.Workspace(root=root, name="тест", origin="test"))
    yield
    W.reset()


@pytest.mark.parametrize("key,want", [
    ("DAHMO/227/1д/406", ("DAHMO", "227", "1д", "406", "")),
    ("DAHMO/227/1d/406", ("DAHMO", "227", "1д", "406", "")),
    ("DAHMO/227/5доп/291", ("DAHMO", "227", "5доп", "291", "")),
    ("DAHMO/227/2д/355а", ("DAHMO", "227", "2д", "355", "а")),
    ("DAHMO/227/1/6563а", ("DAHMO", "227", "1", "6563", "а")),
    ("ДАХмО 227-2д-905", ("DAHMO", "227", "2д", "905", "")),
    ("DAHMO/230/1/43", ("DAHMO", "230", "1", "43", "")),
])
def test_parse_key_literal_opys(_ws, key, want):
    from nyshporka.fonds.registry import parse_key

    assert parse_key(key) == want


def test_parse_key_two_segments_unchanged(_ws):
    from nyshporka.cases.take import opys_named
    from nyshporka.fonds.registry import parse_key

    got = parse_key("DAHMO/230/43")
    assert got[:2] == ("DAHMO", "230") and got[3:] == ("43", "")
    assert not opys_named("DAHMO/230/43")
    assert opys_named("DAHMO/227/1д/406")


def test_disk_key_cyr_and_lat_opys_meet(_ws):
    from nyshporka.fonds.registry import disk_key

    assert disk_key("1д", "406", "") == disk_key("1d", "406", "")
    assert disk_key("1", "5", "а") == ("1", "5", "a")


def test_case_dir_name_for_literal_opys(_ws):
    from nyshporka.cases.take import case_dir_for

    assert case_dir_for("DAHMO", "227", "406", "", "1д").name == "op1д-spr-406"
    assert case_dir_for("DAHMO", "227", "291", "", "5доп").name == "op5доп-spr-291"


def test_library_reads_opys_from_dir_name(_ws):
    from nyshporka.library import _OP_PREFIX_RE

    assert _OP_PREFIX_RE.search("op5доп-spr-291").group(1) == "5доп"
    assert _OP_PREFIX_RE.search("op1д-spr-406").group(1) == "1д"
    assert _OP_PREFIX_RE.search("op2spr-148").group(1) == "2"


# ── одне місце письма літер шифри: `core.casekey` ─────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("355a", "355а"), ("1d", "1д"), ("1D", "1Д"), ("5dop", "5доп"), ("5DOP", "5доп"),
    ("2s", "2с"), ("2e", "2е"), ("3o", "3о"), ("4p", "4п"), ("5x", "5х"),
    ("4r", "4р"), ("6i", "6і"), ("00114", "114"), ("2a", "2а"),
])
def test_norm_part_homoglyphs(a, b):
    from nyshporka.core.casekey import norm_part

    assert norm_part(a) == norm_part(b)


def test_norm_part_leaves_unmapped_and_old_forms():
    from nyshporka.core.casekey import norm_part

    assert norm_part("7049ч") == "7049ч"        # ч у таблиці немає
    assert norm_part("@fuzovka") == "@fuzovka"
    assert norm_part("7864_parish56_1846") == "7864_parish56_1846"
    assert norm_part("2а") == "2a"             # як і раніше
    assert norm_part(1) == "1" and norm_part("") is None


def test_show_part_roundtrip():
    from nyshporka.core.casekey import norm_part, show_part

    for raw in ("1д", "1d", "5доп", "5dop", "2д", "355а", "6563a"):
        assert norm_part(show_part(raw)) == norm_part(raw)
    assert show_part("5dop") == "5доп" and show_part("1D") == "1д"
    assert show_part("GP35") == "gp35"


def test_registry_row_letter_scripts(_ws, tmp_path, monkeypatch):
    from nyshporka.fonds import registry as R

    rows = [{"opys": "2д", "spr_int": "355", "spr_letter": "а", "title": "x"},
            {"opys": "5доп", "spr_int": "291", "spr_letter": "", "title": "y"}]
    monkeypatch.setattr(R, "load_rows", lambda fond_id: rows)
    monkeypatch.setattr(R, "fond_path", lambda fond_id: tmp_path)   # існує
    assert R.registry_row("DAHMO", "227", "2д", "355", "a")[0] is rows[0]
    assert R.registry_row("DAHMO", "227", "2d", "355", "а")[0] is rows[0]
    assert R.registry_row("DAHMO", "227", "5dop", "291", "")[0] is rows[1]
    assert R.registry_row("DAHMO", "227", "2д", "356", "")[0] is None


@pytest.mark.parametrize("key,want", [
    ("DAHMO/230/43", ("DAHMO", "230", None, "43", "")),
    ("ДАХмО 230-1-43", ("DAHMO", "230", "1", "43", "")),
    ("DAHMO/230/1/43а", ("DAHMO", "230", "1", "43", "а")),
])
def test_old_keys_parse_as_before(_ws, key, want):
    from nyshporka.fonds.registry import parse_key

    got = parse_key(key)
    assert got[0] == want[0] and got[1] == want[1] and got[3:] == want[3:]
    if want[2] is not None:
        assert got[2] == want[2]


def test_op_dir_prefix_unchanged(_ws):
    from nyshporka.library import _norm_spr, _OP_PREFIX_RE

    assert _norm_spr(_OP_PREFIX_RE.search("op2spr-148").group(1)) == "2"


def test_table_is_injective_transliteration():
    from nyshporka.core import casekey as C

    assert len(set(C._FOLD.values())) == len(C._FOLD)          # різні літери - різні образи
    for cyr, lat in C._FOLD.items():
        assert C.norm_part(f"1{cyr}") == f"1{lat}"
        assert C.show_part(C.norm_part(f"1{cyr}")) == f"1{cyr}"   # round-trip
        assert C.show_part(f"1{lat}") == f"1{cyr}"
    # колишня колізія: `р` і `п` - різні літери
    assert C.norm_part("5дор") != C.norm_part("5доп")
    assert C.norm_part("5dop") == C.norm_part("5доп")
    assert C.norm_part("5dor") == C.norm_part("5дор")
