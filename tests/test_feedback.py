"""📮 Відгук про Нишпорку: очищення, вкладення, перегляд без відправки, протокол."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.share import feedback as F

#: Вигадані домівка, користувач і простір — жодних справжніх шляхів машини.
HOME = Path("Q:/domivka/petryk")
ROOT = Path("Q:/domivka/petryk/doslidy")


@pytest.fixture(autouse=True)
def _fake_machine(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: HOME))
    monkeypatch.setattr("getpass.getuser", lambda: "petryk")
    W.use(W.Workspace(root=ROOT, name="тест", origin="test"))
    yield
    W.reset()


def _png(w: int = 40, h: int = 30) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 150, 100)).save(b, "PNG")
    return b.getvalue()


def test_scrub_hides_home_user_workspace_and_signatures() -> None:
    text = ("лог Q:/domivka/petryk/doslidy/reports/a.log; тека Q:\\domivka\\petryk\\Desktop\\x; "
            "у JSON Q:\\\\domivka\\\\petryk\\\\y; Petryk каже привіт; "
            "https://bkt.example.org/cases/a.tar?" + "X-" + "Amz-Signature=abc&X-" + "Amz-Date=1")
    got = F.scrub(text)
    assert "petryk" not in got.lower()
    assert "<простір>/reports/a.log" in got
    assert "~\\Desktop\\x" in got and "<user> каже" in got
    assert "X-Amz" not in got and "<підпис вирізано>" in got


def test_image_is_reencoded_small_and_without_metadata() -> None:
    im = Image.new("RGB", (3200, 2000), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "Камера"
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    a = F.image(b.getvalue(), "C:/tmp/знімок екрана.jpg")
    assert a.kind == "image" and a.name.endswith(".webp") and "/" not in a.name
    assert len(a.data) <= F.MAX_IMAGE
    with Image.open(io.BytesIO(a.data)) as out:
        assert out.format == "WEBP" and max(out.size) <= F.MAX_SIDE
        assert not out.getexif(), "EXIF не їде"


@pytest.mark.parametrize("raw", [b"<svg onload=alert(1)/>", b"GIF89a\x01\x00\x01\x00", b""])
def test_image_refuses_what_is_not_png_jpeg_webp(raw: bytes) -> None:
    with pytest.raises(F.FeedbackError):
        F.image(raw, "x.png")


def test_from_path_only_whitelisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(F, "_state_dir", lambda: (tmp_path / "stan").resolve())
    for name in ("canon.toml", "keys.db", "run.exe", "notes.md"):
        (tmp_path / name).write_bytes(b"secret")
        with pytest.raises(F.FeedbackError, match="лише картинку"):
            F.from_path(str(tmp_path / name))
    with pytest.raises(F.FeedbackError, match="немає"):
        F.from_path(str(tmp_path / "nema.log"))
    (tmp_path / "nysh.log").write_bytes("рядок\x00 1\r\nQ:/domivka/petryk/x\n".encode())
    a = F.from_path(str(tmp_path / "nysh.log"))
    assert a.kind == "text" and a.data.decode() == "рядок 1\n~/x\n"


def test_text_from_disk_only_from_workspace_or_state(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Агент не прикладе конфіг із ключами чи дані родин замовника під виглядом журналу."""
    ws, stan, chuzhe = tmp_path / "ws", tmp_path / "stan", tmp_path / "home"
    for d in (ws / "data" / "pages", ws / "reports", stan, chuzhe):
        d.mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    monkeypatch.setattr(F, "_state_dir", lambda: stan.resolve())
    (chuzhe / "credentials.json").write_text('{"k": 1}', encoding="utf-8")
    (chuzhe / "notes.txt").write_text("x", encoding="utf-8")
    (ws / "data" / "pages" / "client.json").write_text("{}", encoding="utf-8")
    (ws / "data" / "client.txt").write_text("x", encoding="utf-8")
    (ws / "reports" / "list.json").write_text("{}", encoding="utf-8")
    for bad in (chuzhe / "credentials.json", chuzhe / "notes.txt",
                ws / "data" / "pages" / "client.json", ws / "data" / "client.txt",
                ws / "reports" / "list.json"):
        with pytest.raises(F.FeedbackError, match="лише з простору"):
            F.from_path(str(bad))
    (ws / "reports" / "run.log").write_text("ок\n", encoding="utf-8")
    (stan / "update.log").write_text("ок\n", encoding="utf-8")
    (stan / "result.json").write_text("{}", encoding="utf-8")
    for good in (ws / "reports" / "run.log", stan / "update.log", stan / "result.json"):
        assert F.from_path(str(good)).kind == "text"


def test_symlink_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("ключ", encoding="utf-8")
    link = tmp_path / "zhurnal.log"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("тут не можна створити посилання")
    with pytest.raises(F.FeedbackError, match="посилання"):
        F.from_path(str(link))


def test_preview_shows_what_is_inside_a_log() -> None:
    a = F.log("".join(f"рядок {i}\n" for i in range(40)), "a.log")
    ex = a.as_json()["excerpt"]
    assert ex[0] == "рядок 0" and ex[-1] == "рядок 39" and "ще 28 рядків" in ex[6]


