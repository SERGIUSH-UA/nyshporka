"""Розкласти збірну теку на справи: `nysh cases split`.

Збірна тека — кадри кількох справ під одним іменем (`cases.span`). Межі справ
машина не вгадує: людина називає їх іменами файлів «від..до», а розбивка
робить із однієї теки кілька справжніх справ — кожна зі своєю текою, паспортом,
прогонами й нотатками сховища сторінок.

🔴 Нічого не видаляється й не переміщується. Частини — жорсткі посилання на ті
самі файли кадрів під тими самими іменами; стара тека й старий прогін
лишаються на диску з позначками (`split_into` у паспорті, `superseded` у меті
прогону), за якими їх перестають рахувати справою й шукати в них двічі.

Операція не атомарна — теки, паспорти, прогони, сховище сторінок, — тож кожен
крок ідемпотентний, а `_split.json` у старій теці тримає карту: повторний
запуск після обриву доробляє те саме, `undo` знімає зроблене.
"""
from __future__ import annotations

import contextlib
import filecmp
import glob
import json
import os
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

JOURNAL = "_split.json"
#: «Лишити поза справами» в карті: обкладинки плівки, чужі аркуші.
LEFTOVER = "-"
#: Поля мети прогону, що описують прогін цілком і для частини були б неправдою.
_RUN_AGGREGATES = ("stages_total", "stages_pages", "geom_lost_pages", "missing",
                   "superseded")
#: Походження кадрів, яке частина успадковує від старої теки.
_PROVENANCE = ("fetched", "fetched_by", "fetched_from", "fetched_ref", "fetched_url",
               "film", "dgs")
_PAGE_FILES = (".txt", ".lines.json")


class SplitError(RuntimeError):
    """Розкласти не можна — з причиною для людини."""


@dataclass
class Part:
    spr: str                   # номер справи або `LEFTOVER`
    first: str
    last: str
    names: list[str]           # імена файлів кадрів частини, у порядку теки
    pos: tuple[int, int]       # позиції першого й останнього кадру, з одиниці
    shifra: str = ""
    key: str = ""
    dir: Path | None = None
    runs: dict[str, str] = field(default_factory=dict)   # старий прогін → новий
    notes: int = 0             # нотаток сховища сторінок, що перейдуть
    title: str = ""
    years: tuple[int | None, int | None] = (None, None)

    @property
    def leftover(self) -> bool:
        return self.spr == LEFTOVER

    def as_json(self, root: Path) -> dict[str, Any]:
        return {"spr": self.spr, "shifra": self.shifra, "key": self.key,
                "first": self.first, "last": self.last, "frames": len(self.names),
                "from": self.pos[0], "to": self.pos[1],
                "dir": _rel(self.dir, root) if self.dir else "",
                "runs": dict(self.runs), "notes": self.notes, "title": self.title}


@dataclass
class Plan:
    case_dir: Path             # тека з паспортом
    frames_dir: Path           # де самі кадри
    names: list[str]
    parts: list[Part]
    old_key: str
    runs: list[str]            # прогони старої теки (разом із голосами)
    warnings: list[tuple[str, str]] = field(default_factory=list)

    def as_json(self, root: Path) -> dict[str, Any]:
        return {"case_dir": _rel(self.case_dir, root), "frames": len(self.names),
                "old_key": self.old_key, "runs": list(self.runs),
                "parts": [p.as_json(root) for p in self.parts]}


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _write_json(path: Path, data: Any) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# ── карта ────────────────────────────────────────────────────────────────────
def parse_part(spec: str) -> tuple[str, str, str]:
    """`"926=0001.jpg..0120.jpg"` → `("926", "0001.jpg", "0120.jpg")`."""
    what, sep, span = str(spec).partition("=")
    first, dots, last = span.partition("..")
    what, first, last = what.strip(), first.strip(), last.strip()
    if not (sep and dots and what and first and last):
        raise SplitError(
            f"частина «{spec}»: чекаю «<справа>=<перший файл>..<останній файл>», "
            f"напр. «926=0001.jpg..0120.jpg»; кадри поза справами — «-=…»")
    return what, first, last


