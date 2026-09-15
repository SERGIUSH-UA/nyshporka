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

__all__ = ["Answer", "CatalogMissing", "Coverage", "church_card", "churches_near",
           "confusers", "find_churches", "find_places", "link_churches_to_places",
           "locate", "locate_all", "place_card", "places_for_fond", "places_near",
           "siblings", "uezd_known"]


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


def uezd_known(uezd: str) -> bool:
    """Чи є в газетирі хоч одне поселення цього повіту чи губернії.

    🔴 Розрізняє два нулі `geog.find` із фільтром повіту: «села з такою назвою
    в повіті немає» і «цього повіту газетир не знає взагалі». Другий — межа
    довідника, і звітувати його як відсутність села означало б закрити напрям,
    який не перевіряли.
    """
    packs = open_packs("geog")
    try:
        for _pid, con in packs:
            try:
                if con.execute("SELECT 1 FROM places WHERE uezd_gub LIKE ? "
                               "OR hist_place LIKE ? LIMIT 1",
                               [f"%{uezd}%", f"%{uezd}%"]).fetchone():
                    return True
            except sqlite3.Error:
                continue
    finally:
        close_all(packs)
    return False


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
    # 📍 точка з пака `places`, якщо він є: без неї картка — лише слова про
    # район, і коло сусідів від цього села не побудувати
    place["location"] = locate(card)
    if place["location"] is not None:
        cov = cov + coverage("places")
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


# ── ⛪ церкви ~1772: база Шади ────────────────────────────────────────────────
#
# 🔑 Газетир каже, ДЕ ЛЕЖАТЬ книги села; ця таблиця каже, ЧИ БУЛА в селі
# церква до поділів, чия вона була (деканат, патрон) і як звалась. Це різні
# питання, і саме тому вони в різних паках: газетир — зріз архіву, церкви —
# зріз друкованих реєстрів XVIII ст. Зшиває їх `link_churches_to_places`.
#
# 🔴 Назви тут польські, а питають кирилицею. Обидві форми зводяться до одного
# ASCII (`normalize_for_matching`): «Липовеньке» → lipovenke, «Lipoweńkie» →
# lipovenkie. Точного збігу не буває за побудовою, тож після LIKE іде фаззі з
# тим самим порогом 84, що виміряний для латинки в газетирі: нижче він
# видавав правдоподібне чуже село замість чесного нуля.

_CHURCH_MIN = _LATIN_MIN


def _church_query(q: str) -> str:
    from nyshporka.utils.translit import normalize_for_matching

    return normalize_for_matching(_norm(q))


def _church_row(r: sqlite3.Row, pack_id: str, score: int = 0, via: str = "name"
                ) -> dict[str, Any]:
    d = _tag(dict(r), pack_id)
    d["score"] = score
    d["via"] = via
    from nyshporka.geog.szady import describe

    d.update(describe(d))
    return d


