"""🦆 Зведений покажчик: перелік справ фонду.

Цінний переліком, а не заголовками: бачить усі описи фонду незалежно від того,
чи їх оцифровано. Через це його помилки коштують інакше — не «трохи не та
назва», а фантомна справа в черзі, за якою замовляють документ в архіві.
"""
from __future__ import annotations

import json
from pathlib import Path

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Target
from nyshporka.fonds.collect.duck import (
    FIELDS,
    PAGE_SIZE,
    DuckCollector,
    file_page,
    is_void,
)

FIX = Path(__file__).parent / "fixtures" / "registry"


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник покажчика. Сторінка бере участь у збігу — інакше двійник
    відповідав би нульовою на кожен запит, і обхід ходив би по колу."""

    def __init__(self, fond: dict[str, object], pages: dict[int, dict[str, object]]):
        self.fond = fond
        self.pages = pages
        self.seen: list[str] = []

    def get(self, url: str) -> _Resp:
        self.seen.append(url)
        if "?page=" in url:
            page = int(url.rsplit("page=", 1)[1])
            return _Resp(json.dumps(self.pages.get(page, {"files": []})))
        return _Resp(json.dumps(self.fond))


def _opys(files: list[dict[str, object]], copies: list[dict[str, object]] | None = None):
    return {"code": "17", "files": files, "online_copies": copies or []}


def _coll(api: _Api) -> DuckCollector:
    from nyshporka.sources.http import Fetcher

    return DuckCollector(fetcher=Fetcher(base="https://п", delay=0.0, client=api))


def test_the_live_shape_of_the_service_is_what_we_parse(tmp_path: Path) -> None:
    """Фікстура — жива відповідь сервісу, скорочена до шести справ."""
    live = json.loads((FIX / "duck_opys.json").read_text(encoding="utf-8"))
    api = _Api({"inventories": [{"code": "17"}]}, {0: live})
    res = _coll(api).collect(Target(repo="DAVIO", fond="904", opys=("17",)),
                             dest=tmp_path)

    assert res.rows == len(live["files"])
    _, rows = T.read_tsv(res.out)
    assert all(r["title"] for r in rows), "заголовки не прочитались"
    assert all(r["year_from"] for r in rows), "роки не прочитались"


def test_empty_positions_go_to_their_own_file_not_into_the_registry(
        tmp_path: Path) -> None:
    """🔴 «Вільний номер» і «Справа вибула» приходять рядками нарівні зі
    справами. Пущені в реєстр, вони стають фантомами в черзі завантаження — і
    за ними замовляють в архіві документ, якого не існує."""
    api = _Api({"inventories": [{"code": "17"}]}, {0: _opys([
        {"code": "1", "title": "Метрична книга", "years": [{"start_year": 1800}]},
        {"code": "2", "title": "вільний номер", "years": [{}]},
        {"code": "3", "title": "Справа вибула", "years": [{}]},
    ])})
    res = _coll(api).collect(Target(repo="DAVIO", fond="904", opys=("17",)),
                             dest=tmp_path)

    assert res.rows == 1
    assert any(b.kind == "void" and b.count == 2 for b in res.blind)
    _, voids = T.read_tsv(tmp_path / "duck_void.tsv")
    assert len(voids) == 2 and all(v["duck_note"] for v in voids)


def test_a_copy_of_the_whole_inventory_is_not_a_copy_of_each_case(
        tmp_path: Path) -> None:
    """🔴 Копії з порожнім `file_id` описують увесь опис (плівку цілком).
    Приписані кожній справі, вони зробили б увесь опис «оцифрованим»."""
    api = _Api({"inventories": [{"code": "17"}]}, {0: _opys(
        [{"id": "aaa", "code": "1", "title": "Книга", "years": [{"start_year": 1800}]},
         {"id": "bbb", "code": "2", "title": "Книга", "years": [{"start_year": 1801}]}],
        [{"file_id": None, "url": "https://плівка/цілком"},
         {"file_id": "bbb", "url": "https://копія/другої"}])})
    res = _coll(api).collect(Target(repo="DAVIO", fond="904", opys=("17",)),
                             dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    by_id = {r["duck_id"]: r for r in rows}
    assert by_id["aaa"]["duck_copy_url"] == "", "копія опису приписалась справі"
    assert by_id["bbb"]["duck_copy_url"] == "https://копія/другої"


def test_the_next_page_is_asked_only_after_a_full_one(tmp_path: Path) -> None:
    """Дока прямо каже: просити наступну сторінку, лише отримавши повну.
    Інакше обхід або спиняється зарано, або ходить зайвий раз по кожному
    описові — а запитів тут п'ять на десять секунд."""
    full = _opys([{"code": str(i), "title": "Книга", "years": [{"start_year": 1800}]}
                  for i in range(1, PAGE_SIZE + 1)])
    api = _Api({"inventories": [{"code": "17"}]}, {0: full, 1: _opys([])})
    res = _coll(api).collect(Target(repo="DAVIO", fond="904", opys=("17",)),
                             dest=tmp_path)

    assert res.rows == PAGE_SIZE
    assert sum(1 for u in api.seen if "page=" in u) == 2


def test_a_non_numeric_inventory_is_collected_and_flagged(tmp_path: Path) -> None:
    """⚠ Описи бувають нечисловими («Л2», «ОРП41») — на `int()` це клало всю
    перезбірку, тобто одна дивна позиція гасила решту фонду."""
    api = _Api({"inventories": [{"code": "Л2"}]}, {0: _opys(
        [{"code": "5", "title": "Книга", "years": [{"start_year": 1799}]}])})
    res = _coll(api).collect(Target(repo="DAVIO", fond="904", opys=("Л2",)),
                             dest=tmp_path)

    assert res.rows == 1
    assert any(b.kind == "non_numeric_opys" for b in res.blind)


def test_the_link_points_at_the_index_page_not_the_copy() -> None:
    """Цього просить дока сервісу, і причина практична: адреси копій
    переїжджають і ламаються без попередження, а сторінка покажчика лишається."""
    url = file_page("ДАВіО", "904", "17", "24")
    assert url.startswith("https://inspector.duckarchive.com/archives/")
    assert url.endswith("/904/17/24")


def test_void_marks_are_recognised() -> None:
    assert is_void("вільний номер") and is_void("Справа вибула")
    assert not is_void("Метрична книга")


def test_the_columns_are_a_promise() -> None:
    assert FIELDS[:3] == ("opys", "spr_int", "spr_letter")
    assert "duck_url" in FIELDS and "duck_online" in FIELDS
