"""🎞 Дзеркало плівок: покажчик аркушів і три його пастки — на фікстурах.

Дерево регіону тут справжнє, лише обрізане до двох плівок: перевіряються межі
покажчика, а не обсяг. Мережа не потрібна жодному тесту — і не має бути
потрібна: фікстура це відповідь чужого сервера, зафіксована один раз.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

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
    """Перелік регіонів росте; зашитий знімок протухав би мовчки.

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

    Різниця тиха: `.get()` по рядку їде по його символах і не падає.
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
    """🔴 Пастка 3: `delo` заповнене лише в першому записі блоку.

    Порожнє далі означає «та сама справа». Без протягування 90% записів
    лишились би без шифру — тобто знайдене село не мало б адреси в архіві, а
    саме адреса й потрібна.
    """
    rows = film_entries(src.tree("moldova"), PARENT, "2086525")
    assert len(rows) > 50
    assert rows[0]["delo"], "перший запис без шифру — фікстура не та"
    assert all(r["delo"] for r in rows), "шифр десь урвався"
    # Протягування має змінюватись на новому блоці, а не залипати назавжди.
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
    """Покажчик відповідає «де метрики мого села» без жодного завантаження."""
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


def test_search_reads_the_region_index_not_the_tree(src: FilmMirrorSource) -> None:
    """🔴 Пошук розгортав дерева всіх регіонів: 4,4 ГБ і 12 с щоразу (07.10.2026).

    Дерево розгортається один раз — на побудову покажчика-супутника — і не
    тримається; далі пошук читає лише супутника.
    """
    from nyshporka.sources.fsfilm import INDEX_SUFFIX

    first = src.search("Ракулешты")
    idx = src.cache_dir / f"moldova{INDEX_SUFFIX}"
    assert idx.is_file(), "супутника не збудовано"
    assert not src._trees, "пошук тримає розгорнуте дерево"

    built = idx.stat().st_mtime_ns
    import nyshporka.sources.fsfilm as F

    def _no(*_a: object, **_k: object) -> None:
        raise AssertionError("дерево розгорнуто вдруге")

    orig = F._decode_tree
    F._decode_tree = _no  # type: ignore[assignment]
    try:
        again = src.search("Ракулешты")
    finally:
        F._decode_tree = orig
    assert [h.ref for h in again] == [h.ref for h in first]
    assert idx.stat().st_mtime_ns == built


def test_a_fresher_tree_rebuilds_the_index(src: FilmMirrorSource) -> None:
    """Оновлене дерево (`tree(refresh=True)`) не сміє шукатись по старому супутнику."""
    import os

    from nyshporka.sources.fsfilm import INDEX_SUFFIX

    src.search("Ракулешты")
    idx = src.cache_dir / f"moldova{INDEX_SUFFIX}"
    old = idx.stat().st_mtime_ns
    blob = src.cache_dir / "moldova.json.gz"
    os.utime(blob, ns=(old + 10**9, old + 10**9))
    src.search("Ракулешты")
    assert idx.stat().st_mtime_ns > old


def test_search_is_insensitive_to_yo(src: FilmMirrorSource) -> None:
    """У покажчику «ё» пишуть і як «е» — це один і той самий населений пункт."""
    assert src.search("Оргеев", regions=["moldova"])


def test_search_without_tree_and_without_bundle_refuses(tmp_path: Path,
                                                        monkeypatch) -> None:
    """Нуль по порожньому кешу означав би «немає», а насправді ми не дивились.

    ⚠ У звичайній установці ця гілка недосяжна: покажчик їде в пакеті. Але вона
    мусить лишатись робочою — пакет ставлять і врізаним, і з підміненими
    даними, а мовчазний нуль звідти нічим не відрізнявся б від чесного.
    """
    monkeypatch.setattr(FilmMirrorSource, "bundled_index", staticmethod(lambda: None))
    s = FilmMirrorSource(cache_dir=tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceError, match="покажчика немає"):
        s.search("Резина")


