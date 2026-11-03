"""🏛 ARCHIUM як рушій, а не один архів.

Сайт-переглядач спільний для кількох архівів, а хости різні. Доки адреса була
константою модуля, джерело вміло рівно один архів; ЦДІАК — де лежить колекція
метричних книг на 2944 справи — не діставався взагалі.

⚠ Наявний `test_sources_archium.py` не змінювався жодним рядком, і це навмисно:
він і є доказ, що мультихостовість нічого не зламала в тому, що працювало.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.archives import active
from nyshporka.sources import archium as A
from nyshporka.sources import load
from nyshporka.sources.base import SourceError
from nyshporka.sources.http import Fetcher


def _cdiak() -> A.ArchiumSource:
    site = active().site("CDIAK", "archium")
    assert site is not None, "майданчик ЦДІАК зник із паку"
    return A.ArchiumSource(site=site, repo="CDIAK")


def test_each_site_is_its_own_source_with_its_own_name() -> None:
    """🔴 `id` їде в «де шукали» кожної відповіді. Спільне ім'я на два різні
    архіви зробило б знаменник пошуку неправдивим: «шукали в archium» не
    сказало б, у якому саме, а нуль читався б як відповідь про обидва."""
    dahmo, cdiak = A.ArchiumSource(), _cdiak()

    assert dahmo.id == "archium", "історичне ім'я ДАХмО має лишитись"
    assert cdiak.id == "archium-cdiak"
    assert dahmo.id != cdiak.id
    assert "ЦДІАК" in cdiak.label


def test_the_host_comes_from_the_pack_not_from_the_module() -> None:
    dahmo, cdiak = A.ArchiumSource(), _cdiak()
    assert dahmo.base == A.BASE
    assert cdiak.base != A.BASE and "cdiak" in cdiak.base


def test_frames_are_addressed_on_the_right_host() -> None:
    """Кадр качається з того хоста, де лежить справа: спільна формула шляху й
    різні хости — найтихіший спосіб піти по чужу сторінку."""
    cdiak = _cdiak()
    assert A.image_url(13943, cdiak.base).startswith(cdiak.base)
    assert A.image_url(13943).startswith(A.BASE), "дефолт зламано"


def test_each_site_keeps_its_own_catalogue() -> None:
    """Спільна тека каталогу означала б, що обхід одного архіву затирає обхід
    іншого, а пошук віддає суміш двох фондових просторів."""
    dahmo, cdiak = A.ArchiumSource(), _cdiak()
    assert dahmo.catalog_rel == A.ArchiumSource.CATALOG_REL, "шлях ДАХмО поїхав"
    assert cdiak.catalog_rel != dahmo.catalog_rel
    assert "cdiak_archium" in cdiak.catalog_rel.as_posix()


class _JsonResp:
    status_code = 200

    def __init__(self, view: str) -> None:
        self.headers: dict[str, str] = {}
        self._view = view
        self.text = json.dumps({"Status": 1, "View": view})

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return {"Status": 1, "View": self._view}


class _Api:
    """Двійник API ARCHIUM: відповідь за підрядком адреси. Мережі нема."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str) -> _JsonResp:
        self.asked.append(url)
        for key, view in self.pages.items():
            if key in url:
                return _JsonResp(view)
        raise AssertionError(f"тест не готував відповіді на {url}")


_FONDS_VIEW = """<table class="fond-groups"><tbody>
<tr><td>13</td><td><a href="/fonds/3625/">Гадяцький повітовий суд</a></td>
    <td>1782-1873</td><td>120</td></tr>
<tr><td>16</td><td><a href="/fonds/3626/">Зіньківський повітовий земський суд</a></td>
    <td></td><td>40</td></tr>
</tbody></table>"""


def _cdiak_with(api: _Api) -> A.ArchiumSource:
    site = active().site("CDIAK", "archium")
    assert site is not None
    return A.ArchiumSource(site=site, repo="CDIAK",
                           fetcher=Fetcher(base=site.url, delay=0.0, client=api))


def test_a_site_without_a_group_tree_lists_its_own_fonds_flat() -> None:
    """🔴 Дві однаково погані відповіді, яких тут немає.

    Чотири групи сусіднього архіву — чуже дерево під іменем цього. Відмова, як
    було доти, лишала перегляд без початку: `fond:<id>` — id сайту, а не номер
    фонду, і знати його наперед людина не може. Тож корінь — суцільний перелік
    фондів (`/api/v1/fonds/`), той самий, яким іде обхід; групи не питаються.
    """
    api = _Api({"/api/v1/fonds/": _FONDS_VIEW})
    nodes = _cdiak_with(api).browse()

    assert [n.ref for n in nodes] == ["fond:3625", "fond:3626"]
    assert nodes[0].label.startswith("ф.13 Гадяцький")
    assert not any("fond-groups" in u for u in api.asked), "груп у майданчика немає"


