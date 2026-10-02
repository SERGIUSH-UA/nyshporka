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

import hashlib
import io
import json
import re
import shutil
import time
import zipfile
from collections.abc import Sequence
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
    #: кілька записаних ключів сходяться в один: файл → [«a + b → c»]
    joined: dict[str, list[str]] = field(default_factory=dict)
    #: файл обліку називає опис, якого справа в бібліотеці не має
    opys_hint: list[str] = field(default_factory=list)
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
            "joined": {k: v for k, v in sorted(self.joined.items())},
            "opys_hint": self.opys_hint,
            "unknown_opys": self.unknown,
        }


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _read(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _read_store(p: Path) -> Any:
    """Сховище для плану: битий файл — зрозуміла відмова, а не трасування."""
    try:
        return _read(p)
    except (OSError, ValueError) as exc:
        raise RekeyError(f"{p}: не читається ({exc}). Перенос не почато — полагодьте "
                         f"файл і повторіть.") from None


#: Карта, за якою перекладає цей перенос (`plan` ставить її перед обходом).
_MOVES: dict[str, str] = {}
#: (архів, фонд, справа) → ключ, якщо справа з невідомим описом його дістала:
#: у бібліотеці тепер рівно одна справа з цим номером, і опис у неї відомий.
_UPGRADE: dict[tuple[str, str, str], str] = {}


def _upgrades(entries: list[dict[str, Any]],
              extra: Sequence[str] = ()) -> dict[tuple[str, str, str], str]:
    """Ключі з `_`, яким паспорт уже дописав опис.

    🔴 Лише однозначне: справа з таким номером у бібліотеці одна, і справи з
    невідомим описом поруч не лишилось. Інакше `_` — це досі окрема справа.
    """
    groups: dict[tuple[str, str, str], list[casekey.CaseKey]] = {}
    for k in [*(e.get("key") for e in entries), *extra]:
        ck = casekey.parse(k)
        if ck is not None:
            # і збірки: `ANRM/211/@x`, записана до 0.22 без опису, — це та сама
            # збірка, що тепер `ANRM/211/11/@x`, коли інших з цією назвою нема
            groups.setdefault((ck.repo, ck.fond, ck.spr), []).append(ck)
    out: dict[tuple[str, str, str], str] = {}
    for rfs, cks in groups.items():
        keys = {c.key for c in cks}
        if len(keys) == 1 and all(c.opys_known for c in cks):
            out[rfs] = keys.pop()
    return out


def _bundle_keys(p: Path) -> list[str]:
    """Збірки простору (їх тримає `overrides.json`, не бібліотека) — новими ключами."""
    if not p.is_file():
        return []
    out = []
    for k in (_read_store(p).get("bundles") or {}):
        new = legacy.current_key(str(k))
        if casekey.parse(new) is not None:
            out.append(new)
    return out


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
    return _lift(got) if casekey.parse(got) is not None else None


def _lift(key: str) -> str:
    """Ключ з `_` → ключ з описом, якщо паспорт його вже дав (`_UPGRADE`)."""
    ck = casekey.parse(key)
    if ck is None or ck.opys_known:
        return key
    return _UPGRADE.get((ck.repo, ck.fond, ck.spr), key)


def _fresh_library() -> list[Any]:
    """Бібліотека з поточних паспортів: перенос мусить бачити щойно дописаний опис.

    Розбір паспорта кешується на процес (`library._sidecar_case`), і без скидання
    довгоживучий процес (застосунок) переносив би за паспортом, яким той був.
    """
    from nyshporka.library import _sidecar_case, _sidecar_village, build_library

    _sidecar_case.cache_clear()
    _sidecar_village.cache_clear()
    return build_library()


# ── план ─────────────────────────────────────────────────────────────────────
def plan(*, entries: list[dict[str, Any]] | None = None) -> Plan:
    """Що зміниться при переносі. Нічого не пише.

    `entries` — записи бібліотеки, зібраної новим кодом; без них бібліотека
    збирається тут (повний обхід диска, як `nysh cases build --rescan`).
    """
    from dataclasses import asdict

    from nyshporka.core.workspace import workspace

    ws = workspace()
    root = ws.root
    if entries is None:
        entries = [asdict(e) for e in _fresh_library()]
    moves, shared = legacy.moves_from_entries(entries, legacy.registry_set(root))
    _UPGRADE.clear()
    _UPGRADE.update(_upgrades(entries, _bundle_keys(root / "data" / "cases" / "overrides.json")))
    # Записана раніше карта (попередній перенос) — головна: на ній уже стоять
    # перенесені записи, і нова збірка бібліотеки її не переписує. Виняток —
    # ціль `_`, якій паспорт відтоді дав опис: вона піднімається, і сам
    # `_`-ключ теж іде в карту.
    f = root / legacy.MOVES
    live = {str(e.get("key")) for e in entries if e.get("key")}
    for old, was in ((_read(f).get("moves") or {}) if f.is_file() else {}).items():
        if old in live:
            # Ключ, з якого справа колись переїхала, знову належить живій справі
            # (з'явилась справжня книга того опису) — її облік лишається її.
            moves.pop(old, None)
            continue
        now = _lift(was)
        moves[old] = now
        if now != was:
            moves[was] = now
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
        said = casekey.norm_part(d.get("opys")) if d.get("opys") else ""
        if not kind and said and said != ck.opys and not ck.bundle:
            pl.opys_hint.append(f"{_rel(pl.root, f)}: файл називає опис {said}, а справа "
                                f"переїжджає як {new}")
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
    data = _read_store(p)
    d = data.get(inner) if inner else data
    if not isinstance(d, dict):
        return
    out: list[tuple[str, str]] = []
    into: dict[str, list[str]] = {}
    for k in d:
        if k.startswith("_"):
            continue
        new = _new_key(k)
        if new is None:
            pl.stuck.setdefault(_rel(pl.root, p), []).append(k)
            continue
        into.setdefault(new, []).append(k)
        if new != k:
            out.append((k, new))
            pl.moves.setdefault(k, new)
    if out:
        pl.stores[_rel(pl.root, p)] = out
    how = ("чинний — пізніший за датою, інший лягає поруч у `superseded`"
           if inner == "verdicts" else "зливаються")
    for new, olds in into.items():
        if len(olds) > 1:
            pl.joined.setdefault(_rel(pl.root, p), []).append(
                f"{' + '.join(olds)} → {new} ({how})")


def _plan_overrides(pl: Plan, p: Path) -> None:
    if not p.is_file():
        return
    data = _read_store(p)
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
    data = _read_store(p)
    for it in data.get("items") or []:
        ref = it.get("ref") or {}
        for k in (str(it.get("id") or ""), str(ref.get("key") or "")):
            new = _queue_key(k)
            if new != k:
                out.append((k, new))
        if "aka" in ref:
            out.append((f"ref.aka {ref['aka']}", "прибирається"))
    for item_id in _queue_dups(data):
        pl.stuck.setdefault(_rel(pl.root, p), []).append(
            f"{item_id}: у черзі двічі — лишиться перший")
    if out:
        pl.stores[_rel(pl.root, p)] = sorted(set(out))


def _queue_key(k: str) -> str:
    """Ключ справи в черзі після переносу. Не ключ (тека, хвіст теки) — як є."""
    if not k or "/" not in k or (casekey.parse(k) is None and not casekey.is_legacy(k)):
        return k
    return _new_key(k) or k


def _queue_id(it: dict[str, Any]) -> str:
    return _queue_key(str(it.get("id") or ""))


def _queue_dups(data: dict[str, Any]) -> list[str]:
    """Ідентифікатори черги, що після переносу зійдуться (старий і новий ключ)."""
    seen: set[str] = set()
    dups: list[str] = []
    for it in data.get("items") or []:
        k = _queue_id(it)
        if k and k in seen:
            dups.append(k)
        seen.add(k)
    return dups


_PROFILE_LINE = re.compile(r"^(\s+)([^\s:#][^:#]*?)(\s*:\s*)(\S.*)$")


def _profile_lines(text: str) -> list[tuple[int, str, str]]:
    """Рядки секції `cases:` профілів записів: (номер рядка, ключ, новий ключ).

    Новий ключ, що вже стоїть у секції (або двоє старих сходяться в один), —
    поза списком: YAML із двома однаковими ключами тихо бере останній.
    Такі рядки лишаються як є, і план показує їх як непереведені.
    """
    got = _profile_all(text)
    have = {k for _, k, _ in got}
    out: list[tuple[int, str, str]] = []
    taken: set[str] = set()
    for i, k, new in got:
        if new == k:
            continue
        if new in have or new in taken:
            continue
        taken.add(new)
        out.append((i, k, new))
    return out


def _profile_clashes(text: str) -> list[str]:
    ok = {i for i, _, _ in _profile_lines(text)}
    return [f"{k}: «{new}» уже є в секції" for i, k, new in _profile_all(text)
            if new != k and i not in ok]


def _profile_all(text: str) -> list[tuple[int, str, str]]:
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
        if new:
            out.append((i, k, new))
    return out


def _plan_profiles(pl: Plan, p: Path) -> None:
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8")
    got = _profile_lines(text)
    if got:
        pl.stores[_rel(pl.root, p)] = [(k, new) for _, k, new in got]
    for clash in _profile_clashes(text):
        pl.stuck.setdefault(_rel(pl.root, p), []).append(clash)


# ── перенос ──────────────────────────────────────────────────────────────────
def _fresh_locks(pages_root: Path) -> list[str]:
    """Свіжі локи сховищ, які перенос переписує: хтось пише просто зараз."""
    from nyshporka.core.workspace import workspace

    data = workspace().data
    now = time.time()
    found = [*pages_root.glob("*/*.lock")] if pages_root.is_dir() else []
    for sub in ("derived", "spotter", "share", "cases", "queue"):
        if (data / sub).is_dir():
            found += (data / sub).glob("*.lock")
    return [p.name for p in found if now - p.stat().st_mtime < _FRESH_LOCK]


def apply(pl: Plan | None = None) -> dict[str, Any]:
    """Перенести облік: архів → запис → перебудова → самоперевірка → позначка."""
    from dataclasses import asdict

    from nyshporka.core import workspace as W
    from nyshporka.library import LIBRARY_PATH, write_library

    ws = W.workspace()
    root = ws.root
    _refuse_busy(ws.pages)
    built = _fresh_library()
    entries = [asdict(e) for e in built]
    if pl is None:
        pl = plan(entries=entries)
    if pl.empty:
        return {"stamp": "", "backup": "", "pages": 0, "stores": {}, "stuck": pl.stuck,
                "unknown_opys": len(pl.unknown), "problems": [], "noop": True}
    pages_rel = _rel(root, ws.pages) + "/" if ws.pages.is_relative_to(root) else ""
    blocked = {k: v for k, v in pl.stuck.items() if pages_rel and k.startswith(pages_rel)}
    if blocked:
        # 🔴 Після переносу старі імена файлів сторінок ніхто не читає, тож
        # файл, який перенос не перевів, — це облік, що зникає з виду.
        lines = "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(blocked.items())[:5])
        raise RekeyError(
            f"файлів сховища сторінок, яких перенос не переведе: {len(blocked)} ({lines}). "
            f"Після переносу їх ніхто не читатиме — спершу розберіть їх руками "
            f"(злийте з файлом, що вже є, чи виправте ключ), потім повторіть.")
    before = _census(root, ws.pages)
    home = _new_home(root)
    stamp = home.name
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
    mv_path = root / legacy.MOVES
    # Що перенос створить — відомо до запису, і в журналі воно лежить ДО
    # першого записаного файла: збій посередині інакше лишав би нові файли,
    # про які відкат не знає, поруч зі старими з архіву.
    created = sorted({m.dst for m in pl.pages if not (root / m.dst).is_file()}
                     | {_rel(root, p) for p in (mv_path, LIBRARY_PATH, DB_PATH)
                        if not p.is_file() and p.is_relative_to(root)})
    journal: dict[str, Any] = {
        "stamp": stamp, "keys_before": pl.keys_before, "backup": _rel(root, backup),
        "kept": keep, "created": created, "plan": pl.as_dict(), "done": False}
    _write_journal(home, journal)

    try:
        overlap = _apply_pages(pl, root)
        _apply_dict(root, root / "data" / "spotter" / "case_verdicts.json", inner="verdicts")
        _apply_dict(root, root / "data" / "derived" / "verdicts.json")
        _apply_dict(root, root / "data" / "derived" / "search_log.json")
        _apply_dict(root, ws.share / "cards.json")
        _apply_overrides(root / "data" / "cases" / "overrides.json")
        _apply_queue(root / "data" / "queue" / "queue.json")
        _apply_profiles(ws.config / "records_profiles.yaml")
        legacy.record_moves(root, pl.moves, made=stamp)
        write_library(built)
        W.set_keys_version(casekey.KEYS_VERSION)
    except Exception as exc:
        journal["failed"] = f"{type(exc).__name__}: {exc}"
        _write_journal(home, journal)
        try:
            rollback(stamp, force=True)
        except Exception as again:
            raise RekeyError(
                f"перенос зупинився на півдорозі ({exc}), і відкат теж не вдався "
                f"({again}). Нічого не пишіть у простір; повторіть відкат: "
                f"nysh cases rekey --rollback --stamp {stamp}") from exc
        raise RekeyError(f"перенос зупинився на півдорозі ({exc}); простір повернуто "
                         f"як був (архів {_rel(root, backup)}).") from exc
    from nyshporka.cases import db

    db.build_index()
    after = _census(root, ws.pages)
    problems = verify(before, after, overlap)
    written = sorted({m.dst for m in pl.pages} | set(pl.stores) | {_rel(root, mv_path)})
    journal.update(done=True, done_at=time.time(), census_before=before,
                   census_after=after, overlap=overlap, problems=problems,
                   written={rel: _sha(root / rel) for rel in written})
    _write_journal(home, journal)
    return {"stamp": stamp, "backup": _rel(root, backup), "pages": len(pl.pages),
            "stores": {k: len(v) for k, v in pl.stores.items()},
            "stuck": pl.stuck, "unknown_opys": len(pl.unknown),
            "census_before": before, "census_after": after, "problems": problems}


def _refuse_busy(pages_root: Path) -> None:
    locks = _fresh_locks(pages_root)
    if locks:
        raise RekeyError(
            f"у сховища обліку просто зараз пишуть ({', '.join(locks[:3])}). "
            f"Перенос і відкат — коли інші сесії й застосунок зупинено.")


def _new_home(root: Path) -> Path:
    """Тека цього переносу. Своя навіть для двох переносів в одну мить.

    🔴 Два переноси в одну секунду ділили теку, і архів другого затирав архів
    першого — тобто єдину копію простору до 0.22.
    """
    base = root / REKEY_DIR
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for n in range(100):
        home = base / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            home.mkdir()
            return home
        except FileExistsError:
            continue
    raise RekeyError(f"не вдалось завести теку переносу в {_rel(root, base)}")


def _write_journal(home: Path, journal: dict[str, Any]) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(home / "journal.json", json.dumps(journal, ensure_ascii=False, indent=1))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def _rid(r: dict[str, Any]) -> str:
    """Тотожність запису: `rid`, а без нього — увесь запис (не губити безіменні)."""
    rid = r.get("rid")
    return f"rid:{rid}" if rid else json.dumps(r, ensure_ascii=False, sort_keys=True)


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
    recs = {_rid(r): r for r in (dst.get("records") or []) if isinstance(r, dict)}
    for r in src.get("records") or []:
        if isinstance(r, dict):
            recs.setdefault(_rid(r), r)
    out = {**src, **dst, "pages": dict(sorted(pages.items())), "records": list(recs.values())}
    return out


def _apply_pages(pl: Plan, root: Path) -> dict[str, int]:
    """Перенести файли сторінок. Вертає, скільки аркушів і записів злилось у спільні.

    Аркуш, що лежав в обох файлах однієї справи, після злиття — один (нотатки
    зведено), тож самоперевірка рахує «не менше, ніж до» за вирахуванням цих.
    """
    from nyshporka.utils.atomic import atomic_write_text

    overlap = {"page_notes": 0, "records": 0}
    # Злиття — у порядку плану: кілька старих файлів можуть сходитись в один.
    for m in pl.pages:
        src, dst = root / m.src, root / m.dst
        d = _read(src)
        d["key"] = m.new_key
        ck = casekey.parse(m.new_key)
        if not m.companion and ck is not None and ck.opys_known and not d.get("opys"):
            d["opys"] = ck.opys
        if dst != src and dst.is_file():
            cur = _read(dst)
            overlap["page_notes"] += len(set(cur.get("pages") or {}) & set(d.get("pages") or {}))
            overlap["records"] += len(
                {_rid(r) for r in cur.get("records") or [] if isinstance(r, dict)}
                & {_rid(r) for r in d.get("records") or [] if isinstance(r, dict)})
            d = _merge_case(cur, d)
            d["key"] = m.new_key
        dst.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dst, json.dumps(d, ensure_ascii=False, indent=1) + "\n")
        if dst != src:
            src.unlink()
    return overlap


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
            # Вердикт справи — один: чинним лишається пізніший за датою, а
            # інший не зникає — лягає поруч (`superseded`), бо це теж рішення людини.
            win, lose = (a, b) if str(a.get("date") or "") >= str(b.get("date") or "") \
                else (b, a)
            if win == lose:
                return win
            prev = [x for x in (win.get("superseded") or []) if isinstance(x, dict)]
            lost = {k: v for k, v in lose.items() if k != "superseded"}
            return {**win, "superseded": [*prev, lost, *(lose.get("superseded") or [])]}
        both = {**b, **a}
        for k in a.keys() & b.keys():
            if isinstance(a[k], (list, dict)) and isinstance(b[k], type(a[k])):
                both[k] = _merge_value(store, a[k], b[k])
        return both
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
        out: dict[str, Any] = {}
        for k, v in data["bundles"].items():
            new = _new_key(k) or k
            out[new] = _merge_value(str(p), out[new], v) if new in out else v
        data["bundles"] = out
    write_json(p, data, indent=1)
    from nyshporka.cases.resolve import _run_overrides, load_overrides

    load_overrides.cache_clear()
    _run_overrides.cache_clear()


