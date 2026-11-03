"""🦆 Онлайн-копії окремих справ зі зведеного покажчика: насамперед плівки FS.

🔴 Сторінка опису покажчика віддає лише копії ВСЬОГО опису (`file_id: null`).
Копія конкретної справи лежить тільки в її картці, тож збирач `duck` їх не бачить:
`duck_copy_url` порожній у кожному реєстрі, а справа з плівкою FS виглядає
«без плівки». 27.10.2026 так знайшлись сім губернських справ ДАХмО ф.315.

Картка коштує запиту, а дока просить 5 запитів на 10 секунд, тож цей збирач
береться лише за справи, плівки яких не знає жодне джерело, і спершу звужує їх
одним пошуком `is_online`. Перевірене лишається у файлі: повторний запуск дочитує,
а не починає заново, і стеля `MAX_CARDS` за запуск нічого не губить.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectResult, Plan, Target
from nyshporka.fonds.collect.duck import DuckCollector
from nyshporka.fonds.collect.wikisource import _dgs
from nyshporka.fonds.merge.text import key_of

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

FIELDS = ("opys", "spr_int", "spr_letter", "checked", "fs_dgs", "fs_more", "fs_url",
          "duck_copy_url", "availability")

#: Карток за один запуск: ~50 хв при ліміті сервісу. Решту бере наступний запуск.
MAX_CARDS = 1500
#: Як часто писати перевірене: обрив дорогого обходу не має коштувати всього.
SAVE_EVERY = 50
#: Стільки збоїв карток поспіль означає, що сервіс недоступний, а не справа погана.
FAIL_STREAK_MAX = 5
#: Копія, яку можна взяти. Порожньо — сервіс не перевіряв, вважаємо доступною.
OPEN = ("", "PUBLIC")

#: Джерела, що вже знають плівку справи.
_FILM_SOURCES = ("fs.tsv", "wikisource.tsv", "catagrafii.tsv")


def choose(copies: list[dict[str, str]]) -> dict[str, str]:
    """Поля рядка з копій справи: перша відкрита плівка FS і решта плівок."""
    opened = [c for c in copies if str(c.get("availability") or "") in OPEN]
    films: list[tuple[str, dict[str, str]]] = []
    for c in opened:
        dgs = _dgs(str(c.get("url") or "")) if "familysearch" in str(c.get("url")) else ""
        if dgs and dgs not in [d for d, _ in films]:
            films.append((dgs, c))
    best = films[0][1] if films else (opened[0] if opened else {})
    return {"fs_dgs": films[0][0] if films else "",
            "fs_more": ";".join(d for d, _ in films[1:]),
            "fs_url": str(best.get("url") or "") if films else "",
            "duck_copy_url": str(best.get("url") or ""),
            "availability": str(best.get("availability") or "")}


class DuckCopiesCollector:
    """Копії справ, яких не бачить перелік опису."""

    id = "duck-copies"
    label = "Duck Inspector: копії окремих справ"
    filename = "duck_copies.tsv"
    source_id = ""
    caps = frozenset({"online"})

    def __init__(self, workspace: Path | None = None, *, source: Any = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._src = source

    def _source(self) -> Any:
        if self._src is None:
            from nyshporka.sources.duck import DuckSource

            self._src = DuckSource(self.workspace)
        return self._src

    def plan(self, target: Target) -> Plan:
        code = DuckCollector(self.workspace)._code(target.repo)
        if not code:
            return Plan(collector=self.id, ready=False,
                        needs={"codes.duck": "як цей архів зветься в покажчику"},
                        why=f"невідомо, як архів {target.repo} підписаний у покажчику")
        return Plan(collector=self.id, ready=True, opys=target.opys,
                    why=f"не більше {MAX_CARDS} карток за запуск; решту бере наступний")

    @staticmethod
    def _filmed(dest: Path) -> set[Any]:
        known: set[Any] = set()
        for name in _FILM_SOURCES:
            for row in T.read_tsv(dest / name)[1]:
                if any((row.get(c) or "").strip() for c in ("dgs", "fs_dgs", "fs_film")):
                    known.add(key_of(row))
        return known

    @staticmethod
    def _spr(row: dict[str, str]) -> str:
        """Номер справи, як його пише покажчик: кінець адреси, не склеєні колонки."""
        tail = unquote((row.get("duck_url") or "").rsplit("/", 1)[-1])
        return tail or f"{row.get('spr_int')}{row.get('spr_letter')}"

    def _online(self, src: Any, code: str, fond: str, opys: str,
                todo: list[dict[str, str]]) -> tuple[list[dict[str, str]],
                                                     list[dict[str, str]]]:
        """(кому потрібна картка, про кого пошук уже сказав «копії немає»).

        Обрізана видача не дає права на «немає»: там карткою перевіряються всі.
        """
        from nyshporka.sources.base import SourceError

        try:
            hits, cut = src.find_files_split(archive=code, fond=fond, inventory=opys,
                                             online=True)
        except SourceError:
            return todo, []
        if cut:
            return todo, []
        keys = set()
        for h in hits:
            num = T.case_number(str(h.shifra).split("-", 3)[-1])
            if num:
                keys.add(key_of({"opys": opys, "spr_int": str(num[0]), "spr_letter": num[1]}))
        return ([r for r in todo if key_of(r) in keys],
                [r for r in todo if key_of(r) not in keys])

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        from nyshporka.sources.base import SourceError

        out = dest / self.filename
        _, duck = T.read_tsv(dest / DuckCollector.filename)
        if not duck:
            return CollectResult(collector=self.id, out=out, blind=(Blind(
                kind="no_duck", count=0, why="спершу `nysh registry collect duck`: "
                "копії шукаються за переліком справ покажчика"),))

        old = [] if refresh else T.read_tsv(out)[1]
        done = {key_of(r): r for r in old}
        filmed = self._filmed(dest)
        wanted = [o for o in (target.opys or sorted({r["opys"] for r in duck})) if o]
        src, today = self._source(), date.today().isoformat()
        code = DuckCollector(self.workspace)._code(target.repo)

        def save() -> None:
            if not dry_run:
                T.write_tsv(out, FIELDS, sorted(done.values(), key=T.sort_key))

        cards = failed = streak = left = 0
        for opys in wanted:
            todo = [r for r in duck if r["opys"] == opys and key_of(r) not in filmed
                    and key_of(r) not in done]
            if not todo:
                continue
            if cards >= MAX_CARDS or streak >= FAIL_STREAK_MAX:
                left += len(todo)
                continue
            ask, none = self._online(src, code, target.fond, opys, todo)
            for r in none:
                done[key_of(r)] = {**r, "checked": today}
            if dry_run:
                left += len(ask)
                continue
            for i, r in enumerate(ask):
                if cards >= MAX_CARDS or streak >= FAIL_STREAK_MAX:
                    left += len(ask) - i
                    break
                try:
                    copies = src.copies_of(code, target.fond, opys, self._spr(r))
                except (SourceError, OSError, ValueError):
                    failed += 1
                    streak += 1
                    continue
                streak = 0
                cards += 1
                done[key_of(r)] = {**r, "checked": today, **choose(copies)}
                if cards % SAVE_EVERY == 0:
                    save()
                if on_progress is not None:
                    on_progress(done=cards, total=MAX_CARDS, unit="картка",
                                note=f"оп.{opys}")
            save()
        save()

        rows = list(done.values())
        blind: list[Blind] = []
        if left:
            blind.append(Blind(kind="cards_left", count=left, why=(
                "справ ще не перевірено; повторний запуск дочитає" if not dry_run
                else "справ потребують картки")))
        if failed:
            blind.append(Blind(kind="cards_failed", count=failed, why=(
                "карток не отримано — ці справи перевірить наступний запуск")))
        # Справи на кількох групах FS сліпою зоною більше не є: злиття кладе
        # першу в `fs_dgs`, решту — у колонку реєстру `fs_more` (0.39.3).
        return CollectResult(
            collector=self.id, out=out, rows=len(rows), opys_collected=tuple(wanted),
            quality={"перевірено": len(rows),
                     "з плівкою FS": sum(1 for r in rows if r.get("fs_dgs")),
                     "на кількох групах FS": sum(1 for r in rows if r.get("fs_more")),
                     "інша копія": sum(1 for r in rows if r.get("duck_copy_url")
                                       and not r.get("fs_dgs"))},
            blind=tuple(blind))
