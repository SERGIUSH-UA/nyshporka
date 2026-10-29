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
    assert shifra_of_ref("commons", ref) == "ДАХмО 227-2д-905"
    assert shifra_of_ref("commons", "https://commons.wikimedia.org/wiki/File:"
                         "ДАХмО_227-1-6563а_Справи.pdf") == "ДАХмО 227-1-6563а"
    assert shifra_of_ref("archium", ref) == ""
    assert shifra_of_ref("commons", "щось без префікса") == ""


def _fetch(case_dir, title):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    record_fetch(case_dir, FetchResult(dest=case_dir, frames=1), source="commons",
                 ref=f"file:{title}", want=1)
    return json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("title,key", [
    ("ДАХмО 227-2д-905 Объявления (1899).pdf", "DAHMO/227/2d/905"),
    ("ДАХмО 227-1d-356. 1851 рік. Метричні книги.pdf", "DAHMO/227/1d/356"),
    ("ДАХмО Ф. 227 О. 5доп С. 291 Статистичний опис.pdf", "DAHMO/227/5dop/291"),
    ("1845 год. ДАХМО. Фонд 227, опись 6д, дело 34. Метрическая книга.pdf",
     "DAHMO/227/6d/34"),
    ("ДАХмО 227-1-6563а Справи.pdf", "DAHMO/227/1/6563a"),
])
def test_get_folder_is_seen_by_library_under_its_key(_ws, title, key):
    """🔴 Наскрізно: `nysh get commons … --out <будь-яка тека>` → бібліотека й
    резолвер бачать теку під ключем із назви файла. Поля без рядка `shifra`
    бібліотека не читала, і тека лишалась нічиєю (рецензія 29.10.2026)."""
    from PIL import Image

    from nyshporka import library as L
    from nyshporka.core.workspace import workspace
    from nyshporka.pagestore import resolve_case

    d = workspace().raw / "commons_get" / "moja_teka"
    d.mkdir(parents=True)
    Image.new("L", (20, 20)).save(d / "0001.jpg")
    meta = _fetch(d, title)
    assert meta["shifra_src"] == "назва файла Commons"
    assert not {"archive", "fond", "inv", "spr"} & meta.keys()
    L._sidecar_case.cache_clear()
    entries = L.build_library()
    assert [e.key for e in entries] == [key]
    L.write_library(entries)
    assert resolve_case(key).path.endswith("commons_get/moja_teka")


@pytest.mark.parametrize("have", [
    {"archive": "DAHMO", "fond": "230", "inv": "1", "spr": "1539"},
    {"archive": "DAHMO", "fond": "230"},                 # часткова — теж шифра
    {"opis": "1", "spr": "356"},                          # синонім опису
    {"repo": "DAHMO"},
    {"archive": "?"},                                     # «архів невідомий» — відповідь
    {"shifra": "ДАХмО 230-1-1539"},
    {"delo": "Ф. 211 Оп. 3 Д. 140"},
])
@pytest.mark.parametrize("where", ["meta.json", "_source.json"])
def test_passport_with_any_shifra_is_not_touched(tmp_path, have, where):
    """Паспорт, де шифру (хоч частину) вже назвали, не дістає нічого з назви
    файла: доповнення по полю складало справу з двох різних."""
    import json

    (tmp_path / where).write_text(json.dumps(have, ensure_ascii=False), encoding="utf-8")
    meta = _fetch(tmp_path, "ДАХмО 227-2д-905 X.pdf")
    if where == "meta.json":
        assert {k: meta[k] for k in have} == have
    assert "shifra_src" not in meta
    assert ("shifra" in meta) == ("shifra" in have and where == "meta.json")


def test_passport_without_shifra_writes_nothing(tmp_path):
    meta = _fetch(tmp_path, "ДАХмО фонд 227 опис 1 том 1.pdf")
    assert not {"shifra", "archive", "fond", "inv", "spr"} & meta.keys()


