"""`nysh opys push/search`: той самий мережевий шлях, що в справ, без мережі в тесті."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from nyshporka.opysy import bundle as B
from nyshporka.opysy import remote as R
from nyshporka.share import upload as U


def _pack(tmp: Path, fond: str = "445", repo: str = "DAOO") -> Path:
    work = tmp / f"w-{repo}-{fond}"
    work.mkdir()
    manifest = {
        "schema": 1, "repo": repo, "fond": fond, "opys": "1", "language": "ru",
        "sources": [{"kind": "archive_site", "url": "https://archive.example/o.djvu",
                     "sha256": "e" * 64, "pages": 1, "label": "o.djvu"}],
        "engines": ["pysar_v31"], "license": "CC-BY-4.0",
        "quality": {"klass": "mid", "form": "hand_ruled"},
    }
    (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "pages.jsonl").write_text(json.dumps({"page": 1, "voices": {"p": "текст"}}),
                                      encoding="utf-8")
    (work / "rows.jsonl").write_text("", encoding="utf-8")
    rep = B.pack(work, tmp / f"{repo}-{fond}", tool="nyshporka test")
    if rep.file is None:
        # Закритий фонд пакувальник не пакує — збираємо байти в обхід, як нечесний клієнт.
        m, pages, rows, _ = B.prepare(B.read_workdir(work))
        assert m is not None
        f = tmp / f"{repo}-{fond}.nyshopys"
        f.write_bytes(B.encode(m, pages, rows))
        return f
    return rep.file


def test_push_registers_with_pack_manifest_puts_bytes_completes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pack = _pack(tmp_path)
    calls: list[tuple[str, str, Any]] = []
    put: list[tuple[str, bytes]] = []

    def fake_request(method: str, url: str, *, body: Any = None, auth: str = "",
                     timeout: float | None = None, attempts: int | None = None) -> dict:
        calls.append((method, url, body))
        if url.endswith("/opysy"):
            return {"vnesok": 7, "opys": 3, "shyfra": "DAOO 445-1",
                    "upload": "https://r2.example/put?X-Amz-SignedHeaders=host%3Bif-none-match"}
        return {"ready": True, "vnesok": 7, "summary": {"pages_read": 1, "pages_total": 1},
                "warnings": [{"code": "no_unconfirmed", "text": "…"}]}

    monkeypatch.setattr(U, "_tok_i_dim", lambda base: ("tok", "https://api.example/v1"))
    monkeypatch.setattr(U, "_request", fake_request)
    monkeypatch.setattr(U, "_put", lambda url, blob: put.append((url, blob)))

    got = R.push(pack)
    assert got["vnesok"] == 7 and got["shyfra"] == "DAOO 445-1"
    reg_body = calls[0][2]
    # Маніфест — із пакета: з `tool`, якого в робочій теці не було.
    assert reg_body["tool"] == "nyshporka test" and reg_body["schema"] == 1
    assert put == [(put[0][0], pack.read_bytes())]
    assert calls[1][1] == "https://api.example/v1/opysy/7/complete"


def test_push_refused_locally_never_touches_network(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pack = _pack(tmp_path, fond="442", repo="ЦДІАК")

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("мережа не мала бути зачеплена")

    monkeypatch.setattr(U, "_tok_i_dim", boom)
    monkeypatch.setattr(U, "_request", boom)
    with pytest.raises(U.UploadError, match="не проходить ворота"):
        R.push(pack)


def test_search_encodes_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(U, "_request", lambda method, url, **k: seen.append(url) or {"zbihy": []})
    monkeypatch.setattr(U, "token", lambda: "")
    R.search("Липовеньки Чижевич", repo="ДАОО", fond="445",
             base="https://api.nyshporka.online/v1")
    q = parse_qs(urlsplit(seen[0]).query)
    assert q["q"] == ["Липовеньки Чижевич"] and q["repo"] == ["ДАОО"] and q["fond"] == ["445"]
    assert seen[0].startswith("https://api.nyshporka.online/v1/opysy/search?")


def test_names_and_rules_go_with_key_and_exact_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Словник і правила — лише з ключем людини; тіло правила — рівно ті поля, що приймає пул."""
    calls: list[tuple[str, str, Any, str]] = []

    def fake_request(method: str, url: str, *, body: Any = None, auth: str = "",
                     timeout: float | None = None, attempts: int | None = None) -> dict:
        calls.append((method, url, body, auth))
        return {"ok": True}

    monkeypatch.setattr(U, "_tok_i_dim", lambda base: ("tok", "https://api.example/v1"))
    monkeypatch.setattr(U, "_request", fake_request)

    R.names("ДАОО", "445", q="Иван", page=2)
    R.rule_add("ДАОО", "445", ["Ибанов", "Ипанова"], "Иванов", evidence="ab" * 16,
               reason="кадр 2")
    R.rule_undo(5, reason="не те")
    R.rules("ДАОО", fond="445", state="zapyt")

    (m1, u1, _, a1), (m2, u2, b2, a2), (m3, u3, b3, _), (_, u4, _, _) = calls
    q1 = parse_qs(urlsplit(u1).query)
    assert m1 == "GET" and u1.startswith("https://api.example/v1/opysy/nazvy?") and a1 == "tok"
    assert q1 == {"repo": ["ДАОО"], "fond": ["445"], "storinka": ["2"], "q": ["Иван"]}
    assert (m2, u2, a2) == ("POST", "https://api.example/v1/opysy/pravyla", "tok")
    assert set(b2) == {"repo", "fond", "opys", "z", "na", "vyd", "dokaz", "prychyna"}
    assert b2["z"] == ["Ибанов", "Ипанова"] and b2["na"] == "Иванов" and b2["vyd"] == "prizvyshche"
    assert (m3, u3, b3) == ("POST", "https://api.example/v1/opysy/pravyla/5/vidkotyty",
                            {"prychyna": "не те"})
    assert parse_qs(urlsplit(u4).query)["stan"] == ["zapyt"]


def test_rule_list_prints_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стан правила видно в друку: квадратні дужки Rich ковтав як розмітку (живий прогін)."""
    from typer.testing import CliRunner

    from nyshporka import ops as O
    from nyshporka.core.envelope import ok
    from nyshporka.opysy import cli as C

    rule = {"id": 1, "stan": "vidkocheno", "repo": "ДАОО", "fond": "445", "z": ["Феодора"],
            "na": "Федор"}
    monkeypatch.setattr(O, "call", lambda name, args: ok({"pravyla": [rule]}))
    got = CliRunner().invoke(C.app, ["rule", "list", "ДАОО", "445"])
    assert got.exit_code == 0, got.output
    assert "(vidkocheno)" in got.output and "Феодора → Федор" in got.output
