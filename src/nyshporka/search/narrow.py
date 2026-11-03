"""🔎 Звузити пошук роком і архівом (`--year`, `--archive`) — поруч із `--case`.

Ідея №8 порталу: питання «це прізвище в ДАХО між 1795 і 1858» доти не ставилось
нічим — лише весь корпус або справи руками по одній. Фільтр не є новим каналом
пошуку: він перетворює область (`htr_store.runs_for_scope`) на ПЕРЕЛІК СПРАВ ще
до тексту. Далі пошук іде тією самою дорогою, що й по серії фонду, — кожна
справа зі своїм знаменником у журналі.

Звідки дані: роки — опис справи (`case_library.json`, `year_from`/`year_to`),
архів — перший сегмент ключа справи (`REPO/фонд/опис/справа`).

🔴 Справа без року в описі ЛИШАЄТЬСЯ в пошуку й рахується окремо
(`year_unknown`). Невідомий рік — це незнання, а не доказ іншого вікна: інакше
фільтр мовчки ховав би справи, яких просто не описали.

🔴 Прогін без ключа справи за `--archive` не шукається (архіву не видно), але
теж рахується (`no_case`): нуль без цього числа читався б як «прошукано все».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_YEARS = re.compile(r"^\s*(\d{3,4})\s*(?:(?:\.\.|–|—|-)\s*(\d{3,4}))?\s*$")

#: До стількох справ відбір шукається справами по одній, з усіма каналами
#: (якорі, запис, самоперевірка). Більше — одним проходом, як корпус: 0,5 с на
#: справу давали 45 хв на 4844 справи ДАХмО 1795–1858 (замір 03.11.2026).
SERIES_MAX = 60

#: Форма поля — у кожній відмові, щоб другий хід був правильним.
YEAR_FORM = "рік «1858» або вікно «1795..1858»"


@dataclass(frozen=True)
class Narrow:
    """Фільтр області: вікно років і/або канонічний код архіву."""

    years: tuple[int, int] | None = None
    repo: str = ""
    #: як людина написала архів — для відмов і журналу
    archive_asked: str = ""

    @property
    def label(self) -> str:
        parts = []
        if self.repo:
            parts.append(self.archive_asked or self.repo)
        if self.years:
            a, b = self.years
            parts.append(str(a) if a == b else f"{a}–{b}")
        return ", ".join(parts)

    def keep_key(self, key: str, lib: dict[str, dict[str, Any]] | None = None
                 ) -> bool | None:
        """Чи справа з ключем `key` у фільтрі. None — рік у описі невідомий
        (справа лишається в пошуку). Порожній ключ — False за `--archive`,
        None за самим `--year`."""
        key = (key or "").strip()
        if self.repo:
            if not key:
                return False
            if key.split("/", 1)[0].upper() != self.repo:
                return False
        if not self.years:
            return True
        if not key:
            return None
        e = (lib if lib is not None else _library()).get(key) or {}
        span = _span(e.get("year_from"), e.get("year_to"))
        if span is None:
            return None
        lo, hi = self.years
        return span[0] <= hi and span[1] >= lo

    def as_json(self) -> dict[str, Any]:
        return {"label": self.label, "repo": self.repo,
                "years": list(self.years) if self.years else None}


def _span(yf: Any, yt: Any) -> tuple[int, int] | None:
    def num(v: Any) -> int | None:
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    a, b = num(yf), num(yt)
    if a is None and b is None:
        return None
    a = b if a is None else a
    b = a if b is None else b
    assert a is not None and b is not None
    return (min(a, b), max(a, b))


def _library() -> dict[str, dict[str, Any]]:
    from nyshporka.library import library_lookup

    return library_lookup().by_key


def parse_years(text: str) -> tuple[int, int] | None:
    """«1858» → (1858, 1858); «1795..1858» → (1795, 1858); порожньо → None."""
    t = (text or "").strip()
    if not t:
        return None
    m = _YEARS.match(t)
    if not m:
        raise ValueError(f"рік «{text}» не розпізнано: {YEAR_FORM}")
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if a > b:
        raise ValueError(f"вікно «{text}» перевернуте: спершу ранній рік — "
                         f"«{b}..{a}»")
    return (a, b)


def parse_archive(text: str) -> str:
    """Мітка чи код архіву → канонічний код (ДАХО, DAHO, ДАХмО — одне)."""
    t = (text or "").strip()
    if not t:
        return ""
    from nyshporka.library import _canon_repo, _repo_alias

    code = _canon_repo(t)
    known = set(_repo_alias().values())
    if code not in known:
        raise ValueError(f"архів «{text}» не впізнано: ні код, ні мітка з паку "
                         f"архівів (nysh archive list). Приклад: «ДАХмО» або «DAHMO»")
    return code


def parse(year: str = "", archive: str = "") -> Narrow | None:
    """Фільтр із двох полів; обидва порожні — None (без звуження)."""
    years = parse_years(year)
    repo = parse_archive(archive)
    if not years and not repo:
        return None
    return Narrow(years=years, repo=repo, archive_asked=(archive or "").strip())


def apply(sc: dict[str, Any], nar: Narrow) -> dict[str, Any]:
    """Область `runs_for_scope` → перелік справ у фільтрі (`kind="cases"`).

    ValueError — коли не лишилось жодної справи: відмова зі знаменником, а не
    нуль хітів по порожній області.
    """
    from nyshporka import htr_store as S

    bound = S._bound_of_listing()
    lib = _library()
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    listed: set[str] = set()
    unknown: set[str] = set()
    loose_listed = no_case = loose_kept = 0
    in_repo: set[str] = set()
    for r in sc.get("rows") or []:
        key = S.run_key(r, bound)
        if key:
            listed.add(key)
            if nar.repo and key.split("/", 1)[0].upper() == nar.repo:
                in_repo.add(key)
        else:
            loose_listed += 1
        got = nar.keep_key(key, lib)
        if got is False:
            if not key:
                no_case += 1
            continue
        rows.append(r)
        if key:
            keys.add(key)
            if got is None:
                unknown.add(key)
        else:
            loose_kept += 1
    stats = {**nar.as_json(), "cases_listed": len(listed), "cases_kept": len(keys),
             "year_unknown": len(unknown), "year_unknown_cases": sorted(unknown)[:20],
             "runs_without_case": loose_listed, "no_case_skipped": no_case,
             "no_case_kept": loose_kept}
    if not rows:
        where = {"all": "у прочитаному", "cases": "в області"}.get(
            str(sc.get("kind")), f"у «{sc.get('shifra') or sc.get('key') or ''}»")
        head = f"{where} справ {len(listed)}"
        if nar.repo:
            head += f", з них в архіві {nar.archive_asked or nar.repo} — {len(in_repo)}"
        if nar.years:
            head += f", у вікні {nar.label.split(', ')[-1]} — 0"
        raise ValueError(f"після фільтра «{nar.label}» не лишилось жодної справи: "
                         f"{head}. Шукати нема в чому")
    return {**sc, "rows": rows, "kind": "cases", "key": "",
            "shifra": sc.get("shifra") or nar.label, "keys": sorted(keys),
            "narrow": stats}


def notes(stats: dict[str, Any]) -> list[tuple[str, str]]:
    """Попередження для конверта: (код, текст) — що фільтр лишив і що відкинув."""
    out: list[tuple[str, str]] = []
    if not stats:
        return out
    out.append(("narrowed", f"звужено «{stats.get('label')}»: справ "
                            f"{stats.get('cases_kept')} із {stats.get('cases_listed')}"))
    if stats.get("one_pass"):
        out.append(("narrow_one_pass",
                    f"відбір великий ({stats.get('cases_kept')} справ > {SERIES_MAX}) — "
                    f"шукано одним проходом: канали імен, запису й самоперевірка, що "
                    f"живуть у межах справи, не ганялись. Звузьте --case чи --year, щоб "
                    f"кожна справа пройшла всіма каналами"))
    if stats.get("year_unknown"):
        out.append(("year_unknown",
                    f"{stats['year_unknown']} справ без року в описі лишено в пошуку "
                    f"(невідомий рік — не доказ іншого вікна): "
                    + ", ".join(stats.get("year_unknown_cases") or [])
                    + (" …" if stats["year_unknown"] > 20 else "")))
    if stats.get("no_case_kept"):
        out.append(("no_case_kept",
                    f"{stats['no_case_kept']} прогонів без ключа справи лишено в пошуку: "
                    f"року їхньої справи не видно"))
    if stats.get("no_case_skipped"):
        out.append(("no_case_skipped",
                    f"{stats['no_case_skipped']} прогонів без ключа справи не прошукано: "
                    f"архіву їх не видно (nysh cases bind)"))
    return out