def test_take_does_not_take_shifra_from_the_title(tmp_path):
    """`cases take` знає шифру з реєстру опису — назва тому її не підміняє."""
    import json
    from types import SimpleNamespace

    from nyshporka.cases import acquire as A
    from nyshporka.sources.base import FetchResult

    class _Src:
        def fetch(self, ref, dest, on_progress=None):
            name = ref.split(":", 1)[1]
            (dest / name).write_bytes(b"%PDF-1.4\n%%EOF\n")
            return FetchResult(dest=dest, frames=1)

        def manifest(self, ref):
            return SimpleNamespace(frames=1)

    A.from_commons(tmp_path, "ДАХмО 227-2д-906 X.pdf", archive="DAHMO", fond="227",
                   opys="2д", spr="905", source=_Src())
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert "shifra" not in meta
    assert (meta["fond"], meta["inv"], meta["spr"]) == ("227", "2д", "905")


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
    ("DAHMO/227/2д/355a", ("DAHMO", "227", "2д", "355", "а")),   # латинська літера справи
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
    from nyshporka.library import _OP_PREFIX_RE, _norm_spr

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


def test_case_dir_same_for_both_scripts(_ws):
    from nyshporka.cases.take import case_dir_for

    a = case_dir_for("DAHMO", "227", "355", "a", "2д")
    b = case_dir_for("DAHMO", "227", "355", "а", "2d")
    assert a == b and a.name == "op2д-spr-355а"


def test_align_names_use_shown_form(_ws):
    from nyshporka.core.workspace import workspace
    from nyshporka.share import align

    d = workspace().raw / "dahmo_227" / "op2д-spr-355а"
    d.mkdir(parents=True)
    assert align.case_home_for("DAHMO/227/2d/355a") == d


@pytest.mark.parametrize("stem,want", [
    ("op3дод-spr-4", "3dod"), ("op3dod-spr-4", "3dod"), ("op5доп-spr-1", "5dop"),
    ("op1д-spr-406", "1d"), ("op2spr-148", "2"), ("op2-spr-148", "2"),
    ("op4а_x", "4a"),
    # `spr` злите з літерним описом — теж роздільник, не частина опису
    ("op1dspr-406", "1d"), ("op1дspr-406", "1d"), ("op5допspr-291", "5dop"),
])
def test_op_prefix_any_suffix(stem, want):
    from nyshporka.library import _OP_PREFIX_RE, _norm_spr

    assert _norm_spr(_OP_PREFIX_RE.search(stem).group(1)) == want


def test_fsub_takes_long_suffix():
    from nyshporka.library import _FSUB_RE

    assert _FSUB_RE.fullmatch("f227_op5доп").group(2) == "5доп"


def test_registry_filter_opys_script_insensitive():
    from nyshporka.fonds.registry import filter_rows

    rows = [{"opys": "1Д", "spr": "1"}, {"opys": "5д", "spr": "2"}, {"opys": "2", "spr": "3"}]
    for q in ("1д", "1d", "1Д"):
        got = filter_rows(rows, opys=q)
        assert [r["spr"] for r in (got[0] if isinstance(got, tuple) else got)] == ["1"]


def test_year_is_not_fond():
    assert shifra_of_title("ДАХмО 2021-1-12.pdf") == {}
    assert shifra_of_title("ДАХмО ф.2021-1-12.pdf")["fond"] == "2021"


def test_write_meta_spr_shown_form(tmp_path):
    import json

    from nyshporka.cases.acquire import write_meta

    for spr in ("6563a", "6563а"):
        write_meta(tmp_path, archive="DAHMO", fond="227", opys="1", spr=spr,
                   files=[], source="commons")
        assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["spr"] == "6563а"


# ── багатолітерний суфікс опису в усіх розборах шифри ────────────────────────

@pytest.mark.parametrize("text,want", [
    ("ДАХмО 227-5доп-291", ("DAHMO/227/5dop/291", "5доп", "291")),
    ("ДАХмО 227-5dop-291", ("DAHMO/227/5dop/291", "5dop", "291")),
    ("ДАХмО ф.227 оп.5доп спр.291", ("DAHMO/227/5dop/291", "5доп", "291")),
    ("ДАХмО 227-5доп-291а", ("DAHMO/227/5dop/291a", "5доп", "291а")),
    ("ДАХмО 227-3дод-4", ("DAHMO/227/3dod/4", "3дод", "4")),
    ("ДАХмО 227-1d-406", ("DAHMO/227/1d/406", "1d", "406")),
    ("ДАХмО 227-2d-355a", ("DAHMO/227/2d/355a", "2d", "355a")),
    ("ДАХмО 227-6d-45", ("DAHMO/227/6d/45", "6d", "45")),
    ("ДАХмО 230-1-43", ("DAHMO/230/1/43", "1", "43")),
])
def test_resolve_and_register_multiletter_opys(_ws, text, want):
    from nyshporka.cases.register import parse_shifra
    from nyshporka.pagestore import resolve_case

    key, opys, spr = want
    assert resolve_case(text).key == key
    got = parse_shifra(text)
    assert (got.opys, got.spr) == (opys, spr)


