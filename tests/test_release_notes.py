"""📰 Кожна версія має нотатку для людини — інакше реліз не виходить.

Журнал змін пише розробник для розробника, і з нього генеалогіст не дізнається,
що тепер можна зробити. Нотатку забувають саме тоді, коли реліз збирають
поспіхом, тож її наявність перевіряє тест, а ворота релізу кличуть той самий
скрипт (`tools/release_notes.py`).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release_notes.py"
WHATS_NEW = ROOT / "docs" / "whats-new.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8", check=False)


def test_the_current_version_has_a_note_for_people() -> None:
    """🔴 Приймач, який ловить забуту нотатку ДО тегу, а не на сторінці релізу."""
    from nyshporka import __version__

    res = _run(__version__)
    assert res.returncode == 0, (
        f"у docs/whats-new.md немає розділу «## {__version__} — <дата>» — "
        f"що тепер можна зробити з цією версією, простою мовою. {res.stderr}")
    assert "- " in res.stdout, "розділ є, але в ньому немає жодного пункту"


def test_a_missing_version_refuses_instead_of_printing_nothing() -> None:
    res = _run("99.0.0")
    assert res.returncode == 1 and not res.stdout.strip()
    assert "99.0.0" in res.stderr


def test_the_section_stops_at_the_next_version() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import release_notes as R
    finally:
        sys.path.pop(0)
    text = "## 0.2.0 — дата\n\n- друге\n\n## 0.1.10 — дата\n\n- десяте\n\n## 0.1.1 — дата\n\n- перше\n"
    assert R.section("0.2.0", text) == "- друге"
    assert R.section("v0.1.1", text) == "- перше", "тег із «v» і межа версії 0.1.1/0.1.10"
    body = R.body("0.2.0", text)
    assert body.startswith(R.PREAMBLE) and "- друге" in body and "- десяте" not in body
    assert "SignPath" in body, "умови підпису вимагають згадки на сторінці завантаження"


def test_headings_are_versions_newest_first_and_the_page_is_on_the_site() -> None:
    text = WHATS_NEW.read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d+)\.(\d+)\.(\d+) — ", text, flags=re.MULTILINE)
    assert heads, "на сторінці немає жодного розділу версії"
    versions = [tuple(int(x) for x in h) for h in heads]
    assert versions == sorted(versions, reverse=True), "новіша версія — вгорі"
    assert "whats-new.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