def test_key_goes_only_to_a_trusted_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Підміна `NYSHPORKA_TOLOKA` не виманює ключ Супряги (як у `share push`)."""
    def _boom(*a: Any, **k: Any) -> None:
        raise AssertionError("ключ поїхав на чужу адресу")

    monkeypatch.setenv("NYSHPORKA_TOLOKA", "http://evil.example/v1")
    monkeypatch.setattr("nyshporka.share.upload.token", lambda: "t0ken")
    monkeypatch.setattr("nyshporka.share.catalog._fetcher", _boom)
    monkeypatch.setattr(F, "_put", _boom)
    with pytest.raises(F.FeedbackError, match="не довірена"):
        F.send("x", "vada", [], with_diag=False)
    assert F.preview("x", "vada", [], with_diag=False)["trusted"] is False


def test_scrub_catches_other_forms_of_the_profile_and_secrets() -> None:
    cases = {
        "C:" + r"\Users\PETRYK~1\AppData\x": "~\\AppData\\x",
        "file:///C:" + "/Users/Petryk%20Ivanov/x": "file:///~/x",
        "/mnt/c/Users/Petryk Ivanov/z": "~/z",
        "пошта petryk.ivanov" + "@" + "example.org": "пошта <e-mail>",
        "Authorization: Bearer abcdefghijklmnop": "Authorization: Bearer <ключ>",
        "password=hunter2xx": "password=<вирізано>",
        "адреса 192.168.1.20": "адреса <ip>",
    }
    for raw, want in cases.items():
        assert F.scrub(raw) == want, (raw, F.scrub(raw))
    assert F.scrub("Q:/domivka/petryk/doslidy2/x") == "~/doslidy2/x", "межа слова у корені"
    assert F._safe_name("petryk_screenshot.png", ".webp") == "user_screenshot.webp" or \
        "petryk" not in F._safe_name("petryk_screenshot.png", ".webp")


def test_long_log_keeps_the_tail() -> None:
    raw = "".join(f"рядок {i}\n" for i in range(200_000))
    a = F.log(raw, "big.log")
    assert len(a.data) <= F.MAX_LOG and a.note
    assert a.data.decode().startswith("… (початок обрізано)")
    assert a.data.decode().rstrip().endswith("рядок 199999")


def test_prepare_limits() -> None:
    with pytest.raises(F.FeedbackError, match="до 5"):
        F.prepare(logs=[{"name": f"{i}.log", "text": "x"} for i in range(6)])
    with pytest.raises(F.FeedbackError, match="пошкоджено"):
        F.prepare(images=[{"name": "a.png", "data": "не base64 !!"}])
    got = F.prepare(images=[{"name": "a.png", "data": "data:image/png;base64,"
                             + base64.b64encode(_png()).decode()}])
    assert got[0].kind == "image"


def test_without_confirm_nothing_leaves_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Перший виклик — лише перегляд: ні `send`, ні мережі."""
    def _boom(*a: Any, **k: Any) -> None:
        raise AssertionError("мережа без confirm")

    monkeypatch.setattr(F, "send", _boom)
    monkeypatch.setattr("nyshporka.share.catalog._fetcher", _boom)
    monkeypatch.setattr(F, "logged_in", lambda: True)
    env = O.call("feedback.send", {"text": "Гортач падає в Q:/domivka/petryk/x", "kind": "vada"})
    assert env.ok and env.data["sent"] is False
    assert env.data["text"] == "Гортач падає в ~/x" and env.data["diag"]["version"]
    assert any(w.code == "confirm" for w in env.warnings)
    env = O.call("feedback.send", {"text": "x", "diag": False})
    assert env.data["diag"] == {}


def test_confirm_without_login_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nyshporka.share.upload.token", lambda: "")
    env = O.call("feedback.send", {"text": "x", "confirm": True})
    assert not env.ok and "nysh share login" in env.error


def test_send_speaks_the_portal_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, Any]] = []

    class Resp:
        def __init__(self, body: dict[str, Any]) -> None:
            self.text = json.dumps(body)

    class Fake:
        def post(self, url: str, json_body: Any = None) -> Resp:
            calls.append(("POST", url, json_body))
            return Resp({"id": 7} if url.endswith("/feedback") else {"status": "nova"})

    monkeypatch.setattr("nyshporka.share.upload.token", lambda: "t0ken")
    monkeypatch.setattr("nyshporka.share.catalog._fetcher", lambda url, **k: Fake())
    monkeypatch.setattr(F, "_put", lambda url, data, ctype, auth: calls.append(
        ("PUT", url, (ctype, len(data), auth))))
    att = [F.image(_png(), "a.png"), F.log("журнал\n", "b.log")]
    got = F.send("Не працює", "vada", att, with_diag=False)
    assert got["id"] == 7 and got["url"].endswith("/kabinet/moi-vidhuky")
    kinds = [(c[0], c[1].rsplit("/v1", 1)[-1]) for c in calls]
    assert kinds == [("POST", "/feedback"), ("PUT", "/feedback/7/files/1"),
                     ("PUT", "/feedback/7/files/2"), ("POST", "/feedback/7/complete")]
    body = calls[0][2]
    assert body["files"] == [{"kind": "image", "name": "a.webp", "size": len(att[0].data)},
                             {"kind": "text", "name": "b.log", "size": len(att[1].data)}]
    assert calls[1][2][0] == "image/webp" and calls[1][2][2] == "t0ken"


def test_daemon_refuses_an_oversized_feedback_body(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from nyshporka.daemon.app import TOKEN_HEADER, create_app

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="тест", origin="test")
    c = TestClient(create_app(ws, token="tk"), base_url="http://127.0.0.1:8788")
    big = b'{"text": "' + b"x" * (12 * 1024 * 1024 + 10) + b'"}'
    r = c.post("/api/op/feedback.send", content=big,
               headers={TOKEN_HEADER: "tk", "content-type": "application/json"})
    assert r.status_code == 413
