"""🌍 Мови сайту роду: словник повний у всіх семи мовах, збірка кладе кожну мову
окремо з перемикачем, а скрипти дістають рядки своєї мови.

ID вигадані (`I9…`, `F9…`)."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.models import Citation, Fact, Family, GedDate, NameVariant, Person, Source
from nyshporka.site import build as B
from nyshporka.site import i18n as I18N
from nyshporka.storage.files import write_entity

PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("lang", [x for x in I18N.LANGS if x != I18N.DEFAULT])
def test_every_language_has_every_key_with_the_same_placeholders(lang: str) -> None:
    base = I18N.S[I18N.DEFAULT]
    got = I18N.S[lang]
    assert set(got) == set(base), (sorted(set(base) - set(got)), sorted(set(got) - set(base)))
    for key, text in base.items():
        assert set(PLACEHOLDER.findall(got[key])) == set(PLACEHOLDER.findall(text)), (lang, key)
    for form in ("months.gen", "months.nom"):
        assert len(got[form].split("|")) == 12, (lang, form)


def test_russian_brand_is_spelled_with_y() -> None:
    assert "Нышпорк" in I18N.S["ru"]["home.built"]


def test_languages_put_the_main_one_first() -> None:
    assert I18N.languages(None, "en")[0] == "en" and len(I18N.languages(None, "en")) == 7
    assert I18N.languages(["pl", "xx", "pl", "uk"], "uk") == ["uk", "pl"]


def _w(root: Path, kind: str, e: object) -> None:
    path = root / "data" / "canonical" / kind / f"{e.id}.md"  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, e)  # type: ignore[arg-type]


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    cite = [Citation(source_id="S_TEST_BOOK", confidence="direct", accessed=date(2026, 1, 1))]
    _w(tmp_path, "sources", Source(id="S_TEST_BOOK", type="book", title="Книга"))

    def person(pid: str, given: str, born: str, **kw: object) -> Person:
        return Person(id=pid, names=[NameVariant(form=f"{given} Тестовий", primary=True,
                                                 given=given, surname="Тестовий")],
                      sex="M", facts=[Fact(type="birth", date=GedDate(value=born),
                                           status="confirmed", citations=cite)],
                      **kw)  # type: ignore[arg-type]

    _w(tmp_path, "persons", person("I9001", "Іван", "1850", spouse_families=["F9001"]))
    _w(tmp_path, "persons", person("I9002", "Петро", "1880", parent_family="F9001"))
    _w(tmp_path, "families", Family(id="F9001", husband="I9001", children=["I9002"]))
    (tmp_path / "data" / "site").mkdir(parents=True)
    (tmp_path / "data" / "site" / "site.yml").write_text("languages: [uk, en]\n", encoding="utf-8")
    return tmp_path


def test_each_language_is_its_own_build_with_a_switcher(space: Path) -> None:
    rep = B.build(space, html=False)
    assert rep.languages == ["uk", "en"]
    uk = (rep.out / "docs" / "persons" / "I9001.md").read_text(encoding="utf-8")
    en = (rep.out / "docs-en" / "persons" / "I9001.md").read_text(encoding="utf-8")
    assert "Показати в дереві" in uk and "Show in the tree" in en
    assert "Іван Тестовий" in en, "дані канону лишаються мовою канону"
    assert "Born 1850" in en and "Нар. 1850" in uk
    main = (rep.out / "mkdocs.yml").read_text(encoding="utf-8")
    second = (rep.out / "mkdocs.en.yml").read_text(encoding="utf-8")
    assert 'site_dir: "html"' in main and 'link: "en/"' in main
    assert 'site_dir: "html/en"' in second and 'link: "../"' in second
    assert "language: en" in second
    js = (rep.out / "docs-en" / "assets" / "js" / "strings.js").read_text(encoding="utf-8")
    assert 'export const LANG = "en"' in js and "Nobody found" in js


def test_one_language_has_no_switcher(space: Path) -> None:
    (space / "data" / "site" / "site.yml").write_text("languages: [uk]\n", encoding="utf-8")
    rep = B.build(space, html=False)
    assert rep.languages == ["uk"]
    assert not (rep.out / "docs-en").exists()
    assert "alternate" not in (rep.out / "mkdocs.yml").read_text(encoding="utf-8")


def test_public_two_language_html_passes_the_guard(space: Path) -> None:
    if not B.mkdocs_available():
        pytest.skip("MkDocs не встановлено (extra site)")
    rep = B.build(space, public=True)
    assert rep.html is not None and not rep.leaks
    assert (rep.html / "index.html").is_file() and (rep.html / "en" / "index.html").is_file()
    assert 'hreflang="en"' in (rep.html / "index.html").read_text(encoding="utf-8")
