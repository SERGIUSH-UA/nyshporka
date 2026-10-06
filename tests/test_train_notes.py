"""🧪 Навчальні пари з нотатника справи: кроп рядка ↔ звірене оком.

Що бережеться:

  · кроп — рівно той рядок, який звірили: рамка рушія, перерахована на кадр
    іншого розміру, без сусідів і полів;
  · набір нотатника не змішується з `gt`: корпус бере його джерелом `notes`;
  · повтор не дублює міток;
  · у пул кроп їде сірим JPEG у межах стелі, лише для рядків, яких пул ще не має;
  · пул без адмінських прав відповідає 404 — і це сказано словами.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()
CASE = "DAHMO/315/8433"
LINES = ["Кто совершалъ", "Священникъ Петръ", "Іоаннъ Ивановъ Коваль-", "пономъ Гри"]
BOXES = [[400, 970, 760, 1050], [340, 1190, 810, 1260], [345, 1380, 1900, 1450],
         [345, 1500, 800, 1560]]


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Справа з прогоном: геометрія 3000×4500, кадр на диску вдвічі більший."""
    from PIL import Image, ImageDraw

    from nyshporka.core import workspace as W

    # Лабораторія — окрема секція застосунку; без неї операції `train.*` закриті.
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="t", origin="test", preset="lab"))
    case_dir = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    case_dir.mkdir(parents=True)
    im = Image.new("RGB", (6000, 9000), "white")
    x0, y0, x1, y1 = (v * 2 for v in BOXES[2])
    ImageDraw.Draw(im).rectangle([x0, y0, x1 - 1, y1 - 1], fill="black")
    im.save(case_dir / "0004.jpg", quality=50)
    (case_dir / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    d = tmp_path / "reports" / "htr" / "проба"
    d.mkdir(parents=True)
    (d / "0004.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    (d / "0004.lines.json").write_text(json.dumps({"size": [3000, 4500], "boxes": BOXES}),
                                       encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic", "case_dir": str(case_dir),
        "case_key": CASE, "pages": {"0004.jpg": {"lines": len(LINES), "orient": 0}},
    }), encoding="utf-8")
    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    yield tmp_path
    W.reset()


def _run(*args: str) -> dict:
    from nyshporka.cli import app

    r = runner.invoke(app, [*args, "--json"])
    assert r.exit_code == 0, r.output
    got = json.loads(r.stdout)
    return got.get("data", got)


def _read(text: str = "Іоаннъ Ивановъ Ковальскій", *extra: str) -> str:
    return _run("note", "read", CASE, "4", "--line", "3", "--text", text, *extra)["notes"][0]["uid"]


def test_the_pair_is_exactly_the_verified_line(space: Path) -> None:
    from PIL import Image

    _read()
    got = _run("train", "from-notes", CASE)
    assert (got["readings"], got["with_box"], got["cut"], got["marked"]) == (1, 1, 1, 1)
    crop = space / "data" / "train" / "crops" / got["set"] / "0004" / "line_002.png"
    with Image.open(crop) as im:
        x0, y0, x1, y1 = BOXES[2]
        assert im.size == ((x1 - x0) * 2, (y1 - y0) * 2), "рамка не перерахована на кадр"
        assert im.convert("L").getextrema()[1] < 60, "у кроп потрапило поле чи сусід"
    from nyshporka.train import sets as S

    reg = S.registry()
    assert reg.load(got["set"]).origin == "notebook"
    mark = reg.marks(got["set"])[("0004", 2)]
    assert mark["text"] == "Іоаннъ Ивановъ Ковальскій" and mark["by"] == "notebook"


def test_a_second_pass_adds_no_marks(space: Path) -> None:
    _read()
    _run("train", "from-notes", CASE)
    again = _run("train", "from-notes", CASE)
    assert again["cut"] == 1 and again["marked"] == 0


def test_the_corpus_takes_notebook_sets_as_their_own_source(space: Path) -> None:
    from nyshporka.train import sets as S
    from nyshporka.train import sources as SRC

    _read()
    _run("train", "from-notes", CASE)
    reg = S.registry()
    assert SRC.read_gt(reg).rows == [], "набір нотатника не мусить іти в gt"
    (row,) = SRC.read_notes(reg).rows
    assert row[1] == "Іоаннъ Ивановъ Ковальскій"


def test_old_sets_read_as_runs_and_stay_byte_identical(tmp_path: Path) -> None:
    from nyshporka.train import sets as S

    spec = S.SetSpec.from_dict({"name": "x", "role": "train"})
    assert spec.origin == "run"
    assert "origin" not in spec.as_dict() and "cursor" not in spec.as_dict()


def test_pool_rows_become_a_pool_set_with_a_cursor(space: Path) -> None:
    from PIL import Image

    from nyshporka.train import notes as N
    from nyshporka.train import sets as S

    buf = io.BytesIO()
    Image.new("L", (300, 40), 0).save(buf, "JPEG")
    rows = [{"id": 7, "uid": "a" * 32, "book": "dazho-1-73-492", "shifra": "ДАЖО 1-73-492",
             "key": "DAZHO/1/73/492", "page": "p0531", "line": {"line_no": 153},
             "text": "Андрей Терешкевъ Грисюкъ 25", "by": "igor_m"}]
    got = N.from_pool(rows, lambda uid: buf.getvalue())
    assert got["cut"] == 1 and got["marked"] == 1
    reg = S.registry()
    spec = reg.load("pool-dazho-1-73-492")
    assert spec.origin == "pool"
    assert reg.marks(spec.name)[("p0531", 152)]["by"] == "pool:igor_m"
    assert N.pool_cursor() == 7


