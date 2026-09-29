"""Паспорт завантаження — один на всі входи, і пишеться навіть при збої.

🔴 Доти `nysh get` писав «обіцяно / взято» без хешів і збоїв, `cases take` —
хеші без знаменника, а при збої нічого, демон — нічого взагалі. Повнота теки
залежала від команди, якою її качали, а частково взяті кадри лишались без
паспорта (звіт користувача 29.09.2026).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources.base import FetchResult, Manifest


def _meta(d: Path) -> dict[str, Any]:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _kadry(d: Path, n: int) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (d / f"{i:04d}_f{1000 + i}.jpg").write_bytes(b"jpg" + bytes([i]))


def test_pasport_nese_znamennyk_zboi_i_kheshi(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import record_fetch

    _kadry(tmp_path, 2)
    res = FetchResult(dest=tmp_path, frames=1, skipped=1, errors=["кадр 3: HTTP 502"])
    verdict = record_fetch(tmp_path, res, source="archium", ref="file:1", want=3)

    m = _meta(tmp_path)
    assert verdict.state == "partial"
    assert (m["frames_promised"], m["frames_got"]) == (3, 2)
    assert (m["frames_new"], m["frames_reused"]) == (1, 1)
    assert m["fetch_state"] == "partial" and m["complete"] is False
    assert m["fetch_errors"] == ["кадр 3: HTTP 502"] and m["fetch_errors_n"] == 1
    assert [f["file"] for f in m["files"]] == ["0001_f1001.jpg", "0002_f1002.jpg"]
    assert all(len(f["sha256"]) == 64 for f in m["files"])


def test_chyslo_zijshlos_ale_zboi_ne_povna(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import record_fetch

    _kadry(tmp_path, 2)
    res = FetchResult(dest=tmp_path, frames=2, errors=["кадр 1 перекачано з 2-ї спроби"])
    record_fetch(tmp_path, res, source="archium", ref="file:1", want=2)
    assert _meta(tmp_path)["complete"] is False


class _Archium:
    id = "archium"

    def __init__(self, dati: int, obitsiaie: int, zboi: list[str]) -> None:
        self.dati, self.obitsiaie, self.zboi = dati, obitsiaie, zboi

    def manifest(self, ref: str) -> Manifest:
        return Manifest(source="archium", ref=ref, title="t", frames=self.obitsiaie)

    def fetch(self, ref: str, dest: Path, *, frames: Any = None,
              on_progress: Any = None) -> FetchResult:
        _kadry(dest, self.dati)
        return FetchResult(dest=dest, frames=self.dati, errors=list(self.zboi))


def test_cases_take_pyshe_pasport_i_pry_zboi(tmp_path: Path) -> None:
    """🔴 Неповна тека лишається з паспортом «неповна, ось збої», а не без нього."""
    from nyshporka.cases.acquire import AcquireError, from_archium

    case = tmp_path / "spr-1"
    with pytest.raises(AcquireError, match="обіцяв 3"):
        from_archium(case, "35112", archive="CDIAK", fond="127", opys="1015",
                     spr="1", source=_Archium(2, 3, ["кадр 3: HTTP 502"]))
    m = _meta(case)
    assert m["fetch_state"] == "partial" and m["frames_promised"] == 3
    assert m["fetch_errors"] == ["кадр 3: HTTP 502"]


def test_cases_take_znaie_znamennyk(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import from_archium

    case = tmp_path / "spr-1"
    got = from_archium(case, "35112", archive="CDIAK", fond="127", opys="1015",
                       spr="1", source=_Archium(3, 3, []))
    m = _meta(case)
    assert m["complete"] is True and m["frames_promised"] == 3
    assert m["files"][0]["file"] == "pages/0001_f1001.jpg"
    assert len(got.files) == 3 and m["spr"] == "1"


@pytest.mark.asyncio
async def test_demon_tezh_pyshe_pasport(tmp_path: Path) -> None:
    from nyshporka.core.jobs import JobBus
    from nyshporka.daemon import workers as W

    _kadry(tmp_path, 2)

    class _Src:
        id = "archium"

        def fetch(self, ref: str, dest: Path, *, frames: Any = None,
                  on_progress: Any = None) -> FetchResult:
            return FetchResult(dest=dest, frames=2)

    bus = JobBus(tmp_path / "jobs.json")
    job, _ = await bus.enqueue("acquire", title="t", cfg={})
    await W._run_acquire(bus, _Src(), job, tmp_path, "file:1", None, 2)
    m = _meta(tmp_path)
    assert m["fetch_state"] == "complete" and m["fetched_from"] == "archium"


def test_commons_povtornyi_file_ne_robyt_nepovnym(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Одиниці — сторінки: цілий файл на диску не дає «сторінок + 1»."""
    from nyshporka.sources.base import completeness
    from nyshporka.sources.commons import CommonsSource

    (tmp_path / "Spr.pdf").write_bytes(b"12345")
    src = CommonsSource()
    monkeypatch.setattr(src, "_info", lambda name: {
        "url": "https://upload.wikimedia.org/x/Spr.pdf", "size": 5, "pagecount": 7})
    res = src.fetch("file:Spr.pdf", tmp_path)
    assert (res.frames, res.skipped) == (0, 7)
    assert completeness(res, 7).state == "complete"
