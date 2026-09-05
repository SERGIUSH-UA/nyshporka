"""🏛 ARCHIUM: розбір каталогу й порядок кадрів — на записаних відповідях.

🔴 Чому не живі запити. Тест мережевого джерела, що ходить у мережу, перевіряє
чужий сервер, а не наш розбір: він червонітиме через профілактику архіву й
зеленітиме через те, що розмітка ще не змінилась. Ні те, ні те не про наш код.
Фікстури тут — справжні відповіді сайту, зняті один раз.

⚠ Зворотний бік чесний: коли сайт перебудують, ці тести лишаться зеленими, а
джерело зламається. Ловить це не тест, а користувач; тому фікстури й називаються
за датою зняття в git-історії, і перезнімати їх треба свідомо.
"""
from __future__ import annotations

import csv
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
    """🔴 Id кадрів у переглядачі перемішані — порядок несе `alt`.

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


@pytest.fixture(scope="module")
def search_view() -> str:
    """`View` живого пошуку — той самий конверт `{"Status":1,"View":"<html>"}`."""
    return json.loads(
        (FIX / "archium_search.json").read_text(encoding="utf-8"))["View"]


def _live(tmp_path: Path, monkeypatch, view: str, *, pages: int = 1) -> tuple[Any, _Recorded]:
    """Джерело без каталогу й із записаною відповіддю пошуку."""
    from nyshporka.sources.http import Fetcher

    monkeypatch.setattr(A.ArchiumSource, "bundled_catalog", staticmethod(lambda: None))
    empty = json.dumps({"Status": 1, "View": ""})
    body = json.dumps({"Status": 1, "View": view})
    rec = _Recorded({rf"search/act/\?Limit=\d+&Page=[1-{pages}](?!\d)": body,
                     r"search/act/": empty})
    src = A.ArchiumSource(workspace=tmp_path,
                          fetcher=Fetcher(base=A.BASE, delay=0.0, client=rec))
    return src, rec


def test_search_row_carries_shifra_and_viewer_id_together(search_view: str) -> None:
    """🔥 Обидва в одному рядку — саме цього бракувало.

    Адресу переглядача доти доводилось рахувати від опорної точки, а формула
    має дрейф: літерні справи (2а, 704А) займають id, не займаючи номера, тож
    далеко від опори вона промахується на десяток. Тут адреса приходить від
    самого сайту разом із шифрою.
    """
    rows = A.parse_search(search_view)
    assert len(rows) == 3
    first = rows[0]
    assert (first.fond, first.opys, first.spr) == ("127", "2", "53")
    assert first.file_id == "935"
    assert first.shifra == "ф.127 оп.2 спр.53"
    # Обсяг — окремим полем: ним звіряють повноту завантаження, а в підписі він
    # злитий з датою («15.06.1797, 6 аркушів»).
    assert first.sheets == 6 and first.date == "15.06.1797"


def test_search_without_a_catalog_asks_the_site_instead_of_refusing(
        tmp_path: Path, monkeypatch, search_view: str) -> None:
    """🔴 Головне в цьому джерелі — і те, що довго було зроблено навпаки.

    Доти без каталогу джерело відмовлялось: вважалось, що сайт індексує лише
    назви фондів і описів. Насправді заголовки справ він шукає, і відповідь
    коштує один запит — тоді як порада «зібрати каталог обходом» це години. Для
    ЦДІАК каталогу немає взагалі, тобто застосунок не вмів знайти в цьому архіві
    жодної справи.
    """
    src, rec = _live(tmp_path, monkeypatch, search_view)
    hits = src.search("Шупики")
    assert [h.ref for h in hits] == ["file:935", "file:1155", "file:1477"]
    assert hits[0].acquirable and hits[0].frames == 6
    # Межа каналу їде з кожною знахідкою: за нею читається його нуль.
    assert "лише оцифровані" in hits[0].note
    assert any("Search=" in u for u in rec.asked)


def test_the_fond_filter_is_applied_here_because_the_server_ignores_it(
        tmp_path: Path, monkeypatch, search_view: str) -> None:
    """🪤 Сервер приймає `FondNumber` і не застосовує його.

    Заміряно: запит «1662» з фондом 127 віддає справи фонду 57. Якби ми
    покладались на серверне звуження, видача чужого фонду читалась би як «ваша
    справа знайшлась» — найдорожчий різновид хибного позитиву, бо шифра в
    рядку виглядає правдоподібно.
    """
    src, _ = _live(tmp_path, monkeypatch, search_view)
    assert len(src.live_search("Шупики", fond="127")) == 3
    assert src.live_search("Шупики", fond="57") == []


def test_a_zero_from_the_snapshot_is_checked_against_the_site(
        tmp_path: Path, monkeypatch, search_view: str) -> None:
    """🔴 Нуль каталогу — це нуль ЗРІЗУ, а не архіву.

    Обхід міг спинитись на половині, а вкладений пак знято колись; справа,
    додана після зрізу, для нього не існує. Питати після цього сам сайт коштує
    один запит — і саме він відповідає про те, чого зріз не бачив.
    """
    from nyshporka.sources.http import Fetcher

    cat = tmp_path / A.ArchiumSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    cat.write_text(
        "fond_no\tfond_title\tinv_label\tfile_id\tcase_no\tdate\tsheets\tdescription\n"
        "18\tЦеркви\tОпис 1\t5301\tСправа 1\t1881\t45\tЦерква, с. Авратин\n",
        encoding="utf-8")
    rec = _Recorded({r"search/act/": json.dumps({"Status": 1, "View": search_view})})
    src = A.ArchiumSource(workspace=tmp_path,
                          fetcher=Fetcher(base=A.BASE, delay=0.0, client=rec))

    assert src.search("авратин")[0].ref == "file:5301"      # зріз відповів сам
    assert not rec.asked, "поки каталог відповідає, сайт не турбуємо"

    hits = src.search("Шупики")
    assert [h.ref for h in hits] == ["file:935", "file:1155", "file:1477"]
    assert "каталог мовчав" in hits[0].note


def test_a_shifra_needs_the_catalog_and_the_refusal_names_what_works(
        tmp_path: Path, monkeypatch) -> None:
    """За шифрою живий пошук не рятує: номера справи в заголовку немає.

    Тому відмова називає не лише обхід (години), а й канал, який працює зараз.
    """
    monkeypatch.setattr(A.ArchiumSource, "bundled_catalog", staticmethod(lambda: None))
    src = A.ArchiumSource(workspace=tmp_path)
    with pytest.raises(SourceError, match="слово з назви"):
        src.find_case("127", "1078", "1662")


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
    """🔴 Табуляція в заголовку розірвала б TSV, і то тихо.

    Наступний рядок став би «справою» з полями зі зсувом: каталог зіпсувався б
    із середини, а виглядав би цілим.
    """
    assert A._flat("Церква,\tс. Авратин\nМетрична книга") == \
        "Церква, с. Авратин Метрична книга"


def test_manifest_title_comes_from_the_catalog(tmp_path: Path,
                                               viewer_html: str) -> None:
    """Підтвердження перед качанням гігабайтів мусить казати, що це.

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


