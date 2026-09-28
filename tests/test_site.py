"""🌐 Сайт роду: відкрита версія не називає живих, сторож ловить витік, приватна
показує всіх, а без MkDocs відмова каже, що поставити.

ID вигадані (`I9…`, `F9…`, `PL9…`): ворота приватних даних шукають вигляд робочих ID.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.models import Citation, Fact, Family, GedDate, NameVariant, Person, Place, Source
from nyshporka.site import build as B
from nyshporka.site import config as CFG
from nyshporka.site import public as PUB
from nyshporka.storage.files import write_entity

SRC = "S_TEST_BOOK"
LIVING_NAME = "Оксана Тестова"


def _cite() -> list[Citation]:
    return [Citation(source_id=SRC, confidence="direct", accessed=date(2026, 1, 1))]


def _p(pid: str, given: str, surname: str, sex: str, born: str | None = None,
       died: str | None = None, **kw: object) -> Person:
    facts = [Fact(type=k, date=GedDate(value=v), status="confirmed", citations=_cite(),
                  place_id="PL9001" if k == "birth" else None)
             for k, v in (("birth", born), ("death", died)) if v]
    return Person(id=pid, names=[NameVariant(form=f"{given} {surname}", lang="uk", primary=True,
                                             given=given, surname=surname)],
                  sex=sex, facts=facts, **kw)  # type: ignore[arg-type]


def _w(root: Path, kind: str, e: object) -> None:
    path = root / "data" / "canonical" / kind / f"{e.id}.md"  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, e)  # type: ignore[arg-type]


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    _w(tmp_path, "sources", Source(id=SRC, type="book", title="Тестова книга"))
    _w(tmp_path, "places", Place(id="PL9001", name="Село", admin=["Україна", "Вінницька обл."],
                                 coords=(48.5, 28.5)))
    _w(tmp_path, "persons", _p("I9001", "Іван", "Тестовий", "M", born="1850", died="1910",
                               spouse_families=["F9001"]))
    _w(tmp_path, "persons", _p("I9002", "Марія", "Тестова", "F", born="1855", died="1920",
                               spouse_families=["F9001"]))
    _w(tmp_path, "persons", _p("I9003", "Петро", "Тестовий", "M", born="1880", died="1950",
                               parent_family="F9001", spouse_families=["F9002"]))
    _w(tmp_path, "persons", _p("I9004", "Оксана", "Тестова", "F", born="1975",
                               parent_family="F9002", private=True,
                               notes="Живе в місті, дзвонила 2026 року."))
    _w(tmp_path, "families", Family(id="F9001", husband="I9001", wife="I9002", children=["I9003"]))
    _w(tmp_path, "families", Family(id="F9002", husband="I9003", children=["I9004"]))
    return tmp_path


def _text(folder: Path, pattern: str = "*.md") -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in folder.rglob(pattern))


def test_the_living_are_absent_from_the_public_sources(space: Path) -> None:
    rep = B.build(space, public=True, html=False)
    docs = rep.out / "docs"
    assert rep.hidden == 1
    assert not (docs / "persons" / "I9004.md").exists()
    body = _text(docs) + _text(docs / "assets", "*.json")
    assert LIVING_NAME not in body
    assert "I9004" not in _text(docs)
    assert (docs / "persons" / "I9001.md").is_file()
    assert "_приватна особа_" in (docs / "families" / "F9002.md").read_text(encoding="utf-8")


def test_the_private_build_shows_the_living_by_decade(space: Path) -> None:
    rep = B.build(space, public=False, html=False)
    page = (rep.out / "docs" / "persons" / "I9004.md").read_text(encoding="utf-8")
    assert "Приватна особа" in page and "1970-х" in page and "1975" not in page
    assert "дзвонила" not in page, "нотатки живих не друкуються й у приватній версії"


def test_config_groups_places_and_rejects_unknown_fields(space: Path) -> None:
    cfg_path = space / CFG.CONFIG
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("title: Рід Тестових\nplace_groups:\n"
                        "  - {id: pod, label: Поділля, match: [вінницьк]}\n", encoding="utf-8")
    rep = B.build(space, html=False)
    docs = rep.out / "docs"
    assert "Поділля" in (docs / "places" / "index.md").read_text(encoding="utf-8")
    assert "Рід Тестових" in (rep.out / "mkdocs.yml").read_text(encoding="utf-8") or \
        "\\u0420" in (rep.out / "mkdocs.yml").read_text(encoding="utf-8")
    cfg_path.write_text("titel: помилка\n", encoding="utf-8")
    with pytest.raises(CFG.ConfigError, match="titel"):
        CFG.load(space)


def test_overlay_pages_win_and_a_foreign_folder_is_not_overwritten(space: Path) -> None:
    overlay = space / CFG.OVERLAY
    overlay.mkdir(parents=True)
    (overlay / "index.md").write_text("# Своя головна\n", encoding="utf-8")
    rep = B.build(space, html=False)
    assert (rep.out / "docs" / "index.md").read_text(encoding="utf-8") == "# Своя головна\n"
    foreign = space / "elsewhere"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("чуже", encoding="utf-8")
    with pytest.raises(B.SiteError, match="не порожня"):
        B.build(space, out=foreign, html=False)


def test_a_broken_canon_stops_the_build(space: Path) -> None:
    _w(space, "persons", _p("I9005", "Зайвий", "Тестовий", "M", parent_family="F9999"))
    env = O.call("site.build", {"html": False})
    assert not env.ok and "помилок" in env.error


def test_guard_names_a_leak_in_finished_html(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text(f"<p>{LIVING_NAME}</p><p>I9004</p>", encoding="utf-8")
    (tmp_path / "search").mkdir()
    (tmp_path / "search" / "index.json").write_text('{"x": "I9004"}', encoding="utf-8")
    guard = PUB.NameGuard({"I9004": [LIVING_NAME]}, None)
    leaks = PUB.guard_site(tmp_path, {"I9004"}, set(), guard)
    assert any("ім'я" in x for x in leaks)
    assert any(x.startswith("a.html: ID") for x in leaks)
    assert any(x.startswith("search/index.json: ID") for x in leaks)


def test_declined_case_forms_are_caught_by_stems() -> None:
    """🪤 Дослівна форма не бачить відмінка — «Оксану Тестову» ловлять основи."""
    persons = [_p("I9004", "Оксана", "Тестова", "F", born="1975")]
    stems, _ = PUB.stem_probes(persons, {"I9004"})
    assert PUB.NameGuard({}, stems).hits("лист від Оксани Тестової")


def test_without_mkdocs_the_refusal_names_the_extra(space: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(B, "mkdocs_available", lambda: False)
    env = O.call("site.build", {})
    assert not env.ok and "nyshporka[site]" in env.error


@pytest.mark.skipif(not B.mkdocs_available(), reason="MkDocs не встановлено (extra site)")
def test_public_html_passes_the_guard(space: Path) -> None:
    env = O.call("site.build", {"public": True})
    assert env.ok, env.error
    html = Path(env.data["html"])
    assert (html / "index.html").is_file()
    assert LIVING_NAME not in _text(html, "*.html")


# ── відкрита версія: витоки, знайдені рецензією ─────────────────────────────
def _scan(space: Path, name: str, size: tuple[int, int] = (300, 40)) -> str:
    from PIL import Image

    rel = f"data/source/citations/test/{name}"
    f = space / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", size, 200).save(f)
    return rel


def test_a_scan_cited_by_a_hidden_card_stays_home_whatever_the_manifest_says(space: Path) -> None:
    """🔴 Застарілий `cited_by` виніс на сайт метрику живої людини.

    Скан, на який посилається прихована картка, не публікується, навіть якщо
    маніфест приписує його опублікованій; скан лише опублікованої — публікується.
    """
    import json

    from nyshporka.canon import evidence as E

    hers = _scan(space, "oksana_birth.jpg")
    his = _scan(space, "petro_birth.jpg", (310, 40))
    both = _scan(space, "family_census.jpg", (320, 40))
    _w(space, "persons", _p("I9004", "Оксана", "Тестова", "F", born="1975",
                            parent_family="F9002", private=True,
                            notes=f"Доказ: `{hers}`, перепис: `{both}`"))
    _w(space, "persons", _p("I9003", "Петро", "Тестовий", "M", born="1880", died="1950",
                            parent_family="F9001", spouse_families=["F9002"],
                            notes=f"Доказ: `{his}`, перепис: `{both}`"))
    E.manifest_path(space).parent.mkdir(parents=True, exist_ok=True)
    E.manifest_path(space).write_text(json.dumps({
        hers: {"secured_to": hers, "cited_by": ["I9003.md"]},
        his: {"secured_to": his, "cited_by": ["I9003.md"]}}), encoding="utf-8")
    rep = B.build(space, public=True, html=False)
    docs = rep.out / "docs"
    assert not list(docs.rglob("oksana_birth.jpg")), "скан прихованої опубліковано"
    assert not list(docs.rglob("family_census.jpg")), "спільний із прихованою скан опубліковано"
    assert "oksana" not in _text(docs)
    assert list(docs.rglob("petro_birth.jpg")), "скан опублікованого загубився"


def test_other_spellings_of_a_hidden_name_are_scrubbed(space: Path) -> None:
    overlay = space / CFG.OVERLAY
    overlay.mkdir(parents=True)
    (overlay / "story.md").write_text(
        "# Історія\n\n"
        "Рядок перший: Тестова Оксана приїхала.\n\n"
        "Рядок другий: **Оксана** Тестова писала.\n\n"
        "Рядок третій: [Оксана](../x.md) Тестова дзвонила.\n\n"
        "Рядок четвертий: лишається.\n", encoding="utf-8")
    rep = B.build(space, public=True, html=False)
    story = (rep.out / "docs" / "story.md").read_text(encoding="utf-8")
    assert "Оксана" not in story
    assert "лишається" in story


def test_the_guard_reads_the_escaped_search_index(tmp_path: Path) -> None:
    import json

    (tmp_path / "search").mkdir()
    (tmp_path / "search" / "search_index.json").write_text(
        json.dumps({"docs": [{"text": "Мар\u2019яна Тестова"}]}), encoding="utf-8")
    guard = PUB.NameGuard({"I9008": ["Мар'яна Тестова"]}, None)
    assert PUB.guard_site(tmp_path, {"I9008"}, set(), guard), "ім'я в \\uXXXX пройшло сторожа"


def test_overlay_files_other_than_pages_stay_out_of_the_public_site(space: Path) -> None:
    overlay = space / CFG.OVERLAY
    (overlay / "stories").mkdir(parents=True)
    (overlay / "stories" / "letter.txt").write_text(f"{LIVING_NAME}, I9004", encoding="utf-8")
    rep = B.build(space, public=True, html=False)
    assert not (rep.out / "docs" / "stories" / "letter.txt").exists()
    assert rep.skipped == ["stories/letter.txt"]
    private = B.build(space, public=False, html=False)
    assert (private.out / "docs" / "stories" / "letter.txt").exists()


def test_hidden_nodes_carry_no_years_and_families_no_marriage_year(space: Path) -> None:
    import json

    _w(space, "families", Family(id="F9002", husband="I9003", children=["I9004"],
                                 facts=[Fact(type="marriage", date=GedDate(value="1905-06-01"),
                                             status="confirmed")]))
    rep = B.build(space, public=True, html=False)
    tree = json.loads((rep.out / "docs" / "assets" / "tree.json").read_text(encoding="utf-8"))
    node = next(n for n in tree["nodes"] if n["id"] == "I9004")
    assert not {"lived_from", "lived_to", "birth_decade"} & set(node)
    assert node["birth"] is None and node["name"] == "(приватна особа)"
    fam = next(f for f in tree["families"] if f["id"] == "F9002")
    assert fam["marriage_year"] is None
    page = (rep.out / "docs" / "families" / "F9002.md").read_text(encoding="utf-8")
    assert "1905" not in page, "точна дата шлюбу родини з прихованою"


def test_a_public_build_without_hidden_still_drops_oral_sources(space: Path) -> None:
    _w(space, "persons", _p("I9004", "Оксана", "Тестова", "F", born="1908", died="1980",
                            parent_family="F9002"))
    _w(space, "sources", Source(id="S_TEST_ORAL", type="oral", title="Розповідь сусідки"))
    p = _p("I9001", "Іван", "Тестовий", "M", born="1850", died="1910", spouse_families=["F9001"])
    p.facts[0].citations.append(Citation(source_id="S_TEST_ORAL", confidence="indirect",
                                         accessed=date(2026, 1, 1)))
    _w(space, "persons", p)
    rep = B.build(space, public=True, html=False)
    assert rep.hidden == 0
    assert not (rep.out / "docs" / "sources" / "S_TEST_ORAL.md").exists()


def test_a_recent_burial_counts_as_a_recent_death() -> None:
    p = _p("I9006", "Ганна", "Тестова", "F", born="1950")
    p.facts.append(Fact(type="burial", date=GedDate(value="2019")))
    assert "I9006" in PUB.hidden_ids([p], CFG.SiteConfig())


def test_the_build_folder_is_ignored_by_git(space: Path) -> None:
    rep = B.build(space, html=False)
    assert (rep.out / ".gitignore").read_text(encoding="utf-8").strip() == "*"


def test_public_without_html_is_refused(space: Path) -> None:
    env = O.call("site.build", {"public": True, "html": False})
    assert not env.ok and "сторож" in env.error
