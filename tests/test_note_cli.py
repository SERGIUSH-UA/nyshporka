"""📓 `nysh note`: командний контракт нотатника справи.

Перевіряється те, що людина й агент роблять руками: дописати, позначити,
повернути додому, відкликати, подивитись, що поїде, віддати, забрати чуже.
Пул підмінено: тест не ходить у мережу, а дивиться, ЩО саме пішло б.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()
CASE = "DAHMO/315/8433"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    (d / "0106.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    return tmp_path


def _run(*args: str) -> dict:
    r = runner.invoke(app, [*args, "--json"])
    assert r.exit_code == 0, r.output
    got = json.loads(r.stdout)
    return got.get("data", got)


def _fail(*args: str) -> str:
    r = runner.invoke(app, [*args, "--json"])
    assert r.exit_code != 0 or not json.loads(r.stdout).get("ok", True), r.output
    return r.output


def test_add_and_list(case):
    got = _run("note", "add", CASE, "--kind", "copy", "--other", "ДАВіО 904-24-55",
               "--relation", "copy", "--text", "копія в консисторії")
    uid = got["notes"][0]["uid"]
    listed = _run("note", "list", CASE)
    assert [n["uid"] for n in listed["notes"]] == [uid]
    assert listed["by_kind"] == {"copy": 1}


def test_a_line_reading_goes_through_read_not_add(case):
    assert "note read" in _fail("note", "add", CASE, "--kind", "reading", "--text", "x")


def test_personal_stays_home_even_when_asked(case):
    assert "не віддається" in _fail("note", "add", CASE, "--kind", "note",
                                     "--text", "мій дід", "--share")


def test_share_then_home_then_push_sends_only_a_retraction(case):
    uid = _run("note", "add", CASE, "--kind", "about", "--text",
               "Метрична книга 1834–1836", "--share")["notes"][0]["uid"]
    first = _run("note", "push", CASE, "--dry-run", "--no-pages")
    assert [e["uid"] for e in first["body"]["entries"]] == [uid]

    _run("note", "share", CASE, uid[:8], "--home")
    second = _run("note", "push", CASE, "--dry-run", "--no-pages")
    assert second["body"]["entries"] == [{"retracts": uid, "kind": "about"}]
    assert len(_run("note", "list", CASE, "--history")["notes"]) == 2


def test_retract_hides_the_entry(case):
    uid = _run("note", "add", CASE, "--kind", "about", "--text", "опис")["notes"][0]["uid"]
    _run("note", "retract", CASE, uid[:8])
    assert _run("note", "list", CASE)["notes"] == []


def test_the_gate_names_what_will_not_pass(case):
    _run("note", "add", CASE, "--kind", "about", "--text", "тут хрестили мого прадіда",
         "--share")
    got = _run("note", "push", CASE, "--dry-run", "--no-pages")
    assert got["entries"] == 0 and got["refused"][0]["kind"] == "about"


def test_the_page_digest_rides_without_comments(case):
    _run("pages", "note", CASE, "0106.jpg", "--type", "birth", "--status", "full",
         "--surnames", "Ковальскій", "--comment", "наш рід, Ян",
         "--agent", "сесія пошуку Ковальських")
    got = _run("note", "push", CASE, "--dry-run")
    (page,) = got["body"]["pages"]
    assert page["surnames"] == ["Ковальскій"]
    assert "comment" not in page and "agent" not in page


def test_push_posts_the_body_and_reports_the_pool(case, monkeypatch):
    from nyshporka.share import upload

    sent: dict = {}

    def fake(method, url, *, body=None, auth=""):
        sent.update(method=method, url=url, body=body, auth=auth)
        return {"book": "davo-904-24-54", "accepted": [e["uid"] for e in body["entries"]],
                "refused": []}

    monkeypatch.setattr(upload, "_request", fake)
    monkeypatch.setattr(upload, "token", lambda: "t0k")
    _run("note", "add", CASE, "--kind", "about", "--text", "опис", "--share")
    got = _run("note", "push", CASE, "--base", "http://pool.test/v1")
    assert sent["method"] == "POST" and sent["url"] == "http://pool.test/v1/notes"
    assert sent["body"]["key"] == "DAHMO/315/1/8433" and sent["auth"] == "t0k"
    assert got["pool"]["book"] == "davo-904-24-54"


def test_pull_marks_foreign_entries_and_drops_their_frame_box(case, monkeypatch):
    from nyshporka.share import upload

    entry = {"id": 7, "by": "igor_m", "uid": "f" * 32, "kind": "reading", "page": "0106",
             "created": "2026-09-23T00:00:00+00:00", "text": "Грисюкъ",
             "line": {"run": "чужий-прогін", "line_no": 3, "bbox": [1, 2, 3, 4]}}
    monkeypatch.setattr(upload, "_request",
                        lambda *a, **k: {"book": "x", "entries": [entry]})
    got = _run("note", "pull", CASE)
    assert got["added"] == ["f" * 32]
    (n,) = _run("note", "list", CASE, "--from", "pool")["notes"]
    assert n["origin"]["by"] == "igor_m" and n["origin"]["alignment"] == "text-only"
    assert n["line"].get("bbox") is None, "рамка чужої нарізки не лягає на наші кадри"
    # повтор не дублює й назад у пул не їде
    assert _run("note", "pull", CASE)["added"] == []
    assert _run("note", "push", CASE, "--dry-run", "--no-pages")["entries"] == 0


EYE_FILE = """\n# claude_eye — p0531 — звірено оком 2026-09-23
# коригує: Писар DAZHO-1-73-492-pages

[рядок 153] Андрей Терешкевъ(?) Грисюкъ 25
  примітка: не «Гришкунь».
"""


def test_import_eye_folder(case, tmp_path):
    eye = tmp_path / "DAZHO-1-73-492-pages-claude_eye"
    eye.mkdir()
    (eye / "p0531.txt").write_text(EYE_FILE, encoding="utf-8")
    got = _run("note", "import-eye", str(eye), "--case", CASE, "--model", "claude-opus-5-5")
    assert (got["readings"], got["private"], got["added"]) == (1, 1, 2)
    assert _run("note", "import-eye", str(eye), "--case", CASE)["added"] == 0
    assert all(not n["share"] for n in _run("note", "list", CASE)["notes"])


def test_the_root_cli_does_not_load_the_page_store_on_import():
    """🔴 `nysh version` на машині без простору мусить працювати.

    Сховище сторінок і бібліотека шукають простір уже на імпорті. Група команд
    нотатника, підключена з `pagestore`, тягнула їх при старті кореневого CLI —
    і чиста машина падала, не дійшовши до першої команди (CI релізу 0.25.0).
    Тут, де простір знаходиться, `test_smoke` цього не бачить, тож перевіряється
    сам ланцюжок імпортів в окремому процесі.
    """
    import subprocess
    import sys

    code = ("import sys, nyshporka.cli; "
            "print([m for m in ('nyshporka.pagestore', 'nyshporka.library') "
            "if m in sys.modules])")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    assert res.stdout.strip().splitlines()[-1] == "[]", res.stdout
