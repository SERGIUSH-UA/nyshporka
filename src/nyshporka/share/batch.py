"""📦 Пачка справ у Супрягу: пакування й заливка кількох справ одночасно.

🔴 Не процес на справу. Сто справ, віддані циклом `nysh share pack` +
`nysh share publish`, платять за запуск інтерпретатора на кожен крок (на
Windows ~2,5 с), а самі справи йдуть строго одна за одною. Хоча пакування
впирається в диск і процесор, а заливка — в мережу й сервер, і одне на друге
не чекає. Замір 11.10.2026 (ф.224, 1 400 справ, дві такі петлі поруч): ~20 с
на справу в петлі, третина з них — запуски; ~6 справ за хвилину.

Тут кожен воркер — довгоживучий процес: пакет імпортується один раз, далі
справа за справою `share.pack` → `share.publish`. Це ті самі операції, що
кличе CLI, тож ворота, журнал і відповіді пулу ті самі, що й у ручній віддачі.

🔴 Процеси, а не потоки: пакування — це обхід тисяч файлів прогону й gzip
геометрії, і під одним GIL чотири потоки пакували б заледве швидше за один.

Модуль навмисно не імпортує доменного коду на рівні модуля: воркер мусить
узяти простір (`_init`) раніше, ніж щось візьме корінь.
"""
from __future__ import annotations

import contextlib
import io
import sys
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, as_completed
from typing import Any

#: Скільки справ іде одночасно, коли не сказано інакше.
JOBS = 4
#: Стеля паралелі пакування: кожен воркер — процес із пакетом у пам'яті, а
#: пакування — диск і процесор тієї самої машини.
MAX_JOBS = 8
#: Скільки справ одночасно ЗАЛИВАЄТЬСЯ, хоч би скільки пакувалось.
#:
#: 🔴 Пул тримає на людину не більше трьох незавершених заливань (від реєстрації
#: до перевірки) і четверту відбиває 429 «Завершіть попередні заливання» з
#: Retry-After 20 хв. Шість воркерів без цієї межі зупинили першу пачку на
#: тридцятій справі з тисячі (11.10.2026). Межа тут — та сама, що на сервері:
#: якщо слот займе ще хтось (черга, друга сесія), справа перечекає (`CHEKATY`).
PUBLISH_SLOTS = 3
#: Паузи між спробами заливки після 429, секунди (~2,5 хв разом). Незавершене
#: заливання сусіда закінчується за секунди; якщо 429 тримається довше — це
#: справжня стеля (година, доба), і пачка зупиняється.
CHEKATY: tuple[float, ...] = (5, 10, 20, 30, 30, 30, 30)
#: Найкоротший `Retry-After`, який слот заливки перечікує сам, замість кроку
#: `CHEKATY`. Довше — рішення пачки (`viddaty_dochekuiuchys`), а не воркера.
CHEKATY_SAM = 60.0
#: Найдовше, скільки `share push --wait` чекає на стелю пулу за раз. Денна норма
#: ковзна, тож довше за добу (і запас на годинники) пул не просить.
CHEKATY_NAIDOVSHE = 26 * 3600.0

#: На якому кроці зупинилась справа.
PACK = "pack"
PUBLISH = "publish"
WORKER = "worker"

#: Що сталося з нотатником справи (`--notes`); решта значень — текст відмови.
NOTES_OK = "ok"
NOTES_NONE = "none"

Item = dict[str, Any]
Row = dict[str, Any]


def jobs_in_range(jobs: int) -> int:
    return max(1, min(MAX_JOBS, int(jobs or JOBS)))


def stderr(text: str) -> None:
    """Рядок ходу — у stderr: stdout у `--json` читає програма.

    🔴 У пайпі агента на Windows stderr буває cp1251/cp1252, а «✓» і «…» там
    немає: голий print валив би пачку на рядку про її хід.
    """
    enc = getattr(sys.stderr, "encoding", None) or "utf-8"
    sys.stderr.write(text.encode(enc, "replace").decode(enc) + "\n")
    sys.stderr.flush()


#: Слоти заливки цього процесу (`PUBLISH_SLOTS`); `None` — справи йдуть по одній.
_SLOTY: Any = None


