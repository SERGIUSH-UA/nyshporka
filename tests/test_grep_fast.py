"""`text grep` швидший, а відповідь та сама.

Еталон — заморожена копія `store.grep` до прискорення (main 528c0b6): ті самі
хіти в тому самому порядку, той самий підсумок і знаменник. Розгорнутий
передфільтр має право читати МЕНШЕ сторінок, але не має права загубити рядок.
"""
from __future__ import annotations

import json
import random
import re
import zlib
from pathlib import Path
from typing import Any

import pytest

from nyshporka.search import store as ST

#: Вигадана родина й вигадані села — правило публічного пакета.
PAGES = {
    "проба-а": [
        "въ селѣ Тихій Бродъ родился Иванъ\nотецъ Петръ Ковальчинскій\nмать Анна",
        "Ковальчинская Марія\nвоспріемникъ Іосифъ Кавальчинскій",
        "Тихобродская волость\nКовальчинскихъ дворъ",
    ],
    "проба-б": [
        "Kowalczynski Józef\nTichy Brod 1858",
        "умре Стефанъ Ковальчинскій\nлѣтъ 54\nИ поховано",
        "Ковальчинск\nій Григорій\nИванъ Ковалинскій",
        "воспріемникъ Онисимъ\nКавальчинскій Тихобродскій",
    ],
    "проба-в": [
        "Іосифъ Ковальчинскій и Іосифъ Кавальчинскій\nсвидѣтели",
        "",
        "Тихій Бродъ\nТихій Бродъ\nКовальчинскій",
    ],
}

PATTERNS = [
    "Ковальчинск", "(Ков|Кав)альчинск", "К.вальчинск", "К[оа]вальчинск",
    "^Ковальчинск", "чинск(ій|ая|ихъ)$", "(?<!о)Ковальчинск", r"\bКов\w+скій",
    "Тих[ії]", "Іосифъ|Józef", "Kowalcz|Kawalcz", r"\d{2,4}", r"\AИ",
    r"Брод(?!ъ)", r"(?<!\s)Ков", "(?i)тихій", "Ков(альч|алин)ск", "Ков(аль)?чинск",
]


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    for run, pages in PAGES.items():
        d = tmp_path / "reports" / "htr" / run
        d.mkdir(parents=True)
        meta: dict[str, Any] = {"model": "pysar_cyr_v17.pt", "script": "cyrillic", "pages": {}}
        for n, text in enumerate(pages, 1):
            (d / f"{n:04}.txt").write_text(text + "\n", encoding="utf-8")
            meta["pages"][f"{n:04}.jpg"] = {"lines": text.count("\n") + 1}
        (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(list(PAGES)))
    yield tmp_path
    W.reset()


def _reference(pattern: str, runs: list[str], *, ignore_case: bool = True,
               limit: int = 200, context: int = 0) -> dict[str, Any]:
    """`store.grep` до прискорення, дослівно (лише `_pages_of` вкладено)."""
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return {"hits": [], "error": f"регекс не розбирається: {exc}"}
    conn = ST.connect(readonly=True)
    try:
        ids: dict[str, int] = {}
        for run in runs:
            row = conn.execute("select id, stamp from runs where run=?", (run,)).fetchone()
            if row and row[1] == ST.stamp_of(run):
                ids[run] = int(row[0])
        by_id = {v: k for k, v in ids.items()}
        lits = ST.literals_of(pattern)
        phrases: list[str] = []
        for lit in lits or []:
            n = ST._norm(ST._literal_core(lit))
            if len(n) >= 3:
                phrases.append(f'"{n}"')
        if lits and len(phrases) == len(lits):
            expr = " OR ".join(phrases)
            raw_pids = {rid >> ST.LINE_BITS for (rid,) in ST._fts_rows(conn, expr, list(ids.values()))}
            pages = ST._pages_for(conn, raw_pids, set(ids.values()))
            prefiltered = True
        else:
            pages = {}
            for rid in ids.values():
                for pid, page in conn.execute("select id, page from pages where run_id=?", (rid,)):
                    pages[int(pid)] = (rid, page)
            prefiltered = False
        pids = set(pages)
        hits: list[dict[str, Any]] = []
        total = 0
        scanned_pages = 0
        for pid in sorted(pids):
            raw = ST._raw_lines(conn, pid)
            scanned_pages += 1
            rid_, page = pages[pid]
            for i, ln in enumerate(raw, 1):
                if not rx.search(ln):
                    continue
                total += 1
                if len(hits) >= limit:
                    continue
                h: dict[str, Any] = {"name": by_id[rid_], "page": page, "line_no": i,
                                     "line_index": i - 1, "line": ln}
                if context:
                    h["before"] = raw[max(0, i - 1 - context):i - 1]
                    h["after"] = raw[i:i + context]
                hits.append(h)
        n_pages = (len(pages) if not prefiltered
                   else int(conn.execute(
                       f"select coalesce(sum(pages),0) from runs where id in "
                       f"({','.join('?' * len(ids))})", list(ids.values())).fetchone()[0])
                   if ids else 0)
        return {"hits": hits, "total": total, "runs": len(ids),
                "runs_asked": len(runs), "unindexed": len(runs) - len(ids),
                "pages": n_pages, "pages_scanned": scanned_pages,
                "prefiltered": prefiltered, "literals": lits or [],
                "literal_pages": len(pids) if prefiltered else None}
    finally:
        conn.close()


