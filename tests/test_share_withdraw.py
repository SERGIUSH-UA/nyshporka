"""Виправити віддане: заміна, відкликання, картка на дублі, взяте застаріло.

Людина помилилась — шифра розібралась у чужу справу, справу перечитали
новою моделлю, віддавати її взагалі не можна було. Межу «що автор може сам,
а що лише модерація» тримає пул; клієнт мусить довезти намір без втрат і
показати людині відповідь пулу, а не власну здогадку.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.share import journal, upload


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(upload, "token", lambda: "t0k")
    # Журнал обміну — свій на тест: він живе в просторі, а не в tmp_path.
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "journal.jsonl")
    return sent


def test_zamina_idde_parametramy_a_ne_manifestom() -> None:
    url = upload._adresa_reiestratsii("https://nyshporka.online/v1", 42, "перечитано Писарем v4")
    assert url.startswith("https://nyshporka.online/v1/contributions?replaces=42&why=")
    assert upload._adresa_reiestratsii("https://x/v1", None, "") == "https://x/v1/contributions"


def test_zamina_bez_prychyny_ne_ide(pool: list[dict[str, Any]],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    def _ne_klykaty(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("без причини до пулу не ходимо")

    monkeypatch.setattr(upload, "publish", _ne_klykaty)
    env = O.call("share.publish", {"path": "x.nyshtext", "replaces": 7, "why": " "})
    assert not env.ok and "--why" in env.error


def test_zamina_dovozyt_nomer_i_prychynu(pool: list[dict[str, Any]],
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    def _publish(path: Any, **kw: Any) -> dict[str, Any]:
        pool.append(kw)
        return {"contribution": 8, "ready": True, "status": "nove", "outcome": "viddano",
                "warnings": [{"code": "zamina", "text": "Внесок 7 замінено цим."}]}

    monkeypatch.setattr(upload, "publish", _publish)
    env = O.call("share.publish", {"path": "x.nyshtext", "replaces": 7,
                                   "why": "перечитано новою моделлю"})
    assert env.ok
    assert pool[0]["replaces"] == 7 and pool[0]["why"] == "перечитано новою моделлю"
    assert any(w.code == "zamina" for w in env.warnings), "людина мусить бачити, що старий сховано"


def test_kartka_na_dubli_vydno(pool: list[dict[str, Any]],
                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload, "publish", lambda path, **kw: {
        "duplicate": True, "ready": True, "status": "nove", "outcome": "vzhe_ye",
        "card": "proposed",
        "text": "Цей текст уже в Супрязі. Правку картки передано модерації."})
    env = O.call("share.publish", {"path": "x.nyshtext"})
    (w,) = [w for w in env.warnings if w.code.startswith("card")]
    assert w.code == "card_proposed" and "модерації" in w.text


def test_vidklykaty(pool: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(method: str, url: str, *, body: Any = None, auth: str = "") -> dict[str, Any]:
        pool.append({"method": method, "url": url, "body": body, "auth": auth})
        return {"contribution": 7, "withdrawn": False, "pending": True,
                "text": "Внесок уже взяли інші, тож відкликання погодить модерація."}

    monkeypatch.setattr(upload, "_request", fake)
    env = O.call("share.withdraw", {"contribution": 7, "why": "хибна шифра",
                                    "base": "https://nyshporka.online/v1"})
    assert env.ok
    assert pool == [{"method": "POST", "url": "https://nyshporka.online/v1/contributions/7/withdraw",
                     "body": {"why": "хибна шифра"}, "auth": "t0k"}]
    assert any(w.code == "withdraw_pending" for w in env.warnings)


def test_vidklykaty_bez_prychyny(pool: list[dict[str, Any]]) -> None:
    env = O.call("share.withdraw", {"contribution": 7, "why": ""})
    assert not env.ok


def test_sync_kazhe_pro_zamineni_i_vidklykani(pool: list[dict[str, Any]],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import pool as PL

    monkeypatch.setattr(PL, "sync", lambda *a, **k: {"of": 1, "scope": "усе", "via": "keys"})
    cdn = "https://cdn.nyshporka.online/b/dahmo/315/1/8433"
    journal.record(journal.IMPORTED, shifra="ДАХмО 315-1-8433", source=f"{cdn}/11/text.nyshtext")
    journal.record(journal.IMPORTED, shifra="ДАХмО 315-1-9000", source=f"{cdn}/12/text.nyshtext")
    journal.record(journal.IMPORTED, shifra="ДАХмО 315-1-9001", source=f"{cdn}/13/text.nyshtext")
    # Узяте з диска, без адреси пулу, — питати нема про що.
    journal.record(journal.IMPORTED, shifra="ДАХмО 315-1-1", source="C:/paket.nyshtext")

    def fake(method: str, url: str, *, body: Any = None, auth: str = "") -> dict[str, Any]:
        pool.append({"url": url, "body": body})
        return {"items": [{"id": 11, "state": "zamineno", "replaced_by": 20},
                          {"id": 12, "state": "vidklykano"},
                          {"id": 13, "state": "chynnyi"}]}

    monkeypatch.setattr(upload, "_request", fake)
    env = O.call("share.sync", {})
    assert env.ok
    assert pool[0]["body"] == {"ids": [11, 12, 13]}
    kody = {w.code: w.text for w in env.warnings}
    assert "внеском 20" in kody["pulled_replaced"] and "--take --force" in kody["pulled_replaced"]
    assert "ДАХмО 315-1-9000" in kody["pulled_withdrawn"]
    assert [z["contribution"] for z in env.data["pulled_stale"]] == [11, 12]


def test_sync_bez_vziatoho_ne_pytaie(pool: list[dict[str, Any]],
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import pool as PL

    monkeypatch.setattr(PL, "sync", lambda *a, **k: {"of": 0, "scope": "усе", "via": "keys"})

    def _ne(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("без узятого в журналі мережі не чіпаємо")

    monkeypatch.setattr(upload, "_request", _ne)
    assert O.call("share.sync", {}).ok
