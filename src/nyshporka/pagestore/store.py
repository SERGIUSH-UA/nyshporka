"""Читання/запис сховища сторінок: `data/pages/<REPO>/<fond>-<spr>.json`.

Ідіоми ті самі, що в library/decode_hits: atomic tmp+replace, людська праця
переживає повторний запис (union-merge, статус лише підвищується), ключ справи —
трійка repo/fond/spr без опису. Плюс lockfile — бо основний сценарій це
паралельні агентні сесії, що пишуть в одну справу.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from nyshporka.core.workspace import workspace
from nyshporka.library import (
    _DEFAULT_OPYS,
    _OPYS_IN_KEY,
    _REPO_LABEL,
    _mk_key,
    _norm_spr,
    load_library,
    parse_case_code,
    parse_source_id,
    split_fond_opys,
)
from nyshporka.pagestore.models import CaseFile, PageNote, Record

ROOT = workspace().root
PAGES_ROOT = workspace().pages

_IMG_EXT = {".jpg", ".jpeg", ".png"}

# порядок підвищення статусу: понизити повний прохід частковим не можна
_STATUS_RANK = {"unreadable": 0, "skipped": 0, "partial": 1, "full": 2}

# «DAHMO/315/8433» і «ANRM/211-3/140» — друга форма з описом у фонді (`_OPYS_IN_KEY`)
# 🔴 Підкреслення в класі спр. — для ЗБІРОК: `@fuzovka` і `@parkovo` проходили,
# а `@klirovi_films` і `@kishinev_ispovedn` — ні, бо `_` у клас не входило.
# Виглядало це не як синтаксична межа, а як «такої справи немає»: команда
# друкувала перелік прийнятних форм, серед яких ключ і був. Спіймано 2026-08-13,
# коли перегляд кадру збірки клірових ANRM не було куди занести.
_KEY_RE = re.compile(r"^([A-Za-z]+)/(\d+(?:-\d+)?)/([0-9A-Za-z@_]+)$")
# «АРХІВ 123-1-456» / «dahmo 315-1-8433» / «315-1-8433» (без архіву — помилка)
_SHIFRA_RE = re.compile(r"^(?:(\S+)\s+)?(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\w+)$")
_LABEL2REPO = {v.casefold(): k for k, v in _REPO_LABEL.items()} | {
    k.casefold(): k for k in _REPO_LABEL
}

_ACCEPTED_FORMATS = (
    "ключ «DAHMO/315/8433» (з описом — «ANRM/211-3/140»), шифра з архівом "
    "«АРХІВ 123-1-456», source-id «S_<АРХІВ>_F<фонд>_D<справа>» або шлях "
    "«data/raw/архів_123/spr-456»"
)


@dataclass
class CaseRef:
    """Розв'язана справа + збагачення з бібліотеки."""

    key: str
    repo: str
    fond: str
    spr: str
    opys: str | None = None
    shifra: str = ""
    title: str = ""
    path: str = ""          # rel-шлях теки сканів (або .pdf) — для status
    frames: int | None = None


@dataclass
class MergeReport:
    """Що сталося при annotate_pages/add_records."""

    path: str
    added: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"path": self.path, "added": self.added, "merged": self.merged,
                "replaced": self.replaced, "errors": self.errors}