def find_churches(q: str, limit: int = 40, voivodeship: str = "",
                  deanery: str = "", confession: str = "") -> Answer:
    """Церкви ~1772 за назвою села — кирилицею чи латинкою.

    Спершу точний і префіксний збіг (окремо за назвою й за варіантами), потім
    фаззі; варіант завжди трохи нижче за назву, бо він — форма з іншого
    джерела, а не те, під чим церкву заведено в базі.
    """
    packs = open_packs("churches")
    cov = coverage("churches")
    nq = _church_query(q)
    rows: dict[int, dict[str, Any]] = {}

    def add(r: sqlite3.Row, score: int, pack_id: str, via: str) -> None:
        prev = rows.get(r["ob_id"])
        if prev is None or prev["score"] < score:
            rows[r["ob_id"]] = _church_row(r, pack_id, score, via)

    where, args = "", []
    if voivodeship:
        where += " AND voivodeship = ?"
        args.append(voivodeship)
    if deanery:
        where += " AND deanery LIKE ?"
        args.append(f"%{deanery}%")
    if confession:
        where += " AND confession = ?"
        args.append(confession)

    try:
        for pack_id, con in packs:
            if not nq:
                for r in con.execute("SELECT * FROM churches WHERE 1=1" + where
                                     + " ORDER BY name LIMIT ?", [*args, limit]):
                    add(r, 0, pack_id, "name")
                continue
            for pat, sc in ((nq, 100), (nq + "%", 92), ("%" + nq + "%", 84)):
                # ⚠ дужки: без них `AND voivodeship = ?` прилипав лише до
                # другого LIKE, і фільтр воєводства мовчки пропускав збіги за
                # основною назвою
                for r in con.execute("SELECT * FROM churches WHERE (norm LIKE ? "
                                     "OR norm_alt LIKE ?)" + where + " LIMIT 400",
                                     [pat, pat, *args]):
                    add(r, sc, pack_id, "name")
                # варіанти лежать через « | », тож LIKE по полю — це інфікс по
                # кожному з них; точний і префіксний тут теж інфікс, і саме
                # тому оцінка на 4 нижча за назву
                for r in con.execute("SELECT * FROM churches WHERE norm_v LIKE ?"
                                     + where + " LIMIT 400",
                                     ["%" + nq + "%", *args]):
                    add(r, sc - 4, pack_id, "variant")
                if len(rows) >= limit and sc >= 92:
                    break
        if nq and len(rows) < limit:
            try:
                from rapidfuzz import fuzz
            except ImportError:
                fuzz = None  # type: ignore[assignment]
            if fuzz is not None:
                for pack_id, con in packs:
                    for r in con.execute("SELECT * FROM churches WHERE 1=1"
                                         + where, args):
                        s = max(fuzz.ratio(nq, r["norm"] or ""),
                                fuzz.ratio(nq, r["norm_alt"] or ""))
                        via = "name"
                        for v in (r["norm_v"] or "").split(" | "):
                            if v and fuzz.ratio(nq, v) > s:
                                s, via = fuzz.ratio(nq, v), "variant"
                        if s >= _CHURCH_MIN:
                            add(r, int(s * 0.8), pack_id, via)
    finally:
        close_all(packs)
    out = sorted(rows.values(), key=lambda d: (-d["score"], d["name"]))
    return Answer(rows=out[:limit], coverage=cov)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    p1, p2 = radians(lat1), radians(lat2)
    dl, dg = p2 - p1, radians(lng2 - lng1)
    a = sin(dl / 2) ** 2 + cos(p1) * cos(p2) * sin(dg / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def churches_near(lat: float, lng: float, km: float = 15.0, limit: int = 60,
                  confession: str = "", exclude: int | None = None) -> Answer:
    """Церкви в колі навколо точки, за відстанню.

    Прямокутник відсікає SQL-ом (індекс по lat, lng), коло — гаверсинус у
    Python: на 8 тис. рядків це мілісекунди, а точність кола тут важить —
    «15 км» людина розуміє як коло, не як квадрат.
    """
    from math import cos, radians

    packs = open_packs("churches")
    cov = coverage("churches")
    dlat = km / 111.0
    dlng = km / (111.0 * max(cos(radians(lat)), 0.1))
    where, args = "", []
    if confession:
        where += " AND confession = ?"
        args.append(confession)
    out: list[dict[str, Any]] = []
    try:
        for pack_id, con in packs:
            for r in con.execute(
                    "SELECT * FROM churches WHERE lat BETWEEN ? AND ? "
                    "AND lng BETWEEN ? AND ?" + where,
                    [lat - dlat, lat + dlat, lng - dlng, lng + dlng, *args]):
                if exclude is not None and r["ob_id"] == exclude:
                    continue
                d = _haversine_km(lat, lng, r["lat"], r["lng"])
                if d <= km:
                    row = _church_row(r, pack_id)
                    row["km"] = round(d, 1)
                    out.append(row)
    finally:
        close_all(packs)
    out.sort(key=lambda d: (d["km"], d["name"]))
    return Answer(rows=out[:limit], coverage=cov)


def church_card(ob_id: int, km: float = 10.0) -> Answer:
    """Картка церкви: рядок бази + сусіди в колі + поселення газетира."""
    packs = open_packs("churches")
    cov = coverage("churches")
    row: dict[str, Any] | None = None
    try:
        for pack_id, con in packs:
            r = con.execute("SELECT * FROM churches WHERE ob_id = ?",
                            [int(ob_id)]).fetchone()
            if r is not None:
                row = _church_row(r, pack_id)
                break
    finally:
        close_all(packs)
    if row is None:
        return Answer(rows=[], coverage=cov,
                      partial=(f"церкви ob_id={ob_id} немає в жодному паку",))
    if row.get("lat") is not None and row.get("lng") is not None:
        row["nearby"] = churches_near(row["lat"], row["lng"], km=km, limit=12,
                                      exclude=row["ob_id"]).rows
    else:
        row["nearby"] = []
    links, partial = link_churches_to_places([row])
    row["places"] = links.get(row["ob_id"], [])
    return Answer(rows=[row], coverage=cov, partial=partial)


#: Код воєводства бази Шади → корінь його назви в `hist_place` газетира
#: («Брацлавського воєв.»). Лише ті, що трапляються на Правобережжі: газетир
#: ЦДІАК західніше Волині й Поділля не сягає.
_VOIV_STEM = {"brac": "брацлав", "kij": "київ", "pod": "поділ", "woł": "волин",
              "rus": "руськ", "beł": "белз", "podl": "підляс"}


#: У які губернії після поділів лягло воєводство (корені назв; «Подольської» —
#: російське написання, яке трапляється в самому газетирі). Поселення з
#: губернії поза цим переліком не може бути тією самою парафією, хоч би як
#: збігалась назва (Chmarówka ↔ «Марківка Старобільського пов. Харківської
#: губ.» на 87). Перелік грубий навмисно: повіт точніший, але тут потрібна
#: лише впевнена відмова, а не впевнене підтвердження.
_VOIV_GUB = {"brac": ("подільськ", "подольськ", "київськ"),
             "kij": ("київськ", "волинськ"),
             "pod": ("подільськ", "подольськ"),
             "woł": ("волинськ", "київськ", "подільськ", "подольськ"),
             "beł": (), "rus": (), "podl": ()}


def _region_check(voivodeship: str, hist_place: str, uezd_gub: str = "") -> str:
    """same | mismatch | unknown — чи те саме воєводство називають обидві бази.

    Газетир називає воєводство в `hist_place` лише у 525 картках із 4566
    («Брацлавського воєв., з 1797 р. …»); в решті — самі повіт і губернія, і
    тоді судити можна лише від протилежного: губернія, у яку це воєводство
    не лягало, — відмова; губернія, у яку лягало, — «невідомо», а не «те саме».
    """
    stem = _VOIV_STEM.get(voivodeship)
    hp = (hist_place or "").casefold()
    if stem and "воєв" in hp:
        if stem in hp:
            return "same"
        if any(s in hp for s in _VOIV_STEM.values()):
            return "mismatch"
    allowed = _VOIV_GUB.get(voivodeship)
    ug = (uezd_gub or "").casefold()
    if allowed and "губ" in ug and not any(g in ug for g in allowed):
        return "mismatch"
    return "unknown"


def link_churches_to_places(churches: list[dict[str, Any]], min_score: int = 0,
                            per_church: int = 3
                            ) -> tuple[dict[int, list[dict[str, Any]]], tuple[str, ...]]:
    """ob_id → поселення газетира з тією самою назвою (за транслітом).

    🔗 Це і є гібрид: церква 1772 р. каже, що село мало парафію і як вона
    звалась; газетир каже, де лежать книги села в архіві. Зшивка йде за
    ASCII-формою назви обох баз (`norm` ↔ `translit`), і поріг той самий, що
    для латинського запиту в газетирі.

    Газетира може не бути — тоді порожня мапа й пояснення в `partial`, а не
    відмова: церква без книг лишається відповіддю про церкву.
    """
    if not churches:
        return {}, ()
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return {}, ("rapidfuzz не встановлено — зшивки з газетиром немає",)
    try:
        packs = open_packs("geog")
    except CatalogMissing as exc:
        return {}, (f"газетира немає, зшивки з книгами не буде ({exc})",)
    forms: list[str] = []
    owners: list[dict[str, Any]] = []
    try:
        for pack_id, con in packs:
            for r in con.execute(
                    "SELECT card, section, institution, village_uk, village_ru, "
                    "uezd_gub, hist_place, n_cases, translit FROM places "
                    "WHERE translit != ''"):
                place = _tag(dict(r), pack_id)
                for f in (r["translit"] or "").split():
                    forms.append(f)
                    owners.append(place)
    finally:
        close_all(packs)
    threshold = min_score or _CHURCH_MIN
    out: dict[int, list[dict[str, Any]]] = {}
    for ch in churches:
        # (форма, клас): основна назва та її чергування — «name», форми за
        # Socjografia — «variant». Клас вирішує порядок, а не поріг.
        keys = [(ch.get("norm") or "", "name"), (ch.get("norm_alt") or "", "name")]
        keys += [(v, "variant") for v in (ch.get("norm_v") or "").split(" | ") if v]
        best: dict[str, dict[str, Any]] = {}
        for key, via in keys:
            if len(key) < 3:
                continue
            for _form, score, idx in process.extract(
                    key, forms, scorer=fuzz.ratio, score_cutoff=threshold,
                    limit=per_church * 4):
                place = owners[idx]
                prev = best.get(place["card"])
                # основна назва має перевагу навіть при меншій оцінці — див.
                # сортування нижче; тут лишаємо кращий запис у межах класу
                if prev is None or (prev["via"] != "name" and via == "name") or (
                        prev["via"] == via and prev["score"] < score):
                    d = dict(place)
                    d["score"] = int(score)
                    d["via"] = via
                    best[place["card"]] = d
        # 🪤 Однойменне село в іншому воєводстві. Kapitanka Балтського деканату
        # (Брацлавське воєв.) зшивалась на 100 із Капітанівкою Чигиринського
        # повіту (Київське воєв.), бо своєї Капітанки в газетирі ЦДІАК немає, —
        # а Капітанок на одну назву чотири. Газетир називає воєводство в
        # `hist_place`, база — у `voivodeship`; розбіжність не викидає рядок
        # (прив'язка до 1793 у газетирі теж буває приблизна), а знімає 10 і
        # позначає `region=mismatch`, щоб людина бачила, ЩО саме зшилось.
        for d in best.values():
            d["region"] = _region_check(ch.get("voivodeship") or "",
                                        d.get("hist_place") or "",
                                        d.get("uezd_gub") or "")
            if d["region"] == "mismatch":
                d["score"] -= 10
        # 🔴 Основна назва поперед варіанта, і лише потім оцінка. Lipoweńkie з
        # варіантом «Lipówka» інакше зшивалось із Липівкою (100) поперед
        # власного Липовенького (94): варіант — форма з іншого джерела, і
        # збіг по ньому — здогад, а не прочитане.
        ranked = sorted(best.values(),
                        key=lambda d: (d["via"] != "name", -d["score"],
                                       -(d["n_cases"] or 0)))
        # 🔴 У межах класу — лише те, що не нижче найкращого мінус 6. Замір на
        # колі Шумилова: Lipoweńkie давало «Липовеньке» 94 і «Липівку
        # Київського пов.» 85, Krasnosiółka — «Красносілку» 95 і «Краснопілку»
        # 86. Другий рядок у кожній парі — інше село за сотню кілометрів, і
        # показаний поруч він читається як кандидат. Рівні ж оцінки лишаються
        # всі: три Маньківки по 87 — справжня неоднозначність, і ховати її
        # не можна.
        floors: dict[str, int] = {}
        for d in ranked:
            floors.setdefault(d["via"], d["score"] - 6)
        ranked = [d for d in ranked if d["score"] >= floors[d["via"]]]
        # 📍 Відстань, якщо в села є точка: це сильніший приймач за воєводство.
        # Церква за 60+ км від села з тією ж назвою — інше село, і навпаки —
        # точка за кілька кілометрів підтверджує зшивку там, де газетир про
        # воєводство мовчить.
        if ch.get("lat") is not None and ranked:
            for d in ranked:
                loc = locate(d["card"])
                if loc is None or loc.get("lat") is None:
                    continue
                d["lat"], d["lng"], d["qid"] = loc["lat"], loc["lng"], loc["qid"]
                d["km"] = round(_haversine_km(ch["lat"], ch["lng"],
                                              loc["lat"], loc["lng"]), 1)
                if d["km"] > _FAR_KM:
                    if d["region"] != "mismatch":
                        d["score"] -= 10
                    d["region"] = "far"
                elif d["km"] <= _NEAR_KM and d["region"] == "unknown":
                    d["region"] = "near"
            ranked.sort(key=lambda d: (d["via"] != "name", -d["score"],
                                       d.get("km", 1e9), -(d["n_cases"] or 0)))
        out[int(ch["ob_id"])] = ranked[:per_church]
    return out, ()


# ── 🗺 сучасні поселення з координатами: точка для села газетира ─────────────
#
# Газетир ЦДІАК не має жодної точки — лише «Голованівського р-ну Кіровоградської
# обл.» словами. Пак `places` (Wikidata) дає точку майже кожному селу України,
# і зшивка з ним іде за назвою + областю, зі старим районом як підказкою:
# однойменних сіл в області буває кілька, а район у газетирі — до реформи 2020,
# тож шукається серед УСІХ адмінодиниць предмета, чинних і колишніх.

#: Відстань, за якою зшивка «церква ↔ село» вважається чужою / своєю. Парафія
#: XVIII ст. — кілька кілометрів; 60 км — це вже інший повіт.
_FAR_KM = 60.0
_NEAR_KM = 20.0

#: memo `locate` за штампом паків: картка → точка (або None). Коло по газетиру
#: кличе це для всіх 4566 карток, і без memo кожен виклик коштував би стільки ж.
_LOCATE_CACHE: dict[str, tuple[Any, dict[str, Any] | None]] = {}
_MODERN_INDEX: tuple[Any, dict[str, list[dict[str, Any]]]] | None = None


def _packs_stamp(*domains: str) -> Any:
    from nyshporka.catalog.store import installed

    return tuple((p.pack_id, str(p.path), p.rows)
                 for dom in domains for p in installed(dom))


_OBL_RE = re.compile(r"([\w'’-]+)\s+обл", re.UNICODE)
_RAION_RE = re.compile(r"([\w'’-]+)\s+р-н", re.UNICODE)


def _stem(word: str) -> str:
    """«Кіровоградської» → «кіровоград», «Бершадського» → «бершад»."""
    w = _norm(word)
    for suf in ("ської", "ського", "ська", "ський", "ське", "цької", "цького",
                "цька", "цький", "ої", "ого", "а", "ий", "е"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _modern_index() -> dict[str, list[dict[str, Any]]]:
    """norm-назва → усі поселення пака `places` (uk, ru і псевдоніми)."""
    global _MODERN_INDEX
    stamp = _packs_stamp("places")
    if _MODERN_INDEX is not None and _MODERN_INDEX[0] == stamp:
        return _MODERN_INDEX[1]
    idx: dict[str, list[dict[str, Any]]] = {}
    packs = open_packs("places")
    try:
        for pack_id, con in packs:
            for r in con.execute("SELECT qid, name_uk, name_ru, kind, admin, top, "
                                 "country, lat, lng, norm_uk, norm_ru, norm_alias "
                                 "FROM modern"):
                d = _tag(dict(r), pack_id)
                keys = {d["norm_uk"], d["norm_ru"],
                        *(a for a in (d["norm_alias"] or "").split(" | ") if a)}
                for k in keys:
                    if k:
                        idx.setdefault(k, []).append(d)
    finally:
        close_all(packs)
    _MODERN_INDEX = (stamp, idx)
    return idx


def locate(card: str) -> dict[str, Any] | None:
    """Точка для картки газетира: {qid, lat, lng, name_uk, how, candidates}.

    Назва (uk або ru, або псевдонім) + область із поля «нині» — обов'язкові;
    район — підказка, що обирає серед однойменних. Кілька рівних кандидатів →
    `how="ambiguous"`, точка береться від першого, і це видно.
    `None` — пака немає або збігу немає.
    """
    stamp = _packs_stamp("places", "geog")
    hit = _LOCATE_CACHE.get(card)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        idx = _modern_index()
    except CatalogMissing:
        return None
    packs = open_packs("geog")
    place = None
    try:
        for _pid, con in packs:
            row = con.execute("SELECT village_uk, village_ru, modern_place, "
                              "norm_uk, norm_ru FROM places WHERE card = ?",
                              [card]).fetchone()
            if row is not None:
                place = dict(row)
                break
    finally:
        close_all(packs)
    out = _locate_row(place, idx) if place else None
    _LOCATE_CACHE[card] = (stamp, out)
    return out


_PAREN_RE = re.compile(r"\(([^)]*)\)")


def _locate_keys(place: dict[str, Any]) -> list[str]:
    """Ключі пошуку з назв газетира.

    🪤 125 карток мають дужки: «Баланівка ( Старобаланівка), с.», «Бороменька
    (Виднівка)». Нормалізація зливає обидві частини в один ключ, якого немає
    ніде; шукати треба кожну частину окремо — і зовнішню, і в дужках.
    """
    keys: list[str] = []
    for raw in (place.get("village_uk") or "", place.get("village_ru") or ""):
        if not raw:
            continue
        keys.append(_norm(raw))
        if "(" in raw:
            keys.append(_norm(_PAREN_RE.sub("", raw)))
            keys += [_norm(inner) for inner in _PAREN_RE.findall(raw)]
    return [k for k in dict.fromkeys(keys) if k]


def _locate_row(place: dict[str, Any], idx: dict[str, list[dict[str, Any]]]
                ) -> dict[str, Any] | None:
    modern = place.get("modern_place") or ""
    m_obl = _OBL_RE.search(modern)
    m_rai = _RAION_RE.search(modern)
    obl = _stem(m_obl.group(1)) if m_obl else ""
    rai = _stem(m_rai.group(1)) if m_rai else ""
    cands: dict[str, dict[str, Any]] = {}
    for key in _locate_keys(place):
        for d in idx.get(key, []):
            cands.setdefault(d["qid"], d)
    if not cands:
        return None
    rows = list(cands.values())
    # область — жорсткий фільтр, коли вона відома: однойменних сіл по країні
    # десятки, і без неї точка буде чужа частіше, ніж своя
    if obl:
        same = [d for d in rows if obl in _norm(d["top"] or "")]
        if same:
            rows = same
        else:
            return None
    if rai and len(rows) > 1:
        by_raion = [d for d in rows if rai in _norm(d["admin"] or "")]
        if by_raion:
            rows = by_raion
    # без області в газетирі (285 карток) — точка лише при єдиному кандидаті
    if not obl and len(rows) > 1:
        return {"qid": "", "lat": None, "lng": None, "how": "ambiguous",
                "candidates": [{"qid": d["qid"], "top": d["top"]} for d in rows]}
    best = rows[0]
    return {"qid": best["qid"], "lat": best["lat"], "lng": best["lng"],
            "name_uk": best["name_uk"], "kind": best["kind"], "top": best["top"],
            "how": "unique" if len(rows) == 1 else "ambiguous",
            "candidates": [{"qid": d["qid"], "admin": d["admin"]} for d in rows]
            if len(rows) > 1 else []}


def locate_all() -> dict[str, dict[str, Any]]:
    """card → точка для ВСІХ карток газетира (для кола по газетиру)."""
    idx = _modern_index()
    packs = open_packs("geog")
    out: dict[str, dict[str, Any]] = {}
    try:
        for _pid, con in packs:
            for r in con.execute("SELECT card, village_uk, village_ru, modern_place, "
                                 "norm_uk, norm_ru, section, institution, n_cases, "
                                 "uezd_gub FROM places"):
                place = dict(r)
                loc = _locate_row(place, idx)
                if loc and loc.get("lat") is not None:
                    out[place["card"]] = {**place, **loc}
    finally:
        close_all(packs)
    return out


def places_near(lat: float, lng: float, km: float = 15.0, limit: int = 100,
                section: str = "") -> Answer:
    """Поселення ГАЗЕТИРА в колі — тобто сусіди, у яких є книги в архіві.

    Коло будується з точок пака `places`, а рядки — з газетира: нуль тут
    означає «у газетирі немає села з точкою в цьому колі», і покриття називає
    обидва паки.
    """
    cov = coverage("geog") + coverage("places")
    located = locate_all()
    out: list[dict[str, Any]] = []
    for card, p in located.items():
        if section and p.get("section") != section:
            continue
        d = _haversine_km(lat, lng, p["lat"], p["lng"])
        if d <= km:
            row = {"card": card, "village_uk": p["village_uk"],
                   "village_ru": p["village_ru"], "section": p["section"],
                   "institution": p["institution"], "n_cases": p["n_cases"],
                   "uezd_gub": p["uezd_gub"], "modern_place": p["modern_place"],
                   "qid": p["qid"], "lat": p["lat"], "lng": p["lng"],
                   "how": p["how"], "km": round(d, 1),
                   "origin": p.get("origin", "catalog"),
                   "pack_id": p.get("pack_id", "")}
            out.append(row)
    out.sort(key=lambda d: (d["km"], -(d["n_cases"] or 0)))
    return Answer(rows=out[:limit], coverage=cov)