def test_frame_url_is_computed_not_taken_from_the_tree(src: FilmMirrorSource) -> None:
    """🔴 Пастка 1: `imageBaseUrl` у дереві виглядає авторитетно й дає 404.

    Воно лишає в шляху `/media/mihailo`; робоча адреса — `rootId` без цього
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
    """🔴 Обірваний запис отруйний: `exists()` каже «є», докачки не буде ніколи.

    Регіон тихо випадає з обходу під виглядом помилки — а насправді на диску
    лежить нуль байтів після Ctrl-C чи скінченого місця.
    """
    blob = src.cache_dir / "moldova.json.gz"
    blob.write_bytes(b"")
    src._trees.clear()
    # Потрібна саме спроба перекачати: мовчазне «файл є» було б гіршою
    # поведінкою. Заглушка замість справжнього DNS-збою — той чекав ретраїв ~30 с.
    asked: list[str] = []

    class _Offline:
        def get(self, url: str, **_kw):
            asked.append(url)
            raise ConnectionError(f"мережі немає: {url}")

    src.http = _Offline()  # type: ignore[assignment]
    with pytest.raises(ConnectionError):
        src.tree("moldova")
    assert asked == ["https://example.invalid/moldova.json.gz"]
    assert not blob.exists(), "порожній блоб мусив бути прибраний"


# ── вкладений покажчик ───────────────────────────────────────────────────────
def test_bundled_sheet_index_answers_where_without_any_download(tmp_path: Path) -> None:
    """🔴 «Де метрики мого села» — одразу після встановлення.

    Дерево одного регіону важить від мегабайта до чотирнадцяти; тягнути їх усі
    заради одного запиту не можна, а без них покажчика не було б узагалі.
    """
    empty = tmp_path / "порожній"
    empty.mkdir()
    s = FilmMirrorSource(cache_dir=empty)
    kind, info = s.catalog_source()
    assert kind == "bundled", "покажчик не доїхав у пакет"
    assert info["taken"], "зріз без дати — «не знайшлось» не має сенсу"
    assert (info["rows"] or 0) > 50_000

    hits = s.search("Резина", limit=3)
    assert hits
    h = hits[0]
    assert h.place == "Резина"
    assert h.shifra.startswith("Ф. 211")
    assert "Л." in h.title, "діапазон аркушів не відновлено"
    assert h.ref.startswith("moldova/")
    assert info["taken"] in h.note


def test_bundled_index_names_the_regions_it_covers(tmp_path: Path) -> None:
    """🔴 Покажчик є не всюди, і мовчати про це не можна.

    У більшості регіонів дзеркала `folder_meta` — це голий підпис теки. Не
    назвати покриття означало б видати «нема в покажчику» за «нема на плівках».
    """
    empty = tmp_path / "порожній"
    empty.mkdir()
    _, info = FilmMirrorSource(cache_dir=empty).catalog_source()
    assert info["regions"], "зріз не каже, які регіони накриває"
    assert "moldova" in info["regions"]


def test_cached_trees_win_over_the_bundled_snapshot(src: FilmMirrorSource) -> None:
    """Дерево в кеші новіше за побудовою — вкладений зріз його не перекриває."""
    assert src.catalog_source()[0] == "workspace"


def test_bundled_index_holds_only_real_sheet_ranges() -> None:
    """Підпис теки без «Л.» у зріз не потрапляє.

    Інакше покажчик показував би відповідь там, де її немає, — а за нею йдуть
    качати плівку на гігабайт.
    """
    import csv
    import gzip

    got = FilmMirrorSource.bundled_index()
    assert got is not None
    with gzip.open(got[0], "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert rows
    assert all(r["start"].isdigit() for r in rows), "запис без діапазону"
    assert all(r["name"].strip() for r in rows), "запис без назви місця"


# ── аудит 29.09.2026: дерево регіону з чужої адреси має стелю ───────────────

def test_gzip_bomba_v_kesh_ne_rozpakovuietsia_bez_steli(
        src: FilmMirrorSource, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Кілобайти, що розпаковуються в гігабайти, клали процес.

    Адресу блоба дає розмітка дзеркала, тож за нею може лежати будь-що.
    """
    import gzip

    from nyshporka.sources import fsfilm as F

    (src.cache_dir / "moldova.json.gz").write_bytes(gzip.compress(b" " * 5_000_000))
    src._trees.clear()
    monkeypatch.setattr(F, "MAX_TREE_JSON_BYTES", 1_000_000)
    with pytest.raises(SourceError, match="розпаковується понад"):
        src.tree("moldova")


