"""Зібрати справу з частин кількох плівок: `nysh cases join`.

Справа буває розірвана між котушками: на одній плівці її голова й картка
«CONTINUED ON ANOTHER ROLL», на наступній — «CONTINUED FROM ANOTHER ROLL» і
хвіст. `nysh cases split` працює з однією текою, тож такі частини лишаються в
карті поза справами (`-`), а тут їх зводять в одну теку справи.

Кадри не копіюються: у теці справи лягають жорсткі посилання на файли плівок.
Ім'я — `<№>_<плівка>_<кадр>` (`0001_007810475_0672.jpg`): конвеєр далі скрізь
сортує кадри за іменами, тож порядок «голова → хвіст» тримає наскрізний номер
на початку, а не номер плівки (номери DGS не йдуть у порядку котушок). З імені
видно, звідки кадр. Теки старого зразка `<плівка>_<кадр>` лишаються чинними, а
повторний виклик на такій теці доробляє її в тому самому зразку.
Паспорт пише `nysh case` після збирання — шифру, назву й роки знає людина.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JOURNAL = "_join.json"


class JoinError(RuntimeError):
    """Зібрати не можна — з причиною для людини."""


@dataclass
class Piece:
    src: Path          # тека плівки
    first: str
    last: str
    label: str = ""    # початок імені файлу в справі; порожньо — з паспорта або імені теки


def parse_piece(spec: str) -> Piece:
    """`"<тека>=0821.jpg..0973.jpg"` → частина."""
    where, sep, span = str(spec).rpartition("=")
    first, dots, last = span.partition("..")
    if not (sep and dots and where.strip() and first.strip() and last.strip()):
        raise JoinError(f"частина «{spec}»: чекаю «<тека плівки>=<перший файл>..<останній файл>»")
    return Piece(Path(where.strip()), first.strip(), last.strip())


def _label(src: Path) -> str:
    """Плівка з паспорта теки (`film`/`dgs`/`fetched_ref`), інакше — перше число в імені."""
    for name in ("_source.json", "meta.json", "_fs_meta.json"):
        p = src / name
        if p.is_file():
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for key in ("film", "dgs", "fetched_ref"):
                val = str(meta.get(key) or "").strip()
                if val.isdigit():
                    return val
    m = re.match(r"(\d{5,})", src.name)
    return m.group(1) if m else src.name


def plan(dest: str | Path, pieces: list[Piece]) -> list[dict[str, Any]]:
    """Що ляже в теку справи: [{src, dst}], у порядку частин. Нічого не пише."""
    from nyshporka.share import align

    if not pieces:
        raise JoinError("жодної частини — нема що збирати")
    spans: list[tuple[str, Path, list[str]]] = []
    for piece in pieces:
        frames_dir = align._frames_dir(piece.src) if piece.src.is_dir() else None
        if frames_dir is None:
            raise JoinError(f"у теці {piece.src} немає кадрів")
        names = [p.name for p in align.frames_sorted(frames_dir)]
        for name in (piece.first, piece.last):
            if name not in names:
                raise JoinError(f"частина {piece.src.name}: файла «{name}» у теці немає")
        a, b = names.index(piece.first), names.index(piece.last)
        if a > b:
            raise JoinError(f"частина {piece.src.name}: «{piece.first}» стоїть після «{piece.last}»")
        spans.append((piece.label or _label(piece.src), frames_dir, names[a:b + 1]))
    total = sum(len(n) for _, _, n in spans)
    width = max(4, len(str(total)))
    d = Path(dest)
    legacy = False
    if d.is_dir():
        have = {p.name for p in align.frames_sorted(align._frames_dir(d) or d)}
        legacy_names = {f"{label}_{name}" for label, _, ns in spans for name in ns}
        # тека старого зразка (без номера): доробляємо в тому самому зразку
        legacy = bool(have) and have <= legacy_names
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    seq = 0
    for label, frames_dir, chosen in spans:
        for name in chosen:
            seq += 1
            dst = f"{label}_{name}" if legacy else f"{seq:0{width}d}_{label}_{name}"
            key = f"{label}_{name}"
            if key in seen:
                raise JoinError(f"кадр «{key}» потрапив би в справу двічі — частини перетинаються")
            seen.add(key)
            out.append({"src": frames_dir / name, "dst": dst})
    order = [row["dst"] for row in out]
    if legacy and order != sorted(order):
        raise JoinError("тека зібрана за старим зразком (<плівка>_<кадр>), а за іменами кадри "
                        "стали б не в порядку частин; зберіть справу заново в порожню теку")
    if d.is_dir():
        alien = have - set(order)
        if alien:
            raise JoinError(f"у теці {d} уже є інші кадри ({len(alien)}, напр. «{sorted(alien)[0]}») — "
                            f"збирати справу поверх чужих кадрів не можна")
    return out


def join(dest: str | Path, pieces: list[Piece], *, copy: bool = False) -> dict[str, Any]:
    """Покласти частини в теку справи жорсткими посиланнями. Повтор доробляє те саме."""
    rows = plan(dest, pieces)
    d = Path(dest)
    d.mkdir(parents=True, exist_ok=True)
    made = 0
    for row in rows:
        target = d / row["dst"]
        if target.exists():
            continue
        try:
            os.link(row["src"], target)
        except OSError as exc:
            if not copy:
                raise JoinError(f"жорстке посилання не створюється ({exc}): тека справи на іншому "
                                f"томі, ніж плівка; --copy скопіює кадри") from None
            shutil.copy2(row["src"], target)
        made += 1
    journal = {"pieces": [{"src": str(p.src), "first": p.first, "last": p.last,
                           "label": p.label or _label(p.src)} for p in pieces],
               "frames": len(rows),
               "order": [{"dst": r["dst"], "src": str(r["src"])} for r in rows]}
    (d / JOURNAL).write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"dest": str(d), "frames": len(rows), "made": made,
            "first": rows[0]["dst"], "last": rows[-1]["dst"]}
