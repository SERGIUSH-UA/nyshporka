r"""SQLite-індекс реєстру справ: схема, запис, запити з фільтрами.

База **derived** — перебудовується з тих самих файлів, що читає конвеєр, і не є
джерелом істини ні для чого. Ручні рішення (прив'язки прогонів) лежать у
`data/cases/overrides.json` під git, тож перебудова їх не змиває.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta, timezone  # noqa: F401  (timezone — у staleness)
from pathlib import Path
from typing import Any

from nyshporka.cases.collect import collect_rows
from nyshporka.cases.model import CaseRow
from nyshporka.cases.resolve import LibraryIndex
from nyshporka.library import ROOT

DB_PATH = ROOT / "data" / "derived" / "case_index.sqlite"

#: Поля, які зберігаються як JSON-текст (списки).
_JSON_FIELDS = {"record_types", "extra_paths", "htr_runs", "fuzzy_runs",
                "settlements", "uezds"}
#: Поля-прапорці — у SQLite як 0/1.
_BOOL_FIELDS = {"htr_pysar", "htr_diak", "htr_skryba", "fuzzy_swept", "curated"}

_SCHEMA = """
CREATE TABLE cases (
    key TEXT PRIMARY KEY, kind TEXT, shifra TEXT, repo TEXT, repo_label TEXT,
    fond TEXT, opys TEXT, spr TEXT, title TEXT, doc_type TEXT,
    record_types TEXT, year_from INTEGER, year_to INTEGER,
    place_raw TEXT, settlement TEXT, settlements TEXT, uezd TEXT, uezds TEXT,
    guberniya TEXT, place_id TEXT, geo_blob TEXT,
    parish TEXT, script TEXT, desc_source TEXT,
    path TEXT, extra_paths TEXT, state TEXT, frames INTEGER, expected INTEGER,
    htr_pysar INTEGER, htr_pysar_model TEXT, htr_pysar_pages INTEGER,
    htr_diak INTEGER, htr_diak_model TEXT, htr_diak_pages INTEGER,
    htr_skryba INTEGER, htr_skryba_model TEXT, htr_skryba_pages INTEGER,
    htr_runs TEXT, htr_pages_max INTEGER, htr_updated TEXT,
    fuzzy_scanned TEXT, fuzzy_model TEXT, fuzzy_pages INTEGER, fuzzy_hits INTEGER,
    fuzzy_reviewed INTEGER, fuzzy_swept INTEGER, fuzzy_runs TEXT,
    canon_source_id TEXT, canon_facts INTEGER, canon_persons INTEGER,
    canon_scans INTEGER, pages_noted INTEGER, pages_full INTEGER,
    verdict TEXT, verdict_note TEXT, curated INTEGER, "group" TEXT, why TEXT,
    htr_stage TEXT, fuzzy_stage TEXT, htr_coverage REAL
);
CREATE INDEX idx_cases_repo ON cases(repo);
CREATE INDEX idx_cases_state ON cases(state);
CREATE INDEX idx_cases_htr ON cases(htr_stage);
CREATE INDEX idx_cases_fuzzy ON cases(fuzzy_stage);
CREATE INDEX idx_cases_years ON cases(year_from, year_to);
CREATE INDEX idx_cases_uezd ON cases(uezd);
CREATE INDEX idx_cases_place ON cases(place_id);

