"""🦆 Копії окремих справ: плівка FS, якої не бачить перелік опису."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from nyshporka.fonds.collect import duck_copies as DC
from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Target
from nyshporka.fonds.collect.duck import FIELDS
from nyshporka.fonds.collect.duck_copies import DuckCopiesCollector, choose
from nyshporka.fonds.merge.sources import blank_row
from nyshporka.fonds.merge.titles import fuse_fs
from nyshporka.sources.base import SourceError

FS = "https://www.familysearch.org/en/records/images/search-results?imageGroupNumbers="
TARGET = Target(repo="DAHMO", fond="315")


@dataclass
class _Hit:
    shifra: str


class _Src:
    """Двійник покажчика: `online` — справи, що мають копію; `cut` — обрізана видача."""

    def __init__(self, copies: dict[str, list[dict[str, str]]], *,
                 online: tuple[str, ...] | None = None, cut: tuple[str, ...] = ()) -> None:
        self.copies, self.online, self.cut = copies, online, cut
        self.asked: list[str] = []
        self.searched = 0

    def find_files_split(self, **kw: object) -> tuple[list[_Hit], tuple[str, ...]]:
        self.searched += 1
        names = self.copies if self.online is None else self.online
        return [_Hit(f"ДАХмО-315-{kw['inventory']}-{n}") for n in names], self.cut

    def copies_of(self, arch: str, fond: str, opys: str, spr: str) -> list[dict[str, str]]:
        self.asked.append(spr)
        if spr not in self.copies:
            raise SourceError("немає")
        return self.copies[spr]


def _duck(dest: Path, *sprs: str, opys: str = "1") -> None:
    rows = [{"opys": opys, "spr_int": s.rstrip("а"), "spr_letter": "а" if s.endswith("а") else "",
             "duck_url": f"https://i/archives/ДАХмО/315/{opys}/{s}"} for s in sprs]
    T.write_tsv(dest / "duck.tsv", FIELDS, rows)


def _coll(src: _Src) -> DuckCopiesCollector:
    c = DuckCopiesCollector(source=src)
    return c


def test_film_of_a_case_comes_from_its_card(tmp_path: Path) -> None:
    """🔴 Живий приклад: 315-1-609 лежить на плівці 118772438, а перелік опису цього
    не каже. `file_id` у копії є лише в картці."""
    _duck(tmp_path, "609")
    res = _coll(_Src({"609": [{"url": FS + "118772438", "availability": "PUBLIC"}]})).collect(
        TARGET, dest=tmp_path)
    rows = T.read_tsv(res.out)[1]
    assert rows[0]["fs_dgs"] == "118772438"
    assert res.quality["з плівкою FS"] == 1


def test_case_with_a_known_film_costs_no_request(tmp_path: Path) -> None:
    """Картка дорога: справа, плівку якої вже знає `fs.tsv`, її не коштує."""
    _duck(tmp_path, "1", "2")
    T.write_tsv(tmp_path / "fs.tsv", ("opys", "spr", "dgs"),
                [{"opys": "1", "spr": "1", "dgs": "555"}])
    src = _Src({"1": [], "2": []})
    _coll(src).collect(TARGET, dest=tmp_path)
    assert src.asked == ["2"]


def test_search_without_a_case_means_no_card(tmp_path: Path) -> None:
    """Пошук `is_online` звужує обхід: справа поза видачею картки не коштує, а в
    файлі лишається як перевірена — наступний запуск її не питає."""
    _duck(tmp_path, "1", "2")
    src = _Src({"1": [], "2": []}, online=("1",))
    res = _coll(src).collect(TARGET, dest=tmp_path)
    assert src.asked == ["1"]
    assert {r["spr_int"]: r["checked"] != "" for r in T.read_tsv(res.out)[1]} == {"1": True, "2": True}


def test_truncated_search_proves_nothing(tmp_path: Path) -> None:
    """🔴 Стеля видачі — 50. Обрізана видача не дає права на «копії немає»."""
    _duck(tmp_path, "1", "2")
    src = _Src({"1": [], "2": []}, online=("1",), cut=("1800–1850",))
    _coll(src).collect(TARGET, dest=tmp_path)
    assert sorted(src.asked) == ["1", "2"]


def test_second_run_does_not_ask_again_and_refresh_does(tmp_path: Path) -> None:
    _duck(tmp_path, "1")
    src = _Src({"1": [{"url": FS + "7", "availability": "PUBLIC"}]})
    _coll(src).collect(TARGET, dest=tmp_path)
    _coll(src).collect(TARGET, dest=tmp_path)
    assert src.asked == ["1"]
    _coll(src).collect(TARGET, dest=tmp_path, refresh=True)
    assert src.asked == ["1", "1"]


def test_card_ceiling_is_named_and_next_run_continues(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(DC, "MAX_CARDS", 2)
    _duck(tmp_path, "1", "2", "3")
    src = _Src({"1": [], "2": [], "3": []})
    res = _coll(src).collect(TARGET, dest=tmp_path)
    assert res.rows == 2
    assert [(b.kind, b.count) for b in res.blind] == [("cards_left", 1)]
    assert _coll(src).collect(TARGET, dest=tmp_path).rows == 3


def test_failed_card_is_not_written_as_checked(tmp_path: Path) -> None:
    """Збій картки — не «копії немає»: такий запис закрив би справу назавжди."""
    _duck(tmp_path, "1", "2")
    src = _Src({"2": []}, online=("1", "2"))
    res = _coll(src).collect(TARGET, dest=tmp_path)
    assert [r["spr_int"] for r in T.read_tsv(res.out)[1]] == ["2"]
    assert [b.kind for b in res.blind] == ["cards_failed"]


def test_case_number_with_a_dash_reaches_the_card(tmp_path: Path) -> None:
    """Група справ: номер береться з адреси покажчика, а не склеюється з колонок."""
    T.write_tsv(tmp_path / "duck.tsv", FIELDS, [
        {"opys": "1", "spr_int": "29", "spr_to": "35",
         "duck_url": "https://i/archives/%D0%94/315/1/29-35"}])
    src = _Src({"29-35": []}, online=("29-35",))
    _coll(src).collect(TARGET, dest=tmp_path)
    assert src.asked == ["29-35"]


def test_without_the_case_list_there_is_nothing_to_ask(tmp_path: Path) -> None:
    res = _coll(_Src({})).collect(TARGET, dest=tmp_path)
    assert res.rows == 0 and res.blind[0].kind == "no_duck"


@pytest.mark.parametrize(("copies", "dgs", "url", "more"), [
    ([{"url": "https://uk.wikisource.org/x", "availability": "PUBLIC"}], "", "https://uk.wikisource.org/x", ""),
    ([{"url": FS + "5", "availability": "PRIVATE"}], "", "", ""),
    ([{"url": FS + "5", "availability": ""}], "5", FS + "5", ""),
    ([{"url": "https://w/x", "availability": "PUBLIC"}, {"url": FS + "5", "availability": "PUBLIC"},
      {"url": FS + "6", "availability": "PUBLIC"}], "5", FS + "5", "6"),
    ([{"url": "https://www.familysearch.org/ark:/61903/3:1:X?i=1&cat=1938521", "availability": "PUBLIC"}],
     "", "https://www.familysearch.org/ark:/61903/3:1:X?i=1&cat=1938521", ""),
])
def test_choose(copies, dgs, url, more) -> None:
    got = choose(copies)
    assert (got["fs_dgs"], got["duck_copy_url"], got["fs_more"]) == (dgs, url, more)


def test_merge_fills_only_empty_and_only_known_cases() -> None:
    a, b, c = ("1", "1", ""), ("1", "2", ""), ("1", "3", "")
    reg = {a: blank_row(a), b: blank_row(b)}
    reg[b]["fs_dgs"] = "111"
    fuse_fs(reg, [], [], [
        {"opys": "1", "spr_int": "1", "fs_dgs": "7", "fs_url": FS + "7", "duck_copy_url": FS + "7"},
        {"opys": "1", "spr_int": "2", "fs_dgs": "8", "fs_url": FS + "8", "duck_copy_url": FS + "8"},
        {"opys": "1", "spr_int": "3", "fs_dgs": "9", "fs_url": FS + "9", "duck_copy_url": FS + "9"},
    ])
    assert (reg[a]["fs_dgs"], reg[a]["fs_url"], reg[a]["duck_online"]) == ("7", FS + "7", "1")
    assert reg[b]["fs_dgs"] == "111", "сильніше джерело не перекривається"
    assert c not in reg, "копія не заводить справу, якої немає в переліку"
