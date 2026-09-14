"""Злиття нотаток сторінки не губить жодного коментаря.

🔴 Доти злиття клеїло «нове ⟂ старе» і різало на 600 символах. Нотатка
суцільної вичитки розвороту має 1–5 тис. символів, тож зріз мовчки з'їдав хвіст
нової нотатки, а старий коментар — цілком. Втрата тиха: запис лишається, статус
і прізвища на місці, бракує лише того, що хтось уже прочитав і пояснив.
"""
from __future__ import annotations

from nyshporka.pagestore.models import PageNote
from nyshporka.pagestore.store import _merge_note


def _note(comment: str, **kw) -> PageNote:
    return PageNote(scan="page_010", page_type="other", comment=comment, **kw)


def test_long_comments_survive_the_merge_whole() -> None:
    old = _note("старе " + "а" * 900)
    new = _note("нове " + "б" * 2400)
    merged = _merge_note(old, new)
    assert merged.comment == f"{new.comment} ⟂ {old.comment}"
    assert len(merged.comment) > 3300


def test_the_old_comment_is_not_dropped_when_the_new_one_alone_is_long() -> None:
    old = _note("попередження: це фальш-друг, не рід")
    new = _note("вичитка розвороту " + "в" * 1200)
    assert old.comment in _merge_note(old, new).comment


def test_a_repeated_comment_is_not_glued_twice() -> None:
    old = _note("той самий текст")
    assert _merge_note(old, _note("той самий текст")).comment == "той самий текст"


def test_an_empty_new_comment_keeps_the_old_one() -> None:
    assert _merge_note(_note("старе"), _note("")).comment == "старе"
