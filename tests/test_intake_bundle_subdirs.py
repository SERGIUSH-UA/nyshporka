"""🗃 «Приймальня»: збірка без кадрів показує, скільки в ній тек, а не «0 кадрів»."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_bundle_without_frames_counts_its_folders(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import nyshporka.core.workspace as W
    from nyshporka.ops_builtin import _bundle_subdirs

    bundle = tmp_path / "data" / "raw" / "plivky"
    for name in ("2086525_0181-0189", "2102930_0309-0313", "2103331_0361-0368"):
        (bundle / name).mkdir(parents=True)
    (bundle / "_source.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(W, "workspace", lambda: SimpleNamespace(root=tmp_path))

    rows = [
        {"kind": "bundle", "frames": 0, "path": "data/raw/plivky"},
        {"kind": "bundle", "frames": 12, "path": "data/raw/plivky"},
        {"kind": "unfiled", "frames": 0, "path": "data/raw/plivky"},
        {"kind": "bundle", "frames": 0, "path": "data/raw/nema"},
    ]
    _bundle_subdirs(rows)
    assert rows[0]["subdirs"] == 3, "файл поруч із теками — не тека"
    assert "subdirs" not in rows[1], "збірка з кадрами показує кадри"
    assert "subdirs" not in rows[2], "звичайна тека без шифри — не збірка"
    assert "subdirs" not in rows[3] and rows[3]["missing"] is True, (
        "теки немає — так і сказано, а не нуль")
