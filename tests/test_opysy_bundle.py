"""Пакет опису `.nyshopys`: пакування з робочої теки, відтворюваність, прийом чужих байтів."""
from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from nyshporka.opysy import bundle as B

SHA = "b" * 64


def _work(tmp: Path, *, rows: list[dict] | None = None, fond: str = "445",
          title_norm: str = "", repo: str = "DAOO") -> Path:
    work = tmp / "work"
    work.mkdir()
    manifest = {
        "schema": 1, "repo": repo, "fond": fond, "opys": "1", "language": "ru",
        "sources": [{"kind": "archive_site", "url": "https://archive.example/0445_01.djvu",
                     "sha256": SHA, "pages": 2, "label": "0445_01.djvu"}],
        "engines": ["pysar_v31"], "license": "CC-BY-4.0",
        "quality": {"klass": "mid", "form": "hand_ruled"},
    }
    if title_norm:
        manifest["normalization"] = {"prompt": "norm_prompt", "version": "1", "model": "sonnet"}
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    pages = [{"page": 1, "voices": {"pysar": "Дело о крестьянине Ивана Петренка"}},
             {"page": 2, "voices": {"pysar": "Дело о мещанине"}}]
    (work / "pages.jsonl").write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pages),
                                      encoding="utf-8")
    rows = rows if rows is not None else [
        {"regions": [{"page": 1, "y0": 0.1, "y1": 0.2}], "no_raw": "1", "no": 1,
         "no_status": "chain", "title_raw": "Дело о крестьянине Ивана Петренка",
         "title_norm": title_norm, "rk": "чужий"},
        {"regions": [{"page": 2, "y0": 0.1, "y1": 0.2}], "no_raw": "2", "no": 2,
         "no_status": "chain", "title_raw": "Дело о мещанине"},
    ]
    (work / "rows.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                                     encoding="utf-8")
    return work


def test_pack_roundtrip_and_recomputed_keys(tmp_path: Path) -> None:
    work = _work(tmp_path, title_norm="Дело о крестьянине Ивана Петренка")
    rep = B.pack(work, tmp_path / "out" / "daoo-445-1")
    assert rep.verdict.passed, rep.verdict.refusals
    assert rep.file is not None and rep.file.suffix == B.SUFFIX
    assert rep.summary["pages_read"] == 2 and rep.summary["rows"] == 2
    c, v = B.verify(rep.file.read_bytes())
    assert v.passed, v.refusals
    assert all(r["rk"] and r["rk"] != "чужий" for r in c.rows)
    from nyshporka.opysy.gates import parse

    _, _, rows, _ = parse(c.manifest, c.pages, c.rows)
    assert {n["name"] for n in B.name_records(rows)} == {"Ивана", "Петренка"}


def test_pack_is_reproducible(tmp_path: Path) -> None:
    work = _work(tmp_path)
    a = B.pack(work, tmp_path / "a")
    b = B.pack(work, tmp_path / "b")
    assert a.sha256 == b.sha256 and a.sha256


def test_refused_pack_writes_nothing(tmp_path: Path) -> None:
    assert B.pack(_work(tmp_path, fond="442"), tmp_path / "ok").verdict.passed  # ДАОО ф.442 — інший фонд
    (tmp_path / "ok.nyshopys").unlink()
    import shutil
    shutil.rmtree(tmp_path / "work")
    work = _work(tmp_path, fond="442", repo="ЦДІАК")
    rep = B.pack(work, tmp_path / "x")
    assert not rep.verdict.passed and rep.file is None
    assert not list(tmp_path.glob("*.nyshopys"))


def test_tampered_key_refused_on_receive(tmp_path: Path) -> None:
    rep = B.pack(_work(tmp_path), tmp_path / "p")
    assert rep.file is not None
    c = B.decode(rep.file.read_bytes())
    c.rows[0]["rk"] = "0" * 20
    blob = _rebuild(c)
    _, v = B.verify(blob)
    assert "row_bad_key" in {d["rule"] for d in v.refusal_details}


def _rebuild(c: B.Contents) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, items in ((B.MANIFEST, None), (B.PAGES, c.pages), (B.ROWS, c.rows)):
            data = (json.dumps(c.manifest).encode() if items is None
                    else "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items).encode())
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


def test_decode_refuses_foreign_member_and_garbage() -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo("../evil.sh")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(B.BundleError, match=r"немає manifest\.json"):
        B.decode(gzip.compress(raw.getvalue()))
    with pytest.raises(B.BundleError):
        B.decode(b"not a tarball")


def test_newer_schema_named_before_foreign_member(tmp_path: Path) -> None:
    rep = B.pack(_work(tmp_path), tmp_path / "p")
    assert rep.file is not None
    c = B.decode(rep.file.read_bytes())
    c.manifest["schema"] = 99
    raw = io.BytesIO(gzip.decompress(_rebuild(c)))
    with tarfile.open(fileobj=raw, mode="a") as tar:
        info = tarfile.TarInfo("rules.jsonl")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(B.BundleError, match=r"схема пакета 99 новіша"):
        B.decode(gzip.compress(raw.getvalue()))


def test_workdir_bad_json_line_named(tmp_path: Path) -> None:
    work = _work(tmp_path)
    (work / "rows.jsonl").write_text('{"title_raw": "x"}\n{bad', encoding="utf-8")
    with pytest.raises(B.BundleError, match=r"rows\.jsonl, рядок 2"):
        B.read_workdir(work)
