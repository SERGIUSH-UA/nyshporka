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


def test_sync_lokalnyi_shliakh_ne_nomer_vnesku(pool: list[dict[str, Any]],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """`…/2024/text.nyshtext` на диску — не внесок 2024 у пулі."""
    from nyshporka.share import pool as PL

    monkeypatch.setattr(PL, "sync", lambda *a, **k: {"of": 0, "scope": "усе", "via": "keys"})
    journal.record(journal.IMPORTED, shifra="x", source="D:/справи/2024/text.nyshtext")

    def _ne(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("локальний шлях — не привід питати пул")

    monkeypatch.setattr(upload, "_request", _ne)
    assert O.call("share.sync", {}).ok


def test_sync_bez_kliucha_i_staryi_pul_tykho(pool: list[dict[str, Any]],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import pool as PL

    monkeypatch.setattr(PL, "sync", lambda *a, **k: {"of": 0, "scope": "усе", "via": "keys"})
    journal.record(journal.IMPORTED, shifra="x",
                   source="https://cdn.nyshporka.online/b/x/11/text.nyshtext")

    def _staryi(*a: Any, **k: Any) -> dict[str, Any]:
        raise upload.UploadError("Not Found", status=404)

    monkeypatch.setattr(upload, "_request", _staryi)
    env = O.call("share.sync", {})
    assert env.ok and not any(w.code == "pulled_unchecked" for w in env.warnings)

    monkeypatch.setattr(upload, "token", lambda: "")
    env = O.call("share.sync", {})
    assert env.ok and not any(w.code.startswith("pulled") for w in env.warnings)


def test_zadovha_prychyna_zaminy(pool: list[dict[str, Any]]) -> None:
    env = O.call("share.publish", {"path": "x.nyshtext", "replaces": 7, "why": "я" * 501})
    assert not env.ok and "500" in env.error


def test_sync_chuzhyi_sait_ne_nomer_vnesku(pool: list[dict[str, Any]],
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import pool as PL

    monkeypatch.setattr(PL, "sync", lambda *a, **k: {"of": 0, "scope": "усе", "via": "keys"})
    journal.record(journal.IMPORTED, shifra="x",
                   source="https://example.org/archive/123/text.nyshtext")

    def _ne(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("чужий сайт — не привід питати пул")

    monkeypatch.setattr(upload, "_request", _ne)
    assert O.call("share.sync", {}).ok


# ── номер свого внеску (лист 20.10.2026) ─────────────────────────────────────

def test_zamina_svoho_bez_nomera_ide_parametrom() -> None:
    url = upload._adresa_reiestratsii("https://x/v1", None, "перечитано", True)
    assert url.startswith("https://x/v1/contributions?replace_own=true&why=")


def test_replace_own_bez_prychyny_i_z_nomerom_ne_ide(pool: list[dict[str, Any]]) -> None:
    assert not O.call("share.publish", {"path": "x.nyshtext", "replace_own": True}).ok
    env = O.call("share.publish", {"path": "x.nyshtext", "replace_own": True,
                                   "replaces": 7, "why": "так"})
    assert not env.ok and "не разом" in env.error


def test_moi_vnesky_z_pulu_z_nomeramy_i_dubliamy(pool: list[dict[str, Any]],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Людина віддала перечитане новими внесками, бо номера старого не мала де взяти."""
    storinky = {
        "": {"items": [{"id": 30, "state": "chynnyi", "book": "dadno-r-1234-15-20",
                        "shifra": "ДАДнО Р-1234-15-20", "pages": 40},
                       {"id": 21, "state": "zamineno", "replaced_by": 22, "book": "b",
                        "shifra": "ДАХмО 315-1-1", "pages": 3}],
             "next_before": 21},
        "?before=21": {"items": [{"id": 12, "state": "chynnyi", "book": "dadno-r-1234-15-20",
                                  "shifra": "ДАДнО Р-1234-15-20", "pages": 38}],
                       "next_before": None},
    }

    def fake(method: str, url: str, *, body: Any = None, auth: str = "") -> dict[str, Any]:
        assert method == "GET" and auth == "t0k"
        return storinky[url.split("/contributions/mine", 1)[1]]

    monkeypatch.setattr(upload, "_request", fake)
    env = O.call("share.list", {"what": "mine"})
    assert env.ok and env.data["source"] == "pool"
    rows = {r["id"]: r for r in env.data["rows"]}
    assert set(rows) == {30, 21, 12}, "усі сторінки пулу"
    assert rows[12]["duplicate_of"] == 30 and "duplicate_of" not in rows[30]
    assert "duplicate_of" not in rows[21], "замінений — не дубль"
    assert any(w.code == "duplicates" and "withdraw" in w.text for w in env.warnings)


def test_moi_vnesky_bez_pulu_kazhut_shcho_tse_zhurnal(pool: list[dict[str, Any]],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    journal.record(journal.PACKED, shifra="ДАХмО 315-1-8433", pages=4)

    def _ne(*a: Any, **k: Any) -> dict[str, Any]:
        raise upload.UploadError("обрив")

    monkeypatch.setattr(upload, "_request", _ne)
    env = O.call("share.list", {"what": "mine"})
    assert env.ok and env.data["source"] == "journal" and env.data["count"] == 1
    assert any(w.code == "pool_unreachable" for w in env.warnings)


def test_viddanyi_vnesok_zapysano_v_zhurnal_z_nomerom(pool: list[dict[str, Any]],
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    monkeypatch.setattr(upload, "_publish", lambda path, **kw: {
        "contribution": 31, "outcome": "viddano", "book": "dadno-r-1234-15-20",
        "shifra": "ДАДнО Р-1234-15-20", "replaces": 12})
    upload.publish(tmp_path / "x.nyshtext")
    (row,) = journal.read(journal.PUBLISHED)
    assert row["contribution"] == 31 and row["replaces"] == 12
    assert row["shifra"] == "ДАДнО Р-1234-15-20"
    assert not [r for r in journal.read() if r.get("event") in journal.EXCHANGE], \
        "заливка не рахується вдруге поруч із pack"
