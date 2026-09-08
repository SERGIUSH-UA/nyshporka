"""🧰 Дії над прочитаним текстом поверх стору: контекст, кроп, голоси, покриття, картка.

Це те, що досі робилось одноразовими скриптами щоразу наново (заміряно на
190 сесіях: ~1 250 читань `.txt` із номером рядка, ~1 300 злиттів двох голосів,
878 кропів руками проти 318 інструментом, ~1 500 лічб сторінок). Кожна дія тут
відповідає одному повторюваному питанню дослідника:

* `ctx` — «який контекст довкола цього рядка» → сторінка, обидва голоси,
  сусіди за геометрією, роки справи, чи бачило око;
* `crop` — «покажи кроп» → вирізка рядка з кадру, з масштабом і поворотом, як
  їх бачив рушій, разом із наступним рядком;
* `voices` — «а що дав Дяк» → два голоси рядок до рядка, де зійшлись і де ні;
* `coverage` — «що не дивились» → кадри → прочитано → у сторі → чим шукали →
  скільки бачило око;
* `whatis` — «що це за справа» → картка з реєстру, паспорта, прогонів і тексту.

🔴 Жодна дія не ходить по теці прогонів: текст і геометрія беруться зі стору,
кадр — за адресою з мети або реєстру справ, паспорт — одним читанням файлу.
"""
from __future__ import annotations

import contextlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from nyshporka.search import store as ST

_DIGITS = re.compile(r"\d+")


# ── адресація ────────────────────────────────────────────────────────────────
def _page_num(name: str) -> int | None:
    """Номер сторінки з імені кадру — ОСТАННЯ група цифр.

    Кадри називають і `0037.JPG`, і `Image00037.jpg`, і `cdiak224-712_0037.txt`;
    людина ж каже «скан 37». Порівнюються числа, а не рядки.
    """
    m = _DIGITS.findall(Path(name).stem)
    return int(m[-1]) if m else None


def scope_runs(scope: str) -> dict[str, Any]:
    """Прогони області: справа, прогін або порожньо. ValueError — не впізнано.

    🔴 Названий прогін розширюється до всіх голосів тієї самої справи. Людина
    називає теку Писаря, а питає «що дав Дяк»: побратим лежить поруч, з тим
    самим ключем або тією самою текою кадрів, і без нього другого голосу не
    було б ні в контексті, ні в порівнянні.
    """
    from nyshporka import htr_store as S

    sc = S.runs_for_scope(scope)
    if sc.get("kind") == "run" and sc["rows"]:
        me = sc["rows"][0]
        key = (me.get("case_key") or "").strip()
        cd = (me.get("case_dir") or "").strip()
        others = [r for r in S.list_cases()
                  if r.get("name") != me.get("name")
                  and ((key and (r.get("case_key") or "").strip() == key)
                       or (cd and (r.get("case_dir") or "").strip() == cd))]
        sc = {**sc, "rows": [me, *others]}
    return sc


def find_page(conn: Any, run: str, page: str) -> str | None:
    """Ім'я сторінки прогону за тим, як її назвала людина.

    Спершу точний збіг імені чи основи, далі — за номером: «73», «0073»,
    «00073.jpg», «Image00073» — усе одна сторінка.
    """
    row = conn.execute(
        "select p.page from pages p join runs r on r.id=p.run_id "
        "where r.run=? and (p.page=? or p.stem=?)", (run, page, Path(page).stem)).fetchone()
    if row:
        return str(row[0])
    want = _page_num(page)
    if want is None:
        return None
    for (pg,) in conn.execute(
            "select p.page from pages p join runs r on r.id=p.run_id where r.run=? "
            "order by p.id", (run,)):
        if _page_num(str(pg)) == want:
            return str(pg)
    return None