def _init(ws: Any, sloty: Any = None) -> None:
    """Воркер працює в тому самому просторі, що й той, хто покликав пачку.

    🔴 Простір передається явно, а не шукається драбиною заново: людина могла
    назвати його прапорцем `--workspace`, а прапорець живе лише в батьківському
    процесі. Без цього воркер пакував би справи з іншого простору.

    `sloty` — спільний на всі воркери семафор заливки: межу пулу тримають усі
    процеси разом, а не кожен свою.
    """
    global _SLOTY
    from nyshporka.core.workspace import use

    use(ws)
    _SLOTY = sloty


def _protsesy(jobs: int) -> Executor:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    from nyshporka.core.workspace import workspace

    # `spawn` і на POSIX: `fork` процесу з живими потоками (httpx, логування)
    # успадковує їхні замки в довільному стані.
    ctx = mp.get_context("spawn")
    return ProcessPoolExecutor(max_workers=jobs, mp_context=ctx, initializer=_init,
                               initargs=(workspace(), ctx.BoundedSemaphore(PUBLISH_SLOTS)))


#: Службове поле справи пачки: причина заміни свого чинного внеску
#: (`share push --replace-own`). У `share.pack` не їде — лише в заливку.
REPLACE_WHY = "_replace_why"


def _zalyty(path: str, row: Row, private_ok: bool = False, replace_why: str = "") -> Any:
    """`share.publish` у слоті заливки; на 429 — пауза й ще раз (`CHEKATY`).

    🔴 Покроковий хід заливки («заливаю текст…», «етапи: …») тут глушиться:
    від кількох воркерів одразу це шість перемішаних рядків на справу. Живість
    пачки показує рядок на справу (`riadok`), етапи лишаються в `etapy`.
    """
    from nyshporka import ops as O

    for pauza in (*CHEKATY, None):
        with _SLOTY if _SLOTY is not None else contextlib.nullcontext(),                 contextlib.redirect_stderr(io.StringIO()):
            viddano = O.call("share.publish", {
                "path": path, "private_ok": private_ok,
                **({"replace_own": True, "why": replace_why} if replace_why else {})})
        if viddano.ok or not (viddano.data or {}).get("rate_limited") or pauza is None:
            return viddano
        # Повтор безпечний: пул упізнає той самий зміст і не заведе другий внесок.
        row["retries"] = int(row.get("retries") or 0) + 1
        # Пул сам сказав, коли звільниться слот, і це скоро — чекати саме стільки.
        prosyt = (viddano.data or {}).get("retry_after")
        if isinstance(prosyt, (int, float)) and prosyt <= CHEKATY_SAM:
            pauza = max(pauza, float(prosyt))
        time.sleep(pauza)
    return viddano


def _etap(etapy: Any, name: str) -> float | None:
    for row in etapy or []:
        if isinstance(row, dict) and row.get("etap") == name:
            return row.get("sec")
    return None


def _notatnyk(case: str, private_ok: bool = False) -> str:
    """`note.push` справи: `ok`, `none` (сховища сторінок немає) або текст відмови.

    🔴 Справа без сховища сторінок — не збій нотатника: віддавати нема чого, і
    в підсумку пачки вона не має стояти поруч зі справжніми відмовами.
    """
    from nyshporka import ops as O
    from nyshporka.pagestore import store

    try:
        if store.load_case(store.resolve_case(case)) is None:
            return NOTES_NONE
    except Exception:
        pass  # шифру розбере сама операція й назве причину
    env = O.call("note.push", {"case": case, "private_ok": private_ok})
    return NOTES_OK if env.ok else (env.error or "note.push відмовив")


