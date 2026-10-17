"""🌐 Сайт родини в консолі: консоль сама віддає зібраний сайт, показує, що
зібрано, і ставить перезбирання в чергу; ярлик відкриває сайт.

ID вигадані (`I9…`)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nyshporka.core import workspace as W  # noqa: E402
from nyshporka.core.workspace import Workspace  # noqa: E402
from nyshporka.daemon.app import TOKEN_HEADER, create_app  # noqa: E402

TOKEN = "test-token-site"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    (tmp_path / "data" / "derived").mkdir(parents=True)
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    db = sys.modules.get("nyshporka.cases.db")
    if db is not None:
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite")
    space = Workspace(root=tmp_path, name="тест", origin="test")
    W.use(space)
    return space


@pytest.fixture
def client(ws: Workspace) -> TestClient:
    return TestClient(create_app(ws, token=TOKEN), base_url="http://127.0.0.1:8788")


def _built(root: Path, public: bool = False) -> Path:
    html = root / "site" / ("public" if public else "private") / "html"
    (html / "persons").mkdir(parents=True)
    (html / "assets").mkdir()
    (html / "index.html").write_text("<h1>Рід</h1>", encoding="utf-8")
    (html / "persons" / "I9001.html").write_text("<h1>Іван</h1>", encoding="utf-8")
    (html / "assets" / "stats.json").write_text(
        json.dumps({"persons": 3, "families": 1, "hypotheses": 2}), encoding="utf-8")
    return html


def test_not_built_site_says_how_to_build_it(client: TestClient) -> None:
    res = client.get("/site/")
    assert res.status_code == 404
    assert "ще не зібрано" in res.text and "/#site" in res.text


def test_console_serves_the_built_site(client: TestClient, ws: Workspace) -> None:
    _built(ws.root)
    assert client.get("/site", follow_redirects=False).headers["location"] == "/site/"
    assert "Рід" in client.get("/site/").text
    assert "Іван" in client.get("/site/persons/I9001.html").text
    assert client.get("/site/persons/I9999.html").status_code == 404
    # Відкрита версія — своя тека: приватна її не підміняє.
    assert client.get("/site-public/").status_code == 404


def test_site_path_does_not_leave_the_build_folder(client: TestClient, ws: Workspace) -> None:
    _built(ws.root)
    (ws.root / "data" / "canonical").mkdir(parents=True)
    (ws.root / "data" / "canonical" / "secret.md").write_text("жива особа", encoding="utf-8")
    for path in ("/site/../../../data/canonical/secret.md",
                 "/site/%2e%2e/%2e%2e/%2e%2e/data/canonical/secret.md"):
        res = client.get(path)
        assert "жива особа" not in res.text


def test_odd_paths_are_404_and_folders_get_a_slash(client: TestClient, ws: Workspace) -> None:
    _built(ws.root)
    assert client.get("/site/%00").status_code == 404
    res = client.get("/site/persons", follow_redirects=False)
    assert res.status_code in (302, 307) and res.headers["location"] == "/site/persons/"


def test_status_names_both_versions(client: TestClient, ws: Workspace) -> None:
    _built(ws.root)
    env = client.post("/api/op/site.status", json={}).json()
    assert env["ok"]
    d = env["data"]
    assert d["private"]["built"] and d["private"]["url"] == "/site/"
    assert d["private"]["counts"]["persons"] == 3
    assert not d["public"]["built"] and d["public"]["url"] == "/site-public/"


def test_rebuild_is_a_queued_job_behind_the_token(client: TestClient) -> None:
    assert client.post("/api/op/site.rebuild", json={}).status_code == 403
    res = client.post("/api/op/site.rebuild", json={}, headers={TOKEN_HEADER: TOKEN})
    assert res.status_code == 200 and res.json()["data"]["job_id"]


def test_serve_page_names_the_site() -> None:
    from nyshporka import cli
    from nyshporka.daemon import app as D

    assert cli._page_path("site") == "site/"
    assert cli._page_path("що завгодно") == ""
    # Порт, на якому нікого немає, — не «уже працює».
    assert D._alive(1) is False


def test_installers_put_a_family_site_shortcut() -> None:
    ps1 = (ROOT / "install" / "windows.ps1").read_text(encoding="utf-8-sig")
    iss = (ROOT / "install" / "nyshporka.iss").read_text(encoding="utf-8-sig")
    assert "'serve --page site'" in ps1 and "Trace 'file' $site" in ps1
    assert iss.count('Parameters: "serve --page site"') == 2
    for lang in ("ukrainian", "english", "polish", "romanian", "french", "german", "russian"):
        assert f"{lang}.SiteName=" in iss
