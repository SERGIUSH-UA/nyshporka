"""🗂 Реєстри опису із Супряги: узяти фонд, дотягувати лише змінене, залити свій.

Сервер тут підроблений, але за тим самим протоколом, що `app.rehistr` порталу:
новий `rev` дістає лише рядок зі зміненим відбитком, видалений приходить
позначкою, перше взяття видалених не бачить.

Що стережемо:
1. Узятий фонд читається скрізь, де читається свій TSV (`cases opys`,
   `cases take`, `fond.rows`, знаменник серії).
2. Свій TSV сильніший за взятий.
3. Друге взяття питає лише змінене й застосовує видалення.
4. Заливка — лише змінене, без `on_disk`; збій заливки не валить злиття.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.fonds import registry as R
from nyshporka.fonds import remote
from nyshporka.share.catalog import PoolError


class FakeSupriaha:
    """Сервер реєстрів у пам'яті — той самий протокол, що `app.rehistr`."""

    def __init__(self) -> None:
        self.fonds: dict[tuple[str, str], dict[str, Any]] = {}
        self.seq = 0
        self.admin = True
        self.gets: list[tuple[str, dict[str, str]]] = []
        self.posts: list[dict[str, Any]] = []

    def put(self, repo: str, fond: str, rows: list[dict[str, Any]],
            delete: list[str] | None = None, label: str = "",
            meta: dict[str, Any] | None = None) -> None:
        f = self.fonds.setdefault((repo, fond), {"label": label, "meta": {}, "rows": {},
                                                  "pushed_at": None})
        for r in rows:
            h = remote.hash_data(r["data"])
            old = f["rows"].get(r["key"])
            if old and old["hash"] == h and not old["deleted"]:
                continue
            self.seq += 1
            f["rows"][r["key"]] = {"data": r["data"], "hash": h, "rev": self.seq,
                                   "deleted": False}
        for k in delete or []:
            old = f["rows"].get(k)
            if old and not old["deleted"]:
                self.seq += 1
                f["rows"][k] = {"data": {}, "hash": "", "rev": self.seq, "deleted": True}
        if label:
            f["label"] = label
        if meta is not None:
            f["meta"] = meta
        f["pushed_at"] = "2026-11-04T10:00:00+00:00"

    def _head(self, repo: str, fond: str) -> dict[str, Any]:
        f = self.fonds[(repo, fond)]
        live = [r for r in f["rows"].values() if not r["deleted"]]
        rev = max((r["rev"] for r in f["rows"].values()), default=0)
        return {"repo": repo, "fond": fond, "label": f["label"], "rows": len(live),
                "rev": rev, "meta": f["meta"], "pushed_at": f["pushed_at"]}

    def get(self, url: str) -> dict[str, Any]:
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.gets.append((u.path, q))
        if u.path.endswith("/fonds"):
            return {"fonds": [self._head(*k) for k in self.fonds]}
        key = (q.get("repo", ""), q.get("fond", ""))
        if u.path.endswith("/fonds/hashes"):
            if not self.admin:
                raise PoolError("не знайдено", status=404)
            f = self.fonds.get(key)
            return {"hashes": {} if f is None else {
                k: r["hash"] for k, r in f["rows"].items() if not r["deleted"]}}
        if u.path.endswith("/fonds/rows"):
            if key not in self.fonds:
                raise PoolError("не знайдено", status=404)
            since, limit = int(q.get("since", 0)), int(q.get("limit", 5000))
            head = self._head(*key)
            got = sorted(((k, r) for k, r in self.fonds[key]["rows"].items()
                          if since < r["rev"] <= head["rev"]
                          and (since > 0 or not r["deleted"])), key=lambda kr: kr[1]["rev"])
            rows = [({"key": k, "rev": r["rev"], "deleted": True} if r["deleted"]
                     else {"key": k, "rev": r["rev"], "data": r["data"]})
                    for k, r in got[:limit]]
            nxt = str(rows[-1]["rev"]) if len(rows) == limit else ""
            return {**head, "rows": rows, "next": nxt}
        raise AssertionError(f"невідомий запит {url}")

    def post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        assert urlsplit(url).path.endswith("/fonds/rows")
        if not self.admin:
            raise PoolError("не знайдено", status=404)
        self.posts.append(body)
        self.put(body["repo"], body["fond"], body.get("rows") or [], body.get("delete"),
                 body.get("label") or "", body.get("meta"))
        return self._head(body["repo"], body["fond"])


