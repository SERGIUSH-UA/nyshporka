"""Пул, мережа й обличчя Супряги: вади, знайдені рев'ю 24.09.2026.

Мережі тут немає: відповіді пулу підставляються двійником, а заборона
`NYSHPORKA_NO_NETWORK` лишається там, де тест перевіряє саме її.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, ClassVar

import pytest
from typer.testing import CliRunner

from nyshporka.share import catalog, pool


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    pool.invalidate()
    yield tmp_path / "ws"
    pool.invalidate()
    W.reset()


# ── C1: чужий текст не ламає друк ───────────────────────────────────────────

ZLYI = "[/i][link=https://evil.example]нотатка[/link] [sic]"


@pytest.mark.parametrize("cmd, op, data", [
    (["share", "pull", "315"], "share.pull",
     {"found": [{"shifra": ZLYI, "pages": "3", "models": ZLYI, "publisher": ZLYI}],
      "count": 1, "of": 1, "catalog": "x"}),
    (["share", "list"], "share.list",
     {"rows": [{"event": "import", "at": "2026", "shifra": ZLYI, "publisher": ZLYI,
                "pages": 1}], "count": 1}),
    (["share", "inspect", "p.nyshtext"], "share.inspect",
     {"shifra": ZLYI, "pages": 1, "frames": 1, "models": [ZLYI],
      "publisher": {"handle": ZLYI, "contact": ZLYI}, "note": ZLYI,
      "alignment": {"label": "text-only", "why": ZLYI}, "gates": {},
      "refs": [{"source": ZLYI, "ref": ZLYI}]}),
])
def test_rozmitka_v_chuzhykh_danykh_ne_valyt_komandu(
        monkeypatch: pytest.MonkeyPatch, cmd: list[str], op: str,
        data: dict[str, Any]) -> None:
    from nyshporka import ops as O
    from nyshporka.cli import app
    from nyshporka.core.envelope import ok
    from nyshporka.share import cli as SC

    monkeypatch.setattr(O, "call", lambda name, args: ok(data))
    monkeypatch.setattr(SC, "_kliuch_abo_vkhid", lambda as_json: None)
    res = CliRunner().invoke(app, cmd)
    assert res.exit_code == 0, res.output
    assert "[sic]" in res.output, "текст у дужках зник — його з'їла розмітка"


# ── C4: sync --json — конверт ────────────────────────────────────────────────

def test_sync_json_konvert(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.cli import app
    from nyshporka.share import cli as SC

    monkeypatch.setattr(SC, "_kliuch_abo_vkhid", lambda as_json: None)
    monkeypatch.setattr(pool, "sync", lambda base="", **kw: {
        "of": 1, "total": 1, "via": "keys", "scope": "все", "covers": ["*"], "path": "x"})
    res = CliRunner().invoke(app, ["share", "sync", "--json"])
    got = json.loads(res.output)
    assert got["ok"] is True and got["data"]["via"] == "keys"

    def _vpav(*a: Any, **k: Any) -> None:
        raise catalog.PoolError("пул лежить")

    monkeypatch.setattr(pool, "sync", _vpav)
    res = CliRunner().invoke(app, ["share", "sync", "--json"])
    got = json.loads(res.output)
    assert got["ok"] is False and "пул лежить" in got["error"]


# ── C5: setup із прапорцями не питає ────────────────────────────────────────

@pytest.mark.parametrize("flags", [["--no-lookup"], ["--geometry"], ["--json"]])
def test_setup_z_praportsiamy_bez_dialohu(space: Path, flags: list[str]) -> None:
    from nyshporka.cli import app

    res = CliRunner().invoke(app, ["share", "setup", *flags], input="")
    assert res.exit_code == 0, res.output
    assert "Aborted" not in res.output


def test_kontakt_prybyraietsia_minusom(space: Path) -> None:
    from nyshporka import ops as O
    from nyshporka.share import profile as P

    O.call("share.setup", {"contact": "t.me/x"})
    assert P.load().contact == "t.me/x"
    O.call("share.setup", {"contact": "-"})
    assert P.load().contact == ""


# ── C6–C8: прапорці пакування ───────────────────────────────────────────────

def test_link_z_rivnistiu_v_adresi() -> None:
    from nyshporka.ops_share import _links

    url = "https://www.familysearch.org/records/images/search-results?imageGroupNumbers=123"
    assert _links([url]) == [{"label": "", "url": url}]
    assert _links([f"звідки скани={url}"]) == [{"label": "звідки скани", "url": url}]


@pytest.mark.parametrize("bad", ["підпис=", "підпис=не-адреса", "просто текст"])
def test_link_bez_adresy_vidmova(bad: str) -> None:
    from nyshporka.ops_share import ArgError, _links

    with pytest.raises(ArgError):
        _links([bad])


@pytest.mark.parametrize("bad", [["bez-rivnosti"], ["=порожній"], ["a=1", "a=2"],
                                 ["partial=бо так"]])
def test_extra_vady_vidmova(bad: list[str]) -> None:
    from nyshporka.ops_share import ArgError, _extra

    with pytest.raises(ArgError):
        _extra(bad)


def test_kontakt_minus_ne_vkazuie() -> None:
    from nyshporka.ops_share import _contact

    assert _contact("-", "t.me/x") == ""
    assert _contact("", "t.me/x") == "t.me/x"
    assert _contact("mail@x", "t.me/x") == "mail@x"


# ── C9: dry-run показує відмову воріт ────────────────────────────────────────

def test_dry_run_kazhe_pro_vidmovu(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka.share import publish as PUB

    monkeypatch.setattr(PUB, "pack", lambda *a, **k: {
        "gates": {"passed": False, "refusals": ["у пакеті нуль рядків"], "warnings": []},
        "dry_run": True})
    env = O.call("share.pack", {"case": "x", "dry_run": True})
    assert any(w.code == "gate_refusal" for w in env.warnings)


# ── C11: «не знаємо» ≠ «немає» ──────────────────────────────────────────────

def test_nerozibrana_shyfra_ne_none(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import suggest as S

    monkeypatch.setattr(pool, "meta", lambda: {"taken_at": "x", "scope": "все"})

    def _ne_rozibraty(v: str) -> None:
        raise ValueError(v)

    monkeypatch.setattr("nyshporka.pagestore.resolve_case", _ne_rozibraty)
    assert S._u_puli("ні-на-що-не-схоже") is None


# ── C12, C13: автовіддача каже правду ───────────────────────────────────────

@pytest.mark.parametrize("got, want", [
    ({"duplicate": True, "ready": True, "status": "nove"}, "vzhe_ye"),
    ({"duplicate": True, "ready": True, "status": "vidkhyleno"}, "vidkhyleno"),
    ({"duplicate": True, "ready": False, "status": "nove"}, "ne_hotovo"),
    ({"duplicate": False, "ready": True, "status": "nove"}, "viddano"),
])
def test_duplicate_ne_oznachaie_u_supriazi(got: dict[str, Any], want: str) -> None:
    from nyshporka.share import upload

    assert upload.outcome(got) == want


def test_avtoviddacha_kazhe_koly_vpala(monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    from nyshporka import ops as O
    from nyshporka.cli import _supriaha_autoshare
    from nyshporka.core.envelope import fail

    monkeypatch.setattr(O, "call", lambda name, args: fail("OSError: диск повний"))
    _supriaha_autoshare("DAHMO/315/8433")
    assert "не віддано" in capsys.readouterr().out


# ── D1: частковий зріз не затирає решту ─────────────────────────────────────

def _rows(*keys: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [{"repo": r, "fond": f, "opys": "1", "spr": s, "n": 1, "pages": 10,
             "geom": False, "publishers": ["x"], "updated": "2026-09-01"}
            for r, f, s in keys]


def test_zriz_fondu_doposuietsia(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[dict[str, Any]] = _rows(("DAVIO", "904", "5"), ("DAHMO", "315", "7"))
    monkeypatch.setattr(pool, "_rows_from_keys", lambda b, r, f: (
        [x for x in got if (not r or x["repo"] == r) and (not f or x["fond"] == f)], "keys"))

    pool.sync()
    assert pool.by_fond("DAVIO", "904")
    got[1]["pages"] = 20
    pool.sync(repo="DAHMO", fond="315")
    assert pool.by_fond("DAVIO", "904"), "зріз одного фонду стер інші"
    assert pool.by_key("DAHMO/315/1/7").pages == 20


def test_zriz_lyshe_fondu_inshi_ne_pytaly(space: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "_rows_from_keys", lambda b, r, f: (
        _rows(("DAHMO", "315", "7")), "keys"))
    pool.sync(repo="DAHMO", fond="315")
    assert pool.by_fond("DAHMO", "315")
    assert pool.by_fond("DAVIO", "904") is None, "«не питали» стало «немає»"
    assert pool.known("DAVIO/904/1/5") is None


# ── D2, D5: адреса ключів і курсор ──────────────────────────────────────────

class _Pul:
    urls: ClassVar[list[str]] = []
    pages: ClassVar[list[dict[str, Any]]] = []
    status = 200

    def __init__(self, **_: Any) -> None:
        pass

    def get(self, url: str) -> Any:
        from nyshporka.sources.http import HttpError

        _Pul.urls.append(url)
        if _Pul.status != 200:
            raise HttpError(f"{url}: HTTP {_Pul.status}", status=_Pul.status)
        body = _Pul.pages.pop(0) if _Pul.pages else {"rows": []}
        return type("R", (), {"text": json.dumps(body)})()


@pytest.fixture
def pul(monkeypatch: pytest.MonkeyPatch) -> type[_Pul]:
    import nyshporka.sources.http as H

    _Pul.urls, _Pul.pages, _Pul.status = [], [], 200
    monkeypatch.setattr(H, "Fetcher", _Pul)
    monkeypatch.delenv(H.ENV_OFFLINE, raising=False)
    monkeypatch.setattr("nyshporka.share.upload.token", lambda: "")
    return _Pul


def test_keys_bez_podviinoho_v1(space: Path, pul: type[_Pul]) -> None:
    pool.sync("https://api.nyshporka.online/v1", repo="DAHMO", fond="315 & 1")
    assert pul.urls[0].startswith("https://api.nyshporka.online/v1/keys?")
    assert "/v1/v1/" not in pul.urls[0]
    assert "fond=315+%26+1" in pul.urls[0], "параметри без кодування ламали запит"


def test_povtorenyi_kursor_ne_tsykl(space: Path, pul: type[_Pul]) -> None:
    pul.pages = [{"rows": [], "next": "A"}, {"rows": [], "next": "A"}]
    with pytest.raises(catalog.PoolError, match="курсор"):
        pool.sync("https://api.nyshporka.online/v1")


def test_na_poshuk_lyshe_pry_404(space: Path, pul: type[_Pul]) -> None:
    pul.status = 503
    with pytest.raises(catalog.PoolError):
        pool.sync("https://api.nyshporka.online/v1")
    assert all("/keys" in u for u in pul.urls), "503 — не привід повторювати пошуком"


# ── D3: причина відмови й 429 без повторів ──────────────────────────────────

def test_prychyna_z_tila() -> None:
    from nyshporka.sources.http import HttpError

    exc = HttpError("x: HTTP 400", status=400, body=json.dumps(
        {"detail": {"text": "Ворота не пустили пакет.", "refusals": ["нуль рядків"]}}))
    got = catalog.reason(exc)
    assert "Ворота не пустили" in got and "нуль рядків" in got


def test_429_ne_povtoriuietsia() -> None:
    from nyshporka.sources.http import Fetcher, HttpError

    calls: list[int] = []

    class _C:
        def get(self, url: str) -> Any:
            calls.append(1)
            return type("R", (), {"status_code": 429, "text": '{"detail": "норма"}'})()

    f = Fetcher(client=_C(), attempts=6, retry_429=False, delay=0)
    with pytest.raises(HttpError) as ei:
        f.get("https://x/contributions")
    assert len(calls) == 1 and ei.value.status == 429 and "норма" in ei.value.body


# ── D4: TSV і JSON каталогу ─────────────────────────────────────────────────

def test_bom_i_null() -> None:
    rows = catalog.parse("﻿" + catalog.header() + "\n" + "\t".join(["ДАХмО 1-1-1"]))
    assert rows[0].shifra == "ДАХмО 1-1-1"
    got = catalog._rows({"rows": [{"shifra": "x", "geom_url": None}]})
    assert got[0].geom_url == ""


def test_fetch_dest_z_novym_riadkom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = catalog.Row(shifra="ДАХмО 1-1-1")
    monkeypatch.setattr(catalog, "search", lambda *a, **k: ([row], 1, 1))
    dest = tmp_path / "c.tsv"
    catalog.fetch(dest=dest)
    assert [r.shifra for r in catalog.parse(dest.read_text(encoding="utf-8"))] == ["ДАХмО 1-1-1"]


# ── D6: підписані посилання не виходять назовні ─────────────────────────────

def test_pidpysani_posylannia_ne_v_vidpovidi(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    from nyshporka.share import upload

    got = upload._public({"contribution": 1, "upload": {"text": "https://r2/sig?x"},
                          "expires": "t", "ready": True})
    assert "upload" not in got and "expires" not in got
    assert "r2" not in json.dumps(got)

    import httpx

    def _boom(url: str, **_: Any) -> Any:
        raise httpx.ConnectError(f"cannot connect to {url}")

    monkeypatch.setattr(httpx, "put", _boom)
    monkeypatch.setattr(upload, "PUT_PAUZY", (0.0, 0.0))
    with pytest.raises(upload.UploadError) as ei:
        upload._put("https://r2.example/b?X-Amz-" + "Signature=SEKRET", b"x")
    assert "SEKRET" not in str(ei.value)


# ── E1, E3: ключ справи й синоніми архіву ───────────────────────────────────

def test_kliuch_z_opysom_zvodytsia(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.pagestore.store import CaseRef

    S._canon_case_key.cache_clear()
    monkeypatch.setattr("nyshporka.pagestore.store.resolve_case", lambda v: CaseRef(
        key="CDIAK/127/1071", repo="CDIAK", fond="127", spr="1071", opys="1012",
        shifra="ЦДІАК 127-1012-1071", path=""))
    try:
        assert S._canon_case_key("CDIAK/127-1012/1071") == "CDIAK/127/1071"
    finally:
        S._canon_case_key.cache_clear()


def test_synonimy_v_zrizi(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    repos = {"DAVIO": SimpleNamespace(same_as="DAVO"), "DAVO": SimpleNamespace(same_as="")}
    monkeypatch.setattr("nyshporka.archives.active",
                        lambda: SimpleNamespace(repositories=repos))
    monkeypatch.setattr(pool, "_rows_from_keys", lambda b, r, f: (
        _rows(("DAVIO", "904", "5")), "keys"))
    pool.sync()
    assert pool.by_fond("DAVO", "904"), "простір на DAVO не бачив пулу на DAVIO"
    assert pool.by_key("DAVO/904/1/5") is not None


# ── завантаження й імена з чужого архіву ────────────────────────────────────

def test_download_404_iak_httperror(tmp_path: Path) -> None:
    import httpx

    from nyshporka.sources.http import Fetcher, HttpError

    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(404, text="нема")))
    with pytest.raises(HttpError) as ei:
        Fetcher(client=client).download("https://x/f", tmp_path / "f")
    assert ei.value.status == 404
    assert not (tmp_path / "f.part").exists()


def test_download_stelia(tmp_path: Path) -> None:
    import httpx

    from nyshporka.sources.http import Fetcher, TooLarge

    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"x" * 5000)))
    with pytest.raises(TooLarge):
        Fetcher(client=client).download("https://x/f", tmp_path / "f", max_bytes=100)
    assert not (tmp_path / "f").exists() and not (tmp_path / "f.part").exists()


@pytest.mark.parametrize("part, good", [
    ("0001.txt", True), ("spr3.", False), ("spr3 ", False), ("a?b", False),
    ("CON.txt", False), ("nul", False), ('a"b', False), ("a\x01b", False),
])
def test_tarsafe_imena(part: str, good: bool) -> None:
    from nyshporka.utils import tarsafe

    assert tarsafe.safe_member_part(part) is good


def test_sqlite_tmp_ne_lyshaietsia(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Обрив посеред запису зрізу не лишає `.sqlite.tmp` і не чіпає наявного."""
    monkeypatch.setattr(pool, "_rows_from_keys", lambda b, r, f: (
        _rows(("DAHMO", "315", "7")), "keys"))
    pool.sync()
    bulo = pool.snapshot_path().read_bytes()

    real = sqlite3.connect

    def _zlamanyi(*a: Any, **k: Any) -> Any:
        con = real(*a, **k)
        if not str(a[0]).endswith(".tmp"):
            return con

        class _C:
            def execute(self, sql: str, *args: Any) -> Any:
                if sql.startswith("INSERT OR REPLACE INTO meta"):
                    raise sqlite3.OperationalError("диск повний")
                return con.execute(sql, *args)

            def __getattr__(self, name: str) -> Any:
                return getattr(con, name)

        return _C()

    monkeypatch.setattr(pool.sqlite3, "connect", _zlamanyi)
    with pytest.raises(sqlite3.OperationalError):
        pool.sync()
    assert not pool.snapshot_path().with_suffix(".sqlite.tmp").exists()
    assert pool.snapshot_path().read_bytes() == bulo


