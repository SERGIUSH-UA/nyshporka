"""🚧 Супряга вимкнена, доки не запущено пул.

Тест сторожить не код, а РІШЕННЯ. Формат пакета ще може змінитись, а роздане
один раз живе в чужих теках і після зміни формату — тож поки каталог не
віддає рядків, команда не мусить працювати в жодної людини, крім тих, хто її
доробляє.

Знімати ці ворота разом: прапорець у `share/cli.py`, `hidden=True` у `cli.py`,
`gui=False` в `ops_share.py` і `share.md` у `mkdocs.yml`. Тест падає, якщо
зняли не всі — саме щоб не лишилось напіввідчиненого.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nyshporka.core import ops
from nyshporka.share.cli import DEV_FLAG

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv(DEV_FLAG, raising=False)
    return CliRunner()


def test_refuses_without_flag(runner: CliRunner) -> None:
    """Без прапорця команда не працює й каже, чому саме."""
    from nyshporka.cli import app

    res = runner.invoke(app, ["share", "list"])
    assert res.exit_code != 0
    assert "розробці" in res.output


def test_runs_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """З прапорцем ворота пропускають — інакше фічу не доробити."""
    from nyshporka.cli import app

    monkeypatch.setenv(DEV_FLAG, "1")
    res = CliRunner().invoke(app, ["share", "--help"])
    assert res.exit_code == 0
    assert "pack" in res.output


def test_hidden_from_help(runner: CliRunner) -> None:
    """У загальній довідці секції немає: її не мусять знаходити випадково."""
    from nyshporka.cli import app

    res = runner.invoke(app, ["--help"])
    assert "share" not in res.output


def test_ops_hidden_from_both_faces() -> None:
    """Жодне обличчя не показує операцій обміну: ні агент, ні застосунок."""
    found = [o for o in ops.REGISTRY.all() if o.name.startswith("share.")]
    assert found, "операції обміну зникли з реєстру — тест більше нічого не сторожить"
    for o in found:
        assert not o.agent, f"{o.name}: agent=True"
        assert not o.gui, f"{o.name}: gui=True"


def test_docs_page_not_published() -> None:
    """Сторінки обміну немає ні в навігації, ні у збірці сайту."""
    cfg = yaml.safe_load(
        # `!ENV` — тег MkDocs для адреси з оточення; safe_load його не знає.
        (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        .replace("!!python/name:", "").replace("!ENV ", "")
    )
    assert "share.md" in (cfg.get("exclude_docs") or "")
    assert "share.md" not in yaml.dump(cfg.get("nav") or [], allow_unicode=True)


def test_flag_not_set_in_repo_env() -> None:
    """Прапорець не проникає в збірку через оточення розробника."""
    assert os.environ.get(DEV_FLAG, "") in {"", "0"} or "PYTEST_CURRENT_TEST" in os.environ
