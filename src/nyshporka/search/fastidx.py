"""⚡ Швидкий передфільтр пошуку роду — індекс Tantivy поверх стору тексту.

Стор (`search.store`) шукає кандидатів FTS-триграмами блоками по 60 тис.
сторінок; на корпусі це хвилини на прізвище. Індекс тут знаходить РЯДКИ, де
може стояти прізвище, за секунди: нечіткий пошук по словнику кандидатів
(автомат Левенштейна над FST). Вердикт і далі виносить той самий
`store._match_unique` з тим самим порогом — індекс лише звужує, ЩО оцінювати.

🔴 Документ — рядок, і в нього три поля, бо прізвище в шумному декоді сидить у
слові по-різному (заміри 20.10.2026 на 10 тис. сторінок ф.224, еталон — повна
оцінка всіх різних слів вибірки):

* `c` — кандидати рядка (слова, пари, трійки, склейки переносу). Ловить
  прізвище НА ПОЧАТКУ слова; стем без 1–3 перших літер — коли рушій зіпсував
  сам початок.
* `x` — ті самі кандидати ЗАДОМ НАПЕРЕД. Ловить прізвище В КІНЦІ склейки
  (`grigoriimakiimelnikk`) і слово зі скаліченим початком (`blescinskii`), бо
  префіксний автомат бачить лише початок терма.
* `y` — хвости довгих сирих слів рядка: прізвище ПОСЕРЕДИНІ зліпленого слова
  (`inanasamelnikami`).

Документ-сторінка губив менше лише тому, що дооцінював усю сторінку — у 9–42
рази більше слів (на корпусі «Мельник» — 13 хв); документ-рядок без `x`/`y` губив
склейки й скалічені початки. Три поля разом: з балом ≥90 нуль утрат на трьох
прізвищах із чотирьох (на четвертому — склейки, чия згадка знайдена в сусідньому
рядку), у смузі 85–89 утрат утричі менше, ніж у сторінки.

🔴 Похідне від стору, не від прогонів: індекс доганяє стор за штампами
прогонів (`sync`), а прогін, якого в індексі ще немає чи який змінився, пошук
бере старим шляхом. Індекс можна видалити будь-коли.

⚠ Необов'язковий: без пакета `tantivy` (`nyshporka[fast]`) усе працює як
раніше, свіпом стору.
"""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import shutil
import sqlite3
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

#: Тека індексу поруч зі стором.
DIR = "fastidx"
#: Які прогони індекс уже несе і під яким штампом стору.
STATE = "runs.json"
#: Версія схеми індексу; інша — індекс збирається наново.
SCHEMA = 3
#: Токенайзер полів: слово ділиться ЛИШЕ пробілом (див. `_analyzer`).
TOKENIZER = "ws"
#: Терм довший за стільки байтів відкидається — як у `default` Tantivy.
TERM_MAX = 40
#: Хвости сирих слів від такої довжини — для прізвища посередині зліпленого слова.
SFX_MIN = 10
#: Хвіст коротший за стільки літер не індексується: він збігається з усім.
SFX_TAIL = 6
#: Від якої довжини стема запит бере ще й його початок (`SHORT_HEAD` літер, ±1):
#: для скорочених форм роду, до яких від повного стему понад дві правки.
SHORT_FROM = 9
SHORT_HEAD = 5
#: Пам'ять письменника індексу; Tantivy ділить її між потоками.
WRITER_HEAP = 400_000_000
#: Від скількох сторінок збірка рахує текст полів воркерами: старт процесу —
#: секунди, на справі він дорожчий за саму роботу.
PARALLEL_PAGES = 20_000
#: Скільки рядків між комітами під час збірки: обрив не губить зроблене.
COMMIT_EVERY = 2_000_000


def available() -> bool:
    try:
        import tantivy  # noqa: F401
    except ImportError:
        return False
    return True


def path() -> Path:
    from nyshporka.search import store as ST

    return ST.path().parent / DIR


def exists() -> bool:
    return available() and bool(state())


def _schema() -> Any:
    import tantivy

    sb = tantivy.SchemaBuilder()
    sb.add_integer_field("pid", stored=False, indexed=True, fast=True)
    sb.add_integer_field("ln", stored=False, indexed=False, fast=True)
    sb.add_integer_field("run", stored=False, indexed=True, fast=True)
    for field in ("c", "x", "y"):
        sb.add_text_field(field, stored=False, tokenizer_name=TOKENIZER, index_option="basic")
    return sb.build()