def odna(item: Item, notes: bool = False) -> Row:
    """Одна справа: `share.pack` → `share.publish` (→ `note.push`). Не кидає.

    Відповідь — рядок звіту. 🔴 Справа, що не спакувалась чи не залилась, не
    зупиняє решти: людина попросила віддати пачку, а не першу-ліпшу. Зупиняє
    лише стеля пулу (429), що не минула за `CHEKATY`, і вирішує це той, хто
    роздає справи (`viddaty`).
    Відмова нотатника справу невіддану не робить: текст у пулі вже лежить.
    """
    from nyshporka import ops as O
    from nyshporka.share.upload import OUTCOME_TEXT, VIDDANO, VZHE_Ye

    pochatok = time.monotonic()
    row: Row = {"case": str(item.get("case") or ""), "ok": False, "stage": PACK,
                "warnings": []}
    try:
        spakovano = O.call("share.pack", {k: v for k, v in item.items() if k != REPLACE_WHY})
        row["warnings"] += [w.as_dict() for w in spakovano.warnings]
        if not spakovano.ok:
            row["error"] = spakovano.error
            return row
        d = spakovano.data or {}
        row["shifra"] = str(((d.get("manifest") or {}).get("case") or {}).get("shifra") or "")
        # Справа сегментами (вирізки по селах, картотека) пакується в теку, і
        # `share.publish` віддає її цілою, сегмент за сегментом.
        row["path"] = str(d.get("path") or d.get("dir") or "")
        row["stage"] = PUBLISH
        # Рішення автора про приватну справу, дане на пакування, діє й на заливку.
        viddano = _zalyty(row["path"], row, bool(item.get("private_ok")),
                          str(item.get(REPLACE_WHY) or ""))
        row["warnings"] += [w.as_dict() for w in viddano.warnings]
        v = viddano.data or {}
        if not viddano.ok:
            row.update(error=viddano.error, status=v.get("status"), klas=v.get("klas"),
                       rate_limited=bool(v.get("rate_limited")))
            if v.get("retry_after") is not None:
                row["retry_after"] = v.get("retry_after")
                row["next_attempt_at"] = v.get("next_attempt_at")
            return row
        vyhid = str(v.get("outcome") or "")
        if vyhid == "segments":
            segs = [x for x in v.get("segments") or [] if isinstance(x, dict)]
            vyhody = {str(x.get("outcome") or "") for x in segs}
            # Справа віддана, коли кожен сегмент або ліг, або вже був у пулі.
            vyhid = (VZHE_Ye if segs and vyhody <= {VZHE_Ye} else
                     VIDDANO if segs and vyhody <= {VIDDANO, VZHE_Ye} else
                     next(iter(vyhody - {VIDDANO, VZHE_Ye}), ""))
            row["segments"] = len(segs)
        row.update(outcome=vyhid, contribution=v.get("contribution"),
                   geometry_attached=bool(v.get("geometry_attached")),
                   complete_sec=_etap(v.get("etapy"), "complete"))
        # 🔴 «Пул відповів» ≠ «справа в каталозі»: відхилений чи не прийнятий
        # дубль у каталозі не лежить, і рахувати його відданим не можна.
        row["ok"] = vyhid in (VIDDANO, VZHE_Ye)
        if not row["ok"]:
            row["error"] = OUTCOME_TEXT.get(vyhid, vyhid or "пул не назвав, що сталося")
        elif notes:
            row["notes"] = _notatnyk(row["case"], bool(item.get("private_ok")))
    except Exception as exc:  # одна справа не має валити воркер і решту пачки
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        row["sec"] = round(time.monotonic() - pochatok, 1)
    return row


def riadok(row: Row, n: int, total: int) -> str:
    """Рядок ходу пачки: людина бачить кожну справу, а не мовчання на годину."""
    from nyshporka.share.upload import VZHE_Ye

    name = row.get("shifra") or row.get("case") or "?"
    head = f"{n}/{total} {name}"
    if row.get("ok"):
        if row.get("geometry_attached"):
            tail = f"дозалито геометрію до внеску {row.get('contribution')}"
        elif row.get("outcome") == VZHE_Ye:
            tail = "уже в Супрязі"
        else:
            tail = f"внесок {row.get('contribution')}"
        # Час перевірки на сервері — видно посеред пачки, чи пул не захлинається.
        server = (f" (сервер {row['complete_sec']} с)"
                  if row.get("complete_sec") is not None else "")
        return f"✓ {head} · {tail} · {row.get('sec')} с{server}"
    krok = {PACK: "пакування", PUBLISH: "заливка"}.get(str(row.get("stage")), "воркер")
    first = str(row.get("error") or "").strip().splitlines()
    return f"✗ {head} · {krok}: {(first[0] if first else '?')[:200]}"


