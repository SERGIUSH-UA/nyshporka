"""🧳 Корінь старого типу → Майстерня + проєкт (`nysh project adopt <ім'я>`).

Простір, у якому хаб і рід — та сама тека (id «.»), стає чистою Майстернею
(`hub_only = true`), а все проєктне — канон, профіль роду, вердикти, журнал
пошуку, погляд на сторінки, сайт — переїжджає в `projects/<ім'я>/`.

Порядок `--apply`, кожен крок у журналі `data/cases/adopt/<мітка>/`:

1. архів усього, що їде, ПОЗА Майстернею (`--archive`, типово — тека-сусідка
   `<хаб>-adopt`) з sha256 кожного файла — і звірка кожного члена архіву;
2. тека проєкту з шаблону (`project.create`);
3. погляд на сторінки — `pages split --to` (свій архів і відкат);
4. теки й файли — перенос (`os.replace`) і `git add -A`, щоб історія йшла
   за файлами;
5. `cited_by` маніфесту доказів: голі імена карток → `<ім'я>:<картка>.md`;
6. пам'ять агента — копія в теку пам'яті проєкту (розбір — крок агента);
7. маркер Майстерні: `hub_only = true`, `legacy_project = "<ім'я>"`.

Що їде — за схемою простору, без переліку руками: проєктне ядро
(`BASE_PATHS`), `reports/*` крім `htr` (шар нотаток проєкту), сайт MkDocs,
підтеки `data/source/`, на які посилається канон, плюс `[adopt] extra`, мінус
`[adopt] stay` (шляхи чи маски, зокрема всередині тек, що їдуть).

План відмовляє, коли в шляхах переїзду пишуть просто зараз (файли новіші за
10 хв), хмарний захід тримає машину, а на диску архіву не вистачає місця.

🔴 Без `--apply` — лише план: що їде, скільки, конфлікти. Відкат
(`--rollback`) іде за журналом у зворотному порядку.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
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
#: Звіти, що лишаються в Майстерні: прочитане рушієм — факт справи, а не роду.
HUB_REPORTS = frozenset({"htr"})
#: Файл, записаний частіше, ніж раз на стільки секунд, — у просторі хтось пише.
FRESH_SECONDS = 600
#: Запас місця під архів понад обсяг того, що їде.
SPACE_MARGIN = 1.1
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
    archive: str = ""
    archive_free: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "hub": self.hub,
                "moves": [m.as_dict() for m in self.moves], "views": self.views,
                "files": sum(m.files for m in self.moves),
                "size": sum(m.size for m in self.moves), "problems": self.problems,
                "archive": self.archive, "archive_free": self.archive_free}


# ── допоміжне ────────────────────────────────────────────────────────────────
def _git(hub: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=hub, capture_output=True)
    if check and out.returncode != 0:
        err = out.stderr.decode("utf-8", errors="replace").strip()
        raise AdoptError(f"git {args[0] if args else ''} (код {out.returncode}): "
                         f"{err[:600] or 'без пояснення'}")
    return out.stdout.decode("utf-8", errors="replace")


TRACKED_LIST = "tracked.txt"


def _tracked_files(hub: Path, paths: list[str]) -> list[str]:
    """Файли, які git відстежує в цих шляхах, — точний перелік, без шаблонів."""
    if not paths:
        return []
    out = _git(hub, "--literal-pathspecs", "ls-files", "-z", "--", *paths)
    return [x for x in out.split("\0") if x]


def _restage(hub: Path, home: Path, files: list[str], src: str, dst: str) -> None:
    """Перенести в індексі рівно ці файли: зі `src/<файл>` на `dst/<файл>`.

    Не `git add -A -- <тека>`: відстежуваний файл під шаблоном `.gitignore`
    (`data/site/site.yml` під `site/`) git на новому місці відкидає, а шлях,
    якого в індексі не було, — фатальна «pathspec не знайдено». Точний перелік
    з примусом (`-f`) лишає відстеженим рівно те, що було відстежене, і не
    додає ігнорованого, якого в git не було.
    """
    if not files:
        return
    def pre(base: str, f: str) -> str:
        return f"{base}/{f}" if base else f

    lst = home / "pathspec.txt"
    lst.write_bytes("\0".join(pre(src, f) for f in files).encode("utf-8"))
    _git(hub, "--literal-pathspecs", "rm", "-r", "-q", "--cached", "--ignore-unmatch",
         f"--pathspec-from-file={lst}", "--pathspec-file-nul")
    lst.write_bytes("\0".join(pre(dst, f) for f in files).encode("utf-8"))
    _git(hub, "--literal-pathspecs", "add", "-f", f"--pathspec-from-file={lst}",
         "--pathspec-file-nul")
    lst.unlink()


def _is_repo(hub: Path) -> bool:
    try:
        top = _git(hub, "rev-parse", "--show-toplevel").strip()
    except (AdoptError, FileNotFoundError):
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


def _adopt_cfg(hub: Path) -> dict[str, Any]:
    got = W._read_toml(hub / W.MARKER).get("adopt") or {}
    return got if isinstance(got, dict) else {}


def _list(cfg: dict[str, Any], key: str) -> list[str]:
    return [str(x).strip().strip("/") for x in (cfg.get(key) or []) if str(x).strip()]


def extra_paths(hub: Path) -> list[str]:
    """Додаткові шляхи Майстерні: `[adopt] extra = [...]` у маркері."""
    return _list(_adopt_cfg(hub), "extra")


def stay_patterns(hub: Path) -> list[str]:
    """Що лишається в Майстерні: `[adopt] stay = [...]` (шляхи або маски `*`)."""
    return _list(_adopt_cfg(hub), "stay")


def _reports_paths(hub: Path) -> list[str]:
    """`reports/*`, крім прочитаного рушієм.

    Той самий набір, що шар нотаток (`search.textops`, шар `notes`): усе, що
    проєкт шукає як свої нотатки, і є проєктом. Лишись звіти в Майстерні —
    `nysh text grep --where notes` з проєкту їх уже не побачив би.
    """
    rep = W.Workspace(root=hub).reports
    if not rep.is_dir():
        return []
    return [f"reports/{c.name}" for c in sorted(rep.iterdir()) if c.name not in HUB_REPORTS]


def _site_paths(hub: Path) -> list[str]:
    """Сайт роду на MkDocs: конфіги, сирці, тема — разом із каноном, з якого він."""
    if not (hub / "mkdocs.yml").is_file():
        return []
    return [*(f.name for f in sorted(hub.glob("mkdocs*.yml"))), "docs", "overrides"]


def _source_refs(hub: Path) -> set[str]:
    """Посилання карток на `data/source/…` (крім стору доказів), як у тексті."""
    canon = W.Workspace(root=hub).canonical
    if not canon.is_dir():
        return set()
    pat = re.compile(r"data/source/[^\s)\"'`\]>|]+")
    out: set[str] = set()
    for card in canon.rglob("*.md"):
        for raw in pat.findall(card.read_text(encoding="utf-8", errors="replace")):
            ref = raw.rstrip(".,;:")
            if not ref.startswith("data/source/citations/") and (hub / ref).exists():
                out.add(ref)
    return out


def _source_paths(hub: Path) -> list[str]:
    """Підтеки `data/source/`, на які посилається канон: вони їдуть разом із ним.

    Канон резолвить такі шляхи від кореня проєкту, тож тека, що лишилась би
    в Майстерні, після переїзду стала б битим посиланням у картці.
    """
    return sorted({"/".join(r.split("/")[:3]) for r in _source_refs(hub)})


def _stays(rel: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) for p in pats)


def _expand(hub: Path, rel: str, pats: list[str]) -> list[str]:
    """Шлях, що їде, мінус те, що лишається.

    Тека, всередині якої щось лишається (`stay = ["reports/research/x"]`),
    їде поелементно — тоді перенос і відкат лишаються простими `os.replace`.
    """
    if _stays(rel, pats):
        return []
    path = hub / rel
    inner = [p for p in pats if p.startswith(rel + "/")]
    if not inner or not path.is_dir():
        return [rel]
    out: list[str] = []
    for child in sorted(path.iterdir()):
        out += _expand(hub, f"{rel}/{child.name}", pats)
    return out


def paths_to_move(hub: Path) -> list[str]:
    cand = dict.fromkeys([*BASE_PATHS, *_reports_paths(hub), *_site_paths(hub),
                          *_source_paths(hub), *extra_paths(hub)])
    pats = stay_patterns(hub)
    out: list[str] = []
    for rel in cand:
        if (hub / rel).exists():
            out += _expand(hub, rel, pats)
    return list(dict.fromkeys(out))


def _refs_left_behind(hub: Path, moving: list[str]) -> list[str]:
    """Посилання карток на `data/source/…`, які все-таки лишились би в Майстерні.

    Підтеки з посиланнями їдуть самі (`_source_paths`); сюди доходить лише те,
    що людина свідомо лишила в `[adopt] stay`.
    """
    return sorted(r for r in _source_refs(hub)
                  if not any(r == m or r.startswith(m.rstrip("/") + "/") for m in moving))


def _fresh(hub: Path, moving: list[str], *, now: float | None = None) -> list[str]:
    """Файли в шляхах переїзду, записані за останні `FRESH_SECONDS`.

    Свіжий запис означає, що в простір пише інша сесія агента, завантажувач чи
    наглядач хмари. Перенести теку з-під нього — означає, що його наступний
    запис ляже в теку, якої вже немає, або половиною потрапить у переїзд.
    """
    edge = (now or time.time()) - FRESH_SECONDS
    out: list[str] = []
    for rel in moving:
        for f in _walk(hub / rel):
            try:
                if f.stat().st_mtime > edge:
                    out.append(f.relative_to(hub).as_posix())
            except OSError:
                continue
    return out


def _held_machines(hub: Path) -> list[str]:
    """Хмарні заходи простору, що досі тримають орендовану машину."""
    from nyshporka.cloud import state as CS

    with W.using(W._build(hub, "explicit")):
        try:
            return [s.run_id for s in CS.live() if s.needs_release]
        except Exception:
            return []


def default_archive(hub: Path) -> Path:
    """Тека архіву за замовчуванням: сусідка Майстерні, поза нею."""
    return hub.parent / f"{hub.name}-adopt"


def _free(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _space_problem(dest: Path, size: int) -> str:
    need = int(size * SPACE_MARGIN)
    free = _free(dest)
    if free >= need:
        return ""
    return (f"для архіву треба ~{need / 2**30:.1f} ГБ, а в {dest} вільно "
            f"{free / 2**30:.1f} ГБ — вкажіть іншу теку: --archive <тека поза Майстернею>")


# ── план ─────────────────────────────────────────────────────────────────────
def plan(hub: Path, pid: str, *, archive: Path | None = None) -> Plan:
    from nyshporka import project as PR
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
        pl.problems.append(f"картка посилається на {ref}, а він лишається в Майстерні "
                           f"([adopt] stay) — приберіть його звідти")
    fresh = _fresh(hub, moving)
    if fresh:
        pl.problems.append(
            f"у шляхах переїзду пишуть просто зараз ({len(fresh)} файлів новіші за "
            f"{FRESH_SECONDS // 60} хв: {', '.join(fresh[:3])}) — інша сесія, "
            "завантажувач чи наглядач; дочекайтесь, поки закінчить")
    held = _held_machines(hub)
    if held:
        pl.problems.append(f"хмарні заходи тримають машину ({', '.join(held[:3])}) — "
                           "спершу забрати результат і звільнити (`nysh cloud state`)")
    mem = PR.memory_dir(P.projects_dir(hub) / pid)
    if mem.is_dir() and any(mem.iterdir()):
        pl.problems.append(f"пам'ять агента для projects/{pid} уже є ({mem}) — "
                           "не затираю; перенесіть її вбік")
    dest = archive or default_archive(hub)
    pl.archive, pl.archive_free = str(dest), _free(dest)
    space = _space_problem(dest, sum(m.size for m in pl.moves))
    if space:
        pl.problems.append(space)
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
    lines.append(f"  архів: {pl.archive} (вільно {pl.archive_free / 2**30:.1f} ГБ)")
    if not pl.problems:
        lines.append(f"Далі: nysh project adopt {pl.pid} --apply"
                     + (f" --archive {pl.archive}" if pl.archive != str(default_archive(Path(pl.hub)))
                        else ""))
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


def _sha_member(z: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with z.open(name) as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: Уже стиснене (скани, PDF, архіви): deflate тут лише палить час — на корені з
#: гігабайтами сканів саме він з'їдав більшість хвилин архівування.
_STORED = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".pdf",
                     ".zip", ".gz", ".rar", ".7z", ".mp4", ".mp3", ".docx", ".xlsx"})


def _verified_mark(zpath: Path) -> Path:
    return zpath.with_name(zpath.name + ".ok")


def _journaled(hub: Path) -> set[str]:
    """Архіви, звірку яких засвідчив журнал переїзду (крок `archive` — після звірки)."""
    out: set[str] = set()
    for jp in (hub / ADOPT_DIR).glob("*/journal.json"):
        try:
            j = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "archive" in (j.get("steps") or []) and (j.get("archive") or {}).get("zip"):
            out.add(str(Path(j["archive"]["zip"]).resolve()))
    return out


def _reusable(hub: Path, dest: Path, sums: dict[str, str]) -> Path | None:
    """Звірений архів попередньої спроби з тим самим переліком sha256.

    Переїзд, що впав після архіву (і відкотився), не мусить пакувати ті самі
    гігабайти вдруге: якщо кожен файл досі той самий, архів — та сама копія.
    Береться лише звірений архів — з позначкою `<zip>.ok` або записаний у
    журналі як пройдений крок; недописаний чи незвірений zip не має жодного.
    """
    seen = _journaled(hub)
    for zpath in sorted(dest.glob("adopt-*.zip"), reverse=True):
        if not _verified_mark(zpath).is_file() and str(zpath.resolve()) not in seen:
            continue
        try:
            with zipfile.ZipFile(zpath) as z:
                old = json.loads(z.read("_sha256.json").decode("utf-8"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue
        if old == sums:
            return zpath
    return None


def _archive(hub: Path, moving: list[str], dest: Path) -> dict[str, Any]:
    """Zip того, що їде, з переліком sha256 — і звірка кожного члена архіву.

    Звірка читає архів потоком, без розпакування на диск: місця треба один
    обсяг, а не два. На корені з гігабайтами сканів друге не влазило.
    """
    dest.mkdir(parents=True, exist_ok=True)
    files = [f for rel in [*moving, W.MARKER] for f in _walk(hub / rel)]
    sums = {f.relative_to(hub).as_posix(): _sha(f) for f in files}
    old = _reusable(hub, dest, sums)
    if old is not None:
        return {"zip": str(old), "files": len(sums), "bytes": old.stat().st_size,
                "reused": True}
    name = f"adopt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    zpath = dest / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for f in files:
            how = zipfile.ZIP_STORED if f.suffix.lower() in _STORED else zipfile.ZIP_DEFLATED
            z.write(f, f.relative_to(hub).as_posix(), compress_type=how)
        z.writestr("_sha256.json", json.dumps(sums, ensure_ascii=False, indent=1))
    with zipfile.ZipFile(zpath) as z:
        bad = [rel for rel, sha in sums.items() if _sha_member(z, rel) != sha]
    if bad:
        raise AdoptError(f"архів {zpath} не звірився ({len(bad)} файлів: {', '.join(bad[:3])})")
    _verified_mark(zpath).write_text(datetime.now(UTC).isoformat(timespec="seconds"),
                                     encoding="utf-8")
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


def _untracked(hub: Path, root: Path) -> list[str]:
    """Файли, що в теці проєкту стали невідстеженими.

    Шаблон `.gitignore` Майстерні, прив'язаний до кореня (`/data/derived/`),
    у підтеці проєкту не діє: файл, який досі ігнорувався, після переїзду
    з'являється в `git status`. Команда їх називає — вирішує людина.
    """
    rel = root.relative_to(hub).as_posix()
    out = _git(hub, "status", "--porcelain", "-z", "--untracked-files=all", "--", rel)
    return [x[3:] for x in out.split("\0") if x.startswith("?? ")]


IGNORE_HEAD = ("# Перенесено з .gitignore Майстерні (`nysh project adopt`): шаблон зі «/»\n"
               "# git прив'язує до теки свого .gitignore, тож у проєкті він мусить бути тут.\n")


def _inside(pattern: str, moved: list[str]) -> bool:
    """Чи шаблон кореня вказує всередину перенесеного шляху (за буквальним префіксом)."""
    body = pattern.lstrip("/")
    if "/" not in body.rstrip("/") or body.startswith("**"):
        return False                   # без скісної — діє на будь-якій глибині й так
    lit = re.split(r"[*?\[]", body, maxsplit=1)[0].rstrip("/")
    return any(lit == m or lit.startswith(m + "/") for m in moved)


def _carry_ignores(hub: Path, root: Path, made: set[str] | frozenset[str] = frozenset(),
                   moved: list[str] | None = None) -> list[str]:
    """Шаблони `.gitignore` Майстерні, що ховали перенесені файли, — у `.gitignore` проєкту.

    Шаблон зі скісною всередині (`docs/persons/`, `data/source/archives/`) git
    прив'язує до теки, де лежить `.gitignore`. Після переїзду він уже не
    ховає ті самі файли в `projects/<ім'я>/`, і гігабайти сканів чи збірки
    сайту виринають у `git status` як нові. Для кожного такого файла береться
    шаблон, що ховав його на старому місці, — і переноситься як є, разом із
    винятками `!…`, що стоять одразу за ним.

    Файли шаблону проєкту (`made`, від кореня проєкту) не переїжджали, тож
    шаблонів для них не шукаємо: інакше `.claude/*` Майстерні сховав би
    `.claude/settings.json` самого проєкту.

    Крім того, переносяться шаблони, що вказують усередину перенесених шляхів
    (`moved`), навіть коли файлів під ними ще немає: збірка сайту створить
    `docs/assets/js/strings.js` уже в проєкті.
    """
    rel = root.relative_to(hub).as_posix()
    olds = [x[len(rel) + 1:] for x in _untracked(hub, root)
            if x.startswith(rel + "/") and x[len(rel) + 1:] not in made]
    gi_hub = hub / ".gitignore"
    if not gi_hub.is_file():
        return []
    lines = gi_hub.read_text(encoding="utf-8", errors="replace").splitlines()
    found: dict[tuple[int, str], None] = {}
    for n, raw in enumerate(lines, 1):
        pat = raw.strip()
        if pat and not pat.startswith(("#", "!")) and moved and _inside(pat, moved):
            found[(n, pat)] = None
    fields: list[str] = []
    if olds:
        out = subprocess.run(["git", "check-ignore", "-v", "-z", "--no-index", "--stdin"],
                             cwd=hub, input=("\0".join(olds) + "\0").encode("utf-8"),
                             capture_output=True)
        fields = out.stdout.decode("utf-8", errors="replace").split("\0")
    for i in range(0, len(fields) - 3, 4):
        source, line, pattern = fields[i], fields[i + 1], fields[i + 2]
        if source == ".gitignore" and pattern and not pattern.startswith("!"):
            found[(int(line or 0), pattern)] = None
    if not found:
        return []
    pats: list[str] = []
    for n, pat in sorted(found):
        pats.append(pat)
        for nxt in lines[n:]:                     # винятки за шаблоном
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            if not nxt.startswith("!"):
                break
            pats.append(nxt)
    pats = list(dict.fromkeys(pats))
    if pats:
        gi = root / ".gitignore"
        have = gi.read_text(encoding="utf-8") if gi.is_file() else ""
        gi.write_text(have + ("\n" if have and not have.endswith("\n") else "")
                      + IGNORE_HEAD + "".join(f"{x}\n" for x in pats), encoding="utf-8")
    return pats


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


def _copy_memory(hub: Path, root: Path) -> str:
    """Пам'ять агента кореня старого типу — пам'ять єдиного проєкту: копія в проєкт.

    Хаб нічого не втрачає. Розібрати, що родинне (лишити в проєкті), а що —
    правила роботи (лишити в хабі), — судження, тож це крок агента після
    переїзду, а не коду (`nysh migrate`).
    """
    from nyshporka import project as PR

    src, dst = PR.memory_dir(hub), PR.memory_dir(root)
    if not src.is_dir():
        return ""
    shutil.copytree(src, dst)
    return str(dst)


#: Кроки агента після переїзду: їх не зробиш кодом, бо це судження.
AFTER = (
    "пам'ять агента скопійовано в проєкт: родинне лишити там, правила роботи — у "
    "пам'яті Майстерні; верх MEMORY.md Майстерні — до 5 тис. знаків (решту хук "
    "проєкту обріже); перелік — людині до видалення",
    "CLAUDE.md / AGENTS.md Майстерні сесія проєкту читає сама: опис роду й «де що "
    "лежить» перенести в CLAUDE.md проєкту",
    "відкрити агента в теці проєкту (`nysh project open <ім'я>`) і перевірити, що "
    "стан роду приходить на старті",
)


def apply(hub: Path, pid: str, *, archive: Path | None = None) -> dict[str, Any]:
    from nyshporka import project as PR
    from nyshporka.canon.check import manifest_path
    from nyshporka.cases.rekey import _refuse_busy
    from nyshporka.core.lock import read as read_lock
    from nyshporka.pagestore import split_views as SV

    archive = archive or default_archive(hub)
    pl = plan(hub, pid, archive=archive)
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
    files = _tracked_files(hub, [m.path for m in pl.moves if m.tracked]) if repo else []

    home = _new_home(hub)
    shutil.copy2(hub / W.MARKER, home / "marker.toml")
    man = manifest_path(hub)
    if man.is_file():
        shutil.copy2(man, home / "manifest.json")
    journal: dict[str, Any] = {"stamp": home.name, "pid": pid, "started": time.time(),
                               "steps": [], "moved": [], "repo": repo,
                               "tracked_files": len(files)}
    (home / TRACKED_LIST).write_bytes("\0".join(files).encode("utf-8"))
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
            _restage(hub, home, files, "", root.relative_to(hub).as_posix())
        if repo:
            here = root.resolve()
            made = {Path(x).resolve().relative_to(here).as_posix()
                    for x in journal.get("created") or [] if Path(x).resolve().is_relative_to(here)}
            ignores = _carry_ignores(hub, root, made, moving)
            if ignores and (root / ".gitignore").is_file():
                journal.setdefault("created", []).append(str(root / ".gitignore"))
            step("ignores", ignores=ignores)
        step("moved", untracked=_untracked(hub, root) if repo else [])
        step("cited_by", cited_by=_rewrite_cited_by(hub, pid))
        step("memory", memory=_copy_memory(hub, root))
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
            "cited_by": journal.get("cited_by", 0), "memory": journal.get("memory", ""),
            "untracked": journal.get("untracked", []),
            "after": list(AFTER)}


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
    if journal.get("memory") and Path(journal["memory"]).is_dir():
        shutil.rmtree(journal["memory"])   # копія: оригінал лишився в хабі
    moved = list(journal.get("moved") or [])
    for rel in reversed(moved):
        src = root / rel
        if src.exists() and not (hub / rel).exists():
            (hub / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, hub / rel)
    if journal.get("repo") and moved and (home / TRACKED_LIST).is_file():
        files = [x for x in (home / TRACKED_LIST).read_text(encoding="utf-8").split("\0") if x]
        _restage(hub, home, files, root.relative_to(hub).as_posix(), "")
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
