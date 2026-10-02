"""Перенос обліку простору на ключі з описом (0.22): `nysh cases rekey`.

До 0.22 ключ справи опису здебільшого не мав (`DAHMO/315/8433`), і ним записано
все, що людина й агенти зробили руками: сховище сторінок, прив'язки прогонів,
вердикти, журнал пошуку, картки Супряги, черга. Тут ці записи переводяться на
`REPO/фонд/опис/справа` (`core.casekey`) — один раз, з архівом для відкату.

Три режими, і перший — за замовчуванням:

  план      нічого не пише; перелічує кожен файл і кожен ключ, що зміниться,
            і те, чого перевести не вдалось;
  перенос   архів усього, що зачіпається → запис → перебудова бібліотеки й
            реєстру → самоперевірка → позначка `keys = 2` у маркері простору;
  відкат    повертає файли з архіву й знімає позначку.

🔴 Старий ключ перекладається за картою, а не вгадується: заморожений старий
будівник (`core.legacy_key`) каже, яким ключем справа звалась до 0.22, а нова
бібліотека — яким зветься тепер. Карта лишається в просторі назавжди
(`data/cases/key_moves.json`), бо старі ключі живуть і там, куди перенос не
дістає: у нотатках, пам'яті агента, чужих повідомленнях.

🔴 Чого перенос НЕ чіпає, і чому:
  · теки з кадрами — тотожність справи дає паспорт, не ім'я теки;
  · ID джерел канону (`S_…`) — це незмінні ідентифікатори, на них посилаються особи;
  · мети прогонів (`_htr_meta.json`) і журнал Супряги — це історія; їхні ключі
    читаються через карту (`htr_store._canon_case_key`);
  · похідні кеші — перебудовуються.

Перенос ідемпотентний: другий запуск на перенесеному просторі нічого не змінює,
а після виправлення опису в паспорті (справа з `_` дістала опис) переносить
облік цієї справи під новий ключ.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core import casekey
from nyshporka.core import legacy_key as legacy

#: Тека архівів переносу в просторі.
REKEY_DIR = Path("data") / "cases" / "rekey"
#: Свіжий лок сховища сторінок — хтось пише просто зараз.
_FRESH_LOCK = 60.0


class RekeyError(RuntimeError):
    """Перенос не почато або зупинено — з причиною."""


@dataclass
class PageMove:
    """Файл сховища сторінок: звідки, куди, яким ключем."""

    src: str
    dst: str
    old_key: str
    new_key: str
    merge: bool = False          # у `dst` уже є облік — зливаються
    #: Супутній файл справи (`315-8433.overrides.json` — вичитка села простору):
    #: його ім'я йде за іменем файла справи, а сам він обліком сторінок не є.
    companion: str = ""


def _companion(name: str) -> str:
    """`315-8433.overrides.json` → `overrides`; файл справи (`315-8433.json`) → `""`."""
    stem = name[:-len(".json")] if name.endswith(".json") else name
    return stem.partition(".")[2]


@dataclass
class Plan:
    """Що зміниться. Шляхи — відносно кореня простору."""

    root: Path
    moves: dict[str, str] = field(default_factory=dict)
    shared: dict[str, list[str]] = field(default_factory=dict)
    pages: list[PageMove] = field(default_factory=list)
    #: файл → [(старий ключ, новий ключ)]
    stores: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: ключі, яких перевести не вдалось: файл → [ключ]
    stuck: dict[str, list[str]] = field(default_factory=dict)
    #: справи, чий опис невідомий (`_`) — переїхали, але опису не мають
    unknown: list[str] = field(default_factory=list)
    keys_before: int = 1

    @property
    def touched(self) -> list[str]:
        out = {m.src for m in self.pages} | {m.dst for m in self.pages if m.merge}
        out |= set(self.stores)
        return sorted(out)

    @property
    def empty(self) -> bool:
        return not (self.pages or self.stores) and self.keys_before >= casekey.KEYS_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "keys_before": self.keys_before,
            "moves": len(self.moves),
            "shared_old_keys": {k: v for k, v in sorted(self.shared.items())},
            "pages": [vars(m) for m in self.pages],
            "stores": {k: [list(x) for x in v] for k, v in sorted(self.stores.items())},
            "stuck": {k: v for k, v in sorted(self.stuck.items())},
            "unknown_opys": self.unknown,
        }


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _read(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


#: Карта, за якою перекладає цей перенос (`plan` ставить її перед обходом).
_MOVES: dict[str, str] = {}


def _new_key(old: str, **fields: Any) -> str | None:
    """Новий ключ для записаного; `None` — перевести нема як.

    Спершу — карта цього переносу (старий ключ кожної справи бібліотеки),
    потім загальний переклад (`legacy_key.current_key`: записана карта, поля
    запису, опис за замовчуванням фонду).
    """
    s = str(old or "").strip()
    got = _MOVES.get(s)
    if got is None and casekey.is_legacy(s):
        norm = legacy.normalize_old(s)
        got = _MOVES.get(norm) if norm else None
    if got is None:
        got = legacy.current_key(s, **fields)
    return got if casekey.parse(got) is not None else None


# ── план ─────────────────────────────────────────────────────────────────────
def plan(*, entries: list[dict[str, Any]] | None = None) -> Plan:
    """Що зміниться при переносі. Нічого не пише.

    `entries` — записи бібліотеки, зібраної новим кодом; без них бібліотека
    збирається тут (повний обхід диска, як `nysh cases build --rescan`).
    """
    from dataclasses import asdict

    from nyshporka.core.workspace import workspace
    from nyshporka.library import build_library

    ws = workspace()
    root = ws.root
    if entries is None:
        entries = [asdict(e) for e in build_library()]
    moves, shared = legacy.moves_from_entries(entries, legacy.registry_set(root))
    # Записана раніше карта (попередній перенос) — головна: на ній уже стоять
    # перенесені записи, і нова збірка бібліотеки її не переписує.
    written = legacy.MOVES
    if (root / written).is_file():
        moves = {**moves, **(_read(root / written).get("moves") or {})}
    pl = Plan(root=root, moves=dict(moves), shared=shared, keys_before=ws.keys)
    _MOVES.clear()
    _MOVES.update(moves)
    _plan_pages(pl, ws.pages)
    _plan_dict(pl, root / "data" / "spotter" / "case_verdicts.json", inner="verdicts")
    _plan_dict(pl, root / "data" / "derived" / "verdicts.json")
    _plan_dict(pl, root / "data" / "derived" / "search_log.json")
    _plan_dict(pl, ws.share / "cards.json")
    _plan_overrides(pl, root / "data" / "cases" / "overrides.json")
    _plan_queue(pl, root / "data" / "queue" / "queue.json")
    _plan_profiles(pl, ws.config / "records_profiles.yaml")
    pl.unknown = sorted(str(e["key"]) for e in entries
                        if (ck := casekey.parse(e.get("key"))) is not None
                        and not ck.bundle and not ck.opys_known)
    return pl


def _plan_pages(pl: Plan, pages_root: Path) -> None:
    if not pages_root.is_dir():
        return
    taken: dict[str, str] = {}
    for f in sorted(pages_root.glob("*/*.json")):
        kind = _companion(f.name)
        try:
            d = _read(f)
        except (OSError, ValueError):
            pl.stuck.setdefault(_rel(pl.root, f), []).append("файл не читається як JSON")
            continue
        if not isinstance(d, dict):
            continue
        old = str(d.get("key") or "").strip()
        new = _new_key(old, repo=str(d.get("repo") or f.parent.name).upper() or None,
                       fond=d.get("fond"), opys=d.get("opys"), spr=d.get("spr"))
        if new is None:
            pl.stuck.setdefault(_rel(pl.root, f), []).append(old or "(без ключа)")
            continue
        ck = casekey.parse(new)
        assert ck is not None
        name = f"{casekey.stem(ck)}.{kind}.json" if kind else f"{casekey.stem(ck)}.json"
        dst = f.parent / name
        src_r, dst_r = _rel(pl.root, f), _rel(pl.root, dst)
        if src_r == dst_r and old == new:
            continue
        merge = (dst.is_file() and dst != f) or dst_r in taken
        if merge and kind:
            # Супутній файл зливати нема як: його будову знає простір, не пакет.
            pl.stuck.setdefault(src_r, []).append(f"{old}: «{dst_r}» уже є")
            continue
        pl.pages.append(PageMove(src_r, dst_r, old, new, merge, kind))
        taken[dst_r] = src_r
        if old and old != new:
            pl.moves.setdefault(old, new)


def _plan_dict(pl: Plan, p: Path, *, inner: str = "") -> None:
    if not p.is_file():
        return
    data = _read(p)
    d = data.get(inner) if inner else data
    if not isinstance(d, dict):
        return
    out: list[tuple[str, str]] = []
    for k in d:
        if k.startswith("_"):
            continue
        new = _new_key(k)
        if new is None:
            pl.stuck.setdefault(_rel(pl.root, p), []).append(k)
        elif new != k:
            out.append((k, new))
            pl.moves.setdefault(k, new)
    if out:
        pl.stores[_rel(pl.root, p)] = out


def _plan_overrides(pl: Plan, p: Path) -> None:
    if not p.is_file():
        return
    data = _read(p)
    out: list[tuple[str, str]] = []
    for run, v in (data.get("runs") or {}).items():
        k = str((v or {}).get("key") or "")
        if not k:
            continue
        new = _new_key(k)
        if new is None:
            pl.stuck.setdefault(_rel(pl.root, p), []).append(f"{run}: {k}")
        elif new != k:
            out.append((k, new))
    for k in data.get("bundles") or {}:
        new = _new_key(k)
        if new is None:
            pl.stuck.setdefault(_rel(pl.root, p), []).append(k)
        elif new != k:
            out.append((k, new))
    if out:
        pl.stores[_rel(pl.root, p)] = sorted(set(out))
        for k, new in out:
            pl.moves.setdefault(k, new)


def _plan_queue(pl: Plan, p: Path) -> None:
    if not p.is_file():
        return
    out: list[tuple[str, str]] = []
    for it in _read(p).get("items") or []:
        ref = it.get("ref") or {}
        for k in (str(it.get("id") or ""), str(ref.get("key") or "")):
            if not k or "/" not in k or not casekey.is_legacy(k):
                continue
            new = _new_key(k)
            if new and new != k:
                out.append((k, new))
        if "aka" in ref:
            out.append((f"ref.aka {ref['aka']}", "прибирається"))
    if out:
        pl.stores[_rel(pl.root, p)] = sorted(set(out))


_PROFILE_LINE = re.compile(r"^(\s+)([^\s:#][^:#]*?)(\s*:\s*)(\S.*)$")


def _profile_lines(text: str) -> list[tuple[int, str, str]]:
    """Рядки секції `cases:` профілів записів: (номер рядка, ключ, новий ключ)."""
    out: list[tuple[int, str, str]] = []
    inside = False
    for i, line in enumerate(text.splitlines()):
        if re.match(r"^cases\s*:\s*$", line):
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.startswith("#"):
            inside = False
        if not inside:
            continue
        m = _PROFILE_LINE.match(line)
        if not m:
            continue
        k = m.group(2).strip().strip("'\"")
        new = _new_key(k)
        if new and new != k:
            out.append((i, k, new))
    return out


def _plan_profiles(pl: Plan, p: Path) -> None:
    if not p.is_file():
        return
    got = _profile_lines(p.read_text(encoding="utf-8"))
    if got:
        pl.stores[_rel(pl.root, p)] = [(k, new) for _, k, new in got]


# ── перенос ──────────────────────────────────────────────────────────────────
def _fresh_locks(pages_root: Path) -> list[str]:
    now = time.time()
    return [p.name for p in pages_root.glob("*/*.lock")
            if now - p.stat().st_mtime < _FRESH_LOCK]


def apply(pl: Plan | None = None) -> dict[str, Any]:
    """Перенести облік: архів → запис → перебудова → самоперевірка → позначка."""
    from dataclasses import asdict

    from nyshporka.core import workspace as W
    from nyshporka.library import LIBRARY_PATH, build_library, write_library

    ws = W.workspace()
    root = ws.root
    locks = _fresh_locks(ws.pages) if ws.pages.is_dir() else []
    if locks:
        raise RekeyError(
            f"у сховище сторінок просто зараз пишуть ({', '.join(locks[:3])}). "
            f"Перенос — коли інші сесії й застосунок зупинено.")
    built = build_library()
    entries = [asdict(e) for e in built]
    if pl is None:
        pl = plan(entries=entries)
    if pl.empty:
        return {"stamp": "", "backup": "", "pages": 0, "stores": {}, "stuck": pl.stuck,
                "unknown_opys": len(pl.unknown), "problems": [], "noop": True}
    before = _census(root, ws.pages)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    home = root / REKEY_DIR / stamp
    home.mkdir(parents=True, exist_ok=True)
    backup = home / "backup.zip"
    from nyshporka.cases.db import DB_PATH

    # Похідні (бібліотека, реєстр) — теж в архів: після відкату вони мусять
    # бути старими, а не перебудованими під нові ключі.
    keep = [*pl.touched, *(_rel(root, p) for p in (ws.marker, LIBRARY_PATH, DB_PATH,
                                                     root / legacy.MOVES) if p.is_file())]
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in keep:
            if (root / rel).is_file():
                z.write(root / rel, rel)
    created: list[str] = []
    journal = {"stamp": stamp, "keys_before": pl.keys_before, "backup": _rel(root, backup),
               "kept": keep, "created": created, "plan": pl.as_dict(), "done": False}
    (home / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    _apply_pages(pl, root, created)
    _apply_dict(root, root / "data" / "spotter" / "case_verdicts.json", inner="verdicts")
    _apply_dict(root, root / "data" / "derived" / "verdicts.json")
    _apply_dict(root, root / "data" / "derived" / "search_log.json")
    _apply_dict(root, ws.share / "cards.json")
    _apply_overrides(root / "data" / "cases" / "overrides.json")
    _apply_queue(root / "data" / "queue" / "queue.json")
    _apply_profiles(ws.config / "records_profiles.yaml")

    mv_path = root / legacy.MOVES
    old_mv = (_read(mv_path).get("moves") or {}) if mv_path.is_file() else {}
    if not mv_path.is_file():
        created.append(_rel(root, mv_path))
    mv_path.parent.mkdir(parents=True, exist_ok=True)
    mv_path.write_text(json.dumps({
        "_comment": ("Старий ключ справи (до 0.22) → новий, з описом. Пише "
                     "`nysh cases rekey --apply`; не правиться руками й не видаляється: "
                     "старі ключі живуть у нотатках і чужих повідомленнях."),
        "made": stamp, "moves": {**pl.moves, **old_mv}},
        ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    legacy.reset()

    write_library(built)
    W.set_keys_version(casekey.KEYS_VERSION)
    from nyshporka.cases import db

    db.build_index()
    after = _census(root, ws.pages)
    problems = verify(before, after)
    journal.update(done=True, census_before=before, census_after=after, problems=problems)
    (home / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return {"stamp": stamp, "backup": _rel(root, backup), "pages": len(pl.pages),
            "stores": {k: len(v) for k, v in pl.stores.items()},
            "stuck": pl.stuck, "unknown_opys": len(pl.unknown),
            "census_before": before, "census_after": after, "problems": problems}


def _merge_case(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Облік однієї справи з двох файлів: аркуші — злиттям нотаток, записи — за rid."""
    from nyshporka.pagestore.models import PageNote
    from nyshporka.pagestore.store import _merge_note

    pages = dict(dst.get("pages") or {})
    for scan, raw in (src.get("pages") or {}).items():
        if scan not in pages:
            pages[scan] = raw
            continue
        merged = _merge_note(PageNote.model_validate(pages[scan]), PageNote.model_validate(raw))
        pages[scan] = merged.model_dump(mode="json")
    recs = {str(r.get("rid")): r for r in (dst.get("records") or []) if isinstance(r, dict)}
    for r in src.get("records") or []:
        if isinstance(r, dict):
            recs.setdefault(str(r.get("rid")), r)
    out = {**src, **dst, "pages": dict(sorted(pages.items())), "records": list(recs.values())}
    return out


