"""Перенос вбудованого погляду з файлів справ у проєкт: `nysh pages split`.

До розщеплення коментар сторінки й хто дивився лежали в самому файлі справи
(`data/pages/<REPO>/<справа>.json`). У Майстерні з проєктами-підтеками файл
справи спільний, тож погляд кореня старого типу переїжджає в теку проєкту, що
його успадковує (`<проєкт>/data/views`), а файл справи лишається з фактом.

Порядок той самий, що в переносі ключів (`cases.rekey`): без `--apply` — лише
план; з ним — архів і журнал до першого запису, перепис до й після, відкат при
збої; `--rollback` — повернути, як було.

🔴 Записи, яких не вдається однозначно віднести до проєкту (замовлення, запити
інших людей), переїжджають у той самий проєкт, що й решта, — і йдуть у звіт
плану переліком голів `agent`. Ділити їх руками — після переносу.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core import projects as P
from nyshporka.core import workspace as W
from nyshporka.pagestore.models import VIEW_FIELDS, PageView
from nyshporka.utils.atomic import atomic_write_text

#: Тека переносів під Майстернею — поруч із теками переносу ключів.
SPLIT_DIR = Path("data") / "cases" / "pages-split"

#: Слова в коментарі, що підказують чужу ціль: людина бачить їх числом у плані.
MARKS = ("замовлен", "портал", "запит", "reach", "клієнт")


class SplitError(RuntimeError):
    """Перенос неможливий або зупинився."""


def _files(pages: Path) -> list[Path]:
    return sorted(p for p in pages.glob("*/*.json")) if pages.is_dir() else []


def _read(p: Path) -> dict[str, Any]:
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _inline(page: Any) -> bool:
    return isinstance(page, dict) and any(page.get(f) for f in VIEW_FIELDS)


def _target(to: str | None) -> Path | None:
    if to is None:
        return None
    if to == P.ROOT_ID:
        raise SplitError("переносити погляд у корінь немає куди — він уже там; "
                         "вкажіть проєкт-підтеку (--to <ім'я>)")
    return P.project_dir(W.workspace().hub, to)


def plan(to: str | None = None) -> dict[str, Any]:
    """Що переїде: скільки сторінок із поглядом, чиї голови `agent`, які позначки."""
    ws = W.workspace()
    target = _target(to)
    files = with_view = pages = 0
    heads: Counter[str] = Counter()
    marks: Counter[str] = Counter()
    for f in _files(ws.pages):
        try:
            d = _read(f)
        except (OSError, ValueError):
            continue
        files += 1
        for page in (d.get("pages") or {}).values():
            pages += 1
            if not _inline(page):
                continue
            with_view += 1
            agent = str(page.get("agent") or "").strip()
            heads[agent.split()[0].lower() if agent else "—"] += 1
            low = str(page.get("comment") or "").lower()
            for m in MARKS:
                if m in low:
                    marks[m] += 1
    return {"to": to, "target": str(target) if target else "", "files": files,
            "pages": pages, "with_view": with_view,
            "agent_heads": heads.most_common(15), "marks": dict(marks)}


def report(pl: dict[str, Any]) -> str:
    lines = [f"Файлів справ: {pl['files']}, сторінок: {pl['pages']}, "
             f"з вбудованим поглядом (коментар чи хто дивився): {pl['with_view']}."]
    if pl["to"]:
        lines.append(f"Переїдуть у проєкт «{pl['to']}» ({pl['target']}).")
    else:
        lines.append("Проєкт не названо — це лише огляд (--to <ім'я> для плану переносу).")
    if pl["agent_heads"]:
        lines.append("Хто дивився (перше слово agent): " + ", ".join(
            f"{h} {n}" for h, n in pl["agent_heads"]))
    if pl["marks"]:
        lines.append("Коментарі з позначками чужої цілі (переїдуть разом — "
                     "розібрати після): " + ", ".join(
                         f"«{m}» {n}" for m, n in sorted(pl["marks"].items())))
    return "\n".join(lines) + "\n"


def _census(pages: Path, target: Path) -> dict[str, int]:
    out = {"page_notes": 0, "inline": 0, "views": 0}
    for f in _files(pages):
        d = _read(f)
        for page in (d.get("pages") or {}).values():
            out["page_notes"] += 1
            out["inline"] += int(_inline(page))
    vdir = W.Workspace(root=target).views
    for f in _files(vdir):
        out["views"] += len(_read(f).get("pages") or {})
    return out


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def _new_home(hub: Path) -> Path:
    base = hub / SPLIT_DIR
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for n in range(100):
        home = base / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            home.mkdir()
            return home
        except FileExistsError:
            continue
    raise SplitError(f"не вдалось завести теку переносу в {base}")


def _write_journal(home: Path, journal: dict[str, Any]) -> None:
    atomic_write_text(home / "journal.json", json.dumps(journal, ensure_ascii=False, indent=1))


def apply(to: str) -> dict[str, Any]:
    """Перенести вбудований погляд у проєкт `to`: архів → запис → перепис."""
    from nyshporka.cases.rekey import _refuse_busy

    ws = W.workspace()
    hub = ws.hub
    target = _target(to)
    assert target is not None
    _refuse_busy(ws.pages)
    vdir = W.Workspace(root=target).views
    todo = [f for f in _files(ws.pages)
            if any(_inline(p) for p in (_read(f).get("pages") or {}).values())]
    if not todo:
        return {"stamp": "", "moved": 0, "files": 0, "noop": True, "problems": []}
    before = _census(ws.pages, target)
    home = _new_home(hub)
    views = [vdir / f.parent.name / f.name for f in todo]
    keep = sorted({_rel(hub, p) for p in [*todo, *views] if p.is_file()})
    created = sorted(_rel(hub, v) for v in views if not v.is_file())
    with zipfile.ZipFile(home / "backup.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for rel in keep:
            z.write(hub / rel, rel)
    journal: dict[str, Any] = {"stamp": home.name, "to": to, "kept": keep,
                               "created": created, "done": False}
    _write_journal(home, journal)
    moved = 0
    try:
        for f, v in zip(todo, views, strict=True):
            moved += _move_one(f, v)
    except Exception as exc:
        journal["failed"] = f"{type(exc).__name__}: {exc}"
        _write_journal(home, journal)
        rollback(home.name, force=True)
        raise SplitError(f"перенос зупинився на півдорозі ({exc}); файли повернуто "
                         f"з архіву {_rel(hub, home / 'backup.zip')}") from exc
    after = _census(ws.pages, target)
    problems = []
    if after["page_notes"] != before["page_notes"]:
        problems.append(f"сторінок у файлах справ: було {before['page_notes']}, "
                        f"стало {after['page_notes']}")
    if after["inline"]:
        problems.append(f"вбудованого погляду лишилось: {after['inline']}")
    if moved != before["inline"]:
        problems.append(f"переїхало {moved} з {before['inline']} сторінок із поглядом")
    if after["views"] < before["views"]:
        problems.append(f"у поглядах проєкту: було {before['views']}, стало {after['views']}")
    written = sorted({*(_rel(hub, f) for f in todo), *(_rel(hub, v) for v in views)})
    journal.update(done=True, done_at=time.time(), census_before=before,
                   census_after=after, problems=problems, moved=moved,
                   written={rel: _sha(hub / rel) for rel in written})
    _write_journal(home, journal)
    return {"stamp": home.name, "moved": moved, "files": len(todo),
            "census_before": before, "census_after": after, "problems": problems,
            "backup": _rel(hub, home / "backup.zip")}


def _move_one(case_file: Path, view_file: Path) -> int:
    """Погляд однієї справи — у файл погляду; з файла справи — геть. Скільки сторінок."""
    from nyshporka.pagestore.store import _merge_view

    d = _read(case_file)
    take: dict[str, PageView] = {}
    for scan, page in (d.get("pages") or {}).items():
        if not _inline(page):
            continue
        take[scan] = PageView(comment=str(page.get("comment") or ""),
                              agent=str(page.get("agent") or ""),
                              noted=page.get("noted") or datetime.now(UTC).date())
    if not take:
        return 0
    vf: dict[str, Any] = _read(view_file) if view_file.is_file() else {"version": 1}
    pages: dict[str, Any] = dict(vf.get("pages") or {})
    for scan, v in take.items():
        old = pages.get(scan)
        pages[scan] = (v if old is None else
                       _merge_view(PageView.model_validate(old), v)).model_dump(mode="json")
    vf.update(key=d.get("key") or vf.get("key") or "", pages=dict(sorted(pages.items())))
    view_file.parent.mkdir(parents=True, exist_ok=True)
    # 🔴 Спершу погляд у проєкт, потім прибирання з файла справи: обрив між
    # ними лишає коментар у двох місцях, а не в жодному.
    atomic_write_text(view_file, json.dumps(vf, ensure_ascii=False, indent=1) + "\n")
    for scan in take:
        for f in VIEW_FIELDS:
            d["pages"][scan][f] = ""
    atomic_write_text(case_file, json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    return len(take)


def rollback(stamp: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Повернути файли до переносу `stamp` (останнього чинного, якщо не названо).

    🔴 Відкат затирає все, що записано після переносу, тож коли файли переносу
    відтоді змінювались, він відмовляє з переліком (`force` — свідомо).
    """
    hub = W.workspace().hub
    base = hub / SPLIT_DIR
    homes = sorted(p for p in base.iterdir()
                   if (p / "journal.json").is_file()) if base.is_dir() else []
    active = [p for p in homes if not _read(p / "journal.json").get("rolled_back")]
    pick = [p for p in active if p.name == stamp] if stamp else active[-1:]
    if not pick:
        raise SplitError(f"переносу для відкату немає ({base})")
    home = pick[0]
    journal = _read(home / "journal.json")
    if not force and journal.get("done"):
        changed = [rel for rel, sha in (journal.get("written") or {}).items()
                   if _sha(hub / rel) != sha]
        if changed:
            raise SplitError(f"після переносу {home.name} змінено файлів: {len(changed)} "
                             f"({', '.join(changed[:5])}). Відкат затре цю роботу. "
                             f"Свідомо — --rollback --force.")
    for rel in journal.get("created") or []:
        (hub / rel).unlink(missing_ok=True)
    with zipfile.ZipFile(home / "backup.zip") as z:
        for name in z.namelist():
            dst = hub / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
    journal["rolled_back"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_journal(home, journal)
    return {"stamp": home.name, "restored": len(journal.get("kept") or []),
            "removed": len(journal.get("created") or [])}