# ── резолюція справи ─────────────────────────────────────────────────────────
def resolve_case(value: str) -> CaseRef:
    """Будь-який людський ідентифікатор справи → CaseRef. ValueError якщо не вийшло."""
    v = (value or "").strip()
    parsed: tuple[str, str, str | None, str] | None = None
    m = _KEY_RE.match(v)
    if m:
        fond_part, opys_part = split_fond_opys(m.group(2))
        parsed = (m.group(1).upper(), str(_norm_spr(fond_part)),
                  _norm_spr(opys_part) if opys_part else None,
                  str(_norm_spr(m.group(3))))
    if parsed is None:
        ms = _SHIFRA_RE.match(v)
        if ms:
            label, fond, opys, spr = ms.groups()
            if not label:
                raise ValueError(
                    f"шифра «{v}» без архіву неоднозначна — додай архів "
                    f"(«ДАХмО {v}») або дай ключ/шлях. Приймаю: {_ACCEPTED_FORMATS}")
            repo = _LABEL2REPO.get(label.casefold())
            if not repo:
                raise ValueError(
                    f"невідомий архів «{label}» (знаю: {', '.join(sorted(_REPO_LABEL.values()))})")
            parsed = (repo, str(_norm_spr(fond)), _norm_spr(opys), str(_norm_spr(spr)))
    if parsed is None and v.startswith("S_"):
        parsed = parse_source_id(v)
    if parsed is None:
        parsed = parse_case_code(v)
    if parsed is None:
        raise ValueError(f"не розпізнав справу «{value}». Приймаю: {_ACCEPTED_FORMATS}")

    repo, fond, opys, spr = parsed
    lib = load_library()
    # Фонди з описом у ключі: без опису запит неоднозначний за побудовою
    # («ANRM 211-1-140» с. Парково vs «ANRM 211-3-140» Кишинівський собор).
    # Мовчки взяти перший-ліпший = дописати аркуші в чужу справу, тому — помилка
    # з переліком того, що реально є на диску.
    if (repo, fond) in _OPYS_IN_KEY and not opys and not str(spr).startswith("@"):
        cands = sorted({e.get("opys") for e in lib
                        if e.get("repo") == repo and e.get("fond") == fond
                        and e.get("spr") == spr and e.get("opys")})
        if len(cands) == 1:
            opys = cands[0]
        else:
            label = _REPO_LABEL.get(repo, repo)
            seen = ", ".join(f"«{label} {fond}-{o}-{spr}»" for o in cands) or "жодного"
            raise ValueError(
                f"у фонді {label} {fond} опис входить у ключ, а «{value}» його не несе. "
                f"Уточни опис (напр. «{label} {fond}-3-{spr}» або «{repo}/{fond}-3/{spr}»). "
                f"На диску знайдено: {seen}")
    key = _mk_key(repo, fond, spr, opys)
    if not key:
        raise ValueError(f"не зібрав ключ зі «{value}» (repo={repo} fond={fond} spr={spr})")

    entry = next((e for e in lib if e.get("key") == key), None)
    if entry is None:
        # ДАВО/ДАВіО-плутанина: лейбл шифри каже одне, тека диска — інше.
        # Якщо по (fond, spr) у бібліотеці РІВНО один запис — його ключ канонічний,
        # інакше нотатки тієї самої справи розповзуться по двох файлах.
        same = [e for e in lib if e.get("fond") == fond and e.get("spr") == spr
                and (not opys or not e.get("opys") or e.get("opys") == opys)]
        if len(same) == 1:
            entry = same[0]
            repo, key = entry["repo"], entry["key"]
    entry = entry or {}
    opys = opys or entry.get("opys") or _DEFAULT_OPYS.get((repo, fond))
    label = _REPO_LABEL.get(repo, repo)
    shifra = entry.get("shifra") or f"{label} {fond}-{opys or '?'}-{spr}"
    return CaseRef(
        key=key, repo=repo, fond=fond, spr=spr, opys=opys, shifra=shifra,
        title=entry.get("title") or "",
        path=entry.get("path") or entry.get("raw_path") or "",
        frames=entry.get("frames"),
    )


def case_path(ref: CaseRef) -> Path:
    """Шлях JSON-файлу справи. Ім'я — з ключа: опис у ньому лише там, де він у ключі.

    `DAHMO/315/8433` → `DAHMO/315-8433.json`; `ANRM/211-3/140` → `ANRM/211-3-140.json`.
    """
    if (ref.repo, ref.fond) in _OPYS_IN_KEY and ref.opys and not str(ref.spr).startswith("@"):
        return PAGES_ROOT / ref.repo / f"{ref.fond}-{ref.opys}-{ref.spr}.json"
    return PAGES_ROOT / ref.repo / f"{ref.fond}-{ref.spr}.json"


# ── читання ──────────────────────────────────────────────────────────────────
def load_case(ref: CaseRef) -> CaseFile | None:
    p = case_path(ref)
    if not p.is_file():
        return None
    return CaseFile.model_validate_json(p.read_text(encoding="utf-8"))


def _empty_case(ref: CaseRef) -> CaseFile:
    return CaseFile(key=ref.key, repo=ref.repo, fond=ref.fond, spr=ref.spr,
                    opys=ref.opys, shifra=ref.shifra, title=ref.title, path=ref.path)


# ── lockfile: паралельні агенти пишуть в одну справу ─────────────────────────
@contextmanager
def _lock(path: Path, timeout: float = 5.0, stale: float = 30.0):
    lockp = path.with_name(path.name + ".lock")
    lockp.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lockp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lockp.stat().st_mtime > stale:
                    lockp.unlink(missing_ok=True)   # власник помер — забираємо лок
                    continue
            except OSError:
                continue                             # лок щойно зник — нова спроба
            if time.monotonic() > deadline:
                raise TimeoutError(f"лок {lockp} зайнятий довше {timeout:.0f}с") from None
            time.sleep(0.1)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lockp.unlink(missing_ok=True)


def _rel(path: Path) -> str:
    """Rel-шлях від кореня для звітів; абсолютний, якщо PAGES_ROOT винесено (тести)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _write(path: Path, cf: CaseFile) -> None:
    cf.pages = dict(sorted(cf.pages.items()))
    cf.records.sort(key=lambda r: (r.scans[0] if r.scans else "", r.rid))
    payload = cf.model_dump(mode="json")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


# ── merge ────────────────────────────────────────────────────────────────────
def _union(a: list[str], b: list[str]) -> list[str]:
    """Об'єднання зі збереженням порядку першої появи; dedup casefold по сирому рядку."""
    seen: dict[str, str] = {}
    for s in [*a, *b]:
        k = s.casefold()
        if k not in seen:
            seen[k] = s
    return list(seen.values())


