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
    monkeypatch.setattr(FX, "by_run", lambda *_a, **_k: {})
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
    "Мел=никъ",                # знак усередині слова (`=` Скриби) — не роздільник
    "Мел҃никъ",           # титло всередині слова — теж
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


def test_a_run_rebuilt_by_the_store_is_not_covered(space: Path) -> None:
    """Стор перебудовує прогін і за правилами склейки, не міняючи штампа мети:
    індекс такого прогону вже не свіжий (рецензія 20.10.2026). Ознака — новий
    `indexed_at`, який стор ставить на кожну збірку прогону."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    conn = ST.connect()
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        assert sorted(FX.covered(conn, ids)) == sorted(ids)
        conn.execute("update runs set indexed_at='2099-01-01T00:00:00.000001' where id=?",
                     (ids[0],))
        conn.commit()
        assert ids[0] not in FX.covered(conn, ids)
    finally:
        conn.close()


def test_accepting_the_rules_does_not_rebuild_the_fast_index(space: Path) -> None:
    """🔴 `text index --accept-rules` («правила не мінялись») писав новий відбиток
    на кожен прогін, а відбиток входив у позначку індексу: приймання правил
    коштувало перебудови всього індексу (25.10.2026: 16 тис. прогонів, 33 ГБ).
    Текст той самий — індекс не чіпається."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    conn = ST.connect()
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        conn.execute("update runs set rules='інше-правило'")
        conn.commit()
        assert sorted(FX.covered(conn, ids)) == sorted(ids)
        got = FX.sync(conn)
        assert got["added"] == 0 and got["lines"] == 0
    finally:
        conn.close()


def test_entries_with_the_rules_in_the_mark_stay_covered(space: Path) -> None:
    """Позначки 24–25.10.2026 (`at:<t>|<правила>`) — той самий текст."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    conn = ST.connect()
    try:
        old = {int(r[0]): f"at:{r[1]}|{r[2] or ''}"
               for r in conn.execute("select id, indexed_at, rules from runs")}
        FX._save_state(old)
        assert sorted(FX.covered(conn, list(old))) == sorted(old)
        assert FX.sync(conn)["added"] == 0
        assert all("|" not in v for v in FX.state().values()), "позначки переведено"
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


def test_a_too_broad_query_goes_by_the_sweep_before_collecting(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Короткий стем бере п'яту частину корпусу, і збір відповіді валив процес
    відмовою пам'яті в Rust (20.10.2026). Ширший за межу запит не збирається —
    ті самі рядки дає свіп, а серія не перераховує його на кожній справі."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    stem = S._norm("Вербищинскій")
    slow = ST.sweep([stem], ["проба", "чужий"], fast=False)
    conn = ST.connect()
    try:
        # Кеш свіпу віддав би відповідь, не питаючи індексу.
        conn.execute("delete from sweeps")
        conn.commit()
    finally:
        conn.close()
    FX._ANSWERS.clear()
    FX._BROAD.clear()
    monkeypatch.setattr(FX, "MAX_HITS", 0)
    collected: list[int] = []
    real_collect = FX._collect_part
    monkeypatch.setattr(FX, "_collect_part",
                        lambda *a: collected.append(1) or real_collect(*a))
    with pytest.raises(FX.TooBroad):
        FX.by_run([stem])
    assert not collected, "відповідь збиралась, хоч запит ширший за межу"
    counted: list[int] = []
    real_count = FX._count_part
    monkeypatch.setattr(FX, "_count_part", lambda *a: counted.append(1) or real_count(*a))
    with pytest.raises(FX.TooBroad):
        FX.by_run([stem])
    assert not counted, "заширокий запит перераховано вдруге"
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert _lines(slow), "перевірка беззмістовна: свіп нічого не знайшов"
    assert _lines(res) == _lines(slow) and res["fast_runs"] == 0
    FX._BROAD.clear()


def test_no_state_is_an_error_not_an_empty_answer(space: Path) -> None:
    """Порожня відповідь без стану лягла б у кеш як «тут нічого» — тож помилка."""
    from nyshporka.search import fastidx as FX

    with pytest.raises(OSError):
        FX.by_run(["verbiscinskii"])


def test_text_state_shows_an_index_that_fell_behind(space: Path) -> None:
    """🔴 Відставання індексу пошук не бреше, але й не показує: його каже `text.state`."""
    from nyshporka.ops_text import TextStateArgs, text_state
    from nyshporka.search import fastidx as FX

    _build()
    env = text_state(TextStateArgs())
    fast = env.data["fast"]
    assert {k: fast[k] for k in ("schema", "fresh", "runs", "covered", "behind")} == {
        "schema": FX.SCHEMA, "fresh": True, "runs": 2, "covered": 2, "behind": False}
    assert fast["segments"] >= 1 and fast["merge_pending_docs"] == 0
    assert "fast_behind" not in [w.code for w in env.warnings]
    # Перерваний догін: позначка прогону в стані вже не та, що в сторі.
    st = json.loads((FX.path() / FX.STATE).read_text(encoding="utf-8"))
    first = next(iter(st["runs"]))
    st["runs"][first] = "застаріла|позначка"
    (FX.path() / FX.STATE).write_text(json.dumps(st), encoding="utf-8")
    env = text_state(TextStateArgs())
    assert env.data["fast"]["covered"] == 1 and env.data["fast"]["behind"]
    assert "fast_behind" in [w.code for w in env.warnings]


def test_parallel_build_gives_the_same_index(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Текст полів воркерами — ті самі кандидати, що й збірка в одному процесі."""
    import concurrent.futures as CF
    import shutil

    from nyshporka import htr_store as S
    from nyshporka.core import cpu
    from nyshporka.search import fastidx as FX

    stems = [S._norm("Вербищинскій"), S._norm("Шевчук")]
    _build()
    one = sorted(FX.candidates(stems))
    shutil.rmtree(FX.path())
    FX._ANSWERS.clear()
    pools: list[int] = []
    real = CF.ProcessPoolExecutor

    class Spy(real):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            pools.append(kw.get("max_workers") or 0)
            super().__init__(*a, **kw)

    monkeypatch.setattr(FX, "PARALLEL_PAGES", 0)
    monkeypatch.setattr(cpu, "usable_cores", lambda: 8)
    monkeypatch.setenv("NYSH_SWEEP_WORKERS", "2")
    monkeypatch.setattr(CF, "ProcessPoolExecutor", Spy)
    got = _build()
    assert pools == [2], "воркери не стартували — тест міряв би послідовний шлях"
    assert got["added"] == 2
    assert len(one) >= 2, "перевірка беззмістовна: замало кандидатів"
    assert sorted(FX.candidates(stems)) == one


