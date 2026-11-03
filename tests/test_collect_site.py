"""🗂 Сайт архіву: збирач реєстру опису, злиття й канал `cases take`.

Без мережі: каталог обходу пишеться у тимчасовий простір так, як його лишає
`nysh crawl site-<архів>`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from nyshporka.fonds.collect.base import CollectError, Target
from nyshporka.fonds.collect.site import SiteCollector, split_years
from nyshporka.fonds.merge.run import merge_fond
from nyshporka.fonds.registry import row_status, site_online


def _case(fond: str, opys: str, spr: str, title: str = "", years: str = "",
          kind: str = "zip") -> dict[str, object]:
    page = f"https://archives.kh.gov.ua/{fond}-{opys}-{spr}"
    return {"fond": fond, "opys": opys, "sprava": spr, "title": title, "years": years,
            "page": page, "files": [{"url": page + "." + kind, "kind": kind, "label": ""}]}


CASES = [
    _case("40", "105", "224", "Метрична книга церков Охтирського повіту, 1850 рік", "1850"),
    _case("40", "105", "225", "Метрична книга, 1851–1852", "1851–1852", kind="pdf"),
    # друга копія тієї самої справи (ДАХеО: оригінал і «відновлена з фотокопій»)
    _case("40", "105", "225", "Метрична книга (відновлена)", "1851–1852", kind="pdf"),
    # 🔴 «12/1» — не справа 12
    _case("40", "105", "12/1", "Частина справи"),
    _case("40", "106", "3а", "Літерна справа"),
    # ДАОО пише літеру через дефіс
    _case("40", "106", "10-а", "Літерна через дефіс"),
    _case("41", "1", "1", "Чужий фонд"),
]


def _catalog(ws: Path, cases: list[dict[str, object]], repo: str = "DAHO") -> Path:
    p = ws / "data" / "raw" / f"{repo.lower()}_site" / "_crawl" / "cases.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"taken": "2026-11-03", "site": "x", "parser": "daho",
                             "pages": 1, "empty_pages": [], "failed_pages": [],
                             "cases": cases}, ensure_ascii=False), encoding="utf-8")
    return p


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_split_years() -> None:
    assert split_years("1851–1852") == ("1851", "1852")
    assert split_years("1850") == ("1850", "1850")
    assert split_years("") == ("", "")


def test_collect_rows_of_one_fond(tmp_path: Path) -> None:
    _catalog(tmp_path, CASES)
    res = SiteCollector(tmp_path).collect(Target(repo="DAHO", fond="40"),
                                          dest=tmp_path / "reg")
    rows = {(r["opys"], r["spr_int"], r["spr_letter"]): r for r in _tsv(res.out)}
    assert set(rows) == {("105", "224", ""), ("105", "225", ""), ("106", "3", "а"),
                         ("106", "10", "а")}
    r = rows[("105", "225", "")]
    assert (r["year_from"], r["year_to"]) == ("1851", "1852")
    assert (r["site_source"], r["site_ref"], r["site_kind"]) == ("site-daho", "40/105/225", "pdf")
    assert r["title"] == "Метрична книга, 1851–1852"          # перша копія, не друга
    blind = {b.kind: b.count for b in res.blind}
    assert blind == {"no_shifra": 1, "second_copy": 1}
    assert res.opys_seen == ("105", "106")


def test_one_opys_only(tmp_path: Path) -> None:
    _catalog(tmp_path, CASES)
    res = SiteCollector(tmp_path).collect(Target(repo="DAHO", fond="40", opys=("106",)),
                                          dest=tmp_path / "reg")
    assert [(r["opys"], r["spr_int"]) for r in _tsv(res.out)] == [("106", "3"), ("106", "10")]


def test_without_catalog_refuses_with_the_crawl_command(tmp_path: Path) -> None:
    """🔴 Порожній реєстр читався б як «на сайті справ фонду немає»."""
    c = SiteCollector(tmp_path)
    plan = c.plan(Target(repo="DAHO", fond="40"))
    assert not plan.ready and "nysh crawl site-daho" in plan.why
    with pytest.raises(CollectError, match="nysh crawl site-daho"):
        c.collect(Target(repo="DAHO", fond="40"), dest=tmp_path / "reg")


def test_archive_without_site_pages_is_not_ready(tmp_path: Path) -> None:
    plan = SiteCollector(tmp_path).plan(Target(repo="CDIAK", fond="224"))
    assert not plan.ready and "не описано" in plan.why


def test_fond_absent_from_the_site_is_an_error_not_an_empty_registry(tmp_path: Path) -> None:
    _catalog(tmp_path, CASES)
    with pytest.raises(CollectError, match="фонду 99 на сторінках сайту"):
        SiteCollector(tmp_path).collect(Target(repo="DAHO", fond="99"),
                                        dest=tmp_path / "reg")


def test_merge_makes_the_site_case_a_free_channel(tmp_path: Path) -> None:
    """Справа лише на сайті архіву — «взяти самому», а не «замовлення»."""
    _catalog(tmp_path, CASES)
    reg = tmp_path / "reg"
    SiteCollector(tmp_path).collect(Target(repo="DAHO", fond="40"), dest=reg)
    out = tmp_path / "f40.tsv"
    res = merge_fond(Target(repo="DAHO", fond="40"), dest=reg, out=out)
    rows = {(r["opys"], r["spr_int"]): r for r in _tsv(out)}
    r = rows[("105", "224")]
    assert r["site_ref"] == "40/105/224" and r["title_src"] == "site"
    assert site_online(r)
    assert row_status(r, {}, {})["disk_state"] == "todo"
    assert res.channels["site"] == 4 and res.channels["order"] == 0


def test_site_without_source_is_not_a_channel() -> None:
    assert not site_online({"site_ref": "40/105/224", "site_source": ""})
    assert row_status({"opys": "1", "spr_int": "1", "site_ref": "1/1/1"},
                      {}, {})["disk_state"] == "order"


def test_take_plan_uses_the_site_when_nothing_faster(tmp_path: Path) -> None:
    from nyshporka.cases import take as T

    row = {"site_ref": "40/105/224", "site_source": "site-daho", "title": "X"}
    p = T._plan_from("DAHO", "40", "105", "224", "", row)
    assert (p["channel"], p["ref"], p["site_source"]) == ("site", "40/105/224", "site-daho")
    assert "сайт архіву" in p["why"]
    # Commons там, де є обидва, лишається першим.
    both = T._plan_from("DAHO", "40", "105", "224", "", {**row, "commons_title": "X.pdf"})
    assert both["channel"] == "commons" and both["site_source"] == ""
