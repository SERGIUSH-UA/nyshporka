"""🔎 Читання каталогу: віяловий запит по паках + чесне покриття.

Кожна функція тут повертає `Answer`, а не голий список. Причина одна і вона
головна:

    🔴 порожній результат дозволено тільки разом із непорожнім покриттям.

«Нічого не знайдено» і «ніде не шукали» — різні відповіді, і в генеалогії ціна
плутанини між ними максимальна: «немає» закриває напрям пошуку. Інваріант
тримається кодом (`Answer.__post_init__`) і тестом, а не домовленістю.

Другий інваріант, теж під тестом: **кожен рядок несе `origin` і `pack_id`**.
Різниця між «так каже офіційний покажчик архіву» і «так я сам прочитав з
обкладинки» — це різниця між доказом і гіпотезою, і генеалог, який її загубить,
опублікує чужу помилку як факт.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from nyshporka.catalog.store import (
    CatalogMissing,
    Coverage,
    close_all,
    coverage,
    open_packs,
)

__all__ = ["Answer", "CatalogMissing", "Coverage", "confusers", "find_places",
           "place_card", "places_for_fond", "siblings"]


@dataclass
class Answer:
    """Рядки + де саме шукали + що лишилось непокритим."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    partial: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rows and not self.coverage:
            raise AssertionError(
                "порожня відповідь без покриття: якщо шукати не було де, треба "
                "кидати CatalogMissing, а не віддавати нуль")

    def as_dict(self) -> dict[str, Any]:
        return {"rows": self.rows,
                "coverage": [c.as_dict() for c in self.coverage],
                "conflicts": self.conflicts, "partial": list(self.partial)}

    def human_coverage(self) -> str:
        return "; ".join(c.human() for c in self.coverage) or "ніде"


def _tag(row: dict[str, Any], pack_id: str) -> dict[str, Any]:
    """Позначити рядок джерелом. Без цього він — твердження без автора."""
    row["origin"] = "own" if pack_id == "own" else "catalog"
    row["pack_id"] = pack_id
    return row


def _norm(s: str) -> str:
    from nyshporka.geog.gazetteer import norm_name

    return norm_name(s)


_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def _has_latin(s: str) -> bool:
    return bool(_LATIN_RE.search(s or ""))


#: Поріг схожості латинських форм. **Виміряний, а не вгаданий** — і саме він
#: вирішує, чи ця гілка корисна, чи шкідлива.
#:
#:     Miastkowka ↔ Мястковка   94.7 ✅      Horodkivka ↔ Бородаївка  80.0 ❌ шум
#:     Horodkivka ↔ Городківка  90.0 ✅      Miastkowka ↔ Ілляшівка   63.2 ❌ шум
#:     Ustia      ↔ Устя        88.9 ✅      Tsarevka   ↔ Андріївка   58.8 ❌ шум
#:     Miastkowka ↔ М'ястківка  84.2 ✅
#:     Tsarevka   ↔ Царёвка     80.0 ✅ (на межі — не проходить)
#:
#: 🔴 На порозі 70 гілка видавала «Ілляшівку» першим хітом на запит `Miastkowka` —
#: тобто правдоподібне чуже село замість чесного нуля. Це гірше за відсутність
#: пошуку: нуль людина перевірить, а впевнену помилку понесе далі.
#:
#: 84 обрано вище за найвищий заміряний шум (80) із запасом. Ціна відома і
#: прийнята: `Tsarevka`→«Царівка» (66.7) і `Ustia`→«Устье» (66.7) не знайдуться.
#: Пропущений збіг чесний — його видно як нуль; хибний збіг не видно ніяк.
_LATIN_MIN = 84


def _add_latin_hits(packs: list[tuple[str, sqlite3.Connection]], nq: str,
                    where: str, args: list[Any], limit: int, add: Any) -> None:
    """Дошукати поселення за латинською формою назви (колонка `translit`)."""
    try:
        from rapidfuzz import fuzz

        from nyshporka.utils.translit import normalize_for_matching
    except ImportError:
        return
    lat = normalize_for_matching(nq)
    if len(lat) < 3:
        return
    for pack_id, con in packs:
        # 🔴 Повний скан по `translit`, а не вибірка з FTS. Спершу тут стояла
        # триграмна FTS із `LIMIT 300` — і вона мовчки губила потрібне: без
        # ранжування ліміт обрізає кандидатів у довільному порядку, а триграма
        # «vka» є в кожній другій українській назві. `Miastkowka` віддавала нуль
        # при тому, що збіг із «Мястковка» — 94.7.
        # Таблиця поселень мала (4566 рядків): скан коштує стільки ж, скільки
        # сусідній кириличний фаззі-фолбек, тобто десятки мілісекунд.
        for r in con.execute("SELECT * FROM places WHERE translit != ''"):
            # найкраща з форм (українська й російська лежать в одній колонці),
            # а не перша-ліпша: інакше порядок слів у `translit` впливав би на
            # те, чи село знайдеться
            forms = (r["translit"] or "").split()
            s = max((fuzz.ratio(lat, f) for f in forms), default=0.0)
            if s >= _LATIN_MIN:
                # нижче за будь-який кириличний збіг: латинка — здогад про
                # написання, а не прочитане в джерелі
                add(r, int(s * 0.7), pack_id)