def load_map(path: str | Path) -> list[tuple[str, str, str]]:
    """Карта з файла JSON: `[{"spr": "926", "first": "…", "last": "…"}, …]`."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SplitError(f"карту «{path}» не прочитано: {exc}") from None
    if not isinstance(raw, list):
        raise SplitError(f"карта «{path}» мусить бути списком частин")
    out = []
    for row in raw:
        if not isinstance(row, dict):
            raise SplitError(f"карта «{path}»: частина мусить бути об'єктом — {row!r}")
        what = str(row.get("spr") or row.get("shifra") or "").strip()
        first, last = str(row.get("first") or "").strip(), str(row.get("last") or "").strip()
        if not (what and first and last):
            raise SplitError(f"карта «{path}»: у частині бракує spr, first або last — {row!r}")
        out.append((what, first, last))
    return out


def _base_shifra(meta: dict[str, Any]) -> Any:
    from nyshporka.cases import register as REG

    text = str(meta.get("shifra") or "").strip()
    if not text:
        return None
    try:
        return REG.parse_shifra(text, repo_hint=str(meta.get("repo") or ""))
    except REG.RegisterError:
        return None


def _shifra_of(what: str, base: Any) -> Any:
    """Шифра частини: повна, як її написано, або номер справи в тому самому описі."""
    from nyshporka.cases import register as REG

    if any(ch in what for ch in " -–/"):
        try:
            return REG.parse_shifra(what, repo_hint=base.repo if base else "")
        except REG.RegisterError as exc:
            raise SplitError(f"частина «{what}»: {exc}") from None
    if base is None:
        raise SplitError(
            f"частину названо номером «{what}», а в паспорті теки шифри немає — "
            f"звідки взяти архів, фонд і опис, невідомо. Назвіть шифру повністю: "
            f"«РДІА 592-25-{what}=…»")
    return replace(base, spr=what.lstrip("0") or "0")


def plan(case_dir: str | Path, specs: list[tuple[str, str, str]]) -> Plan:
    """Що станеться, якщо розкласти теку за цією картою. Нічого не пише."""
    from nyshporka import htr_store as S
    from nyshporka import library as L
    from nyshporka.cases import take
    from nyshporka.cases.chain import sidecar_of
    from nyshporka.cases.register import case_path
    from nyshporka.cloud.verify import voice_dirs
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.runname import run_name
    from nyshporka.share import align

    d = case_path(case_dir)
    if not d.is_dir():
        raise SplitError(f"теки немає: {d}")
    frames_dir = align._frames_dir(d)
    if frames_dir is None:
        raise SplitError(f"у теці {d} немає кадрів")
    names = [p.name for p in align.frames_sorted(frames_dir)]
    if not specs:
        raise SplitError("карти немає: назвіть частини — --part "
                         "«<справа>=<перший файл>..<останній файл>» або --map <файл>")
    _, meta = sidecar_of(d)
    base = _base_shifra(meta)
    pos = {n: i for i, n in enumerate(names)}
    taken: dict[str, str] = {}
    parts: list[Part] = []
    for what, first, last in specs:
        for name in (first, last):
            if name not in pos:
                raise SplitError(f"частина «{what}»: файла «{name}» у теці немає")
        a, b = pos[first], pos[last]
        if a > b:
            raise SplitError(f"частина «{what}»: «{first}» стоїть після «{last}»")
        mine = names[a:b + 1]
        for name in mine:
            if name in taken:
                raise SplitError(f"кадр «{name}» потрапив у дві частини: "
                                 f"«{taken[name]}» і «{what}»")
            taken[name] = what
        part = Part(spr=what if what != LEFTOVER else LEFTOVER, first=first, last=last,
                    names=mine, pos=(a + 1, b + 1))
        if not part.leftover:
            sh = _shifra_of(what, base)
            part.spr = sh.spr
            part.shifra = sh.as_text()
            part.key = str(L._mk_key(sh.repo, sh.fond, sh.spr, sh.opys) or "")
            part.dir = take.case_dir_for(sh.repo, sh.fond, sh.spr, "", sh.opys or "")
        parts.append(part)

    free = [n for n in names if n not in taken]
    if free:
        raise SplitError(
            f"карта не покриває {len(free)} кадрів: від «{free[0]}» до «{free[-1]}». "
            f"Кожен кадр мусить належати частині; ті, що поза справами, назвіть "
            f"явно: --part «-={free[0]}..{free[-1]}»")
    real = [p for p in parts if not p.leftover]
    if len(real) < 2:
        raise SplitError("у карті менше двох справ — розкладати нічого. Якщо тека "
                         "— одна справа: nysh case <тека> --one-case")
    keys = [p.key for p in real]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise SplitError(f"справу названо двічі: {', '.join(twice)} — кадри однієї "
                         f"справи мають іти одним відтинком")
    for p in real:
        assert p.dir is not None
        if p.dir.resolve() in (d.resolve(), frames_dir.resolve()):
            raise SplitError(f"частина «{p.spr}» лягла б у ту саму теку, що розкладається")

    root = workspace().root
    out = Plan(case_dir=d, frames_dir=frames_dir, names=names, parts=parts,
               old_key=_old_key(d, meta), runs=[])
    by_dir = S.runs_by_case_dir()
    mains = {str(r.get("name") or "") for key in (str(frames_dir), str(d))
             for r in by_dir.get(key) or []} - {""}
    allruns = set(mains)
    for name in sorted(mains):
        allruns |= {v.name for v in voice_dirs(S.HTR_ROOT / name)}
    out.runs = sorted(allruns)
    bases = sorted(n for n in allruns
                   if not any(n != o and n.startswith(o + "-") for o in allruns))
    for p in real:
        assert p.dir is not None
        new_base = run_name(p.dir, p.key)
        for idx, base_run in enumerate(bases):
            target = new_base if idx == 0 else f"{new_base}-{base_run}"
            for run in sorted(allruns):
                if run == base_run:
                    p.runs[run] = target
                elif run.startswith(base_run + "-"):
                    p.runs[run] = target + run[len(base_run):]
        _describe_from_registry(p)
    _count_notes(out)
    _foresee(out, root)
    return out


def _old_key(d: Path, meta: dict[str, Any]) -> str:
    from nyshporka.cases import chain as C

    base = _base_shifra(meta)
    if base is not None:
        from nyshporka import library as L

        return str(L._mk_key(base.repo, base.fond, base.spr, base.opys) or "")
    try:
        return str(C.judge(d).key or "")
    except Exception:
        return ""


def _describe_from_registry(p: Part) -> None:
    """Назва й роки частини з реєстру опису — лише те, чому там вірять."""
    try:
        from nyshporka.share import opys

        row = opys.registry_row(p.shifra)
        got = opys.from_registry(row) if row else {}
    except Exception:
        return
    p.title = str(got.get("title") or "")
    p.years = (got.get("year_from"), got.get("year_to"))


def _pagestore_ref(address: str) -> Any:
    from nyshporka.pagestore import resolve_case

    try:
        return resolve_case(address)
    except Exception:
        return None


def _count_notes(pl: Plan) -> None:
    from nyshporka.pagestore import store as PS

    ref = _pagestore_ref(pl.old_key) if pl.old_key else None
    cf = PS.load_case(ref) if ref is not None else None
    if cf is None:
        return
    have = {k.casefold() for k in cf.pages}
    for p in pl.parts:
        if not p.leftover:
            p.notes = sum(1 for n in p.names if n.casefold() in have)


def _foresee(pl: Plan, root: Path) -> None:
    """Те, чого розбивка не зробить сама, — сказати до того, як щось змінено."""
    from nyshporka.core.workspace import workspace

    for p in pl.parts:
        if p.leftover or p.dir is None:
            continue
        if p.dir.is_dir() and not _ours(p, pl):
            raise SplitError(
                f"тека частини «{p.spr}» уже існує й містить інше: {_rel(p.dir, root)}. "
                f"Розбивка чужих файлів не чіпає — звільніть теку або назвіть іншу шифру")
        for old, new in p.runs.items():
            target = workspace().htr_reports / new
            if target.is_dir() and _read_json(target / "_htr_meta.json").get(
                    "split_from", {}).get("run") != old:
                raise SplitError(
                    f"прогін «{new}» уже існує й не походить із цієї розбивки — "
                    f"частина «{p.spr}» лягла б поверх чужого тексту")
    try:
        from nyshporka.share.suggest import _komirka

        cell = _komirka(pl.old_key) if pl.old_key else None
    except Exception:
        cell = None
    if cell is not None and cell.pages and cell.mine:
        pl.warnings.append((
            "already_shared",
            f"цю теку вже віддано в Супрягу під шифрою першої справи ({pl.old_key}, "
            f"{cell.pages} стор.): там лежить текст усіх справ теки. Розбивка на "
            f"диску цього не відкличе — напишіть у Супрягу, щоб внесок зняли, і "
            f"віддайте справи наново"))
    if pl.old_key:
        pl.warnings.append((
            "references",
            f"посилання на стару шифру ({pl.old_key}) у каноні, вердиктах і нотатках "
            f"розбивка не переписує: після неї кадри справ, крім першої, лежать під "
            f"іншими ключами — перегляньте їх"))


def _ours(p: Part, pl: Plan) -> bool:
    """Чи все, що вже лежить у теці частини, — її власні кадри з цієї розбивки."""
    assert p.dir is not None
    ok = {JOURNAL, "_source.json", "_fs_meta.json"}
    for f in p.dir.iterdir():
        if f.name in ok:
            continue
        src = pl.frames_dir / f.name
        if f.is_dir() or f.name not in p.names or not _same(src, f):
            return False
    return True


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


# ── розкласти ────────────────────────────────────────────────────────────────
def split(case_dir: str | Path, specs: list[tuple[str, str, str]], *,
          copy: bool = False) -> dict[str, Any]:
    """Розкласти теку на справи за картою. Повертає, що зроблено."""
    from nyshporka.cases.register import case_path
    from nyshporka.core.workspace import workspace

    root = workspace().root
    here = case_path(case_dir)
    journal = here / JOURNAL
    old = _read_json(journal)
    # 🔴 Журнал питається ДО плану: після обриву теки частин уже лежать, і план
    # за іншою картою побачив би в них «чуже» — тобто назвав би не ту причину.
    if old.get("state") == "done":
        raise SplitError(f"теку вже розкладено ({old.get('at')}). Інша карта — "
                         f"спершу зняти: nysh cases split \"{_rel(here, root)}\" --undo")
    if old and _spans(old.get("parts") or []) != [(a, b) for _w, a, b in specs]:
        raise SplitError("у теці лежить незавершена розбивка за ІНШОЮ картою. Дороблю "
                         "лише ту саму; щоб почати наново — --undo")
    pl = plan(case_dir, specs)
    if old:
        # 🔴 Після обриву прогони старої теки беруться з журналу, а не з
        # переліку: якщо обрив стався після позначки «заміщено», перелік їх уже
        # не показує — і доробка записала б, що прогонів у теки не було.
        pl.runs = [str(r) for r in old.get("runs") or pl.runs]
        for p, was in zip(pl.parts, old.get("parts") or [], strict=False):
            if was.get("runs"):
                p.runs = {str(k): str(v) for k, v in was["runs"].items()}
    want = [p.as_json(root) for p in pl.parts]
    _write_json(journal, {"state": "doing", "at": _now(), "copy": copy, "parts": want,
                          "runs": pl.runs, "old_key": pl.old_key,
                          "made_passport": old.get("made_passport",
                                                   not (pl.case_dir / "_source.json").is_file())})
    real = [p for p in pl.parts if not p.leftover]
    for p in real:
        _frames(pl, p, copy=copy)
        _passport(pl, p, root)
        _fs_meta(pl, p)
        _seg_cache(pl, p)
        for run in pl.runs:
            _split_run(pl, p, run, root)
    moved = _move_notes(pl)
    _mark_old(pl, root)
    index = _reindex(pl)
    done = json.loads(journal.read_text(encoding="utf-8"))
    done.update(state="done", done_at=_now())
    _write_json(journal, done)
    return {**pl.as_json(root), "notes_moved": moved, "index": index,
            "journal": _rel(journal, root)}


def _spans(parts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(p.get("first")), str(p.get("last"))) for p in parts]


def _frames(pl: Plan, p: Part, *, copy: bool) -> None:
    assert p.dir is not None
    p.dir.mkdir(parents=True, exist_ok=True)
    for name in p.names:
        src, dst = pl.frames_dir / name, p.dir / name
        if dst.exists():
            continue
        try:
            os.link(src, dst)
        except OSError as exc:
            if not copy:
                raise SplitError(
                    f"жорстке посилання на «{name}» не створилось ({exc}): тека "
                    f"частини на іншому томі або файлова система їх не вміє. "
                    f"Скопіювати кадри (місце на диску подвоїться) — --copy") from None
            shutil.copy2(src, dst)


def _passport(pl: Plan, p: Part, root: Path) -> None:
    from nyshporka.cases import register as REG
    from nyshporka.cases.chain import sidecar_of

    assert p.dir is not None
    REG.describe(p.dir, shifra=p.shifra, title=p.title, year_from=p.years[0],
                 year_to=p.years[1])
    side = p.dir / "_source.json"
    meta = _read_json(side)
    _, old = sidecar_of(pl.case_dir)
    loader = _read_json(pl.case_dir / "meta.json")
    for key in _PROVENANCE:
        value = old.get(key) or loader.get(key)
        if value and key not in meta:
            meta[key] = value
    # 🔴 Походження частини — у її паспорті: тека переїжджає й потрапляє до
    # колег, і «ці кадри вирізано з плівки такої-то» мусить їхати разом із нею.
    meta["split_from"] = {"dir": _rel(pl.case_dir, root), "first": p.first,
                          "last": p.last, "frames": len(p.names),
                          "from": p.pos[0], "to": p.pos[1]}
    meta.pop("spr_to", None)
    _write_json(side, meta)


def _fs_meta(pl: Plan, p: Part) -> None:
    """Id кадрів FamilySearch — частині лише її власні."""
    from nyshporka.share import align

    assert p.dir is not None
    src = pl.frames_dir / align.FS_META
    if not src.is_file():
        return
    raw = _read_json(src)
    stems = {Path(n).stem for n in p.names}
    mine = {k: v for k, v in raw.items() if k in stems or k in p.names}
    if mine:
        _write_json(p.dir / align.FS_META, mine)


def _seg_cache(pl: Plan, p: Part) -> None:
    """Готова сегментація — під новий шлях, щоб перечитування не рахувало її знову."""
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.run import seg_cache_dir

    assert p.dir is not None
    derived = workspace().derived
    src, dst = seg_cache_dir(pl.frames_dir, derived), seg_cache_dir(p.dir, derived)
    if not src.is_dir():
        return
    for name in p.names:
        for f in src.glob(f"{glob.escape(Path(name).stem)}.o*"):
            target = dst / f.name
            if target.exists():
                continue
            dst.mkdir(parents=True, exist_ok=True)
            try:
                os.link(f, target)
            except OSError:
                shutil.copy2(f, target)


def _split_run(pl: Plan, p: Part, run: str, root: Path) -> None:
    """Сторінки частини — у власний прогін із власною метою."""
    from nyshporka import htr_store as S
    from nyshporka.cloud.verify import META_NAME, QUARANTINE_NAME

    assert p.dir is not None
    src = S.HTR_ROOT / run
    dst = S.HTR_ROOT / p.runs[run]
    meta = _read_json(src / META_NAME)
    if not meta:
        return
    mine = set(p.names)
    stems = {Path(n).stem for n in p.names}
    dst.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        for suffix in _PAGE_FILES:
            f = src / f"{stem}{suffix}"
            if f.is_file() and not (dst / f.name).exists():
                shutil.copy2(f, dst / f.name)
    new = {k: v for k, v in meta.items() if k not in _RUN_AGGREGATES}
    pages = {k: v for k, v in (meta.get("pages") or {}).items() if k in mine}
    rel_style = not Path(str(meta.get("case_dir") or "")).is_absolute()
    new.update(
        case_dir=_rel(p.dir, root) if rel_style else str(p.dir),
        case_key=p.key, frames_total=len(p.names), pages=pages,
        split_from={"run": run, "dir": _rel(pl.case_dir, root), "at": _now()})
    for key in ("failed", "quarantined"):
        if isinstance(meta.get(key), list):
            new[key] = [n for n in meta[key] if n in mine]
    # У побічних теках голосів `done` — число сторінок, у головній — «дочитано».
    new["done"] = (len(pages) if not isinstance(meta.get("done"), bool)
                   else all(n in pages for n in p.names))
    _write_json(dst / META_NAME, new)
    quar = _read_json(src / QUARANTINE_NAME)
    held = quar.get("pages") if isinstance(quar.get("pages"), dict) else None
    if held:
        kept = {k: v for k, v in held.items() if k in mine}
        if kept:
            _write_json(dst / QUARANTINE_NAME, {"version": 1, "pages": kept})


def _move_notes(pl: Plan) -> int:
    from nyshporka.pagestore import store as PS

    src = _pagestore_ref(pl.old_key) if pl.old_key else None
    if src is None:
        return 0
    moved = 0
    for p in pl.parts:
        if p.leftover or not p.notes:
            continue
        dst = _pagestore_ref(p.shifra)
        if dst is None:
            continue
        moved += PS.move_pages(src, dst, p.names)["pages"]
    return moved


def _mark_old(pl: Plan, root: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.cloud.verify import META_NAME

    side = pl.case_dir / "_source.json"
    meta = _read_json(side)
    meta["split_into"] = [p.key for p in pl.parts if not p.leftover]
    meta["split_at"] = _now()
    _write_json(side, meta)
    for run in pl.runs:
        f = S.HTR_ROOT / run / META_NAME
        m = _read_json(f)
        if not m:
            continue
        m["superseded"] = {"by": sorted({p.runs[run] for p in pl.parts
                                         if not p.leftover and run in p.runs}),
                           "at": _now(), "why": "теку розкладено на справи"}
        _write_json(f, m)


def _forget_caches() -> None:
    from nyshporka import htr_store as S
    from nyshporka import library as L

    for fn in ("_sidecar_case", "load_library"):
        clear = getattr(getattr(L, fn, None), "cache_clear", None)
        if clear is not None:
            clear()
    S._RUNS_CACHE = None
    S._META_MEMO.clear()


def _reindex(pl: Plan) -> dict[str, Any]:
    """Каталог справ і текстовий стор: старе прибрати, нове показати пошуку."""
    from nyshporka.cases import db
    from nyshporka.search import store as ST

    _forget_caches()
    out: dict[str, Any] = {"catalog": False, "store": 0, "notes": []}
    try:
        db.rebuild(rescan=True)
        out["catalog"] = True
    except Exception as exc:
        out["notes"].append(f"каталог справ не перезібрався ({exc}) — nysh cases build")
    fresh = sorted({n for p in pl.parts if not p.leftover for n in p.runs.values()})
    if not ST.exists():
        return out
    try:
        _drop_from_store(pl.runs)
        out["store"] = sum(1 for _ in ST.ensure_all(fresh, force=True))
    except Exception as exc:
        out["notes"].append(f"текстовий стор не оновився ({exc}) — "
                            f"nysh text index --case <справа>")
    return out


def _drop_from_store(runs: list[str]) -> None:
    from nyshporka.search import store as ST

    conn = ST.connect(migrate=True)
    try:
        for run in runs:
            for (run_id,) in conn.execute("select id from runs where run=?", (run,)).fetchall():
                ST._delete_run(conn, int(run_id))
        conn.commit()
    finally:
        conn.close()


# ── зняти ────────────────────────────────────────────────────────────────────
def undo(case_dir: str | Path) -> dict[str, Any]:
    """Зняти розбивку: прибрати лише те, що вона створила, і повернути позначки."""
    from nyshporka import htr_store as S
    from nyshporka.cases.register import case_path
    from nyshporka.cloud.verify import META_NAME
    from nyshporka.core.workspace import workspace
    from nyshporka.pagestore import store as PS
    from nyshporka.search import store as ST
    from nyshporka.share import align

    d = case_path(case_dir)
    root = workspace().root
    journal = _read_json(d / JOURNAL)
    if not journal:
        raise SplitError(f"розбивки в теці немає (файла {JOURNAL} не знайдено): {d}")
    frames_dir = align._frames_dir(d) or d
    kept: list[str] = []
    gone_runs: list[str] = []
    src_ref = _pagestore_ref(str(journal.get("old_key") or ""))
    for part in journal.get("parts") or []:
        if not part.get("dir"):
            continue
        pdir = root / str(part["dir"])
        for old, new in (part.get("runs") or {}).items():
            run_dir = S.HTR_ROOT / str(new)
            if not run_dir.is_dir():
                continue
            if _read_json(run_dir / META_NAME).get("split_from", {}).get("run") != old \
                    or not _run_is_copy(run_dir, S.HTR_ROOT / str(old)):
                kept.append(f"прогін {new}: змінено після розбивки — лишаю")
                continue
            shutil.rmtree(run_dir)
            gone_runs.append(str(new))
        if src_ref is not None and part.get("shifra"):
            dst_ref = _pagestore_ref(str(part["shifra"]))
            if dst_ref is not None and pdir.is_dir():
                names = [p.name for p in align.frames_sorted(pdir)]
                PS.move_pages(dst_ref, src_ref, names)
        if not pdir.is_dir():
            continue
        side = _read_json(pdir / "_source.json")
        mine = str((side.get("split_from") or {}).get("dir") or "") == _rel(d, root)
        for f in list(pdir.iterdir()):
            frame = f.is_file() and (frames_dir / f.name).is_file()                 and _same(frames_dir / f.name, f)
            if frame or (mine and f.name in ("_source.json", align.FS_META)):
                f.unlink()
        with contextlib.suppress(OSError):
            pdir.rmdir()
        if pdir.is_dir():
            kept.append(f"тека {part['dir']}: у ній лишились файли не з розбивки")
    passport = d / "_source.json"
    meta = _read_json(passport)
    meta.pop("split_into", None)
    meta.pop("split_at", None)
    if journal.get("made_passport") and not {k for k in meta if k != "unidentified"}:
        passport.unlink(missing_ok=True)
    elif passport.is_file():
        _write_json(passport, meta)
    for run in journal.get("runs") or []:
        f = S.HTR_ROOT / str(run) / META_NAME
        m = _read_json(f)
        if m.pop("superseded", None) is not None:
            _write_json(f, m)
    (d / JOURNAL).unlink(missing_ok=True)
    _forget_caches()
    notes: list[str] = []
    try:
        from nyshporka.cases import db

        db.rebuild(rescan=True)
        if ST.exists():
            _drop_from_store(gone_runs)
            list(ST.ensure_all([str(r) for r in journal.get("runs") or []], force=True))
    except Exception as exc:
        notes.append(f"облік не оновився ({exc}) — nysh cases build")
    return {"case_dir": _rel(d, root), "runs_removed": gone_runs, "kept": kept,
            "notes": notes}


def _run_is_copy(new: Path, old: Path) -> bool:
    """Чи прогін частини досі дослівна вибірка зі старого — тоді його можна прибрати."""
    for f in new.iterdir():
        if f.name.startswith("_"):
            continue
        if not (old / f.name).is_file() or not filecmp.cmp(f, old / f.name, shallow=False):
            return False
    return True
