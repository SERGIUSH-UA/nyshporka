"""Тека кадрів справи для пакета: ключ з описом і кадри в `pages/`.

Справи ЦДІАК, узяті з ARCHIUM, їхали в пул без кадрів, без відбитка й без
посилання на скани: ключ пакета `CDIAK/224-2/49`, у бібліотеці — `CDIAK/224/49`
з описом окремим полем, а кадри — у підтеці `pages/`.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nyshporka.cases.register import read_sidecar
from nyshporka.share import align


def _sprava(root: Path, rel: str, n: int) -> None:
    pages = root / rel / "pages"
    pages.mkdir(parents=True)
    for i in range(n):
        (pages / f"{i + 1:04d}.jpg").write_bytes(b"\xff\xd8")
    (root / rel / "meta.json").write_text(json.dumps({"viewer_id": rel[-2:]}),
                                          encoding="utf-8")


@pytest.fixture
def biblioteka(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Під одним ключем без опису — дві різні книги: оп.1 і оп.2 спр.49.
    _sprava(tmp_path, "raw/op1-49", 3)
    _sprava(tmp_path, "raw/op2-49", 5)
    rows = [
        {"key": "CDIAK/224/49", "repo": "CDIAK", "fond": "224", "opys": "1",
         "spr": "49", "path": "raw/op1-49"},
        {"key": "CDIAK/224/49", "repo": "CDIAK", "fond": "224", "opys": "2",
         "spr": "49", "path": "raw/op2-49"},
    ]
    import nyshporka.core.workspace as ws
    import nyshporka.library as lib
    monkeypatch.setattr(ws, "workspace", lambda: SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(lib, "load_library", lambda: rows)
    return tmp_path


def test_kliuch_z_opysom_znakhodyt_same_tsiu_knygu(biblioteka: Path) -> None:
    got = align.case_dir_for("CDIAK/224-2/49")
    assert got == biblioteka / "raw/op2-49/pages"
    assert align.case_dir_for("CDIAK/224-1/49") == biblioteka / "raw/op1-49/pages"


def test_nevidomyi_opys_ne_bere_chuzhu_knygu(biblioteka: Path) -> None:
    assert align.case_dir_for("CDIAK/224-3/49") is None


def test_saidkar_z_teky_vyshche_pages(biblioteka: Path) -> None:
    assert read_sidecar(biblioteka / "raw/op2-49/pages") == {"viewer_id": "49"}