def test_push_sends_a_grey_jpeg_only_for_lines_the_pool_lacks(space: Path,
                                                             monkeypatch) -> None:
    from PIL import Image

    from nyshporka.share import upload

    uid = _read("Іоаннъ Ивановъ Ковальскій", "--share")
    sent: list[tuple[str, bytes]] = []
    monkeypatch.setattr(upload, "token", lambda: "t0k")
    monkeypatch.setattr(upload, "_request", lambda *a, **k: {
        "book": "dahmo-315-1-8433", "accepted": [uid], "need_crop": [uid]})
    monkeypatch.setattr(upload, "_put_bytes",
                        lambda url, blob, **k: sent.append((url, blob)) or 204)
    got = _run("note", "push", CASE, "--no-pages", "--base", "http://pool.test/v1")
    assert got["crops"]["sent"] == 1
    (url, blob), = sent
    assert url == f"http://pool.test/v1/notes/{uid}/crop"
    with Image.open(io.BytesIO(blob)) as im:
        assert im.format == "JPEG" and im.mode == "L"
    assert len(blob) <= 256 * 1024

    sent.clear()
    monkeypatch.setattr(upload, "_request", lambda *a, **k: {
        "book": "dahmo-315-1-8433", "known": [uid], "need_crop": []})
    assert _run("note", "push", CASE, "--no-pages")["crops"]["sent"] == 0 and not sent


def test_the_dry_run_says_what_sharing_a_line_means(space: Path) -> None:
    from nyshporka import ops as O

    _read("Іоаннъ Ивановъ Ковальскій", "--share")
    env = O.call("note.push", {"case": CASE, "pages": False, "dry_run": True})
    assert env.data["with_crop"] == 1
    assert any(w.code == "training" for w in env.warnings)


def test_from_pool_without_owner_rights_says_so(space: Path, monkeypatch) -> None:
    from nyshporka import ops as O
    from nyshporka.share import upload

    def nope(*a, **k):
        raise upload.UploadError("Not Found", status=404)

    monkeypatch.setattr(upload, "token", lambda: "t0k")
    monkeypatch.setattr(upload, "_request", nope)
    env = O.call("train.from_pool", {})
    assert not env.ok and "власника" in env.error


def test_a_retracted_reading_leaves_the_set(space: Path) -> None:
    from nyshporka.train import sets as S
    from nyshporka.train import sources as SRC

    uid = _read("Хибно прочитане")
    first = _run("train", "from-notes", CASE)
    _run("note", "retract", CASE, uid[:8])
    again = _run("train", "from-notes", CASE)
    assert again["withdrawn"] == 1
    assert S.registry().marks(first["set"])[("0004", 2)]["status"] == "skip"
    assert SRC.read_notes(S.registry()).rows == [], "відкликане не мусить іти в корпус"


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (300, 40), 0).save(buf, "JPEG")
    return buf.getvalue()


def _row(cid: int, uid: str, book: str = "dazho-1-73-492") -> dict:
    return {"cid": cid, "id": cid, "uid": uid, "book": book, "shifra": "ДАЖО",
            "key": "DAZHO/1/73/492", "page": "p0531", "line": {"line_no": cid},
            "text": f"рядок {cid}", "by": "igor_m"}


def test_the_pool_cursor_stops_before_a_failed_crop(space: Path) -> None:
    from nyshporka.train import notes as N

    def fetch(uid: str) -> bytes:
        if uid == "a" * 32:
            raise OSError("обрив")
        return _jpeg()

    rows = [_row(1, "a" * 32), _row(2, "b" * 32), _row(3, "c" * 32, book="other")]
    got = N.from_pool(rows, fetch)
    assert got["cursor"] == 0 and N.pool_cursor() == 0, "збій на рядку 1 мусить повторитись"
    again = N.from_pool([_row(1, "a" * 32)], lambda uid: _jpeg())
    assert again["cursor"] == 1


def test_a_line_withdrawn_in_the_pool_leaves_the_set(space: Path) -> None:
    from nyshporka.train import notes as N
    from nyshporka.train import sets as S

    N.from_pool([_row(5, "f" * 32)], lambda uid: _jpeg())
    got = N.from_pool([], lambda uid: _jpeg(), dead=["f" * 32])
    assert got["withdrawn"] == 1
    assert S.registry().marks("pool-dazho-1-73-492")[("p0531", 4)]["status"] == "skip"


def test_a_holdout_case_never_feeds_the_notes_source(space: Path) -> None:
    from nyshporka.train import sets as S
    from nyshporka.train import sources as SRC

    _read()
    _run("train", "from-notes", CASE)
    reg = S.registry()
    reg.save(S.SetSpec(name="ho", case="ДАХмО 315-1-8433", role="holdout"))
    it = SRC.read_notes(reg)
    assert it.rows == [] and any("holdout" in n for n in it.notes)
