"""`share.row` хешує лише пакет у просторі (аудит 29.09.2026).

Доти операція без токена рахувала sha256 будь-якого файла машини — відповідь
видавала, чи файл є і який у нього хеш, а мережевий шлях змушував Windows
іти на чужий SMB-сервер з NTLM-хешем людини.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    (tmp_path / "ws").mkdir()
    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


@pytest.fixture
def no_hash(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Хеш не рахується для відхиленого шляху — його не має бути взагалі."""
    from nyshporka.share import bundle

    seen: list[str] = []
    monkeypatch.setattr(bundle, "sha256_of", lambda p, *a, **k: seen.append(str(p)) or "x")
    return seen


def test_file_outside_space_is_refused(space: Path, tmp_path: Path, no_hash: list[str]) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("таємне", encoding="utf-8")
    env = O.call("share.row", {"path": str(secret)})
    assert not env.ok and "просторі" in env.error and "пакета немає" not in env.error
    env = O.call("share.row", {"path": str(space / ".." / "secret.txt")})
    assert not env.ok and "просторі" in env.error
    assert no_hash == []


@pytest.mark.parametrize("unc", ["\\\\evil-host\\share\\x.tar", "//evil-host/share/x.tar",
                                 "\\\\?\\UNC\\evil-host\\x"])
def test_unc_is_refused_before_touching_disk(space: Path, unc: str, no_hash: list[str],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> bool:
        raise AssertionError("мережевий шлях дійшов до звертання до диска")

    monkeypatch.setattr(Path, "is_file", boom)
    env = O.call("share.row", {"path": unc})
    assert not env.ok and "мережевий" in env.error


def test_file_inside_space_passes_the_guard(space: Path, no_hash: list[str]) -> None:
    f = space / "share" / "outbox" / "not-a-bundle.tar"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"zzz")
    env = O.call("share.row", {"path": str(f)})
    assert not env.ok and "не прочитати пакет" in env.error


def test_share_row_needs_token_in_daemon() -> None:
    op = O.get("share.row")
    assert op is not None and op.private
