"""🏗 Збірка паків каталогу з джерельних TSV.

Це бік ВИДАВЦЯ, а не користувача: паки збираються там, де лежать зібрані з
архівних сайтів TSV (дослідницький репозиторій), і виїжджають релізним ассетом.
Користувач їх лише ставить і читає.

🔴 **TSV лишаються джерелом істини під git — це ланцюг доказів.** Пак —
артефакт збірки, і в `meta` він несе `built_from`, тобто відбиток джерела, з
якого зібраний. Без цього «звідки це число» не має відповіді.
"""
from __future__ import annotations

import csv
import hashlib
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nyshporka.catalog import schema

#: TSV бувають із дуже довгими полями (перелік парафій у картці поселення).
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _norm_name(s: str) -> str:
    """Назва → форма для порівняння (та сама, що в газетирі)."""
    from nyshporka.geog.gazetteer import norm_name

    return norm_name(s)


def _translit(*names: str) -> str:
    """Кириличні назви → латинська нормалізована форма (обидві в одному полі).

    🔑 Саме ця колонка робить можливим пошук латинкою, якого газетир не вмів
    ніколи: `Miastkowka` віддавала НУЛЬ — найгірший вид нуля, бо його читають
    як «такого села немає». А писали так усе: польські акти, костельні книги,
    анотації FamilySearch, закордонні дослідники.

    Точний збіг тут неможливий за побудовою (`М'ястківка` → `mastkivka`, а
    `Miastkowka` → `miastkovka`), тож порівняння лишається фаззі — але тепер є
    З ЧИМ порівнювати.
    """
    from nyshporka.utils.translit import normalize_for_matching

    parts = []
    for n in names:
        v = normalize_for_matching(_norm_name(n))
        if v and v not in parts:
            parts.append(v)
    return " ".join(parts)