def _analyzer() -> Any:
    """Пробіл — єдиний роздільник: слово в індексі те саме, що оцінює свіп.

    🔴 `default` Tantivy ріже слово на кожному не-літерно-цифровому знаку, а
    кандидати стору (`htr_store._TOKEN_RE` + `_norm`) їх лишають: `=` Скриби
    на місці `z` (`Siemas=ko` = Siemaszko), `_ + * ~ ^`, титло й наголос
    (`dol҃inskii`). Розірване слово давало терми `siemas` і `ko`, і жоден не
    доходив до стему за дві правки — справжня згадка з балом 88 зникала з
    корпусного пошуку (відгук порталу №2, 24.10.2026). Цілим словом `siemas=ko`
    за одну заміну від `siemaszko`, тож автомат його бере.
    """
    import tantivy

    return (tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.whitespace())
            .filter(tantivy.Filter.remove_long(TERM_MAX))
            .filter(tantivy.Filter.lowercase())
            .build())


def _open(create: bool) -> Any:
    import tantivy

    d = path()
    if create:
        d.mkdir(parents=True, exist_ok=True)
    index = tantivy.Index(_schema(), path=str(d), reuse=True)
    # Токенайзер не зберігається в індексі: без реєстрації на КОЖНОМУ відкритті
    # письменник упаде на невідомому імені.
    index.register_tokenizer(TOKENIZER, _analyzer())
    return index


