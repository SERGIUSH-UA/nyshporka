"""Відбір файлів сховища за ключем справи: за ключем У ФАЙЛІ, а не за іменем.

Мапа «ключ → файли» читає лише ключ (`query._key_of`), без індексу прізвищ.
Тут стережеться, що відбір за ключем і далі віддає рівно файли справи — і в
знімку (`one_snapshot`), і без нього, — а свіжий запис у файл видно одразу.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nyshporka.pagestore import query as Q
from nyshporka.pagestore import store

KEY = "DAHMO/315/1/8433"
OTHER = "DAHMO/315/1/9000"


def _put(root: Path, rel: str, key: str, surname: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "shifra": key, "pages": {
        "0001.jpg": {"surnames": [surname], "status": "full"}}},
        ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "pages_root", lambda: tmp_path)
    Q._CACHE.clear()
    Q._KEYS.clear()
    # ім'я файла навмисно чуже: справа визначається ключем усередині
    _put(tmp_path, "DAHMO/315-1-9000.json", KEY, "Ковальчинскій")
    _put(tmp_path, "DAHMO/315-1-8433.json", OTHER, "Ковальчинская")
    return tmp_path


def _shifry(case_key: str) -> list[str]:
    got = Q.grep_surnames("Ковальчинскій", case_key=case_key, profile=False,
                          given=False, rank_hits=False)
    return sorted({h["shifra"] for h in got["hits"]})


@pytest.mark.parametrize("snap", [False, True])
def test_case_key_selects_by_key_inside_file(root: Path, snap: bool) -> None:
    if snap:
        with Q.one_snapshot():
            assert _shifry(KEY) == [KEY]
            assert _shifry(OTHER) == [OTHER]
    else:
        assert _shifry(KEY) == [KEY]
        assert _shifry(OTHER) == [OTHER]


def test_rewritten_key_is_seen_without_restart(root: Path) -> None:
    assert _shifry(KEY) == [KEY]
    p = _put(root, "DAHMO/315-1-9000.json", OTHER, "Ковальчинскій")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert _shifry(KEY) == []
    assert _shifry(OTHER) == [OTHER]
