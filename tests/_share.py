"""Спільні цеглини для тестів обміну: тека прогону й маніфест до неї.

Окремий модуль, а не імпорт із сусіднього тесту, — за зразком `_front.py`:
тека тестів плоска й не є пакетом, тож `from tests.x import y` тут не працює.
"""
from __future__ import annotations

import json
from pathlib import Path

from nyshporka.share import bundle

#: Шлях, якого не мусить бути в пакеті: він містить ім'я людини.
SECRET_CASE_DIR = "D:/skany-Tarasa-Petrenka/315-8433"


def make_run(root: Path, name: str, pages: int = 3, *,
             model: str = "pysar_cyr_v17.pt", geometry: bool = False,
             case_key: str = "DAHMO/315/8433", blank: int = 0) -> Path:
    """Тека прогону, як її лишає раннер."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, pages + 1):
        body = "" if i <= blank else (
            f"рядок перший сторінки {i}\nВишневецкій Григорій\n")
        (d / f"{i:04d}.txt").write_text(body, encoding="utf-8")
        if geometry:
            (d / f"{i:04d}.lines.json").write_text(
                json.dumps({"size": [2000, 3000], "boxes": [[10, 10, 500, 60]]}),
                encoding="utf-8")
    meta = {
        "version": 3, "case_key": case_key, "model": model, "script": "cyrillic",
        "engine": "parseq", "frames_total": pages,
        "case_dir": SECRET_CASE_DIR,
        "pages": {f"{i:04d}.jpg": {"lines": 2, "chars": 40, "conf": 0.8}
                  for i in range(1, pages + 1)},
    }
    (d / bundle.META_NAME).write_text(json.dumps(meta, ensure_ascii=False),
                                      encoding="utf-8")
    return d


def manifest_for(voices: list[bundle.Voice], *, pages: int = 3, frames: int = 3,
                 lines: int = 0, chars: int = 0,
                 blank: int = 0) -> bundle.Manifest:
    """Маніфест, який проходить ворота, — щоб тест міняв рівно одне поле."""
    return bundle.Manifest(
        case={"shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
              "opys": "1", "spr": "8433"},
        frames={"total": frames, "listed": frames, "with_sha256": 0,
                "with_apid": 0},
        decode={"pages": pages, "lines": lines or pages * 2,
                "chars": chars or pages * 40, "blank_pages": blank,
                "voices": [v.as_json() for v in voices]},
        license={"text": "CC0-1.0"}, tool="nyshporka test",
        created="2026-09-20T10:00:00+0300")