def _apply_queue(p: Path) -> None:
    from nyshporka.utils.atomic import write_json

    if not p.is_file():
        return
    data = _read(p)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in data.get("items") or []:
        ref = it.setdefault("ref", {})
        for holder, field_ in ((it, "id"), (ref, "key")):
            k = str(holder.get(field_) or "")
            if k:
                holder[field_] = _queue_key(k)
        ref.pop("aka", None)
        k = str(it.get("id") or "")
        if k and k in seen:
            continue        # той самий елемент під старим і новим ключем — план це назвав
        seen.add(k)
        items.append(it)
    data["items"] = items
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


def verify(before: dict[str, Any], after: dict[str, Any],
           overlap: dict[str, int] | None = None) -> list[str]:
    """Що в переносі пішло не так. Порожньо — облік цілий.

    Людська праця не губиться: нотаток аркушів і записів після переносу стільки
    ж, скільки до, мінус ті, що лежали в ОБОХ файлах однієї справи й злились у
    одну (`overlap` — їх рахує сам перенос). Старих ключів у сховищі сторінок
    не лишається.
    """
    problems: list[str] = []
    overlap = overlap or {}
    for k in ("page_notes", "records", "line_verdicts_items"):
        want = before.get(k, 0) - overlap.get(k, 0)
        if after.get(k, 0) < want:
            problems.append(f"{k}: було {before.get(k)}, злилось {overlap.get(k, 0)}, "
                            f"стало {after.get(k)}")
    if after.get("legacy_page_keys"):
        problems.append(f"у сховищі сторінок лишились старі ключі: "
                        f"{after['legacy_page_keys']}")
    return problems