# ── вкладений зріз каталогу ──────────────────────────────────────────────────
def test_bundled_snapshot_makes_search_work_on_day_one(tmp_path: Path) -> None:
    """🔴 Це те, заради чого зріз узагалі їде в пакеті.

    Аудиторія «не знаю, де шукати» не має ні сканів, ні відеокарти. Без
    готового зрізу вона мусила б спершу години обходити чужий сайт — щоб лише
    дізнатись, чи потрібна справа існує.
    """
    src = A.ArchiumSource(workspace=tmp_path)      # простір порожній
    kind, meta = src.catalog_source()
    assert kind == "bundled", "зріз не доїхав у пакет"
    assert meta["taken"], "зріз без дати — «не знайшлось» не має сенсу"
    assert (meta["rows"] or 0) > 8000

    hits = src.search("Борсуківці", limit=3)
    assert hits, "у зрізі немає села, яке в ньому точно є"
    assert hits[0].shifra.startswith("ф.")
    assert meta["taken"] in hits[0].note, "дата зрізу не доїхала до знахідки"


def test_own_crawl_wins_over_the_bundled_snapshot(tmp_path: Path) -> None:
    """Зібраний на місці новіший за побудовою — вкладений його не перекриває."""
    cat = tmp_path / A.ArchiumSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    cat.write_text("file_id\tdescription\n1\tсвіжа справа\n", encoding="utf-8")
    src = A.ArchiumSource(workspace=tmp_path)
    assert src.catalog_source()[0] == "workspace"
    assert [h.ref for h in src.search("свіжа")] == ["file:1"]


