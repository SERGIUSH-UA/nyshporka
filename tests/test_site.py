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
    family = (docs / "families" / "F9002.md").read_text(encoding="utf-8")
    assert '<span class="nysh-pc__name">приватна особа</span>' in family
    # Відкриту версію можна шукати лише серед опублікованих.
    index = (docs / "assets" / "search.json").read_text(encoding="utf-8")
    assert "I9004" not in index and LIVING_NAME not in index
    assert "I9001" in index


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
    assert not env.ok and "набір site" in env.error and "pip install nyshporka[site]" not in env.error


@pytest.mark.skipif(not B.mkdocs_available(), reason="MkDocs не встановлено (extra site)")
def test_public_html_passes_the_guard(space: Path) -> None:
    env = O.call("site.build", {"public": True})
    assert env.ok, env.error
    html = Path(env.data["html"])
    assert (html / "index.html").is_file()
    assert LIVING_NAME not in _text(html, "*.html")


@pytest.mark.skipif(not B.mkdocs_available(), reason="MkDocs не встановлено (extra site)")
def test_a_failed_mkdocs_build_is_a_site_error(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MkDocs збирає сайт у процесі nysh: його відмова — зрозуміла `SiteError`
    з причиною, а не голий виняток посеред команди."""
    import mkdocs.config as MC
    from mkdocs.exceptions import ConfigurationError

    def broken(*_a: object, **_k: object) -> None:
        raise ConfigurationError("зламаний конфіг")

    monkeypatch.setattr(MC, "load_config", broken)
    with pytest.raises(B.SiteError, match=r"mkdocs build не зібрав сайт:\n.*зламаний конфіг"):
        B.build(space, public=True)


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


def test_private_case_stays_off_the_public_site_but_not_the_private(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔒 Справа з `private` у паспорті: на відкритому сайті ні шифри, ні кропу."""
    from nyshporka.cases import privacy

    # Вигаданий архів із літерним фондом: ID справжнього канону сюди не можна.
    sid = "S_TESTA_FR9001_D9"
    _w(space, "sources", Source(id=sid, type="archive", title="Тест-архів Р-9001-9 сповідна"))
    crop = _scan(space, "petro_confession.jpg", (330, 40))
    _w(space, "persons", Person(
        id="I9003", names=[NameVariant(form="Петро Тестовий", lang="uk", primary=True,
                                       given="Петро", surname="Тестовий")],
        sex="M", parent_family="F9001", spouse_families=["F9002"],
        facts=[Fact(type="birth", date=GedDate(value="1880"), status="confirmed",
                    citations=[Citation(source_id=sid, confidence="direct",
                                        accessed=date(2026, 1, 1))])],
        notes=f"Доказ: `{crop}`"))
    asked: list[str] = []

    def is_private(key: str) -> Path | None:
        asked.append(key)
        return space / "_source.json" if "/R-9001/" in key and key.endswith("/9") else None

    monkeypatch.setattr(privacy, "is_private", is_private)
    rep = B.build(space, public=True, html=False)
    docs = rep.out / "docs"
    assert rep.private_sources == [sid], asked
    assert not list(docs.rglob("petro_confession.jpg")), "кроп приватної справи на сайті"
    assert sid not in _text(docs) and "Тест-архів" not in _text(docs)
    assert "Петро" in _text(docs), "сама особа лишається"
    rep = B.build(space, public=False, html=False)
    assert list((rep.out / "docs").rglob("petro_confession.jpg")), "приватний сайт — усе"


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


def _hypotheses(root: Path) -> None:
    from nyshporka.models import Hypothesis
    _w(root, "hypotheses", Hypothesis(
        id="H9001", claim="Петро [[I9003]] — син Івана [[I9001]].", status="open",
        about=["I9003", "I9001", "F9001"], basis="Сусідство в сповідці.",
        decides="Метрика народження 1880.", updated=date(2026, 1, 1)))
    _w(root, "hypotheses", Hypothesis(
        id="H9002", claim="Оксана [[I9004]] — онука Івана.", status="closed",
        about=["I9004"], verdict="Дослідник: так.", reopen_if="Інша метрика.",
        updated=date(2026, 1, 1)))


def test_hypotheses_get_pages_and_show_on_persons(space: Path) -> None:
    _hypotheses(space)
    rep = B.build(space, html=False)
    docs = rep.out / "docs"
    page = (docs / "hypotheses" / "H9001.md").read_text(encoding="utf-8")
    assert "Метрика народження 1880." in page and "Відкрита" in page
    assert "H9001.md" in (docs / "hypotheses" / "index.md").read_text(encoding="utf-8")
    person = (docs / "persons" / "I9003.md").read_text(encoding="utf-8")
    assert "../hypotheses/H9001.md" in person
    assert "../hypotheses/H9001.md" in (docs / "families" / "F9001.md").read_text(encoding="utf-8")
    assert rep.counts["hypotheses"] == 2


def test_public_build_drops_hypotheses_about_the_hidden(space: Path) -> None:
    _hypotheses(space)
    rep = B.build(space, public=True, html=False)
    docs = rep.out / "docs"
    assert (docs / "hypotheses" / "H9001.md").is_file()
    assert not (docs / "hypotheses" / "H9002.md").exists()
    assert "H9002" not in (docs / "hypotheses" / "index.md").read_text(encoding="utf-8")
    assert rep.counts["hypotheses"] == 1


def test_wikilink_to_a_person_is_labelled_with_the_name(tmp_path: Path) -> None:
    pytest.importorskip("mkdocs")  # хуки сайту — лише з набором `site`
    from nyshporka.site import hooks as H
    docs = tmp_path / "docs"
    (docs / "persons").mkdir(parents=True)
    (docs / "persons" / "I9001.md").write_text("# x\n", encoding="utf-8")
    (docs / "assets").mkdir()
    (docs / "assets" / "search.json").write_text(
        '[{"id": "I9001", "n": "Іван Тестовий"}]', encoding="utf-8")
    cfg = {"docs_dir": str(docs)}
    H.on_files([], config=cfg)
    out = H.on_page_markdown("Син [[I9001]], брат [[I9099]].", page=None, config=cfg, files=None)
    assert out == "Син [[I9001|Іван Тестовий]], брат *I9099*."