# ── пошук поселення ──────────────────────────────────────────────────────────

def find_places(q: str, limit: int = 40, uezd: str = "", fond: str = "",
                section: str = "") -> Answer:
    """Поселення за назвою (укр, рос або латинкою), з фаззі-добором.

    Порядок відбору дослівно той самий, що був у `geog.gazetteer`: спершу точний
    і префіксний збіг, і лише потім фаззі — інакше на короткому запиті («Устя»)
    фаззі-хвіст витісняє з видачі саме те, що шукали.
    """
    packs = open_packs("geog")
    cov = coverage("geog")
    nq = _norm(q)
    rows: dict[str, dict[str, Any]] = {}

    def add(r: sqlite3.Row, score: int, pack_id: str) -> None:
        d = _tag(dict(r), pack_id)
        d["score"] = score
        prev = rows.get(d["card"])
        if prev is None or prev["score"] < score:
            rows[d["card"]] = d

    where, args = "", []
    # 🕍 Конфесія — фільтр, а не поділ на три газетири. Одне містечко присутнє в
    # кількох розділах: у М'ястківці була православна церква, костел і єврейська
    # громада, і метрики кожної лежать окремо. Дефолт «усі» саме тому.
    if section:
        where += " AND section = ?"
        args.append(section)
    if uezd:
        where += " AND (uezd_gub LIKE ? OR hist_place LIKE ?)"
        args += [f"%{uezd}%", f"%{uezd}%"]

    try:
        for pack_id, con in packs:
            if nq:
                for pat, sc in ((nq, 100), (nq + "%", 92), ("%" + nq + "%", 84)):
                    sql = ("SELECT * FROM places WHERE (norm_uk LIKE ? OR "
                           "norm_ru LIKE ?)" + where + " LIMIT 400")
                    for r in con.execute(sql, [pat, pat, *args]):
                        add(r, sc, pack_id)
                    if len(rows) >= limit and sc >= 92:
                        break
            else:
                sql = ("SELECT * FROM places WHERE 1=1" + where
                       + " ORDER BY n_cases DESC LIMIT ?")
                for r in con.execute(sql, [*args, limit]):
                    add(r, 0, pack_id)

        # фаззі — лише якщо точних мало
        if nq and len(rows) < limit:
            try:
                from rapidfuzz import fuzz
            except ImportError:
                fuzz = None  # type: ignore[assignment]
            if fuzz is not None:
                for pack_id, con in packs:
                    for r in con.execute(
                            "SELECT * FROM places WHERE 1=1" + where, args):
                        s = max(fuzz.ratio(nq, r["norm_uk"]),
                                fuzz.ratio(nq, r["norm_ru"]))
                        if s >= 82:
                            add(r, int(s * 0.8), pack_id)

        # 🆕 Латинка. Газетир її не вмів узагалі: `Miastkowka` віддавала нуль —
        # і це найгірший вид нуля, бо виглядає як «такого села немає». А писали
        # так усе: польські акти, костельні книги, анотації FamilySearch,
        # закордонні дослідники.
        #
        # Точний збіг тут неможливий за побудовою: `М'ястківка` нормалізується в
        # `mastkivka`, а `Miastkowka` — у `miastkovka` (ia/a, v/w); `Городківка`
        # дає `gorodkivka` проти `horodkivka`. Зате спільні триграми є, і саме
        # їх і зважує `rapidfuzz` по колонці `translit`.
        #
        # 🔴 Гілка вмикається лише на латинському запиті. Кириличний у неї не
        # заходить ніколи, тож поведінка старого газетира лишається дослівною —
        # це не «майже паритет», а паритет за побудовою.
        if nq and _has_latin(nq) and len(rows) < limit:
            _add_latin_hits(packs, nq, where, args, limit, add)

        out = sorted(rows.values(), key=lambda d: (-d["score"], -d["n_cases"]))
        if fond:
            keep: set[str] = set()
            for _pid, con in packs:
                keep |= {r["card"] for r in con.execute(
                    "SELECT DISTINCT card FROM cases WHERE fond = ?", [fond])}
            out = [d for d in out if d["card"] in keep]
    finally:
        close_all(packs)
    return Answer(rows=out[:limit], coverage=cov)


