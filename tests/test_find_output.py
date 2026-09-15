"""🖨 `nysh find` друкує те, що прийшло від джерела, дослівно — і не падає.

Примітка знахідки `ia` несе сирий OCR газет, а в ньому квадратні дужки — звична
річ. Rich читав `[/Ред.]` як закривальний тег і обривав увесь вивід разом зі
знаменником (верифікатор релізу 0.16.0, 15.09.2026).
"""
from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.sources.base import Hit, SourceAbout, SourceScope

runner = CliRunner()


class _Brackets:
    id = "x-brackets"
    label = "Дужки"
    caps = frozenset({"search"})

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        return [Hit(source=self.id, ref="r:1", title="Іван [/Ред.] Креницька",
                    note="[sic] з OCR [b]не жирне[/b]")]


class _Zero:
    id = "x-zero"
    label = "Нуль"
    caps = frozenset({"search"})
    about = SourceAbout(answers="питання", gives="щось", not_gives="інше",
                        where_class="фотоархів дослідника", scope=SourceScope(),
                        match_on=("title",), match_how="substring",
                        zero_means="ZEROMEANS")

    def search(self, q: str, *, limit: int = 30) -> list[Any]:
        return []


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.sources import registry

    monkeypatch.setattr(registry, "_from_entry_points",
                        lambda: ([_Brackets(), _Zero()], []))


def test_brackets_from_a_source_are_printed_not_parsed(plugins: None) -> None:
    res = runner.invoke(app, ["find", "Креницька", "--source", "x-brackets", "--text"])
    assert res.exit_code == 0, res.stdout
    assert "[/Ред.]" in res.stdout and "[sic]" in res.stdout and "[b]" in res.stdout
    assert "знайдено 1" in res.stdout, "знаменник мусить доїхати до кінця виводу"


def test_a_total_zero_names_each_meaning_once(plugins: None) -> None:
    res = runner.invoke(app, ["find", "щосьтакенемає", "--source", "x-zero", "--text"])
    assert res.exit_code == 0, res.stdout
    assert res.stdout.count("ZEROMEANS") == 1, (
        "на повний нуль сенс нуля стоїть у попередженні — рядок `0 · …` його дублював")
