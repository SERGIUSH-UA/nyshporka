"""🦆 Збирач переліку справ фонду зі зведеного покажчика Duck Inspector.

Сервіс індексує українські архіви в тій самій ієрархії, що й ми (архів → фонд →
опис → справа), і коди архівів у нього збігаються з нашими. Цінний він
переліком, а не заголовками: бачить усі описи фонду незалежно від того, чи їх
оцифровано, — тобто відповідає на «що взагалі існує», коли решта джерел описує
лише вже виставлене в мережу.

🔴🔴 ліміт запитів — на клієнта, А не на процес. Дока просить 5 запитів на 10
секунд і попереджає, що зловживання карається блокуванням без попередження. Це
безкоштовний волонтерський сервіс без окремої інфраструктури, тож пауза
всередині процесу тут нічого не доводить: дві сесії з бездоганною паузою кожна
дають подвійний темп. Тому кожен запит іде через чергу, спільну на всю машину
(`core.xrate`), а приймач — журнал фактичних відправок.

⚠ Дока сервісу лежить за `/llms.txt`, і саме вона тут джерело істини: ендпоінт
`/api/archives`, описаний у старих нотатках, більше не існує — на нього
приходить HTML сторінки.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import (
    Blind,
    CollectResult,
    Plan,
    Target,
)

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://inspector.duckarchive.com"

#: Ключ спільної черги. Один на весь застосунок — бюджет міряється по IP.
RATE_KEY = "duck-inspector"
RATE_MAX = 5
RATE_WINDOW = 10.0

#: Колонки, які читає злиття реєстру.
FIELDS = ("opys", "spr_int", "spr_letter", "title", "year_from", "year_to",
          "folios", "duck_id", "duck_url", "duck_online", "duck_copies",
          "duck_copy_url")
VOID_FIELDS = (*FIELDS, "duck_note")

#: Повна сторінка — ознака, що є наступна (дока: page 0-based, крок 5000).
PAGE_SIZE = 5000

#: Позиції, які приходять рядками нарівні зі справами, але справами не є.
#: 🔴 Пущені в реєстр, вони стають фантомами в черзі завантаження — і за ними
#: замовляють в архіві документ, якого не існує.
_VOID_MARKS = ("вільний номер", "вибула", "вилучен", "відсутн", "немає справи")


def is_void(title: str) -> bool:
    """Чи це «порожня» позиція, а не справа."""
    t = (title or "").casefold()
    return any(m in t for m in _VOID_MARKS)


def file_page(archive: str, fond: str, opys: str, spr: str) -> str:
    """Адреса справи на сайті покажчика.

    🔴 Саме сторінка покажчика, а не пряме посилання на копію. Цього просить
    дока сервісу, і причина практична: адреси копій переїжджають, потрапляють
    за скорочувачі й ламаються без попередження, а сторінка покажчика лишається.
    """
    parts = "/".join(quote(str(p)) for p in (archive, fond, opys, spr))
    return f"{HOST}/archives/{parts}"


class DuckCollector:
    """Перелік справ фонду зі зведеного покажчика."""

    id = "duck"
    label = "Duck Inspector (зведений покажчик)"
    filename = "duck.tsv"
    #: Сам сервіс нічого не віддає — він покажчик, а не сховище.
    source_id = ""
    caps = frozenset({"opys", "titles", "years", "online"})

    def __init__(self, workspace: Path | None = None, *, fetcher: Any = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Any:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter
        from nyshporka.sources.http import Fetcher, app_ua

        # `delay=0`, бо темп тримає черга: два механізми складалися б, і
        # обіцяний у плані час перестав би збігатися з дійсністю.
        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        return Fetcher(base=HOST, delay=0.0, limiter=lim,
                       headers={"User-Agent": app_ua()})

    def _code(self, repo: str) -> str:
        from nyshporka.archives import active

        codes = active().codes_for(repo, "duck")
        return codes[0] if codes else ""

    def _get(self, http: Any, path: str) -> dict[str, Any]:
        r = http.get(path)
        try:
            data: dict[str, Any] = json.loads(getattr(r, "text", "") or "{}")
        except ValueError:
            # Сервіс відповідає сторінкою, коли шляху не існує, — і мовчазний
            # порожній результат тут читався б як «у фонді нічого немає».
            raise ValueError(f"{path}: відповідь не JSON — такого шляху немає") from None
        return data

    def plan(self, target: Target) -> Plan:
        code = self._code(target.repo)
        if not code:
            return Plan(
                collector=self.id, ready=False,
                needs={"codes.duck": "як цей архів зветься в покажчику"},
                why=(f"невідомо, як архів {target.repo} підписаний у покажчику. "
                     f"Здогад дав би запит про архів, якого там немає, а нуль у "
                     f"відповідь читався б як «у фонді нічого немає»."))
        try:
            fond = self._get(self._http(), f"/api/catalog/{quote(code)}/{quote(target.fond)}")
        except (ValueError, OSError) as exc:
            return Plan(collector=self.id, ready=False, why=str(exc))
        invs = [str(i.get("code") or "") for i in (fond.get("inventories") or [])]
        wanted = tuple(o for o in (target.opys or invs) if o)
        # Один запит на опис плюс уже зроблений на фонд; при п'яти запитах на
        # десять секунд це і є весь час роботи.
        n = len(wanted) + 1
        return Plan(collector=self.id, ready=bool(wanted), opys=tuple(wanted),
                    requests=n, eta_sec=n * RATE_WINDOW / RATE_MAX,
                    why="" if wanted else "у покажчику немає описів цього фонду")

    # ── збирання ─────────────────────────────────────────────────────────────
    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        http = self._http()
        code = self._code(target.repo)
        fond = self._get(http, f"/api/catalog/{quote(code)}/{quote(target.fond)}")
        seen = [str(i.get("code") or "") for i in (fond.get("inventories") or []) if i]
        wanted = tuple(o for o in (target.opys or seen) if o)

        rows: list[dict[str, Any]] = []
        voids: list[dict[str, Any]] = []
        non_numeric: list[str] = []
        for i, opys in enumerate(wanted):
            if on_progress is not None:
                on_progress(done=i, total=len(wanted), unit="опис",
                            note=f"оп.{opys} · зібрано {len(rows)}")
            got, void = self._one_opys(http, code, target.fond, opys)
            rows.extend(got)
            voids.extend(void)
            if not opys.isdigit():
                non_numeric.append(opys)
        if on_progress is not None:
            on_progress(done=len(wanted), total=len(wanted), unit="опис")

        out = dest / self.filename
        kept = 0
        extra: tuple[Path, ...] = ()
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=wanted)
            if voids:
                void_path = dest / "duck_void.tsv"
                T.merge_into(void_path, VOID_FIELDS, voids, touched=wanted)
                extra = (void_path,)

        blind: list[Blind] = []
        if voids:
            blind.append(Blind(
                kind="void", count=len(voids),
                where=dest / "duck_void.tsv",
                why=("позиції «вільний номер» і «справа вибула» — не справи; "
                     "пущені в реєстр, вони стали б фантомами в черзі, за якою "
                     "замовляють документи в архіві")))
        if non_numeric:
            blind.append(Blind(
                kind="non_numeric_opys", count=len(non_numeric),
                why=(f"нечислові описи ({', '.join(non_numeric[:5])}) — звірити "
                     f"оком з описом фонду: частина з них схожа на описки")))
        return CollectResult(
            collector=self.id, out=out, extra=extra, rows=len(rows), kept=kept,
            opys_seen=tuple(seen), opys_collected=wanted,
            quality=self._quality(rows), blind=tuple(blind))

    def _one_opys(self, http: Any, code: str, fond: str,
                  opys: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        voids: list[dict[str, Any]] = []
        page = 0
        while True:
            path = (f"/api/catalog/{quote(code)}/{quote(fond)}/{quote(opys)}"
                    f"?page={page}")
            data = self._get(http, path)
            files = data.get("files") or []
            # 🔴 Копії з `file_id: null` описують увесь опис (плівка цілком), і
            # в рядок конкретної справи вони не належать: інакше кожна справа
            # опису виглядала б оцифрованою.
            by_file: dict[str, str] = {}
            for c in data.get("online_copies") or []:
                fid, url = c.get("file_id"), str(c.get("url") or "")
                if fid and url:
                    by_file[str(fid)] = url
            for x in files:
                row = self._row(x, code, fond, opys, by_file)
                (voids if row.pop("_void", False) else rows).append(row)
            # Дока: наступну сторінку просити лише отримавши повну.
            if len(files) < PAGE_SIZE:
                return rows, voids
            page += 1

    @staticmethod
    def _row(x: dict[str, Any], code: str, fond: str, opys: str,
             by_file: dict[str, str]) -> dict[str, Any]:
        raw = str(x.get("code") or "")
        title = T.flat(str(x.get("title") or ""))
        num = T.case_number(raw)
        years = x.get("years") or [{}]
        y1 = years[0].get("start_year") or ""
        y2 = years[0].get("end_year") or y1
        fid = str(x.get("id") or "")
        row: dict[str, Any] = {
            "opys": opys,
            "spr_int": num[0] if num else "",
            "spr_letter": num[1] if num else "",
            "title": title,
            "year_from": y1, "year_to": y2,
            "folios": "",
            "duck_id": fid,
            "duck_url": file_page(code, fond, opys, raw or (str(num[0]) if num else "")),
            "duck_online": "1" if x.get("is_online") else "",
            "duck_copies": "1" if by_file.get(fid) else "",
            "duck_copy_url": by_file.get(fid, ""),
            "_void": is_void(title) or not num,
        }
        if row["_void"]:
            row["duck_note"] = ("порожня позиція" if is_void(title)
                                else f"нерозбірний номер: {raw!r}")
        return row

    @staticmethod
    def _quality(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "із заголовком": sum(1 for r in rows if r.get("title")),
            "з роками": sum(1 for r in rows if r.get("year_from")),
            "з копією онлайн": sum(1 for r in rows if r.get("duck_online")),
        }
