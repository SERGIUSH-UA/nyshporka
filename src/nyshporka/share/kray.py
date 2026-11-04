"""Перед заливкою: частина плівки, що торкається її краю, могла бути не всією справою.

Ворота повноти (`share.gates`, ≥ 75 %) рахують кадри справи проти її ВЛАСНИХ
кадрів. Після `nysh cases split` знаменник — шматок плівки, тож шматок справи,
що почалась на попередній котушці чи йде далі на наступну, проходить ворота як
повна справа. 04.11.2026 так «пройшли» три справи ANRM ф.211 оп.20: 19 (959 з
1460 кадрів — голова на сусідній плівці), 15 (859 з 1031) і 22 (280 з 614); їх
спіймав лише погляд на каталог FS.

Ознака без мережі: відтинок починається з першого кадру плівки або доходить до
останнього. Повна справа теж буває такою (плівка закінчилась разом зі справою),
тож це лише підказка — заливку вона не зупиняє, як і `opys_check`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["check"]

CODE = "kray_plivky"


def _read(p: Path) -> dict[str, Any]:
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _names(film_dir: Path) -> list[str]:
    """Кадри плівки: на диску або в маніфесті бакета."""
    from nyshporka.cloud.verify import REMOTE_FRAMES
    from nyshporka.share import align

    local = [p.name for p in align.frames_sorted(film_dir)] if film_dir.is_dir() else []
    if local:
        return local
    frames = _read(film_dir / REMOTE_FRAMES).get("frames") or []
    return sorted(str(f.get("name") if isinstance(f, dict) else f) for f in frames)


def _edges(film_dir: Path, first: str, last: str) -> tuple[bool, bool]:
    names = _names(film_dir)
    if not names:
        return False, False
    return first == names[0], last == names[-1]


def check(case_dir: Path | None) -> list[dict[str, str]]:
    """Попередження, коли справа з розкладки чи склейки торкається краю плівки."""
    if case_dir is None:
        return []
    from nyshporka.core.workspace import workspace

    side = _read(Path(case_dir) / "_source.json")
    root = workspace().hub
    head = tail = ""
    sf = side.get("split_from")
    if isinstance(sf, dict) and sf.get("dir"):
        film = root / str(sf["dir"])
        at_start, at_end = _edges(film, str(sf.get("first") or ""), str(sf.get("last") or ""))
        label = film.name
        head = label if at_start else ""
        tail = label if at_end else ""
    jf = side.get("join_from")
    if isinstance(jf, list) and jf:
        a, b = jf[0], jf[-1]
        if isinstance(a, dict) and a.get("dir"):
            film = root / str(a["dir"])
            if _edges(film, str(a.get("first") or ""), str(a.get("last") or ""))[0]:
                head = str(a.get("film") or film.name)
        if isinstance(b, dict) and b.get("dir"):
            film = root / str(b["dir"])
            if _edges(film, str(b.get("first") or ""), str(b.get("last") or ""))[1]:
                tail = str(b.get("film") or film.name)
    out: list[dict[str, str]] = []
    if head:
        out.append({"code": CODE, "text": (
            f"справа починається з першого кадру плівки {head}: її голова могла лишитись на "
            f"попередній котушці. Звірте з каталогом FS (група з тією ж шифрою чи без шифри "
            f"наприкінці сусідньої плівки, картка «ДЕЛО N» на її кадрі) — неповну справу "
            f"доберіть `cases join` або позначте --partial")})
    if tail:
        out.append({"code": CODE, "text": (
            f"справа доходить до останнього кадру плівки {tail}: вона могла продовжуватись на "
            f"наступній котушці. Звірте з каталогом FS (перша група наступної плівки, картка "
            f"«ДЕЛО N» на її початку) — неповну справу доберіть `cases join` або позначте "
            f"--partial")})
    return out
