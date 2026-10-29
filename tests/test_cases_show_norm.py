"""`cases show` знаходить справу за шифрою, написаною не так, як канонічний ключ."""
from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.cases import cli as cases_cli

ROW = {"key": "DAHMO/227/5dop/291", "shifra": "ДАХмО 227-5доп-291",
       "title": "Статистичний опис м. Ольгополь"}


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def query_rows(q: str = "", **_: Any) -> list[dict[str, Any]]:
        asked.append(q)
        return [ROW] if q and (q in ROW["key"] or q in ROW["shifra"]) else []

    monkeypatch.setattr(cases_cli.db, "query_rows", query_rows)
    monkeypatch.setattr(cases_cli, "_warn_stale", lambda: None)
    return asked


@pytest.mark.parametrize("q", [
    "DAHMO/227/5доп/291",     # ключ кирилицею — підрядком не збігається
    "ДАХмО 227-5dop-291",     # шифра латинкою
    "DAHMO/227/5dop/291",     # канонічний ключ — як і раніше
])
def test_show_finds_case_in_any_script(registry: list[str], q: str) -> None:
    out = CliRunner().invoke(cases_cli.app, ["show", q, "--json"])
    assert out.exit_code == 0, out.output
    assert '"DAHMO/227/5dop/291"' in out.output


def test_show_title_substring_untouched(registry: list[str]) -> None:
    """Підрядок назви не шифра: розбір не підміняє запит і не падає."""
    out = CliRunner().invoke(cases_cli.app, ["show", "Ольгопол"])
    assert out.exit_code == 1
    assert "не знайшов справу" in out.output