def _changed_since(root: Path, pages_root: Path, journal: dict[str, Any]) -> list[str]:
    """Файли, змінені після переносу: їх відкат затер би чи лишив без пари."""
    if not journal.get("done"):
        return []
    out = [rel for rel, sha in (journal.get("written") or {}).items()
           if _sha(root / rel) != sha]
    done_at = float(journal.get("done_at") or 0)
    known = set(journal.get("written") or {})
    if done_at and pages_root.is_dir():
        out += [_rel(root, f) for f in pages_root.glob("*/*.json")
                if _rel(root, f) not in known and f.stat().st_mtime > done_at]
    return sorted(out)


def rollback(stamp: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Повернути простір до стану перед переносом `stamp` (останнім чинним, якщо не названо).

    🔴 Відкат повертає файли з архіву, тож усе, що записано ПІСЛЯ переносу, він
    затирає. Тому: відкочений перенос удруге не відкочується; давніший — лише
    після пізніших; а коли файли переносу відтоді змінювались, відкат
    відмовляє з переліком (`force` — свідомо затерти).
    """
    from nyshporka.core import workspace as W

    ws = W.workspace()
    root = ws.root
    base = root / REKEY_DIR
    homes = sorted(p for p in base.iterdir()
                   if p.is_dir() and (p / "journal.json").is_file()) if base.is_dir() else []
    journals = {p.name: _read(p / "journal.json") for p in homes}
    active = [p for p in homes if not journals[p.name].get("rolled_back")]
    if stamp:
        pick = [p for p in homes if p.name == stamp]
        if not pick:
            raise RekeyError(f"переносу {stamp} для відкату немає ({_rel(root, base)})")
        home = pick[0]
        if journals[stamp].get("rolled_back"):
            raise RekeyError(f"перенос {stamp} уже відкочено "
                             f"({journals[stamp]['rolled_back']})")
        later = [p.name for p in active if p.name > stamp]
        if later:
            raise RekeyError(f"після {stamp} були ще переноси ({', '.join(later)}) — "
                             f"спершу відкотіть їх")
    elif active:
        home = active[-1]
    else:
        raise RekeyError(f"переносу для відкату немає ({_rel(root, base)})")
    journal = journals[home.name]
    if not force:
        _refuse_busy(ws.pages)
        changed = _changed_since(root, ws.pages, journal)
        if changed:
            shown = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")
            raise RekeyError(
                f"після переносу {home.name} змінено файлів: {len(changed)} ({shown}). "
                f"Відкат затре цю роботу. Свідомо — `--rollback --force`.")
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
    W.refresh_keys()
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
    if pl.keys_before < casekey.KEYS_VERSION:
        w(f"Ключі простору: версія {pl.keys_before} → {casekey.KEYS_VERSION}.\n")
    w(f"Карта переїзду: {len(pl.moves)} старих ключів.\n")
    merges = [m for m in pl.pages if m.merge]
    w(f"Сховище сторінок: {len(pl.pages)} файлів"
      + (f", з них {len(merges)} зливаються з наявним обліком" if merges else "") + ".\n")
    for m in pl.pages[:10]:
        where = f"{m.src} → {m.dst}" if m.src != m.dst else m.src
        w(f"  {where}  ({m.old_key or '—'} → {m.new_key}){'  злиття' if m.merge else ''}\n")
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
    for store, lines in sorted(pl.joined.items()):
        what = ("вердикти однієї справи" if store.endswith("case_verdicts.json")
                else "записи однієї справи")
        w(f"⚠ {store}: {what} під кількома ключами зливаються в один ({len(lines)}):\n")
        for line in lines[:5]:
            w(f"  {line}\n")
    if pl.opys_hint:
        w(f"⚠ Файли обліку називають опис, якого справа не має ({len(pl.opys_hint)}). "
          f"Якщо опис правильний — допишіть його в паспорт теки, і наступний "
          f"`rekey --apply` перенесе облік:\n")
        for line in pl.opys_hint[:5]:
            w(f"  {line}\n")
    if pl.unknown:
        w(f"Справ без опису (ключ з «_»): {len(pl.unknown)} — переїдуть так; опис "
          f"дописується в паспорт, і наступний `rekey --apply` перенесе їхній облік.\n")
    w("Перенести: nysh cases rekey --apply (архів для відкату — data/cases/rekey/).\n")
    return buf.getvalue()
