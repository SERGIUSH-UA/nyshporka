"""📁 Одна тека на все: програма, Python, кеш uv, моделі й простір.

🔴 Відеоурок 16.10.2026: людина обрала теку на D:, а простір, середовище
застосунку й кеш uv лягли в профіль на C:, і C: закінчився. Обіцянка тут одна:
кожен наступний виклик після інсталятора кладе туди ж, куди клав він, —
`nysh update`, `nysh htr install` (кеш torch) і `nysh models get`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Розкладка, яку лишає інсталятор: `<простір>/.program/tools/nyshporka`."""
    home = tmp_path / "Нишпорка" / ".program"
    prefix = home / "tools" / "nyshporka"
    prefix.mkdir(parents=True)
    (home / "install-info.ini").write_text(
        "[nyshporka]\n"
        f"uv={home / 'uv' / 'uv.exe'}\n"
        f"python_dir={home / 'python'}\n"
        f"tool_dir={home / 'tools'}\n"
        f"bin_dir={home / 'bin'}\n"
        f"cache_dir={home / 'cache'}\n"
        f"data_dir={home / 'data'}\n"
        f"workspace={tmp_path / 'Нишпорка'}\n",
        encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.delenv("NYSHPORKA_DATA_DIR", raising=False)
    monkeypatch.delenv("NYSHPORKA_CATALOG", raising=False)
    return home


def test_the_app_finds_its_own_folder_from_where_it_runs(program: Path) -> None:
    from nyshporka.setup import update as U

    assert U.install_home().resolve() == program.resolve()


def test_every_uv_call_keeps_to_the_chosen_folder(program: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Без цього `nysh update` ставив нову версію назад у профіль на C:."""
    from nyshporka.setup import update as U

    monkeypatch.setattr(U, "tool_env", lambda: True)

    env = U.uv_python_env()
    assert env["UV_TOOL_DIR"] == str(program / "tools")
    assert env["UV_TOOL_BIN_DIR"] == str(program / "bin")
    assert env["UV_CACHE_DIR"] == str(program / "cache")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(program / "python")
    line = U.how_to_update("researcher")
    assert "UV_CACHE_DIR" in line and "UV_TOOL_DIR" in line, line


def test_catalogs_and_models_follow_the_chosen_folder(program: Path) -> None:
    from nyshporka.catalog.store import catalog_dir
    from nyshporka.setup.packs import target_dir

    assert catalog_dir() == program / "data" / "catalog"
    assert target_dir("catalog") == catalog_dir()
    assert target_dir("model") == program / "data" / "Cache" / "model"


def test_an_explicit_variable_beats_the_installer(program: Path, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup.packs import target_dir

    monkeypatch.setenv("NYSHPORKA_DATA_DIR", str(tmp_path / "своє"))
    assert target_dir("model") == tmp_path / "своє" / "Cache" / "model"


def test_an_old_install_keeps_its_old_places(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Середовище без сліду поруч — стара розкладка: нічого не вигадуємо."""
    from nyshporka.setup import update as U

    prefix = tmp_path / "uv" / "tools" / "nyshporka"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    assert U._home_from_prefix() is None
