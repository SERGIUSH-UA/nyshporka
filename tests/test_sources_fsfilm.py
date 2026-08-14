"""🎞 Дзеркало плівок: покажчик аркушів і три його пастки — на фікстурах.

Дерево регіону тут справжнє, лише обрізане до двох плівок: перевіряються межі
покажчика, а не обсяг. Мережа не потрібна жодному тесту — і не має бути
потрібна: фікстура це відповідь чужого сервера, зафіксована один раз.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.fsfilm import (
    FilmMirrorSource,
    entry_name,
    entry_range,
    film_entries,
    meta_entries,
    parse_sources,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "sources"
PARENT = "_2043433 - 2098841 - 500 плёнок"


@pytest.fixture
def src(tmp_path: Path) -> FilmMirrorSource:
    """Джерело з підкладеним кешем — реєстр і дерево вже «завантажені»."""
    cache = tmp_path / "cache"
    cache.mkdir()
    shutil.copy(FIX / "fsfilm_region.json.gz", cache / "moldova.json.gz")
    s = FilmMirrorSource(cache_dir=cache)
    s._sources = [{"name": "Молдова", "slug": "moldova",
                   "root_id": "/media/mihailo/Russian_Empire_2/Moldova/",
                   "url": "https://example.invalid/moldova.json.gz"}]
    return s


# ── реєстр регіонів ──────────────────────────────────────────────────────────

def test_regions_are_read_from_the_page_not_hardcoded() -> None:
    """Перелік регіонів росте; зашитий знімок протухав би МОВЧКИ.

    Новий архів просто не з'являвся б у застосунку — без помилки, без ознаки,
    що щось не так.
    """
    got = parse_sources((FIX / "fsfiles_spa.html").read_text(encoding="utf-8"))
    slugs = {s["slug"] for s in got}
    assert len(got) >= 20
    assert {"moldova", "odessa", "pskov"} <= slugs
    md = next(s for s in got if s["slug"] == "moldova")
    # `id` у сторінці задається через константу — підстановка мусить спрацювати,
    # інакше саме з нього рахується адреса кадру.
    assert md["root_id"].startswith("/media/mihailo/")
    assert md["url"].endswith(".json.gz")


# ── форма folder_meta ────────────────────────────────────────────────────────

def test_meta_shape_differs_by_region_and_is_normalised() -> None:
    """🔴 Пастка 2: у Молдові це список словників, у Пскові — голий рядок.

    Різниця тиха: `.get()` по рядку їде по його СИМВОЛАХ і не падає.
    """
    assert meta_entries([{"listy": "Л. 1-5 - Село"}]) == [{"listy": "Л. 1-5 - Село"}]
    assert meta_entries("22-опись") == [{"listy": "22-опись"}]
    assert meta_entries({"listy": "Л. 7"}) == [{"listy": "Л. 7"}]
    assert meta_entries(None) == []


def test_a_folder_label_is_not_a_sheet_index(src: FilmMirrorSource) -> None:
    """Підпис теки («22-опись») не має вдавати поаркушевий покажчик.

    Інакше «з покажчиком N» брехало б там, де шукати нічим: користувач пішов би
    по відповідь, якої в цьому регіоні не існує в принципі.
    """
    man = src.manifest("moldova/опис/22")
    assert man.meta["meta_rows"] == 1
    assert man.meta["sheet_rows"] == 0
    assert man.sheets == ()


# ── розбір рядка покажчика ───────────────────────────────────────────────────

@pytest.mark.parametrize(("listy", "want"), [
    ("Л. 132-223 - Резина", (132, 223)),
    ("Л. 137 - Резина", (137, 137)),
    ("Л. 900-… - Резина", (900, None)),
    ("Л. 900-... - Резина", (900, None)),
    ("22-опись", None),
])
def test_sheet_range_parsing(listy: str, want: tuple[int, int | None] | None) -> None:
    assert entry_range(listy) == want


def test_place_is_split_off_the_range() -> None:
    assert entry_name("Л. 132-223 - Резина") == "Резина"
    assert entry_name("22-опись") == ""


# ── протягування й закриття меж ──────────────────────────────────────────────

def test_shifra_is_carried_forward(src: FilmMirrorSource) -> None:
    """🔴 Пастка 3: `delo` заповнене лише в ПЕРШОМУ записі блоку.

    Порожнє далі означає «та сама справа». Без протягування 90% записів
    лишились би без шифру — тобто знайдене село не мало б адреси в архіві, а
    саме адреса й потрібна.
    """
    rows = film_entries(src.tree("moldova"), PARENT, "2086525")
    assert len(rows) > 50
    assert rows[0]["delo"], "перший запис без шифру — фікстура не та"
    assert all(r["delo"] for r in rows), "шифр десь урвався"
    # Протягування має ЗМІНЮВАТИСЬ на новому блоці, а не залипати назавжди.
    assert len({r["delo"] for r in rows}) > 1


def test_open_range_is_closed_by_the_neighbour_not_by_film_end(
        src: FilmMirrorSource) -> None:
    """🔴 «Л. 900-…» закривається наступним записом, а не кінцем плівки.

    Інакше один запис тягнув би пів справи чужих сіл: відповідь «метрики вашого
    села на кадрах 900-991» була б хибною на сотні аркушів — і хибною
    правдоподібно, бо перевірити її можна лише перегортавши все.
    """
    rows = film_entries(src.tree("moldova"), PARENT, "2064122")
    open_rows = [r for r in rows if r["end_inferred"]]
    assert open_rows, "у фікстурі немає запису з відкритою межею"
    for r in open_rows:
        nxt = [o for o in rows if o["start"] and o["start"] > r["start"]]
        if nxt:
            assert r["end"] == min(o["start"] for o in nxt) - 1
        else:
            assert r["end"] == r["frames"]


# ── контракт джерела ─────────────────────────────────────────────────────────

def test_manifest_answers_where_without_downloading(src: FilmMirrorSource) -> None:
    """Покажчик відповідає «де метрики мого села» БЕЗ жодного завантаження."""
    man = src.manifest(f"moldova/{PARENT}/2086525")
    assert man.frames == 20            # фікстура обрізана, це не обсяг плівки
    assert man.meta["sheet_rows"] == len(man.sheets) > 50
    rng = man.frames_for("Оргеев")
    assert rng == (24, 43)


def test_search_walks_the_sheet_index(src: FilmMirrorSource) -> None:
    hits = src.search("Ракулешты", regions=["moldova"])
    assert hits
    h = hits[0]
    assert h.place == "Ракулешты"
    assert h.shifra.startswith("Ф. 211")
    assert h.ref.endswith("2086525")
    assert h.acquirable


def test_search_is_insensitive_to_yo(src: FilmMirrorSource) -> None:
    """У покажчику «ё» пишуть і як «е» — це один і той самий населений пункт."""
    assert src.search("Оргеев", regions=["moldova"])


def test_search_without_any_tree_refuses(tmp_path: Path) -> None:
    """Нуль по порожньому кешу означав би «немає», а насправді ми не дивились."""
    s = FilmMirrorSource(cache_dir=tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceError, match="дерева регіону"):
        s.search("Резина")


def test_frame_url_is_computed_not_taken_from_the_tree(src: FilmMirrorSource) -> None:
    """🔴 Пастка 1: `imageBaseUrl` у дереві виглядає авторитетно й дає 404.

    Воно лишає в шляху `/media/mihailo`; робоча адреса — `rootId` БЕЗ цього
    префікса, приклеєний до `/storage`. Перевірено запитом: перша форма 404,
    друга 200. Довіритись полю означало б порожню теку без пояснення.
    """
    url = src.frame_url("moldova", f"{PARENT}/2086525", "0001.jpg")
    assert url.startswith("https://geno-dbase.ru/storage/Russian_Empire_2/Moldova/")
    assert "/media/mihailo" not in url
    assert url.endswith("/2086525/0001.jpg")
    # пробіли й кирилиця в назві теки мусять бути закодовані
    assert " " not in url


def test_browse_marks_folders_that_actually_hold_frames(src: FilmMirrorSource) -> None:
    """Тека з кадрами — це плівка, яку качають; без кадрів — просто рівень."""
    nodes = src.browse(f"moldova/{PARENT}")
    kinds = {n.label: n.kind for n in nodes}
    assert kinds["2086525"] == "case"
    assert all(n.frames for n in nodes if n.kind == "case")


def test_url_from_the_viewer_is_understood() -> None:
    assert FilmMirrorSource.parse_url(
        "https://fsfiles.ru/#moldova%2F_2043433%20-%202098841%2F2086525"
    ) == "moldova/_2043433 - 2098841/2086525"


def test_zero_length_cache_is_treated_as_missing(src: FilmMirrorSource) -> None:
    """🔴 Обірваний запис отруйний: `exists()` каже «є», докачки не буде НІКОЛИ.

    Регіон тихо випадає з обходу під виглядом помилки — а насправді на диску
    лежить нуль байтів після Ctrl-C чи скінченого місця.
    """
    blob = src.cache_dir / "moldova.json.gz"
    blob.write_bytes(b"")
    src._trees.clear()
    # Мережі немає, тож спроба перекачати впаде — але саме СПРОБА і потрібна:
    # мовчазне «файл є» було б гіршою поведінкою.
    with pytest.raises(Exception, match=r"(?i)example\.invalid|resolve|connect|name"):
        src.tree("moldova")
    assert not blob.exists(), "порожній блоб мусив бути прибраний"
