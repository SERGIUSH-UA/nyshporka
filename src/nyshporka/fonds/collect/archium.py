"""🏛 Збирач реєстру опису з переглядача архіву (ARCHIUM).

Найцінніше тут — не заголовки, а `archium_file`: адреса ПОСТОРІНКОВИХ JPG.
Доки її не було, справа, що лежить онлайн, стояла в черзі «замовлення в
архіві» — тобто найшвидший канал виглядав як відсутній.

🔴 Сайт адресує фонд і опис ВЛАСНИМИ номерами, з архівною шифрою не пов'язаними
ніяк (ф.224 він зве фондом 198). Офсетом це не рахується: 224-1-1 дає 51068, а
224-1-711 дає 51789, тобто крок пливе — номери йдуть за порядком опису, а той
має пропуски й літерні справи. Порахований офсет віддає ЧУЖУ справу з
правдоподібним іменем теки, і це найгірший різновид помилки.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectError, CollectResult, Plan, Target
from nyshporka.sources.archium import (
    ArchiumSource,
    CaseRow,
    case_meta,
    last_page,
    parse_cases,
    parse_inventories,
)

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

#: Колонки, які читає злиття реєстру. Порядок і назви — зобов'язання.
FIELDS = ("opys", "spr_int", "spr_letter", "title", "year_from", "year_to",
          "folios", "archium_file", "archium_url")

#: Скільки справ просимо однією сторінкою.
PAGE_LIMIT = 2000


class ArchiumCollector:
    """Перелік справ фонду з переглядача архіву."""

    id = "archium"
    label = "ARCHIUM (переглядач архіву)"
    filename = "archium.tsv"
    caps = frozenset({"opys", "titles", "years", "folios", "scans"})

    def __init__(self, workspace: Path | None = None, *,
                 source: ArchiumSource | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._source = source
        #: Чим качати знайдене — тим самим джерелом, що читало сторінку.
        self.source_id = source.id if source is not None else "archium"

    def _src(self, repo: str) -> ArchiumSource:
        if self._source is not None:
            return self._source
        from nyshporka.archives import active

        return ArchiumSource(self.workspace, site=active().site(repo, "archium"),
                             repo=repo)

    def _sidecar(self, target: Target) -> Path | None:
        from nyshporka.fonds.registry import registry_dir

        if self.workspace is None:
            return None
        return self.workspace / registry_dir(target.fond_id) / "archium_fond.json"

    def known_fond_id(self, target: Target) -> tuple[str, dict[str, str]]:
        """Внутрішній номер фонду й описи — з кешу минулого збирання.

        ⚠ Автопошуку за назвою тут навмисно немає: пошук сайту віддає разом із
        фондами й пункти меню, тож «вгадати» означало б із певною ймовірністю
        зібрати ЧУЖИЙ фонд під іменем потрібного — а помітити це можна лише за
        заголовками, які ніхто не звіряє.
        """
        side = self._sidecar(target)
        if side is not None and side.is_file():
            try:
                data = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return "", {}
            invs = {str(k): str(v) for k, v in (data.get("inventories") or {}).items()}
            return str(data.get("fond_id") or ""), invs
        return "", {}

    def fond_id_from_case(self, viewer_id: str, repo: str = "DAHMO") -> str:
        """Номер фонду з будь-якої ВЖЕ ВІДОМОЇ справи цього фонду.

        Найдешевший спосіб і не здогад: сторінка переглядача сама несе
        посилання на фонд, тобто це відповідь самого сайту.
        """
        src = self._src(repo)
        return case_meta(src.http.get(f"/file-viewer/{viewer_id}/").text).fond_id

    def plan(self, target: Target) -> Plan:
        site = self._src(target.repo).site
        if not site.url:
            return Plan(collector=self.id, ready=False,
                        why=f"для архіву {target.repo} майданчик ARCHIUM не описано "
                            f"в паку — додайте його в config/archives.yaml")
        fond_id, invs = self.known_fond_id(target)
        if not fond_id:
            return Plan(
                collector=self.id, ready=False,
                needs={"fond_id": "внутрішній номер фонду на сайті"},
                why=("сайт адресує фонд ВЛАСНИМ номером, і з архівним він не "
                     "пов'язаний (ф.224 значиться фондом 198). Узяти його можна "
                     "з адреси будь-якої справи цього фонду в переглядачі — "
                     "`/fonds/<цей номер>/` — або передати `--fond-id`."))
        opys = target.opys or tuple(sorted(invs))
        return Plan(collector=self.id, ready=True, opys=opys,
                    requests=len(opys) + 1)

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False,
                fond_id: str = "") -> CollectResult:
        src = self._src(target.repo)
        known_id, invs = self.known_fond_id(target)
        fid = fond_id or known_id
        if not fid:
            raise CollectError(self.plan(target).why)

        # Описи перечитуються зі сторінки фонду щоразу: їх могло побільшати, а
        # застарілий перелік мовчки лишив би частину фонду поза реєстром.
        _, nodes = parse_inventories(src.http.get(f"/fonds/{fid}/").text)
        found = {self._opys_no(n.label): n.ref.partition(":")[2] for n in nodes}
        invs = {k: v for k, v in {**invs, **found}.items() if k}
        wanted = tuple(o for o in (target.opys or sorted(invs)) if o in invs)

        rows: list[dict[str, Any]] = []
        blind: list[Blind] = []
        for i, opys in enumerate(wanted):
            if on_progress is not None:
                on_progress(done=i, total=len(wanted), unit="опис",
                            note=f"оп.{opys} · зібрано {len(rows)}")
            got, skipped = self._one_opys(src, invs[opys], opys)
            rows.extend(got)
            if skipped:
                blind.append(Blind(
                    kind="no_shifra", count=skipped,
                    why=("рядки без номера справи: у переліку вони є, але шифри "
                         "не несуть, тож у реєстр не лягли")))
        if on_progress is not None:
            on_progress(done=len(wanted), total=len(wanted), unit="опис")

        out = dest / self.filename
        kept = 0
        extra: tuple[Path, ...] = ()
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=wanted)
            side = dest / "archium_fond.json"
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text(json.dumps(
                {"fond": target.fond, "fond_id": fid, "inventories": invs},
                ensure_ascii=False, indent=1), encoding="utf-8")
            extra = (side,)

        return CollectResult(
            collector=self.id, out=out, extra=extra,
            rows=len(rows), kept=kept,
            opys_seen=tuple(sorted(invs)), opys_collected=wanted,
            quality=self._quality(rows), blind=tuple(blind))

    # ── розбір ───────────────────────────────────────────────────────────────
    def _one_opys(self, src: ArchiumSource, inv_id: str,
                  opys: str) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        skipped = 0
        page, pages = 1, 1
        while page <= pages:
            view = self._view(src, inv_id, page)
            if page == 1:
                pages = max(1, last_page(view))
            for case in parse_cases(view):
                row = self._row(case, opys, src.base)
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)
            page += 1
        return rows, skipped

    @staticmethod
    def _view(src: ArchiumSource, inv_id: str, page: int) -> str:
        """Сторінка опису. Сайт віддає HTML у JSON-конверті."""
        r = src.http.get(f"/api/v1/inventories/{inv_id}?Limit={PAGE_LIMIT}&Page={page}")
        try:
            return str(r.json().get("View") or "")
        except (AttributeError, ValueError):
            return str(getattr(r, "text", ""))

    @staticmethod
    def _row(case: CaseRow, opys: str, base: str) -> dict[str, Any] | None:
        code = T.case_number(case.number)
        if code is None:
            return None
        num, letter = code
        title, y1, y2, folios = T.parse_title_tail(case.description)
        # Дати сайт подає ще й окремим полем — воно виграє, бо не залежить від
        # того, чи дописав писар роки в кінець заголовка.
        if case.date:
            _, d1, d2, _ = T.parse_title_tail(f"х, {case.date}")
            y1, y2 = d1 or y1, d2 or y2
        return {
            "opys": opys, "spr_int": num, "spr_letter": letter,
            "title": title, "year_from": y1, "year_to": y2,
            "folios": folios or (str(case.sheets) if case.sheets else ""),
            "archium_file": case.file_id,
            "archium_url": f"{base}/file-viewer/{case.file_id}/",
        }

    @staticmethod
    def _opys_no(label: str) -> str:
        """«Опис 1» дає «1». Порожньо — цей вузол описом не є."""
        m = re.search(r"Опис\s*([\w-]+)", label)
        return m.group(1) if m else ""

    @staticmethod
    def _quality(rows: list[dict[str, Any]]) -> dict[str, int]:
        """🔴 Не число рядків, а чи є в них те, заради чого їх збирали."""
        return {
            "із заголовком": sum(1 for r in rows if r.get("title")),
            "з роками": sum(1 for r in rows if r.get("year_from")),
            "з аркушами": sum(1 for r in rows if r.get("folios")),
            "зі сканом": sum(1 for r in rows if r.get("archium_file")),
        }
