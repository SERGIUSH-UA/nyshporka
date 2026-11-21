"""Відмова «справу розкладено на кілька тек кадрів» називає прогони кожної теки.

21.11.2026: друга тека була трен-набором (кадр з індексом FS) з двома голосами;
відмова не казала, які прогони до неї належать, і `--skip-run` одного голосу
лишав теку в пакеті.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def test_nazyvaie_progony_i_menshu_teku_za_kadramy(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.share import publish as P

    sprava = tmp_path / "pages"
    proba = tmp_path / "proba"
    sprava.mkdir()
    proba.mkdir()
    for i in range(5):
        (sprava / f"{i:04d}.jpg").write_bytes(b"x")
    (proba / "0486.jpg").write_bytes(b"x")

    runs = {"sp": sprava, "sp-diak": sprava, "pr": proba, "pr-diak": proba}
    run_dirs = [tmp_path / "htr" / n for n in runs]
    monkeypatch.setattr(P, "_meta_of", lambda d: {"case_dir": str(runs[d.name])})
    monkeypatch.setattr(S, "frames_dir_key", lambda p: str(p or ""))

    why = P._rozkladena(run_dirs)
    assert "pages: sp, sp-diak" in why
    assert "proba: pr, pr-diak" in why
    assert "--skip-run pr --skip-run pr-diak" in why
    assert "--skip-run sp" not in why


def test_odna_teka_bez_vidmovy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.share import publish as P

    t = tmp_path / "pages"
    t.mkdir()
    monkeypatch.setattr(P, "_meta_of", lambda d: {"case_dir": str(t)})
    monkeypatch.setattr(S, "frames_dir_key", lambda p: str(p or ""))
    assert P._rozkladena([tmp_path / "a", tmp_path / "b"]) == ""
