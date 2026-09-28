"""Приймач повноти завантаження — один на термінал і чергу демона.

Аудит 29.09.2026: демон ставив DONE усьому, крім «самі збої й жодного кадру»,
тож нуль кадрів без збою чи 10 кадрів із 300 висіли в черзі завершеною
роботою, хоча `nysh get` на тому самому результаті виходив із кодом 1. А
ARCHIUM і «Бабин Яр» на неоцифровану справу повертали з `fetch` нуль кадрів
без жодної помилки — і маніфест, і завантаження мусять казати причину.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.core.jobs import JobBus, JobState
from nyshporka.sources.base import FetchResult, Manifest, SourceError, completeness


@pytest.mark.parametrize(("frames", "skipped", "errors", "want", "state", "ok"), [
    (300, 0, 0, 300, "complete", True),
    (100, 200, 0, 300, "complete", True),       # докачка поверх готового
    (10, 0, 290, 300, "partial", False),
    (40, 0, 0, 300, "partial", False),          # дзеркало обрізало мовчки
    (0, 0, 0, 300, "empty", False),
    (0, 0, 0, None, "empty", False),
    (7, 0, 0, None, "unknown", True),
    (300, 0, 2, 300, "complete", False),        # збої джерела теж не пускають
])
def test_the_verdict(frames: int, skipped: int, errors: int, want: int | None,
                     state: str, ok: bool) -> None:
    res = FetchResult(dest=Path("x"), frames=frames, skipped=skipped,
                      errors=["збій"] * errors)
    v = completeness(res, want)
    assert (v.state, v.ok) == (state, ok)


class _Src:
    def __init__(self, res: FetchResult) -> None:
        self.res = res

    def fetch(self, ref: str, dest: Path, *, frames: Any = None,
              on_progress: Any = None) -> FetchResult:
        return self.res


async def _acquire(tmp_path: Path, res: FetchResult, total: int | None) -> Any:
    from nyshporka.daemon import workers as W

    bus = JobBus(tmp_path / "jobs.json")
    job, _ = await bus.enqueue("acquire", title="t", cfg={})
    await W._run_acquire(bus, _Src(res), job, tmp_path, "file:1", None, total)
    return bus.get(job.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("frames", "errors", "total", "state"), [
    (10, 290, 300, JobState.ERROR),
    (0, 0, 300, JobState.ERROR),
    (0, 0, None, JobState.ERROR),
    (40, 0, 300, JobState.ERROR),
    (300, 0, 300, JobState.DONE),
    (7, 0, None, JobState.DONE),
])
async def test_the_daemon_queue_uses_the_same_verdict(tmp_path: Path, frames: int,
                                                     errors: int, total: int | None,
                                                     state: JobState) -> None:
    res = FetchResult(dest=tmp_path, frames=frames, errors=["збій"] * errors)
    job = await _acquire(tmp_path, res, total)
    assert job.state == state, (job.state, job.error)
    if state == JobState.ERROR:
        assert job.error, "причина відмови мусить дійти до людини"
    if total is None and state == JobState.DONE:
        assert "повноту" in job.result["note"]


def test_the_terminal_refuses_an_empty_download(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from nyshporka import cli as C

    class Порожнє:
        id, label, caps = "проба", "Проба", frozenset({"manifest", "fetch"})

        def manifest(self, ref: str) -> Manifest:
            return Manifest(source=self.id, ref=ref, title="скан", frames=None)

        def fetch(self, ref, dest, *, frames=None, on_progress=None):  # type: ignore[no-untyped-def]
            return FetchResult(dest=Path(dest))

    class Реєстр:
        def get(self, sid: str) -> Порожнє:
            return Порожнє()

    monkeypatch.setattr(C, "_sources_registry", lambda: Реєстр())
    res = CliRunner().invoke(C.app, ["get", "проба", "адреса",
                                     "--out", str(tmp_path / "куди")])
    assert res.exit_code == 1, res.stdout
    assert "порожня" in res.stdout, res.stdout


# ── джерела: неоцифрована справа на завантаженні ────────────────────────────
class _Page:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _One:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, url: str) -> _Page:
        return _Page(self.text)


def test_archium_fetch_of_a_non_digitised_case_says_so(tmp_path: Path) -> None:
    from nyshporka.sources import archium as A

    absent = (Path(__file__).parent / "fixtures" / "sources"
              / "archium_viewer_absent.html").read_text(encoding="utf-8")
    src = A.ArchiumSource(fetcher=A.Fetcher(base="https://x", delay=0.0,
                                            client=_One(absent)))
    with pytest.raises(SourceError, match="200"):
        src.fetch("file:52170", tmp_path / "out")
    assert not (tmp_path / "out").exists(), "порожня тека лишилась би як «справа»"


def test_archium_fetch_of_a_range_outside_the_case_says_so(tmp_path: Path) -> None:
    from nyshporka.sources import archium as A

    viewer = (Path(__file__).parent / "fixtures" / "sources"
              / "archium_viewer.html").read_text(encoding="utf-8")
    src = A.ArchiumSource(fetcher=A.Fetcher(base="https://x", delay=0.0,
                                            client=_One(viewer)))
    with pytest.raises(SourceError, match="діапазоні"):
        src.fetch("file:5301", tmp_path / "out", frames=(9000, 9001))


def test_babynyar_fetch_of_a_non_digitised_case_says_so(tmp_path: Path) -> None:
    from nyshporka.sources.babynyar import BabynYarSource

    class _Cf:
        def get(self, url: str) -> _Page:
            return _Page("<html>порожньо</html>")

    src = BabynYarSource(client=_Cf())
    with pytest.raises(SourceError, match="НЕоцифрована"):
        src.fetch("case:26919", tmp_path / "case")
    assert not (tmp_path / "case").exists()
