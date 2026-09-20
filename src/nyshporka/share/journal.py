"""📒 Журнал обміну: що звідки прийшло і що куди пішло.

🔴 Не в `data/derived`. Критерій там сформульовано в `search/trace.py`: у
похідне кладуть те, що відтворюється повторним запитом і саме собою нічого не
доводить. Журнал обміну — протилежне. Він єдине, що доводить ПОХОДЖЕННЯ чужого
факту, і повторити його нема з чого: пакет міг зникнути з тієї адреси, звідки
приїхав, наступного дня.

З тієї ж причини поруч лежить і сам прийнятий пакет (`data/share/inbox`). Факт,
узятий із чужого декоду й унесений у канон, мусить спиратись на постійний
доказ-файл — інакше цитата провисає, щойно почистять кеш. Три-чотири мегабайти
на справу проти шістнадцяти посилань, які так уже провисли одного разу, —
невигідний обмін.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

JOURNAL = "journal.jsonl"
INBOX = "inbox"
OUTBOX = "outbox"

PACKED = "pack"
IMPORTED = "import"


def share_dir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().share


def journal_path() -> Path:
    return share_dir() / JOURNAL


def inbox() -> Path:
    return share_dir() / INBOX


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def record(event: str, **fields: Any) -> dict[str, Any]:
    """Дописати подію. Дозапис рядком, щоб дві сесії не перетирали одна одну."""
    row: dict[str, Any] = {"at": _now(), "event": event}
    row.update({k: v for k, v in fields.items() if v not in (None, "", [], {})})
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read(event: str = "") -> list[dict[str, Any]]:
    """Події журналу, найновіші спершу. Побитий рядок пропускається мовчки."""
    path = journal_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and (not event or row.get("event") == event):
            out.append(row)
    out.reverse()
    return out


def keep(src: Path, name: str) -> Path:
    """Покласти прийнятий пакет у постійне сховище. Повертає шлях доказу."""
    import shutil

    dest = inbox() / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(src).resolve() == dest.resolve():
        return dest
    shutil.copy2(src, dest)
    return dest


def stats() -> dict[str, Any]:
    """Скільки віддано й скільки прийнято — і від кого саме.

    🔴 Рахуються СПРАВИ, не події. Один пакет можна прийняти двічі (повторний
    імпорт після оновлення), і рахунок за подіями показував би вдвічі більше
    роботи, ніж її було.
    """
    rows = read()
    packed: dict[str, dict[str, Any]] = {}
    taken: dict[str, dict[str, Any]] = {}
    people: dict[str, int] = {}
    for r in rows:
        key = str(r.get("shifra") or r.get("case_key") or r.get("path") or "")
        if not key:
            continue
        bucket = packed if r.get("event") == PACKED else taken
        # Найновіша подія по справі виграє: журнал читається новими вперед.
        bucket.setdefault(key, r)
        if r.get("event") == IMPORTED:
            who = str(r.get("publisher") or "").strip() or "без імені"
            if key not in taken or taken[key] is r:
                people[who] = people.get(who, 0) + 1
    def _sum(b: dict[str, dict[str, Any]], f: str) -> int:
        return sum(int(x.get(f) or 0) for x in b.values())
    return {
        "packed": {"cases": len(packed), "pages": _sum(packed, "pages"),
                   "bytes": _sum(packed, "bytes")},
        "imported": {"cases": len(taken), "pages": _sum(taken, "pages"),
                     "bytes": _sum(taken, "bytes")},
        "from": sorted(({"publisher": k, "cases": v} for k, v in people.items()),
                       key=lambda x: -int(x["cases"])),
        "events": len(rows),
        "journal": str(journal_path()),
    }