def _apply_pages(pl: Plan, root: Path, created: list[str]) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    # Злиття — у порядку плану: кілька старих файлів можуть сходитись в один.
    for m in pl.pages:
        src, dst = root / m.src, root / m.dst
        d = _read(src)
        d["key"] = m.new_key
        ck = casekey.parse(m.new_key)
        if not m.companion and ck is not None and ck.opys_known and not d.get("opys"):
            d["opys"] = ck.opys
        if dst != src and dst.is_file():
            d = _merge_case(_read(dst), d)
            d["key"] = m.new_key
        elif dst != src:
            created.append(m.dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dst, json.dumps(d, ensure_ascii=False, indent=1) + "\n")
        if dst != src:
            src.unlink()


def _merge_value(store: str, a: Any, b: Any) -> Any:
    """Два записи однієї справи в словниковому сховищі → один."""
    if isinstance(a, list) and isinstance(b, list):
        seen, out = set(), []
        for x in [*a, *b]:
            k = json.dumps(x, ensure_ascii=False, sort_keys=True)
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        if store.endswith("case_verdicts.json"):
            # вердикт справи — один; лишається пізніший за датою
            return a if str(a.get("date") or "") >= str(b.get("date") or "") else b
        return {**b, **a}
    return a


def _apply_dict(root: Path, p: Path, *, inner: str = "") -> None:
    from nyshporka.utils.atomic import write_json

    if not p.is_file():
        return
    data = _read(p)
    d = data.get(inner) if inner else data
    if not isinstance(d, dict):
        return
    out: dict[str, Any] = {}
    for k, v in d.items():
        new = k if k.startswith("_") else (_new_key(k) or k)
        out[new] = _merge_value(str(p), out[new], v) if new in out else v
    if inner:
        data[inner] = out
    else:
        data = out
    write_json(p, data, indent=1)


