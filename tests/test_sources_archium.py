"""🏛 ARCHIUM: розбір каталогу й порядок кадрів — на ЗАПИСАНИХ відповідях.

🔴 Чому не живі запити. Тест мережевого джерела, що ходить у мережу, перевіряє
чужий сервер, а не наш розбір: він червонітиме через профілактику архіву й
зеленітиме через те, що розмітка ще не змінилась. Ні те, ні те не про наш код.
Фікстури тут — справжні відповіді сайту, зняті один раз.

⚠ Зворотний бік чесний: коли сайт перебудують, ці тести лишаться зеленими, а
джерело зламається. Ловить це не тест, а користувач; тому фікстури й називаються
за датою зняття в git-історії, і перезнімати їх треба свідомо.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources import archium as A
from nyshporka.sources.base import SourceError

FIX = Path(__file__).resolve().parent / "fixtures" / "sources"


@pytest.fixture(scope="module")
def fond_html() -> str:
    return (FIX / "archium_fond.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def inventory_view() -> str:
    """`View` із конверта `{"Status":1,"View":"<html>"}` — API віддає HTML."""
    return json.loads((FIX / "archium_inventory.json").read_text(encoding="utf-8"))["View"]


@pytest.fixture(scope="module")
def viewer_html() -> str:
    return (FIX / "archium_viewer.html").read_text(encoding="utf-8")


def test_fond_page_gives_inventories(fond_html: str) -> None:
    title, invs = A.parse_inventories(fond_html)
    assert "Церкви Подільської" in title
    assert [n.ref for n in invs] == ["inv:11035", "inv:11046"]
    # Число справ у описі — це відповідь «чи варто сюди йти», і воно мусить
    # вижити розбір: `2 036` з пробілом-роздільником інакше стало б `2`.
    assert invs[0].frames == 2036
    assert "1795-1921" in invs[0].label


def test_inventory_gives_cases_with_sheet_counts(inventory_view: str) -> None:
    cases = A.parse_cases(inventory_view)
    assert len(cases) == 25
    first = cases[0]
    assert first.file_id == "5301"
    assert first.number == "Справа 1"
    assert first.date == "1881"
    assert first.sheets == 45
    assert "Авратин" in first.description


def test_pagination_is_read_from_the_envelope(inventory_view: str) -> None:
    """Опис на 2036 справ не влазить в одну сторінку — і це видно з конверта."""
    assert A.last_page(inventory_view) == 82


def test_page_order_comes_from_alt_not_from_image_ids(viewer_html: str) -> None:
    """🔴 Id кадрів у переглядачі ПЕРЕМІШАНІ — порядок несе `alt`.

    Взяти кадри в порядку появи в документі (або за зростанням id) означає
    отримати справу, зшиту навмання. Виявиться це аж на читанні, коли записи
    перестануть сходитись із датами, — тобто після годин роботи.
    """
    pages = A.viewer_pages(viewer_html)
    assert len(pages) == 47
    assert [p for _, p in pages] == list(range(1, 48)), "сторінки не 1..N"
    ids = [i for i, _ in pages]
    assert ids != sorted(ids), (
        "id кадрів виявились упорядкованими — фікстура більше не показує тієї "
        "пастки, заради якої існує цей розбір")


def test_image_url_pads_the_id_into_a_shard(viewer_html: str) -> None:
    """Кадри розкладені по теках за трьома першими цифрами доповненого id."""
    assert A.image_url(13943).endswith("/static/files/013/013943.jpg")
    assert A.image_url(5) .endswith("/static/files/000/000005.jpg")


def test_search_without_catalog_refuses_instead_of_returning_zero(tmp_path: Path) -> None:
    """🔴 Головне в цьому джерелі.

    Вбудований пошук сайту індексує лише назви фондів і описів — не заголовки
    справ. Тому без зібраного каталогу шукати нема де, і мовчазний нуль читався
    б як «у цьому архіві такого немає»: висновок, що закриває напрям пошуку й
    коштує місяців. Ціна правильної поведінки — одне речення у відповіді.
    """
    src = A.ArchiumSource(workspace=tmp_path)
    with pytest.raises(SourceError, match="каталог"):
        src.search("Борсуківці")


def test_search_over_the_crawled_catalog(tmp_path: Path) -> None:
    cat = tmp_path / A.ArchiumSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    cat.write_text(
        "fond_no\tfond_title\tinv_label\tfile_id\tcase_no\tdate\tsheets\tdescription\n"
        "18\tЦеркви\tОпис 1\t5301\tСправа 1\t1881\t45\tЦерква, с. Авратин\n"
        "18\tЦеркви\tОпис 1\t5303\tСправа 3\t1892\t68\tЦерква, м-ко Аннопіль\n",
        encoding="utf-8")
    src = A.ArchiumSource(workspace=tmp_path)
    hits = src.search("авратин")
    assert [h.ref for h in hits] == ["file:5301"]
    assert hits[0].frames == 45
    assert hits[0].acquirable


def test_search_ignores_apostrophe_shape(tmp_path: Path) -> None:
    """В українських заголовках апостроф пишуть трьома різними символами.

    Прямий збіг рядків тут дав би нуль на назві, яка в каталозі є, — і це знову
    був би нуль, що бреше.
    """
    cat = tmp_path / A.ArchiumSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    cat.write_text("file_id\tdescription\n7\tМ’ястківка, метрична книга\n",
                   encoding="utf-8")
    src = A.ArchiumSource(workspace=tmp_path)
    assert src.search("М'ястківка")
    assert src.search("М’ястківка")


def test_fetch_refuses_a_non_case_ref(tmp_path: Path) -> None:
    src = A.ArchiumSource(workspace=tmp_path)
    with pytest.raises(SourceError, match="справу"):
        src.fetch("fond:13630", tmp_path / "out")


# ── обхід каталогу ───────────────────────────────────────────────────────────

class _Recorded:
    """Клієнт із записаними відповідями. Мережі тут немає й бути не має."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str) -> Any:
        self.asked.append(url)
        for pattern, body in self.pages.items():
            # 🔴 Регулярка, а не підрядок. Підрядок «Page=1» збігається і з
            # «Page=10», і з «Page=19» — фікстура віддавалась одинадцять разів,
            # і тест бачив 550 справ там, де їх 50. Фальшивий сервер, що
            # відповідає не на те, про що спитали, перевіряє не той код.
            if re.search(pattern, url):
                return _Resp(body)
        raise AssertionError(f"тест не готував відповіді на {url}")


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def recorded(fond_html: str) -> _Recorded:
    fond_group = (
        '<table class="fond-groups"><tbody><tr>'
        '<td>18</td><td><a href="/fonds/13630/">Церкви</a></td>'
        '<td>1795-1927</td><td>3160</td></tr></tbody></table>')
    inv = (FIX / "archium_inventory.json").read_text(encoding="utf-8")
    # Другу сторінку опису підміняємо порожньою: обхід має спинитись, а не
    # молотити 82 сторінки, яких у фікстурі немає.
    empty = json.dumps({"Status": 1, "View": ""})
    return _Recorded({
        "fond-groups": json.dumps({"Status": 1, "View": fond_group}),
        r"/fonds/13630/": fond_html,
        r"inventories/\d+\?Limit=\d+&Page=1(?!\d)": inv,
        r"inventories": empty,
    })