def viddaty(items: list[Item], *, jobs: int = JOBS, notes: bool = False,
            say: Callable[[str], None] | None = None,
            pool: Callable[[int], Executor] | None = None) -> dict[str, Any]:
    """Віддати пачку справ, `jobs` одночасно.

    `pool(n)` — фабрика виконавця; типово процеси (`_protsesy`), тести дають
    потоки. Порядок відповіді — порядок `items`, а не закінчення.

    🔴 Стеля пулу (429), що не минула за `CHEKATY`, зупиняє всю пачку: решта
    справ однаково отримала б ту саму відмову, і кожна — ще й пакування, яке
    нікуди не поїде. Справи, які вже йдуть, доходять до кінця; ще не початі
    лишаються в `not_started`.

    Поступ — `core.progress.report` після кожної справи (у консолі це смуга
    «справа i з n»; поза роботою в черзі — нічого). Прохання спинитись
    (`progress.stopped`, кнопка «Зупинити» консолі) зупиняє пачку так само, як
    стеля пулу: розпочаті справи доходять до кінця, решта — у `not_started`,
    і відповідь каже `stopped`.
    """
    from nyshporka.core import progress

    global _SLOTY
    jobs = jobs_in_range(jobs)
    total = len(items)
    pochatok = time.monotonic()
    rows: list[Row | None] = [None] * total
    stop: Row | None = None
    spyneno = False
    gotovo = 0

    def _pryiniaty(i: int, row: Row) -> None:
        nonlocal stop, gotovo, spyneno
        rows[i] = row
        gotovo += 1
        if say is not None:
            say(riadok(row, gotovo, total))
        progress.report(gotovo, total, str(row.get("case") or ""))
        if row.get("rate_limited") and stop is None:
            stop = row
        if progress.stopped():
            spyneno = True

    if jobs == 1 or total <= 1:
        for i, item in enumerate(items):
            if stop is not None or spyneno or progress.stopped():
                spyneno = spyneno or progress.stopped()
                break
            _pryiniaty(i, odna(item, notes))
    else:
        if pool is None:
            ex = _protsesy(min(jobs, total))
        else:
            import threading

            # Потоки цього процесу ділять один семафор так само, як процеси — свій.
            _SLOTY = threading.BoundedSemaphore(PUBLISH_SLOTS)
            ex = pool(min(jobs, total))
        futs: dict[Future[Row], int] = {}
        try:
            futs = {ex.submit(odna, item, notes): i for i, item in enumerate(items)}
            for f in as_completed(futs):
                if f.cancelled():
                    continue
                i = futs[f]
                try:
                    row = f.result()
                except Exception as exc:  # воркер упав (BrokenProcessPool, пам'ять)
                    row = {"case": str(items[i].get("case") or ""), "ok": False,
                           "stage": WORKER, "warnings": [],
                           "error": f"{type(exc).__name__}: {exc}"}
                _pryiniaty(i, row)
                if stop is not None or spyneno:
                    for g in futs:
                        g.cancel()
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
            if pool is not None:
                _SLOTY = None

    done = [r for r in rows if r is not None]
    not_started = [str(items[i].get("case") or "") for i, r in enumerate(rows) if r is None]
    sec = round(time.monotonic() - pochatok, 1)
    return {
        "rows": done,
        "total": total,
        "jobs": jobs,
        "summary": pidsumok(done),
        "failed": [r["case"] for r in done if not r.get("ok")],
        "not_started": not_started,
        "stopped": spyneno,
        "rate_limited": ({k: stop.get(k) for k in ("error", "retry_after", "next_attempt_at")}
                         if stop is not None else None),
        "sec": sec,
        "per_min": round(len(done) / sec * 60, 1) if sec > 0 else None,
        "complete_sec_median": _mediana([r.get("complete_sec") for r in done]),
    }