def _apply_overrides(p: Path) -> None:
    from nyshporka.utils.atomic import write_json

    if not p.is_file():
        return
    data = _read(p)
    for v in (data.get("runs") or {}).values():
        k = str((v or {}).get("key") or "")
        if k:
            v["key"] = _new_key(k) or k
    if isinstance(data.get("bundles"), dict):
        data["bundles"] = {(_new_key(k) or k): v for k, v in data["bundles"].items()}
    write_json(p, data, indent=1)
    from nyshporka.cases.resolve import _run_overrides, load_overrides

    load_overrides.cache_clear()
    _run_overrides.cache_clear()


def _apply_queue(p: Path) -> None:
    from nyshporka.utils.atomic import write_json

    if not p.is_file():
        return
    data = _read(p)
    for it in data.get("items") or []:
        ref = it.setdefault("ref", {})
        for holder, field_ in ((it, "id"), (ref, "key")):
            k = str(holder.get(field_) or "")
            if k and "/" in k and casekey.is_legacy(k):
                holder[field_] = _new_key(k) or k
        ref.pop("aka", None)
    write_json(p, data, indent=1)


def _apply_profiles(p: Path) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for i, k, new in _profile_lines(text):
        lines[i] = lines[i].replace(k, new, 1)
    atomic_write_text(p, "".join(lines))