def test_snapshot_has_no_test_rows_of_the_archive() -> None:
    """Службові рядки самого архіву («Справа 0», «Опис Test») у зріз не йдуть.

    Справами вони не є й у пошуку лише шумлять — а шум у каталозі коштує
    дорожче за його відсутність: за ним ідуть замовляти справу.
    """
    import gzip

    got = A.ArchiumSource.bundled_catalog()
    assert got is not None
    with gzip.open(got[0], "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert not [r for r in rows if r["case_no"].strip() == "Справа 0"]
    assert not [r for r in rows if "test" in (r["inv_label"] or "").lower()]
def test_crawl_walks_flat_where_the_site_has_no_fond_groups(
        tmp_path: Path, fond_html: str) -> None:
    """🔴 У ЦДІАК груп фондів немає: `/api/v1/fond-groups/1/` — HTTP 500.

    Обхід, що завжди питає групу, для такого майданчика падав завжди, і падав
    повідомленням про відсічку за темпом — постійну ваду видавав за тимчасову.
    Приймач тут — ЯКУ адресу спитали, а не скільки справ зібрали: каталог на
    правильній адресі зібрався б і з помилковою гілкою, якби фікстура відповіла
    на обидві.
    """
    from nyshporka.archives.pack import Site
    from nyshporka.sources.http import Fetcher

    flat = ('<table class="fond-groups"><tbody><tr>'
            '<td>18</td><td><a href="/fonds/13630/">Церкви</a></td>'
            '<td>1795-1927</td><td>3160</td></tr></tbody></table>')
    inv = (FIX / "archium_inventory.json").read_text(encoding="utf-8")
    empty = json.dumps({"Status": 1, "View": ""})
    rec = _Recorded({
        r"/api/v1/fonds/\?Limit=\d+&Page=1(?!\d)": json.dumps({"Status": 1, "View": flat}),
        r"/api/v1/fonds/": empty,
        r"/fonds/13630/": fond_html,
        r"inventories/\d+\?Limit=\d+&Page=1(?!\d)": inv,
        r"inventories": empty,
    })
    site = Site(engine="archium", url="https://архів",
                source_id="archium-cdiak", fond_groups=False)
    src = A.ArchiumSource(workspace=tmp_path, site=site, repo="CDIAK",
                          fetcher=Fetcher(base="https://архів", delay=0.0, client=rec))

    stats = src.crawl()

    assert stats["cases"] == 50
    assert not any("fond-groups" in u for u in rec.asked), (
        "обхід спитав групу фондів у майданчика, який їх не має — "
        f"адреси: {rec.asked}")


def test_crawl_says_groups_mean_nothing_where_there_are_none(tmp_path: Path) -> None:
    """Мовчазне ігнорування `--groups` віддало б увесь архів замість частини."""
    from nyshporka.archives.pack import Site
    from nyshporka.sources.http import Fetcher

    site = Site(engine="archium", url="https://архів",
                source_id="archium-cdiak", fond_groups=False)
    src = A.ArchiumSource(workspace=tmp_path, site=site, repo="CDIAK",
                          fetcher=Fetcher(base="https://архів", delay=0.0))
    with pytest.raises(SourceError, match="груп фондів"):
        src.crawl(("1",))
