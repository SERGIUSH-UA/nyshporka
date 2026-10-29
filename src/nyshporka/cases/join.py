"""Зібрати справу з частин кількох плівок: `nysh cases join`.

Справа буває розірвана між котушками: на одній плівці її голова й картка
«CONTINUED ON ANOTHER ROLL», на наступній — «CONTINUED FROM ANOTHER ROLL» і
хвіст. `nysh cases split` працює з однією текою, тож такі частини лишаються в
карті поза справами (`-`), а тут їх зводять в одну теку справи.

Кадри не копіюються. Ім'я кадру в справі — `<№>_<плівка>_<кадр>`
(`0001_007810475_0672.jpg`): конвеєр далі скрізь сортує кадри за іменами, тож
порядок «голова → хвіст» тримає наскрізний номер на початку, а не номер плівки
(номери DGS не йдуть у порядку котушок). З імені видно, звідки кадр. Теки
старого зразка `<плівка>_<кадр>` лишаються чинними, а повторний виклик на такій
теці доробляє її в тому самому зразку.

* Кадри на диску — у теці справи жорсткі посилання на файли плівок.
* Кадри в бакеті (`_r2_frames.json`, плівку взяли «лише прогнати») — у теці
  справи маніфест із новими іменами, `names_in_archive` і позначкою `joined`.
  Архіви ті самі, що в плівок; хмара таку справу не перечитує (`cloud go`
  відмовляє), бо в архівах кадри лежать під іменами плівки.
* Плівку вже прочитано — з шифрою (`shifra`) у справу переїжджає й текст: кожен
  голос стає прогоном справи зі сторінками під новими іменами, нотатки
  сховища сторінок, ідентифікатори кадрів FamilySearch і кеш сегментації — теж.
  Повторне читання не потрібне (29.10.2026: 12 справ ф.127, 2 355 кадрів).

Повтор доробляє те саме: журнал `_join.json` тримає порядок кадрів і прогони.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JOURNAL = "_join.json"
#: Сторінка прогону — ці файли на кадр.
_PAGE_FILES = (".txt", ".lines.json")


class JoinError(RuntimeError):
    """Зібрати не можна — з причиною для людини."""


@dataclass
class Piece:
    src: Path          # тека плівки
    first: str
    last: str
    label: str = ""    # початок імені файлу в справі; порожньо — з паспорта або імені теки


@dataclass
class _Span:
    piece: Piece
    label: str
    frames_dir: Path
    names: list[str]                       # кадри частини, у порядку плівки
    remote: dict[str, Any] | None = None   # маніфест бакета плівки
    runs: list[str] = field(default_factory=list)
    whole: bool = False                    # частина — уся тека, а не шматок плівки


def parse_piece(spec: str) -> Piece:
    """`"<тека>=0821.jpg..0973.jpg"` → частина."""
    where, sep, span = str(spec).rpartition("=")
    first, dots, last = span.partition("..")
    if not (sep and dots and where.strip() and first.strip() and last.strip()):
        raise JoinError(f"частина «{spec}»: чекаю «<тека плівки>=<перший файл>..<останній файл>»")
    return Piece(Path(where.strip()), first.strip(), last.strip())


def _label(src: Path) -> str:
    """Плівка з паспорта теки (`film`/`dgs`/`fetched_ref`), інакше — перше число в імені."""
    for name in ("_source.json", "meta.json", "_fs_meta.json"):
        p = src / name
        if p.is_file():
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for key in ("film", "dgs", "fetched_ref"):
                val = str(meta.get(key) or "").strip()
                if val.isdigit():
                    return val
    m = re.match(r"(\d{5,})", src.name)
    return m.group(1) if m else src.name


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, data: Any) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _piece_runs(src: Path, frames_dir: Path) -> list[str]:
    """Прогони теки плівки разом із голосами.

    Розкладену плівку (`cases split`) перелік прогонів уже не показує — її
    прогони заміщено частинами, — тож вони беруться з журналу розбивки: саме
    там лежить текст шматків, що лишились поза справами (`-`).
    """
    from nyshporka import htr_store as S
    from nyshporka.cases import split as SPL
    from nyshporka.cloud.verify import voice_dirs

    journal = _read_json(src / SPL.JOURNAL)
    if journal.get("runs"):
        return sorted(str(r) for r in journal["runs"])
    # Тека, що ввійшла в справу цілою, свої прогони вже заміщено (`_retire`):
    # повтор бере їх із паспорта.
    joined = _read_json(src / "_source.json").get("joined_runs")
    if isinstance(joined, list) and joined:
        return sorted(str(r) for r in joined)
    by_dir = S.runs_by_case_dir()
    mains = {str(r.get("name") or "") for key in SPL._dir_keys(frames_dir, src)
             for r in by_dir.get(key) or []} - {""}
    runs = set(mains)
    for name in sorted(mains):
        runs |= {v.name for v in voice_dirs(S.htr_root() / name)}
    return sorted(runs)


def _spans(pieces: list[Piece]) -> list[_Span]:
    from nyshporka.cloud.verify import remote_manifest
    from nyshporka.share import align

    spans: list[_Span] = []
    for piece in pieces:
        if not piece.src.is_dir():
            raise JoinError(f"теки {piece.src} немає")
        frames_dir = align._frames_dir(piece.src)
        local = [p.name for p in align.frames_sorted(frames_dir)] if frames_dir else []
        try:
            remote = remote_manifest(piece.src, local)
        except ValueError as exc:
            raise JoinError(str(exc)) from None
        if remote is not None:
            frames_dir, names = piece.src, sorted(str(f["name"]) for f in remote["frames"])
        elif frames_dir is None:
            raise JoinError(f"у теці {piece.src} немає кадрів")
        else:
            names = local
        for name in (piece.first, piece.last):
            if name not in names:
                raise JoinError(f"частина {piece.src.name}: файла «{name}» у теці немає")
        a, b = names.index(piece.first), names.index(piece.last)
        if a > b:
            raise JoinError(f"частина {piece.src.name}: «{piece.first}» стоїть після «{piece.last}»")
        spans.append(_Span(piece, piece.label or _label(piece.src), frames_dir,
                           names[a:b + 1], remote, _piece_runs(piece.src, frames_dir),
                           whole=a == 0 and b == len(names) - 1))
    if len({s.remote is None for s in spans}) > 1:
        raise JoinError("частини змішано: одна плівка з кадрами на диску, інша — в бакеті "
                        "(`_r2_frames.json`). Зберіть однаково: докачайте кадри бакетної плівки")
    buckets = {str(s.remote.get("bucket") or "") for s in spans if s.remote is not None}
    if len(buckets) > 1:
        raise JoinError(f"кадри плівок у різних бакетах ({', '.join(sorted(buckets))})")
    return spans


def plan(dest: str | Path, pieces: list[Piece]) -> list[dict[str, Any]]:
    """Що ляже в теку справи: [{src, dst, name, piece}], у порядку частин. Нічого не пише."""
    if not pieces:
        raise JoinError("жодної частини — нема що збирати")
    return _plan(dest, _spans(pieces))


def _plan(dest: str | Path, spans: list[_Span]) -> list[dict[str, Any]]:
    from nyshporka.cloud.verify import REMOTE_FRAMES
    from nyshporka.share import align

    total = sum(len(s.names) for s in spans)
    width = max(4, len(str(total)))
    d = Path(dest)
    legacy = False
    have: set[str] = set()
    if d.is_dir():
        have = {p.name for p in align.frames_sorted(align._frames_dir(d) or d)}
        have |= {str(f.get("name")) for f in _read_json(d / REMOTE_FRAMES).get("frames") or []}
        legacy_names = {f"{s.label}_{name}" for s in spans for name in s.names}
        # тека старого зразка (без номера): доробляємо в тому самому зразку
        legacy = bool(have) and have <= legacy_names
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    seq = 0
    for i, s in enumerate(spans):
        for name in s.names:
            seq += 1
            dst = f"{s.label}_{name}" if legacy else f"{seq:0{width}d}_{s.label}_{name}"
            key = f"{s.label}_{name}"
            if key in seen:
                raise JoinError(f"кадр «{key}» потрапив би в справу двічі — частини перетинаються")
            seen.add(key)
            out.append({"src": s.frames_dir / name, "dst": dst, "name": name, "piece": i})
    order = [row["dst"] for row in out]
    if legacy and order != sorted(order):
        raise JoinError("тека зібрана за старим зразком (<плівка>_<кадр>), а за іменами кадри "
                        "стали б не в порядку частин; зберіть справу заново в порожню теку")
    alien = have - set(order)
    if alien:
        raise JoinError(f"у теці {d} уже є інші кадри ({len(alien)}, напр. «{sorted(alien)[0]}») — "
                        f"збирати справу поверх чужих кадрів не можна")
    return out


def join(dest: str | Path, pieces: list[Piece], *, copy: bool = False, shifra: str = "",
         title: str = "", years: tuple[int | None, int | None] = (None, None),
         rebuild: bool = True) -> dict[str, Any]:
    """Покласти частини в теку справи. Повтор доробляє те саме.

    З `shifra` справа отримує паспорт, а прочитане плівок — прогони справи
    (`rebuild=False` — каталог справ не перебудовувати, лише стор тексту).
    """
    if not pieces:
        raise JoinError("жодної частини — нема що збирати")
    spans = _spans(pieces)
    rows = _plan(dest, spans)
    if any(s.runs for s in spans) and not shifra:
        raise JoinError("плівки вже прочитано: щоб текст переїхав у справу, назвіть її шифру "
                        "(--shifra «ЦДІАК 127-1012-535»); без неї прогону нема до якої справи лягти")
    d = Path(dest)
    key = _key_of(shifra) if shifra else ""
    d.mkdir(parents=True, exist_ok=True)
    remote = spans[0].remote is not None
    made = _remote_frames(d, spans, rows) if remote else _link_frames(d, rows, copy=copy)
    out: dict[str, Any] = {"dest": str(d), "frames": len(rows), "made": made,
                           "first": rows[0]["dst"], "last": rows[-1]["dst"], "remote": remote}
    journal = _read_json(d / JOURNAL)
    journal.update({"pieces": [{"src": str(s.piece.src), "first": s.piece.first,
                                "last": s.piece.last, "label": s.label} for s in spans],
                    "frames": len(rows),
                    "order": [{"dst": r["dst"], "src": str(r["src"])} for r in rows]})
    if shifra:
        from nyshporka.core.workspace import workspace

        root = workspace().hub
        _passport(d, spans, rows, shifra=shifra, title=title, years=years, root=root)
        runs, skipped = _carry_runs(d, spans, rows, key, root)
        _fs_meta(d, spans, rows)
        _seg_cache(d, spans, rows)
        out["runs"] = runs
        out["voices_skipped"] = skipped
        out["notes_moved"] = _move_notes(spans, rows, shifra)
        out["key"] = key
        out["retired"] = _retire(spans, runs, key)
        out["index"] = _reindex(sorted(runs.values()), rebuild=rebuild)
        journal.update({"shifra": shifra, "key": key, "runs": runs})
    _write_json(d / JOURNAL, journal)
    return out


def _retire(spans: list[_Span], runs: dict[str, str], key: str) -> list[str]:
    """Тека, що ввійшла в справу ЦІЛОЮ, справою більше не є.

    🔴 Частина справи на окремій плівці («д. 502-2» у каталозі FS) — це тека з
    власним паспортом і прогонами. Без цього кроку після збирання вона лишалась
    би в бібліотеці окремою «справою» поруч із цілою, і в Супрягу пішли б обидві
    (29.10.2026: 12 частин справ ДАОО ф.37). Так само, як `cases split` знімає
    розкладену теку: `joined_into` у паспорті ховає її з бібліотеки
    (`library.split_into`), `superseded` у меті — її прогони з підрахунку.
    Шматок плівки (не вся тека) нічого не знімає: решта плівки — інші справи.
    """
    from nyshporka import htr_store as S
    from nyshporka.cases import split as SPL
    from nyshporka.cloud.verify import META_NAME

    done: list[str] = []
    by = sorted(runs.values())
    for s in spans:
        src = s.piece.src
        if not s.whole or (src / SPL.JOURNAL).exists():
            continue
        side = src / "_source.json"
        meta = _read_json(side)
        if meta.get("joined_into") != key or meta.get("joined_runs") != s.runs:
            _write_json(side, {**meta, "joined_into": key, "joined_runs": s.runs})
        for run in s.runs:
            f = S.htr_root() / run / META_NAME
            m = _read_json(f)
            if m and not m.get("superseded"):
                m["superseded"] = {"by": by, "at": SPL._now(),
                                   "why": f"теку зведено в справу {key}"}
                _write_json(f, m)
        done.append(str(src))
    return done


def _key_of(shifra: str) -> str:
    from nyshporka import library as L
    from nyshporka.cases import register as REG

    try:
        sh = REG.parse_shifra(shifra)
    except REG.RegisterError as exc:
        raise JoinError(f"шифра «{shifra}»: {exc}") from None
    return str(L._mk_key(sh.repo, sh.fond, sh.spr, sh.opys) or "")


def _link_frames(d: Path, rows: list[dict[str, Any]], *, copy: bool) -> int:
    made = 0
    for row in rows:
        target = d / row["dst"]
        if target.exists():
            continue
        try:
            os.link(row["src"], target)
        except OSError as exc:
            if not copy:
                raise JoinError(f"жорстке посилання не створюється ({exc}): тека справи на іншому "
                                f"томі, ніж плівка; --copy скопіює кадри") from None
            shutil.copy2(row["src"], target)
        made += 1
    return made


def _remote_frames(d: Path, spans: list[_Span], rows: list[dict[str, Any]]) -> int:
    """Маніфест справи з кадрів у бакеті: нові імена, архіви плівок, відповідність імен."""
    from nyshporka.cloud.verify import REMOTE_FRAMES

    frames: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    for i, s in enumerate(spans):
        assert s.remote is not None
        mine = {r["name"]: r["dst"] for r in rows if r["piece"] == i}
        by_name = {str(f["name"]): f for f in s.remote["frames"]}
        for name, dst in mine.items():
            frames.append({**by_name[name], "name": dst, "src": {"film": s.label, "name": name}})
        for part in s.remote["parts"]:
            got = [n for n in part["frames"] if n in mine]
            if got:
                parts.append({**{k: v for k, v in part.items() if k != "frames"},
                              "frames": [mine[n] for n in got],
                              "names_in_archive": {mine[n]: n for n in got},
                              "frames_in_archive": len(part["frames"])})
    first = spans[0].remote or {}
    data = {k: v for k, v in first.items() if k not in ("frames", "parts", "dgs", "split_from")}
    data.update(frames=frames, parts=parts, joined=True,
                films=[{"film": s.label, "first": s.piece.first, "last": s.piece.last,
                        "frames": len(s.names)} for s in spans])
    path = d / REMOTE_FRAMES
    had = _read_json(path)
    _write_json(path, data)
    return 0 if had.get("frames") == frames else len(frames)


def _passport(d: Path, spans: list[_Span], rows: list[dict[str, Any]], *, shifra: str,
              title: str, years: tuple[int | None, int | None], root: Path) -> None:
    from nyshporka.cases import register as REG

    REG.describe(d, shifra=shifra, title=title, year_from=years[0], year_to=years[1],
                 one_case=True)
    side = d / "_source.json"
    meta = _read_json(side)
    meta["join_from"] = [{"dir": _rel(s.piece.src, root), "film": s.label, "first": s.piece.first,
                          "last": s.piece.last, "frames": len(s.names)} for s in spans]
    if spans[0].remote is not None:
        meta["frames_remote"] = True
        bucket = spans[0].remote.get("bucket")
        if bucket:
            meta["r2_bucket"] = bucket
        meta["r2_keys"] = sorted({str(p["key"]) for s in spans for p in (s.remote or {})["parts"]
                                  if set(p["frames"]) & set(s.names)})
    old = _read_json(spans[0].piece.src / "_source.json")
    if old.get("fetched_from") and "fetched_from" not in meta:
        meta["fetched_from"] = old["fetched_from"]
    if old.get("private") and "private" not in meta:
        # 🔒 частина приватної плівки лишається приватною
        meta["private"] = old["private"]
    _write_json(side, meta)


def _rel(p: Path, root: Path) -> str:
    try:
        return str(Path(os.path.abspath(p)).relative_to(Path(os.path.abspath(root)))).replace("\\", "/")
    except ValueError:
        return str(p)


def _voices(runs: list[str]) -> dict[str, str]:
    """Суфікс голосу відносно базового прогону → прогін: «» — сам базовий."""
    if not runs:
        return {}
    base = min(runs, key=len)
    return {r[len(base):]: r for r in runs if r.startswith(base)}


def _carry_runs(d: Path, spans: list[_Span], rows: list[dict[str, Any]], key: str,
                root: Path) -> tuple[dict[str, str], list[str]]:
    """Кожен голос, що є в УСІХ частинах, — прогін справи. Повертає (суфікс → прогін, пропущені)."""
    from nyshporka.htr.runname import run_name

    per = [_voices(s.runs) for s in spans]
    if not any(per):
        return {}, []
    common = set(per[0])
    for v in per[1:]:
        common &= set(v)
    skipped = sorted({run for v in per for suf, run in v.items() if suf not in common})
    if "" not in common:
        raise JoinError("у частинах немає спільного основного прогону — текст не зводиться; "
                        f"прогони: {', '.join(sorted(r for v in per for r in v.values()))}")
    journal = _read_json(d / JOURNAL)
    base = str((journal.get("runs") or {}).get("") or run_name(d, key))
    out: dict[str, str] = {}
    for suf in sorted(common):
        target = base + suf
        _carry_run(target, [(i, v[suf]) for i, v in enumerate(per)], d, spans, rows, key, root)
        out[suf] = target
    return out, skipped


def _carry_run(target: str, src: list[tuple[int, str]], d: Path, spans: list[_Span],
               rows: list[dict[str, Any]], key: str, root: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.cases.split import _RUN_AGGREGATES
    from nyshporka.cases.split import _now as now_iso
    from nyshporka.cloud.verify import META_NAME, QUARANTINE_NAME

    dst = S.htr_root() / target
    old = _read_json(dst / META_NAME)
    if dst.is_dir() and old and not old.get("join_from"):
        raise JoinError(f"прогін «{target}» уже існує й не походить зі збирання — "
                        f"текст справи ліг би поверх чужого")
    dst.mkdir(parents=True, exist_ok=True)
    first = _read_json(S.htr_root() / src[0][1] / META_NAME)
    new = {k: v for k, v in first.items() if k not in _RUN_AGGREGATES and k != "split_from"}
    pages: dict[str, Any] = {}
    lists: dict[str, list[str]] = {"failed": [], "quarantined": []}
    held: dict[str, Any] = {}
    done_flags: list[Any] = []
    for i, run in src:
        sdir = S.htr_root() / run
        meta = _read_json(sdir / META_NAME)
        done_flags.append(meta.get("done"))
        ren = {r["name"]: r["dst"] for r in rows if r["piece"] == i}
        for name, dname in ren.items():
            stem, dstem = Path(name).stem, Path(dname).stem
            for suffix in _PAGE_FILES:
                f = sdir / f"{stem}{suffix}"
                if f.is_file() and not (dst / f"{dstem}{suffix}").exists():
                    shutil.copy2(f, dst / f"{dstem}{suffix}")
        for k, v in (meta.get("pages") or {}).items():
            if k in ren:
                pages[ren[k]] = v
        for lk in lists:
            lists[lk] += [ren[n] for n in meta.get(lk) or [] if n in ren]
        quar = _read_json(sdir / QUARANTINE_NAME).get("pages")
        if isinstance(quar, dict):
            held.update({ren[k]: v for k, v in quar.items() if k in ren})
    names = [r["dst"] for r in rows]
    rel_style = not Path(str(first.get("case_dir") or "")).is_absolute()
    new.update(case_dir=_rel(d, root) if rel_style else str(Path(os.path.abspath(d))),
               case_key=key, frames_total=len(names), pages=pages,
               join_from=[{"run": run, "dir": _rel(spans[i].piece.src, root),
                           "first": spans[i].piece.first, "last": spans[i].piece.last}
                          for i, run in src],
               joined_at=now_iso())
    for lk, vals in lists.items():
        if isinstance(first.get(lk), list) or vals:
            new[lk] = vals
    # У побічних теках голосів `done` — число сторінок, у головній — «дочитано».
    new["done"] = (len(pages) if not isinstance(first.get("done"), bool)
                   else all(n in pages for n in names) and all(x is True for x in done_flags))
    _write_json(dst / META_NAME, new)
    if held:
        _write_json(dst / QUARANTINE_NAME, {"version": 1, "pages": held})


def _fs_meta(d: Path, spans: list[_Span], rows: list[dict[str, Any]]) -> None:
    """Ідентифікатори кадрів FamilySearch — під новими іменами."""
    from nyshporka.share import align

    out = _read_json(d / align.FS_META)
    for i, s in enumerate(spans):
        raw = _read_json(s.frames_dir / align.FS_META) or _read_json(s.piece.src / align.FS_META)
        for r in rows:
            if r["piece"] != i:
                continue
            stem, dstem = Path(r["name"]).stem, Path(r["dst"]).stem
            if r["name"] in raw:
                out[r["dst"]] = raw[r["name"]]
            elif stem in raw:
                out[dstem] = raw[stem]
    if out:
        _write_json(d / align.FS_META, out)


def _seg_cache(d: Path, spans: list[_Span], rows: list[dict[str, Any]]) -> None:
    """Готова сегментація — під новий шлях і нові імена."""
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.run import seg_cache_dir

    derived = workspace().derived
    dst = seg_cache_dir(d, derived)
    for i, s in enumerate(spans):
        src = seg_cache_dir(s.frames_dir, derived)
        if not src.is_dir():
            continue
        for r in rows:
            if r["piece"] != i:
                continue
            stem, dstem = Path(r["name"]).stem, Path(r["dst"]).stem
            for f in src.glob(f"{glob.escape(stem)}.o*"):
                target = dst / (dstem + f.name[len(stem):])
                if target.exists():
                    continue
                dst.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(f, target)
                except OSError:
                    shutil.copy2(f, target)


def _move_notes(spans: list[_Span], rows: list[dict[str, Any]], shifra: str) -> int:
    """Нотатки сховища сторінок — зі справ плівок у справу, під новими іменами."""
    from nyshporka.cases import split as SPL
    from nyshporka.cases.chain import sidecar_of
    from nyshporka.pagestore import store as PS

    dst = SPL._pagestore_ref(shifra)
    if dst is None:
        return 0
    moved = 0
    for i, s in enumerate(spans):
        _, meta = sidecar_of(s.piece.src)
        old_key = SPL._old_key(s.piece.src, meta)
        src = SPL._pagestore_ref(old_key) if old_key else None
        if src is None:
            continue
        ren = {r["name"]: r["dst"] for r in rows if r["piece"] == i}
        moved += PS.move_pages(src, dst, list(ren), rename=ren)["pages"]
    return moved


def _reindex(runs: list[str], *, rebuild: bool) -> dict[str, Any]:
    """Каталог справ і стор тексту: нова справа — пошуку, як після розбивки."""
    from nyshporka.cases import db
    from nyshporka.cases.split import _forget_caches
    from nyshporka.search import store as ST

    _forget_caches()
    out: dict[str, Any] = {"catalog": False, "store": 0, "notes": []}
    if not rebuild:
        out["notes"].append("каталог справ не перебудовано (відкладено) — "
                            "після останньої справи: nysh cases build")
    else:
        try:
            db.rebuild(rescan=True)
            out["catalog"] = True
        except Exception as exc:
            out["notes"].append(f"каталог справ не перезібрався ({exc}) — nysh cases build")
    if runs and ST.exists():
        try:
            out["store"] = sum(1 for _ in ST.ensure_all(runs, force=True, optimize=False))
        except Exception as exc:
            out["notes"].append(f"текстовий стор не оновився ({exc}) — "
                                f"nysh text index --case <справа>")
    return out