def test_parallel_rerank_gives_the_same_rows(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Дооцінка воркерами — ті самі рядки й бали, що в одному процесі."""
    import concurrent.futures as CF

    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    _build()
    stems = [S._norm("Вербищинскій"), S._norm("Шевчук")]
    pools: list[int] = []
    real = CF.ProcessPoolExecutor

    class Spy(real):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            pools.append(kw.get("max_workers") or 0)
            super().__init__(*a, **kw)

    conn = ST.connect(readonly=True)
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        one = ST._sweep_fast(conn, stems, ids, 78)
        monkeypatch.setattr(ST, "FAST_PARALLEL_PAGES", 1)
        monkeypatch.setattr(ST, "FAST_CHUNK_PAGES", 1)
        monkeypatch.setenv("NYSH_SWEEP_WORKERS", "2")
        monkeypatch.setattr(CF, "ProcessPoolExecutor", Spy)
        many = ST._sweep_fast(conn, stems, ids, 78)
    finally:
        conn.close()
    assert pools == [2], "воркери не стартували — тест міряв би послідовний шлях"
    assert sum(len(v) for v in one.values()) >= 2, "перевірка беззмістовна: замало знайденого"
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


def test_a_stop_caches_nothing(space: Path) -> None:
    """«Стоп» посеред швидкого каналу: пошук каже, що спинений, і обірвана
    відповідь не лягає в кеш як повна (рецензія 20.10.2026)."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    _build()
    stem = S._norm("Вербищинскій")
    res = ST.sweep([stem], ["проба", "чужий"], fast=True, cancel=lambda: True)
    assert res["cancelled"] is True
    conn = ST.connect(readonly=True)
    try:
        assert conn.execute("select count(*) from sweeps where key like ?",
                            ("%" + ST.FAST_KEY_SUFFIX + "%",)).fetchone()[0] == 0
    finally:
        conn.close()


def test_a_fast_zero_is_confirmed_even_beside_cached_hits(space: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Хіти з кешу свіпу по ІНШОМУ прогону області не підтверджують нуля
    швидкого каналу: ці прогони однаково проходить свіп (рецензія 20.10.2026)."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    d = space / "reports" / "htr" / "чужий"
    (d / "0002.txt").write_text("свідокъ Шевчукъ\n", encoding="utf-8")
    meta = json.loads((d / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0002.jpg"] = {"lines": 1}
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    _build()
    stem = S._norm("Шевчук")
    assert ST.sweep([stem], ["чужий"], fast=False)["hits"], "кеш свіпу не наповнився"
    monkeypatch.setattr(FX, "by_run", lambda *_a, **_k: {})
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert {h["name"] for h in res["hits"]} == {"проба", "чужий"}


def test_free_memory_lowers_the_hit_limit(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Слабка машина: межу збігів знижує вільна пам'ять, і запит іде свіпом — ті самі рядки."""
    from types import SimpleNamespace

    import psutil

    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    stem = S._norm("Вербищинскій")
    slow = ST.sweep([stem], ["проба", "чужий"], fast=False)
    monkeypatch.setattr(psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=10 ** 12))
    assert FX.max_hits() == FX.MAX_HITS                  # багато пам'яті — стеля
    monkeypatch.setattr(psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=FX.HIT_BYTES))
    assert FX.max_hits() == 0                            # пам'яті ні на що
    conn = ST.connect()
    try:
        conn.execute("delete from sweeps")
        conn.commit()
    finally:
        conn.close()
    FX._ANSWERS.clear()
    FX._BROAD.clear()
    with pytest.raises(FX.TooBroad):
        FX.by_run([stem])
    res = ST.sweep([stem], ["проба", "чужий"], fast=True)
    assert _lines(slow) and _lines(res) == _lines(slow) and res["fast_runs"] == 0
    # відмову дала пам'ять цього моменту — у кеш вона не лягає
    assert not FX._BROAD
    monkeypatch.setattr(psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=10 ** 12))
    assert FX.by_run([stem])
    FX._BROAD.clear()


def test_answer_pairs_are_sorted_within_each_run(space: Path) -> None:
    """Збір іде без порядку поля (пам'ять) — порядок пар наводить `by_run`."""
    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX

    _build()
    FX._ANSWERS.clear()
    got = FX.by_run([S._norm("Вербищинскій"), S._norm("Шевчук")])
    assert got and all(pairs == sorted(pairs) for pairs in got.values())


def test_a_meta_only_change_does_not_rebuild_the_fast_index(space: Path) -> None:
    """Стор оновлює штамп, коли змінилась лише мета; індекс — не перебудовує.

    🔴 Правка мет 9 361 прогону (23.10.2026) змушувала індекс перебудовувати їх
    усі — години й гігабайти пам'яті, — хоч текст той самий.
    """
    import os
    import time

    from nyshporka import htr_store as S
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    old = time.time() - 3600
    for f in (space / "reports" / "htr").rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))
    _build()
    d = space / "reports" / "htr" / "чужий"
    meta = json.loads((d / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["project"] = ""
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    got = _build()
    assert got["added"] == 0, "лише мета — індекс не перебудовано"
    conn = ST.connect()
    try:
        ids = [r for (r,) in conn.execute("select id from runs")]
        assert sorted(FX.covered(conn, ids)) == sorted(ids)
    finally:
        conn.close()


def test_entries_written_with_stamps_move_to_the_text_mark_without_a_rebuild(space: Path) -> None:
    """Індекс, зібраний до 0.37, ключував прогони штампом; збіг — той самий текст."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    _build()
    conn = ST.connect()
    try:
        legacy = {int(r[0]): f"{r[1]}|{r[2] or ''}"
                  for r in conn.execute("select id, stamp, rules from runs")}
        FX._save_state(legacy)
        assert sorted(FX.covered(conn, list(legacy))) == sorted(legacy), "давні записи — охоплені"
        got = FX.sync(conn)
        assert got["added"] == 0
        assert all(v.startswith("at:") for v in FX.state().values())
    finally:
        conn.close()


def test_a_scoped_sync_takes_only_the_named_runs(space: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """`text index --case X` доганяє швидкий індекс лише для X: доти він доганяв
    увесь корпус і чекав на злиття сегментів — хвилини на кожну справу
    (25.10.2026). Решта прогонів лишається неохопленою до повного догону."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    assert list(ST.ensure_all(["проба", "чужий"])) == ["проба", "чужий"]
    conn = ST.connect()
    try:
        ids = {r: int(i) for i, r in conn.execute("select id, run from runs")}
        got = FX.sync(conn, only={ids["проба"]})
        assert got["added"] == 1
        assert FX.covered(conn, list(ids.values())) == [ids["проба"]]
        full = FX.sync(conn)
        assert full["added"] == 1, "повний догін бере те, що точковий лишив"
        assert sorted(FX.covered(conn, list(ids.values()))) == sorted(ids.values())
    finally:
        conn.close()


def test_text_index_for_a_case_does_not_touch_other_runs(space: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.ops_text import _fast_sync
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    list(ST.ensure_all(["проба", "чужий"]))
    got = _fast_sync(True, ["чужий"])
    assert got["added"] == 1 and not got.get("error")
    conn = ST.connect()
    try:
        ids = {r: int(i) for i, r in conn.execute("select id, run from runs")}
        assert FX.covered(conn, list(ids.values())) == [ids["чужий"]]
    finally:
        conn.close()


# ── політика сегментів, замок письменника, догоняння ────────────────────────
def _more_runs(space: Path, n: int) -> list[str]:
    """Ще `n` малих прогонів у просторі (стор збирає їх звичайним шляхом)."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    names = []
    for i in range(n):
        name = f"малий{i:02d}"
        d = space / "reports" / "htr" / name
        d.mkdir(parents=True)
        (d / "0001.txt").write_text(f"въ селѣ Вербівцахъ\nродился Иванъ {i} Вербищинскій\n",
                                    encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps({
            "model": "pysar_cyr_v17.pt", "script": "cyrillic",
            "pages": {"0001.jpg": {"lines": 2}}}), encoding="utf-8")
        names.append(name)
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(names))
    return names


def _ids(conn, names: list[str]) -> dict[str, int]:
    return {r: int(i) for i, r in conn.execute("select id, run from runs") if r in names}


def test_point_syncs_keep_the_segment_count_bounded(space: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Точковий догін без злиття: кожна справа — нові сегменти, і після сотень
    справ пошук ходить по тисячах (tantivy-py не вміє злити вибране, а типове
    злиття вмирає разом із письменником, якого кидають одразу після коміту)."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)    # інакше перша справа забере всі
    names = _more_runs(space, 30)
    conn = ST.connect()
    try:
        ids = _ids(conn, names)
        worst = 0
        for rid in ids.values():
            FX.sync(conn, only={rid})
            worst = max(worst, len(FX.segment_docs()))
        assert worst < 2 * FX.MERGE_MIN_SEGMENTS, f"сегментів до {worst}: злиття не відбувається"
        assert sorted(FX.covered(conn, list(ids.values()))) == sorted(ids.values())
    finally:
        conn.close()


def test_without_the_merge_wait_segments_pile_up(space: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Контроль до попереднього: з нульовою межею очікування сегменти ростуть."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    monkeypatch.setattr(FX, "MERGE_WAIT_DOCS", -1)
    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    names = _more_runs(space, 30)
    conn = ST.connect()
    try:
        for rid in _ids(conn, names).values():
            FX.sync(conn, only={rid})
        assert len(FX.segment_docs()) >= 30
    finally:
        conn.close()


def test_merge_plan_matches_tantivy(tmp_path: Path) -> None:
    """Розрахунок злиття (`merge_plan`) збігається з тим, що робить Tantivy."""
    import tantivy

    from nyshporka.search import fastidx as FX

    d = tmp_path / "idx"
    d.mkdir()
    index = tantivy.Index(FX._schema(), path=str(d), reuse=True)
    index.register_tokenizer(FX.TOKENIZER, FX._analyzer())
    for rid, n in enumerate([30] * 9 + [12_000] * 3 + [500] * 2, 1):
        w = index.writer(15_000_000, 1)
        for i in range(n):
            w.add_document(tantivy.Document(pid=rid, ln=i, run=rid, c="слово", x="овол", y=""))
        w.commit()
        del w

    def segments() -> list[tuple[int, int]]:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return [(s["max_doc"], s["max_doc"] - ((s.get("deletes") or {}).get("num_deleted_docs") or 0))
                for s in meta["segments"]]

    before = segments()
    plan = FX.merge_plan(before)
    assert plan, "перевірка беззмістовна: нема що зливати"
    w = index.writer(15_000_000, 1)
    w.commit()
    w.wait_merging_threads()
    after = segments()
    merged = {x for g in plan for x in g}
    kept = [sg for sg in before if sg[1] not in merged]
    expect = sorted(kept + [(sum(g), sum(g)) for g in plan])
    assert sorted(after) == expect
    assert FX.merge_plan(after) == []


def test_merge_plan_leaves_giant_levels_to_the_full_sync() -> None:
    """Вісім сегментів по 6–10 млн — це години; 8 малих — секунди: ціна різна."""
    from nyshporka.search import fastidx as FX

    small = [(30, 30)] * 8
    giant = [(8_000_000, 8_000_000)] * 8
    assert FX.merge_cost(small) == 240 <= FX.MERGE_WAIT_DOCS
    assert FX.merge_cost(giant) == 64_000_000 > FX.MERGE_WAIT_DOCS
    # Сегмент понад межу не зливається нізащо; сім — ще не рівень.
    assert FX.merge_cost([(11_000_000, 11_000_000)] * 20) == 0
    assert FX.merge_cost(giant[:7]) == 0


def test_an_expensive_merge_is_not_awaited_and_is_named(space: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.ops_text import TextIndexArgs, text_index
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    names = _more_runs(space, 10)
    monkeypatch.setattr(FX, "MERGE_WAIT_DOCS", 0)
    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    conn = ST.connect()
    try:
        for rid in [i for n, i in _ids(conn, names).items() if n != names[-1]]:
            got = FX.sync(conn, only={rid})
        assert got["merge_pending_docs"] > 0, "дорога каскада названа у відповіді"
    finally:
        conn.close()
    env = text_index(TextIndexArgs(case=names[-1]))
    assert "fast_merge_due" in [w.code for w in env.warnings]
    assert env.data["fast"]["merge_pending_docs"] > 0


def test_the_full_sync_merges_even_when_there_is_nothing_to_add(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`text index --fast` на вже догнаному індексі мусить зливати: інакше
    чекаюче злиття ніхто ніколи не зробить."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    names = _more_runs(space, 12)
    monkeypatch.setattr(FX, "MERGE_WAIT_DOCS", -1)
    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    conn = ST.connect()
    try:
        for rid in _ids(conn, names).values():
            FX.sync(conn, only={rid})
        piled = len(FX.segment_docs())
        assert piled >= 12 and FX.segments_state()["merge_pending_docs"] > 0
        got = FX.sync(conn)
        assert got["added"] == len([r for r in conn.execute("select 1 from runs")]) - 12
        got = FX.sync(conn)
        assert got["added"] == 0
        assert len(FX.segment_docs()) < piled
        assert FX.segments_state()["merge_pending_docs"] == 0
    finally:
        conn.close()


def test_a_busy_writer_is_waited_for_a_while(space: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Наглядачі хмари кличуть `text index --case` одночасно: чужий точковий
    догін триває секунди, і пропускати свою справу через нього — марно."""
    import threading
    import time

    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    names = _more_runs(space, 2)
    conn = ST.connect()
    try:
        ids = _ids(conn, names)
        FX.sync(conn, only={ids[names[0]]})
        box = [FX._open(create=False).writer(15_000_000, 1)]
        assert FX.sync(conn, only={ids[names[1]]})["busy"] is True, "без очікування — busy"

        def free() -> None:
            time.sleep(1.0)
            box.clear()            # писаря відпущено: замок вільний

        t = threading.Thread(target=free)
        t.start()
        started = time.monotonic()
        got = FX.sync(conn, only={ids[names[1]]}, lock_wait=15)
        t.join()
        assert got["busy"] is False and got["added"] == 1
        assert time.monotonic() - started >= 0.9, "чекав, а не пройшов повз замок"
    finally:
        conn.close()


def test_a_run_missed_by_busy_is_caught_up_by_the_next_scoped_sync(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Справа, що отримала `busy`, догонялась лише власним повтором. Тепер
    наступний точковий догін ІНШОЇ справи бере й її (в межах `CATCHUP_LINES`)."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    default = FX.CATCHUP_LINES
    monkeypatch.setattr(FX, "CATCHUP_LINES", 0)
    names = _more_runs(space, 3)
    conn = ST.connect()
    try:
        ids = _ids(conn, names)
        a, b, c = (ids[n] for n in names)
        FX.sync(conn, only={a})
        holder = FX._open(create=False).writer(15_000_000, 1)
        assert FX.sync(conn, only={b})["busy"] is True       # b пропущено
        del holder
        assert b not in FX.covered(conn, [a, b, c])
        monkeypatch.setattr(FX, "CATCHUP_LINES", default)
        got = FX.sync(conn, only={c})
        assert got["catchup"] >= 1
        assert {b, c} <= set(FX.covered(conn, [a, b, c]))
    finally:
        conn.close()


def test_catchup_takes_the_small_leftovers_first_and_within_the_budget(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    names = _more_runs(space, 3)
    conn = ST.connect()
    try:
        ids = _ids(conn, names)
        sizes = {rid: n for rid, n in conn.execute("select id, lines from runs")}
        a, b, c = (ids[n] for n in names)
        conn.execute("update runs set lines=1000000 where id=?", (b,))
        conn.commit()
        monkeypatch.setattr(FX, "CATCHUP_LINES", sizes[c] + 1)
        got = FX.sync(conn, only={a})
        assert got["catchup"] == 1
        cov = set(FX.covered(conn, [a, b, c]))
        assert a in cov and c in cov and b not in cov, "великий хвіст не вписався в межу"
    finally:
        conn.close()


def test_a_scoped_sync_does_not_wipe_an_index_of_another_schema(space: Path) -> None:
    """🔴 Старий індекс точково не зноситься: індекс з однією справою виглядав би
    повним, а решту корпусу пошук мовчки брав би свіпом."""
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    names = _more_runs(space, 1)
    old = FX.path()
    old.mkdir(parents=True)
    (old / FX.STATE).write_text('{"schema": 1, "runs": {"1": "x"}}', encoding="utf-8")
    (old / "сегмент.idx").write_text("чужа схема", encoding="utf-8")
    conn = ST.connect()
    try:
        got = FX.sync(conn, only={_ids(conn, names)[names[0]]})
    finally:
        conn.close()
    assert got["schema_old"] and got["added"] == 0
    assert (old / "сегмент.idx").exists()


def test_a_small_scoped_sync_uses_one_writer_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кожен потік письменника лишає свій сегмент: малій справі — один."""
    from nyshporka.search import fastidx as FX

    monkeypatch.setattr(FX, "_writer_threads", lambda: 8)
    assert FX._point_threads(5_000) == 1
    assert FX._point_threads(250_000) == 2
    assert FX._point_threads(50_000_000) == 8


def test_scoped_store_stats_count_only_the_named_runs(space: Path) -> None:
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба", "чужий"]))
    one = ST.stats(["проба"])
    both = ST.stats()
    assert (one["runs"], one["indexed"], one["stale"]) == (1, 1, 0)
    assert both["runs"] == 2
    assert one["pages"] == both["pages"], "розмір стору — цілого"


def test_text_index_for_a_case_never_optimizes_the_whole_store(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 `optimize` FTS зливає сегменти ВСЬОГО стору під замком на запис: на 52 ГБ
    `--rebuild --case X` висів годинами. Для названої справи його нема; без справи
    (повна збірка) — лишається."""
    from nyshporka.ops_text import TextIndexArgs, text_index
    from nyshporka.search import store as ST

    seen: list[object] = []
    real = ST.ensure_all
    monkeypatch.setattr(ST, "ensure_all",
                        lambda runs, **kw: seen.append(kw.get("optimize")) or real(runs, **kw))
    text_index(TextIndexArgs(case="проба", rebuild=True))
    text_index(TextIndexArgs(rebuild=True))
    assert seen == [False, None]
