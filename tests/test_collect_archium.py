"""🏛 Збирач реєстру з переглядача архіву."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nyshporka.archives.pack import Site
from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.archium import FIELDS, ArchiumCollector
from nyshporka.fonds.collect.base import Target
from nyshporka.sources.archium import ArchiumSource
from nyshporka.sources.http import Fetcher

FIX = Path(__file__).parent / "fixtures" / "sources"


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def json(self) -> dict[str, object]:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        pass


class _Recorded:
    """Двійник із записаними відповідями; збіг за регексом.

    ⚠ Підрядок тут не годиться: `Page=1` збігається з `Page=10`, тож двійник
    віддавав би першу сторінку на кожен запит — нескінченний цикл, який виглядає
    як успішне збирання.
    """

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.seen: list[str] = []

    def get(self, url: str) -> _Resp:
        self.seen.append(url)
        for pat, body in self.pages.items():
            if re.search(pat, url):
                return _Resp(body)
        raise AssertionError(f"двійник не знає адреси: {url}")


@pytest.fixture
def collector() -> tuple[ArchiumCollector, _Recorded]:
    rec = _Recorded({
        r"/fonds/198/": (FIX / "archium_fond.html").read_text(encoding="utf-8"),
        r"/api/v1/inventories/\d+\?Limit=\d+&Page=1$":
            (FIX / "archium_inventory.json").read_text(encoding="utf-8"),
        # Сторінки за межами переліку сайт віддає порожніми — і збирач мусить
        # на цьому спинитись, а не ходити по колу.
        # ⚠ `[2-9]` тут не годиться — сторінок буває більше дев'яти, і на
        # десятій двійник знову не знав би адреси. Та сама пастка, що з `Page=1`.
        r"/api/v1/inventories/\d+\?Limit=\d+&Page=\d+": '{"Status":1,"View":""}',
    })
    # Майданчик задається явно: адреса кадрів береться з нього, а не з бази
    # мережевого клієнта, і саме це має перевірятись.
    site = Site(engine="archium", url="https://архів", source_id="archium-тест")
    src = ArchiumSource(site=site, repo="DAHMO",
                        fetcher=Fetcher(base="https://архів", delay=0.0, client=rec))
    return ArchiumCollector(source=src), rec


def test_the_columns_are_a_promise_not_a_detail() -> None:
    """🔴 Ці колонки читає злиття реєстру, яке живе в іншому репозиторії.
    Перейменувати одну означає зламати чужий конвеєр без жодного сигналу: файл
    на місці, рядки в ньому є, а колонка мовчки порожня."""
    assert FIELDS == ("opys", "spr_int", "spr_letter", "title", "year_from",
                      "year_to", "folios", "archium_file", "archium_url")


def test_a_case_number_is_read_from_how_the_site_writes_it() -> None:
    """🔴 Переглядач підписує номер словом: «Справа 1», а не «1».

    Заміряно на живому фонді: без зняття префікса збирач узяв 1525 рядків і не
    визнав ні одного справою. За числом отриманих рядків це виглядало б
    успіхом — і саме тому приймачем збирання є `quality`, а не кількість.
    """
    assert T.case_number("Справа 1") == (1, "")
    assert T.case_number("Спр. 24а") == (24, "а")
    assert T.case_number("вільний номер") is None


def test_collecting_writes_the_registry_and_the_sidecar(
        collector: tuple[ArchiumCollector, _Recorded], tmp_path: Path) -> None:
    coll, _ = collector
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path, fond_id="198")

    assert res.rows > 0
    assert res.out.name == "archium.tsv"
    fields, rows = T.read_tsv(res.out)
    assert tuple(fields) == FIELDS
    assert all(r["archium_url"].startswith("https://архів/file-viewer/") for r in rows)

    side = json.loads((tmp_path / "archium_fond.json").read_text(encoding="utf-8"))
    assert side["fond_id"] == "198"
    assert side["inventories"], "перелік описів не збережено — наступний запуск шукатиме його знову"


def test_quality_says_what_the_rows_actually_carry(
        collector: tuple[ArchiumCollector, _Recorded], tmp_path: Path) -> None:
    """Позиційний розбір таблиці опису вже одного разу віддав тисячі справ з
    однаковим заголовком і нулем аркушів, і за числом рядків це виглядало
    успіхом."""
    coll, _ = collector
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path, fond_id="198")
    assert set(res.quality) >= {"із заголовком", "з роками", "зі сканом"}
    assert res.quality["зі сканом"] == res.rows, "адреса кадрів — головне тут"


def test_without_the_internal_fond_number_the_plan_says_how_to_get_it() -> None:
    """🔴 Сайт адресує фонд власним номером, і офсетом він не рахується: крок
    пливе, бо номери йдуть за порядком опису з пропусками. Порахований офсет
    віддав би чужу справу з правдоподібним іменем теки."""
    plan = ArchiumCollector().plan(Target(repo="DAHMO", fond="230"))
    assert not plan.ready
    assert "fond_id" in plan.needs
    assert "198" in plan.why, "порада має показувати, як цей номер виглядає"


def test_a_dry_run_writes_nothing(
        collector: tuple[ArchiumCollector, _Recorded], tmp_path: Path) -> None:
    coll, _ = collector
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path,
                       fond_id="198", dry_run=True)
    assert res.rows > 0
    assert not list(tmp_path.iterdir()), "суха спроба лишила файли"