def test_an_empty_flat_list_is_not_read_as_an_empty_archive() -> None:
    """Порожній перелік — ознака зміненої розмітки, а не порожнього архіву."""
    with pytest.raises(SourceError) as exc:
        _cdiak_with(_Api({"/api/v1/fonds/": "<p>нічого</p>"})).browse()
    assert "archium-cdiak" in str(exc.value), "відмова не каже, чим шукати далі"


#: Майданчики, вписані за дайджестом Укрдержархіву за жовтень 2026 (перевірено
#: живими запитами 03.11.2026): код архіву → підрядок хоста й мітка.
NEW_SITES = {
    "CDAVO": ("e-resource.tsdavo.gov.ua", "ЦДАВО"),
    "CDAHOU": ("e.tsdahou.archives.gov.ua", "ЦДАГОУ"),
    "CDAMLM": ("ksi-csamm.archives.gov.ua", "ЦДАМЛМ"),
    "DALO": ("e.archivelviv.gov.ua", "ДАЛО"),
    "DAKO": ("archium.dako.gov.ua", "ДАКО"),
    "DAKRO": ("archium.krop.archives.gov.ua", "ДАКрО"),
    "DAPO": ("e-resource.poltava.archives.gov.ua", "ДАПО"),
}


@pytest.mark.parametrize("code", sorted(NEW_SITES))
def test_new_site_is_its_own_archium_source(code: str) -> None:
    host, label = NEW_SITES[code]
    site = active().site(code, "archium")
    assert site is not None, f"майданчик {code} зник із паку"
    src = A.ArchiumSource(site=site, repo=code)

    assert src.id == f"archium-{code.lower()}"
    assert host in src.base and src.base != A.BASE
    assert label in src.label
    assert not site.fond_groups, "дерево груп у цих майданчиків віддає 500"


def test_archium_source_ids_are_unique_in_the_registry(tmp_path: Path) -> None:
    """`id` їде в «де шукали»: два архіви під одним ім'ям — неправдивий знаменник."""
    ids = [s.id for s in load(tmp_path).all() if isinstance(s, A.ArchiumSource)]
    assert len(ids) == len(set(ids))
    assert {f"archium-{c.lower()}" for c in NEW_SITES} <= set(ids)


def test_cdamlm_is_not_the_chisinau_archive() -> None:
    """Код `CSAMM` зайнятий кишинівським архівом; шифра «ЦДАМЛМ» мусить лягати
    в український архів-музей, а не туди."""
    assert active().site("CSAMM", "archium") is None
    assert active().site("CDAMLM", "archium") is not None


def test_mirror_host_of_a_site_routes_to_its_source(tmp_path: Path) -> None:
    """Посилання на голий IP того самого переглядача — це та сама справа ДАКрО,
    а не тимчасовий майданчик з чужим id. Мережі тут не треба: хост відомий."""
    got = A.route_viewer_url(load(tmp_path), "archium",
                             "http://185.250.20.62/file-viewer/26106")
    assert got is not None
    src, ref, note = got
    assert src.id == "archium-dakro" and ref == "file:26106" and note == ""


def test_source_accepts_a_viewer_url_of_its_mirror_host() -> None:
    """Перевірка «чужий хост» не мусить відкидати власне дзеркало."""
    site = active().site("DAKRO", "archium")
    assert site is not None
    src = A.ArchiumSource(site=site, repo="DAKRO")
    assert src._ident("http://185.250.20.62/file-viewer/26106") == "26106"


def test_the_bundled_snapshot_belongs_to_its_own_site() -> None:
    """Зріз каталогу зібрано для ДАХмО; віддавати його від імені іншого архіву
    означало б показати чужі справи як свої."""
    assert A.ArchiumSource().catalog_source()[0] == "bundled"
    assert _cdiak().catalog_source()[0] == "none"


# ── неоцифрована справа ──────────────────────────────────────────────────────
def _absent_html() -> str:
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / "sources"
            / "archium_viewer_absent.html").read_text(encoding="utf-8")


def test_a_case_that_is_not_digitised_answers_200_not_404() -> None:
    """🔴 Найтихіша пастка цього сайту, і фікстура тут — жива відповідь.

    На справу, якої в переглядачі немає, ARCHIUM віддає головну сторінку з
    кодом 200 (заміряно: 9.9 КБ, жодного кадру). Той, хто перевіряє статус,
    дістає «все гаразд» і порожній список — і читає це як «кадри скінчились»,
    тобто як властивість справи, а не як відсутність сторінки.
    """
    html = _absent_html()
    assert "data-observe-src" not in html, "фікстура не та: у ній є кадри"
    assert not A.viewer_pages(html)
    assert not A.case_meta(html), "шифри на цій сторінці бути не може"