@pytest.fixture
def prostir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NYSHPORKA_WORKSPACE", str(tmp_path))
    W.use(tmp_path)
    R.invalidate()
    yield tmp_path
    R.invalidate()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSupriaha:
    s = FakeSupriaha()
    monkeypatch.setattr(remote, "_get", s.get)
    monkeypatch.setattr(remote, "_post", s.post)
    return s


def _d(title: str, **extra: Any) -> dict[str, Any]:
    return {"opys": "1", "spr_int": extra.pop("spr_int"), "spr_letter": "",
            "title": title, "year_from": "1820", "year_to": "1825", **extra}


def _seed_315(server: FakeSupriaha) -> None:
    server.put("DAHMO", "315", [
        {"key": "1/1", "data": _d("Сповідні розписи Балтського пов.", spr_int="1",
                                  fs_dgs="004810512", fs_frames="91")},
        {"key": "1/2", "data": _d("Метрична книга с. Людвинка", spr_int="2",
                                  commons_url="https://commons.example/2.pdf")},
        {"key": "1/3", "data": _d("Ревізька казка", spr_int="3")},
    ], label="ДАХмО ф.315", meta={"schema": "merged_v2"})


def _tsv(root: Path, slug: str, fond: str, rows: list[dict[str, str]]) -> Path:
    p = root / "data" / "raw" / slug / f"f{fond}_opys_merged.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = ["opys", "spr_int", "spr_letter", "title", "year_from", "year_to", "fs_dgs",
            "on_disk"]
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    R.invalidate()
    return p


# ── 1. узятий фонд читається скрізь ──────────────────────────────────────────

def test_uziatyi_fond_chytaietsia_iak_svii(prostir: Path, server: FakeSupriaha) -> None:
    _seed_315(server)
    assert not R.has_registry("dahmo_315")

    got = remote.pull("DAHMO", "315")
    assert (got["first"], got["got"], got["rows"]) == (True, 3, 3)

    assert R.has_registry("dahmo_315")
    found = {f["id"]: f for f in R.discover_fonds()}
    assert found["dahmo_315"]["source"] == "supriaha"
    rows = R.load_rows("dahmo_315")
    assert [r["shifra"] for r in rows] == ["315-1-1", "315-1-2", "315-1-3"]
    assert rows[0]["fs_dgs"] == "004810512"
    # стану чужого диска немає — і розбіжності з бібліотекою теж
    assert rows[0]["on_disk"] is None
    assert R.row_status(rows[0], {}, {})["disk_mismatch"] is False

    row, path = R.registry_row("DAHMO", "315", "1", "2")
    assert row is not None and row["commons_url"].endswith("2.pdf")
    assert path == remote.store_path()
    assert R.opys_keys("DAHMO", "315", "1") == ["DAHMO/315/1/1", "DAHMO/315/1/2",
                                                "DAHMO/315/1/3"]

    from nyshporka.cases import take
    assert take._row("DAHMO/315/1/1")[5]["fs_dgs"] == "004810512"

    env = O.call("fond.rows", {"fond": "dahmo_315", "state": "film"})
    assert env.ok, env.error
    assert [r["shifra"] for r in (env.data or {})["rows"]] == ["315-1-1"]


def test_bez_reiestru_porada_vede_v_suprіahu(prostir: Path) -> None:
    from nyshporka.cases import take

    with pytest.raises(take.TakeError, match="nysh registry pull --repo DAHMO --fond 315"):
        take._row("DAHMO/315/1/1")


# ── 2. свій сильніший ────────────────────────────────────────────────────────