# ── самоперевірка й відкат ───────────────────────────────────────────────────
def _census(root: Path, pages_root: Path) -> dict[str, Any]:
    """Скільки людської праці лежить у сховищах — до і після переносу."""
    out: dict[str, Any] = {"pages_files": 0, "page_notes": 0, "records": 0,
                           "legacy_page_keys": 0}
    if pages_root.is_dir():
        for f in pages_root.glob("*/*.json"):
            if _companion(f.name):
                continue
            try:
                d = _read(f)
            except (OSError, ValueError):
                continue
            out["pages_files"] += 1
            out["page_notes"] += len(d.get("pages") or {})
            out["records"] += len(d.get("records") or [])
            out["legacy_page_keys"] += int(casekey.parse(d.get("key")) is None)
    for name, p, inner in (
            ("case_verdicts", root / "data" / "spotter" / "case_verdicts.json", "verdicts"),
            ("line_verdicts", root / "data" / "derived" / "verdicts.json", ""),
            ("search_log", root / "data" / "derived" / "search_log.json", ""),
            ("bindings", root / "data" / "cases" / "overrides.json", "runs")):
        if not p.is_file():
            continue
        d = _read(p)
        d = d.get(inner) if inner else d
        if isinstance(d, dict):
            items = [k for k in d if not k.startswith("_")]
            out[name] = len(items)
            if name == "line_verdicts":
                out["line_verdicts_items"] = sum(len(v) for v in d.values()
                                                 if isinstance(v, dict))
    return out


