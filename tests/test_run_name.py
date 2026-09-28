"""Ім'я прогону: голе, поки теку не займе ІНША справа (`spr-145` у двох фондах)."""
from __future__ import annotations

import json
from pathlib import Path

from nyshporka.cloud import frames as F
from nyshporka.htr.runname import run_name


def _run(reports: Path, name: str, **meta: object) -> None:
    d = reports / name
    d.mkdir(parents=True)
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _case(tmp_path: Path, archive: str, name: str = "spr-145") -> Path:
    d = tmp_path / "raw" / archive / name / "pages"
    d.mkdir(parents=True)
    return d


def test_free_name_stays_bare(tmp_path: Path) -> None:
    case = _case(tmp_path, "cdiak_2")
    assert run_name(case, "CDIAK/2/145", reports=tmp_path / "rep") == "spr-145"


def test_own_earlier_run_keeps_the_bare_name(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    case = _case(tmp_path, "cdiak_224")
    _run(rep, "spr-145", case_key="CDIAK/224/145", case_dir=str(case))
    assert run_name(case, "CDIAK/224/145", reports=rep) == "spr-145"


def test_other_case_gets_the_archive_folder(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    _run(rep, "spr-145", case_key="CDIAK/224/145")
    case = _case(tmp_path, "cdiak_2")
    assert run_name(case, "CDIAK/2/145", reports=rep) == "cdiak_2-spr-145"


def test_without_keys_the_case_dir_decides(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    mine, other = _case(tmp_path, "cdiak_224"), _case(tmp_path, "cdiak_2")
    _run(rep, "spr-145", case_dir=str(mine).replace("\\", "/"))
    assert run_name(mine, reports=rep) == "spr-145"
    assert run_name(other, reports=rep) == "cdiak_2-spr-145"


def test_no_proof_means_no_rename(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    case = _case(tmp_path, "cdiak_2")
    _run(rep, "spr-145")                      # мета без ключа й теки
    assert run_name(case, "CDIAK/2/145", reports=rep) == "spr-145"
    (rep / "spr-145" / "_htr_meta.json").write_text("{битий", encoding="utf-8")
    assert run_name(case, "CDIAK/2/145", reports=rep) == "spr-145"


def test_shrunk_copy_in_meta_is_not_proof(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    case = _case(tmp_path, "cdiak_2")
    _run(rep, "spr-145", case_dir="E:/x/derived/cloud/frames/spr-145")
    assert run_name(case, reports=rep) == "spr-145"


def test_flat_case_dir_without_pages(tmp_path: Path) -> None:
    rep = tmp_path / "rep"
    _run(rep, "spr-9", case_key="A/1/9")
    flat = tmp_path / "raw" / "cdiak_2" / "spr-9"
    flat.mkdir(parents=True)
    assert run_name(flat, "A/2/9", reports=rep) == "cdiak_2-spr-9"


def test_shrink_dir_follows_the_run_name(tmp_path: Path, monkeypatch) -> None:
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    case = _case(tmp_path, "cdiak_2")
    assert F.shrink_dir_for(case).name == "spr-145"
    assert F.shrink_dir_for(case, name="cdiak_2-spr-145").name == "cdiak_2-spr-145"
