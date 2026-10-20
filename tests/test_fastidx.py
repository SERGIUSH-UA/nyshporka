"""⚡ Швидкий передфільтр (Tantivy): та сама відповідь, менше роботи, нуль — свіпом.

🔴 Головне твердження файлу — передфільтр лише звужує, ЩО оцінювати: бал рядка
виносить той самий `_match_unique`, тож знайдене швидким каналом рядок у рядок
збігається зі свіпом триграмами там, де обидва бачать сторінку. А «немає» по
області без свіпу триграмами не друкується.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("tantivy")


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Простір із двома прогонами: рід є в «проба», у «чужий» — немає."""
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    pages = {
        "проба": {"0001": "въ селѣ Вербівцахъ\nродился Иванъ Вербищинскій\n",
                  "0002": "Священникъ Петръ Р\nкрестилъ младенца\n",
                  "0003": "восприемникъ Павелъ Шевчукъ\n"},
        "чужий": {"0001": "Ковальскій Iосифъ\nи жена его Марія\n"},
    }
    for run, txts in pages.items():
        d = tmp_path / "reports" / "htr" / run
        d.mkdir(parents=True)
        for stem, text in txts.items():
            (d / f"{stem}.txt").write_text(text, encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps({
            "model": "pysar_cyr_v17.pt", "script": "cyrillic",
            "pages": {f"{s}.jpg": {"lines": 2} for s in txts}}), encoding="utf-8")
    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    monkeypatch.delenv("NYSH_FAST", raising=False)
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W.reset()


def _build() -> dict:
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    assert list(ST.ensure_all(["проба", "чужий"])) == ["проба", "чужий"]
    conn = ST.connect()
    try:
        return FX.sync(conn)
    finally:
        conn.close()


def _lines(res: dict) -> dict[tuple[str, str, int], int]:
    return {(h["name"], h["page"], h["line_no"]): h["score"] for h in res["hits"]}


