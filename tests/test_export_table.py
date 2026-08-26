"""📤 Виписка справи таблицею — чотири вигляди й два формати.

Перевіряється не «функція повертає рядки», а те, чим таблиця може збрехати
генеалогові:

* підсумок книги, порахований нами замість прочитаного (найдорожча брехня: сума
  по всіх лічильниках рахує власний `total` книги вдруге);
* зникле посилання на аркуш — без нього виписку не перевірити ніяк;
* з'їдений Екселем текст: провідний «=» стає формулою, керівний символ ламає
  весь файл, кирилиця без BOM показується «крякозябрами»;
* «м10» перед «м9» — і таблиця перестає горнутись, як сама книга.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka import tabular
from nyshporka.pagestore.models import CaseFile, PageNote, Record, RecordPerson


def _person(role: str, name: str, **kw: object) -> RecordPerson:
    return RecordPerson(role=role, name=name, **kw)  # type: ignore[arg-type]


@pytest.fixture
def case() -> CaseFile:
    """Мініатюра справжньої метрики: народження, смерть, підсумок, сторінка."""
    return CaseFile(
        key="DAVO/904/24", repo="DAVO", fond="904", spr="24",
        shifra="ДАВО 904-24-24",
        pages={"0004.JPG": PageNote(
            scan="0004.JPG", page_type="birth", status="full",
            surnames=["Дзюравскій"], places=["М. Мясковка"], years=[1865])},
        records=[
            Record(rtype="birth", scans=["0004.JPG"], row="м10", sheet="2",
                   date="1865-01-04", date2="1865-01-10",
                   places=["М. Мясковка"], quote="родился Климентъ",
                   persons=[
                       _person("child", "Климентъ", given="Климентъ", sex="m"),
                       _person("father", "Матѳѣй Григоріевъ Дзюравскій",
                               surname="Дзюравскій", estate="однодворецъ"),
                       _person("mother", "Софія Іаковлева"),
                       # Двоє хрещених — саме та ситуація, заради якої ролі
                       # склеюються в одну колонку, а не розсуваються в дві.
                       _person("godfather", "Ефремъ Михайловъ"),
                       _person("godfather", "[нрзб]"),
                   ]),
            Record(rtype="birth", scans=["0004.JPG"], row="м9", sheet="2",
                   date="1865-01-02",
                   persons=[_person("child", "Іоаннъ")]),
            Record(rtype="death", scans=["0005.JPG"], row="ж3", sheet="3",
                   date="1865-02-11", cause="отъ старости",
                   persons=[_person("deceased", "Анна Максимова", age="80")]),
            # 🔴 Підсумок несе і власні лічильники книги, і власне «разом» —
            # рівно та комбінація, на якій обчислена сума рахує двічі.
            Record(rtype="tally", scans=["0005.JPG"], row="tally-1865-01",
                   date="1865-01", counts={"m": 2, "f": 1, "total": 3}),
        ])


# ── вигляд «акти» ────────────────────────────────────────────────────────────
def test_acts_put_each_role_in_its_own_column(case: CaseFile) -> None:
    columns, rows = tabular.build(case, "acts")
    assert "father" in columns and "godfather" in columns
    born = next(r for r in rows if r["row"] == "м10")
    assert born["father"] == "Матѳѣй Григоріевъ Дзюравскій"
    assert born["mother"] == "Софія Іаковлева"


def test_several_bearers_of_one_role_share_a_column(case: CaseFile) -> None:
    """Двоє хрещених — один стовпчик, бо «свідок 1/2» розсунули б схему."""
    _, rows = tabular.build(case, "acts")
    born = next(r for r in rows if r["row"] == "м10")
    assert born["godfather"] == "Ефремъ Михайловъ; [нрзб]"


def test_roles_absent_from_the_case_do_not_become_columns(case: CaseFile) -> None:
    """У книзі народжень порожня «наречена» лише заважає фільтрувати."""
    columns, _ = tabular.build(case, "acts")
    assert "bride" not in columns and "sponsor" not in columns


def test_tally_never_travels_among_the_acts(case: CaseFile) -> None:
    """🔴 Підсумок — чексум повноти, а не подія: серед актів він їх підробляє."""
    _, acts = tabular.build(case, "acts")
    _, people = tabular.build(case, "records")
    assert all(r["type"] != "tally" for r in acts)
    assert all(r["type"] != "tally" for r in people)
    assert len(acts) == 3


@pytest.mark.parametrize("view", tabular.VIEWS)
def test_every_view_carries_the_scan(view: str, case: CaseFile) -> None:
    """🔴 Виписка без посилання на аркуш — переказ, а не джерело."""
    columns, rows = tabular.build(case, view)
    key = "scan" if view == "pages" else "scans"
    assert key in columns
    assert all(r[key] for r in rows), f"вигляд «{view}» загубив аркуш"


def test_numbering_follows_the_book_not_the_alphabet(case: CaseFile) -> None:
    """«м9» стоїть перед «м10»: лічильник книги — число з літерою, не рядок."""
    _, rows = tabular.build(case, "acts")
    same_scan = [r["row"] for r in rows if r["scans"] == "0004.JPG"]
    assert same_scan == ["м9", "м10"]


def test_year_comes_from_the_act_itself(case: CaseFile) -> None:
    _, rows = tabular.build(case, "acts")
    assert {r["year"] for r in rows} == {"1865"}


def test_year_stays_empty_when_the_act_does_not_give_it() -> None:
    """🔴 Рік не добудовується з сусіднього аркуша: у справі буває два примірники."""
    cf = CaseFile(key="X/1/1", repo="X", fond="1", spr="1",
                  records=[Record(rtype="birth", scans=["0001.JPG"],
                                  date="18??-02-05", row="1")])
    _, rows = tabular.build(cf, "acts")
    assert rows[0]["year"] == ""


def test_the_death_cause_survives_into_the_table(case: CaseFile) -> None:
    """Найцінніша графа книги смертей: епідемії видно тільки по ній."""
    _, rows = tabular.build(case, "acts")
    died = next(r for r in rows if r["type"] == "death")
    assert died["cause"] == "отъ старости"


# ── вигляд «учасники» ────────────────────────────────────────────────────────
def test_participants_view_breaks_the_person_into_fields(case: CaseFile) -> None:
    _, rows = tabular.build(case, "records")
    father = next(r for r in rows if r["role"] == "father")
    assert father["surname"] == "Дзюравскій"
    assert father["estate"] == "однодворецъ"
    assert father["scans"] == "0004.JPG"


def test_an_act_without_parsed_participants_still_appears() -> None:
    """Інакше сторінка виглядає невичитаною там, де її читали."""
    cf = CaseFile(key="X/1/1", repo="X", fond="1", spr="1",
                  records=[Record(rtype="birth", scans=["0001.JPG"], row="1")])
    _, rows = tabular.build(cf, "records")
    assert len(rows) == 1 and rows[0]["role"] == ""


# ── вигляд «підсумки» ────────────────────────────────────────────────────────
def test_the_tally_is_never_recomputed(case: CaseFile) -> None:
    """🔴 Головне: сума по лічильниках порахувала б власний «разом» книги вдруге.

    У цій справі підсумок несе m=2, f=1 і total=3. Обчислене «разом» дало б 6 —
    число, якого в книзі немає, але яке виглядає прочитаним.
    """
    columns, rows = tabular.build(case, "tally")
    assert "total" not in columns, "обчислений підсумок повернувся в таблицю"
    assert rows[0]["counts.m"] == "2"
    assert rows[0]["counts.total"] == "3"


def test_unknown_counters_keep_the_name_the_book_gave_them() -> None:
    """Перелік лічильників відкритий: вигадана назва графи гірша за ключ."""
    assert tabular.label_for("counts.m") == "чоловіча"
    assert tabular.label_for("counts.presoedineno_zh") == "presoedineno_zh"


# ── підписи колонок ──────────────────────────────────────────────────────────
def test_the_same_key_is_labelled_by_what_it_means_here() -> None:
    """`places` в акті — місця акту; на сторінці — усе, що на аркуші."""
    assert tabular.label_for("places") == "місця акту"
    assert tabular.label_for("places", "pages") == "місця"


# ── CSV ──────────────────────────────────────────────────────────────────────
def test_csv_starts_with_a_bom_so_excel_shows_cyrillic(
        case: CaseFile, tmp_path: Path) -> None:
    """🔴 Без BOM виписка відкривається «крякозябрами» — і це читають як зіпсовані дані."""
    dest = tmp_path / "acts.csv"
    columns, rows = tabular.build(case, "acts")
    tabular.write_delimited(dest, columns, rows, view="acts")
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")

    text = dest.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("ключ запису,тип,рік")
    assert "[нрзб]" in text


def test_raw_headers_keep_the_machine_keys(case: CaseFile, tmp_path: Path) -> None:
    dest = tmp_path / "acts.tsv"
    columns, rows = tabular.build(case, "acts")
    tabular.write_delimited(dest, columns, rows, sep="\t", human=False)
    head = dest.read_text(encoding="utf-8-sig").splitlines()[0]
    assert head.split("\t")[:3] == ["rid", "type", "year"]


# ── XLSX ─────────────────────────────────────────────────────────────────────
openpyxl = pytest.importorskip("openpyxl", reason="гілка xlsx без openpyxl")


def test_xlsx_lays_the_views_out_as_sheets(case: CaseFile, tmp_path: Path) -> None:
    dest = tmp_path / "case.xlsx"
    sheets = [(v, *tabular.build(case, v)) for v in tabular.VIEWS]
    report = tabular.write_xlsx(dest, sheets)

    book = openpyxl.load_workbook(dest)
    assert book.sheetnames == ["Акти", "Учасники", "Сторінки", "Підсумки"]
    assert report["rows"] == sum(len(r) for _, _, r in sheets)
    acts = book["Акти"]
    # Закріплена шапка й автофільтр — те, заради чого xlsx і береться замість CSV.
    assert acts.freeze_panes == "A2"
    assert acts.auto_filter.ref is not None


def test_a_leading_equals_sign_stays_text_not_a_formula(tmp_path: Path) -> None:
    """🔴 Інакше прочитане з аркуша перетворюється на #NAME? і зникає з таблиці."""
    dest = tmp_path / "eq.xlsx"
    rows = [{"scans": "0001.JPG", "name": "=Іоаннъ", "note": "-Анна"}]
    tabular.write_xlsx(dest, [("acts", ["scans", "name", "note"], rows)])

    sheet = openpyxl.load_workbook(dest)["Акти"]
    assert sheet["B2"].value == "=Іоаннъ"
    assert sheet["B2"].data_type == "s"
    assert sheet["C2"].data_type == "s"


def test_control_characters_are_reported_not_swallowed(tmp_path: Path) -> None:
    """Керівний символ ламає файл ЦІЛКОМ, тож його прибирають — але не мовчки."""
    dest = tmp_path / "ctl.xlsx"
    rows = [{"scans": "0001.JPG", "name": "Іоан\x07нъ"}]
    report = tabular.write_xlsx(dest, [("acts", ["scans", "name"], rows)])

    assert report["cleaned"] == 1
    assert openpyxl.load_workbook(dest)["Акти"]["B2"].value == "Іоаннъ"


def test_a_cell_over_the_format_ceiling_is_cut_and_counted(tmp_path: Path) -> None:
    dest = tmp_path / "long.xlsx"
    rows = [{"scans": "0001.JPG", "quote": "я" * 40_000}]
    report = tabular.write_xlsx(dest, [("acts", ["scans", "quote"], rows)])

    assert report["truncated"] == 1
    assert len(openpyxl.load_workbook(dest)["Акти"]["B2"].value) == 32_767
