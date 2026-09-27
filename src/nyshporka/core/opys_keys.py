"""Справи, чий ключ несе опис, бо поруч лежить справа того самого номера в іншому описі.

Ключ справи — `REPO/фонд/спр`, без опису (`library._mk_key`). Для більшості
фондів цього досить, і на ньому стоїть усе вже записане: файли сховища
сторінок, прив'язки прогонів, мети. Але опис — фізично окремий підрозділ
фонду, і номери справ у різних описах повторюються: «ДАДнО 193-1-213»
(Катеринослав 1865–1867) і «ДАДнО 193-3-213» (Нікополь 1899) — дві різні
книги з одним ключем `DADNO/193/213`. Клієнт їх зливав, і людині лишалось
вигадати номер («213b»), щоб завести другу.

Поширити опис у ключі на всі фонди не можна: кожен рядок, уже записаний без
опису, підвис би. Список фондів `_OPYS_IN_KEY` рятує лише ті, де колізію вже
хтось помітив.

🔴 Тому опис входить у ключ ОКРЕМОЇ справи — тієї, що народилась у колізії, —
і це рішення записується в простір рівно один раз, на реєстрації. Справа, що
була першою, лишається зі своїм ключем без опису: усе, що на неї посилається,
і далі означає її саму. Міграції немає, бо змінюється лише нове.

Файл — `data/cases/opys_keys.json`. Поза простором (сервер Супряги, чисті
тести) реєстр порожній, і ключі там такі, як завжди.
"""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.utils.atomic import read_json, write_json

__all__ = ["FILE_NAME", "add", "has", "path", "reset", "rows"]

FILE_NAME = "opys_keys.json"

#: Як часто перевіряти, чи файл змінився. `_mk_key` кличуть тисячі разів за
#: одну збірку бібліотеки, а stat на Windows не безплатний.
_RECHECK = 0.5

_cache: dict[str, Any] = {"path": None, "mtime": None, "checked": 0.0, "set": frozenset()}


def _norm(part: object) -> str:
    """Одна форма для запису й для пошуку: інакше «0213» і «213» — різні справи."""
    s = str(part or "").strip().casefold()
    stripped = s.lstrip("0")
    return stripped or s


def _quad(repo: object, fond: object, opys: object, spr: object) -> tuple[str, str, str, str]:
    return (str(repo or "").strip().upper(), _norm(fond), _norm(opys), _norm(spr))


def path() -> Path | None:
    """Файл реєстру в поточному просторі; `None`, якщо простору немає."""
    try:
        from nyshporka.core.workspace import workspace

        return workspace().data / "cases" / FILE_NAME
    except Exception:       # простору немає — реєстру теж, і це штатний стан
        return None


def rows() -> list[dict[str, Any]]:
    """Записи реєстру як є. Побитий файл — виняток (`read_json`), не порожнеча."""
    p = path()
    if p is None:
        return []
    data = read_json(p, default={"cases": []})
    return list(data.get("cases") or [])


def _current() -> frozenset[tuple[str, str, str, str]]:
    p = path()
    now = time.monotonic()
    if p != _cache["path"]:
        _cache.update(path=p, mtime=None, checked=0.0, set=frozenset())
    if p is None:
        return frozenset()
    known: frozenset[tuple[str, str, str, str]] = _cache["set"]
    if now - _cache["checked"] < _RECHECK:
        return known
    _cache["checked"] = now
    try:
        mtime = os.stat(p).st_mtime_ns
    except OSError:
        _cache.update(mtime=None, set=frozenset())
        return frozenset()
    if mtime != _cache["mtime"]:
        _cache.update(mtime=mtime, set=frozenset(
            _quad(r.get("repo"), r.get("fond"), r.get("opys"), r.get("spr"))
            for r in rows()))
    fresh: frozenset[tuple[str, str, str, str]] = _cache["set"]
    return fresh


def has(repo: object, fond: object, opys: object, spr: object) -> bool:
    """Чи ключ цієї справи несе опис за рішенням, записаним у просторі."""
    if not (repo and fond and opys and spr):
        return False
    known = _current()
    return bool(known) and _quad(repo, fond, opys, spr) in known


def add(repo: str, fond: str, opys: str, spr: str, *, shifra: str = "",
        why: str = "") -> bool:
    """Записати справу в реєстр. `False` — вже була або простору немає."""
    p = path()
    if p is None or has(repo, fond, opys, spr):
        return False
    data = read_json(p, default={"cases": []})
    cases = list(data.get("cases") or [])
    if any(_quad(r.get("repo"), r.get("fond"), r.get("opys"), r.get("spr"))
           == _quad(repo, fond, opys, spr) for r in cases):
        return False
    cases.append({"repo": repo, "fond": fond, "opys": opys, "spr": spr,
                  "shifra": shifra, "why": why,
                  "at": datetime.now(UTC).isoformat(timespec="seconds")})
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, {**data, "cases": cases})
    _cache.update(checked=0.0, mtime=None)
    return True


def reset() -> None:
    """Скинути кеш — для тестів і після перемикання простору."""
    _cache.update(path=None, mtime=None, checked=0.0, set=frozenset())