def _merge_note(old: PageNote, new: PageNote) -> PageNote:
    merged = new.model_copy(deep=True)
    merged.surnames = _union(old.surnames, new.surnames)
    merged.places = _union(old.places, new.places)
    merged.years = list(dict.fromkeys([*old.years, *new.years]))
    if _STATUS_RANK[new.status] < _STATUS_RANK[old.status]:
        merged.status = old.status          # повний прохід не понижується частковим
    for f in ("sheet", "agent"):
        if not getattr(new, f):
            setattr(merged, f, getattr(old, f))
    # коментарі різних агентів НЕ затирають одне одного (інцидент 00898,
    # 2026-07-21: паралельна сесія стерла попередження про фальш-друга) —
    # конкатенуємо відмінні, обрізаючи хвіст на 600 символах
    if not new.comment:
        merged.comment = old.comment
    elif old.comment and old.comment not in new.comment \
            and new.comment not in old.comment:
        merged.comment = f"{new.comment} ⟂ {old.comment}"[:600]
    return merged


def annotate_pages(ref: CaseRef, notes: list[PageNote], replace: bool = False) -> MergeReport:
    """Внести/домержити анотації сторінок. Пише атомарно під локом."""
    path = case_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = MergeReport(path=_rel(path))
    with _lock(path):
        cf = load_case(ref) or _empty_case(ref)
        # збагачення бібліотеки могло оновитись — освіжаємо, не чіпаючи дані
        cf.shifra, cf.title = ref.shifra or cf.shifra, ref.title or cf.title
        cf.path, cf.opys = ref.path or cf.path, ref.opys or cf.opys
        for note in notes:
            old = cf.pages.get(note.scan)
            if old is None:
                cf.pages[note.scan] = note
                report.added.append(note.scan)
            elif replace:
                cf.pages[note.scan] = note
                report.replaced.append(note.scan)
            else:
                cf.pages[note.scan] = _merge_note(old, note)
                report.merged.append(note.scan)
        _write(path, cf)
    return report


def add_records(ref: CaseRef, records: list[Record], replace: bool = False) -> MergeReport:
    """Внести записи (upsert по rid). `replace=True` стирає всі записи справи спершу."""
    path = case_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = MergeReport(path=_rel(path))
    with _lock(path):
        cf = load_case(ref) or _empty_case(ref)
        if replace and cf.records:
            report.replaced = [r.rid for r in cf.records]
            cf.records = []
        by_rid = {r.rid: i for i, r in enumerate(cf.records)}
        for rec in records:
            i = by_rid.get(rec.rid)
            if i is None:
                by_rid[rec.rid] = len(cf.records)
                cf.records.append(rec)
                report.added.append(rec.rid)
            else:
                cf.records[i] = rec
                report.merged.append(rec.rid)
        _write(path, cf)
    return report


# ── статус: «чи рендерити цю сторінку?» ──────────────────────────────────────
def _disk_scans(ref: CaseRef) -> list[str]:
    if not ref.path:
        return []
    d = (ROOT / ref.path)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in _IMG_EXT)


_NUM_NAME_RE = re.compile(r"^(.*?)(\d+)(\D*)$")


def _compress(names: list[str]) -> list[str]:
    """Послідовні числові імена → діапазони: «0031.JPG–0045.JPG (15)»."""
    out: list[str] = []
    run: list[str] = []
    prev: tuple[str, int, str] | None = None
    def flush() -> None:
        if not run:
            return
        out.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]} ({len(run)})")
        run.clear()
    for name in names:
        m = _NUM_NAME_RE.match(name)
        cur = (m.group(1), int(m.group(2)), m.group(3)) if m else None
        if not (cur and prev and cur[0] == prev[0] and cur[2] == prev[2]
                and cur[1] == prev[1] + 1):
            flush()
        run.append(name)
        prev = cur
    flush()
    return out


def case_status(ref: CaseRef, scans: list[str] | None = None) -> dict:
    """Гейт перед рендером: що вже оброблено, що ні."""
    cf = load_case(ref)
    pages = cf.pages if cf else {}
    if scans:
        return {"key": ref.key, "shifra": ref.shifra, "scans": [
            ({"scan": s, "noted": True, "page_type": n.page_type, "status": n.status,
              "surnames_n": len(n.surnames), "noted_date": n.noted.isoformat()}
             if (n := pages.get(s)) else {"scan": s, "noted": False})
            for s in scans]}
    disk = _disk_scans(ref)
    unnoted = [s for s in disk if s not in pages]
    by_status: dict[str, int] = {}
    for n in pages.values():
        by_status[n.status] = by_status.get(n.status, 0) + 1
    return {
        "key": ref.key, "shifra": ref.shifra, "title": ref.title,
        "total_disk": len(disk) or (ref.frames or 0),
        "noted": len(pages), "by_status": by_status,
        "records": len(cf.records) if cf else 0,
        "unnoted_count": len(unnoted) if disk else None,
        "unnoted": _compress(unnoted) if disk else None,
    }
