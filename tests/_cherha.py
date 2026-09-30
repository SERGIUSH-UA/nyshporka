"""Спільний каркас тестів черги справ: порожній простір і справа на диску.

Не тест: імпортується як `from _cherha import …`.

🔴 Усе, що тягне `nyshporka.library`, імпортується тут усередині функцій —
бібліотека заморожує простір на імпорті (див. `test_case_key_builder`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def make_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Оголосити тимчасовий простір і перевести на нього заморожені шляхи."""
    from nyshporka.core import opys_keys as K
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    K.reset()

    from nyshporka import htr_store
    from nyshporka import library as lib
    from nyshporka.cases import db as DB
    from nyshporka.pagestore import store as S

    for mod, attr, value in (
        (lib, "ROOT", tmp_path), (lib, "RAW_DIR", tmp_path / "data" / "raw"),
        (lib, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (lib, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
        (htr_store, "ROOT", tmp_path), (htr_store, "HTR_ROOT", tmp_path / "reports" / "htr"),
        (htr_store, "_RUNS_CACHE", None),
    ):
        monkeypatch.setattr(mod, attr, value)
    htr_store._META_MEMO.clear()
    for fn in ("load_library", "_sidecar_case"):
        got = getattr(lib, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()
    return tmp_path


def drop_space() -> None:
    from nyshporka import htr_store
    from nyshporka.core import opys_keys as K
    from nyshporka.core import workspace as W

    htr_store._META_MEMO.clear()
    K.reset()
    W.reset()


def frames(space: Path, rel: str, n: int = 3) -> Path:
    """Тека з `n` кадрами під `data/raw`."""
    d = space / "data" / "raw" / rel
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"jpg" + bytes([i]))
    return d


def write_run(out: Path, case_dir: Path, *, key: str = "", pages: int | None = None,
              shared: dict[str, Any] | None = None) -> Path:
    """Прогін, яким його лишає раннер: txt на кадр і мета."""
    out.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in case_dir.glob("*.jpg"))
    done = names if pages is None else names[:pages]
    for name in done:
        (out / f"{Path(name).stem}.txt").write_text("Іванъ Петровъ сынъ\n" * 3,
                                                    encoding="utf-8")
    meta: dict[str, Any] = {
        "case_dir": str(case_dir), "case_key": key, "frames_total": len(names),
        "model": "pysar_cyr_v17.pt", "engine": "parseq", "script": "cyrillic",
        "done": len(done) == len(names), "pages": {n: {"lines": 3} for n in done}}
    if shared:
        meta["shared"] = shared
    (out / "_htr_meta.json").write_text(json.dumps(meta, ensure_ascii=False),
                                        encoding="utf-8")
    return out