def verify(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Що в переносі пішло не так. Порожньо — облік цілий.

    Людська праця не губиться: нотаток аркушів і записів після переносу не
    менше, ніж до (злиття двох файлів однієї справи дає не менше нотаток,
    ніж у більшому з них). Старих ключів у сховищі сторінок не лишається.
    """
    problems: list[str] = []
    for k in ("page_notes", "records", "line_verdicts_items"):
        if after.get(k, 0) < before.get(k, 0):
            problems.append(f"{k}: було {before.get(k)}, стало {after.get(k)}")
    if after.get("legacy_page_keys"):
        problems.append(f"у сховищі сторінок лишились старі ключі: "
                        f"{after['legacy_page_keys']}")
    return problems


def rollback(stamp: str | None = None) -> dict[str, Any]:
    """Повернути простір до стану перед переносом `stamp` (останнім, якщо не названо)."""
    from nyshporka.core import workspace as W

    ws = W.workspace()
    root = ws.root
    base = root / REKEY_DIR
    homes = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    if stamp:
        homes = [p for p in homes if p.name == stamp]
    if not homes:
        raise RekeyError(f"переносу {stamp or ''} для відкату немає ({_rel(root, base)})")
    home = homes[-1]
    journal = _read(home / "journal.json")
    for rel in journal.get("created") or []:
        p = root / rel
        if p.is_file():
            p.unlink()
    with zipfile.ZipFile(home / "backup.zip") as z:
        for name in z.namelist():
            dst = root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
    W.reset()
    legacy.reset()
    journal["rolled_back"] = datetime.now(UTC).isoformat(timespec="seconds")
    (home / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return {"stamp": home.name, "restored": len(journal.get("kept") or []),
            "removed": len(journal.get("created") or [])}


def report(pl: Plan) -> str:
    """План людською мовою — для `nysh cases rekey` без `--apply`."""
    buf = io.StringIO()
    w = buf.write
    if pl.empty:
        w("Простір уже на ключах з описом; переносити нічого.\n")
        return buf.getvalue()
    w(f"Ключі простору: версія {pl.keys_before} → {casekey.KEYS_VERSION}.\n")
    w(f"Карта переїзду: {len(pl.moves)} старих ключів.\n")
    merges = [m for m in pl.pages if m.merge]
    w(f"Сховище сторінок: {len(pl.pages)} файлів"
      + (f", з них {len(merges)} зливаються з наявним обліком" if merges else "") + ".\n")
    for m in pl.pages[:10]:
        w(f"  {m.src} → {m.dst}{'  (злиття)' if m.merge else ''}\n")
    if len(pl.pages) > 10:
        w(f"  … і ще {len(pl.pages) - 10}\n")
    for store, items in sorted(pl.stores.items()):
        w(f"{store}: {len(items)} ключів\n")
        for old, new in items[:3]:
            w(f"  {old} → {new}\n")
    if pl.shared:
        w(f"⚠ Старі ключі, під якими лежало кілька справ ({len(pl.shared)}): облік "
          f"під ними йде ПЕРШІЙ, як і до 0.22.\n")
        for k, v in list(pl.shared.items())[:5]:
            w(f"  {k}: {', '.join(v)}\n")
    if pl.stuck:
        w(f"⚠ Не переводиться ({sum(len(v) for v in pl.stuck.values())}) — лишиться як є:\n")
        for store, keys in sorted(pl.stuck.items()):
            w(f"  {store}: {', '.join(keys[:5])}{' …' if len(keys) > 5 else ''}\n")
    if pl.unknown:
        w(f"Справ без опису (ключ з «_»): {len(pl.unknown)} — переїдуть так; опис "
          f"дописується в паспорт, і наступний `rekey --apply` перенесе їхній облік.\n")
    w("Перенести: nysh cases rekey --apply (архів для відкату — data/cases/rekey/).\n")
    return buf.getvalue()
