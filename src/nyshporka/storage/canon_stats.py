"""📊 Зведення канону — те, що є в базі роду, одним запитом.

Зворотний напрям до `storage.reindex`: та збирає `data/derived/nyshporka.sqlite`
з карток `data/canonical/**`, ця її читає. Обидві на одному шарі саме тому, що
описують один формат із двох боків, і розводити їх по різних місцях означало б
дати схемі два незалежні описи.

🔴 **Читаємо SQLite, а не картки MD.** Розбір карток мусить їх валідувати —
інакше це не читання, а здогад, — тобто одна зіпсована картка особи кидає
виняток. Для команди перевірки цілості це правильна поведінка й там вона й
лишається; але дашборд, який гасне цілком через один битий файл, показує
відмову там, де мала бути одна помітка. SQLite до того ж дає розрізи, яких у
картках без повного обходу не порахувати: цитати, статуси, факти без доказу.

🔴 **«Канону немає» і «канон порожній» — різні відповіді.** Нулі замість
відсутньої бази читаються як «я перевірив, у тебе нічого немає», хоча насправді
перевіряти не було чого. Тому тут `present: false` з поясненням, а не зведення
з нулями.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

#: Скільки прізвищ і типів фактів показувати. Дашборд — оглядовий екран: довгий
#: хвіст із одного факту на тип забиває його, нічого не додаючи до картини.
TOP_N = 12


def canon_db() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / "nyshporka.sqlite"


def summary() -> dict[str, Any]:
    """Числа канону + розрізи. Бази немає → `{"present": False, "why": ...}`."""
    try:
        path = canon_db()
    except Exception as exc:
        return _absent(f"простір не визначено ({type(exc).__name__})")
    if not path.is_file():
        # ⚠ Порада тут не називає команди, і це навмисно: у публічному
        # застосунку її немає. Базу роду збирає дослідницький конвеєр
        # (`storage.reindex`), а консоль її лише читає — тож «наберіть X»
        # відправило б людину шукати те, чого в її збірці не існує.
        return _absent(
            "канону в цьому просторі немає: базу роду збирають із карток "
            "`data/canonical/**`, і поки їх не зібрано, показувати нема чого")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return _absent(f"канон не читається ({exc})")
    try:
        out: dict[str, Any] = {
            "present": True,
            "built": time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.localtime(path.stat().st_mtime)),
        }
        out.update(_totals(con))
        out["facts_by_type"] = _facts_by_type(con)
        out["facts_by_decade"] = _facts_by_decade(con)
        out["top_surnames"] = _top_surnames(con)
        out.update(_quality(con))
    except sqlite3.Error as exc:
        # 🔴 Схема derived-бази належить `reindex`, і вона рухається. Якщо
        # таблиці змінили форму, дашборд мусить сказати саме це — інакше
        # старий екран поверх нової бази виглядав би як спорожнілий канон.
        return _absent(f"канон зібрано іншою версією схеми ({exc}) — "
                       f"базу роду треба перезібрати")
    finally:
        con.close()
    out["coverage"] = _coverage(path.parent)
    return out


def _absent(why: str) -> dict[str, Any]:
    return {"present": False, "why": why}


def _one(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def _totals(con: sqlite3.Connection) -> dict[str, int]:
    return {
        "persons": _one(con, "SELECT count(*) FROM persons"),
        "families": _one(con, "SELECT count(*) FROM families"),
        "places": _one(con, "SELECT count(*) FROM places"),
        "sources": _one(con, "SELECT count(*) FROM sources"),
        "facts": _one(con, "SELECT count(*) FROM facts"),
        "citations": _one(con, "SELECT count(*) FROM citations"),
        "media": _one(con, "SELECT count(*) FROM media"),
    }


def _facts_by_type(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT type AS code, count(*) AS n FROM facts"
        " WHERE type <> '' GROUP BY type ORDER BY n DESC").fetchall()
    return _capped([dict(r) for r in rows])


def _facts_by_decade(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Факти за десятиліттями — історична вісь документа, не роботи.

    ⚠ Це відповідь на «який період мого роду вже описано», і плутати її з
    графіком «як росла база» не можна: перша рахує роки подій, друга — дні,
    коли ми про них дізнались.

    Дата в каноні — рядок (`date_value`), бо вона буває неточною («бл. 1802»,
    «1802-1804»). Тому десятиліття беремо з перших чотирьох цифр і мовчки
    пропускаємо все, з чого року не видно: підставити нуль означало б
    намалювати стовпчик на 0-х роках.
    """
    got: dict[int, int] = {}
    for (raw,) in con.execute(
            "SELECT date_value FROM facts WHERE date_value <> ''"):
        year = str(raw or "")[:4]
        if not year.isdigit():
            continue
        got[int(year) // 10 * 10] = got.get(int(year) // 10 * 10, 0) + 1
    return [{"decade": d, "n": got[d]} for d in sorted(got)]


def _top_surnames(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT surname AS code, count(DISTINCT person_id) AS n"
        " FROM name_variants WHERE is_primary AND surname <> ''"
        " GROUP BY surname ORDER BY n DESC").fetchall()
    return _capped([dict(r) for r in rows])


def _quality(con: sqlite3.Connection) -> dict[str, int]:
    """Показники довіри до бази — те, чого не видно з підсумків.

    🔴 `facts_uncited` — головне число цього блоку. Факт без цитати не
    неправильний, він недоведений, а на вигляд у дереві він такий самий, як
    доведений. Поки його не рахують окремо, база росте, а частка доказаного в
    ній мовчки падає — і помітно це стає лише тоді, коли хтось просить джерело.
    """
    return {
        "facts_uncited": _one(
            con, "SELECT count(*) FROM facts f WHERE NOT EXISTS ("
                 "SELECT 1 FROM citations c WHERE c.fact_id = f.id)"),
        "persons_no_dates": _one(
            con, "SELECT count(*) FROM persons p WHERE NOT EXISTS ("
                 "SELECT 1 FROM facts f WHERE f.person_id = p.id"
                 " AND f.type IN ('birth', 'death') AND f.date_value <> '')"),
        "sources_uncited": _one(
            con, "SELECT count(*) FROM sources s WHERE NOT EXISTS ("
                 "SELECT 1 FROM citations c WHERE c.source_id = s.id)"),
    }


def _capped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Верхівка + чесний хвіст.

    🔴 Обрізати мовчки не можна: «12 типів фактів» на екрані там, де їх 30,
    це той самий тихий знаменник, від якого відмовляється решта застосунку.
    Тому решта лишається рядком «ще N».
    """
    if len(rows) <= TOP_N:
        return rows
    rest = rows[TOP_N:]
    return [*rows[:TOP_N], {"code": "", "n": sum(r["n"] for r in rest),
                            "rest": len(rest)}]


def _coverage(derived: Path) -> dict[str, Any]:
    """Покриття джерел роками, станами й типами записів — із `coverage.json`.

    Файл будує `storage.reindex`; рахувати те саме вдруге тут означало б завести
    другу відповідь на те саме питання. Немає файла — немає блоку: він
    необов'язковий, і вигадувати замість нього нулі нема потреби.

    ⚠ Верхні поля `record_types`/`statuses`/`governorates` у файлі — довідники
    (`{id, label}`), а не підрахунки. Числа живуть у `sources[].spans[]`, і
    брати їх треба звідти: перша редакція цього модуля прийняла довідник за
    зведення й малювала дванадцять нулів із порожніми підписами.
    """
    path = derived / "coverage.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    labels = {**_labels(raw.get("record_types")), **_labels(raw.get("statuses"))}
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    spans = 0
    for src in raw.get("sources") or []:
        if not isinstance(src, dict):
            continue
        for span in src.get("spans") or []:
            if not isinstance(span, dict):
                continue
            spans += 1
            st = str(span.get("status") or "")
            if st:
                by_status[st] = by_status.get(st, 0) + 1
            for rt in span.get("record_types") or []:
                by_type[str(rt)] = by_type.get(str(rt), 0) + 1
    return {
        "year_min": raw.get("year_min"),
        "year_max": raw.get("year_max"),
        "generated": raw.get("generated") or "",
        "sources": len(raw.get("sources") or []),
        "spans": spans,
        "by_status": _tally(by_status, labels),
        "by_record_type": _tally(by_type, labels),
    }


def _labels(items: Any) -> dict[str, str]:
    """`[{"id": "birth", "label": "Народження"}]` → `{"birth": "Народження"}`."""
    if not isinstance(items, list):
        return {}
    out: dict[str, str] = {}
    for r in items:
        if isinstance(r, dict) and r.get("id"):
            out[str(r["id"])] = str(r.get("label") or r["id"])
    return out


def _tally(got: dict[str, int], labels: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{"code": k, "label": labels.get(k, k), "n": n}
                                  for k, n in got.items()]
    rows.sort(key=lambda r: (-r["n"], r["code"]))
    return _capped(rows)
