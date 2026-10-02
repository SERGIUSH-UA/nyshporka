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
    # Дві різні книги з тим самим номером: оп.1 і оп.2 спр.49.
    _sprava(tmp_path, "raw/op1-49", 3)
    _sprava(tmp_path, "raw/op2-49", 5)
    rows = [
        {"key": "CDIAK/224/1/49", "repo": "CDIAK", "fond": "224", "opys": "1",
         "spr": "49", "path": "raw/op1-49"},
        {"key": "CDIAK/224/2/49", "repo": "CDIAK", "fond": "224", "opys": "2",
         "spr": "49", "path": "raw/op2-49"},
    ]
    import nyshporka.core.workspace as ws
    import nyshporka.library as lib
    monkeypatch.setattr(ws, "workspace", lambda: SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(lib, "load_library", lambda: rows)
    return tmp_path


def test_kliuch_z_opysom_znakhodyt_same_tsiu_knygu(biblioteka: Path) -> None:
    assert align.case_dir_for("CDIAK/224/2/49") == biblioteka / "raw/op2-49/pages"
    assert align.case_dir_for("CDIAK/224/1/49") == biblioteka / "raw/op1-49/pages"
    # ключ до 0.22 (мета прогону, давній пакет) веде до тієї самої книги
    assert align.case_dir_for("CDIAK/224-2/49") == biblioteka / "raw/op2-49/pages"


def test_nevidomyi_opys_ne_bere_chuzhu_knygu(biblioteka: Path) -> None:
    assert align.case_dir_for("CDIAK/224/3/49") is None
    assert align.case_dir_for("CDIAK/224-3/49") is None


def test_saidkar_z_teky_vyshche_pages(biblioteka: Path) -> None:
    assert read_sidecar(biblioteka / "raw/op2-49/pages") == {"viewer_id": "49"}


def _bez_kadriv(root: Path, opys: str, frames: int) -> Path:
    d = root / "data" / "raw" / "cdiak_127" / "spr-1660"
    (d / "pages").mkdir(parents=True)
    (d / "_source.json").write_text(json.dumps({
        "opys": opys, "frames": frames, "viewer_id": "133462",
        "viewer_url": "https://archium.cdiak.archives.gov.ua/file-viewer/133462/"}),
        encoding="utf-8")
    (d / "_frames_removed.json").write_text(json.dumps({"frames_was": frames}),
                                            encoding="utf-8")
    return d


@pytest.fixture
def bez_kadriv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Кадри прибрано після читання, у бібліотеці справи немає."""
    import nyshporka.core.workspace as ws
    import nyshporka.library as lib
    raw = tmp_path / "data" / "raw"
    monkeypatch.setattr(ws, "workspace",
                        lambda: SimpleNamespace(root=tmp_path, case_roots=lambda: [raw]))
    monkeypatch.setattr(lib, "load_library", lambda: [])
    return tmp_path


def test_teka_bez_kadriv_daie_pasport_i_znamennyk(bez_kadriv: Path) -> None:
    from nyshporka.share.publish import _refs_from_sidecar, _znamennyk_z_pasporta

    d = _bez_kadriv(bez_kadriv, "1078", 169)
    assert align.case_dir_for("CDIAK/127-1078/1660") is None, "кадрів немає"
    home = align.case_home_for("CDIAK/127/1660", opys="1078")
    assert home == d
    assert _refs_from_sidecar(home)[0]["ref"] == "file:133462"
    blok = _znamennyk_z_pasporta({"total": 0, "listed": 0}, home)
    assert blok["total"] == 169 and blok["listed"] == 0


def test_teka_chuzhoho_opysu_ne_beretsia(bez_kadriv: Path) -> None:
    _bez_kadriv(bez_kadriv, "699", 40)
    assert align.case_home_for("CDIAK/127/1660", opys="1078") is None
    assert align.case_home_for("CDIAK/127-1078/1660") is None


def test_kod_os_bez_shliakhu() -> None:
    from nyshporka.share.upload import _kod_os

    exc = PermissionError(13, "Процес не має доступу", "imia/paket.nyshtext")
    got = _kod_os(exc)
    assert got.startswith("PermissionError errno=13")
    assert "imia" not in got and "paket" not in got
