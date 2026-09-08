"""🎯 Самоперевірка пошуку: чи бачить він те, що око вже знайшло.

🔴 Третє з трьох чисел, без яких нуль не є відповіддю — і єдине, якого пакет
не вмів порахувати. Перші два («чи читабельний декод», «скільки сторінок
прошукано») пошук віддає сам; це — ні, і його доводилось брати на віру.

**Джерело позитиву — сховище сторінок**, тобто аркуші, де прізвище виписала
ЛЮДИНА, дивлячись на скан. Незалежне від пошуку за побудовою: якщо він їх не
бачить, нуль по решті справи не означає нічого.

🔴 **Знаменник — позитиви ∩ фактично декодовані сторінки.** Аркуш, який око
знає, а рушій не читав, у знаменник не входить: інакше ми міряли б повноту
декоду й називали б це якістю пошуку.

🔴 **Два числа, не одне: «знайдено» і «подано».** Сторінка може бути знайдена
й при цьому не потрапити в показане — саме там вимірювач починає брехати у свій
бік. У приватному конвеєрі це коштувало рядка з найвищим балом справи: recall
каналу його враховував, а на око він не подавався.

⚠ Позитивів може не бути. Тоді це **відмова, а не нуль**: порожній recall і
нульовий recall означають протилежне, і зводити їх в одне число означає видати
неміряне за поміряне.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Report:
    """Що знає око, що бачить машина, і чого не бачить."""

    #: Ключ справи, як його зрозумів резолвер.
    key: str = ""
    shifra: str = ""
    #: Чим міряли.
    query: str = ""
    #: Аркуші, де око виписало це прізвище.
    eye: int = 0
    #: З них декодовані — це і є знаменник.
    denom: list[str] = field(default_factory=list)
    #: Знайдені пошуком (понад порогом).
    found: list[str] = field(default_factory=list)
    #: Із знайдених — ті, що потрапили в показане.
    shown: list[str] = field(default_factory=list)
    #: Чому міряти не вийшло. Непорожнє — жодного числа не друкуємо.
    why: str = ""

    @property
    def measured(self) -> bool:
        return not self.why and bool(self.denom)

    @property
    def missed(self) -> list[str]:
        return sorted(set(self.denom) - set(self.found))

    @property
    def found_not_shown(self) -> list[str]:
        return sorted(set(self.found) - set(self.shown))

    def pct(self, part: list[str]) -> int:
        return round(100 * len(part) / len(self.denom)) if self.denom else 0


def run(case: str, q: str = "", *, thresh: int = 80, limit: int = 100,
        shown_hits: list[dict[str, Any]] | None = None,
        all_hits: list[dict[str, Any]] | None = None,
        all_pages: list[tuple[str, str]] | None = None) -> Report:
    """Поміряти recall пошуку на тому, що вже виписало око.

    ⚠ `q` за замовчуванням береться з профілю простору: міряти треба саме тим
    прізвищем, яким шукають, інакше число не про цей пошук.
    """
    from nyshporka import htr_store as S
    from nyshporka.pagestore import query as PQ
    from nyshporka.pagestore import store as PS

    if not q:
        try:
            from nyshporka.core.profile import active

            prof = active()
            q = prof.display or prof.name
        except Exception:
            return Report(why="нема чим міряти: ні запиту, ні профілю простору")
    rep = Report(query=q)
    try:
        ref = PS.resolve_case(case)
    except Exception as exc:
        return Report(query=q, why=str(exc))
    rep.key, rep.shifra = ref.key, ref.shifra

    # 🔴 Аркуш ототожнюється за ОСНОВОЮ імені без регістру. Око записує «00301»,
    # мета прогону — «00301.jpg», еталон — «00301.JPG»; порівняння рядків тут
    # давало «жоден аркуш ока не прочитаний рушієм» на справі, прочитаній
    # цілком, — тобто recall не мірявся там, де він був найпотрібніший.
    eye = {_pid(h["scan"]) for h in
           (PQ.grep_surnames(q, thresh=thresh, case_key=ref.key)["hits"] or [])}
    rep.eye = len(eye)
    if not eye:
        rep.why = ("у сховищі сторінок цієї справи прізвища немає — міряти нема "
                   "на чому. Занесіть хоч один аркуш, де ви його бачили оком")
        return rep

    try:
        scope = S.runs_for_scope(ref.key)
    except Exception as exc:
        rep.why = str(exc)
        return rep
    decoded: set[str] = set()
    for row in scope["rows"]:
        for page in ((S.case_pages(row["name"]) or {}).get("pages") or []):
            decoded.add(_pid(str(page.get("page") or "")))
    rep.denom = sorted(eye & decoded)
    if not rep.denom:
        rep.why = (f"жоден із {len(eye)} аркушів, де око бачило прізвище, не "
                   f"прочитаний рушієм — recall НЕ ВИМІРЯНИЙ, нулю по цій "
                   f"справі вірити не можна")
        return rep

    # Хіти можна передати готовими (`find` уже їх має) — тоді пошук не
    # повторюється двічі заради тих самих чисел.
    if shown_hits is None:
        got = S.search(q, name=ref.key, thresh=thresh, limit=limit)
        shown_hits, total = got["hits"], int(got["total"] or 0)
    else:
        total = len(all_hits) if all_hits is not None else len(shown_hits)
    rep.shown = sorted({_pid(h["page"]) for h in shown_hits} & set(rep.denom))
    # 🔴 «Знайдено» рахується по ВСІХ хітах понад порогом, а «подано» — лише по
    # тих, що влізли в `limit`. Розрив між ними і є те, чого одне число не
    # показує: сторінка знайшлась, а на око не поїхала.
    if all_pages is not None:
        rep.found = sorted({_pid(pg) for _run, pg in all_pages} & set(rep.denom))
        return rep
    if all_hits is None:
        wide = S.search(q, name=ref.key, thresh=thresh, limit=max(limit, total))
        all_hits = wide["hits"]
    rep.found = sorted({_pid(h["page"]) for h in all_hits} & set(rep.denom))
    return rep


def _pid(name: str) -> str:
    """Тотожність аркуша: основа імені без регістру («00301.JPG» → «00301»)."""
    from pathlib import Path

    return Path(str(name or "")).stem.lower()


def as_dict(rep: Report) -> dict[str, Any]:
    return {"key": rep.key, "shifra": rep.shifra, "query": rep.query,
            "measured": rep.measured, "why": rep.why,
            "eye": rep.eye, "denominator": rep.denom,
            "found": rep.found, "found_pct": rep.pct(rep.found),
            "shown": rep.shown, "shown_pct": rep.pct(rep.shown),
            "missed": rep.missed, "found_not_shown": rep.found_not_shown}