def place_card(card: str, repo: str = "CDIAK") -> Answer:
    """Картка поселення + усі його справи, зшиті з нашим обліком."""
    packs = open_packs("geog")
    cov = coverage("geog")
    place: dict[str, Any] | None = None
    cases: list[dict[str, Any]] = []
    try:
        for pack_id, con in packs:
            row = con.execute("SELECT * FROM places WHERE card = ?",
                              [card]).fetchone()
            if row is None:
                continue
            place = _tag(dict(row), pack_id)
            cases = [_tag(dict(r), pack_id) for r in con.execute(
                "SELECT c.card, c.fond, c.opys, c.spr, c.year_from, c.year_to, "
                "       d.name AS doc_type, p.name AS parish "
                "FROM cases c "
                "LEFT JOIN doc_types d ON d.id = c.doc_type_id "
                "LEFT JOIN parishes  p ON p.id = c.parish_id "
                "WHERE c.card = ? "
                "ORDER BY CAST(c.fond AS INTEGER), CAST(c.opys AS INTEGER), "
                "         c.spr_int", [card])]
            break
    finally:
        close_all(packs)

    if place is None:
        return Answer(rows=[], coverage=cov,
                      partial=(f"картки «{card}» немає в жодному встановленому паку",))

    # 🔗 зшивка з обліком: та сама бібліотека, що живить реєстр опису, тож
    # «на диску» тут і у вкладці «🏛 Фонди» не розійдуться.
    # 🔴 Ключ — (фонд, опис, номер, літера): номер справи неунікальний між
    # описами, і переплутавши їх, дістаєш тихий нуль «на диску немає» для справ,
    # які лежать поруч на диску.
    disk: dict[tuple[str, str, str, str], str] = {}
    try:
        from nyshporka.fonds.registry import live_on_disk

        for fond in {c["fond"] for c in cases}:
            disk.update({(fond, k[0], k[1], k[2]): v
                         for k, v in live_on_disk(repo, fond).items()})
    except Exception:
        pass
    for c in cases:
        n = re.sub(r"\D", "", c["spr"] or "")
        letter = (c["spr"] or "")[len(n):].lower()
        c["shifra"] = f"{c['fond']}-{c['opys']}-{c['spr']}"
        # 🔴 Спільний ключ трьох реєстрів — щоб із картки села можна було піти
        # в бібліотеку й у реєстр опису, а не лише подивитись на позначку «✓».
        # Доти рядок картки був тупиком: видно, що справа на диску, і нічим її
        # відкрити.
        c["repo"] = repo
        c["key"] = f"{repo}/{c['fond']}/{c['spr']}"
        c["on_disk"] = disk.get((c["fond"], c["opys"], n, letter), "")
    place["cases"] = cases
    place["n_on_disk"] = sum(1 for c in cases if c["on_disk"])
    # 🕍 те саме поселення в інших конфесіях
    place["siblings"] = siblings(card).rows
    return Answer(rows=[place], coverage=cov)


def siblings(card: str) -> Answer:
    """Те саме поселення в інших розділах каталогу (конфесіях)."""
    packs = open_packs("geog")
    cov = coverage("geog")
    out: list[dict[str, Any]] = []
    try:
        for pack_id, con in packs:
            me = con.execute("SELECT * FROM places WHERE card = ?",
                             [card]).fetchone()
            if me is None:
                continue
            out += [_tag(dict(r), pack_id) for r in con.execute(
                "SELECT card, section, institution, village_uk, church, n_cases "
                "FROM places WHERE card != ? AND section != ? "
                "AND (norm_uk = ? OR norm_ru = ?)",
                [card, me["section"], me["norm_uk"], me["norm_ru"]])]
    finally:
        close_all(packs)
    return Answer(rows=out, coverage=cov)


