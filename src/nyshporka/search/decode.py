"""🗂 Індекс декоду: пласкі кандидати на диску замість перебудови щоразу.

## Навіщо

Пошук прізвища по всьому прочитаному будував індекс наново при кожному запиті:
читав 919 МБ тексту, різав на токени, склеював переноси й пари, нормалізував
кожного кандидата. Заміряно на корпусі з 1142 прогонів (429 888 файлів):
**побудова 13 хв, зіставлення 3 хв, 22 ГБ памʼяті**, якби індекс лишався
цілим. Браузер на цей час переставав відповідати, а другий такий самий запит
коштував рівно стільки ж.

При цьому сам матчер дешевий: він порівнює короткі рядки, і rapidfuzz робить це
на C. Дорогою була саме ПІДГОТОВКА — і вона повторювана: доки прогін не
перечитали, його кандидати ті самі.

## Що тут лежить

Один файл на прогін, `data/derived/decode_index/<прогін>.idx.gz`, рядками:

    <сторінка>\\t<номер рядка>\\t<норм1> <норм2> …

🔴 У файлі лише НОРМАЛІЗОВАНІ форми — те єдине, з чим працює зіставлення.
Показане слово (`matched`) і сам рядок відновлюються з `.txt` уже ПІСЛЯ того, як
хіт знайдено: таких рядків одиниці, а зберігати їх для всіх означало б утричі
роздути індекс заради даних, що майже ніколи не читаються.

🔴 Свіжість — ШТАМПОМ прогону, а не часом життя. Штамп той самий, що в кеші
сховища: `mtime` мети плюс кількість текстів. Прогін дочитали — індекс цієї
справи перебудується, решта лишиться. Кеш «на N хвилин» показував би щойно
прочитану сторінку як неіснуючу.

⚠ Індекс — ПОХІДНЕ. Його можна видалити будь-коли: наступний пошук збере його
наново. Тому він і живе в `data/derived`, а не поруч із прогонами.
"""
from __future__ import annotations

import gzip
import hashlib
import os
from bisect import bisect_right
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

#: Версія формату. Змінилась розкладка кандидатів — старі файли треба
#: перебудувати, і найдешевший спосіб це зробити — не читати їх узагалі.
VERSION = 1

#: Роздільник кандидатів усередині рядка. Пробіл законний, бо нормалізована
#: форма пробілів не містить: `_squash` лишає їх лише в цілих реченнях, а сюди
#: приходять слова й склейки слів.
SEP = " "


def index_dir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().root / "data" / "derived" / "decode_index"


def stamp_of(run: str) -> str:
    """Штамп свіжості прогону — два `stat`, без жодного обходу теки.

    🔴 Мета плюс сама тека. Раннер оновлює `_htr_meta.json` після кожної
    сторінки, а поява чи зникнення файлу міняє час теки — разом цього досить,
    щоб дочитаний прогін перебудував свій індекс.

    ⚠ Саме `stat`, а не перелік `*.txt`: перелік означав би обхід теки на
    КОЖЕН прогін, тобто тисячу обходів на одне питання «чи зібрано індекс», —
    і питати про стан індексу стало б дорожче, ніж шукати.
    """
    d = _run_dir(run)
    if d is None:
        return ""
    meta = d / "_htr_meta.json"
    try:
        return f"{meta.stat().st_mtime_ns:x}-{d.stat().st_mtime_ns:x}"
    except OSError:
        return ""


def _run_dir(run: str) -> Path | None:
    from nyshporka import htr_store as S

    d = S._case_dir(run)
    if d is None or not (d / "_htr_meta.json").is_file():
        return None
    return d


def _digest(stamp: str) -> str:
    """Коротке ім'я штампа для імені файлу."""
    return hashlib.blake2b(stamp.encode("utf-8"), digest_size=6).hexdigest()


def index_path(run: str, stamp: str = "") -> Path:
    """Шлях індексу. ШТАМП У ІМЕНІ, і це не косметика.

    🔴 Свіжість перевіряється існуванням файлу — тобто одним `stat`, — а не
    відкриттям архіву заради першого рядка. На корпусі це різниця між «стан
    індексу видно одразу» і «питання про стан коштує секунди».

    ⚠ Ім'я прогону — вже безпечне ім'я теки (`reports/htr/<run>`), тож окремої
    санітизації не треба: якби воно було небезпечним, теки прогону не існувало б.
    """
    st = stamp or stamp_of(run)
    return index_dir() / f"{run}.{_digest(st)}.v{VERSION}.idx.gz"


def is_fresh(run: str) -> bool:
    """Чи індекс цього прогону відповідає тому, що на диску."""
    st = stamp_of(run)
    return bool(st) and index_path(run, st).is_file()