def test_crawl_writes_a_searchable_catalog(tmp_path: Path, recorded: _Recorded) -> None:
    """Обхід — єдиний спосіб зробити пошук у цьому архіві можливим."""
    from nyshporka.sources.http import Fetcher

    src = A.ArchiumSource(workspace=tmp_path,
                          fetcher=Fetcher(base=A.BASE, delay=0.0, client=recorded))
    stats = src.crawl(("1",))
    assert stats["fonds"] == 1
    assert stats["inventories"] == 2
    assert stats["cases"] == 50          # два описи по 25 справ у фікстурі

    hits = src.search("Авратин")
    assert hits and hits[0].ref == "file:5301"
    assert hits[0].shifra.startswith("ф.18")
    assert "Церква" in hits[0].title


def test_crawl_resumes_instead_of_starting_over(tmp_path: Path,
                                                recorded: _Recorded) -> None:
    """🔴 Перерваний обхід уже коштував запитів до чужого сервера.

    Починати наново означало б платити двічі — і чужим ресурсом, не своїм.
    """
    from nyshporka.sources.http import Fetcher

    src = A.ArchiumSource(workspace=tmp_path,
                          fetcher=Fetcher(base=A.BASE, delay=0.0, client=recorded))
    src.crawl(("1",))
    n_first = len(recorded.asked)
    again = src.crawl(("1",))
    assert again["fonds"] == 0 and again["skipped"] == 1
    # Другий прохід іще питає перелік фондів (інакше не дізнатись, чи не додали
    # нових), але жодного опису вже не читає.
    assert len(recorded.asked) - n_first <= 1


def test_crawl_flattens_titles_so_the_tsv_survives(tmp_path: Path) -> None:
    """🔴 Табуляція в заголовку розірвала б TSV, і то ТИХО.

    Наступний рядок став би «справою» з полями зі зсувом: каталог зіпсувався б
    із середини, а виглядав би цілим.
    """
    assert A._flat("Церква,\tс. Авратин\nМетрична книга") == \
        "Церква, с. Авратин Метрична книга"


def test_manifest_title_comes_from_the_catalog(tmp_path: Path,
                                               viewer_html: str) -> None:
    """Підтвердження перед качанням гігабайтів мусить казати, ЩО це.

    Переглядач заголовка не несе; єдине місце, де він є, — зібраний каталог.
    """
    from nyshporka.sources.http import Fetcher

    cat = tmp_path / A.ArchiumSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    cat.write_text("fond_no\tinv_label\tcase_no\tfile_id\tdescription\n"
                   "18\tОпис 1\tСправа 1\t5301\tЦерква, с. Авратин\n",
                   encoding="utf-8")
    src = A.ArchiumSource(workspace=tmp_path,
                          fetcher=Fetcher(base=A.BASE, delay=0.0,
                                          client=_Recorded({"file-viewer": viewer_html})))
    man = src.manifest("file:5301")
    assert man.frames == 47
    assert "ф.18 Опис 1 Справа 1" in man.title
    assert "Авратин" in man.title
