"""Бік помічника: розпакувати пакет у пісочницю, показати стан, віддати відповідь.

Пісочниця — окремий простір Нишпорки (`<дані>/zvid/<id>/`) з профілем «lab»:
там набори пакета виглядають як звичайні набори лабораторії, тож
`nysh -w <пісочниця> train view strip|zoom|ctx` працюють без змін, а завдання
перебудовуються локально — шляхи в них ведуть у цю машину, а не в машину
власника.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core import workspace as W
from nyshporka.train import sets as S
from nyshporka.train import tasks as T
from nyshporka.utils.atomic import read_json, write_json
from nyshporka.zvid import common as C

#: Маркери розбіжності й домислу, яких у мітці бути не може. Ворота власника
#: їх теж знімуть, але понизять рядок до `low` — тобто робота пропаде. Краще
#: відмовити тут, поки агент ще може виправити.
_MARKS = re.compile(r"[‹›|]|\[\?|\?\]|\(\?\)")
_ROW_ID = re.compile(r"^(\S+:\d+)$", re.M)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def root_of(pack_id: str, base: Path | None = None) -> Path:
    if not C.valid_id(pack_id):
        raise C.ZvidError(f"неприпустимий id пакета: {pack_id!r}")
    return (base or C.base_dir()) / pack_id


def _marker(root: Path, pack_id: str) -> None:
    (root / W.MARKER).write_text(
        f'[workspace]\nschema = 1\nname = "zvid-{pack_id}"\npreset = "lab"\n', encoding="utf-8")


def sandbox(root: Path) -> W.Workspace:
    return W.resolve(root)


def commands(pack_id: str, root: Path) -> dict[str, str]:
    """Готові команди для агента — з `-w`, щоб він не вгадував простір."""
    w = f'nysh -w "{root}"'
    return {"strip": f"{w} train view strip --set <набір> --page <стор> --lines 0-8 "
                     "--out <файл.png>",
            "zoom": f"{w} train view zoom --set <набір> --page <стор> --line <N> "
                    "--from 0 --to 0.5 --out <файл.png>",
            "ctx": f"{w} train view ctx --set <набір> --page <стор> --line <N> "
                   "--out <файл.png>",
            "status": f"nysh zvid status {pack_id}",
            "give": f"nysh zvid give {pack_id} --model <модель>"}


# ── взяти ────────────────────────────────────────────────────────────────────
@dataclass
class TakeReport:
    id: str
    root: Path
    procedure: str
    resumed: bool = False
    tasks: list[Path] = field(default_factory=list)
    rows: int = 0
    context: bool = False
    commands: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def take(path: Path, *, base: Path | None = None, fresh: bool = False) -> TakeReport:
    """Розпакувати `.zvid` у пісочницю й зробити завдання."""
    from PIL import Image

    from nyshporka import __version__

    with C.open_zip(path) as zf:
        manifest = C.read_json_member(zf, C.MANIFEST)
        C.check_manifest(manifest)
        need = str(manifest.get("min_client") or "0")
        if C.version_tuple(__version__) < C.version_tuple(need):
            raise C.ZvidError(f"пакет зроблено Нишпоркою {need}, тут {__version__}: правила "
                              "зведення могли змінитись — онови: nysh update")
        pack_id = str(manifest["id"])
        root = root_of(pack_id, base)
        if (root / C.STATE).is_file() and not fresh:
            # 🔴 Повторний `take` — продовження, а не перезапис: відповіді
            # агента вже лежать у `tasks/`, і розпакування поверх них з'їло б
            # години роботи.
            rep = TakeReport(id=pack_id, root=root, procedure=str(manifest.get("procedure")),
                             resumed=True, context=(root / C.CONTEXT).is_file(),
                             commands=commands(pack_id, root))
            rep.tasks = sorted((root / C.TASKS).glob("*.txt"))
            rep.rows = sum(len(_task_ids(f)) for f in rep.tasks)
            return rep
        root.mkdir(parents=True, exist_ok=True)
        _marker(root, pack_id)
        ws = sandbox(root)
        train = ws.hub_data / "train"
        for info in zf.infolist():
            p = C.member_path(info.filename)
            if info.is_dir() or p.name in (C.MANIFEST,):
                continue
            head = p.parts[0]
            if head in ("sets", "crops", C.PAGES) and (
                    len(p.parts) < 3 or not C.valid_alias(p.parts[1])):
                raise C.ZvidError(f"у пакеті чужий шлях: {info.filename}")
            if head == "sets":
                dst = train / "sets" / Path(*p.parts[1:])
            elif head == "crops" and p.suffix == ".jpg":
                dst = (train / "crops" / Path(*p.parts[1:])).with_suffix(".png")
                dst.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(io.BytesIO(zf.read(info))) as im:
                    im.save(dst)
                continue
            elif head == "crops":
                dst = train / "crops" / Path(*p.parts[1:])
            elif head == C.PAGES or p.name == C.CONTEXT:
                dst = root / Path(*p.parts)
            else:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(info))
    # Сторінка в меті нарізки — шлях у пісочниці, абсолютний: `page_image`
    # відкриває `src` як є, від поточної теки агента.
    for cm in (train / "crops").glob(f"*/{S.CUT_META_FILE}"):
        meta = read_json(cm, default={})
        for pm in (meta.get("pages") or {}).values():
            if pm.get("src"):
                pm["src"] = str(root / C.member_path(str(pm["src"])))
        write_json(cm, meta)
    rep = TakeReport(id=pack_id, root=root, procedure=str(manifest.get("procedure") or "arbiter"),
                     context=(root / C.CONTEXT).is_file(), commands=commands(pack_id, root))
    for s in manifest.get("sets") or []:
        got = T.export_tasks(str(s["name"]), pages_per_file=int(manifest.get("pages_per_file") or 1),
                             out=root / C.TASKS, ws=ws, procedure=rep.procedure,
                             next_cmd=f"nysh zvid give {pack_id} --model <модель>",
                             only=s.get("only"))
        rep.tasks += got.files
        rep.rows += got.rows
        rep.warnings += [f"{s['name']}: {w}" for w in got.warnings]
    write_json(root / C.STATE, {**manifest, "taken": _now(), "root": str(root),
                                "source": str(path)})
    return rep


# ── стан ─────────────────────────────────────────────────────────────────────
def _task_ids(f: Path) -> list[str]:
    txt = f.read_text(encoding="utf-8", errors="replace")
    rows = txt.split("\nРядки:\n", 1)
    return _ROW_ID.findall(rows[1]) if len(rows) == 2 else []


def _answer_of(task: Path) -> Path:
    return task.with_name(task.stem + ".answer.json")


def status(pack_id: str = "", *, base: Path | None = None) -> list[dict[str, Any]]:
    """Стан пісочниць: скільки рядків у завданнях і скільки вже зведено."""
    b = base or C.base_dir()
    if pack_id:
        roots = [root_of(pack_id, b)]
    elif b.is_dir():
        roots = sorted(d for d in b.glob("zv*") if (d / C.STATE).is_file())
    else:
        roots = []
    out = []
    for root in roots:
        state = read_json(root / C.STATE, default=None)
        if not isinstance(state, dict):
            if pack_id:
                raise C.ZvidError(f"пакет {pack_id} не взято: спершу nysh zvid take <файл>")
            continue
        tasks: list[dict[str, Any]] = []
        rows = done = 0
        for f in sorted((root / C.TASKS).glob("*.txt")):
            ids = _task_ids(f)
            a = _answer_of(f)
            got = T.parse_answer(a.read_text(encoding="utf-8")) if a.is_file() else {}
            n = sum(1 for k in ids if k in got)
            rows, done = rows + len(ids), done + n
            tasks.append({"task": f.name, "rows": len(ids), "done": n,
                          "answer": a.name if a.is_file() else ""})
        out.append({"id": state.get("id"), "root": str(root), "taken": state.get("taken"),
                    "procedure": state.get("procedure"), "tasks": tasks,
                    "rows": rows, "done": done, "given": state.get("given", "")})
    return out


# ── віддати ──────────────────────────────────────────────────────────────────
@dataclass
class GiveReport:
    id: str
    file: Path
    rows: int = 0
    answered: int = 0
    missing: int = 0
    conf: dict[str, int] = field(default_factory=lambda: dict.fromkeys(S.CONFS, 0))


def check_answers(root: Path) -> tuple[dict[str, dict[str, dict[str, str]]], list[str], int, int]:
    """Відповіді пісочниці → (за файлами, помилки, рядків у завданнях, бракує)."""
    by_file: dict[str, dict[str, dict[str, str]]] = {}
    errors: list[str] = []
    rows = missing = 0
    for f in sorted((root / C.TASKS).glob("*.txt")):
        ids = _task_ids(f)
        rows += len(ids)
        a = _answer_of(f)
        got = T.parse_answer(a.read_text(encoding="utf-8")) if a.is_file() else {}
        want = set(ids)
        ok: dict[str, dict[str, str]] = {}
        for k, v in got.items():
            m, c = v.get("m"), str(v.get("c") or "")
            if k not in want:
                errors.append(f"{a.name}: ключ {k} не з цього завдання")
            elif not isinstance(m, str):
                errors.append(f"{a.name}: {k} — «m» не рядок")
            elif c not in S.CONFS:
                errors.append(f"{a.name}: {k} — «c» має бути high|med|low, а не {c!r}")
            elif _MARKS.search(m):
                errors.append(f"{a.name}: {k} — маркер розбіжності в мітці: «{m}» "
                              "(обери один варіант і постав low)")
            else:
                ok[k] = {"m": m, "c": c}
        missing += len(want - set(ok))
        if ok:
            by_file[a.name] = ok
    return by_file, errors, rows, missing


def give(pack_id: str, *, model: str, agents: int = 0, note: str = "",
         out: Path | None = None, partial: bool = False,
         base: Path | None = None) -> GiveReport:
    """Перевірити відповіді в пісочниці й зібрати `<id>.answer.zvid`."""
    from nyshporka import __version__

    root = root_of(pack_id, base)
    state = read_json(root / C.STATE, default=None)
    if not isinstance(state, dict):
        raise C.ZvidError(f"пакет {pack_id} не взято: спершу nysh zvid take <файл>")
    if not model.strip():
        raise C.ZvidError("назви модель, що зводила (--model): без неї власник не знає, "
                          "якій розмітці скільки довіряти")
    by_file, errors, rows, missing = check_answers(root)
    if errors:
        head = "\n  ".join(errors[:12])
        more = f"\n  … ще {len(errors) - 12}" if len(errors) > 12 else ""
        raise C.ZvidError(f"відповіді не проходять перевірку ({len(errors)}):\n  {head}{more}")
    if not by_file:
        raise C.ZvidError("жодної відповіді — віддавати нічого")
    if missing and not partial:
        raise C.ZvidError(f"не зведено {missing} рядків з {rows}: доведи до кінця або "
                          "віддай частину свідомо (--partial)")
    dest = out or root
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{pack_id}{C.ANSWER_SUFFIX}"
    rep = GiveReport(id=pack_id, file=path, rows=rows, missing=missing)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, ok in sorted(by_file.items()):
            zf.writestr(f"answers/{name}", json.dumps(ok, ensure_ascii=False, indent=1))
            rep.answered += len(ok)
            for v in ok.values():
                rep.conf[v["c"]] += 1
        zf.writestr(C.META, json.dumps({
            "format": C.FORMAT, "version": C.VERSION, "id": pack_id,
            "frames": {s["name"]: s["frames"] for s in state.get("sets") or []},
            "model": model.strip(), "agents": agents, "note": note, "client": __version__,
            "at": _now(), "rows": rows, "answered": rep.answered, "missing": missing,
            "conf": rep.conf}, ensure_ascii=False, indent=1))
    state["given"] = _now()
    write_json(root / C.STATE, state)
    return rep
