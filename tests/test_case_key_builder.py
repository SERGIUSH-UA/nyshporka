"""Ключ справи збирає тільки `_mk_key` — f-рядок повз нього заборонений.

Підстава — інцидент 2026-08-25. Фонд перевели на ключ-з-описом
(`_OPYS_IN_KEY`), і збірка реєстру відв'язала від справи канон: картка
показала «фактів 0» там, де канон цитує аркуш дослівно. Причина була не в
міграції, а в тому, що `cases/collect.py` у трьох місцях складав ключ як
`f"{repo}/{fond}/{spr}"` — тобто опис у ньому не з'являвся ніколи, хоч би що
казав `_OPYS_IN_KEY`.

Помилка мовчазна за побудовою: рядок збирається успішно, просто не влучає в
жоден запис реєстру. Тому приймач тут не на поведінку, а на форму коду.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nyshporka.library import _OPYS_IN_KEY, _mk_key, candidate_keys

PKG = Path(__file__).resolve().parents[1] / "src" / "nyshporka"

#: `f"{repo}/{fond}/{spr}"` і подібне: три поля через слеш усередині f-рядка.
HAND_BUILT = re.compile(r'f"\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}"')


def test_no_hand_built_case_keys() -> None:
    """У пакеті `cases` ключ не збирається f-рядком із трьох полів."""
    findings: list[str] = []
    for path in sorted((PKG / "cases").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HAND_BUILT.search(line):
                findings.append(f"{path.name}:{n}: {line.strip()}")
    assert not findings, (
        "ключ справи зібрано f-рядком повз `_mk_key` — у фондах із `_OPYS_IN_KEY` "
        "такий ключ не несе опису й не влучає в реєстр:\n" + "\n".join(findings))


@pytest.mark.parametrize("fond_in_key", sorted(_OPYS_IN_KEY))
def test_opys_fond_keys_carry_opys(fond_in_key: tuple[str, str]) -> None:
    """Для фонду з `_OPYS_IN_KEY` ключ без опису й ключ З описом — різні."""
    repo, fond = fond_in_key
    with_opys = _mk_key(repo, fond, "13", "3")
    without = _mk_key(repo, fond, "13")
    assert with_opys != without
    assert with_opys == f"{repo}/{fond}-3/13"


def test_candidate_keys_offers_default_opys() -> None:
    """Форма без опису мусить лишатись знаходжуваною через опис за замовчуванням.

    ID джерела канону (`S_<архів>_F<фонд>_D<справа>`) опису не несе — і без
    цього кандидата канон відв'язується від справи щойно фонд переходить на
    ключ-з-описом.
    """
    from nyshporka.library import _DEFAULT_OPYS

    for (repo, fond), default in _DEFAULT_OPYS.items():
        if (repo, fond) not in _OPYS_IN_KEY:
            continue
        keys = candidate_keys((repo, fond, None, "13"))
        assert f"{repo}/{fond}-{default}/13" in keys, (
            f"{repo} ф.{fond}: серед кандидатів немає форми з описом за "
            f"замовчуванням — канон і сховище сторінок відв'яжуться")