def test_the_fast_channel_answers_what_the_trigram_sweep_answers(space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    got = _build()
    assert got["added"] == 2 and got["lines"] > 0
    stem = S._norm("Вербищинскій")
    # Швидкий — першим: відповідь свіпу триграмами лягає в кеш, і швидкий канал
    # чесно бере її звідти, нічого не рахуючи (вона не гірша за його власну).
    fast = ST.sweep([stem], ["проба", "чужий"], fast=True)
    slow = ST.sweep([stem], ["проба", "чужий"], fast=False)
    assert _lines(slow), "перевірка беззмістовна: свіп нічого не знайшов"
    assert _lines(fast) == _lines(slow)
    assert fast["fast_runs"] == 2 and slow["fast_runs"] == 0


def test_a_zero_is_confirmed_by_the_trigram_sweep(space: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Передфільтр, що «нічого не знайшов», не має права сказати «немає»."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    monkeypatch.setattr(FX, "candidates", lambda *_a, **_k: [])
    stem = S._norm("Вербищинскій")
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert _lines(res), "нуль передфільтра пройшов без свіпу триграмами"
    assert res["fast_runs"] == 0


def test_a_run_changed_after_the_index_goes_by_the_old_road(space: Path) -> None:
    """Індекс доганяє стор за штампами; прогін, якого він ще не знає, шукається
    свіпом — швидкий канал не бреше про те, чого не бачив."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    d = space / "reports" / "htr" / "чужий"
    (d / "0002.txt").write_text("свідокъ Iванъ Вербищинскій\n", encoding="utf-8")
    meta = json.loads((d / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0002.jpg"] = {"lines": 1}
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(["чужий"]))
    conn = ST.connect()
    try:
        assert FX.covered(conn, [r for (r,) in conn.execute("select id from runs")]) != []
        ids = dict(conn.execute("select run, id from runs").fetchall())
        assert ids["чужий"] not in FX.covered(conn, list(ids.values()))
    finally:
        conn.close()
    stem = S._norm("Вербищинскій")
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert any(h["name"] == "чужий" for h in res["hits"])
    assert res["fast_runs"] == 1
    assert _build()["added"] == 1


def test_query_terms_follow_the_pilot_scheme() -> None:
    from nyshporka.search import fastidx as FX

    terms = FX.query_terms(["verbiscinskii"])
    assert ("c", "verbiscinskii", 2) in terms
    assert ("c", "erbiscinskii", 1) in terms and ("c", "biscinskii", 1) in terms
    assert ("x", "iiksnicsibrev", 2) in terms and ("y", "verbiscinskii", 2) in terms
    assert ("x", "iiksnicsib", 1) in terms and ("x", "iiksnicsibr", 1) in terms
    # Скорочені форми роду (скорочені форми) — через початок стему.
    assert ("c", "verbi", 1) in terms
    assert FX.query_terms(["sevcuk"]) == [("c", "sevcuk", 2), ("x", "kucves", 1),
                                         ("y", "sevcuk", 1)]


def test_query_terms_are_not_collapsed_by_prefix() -> None:
    """🔴 Префіксний режим Tantivy вужчий за модель «якийсь початок слова в межах
    d»: стем, що є початком іншого, НЕ покриває його (рецензія 20.10.2026 —
    `boliscikiego` бере `boliscinski`, але не `boliscinsk`). Тож прибираються лише
    повтори, і кожна форма роду йде в запит своїм термом."""
    from nyshporka.search import fastidx as FX

    stems = ["boliscinsk", "boliscinski", "boliscinskiego"]
    terms = FX.query_terms(stems)
    for s in stems:
        assert ("c", s, 2) in terms and ("y", s, 2) in terms
    assert len(terms) == len(set(terms))


def test_the_prefix_mode_of_tantivy_is_narrower_than_the_model(tmp_path: Path) -> None:
    """Сторож рішення вище: якщо колись Tantivy почне брати `boliscikiego` коротшим
    стемом, згортання можна буде повернути — а доти воно губить слова."""
    import tantivy

    sb = tantivy.SchemaBuilder()
    sb.add_text_field("c", stored=False, tokenizer_name="default", index_option="basic")
    idx = tantivy.Index(sb.build(), path=str(tmp_path))
    w = idx.writer(15_000_000, 1)
    w.add_document(tantivy.Document(c="boliscikiego"))
    w.commit()
    idx.reload()

    def hits(term: str) -> int:
        q = tantivy.Query.fuzzy_term_query(idx.schema, "c", term, distance=2,
                                           transposition_cost_one=True, prefix=True)
        return idx.searcher().search(q, limit=1, count=True).count or 0

    assert hits("boliscinski") == 1
    assert hits("boliscinsk") == 0


@pytest.mark.parametrize("word", [
    "Григорiймакiймелникъ",    # прізвище в КІНЦІ зліпленого слова — поле x
    "инанасаМелникаМи",        # посередині зліпленого слова — поле y
    "Хмелникъ",                # скалічений початок — x з обрізаним стемом
])
def test_the_three_shapes_of_a_mangled_surname_are_found(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, word: str) -> None:
    """🔴 Заради цього в рядка три поля: префіксний автомат бачить лише початок
    терма, а прізвище в шумному декоді сидить у слові скрізь (заміри 20.10.2026)."""
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "reports" / "htr" / "проба"
    d.mkdir(parents=True)
    (d / "0001.txt").write_text(f"свідки були\n{word} зъ села\n", encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "pages": {"0001.jpg": {"lines": 2}}}), encoding="utf-8")
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    try:
        list(ST.ensure_all(["проба"]))
        conn = ST.connect()
        try:
            FX.sync(conn)
        finally:
            conn.close()
        stem = S._norm("Мельник")
        assert (FX.candidates([stem]) or [None])[0] is not None, f"не знайдено: {word}"
        assert [h["line_no"] for h in ST.sweep([stem], ["проба"], fast=True)["hits"]] == [2]
    finally:
        W.reset()


def test_an_index_of_another_schema_is_rebuilt_not_appended(space: Path) -> None:
    """Старий індекс (документ-сторінка, стан без `schema`) не доповнюється рядками:
    його сегменти іншої схеми, і запит до суміші бреше."""
    from nyshporka.search import fastidx as FX

    old = FX.path()
    old.mkdir(parents=True)
    (old / FX.STATE).write_text('{"1": "старий штамп"}', encoding="utf-8")
    (old / "сегмент.idx").write_text("чужа схема", encoding="utf-8")
    assert not FX.exists()
    assert _build()["added"] == 2
    assert not (old / "сегмент.idx").exists()
    assert FX.exists()


def test_a_folder_without_state_is_not_wiped(space: Path) -> None:
    """🔴 Тека без `runs.json` — найпевніше, перша збірка в іншому процесі, що ще
    не дійшла до коміту. Стерти її означало б вирвати теку з-під письменника."""
    from nyshporka.search import fastidx as FX

    d = FX.path()
    d.mkdir(parents=True)
    (d / "чужий.lock").write_text("пише інший процес", encoding="utf-8")
    _build()
    assert (d / "чужий.lock").exists()


def test_rules_rebuild_without_stamp_change_is_not_covered(space: Path) -> None:
    """Стор перебудовує прогін і за правилами склейки, не міняючи штампа мети:
    індекс такого прогону вже не свіжий (рецензія 20.10.2026)."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    conn = ST.connect()
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        assert sorted(FX.covered(conn, ids)) == sorted(ids)
        conn.execute("update runs set rules='інше-правило' where id=?", (ids[0],))
        conn.commit()
        assert ids[0] not in FX.covered(conn, ids)
    finally:
        conn.close()


def test_a_broken_index_falls_back_to_the_sweep(space: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Індекс лише прискорює: його збій не валить пошук, ті самі прогони йдуть свіпом."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()

    def broken(*_a, **_k):
        raise OSError("індекс побито")

    monkeypatch.setattr(FX, "by_run", broken)
    stem = S._norm("Вербищинскій")
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert _lines(res) and res["fast_runs"] == 0


def test_no_state_is_an_error_not_an_empty_answer(space: Path) -> None:
    """Порожня відповідь без стану лягла б у кеш як «тут нічого» — тож помилка."""
    from nyshporka.search import fastidx as FX

    with pytest.raises(OSError):
        FX.by_run(["verbiscinskii"])


def test_parallel_rerank_gives_the_same_rows(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Дооцінка воркерами — ті самі рядки й бали, що в одному процесі."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    _build()
    stem = S._norm("Вербищинскій")
    conn = ST.connect(readonly=True)
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        one = ST._sweep_fast(conn, [stem], ids, 78)
        monkeypatch.setattr(ST, "FAST_PARALLEL_PAGES", 1)
        monkeypatch.setattr(ST, "FAST_CHUNK_PAGES", 1)
        monkeypatch.setenv("NYSH_SWEEP_WORKERS", "2")
        many = ST._sweep_fast(conn, [stem], ids, 78)
    finally:
        conn.close()
    assert any(one.values()), "перевірка беззмістовна: нічого не знайшлось"
    assert {k: sorted(v) for k, v in one.items()} == {k: sorted(v) for k, v in many.items()}


def test_threaded_query_gives_the_same_candidates(space: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Терми частинами в потоках — та сама множина рядків, що одним запитом."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX

    _build()
    stems = [S._norm("Вербищинскій"), S._norm("Шевчук")]
    monkeypatch.setattr(FX, "QUERY_THREADS", 1)
    FX._ANSWERS.clear()
    one = FX.candidates(stems)
    monkeypatch.setattr(FX, "QUERY_THREADS", 4)
    FX._ANSWERS.clear()
    many = FX.candidates(stems)
    assert one and one == many