_NARROWS = ("pages_scanned", "literal_pages")


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("pattern", PATTERNS)
def test_grep_answers_like_before(space: Path, pattern: str, bulk: bool,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    if bulk:
        monkeypatch.setattr(ST, "BULK_RUNS", 1)
    runs = [*PAGES, "немає-такого"]
    for limit, context in ((200, 1), (2, 0)):
        want = _reference(pattern, runs, limit=limit, context=context)
        got = ST.grep(pattern, runs, limit=limit, context=context)
        assert {k: v for k, v in got.items() if k not in _NARROWS} == \
            {k: v for k, v in want.items() if k not in _NARROWS}, pattern
        if want["prefiltered"]:
            assert got["pages_scanned"] <= want["pages_scanned"]
            if want["total"]:
                assert got["literal_pages"] is None
            else:
                # цілий літерал (кожного варіанта) у нормі — не вікно передфільтра
                assert got["literal_pages"] is not None
                assert got["literal_pages"] <= want["literal_pages"]
                if ST._variants(pattern) == [pattern]:
                    assert got["literal_pages"] == want["literal_pages"]
        else:
            assert got["pages_scanned"] == want["pages_scanned"]


def test_grep_one_run_without_literal_scans_its_pages_only(space: Path) -> None:
    got = ST.grep(r"\d{2,4}", ["проба-б"])
    assert got == _reference(r"\d{2,4}", ["проба-б"])
    assert got["pages_scanned"] == 4 and got["total"] == 2


def test_alternation_prefilter_reads_fewer_pages(space: Path) -> None:
    """«(Ков|Кав)…» — передфільтр за обома варіантами, а не за хвостом «альчинск»."""
    old = _reference("(Ков|Кав)альчинскій", list(PAGES))
    new = ST.grep("(Ков|Кав)альчинскій", list(PAGES))
    assert new["hits"] == old["hits"]
    phrases = ST._prefilter_phrases("(Ков|Кав)альчинскій")
    assert phrases is not None and len(phrases) == 2


def test_variants_expand_only_plain_unquantified_groups() -> None:
    assert ST._variants("(Ков|Кав)альч") == ["Ковальч", "Кавальч"]
    assert ST._variants("(?:ов|ев|)ичъ") == ["овичъ", "евичъ", "ичъ"]
    assert ST._variants("К[оа]в[аі]ль") == ["Коваль", "Ковіль", "Каваль", "Кавіль"]
    # вкладена група — зсередини назовні, без дублів
    got = ST._variants("((К|Г)ов|Кав)альч")
    assert sorted(got) == sorted(["Ковальч", "Говальч", "Кавальч"]) and len(got) == 3
    # квантифікатор, екранування, клас з діапазоном — як є
    for p in ("(Ков|Кав)?альч", r"\(Ков|Кав\)", "К[а-я]вальч", "К[оа]+вальч"):
        assert ST._variants(p) == [p]
    many = "(а|б)(в|г)(д|е)(є|ж)(з|и)(і|ї)"            # 64 > VARIANTS_MAX
    assert len(ST._variants(many)) <= ST.VARIANTS_MAX


def test_prefilter_refuses_when_any_variant_has_no_literal() -> None:
    assert ST._prefilter_phrases("(Ков|К)альч") is not None
    assert ST._prefilter_phrases("(Ковальч|..)") is None
    assert ST._prefilter_phrases(r"\bДо\w+ск") is None


def test_page_gate_never_drops_a_line_match() -> None:
    """Збіг у рядку ⇒ збіг у тексті сторінки — для всього, що `_line_gate_safe` пускає.

    Небезпечні конструкції тут перелічено навмисно: для кожної знайдено рядок,
    де відсів сторінки загубив би збіг.
    """
    rng = random.Random(5)
    alphabet = "аоКвль ъ\t1"
    safe = ["К.в", "^Кав", "ль$", r"\bКов", r"(?<=\s)К", r"К(?=о)", r"\sК",
            r"[^а]К", r"К\W", r"(?s)К.в", r"\Bл", "ъ$", r"^\s*$", r"\S+$"]
    for _ in range(3000):
        lines = ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
                 for _ in range(rng.randint(1, 4))]
        text = "\n".join(lines)
        for p in safe:
            assert ST._line_gate_safe(p)
            if any(re.search(p, ln) for ln in lines):
                assert re.search(p, text, re.MULTILINE), (p, lines)
    for p, lines in ((r"\AД", ["а", "Д"]), (r"(?<!\s)Д", ["а ", "Д"]),
                     (r"а(?!\s)", ["а", " "])):
        assert not ST._line_gate_safe(p)
        assert any(re.search(p, ln) for ln in lines)
        assert not re.search(p, "\n".join(lines), re.MULTILINE)
    assert not ST._line_gate_safe(r"(?-i:Д)")