def test_blob_z_merezhi_kachaietsia_zi_steleiu(
        src: FilmMirrorSource, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from nyshporka.sources import fsfilm as F
    from nyshporka.sources.http import Fetcher, TooLarge

    blob = src.cache_dir / "moldova.json.gz"
    blob.unlink()
    src._trees.clear()
    src.http = Fetcher(delay=0.0, client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"\x1f\x8b" + b"x" * 10_000))))
    monkeypatch.setattr(F, "MAX_TREE_GZ_BYTES", 1000)
    with pytest.raises(TooLarge):
        src.tree("moldova")
    assert not blob.exists()


# ── чому дзеркало не віддало — причиною, а не рядком «HTTP 403» ───────────────

REF = f"moldova/{PARENT}/2086525"


def _z_vidpoviddiu(src: FilmMirrorSource, handler: Any) -> None:
    import httpx

    from nyshporka.sources.http import Fetcher

    src.http = Fetcher(delay=0.0, attempts=1,
                       client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(("status", "cause"), [
    (404, "not_found"), (403, "denied"), (401, "denied"), (429, "rate_limited"),
    (503, "host_down")])
def test_prychyna_vidmovy_kadru(src: FilmMirrorSource, tmp_path: Path,
                                status: int, cause: str) -> None:
    """🔴 «Кадрів там немає», «не пускає» і «хост лежить» — різні дії для людини."""
    import httpx

    _z_vidpoviddiu(src, lambda req: httpx.Response(status))

    res = src.fetch(REF, tmp_path / "out", frames=(1, 3))

    assert res.frames == 0 and res.causes == {cause: 3}
    assert "3" in res.why()


def test_obryv_ziednannia_tse_khost_a_ne_kadr(src: FilmMirrorSource, tmp_path: Path) -> None:
    import httpx

    def _obryv(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _z_vidpoviddiu(src, _obryv)
    res = src.fetch(REF, tmp_path / "out", frames=(1, 2))

    assert res.causes == {"host_down": 2}


def test_vzyati_kadry_bez_prychyn(src: FilmMirrorSource, tmp_path: Path) -> None:
    import httpx

    _z_vidpoviddiu(src, lambda req: httpx.Response(200, content=b"JPEG"))
    res = src.fetch(REF, tmp_path / "out", frames=(1, 2))

    assert res.frames == 2 and res.causes == {} and res.why() == ""
    # Повтор нічого не качає: кадри з тим самим іменем уже лежать.
    znovu = src.fetch(REF, tmp_path / "out", frames=(1, 2))
    assert (znovu.frames, znovu.skipped) == (0, 2)


def test_dzerkalo_movchyt_tse_vidmova_z_prychynoiu(src: FilmMirrorSource) -> None:
    """🔴 Збій мережі на дереві регіону — відмова словами, а не трасування.

    І вона каже, що це стороннє дзеркало: про плівку на FamilySearch його
    відмова нічого не доводить.
    """
    import httpx

    (src.cache_dir / "moldova.json.gz").unlink()
    src._trees.clear()
    _z_vidpoviddiu(src, lambda req: httpx.Response(403))

    with pytest.raises(SourceError, match="не FamilySearch") as ei:
        src.tree("moldova")
    assert "401/403" in str(ei.value)


def test_prychyna_liahaie_v_pasport(tmp_path: Path) -> None:
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    res = FetchResult(dest=tmp_path, errors=["0001.jpg: HTTP 403"], causes={"denied": 1})
    record_fetch(tmp_path, res, source="fsfilm", ref="moldova/x", want=1)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetch_causes"] == {"denied": 1} and meta["fetch_state"] == "empty"
