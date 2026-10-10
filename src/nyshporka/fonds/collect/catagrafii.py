"""📜 Збирач реєстру опису з покажчика катаграфій Бессарабії (ANRM ф.134 оп.2).

Що він дає такого, чого немає в інших збирачів: перелік справ опису РАЗОМ із
плівкою FamilySearch кожної. Майстер-індекс FS по цьому фонду називає плівки
групами, а покажчик дзеркала — лише частину справ, тож без цього збирача реєстр
радив би замовлення в архіві про справи, які лежать на вільному дзеркалі.

Збирач читає знімок джерела `catagrafii` (`nysh crawl catagrafii`), а немає
знімка — бере його сам: це три статичні файли.

🔴 Лише ANRM ф.134 оп.2. Інший фонд чи опис — відмова з причиною, а не
порожній реєстр: порожній читався б як «справ у фонді немає».
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectError, CollectResult, Plan, Target
from nyshporka.sources.base import SourceError
from nyshporka.sources.catagrafii import CatagrafiiSource, reels, safe_url

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

#: Колонки, які читає злиття реєстру. Порядок і назви — зобов'язання.
FIELDS = ("opys", "spr_int", "spr_letter", "title", "year_from", "year_to",
          "fs_film", "fs_url", "fs_frames", "fs_place", "fs_record_type")

REPO, FOND, OPYS = "ANRM", "134", "2"


class CatagrafiiCollector:
    """Перелік справ ANRM ф.134 оп.2 із плівками FS."""

    id = "catagrafii"
    label = "Катаграфії Бессарабії (index-moldova-revision-lists)"
    filename = "catagrafii.tsv"
    # Чим качати знайдене: плівки фонду лежать на дзеркалі, адресу плівки
    # дає `nysh find "ANRM 134-2-<справа>"`.
    source_id = "fsfilm"
    caps = frozenset({"opys", "titles", "years", "scans"})

    def __init__(self, workspace: Path | None = None, *,
                 source: CatagrafiiSource | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._source = source

    def _src(self) -> CatagrafiiSource:
        return self._source or CatagrafiiSource(self.workspace)

    @staticmethod
    def _not_ours(target: Target) -> str:
        if target.repo.upper() != REPO or str(target.fond).strip() != FOND:
            return (f"покажчик катаграфій знає лише {REPO} ф.{FOND} оп.{OPYS}; "
                    f"{target.repo} ф.{target.fond} у ньому немає")
        want = {str(o).strip() for o in target.opys if str(o).strip()}
        if want and OPYS not in want:
            return (f"покажчик катаграфій знає лише оп.{OPYS} фонду {FOND}; описів "
                    f"{', '.join(sorted(want))} у ньому немає")
        return ""

    def plan(self, target: Target) -> Plan:
        why = self._not_ours(target)
        if why:
            return Plan(collector=self.id, ready=False, why=why)
        have = self._src().catalog_source()[0] != "none"
        # Знімок є — збирання локальне; немає — три запити на статичні файли.
        return Plan(collector=self.id, ready=True, requests=0 if have else 3,
                    opys=(OPYS,))

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        why = self._not_ours(target)
        if why:
            raise CollectError(why)
        src = self._src()
        notes: list[str] = []
        try:
            if refresh or src.catalog_source()[0] == "none":
                notes.append(src.crawl(on_progress=on_progress)["summary"])
            dossiers = src.dossiers()
        except SourceError as exc:
            raise CollectError(str(exc)) from exc
        taken = src.catalog_source()[1].get("taken") or ""

        rows: list[dict[str, str]] = []
        no_number = two_reels = no_film = 0
        for d in dossiers.values():
            num = d["dosar"].strip()
            if not num.isdigit():
                no_number += 1
                continue
            got = reels(d.get("microfilm", ""), d.get("image_range", ""))
            films = list(dict.fromkeys(f for f, _r in got))
            if len(films) > 1:
                two_reels += 1
            if not films:
                no_film += 1
            rows.append({
                "opys": OPYS, "spr_int": str(int(num)), "spr_letter": "",
                "title": T.flat(d.get("title_ro", "")),
                "year_from": (d.get("year_from") or "").strip(),
                "year_to": (d.get("year_to") or "").strip(),
                "fs_film": films[0] if films else "",
                "fs_url": safe_url(d.get("familysearch_url")),
                "fs_frames": (d.get("image_count") or "").strip(),
                "fs_place": T.flat(d.get("county", "")),
                "fs_record_type": "ревізькі казки",
            })
        out = dest / self.filename
        kept = 0
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=(OPYS,))

        blind: list[Blind] = []
        if no_number:
            blind.append(Blind(
                kind="void", count=no_number,
                why="номер справи не читається як номер — у реєстр не пішли"))
        if two_reels:
            blind.append(Blind(
                kind="second_reel", count=two_reels,
                why=("справа на двох плівках: у реєстр іде перша (поле на одну "
                     "плівку); обидві й кадри на кожній — `nysh find "
                     "\"ANRM 134-2-<справа>\"`")))
        if no_film:
            blind.append(Blind(
                kind="no_film", count=no_film,
                why=("покажчик плівки справи ще не знає — це не «плівки немає», а "
                     "«не прив'язано»; плівку шукати в каталозі FS за роком і повітом")))
        if taken:
            notes.append(f"знімок покажчика від {taken}")
        return CollectResult(
            collector=self.id, out=out, rows=len(rows), kept=kept,
            opys_seen=(OPYS,), opys_collected=(OPYS,),
            quality={
                "із заголовком": sum(1 for r in rows if r["title"]),
                "з роками": sum(1 for r in rows if r["year_from"]),
                "з плівкою": sum(1 for r in rows if r["fs_film"]),
            },
            blind=tuple(blind), notes=tuple(notes))