def _voices_of(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(прогін, мітка голосу) для всіх прогонів області, по одному на модель."""
    out: list[tuple[str, str]] = []
    for r in rows:
        ids = r.get("engine_ids") or [r.get("engine_id") or r.get("engine") or "?"]
        out.append((str(r["name"]), "+".join(str(x) for x in ids)))
    return out


# ── контекст ─────────────────────────────────────────────────────────────────
def ctx(scope: str, page: str, line: int | None = None, *, window: int = 4,
        full: bool = False) -> dict[str, Any]:
    """Сторінка навколо рядка: усі голоси, сусіди за геометрією, роки, око.

    🔴 Сторінку читати сторінкою, не вікном (правило з приватного конвеєра:
    класифікація по ±2 рядки — це фільтр, а не контекст). Вікно тут лише
    обмежує друк; `full` віддає всю сторінку.
    """
    from nyshporka import htr_store as S

    sc = scope_runs(scope)
    rows = sc["rows"]
    if not rows:
        return {"error": f"у області «{scope}» немає жодного прогону"}
    conn = ST.connect(readonly=True)
    try:
        voices: list[dict[str, Any]] = []
        pid_main: int | None = None
        page_name = ""
        for run, label in _voices_of(rows):
            pg = find_page(conn, run, page)
            if pg is None:
                continue
            text = ST.page_text(run, pg, conn) or []
            voices.append({"run": run, "voice": label, "page": pg, "lines": text})
            if pid_main is None:
                pid_main = ST._page_id(conn, run, pg)
                page_name = pg
        if not voices or pid_main is None:
            return {"error": f"сторінки «{page}» немає в жодному прогоні області «{scope}»"}
        geo = ST._page_lines(conn, pid_main)
    finally:
        conn.close()
    base = voices[0]["lines"]
    n = len(base)
    succ = {ln.no: ln.succ for ln in geo if ln.succ}
    pred = {v: k for k, v in succ.items()}
    if line is not None and not 1 <= line <= n:
        return {"error": f"рядка {line} немає: на сторінці {n} рядків"}
    if full or line is None:
        lo, hi = 1, n
    else:
        lo, hi = max(1, line - window), min(n, line + window)
    aligned = all(len(v["lines"]) == n for v in voices)
    out_lines: list[dict[str, Any]] = []
    for no in range(lo, hi + 1):
        item: dict[str, Any] = {"no": no, "text": base[no - 1] if no <= n else ""}
        if len(voices) > 1:
            item["voices"] = {v["voice"]: (v["lines"][no - 1] if no <= len(v["lines"]) else "")
                              for v in voices[1:]}
        if no == line:
            item["mark"] = "»"
        if succ.get(no):
            item["geo_next"] = succ[no]
        if pred.get(no):
            item["geo_prev"] = pred[no]
        out_lines.append(item)
    key = str(sc.get("key") or "")
    years = S.case_years(key) if key else (None, None)
    eye: dict[str, Any] | None = None
    if key:
        with contextlib.suppress(Exception):
            from nyshporka.pagestore import store as PS

            ref = PS.resolve_case(key)
            st = PS.case_status(ref, scans=[page_name])
            eye = (st.get("scans") or [{}])[0]
    return {"scope": sc["kind"], "case_key": key, "shifra": sc.get("shifra") or "",
            "page": page_name, "line": line, "lines_total": n,
            "voices": [{"run": v["run"], "voice": v["voice"]} for v in voices],
            "aligned": aligned, "years": list(years), "eye": eye,
            "geo_next": succ.get(line) if line else None,
            "geo_prev": pred.get(line) if line else None,
            "window": out_lines}


# ── кроп ─────────────────────────────────────────────────────────────────────
def _rotated(im: Any, orient: int) -> Any:
    from PIL import Image

    if orient == 90:
        return im.transpose(Image.Transpose.ROTATE_90)
    if orient == 180:
        return im.transpose(Image.Transpose.ROTATE_180)
    if orient == 270:
        return im.transpose(Image.Transpose.ROTATE_270)
    return im


def _geometry_size(run: str, page: str) -> list[int] | None:
    """Розмір зображення, у якому лежать рамки: свій `.lines.json`, інакше —
    побратима тієї самої справи (стор позичає в нього й рамки)."""
    from nyshporka import htr_store as S

    geom = S.page_lines(run, page) or {}
    size = geom.get("size")
    if size:
        return [int(size[0]), int(size[1])]
    if "-" in run:
        base = run.rsplit("-", 1)[0]
        bmeta, mine = S.load_meta(base) or {}, S.load_meta(run) or {}
        same = (mine.get("case_key") and mine.get("case_key") == bmeta.get("case_key")) or \
               (mine.get("case_dir") and mine.get("case_dir") == bmeta.get("case_dir"))
        if same:
            geom = S.page_lines(base, page) or {}
            size = geom.get("size")
            if size:
                return [int(size[0]), int(size[1])]
    return None


def crop(scope: str, page: str, line: int, *, with_next: bool = True, wide: bool = False,
         pad: int = 12, scale: float = 1.0, out: str | Path | None = None,
         ) -> dict[str, Any]:
    """Вирізка рядка з кадру — за рамкою рушія, з поворотом і масштабом.

    🔴 Рамки лежать у координатах тієї копії кадру, яку бачив рушій: повернутої
    на `orient` з мети й у розмірі `size` з `.lines.json`. Кадр на диску буває
    інший — більший і неповернутий. Без обох поправок кроп ріже порожнє поле й
    читається як «пустий скан»; заміряно 07.09: три спроби по 40 с на один кроп.

    `with_next` бере в кроп ще й наступний рядок — за геометрією, коли вона
    показує наступника в іншій колонці, інакше за файлом: прізвище часто
    переноситься. `wide` — на всю ширину сторінки.
    """
    from PIL import Image

    from nyshporka import htr_store as S

    sc = scope_runs(scope)
    rows = sc["rows"]
    conn = ST.connect(readonly=True)
    try:
        # 🔴 Рамки позичаються в іншого прогону лише при ТІЙ САМІЙ нарізці
        # (число рядків збігається): перший-ліпший прогін із рамками різав
        # рядок N із чужої сегментації, і картка гортача показувала чужий
        # рядок з виглядом правильного (рецензія 08.09). Названий прогін —
        # перший у переліку області.
        named: tuple[str, str, int, int, int] | None = None
        cands: list[tuple[str, str, int, int, int]] = []
        for r in rows:
            run = str(r["name"])
            pg = find_page(conn, run, page)
            if pg is None:
                continue
            pid = ST._page_id(conn, run, pg)
            if pid is None:
                continue
            row = conn.execute("select geo, nlines from pages where id=?", (pid,)).fetchone()
            item = (run, pg, pid, int(row[0] or 0), int(row[1] or 0))
            if named is None:
                named = item
            cands.append(item)
        if named is None:
            return {"error": f"сторінки «{page}» немає в області «{scope}»"}
        chosen = next((c for c in cands if c[3] and c[4] == named[4]), None)
        if chosen is None:
            return {"error": f"рамок для {named[0]} · {named[1]} немає: прогін без "
                             f"геометрії, а побратими з рамками мають іншу нарізку "
                             f"({named[4]} рядків тут)"}
        run, pg, pid = chosen[0], chosen[1], chosen[2]
        lines = ST._page_lines(conn, pid)
    finally:
        conn.close()
    by_no = {ln.no: ln for ln in lines}
    target = by_no.get(line)
    if target is None or target.box is None:
        return {"error": f"рамки рядка {line} у прогоні {run} немає — прогін без "
                         f"геометрії або рядок порожній"}
    boxes = [target.box]
    nxt_no: int | None = None
    if with_next:
        nxt_no = target.succ or (line + 1 if (line + 1) in by_no else None)
        nxt = by_no.get(nxt_no) if nxt_no else None
        if nxt and nxt.box:
            boxes.append(nxt.box)
    size = _geometry_size(run, pg)
    got = S.resolve_scan(run, pg)
    if got is None:
        return {"error": f"кадру для {run} · {pg} на цій машині немає: мета веде в "
                         f"нікуди, реєстр справ теки не знає"}
    src, orient = got
    with Image.open(src) as raw:
        im = _rotated(raw.convert("RGB"), int(orient))
        k = 1.0
        if size and size[0]:
            if (im.width > im.height) != (size[0] > size[1]):
                im = im.transpose(Image.Transpose.ROTATE_270)
            k = im.width / float(size[0])
        x0 = float(min(b[0] for b in boxes) - pad)
        y0 = float(min(b[1] for b in boxes) - pad)
        x1 = float(max(b[2] for b in boxes) + pad)
        y1 = float(max(b[3] for b in boxes) + pad)
        if abs(k - 1.0) > 0.01:
            x0, y0, x1, y1 = (v * k for v in (x0, y0, x1, y1))
        if wide:
            x0, x1 = 0.0, float(im.width)
        box = (max(0, int(x0)), max(0, int(y0)), min(im.width, int(x1)), min(im.height, int(y1)))
        piece = im.crop(box)
        if scale != 1.0:
            piece = piece.resize((max(1, int(piece.width * scale)),
                                  max(1, int(piece.height * scale))),
                                 Image.Resampling.LANCZOS)
        if out is None:
            from nyshporka.core.workspace import workspace

            dst = workspace().derived / "crops" / run / f"{Path(pg).stem}_l{line}.png"
        else:
            dst = Path(out)
        dst.parent.mkdir(parents=True, exist_ok=True)
        piece.save(dst)
        return {"run": run, "page": pg, "line": line, "next": nxt_no,
                "frame": str(src), "orient": int(orient), "scale_k": round(k, 3),
                "box": list(box), "out": str(dst), "width": piece.width,
                "height": piece.height, "text": target.toks,
                "next_text": by_no[nxt_no].toks if nxt_no and nxt_no in by_no else ""}


# ── голоси ───────────────────────────────────────────────────────────────────
#: Поріг «зійшлись» по нормалізованому рядку. 97, а не 90: на рядку в 30 літер
#: одна заміна дає ~93, а одна літера — це вся різниця між двома прізвищами.
AGREE = 97


def voices(scope: str, page: str, *, lines: tuple[int, int] | None = None
           ) -> dict[str, Any]:
    """Два голоси рядок до рядка: де зійшлись, де розійшлись.

    🔴 Збіг голосів — надійне ЧИТАННЯ, не приналежність (правило приватного
    конвеєра): чужий рід читається так само надійно, як свій. Розбіжність —
    сигнал, що ознака в пікселях і судити має око.
    """
    from rapidfuzz import fuzz

    from nyshporka import htr_store as S

    sc = scope_runs(scope)
    rows = sc["rows"]
    conn = ST.connect(readonly=True)
    try:
        got: list[dict[str, Any]] = []
        for run, label in _voices_of(rows):
            pg = find_page(conn, run, page)
            if pg is None:
                continue
            got.append({"run": run, "voice": label, "page": pg,
                        "lines": ST.page_text(run, pg, conn) or []})
    finally:
        conn.close()
    if not got:
        return {"error": f"сторінки «{page}» немає в області «{scope}»"}
    if len(got) < 2:
        return {"error": f"у області «{scope}» лише один голос ({got[0]['voice']}): "
                         f"порівнювати нема з чим", "voices": [got[0]["voice"]]}
    n = max(len(v["lines"]) for v in got)
    aligned = all(len(v["lines"]) == n for v in got)
    lo, hi = (1, n) if not lines else (max(1, lines[0]), min(n, lines[1]))
    out: list[dict[str, Any]] = []
    agree = disagree = 0
    for no in range(lo, hi + 1):
        texts = {v["voice"]: (v["lines"][no - 1] if no <= len(v["lines"]) else "")
                 for v in got}
        vals = [t for t in texts.values() if t.strip()]
        sim: float | None = None
        if len(vals) >= 2:
            sim = round(fuzz.ratio(S._norm(vals[0]), S._norm(vals[1])), 1)
            if sim >= AGREE:
                agree += 1
            else:
                disagree += 1
        out.append({"no": no, "sim": sim, "agree": (sim is not None and sim >= AGREE),
                    **texts})
    return {"scope": sc["kind"], "case_key": sc.get("key") or "", "page": got[0]["page"],
            "voices": [v["voice"] for v in got], "aligned": aligned,
            "lines_total": n, "agree": agree, "disagree": disagree, "lines": out}


# ── покриття ─────────────────────────────────────────────────────────────────
def coverage(scope: str = "", *, unsearched: bool = False, limit: int = 300
             ) -> dict[str, Any]:
    """Кадри → прочитано → у сторі → чим шукали → скільки бачило око.

    🔴 П'ять чисел, і всі з різних джерел: кадри й прочитане — з реєстру справ,
    свіжість — зі стору, «чим шукали» — зі сліду свіпу, око — зі сховища
    сторінок. Порахувати одне з іншого не можна: саме їх розбіжність і є
    відповіддю на «що не дивились».
    """
    from nyshporka.cases import db as CDB
    from nyshporka.search import trace as TRACE

    q = ""
    run_names: set[str] = set()
    if scope:
        try:
            sc = scope_runs(scope)
            q = str(sc.get("key") or "")
            run_names = {str(r["name"]) for r in sc["rows"]}
        except ValueError:
            q = scope
    try:
        rows = CDB.query_rows(q=q, kind="case", limit=0)
    except FileNotFoundError as exc:
        # Реєстру ще немає — це відповідь, а не поламка: без нього немає ні
        # кадрів, ні «прочитано», і покриття міряти нема від чого.
        return {"scope": scope, "unsearched": unsearched, "cases": [], "truncated": 0,
                "total": {"cases": 0, "frames": 0, "decoded": 0, "with_runs": 0,
                          "in_store": 0, "searched": 0, "eye_touched": 0},
                "why": str(exc)}
    if scope and q and not any(str(r.get("key")) == q for r in rows):
        rows = [r for r in rows if q.lower() in str(r.get("key") or "").lower()]
    elif scope and q:
        rows = [r for r in rows if str(r.get("key")) == q]
    elif scope and run_names:
        # Прогін без ключа справи: покриття лише тих рядків реєстру, що
        # згадують його, а не всього корпусу.
        rows = [r for r in rows
                if run_names & set(json.loads(r.get("htr_runs") or "[]")
                                   if isinstance(r.get("htr_runs"), str)
                                   else (r.get("htr_runs") or []))]
    known: dict[str, str] = {}
    if ST.exists():
        conn = ST.connect(readonly=True)
        try:
            known = ST.stamps(conn)
        finally:
            conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = str(r.get("key") or "")
        raw_runs = r.get("htr_runs") or []
        runs = json.loads(raw_runs) if isinstance(raw_runs, str) else list(raw_runs)
        fresh = sum(1 for x in runs if known.get(x) and known[x] == ST.stamp_of(x))
        searched = TRACE.of(key) if key else []
        item = {"key": key, "shifra": r.get("shifra") or "", "frames": int(r.get("frames") or 0),
                "decoded": int(r.get("htr_pages_max") or 0), "runs": len(runs),
                "in_store": fresh, "searched": [{"q": s.get("q"), "when": s.get("when"),
                                                 "channels": s.get("channels")}
                                                for s in searched[:3]],
                "eye_noted": int(r.get("pages_noted") or 0),
                "eye_full": int(r.get("pages_full") or 0),
                "fuzzy_stage": r.get("fuzzy_stage") or ""}
        if unsearched and (not runs or searched or item["fuzzy_stage"] not in ("", "none")):
            continue
        out.append(item)
    total = {"cases": len(out), "frames": sum(x["frames"] for x in out),
             "decoded": sum(x["decoded"] for x in out),
             "with_runs": sum(1 for x in out if x["runs"]),
             "in_store": sum(1 for x in out if x["runs"] and x["in_store"] == x["runs"]),
             "searched": sum(1 for x in out if x["searched"] or x["fuzzy_stage"] not in ("", "none")),
             "eye_touched": sum(1 for x in out if x["eye_noted"])}
    return {"scope": scope, "unsearched": unsearched, "total": total,
            "cases": out[:limit], "truncated": max(0, len(out) - limit)}


# ── картка справи ────────────────────────────────────────────────────────────
_CAP_TOKEN = re.compile(r"^[A-ZА-ЯІЇЄҐѲѢ][^\W\d_]{4,}$")
_STOP = {"Священникъ", "Крестьяне", "Крестьянинъ", "Крестьянка", "Іоаннъ", "Марія",
         "Анна", "Иванъ", "Іосифъ", "Петръ", "Василій", "Григорій", "Николай", "Михаилъ",
         "Ѳеодоръ", "Стефанъ", "Евдокія", "Параскева", "Пелагія", "Екатерина"}


def whatis(scope: str) -> dict[str, Any]:
    """Картка справи: реєстр, паспорт, прогони, слід пошуку, око, слова тексту.

    «Топ слів» — найчастіші слова з великої літери в тексті головного прогону,
    без найпоширеніших імен і формул. Це не покажчик, а підказка: які прізвища
    й топоніми стоять у книзі найчастіше.
    """
    from nyshporka import htr_store as S
    from nyshporka.cases import db as CDB
    from nyshporka.search import trace as TRACE

    sc = scope_runs(scope)
    key = str(sc.get("key") or "")
    row: dict[str, Any] = {}
    if key:
        with contextlib.suppress(FileNotFoundError):
            for r in CDB.query_rows(q=key, limit=5):
                if str(r.get("key") or "") == key:
                    row = r
                    break
    source: dict[str, Any] = {}
    path = str(row.get("path") or "")
    if path:
        from nyshporka.core.workspace import workspace

        p = Path(path)
        p = p if p.is_absolute() else workspace().root / p
        side = p / "_source.json" if p.is_dir() else p.parent / "_source.json"
        with contextlib.suppress(OSError, ValueError):
            source = json.loads(side.read_text(encoding="utf-8"))
    runs_out: list[dict[str, Any]] = []
    top: list[tuple[str, int]] = []
    if ST.exists():
        conn = ST.connect(readonly=True)
        try:
            for r in sc["rows"]:
                run = str(r["name"])
                got = conn.execute("select id, pages, lines, geo, model, script "
                                   "from runs where run=?", (run,)).fetchone()
                if not got:
                    runs_out.append({"run": run, "in_store": False})
                    continue
                runs_out.append({"run": run, "in_store": True, "pages": got[1],
                                 "lines": got[2], "geo": got[3], "model": got[4],
                                 "script": got[5], "engine_ids": r.get("engine_ids") or []})
            if runs_out and runs_out[0].get("in_store"):
                rid = conn.execute("select id from runs where run=?",
                                   (runs_out[0]["run"],)).fetchone()[0]
                cnt: Counter[str] = Counter()
                for (pid,) in conn.execute("select id from pages where run_id=?", (rid,)):
                    for ln in ST._raw_lines(conn, int(pid)):
                        for tok in S._TOKEN_RE.findall(ln):
                            if _CAP_TOKEN.match(tok) and tok not in _STOP:
                                cnt[tok] += 1
                top = cnt.most_common(20)
        finally:
            conn.close()
    phantoms: dict[str, int] = {}
    for r in sc["rows"]:
        with contextlib.suppress(Exception):
            ph = S.phantom_pages(str(r["name"]))
            phantoms[str(r["name"])] = len(ph.get("pages") or []) if isinstance(ph, dict) else 0
    eye: dict[str, Any] | None = None
    if key:
        with contextlib.suppress(Exception):
            from nyshporka.pagestore import store as PS

            eye = PS.case_status(PS.resolve_case(key))
    return {"scope": sc["kind"], "case_key": key, "shifra": sc.get("shifra") or row.get("shifra") or "",
            "title": row.get("title") or "", "years": [row.get("year_from"), row.get("year_to")],
            "place": row.get("place_raw") or "", "doc_type": row.get("doc_type") or "",
            "frames": row.get("frames"), "source": {k: source.get(k) for k in
                                                    ("archive", "shifra", "title", "record_type",
                                                     "place", "script", "langs", "year_from",
                                                     "year_to", "downloaded_via", "note")
                                                    if source.get(k) is not None},
            "runs": runs_out, "phantom_pages": phantoms,
            "searched": TRACE.of(key) if key else [],
            "eye": eye, "top_words": top}



# ── find: усі канали разом ───────────────────────────────────────────────────
def _query_is_profile(q: str) -> bool:
    """Чи запит є написанням прізвища профілю — стемом, не схожістю."""
    from nyshporka import htr_store as S

    try:
        from nyshporka.core import profile as PROF

        forms, whose = PROF.forms_for_query(q)
    except Exception:
        return False
    if not whose:
        return False
    want = {S._norm(w) for w in S._TOKEN_RE.findall(q)}
    have = {S._norm(f) for f in forms} | {S._norm(whose)}
    try:
        prof = PROF.active()
        have |= {S._norm(x) for x in (prof.all_spellings() or [])}
    except Exception:
        pass
    return bool(want) and want <= {h for h in have if h}


def find(q: str, scope: str = "", *, thresh: int = 78, limit: int = 40,
         context: int = 1) -> dict[str, Any]:
    """Пошук усіма каналами пакета з журналом заходу.

    🔴 Журнал — не прикраса. «Шукай ще» доти означало імпровізацію, бо жоден
    пошук не казав, які канали по цій справі вже ганяли. Тут кожен канал
    названий: ганяли — з числами, не ганяли — з причиною.
    """
    from nyshporka import htr_store as S
    from nyshporka.cases import db as CDB
    from nyshporka.search import selfcheck as SC
    from nyshporka.search import trace as TRACE

    in_case = bool(scope)
    # 🔴 Запит «про профіль» — лише коли він СТЕМОМ збігається з формою профілю,
    # а не схожий на 85: сусідній рід із тим самим коренем схожий на 85, і профіль
    # підмішував 26 форм роду в пошук конфузера (рецензія 08.09). Якорі — теж
    # лише для профільного запиту: кін чужому прізвищу ні до чого.
    about_profile = _query_is_profile(q)
    res = S.search(q, name=scope or None, thresh=thresh, limit=limit, context=context,
                   given=True, folk=False, rank=True, profile=about_profile,
                   anchors=in_case and about_profile)
    if res.get("error") and not res.get("hits"):
        return {"error": str(res["error"])}
    anchor: dict[str, Any] = res.get("anchor") or {"on": False}
    key = str(res.get("scope_key") or "")
    sc: dict[str, Any] = scope_runs(scope) if scope else {"rows": S.list_cases(), "kind": "all"}
    rows: list[dict[str, Any]] = list(sc["rows"])
    voices = sorted({str(x) for r in rows for x in (r.get("engine_ids") or [])})
    scripts = sorted({str(r.get("script") or "") for r in rows if r.get("script")})
    frames = decoded = None
    if key:
        with contextlib.suppress(Exception):
            for r in CDB.query_rows(q=key, limit=5):
                if str(r.get("key") or "") == key:
                    frames = int(r.get("frames") or 0)
                    decoded = int(r.get("htr_pages_max") or 0)
                    break
    known: dict[str, str] = {}
    if ST.exists():
        conn = ST.connect(readonly=True)
        try:
            known = ST.stamps(conn)
        finally:
            conn.close()
    fresh = sum(1 for r in rows if known.get(str(r["name"])) == ST.stamp_of(str(r["name"])))
    total = int(res.get("total") or 0)
    shown = list(res.get("hits") or [])
    # Сторінок із хітами — лише коли показано ВСЕ; інакше число брехало б
    # («262387 хітів / 2 стор.» на обрізаній видачі).
    pages_hit: int | None = (len({(h["name"], h["page"]) for h in shown})
                             if total <= len(shown) else None)
    has_latin = any("skryba" in v for v in voices) or "latin" in scripts
    if has_latin and "latin" not in scripts:
        scripts = sorted({*scripts, "latin"})
    channels: list[dict[str, Any]] = [
        {"id": "surname", "label": "прізвище (ціле слово + корінь, склейки в кандидатах)",
         "ran": True, "hits": total, "pages": pages_hit,
         "stems": len(res.get("stems") or []), "dropped": res.get("stems_dropped") or []},
        {"id": "anchor", "label": "якорі: ім'я + по батькові роду у вікні років",
         "ran": bool(anchor.get("on")) and bool(anchor.get("given")) and bool(anchor.get("patronymic")),
         "hits": int(anchor.get("total") or 0),
         "why": ("потребує справи (--case): вікно якорів береться з її років" if not in_case
                 else "запит не про рід профілю — кін профілю тут ні до чого" if not about_profile
                 else ("у профілі й каноні немає пари ім'я + по батькові у вікні "
                       f"{anchor.get('years') or 'справи'}" if anchor.get("on") else ""))},
        {"id": "latin", "label": "латинський голос (Скриба) у тій самій області",
         "ran": has_latin,
         "why": "" if has_latin
                else "у області немає прогону латинкою: польський текст читати Скрибою"},
    ]
    selfcheck: dict[str, Any] | None = None
    if in_case and key:
        # Один пошук: самоперевірка рахує по сторінках усіх хітів, які пошук
        # уже віддав (`hit_pages`), а не другим повним проходом.
        rep = SC.run(scope, q, thresh=max(thresh, 78), limit=max(limit, 100),
                     shown_hits=shown,
                     all_pages=[(str(a), str(b)) for a, b in (res.get("hit_pages") or [])])
        selfcheck = SC.as_dict(rep)
        channels.append({"id": "selfcheck", "label": "самоперевірка на аркушах, виписаних оком",
                         "ran": bool(rep.measured), "why": rep.why or "",
                         "eye": rep.eye, "found": len(rep.found), "shown": len(rep.shown),
                         "missed": rep.missed})
    ledger = {"frames": frames, "decoded": decoded, "runs": len(rows), "in_store": fresh,
              "unindexed": int(res.get("unindexed") or 0), "voices": voices,
              "scripts": scripts, "backend": res.get("backend"),
              "pages_scoped": res.get("pages"), "channels": channels,
              "searched_before": TRACE.of(key) if key else []}
    return {"q": q, "scope": sc["kind"], "case_key": key, "shifra": res.get("scope_shifra") or "",
            "hits": res.get("hits") or [], "total": res.get("total"),
            "stems": res.get("stems"), "stems_dropped": res.get("stems_dropped") or [],
            "anchor": anchor, "selfcheck": selfcheck, "ledger": ledger}



# ── етап 4: гортач із вердиктами ─────────────────────────────────────────────
VERDICTS = ("hit", "known", "other-surname", "noise", "unreadable")
VERDICT_LABEL = {"hit": "наш рід", "known": "уже в каноні", "other-surname": "інше прізвище",
                 "noise": "не прізвище", "unreadable": "не читається"}
VERDICTS_FILE = "verdicts.json"


def _verdicts_path() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / VERDICTS_FILE


def verdicts_load(key: str) -> dict[str, dict[str, Any]]:
    """Вердикти по справі: «прогін|сторінка|рядок» → запис."""
    try:
        data = json.loads(_verdicts_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    got = data.get(key) if isinstance(data, dict) else None
    return dict(got) if isinstance(got, dict) else {}


def _verdicts_save(key: str, items: dict[str, dict[str, Any]]) -> None:
    p = _verdicts_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    cur: dict[str, Any] = dict(data[key]) if isinstance(data.get(key), dict) else {}
    cur.update(items)
    data[key] = cur
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _crop_b64(scope: str, page: str, line: int, *, max_w: int = 1400) -> str:
    """Кроп рядка як JPEG у base64 для вбудування в HTML; порожньо — не вийшло."""
    import base64
    import io

    from PIL import Image

    got = crop(scope, page, line, with_next=True)
    if got.get("error"):
        return ""
    try:
        with Image.open(got["out"]) as raw:
            im: Any = raw.convert("RGB")
            if im.width > max_w:
                im = im.resize((max_w, round(im.height * max_w / im.width)),
                               Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72, optimize=True)
    except OSError:
        return ""
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _esc(s: Any) -> str:
    import html

    return html.escape(str(s or ""))


def sheet(q: str, scope: str, *, thresh: int = 78, limit: int = 60, crops: int = 40,
          out: str | Path | None = None) -> dict[str, Any]:
    """HTML-гортач: кандидати з контекстом, другим голосом і кропом, поле вердикту.

    🔴 Вердикт виносить людина. Гортач не має кнопки «закрити все»: кожен рядок
    отримує свій вибір, а «наш рід» не проставляється за замовчуванням.
    Колонка вердикту експортується в JSON, який `verdicts_import` заносить у
    сховище сторінок — щоб наступна сесія не передивлялась той самий аркуш.
    """
    got = find(q, scope, thresh=thresh, limit=limit, context=1)
    if got.get("error"):
        return {"error": str(got["error"])}
    key = str(got.get("case_key") or "")
    known = verdicts_load(key) if key else {}
    hits = list(got.get("hits") or [])
    cards: list[dict[str, Any]] = []
    n_crops = 0
    for h in hits:
        run, page, no = str(h["name"]), str(h["page"]), int(h["line_no"])
        ck = f"{run}|{page}|{no}"
        img = ""
        if n_crops < crops:
            img = _crop_b64(run, page, no)
            n_crops += bool(img)
        prev = known.get(ck) or {}
        cards.append({"key": ck, "run": run, "page": page, "line": no,
                      "score": h.get("score"), "matched": h.get("matched"),
                      "text": h.get("line"), "stem": h.get("stem"),
                      "before": (h.get("context") or {}).get("before") or [],
                      "after": (h.get("context") or {}).get("after") or [],
                      "alt": (h.get("alt") or {}).get("line") or "",
                      "rank_why": h.get("rank_why") or "", "img": img,
                      "verdict": prev.get("verdict") or "", "note": prev.get("note") or ""})
    led = got["ledger"]
    html_doc = _render_sheet(q, got, cards, led)
    if out is None:
        from nyshporka.core.workspace import workspace

        safe = re.sub(r"[^\w.-]+", "_", f"{key or scope}_{q}")
        dst = workspace().derived / "sheets" / f"{safe}.html"
    else:
        dst = Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(html_doc, encoding="utf-8")
    return {"out": str(dst), "cards": len(cards), "crops": n_crops, "case_key": key,
            "total": got.get("total"), "known_verdicts": len(known), "ledger": led}


def _render_sheet(q: str, got: dict[str, Any], cards: list[dict[str, Any]],
                  led: dict[str, Any]) -> str:
    dl = _esc(re.sub(r"[^\w.-]+", "_", str(got.get("case_key") or "case")))
    opts = "".join(f'<option value="{v}">{_esc(VERDICT_LABEL[v])}</option>' for v in VERDICTS)
    parts: list[str] = []
    for c in cards:
        ctx_b = "".join(f'<div class="ctx">↑ {_esc(x)}</div>' for x in c["before"])
        ctx_a = "".join(f'<div class="ctx">↓ {_esc(x)}</div>' for x in c["after"])
        alt = f'<div class="alt">2-й голос: {_esc(c["alt"])}</div>' if c["alt"] else ""
        img = (f'<img src="data:image/jpeg;base64,{c["img"]}" alt="кроп">' if c["img"]
               else '<div class="noimg">кропу немає (кадр не знайдено або без геометрії)</div>')
        why = f' <span class="why">↓ {_esc(c["rank_why"])}</span>' if c["rank_why"] else ""
        sel = opts.replace(f'value="{c["verdict"]}"', f'value="{c["verdict"]}" selected') \
            if c["verdict"] else opts
        parts.append(f'''<section class="card" data-key="{_esc(c["key"])}" data-run="{_esc(c["run"])}"
 data-page="{_esc(c["page"])}" data-line="{c["line"]}">
<header><b>{_esc(c["score"])}</b> · {_esc(c["run"])} · {_esc(c["page"])} · рядок {c["line"]}
 · <span class="m">{_esc(c["matched"])}</span>{why}</header>
{ctx_b}<div class="line">» {_esc(c["text"])}</div>{ctx_a}{alt}
{img}
<div class="verdict"><label>вердикт <select><option value="">—</option>{sel}</select></label>
<label>прізвище як у джерелі <input class="surname" placeholder="лише для «наш рід» / «уже в каноні»"></label>
<label>примітка <input class="note" value="{_esc(c["note"])}"></label></div>
</section>''')
    chans = " · ".join(f"{ch['id']} {'✓' if ch['ran'] else '✗'}" for ch in led.get("channels") or [])
    head = (f"кадрів {led.get('frames') if led.get('frames') is not None else '?'} · "
            f"прочитано {led.get('decoded') if led.get('decoded') is not None else '?'} · "
            f"у сторі {led.get('in_store')}/{led.get('runs')} · голоси "
            f"{', '.join(led.get('voices') or []) or '—'} · канали: {chans}")
    return f'''<!doctype html><html lang="uk"><head><meta charset="utf-8">
<title>гортач · {_esc(q)} · {_esc(got.get("shifra") or got.get("case_key") or "")}</title>
<style>
body{{font:15px/1.4 system-ui,sans-serif;margin:0;padding:16px 20px;background:#f6f4ef;color:#222}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#555;margin-bottom:14px}}
.card{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin:0 0 12px}}
header b{{font-size:18px}} .m{{background:#ffe9a8;padding:0 4px}} .why{{color:#a55}}
.ctx{{color:#777}} .line{{font-size:17px;margin:4px 0}} .alt{{color:#357;font-style:italic}}
img{{max-width:100%;border:1px solid #ccc;margin:8px 0;display:block}}
.noimg{{color:#999;font-style:italic;margin:6px 0}}
.verdict{{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-top:6px}}
.verdict input{{width:260px}} select{{font-size:15px}}
.bar{{position:sticky;top:0;background:#f6f4ef;padding:8px 0;border-bottom:1px solid #ccc;margin-bottom:12px}}
button{{font-size:15px;padding:6px 12px}} textarea{{width:100%;height:160px;margin-top:8px}}
.card.done{{border-color:#8b8}} .card.done header{{color:#585}}
</style></head><body>
<h1>«{_esc(q)}» · {_esc(got.get("shifra") or got.get("case_key") or got.get("scope"))}</h1>
<div class="sub">{_esc(head)} · показано {len(cards)} із {_esc(got.get("total"))}</div>
<div class="bar"><button onclick="collect()">Зібрати вердикти → JSON</button>
 <span id="cnt"></span>
 <div><small>Далі: <code>nysh text verdicts &lt;файл.json&gt; --case &lt;справа&gt;</code> — занесе в сховище сторінок.</small></div>
<textarea id="out" placeholder="тут з'явиться JSON"></textarea></div>
{"".join(parts)}
<script>
function collect(){{
  const rows=[];
  document.querySelectorAll('.card').forEach(c=>{{
    const v=c.querySelector('select').value; if(!v) return;
    c.classList.add('done');
    rows.push({{run:c.dataset.run,page:c.dataset.page,line_no:parseInt(c.dataset.line),
      verdict:v,surname:c.querySelector('.surname').value.trim(),
      note:c.querySelector('.note').value.trim(),source:'sheet'}});
  }});
  const txt=JSON.stringify(rows,null,1);
  document.getElementById('out').value=txt;
  document.getElementById('cnt').textContent=rows.length+' вердиктів';
  try{{
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([txt],{{type:'application/json'}}));
    a.download='verdicts_{dl}.json';
    a.click();
  }}catch(e){{}}
}}
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',e=>{{
  e.target.closest('.card').classList.toggle('done',!!e.target.value);}}));
</script></body></html>'''


def verdicts_import(path: str | Path, scope: str, *, q: str = "", agent: str = "text.verdicts"
                    ) -> dict[str, Any]:
    """Занести вердикти з JSON гортача у сховище сторінок і в журнал вердиктів.

    🔴 Кожен переглянутий аркуш іде в сховище — і «не прізвище», і «не
    читається», не лише «наш рід»: негативний результат коштує тих самих очей,
    а без запису наступна сесія передивиться той самий аркуш. Статус аркуша —
    `partial`: вердикт по рядку не є повним переліком прізвищ сторінки.
    """
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote

    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": f"файл вердиктів не читається: {exc}"}
    if not isinstance(rows, list):
        return {"error": "очікувався JSON-масив вердиктів"}
    sc = scope_runs(scope)
    key = str(sc.get("key") or "")
    if not key:
        return {"error": f"область «{scope}» не має ключа справи — вердикти нікуди класти"}
    ref = PS.resolve_case(key)
    existing = (PS.load_case(ref) or PS._empty_case(ref)).pages
    # 🔴 Око записує «00301», мета прогону — «00301.jpg». Нотатка кладеться
    # під ІСНУЮЧИМ ключем аркуша, інакше той самий аркуш подвоюється, і облік
    # ока («birth, full») підміняється вердиктом рядка (рецензія 08.09).
    by_stem = {Path(k).stem.lower(): k for k in existing}
    items: dict[str, dict[str, Any]] = {}
    notes: list[PageNote] = []
    bad: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = str(r.get("verdict") or "")
        page = str(r.get("page") or "")
        if v not in VERDICTS or not page:
            bad.append(str(r))
            continue
        # 🔴 Вердикт про прізвище («наш рід», «уже в каноні», «інше прізвище»)
        # приймається лише з гортача, тобто від людини (`source: sheet`, який
        # ставить кнопка). Агент, зібравши JSON руками, може закрити хіба
        # «не прізвище» й «не читається» — те, що йому й дозволено.
        if v in ("hit", "known", "other-surname") and str(r.get("source") or "") != "sheet":
            bad.append(f"{r.get('run')}|{page}|{r.get('line_no')}: «{VERDICT_LABEL[v]}» "
                       f"без походження з гортача — вердикт про прізвище виносить людина")
            continue
        page = by_stem.get(Path(page).stem.lower(), page)
        ck = f"{r.get('run')}|{page}|{r.get('line_no')}"
        items[ck] = {"verdict": v, "note": str(r.get("note") or ""),
                     "surname": str(r.get("surname") or ""), "q": q,
                     "when": time.strftime("%Y-%m-%d"), "by": agent}
        surnames = [str(r["surname"])] if r.get("surname") and v in ("hit", "known") else []
        comment = f"вердикт пошуку{(' «' + q + '»') if q else ''}, рядок {r.get('line_no')}: " \
                  f"{VERDICT_LABEL[v]}" + (f" — {r['note']}" if r.get("note") else "")
        prev = existing.get(page)
        # Тип і спосіб уже описаного аркуша не затираються вердиктом рядка:
        # «birth», побачений оком, не стає «other» (рецензія 08.09).
        notes.append(PageNote(scan=page, page_type=prev.page_type if prev else "other",
                              surnames=surnames, status="partial",
                              method=prev.method if prev else "visual",
                              comment=comment, agent=agent))
    if not items:
        return {"error": "жодного дійсного вердикту в файлі", "bad": bad[:5]}
    rep = PS.annotate_pages(ref, notes)
    _verdicts_save(key, items)
    return {"case_key": key, "shifra": ref.shifra, "imported": len(items),
            "pages_added": len(rep.added), "pages_merged": len(rep.merged),
            "errors": rep.errors, "bad": bad[:5],
            "by_verdict": dict(Counter(x["verdict"] for x in items.values()))}



# ── етап 6: регекс по шарах поза декодом ─────────────────────────────────────
#: Шари простору й де вони лежать. «Нотатки» — усе під `reports/`, КРІМ теки
#: прогонів: та тримає понад мільйон файлів, і обхід її коштує хвилини.
LAYERS = ("canon", "opys", "notes")


def layer_files(layer: str, *, extra: list[str] | None = None) -> list[Path]:
    """Файли шару. Обхід дешевий за побудовою: канон — сотні карток, описи —
    десятки TSV і текстів OCR, нотатки — теки `reports/` без `htr`."""
    from nyshporka.core.workspace import workspace

    ws = workspace()
    out: list[Path] = []
    if layer == "canon":
        out += sorted(ws.canonical.rglob("*.md")) if ws.canonical.is_dir() else []
    elif layer == "opys":
        raw = ws.raw
        if raw.is_dir():
            for d in sorted(raw.iterdir()):
                reg = d / "registry"
                if reg.is_dir():
                    out += sorted(reg.glob("*.tsv"))
                for side in sorted(d.glob("*_opys*.tsv")):
                    out.append(side)
        der = ws.derived
        if der.is_dir():
            for d in sorted(der.iterdir()):
                if d.is_dir() and "opys" in d.name.lower():
                    out += sorted(d.rglob("*.txt"))[:5000]
    elif layer == "notes":
        rep = ws.reports
        if rep.is_dir():
            out += sorted(rep.glob("*.md"))
            for d in sorted(rep.iterdir()):
                if d.is_dir() and d.name != "htr":
                    out += sorted(d.rglob("*.md"))
    for e in extra or []:
        p = Path(e)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += sorted(x for x in p.rglob("*") if x.suffix.lower() in (".md", ".txt", ".tsv", ".yaml", ".yml", ".json"))
    return out


def grep_layers(pattern: str, layers: list[str], *, ignore_case: bool = True,
                limit: int = 100, context: int = 0, extra: list[str] | None = None
                ) -> dict[str, Any]:
    """Регекс по канону, описах і нотатках — щоб «ми це вже знаємо?» було одним
    запитом, а не грепом по чотирьох схованках."""
    import re as _re

    flags = _re.IGNORECASE if ignore_case else 0
    try:
        rx = _re.compile(pattern, flags)
    except _re.error as exc:
        return {"error": f"регекс не розбирається: {exc}"}
    hits: list[dict[str, Any]] = []
    per_layer: dict[str, dict[str, int]] = {}
    from nyshporka.core.workspace import workspace

    root = workspace().root
    for layer in layers:
        files = layer_files(layer, extra=extra if layer == "notes" else None)
        n_files = n_hits = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            n_files += 1
            lines = text.split("\n")
            for i, ln in enumerate(lines, 1):
                if not rx.search(ln):
                    continue
                n_hits += 1
                if len(hits) >= limit:
                    continue
                try:
                    rel = str(f.relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel = str(f)
                h: dict[str, Any] = {"layer": layer, "file": rel, "line_no": i,
                                     "line": ln.strip()[:400]}
                if context:
                    h["before"] = [x.strip()[:200] for x in lines[max(0, i - 1 - context):i - 1]]
                    h["after"] = [x.strip()[:200] for x in lines[i:i + context]]
                hits.append(h)
        per_layer[layer] = {"files": n_files, "hits": n_hits}
    return {"hits": hits, "total": sum(v["hits"] for v in per_layer.values()),
            "layers": per_layer}
