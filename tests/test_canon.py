"""🌳 Канон: перевірка ловить те, що ламає правка файлом; ID не вгадуються; доказ
лягає в стор так, щоб цитата не провисла.

ID тут вигадані й поза діапазоном справжнього канону (`I9…`, `F9…`) — ворота
приватних даних шукають саме вигляд робочих ID.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from nyshporka import ops as O
from nyshporka.canon import check as C
from nyshporka.canon import evidence as E
from nyshporka.canon.ids import new_id
from nyshporka.core import workspace as W
from nyshporka.models import (
    Citation,
    Fact,
    Family,
    GedDate,
    Hit,
    Hypothesis,
    NameVariant,
    Person,
    Place,
    Source,
)
from nyshporka.storage.files import write_entity

SRC = "S_TEST_BOOK"


def _person(pid: str, name: str, sex: str = "M", born: str | None = None,
            died: str | None = None, **kw) -> Person:
    facts = []
    for kind, val in (("birth", born), ("death", died)):
        if val:
            facts.append(Fact(type=kind, date=GedDate(value=val), status="confirmed",
                              citations=[Citation(source_id=SRC, confidence="direct",
                                                  accessed=date(2026, 1, 1))]))
    return Person(id=pid, names=[NameVariant(form=name, lang="uk", primary=True)],
                  sex=sex, facts=facts, **kw)


def _write(root: Path, kind: str, entity, name: str | None = None) -> Path:
    path = root / "data" / "canonical" / kind / f"{name or entity.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, entity)
    return path


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    return tmp_path


@pytest.fixture
def family(space: Path) -> Path:
    """Цілий канон: батьки, дитина, місце, джерело — перевірка мусить мовчати."""
    _write(space, "sources", Source(id=SRC, type="book", title="Тестова книга"))
    _write(space, "places", Place(id="PL9001", name="Село"))
    _write(space, "persons", _person("I9001", "Іван", "M", born="1800",
                                     spouse_families=["F9001"]))
    _write(space, "persons", _person("I9002", "Марія", "F", born="1805",
                                     spouse_families=["F9001"]))
    _write(space, "persons", _person("I9003", "Петро", "M", born="1830",
                                     parent_family="F9001"))
    _write(space, "families", Family(id="F9001", husband="I9001", wife="I9002",
                                     children=["I9003"]))
    return space


def _codes(rep: C.Report, sev: str) -> list[str]:
    return sorted(i.code for i in rep.issues if i.severity == sev)


def test_a_whole_canon_has_no_errors_or_warnings(family: Path) -> None:
    rep = C.check(family)
    assert rep.ok and _codes(rep, "ERROR") == [] and _codes(rep, "WARN") == []
    assert rep.canon.counts() == {"persons": 3, "families": 1, "places": 1, "sources": 1,
                                  "hypotheses": 0}


def test_a_broken_card_does_not_hide_the_rest(family: Path) -> None:
    """🔴 Одна зіпсована картка — рядок ERROR, а не виняток, що ховає решту."""
    bad = family / "data" / "canonical" / "persons" / "I9004.md"
    bad.write_text("---\nid: I9004\nsex: X\n---\n", encoding="utf-8")
    _write(family, "persons", _person("I9005", "Сирота", parent_family="F9999"))
    rep = C.check(family)
    assert "schema" in _codes(rep, "ERROR")
    assert "missing_ref" in _codes(rep, "ERROR")


def test_file_name_must_match_the_id(family: Path) -> None:
    """Скопійована заготовка з незміненим id — найчастіша помилка ручної правки."""
    _write(family, "persons", _person("I9003", "Копія"), name="I9010")
    rep = C.check(family)
    assert {"file_name", "duplicate_id"} & set(_codes(rep, "ERROR"))


def test_one_sided_link_and_wrong_sex(family: Path) -> None:
    _write(family, "persons", _person("I9002", "Марія", "M", born="1805",
                                      spouse_families=["F9001"]))
    _write(family, "persons", _person("I9006", "Зайвий", parent_family="F9001", born="1832"))
    rep = C.check(family)
    assert "sex" in _codes(rep, "ERROR")
    assert "one_sided" in _codes(rep, "WARN")


def test_chronology_errors(family: Path) -> None:
    _write(family, "persons", _person("I9003", "Петро", "M", born="1808",
                                      parent_family="F9001"))
    _write(family, "persons", _person("I9001", "Іван", "M", born="1800", died="1790",
                                      spouse_families=["F9001"]))
    rep = C.check(family)
    texts = " ".join(i.text for i in rep.issues if i.code == "chronology")
    assert "пізніше за смерть" in texts
    assert "мати I9002 мав(ла) 3 років" in texts


def test_an_issue_speaks_to_a_person_about_the_person(family: Path) -> None:
    """🔴 Людині — речення про особу, агентові — поля й ID родини.

    Консоль показувала `text`: «parent_family і hypothetical_parent_family»,
    «мав(ла) 51 років» під іменами обох подружжів (прохід канону 22.10.2026).
    """
    _write(family, "persons", _person("I9003", "Петро", "M", born="1860",
                                      parent_family="F9001"))
    _write(family, "persons", _person("I9004", "Олена", "F", born="1830",
                                      parent_family="F9001",
                                      hypothetical_parent_family="F9001"))
    _write(family, "families", Family(id="F9001", husband="I9001", wife="I9002",
                                      children=["I9003", "I9004"]))
    rep = C.check(family)
    age = next(i for i in rep.issues if i.code == "chronology" and i.who == "I9002")
    assert age.where == "F9001" and "мав(ла) 55 років" in age.text
    assert age.say == "Мати у віці 55, дитина I9003 народжена 1860"
    both = next(i for i in rep.issues if i.code == "both_levels")
    assert "hypothetical_parent_family" in both.text
    assert "_family" not in both.say and both.as_dict()["say"] == both.say
    # Без речення поле не з'являється: вивід для агента той самий, що й був.
    assert "say" not in C.Issue("WARN", "x", "I9001", "t").as_dict()


def test_confirmed_without_a_strong_citation_is_flagged(family: Path) -> None:
    p = _person("I9003", "Петро", "M", parent_family="F9001")
    p.facts.append(Fact(type="residence", status="confirmed"))
    p.facts.append(Fact(type="occupation", status="confirmed", citations=[
        Citation(source_id=SRC, confidence="speculative", accessed=date(2026, 1, 1))]))
    _write(family, "persons", p)
    assert {"uncited", "weak_confirmed"} <= set(_codes(C.check(family), "WARN"))


def test_evidence_path_and_manifest_are_checked(family: Path) -> None:
    p = _person("I9003", "Петро", "M", parent_family="F9001",
                notes="Доказ: `data/source/citations/test/missing.jpg`")
    _write(family, "persons", p)
    crop = family / "data" / "source" / "citations" / "test" / "real.jpg"
    crop.parent.mkdir(parents=True)
    crop.write_bytes(b"x")
    E.manifest_path(family).write_text(json.dumps({
        "data/source/citations/test/real.jpg": {"secured_to": "data/source/citations/test/real.jpg",
                                                 "sha256": "0" * 64, "cited_by": []},
        "data/source/citations/test/gone.jpg": {"secured_to": "data/source/citations/test/gone.jpg",
                                                 "cited_by": ["I9003.md"]},
    }), encoding="utf-8")
    assert {"evidence_missing", "manifest_missing"} <= set(_codes(C.check(family), "ERROR"))
    assert "manifest_hash" not in _codes(C.check(family), "ERROR"), "без --hash хеш не рахується"
    assert "manifest_hash" in _codes(C.check(family, hash_evidence=True), "ERROR")


def test_a_probably_living_person_without_private_is_flagged(family: Path) -> None:
    _write(family, "persons", _person("I9003", "Петро", "M", born="1990", parent_family="F9001"))
    rep = C.check(family)
    assert "maybe_living" in _codes(rep, "WARN")
    _write(family, "persons", _person("I9003", "Петро", "M", born="1990",
                                      parent_family="F9001", private=True))
    assert "maybe_living" not in _codes(C.check(family), "WARN")


def test_regions_are_required_only_when_coverage_uses_them(family: Path) -> None:
    from nyshporka.models import CoverageSpan

    _write(family, "sources", Source(id=SRC, type="book", title="Книга", coverage=[
        CoverageSpan(region="xx", year_from=1800, year_to=1810)]))
    assert "regions" in _codes(C.check(family), "ERROR")


def test_new_id_is_max_plus_one_and_skips_gaps(family: Path) -> None:
    (family / "data" / "canonical" / "persons" / "I9003.md").unlink()
    canonical = family / "data" / "canonical"
    assert new_id(canonical, "person") == "I9003", "дірка після максимуму — не дірка"
    _write(family, "persons", _person("I9020", "Далекий"))
    assert new_id(canonical, "person") == "I9021"
    assert new_id(canonical, "place") == "PL9002"
    assert new_id(canonical, "family") == "F9002"


def _png(path: Path, size: tuple[int, int] = (300, 40), noise: bool = False) -> Path:
    if noise:
        im = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        im = Image.new("RGB", size, (200, 120, 40))
    im.save(path)
    return path


def test_evidence_add_stores_a_grey_jpeg_and_is_idempotent(space: Path) -> None:
    src = _png(space / "crop.png")
    got = E.add(space, src, "test", name="рядок 1")
    stored = space / got.path
    assert got.path == "data/source/citations/test/рядок_1.jpg"
    with Image.open(stored) as im:
        assert im.format == "JPEG" and im.mode == "L"
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == got.sha256
    man = json.loads(E.manifest_path(space).read_text(encoding="utf-8"))
    assert man[got.path]["cited_by"] == []
    again = E.add(space, src, "test", name="рядок 1")
    assert again.existed and again.sha256 == got.sha256


def test_evidence_add_refuses_what_would_break_a_citation(space: Path) -> None:
    first = E.add(space, _png(space / "a.png"), "test", name="x")
    other = _png(space / "b.png", size=(310, 40))
    with pytest.raises(E.EvidenceError, match="іншим вмістом"):
        E.add(space, other, "test", name="x")
    assert E.add(space, other, "test", name="x", overwrite=True).sha256 != first.sha256
    with pytest.raises(E.EvidenceError, match="латиниця"):
        E.add(space, other, "Архів", name="y")
    with pytest.raises(E.EvidenceError, match="аркуш, а не"):
        E.add(space, _png(space / "big.png", size=(2600, 2600), noise=True), "test")


def test_index_normalises_and_fills_cited_by(family: Path) -> None:
    got = E.add(family, _png(family / "c.png"), "test", name="c")
    other = E.add(family, _png(family / "d.png", size=(320, 40)), "test", name="d")
    man = E.manifest_path(family)
    data = json.loads(man.read_text(encoding="utf-8"))
    data[got.path]["cited_by"] = ["I9001", "data/canonical/persons/I9001.md"]
    man.write_text(json.dumps(data), encoding="utf-8")
    _write(family, "persons", _person("I9003", "Петро", "M", parent_family="F9001",
                                      notes=f"Доказ: `{got.path}`"))
    env = O.call("canon.index", {})
    assert env.ok, env.error
    data = json.loads(man.read_text(encoding="utf-8"))
    assert data[got.path]["cited_by"] == ["I9001.md", "I9003.md"]
    assert env.data["evidence"]["unreferenced"] == [other.path]
    assert (family / "data" / "derived" / "nyshporka.sqlite").is_file()


def test_precommit_blocks_a_full_sheet_and_a_broken_staged_card(family: Path) -> None:
    """🔴 Лише те, що комітиться: старий борг в інших картках коміт не блокує."""
    import shutil
    import subprocess

    from nyshporka.canon import hook as H

    if shutil.which("git") is None:
        pytest.skip("git недоступний")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=family, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t")
    git("config", "user.name", "t")
    # Старий борг: зламана картка, яку в цьому коміті ніхто не чіпає.
    _write(family, "persons", _person("I9005", "Борг", parent_family="F9999"))
    git("add", "-A")
    git("commit", "-qm", "base")
    assert H.problems(family) == [], "нічого не застейджено — нічого не блокує"

    sheet = family / "data" / "source" / "citations" / "test" / "sheet.png"
    sheet.parent.mkdir(parents=True)
    _png(sheet, size=(2600, 2600), noise=True)
    _write(family, "persons", _person("I9003", "Петро", "M", born="1830",
                                      parent_family="F9404"))
    git("add", "-A")
    found = H.problems(family)
    assert any("sheet.png" in p for p in found)
    assert any("F9404" in p for p in found)
    assert not any("F9999" in p for p in found), "борг незастейдженої картки не блокує"

    target = H.install(family)
    assert "nyshporka canon precommit" in target.read_text(encoding="utf-8")
    assert H.install(family) == target, "свій хук перевстановлюється"


def test_a_manifest_written_as_a_list_is_checked_not_crashed(family: Path) -> None:
    E.manifest_path(family).parent.mkdir(parents=True, exist_ok=True)
    E.manifest_path(family).write_text(json.dumps([
        {"secured_to": "data/source/citations/test/gone.jpg", "cited_by": []}]),
        encoding="utf-8")
    assert "manifest_missing" in _codes(C.check(family), "ERROR")


def test_precommit_blocks_deleting_a_card_others_point_to(family: Path) -> None:
    import shutil
    import subprocess

    from nyshporka.canon import hook as H

    if shutil.which("git") is None:
        pytest.skip("git недоступний")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=family, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("rm", "-q", "data/canonical/families/F9001.md")
    found = H.problems(family)
    assert any("F9001" in p for p in found), "видалення родини, на яку посилаються, пройшло"


def test_ops_on_a_space_without_canon(space: Path) -> None:
    env = O.call("canon.check", {})
    assert env.ok and env.data["loaded"] == {}
    assert any(w.code == "no_canon" for w in env.warnings)
    assert not O.call("canon.index", {}).ok


def test_check_op_reports_errors_as_data(family: Path) -> None:
    _write(family, "persons", _person("I9005", "Сирота", parent_family="F9999"))
    env = O.call("canon.check", {})
    assert env.ok and env.data["errors"] == 1
    assert any(w.code == "canon_errors" for w in env.warnings)
    assert O.call("canon.new_id", {"kind": "person"}).data["id"] == "I9006"


# ── гіпотези ─────────────────────────────────────────────────────────────────
def _hyp(hid: str, status: str = "open", **kw) -> Hypothesis:
    kw.setdefault("claim", "Петро — син Івана")
    kw.setdefault("updated", date.today())
    if status != "closed":
        kw.setdefault("decides", "метрика хрещення Петра")
    return Hypothesis(id=hid, status=status, **kw)


def _hit(strength: str = "strong", **kw) -> Hit:
    kw.setdefault("case", "TEST/1/2/3")
    kw.setdefault("scan", "0007")
    kw.setdefault("reading", "Петро Іванов")
    return Hit(strength=strength, **kw)


def _disputed(hypothesis: str | None = None) -> Person:
    p = _person("I9003", "Петро", "M", born="1830", parent_family="F9001")
    p.facts.append(Fact(type="other", value="спірне", status="disputed",
                        hypothesis=hypothesis))
    return p


def test_a_disputed_fact_must_point_to_a_hypothesis(family: Path) -> None:
    """🔴 Спірний факт без «чим вирішиться» не лягає в канон."""
    _write(family, "persons", _disputed())
    assert "disputed_unlinked" in _codes(C.check(family), "ERROR")
    _write(family, "persons", _disputed("H9009"))
    assert "missing_ref" in _codes(C.check(family), "ERROR")
    _write(family, "hypotheses", _hyp("H9009", about=["I9003"]))
    rep = C.check(family)
    assert rep.ok and _codes(rep, "WARN") == []


def test_a_hypothesis_says_what_decides_it_and_how_it_reopens(family: Path) -> None:
    _write(family, "hypotheses", _hyp("H9001", decides=""))
    _write(family, "hypotheses", _hyp("H9002", status="closed", verdict="людина, 2026"))
    _write(family, "hypotheses", _hyp("H9003", status="awaiting"))
    _write(family, "hypotheses", _hyp("H9004", hits=[_hit() for _ in range(6)]))
    _write(family, "hypotheses", _hyp("H9005", about=["I9999"], versus=["H9998"]))
    errors = _codes(C.check(family), "ERROR")
    for code in ("hyp_no_decides", "hyp_no_reopen", "hyp_awaiting_no_hits",
                 "hyp_too_many_hits", "missing_ref"):
        assert code in errors, code


def test_a_hit_is_written_with_a_canonical_case_key(family: Path) -> None:
    """Ключ не в канонічній формі — вердикт із журналу до хіта не знайдеться."""
    _write(family, "hypotheses", _hyp("H9001", hits=[_hit(case="1-2-3")]))
    _write(family, "hypotheses", _hyp("H9002", hits=[_hit(case="TEST/1/2/207б")]))
    issues = [i for i in C.check(family).issues if i.code == "hyp_bad_case"]
    assert {i.where for i in issues} == {"H9001", "H9002"}
    assert any("TEST/1/2/207b" in i.text for i in issues)


def test_a_hypothetical_link_wants_a_hypothesis(family: Path) -> None:
    _write(family, "persons", _person("I9006", "Можливий", born="1834",
                                      hypothetical_parent_family="F9001"))
    _write(family, "families", Family(id="F9001", husband="I9001", wife="I9002",
                                      children=["I9003"], hypothetical_children=["I9006"]))
    warned = {i.where for i in C.check(family).issues if i.code == "hypothetical_unlinked"}
    assert warned == {"I9006", "F9001"}
    _write(family, "hypotheses", _hyp("H9001", about=["I9006", "F9001"]))
    assert "hypothetical_unlinked" not in _codes(C.check(family), "WARN")


def test_a_verdict_in_the_journal_flags_a_waiting_hypothesis(family: Path) -> None:
    _write(family, "hypotheses", _hyp("H9001", status="awaiting",
                                      hits=[_hit(line=12), _hit(scan="0008")]))
    journal = family / "data" / "derived" / "verdicts.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"TEST/1/2/3": {
        "run-a|0007.jpg|11": {"verdict": "noise"},
        "run-a|0007.jpg|12": {"verdict": "hit"}}}), encoding="utf-8")
    ready = [i for i in C.check(family).issues if i.code == "hyp_verdict_ready"]
    assert len(ready) == 1 and "«hit»" in ready[0].text, "рядок 11 — чужий, 0008 — без вердикту"


def test_an_untouched_open_hypothesis_goes_stale(family: Path) -> None:
    _write(family, "hypotheses", _hyp("H9001", updated=date(2000, 1, 1)))
    _write(family, "hypotheses", _hyp("H9002", status="closed", verdict="людина",
                                      reopen_if="новий документ", updated=date(2000, 1, 1)))
    stale = {i.where for i in C.check(family).issues if i.code == "hyp_stale"}
    assert stale == {"H9001"}, "закрита не старіє"


def test_next_ranks_waiting_strong_and_heavy_first(family: Path) -> None:
    from nyshporka.canon.next import next_decisions

    # Важча стоїть під БІЛЬШИМ номером: порядок мусить тримати вага, а не ID.
    _write(family, "persons", _disputed("H9004"))
    _write(family, "hypotheses", _hyp("H9001", about=["I9001", "I9002", "I9003"]))
    _write(family, "hypotheses", _hyp("H9002", status="awaiting", hits=[_hit("weak")]))
    _write(family, "hypotheses", _hyp("H9003", status="awaiting", hits=[_hit("strong")]))
    _write(family, "hypotheses", _hyp("H9004", status="awaiting", about=["I9003"],
                                      hits=[_hit("weak", line=4), _hit("strong", line=5)]))
    _write(family, "hypotheses", _hyp("H9005", status="closed", verdict="людина",
                                      reopen_if="новий документ"))
    got = next_decisions(family, limit=10)
    assert [d["id"] for d in got["next"]] == ["H9004", "H9003", "H9002", "H9001"]
    top = got["next"][0]
    assert top["id"] == "H9004" and top["weight"] == 2 and top["facts"] == ["I9003:other"]
    assert top["hits"][0]["strength"] == "strong", "сильний хіт першим"
    assert top["hits"][0]["crop"] == 'nysh text crop "TEST/1/2/3" 0007 5'
    assert (got["open"], got["awaiting"], got["closed"]) == (1, 3, 1)
    env = O.call("canon.next", {"limit": 1})
    assert env.ok and [d["id"] for d in env.data["next"]] == ["H9004"]
    assert O.call("canon.new_id", {"kind": "hypothesis"}).data["id"] == "H9006"


def test_precommit_blocks_a_staged_disputed_fact_without_hypothesis(family: Path) -> None:
    import shutil
    import subprocess

    from nyshporka.canon import hook as H

    if shutil.which("git") is None:
        pytest.skip("git недоступний")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=family, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    _write(family, "persons", _disputed())
    git("add", "-A")
    assert any("disputed" in p for p in H.problems(family))


def test_evidence_origin_is_kept_and_indexed(space: Path) -> None:
    """Походження кропу (справа, скан, рядок) — у маніфест; повтор без нього не стирає."""
    src = _png(space / "o.png")
    got = E.add(space, src, "test", name="o",
                origin={"case": "TEST/1/1/5", "page": "0012", "line": 7})
    E.add(space, src, "test", name="o")
    man = E.manifest_path(space)
    data = json.loads(man.read_text(encoding="utf-8"))
    assert data[got.path]["origin"] == {"case": "TEST/1/1/5", "page": "0012", "line": 7}
    # Без картки кроп ще не канон — у покажчику його немає.
    assert E.origins(man) == {}
    data[got.path]["cited_by"] = ["I9001.md", "kovalchuk:I9002.md"]
    man.write_text(json.dumps(data), encoding="utf-8")
    assert E.origins(man) == {("TEST/1/1/5", "0012", 7): [(".", "I9001"), ("kovalchuk", "I9002")]}


def test_evidence_op_wants_the_whole_origin(space: Path) -> None:
    src = _png(space / "p.png")
    env = O.call("evidence.add", {"file": str(src), "provenance": "test",
                                  "origin_case": "TEST/1/1/5", "origin_line": 3})
    assert not env.ok and "справа, скан і рядок" in env.error
    env = O.call("evidence.add", {"file": str(src), "provenance": "test", "name": "p",
                                  "origin_case": "TEST/1/1/5", "origin_page": "0003.jpg",
                                  "origin_line": 3})
    assert env.ok, env.error


def test_search_hit_cut_into_canon_is_marked(space: Path) -> None:
    """Рядок видачі, з якого вирізано кроп картки, позначено проєктом і карткою."""
    from nyshporka import ops_text as OT

    got = E.add(space, _png(space / "m.png"), "test", name="m",
                origin={"case": "TEST/1/1/5", "page": "0012", "line": 7})
    man = E.manifest_path(space)
    data = json.loads(man.read_text(encoding="utf-8"))
    data[got.path]["cited_by"] = ["kovalchuk:I9002.md"]
    man.write_text(json.dumps(data), encoding="utf-8")
    res = {"case_key": "TEST/1/1/5",
           "hits": [{"page": "0012.JPG", "line_no": 7}, {"page": "0012.jpg", "line_no": 8},
                    {"case_key": "TEST/1/1/6", "page": "0012", "line_no": 7}],
           "anchor": {"hits": []}, "record": {"hits": []}}
    OT._mark_in_canon(res)
    assert res["in_canon_known"] == 1
    assert res["hits"][0]["in_canon"] == [{"project": "kovalchuk", "name": "kovalchuk",
                                           "card": "I9002"}]
    assert "in_canon" not in res["hits"][1] and "in_canon" not in res["hits"][2]


def _hub_project(tmp_path: Path, cited_by: list[str]) -> tuple[Path, Path]:
    """Майстерня з проєктом `rid-nash`; у спільному маніфесті — один зниклий файл."""
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text('[workspace]\nschema = 1\nname = "h"\n', encoding="utf-8")
    root = hub / W.PROJECTS_DIR / "rid-nash"
    root.mkdir(parents=True)
    (root / W.MARKER).write_text('[project]\nname = "Ткачів"\nkind = "family"\n',
                                 encoding="utf-8")
    man = C.manifest_path(root)
    man.parent.mkdir(parents=True, exist_ok=True)
    gone = "data/source/citations/test/gone.pdf"
    man.write_text(json.dumps({gone: {"secured_to": gone, "cited_by": cited_by}}),
                   encoding="utf-8")
    return hub, root


def test_foreign_only_missing_evidence_is_a_warning(tmp_path: Path) -> None:
    _, root = _hub_project(tmp_path, ["rid-sosidy:I9037.md"])
    rep = C.check(root)
    assert "manifest_missing" not in _codes(rep, "ERROR")
    assert _codes(rep, "WARN") == ["manifest_missing_foreign"]
    assert "rid-sosidy" in next(i.text for i in rep.issues
                                   if i.code == "manifest_missing_foreign")


def test_own_cited_missing_evidence_stays_an_error(tmp_path: Path) -> None:
    _, root = _hub_project(tmp_path, ["rid-sosidy:I9037.md", "rid-nash:I9001.md"])
    assert "manifest_missing" in _codes(C.check(root), "ERROR")


def test_unknown_owner_missing_evidence_stays_an_error(tmp_path: Path) -> None:
    _, root = _hub_project(tmp_path, [])
    assert "manifest_missing" in _codes(C.check(root), "ERROR")


def test_foreign_hash_mismatch_is_a_warning(tmp_path: Path) -> None:
    hub, root = _hub_project(tmp_path, ["rid-sosidy:I9037.md"])
    f = hub / "data/source/citations/test/gone.pdf"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    man = C.manifest_path(root)
    rec = json.loads(man.read_text(encoding="utf-8"))
    rec["data/source/citations/test/gone.pdf"]["sha256"] = "0" * 64
    man.write_text(json.dumps(rec), encoding="utf-8")
    rep = C.check(root, hash_evidence=True)
    assert "manifest_hash" not in _codes(rep, "ERROR")
    assert "manifest_hash_foreign" in _codes(rep, "WARN")


def test_no_project_workspace_keeps_error_for_foreign_looking_cited_by(family: Path) -> None:
    E.manifest_path(family).parent.mkdir(parents=True, exist_ok=True)
    E.manifest_path(family).write_text(json.dumps({
        "data/source/citations/test/gone.pdf": {
            "secured_to": "data/source/citations/test/gone.pdf",
            "cited_by": ["rid-sosidy:I9037.md"]}}), encoding="utf-8")
    assert "manifest_missing" in _codes(C.check(family), "ERROR")