def test_resolve_key_form_unchanged(_ws):
    from nyshporka.pagestore import resolve_case

    assert resolve_case("DAHMO/230/43").key == "DAHMO/230/1/43"


def test_manifest_shifra_with_multiletter_opys_passes(_ws):
    from nyshporka.share.publish import _normalize_shifra

    case = {"shifra": "ДАХмО 227-5доп-291"}
    assert _normalize_shifra(case, "DAHMO/227/5dop/291") == case


def test_prose_shifra_does_not_swallow_next_word():
    from nyshporka.library import _SHIFRA_RE

    m = _SHIFRA_RE.search("див. 127-1-5 абв про щось")
    assert m.groups() == ("127", "1", "5")
    # Злите слово не дає літери справи: не фантом `261С`, а справа 261.
    m = _SHIFRA_RE.search("ДАХмО 227-1-261Справа про призначення")
    assert m.groups() == ("227", "1", "261")
    m = _SHIFRA_RE.search("ДАХмО 230-1-2а. Метрична")
    assert m.groups() == ("230", "1", "2а")
    m = _SHIFRA_RE.search("ЦДІАК 127-1-5і про")
    assert m.groups() == ("127", "1", "5і")
    m = _SHIFRA_RE.search("227-5доп-291 книга")
    assert m.groups() == ("227", "5доп", "291")


@pytest.mark.parametrize("text", ["ДАХмО 227-1-261Справа", "ДАХмО 227-1-261справа про"])
def test_glued_word_is_not_a_case_key(_ws, text):
    """Номер, злитий зі словом назви, ключем не стає ні в `nysh case`, ні в резолвері."""
    from nyshporka.cases.register import RegisterError, parse_shifra
    from nyshporka.pagestore import resolve_case

    with pytest.raises(RegisterError, match="слово"):
        parse_shifra(text)
    with pytest.raises(ValueError):       # відмова, а не ключ `…/261sprava`
        resolve_case(text)


def test_glued_word_rule():
    from nyshporka.core.casekey import glued_word

    assert glued_word("261Справа") and glued_word("12bis")
    assert not glued_word("2а") and not glued_word("8433") and not glued_word("@fuzovka")
    assert not glued_word("pt1a") and not glued_word("7864_parish56_1846")


# ── один розбір назв Commons: паспорт `nysh get` і збирач реєстру опису ─────

_SPILNI = [
    "ДАХмО 227-2д-905 Объявления о торгах (1899).pdf",
    "ДАХмО 227-1-6563а Справи про щось.pdf",
    "ДАХмО 227-1d-356. 1851 рік. Метричні книги.pdf",
    "ДАХмО Ф.227, о.2, с.6026 Списки мешканців.pdf",
    "ДАХмО Ф. 227 О. 5доп С. 291 Статистичний опис.pdf",
    "1845 год. ДАХМО. Фонд 227, опись 6д, дело 34. Метрическая книга.pdf",
    "ДАХмО 227 1 6563 Метрична книга.pdf",
    "ДАХмО 227-01-0624. Родовід.pdf",
    "ДАХмО 227 -1-2621 Iliński.pdf",
    "ДАХмО 227-1-2640 Дзічковських.pdf",
    "ДАХмО фонд 227, опис 1, справа 54а. Метрична книга.pdf",
    "ДАХмО-227-1-253. Справа про призначення.pdf",
    # без шифри в обох
    "ДАХмО фонд 227 опис 1 том 1.pdf",
    "ДАХмО 227-1-261Справа про призначення.pdf",
    "ДАХмО 227 1858 1859 метрики.pdf",
]


@pytest.mark.parametrize("title", _SPILNI)
def test_get_and_registry_collector_agree(title):
    """🔴 Обидва шляхи дають ОДИН ключ: справа, яку `nysh get` назвав, у реєстрі
    опису стоїть під тією самою шифрою, і `cases take` її знаходить."""
    from nyshporka.core import casekey as ck
    from nyshporka.fonds.collect.commons import parse_shifra

    got = shifra_of_title(title)
    reg = parse_shifra(title, ("ДАХмО", "ДАХМО"), "227")
    k_get = ck.make(got["archive"], got["fond"], got["inv"], got["spr"]) if got else None
    k_reg = ck.make("DAHMO", "227", reg[0], reg[1] + reg[2]) if reg else None
    assert k_get == k_reg