def test_svii_tsv_sylnishyi_za_uziatyi(prostir: Path, server: FakeSupriaha) -> None:
    _seed_315(server)
    remote.pull("DAHMO", "315")
    _tsv(prostir, "dahmo_315", "315", [{"opys": "1", "spr_int": "1", "title": "СВІЙ"}])

    rows = R.load_rows("dahmo_315")
    assert [r["title"] for r in rows] == ["СВІЙ"]
    same = [f for f in R.discover_fonds() if f["id"] == "dahmo_315"]
    assert [f["source"] for f in same] == ["disk"]


# ── 3. лише змінене ──────────────────────────────────────────────────────────

def test_druhe_vziattia_pytaie_lyshe_zminene(prostir: Path, server: FakeSupriaha) -> None:
    _seed_315(server)
    first = remote.pull("DAHMO", "315")
    server.put("DAHMO", "315", [{"key": "1/2", "data": _d(
        "Метрична книга с. Людвинка", spr_int="2", fs_dgs="004810513")}], delete=["1/3"])
    server.gets.clear()

    got = remote.pull("DAHMO", "315")
    since = [q["since"] for path, q in server.gets if path.endswith("/fonds/rows")]
    assert since == [str(first["rev"])], "друге взяття мусить питати лише понад відоме"
    assert (got["first"], got["got"], got["deleted"], got["rows"]) == (False, 1, 1, 2)
    rows = {r["shifra"]: r for r in R.load_rows("dahmo_315")}
    assert set(rows) == {"315-1-1", "315-1-2"}
    assert rows["315-1-2"]["fs_dgs"] == "004810513"

    server.gets.clear()
    again = remote.pull("DAHMO", "315")
    assert (again["got"], again["deleted"], again["rows"]) == (0, 0, 2)


def test_hortannia_storinkamy(prostir: Path, server: FakeSupriaha,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote, "PAGE", 2)
    server.put("DAHMO", "315", [{"key": f"1/{i}", "data": _d(f"справа {i}", spr_int=str(i))}
                                for i in range(1, 6)], label="ДАХмО ф.315")
    assert remote.pull("DAHMO", "315")["rows"] == 5
    assert len(R.load_rows("dahmo_315")) == 5


def test_fondu_nemaie_v_supriazi(prostir: Path, server: FakeSupriaha) -> None:
    with pytest.raises(remote.NotInSupriaha, match="nysh registry remote"):
        remote.pull("DAHMO", "999")
    assert not R.has_registry("dahmo_999")


# ── 4. заливка ───────────────────────────────────────────────────────────────

def test_zalyvka_lyshe_zminene_i_bez_on_disk(prostir: Path, server: FakeSupriaha) -> None:
    rows = [{"opys": "1", "spr_int": str(i), "title": f"справа {i}", "on_disk": "1"}
            for i in range(1, 4)]
    _tsv(prostir, "dahmo_230", "230", rows)

    first = remote.push("dahmo_230")
    assert (first["rows"], first["sent"], first["deleted"]) == (3, 3, 0)
    sent = [r for b in server.posts for r in b.get("rows") or []]
    assert sent and all("on_disk" not in r["data"] for r in sent)
    assert all("shifra" not in r["data"] for r in sent)

    server.posts.clear()
    again = remote.push("dahmo_230")
    assert (again["sent"], again["same"]) == (0, 3)
    assert [len(b.get("rows") or []) for b in server.posts] == [0], \
        "незмінений реєстр — один порожній виклик, щоб оновити «станом на»"

    rows[1]["title"] = "справа 2 (виправлено)"
    _tsv(prostir, "dahmo_230", "230", rows[:2])
    third = remote.push("dahmo_230")
    assert (third["sent"], third["deleted"]) == (1, 1)
    assert server.fonds[("DAHMO", "230")]["rows"]["1/3"]["deleted"]


