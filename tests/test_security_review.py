"""Регресії з рев'ю безпеки й стабільності 2026-09-06.

Кожен тест тут — конкретна діра або збій, знайдені при читанні коду: шлях із
чужого архіву чи чужого JSON, що виводить за теку; формула в CSV; довга
операція без токена; тека призначення, яка не підставлялась; наглядач, який
повертав 0 на порожній теці.
"""
from __future__ import annotations

import csv
import tarfile
from pathlib import Path

import pytest

from nyshporka import tabular
from nyshporka.cloud import run as RUN
from nyshporka.htr import pdfpage
from nyshporka.utils.fsname import UnsafeName, safe_filename


# ── tar з чужої машини ───────────────────────────────────────────────────────
@pytest.mark.parametrize("arcname", [
    "out/..\\..\\стороннє.txt",        # backslash усередині POSIX-компонента
    "out/C:стороннє.txt",              # диск-відносне ім'я Windows
    "out-diak_v4/..\\стороннє.txt",    # те саме через теку голосу
    "logs/../../стороннє.txt",
])
def test_unpack_refuses_windows_style_escapes(tmp_path: Path, arcname: str) -> None:
    """🔴 `".." in rest` ловило лише POSIX-роздільник; `\\` і `C:` проходили."""
    payload = tmp_path / "evil.txt"
    payload.write_text("шкода", encoding="utf-8")
    tar_path = tmp_path / "r.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(payload, arcname=arcname)

    out_dir = tmp_path / "reports" / "sprava"
    RUN.unpack(tar_path, out_dir)
    stray = [p for p in tmp_path.rglob("стороннє.txt")]
    assert not stray, f"файл ліг поза текою виходу: {stray}"


def test_unpack_still_places_honest_members(tmp_path: Path) -> None:
    payload = tmp_path / "0001.txt"
    payload.write_text("текст", encoding="utf-8")
    tar_path = tmp_path / "r.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(payload, arcname="out/0001.txt")
        tar.add(payload, arcname="out-diak_v4/0001.txt")
        tar.add(payload, arcname="logs/shard1.log")
    out_dir = tmp_path / "reports" / "sprava"
    RUN.unpack(tar_path, out_dir)
    assert (out_dir / "0001.txt").read_text(encoding="utf-8") == "текст"
    assert (out_dir.with_name("sprava-diak_v4") / "0001.txt").is_file()
    assert (out_dir / "logs" / "shard1.log").is_file()


# ── ім'я кадру з чужого JSON ─────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "..\\..\\x.jpg", "../x.jpg", "C:\\x.jpg", "a/b.jpg", "CON.jpg", "nul",
    "", " x.jpg", "x\x00.jpg", "x" * 201,
])
def test_safe_filename_refuses(bad: str) -> None:
    with pytest.raises(UnsafeName):
        safe_filename(bad)


@pytest.mark.parametrize("ok", ["0042.jpg", "М'ястківка_0001.JPG", "f792-1-55_0042.png"])
def test_safe_filename_accepts_honest_names(ok: str) -> None:
    assert safe_filename(ok) == ok


# ── CSV-ін'єкція ─────────────────────────────────────────────────────────────
def test_csv_neutralises_formulas(tmp_path: Path) -> None:
    """Текст із декоду може починатись з `=`; Excel виконав би його як формулу."""
    dest = tmp_path / "t.csv"
    rows = [{"a": "=HYPERLINK(\"http://evil\")", "b": "-1+cmd|' /C calc'!A0",
             "c": "звичайний текст", "d": "+380"}]
    tabular.write_delimited(dest, ["a", "b", "c", "d"], rows, human=False)
    with dest.open(encoding="utf-8-sig", newline="") as fh:
        got = list(csv.reader(fh))[1]
    assert got[0].startswith("'=")
    assert got[1].startswith("'-")
    assert got[2] == "звичайний текст"
    assert got[3].startswith("'+")


# ── номер кадру в імені ──────────────────────────────────────────────────────
def test_frame_number_takes_the_last_number() -> None:
    """`f792-1-55_0042.jpg` — кадр 42, а не фонд 792."""
    assert pdfpage.frame_number("f792-1-55_0042.jpg") == 42
    assert pdfpage.frame_number("00042.jpg") == 42
    assert pdfpage.frame_number("без-числа.jpg") is None


# ── демон: довга операція вимагає токена ─────────────────────────────────────
def test_long_op_requires_token() -> None:
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from nyshporka.core.workspace import Workspace
    from nyshporka.daemon.app import create_app

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "data" / "derived").mkdir(parents=True)
        (root / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
        ws = Workspace(root=root, name="тест", origin="test")
        client = TestClient(create_app(ws, token="t0k"), base_url="http://127.0.0.1:8788")
        r = client.post("/api/op/search.sweep", json={"q": "Іваненко"})
        assert r.status_code == 403, "довга операція стала в чергу без токена"