#: 🔴 гіпотеза, яка не підтвердилась — лишено як запис, щоб не повторювати.
#:
#: План передбачав двоступеневий відбір конфузерів: `places_fts` (триграма) дає
#: ≤400 кандидатів, `rapidfuzz` зважує їх тією самою формулою. Виглядало
#: безпечно: на високій схожості спільні триграми справді є
#: («М'ястківка»↔«Мястковка» — ratio 88.9, 4 спільні триграми).
#:
#: **Замір на всіх 4566 картках спростував це.** Прискорення було ×6.9
#: (190.8 → 27.7 с), але результат розійшовся на **2362 картках**, і в **1348**
#: конфузерів було втрачено. Причина: `fuzz.ratio` набирає 78 і на розсіяних
#: збігах, без жодного спільного тризнакового шматка — надто на довгих назвах.
#:
#: Конфузери — це список попереджень («чому знайшлось не те село»). Тихо
#: вкорочений список попереджень гірший за повільний: він виглядає повним.
#: Тому тут повний скан, 4566 порівнянь, ~42 мс на картку — і це прийнятно, бо
#: картка відкривається раз, а не на кожен натиск клавіші.
#:
#: `places_fts` зі схеми теж прибрано — див. коментар у `catalog/schema.py`.
_CONFUSERS_ARE_A_FULL_SCAN = True


def confusers(card: str, limit: int = 8, min_score: int = 78) -> Answer:
    """Поселення, чиї назви дають хибні спрацювання на цьому.

    Це не прикраса: у самому каталозі поруч стоять М'ястківка, М'яколовичі й
    М'якохід — усі з метричними книгами XVIII ст. Побачити цей список до пошуку
    дешевше, ніж потім розбирати, чому «знайшлось» не те село.

    ⏱ Двоступенево: FTS-триграма дає кандидатів, `rapidfuzz` їх зважує тією
    самою формулою, що й раніше. Повний скан 4566 рядків лишається фолбеком для
    назв, коротших за триграму, — там FTS безсила за побудовою.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return Answer(rows=[], coverage=coverage("geog"),
                      partial=("rapidfuzz не встановлено",))

    packs = open_packs("geog")
    cov = coverage("geog")
    out: list[dict[str, Any]] = []
    partial: list[str] = []
    try:
        for pack_id, con in packs:
            me = con.execute("SELECT * FROM places WHERE card = ?",
                             [card]).fetchone()
            if me is None:
                continue
            for r in con.execute("SELECT * FROM places WHERE card != ?", [card]):
                # 🔴 Формула дослівно та сама, що була: три пари й `round`.
                # `int()` тут була б не оптимізацією, а зсувом межі — 77.6
                # обрізалось би в 77 і випадало з видачі при порозі 78.
                s = max(fuzz.ratio(me["norm_uk"], r["norm_uk"]),
                        fuzz.ratio(me["norm_uk"], r["norm_ru"]),
                        fuzz.ratio(me["norm_ru"], r["norm_ru"]))
                if s >= min_score:
                    d = _tag(dict(r), pack_id)
                    d["score"] = round(s)
                    out.append(d)
            break
    finally:
        close_all(packs)
    out.sort(key=lambda d: -d["score"])
    return Answer(rows=out[:limit], coverage=cov, partial=tuple(partial))


def places_for_fond(fond: str) -> dict[tuple[str, str], dict[str, Any]]:
    """(опис, номер) → {село, парафія, тип} для всіх справ фонду в каталозі.

    Тут навмисно не `Answer`: це не відповідь людині, а зріз для домальовування
    колонки в таблиці реєстру опису. Порожньо, коли каталогу немає, — і саме
    тому колонка тоді просто зникає, а не показує «сіл немає».
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        packs = open_packs("geog")
    except CatalogMissing:
        return out
    try:
        for _pid, con in packs:
            for r in con.execute(
                    "SELECT c.opys, c.spr, d.name AS doc_type, p2.name AS parish, "
                    "       p.village_uk, p.card "
                    "FROM cases c JOIN places p ON p.card = c.card "
                    "LEFT JOIN doc_types d ON d.id = c.doc_type_id "
                    "LEFT JOIN parishes  p2 ON p2.id = c.parish_id "
                    "WHERE c.fond = ?", [str(fond)]):
                key = (str(r["opys"]), re.sub(r"\D", "", r["spr"] or ""))
                prev = out.get(key)
                if prev is None:
                    out[key] = {"village": r["village_uk"],
                                "parish": r["parish"] or "",
                                "doc_type": r["doc_type"] or "", "card": r["card"]}
                elif r["village_uk"] not in prev["village"]:
                    # одна справа буває на кілька сіл (збірний том) — не губимо
                    # їх, але й не роздуваємо: перші два й лічильник
                    prev["more"] = int(prev.get("more") or 0) + 1
                    if prev["more"] == 1:
                        prev["village"] += f" · {r['village_uk']}"
    finally:
        close_all(packs)
    return out