def build(run: str) -> int:
    """Зібрати індекс одного прогону. Повертає, скільки рядків у ньому.

    🔴 Кандидати беруться з `htr_store._case_index`, а не рахуються тут наново.
    Правила склейки (перенос через рядок, пара, трійка) вистраждані замірами й
    задокументовані там; друга їх копія розійшлася б із першою тихо, і пошук
    почав би знаходити не те, що вміє знаходити гортач.
    """
    from nyshporka import htr_store as S

    stamp = stamp_of(run)
    if not stamp:
        return 0
    index = S._case_index(run)
    path = index_path(run, stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        fh.write(stamp + "\n")
        for page, ln_no, _raw, cands in index:
            norms = SEP.join(n for _w, n in cands if n)
            if not norms:
                continue
            fh.write(f"{page}\t{ln_no}\t{norms}\n")
    # 🔴 Атомарна підміна. Обірваний запис (місце на диску, Ctrl+C) інакше
    # лишив би файл, чий штамп збігається, а вміст обрізаний, — і пошук мовчки
    # перестав би бачити хвіст справи.
    os.replace(tmp, path)
    # Індекси попередніх станів цього прогону більше ніколи не знадобляться:
    # штамп у їхньому імені вже не збігається ні з чим. Лишити їх означало б
    # тримати на диску стільки копій, скільки разів справу дочитували.
    for old in index_dir().glob(f"{run}.*.v{VERSION}.idx.gz"):
        if old != path:
            try:
                old.unlink()
            except OSError:
                continue
    # Кеш сховища тримає щойно побудований індекс цілком; на корпусі це
    # десятки гігабайтів, тож віддаємо памʼять одразу після запису.
    S._CACHE.pop(run, None)
    return len(index)


def ensure(run: str) -> bool:
    """Індекс прогону на місці й свіжий. `False` — зібрати не було з чого."""
    if is_fresh(run):
        return True
    return build(run) > 0 or index_path(run).is_file()


def read(run: str) -> tuple[list[str], list[int], list[tuple[str, int]]] | None:
    """Пласкі кандидати прогону + МЕЖІ рядків.

    Повертає `(norms, starts, lines)`: `norms` — усі кандидати підряд,
    `lines[i]` — сторінка й номер i-го рядка, `starts[i]` — з якого місця в
    `norms` починаються його кандидати.

    🔴 Межі, а не власник на КОЖНОГО кандидата. Власників було б стільки ж,
    скільки кандидатів (мільйони на корпус), і будувались би вони в Python —
    тобто розбір індексу коштував би дорожче за саме зіставлення. Хіти ж
    поодинокі, і для них рядок знаходиться двійковим пошуком.

    ⚠ Пласко навмисно: саме в такому вигляді rapidfuzz порівнює гуртом; список
    списків довелось би розплющувати, а це знову Python на мільйонах.
    """
    path = index_path(run)
    if not path.is_file():
        return None
    norms: list[str] = []
    starts: list[int] = []
    lines: list[tuple[str, int]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            fh.readline()                      # штамп
            for row in fh:
                parts = row.rstrip("\n").split("\t", 2)
                if len(parts) < 3 or not parts[2]:
                    continue
                try:
                    ln = int(parts[1])
                except ValueError:
                    continue
                starts.append(len(norms))
                lines.append((parts[0], ln))
                norms += parts[2].split(SEP)
    except (OSError, EOFError):
        return None
    return norms, starts, lines


def stats() -> dict[str, Any]:
    """Скільки прогонів зібрано й скільки лишилось — знаменник для екрана.

    🔴 «Зібрано 40 із 1142» і «зібрано все» — різні відповіді на питання «чому
    пошук такий довгий», і без першої людина чекає, не знаючи чого.
    """
    from nyshporka import htr_store as S

    try:
        runs = [c["name"] for c in S.list_cases()]
    except Exception:
        runs = []
    d = index_dir()
    fresh = sum(1 for r in runs if is_fresh(r))
    size = 0
    if d.is_dir():
        size = sum(x.stat().st_size for x in d.glob(f"*.v{VERSION}.idx.gz"))
    return {"runs": len(runs), "indexed": fresh, "stale": len(runs) - fresh,
            "bytes": size, "dir": str(d)}


def ensure_all(runs: list[str], *,
               progress: Callable[[int, int, str], None] | None = None,
               ) -> Iterator[str]:
    """Догнати індекс по переліку прогонів, звітуючи про кожен.

    ⚠ Генератор навмисно: збирання корпусу триває хвилини, і той, хто його
    запустив, мусить бачити, де воно зараз, — інакше довга робота нічим не
    відрізняється від зависання.
    """
    total = len(runs)
    for i, run in enumerate(runs, 1):
        if progress:
            progress(i, total, run)
        if ensure(run):
            yield run


def _matches(norms: list[str], stems: list[str], thresh: int
             ) -> dict[int, tuple[float, int]]:
    """Кандидати понад поріг: індекс → (бал, індекс кандидата).

    🔴 Правило зіставлення ТЕ САМЕ, що було в поцикловому пошуку, і це не збіг:
    воно вистраждане замірами. Закороткий кандидат не порівнюється зовсім
    (чотирилітерні уламки шумлять на 86 балів), а `partial_ratio` додається
    лише там, де кандидат не коротший за стем — саме він пропускає відмінкові
    хвости («-iego», «-ого»).

    🔴 `extract` замість власного циклу, і НЕ заради краси: він відсіює нижче
    порога всередині C, не створюючи в Python ні числа, ні кортежа на кожен із
    мільйонів кандидатів. Гуртовий `cdist` дав би те саме, але потребує numpy —
    а той у пакеті лише для розробки, і тягнути його в базові залежності
    заради одного виклику немає підстав.

    ⚠ Довжинні умови накладаються ПІСЛЯ, на кількох знайдених, а не до, на
    мільйонах: вони лише ВИКИДАЮТЬ кандидатів, тож порядок не міняє відповіді,
    зате міняє ціну.
    """
    from rapidfuzz import fuzz, process

    best: dict[int, tuple[float, int]] = {}

    def take(items: list[Any], need: int, floor: int) -> None:
        for _choice, score, j in items:
            n = len(norms[j])
            if n < need or n < floor:
                continue
            cur = best.get(j)
            if cur is None or score > cur[0]:
                best[j] = (float(score), j)

    for stem in stems:
        need = max(4, int(len(stem) * 0.6))
        take(process.extract(stem, norms, scorer=fuzz.ratio,
                             score_cutoff=thresh, limit=None), need, 0)
        take(process.extract(stem, norms, scorer=fuzz.partial_ratio,
                             score_cutoff=thresh, limit=None), need, len(stem))
    return best


#: Скільки НЕЗІБРАНИХ прогонів пошук згоден зібрати сам, усередині запиту.
#:
#: 🔴 Число, а не «так/ні». Обидві крайності хибні: збирати завжди означає
#: чверть години мовчазного очікування на корпусі, не збирати ніколи — що
#: щойно дочитана справа не шукається, доки людина окремо не попросить індекс.
#: Кілька прогонів коштують секунди, і саме стільки їх з'являється після
#: звичайного читання.
INLINE_BUILD = 24


def sweep(stems: list[str], runs: list[str], *, thresh: int = 78,
          build_budget: int = 0,
          progress: Callable[[int, int, str], None] | None = None,
          cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Прочесати прогони за індексом. Повертає хіти без контексту й слова.

    🔴 Один прогін за раз, і його кандидати гинуть одразу після зіставлення.
    Доти індекс накопичувався цілком: на цьому корпусі це 22 ГБ, тобто пошук
    не «повільний», а неможливий — процес помирав або ставив машину на коліна.

    🔴 `build_budget` — головне рішення модуля. Зібрати індекс усього корпусу
    коштує чверть години; зробити це «дорогою», усередині запиту з браузера,
    означає повісити застосунок і не сказати, на чому. Але й ніколи не збирати
    не можна: тоді щойно дочитана справа мовчки не шукається. Тому бюджет —
    ЧИСЛО прогонів: скільки їх бракує, стільки й коштує, і рішення приймається
    ДО роботи, а не посеред неї.

    ⚠ Або всі, або жоден: якщо незібраних більше за бюджет, не збирається
    жодного. Зібрати «скільки встигнеться» означало б віддати відповідь, чий
    знаменник залежить від того, в якому порядку лежать теки.

    ⚠ `scanned` рахує прогони, які СПРАВДІ прочесані, а не ті, що просились:
    без індексу (порожня тека, збій читання) прогін у знаменник не йде, інакше
    нуль виглядав би повнішим, ніж він є.
    """
    stale = [r for r in runs if not is_fresh(r)]
    build_missing = 0 < len(stale) <= max(0, build_budget)
    hits: list[dict[str, Any]] = []
    scanned = 0
    missing = 0
    total = len(runs)
    for i, run in enumerate(runs, 1):
        if cancel and cancel():
            break
        if progress:
            progress(i, total, run)
        ready = ensure(run) if build_missing else is_fresh(run)
        if not ready:
            missing += 1
            continue
        got = read(run)
        if not got:
            continue
        norms, starts, lines = got
        if not norms:
            continue
        scanned += 1
        # Найкращий кандидат КОЖНОГО рядка — а не кожен кандидат понад поріг:
        # рядок у видачі один, і показувати його стільки разів, скільки в ньому
        # схожих слів, означало б роздути число знахідок.
        by_line: dict[tuple[str, int], tuple[float, int]] = {}
        for j, (sc, _) in _matches(norms, stems, thresh).items():
            key = lines[bisect_right(starts, j) - 1]
            cur = by_line.get(key)
            if cur is None or sc > cur[0]:
                by_line[key] = (sc, j)
        for (page, ln), (sc, j) in by_line.items():
            hits.append({"name": run, "page": page, "line_no": ln,
                         "line_index": ln - 1, "norm": norms[j],
                         "score": round(sc)})
    return {"hits": hits, "scanned": scanned, "runs": total,
            "unindexed": missing}