def test_pachky_vmishchaiutsia_v_tilo_zapytu(prostir: Path, server: FakeSupriaha,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Тіло запиту до API — до 1 МБ: пачка ділиться за розміром, а не лише кількістю."""
    import json

    monkeypatch.setattr(remote, "PUSH_BYTES", 2000)
    rows = [{"opys": "1", "spr_int": str(i), "title": "Метрична книга церкви " * 8}
            for i in range(1, 21)]
    _tsv(prostir, "dahmo_230", "230", rows)

    got = remote.push("dahmo_230")
    assert got["sent"] == 20
    sizes = [len(json.dumps(b["rows"], ensure_ascii=False).encode()) for b in server.posts
             if b.get("rows")]
    assert len(sizes) > 1 and max(sizes) <= 2000 + 400, sizes
    assert len(server.fonds[("DAHMO", "230")]["rows"]) == 20


def test_zalyvaie_lyshe_vlasnyk(prostir: Path, server: FakeSupriaha) -> None:
    _tsv(prostir, "dahmo_230", "230", [{"opys": "1", "spr_int": "1", "title": "А"}])
    server.admin = False
    with pytest.raises(remote.RegistryRemoteError, match="власник"):
        remote.push("dahmo_230")


def test_push_all_propuskaie_vykliucheni_i_nezmineni(prostir: Path,
                                                     server: FakeSupriaha) -> None:
    (prostir / W.MARKER).write_text(
        '[workspace]\nname = "t"\n\n[registry.push]\nenabled = true\n'
        'exclude = ["rgia_796"]\n', encoding="utf-8")
    W.use(prostir)
    _tsv(prostir, "dahmo_230", "230", [{"opys": "1", "spr_int": "1", "title": "А"}])
    _tsv(prostir, "rgia_796", "796", [{"opys": "1", "spr_int": "1", "title": "Б"}])

    first = {x["id"]: x for x in remote.push_all()}
    assert first["rgia_796"] == {"id": "rgia_796", "skipped": "excluded"}
    assert first["dahmo_230"]["sent"] == 1
    assert ("RGIA", "796") not in server.fonds

    second = {x["id"]: x for x in remote.push_all()}
    assert second["dahmo_230"] == {"id": "dahmo_230", "skipped": "same"}


def test_zbii_zalyvky_ne_valyt_zlyttia(prostir: Path, server: FakeSupriaha,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    (prostir / W.MARKER).write_text(
        '[workspace]\nname = "t"\n\n[registry.push]\nenabled = true\n', encoding="utf-8")
    W.use(prostir)
    _tsv(prostir, "dahmo_230", "230", [{"opys": "1", "spr_int": "1", "title": "А"}])

    class _Res:
        def __init__(self) -> None:
            self.blind: list[Any] = []
            self.sources: list[Any] = []

        def as_dict(self) -> dict[str, Any]:
            return {"rows": 1}

    from nyshporka.fonds.merge import run

    monkeypatch.setattr(run, "merge_fond", lambda *a, **k: _Res())

    def _vpav(url: str) -> dict[str, Any]:
        raise PoolError("сервер лежить", status=502)

    monkeypatch.setattr(remote, "_get", _vpav)
    env = O.call("registry.merge", {"repo": "DAHMO", "fond": "230"})
    assert env.ok, env.error
    assert any(w.code == "push_failed" for w in env.warnings), env.warnings

    # без `[registry.push]` злиття в мережу не ходить узагалі
    (prostir / W.MARKER).write_text('[workspace]\nname = "t"\n', encoding="utf-8")
    W.use(prostir)
    env = O.call("registry.merge", {"repo": "DAHMO", "fond": "230"})
    assert env.ok and "pushed" not in (env.data or {})


def test_vidbytok_iak_na_servieri() -> None:
    """Той самий вектор, що в тестах порталу (`app.rehistr.hash_danykh`)."""
    assert remote.hash_data({"title": "Сповідні розписи", "year_from": "1820",
                             "fs_frames": None, "commons_flag": True}) \
        == "afd7b6bf088278d8c301f2f73ace3aea"


def test_publichni_polia_bez_on_disk() -> None:
    assert "on_disk" not in R.PUBLIC_FIELDS
    d = R.public_data({"opys": "1", "spr_int": "2", "title": " А ", "on_disk": "x",
                       "commons_url": "", "mirror_size": None})
    assert d == {"opys": "1", "spr_int": "2", "title": "А", "mirror_size": None}