def test_the_shifra_is_read_from_the_page_when_the_case_is_there() -> None:
    """Та сама розмітка дає й внутрішні номери сайту: фонд і опис він адресує
    власними, з архівною шифрою не пов'язаними ніяк, а взяти їх більше нізвідки
    (для ф.224 сайт зве фонд номером 198)."""
    html = (
        '<div class="description"><div class="description-item">'
        '<h4 class="item-head-upper">'
        '<a href="/files/51068/" class="no-link-item">Справа&nbsp;1</a></h4>'
        '<ul class="item-lists">'
        '<li> Фонд <a href="/fonds/198/">224</a> </li>'
        '<li> Опис <a href="/inventories/1527/">1</a> </li>'
        "</ul>")
    m = A.case_meta(html)
    assert (m.fond, m.opys, m.spr) == ("224", "1", "1")
    assert (m.fond_id, m.inv_id) == ("198", "1527")
    assert m.fond_id != m.fond, "номер сайту й номер фонду — різні числа"


def test_the_refusal_says_which_of_the_two_states_it_is() -> None:
    """«Справи немає в переглядачі» і «справа є, кадрів немає» лікуються
    по-різному: перше — шукати іншим каналом, друге — замовляти в архіві."""
    class _One:
        def get(self, url: str) -> object:
            class R:
                status_code = 200
                text = _absent_html()

                def raise_for_status(self) -> None:
                    pass
            return R()

    src = A.ArchiumSource(fetcher=A.Fetcher(base="https://x", delay=0.0, client=_One()))
    with pytest.raises(SourceError) as exc:
        src.manifest("file:52170")
    assert "200" in str(exc.value) and "404" in str(exc.value)


def test_viewer_is_not_asked_with_the_bare_site_root_as_referer() -> None:
    """🔴 ЦДІАК віддає 403 на `/file-viewer/<id>` рівно з `Referer: <корінь>/`.

    Типовий `Referer` `Fetcher` — саме корінь, і «Завантажити» з ЦДІАК падало в
    кожного (прохід новачка 23.10.2026). Без заголовка, з `/fonds/` чи з самою
    сторінкою сайт відповідає 200.
    """
    for src in (A.ArchiumSource(), _cdiak()):
        ref = src.http._headers.get("Referer", "")
        assert ref.rstrip("/") != src.base.rstrip("/"), ref
        assert ref.startswith(src.base)


@pytest.mark.parametrize(("code", "word"), [(403, "не пустив"), (404, "немає"),
                                            (429, "пригальмувати"), (503, "не відповідає")])
def test_site_refusal_is_explained_not_bare(code: int, word: str) -> None:
    """Відмова сайту — словами й з адресою, а не голе «HTTP 403»."""
    from nyshporka.sources.http import HttpError, explain

    msg = explain(HttpError(f"https://archium.example/file-viewer/1: HTTP {code}", status=code))
    assert word in msg and "https://archium.example/file-viewer/1" in msg
    assert f"HTTP {code}" in msg


def test_search_title_keeps_spaces_around_the_highlighted_match() -> None:
    """Сайт обгортає збіг тегом; заголовок не клеїться в «м-каМеджибіжЛетичівського»."""
    html = ('<div class="row"><div class="left"><span>Фонд 224</span><span>Опис 1</span>'
            '<span>Справа 793</span></div><div class="right"><a href="/files/51871/">x</a>'
            '<p class="doc-title">Метрична книга м-ка <mark>Меджибіж</mark> Летичівського повіту</p>'
            '<p class="date">1736, 90 аркушів</p></div></div>')
    rows = A.parse_search(html)
    assert rows and rows[0].title == "Метрична книга м-ка Меджибіж Летичівського повіту"


def test_cdial_site_is_its_own_archium_source() -> None:
    """ЦДІАЛ: той самий рушій, свій хост і своє `id` (`archium-cdial`)."""
    site = active().site("CDIAL", "archium")
    assert site is not None, "майданчик ЦДІАЛ зник із паку"
    src = A.ArchiumSource(site=site, repo="CDIAL")

    assert src.id == "archium-cdial"
    assert "tsdial" in src.base and src.base != A.BASE
    assert "ЦДІАЛ" in src.label
    assert active().site("CDIAL", "web") is not None, "звичайний сайт має лишитись"