def test_bulk_run_ids_match_per_run(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.search import decode as D

    runs = [*PAGES, "немає-такого", ".приховане"]
    assert D.stamps_of(runs) == {r: D.stamp_of(r) for r in runs}
    conn = ST.connect(readonly=True)
    try:
        slow = ST._run_ids(conn, runs, fresh_only=True)
        monkeypatch.setattr(ST, "BULK_RUNS", 1)
        assert ST._run_ids(conn, runs, fresh_only=True) == slow
        assert ST._run_ids(conn, runs) == ST._run_ids(conn, runs, fresh_only=False)
        # дописана сторінка робить прогін несвіжим — і гуртом теж
        meta = space / "reports" / "htr" / "проба-а" / "_htr_meta.json"
        meta.write_text(meta.read_text(encoding="utf-8") + " ", encoding="utf-8")
        assert "проба-а" not in ST._run_ids(conn, runs, fresh_only=True)
    finally:
        conn.close()


def test_page_texts_in_id_order_and_scoped(space: Path) -> None:
    conn = ST.connect(readonly=True)
    try:
        ids = ST._run_ids(conn, list(PAGES))
        rows = list(ST._run_texts(conn, [ids["проба-в"], ids["проба-а"]]))
        assert len(rows) == 6
        assert {r[0] for r in rows} == {ids["проба-в"], ids["проба-а"]}
        everything = list(ST._run_texts(conn, list(ids.values())))
        assert len(everything) == 10
        texts = [zlib.decompress(b).decode("utf-8") for _r, _p, b in everything if b]
        assert any("Józef" in t for t in texts)
    finally:
        conn.close()


def test_cheap_window_takes_rarest_part_of_phrase() -> None:
    freq = {"tik": 50, "ikh": 400, "khb": 5, "hbr": 9, "bro": 9000, "rod": 1}
    assert ST._cheap_window("tikhb", freq) == "tikhb"
    got = ST._cheap_window("tikhbro", freq)
    assert len(got) == ST.PHRASE_WINDOW and got in "tikhbro"
    assert got == "tikhbr"          # без частої «bro»
    assert ST._cheap_window("abcdefgh", {}) == "abcdef"


def test_zero_counts_pages_with_whole_literal(space: Path) -> None:
    """Нуль по сирому рядку, а літерал у нормі є — на тих сторінках, де він цілий."""
    got = ST.grep("Кавальчинскійъ", list(PAGES))
    want = _reference("Кавальчинскійъ", list(PAGES))
    assert got["total"] == want["total"] == 0
    assert got["literal_pages"] == want["literal_pages"]
    assert got["literal_pages"] and got["literal_pages"] > 0


def test_trigram_freq_cached_beside_store_until_it_doubles(space: Path) -> None:
    conn = ST.connect(readonly=True)
    try:
        ST._TRIGRAMS.clear()
        first = ST._trigram_freq(conn)
        cache = Path(f"{ST.path()}.trigrams.json")
        assert first and cache.is_file()
        # новий процес бере частоти з файла, а не з вибірки
        ST._TRIGRAMS.clear()
        saved = json.loads(cache.read_text(encoding="utf-8"))
        saved["freq"] = {"xyz": 1}
        cache.write_text(json.dumps(saved), encoding="utf-8")
        assert ST._trigram_freq(conn) == {"xyz": 1}
        # стор виріс більш ніж удвічі — вибірка заново
        ST._TRIGRAMS.clear()
        saved["top"] = 1 if int(saved["top"]) > 2 else 0
        cache.write_text(json.dumps(saved), encoding="utf-8")
        assert ST._trigram_freq(conn) == first
    finally:
        ST._TRIGRAMS.clear()
        conn.close()