def test_collector_keeps_fond_that_looks_like_a_year():
    """Збирач знає свій фонд: ЦДІАК ф.2081 — фонд, а не рік."""
    from nyshporka.fonds.collect.commons import parse_shifra

    assert parse_shifra("ЦДІАК 2081-1-5. Справа.pdf", ("ЦДІАК",), "2081") == ("1", "5", "")
    assert shifra_of_title("ЦДІАК 2081-1-5. Справа.pdf") == {}


def test_collector_reads_literal_opys():
    from nyshporka.fonds.collect.commons import parse_shifra

    codes = ("ДАХмО",)
    assert parse_shifra("ДАХмО 227-2д-905 X.pdf", codes, "227") == ("2д", "905", "")
    assert parse_shifra("ДАХмО 227-1d-356. X.pdf", codes, "227") == ("1д", "356", "")
    assert parse_shifra("ДАХмО Ф. 227 О. 5доп С. 291 X.pdf", codes, "227") == ("5доп", "291", "")
    assert parse_shifra("ДАХмО 227-2д-355a X.pdf", codes, "227") == ("2д", "355", "а")


# ── шифра для показу: кирилицею для кириличного архіву ──────────────────────

@pytest.mark.parametrize("args,want", [
    (("ДАХмО", "227", "5dop", "291"), "ДАХмО 227-5доп-291"),
    (("ДАХмО", "227", "2d", "355a"), "ДАХмО 227-2д-355а"),
    (("ДАХмО", "315", "1", "7029a"), "ДАХмО 315-1-7029а"),
    (("ДАВіО", "R-6129", "24", "5"), "ДАВіО Р-6129-24-5"),
    (("ДАХмО", "315", "1", "7049ч"), "ДАХмО 315-1-7049ч"),
    (("ДАОО", "37", "_", "1235"), "ДАОО 37-_-1235"),
    (("ANRM", "211", "", "@fuzovka"), "ANRM 211-@fuzovka"),
    (("ДАХмО", "211", "11", "@Razeni"), "ДАХмО 211-11-@Razeni"),
    (("LVVA", "1407", "1", "5a"), "LVVA 1407-1-5a"),           # латинський архів — як є
    (("ANRM", "211", "1d", "5"), "ANRM 211-1d-5"),
])
def test_show_shifra(args, want):
    from nyshporka.core.casekey import show_shifra

    assert show_shifra(*args) == want


@pytest.mark.parametrize("folder,key,shifra", [
    ("dahmo_227/op5доп-spr-291", "DAHMO/227/5dop/291", "ДАХмО 227-5доп-291"),
    ("dahmo_227/op2д-spr-355а", "DAHMO/227/2d/355a", "ДАХмО 227-2д-355а"),
    ("dahmo_315/op1-spr-7029a", "DAHMO/315/1/7029a", "ДАХмО 315-1-7029а"),
])
def test_library_shifra_is_shown_and_resolves_back(_ws, folder, key, shifra):
    """Бібліотека показує шифру кирилицею, і резолвер (а за ним сервер Супряги)
    розбирає її назад у той самий латинський ключ."""
    from PIL import Image

    from nyshporka import library as L
    from nyshporka.core.workspace import workspace
    from nyshporka.pagestore import resolve_case

    d = workspace().raw / folder
    d.mkdir(parents=True)
    Image.new("L", (20, 20)).save(d / "0001.jpg")
    entries = L.build_library()
    got = [(e.key, e.shifra) for e in entries]
    assert got == [(key, shifra)]
    L.write_library(entries)
    ref = resolve_case(shifra)
    assert (ref.key, ref.shifra) == (key, shifra)


def test_conflicts_index_meets_row_in_either_script(monkeypatch):
    """Розбіжність опису, записана `1d/355a`, видна рядку реєстру `1д/355а`."""
    from nyshporka.fonds import registry as F

    monkeypatch.setattr(F, "load_conflicts", lambda fid: [
        {"opys": "1д", "spr": "355а"}, {"opys": "1d", "spr": "355a"}, {"opys": "1", "spr": "355"}])
    idx = F.conflicts_index("DAHMO_227")
    assert idx[("1d", "355a")] == 2 and idx[("1", "355")] == 1
    row = {"opys": "1д", "spr": "355а", "spr_int": "355", "spr_letter": "а"}
    assert F.row_status(row, {}, idx)["conflicts"] == 2
