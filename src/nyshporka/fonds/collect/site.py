"""🗂 Збирач реєстру опису зі сторінок «оцифровані справи» сайту архіву.

Читає каталог джерела `site-<архів>` (`nysh crawl site-<архів>`) і кладе в
реєстр фонду справи, які архів виклав на власному сайті поза ARCHIUM: ДАОО,
ДАДнО, ДАХО, ДАМО, ДАХеО. Найцінніше тут — не заголовок, а `site_ref`: за ним
справу бере `cases take`. Доки цього збирача не було, справа, що лежить на сайті
архіву, у реєстрі стояла в черзі «замовлення в архіві».

🔴 Каталог — знімок на дату обходу. Немає знімка — відмова з командою, а не
порожній реєстр: порожній читався б як «на сайті справ фонду немає».

⚠ Перелік НЕ повний опис фонду: сайт показує лише оцифроване. Тому збирач не
каже «справ у фонді N», а лише «на сайті N».
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectError, CollectResult, Plan, Target
from nyshporka.sources.base import SourceError

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn
    from nyshporka.sources.sitecases import SiteCasesSource

#: Колонки, які читає злиття реєстру. Порядок і назви — зобов'язання.
FIELDS = ("opys", "spr_int", "spr_letter", "title", "year_from", "year_to",
          "site_source", "site_ref", "site_url", "site_kind")


def split_years(years: str) -> tuple[str, str]:
    """«1850–1852» → ("1850", "1852"), «1850» → ("1850", "1850"), «» → ("", "")."""
    parts = [p for p in years.replace("—", "–").replace("-", "–").split("–") if p.strip()]
    if not parts:
        return "", ""
    return parts[0].strip(), parts[-1].strip()


class SiteCollector:
    """Справи фонду, викладені на сайті архіву."""

    id = "site"
    label = "Сайт архіву (сторінки «оцифровані справи»)"
    filename = "site.tsv"
    caps = frozenset({"opys", "titles", "years", "scans", "online"})
    # Чим качати — джерелом сайту саме цього архіву; тут лише родове ім'я.
    source_id = "site"

    def __init__(self, workspace: Path | None = None, *,
                 source: SiteCasesSource | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._source = source

    def _src(self, repo: str) -> SiteCasesSource | None:
        if self._source is not None:
            return self._source
        from nyshporka.archives import active
        from nyshporka.sources.sitecases import SiteCasesSource

        site = active().site(repo.upper(), "cases")
        if site is None or not site.url:
            return None
        return SiteCasesSource(self.workspace, site=site, repo=repo)

    def _not_ready(self, target: Target) -> str:
        src = self._src(target.repo)
        if src is None:
            return (f"для архіву {target.repo} сторінок «оцифровані справи» в паку не "
                    f"описано — розбір є для ДАОО, ДАДнО, ДАХО, ДАМО, ДАХеО")
        if self.workspace is None and self._source is None:
            return "для каталогу сайту потрібен робочий простір"
        if src.catalog_source()[0] == "none":
            return (f"каталогу сайту {target.repo} ще немає — спершу `nysh crawl {src.id}` "
                    f"(обхід сторінок сайту, від секунд до кількох хвилин)")
        return ""

    def plan(self, target: Target) -> Plan:
        why = self._not_ready(target)
        if why:
            return Plan(collector=self.id, ready=False, why=why)
        # Збирання локальне: каталог уже на диску.
        return Plan(collector=self.id, ready=True, requests=0, opys=target.opys)

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        from nyshporka.sources.sitecases import _eq

        src = self._src(target.repo)
        if src is not None and refresh and self.workspace is not None:
            # Свіжий обхід на прохання людини; без простору писати каталог нікуди.
            try:
                src.crawl(on_progress=on_progress)
            except SourceError as exc:
                raise CollectError(str(exc)) from exc
        why = self._not_ready(target)
        if why or src is None:
            raise CollectError(why)
        try:
            refs = src._refs()
        except SourceError as exc:
            raise CollectError(str(exc)) from exc

        want = tuple(T.flat(o) for o in target.opys if T.flat(o))
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()
        opys_seen: set[str] = set()
        no_number = dup = 0
        for ref, e in refs:
            if not _eq(e.fond, str(target.fond)):
                continue
            opys_seen.add(e.opys)
            if want and not any(_eq(e.opys, o) for o in want):
                continue
            # ДАОО пише літерну справу через дефіс: «10-а» — це 10а.
            spr = re.sub(r"^(\d+)[-\s]+([а-яіїєґ])$", r"\1\2", e.sprava.strip().lower())
            code = T.case_number(spr)
            # 🔴 Номер мусить бути ЦІЛИМ: «12/1» розбір віддав би справою 12, і
            # чужа справа лягла б під її шифру з адресою завантаження.
            if code is None or f"{code[0]}{code[1]}" != spr:
                no_number += 1
                continue
            num, letter = code
            k = (e.opys, num, letter)
            if k in seen:
                # Друга копія тієї самої справи на сайті (ДАХеО: оригінал і
                # «відновлена з фотокопій»). У реєстрі рядок один, обидві копії
                # бере `nysh get` за адресою першої.
                dup += 1
                continue
            seen.add(k)
            y1, y2 = split_years(e.years)
            rows.append({
                "opys": e.opys, "spr_int": num, "spr_letter": letter,
                "title": T.flat(e.title), "year_from": y1, "year_to": y2,
                # Перша копія шифри має адресу без «~N» — саме її бере `nysh get`.
                "site_source": src.id, "site_ref": ref,
                "site_url": e.page,
                "site_kind": ",".join(dict.fromkeys(f.kind for f in e.files)),
            })
        if not opys_seen:
            raise CollectError(
                f"фонду {target.fond} на сторінках сайту {src.base} немає (каталог від "
                f"{src.catalog_source()[1].get('taken') or '?'}). Це не «не оцифровано»: "
                f"сайт оновлюється — `nysh crawl {src.id}`")

        touched = tuple(sorted({r["opys"] for r in rows} | set(want)))
        out = dest / self.filename
        kept = 0
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=touched)

        blind: list[Blind] = []
        if no_number:
            blind.append(Blind(
                kind="no_shifra", count=no_number,
                why="номер справи на сайті не читається як номер — у реєстр не пішли; "
                    f"їх видно в `nysh browse {src.id} {target.fond}`"))
        if dup:
            blind.append(Blind(
                kind="second_copy", count=dup,
                why="друга копія тієї самої справи на сайті — рядок у реєстрі один, "
                    "обидві копії бере `nysh get`"))
        taken = src.catalog_source()[1].get("taken") or ""
        return CollectResult(
            collector=self.id, out=out, rows=len(rows), kept=kept,
            opys_seen=tuple(sorted(opys_seen)), opys_collected=touched,
            quality={
                "із заголовком": sum(1 for r in rows if r["title"]),
                "з роками": sum(1 for r in rows if r["year_from"]),
                "зі сканом": len(rows),
            },
            blind=tuple(blind),
            notes=((f"каталог сайту від {taken}; на сайті лише оцифроване — це не "
                    f"повний опис фонду",) if taken else ()))