# ── вікно підміни в R2 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("signed, status, raises, header", [
    ("host", 200, False, False),
    ("host;if-none-match", 200, False, True),
    ("host;if-none-match", 412, False, True),   # повтор після обриву: уже лежить
    ("host", 412, True, False),                 # без підпису 412 — справжня відмова
])
def test_umovnyi_put_lyshe_za_pidpysom(monkeypatch: pytest.MonkeyPatch, signed: str,
                                       status: int, raises: bool, header: bool) -> None:
    """`If-None-Match` шлеться рівно тоді, коли сервер вписав його в підпис."""
    import httpx

    from nyshporka.share import upload

    seen: dict[str, Any] = {}

    def _put(url: str, **kw: Any) -> Any:
        seen.update(kw.get("headers") or {})
        return httpx.Response(status)

    monkeypatch.setattr(httpx, "put", _put)
    url = f"https://r2.example/k?X-Amz-SignedHeaders={signed.replace(';', '%3B')}"
    if raises:
        with pytest.raises(upload.UploadError):
            upload._put(url, b"x")
    else:
        upload._put(url, b"x")
    assert ("If-None-Match" in seen) is header


def test_pull_zviriaie_geom_z_katalohom(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka.share import accept as A
    from nyshporka.share import catalog as C

    row = C.Row(shifra="ДАХмО 1-1-1", url="https://x/t", sha256="a" * 64,
                geom_url="https://x/g", geom_sha256="b" * 64)
    monkeypatch.setattr(C, "search", lambda *a, **k: ([row], 1, 1))
    zvirka: dict[str, str] = {}
    monkeypatch.setattr(A, "accept", lambda url, **k: (
        zvirka.update(text=k.get("sha256")) or
        {"alignment": {"label": "exact", "can_crop": True}}))
    monkeypatch.setattr(A, "accept_geometry", lambda url, **k: (
        zvirka.update(geom=k.get("sha256")) or {"pages": 1}))
    env = O.call("share.pull", {"query": "1-1-1", "take": True})
    assert env.ok, env.error
    assert zvirka == {"text": "a" * 64, "geom": "b" * 64}


def test_lokalnyi_paket_zviriaietsia_z_sha(tmp_path: Path) -> None:
    from nyshporka.share import accept as A

    p = tmp_path / "p.nyshtext"
    p.write_bytes(b"x")
    with pytest.raises(A.AcceptError, match="sha256"):
        A.fetch(str(p), tmp_path, sha256="0" * 64)