def viddaty_dochekuiuchys(items: list[Item], *, jobs: int = JOBS, notes: bool = False,
                          say: Callable[[str], None] | None = None,
                          pool: Callable[[int], Executor] | None = None,
                          sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    """`viddaty`, яка на стелі пулу (429) чекає, скільки просить пул, і йде далі.

    Для `share push --wait`: заливка сотень справ за ніч, коли нікому
    перезапускати пачку щоранку. Знову йдуть справа, що вперлась у стелю, і ще
    не початі; уже віддане не чіпається.

    🔴 Чекає лише на число пулу (`retry_after`). 429 без нього — відповідь
    старого сервера, і тут він зупиняє пачку так само, як `viddaty`: вгадувати
    паузу означало б або стукати марно, або простояти ніч.
    """
    from nyshporka.sources.http import RETRY_AFTER_PAD_S

    pochatok = time.monotonic()
    got = viddaty(items, jobs=jobs, notes=notes, say=say, pool=pool)
    po_spravi: dict[str, Row] = {r["case"]: r for r in got["rows"]}
    chekano = 0.0
    while True:
        if got.get("stopped"):
            break                       # людина спинила — не чекаємо стелі й не тягнемо далі
        stop = got.get("rate_limited") or {}
        prosyt = stop.get("retry_after")
        if not isinstance(prosyt, (int, float)) or prosyt > CHEKATY_NAIDOVSHE:
            break
        vpersheni = {r["case"] for r in got["rows"] if r.get("rate_limited")}
        znovu = set(got["not_started"]) | vpersheni
        cherha = [it for it in items if str(it.get("case") or "") in znovu]
        if not cherha:
            break
        if say is not None:
            koly = time.strftime("%H:%M", time.localtime(time.time() + prosyt))
            say(f"⏸ стеля пулу: чекаю до {koly} ({prosyt / 60:.0f} хв), "
                f"лишилось {len(cherha)} справ")
        pauza = float(prosyt) + RETRY_AFTER_PAD_S
        (sleep or time.sleep)(pauza)
        chekano += pauza
        got = viddaty(cherha, jobs=jobs, notes=notes, say=say, pool=pool)
        po_spravi.update({r["case"]: r for r in got["rows"]})

    rows = [po_spravi[c] for c in (str(it.get("case") or "") for it in items) if c in po_spravi]
    sec = round(time.monotonic() - pochatok, 1)
    pratsiuvalo = sec - chekano
    return {
        **got,
        "rows": rows,
        "total": len(items),
        "summary": pidsumok(rows),
        "failed": [r["case"] for r in rows if not r.get("ok")],
        "sec": sec,
        "waited_sec": round(chekano, 1),
        "per_min": round(len(rows) / pratsiuvalo * 60, 1) if pratsiuvalo > 0 else None,
        "complete_sec_median": _mediana([r.get("complete_sec") for r in rows]),
    }


def pidsumok(rows: list[Row]) -> dict[str, int]:
    """Скільки чого сталося — у словах пулу, а не «успіх/невдача»."""
    from nyshporka.share.upload import VIDDANO, VZHE_Ye

    ok = [r for r in rows if r.get("ok")]
    return {
        "viddano": sum(1 for r in ok if r.get("outcome") == VIDDANO),
        "geometry_attached": sum(1 for r in ok if r.get("geometry_attached")),
        "vzhe_ye": sum(1 for r in ok if r.get("outcome") == VZHE_Ye
                       and not r.get("geometry_attached")),
        "pack_failed": sum(1 for r in rows if not r.get("ok") and r.get("stage") == PACK),
        "publish_failed": sum(1 for r in rows if not r.get("ok") and r.get("stage") == PUBLISH),
        "worker_failed": sum(1 for r in rows if r.get("stage") == WORKER),
        "publish_retries": sum(int(r.get("retries") or 0) for r in rows),
        "notes_sent": sum(1 for r in rows if r.get("notes") == NOTES_OK),
        "notes_failed": sum(1 for r in rows
                            if r.get("notes") not in (None, NOTES_OK, NOTES_NONE)),
    }


def _mediana(values: list[Any]) -> float | None:
    xs = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not xs:
        return None
    mid = len(xs) // 2
    return round(xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2, 2)
