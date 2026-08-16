"""Газетир зведеного каталогу ЦДІАК — «де документи цього села».

Читає те, що зібрав `scripts/cdiak_geog_catalog.py`, і відповідає на питання, з
якого починається пошук: **які взагалі метрики цього поселення вціліли і що з
них у нас уже є**. Реєстр опису на це відповісти не може — він знає один фонд і
мовчить про сусідні.

🔴 Три речі, які цей модуль зобов'язаний робити, і кожна має свою ціну:

1. **Зшивати каталог із нашим обліком.** Рядок «224-1-864» без позначки
   «на диску» — довідка, а не робочий інструмент: щоб зрозуміти, чого бракує,
   довелось би звіряти руками 5762 справи ф.224. Стан береться з тієї самої
   бібліотеки, що й у реєстрі опису (`live_on_disk`), тож два входи не
   розійдуться.
2. **Шукати за ОБОМА назвами.** Заголовки справ XIX ст. писані російською
   («Мястковка»), наш канон — українською. Пошук лише за однією формою
   систематично не знаходить половини; каталог дає пару на кожне поселення, і
   не скористатись нею було б марнотратством.
3. **Показувати конфузерів.** У самому каталозі поруч стоять М'ястківка,
   М'яколовичі та М'якохід — усі метричні книги XVIII ст. на «Мя». Fuzzy-пошук
   плутає їх за побудовою, тож список схожих назв має бути видний ДО пошуку, а
   не з'ясовуватись після (пор. `surname-split-by-hyphen-paired-search`, де та
   сама логіка застосована до прізвищ).

SQLite, а не читання TSV на кожен запит: повний зріз справ — 343 тис. рядків
(35 МБ), і консоль на ньому стоятиме секундами. Індекс — ЗРІЗ, як
`case_index.sqlite`: він старіє, коли перезбирають каталог або качають справу,
і `index_stale()` каже про це вголос замість тихо показувати вчорашній стан.
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import workspace

#: тека, куди `cdiak_geog_catalog.py` кладе свої виходи
GEOG_DIR = "cdiak_geog"
SCHEMA_VERSION = 1


def catalog_dir() -> Path:
    return workspace().raw / GEOG_DIR


def index_path() -> Path:
    return workspace().root / "data" / "derived" / "geog.sqlite"


def _sources() -> tuple[Path, Path]:
    """(поселення, справи). Повний зріз, а не пофондовий."""
    d = catalog_dir()
    return d / "geog_places.tsv", d / "geog_cases.tsv"


# ── нормалізація назв ─────────────────────────────────────────────────────────

#: `М'ястківка, м-ко.` → `мястківка`; тип поселення й пунктуація не шукані
_TYPE_TAIL = re.compile(r",?\s*(?:м-ко|м\.|с\.|сл\.|х\.|хут\.|сщ\.|мст\.)\s*\.?\s*$",
                        re.IGNORECASE)
_PUNCT = re.compile(r"[’'ʼ’`\"().,;:]+")


def norm_name(s: str) -> str:
    """Назва → форма для порівняння.

    Апостроф знімається навмисно: у каталозі те саме село пишуть і `М'ястківка`,
    і `М"ястківка` (лапки замість апострофа — так у джерелі), а в наших файлах
    трапляється й `Мястківка`. Три написання однієї назви, які інакше не
    зустрінуться.
    """
    s = _TYPE_TAIL.sub("", str(s or "").strip())
    s = _PUNCT.sub("", s)
    return s.lower().replace("ё", "е").strip()


# ── побудова індексу ──────────────────────────────────────────────────────────

def build_index(verbose: bool = False) -> dict[str, int]:
    """Зібрати `data/derived/geog.sqlite` з TSV каталогу."""
    places_tsv, cases_tsv = _sources()
    if not places_tsv.is_file():
        raise FileNotFoundError(
            f"немає {places_tsv} — спершу зібрати каталог: "
            "uv run python scripts/cdiak_geog_catalog.py")
    out = index_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE places (
            card TEXT PRIMARY KEY, village_uk TEXT, village_ru TEXT,
            hist_place TEXT, uezd_gub TEXT, modern_place TEXT, church TEXT,
            norm_uk TEXT, norm_ru TEXT, n_cases INTEGER DEFAULT 0);
        CREATE TABLE cases (
            card TEXT, fond TEXT, opys TEXT, spr TEXT,
            year_from INTEGER, year_to INTEGER, doc_type TEXT, parish TEXT);
        CREATE INDEX ix_cases_card ON cases(card);
        CREATE INDEX ix_cases_fond ON cases(fond, opys);
        CREATE INDEX ix_places_uk ON places(norm_uk);
        CREATE INDEX ix_places_ru ON places(norm_ru);
        CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    n_pl = n_cs = 0
    with places_tsv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            con.execute(
                "INSERT OR REPLACE INTO places(card,village_uk,village_ru,"
                "hist_place,uezd_gub,modern_place,church,norm_uk,norm_ru)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (r["card"], r["village_uk"], r["village_ru"], r["hist_place"],
                 r["uezd_gub"], r["modern_place"], r["church"],
                 norm_name(r["village_uk"]), norm_name(r["village_ru"])))
            n_pl += 1
    if cases_tsv.is_file():
        with cases_tsv.open(encoding="utf-8") as f:
            rows = []
            for r in csv.DictReader(f, delimiter="\t"):
                rows.append((r["card"], r["fond"], r["opys"], r["spr"],
                             int(r["year_from"] or 0), int(r["year_to"] or 0),
                             r["doc_type"], r.get("case_church", "")))
                if len(rows) >= 5000:
                    con.executemany("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?)", rows)
                    n_cs += len(rows)
                    rows = []
            if rows:
                con.executemany("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?)", rows)
                n_cs += len(rows)
    con.execute("UPDATE places SET n_cases = "
                "(SELECT COUNT(*) FROM cases WHERE cases.card = places.card)")
    src_mtime = max(int(p.stat().st_mtime) for p in (places_tsv, cases_tsv)
                    if p.is_file())
    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)",
                    [("version", str(SCHEMA_VERSION)),
                     ("src_mtime", str(src_mtime)),
                     ("places", str(n_pl)), ("cases", str(n_cs))])
    con.commit()
    con.close()
    tmp.replace(out)
    if verbose:
        print(f"✅ {out} — {n_pl} поселень · {n_cs} справ")
    return {"places": n_pl, "cases": n_cs}


def _con() -> sqlite3.Connection:
    p = index_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"немає {p} — зібрати: nysh geog build")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def index_stale() -> str:
    """Порожньо, якщо індекс свіжий; інакше — ЧОМУ він застарів.

    Той самий принцип, що в реєстрі справ: застарілий зріз небезпечніший за
    відсутній, бо виглядає як відповідь. Тут він старіє, коли перезібрали
    каталог — і тоді «метрик села немає» може бути просто старим індексом.
    """
    p = index_path()
    if not p.is_file():
        return "індексу немає"
    places_tsv, cases_tsv = _sources()
    try:
        con = _con()
        have = int(dict(con.execute("SELECT k,v FROM meta").fetchall()
                        ).get("src_mtime", "0"))
        con.close()
    except Exception:
        return "індекс нечитабельний"
    disk = max((int(q.stat().st_mtime) for q in (places_tsv, cases_tsv)
                if q.is_file()), default=0)
    if disk > have:
        return "каталог перезібрано після індексу"
    return ""


# ── пошук ─────────────────────────────────────────────────────────────────────

def find_places(q: str, limit: int = 40, uezd: str = "",
                fond: str = "") -> list[dict[str, Any]]:
    """Пошук поселення за назвою (укр або рос), з фаззі-добором.

    Спершу точний і префіксний збіг, і лише потім фаззі: інакше на короткому
    запиті («Устя») фаззі-хвіст витісняє з видачі саме те, що шукали.
    """
    con = _con()
    nq = norm_name(q)
    rows: dict[str, dict] = {}

    def _add(r, score):
        d = dict(r)
        d["score"] = score
        prev = rows.get(d["card"])
        if prev is None or prev["score"] < score:
            rows[d["card"]] = d

    where, args = "", []
    if uezd:
        where += " AND (uezd_gub LIKE ? OR hist_place LIKE ?)"
        args += [f"%{uezd}%", f"%{uezd}%"]
    if nq:
        for pat, sc in ((nq, 100), (nq + "%", 92), ("%" + nq + "%", 84)):
            sql = ("SELECT * FROM places WHERE (norm_uk LIKE ? OR norm_ru LIKE ?)"
                   + where + " LIMIT 400")
            for r in con.execute(sql, [pat, pat, *args]):
                _add(r, sc)
            if len(rows) >= limit and sc >= 92:
                break
    else:
        sql = "SELECT * FROM places WHERE 1=1" + where + " ORDER BY n_cases DESC LIMIT ?"
        for r in con.execute(sql, [*args, limit]):
            _add(r, 0)

    # фаззі — лише якщо точних мало; 4263 поселення порівнюються за мілісекунди
    if nq and len(rows) < limit:
        try:
            from rapidfuzz import fuzz
            for r in con.execute("SELECT * FROM places WHERE 1=1" + where, args):
                s = max(fuzz.ratio(nq, r["norm_uk"]), fuzz.ratio(nq, r["norm_ru"]))
                if s >= 82:
                    _add(r, int(s * 0.8))      # фаззі завжди нижче за точний
        except ImportError:
            pass

    out = sorted(rows.values(), key=lambda d: (-d["score"], -d["n_cases"]))
    if fond:
        con2 = _con()
        keep = {r["card"] for r in con2.execute(
            "SELECT DISTINCT card FROM cases WHERE fond = ?", [fond])}
        con2.close()
        out = [d for d in out if d["card"] in keep]
    con.close()
    return out[:limit]


def place_card(card: str, repo: str = "CDIAK") -> dict[str, Any]:
    """Картка поселення + УСІ його справи, зшиті з нашим обліком."""
    con = _con()
    row = con.execute("SELECT * FROM places WHERE card = ?", [card]).fetchone()
    if row is None:
        con.close()
        return {}
    place = dict(row)
    cases = [dict(r) for r in con.execute(
        "SELECT * FROM cases WHERE card = ? "
        "ORDER BY CAST(fond AS INTEGER), CAST(opys AS INTEGER), "
        "CAST(spr AS INTEGER)", [card])]
    con.close()

    # 🔗 зшивка з обліком: та сама бібліотека, що живить реєстр опису, тож
    # «на диску» тут і у вкладці «🏛 Фонди» не розійдуться
    # 🔴 Ключ — (фонд, ОПИС, номер, літера), і порядок тут не косметика:
    # `live_on_disk` віддає (опис, номер, літера), а номер справи неунікальний
    # між описами. Переплутавши опис із номером, дістаєш тихий нуль — «на диску
    # немає» для справ, які лежать поруч на диску.
    disk: dict[tuple[str, str, str, str], str] = {}
    try:
        from nyshporka.fonds.registry import live_on_disk
        for fond in {c["fond"] for c in cases}:
            disk.update({(fond, k[0], k[1], k[2]): v
                         for k, v in live_on_disk(repo, fond).items()})
    except Exception:
        pass
    for c in cases:
        n = re.sub(r"\D", "", c["spr"])
        letter = c["spr"][len(n):].lower()
        c["shifra"] = f"{c['fond']}-{c['opys']}-{c['spr']}"
        c["on_disk"] = disk.get((c["fond"], c["opys"], n, letter), "")
    place["cases"] = cases
    place["n_on_disk"] = sum(1 for c in cases if c["on_disk"])
    return place


def places_for_fond(fond: str) -> dict[tuple[str, str], dict[str, str]]:
    """(опис, номер) → {село, парафія, тип} для всіх справ фонду в каталозі.

    🔑 Це те, чого реєстр опису дати не може. Село у ньому є лише тоді, коли
    його вписали в ЗАГОЛОВОК: у ЦДІАК ф.224 це так, у більшості фондів — ні.
    Каталог знає прив'язку справи до поселення незалежно від заголовка, тож
    ним можна заповнити географію там, де опис мовчить.

    Ключ БЕЗ літери: у каталозі номер пишуть «12а», у реєстрі — номер і літера
    окремо; звіряти доводиться нормалізовано, інакше літерні справи (їх у ф.224
    дев'ятнадцять) не зіставляться жодного разу.
    """
    con = _con()
    out: dict[tuple[str, str], dict[str, str]] = {}
    for r in con.execute(
            "SELECT c.opys, c.spr, c.doc_type, c.parish, p.village_uk, p.card "
            "FROM cases c JOIN places p ON p.card = c.card WHERE c.fond = ?",
            [str(fond)]):
        key = (str(r["opys"]), re.sub(r"\D", "", r["spr"]))
        prev = out.get(key)
        if prev is None:
            out[key] = {"village": r["village_uk"], "parish": r["parish"] or "",
                        "doc_type": r["doc_type"] or "", "card": r["card"]}
        elif r["village_uk"] not in prev["village"]:
            # одна справа буває на кілька сіл (збірний том) — не губимо їх,
            # але й не роздуваємо: показуємо перші два й лічильник
            prev.setdefault("more", 0)
            prev["more"] += 1
            if prev["more"] == 1:
                prev["village"] += f" · {r['village_uk']}"
    con.close()
    return out


def confusers(card: str, limit: int = 8, min_score: int = 78) -> list[dict[str, Any]]:
    """Поселення, чиї назви дають хибні спрацювання на цьому.

    Це не прикраса: у самому каталозі поруч стоять М'ястківка, М'яколовичі й
    М'якохід — усі з метричними книгами XVIII ст. Побачити цей список ДО
    пошуку дешевше, ніж потім розбирати, чому «знайшлось» не те село.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return []
    con = _con()
    me = con.execute("SELECT * FROM places WHERE card = ?", [card]).fetchone()
    if me is None:
        con.close()
        return []
    out = []
    for r in con.execute("SELECT * FROM places WHERE card != ?", [card]):
        s = max(fuzz.ratio(me["norm_uk"], r["norm_uk"]),
                fuzz.ratio(me["norm_uk"], r["norm_ru"]),
                fuzz.ratio(me["norm_ru"], r["norm_ru"]))
        if s >= min_score:
            d = dict(r)
            d["score"] = round(s)
            out.append(d)
    con.close()
    return sorted(out, key=lambda d: -d["score"])[:limit]
