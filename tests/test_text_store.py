"""🗄 Текстовий стор: свіп без втрат, регекс без сліпоти, склейка за колонкою.

🔴 Головне твердження файлу — стор не міняє відповіді пошуку там, де кандидат
має спільний підрядок зі стемом. Виграш у часі нічого не вартий, якщо при
цьому зник хоч один хіт, який давав повний перебір.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Простір із одним прогоном на дві сторінки (та сама фікстура, що в індексу)."""
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    (run / "0001.txt").write_text(
        "въ селѣ Липовенькомъ\nродился Иванъ\n", encoding="utf-8")
    (run / "0002.txt").write_text(
        "Липовень\nкомъ приходѣ\n", encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W.reset()


def test_store_sweep_finds_what_the_gzip_index_finds(space: Path) -> None:
    """Той самий набір рядків і ті самі бали, що й у gzip-індексу."""
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    stem = S._norm("Липовеньке")
    assert list(ST.ensure_all(["проба"])) == ["проба"]
    mine = ST.sweep([stem], ["проба"], thresh=78)
    ref = D.sweep([stem], ["проба"], thresh=78, build_budget=1)
    key = {(h["page"], h["line_no"]): h["score"] for h in mine["hits"]}
    want = {(h["page"], h["line_no"]): h["score"] for h in ref["hits"]}
    assert key == want
    assert want, "перевірка беззмістовна: перебір нічого не знайшов"
    assert mine["backend"] == "store"
    assert mine["scanned"] == 1 and mine["unindexed"] == 0


def test_a_reread_run_is_reindexed_by_stamp(space: Path) -> None:
    """Дочитану сторінку стор мусить бачити після наступного `ensure_all`."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    stem = S._norm("Липовеньке")
    list(ST.ensure_all(["проба"]))
    assert ST.is_fresh("проба")
    run = space / "reports" / "htr" / "проба"
    (run / "0003.txt").write_text("село Липовеньке знову\n", encoding="utf-8")
    meta = json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0003.jpg"] = {"lines": 1}
    (run / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert not ST.is_fresh("проба")
    list(ST.ensure_all(["проба"]))
    got = ST.sweep([stem], ["проба"], thresh=78)
    assert any(h["page"] == "0003.jpg" for h in got["hits"])
    st = ST.stats()
    assert st["pages"] == 3 and st["indexed"] == 1


def test_grep_reads_cyrillic_as_written_and_carries_context(space: Path) -> None:
    """Регекс іде по сирому тексту, не по латинізованій нормі."""
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    got = ST.grep(r"Липовень(комъ|ке|$)", ["проба"], context=1)
    pages = {(h["page"], h["line_no"]) for h in got["hits"]}
    assert ("0001.jpg", 1) in pages and ("0002.jpg", 1) in pages
    assert got["prefiltered"] and got["literals"] == ["Липовень"]
    first = next(h for h in got["hits"] if h["page"] == "0002.jpg")
    assert first["after"] == ["комъ приходѣ"]
    # Без літерала — повний прохід, і відповідь це каже.
    got = ST.grep(r"\d+", ["проба"])
    assert not got["prefiltered"] and got["total"] == 0


def test_literals_pick_the_longest_required_run_per_branch() -> None:
    from nyshporka.search.store import literals_of

    assert literals_of(r"Дол[иіе]щ|Дал[иі]щ") == ["Дол", "Дал"]
    assert literals_of(r"лищин|лищен|олищ") == ["лищин", "лищен", "олищ"]
    # Квантифікатор робить літеру необов'язковою — літерал коротшає на неї.
    assert literals_of(r"Липовень?к") == ["Липовен"]
    # Гілка без трьох літер поспіль — передфільтра немає.
    assert literals_of(r"\bсе\S+|Долищ") is None
    assert literals_of(r"[а-я]{4,}") is None


def test_successor_joins_a_surname_split_across_columns(space: Path) -> None:
    """Хвіст «Коваль-» у широкому рядку, голова «скій» під ним у правій колонці,
    а в файлі — за вісім рядків. Стор мусить склеїти їх за геометрією."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    run = space / "reports" / "htr" / "проба"
    lines = ["Кто совершалъ", "Священникъ Петръ", "Іоаннъ Ивановъ Коваль-",
             "пономъ Гри", "горіемъ и зпа", "ломщикомъ", "Волошинымъ",
             "Священникъ Пе", "тръ Гончаръ", "скій съ діакономъ",
             "скій по невѣстѣ села", "Вербки крестьяне",
             "Іоаннъ Ефимовъ Лѣновый", "подпись свидѣтелей", "и поручителей"]
    # ліва колонка x0≈350, права x0≈850, крайня права x0≈2000; сторінка 3000
    boxes = [[400, 970, 760, 1050], [340, 1190, 810, 1260], [345, 1380, 1900, 1450],
             [345, 1500, 800, 1560], [340, 1580, 820, 1640], [343, 1660, 790, 1720],
             [348, 1770, 810, 1830], [345, 2110, 830, 2170], [353, 2200, 810, 2260],
             [348, 2270, 820, 2330], [848, 1490, 1840, 1550], [848, 1570, 1860, 1630],
             [853, 1640, 1870, 1700], [2005, 890, 2510, 950], [2020, 1010, 2450, 1070]]
    (run / "0004.txt").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    (run / "0004.lines.json").write_text(json.dumps({"size": [3000, 4500],
                                                     "boxes": boxes}),
                                         encoding="utf-8")
    meta = json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0004.jpg"] = {"lines": len(lines)}
    (run / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    list(ST.ensure_all(["проба"]))

    conn = ST.connect(readonly=True)
    pid = ST._page_id(conn, "проба", "0004.jpg")
    assert pid is not None
    page_lines = ST._page_lines(conn, pid)
    conn.close()
    assert ST.successors(page_lines).get(3) == 11
    stem = S._norm("Ковальскій")
    got = ST.sweep([stem], ["проба"], thresh=78)
    hit = next((h for h in got["hits"] if h["page"] == "0004.jpg"), None)
    assert hit is not None and hit["norm"] == stem
    assert hit["line_no"] in (3, 11)


def test_cli_grep_answers_with_denominator(space: Path) -> None:
    from nyshporka.cli import app
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    res = runner.invoke(app, ["text", "grep", "Липовень", "--case", "проба", "--json"])
    assert res.exit_code == 0, res.output
    got = json.loads(res.output)
    assert got["ok"] and got["data"]["total"] == 2
    cov = got["data"]["coverage"]
    assert cov["runs"] == 1 and cov["prefiltered"] and cov["scope"] == "run"

    res = runner.invoke(app, ["text", "state", "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["data"]["indexed"] == 1


def test_search_prefers_the_store_once_it_covers_the_scope(space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    res = S.search("Липовеньке", name="проба", thresh=78, profile=False, given=False)
    assert res["backend"] == "store"
    assert res["hits"]



# ── правки за третім раундом рецензій 08.09 ──────────────────────────────────
def test_verbose_flag_disables_the_literal_prefilter() -> None:
    from nyshporka.search.store import literals_of

    assert literals_of(r"(?x) Ковал # коментар") is None
    assert literals_of(r"(?ix)Ковал  ь") is None
    assert literals_of(r"(?i)Коваль") == ["Коваль"]


def test_grep_latin_literal_cut_before_the_vowel_of_sch_still_finds_the_line(space: Path) -> None:
    from nyshporka.search import store as ST

    assert ST._literal_core("Kowalsch") == "Kowal"
    run = space / "reports" / "htr" / "проба"
    (run / "0007.txt").write_text("Jan Kowalschinski z zona\n", encoding="utf-8")
    meta = json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0007.jpg"] = {"lines": 1}
    (run / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    list(ST.ensure_all(["проба"]))
    got = ST.grep(r"Kowalsch", ["проба"])
    assert got["total"] == 1, got



# ── швидкість за третім раундом: кеш свіпів, передфільтр partial, правила ────
def test_sweep_caches_per_run_and_forgets_a_reread_run(space: Path) -> None:
    import shutil

    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    src = space / "reports" / "htr" / "проба"
    shutil.copytree(src, src.parent / "проба2")
    S._RUNS_CACHE = None
    stem = S._norm("Липовеньке")
    list(ST.ensure_all(["проба", "проба2"]))
    first = ST.sweep([stem], ["проба", "проба2"], thresh=78)
    assert first["hits"] and first["cached"] == 0 and first["computed"] == 2
    second = ST.sweep([stem], ["проба", "проба2"], thresh=78)
    assert second["cached"] == 2 and second["computed"] == 0
    assert sorted(map(str, second["hits"])) == sorted(map(str, first["hits"]))
    # інший поріг — інший ключ, кеш не підсовує чужу відповідь
    other = ST.sweep([stem], ["проба"], thresh=90)
    assert other["computed"] == 1
    # перечитаний прогін випадає з кешу лише сам
    (src / "0001.txt").write_text("знову Липовеньке" + chr(10), encoding="utf-8")
    meta = json.loads((src / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0001.jpg"]["lines"] = 1
    (src / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    list(ST.ensure_all(["проба"]))
    third = ST.sweep([stem], ["проба", "проба2"], thresh=78)
    assert third["cached"] == 1 and third["computed"] == 1
    assert any(h["name"] == "проба" and h["page"] == "0001.jpg" and h["line_no"] == 1
               for h in third["hits"])


def test_partial_prefilter_keeps_every_hit_of_the_plain_matcher() -> None:
    """Межа `_partial_bound` — необхідна умова, а не евристика: те саме, що
    `decode._matches`, до бала, включно зі склейками довшими за стем."""
    import random

    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    stems = ["kovalskii", "kovalskogo", "koval"]
    base = ["kovalskii", "kovalskiipetr", "ivankovalskii", "kovlskii", "kavalskago",
            "kovalskiiivanovsyn", "xkovalskiix", "ivanov", "svascennik", "kowalsky",
            "kovalevskii", "kovalskiykovalskiy", "oval", "kov", "kovals"]
    rng = random.Random(7)
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    for _ in range(400):
        w = "".join(rng.choice(alphabet) for _ in range(rng.randint(3, 25)))
        base.append(w)
        base.append(w[:3] + "kovalsk" + w[3:])       # склейка зі стемом усередині
    for thresh in (78, 85, 92):
        a = ST._match_cdist(base, stems, thresh)
        b = D._matches(base, stems, thresh)
        assert a is not None and set(a) == set(b), (thresh, set(a) ^ set(b))
        assert all(round(a[j][0]) == round(b[j][0]) for j in a), thresh


def test_rules_fingerprint_is_versioned_and_can_be_accepted(space: Path) -> None:
    from nyshporka.cli import app
    from nyshporka.search import store as ST

    assert ST.rules_hash().startswith("v2:")
    list(ST.ensure_all(["проба"]))
    conn = ST.connect()
    conn.execute("update meta set value='старий' where key='rules'")
    conn.commit()
    conn.close()
    assert ST.stats()["rules_stale"] is True
    got = ST.sweep(["kovalskii"], ["проба"], thresh=78)
    assert got["rules_stale"] is True
    res = runner.invoke(app, ["text", "index", "--accept-rules"])
    assert res.exit_code == 0, res.output
    assert ST.stats()["rules_stale"] is False


def test_a_rebuild_killed_halfway_is_visible_run_by_run(space: Path) -> None:
    """🔴 Спільний відбиток правил бреше на користь свіжості.

    `ensure_all(force, reset_rules)` стирає єдиний рядок `meta.rules`, і перший
    же переіндексований прогін ставить туди НОВИЙ відбиток. Далі стор рапортує
    «правила збігаються», хоч решта прогонів ще тримає старих кандидатів.
    08.09.2026 перебудову на 6.8 ГБ убило браком пам'яті посеред, і
    `nysh text state` показав «1328 із 1328 · застаріло 0» на сторі, де 234
    прогони були зібрані іншим правилом склейки; знайшлось це лише прямою
    звіркою блобів. Тому відбиток стоїть НА КОЖНОМУ прогоні.
    """
    from nyshporka.cli import app
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба", "проба-diak_v4"]))
    assert ST.stats()["rules_other"] == 0

    conn = ST.connect()
    conn.execute("update runs set rules='правила до правки' where run='проба'")
    conn.commit()
    conn.close()

    st = ST.stats()
    # спільний відбиток мовчить — саме цим він і збрехав
    assert st["rules_stale"] is False
    assert st["rules_other"] == 1

    res = runner.invoke(app, ["text", "state"])
    assert res.exit_code == 0, res.output
    assert "іншим правилом склейки" in res.output

    # і доганяється звичайним `index`, без другої перебудови на 40 хвилин
    res = runner.invoke(app, ["text", "index"])
    assert res.exit_code == 0, res.output
    assert ST.stats()["rules_other"] == 0
