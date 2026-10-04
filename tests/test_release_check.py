"""🧾 Перед релізом нічого не забуто — `tools/release_check.py`.

Скрипт стоїть у хуку `pre-push` на теги й у воротах `release.yml`. Тут —
справжній git-репозиторій у tmp: перевірка читає файли з коміту, а не з диска.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
try:
    import release_check as RC
finally:
    sys.path.pop(0)


def _sh(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _put(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _release(version: str, *, unreleased: str = "") -> dict[str, str]:
    return {
        RC.VERSION_FILE: f'__version__ = "{version}"\n',
        RC.CHANGELOG: (f"# Журнал\n\n## [Unreleased]\n{unreleased}\n"
                       f"## [{version}] — 2026-10-04\n\n- зміна {version}\n\n"
                       f"## [0.1.0] — 2026-09-01\n\n- перше\n"),
        RC.WHATS_NEW: f"# Що нового\n\n## {version} — 4 жовтня\n\n- можна більше\n",
    }


MIG = '---\nversion: "{v}"\ntitle: t\n---\n\n# Міграція {v}\n{extra}'


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пакет, випущений як v0.1.0 з міграцією 0.1."""
    r = tmp_path / "pkg"
    r.mkdir()
    _sh(r, "init", "-q")
    _sh(r, "config", "user.email", "t@t")
    _sh(r, "config", "user.name", "t")
    _put(r, {**_release("0.1.0"), f"{RC.MIGRATIONS}/0.1.md": MIG.format(v="0.1", extra="")})
    _sh(r, "add", "-A")
    _sh(r, "commit", "-qm", "0.1.0")
    _sh(r, "tag", "v0.1.0")
    monkeypatch.setattr(RC, "ROOT", r)
    return r


def _commit(repo: Path, files: dict[str, str]) -> None:
    _put(repo, files)
    _sh(repo, "add", "-A")
    _sh(repo, "commit", "-qm", "next")


def test_a_complete_release_passes(repo: Path) -> None:
    _commit(repo, {**_release("0.2.0"), f"{RC.MIGRATIONS}/0.2.md": MIG.format(v="0.2", extra="")})
    rep = RC.check("v0.2.0")
    assert rep.errors == []
    assert any("0.2.md" in line for line in rep.info)


def test_forgotten_version_changelog_and_note(repo: Path) -> None:
    _commit(repo, {RC.CHANGELOG: "## [Unreleased]\n\n- нове\n\n## [0.1.0]\n\n- перше\n"})
    errors = " ".join(RC.check("0.2.0").errors)
    assert "__version__" in errors
    assert "## [0.2.0]" in errors
    assert "[Unreleased] лишились записи" in errors
    assert "whats-new" in errors


def test_a_migration_newer_than_the_release_is_refused(repo: Path) -> None:
    """Файл `0.3.md` у релізі 0.2.1 мовчав би: `pending` бере лише не новіші."""
    _commit(repo, {**_release("0.2.1"), f"{RC.MIGRATIONS}/0.3.md": MIG.format(v="0.3", extra="")})
    assert any("0.3.md" in e and "новіша за реліз" in e for e in RC.check("0.2.1").errors)


def test_a_thesis_added_to_a_released_migration_is_refused(repo: Path) -> None:
    """🔴 04.10.2026: теза дописана в `0.23.md` після тега v0.23.2 — простір,
    що 0.23 пройшов, її не побачив би ніколи."""
    _commit(repo, {**_release("0.1.1"),
                   f"{RC.MIGRATIONS}/0.1.md": MIG.format(v="0.1", extra="\nнова теза\n")})
    errors = RC.check("0.1.1").errors
    assert any("0.1.md" in e and "вже випущена" in e for e in errors)


def test_changed_skills_without_a_migration_warn(repo: Path) -> None:
    _commit(repo, {**_release("0.2.0"), f"{RC.SKILLS}/read-case/SKILL.md": "нова поведінка\n"})
    rep = RC.check("0.2.0")
    assert rep.errors == []
    assert any("read-case" in w for w in rep.warnings)


def test_the_check_reads_the_commit_not_the_working_tree(repo: Path) -> None:
    _commit(repo, _release("0.2.0"))
    _put(repo, {RC.VERSION_FILE: '__version__ = "9.9.9"\n'})     # не закомічено
    assert RC.check("0.2.0").errors == []