-- Прогони, які не прив'язались до жодної справи. Тримаємо в базі, а не викидаємо:
-- мовчазний фільтр дав би хибне «все прив'язано».
CREATE TABLE orphan_runs (
    run TEXT PRIMARY KEY, case_dir TEXT, pages INTEGER, model TEXT,
    source TEXT, resolved_by TEXT, note TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _row_values(row: CaseRow) -> dict[str, Any]:
    d = asdict(row)
    for f in _JSON_FIELDS:
        d[f] = json.dumps(d.get(f) or [], ensure_ascii=False)
    for f in _BOOL_FIELDS:
        d[f] = int(bool(d.get(f)))
    d["htr_coverage"] = round(row.htr_coverage, 4)
    return d


def _pulse_seq() -> int:
    """Мітка пульсу простору; 0, якщо пульсу немає (це теж дійсний стан)."""
    try:
        from nyshporka.core import pulse

        return pulse.seq()
    except Exception:
        return 0


def build_index(db_path: Path | None = None,
                index: LibraryIndex | None = None) -> dict[str, Any]:
    """Зібрати реєстр і перезаписати базу. Повертає підсумок для друку."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 💓 Мітку пульсу знімаємо ПЕРЕД збором, а не після. Збірка триває секунди, і
    # удар, що стався в цей час, описує зміну, якої ми ще не прочитали. Записавши
    # мітку «після», ми оголосили б реєстр свіжим саме тоді, коли він уже ні —
    # помилка в небезпечному напрямку. «До» дає щонайбільше зайву перезбірку.
    pulse_at_start = _pulse_seq()
    rows, orphans = collect_rows(index)
    tmp = path.with_suffix(".sqlite.tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        cols = [f.name for f in fields(CaseRow)] + ["htr_coverage"]
        placeholders = ", ".join(f":{c}" for c in cols)
        quoted = ", ".join(f'"{c}"' for c in cols)
        con.executemany(f"INSERT INTO cases ({quoted}) VALUES ({placeholders})",
                        [_row_values(r) for r in rows])
        con.executemany(
            "INSERT OR REPLACE INTO orphan_runs (run, case_dir, pages, model, source,"
            " resolved_by, note) VALUES (:run, :case_dir, :pages, :model, :source,"
            " :resolved_by, :note)",
            [{"run": o.get("run"), "case_dir": o.get("case_dir") or "",
              "pages": o.get("pages") or 0, "model": o.get("model") or "",
              "source": o.get("source") or "htr",
              "resolved_by": o.get("resolved_by") or "", "note": o.get("note") or ""}
             for o in orphans])
        # «нема до чого прив'язати» (override з `key: null`) — рішення людини, а не
        # діра в реєстрі; у таблиці лишається, але з числа нерозв'язаних виходить,
        # інакше приймач «нуль нічиїх» недосяжний за побудовою.
        decided = sum(1 for o in orphans if (o.get("resolved_by") or "") == "override")
        con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", [
            ("built", datetime.now(UTC).isoformat(timespec="seconds")),
            ("cases", str(len(rows))),
            ("orphan_runs", str(len(orphans) - decided)),
            ("decided_none_runs", str(decided)),
            # 💓 Мітка пульсу (знята ДО збору — див. вище). По ній
            # `staleness(quick=True)` за один `stat` каже «точно застарів»,
            # не обходячи 840 файлів.
            ("pulse", str(pulse_at_start)),
        ])
        con.commit()
    finally:
        con.close()
    tmp.replace(path)
    return {"cases": len(rows), "orphans": len(orphans) - decided,
            "decided": decided, "path": str(path)}


#: Поріг гео-фільтра (`rapidfuzz.ratio` по КОРЕНЯХ нормалізованих форм).
#: Калібровано заміром: правильні збіги — 80…100 (`Miastkowka`↔«М'ястківка» 80,
#: `Tsarevka`↔«Царёвка» 80, «Ольгопіль»↔«Ольгопільський» 100 після обрізання),
#: чужі — до 77 («Ямпільський»↔«Ольгопільський» 77).
_GEO_MIN = 80
#: Суфікси прикметника-повіту в нормалізованій формі: «Ольгопільський» → `olgopilskii`.
_GEO_SUFFIXES = ("skogo", "skomu", "skoi", "skii", "skij", "skiy", "ska", "skoy", "sk")


def geo_root(value: str) -> str:
    """Нормалізована форма без суфікса прикметника: `olgopilskii` → `olgopil`."""
    # Беремо з першоджерела, а не через `cases.geo`: там воно лише реекспорт,
    # і імпорт «крізь» модуль ховає справжню залежність.
    from nyshporka.utils.translit import normalize_for_matching
    v = normalize_for_matching(value or "")
    for suf in _GEO_SUFFIXES:
        if v.endswith(suf) and len(v) - len(suf) >= 4:
            return v[: -len(suf)]
    return v


def geo_hit(query: str, values: list[str]) -> bool:
    """Чи згадує рядок це місце — з урахуванням відмінка, суфікса й латинки.

    🔴 Чому не SQL LIKE: «Miastkowka» нормалізується в `miastkovka`, а
    «М'ястківка» — в `m'astkivka`; підрядком вони не збігаються ніколи, тож
    пошук латинкою по кириличному каталогу мовчки давав нуль.
    🔴 Чому не `partial_ratio`: у наших повітів спільний хвіст «-ільський», і
    «Ямпільський» діставав «Ольгопільський» на 80+. Порівнюємо КОРЕНІ.
    """
    q = geo_root(query)
    if len(q) < 3:
        return False
    roots = [geo_root(v) for v in values if v]
    if any(r and (q.startswith(r) or r.startswith(q)) for r in roots):
        return True
    try:
        from rapidfuzz import fuzz
    except Exception:
        return False
    return any(fuzz.ratio(q, r) >= _GEO_MIN for r in roots if len(r) > 2)


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"реєстру ще немає ({path.name}) — зберіть його: nysh cases build")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def query_rows(q: str = "", repo: str = "", state: str = "", htr: str = "",
               fuzzy: str = "", year: str = "", place: str = "", doc: str = "",
               verdict: str = "", curated: bool = False, kind: str = "",
               uezd: str = "", settlement: str = "", place_id: str = "",
               limit: int = 0, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Рядки реєстру за фільтрами. Порожній фільтр не звужує вибірку."""
    where: list[str] = []
    args: dict[str, object] = {}
    if kind:
        where.append("kind = :kind")
        args["kind"] = kind
    if repo:
        where.append("upper(repo) = upper(:repo)")
        args["repo"] = repo
    if state:
        where.append("state = :state")
        args["state"] = state
    if htr:
        where.append("htr_stage = :htr")
        args["htr"] = htr
    if fuzzy:
        where.append("fuzzy_stage = :fuzzy")
        args["fuzzy"] = fuzzy
    if verdict:
        where.append("verdict = :verdict")
        args["verdict"] = verdict
    if curated:
        where.append("curated = 1")
    if place_id:
        where.append("place_id = :place_id")
        args["place_id"] = place_id
    if doc:
        where.append("(lower(doc_type) LIKE :doc OR lower(record_types) LIKE :doc)")
        args["doc"] = f"%{doc.lower()}%"
    if year:
        lo, _, hi = year.partition("-")
        lo_i = int(lo) if lo.strip().isdigit() else None
        hi_i = int(hi) if hi.strip().isdigit() else lo_i
        if lo_i is not None:
            # перетин діапазонів: справа торкається запитаного вікна
            where.append("(coalesce(year_to, year_from) >= :ylo "
                         "AND coalesce(year_from, year_to) <= :yhi)")
            args["ylo"], args["yhi"] = lo_i, hi_i
    if q:
        # `key` теж шукаємо: ним оперують скрипти й агенти («DAHMO/315/7864»),
        # і без нього `show` за ключем не знаходив нічого.
        where.append("(lower(key) LIKE :q OR lower(shifra) LIKE :q OR lower(title) LIKE :q "
                     "OR lower(place_raw) LIKE :q OR lower(coalesce(path, '')) LIKE :q "
                     "OR lower(coalesce(\"group\", '')) LIKE :q)")
        args["q"] = f"%{q.lower()}%"
    sql = "SELECT * FROM cases"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY repo_label, CAST(fond AS INTEGER), CAST(spr AS INTEGER)"
    # LIMIT ставимо ПІСЛЯ гео-фільтра (він у Python), інакше «перші 60» відсіклись
    # би до фільтрації і половина повіту зникла б без сліду.
    geo_filter = bool(uezd or settlement or place)
    if limit and not geo_filter:
        sql += f" LIMIT {int(limit)}"
    con = _connect(db_path)
    try:
        rows = [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()
    for r in rows:
        for f in _JSON_FIELDS:
            try:
                r[f] = json.loads(r.get(f) or "[]")
            except Exception:
                r[f] = []
    if uezd:
        rows = [r for r in rows if geo_hit(uezd, [r.get("uezd") or "", *(r.get("uezds") or [])])]
    if settlement:
        rows = [r for r in rows
                if geo_hit(settlement, [r.get("settlement") or "",
                                         *(r.get("settlements") or [])])]
    if place:
        rows = [r for r in rows
                if geo_hit(place, [r.get("place_raw") or "", r.get("guberniya") or "",
                                    *(r.get("settlements") or []), *(r.get("uezds") or [])])]
    if limit and geo_filter:
        rows = rows[:limit]
    return rows


def orphan_runs(db_path: Path | None = None) -> list[dict[str, Any]]:
    con = _connect(db_path)
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM orphan_runs ORDER BY pages DESC, run")]
    finally:
        con.close()


def staleness(db_path: Path | None = None, *, quick: bool = False) -> dict[str, Any]:
    """Чи відстав реєстр від своїх джерел — і від яких саме.

    ⏱ `quick=True` — дешевий шар на 💓 пульсі (`core.pulse`): якщо мітка простору
    змінилась після збірки, реєстр застарів ТОЧНО, і повну перевірку робити
    нема сенсу. Коштує один `stat` замість двох `glob` і ~840 `stat`.

    🔴 Зворотне НЕ виконується, і на цьому тримається вся чесність механізму:
    збіг мітки означає лише «через застосунок нічого не міняли». Файл, покладений
    у `data/raw` Провідником, пульсу не б'є. Тому `quick` при збігу мітки чесно
    каже «не знаю» (`unknown=True`), а не «свіжий», і викликач мусить або зробити
    повну перевірку, або показати це станом — але не видавати за відповідь.

    🔴 Навіщо це в коді, а не лише в інструкції. Реєстр — derived-зріз п'яти
    сховищ, і будь-який прогін, пошук чи внесення факту робить його старим за
    хвилини. Застарілий зріз небезпечніший за відсутній: він виглядає як відповідь
    («декоду немає») там, де декод зроблено годину тому, і рішення «що гнати далі»
    ухвалюють по ньому. Тому свіжість перевіряється **приймачем** — часом зміни
    самих файлів, а не обіцянкою перебудувати.

    Порівнюємо час збірки з найновішою зміною джерел; `reports/htr` рахуємо ще й
    кількістю тек, бо новий прогін може бути старішим за файлом, ніж перебудова
    (розпакований архів зберігає час створення).
    """
    path = Path(db_path or DB_PATH)
    if not path.is_file():
        return {"built": None, "stale": True, "reasons": ["реєстру ще немає"]}
    meta = index_meta(path)
    built_raw = meta.get("built") or ""
    try:
        built = datetime.fromisoformat(built_raw)
    except ValueError:
        return {"built": built_raw, "stale": True, "reasons": ["час збірки не читається"]}
    if built.tzinfo is None:
        built = built.replace(tzinfo=UTC)

    if quick:
        try:
            from nyshporka.core import pulse

            now, at_build = pulse.seq(), int(meta.get("pulse") or 0)
        except Exception:
            now, at_build = 0, 0
        # 🔴 Проста нерівність, а не `now and at_build and now != at_build`.
        # Нуль тут — ЗНАЧУЩЕ значення («пульсу не було»), а не «немає даних»:
        # збірка на просторі без пульсу записує 0, і перший же удар дає 0 → N,
        # тобто справжню зміну. Вимога «обидві ненульові» робила саме цей
        # перехід невидимим — і найчастіший випадок (перша збірка, потім робота)
        # мовчки читався б як «нічого не міняли».
        if now != at_build:
            return {"built": built_raw, "stale": True, "unknown": False,
                    "reasons": ["у просторі щось міняли після збірки"]}
        # мітки збіглись — це НЕ доказ свіжості, а лише «через застосунок
        # нічого не міняли»
        return {"built": built_raw, "stale": False, "unknown": True, "reasons": []}

    # 🔴 Допуск в одну секунду, і він не «про всяк випадок». Мітка збірки
    # пишеться з `timespec="seconds"`, тобто ОБРІЗАЄТЬСЯ вниз, а mtime
    # порівнюється з мікросекундами. `cases build --rescan` сам перезаписує
    # `case_library.json` — і той опиняється на частку секунди «пізніше» за
    # власну збірку: щойно зібраний реєстр одразу звітував «зріз застарів».
    # Заміряно на чистому просторі: built 13:47:16, mtime 13:47:16.745.
    # Ворота, які завжди червоні, вимикають — і тоді вони не ловлять нічого.
    built = built + timedelta(seconds=1)

    reasons: list[str] = []
    for label, target in (
        ("каталог справ", ROOT / "data" / "derived" / "case_library.json"),
        ("пошук роду", ROOT / "data" / "clan_hunt" / "state.json"),
        ("канон", ROOT / "data" / "derived" / "nyshporka.sqlite"),
        ("ручні прив'язки", ROOT / "data" / "cases" / "overrides.json"),
    ):
        try:
            mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime > built:
            reasons.append(f"{label} змінено {mtime:%m-%d %H:%M}")
    newest_run, n_runs = None, 0
    for meta_path in (ROOT / "reports" / "htr").glob("*/_htr_meta.json"):
        n_runs += 1
        try:
            ts = datetime.fromtimestamp(meta_path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if newest_run is None or ts > newest_run:
            newest_run = ts
    if newest_run and newest_run > built:
        reasons.append(f"є прогін, оновлений {newest_run:%m-%d %H:%M}")
    known_runs = 0
    con = _connect(path)
    try:
        known_runs = con.execute(
            "SELECT coalesce(sum(json_array_length(htr_runs)), 0) FROM cases").fetchone()[0]
        known_runs += con.execute("SELECT count(*) FROM orphan_runs").fetchone()[0]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    if n_runs > known_runs:
        reasons.append(f"на диску {n_runs} прогонів, у реєстрі {known_runs}")
    pages_dir = ROOT / "data" / "pages"
    newest_note = max((p.stat().st_mtime for p in pages_dir.glob("*/*.json")), default=0)
    if newest_note and datetime.fromtimestamp(newest_note, tz=UTC) > built:
        reasons.append("сховище сторінок оновлено")
    return {"built": built_raw, "stale": bool(reasons), "unknown": False,
            "reasons": reasons}


def index_meta(db_path: Path | None = None) -> dict[str, Any]:
    con = _connect(db_path)
    try:
        return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    finally:
        con.close()


def stats(db_path: Path | None = None) -> dict[str, Any]:
    """Зведення реєстру — те, що вчора збиралося вручну шістьма запитами."""
    con = _connect(db_path)
    try:
        def one(sql: str) -> int:
            return int(con.execute(sql).fetchone()[0])

        # 🔴 Скрізь `kind='case'`: кадри збірки — ті самі файли, що й у її справах,
        # тож в одному підсумку вони подвоїли б сторінки. Збірки рахуються окремо.
        c = "WHERE kind = 'case'"
        # Зведення неоднорідне за побудовою: числа плюс розрізи списками.
        out: dict[str, Any] = {
            "cases": one(f"SELECT count(*) FROM cases {c}"),
            "frames": one(f"SELECT coalesce(sum(frames), 0) FROM cases {c}"),
            "ordered": one(f"SELECT count(*) FROM cases {c} AND state = 'ordered'"),
            "partial": one(f"SELECT count(*) FROM cases {c} AND state = 'partial'"),
            "htr_none": one(f"SELECT count(*) FROM cases {c} AND htr_stage = 'none'"),
            "htr_frames_left": one(
                f"SELECT coalesce(sum(frames), 0) FROM cases {c} AND htr_stage = 'none'"),
            "htr_pages": one(f"SELECT coalesce(sum(htr_pages_max), 0) FROM cases {c}"),
            "fuzzy_none": one(f"SELECT count(*) FROM cases {c} AND fuzzy_stage = 'none'"),
            "fuzzy_hits_open": one(
                "SELECT coalesce(sum(max(fuzzy_hits - fuzzy_reviewed, 0)), 0) FROM cases"),
            "canon_cases": one(f"SELECT count(*) FROM cases {c} AND canon_facts > 0"),
            "eye_cases": one(f"SELECT count(*) FROM cases {c} AND pages_noted > 0"),
            "unfiled": one("SELECT count(*) FROM cases WHERE kind = 'unfiled'"),
            "unfiled_frames": one(
                "SELECT coalesce(sum(frames), 0) FROM cases WHERE kind = 'unfiled'"),
            "bundles": one("SELECT count(*) FROM cases WHERE kind = 'bundle'"),
            "bundle_frames": one(
                "SELECT coalesce(sum(frames), 0) FROM cases WHERE kind = 'bundle'"),
            "bundle_pages": one(
                "SELECT coalesce(sum(htr_pages_max), 0) FROM cases WHERE kind = 'bundle'"),
            # свідоме «нема до чого прив'язати» (override `key: null`) сюди не йде —
            # це рішення, а не діра; воно рахується окремо як decided_none_runs
            "orphan_runs": one(
                "SELECT count(*) FROM orphan_runs WHERE resolved_by <> 'override'"),
            "orphan_pages": one(
                "SELECT coalesce(sum(pages), 0) FROM orphan_runs"
                " WHERE resolved_by <> 'override'"),
            "decided_none_runs": one(
                "SELECT count(*) FROM orphan_runs WHERE resolved_by = 'override'"),
        }
        # Гео-покриття: скільки справ мають розібране місце. Показуємо ЧЕСНО, бо
        # фільтр за повітом мовчки пропускає все, що не розібралось.
        out["geo_uezd"] = one(f"SELECT count(*) FROM cases {c} AND uezd <> ''")
        out["geo_settlement"] = one(f"SELECT count(*) FROM cases {c} AND settlement <> ''")
        out["geo_place_id"] = one(f"SELECT count(*) FROM cases {c} AND place_id IS NOT NULL")
        out["geo_unparsed"] = one(
            f"SELECT count(*) FROM cases {c} AND place_raw <> '' "
            "AND uezd = '' AND settlement = ''")
        out["geo_empty"] = one(f"SELECT count(*) FROM cases {c} AND place_raw = ''")
        out["by_uezd"] = [dict(r) for r in con.execute(
            "SELECT uezd, count(*) AS n, coalesce(sum(frames),0) AS frames,"
            " sum(CASE WHEN htr_stage='none' THEN 1 ELSE 0 END) AS no_htr"
            " FROM cases WHERE kind='case' AND uezd <> ''"
            " GROUP BY uezd ORDER BY n DESC LIMIT 12")]
        out["by_repo"] = [dict(r) for r in con.execute(
            "SELECT repo_label AS repo, count(*) AS n, coalesce(sum(frames),0) AS frames,"
            " sum(CASE WHEN htr_stage='none' THEN 1 ELSE 0 END) AS no_htr,"
            " coalesce(sum(CASE WHEN htr_stage='none' THEN frames ELSE 0 END),0) AS frames_left"
            " FROM cases WHERE kind='case' GROUP BY repo_label ORDER BY frames DESC")]
        return out
    finally:
        con.close()


def rebuild(*, rescan: bool = True) -> dict[str, Any]:
    """Перезібрати реєстр цілком: опис справ на диску, тоді сам зріз.

    🔴 Два кроки, а не один, і саме тому вони тут разом. `build_index()` лише
    ЧИТАЄ опис справ (`case_library.json`); зібрати індекс, не перечитавши диск,
    означає побудувати зріз на бібліотеці, якої ще немає, — і він виходить не
    порожній, а НЕПРАВИЛЬНИЙ: справа без шифри, прогони нічиї. Тобто гірший за
    відсутній, бо виглядає як відповідь. Перший виклик у обхід цієї функції вже
    дав рівно таку картину, тож окремих «зберу лише індекс» бути не повинно.

    `rescan=False` лишається для випадку, коли диск щойно перечитали.
    """
    entries = 0
    if rescan:
        from nyshporka.library import build_library, write_library

        rows = build_library()
        write_library(rows)
        entries = len(rows)
    res = build_index()
    return {"entries": entries, "rescanned": rescan, **res}
