"""🧳 Корінь старого типу → Майстерня + проєкт (`nysh project adopt <ім'я>`).

Простір, у якому хаб і рід — та сама тека (id «.»), стає чистою Майстернею
(`hub_only = true`), а все проєктне — канон, профіль роду, вердикти, журнал
пошуку, погляд на сторінки, сайт — переїжджає в `projects/<ім'я>/`.

Порядок `--apply`, кожен крок у журналі `data/cases/adopt/<мітка>/`:

1. архів усього, що їде, ПОЗА Майстернею (`--archive`) з sha256 кожного
   файла — і перевірка розпакуванням;
2. тека проєкту з шаблону (`project.create`);
3. погляд на сторінки — `pages split --to` (свій архів і відкат);
4. теки й файли — перенос (`os.replace`) і `git add -A`, щоб історія йшла
   за файлами;
5. `cited_by` маніфесту доказів: голі імена карток → `<ім'я>:<картка>.md`;
6. маркер Майстерні: `hub_only = true`, `legacy_project = "<ім'я>"`.

🔴 Без `--apply` — лише план: що їде, скільки, конфлікти. Відкат
(`--rollback`) іде за журналом у зворотному порядку.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core import projects as P
from nyshporka.core import workspace as W
from nyshporka.utils.atomic import atomic_write_text

ADOPT_DIR = Path("data") / "cases" / "adopt"

#: Проєктне за схемою простору (`Workspace.proot`). Погляд на сторінки
#: (`data/views`) сюди не входить: його переносить `pages split`.
BASE_PATHS = (
    "data/canonical", "data/candidates", "data/clan_hunt", "data/site",
    "config/research_profile.yaml", "config/records_profiles.yaml",
    "config/folk_names.yaml",
    "data/spotter/case_verdicts.json", "data/spotter/decode_hits.json",
    "data/derived/verdicts.json", "data/derived/search_log.json",
)
# ⚠ Збірка сайту (`site/`) не їде: вона перезбирається з канону (`site build`),
# а в архів переїзду лягли б гігабайти HTML.


class AdoptError(RuntimeError):
    """Переїзд не почато або зупинено — з поясненням."""


@dataclass
class Move:
    path: str
    files: int
    size: int
    tracked: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "files": self.files, "size": self.size,
                "tracked": self.tracked}


@dataclass
class Plan:
    pid: str
    hub: str
    moves: list[Move] = field(default_factory=list)
    views: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "hub": self.hub,
                "moves": [m.as_dict() for m in self.moves], "views": self.views,
                "files": sum(m.files for m in self.moves),
                "size": sum(m.size for m in self.moves), "problems": self.problems}


# ── допоміжне ────────────────────────────────────────────────────────────────
def _git(hub: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=hub, capture_output=True, check=check)
    return out.stdout.decode("utf-8", errors="replace")


def _is_repo(hub: Path) -> bool:
    try:
        top = _git(hub, "rev-parse", "--show-toplevel").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return bool(top) and Path(top).resolve() == hub.resolve()


def _walk(p: Path) -> list[Path]:
    if p.is_file():
        return [p]
    return sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else []


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extra_paths(hub: Path) -> list[str]:
    """Додаткові шляхи Майстерні: `[adopt] extra = [...]` у маркері."""
    got = W._read_toml(hub / W.MARKER).get("adopt") or {}
    return [str(x).strip("/") for x in (got.get("extra") or []) if str(x).strip()]


def paths_to_move(hub: Path) -> list[str]:
    seen = dict.fromkeys([*BASE_PATHS, *extra_paths(hub)])
    return [p for p in seen if (hub / p).exists()]


def _refs_left_behind(hub: Path, moving: list[str]) -> list[str]:
    """Посилання карток на `data/source/…`, які лишились би в Майстерні.

    Канон резолвить такі шляхи від кореня проєкту (крім доказів у
    `data/source/citations/`), тож файл, що не поїхав разом із карткою, після
    переїзду стає битим посиланням.
    """
    import re

    canon = W.Workspace(root=hub).canonical
    if not canon.is_dir():
        return []
    pat = re.compile(r"data/source/[^\s)\"'`\]>|]+")
    out: set[str] = set()
    for card in canon.rglob("*.md"):
        for raw in pat.findall(card.read_text(encoding="utf-8", errors="replace")):
            ref = raw.rstrip(".,;:")
            if ref.startswith("data/source/citations/"):
                continue
            stays = not any(ref == m or ref.startswith(m.rstrip("/") + "/") for m in moving)
            if stays and (hub / ref).exists():
                out.add(ref)
    return sorted(out)


# ── план ─────────────────────────────────────────────────────────────────────
def plan(hub: Path, pid: str) -> Plan:
    from nyshporka.pagestore import split_views as SV

    P.check_name(pid)
    pl = Plan(pid=pid, hub=str(hub))
    cfg = W._read_marker(hub / W.MARKER)
    if W.read_project_table(hub) is not None:
        pl.problems.append(f"{hub} — сам проєкт, а не корінь Майстерні")
    if cfg.get("hub_only"):
        pl.problems.append("корінь уже чиста Майстерня (hub_only) — переїжджати нічому")
    if (P.projects_dir(hub) / pid).exists():
        pl.problems.append(f"тека projects/{pid} уже є")
    repo = _is_repo(hub)
    moving = paths_to_move(hub)
    for rel in moving:
        files = _walk(hub / rel)
        tracked = (len([x for x in _git(hub, "ls-files", "-z", "--", rel).split("\0") if x])
                   if repo else 0)
        pl.moves.append(Move(path=rel, files=len(files),
                             size=sum(f.stat().st_size for f in files), tracked=tracked))
    if repo and moving:
        dirty = [x for x in _git(hub, "status", "--porcelain", "-z", "--", *moving)
                 .split("\0") if x]
        if dirty:
            pl.problems.append(f"незакомічене в шляхах переїзду ({len(dirty)}): "
                               + ", ".join(d[3:] for d in dirty[:5])
                               + " — спершу закомітити")
    for ref in _refs_left_behind(hub, moving)[:20]:
        pl.problems.append(f"картка посилається на {ref}, а він не їде — додайте теку "
                           f"в [adopt] extra")
    with W.using(W._build(hub, "explicit")):
        try:
            pl.views = SV.plan()
        except Exception as exc:  # план поглядів — підказка, не умова
            pl.views = {"error": str(exc)}
    return pl


def report(pl: Plan) -> str:
    d = pl.as_dict()
    lines = [f"Переїзд кореня в проєкт «{pl.pid}»: {len(pl.moves)} шляхів, "
             f"{d['files']} файлів, {d['size'] / 1048576:.1f} МБ"]
    for m in pl.moves:
        lines.append(f"  {m.path:<44} {m.files:>6} ф.  {m.size / 1048576:8.1f} МБ"
                     f"  (git: {m.tracked})")
    v = pl.views
    if v and "error" not in v:
        lines.append(f"  погляд на сторінки: {v.get('with_view', '?')} сторінок → "
                     f"projects/{pl.pid}/data/views")
        if v.get("marks"):
            lines.append("    з них про чуже (позначки, перелік ляже в журнал): "
                         + ", ".join(f"«{k}» {n}" for k, n in v["marks"].items()))
    for p in pl.problems:
        lines.append(f"🔴 {p}")
    if not pl.problems:
        lines.append(f"Далі: nysh project adopt {pl.pid} --apply --archive <тека поза Майстернею>")
    return "\n".join(lines)


# ── переїзд ──────────────────────────────────────────────────────────────────
def _new_home(hub: Path) -> Path:
    base = hub / ADOPT_DIR
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    home = base / stamp
    home.mkdir()
    return home


def _journal(home: Path, data: dict[str, Any]) -> None:
    atomic_write_text(home / "journal.json", json.dumps(data, ensure_ascii=False, indent=1))


def _archive(hub: Path, moving: list[str], dest: Path) -> dict[str, Any]:
    """Zip того, що їде, з переліком sha256 — і перевірка розпакуванням."""
    dest.mkdir(parents=True, exist_ok=True)
    name = f"adopt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    zpath = dest / name
    files = [f for rel in [*moving, W.MARKER] for f in _walk(hub / rel)]
    sums = {f.relative_to(hub).as_posix(): _sha(f) for f in files}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for f in files:
            z.write(f, f.relative_to(hub).as_posix())
        z.writestr("_sha256.json", json.dumps(sums, ensure_ascii=False, indent=1))
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        bad = [rel for rel, sha in sums.items() if _sha(Path(tmp) / rel) != sha]
    if bad:
        raise AdoptError(f"архів {zpath} не звірився ({len(bad)} файлів: {', '.join(bad[:3])})")
    return {"zip": str(zpath), "files": len(sums),
            "bytes": zpath.stat().st_size}


def _rewrite_cited_by(hub: Path, pid: str) -> int:
    """Голі імена карток у `cited_by` → `<pid>:<картка>.md`: тепер вони проєктні."""
    from nyshporka.canon.check import manifest_path
    from nyshporka.utils.atomic import read_json, write_json

    man = manifest_path(hub)
    if not man.is_file():
        return 0
    records: dict[str, Any] = read_json(man, default={}) or {}
    changed = 0
    for rec in records.values():
        before = list(rec.get("cited_by") or [])
        after = [f"{pid}:{x}" if isinstance(x, str) and ":" not in x else x for x in before]
        if after != before:
            rec["cited_by"] = list(dict.fromkeys(after))
            changed += 1
    if changed:
        write_json(man, records, indent=1)
    return changed


def _foreign_views(home: Path) -> int:
    """Справи, чий погляд схожий на чужу ціль (портал, замовлення, запит).

    Погляд їде в проєкт роду весь — у чистій Майстерні вбудованого погляду бути
    не може. Перелік (`foreign.tsv`) — щоб потім відділити це в проєкти
    замовлень, не перечитуючи всього сховища.
    """
    from nyshporka.pagestore import split_views as SV

    rows: list[str] = []
    for f in SV._files(W.workspace().pages):
        try:
            d = SV._read(f)
        except (OSError, ValueError):
            continue
        for key, page in (d.get("pages") or {}).items():
            if not SV._inline(page):
                continue
            low = str(page.get("comment") or "").lower()
            hit = [m for m in SV.MARKS if m in low]
            if hit:
                rows.append("\t".join((f"{f.parent.name}/{f.name}", str(key), ",".join(hit))))
    atomic_write_text(home / "foreign.tsv",
                      "справа\tсторінка\tпозначки\n" + "".join(r + "\n" for r in rows))
    return len(rows)


def _set_hub_marker(hub: Path, pid: str) -> None:
    text = (hub / W.MARKER).read_text(encoding="utf-8")
    text = W._marker_set(text, "hub_only", "hub_only = true")
    text = W._marker_set(text, "legacy_project", f'legacy_project = "{pid}"')
    W._write_marker(hub / W.MARKER, text)


def apply(hub: Path, pid: str, *, archive: Path) -> dict[str, Any]:
    from nyshporka import project as PR
    from nyshporka.canon.check import manifest_path
    from nyshporka.cases.rekey import _refuse_busy
    from nyshporka.core.lock import read as read_lock
    from nyshporka.pagestore import split_views as SV

    pl = plan(hub, pid)
    if pl.problems:
        raise AdoptError("переїзд не починаю:\n" + "\n".join(f"  - {p}" for p in pl.problems))
    try:
        archive.resolve().relative_to(hub.resolve())
        raise AdoptError(f"архів кладеться поза Майстернею, а {archive} — усередині неї")
    except ValueError:
        pass
    held = read_lock(hub)
    if held is not None and not held.is_stale():
        raise AdoptError(f"Майстерню тримає застосунок (pid {held.pid}) — закрийте його")
    base = W._build(hub, "explicit")
    _refuse_busy(base.pages)
    moving = [m.path for m in pl.moves]
    repo = _is_repo(hub)

    home = _new_home(hub)
    shutil.copy2(hub / W.MARKER, home / "marker.toml")
    man = manifest_path(hub)
    if man.is_file():
        shutil.copy2(man, home / "manifest.json")
    journal: dict[str, Any] = {"stamp": home.name, "pid": pid, "started": time.time(),
                               "steps": [], "moved": [], "repo": repo}
    _journal(home, journal)

    def step(name: str, **extra: Any) -> None:
        journal["steps"].append(name)
        journal.update(extra)
        _journal(home, journal)

    try:
        step("archive", archive=_archive(hub, moving, archive))
        with W.using(base):
            step("foreign", foreign=_foreign_views(home))
        with W.using(base):
            created = PR.create(hub, pid, kind="family")
        step("create", created=[str(created.root / f) for f in created.files])
        root = created.root
        with W.using(base):
            split = SV.apply(pid)
        step("split", split_stamp=split.get("stamp") or "")
        for rel in moving:
            dst = root / rel
            if dst.is_dir() and not any(dst.iterdir()):
                dst.rmdir()          # порожня тека з шаблону — місце для своєї
            if dst.exists():
                raise AdoptError(f"projects/{pid}/{rel} уже є — не затираю")
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(hub / rel, dst)
            journal["moved"].append(rel)
            _journal(home, journal)
        if repo:
            proj_rel = root.relative_to(hub).as_posix()
            _git(hub, "add", "-A", "--", *moving, *[f"{proj_rel}/{r}" for r in moving])
        step("moved")
        step("cited_by", cited_by=_rewrite_cited_by(hub, pid))
        _set_hub_marker(hub, pid)
        step("marker")
        W.reset()
    except Exception as exc:
        journal["failed"] = f"{type(exc).__name__}: {exc}"
        _journal(home, journal)
        try:
            rollback(hub, home.name)
        except Exception as rb:  # відкат теж упав — людині обидві причини
            raise AdoptError(f"переїзд упав ({exc}), і відкат теж ({rb}). Журнал: "
                             f"{home / 'journal.json'}") from exc
        raise AdoptError(f"переїзд упав ({exc}); усе повернуто за журналом "
                         f"{home / 'journal.json'}") from exc
    journal["done"] = time.time()
    _journal(home, journal)
    return {"stamp": home.name, "project": str(root), "moved": moving,
            "archive": journal["archive"], "split": journal.get("split_stamp"),
            "cited_by": journal.get("cited_by", 0)}


def rollback(hub: Path, stamp: str | None = None) -> dict[str, Any]:
    """Повернути переїзд `stamp` (останній, якщо не названо) за журналом."""
    from nyshporka.canon.check import manifest_path
    from nyshporka.pagestore import split_views as SV

    base = hub / ADOPT_DIR
    homes = sorted(p for p in base.iterdir() if (p / "journal.json").is_file()) \
        if base.is_dir() else []
    live = [p for p in homes
            if not json.loads((p / "journal.json").read_text(encoding="utf-8"))
            .get("rolled_back")]
    pick = [p for p in live if p.name == stamp] if stamp else live[-1:]
    if not pick:
        raise AdoptError(f"переїзду для відкату немає ({base})")
    home = pick[0]
    journal = json.loads((home / "journal.json").read_text(encoding="utf-8"))
    pid = journal["pid"]
    root = P.projects_dir(hub) / pid
    steps = journal.get("steps") or []
    # Маркер — першим: далі простір знову корінь старого типу.
    if (home / "marker.toml").is_file():
        W._write_marker(hub / W.MARKER, (home / "marker.toml").read_text(encoding="utf-8"))
    W.reset()
    if (home / "manifest.json").is_file():
        shutil.copy2(home / "manifest.json", manifest_path(hub))
    moved = list(journal.get("moved") or [])
    for rel in reversed(moved):
        src = root / rel
        if src.exists() and not (hub / rel).exists():
            (hub / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, hub / rel)
    if journal.get("repo") and moved:
        proj_rel = root.relative_to(hub).as_posix()
        _git(hub, "add", "-A", "--", *moved, *[f"{proj_rel}/{r}" for r in moved],
             check=False)
    if "split" in steps and journal.get("split_stamp"):
        with W.using(W._build(hub, "explicit")):
            SV.rollback(journal["split_stamp"], force=True)
    if "create" in steps and root.is_dir():
        # Тека проєкту — наша, лише якщо в ній не лишилось нічого, крім шаблону.
        from nyshporka.project import LEDGER

        made = {Path(p).resolve() for p in journal.get("created") or []}
        made.add((root / LEDGER).resolve())
        left = [f for f in _walk(root) if f.resolve() not in made]
        if not left:
            shutil.rmtree(root)
            pdir = P.projects_dir(hub)
            if pdir.is_dir() and not any(pdir.iterdir()):
                pdir.rmdir()
    journal["rolled_back"] = datetime.now(UTC).isoformat(timespec="seconds")
    _journal(home, journal)
    return {"stamp": home.name, "restored": moved}
