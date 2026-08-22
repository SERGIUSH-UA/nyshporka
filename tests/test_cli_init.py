"""🧭 `nysh init` — команда, яку виконують РІВНО ОДИН раз, і саме тому вона
найдорожча в помилці.

Тестів на неї не було взагалі. Через це вада прожила довго й тихо: майстер
рахував шлях сам і знав одне джерело з п'яти, тож простір створювався в
типовому місці навіть тоді, коли людина явно назвала інше змінною середовища.
Далі всі команди йшли за драбиною резолвера — тобто в іншу теку, ніж та, яку
щойно створили. Обидві сторони поводились «правильно», а разом давали розлад.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


def _marker(root: Path) -> Path:
    return root / W.MARKER


def test_init_without_a_path_uses_the_variable(monkeypatch, tmp_path: Path) -> None:
    """🔴 Найдорожчий випадок: обидва інсталятори кличуть `nysh init --yes` БЕЗ
    шляху. Доки майстер не бачив змінної, це означало, що виставлена людиною
    тека мовчки ігнорувалась саме там, де вона не могла це помітити."""
    target = tmp_path / "дослідження"
    monkeypatch.setenv(W.ENV_WORKSPACE, str(target))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "домівка"))

    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])

    assert res.exit_code == 0, res.stdout
    assert _marker(target).is_file()
    # І нічого не з'явилось у типовому місці.
    assert not (tmp_path / "домівка" / "Нишпорка").exists()


def test_init_says_where_the_path_came_from(monkeypatch, tmp_path: Path) -> None:
    """Сенс `Plan.origin`: людина бачить не лише КУДИ, а й ЧОМУ туди. З `--yes`
    питань немає зовсім, тож цей рядок — єдина нагода помітити чужий шлях."""
    monkeypatch.setenv(W.ENV_WORKSPACE, str(tmp_path / "дослідження"))
    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])
    assert res.exit_code == 0, res.stdout
    assert W.ENV_WORKSPACE in res.stdout


def test_init_inside_a_workspace_does_not_offer_a_new_one(monkeypatch, tmp_path: Path) -> None:
    """`nysh init`, запущений у наявному просторі, пропонував створити НОВИЙ у
    типовому місці — тобто роздвоював дослідження рівно тим рухом, яким людина
    намагалась його полагодити."""
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    _marker(root).write_text("[workspace]" + chr(10) + "schema = 1" + chr(10),
                             encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "домівка"))

    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])

    assert res.exit_code == 0, res.stdout
    assert "уже існує" in res.stdout
    assert not (tmp_path / "домівка" / "Нишпорка").exists()


def test_init_refuses_a_dangerous_path_from_the_variable(monkeypatch, tmp_path: Path) -> None:
    """Змінна не обходить перевірку кореня, і відмова називає джерело."""
    monkeypatch.setenv(W.ENV_WORKSPACE, str(Path.home()))
    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])
    assert res.exit_code == 2
    assert W.ENV_WORKSPACE in res.stdout
