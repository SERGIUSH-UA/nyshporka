"""Гард розпакування чужого архіву — один на два розпакувальники.

🔴 Перевірка ПОКОМПОНЕНТНА, а не на підрядок `..`. На Windows `joinpath`
розбирає `\\` і `C:` усередині одного POSIX-компонента, тож `out/..\\..\\evil`
проходив фільтр на підрядок і лягав на два рівні вище. Тест тримає саме цей
випадок, бо він уже одного разу був.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.utils import tarsafe


@pytest.mark.parametrize("part", ["0001.txt", "_htr_meta.json", "spr-8433"])
def test_plain_names_pass(part: str) -> None:
    assert tarsafe.safe_member_part(part)


@pytest.mark.parametrize("part", [
    "", ".", "..", " лишок", "лишок ",
    r"..\..\evil", "C:evil", "a\x00b", "a\\b",
])
def test_dangerous_names_are_refused(part: str) -> None:
    assert not tarsafe.safe_member_part(part)


def test_empty_path_is_not_a_path() -> None:
    assert not tarsafe.safe_member_parts(())
    assert tarsafe.safe_member_parts(("spr", "0001.txt"))
    assert not tarsafe.safe_member_parts(("spr", ".."))


def test_under_is_the_second_line(tmp_path: Path) -> None:
    base = tmp_path / "runs"
    assert tarsafe.under(base / "a" / "b.txt", base)
    assert not tarsafe.under(tmp_path / "evil.txt", base)
    assert not tarsafe.under(base.parent, base)


def test_cloud_fetch_uses_the_same_guard() -> None:
    """Друга копія цього виправлення розійшлася б із першою мовчки."""
    from nyshporka.cloud import run as R

    assert R._safe_member_part is tarsafe.safe_member_part
    assert R._under is tarsafe.under
