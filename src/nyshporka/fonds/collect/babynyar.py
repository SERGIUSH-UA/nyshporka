"""🕯 Збирач реєстру опису з онлайн-архіву «Бабин Яр».

Що він дає такого, чого немає в інших збирачів: перелік справ фонду РАЗОМ із
числом цифрових копій кожної — тобто відповідь не лише «що існує», а й «що вже
оцифровано й доступне безкоштовно». Для фондів РАЦС 1921-1946 це взагалі єдине
джерело: у переглядачах самих архівів їх немає через 75-річне обмеження.

🔴 Номер фонду звіряється РЯДКОМ, а не числом. «Р-6453» і «6453» — два різні
фонди в тому самому архіві, і зведення їх за першим числом підсунуло б перелік
справ радянського фонду під іменем дореволюційного. Єдина вільність — латинська
`R` замість кирилічної `Р`: майданчик пише саме `R-6453` там, де архів пише
`Р-6453`, і це та сама літера в двох розкладках, а не інший фонд.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectError, CollectResult, Plan, Target
from nyshporka.sources.babynyar import BASE, BabynYarSource, fond_key, table_rows

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

#: Колонки, які читає злиття реєстру. Порядок і назви — зобов'язання.
FIELDS = ("opys", "spr_int", "spr_letter", "title", "year_from", "year_to",
          "babynyar_case", "babynyar_url", "babynyar_scans")

_YEAR = re.compile(r"(\d{4})")
#: Рік у ЗАГОЛОВКУ справи: окреме число, не шматок довшого, і з того століття,
#: з якого на майданчику взагалі бувають документи.
_TITLE_YEAR = re.compile(r"(?<!\d)(1[5-9]\d\d|20[0-2]\d)(?!\d)")


def norm_fond(number: str) -> str:
    """Номер фонду до порівнюваного вигляду.

    Знімаються пробіли й розрізнення регістру, дефіси різних видів зводяться в
    один, а латинська `R` — у кирилічну `Р`. ⚠ Число НЕ витягується: див.
    заголовок модуля, це коштувало б підміни фонду.
    """
    return fond_key(number)


def fond_bounds(fund: dict[str, Any]) -> tuple[int, int] | None:
    """Межі років фонду так, як їх декларує сам архів (`start_date`/`end_date`).

    `None` — архів меж не назвав, і тоді рік справи ні з чим не звіряється.
    """
    try:
        lo = int(str(fund.get("start_date") or "").strip()[:4])
        hi = int(str(fund.get("end_date") or "").strip()[:4])
    except ValueError:
        return None
    return (lo, hi) if lo <= hi else None


def year_span(dates: str, title: str = "", *,
              bounds: tuple[int, int] | None = None) -> tuple[str, str, list[int]]:
    """(рік від, рік до, роки поза межами фонду).

    «1931 - 1932» або «16.01.1853 - 16.06.1854» → 1931-1932 і 1853-1854.
    ⚠ З колонки дат береться саме перший і ОСТАННІЙ чотиризначник: у датах із
    днями чисел більше двох, і наївне «перші два» дало б 16.01 як рік.

    🔴 Коли колонка дат порожня, роки шукаються В ЗАГОЛОВКУ. Це не запасний
    шлях, а головний: цілі фонди майданчика тримають дати всередині назви
    справи («…про народжених (1853-1857), про одружених (1853-1857)»), а
    колонку лишають пустою. Заміряно на ДАМО ф.484 — 1491 справа, роки в
    колонці мали 93 (6%). Із заголовка береться найменший і найбільший рік, а
    не перший і останній: там вони перелічені по типах запису. І лише окреме
    число з правдоподібного діапазону: «Справа 1205» чи «12345 арк.» — не роки.

    🔴 Рік поза межами фонду в діапазон справи НЕ береться, а повертається
    окремо — щоб збирач назвав його в `blind`. Заміряно на ДАМО ф.484 (фонд
    1804-1925): шість справ мали в описі «1993», «1996», «1997» серед сусідніх
    1892 і 1895 — описки архіву, і реєстр показував метричну книгу XIX ст. до
    1996 року. Виправляти такий рік на інше століття не можна: це вигадало б
    дату, а рішення тут — за людиною, що гляне на обкладинку.
    """
    raw = _YEAR.findall(dates or "")
    from_column = bool(raw)
    found = ([int(y) for y in raw] if raw else
             [int(y) for y in _TITLE_YEAR.findall(title or "")])
    outside: list[int] = []
    if bounds is not None:
        lo, hi = bounds
        outside = sorted({y for y in found if not lo <= y <= hi})
        found = [y for y in found if lo <= y <= hi]
    if not found:
        return "", "", outside
    if from_column:
        return str(found[0]), str(found[-1]), outside
    return str(min(found)), str(max(found)), outside


def years(dates: str, title: str = "", *,
          bounds: tuple[int, int] | None = None) -> tuple[str, str]:
    """Діапазон років справи — те саме, що `year_span`, без переліку відкинутих."""
    y1, y2, _ = year_span(dates, title, bounds=bounds)
    return y1, y2


class BabynYarCollector:
    """Перелік справ фонду з майданчика «Бабин Яр»."""

    id = "babynyar"
    label = "Бабин Яр (BYHMC)"
    filename = "babynyar.tsv"
    source_id = "babynyar"
    caps = frozenset({"opys", "titles", "years", "scans", "online"})

    def __init__(self, workspace: Path | None = None, *,
                 source: BabynYarSource | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._source = source

    def _src(self) -> BabynYarSource:
        return self._source or BabynYarSource(self.workspace)

    def _arch_ids(self, repo: str) -> tuple[str, ...]:
        from nyshporka.archives import active

        return active().codes_for(repo, "babynyar")

    def plan(self, target: Target) -> Plan:
        ids = self._arch_ids(target.repo)
        if not ids:
            return Plan(
                collector=self.id, ready=False,
                needs={"codes.babynyar": "числовий id архіву на майданчику"},
                why=(f"невідомо, під яким номером архів {target.repo} стоїть на "
                     f"«Бабиному Яру». Здогад тут шкідливий удвічі: скорочення "
                     f"там неоднозначні — «ДАЧО» носять ТРИ різні архіви, — тож "
                     f"запит навмання дав би перелік справ чужого архіву, а не "
                     f"нуль. Перелік із номерами: `nysh browse babynyar`. "
                     f"Додайте `codes.babynyar` у config/archives.yaml."))
        # Один запит на перелік фондів архіву, один на фонд, далі по одному на
        # опис. Скільки описів — до першого запиту невідомо, і вигадувати це
        # число означало б назвати неправдивий час.
        return Plan(collector=self.id, ready=True, requests=2, opys=target.opys)

    # ── збирання ─────────────────────────────────────────────────────────────

    def _find_fond(self, src: BabynYarSource, arch_id: str,
                   fond: str) -> dict[str, Any]:
        """Фонд майданчика за нашим номером — або порожньо, якщо його там немає.

        🔴 Через API, а не через сторінку «фонди архіву»: та гортається, і
        перший аркуш неповний (ДАМО: 75 фондів із 97). Саме на цьому збирач
        одного разу відмовив по ф.484 — найбільшій колекції метричних книг
        майданчика — словами «такого фонду тут немає».
        """
        want = norm_fond(fond)
        for f in src.funds(arch_id):
            if norm_fond(str(f.get("number") or "")) == want:
                return f
        return {}

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        _ = refresh                      # каталогу на диску цей збирач не тримає
        src = self._src()
        ids = self._arch_ids(target.repo)
        if not ids:
            raise CollectError(self.plan(target).why)

        found: dict[str, Any] = {}
        arch_used = ""
        for arch_id in ids:
            found = self._find_fond(src, arch_id, target.fond)
            if found:
                arch_used = arch_id
                break
        fond_id = str(found.get("id") or "")
        fond_name = str(found.get("name") or "")
        if not fond_id:
            # 🔴 Не порожній результат, а відмова з причиною. Порожній реєстр
            # читався б як «фонд є, але справ у ньому нема», тоді як насправді
            # цього фонду на майданчику не викладали взагалі.
            raise CollectError(
                f"фонду {target.fond} архіву {target.repo} на «Бабиному Яру» "
                f"немає: там викладено лише частину фондів кожного архіву. "
                f"Що саме є — `nysh browse babynyar arch:{ids[0]}`.")

        descs = [(str(d.get("id") or ""), str(d.get("number") or ""))
                 for d in (found.get("descriptions") or []) if d.get("id")]
        want = {str(o).strip() for o in target.opys if str(o).strip()}
        picked = [(did, num) for did, num in descs if not want or num in want]
        if want and not picked:
            raise CollectError(
                f"у фонді {target.fond} на майданчику немає описів "
                f"{sorted(want)} — там лежать: "
                f"{', '.join(n for _i, n in descs) or '(жодного)'}")

        rows: list[dict[str, Any]] = []
        no_number = 0
        offline = 0
        short: list[str] = []
        outside: list[str] = []
        bounds = fond_bounds(found)
        for i, (did, opys) in enumerate(picked, 1):
            seen = 0
            for cid, c in table_rows(src.page(f"/archive/desc/{did}"), "case"):
                seen += 1
                code = T.case_number(c[0] if c else "")
                if code is None:
                    # ⚠ Номер, який не є номером справи, лишається в знаменнику
                    # окремим рядком `blind`, а не тихо зникає.
                    no_number += 1
                    continue
                spr_int, letter = code
                scans = re.sub(r"\D", "", c[3]) if len(c) > 3 else ""
                if not scans or scans == "0":
                    offline += 1
                y1, y2, odd = year_span(c[2] if len(c) > 2 else "",
                                        c[1] if len(c) > 1 else "", bounds=bounds)
                if odd:
                    outside.append(f"спр.{spr_int}{letter}: "
                                   f"{', '.join(map(str, odd))}")
                rows.append({
                    "opys": opys, "spr_int": str(spr_int), "spr_letter": letter,
                    "title": T.flat(c[1] if len(c) > 1 else ""),
                    "year_from": y1, "year_to": y2,
                    "babynyar_case": cid,
                    "babynyar_url": f"{BASE}/archive/case/{cid}",
                    "babynyar_scans": scans,
                })
            # 🔴 Приймач повноти: скільки справ в описі каже САМ майданчик.
            # Сторінка опису пагінації не має, але доводить це лише число з
            # іншого каналу — обрізаний перелік інакше виглядав би як повний
            # фонд, і «справи 900-1491 не існує» пішло б у реєстр як факт.
            promised = src.cases_count(did)
            if promised is not None and promised != seen:
                short.append(f"оп.{opys}: розібрано {seen} з {promised}")
            if on_progress is not None:
                on_progress(done=i, total=len(picked), unit="опис",
                            note=f"справ зібрано {len(rows)}")

        touched = tuple(sorted({str(r["opys"]) for r in rows if r["opys"]}))
        out = dest / self.filename
        kept = 0
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=touched)

        blind: list[Blind] = []
        if no_number:
            blind.append(Blind(
                kind="void", count=no_number,
                why=("рядки, номер справи в яких не читається як номер — у реєстр "
                     "вони не пішли, бо стали б фантомами в черзі завантаження")))
        if short:
            blind.append(Blind(
                kind="capped", count=len(short),
                why=("опис віддав менше справ, ніж сам обіцяє "
                     f"({'; '.join(short)}) — перелік неповний, тож «такої "
                     f"справи у фонді немає» по ньому казати не можна")))
        if outside and bounds is not None:
            shown = "; ".join(outside[:8]) + (" …" if len(outside) > 8 else "")
            blind.append(Blind(
                kind="year_out_of_fond", count=len(outside),
                why=(f"роки поза межами фонду {bounds[0]}-{bounds[1]}, які "
                     f"декларує сам архів ({shown}): у діапазон справи їх не "
                     f"взято, у заголовку вони лишились як є. Схоже на описки "
                     f"опису, але виправляти їх на інше століття означало б "
                     f"вигадати дату — це рішення за людиною, що гляне на "
                     f"обкладинку")))
        if offline:
            blind.append(Blind(
                kind="no_scans", count=offline,
                why=("справи без цифрових копій: на майданчику вони є описом, а "
                     "не сканами, тож завантажити їх звідси не вийде")))
        return CollectResult(
            collector=self.id, out=out, rows=len(rows), kept=kept,
            opys_seen=tuple(sorted({n for _d, n in descs})),
            opys_collected=touched,
            quality={
                "із заголовком": sum(1 for r in rows if r["title"]),
                "з роками": sum(1 for r in rows if r["year_from"]),
                "зі сканами": sum(1 for r in rows if r["babynyar_scans"]),
            },
            blind=tuple(blind),
            notes=(f"архів {arch_used} · фонд {fond_id} · {fond_name}"[:200],))
