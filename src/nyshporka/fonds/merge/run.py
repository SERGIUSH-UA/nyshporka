"""🧬 Оркестратор злиття: від теки джерел до реєстру фонду."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.fonds.collect.base import Blind, Target
from nyshporka.fonds.merge import coverage as C
from nyshporka.fonds.merge import scans as S
from nyshporka.fonds.merge import titles as TT
from nyshporka.fonds.merge import write as W
from nyshporka.fonds.merge.sources import SourceBook, read_book


class MergeError(RuntimeError):
    """Звести не вдалось, і причина сформульована для людини."""


@dataclass(frozen=True)
class MergeResult:
    """Що вийшло — і чого НЕ видно."""

    fond_id: str
    out: Path
    extra: tuple[Path, ...] = ()
    rows: int = 0
    sources: tuple[tuple[str, int], ...] = ()
    conflicts: int = 0
    verdicts_kept: int = 0
    coverage: dict[str, Any] = field(default_factory=dict)
    #: Звідки взявся знаменник. Порожньо — його немає, і покриття не рахувалось.
    #: 🔴 Двома окремими полями навмисно: `coverage` — числа, а це — підстава.
    denominator: str = ""
    channels: dict[str, int] = field(default_factory=dict)
    multi: dict[str, int] = field(default_factory=dict)
    blind: tuple[Blind, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "fond_id": self.fond_id, "out": str(self.out),
            "extra": [str(p) for p in self.extra],
            "rows": self.rows, "sources": [list(s) for s in self.sources],
            "conflicts": self.conflicts, "verdicts_kept": self.verdicts_kept,
            "coverage": self.coverage, "denominator": self.denominator,
            "channels": dict(self.channels), "multi": dict(self.multi),
            "blind": [{"kind": b.kind, "count": b.count, "why": b.why,
                       "where": str(b.where) if b.where else ""} for b in self.blind],
            "notes": list(self.notes),
        }


def fuse(book: SourceBook, target: Target) -> tuple[dict[Any, dict[str, Any]],
                                                    list[dict[str, str]],
                                                    list[tuple[str, str]]]:
    """Звести прочитані джерела в рядки реєстру. БЕЗ диска — усе в пам'яті.

    ⚠ Порядок кроків тут значущий: каталог звіряє село з назвою файлу скана,
    тож скани мусять бути зведені ДО нього.
    """
    reg, conflicts = TT.fuse_text(book)
    TT.fuse_alfavitka(reg, book.rows.get("alfavitka", []))

    unresolved: list[tuple[str, str]] = []
    S.fuse_commons(reg, book.rows.get("commons", []), unresolved)
    S.fuse_mirror(reg, book.rows.get("mirror", []), unresolved)
    S.mark_disk_and_truncation(reg, S.disk_map(book.library, target.fond))

    TT.fuse_covers(reg, book.rows.get("covers", []))
    TT.fuse_catalog(reg, book.rows.get("catalog", []), conflicts)
    TT.fuse_fs(reg, book.rows.get("fs", []), book.rows.get("wikisource", []))
    return reg, conflicts, unresolved


def _channels(reg: dict[Any, dict[str, Any]]) -> dict[str, int]:
    """Черга завантаження. Канали ВЗАЄМОВИКЛЮЧНІ й у порядку швидкості.

    🔴 Кожна справа рахується рівно в одному — тому, яким її справді візьмуть.
    Інакше сума каналів перевищила б чергу, і «скільки лишилось узяти» стало б
    неправдою.
    """
    out = {"disk": 0, "free": 0, "order": 0,
           "archium": 0, "commons": 0, "mirror": 0, "film": 0}
    for r in reg.values():
        if r.get("on_disk"):
            out["disk"] += 1
            continue
        if r.get("archium_file"):
            out["free"] += 1
            out["archium"] += 1
        elif r.get("commons_url"):
            out["free"] += 1
            out["commons"] += 1
        elif r.get("mirror_url"):
            out["free"] += 1
            out["mirror"] += 1
        elif r.get("fs_dgs"):
            out["free"] += 1
            out["film"] += 1
        else:
            out["order"] += 1
    return out


def _multi(reg: dict[Any, dict[str, Any]]) -> dict[str, int]:
    kinds = [r.get("commons_kind") or "" for r in reg.values()
             if str(r.get("commons_files") or "0").isdigit()
             and int(r.get("commons_files") or 0) > 1]
    return {"volumes": kinds.count("volumes"), "variants": kinds.count("variants")}


def merge_fond(target: Target, *, dest: Path, out: Path,
               library: Path | None = None, dry_run: bool = False) -> MergeResult:
    """Звести джерела опису фонду в один реєстр.

    🔴 `target.opys` тут не шанується Й НЕ ІГНОРУЄТЬСЯ МОВЧКИ. Знаменник
    покриття пофондовий за побудовою, а злиття одного опису лишило б реєстр із
    одним описом — та сама вада, від якої в збирачах стоїть збереження
    незачеплених описів. Тому це помилка з поясненням, а не тиха згода.
    """
    from nyshporka.archives import active

    if target.opys:
        raise MergeError(
            "злиття працює по ФОНДУ цілком: знаменник покриття пофондовий, а "
            "зведення одного опису лишило б реєстр із одним описом. Приберіть "
            "перелік описів.")

    book = read_book(dest, library)
    reg, conflicts, unresolved = fuse(book, target)

    pack = active()
    bounds = pack.opys_bounds(target.repo, target.fond)
    rows_list = list(reg.values())
    cov = C.classify(rows_list, bounds, pack.guide_total(target.repo, target.fond))

    blind: list[Blind] = []
    if not bounds:
        blind.append(Blind(
            kind="no_denominator", count=0,
            why=("меж описів цього фонду немає, тож покриття не рахується: "
                 "частка була б вигадана, а «0/0 · немає 0» читається як «усе "
                 "на місці»")))
    for opys, b in bounds.items():
        if b.is_lower_estimate:
            blind.append(Blind(
                kind="lower_estimate", count=1,
                why=(f"межа опису {opys} — з транскрипції, тобто НИЖНЯ оцінка: "
                     f"покриття по ньому завищене й зростатиме лише вниз")))
    if not book.has_library:
        blind.append(Blind(
            kind="no_library", count=0,
            why=("бібліотеки справ немає, тож «на диску» порожнє у ВСЬОМУ фонді "
                 "— це не означає, що нічого не завантажено")))
    if unresolved:
        blind.append(Blind(
            kind="no_shifra", count=len(unresolved),
            where=dest / "unresolved_scans.tsv",
            why=("скани, шифру яких немає в назві: тихо викинути їх — те саме, "
                 "що сказати «сканів немає»")))
    truncated = sum(1 for r in rows_list if r.get("truncated_mirror"))
    if truncated:
        blind.append(Blind(
            kind="truncated", count=truncated,
            why="дзеркало віддає менше за найбільший файл — качати з нього недокачати"))

    kept = 0
    notes: list[str] = []
    extra: tuple[Path, ...] = ()
    n_rows = len(rows_list)
    if not dry_run:
        n_rows = W.write_merged(out, reg)
        kept = W.carry_verdicts(dest / "conflicts.tsv", conflicts)
        W.write_conflicts(dest / "conflicts.tsv", conflicts)
        W.write_coverage(dest / "coverage.json", cov)
        extra = (dest / "conflicts.tsv", dest / "coverage.json")
        unres = dest / "unresolved_scans.tsv"
        if W.write_unresolved(unres, unresolved):
            extra += (unres,)
        elif unres.is_file():
            # Бланк лишився, бо в нього вписували руками, — а розбирати вже
            # нічого. Мовчазний файл тут читався б як жива черга.
            notes.append(f"{unres.name}: черги вже немає, але файл лишено — у "
                         f"ньому є вписані руками шифри")

    return MergeResult(
        fond_id=target.fond_id, out=out, extra=extra, rows=n_rows,
        sources=book.counts(), conflicts=len(conflicts), verdicts_kept=kept,
        coverage=cov,
        denominator=f"pack:{target.repo}/{target.fond}" if bounds else "",
        channels=_channels(reg), multi=_multi(reg), blind=tuple(blind),
        notes=tuple(notes))
