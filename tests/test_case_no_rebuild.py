"""📚 `nysh case --no-rebuild`: паспорт без перезбірки бібліотеки.

Кожен `nysh case` перезбирає бібліотеку цілком — на великому просторі це
десятки секунд. Для однієї справи це чесна ціна, а на пачці з десяти тек
(розрізана плівка) виходило десять перезбірок поспіль замість однієї в кінці.

🔴 Перевіряється саме те, що коштує часу: з прапорцем `build_library` не
кличеться зовсім, без нього — кличеться, тож типова поведінка не змінилась.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka import library as L
from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


@pytest.fixture
def case_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "простір"
    d = root / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (root / W.MARKER).write_text("[workspace]\nschema = 1\nname = \"тест\"\n",
                                 encoding="utf-8")
    monkeypatch.setenv(W.ENV_WORKSPACE, str(root))
    W.reset()
    yield d
    W.reset()


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def fake_build(*_a, **_k):
        calls.append(1)
        return []

    monkeypatch.setattr(L, "build_library", fake_build)
    monkeypatch.setattr(L, "write_library", lambda *_a, **_k: None)
    return calls


def _case(case_dir: Path, *extra: str):
    return runner.invoke(app, ["case", str(case_dir), "--shifra", "ДАХмО 315-1-8433",
                               "--title", "проба", *extra])


def test_no_rebuild_skips_library_build(case_dir: Path, builds: list[int]) -> None:
    res = _case(case_dir, "--no-rebuild")
    assert res.exit_code == 0, res.stdout
    assert builds == []
    assert (case_dir / "_source.json").is_file()


def test_default_still_rebuilds(case_dir: Path, builds: list[int]) -> None:
    res = _case(case_dir)
    assert res.exit_code == 0, res.stdout
    assert builds == [1]