def _digest(paths: Iterable[Path]) -> str:
    """Відбиток джерел: sha256 по (ім'я, розмір, вміст) кожного файла."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda q: q.name):
        if not p.is_file():
            continue
        h.update(p.name.encode("utf-8"))
        with p.open("rb") as fh:
            while block := fh.read(1 << 20):
                h.update(block)
    return h.hexdigest()


def _open_fresh(out: Path, domain: str) -> tuple[sqlite3.Connection, Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    schema.apply(con, domain)
    return con, tmp


def finalize(con: sqlite3.Connection, tmp: Path, out: Path, *,
             domain: str, pack_id: str, taken: str, source: str,
             built_from: str, rows: int,
             coverage: Iterable[tuple[str, str, int, int | None, str]] = (),
             note: str = "") -> dict[str, Any]:
    """Дописати `meta` й `coverage_scope`, стиснути базу, покласти на місце.

    `VACUUM` і `ANALYZE` тут не косметика: перший знімає порожні сторінки після
    масових вставок, другий дає планувальнику статистику, без якої запити з
    `JOIN` по словниках ідуть не тим індексом.
    """
    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [
        ("schema", str(schema.SCHEMA_VERSION)),
        ("domain", domain),
        ("pack_id", pack_id),
        ("taken", taken),          # дата ЗРІЗУ — не дата збірки пака
        ("rows", str(rows)),
        ("source", source),
        ("built_from", built_from),  # відбиток джерельних TSV
        ("note", note),
    ])
    con.executemany(
        "INSERT INTO coverage_scope (dim, value, n, denom, note) VALUES(?,?,?,?,?)",
        list(coverage))
    con.commit()
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.close()
    out.unlink(missing_ok=True)
    tmp.replace(out)
    size = out.stat().st_size
    return {"path": str(out), "pack_id": pack_id, "rows": rows, "size": size}


# ── газетир ──────────────────────────────────────────────────────────────────

def build_geog(places_tsv: Path, cases_tsv: Path, out: Path, *,
               pack_id: str, taken: str,
               source: str = "https://cdiak.archives.gov.ua/baza_geog_pok",
               verbose: bool = False) -> dict[str, Any]:
    """Пак газетира: поселення + справи по всіх фондах архіву."""
    con, tmp = _open_fresh(out, "geog")

    n_pl = 0
    with places_tsv.open(encoding="utf-8", newline="") as fh:
        batch: list[tuple[Any, ...]] = []
        for r in csv.DictReader(fh, delimiter="\t"):
            uk, ru = r.get("village_uk", ""), r.get("village_ru", "")
            batch.append((
                r["card"], r.get("section") or "church",
                r.get("institution") or "православна церква",
                uk, ru, r.get("hist_place", ""), r.get("uezd_gub", ""),
                r.get("modern_place", ""), r.get("church", ""),
                r.get("eparchy", ""), r.get("parishes", ""), r.get("note", ""),
                _norm_name(uk), _norm_name(ru), _translit(uk, ru)))
            n_pl += 1
        con.executemany(
            "INSERT OR REPLACE INTO places(card,section,institution,village_uk,"
            "village_ru,hist_place,uezd_gub,modern_place,church,eparchy,parishes,"
            "note,norm_uk,norm_ru,translit) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch)

    # словники: `doc_type` ≈20 значень, `parish` дублює назви поселень — саме
    # їхнє повторення й давало більшу частину ваги старого індексу
    doc_ids: dict[str, int] = {}
    par_ids: dict[str, int] = {}

    def _id(name: str, store: dict[str, int]) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        got = store.get(name)
        if got is None:
            got = len(store) + 1
            store[name] = got
        return got

    n_cs = 0
    if cases_tsv.is_file():
        with cases_tsv.open(encoding="utf-8", newline="") as fh:
            batch = []
            for r in csv.DictReader(fh, delimiter="\t"):
                spr = (r.get("spr") or "").strip()
                digits = "".join(ch for ch in spr if ch.isdigit())
                batch.append((
                    r["card"], r.get("fond", ""), r.get("opys", ""), spr,
                    int(digits) if digits else None,
                    int(r.get("year_from") or 0), int(r.get("year_to") or 0),
                    _id(r.get("doc_type", ""), doc_ids),
                    _id(r.get("case_church", ""), par_ids)))
                n_cs += 1
                if len(batch) >= 20000:
                    con.executemany(
                        "INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?)", batch)
                    batch = []
            if batch:
                con.executemany("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?)", batch)

    con.executemany("INSERT INTO doc_types(id,name) VALUES(?,?)",
                    [(v, k) for k, v in doc_ids.items()])
    con.executemany("INSERT INTO parishes(id,name) VALUES(?,?)",
                    [(v, k) for k, v in par_ids.items()])
    con.execute("UPDATE places SET n_cases = "
                "(SELECT COUNT(*) FROM cases WHERE cases.card = places.card)")

    coverage = [("section", sec, n, None, "")
                for sec, n in con.execute(
                    "SELECT section, COUNT(*) FROM places GROUP BY section")]
    coverage += [("fond", f, n, None, "")
                 for f, n in con.execute(
                     "SELECT fond, COUNT(*) FROM cases GROUP BY fond "
                     "ORDER BY COUNT(*) DESC LIMIT 200")]

    res = finalize(con, tmp, out, domain="geog", pack_id=pack_id, taken=taken,
                   source=source, built_from=_digest([places_tsv, cases_tsv]),
                   rows=n_cs, coverage=coverage,
                   note=f"{n_pl} поселень · {n_cs} справ")
    if verbose:
        print(f"✅ {out.name} — {n_pl} поселень · {n_cs} справ · "
              f"{res['size'] / 1e6:.1f} МБ")
    return {**res, "places": n_pl, "cases": n_cs}


# ── реєстр опису фонду ───────────────────────────────────────────────────────

#: 🔴 Колонки, які в пак НЕ ЇДУТЬ. `on_disk` описує диск ДОСЛІДНИКА на момент
#: злиття — поїхавши в пак, вона стала б чужим станом, виданим за факт про архів,
#: і зламала б позначку «реєстр розходиться з бібліотекою» в кожного користувача.
_OPYS_DROP = frozenset({"on_disk"})


def _uezd_of(title: str) -> str:
    """Повіт із заголовка справи — матеріалізується ТУТ, а не regex у запиті.

    Заміряно: `facets()` ганяв цей regex по кожному з 12 824 заголовків на кожен
    запит вкладки — 137 мс, третина всього часу відповіді.
    """
    from nyshporka.fonds.registry import _UEZD_LABEL, _UEZD_RE

    m = _UEZD_RE.search(title or "")
    if not m:
        return ""
    return _UEZD_LABEL.get(m.group(1).lower(), m.group(1))


def build_opys(merged_tsv: Path, out: Path, *, fond: str, pack_id: str,
               taken: str, registry_dir: Path | None = None,
               source: str = "", verbose: bool = False) -> dict[str, Any]:
    """Пак реєстру опису одного фонду: справи + алфавітка + розбіжності."""
    con, tmp = _open_fresh(out, "opys")
    reg = registry_dir if registry_dir is not None else merged_tsv.parent / "registry"

    cols_out = [c for c in (
        "opys", "spr_int", "spr_letter", "spr", "shifra", "title", "title_norm",
        "title_src", "title_alt", "commons_title", "year_from", "year_to",
        "years_src", "folios", "folios_src", "dv_no", "uezd",
        "commons_url", "commons_size", "commons_pages", "mirror_url",
        "mirror_size", "truncated_mirror", "src_page", "page_quality", "num_src",
        "surnames", "cover_place", "cover_letters", "cover_note",
        "fs_dgs", "fs_film", "fs_url", "fs_record_type", "fs_place", "fs_frames",
        "sources")]
    placeholders = ",".join("?" * len(cols_out))

    from nyshporka.utils.translit import normalize_for_matching

    n = 0
    by_opys: dict[str, int] = {}
    with merged_tsv.open(encoding="utf-8", newline="") as fh:
        batch: list[tuple[Any, ...]] = []
        for r in csv.DictReader(fh, delimiter="\t"):
            assert not (_OPYS_DROP & set(cols_out)), "у пак поїхала колонка диска"
            opys = (r.get("opys") or "").strip()
            spr_int = (r.get("spr_int") or "").strip()
            letter = (r.get("spr_letter") or "").strip()
            spr = f"{spr_int}{letter}"
            title = (r.get("title") or "").strip()
            by_opys[opys] = by_opys.get(opys, 0) + 1
            vals = {
                "opys": opys,
                "spr_int": int(spr_int) if spr_int.isdigit() else None,
                "spr_letter": letter, "spr": spr,
                "shifra": f"{fond}-{opys}-{spr}",
                "title": title, "title_norm": normalize_for_matching(title),
                "uezd": _uezd_of(title),
            }
            for c in cols_out:
                if c not in vals:
                    vals[c] = (r.get(c) or "").strip() or None
            batch.append(tuple(vals[c] for c in cols_out))
            n += 1
        con.executemany(
            f"INSERT OR REPLACE INTO cases ({','.join(cols_out)}) "
            f"VALUES ({placeholders})", batch)

    n_alf = 0
    alf = reg / "alfavitka.tsv"
    if alf.is_file():
        with alf.open(encoding="utf-8", newline="") as fh:
            rows: list[tuple[Any, ...]] = [(r.get("surname", ""),
                     normalize_for_matching(r.get("surname", "")),
                     r.get("opys", ""), r.get("spr", ""), r.get("note", ""))
                    for r in csv.DictReader(fh, delimiter="\t")]
        con.executemany("INSERT INTO alfavitka VALUES(?,?,?,?,?)", rows)
        n_alf = len(rows)

    n_conf = 0
    conf = reg / "conflicts.tsv"
    if conf.is_file():
        with conf.open(encoding="utf-8", newline="") as fh:
            rows = [(r.get("opys", ""), r.get("spr", ""), r.get("field", ""),
                     r.get("a", ""), r.get("b", ""), r.get("note", ""))
                    for r in csv.DictReader(fh, delimiter="\t")]
        con.executemany("INSERT INTO conflicts VALUES(?,?,?,?,?,?)", rows)
        n_conf = len(rows)

    # покриття пофондово-поописно; `denom` із `coverage.json`, якщо він є
    denoms: dict[str, int] = {}
    cov_json = reg / "coverage.json"
    if cov_json.is_file():
        try:
            import json

            raw = json.loads(cov_json.read_text(encoding="utf-8"))
            for k, v in (raw.get("opys") or {}).items():
                if isinstance(v, dict) and v.get("total"):
                    denoms[str(k)] = int(v["total"])
        except Exception:
            pass
    coverage = [("opys", o, cnt, denoms.get(o),
                 "" if o in denoms else "межа опису невідома — це НИЖНЯ оцінка")
                for o, cnt in sorted(by_opys.items())]

    res = finalize(con, tmp, out, domain="opys", pack_id=pack_id, taken=taken,
                   source=source or f"реєстр опису ф.{fond}",
                   built_from=_digest([merged_tsv, alf, conf]),
                   rows=n, coverage=coverage,
                   note=f"ф.{fond}: {n} справ · алфавітка {n_alf} · "
                        f"розбіжностей {n_conf}")
    if verbose:
        print(f"✅ {out.name} — {n} справ · алфавітка {n_alf} · "
              f"{res['size'] / 1e6:.1f} МБ")
    return {**res, "cases": n, "alfavitka": n_alf, "conflicts": n_conf}