def _read_state() -> dict[str, Any]:
    try:
        raw = json.loads((path() / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def state() -> dict[int, str]:
    """run_id → позначка тексту стору, з якою прогін лежить в індексі. Інша схема — порожньо."""
    raw = _read_state()
    if raw.get("schema") != SCHEMA:
        return {}
    runs = raw.get("runs") or {}
    return {int(k): str(v) for k, v in runs.items()}


def _save_state(st: dict[int, str]) -> None:
    from nyshporka.utils.atomic import write_json

    write_json(path() / STATE, {"schema": SCHEMA,
                                "runs": {str(k): v for k, v in sorted(st.items())}}, indent=0)


#: Знак, що не є літерою чи цифрою, — там, де `default` Tantivy різав слово.
_NON_ALNUM = re.compile(r"(?:[^\w]|_)+")
#: Те саме, але пробіл не рахується: один пошук на весь рядок замість слова.
_ODD = re.compile(r"[^\w ]|_")


def _with_parts(text: str) -> str:
    """Слова цілими і, якщо в слові є не-літерний знак, ще й його частини.

    🔴 Ціле слово ловить згадку зі знаком усередині (`siemas=ko`), частини —
    прізвище ПІСЛЯ знака (`x=kowalski`) і шматки задовгої склейки, яку
    `TERM_MAX` відкидає цілою. Лише разом вони не губять нічого з того, що
    бачив `default` (замір 24.10.2026 на 120 тис. сторінок: без частин — мінус
    643 хіти «Коваля» з тих, що бачив старий індекс).
    """
    if not _ODD.search(text):        # звичайний рядок: частин немає
        return text
    out = text.split(" ")
    for t in text.split(" "):
        if _NON_ALNUM.search(t):
            out.extend(p for p in _NON_ALNUM.split(t) if p)
    return " ".join(out)


def _suffixes(raw: str) -> str:
    from nyshporka import htr_store as S

    out: list[str] = []
    for tok in S._TOKEN_RE.findall(raw):
        n = S._norm(tok)
        if len(n) >= SFX_MIN:
            out.extend(n[k:] for k in range(2, len(n) - SFX_TAIL + 1))
    return _with_parts(" ".join(out))


#: Рядок індексу до `Document`: (pid, рядок, c, x, y) — те, що вміє передати воркер.
Fields = tuple[int, int, str, str, str]


def _fields(pid: int, cands: bytes, raw: bytes | None) -> Iterator[Fields]:
    """Поля рядків сторінки: кандидати, вони ж задом наперед, хвости сирих слів."""
    raws = zlib.decompress(raw).decode("utf-8").split("\n") if raw is not None else []
    for line in zlib.decompress(cands).decode("utf-8").split("\n"):
        no_s, _sep, rest = line.partition("\t")
        if not rest:
            continue
        no = int(no_s)
        c = _with_parts(rest)
        src = raws[no - 1] if 0 < no <= len(raws) else ""
        yield int(pid), no, c, " ".join(t[::-1] for t in c.split(" ")), _suffixes(src)


def _docs(pid: int, run_id: int, cands: bytes, raw: bytes | None) -> Iterator[Any]:
    """Документи рядків сторінки."""
    import tantivy

    for p, no, c, x, y in _fields(pid, cands, raw):
        yield tantivy.Document(pid=p, ln=no, run=int(run_id), c=c, x=x, y=y)


_PAGES_SQL = "select id, cands, raw from pages where run_id=? and cands is not null"


def _run_fields(rid: int) -> tuple[int, list[Fields]]:
    """Воркер: поля всіх рядків одного прогону (стор — лише читання)."""
    from nyshporka.search import store as ST

    conn = ST.connect(readonly=True)
    try:
        return rid, [f for pid, cands, raw in conn.execute(_PAGES_SQL, (rid,))
                     for f in _fields(pid, cands, raw)]
    finally:
        conn.close()


def _writer_threads() -> int:
    """Потоки письменника від ядер: з двома `add_document` чекав на індексацію
    (замір 24.10.2026, 1,5 млн рядків: 2 потоки — 17,7 с, 8 — 12,8 с)."""
    from nyshporka.core.cpu import usable_cores

    return min(8, max(2, usable_cores() // 3))


def _by_run(conn: sqlite3.Connection, todo: list[int], threads: int
            ) -> Iterator[tuple[int, list[Fields]]]:
    """(прогін, його поля): воркерами, коли збірка велика, інакше в цьому процесі.

    🔴 Текст полів — чистий Python і майже половина часу збірки (той самий замір:
    21,7 с із 48), тож без процесів він сидів на одному ядрі. Документи й запис
    лишаються тут, бо письменник у Tantivy один. У польоті не більше двох прогонів
    на воркер: відповіді, яких головний ще не записав, не накопичуються в пам'яті.
    """
    from nyshporka.core.cpu import usable_cores
    from nyshporka.search import store as ST

    marks = ",".join("?" * len(todo))
    pages = conn.execute(f"select coalesce(sum(pages), 0) from runs where id in ({marks})",
                         todo).fetchone()[0] if todo else 0
    workers = min(ST.sweep_workers(len(todo), worker_gb=ST.FAST_WORKER_GB),
                  max(1, usable_cores() - threads - 1))
    if pages < PARALLEL_PAGES or workers < 2:
        for rid in todo:
            yield rid, [f for pid, cands, raw in conn.execute(_PAGES_SQL, (rid,))
                        for f in _fields(pid, cands, raw)]
        return
    import multiprocessing as mp
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    from nyshporka.core.workspace import workspace

    ex = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                             initializer=ST._block_init, initargs=(workspace(),))
    try:
        queue = iter(todo)
        pending = {ex.submit(_run_fields, rid) for rid in itertools.islice(queue, 2 * workers)}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                nxt = next(queue, None)
                if nxt is not None:
                    pending.add(ex.submit(_run_fields, nxt))
                yield fut.result()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)


def _store_marks(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """run_id → (позначка тексту, давня позначка штампом).

    Позначка тексту — коли стор зібрав прогін і яким правилом склейки
    (`at:<indexed_at>|<rules>`). 🔴 Не штамп мети: штамп стор оновлює й тоді, коли
    змінилась лише мета (позначка проєкту, тека справи), а текст той самий. Доти
    така правка 9 361 прогону змушувала індекс перебудовувати їх усі — години й
    гігабайти пам'яті (23.10.2026).

    Давня позначка (`<штамп>|<правила>`) — те, що індекс писав до цього: запис,
    що з нею збігається, той самий текст, і переводиться без перебудови.
    """
    return {int(r[0]): (f"at:{r[3] or ''}|{r[2] or ''}", f"{r[1]}|{r[2] or ''}")
            for r in conn.execute("select id, stamp, rules, indexed_at from runs")}


def covered(conn: sqlite3.Connection, run_ids: list[int]) -> list[int]:
    """Прогони, які індекс несе з тим самим текстом, що й стор."""
    if not available():
        return []
    st = state()
    if not st:
        return []
    now = _store_marks(conn)
    return [rid for rid in run_ids if rid in st and st[rid] in now.get(rid, ())]


def sync(conn: sqlite3.Connection, *,
         progress: Callable[[int, int, str], None] | None = None,
         only: set[int] | None = None) -> dict[str, Any]:
    """Догнати індекс до стору: нові й змінені прогони — заново, зниклі — геть.

    Письменник у Tantivy один на індекс; якщо його тримає інший процес, догін
    пропускається (`busy`) — пошук тоді бере неохоплені прогони старим шляхом.
    Індекс іншої схеми стирається й збирається з нуля.

    `only` — точковий догін: лише ці прогони, і БЕЗ чекання на злиття сегментів.
    🔴 Доти `text index --case <справа>` доганяв увесь корпус і чекав, поки
    Tantivy зіллє багатогігабайтні сегменти (33 ГБ, 54 сегменти): 2 хв 54 с на
    справу, що вже була в сторі, а п'ять таких викликів наглядачів разом — години
    й переповнений диск (25.10.2026). Злиття — лише оптимізація пошуку; закомічені
    сегменти цілі й без нього, а зливає їх повний догін (`text index` без справи,
    `--fast`).
    """
    # Стирається лише індекс, який СКАЗАВ, що він іншої схеми (є `runs.json`).
    # Тека без стану — це, найпевніше, перша збірка в іншому процесі, яка ще не
    # дійшла до коміту: стерти її означало б вирвати теку з-під живого
    # письменника (рецензія 20.10.2026). Тут вирішує замок письменника нижче.
    if (path() / STATE).is_file() and _read_state().get("schema") != SCHEMA:
        shutil.rmtree(path())
    index = _open(create=True)
    st = state()
    now = _store_marks(conn)
    gone = [rid for rid in st if rid not in now and (only is None or rid in only)]
    todo: list[int] = []
    moved = False
    for rid, (mark, legacy) in now.items():
        if only is not None and rid not in only:
            continue
        have = st.get(rid)
        if have == mark:
            continue
        if have == legacy:             # давній запис, текст той самий — лише нова позначка
            st[rid] = mark
            moved = True
            continue
        todo.append(rid)
    if not gone and not todo:
        if moved:
            _save_state(st)
        return {"added": 0, "removed": 0, "lines": 0, "busy": False}
    threads = _writer_threads()
    try:
        w = index.writer(WRITER_HEAP, threads)
    except ValueError:
        return {"added": 0, "removed": 0, "lines": 0, "busy": True}
    lines = since = 0
    try:
        for rid in [*gone, *todo]:
            w.delete_documents_by_term("run", rid)
        import tantivy

        for i, (rid, fields) in enumerate(_by_run(conn, todo, threads), 1):
            if progress:
                progress(i, len(todo), "індекс Tantivy")
            for p, no, c, x, y in fields:
                w.add_document(tantivy.Document(pid=p, ln=no, run=rid, c=c, x=x, y=y))
            lines += len(fields)
            since += len(fields)
            st[rid] = now[rid][0]
            if since >= COMMIT_EVERY:
                w.commit()
                _save_state(st)
                since = 0
        for rid in gone:
            st.pop(rid, None)
        w.commit()
        if only is None:
            w.wait_merging_threads()
        else:
            del w               # відпустити замок письменника одразу, злиття не чекаючи
    except BaseException:
        with contextlib.suppress(Exception):
            w.rollback()
        raise
    _save_state(st)
    return {"added": len(todo), "removed": len(gone), "lines": lines, "busy": False}


def query_terms(stems: list[str]) -> list[tuple[str, str, int]]:
    """(поле, терм, правок) по трьох полях; повтори прибрано, і більш нічого.

    🔴 Терми НЕ згортаються за префіксом. Здавалося б, коли стем A — початок
    стему B, префіксний автомат A покриває все, що B; на моделі «якийсь початок
    слова в межах d» це доводилось, але префіксний режим Tantivy вужчий за
    модель: рецензія 20.10.2026 знайшла на живому індексі слова, які B бере,
    а A — ні (тест `test_the_prefix_mode_of_tantivy_is_narrower_than_the_model`). Згортання
    скорочувало запит роду вдвічі ціною тихих утрат, тож його прибрано.
    """
    raw: list[tuple[str, str, int]] = []
    for s in stems:
        far = 2 if len(s) >= 8 else 1
        raw.append(("c", s, 2))
        raw.append(("x", s[::-1], far))
        raw.append(("y", s, far))
        for k in (1, 2, 3):
            if len(s) - k >= 6:
                # Скалічений початок: у `c` — стем без перших літер, у `x` той
                # самий стем задом наперед (хвіст терма обрізано, і префіксний
                # збіг не вимагає зіпсованих літер).
                raw.append(("c", s[k:], 1))
                raw.append(("x", s[k:][::-1], 1))
        if len(s) >= SHORT_FROM:
            # 🔴 Скорочена й скалічена форма прізвища — справжні згадки роду з
            # голдсету дослідника (бал 80), коротші за стем на 4–5 літер, тож
            # двох правок до повного стему не вистачає. Спільний у них лише
            # початок; бал і далі виносить `_match_unique`, тож зайві кандидати
            # у видачу не йдуть.
            raw.append(("c", s[:SHORT_HEAD], 1))
    return list(dict.fromkeys(raw))


#: Скільки потоків ділять терми запиту (див. `by_run`).
QUERY_THREADS = min(8, os.cpu_count() or 1)
#: Скільки рядків індексу запит може зібрати; ширший іде свіпом (див. `by_run`).
#: Межа — сума по частинах (рядок, що збігся термами двох частин, рахується двічі).
#: Замір 20.10.2026 (сума по частинах запиту, корпус 227 млн рядків): Шевченко 1,1 млн,
#: Мельник 2,8, Коваль 13,1; Іосиф із гніздом (там «Осип») — понад 50, Іван — 279.
#: Це СТЕЛЯ: на слабшій машині межу знижує вільна пам'ять (`max_hits`).
MAX_HITS = 16_000_000
#: Пам'ять на один збіг під час збору, байти: ~230 тимчасово в Tantivy і ~300 у
#: готовій відповіді (пари за прогонами); пік на 3,9 млн збігів — 0,9 ГБ
#: (замір 22.10.2026), тут із запасом.
HIT_BYTES = 400
#: Яку частку вільної пам'яті можна віддати під збір.
HIT_MEM_SHARE = 0.5


def max_hits() -> int:
    """Скільки збігів цей процес може зібрати, не ризикуючи пам'яттю машини.

    🔴 Нишпорка йде на різне залізо: 16 млн збігів — це ~6 ГБ, і на ноутбуці з
    8 ГБ процес упав би без виводу (відмова пам'яті в Rust не ловиться). Ширший
    за межу запит іде свіпом — повільніше, але без падіння.
    """
    try:
        import psutil

        free = psutil.virtual_memory().available
    except Exception:
        return MAX_HITS
    return min(MAX_HITS, int(free * HIT_MEM_SHARE / HIT_BYTES))


def _query_threads() -> int:
    """Потоки на частини термів: доступні ядра (з квотою контейнера), до 8."""
    try:
        from nyshporka.core.cpu import usable_cores

        return max(1, min(QUERY_THREADS, usable_cores()))
    except Exception:
        return QUERY_THREADS


class TooBroad(RuntimeError):
    """Запит бере забагато рядків індексу — передфільтр тут не звужує."""


#: Скільки відповідей індексу тримати в пам'яті процесу.
ANSWERS_KEEP = 3
#: Версія запиту (`query_terms`): входить у ключ кешу відповідей швидкого каналу в
#: сторі, тож зміна схеми запиту не лишає старих відповідей.
QUERY_VERSION = 2

#: Відповіді індексу на процес: (стеми, штамп стану) → прогін → [(pid, рядок)].
_ANSWERS: dict[tuple[str, tuple[str, ...], int], dict[int, list[tuple[int, int]]]] = {}
#: Запити, заширокі для індексу (той самий ключ) → чому.
_BROAD: dict[tuple[str, tuple[str, ...], int], str] = {}


def by_run(stems: list[str]) -> dict[int, list[tuple[int, int]]]:
    """Рядки-кандидати всього корпусу, розкладені за прогонами. Один запит на процес.

    🔴 Запит до індексу коштує однаково — що на справу, що на корпус: автомат
    іде по ВСЬОМУ словнику, а фільтр за прогоном накладається після (заміри
    20.10.2026: 12–50 с на прізвище). Пошук по серії кличе свіп на кожну справу,
    і 150 справ серії означали 150 повних проходів — пів години на те, що свіп
    робить за три хвилини. Тому відповідь рахується раз на прізвище й кешується
    до наступної зміни індексу, а справа бере з неї свої рядки.
    """

    # Без стану відповіді немає — і це помилка, а не порожня відповідь: тихі нулі
    # лягли б у кеш швидкого каналу як «тут нічого» (рецензія 20.10.2026).
    stamp = (path() / STATE).stat().st_mtime_ns
    key = (str(path()), tuple(stems), stamp)
    got = _ANSWERS.get(key)
    if got is not None:
        return got
    if key in _BROAD:
        # Пошук по серії кличе індекс на кожну справу — не перераховувати.
        raise TooBroad(_BROAD[key])
    index = _open(create=False)
    index.reload()
    terms = query_terms(stems)
    # 🔴 Частинами в потоках: запит до індексу однопотоковий, а терми
    # незалежні. Рід із двома сотнями термів — 186 с одним запитом і 18 с вісьмома
    # потоками, та сама множина рядків (замір 20.10.2026).
    k = max(1, min(_query_threads(), len(terms)))
    parts = [terms[i::k] for i in range(k)] if terms else []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=k) as ex:
        counted = list(ex.map(lambda part: _count_part(index, part), parts))
        total = sum(n for _s, _q, n in counted)
        # 🔴 Спершу рахунок, потім збір. Короткий стем («Осип» у гнізді «Іосифа»)
        # бере п'яту частину корпусу — 50 млн рядків (з гніздом «Іосифа» сума частин
        # 78 млн із 227), і Tantivy, збираючи їх,
        # просив 2,3 ГБ одним шматком: відмова пам'яті в Rust не ловиться, процес
        # падав без відповіді (20.10.2026). Такому запиту передфільтр однаково не
        # допомагає, тож він іде свіпом триграмами (`store.sweep` ловить помилку).
        limit = max_hits()
        if total > limit:
            why = f"запит бере {total:_} рядків індексу, межа {limit:_}".replace("_", " ")
            # Кешується лише відмова за стелею: межу нижче стелі дала вільна
            # пам'ять ЦЬОГО моменту, і за хвилину той самий запит уже пройде
            # (рецензія 22.10.2026).
            if total > MAX_HITS:
                _BROAD[key] = why
            raise TooBroad(why)
        found = list(ex.map(lambda c: _collect_part(*c), counted))
    seen: set[tuple[int, int]] = set()
    out: dict[int, list[tuple[int, int]]] = {}
    for part in found:
        for p, ln, rid in part:
            if (p, ln) not in seen:
                seen.add((p, ln))
                out.setdefault(rid, []).append((p, ln))
    for pairs in out.values():
        pairs.sort()
    # Відповідь поширеного прізвища — мільйони пар; тримаємо лише останні кілька.
    while len(_ANSWERS) >= ANSWERS_KEEP:
        _ANSWERS.pop(next(iter(_ANSWERS)))
    _ANSWERS[key] = out
    return out


def _count_part(index: Any, terms: list[tuple[str, str, int]]) -> tuple[Any, Any, int]:
    """(searcher, запит, скільки документів він бере) для частини термів."""
    import tantivy

    schema = index.schema
    q = tantivy.Query.boolean_query([(tantivy.Occur.Should, tantivy.Query.fuzzy_term_query(
        schema, field, term, distance=d, transposition_cost_one=True, prefix=True))
        for field, term, d in terms])
    searcher = index.searcher()
    return searcher, q, searcher.search(q, limit=1, count=True).count or 0


def _collect_part(searcher: Any, q: Any, n: int) -> list[tuple[int, int, int]]:
    """(pid, рядок, прогін) документів, де збігся хоч один із термів."""
    if not n:
        return []
    # 🔴 Без `order_by_field`: збір у порядку поля бере в Tantivy ~2,5 КБ
    # тимчасової пам'яті на збіг, без нього — ~0,23 КБ (замір 22.10.2026). Рід
    # із профілем — 3,9 млн збігів, і вісім частин разом давали пік 4,9 ГБ у
    # головному процесі. Порядок наводить `by_run` уже на готових парах.
    hits = [addr for _k, addr in searcher.search(q, limit=n).hits]
    return [(int(p), int(ln), int(rid)) for p, ln, rid in zip(
        searcher.fast_field_values("pid", hits), searcher.fast_field_values("ln", hits),
        searcher.fast_field_values("run", hits), strict=True)
        if p is not None and ln is not None and rid is not None]


def known(stems: list[str]) -> bool:
    """Чи відповідь на ці стеми вже порахована в цьому процесі."""
    try:
        stamp = (path() / STATE).stat().st_mtime_ns
    except OSError:
        return False
    return (str(path()), tuple(stems), stamp) in _ANSWERS


def candidates(stems: list[str], run_ids: list[int] | None = None
               ) -> list[tuple[int, int]]:
    """(pid стору, номер рядка) рядків, де може стояти прізвище. `run_ids` — лише в цих прогонах."""
    got = by_run(stems)
    want = got.keys() if run_ids is None else run_ids
    return sorted({x for rid in want for x in got.get(rid, ())})


__all__ = ["SCHEMA", "TooBroad", "available", "by_run", "candidates", "covered", "exists", "known",
           "path", "query_terms", "state", "sync"]
