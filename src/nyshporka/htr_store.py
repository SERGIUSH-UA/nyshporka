"""🖋 Read-сторона HTR-прогонів — тексти справ, розпізнані Kraken'ом.

Пише їх раннер (`nyshporka.htr.runner`, окремий інтерпретатор рушіїв; запуск —
`nysh read`) у `reports/htr/<name>/`: `<stem>.txt` посторінково +
`_htr_meta.json` (модель, per-page орієнтація/conf).
Цей модуль лише читає — консоль (роутер htr) віддає тексти, картинки і fuzzy-пошук.

CER Kraken на скорописі XVIII-XIX ст. ~25-35%: «Franciszka Lubkowskiego» →
«Francisrha Lubhoustrio90». Тому пошук — не точний grep, а fuzzy по нормалізованих
токенах (нормалізація обох сторін: `translit.normalize_for_matching` + фолд
історичних літер і типових конфузій самого HTR). Точний патерн «genealog» реальну
«Gencaloqui» не ловить — перевірено на ф.792-1-55.

Гарди шляхів — за зразком `nyshporka.decode_hits` (справи лежать під data/raw,
сторінка = голе ім'я файлу, parent==base).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import workspace
from nyshporka.records import names as NAMES
from nyshporka.search import rank as RANK
from nyshporka.utils.translit import normalize_archival

ROOT = workspace().root
HTR_ROOT = workspace().htr_reports

_TOKEN_RE = re.compile(r"[^\s.,;:()\[\]{}/\\|«»\"'’—–-]+")


def _norm(s: str) -> str:
    # спільна архівна нормалізація (translit.normalize_archival) — фолд
    # історичних літер + Kraken-плутанин живе тепер там
    return normalize_archival(s)


def _case_roots() -> list[Path]:
    """Корені, з яких дозволено брати теки справ.

    Перший — завжди `data/raw` (канонічне місце). Далі — архівні корені поза
    репо: не весь архів підключений junction'ами в `data/raw`
    (`D:\\архів\\davio\\{f471_op4_d1,f635_op1_d11,f904_op24}`, `cdiak`,
    `_cdiak_rotm_myastk_flat` — ні), а заводити junction на кожну нову теку лише
    щоб поставити прогін — зайвий ручний крок.

    Перелік тепер веде `core.workspace`: env `MEGEN_CASE_ROOTS` перебиває маркер
    простору, маркер перебиває історичний дефолт `D:\\архів`, а неіснуючі
    корені відпадають — на іншій машині диска просто немає. Семантика та сама,
    змінилось лише те, звідки береться перелік: раніше він жив у цій функції й
    тому був невидимий для решти конвеєра.

    Це розширення зони гарда, тому корені задаються явним списком, а не
    «будь-який абсолютний шлях»: у в'ювері сторінок шлях приходить із запиту.
    """
    return workspace().case_roots()


def under_raw(path: str | Path) -> Path | None:
    """Абсолютний шлях справи, якщо він під дозволеним коренем — інакше None.

    Корені: `data/raw` + архівні (див. `_case_roots`). Ім'я лишилось історичним —
    функція є гардом шляху в трьох місцях (enqueue прогону, читання сторінок
    в'ювером, `decode_hits`).

    🔴 Чому не `.resolve()`. Великі фонди лежать на T: і видні в репо через
    junction (`data/raw/dahmo_196/<spr>` → `D:\\архів\\dahmo_196_fs\\<spr>`,
    memory `disk-layout-t-drive-junctions`). `resolve()` розкриває junction, шлях
    стає `T:\\…`, і перевірка «під data/raw» падає — тобто весь ф.196 (35 справ,
    2289 сканів) неможливо було ні поставити в чергу HTR, ні показати у в'ювері:
    гард відкидав його як чужий. Виявлено 2026-07-30 при тесті enqueue.

    `os.path.abspath` нормалізує `..` (тобто traversal так само відсікається —
    `data/raw/../../etc` вийде за межі й отримає None), але junction не розкриває.
    Фолбек на `resolve()` лишається для випадку, коли симлінком є сам корінь.
    """
    p = Path(os.path.abspath(Path(path) if Path(path).is_absolute() else ROOT / path))
    for base in _case_roots():
        for cand, root in ((p, base), (p.resolve(), base.resolve())):
            try:
                cand.relative_to(root)
                return p
            except (ValueError, OSError):
                continue
    return None


# ── довідники ────────────────────────────────────────────────────────────────
_CASE_DIR_MEMO: dict[tuple[str, str], Path] = {}


def _case_dir(name: str) -> Path | None:
    """Тека прогону за іменем — з гардом від traversal у `?name=`.

    ⚠ Розв'язаний шлях запам'ятовується: `resolve()` на NTFS коштує ~0.4 мс,
    а штамп свіжості кличе його по кілька разів на кожен із 1300 прогонів —
    4.9 с із 11 у корпусному пошуку з кешу (замір 08.09). Наявність теки
    перевіряється щоразу, лише розв'язання не повторюється.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    key = (str(HTR_ROOT), name)
    d = _CASE_DIR_MEMO.get(key)
    if d is not None:
        if d.is_dir():
            return d
        _CASE_DIR_MEMO.pop(key, None)
    d = (HTR_ROOT / name).resolve()
    if d.parent != HTR_ROOT.resolve() or not d.is_dir():
        return None
    _CASE_DIR_MEMO[key] = d
    return d


_META_MEMO: dict[str, tuple[str, dict[str, Any]]] = {}
_META_MEMO_CAP = 256


def load_meta(name: str) -> dict[str, Any] | None:
    """Мета прогону; повторне читання тієї самої мети — з пам'яті процесу.

    ⚠ Ключ пам'яті — mtime і розмір файлу, тобто дописана мета перечитується.
    Мета справи на тисячу сторінок важить мегабайт, а контекст до 2400 хітів
    читав її по разу на хіт (перевірка живим пошуком 08.09).
    """
    d = _case_dir(name)
    if d is None:
        return None
    path = d / "_htr_meta.json"
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = f"{st.st_mtime_ns:x}-{st.st_size:x}"
    hit = _META_MEMO.get(name)
    if hit and hit[0] == stamp:
        return dict(hit[1])
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    if len(_META_MEMO) >= _META_MEMO_CAP:
        _META_MEMO.clear()
    _META_MEMO[name] = (stamp, meta)
    return dict(meta)


#: Розширення моделі → рушій (дзеркало `scripts/htr_case_run._ENGINE_BY_SUFFIX`;
#: продубльовано, бо той скрипт живе в іншому venv і імпортувати його не можна).
_ENGINE_BY_SUFFIX = {".mlmodel": "kraken", ".pt": "parseq",
                     ".ckpt": "parseq", ".pth": "parseq"}


def model_names(meta: dict[str, Any]) -> list[str]:
    """Імена моделей прогону.

    🔴 Прогін двома голосами записує обидві моделі одним полем через «+»
    (`pysar_cyr_v17.pt+diak_v4`), і це не рідкість, а рекомендований спосіб
    читати кириличну справу. Розбирати таке поле як одне ім'я означає не
    впізнати жодної з двох: розширення в нього виходить `.pt+diak_v4`, глоб
    маніфесту не збігається, і прогін лишається «без рушія» — тобто без
    бейджа, без покриття письма й без другого голосу в гортачі.
    """
    return [p.strip() for p in str(meta.get("model") or "").split("+") if p.strip()]


def engine_of_model(name: str) -> Any:
    """Модель → рушій маніфесту, або порожньо.

    Два кроки, і другий обов'язковий. Глоб маніфесту вимагає розширення
    (`diak_*.mlmodel`), а другий голос у складеному імені записаний без нього
    (`diak_v4`). Тому далі пробуємо префікс — ту саму ознаку, якою письмо
    визначають усюди: `.mlmodel` буває двох письм, і каже про них саме префікс.
    """
    from nyshporka.htr import manifest as M

    name = Path(str(name or "")).name
    if not name:
        return None
    try:
        man = M.active()
    except Exception:
        return None
    got = man.engine_for_model(name)
    if got is not None:
        return got
    low = name.lower()
    for e in man.engines:
        if low.startswith(e.id.lower() + "_"):
            return e
    return None


def run_engine(meta: dict[str, Any]) -> str:
    """Рушій прогону. Мети до 2026-07-30 поля `engine` не мають — вгадуємо з
    розширення імені моделі; воно є в кожній меті, включно з прогонами старого
    `pysar_lines_infer.py`."""
    engine = (meta.get("engine") or "").strip()
    if engine:
        return engine
    names = model_names(meta)
    model = names[0] if names else ""
    # CHURRO-прогони (VLM, `scripts/churro_*`) пишуть у `model` назву HF-репо без
    # розширення — без цієї гілки вони лишались би «без рушія», і гард змішування
    # не захищав би їхні теки
    if "churro" in model.lower():
        return "churro"
    kind = _ENGINE_BY_SUFFIX.get(Path(model).suffix.lower(), "")
    if kind:
        return kind
    # Складене ім'я другого голосу розширення не має — питаємо маніфест.
    eng = engine_of_model(model)
    return eng.kind if eng is not None else ""


def run_engine_id(meta: dict[str, Any]) -> str:
    """Прогін → ідентичність моделі (`pysar` · `diak` · `skryba`), не вид рушія.

    🔴 Два різні поняття, і плутати їх не можна. `run_engine()` віддає вид
    (`kraken` · `parseq`): він каже, яким кодом рахувалось, і саме цим гард
    боронить теки від змішування. Але одного виду замало для показу: `kraken`
    буває двох письм — латинський Скриба й кириличний Дяк, — і бейдж, зроблений
    з виду, назвав би їх однаково рівно там, де різниця вирішує.

    ⚠ Ця розбіжність уже коштувала мовчазної вади: розбір знахідок малював
    бейдж із поля `engine`, тобто з виду, а таблиця бейджів ключована
    ідентичністю — збігу не було ніколи, `<use>` на неіснуючий символ не
    помиляється, і бейдж просто не з'являвся. Порожньо там, де мала стояти
    ознака «хто це прочитав».

    Порожньо тут — законна відповідь: модель поза маніфестом (чужий файн-тюн,
    CHURRO) ідентичності не має, і вигадувати її не можна.
    """
    ids = run_engine_ids(meta)
    return ids[0] if ids else ""


def run_engine_ids(meta: dict[str, Any]) -> list[str]:
    """всі рушії прогону: другий голос пише обидві моделі одним полем.

    🔴 Саме тому список, а не рядок. Прогін «Писар + Дяк» покриває письмо
    двома рушіями, і звівши його до одного, покриття справи виглядало б
    наполовину зробленим — тобто екран радив би прогнати те, що вже прогнали.
    """
    out: list[str] = []
    for name in model_names(meta):
        eng = engine_of_model(name)
        if eng is not None and eng.id not in out:
            out.append(eng.id)
    return out


#: 🪤 фантомні рядки — скільки символів на рядок мусить лишитись, щоб сторінка
#: не вважалась підозрілою. Частка від медіани самої справи, а не абсолютне
#: число: почерк і формуляр у кожній книзі свої (медіана 25.6 симв/рядок на
#: ДАВіО 474-1-174, 7.4 на ф.726-1-7, 43.9 на ф.792-1-5).
PHANTOM_FRAC = 0.30
#: Нижче цього рядків сторінку не судимо: коротка сторінка — це нормально
#: (титулка, роздільний аркуш). Фантом упізнається саме поєднанням багато
#: рядків + мало чорнила. Замір на 474-1-174: кадр 00001 (титулка, 15 рядків /
#: 101 символ) відсікається цією умовою і хибнопозитивом не стає.
PHANTOM_MIN_LINES = 25
#: Другий бік умови — причина. Фантоми родяться там, де сегментація прийняла за
#: рядки не чорнило: просвічування зі звороту на тонкому папері, водяний знак,
#: вотермарк оцифрувальника. Такі сторінки або мають низький контраст, або їх
#: підняв `--enhance auto` (він і підсилює просвічене до рівня сигналу).
PHANTOM_CONTRAST = 40.0


def phantom_pages(name: str, frac: float = PHANTOM_FRAC,
                  min_lines: int = PHANTOM_MIN_LINES,
                  contrast_max: float = PHANTOM_CONTRAST) -> dict[str, Any]:
    """🪤 Сторінки, де кількість рядків не підкріплена чорнилом.

    Навіщо. Сегментація рахує рядки за скелетом темних смуг, а не за текстом,
    тож на аркуші з просвічуванням зі звороту вона чесно віддає 75-117 «рядків»
    там, де чорнилом написано два. Розпізнавач їх слухняно декодує — виходить
    осмислена на вигляд каша, і вона потрапляє в той самий індекс, що й справжній
    текст. Далі фаззі-пошук знаходить у ній прізвище: на ДАВіО 474-1-174 кадр
    00176 дав `htr_clan_scan` найсильніший хіт роду за всю справу («Долщикъ
    Василія», root 90.9) — на аркуші, де в чорнилі є лише «Копію настоящаго
    вводнаго листа получилъ…» і латинський підпис. Такий хіт нічим не
    відрізняється від справжнього, поки не подивишся на скан.

    🔴 Це не «сторінка-сміття». На тому самому детекторі спрацьовує роздільний
    аркуш метричної книги костелу (685-1-410 кадр 0245: «Мястковской церкви за
    септембрь 1800 года… О умершихъ» — три рядки великого письма поверх
    водяного знака-дерева і вотермарку сайту, 50 рядків / 93 символи). Текст
    там цінний, зайві лише рядки. Тому викликач має позначати хіти звідси як
    такі, що потребують ока, а не мовчки викидати сторінку.

    Ознака рахується з мети прогону, без зображень: `lines`, `chars`,
    `contrast`, `enhanced`. Три умови разом (кожна поодинці шумить):
      1. `lines >= min_lines` — інакше це просто коротка сторінка;
      2. `chars/lines < frac × медіани справи` — рядки є, чорнила нема;
      3. контраст нижчий за `contrast_max` або сторінку піднімав `--enhance`
         — тобто відома причина, чому сегментація побачила зайве.

    Замір по 79 наявних прогонах: спрацьовує на 13, максимум 15% сторінок
    (468-1-495, 20 сторінок) і 10.6% (костел 685-1-410), на великих справах —
    частки відсотка (474-1-174: 6 з 364; ф.792-1-16: 1 з 3275). Тобто фільтр
    консервативний і щільні формуляри не чистить.

    ⚠ `has_contrast` < 1.0 означає, що частина мети старіша за поле `contrast`
    (з'явилось разом із `--enhance auto`); для тих сторінок працює лише гілка
    `enhanced`, і детектор мовчки слабшає. Друкувати це число, а не ховати.

    Повертає `{"pages": {скан: {...}}, "median_cpl": …, "n_pages": …,
    "has_contrast": …, "params": {...}}`; `pages` порожній, якщо мети немає.
    """
    empty = {"pages": {}, "median_cpl": 0.0, "n_pages": 0, "has_contrast": 0.0,
             "params": {"frac": frac, "min_lines": min_lines,
                        "contrast_max": contrast_max}}
    meta = load_meta(name)
    if not meta:
        return empty
    pm = meta.get("pages")
    if not isinstance(pm, dict) or not pm:
        return empty
    rows = []
    for scan, v in pm.items():
        if not isinstance(v, dict):
            continue
        lines = v.get("lines") or 0
        if lines <= 0:
            continue
        rows.append((scan, lines, v.get("chars") or 0, v.get("contrast"),
                     v.get("enhanced")))
    if not rows:
        return empty
    cpl = sorted(c / ln for _, ln, c, _, _ in rows)
    mid = len(cpl) // 2
    median = cpl[mid] if len(cpl) % 2 else (cpl[mid - 1] + cpl[mid]) / 2
    out: dict[str, dict[str, Any]] = {}
    for scan, lines, chars, contrast, enhanced in rows:
        ratio = chars / lines
        if lines < min_lines or ratio >= median * frac:
            continue
        faint = contrast is not None and contrast < contrast_max
        if not (faint or enhanced):
            continue
        why = "вицвіла" if faint else "піднято контраст"
        out[scan] = {"lines": lines, "chars": chars, "cpl": round(ratio, 1),
                     "contrast": contrast, "enhanced": enhanced,
                     "why": f"{lines} рядків на {chars} симв. "
                            f"({ratio:.1f}/рядок проти {median:.1f} по справі), {why}"}
    return {"pages": out, "median_cpl": round(median, 1), "n_pages": len(rows),
            "has_contrast": round(sum(1 for r in rows if r[3] is not None) / len(rows), 2),
            "params": {"frac": frac, "min_lines": min_lines,
                       "contrast_max": contrast_max}}


def _sec_median(meta: dict[str, Any]) -> float | None:
    """Медіана секунд на сторінку в цьому прогоні, або порожньо.

    🔴 Порожньо, а не нуль. Нуль читався б як «читає миттєво» й дав би оцінку
    «≈0 хв» на справу в три тисячі аркушів; відсутнє число чесно каже, що
    міряти нема на чому — і тоді на екрані стоїть кількість кадрів замість
    вигаданого часу.

    ⚠ Беремо саме медіану: перші сторінки прогону несуть розігрів моделі, а
    порожні звороти — частки секунди, тож середнє хибне в обидва боки.
    """
    secs = sorted(float(p["sec"]) for p in (meta.get("pages") or {}).values()
                  if isinstance(p, dict) and isinstance(p.get("sec"), (int, float))
                  and p["sec"] > 0)
    if not secs:
        return None
    mid = len(secs) // 2
    return round(secs[mid] if len(secs) % 2 else (secs[mid - 1] + secs[mid]) / 2, 2)


#: Останній зібраний перелік прогонів і штамп, за якого його зібрали.
#: 🔴 Не заради швидкодії заради швидкодії: на просторі з 1125 прогонами
#: перелік коштує 8.2 с — стільки читаються 1125 файлів мети плюс опис справи
#: на кожен. Екран прогонів на таких паузах перестає бути переліком і стає
#: очікуванням, а гортати його доводиться постійно.
_RUNS_CACHE: tuple[tuple[int, int, int, str], list[dict[str, Any]]] | None = None


def _runs_stamp() -> tuple[int, int, int, str]:
    """Скільки тек прогонів, коли найсвіжіша торкалась, найсвіжіша мета, бібліотека.

    ⚠ Штамп, а не час життя: перелік мусить оновитись одразу після прогону, і
    кеш «на десять секунд» показував би щойно завершену роботу як відсутню.
    Один обхід тек коштує міллісекунди проти восьми секунд читання мет.

    🔴 Мета окремо від теки: правка `_htr_meta.json` на місці mtime теки на
    NTFS не міняє, і довгоживучий процес (в'ювер, MCP) не бачив її до
    перезапуску (рецензія 08.09, третій раунд). Бібліотека — бо шифра й кадри
    в рядку переліку беруться з неї.
    """
    if not HTR_ROOT.is_dir():
        return (0, 0, 0, "")
    n = 0
    newest = 0
    newest_meta = 0
    with os.scandir(HTR_ROOT) as it:
        for e in it:
            if not e.is_dir():
                continue
            n += 1
            try:
                newest = max(newest, e.stat().st_mtime_ns)
                newest_meta = max(newest_meta,
                                  os.stat(os.path.join(e.path, "_htr_meta.json")).st_mtime_ns)
            except OSError:
                continue
    return (n, newest, newest_meta, _library_stamp())


def _library_stamp() -> str:
    try:
        from nyshporka.library import LIBRARY_PATH

        st = LIBRARY_PATH.stat()
        return f"{st.st_mtime_ns:x}-{st.st_size:x}"
    except Exception:
        return ""


def list_cases() -> list[dict[str, Any]]:
    """Прогони з reports/htr/* — для списку в'ювера. Назва справи — з бібліотеки."""
    global _RUNS_CACHE

    stamp = _runs_stamp()
    if _RUNS_CACHE is not None and _RUNS_CACHE[0] == stamp:
        return _RUNS_CACHE[1]
    # 🔴 Кеш на диску ПО ПРОГОНАХ, за штампом мети кожного (mtime+розмір —
    # той самий, що в `decode.stamp_of`). Читання 1300 мет коштує 3 с у КОЖНІЙ
    # команді нового процесу; кеш за mtime кореня зривався щоразу, коли хоч
    # один прогін живий, а правку мети на місці не бачив узагалі (рецензія
    # 08.09). Тепер перечитуються лише прогони, чия мета змінилась.
    entries = _runs_cache_read(stamp[3])
    changed = False
    out: list[dict[str, Any]] = []
    if not HTR_ROOT.is_dir():
        return out
    try:
        from nyshporka.library import describe_case
    except Exception:  # бібліотека не критична для списку
        def describe_case(_p: str) -> dict[str, Any] | None:  # type: ignore[misc]
            return None
    seen: set[str] = set()
    for meta_path in sorted(HTR_ROOT.glob("*/_htr_meta.json")):
        name = meta_path.parent.name
        seen.add(name)
        try:
            ms = meta_path.stat()
            mstamp = f"{ms.st_mtime_ns:x}-{ms.st_size:x}"
        except OSError:
            continue
        hit = entries.get(name)
        if hit and hit.get("stamp") == mstamp and isinstance(hit.get("row"), dict):
            out.append(dict(hit["row"]))
            continue
        changed = True
        meta = load_meta(name)
        if not meta:
            entries.pop(name, None)
            continue
        case = None
        # Шифра — прикраса переліку: прогін без розв'язаної справи лишається
        # видимим, просто без неї. Падати тут означало б сховати цілий перелік
        # через один нерозв'язаний шлях.
        with contextlib.suppress(Exception):
            case = describe_case(meta.get("case_dir") or "")
        out.append({
            "name": name,
            "case_dir": meta.get("case_dir") or "",
            "shifra": (case or {}).get("shifra") or "",
            "title": (case or {}).get("title") or "",
            # 🔴 Шифра З мети, а не з бібліотеки. Це різні числа: `shifra` вище —
            # прикраса переліку, яку дав резолвер, а `case_key` — те, що прогін
            # несе В собі. Саме за ним справу впізнає будь-хто поза цим
            # простором, і саме його порожність робить прогін нічиїм: текст є,
            # а чия це справа — невідомо, і зшивати доводиться руками.
            "case_key": (meta.get("case_key") or "").strip(),
            # 🔴 Кадри справи — знаменник покриття, і їдуть вони поруч із
            # чисельником навмисно. Без них лишається саме число прочитаних
            # сторінок, а поділити його нема на що: покриття, пораховане від
            # себе самого, завжди дорівнює 100% і читається як «прочитано
            # все». Порожньо тут законне — опису справи може не бути.
            "frames": int((case or {}).get("frames") or 0),
            "pages_done": len(meta.get("pages") or {}),
            "failed": len(meta.get("failed") or []),
            "done": bool(meta.get("done")),
            "model": meta.get("model") or "",
            # рушій і письмо прогону: на одну справу їх буває кілька (латинку читає
            # Скриба, кирилицю Писар), і без цього не сказати, чим прочитана сторінка
            "engine": run_engine(meta),
            # Ідентичність моделі — окремо від виду: `kraken` буває двох письм.
            "engine_id": run_engine_id(meta),
            # Прогін двома голосами покриває два рушії; звівши його до
            # одного, покриття справи виглядало б наполовину зробленим.
            "engine_ids": run_engine_ids(meta),
            "script": meta.get("script") or "",
            "device": meta.get("device") or "",
            "enhance": meta.get("enhance") or "",
            # ⏱ Медіана секунд на сторінку — замір цієї машини, а не константа.
            # Єдине чесне джерело оцінки часу: та сама справа на чужій карті
            # читається в рази інакше, а на процесорі — на порядок.
            "sec_median": _sec_median(meta),
            "updated": meta.get("updated") or "",
        })
        entries[name] = {"stamp": mstamp, "row": dict(out[-1])}
    gone = [n for n in entries if n not in seen]
    for n in gone:
        entries.pop(n, None)
    out.sort(key=lambda c: c["updated"], reverse=True)
    _RUNS_CACHE = (stamp, out)
    if changed or gone:
        _runs_cache_write(entries, stamp[3])
    return out


def _runs_cache_path() -> Path:
    return workspace().derived / "runs_cache.json"


def _runs_cache_read(lib: str = "") -> dict[str, dict[str, Any]]:
    """Кеш по прогонах; чужа бібліотека — кеш порожній: шифра й кадри в рядках
    беруться з неї, і після її перезбірки вони старіли, поки мета не зміниться."""
    try:
        data = json.loads(_runs_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or str(data.get("lib") or "") != lib:
        return {}
    ent = data.get("entries")
    return {str(k): v for k, v in ent.items() if isinstance(v, dict)} if isinstance(ent, dict) else {}


def _runs_cache_write(entries: dict[str, dict[str, Any]], lib: str = "") -> None:
    p = _runs_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"lib": lib, "entries": entries}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass  # кеш — зручність, не умова роботи


def runs_by_case_dir() -> dict[str, list[dict[str, Any]]]:
    """Мапа resolved-case_dir → прогони цієї теки. Для масового збагачення пікера
    файлового браузера (десятки тек за один запит) — щоб не пере-читувати всі
    `_htr_meta.json` per-тека (`list_cases()` уже це робить один раз)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for c in list_cases():
        # abspath, не resolve: ключ мусить збігатися з тим, що дає `under_raw`,
        # інакше junction-справи (ф.196 на T:) не матчились би з пікером
        try:
            key = str(Path(os.path.abspath(ROOT / (c.get("case_dir") or ""))))
        except OSError:
            continue
        out.setdefault(key, []).append(c)
    return out


def find_runs_for_case(case: str) -> list[dict[str, Any]]:
    """Прогони, чия case_dir збігається з `case` (та сама розрізнення теки, що при
    enqueue) — щоб пікер показав «прогін уже був» ще до постановки в чергу."""
    case = (case or "").strip()
    if not case:
        return []
    case_dir = Path(os.path.abspath(
        Path(case) if Path(case).is_absolute() else ROOT / case))
    return runs_by_case_dir().get(str(case_dir), [])


def unique_pages(rows: list[dict[str, Any]]) -> int:
    """Скільки різних сторінок прочитано в цих прогонах.

    🔴 Не сума `pages_done`. Справу з двома письмами читають двома голосами —
    Писар кирилицю, Скриба латинку, — і кожен проходить ті самі аркуші. Сума
    дає рівно подвійний знаменник, тобто «не знайшлось у 6 сторінках» на справі
    з трьох. Знаменник, більший за наявне, гірший за відсутній: він виглядає як
    ширше покриття, ніж було, і саме за ним закривають напрям.

    Тому по кожній справі береться найповніший прогін, а не всі разом — так
    само, як це давно робить реєстр (`cases.collect`, `htr_pages_max`).
    ⚠ Нічийний прогін (без ключа й теки) рахується сам за себе: склеївши їх
    усіх в одну групу, ми б втратили знаменник саме там, де він найкрихкіший.
    """
    groups: dict[str, int] = {}
    for r in rows:
        key = (r.get("case_key") or "").strip()
        if not key:
            case_dir = (r.get("case_dir") or "").strip()
            key = f"dir:{case_dir}" if case_dir else f"run:{r.get('name')}"
        groups[key] = max(groups.get(key, 0), int(r.get("pages_done") or 0))
    return sum(groups.values())


def runs_for_scope(scope: str) -> dict[str, Any]:
    """Прогони, у яких шукати: `scope` — справа, прогін або порожньо (весь корпус).

    🔴 Одна функція на чисельник і знаменник. Доти, доки область пошуку
    вибиралась в одному місці, а знаменник рахувався в іншому, відповідь
    звучала як «не знайшлось у 1 прогонах (320 669 сторінок)»: шукали в справі,
    а звітували обсягом усього простору. Знаменник від чужої роботи — це вже не
    нуль зі знаменником, а нуль із чужим алібі.

    🔴 Справа, а не лише прогін. Ім'я теки прогону — наша внутрішня дрібниця;
    людина (і кнопка «шукати в цій справі») знає справу за ключем чи шифрою.
    Доти, доки сюди приймалось лише ім'я теки, ключ `DAHMO/315/159` не
    резолвився в жодну теку й пошук чесно відповідав «не знайшлось у 0
    прогонах» — тобто нуль хітів на справі, де рід є.

    ValueError — якщо рядок не впізнано ні як прогін, ні як справу; текст
    відмови нормативний (перелік прийнятних форм дає `pagestore.resolve_case`).
    """
    rows = list_cases()
    want = (scope or "").strip()
    if not want:
        return {"rows": rows, "kind": "all", "key": "", "shifra": ""}

    by_name = [r for r in rows if r.get("name") == want]
    if by_name:
        # Ключ прогону віддається разом із ним: те саме значення `--case` має
        # означати ту саму справу і в пошуку по декоду, і в пошуку по
        # виписаному. Порожньо тут законне — прогін буває нічийним.
        return {"rows": by_name,
                "kind": "run",
                "key": (by_name[0].get("case_key") or "").strip(),
                "shifra": by_name[0].get("shifra") or ""}

    from nyshporka.pagestore.store import resolve_case

    try:
        ref = resolve_case(want)
    except ValueError:
        # 🔴 Фонд або опис — теж область: «904-24», «ДАВіО 904-24», «230-1»
        # означають усі справи серії. Доти доводилось ганяти справи по одній
        # (перевірка живим пошуком 08.09). Збіг — за хвостом шифри прогону,
        # тож «230-1» не тягне «230-10».
        series = _series_rows(rows, want)
        if not series:
            raise
        keys = sorted({(r.get("case_key") or "").strip() for r in series})
        return {"rows": series, "kind": "cases", "key": "", "shifra": want,
                "keys": keys}
    mine = [r for r in rows if (r.get("case_key") or "").strip() == ref.key]
    if not mine and ref.path:
        # Прогін, який не несе ключа в собі, ще може вказувати на ту саму теку.
        # Це не рідкість: ключ у меті з'явився пізніше за самі прогони.
        mine = find_runs_for_case(ref.path)
    return {"rows": mine, "kind": "case", "key": ref.key, "shifra": ref.shifra}


_SERIES_RE = re.compile(r"(\d+(?:[-/]\d+[a-zа-я]?)*)\s*$")


def _series_rows(rows: list[dict[str, Any]], want: str) -> list[dict[str, Any]]:
    """Прогони справ, чия шифра починається з фонду/опису запиту."""
    m = _SERIES_RE.search(want.replace("\\", "/").strip())
    if not m:
        return []
    head = m.group(1).replace("/", "-")
    out: list[dict[str, Any]] = []
    for r in rows:
        sh = str(r.get("shifra") or "").strip()
        tail = sh.split()[-1].replace("/", "-") if sh else ""
        if tail and (tail == head or tail.startswith(head + "-")):
            out.append(r)
    return out


def case_pages(name: str) -> dict[str, Any] | None:
    """Мета + сторінки прогону (для навігації в'ювера)."""
    meta = load_meta(name)
    if meta is None:
        return None
    pages = []
    for pg, info in sorted((meta.get("pages") or {}).items()):
        pages.append({"page": pg, **{k: info.get(k) for k in
                                     ("orient", "lines", "chars", "conf", "sec",
                                      "gap_loop", "suspect_confab")}})
    return {"name": name, "case_dir": meta.get("case_dir") or "",
            "model": meta.get("model") or "", "done": bool(meta.get("done")),
            "engine": run_engine(meta), "engine_id": run_engine_id(meta),
            "engine_ids": run_engine_ids(meta),
            "script": meta.get("script") or "",
            "case_key": (meta.get("case_key") or "").strip(),
            "failed": meta.get("failed") or [], "pages": pages}


def read_page_text(name: str, page: str) -> dict[str, Any] | None:
    meta = load_meta(name)
    if meta is None:
        return None
    info = (meta.get("pages") or {}).get(page)
    if info is None:
        return None
    d = _case_dir(name)
    txt = d / (Path(page).stem + ".txt") if d else None
    if txt is None or not txt.is_file() or txt.parent != d:
        return None
    lines = txt.read_text(encoding="utf-8").splitlines()
    return {"page": page, "lines": lines, "orient": info.get("orient", 0),
            "conf": info.get("conf"), "detector": info.get("detector")}


def page_lines(name: str, page: str) -> dict[str, Any] | None:
    """🖼 Геометрія рядків сторінки — щоб в'ювер міг показати, звідки рядок тексту.

    Джерело — `<стем>.lines.json`, який пише прогін: `boxes` (AABB, ним ріжуть
    кропи) і `polys` (полігон рядка — рядок скоропису йде похило, тож його bbox
    накриває сусідів; підсвічувати треба фігуру). Індекс рамки == номер рядка в
    `.txt`, вирівнювання гарантує сам прогін.

    Рамки лежать у координатах повернутого зображення — того самого, яким
    `/htr/img` віддає скан, тож фронту лишається тільки вписати `size` у
    viewBox. Старі файли `size` не мають: тоді він добирається із заголовка
    скану (пікселі не декодуються).

    Відсутність рамок — не помилка: kraken-прогони до 2026-08-09 їх не писали
    зовсім. Повертається `has=False`, і в'ювер просто лишається без оверлея.
    """
    meta = load_meta(name)
    if meta is None:
        return None
    info = (meta.get("pages") or {}).get(page)
    if info is None:
        return None
    d = _case_dir(name)
    f = d / (Path(page).stem + ".lines.json") if d else None
    if f is None or not f.is_file() or f.parent != d:
        return {"page": page, "has": False}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"page": page, "has": False}
    if not isinstance(data, dict) or not isinstance(data.get("boxes"), list):
        return {"page": page, "has": False}
    # 🔴 Лише числа. Рамки й розмір консоль вписує в SVG через `innerHTML`, а
    # `.lines.json` приїжджає й з орендованої машини (`cloud fetch`): рядок на
    # місці числа вийшов би з атрибута й виконався б у сторінці застосунку —
    # разом із її токеном. Зіпсована рамка стає `null`, як рядок без обведення,
    # тож нумерація рядків не зсувається.
    boxes = [_numbers(b) for b in data["boxes"]]
    if not boxes:
        return {"page": page, "has": False}
    size = _numbers(data.get("size"))
    if size is not None and len(size) < 2:
        size = None
    if not size:
        got = resolve_scan(name, page)
        if got is not None:
            src, orient = got
            wh = _image_size(src)
            if wh:
                size = [wh[1], wh[0]] if orient in (90, 270) else [wh[0], wh[1]]
    if not size:
        # 🔴 Рамки Є, але масштаб невідомий — і це різні речі, які досі
        # виглядали однаково. Так буває саме на PDF-прогонах: старий
        # `.lines.json` без `size`, а скану, з якого можна доміряти, на цій
        # машині немає (кадри жили на орендованому боксі). Накласти рамку на
        # рендер тут нічим — але сказати «рамок немає» означає збрехати про
        # причину, а причина лікується по-різному: рамки додає перепрогін,
        # масштаб — поява самого скану.
        return {"page": page, "has": False, "boxes_known": True,
                "why": "прогін не записав розміру зображення, тож рамку рядка "
                       "накласти нічим — показано всю сторінку (рамки в цьому "
                       "прогоні є, бракує лише масштабу)"}
    raw_polys = data.get("polys")
    polys = [_points(p) for p in raw_polys] if isinstance(raw_polys, list) and raw_polys else None
    if polys is not None and len(polys) != len(boxes):
        polys = None            # довжини розійшлись — краще прямокутник, ніж не той рядок
    return {"page": page, "has": True, "size": size,
            "boxes": boxes, "polys": polys}


def _numbers(v: Any) -> list[int | float] | None:
    """Список чисел із чужого JSON як є — або None, якщо там бодай щось інше."""
    if not isinstance(v, list) or not v:
        return None
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return None
    return list(v)


def _points(v: Any) -> list[list[int | float]] | None:
    """Полігон рядка: список пар чисел — або None."""
    if not isinstance(v, list) or not v:
        return None
    pts = [_numbers(p) for p in v]
    if any(p is None for p in pts):
        return None
    return [p for p in pts if p is not None]


def _image_size(path: Path) -> list[int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return [int(im.width), int(im.height)]
    except (ImportError, OSError):
        return None


def resolve_scan(name: str, page: str) -> tuple[Path, int] | None:
    """Оригінальний скан сторінки + кут повороту, яким користувався OCR."""
    got = resolve_scan_how(name, page)
    return None if got is None else (got[0], got[1])


def resolve_scan_how(name: str, page: str) -> tuple[Path, int, str] | None:
    """Те саме, але третім значенням — ЯК кадр знайшовся: `meta` чи `registry`.

    🔴 Різниця не технічна. `meta` означає, що шлях у меті прогону живий і кадр
    узято звідти, де рушій його й бачив. `registry` означає, що шлях мертвий
    (хмарний прогін записав теку орендованого бокса) і тека дібрана за шифрою
    вже нами — а тоді збіг ІМЕНІ файла ще не є збігом кадру: плоский стейджинг
    перенумеровує сторінки, і `0001.jpg` однієї теки це не `0001.jpg` іншої.
    Такий кроп треба звіряти рядком `скан:`, і про це має бути сказано вголос.

    Гарди як у decode_hits.scan_path: `page` — голе ім'я, тека справи — під
    data/raw (junction'и на T: лінковані туди ж), результат — прямо в ній.
    """
    if not page or "/" in page or "\\" in page or page.startswith("."):
        return None
    meta = load_meta(name)
    if meta is None:
        return None
    info = (meta.get("pages") or {}).get(page)
    if info is None:
        return None
    orient = int(info.get("orient") or 0)
    # junction-safe: див. `under_raw` — `.resolve()` тут відкидав увесь ф.196
    base = under_raw(meta.get("case_dir") or "")
    if base is not None:
        target = Path(os.path.abspath(base / page))
        if target.parent == base and target.is_file():
            return target, orient, "meta"

    # 🔴 Фолбек через реєстр справ, і він подвоює зону видимості гортача.
    # Хмарний прогін пише в мету шлях орендованого бокса
    # (`/tmp/htrcase/pages_dl`) або стейджингу — теки, якої на цій машині немає
    # й не було. Текст такого прогону є, рамки рядків є, а подивитись оком
    # нічим: `case_dir` веде в нікуди. Резолвер саме для цього й існує — він
    # зводить ім'я прогону до справи бібліотеки, а в неї шлях уже справжній.
    #
    # Заміряно 2026-08-15 на 478 прогонах: скан лежить там, де каже мета, у
    # 161; ще 165 знаходяться цим фолбеком (34% → 68%). Решта 150 — справи, що
    # лежать PDF-ом: прогін читав рендер, якого на цій машині ніколи не було,
    # і вгадувати відповідність «кадр → сторінка PDF» тут не можна — показати
    # не той аркуш гірше, ніж не показати нічого.
    for cand in _case_dirs_via_registry(name):
        target = Path(os.path.abspath(cand / page))
        if target.parent == cand and target.is_file():
            return target, orient, "registry"
    return None


def frames_match_meta(run: str, sample: int = 3) -> tuple[bool, str]:
    """Чи ті самі кадри бачить споживач декоду, що бачив рушій.

    🔴 «Кадрів у теці стільки ж» доказом НЕ є. Плоский стейджинг перенумеровує
    сторінки, тож тека може мати рівно стільки ж файлів із тими самими іменами
    і бути іншою книгою. Тому три перевірки, і кожна може відмовити окремо:

    1. **ім'я** — сторінки з мети існують у теці, куди резолвиться скан;
    2. **обсяг** — кадрів у теці не менше, ніж сторінок у прогоні;
    3. **пропорції** — для `sample` сторінок із рамками розмір, у якому рушій
       бачив кадр (`size` у `.lines.json`), звіряється з реальним розміром
       файла з точністю до `orient`. Розбіжність співвідношення сторін означає
       ІНШИЙ кадр, і це єдина з трьох перевірок, яка ловить перенумерований
       стейджинг.

    Повертає `(усе сходиться, чому ні)`. Порожня причина при `False` не буває:
    мовчазний `False` тут був би тим самим мовчазним звуженням.
    """
    meta = load_meta(run)
    if meta is None:
        return False, "меты прогону немає"
    pages = list((meta.get("pages") or {}).keys())
    if not pages:
        return False, "мета не називає жодної сторінки"
    missing = [p for p in pages if resolve_scan(run, p) is None]
    if missing:
        return False, (f"кадрів немає для {len(missing)} із {len(pages)} сторінок"
                       f" (напр. {', '.join(missing[:3])})")
    first = resolve_scan(run, pages[0])
    assert first is not None
    folder = first[0].parent
    have = sum(1 for x in folder.iterdir() if x.is_file())
    if have < len(pages):
        return False, (f"у теці {folder.name} кадрів {have}, а сторінок прогону "
                       f"{len(pages)}")
    checked = bad = 0
    for page in pages:
        if checked >= sample:
            break
        geom = page_lines(run, page)
        size = (geom or {}).get("size")
        got = resolve_scan(run, page)
        if not size or got is None:
            continue
        real = _image_size(got[0])
        if not real:
            continue
        checked += 1
        # Рушій міг крутити кадр, тож пропорція звіряється в обидва боки.
        want = size[0] / size[1] if size[1] else 0.0
        here = real[0] / real[1] if real[1] else 0.0
        if want and here and min(abs(want - here), abs(want - 1 / here)) > 0.02:
            bad += 1
    if bad:
        return False, (f"пропорції кадру не сходяться з тим, у чому читав рушій:"
                       f" {bad} із {checked} звірених сторінок")
    if not checked:
        return True, "імена й обсяг сходяться; геометрії немає — звіряти нічим"
    return True, ""


def _case_dirs_via_registry(run: str) -> list[Path]:
    """Теки, де можуть лежати скани цього прогону, за реєстром справ.

    Справа часто лежить у кількох теках — оригінали, зменшені копії для хмари,
    посторінковий рендер PDF, — і сторінка з тим самим іменем є не в кожній.
    Тому повертається перелік, а не одна тека.
    """
    try:
        from nyshporka.cases.resolve import LibraryIndex, resolve_run
        from nyshporka.library import load_library
    except Exception:
        return []
    # 🔴 Резолвер питається ПОВНІСТЮ, як його питає реєстр справ
    # (`cases.collect._rows_from_runs`). Доти сюди йшов голий `resolve_run(run)`
    # — без `case_dir` і без `meta_key`, тобто два найсильніші з шести каналів
    # були вимкнені просто тим, що аргументи не передали. Наслідок бачив
    # користувач, а не розробник: реєстр показував прогін прив'язаним, а гортач
    # на тій самій справі казав «теки справи цей прогін не називає» і слав
    # набирати `nysh cases bind` у терміналі.
    meta = load_meta(run) or {}
    try:
        link = resolve_run(run, str(meta.get("case_dir") or ""),
                           meta_key=str(meta.get("case_key") or ""))
    except Exception:
        return []
    if not link.key:
        return []
    out: list[Path] = []
    try:
        idx = LibraryIndex(load_library())
        entry = idx.by_key.get(link.key) or {}
    except Exception:
        return []
    for rel in (entry.get("path"), entry.get("raw_path"),
                *(entry.get("extra_paths") or [])):
        if not rel:
            continue
        d = under_raw(str(rel))
        if d is not None and d.is_dir() and d not in out:
            out.append(d)
    return out


# ── fuzzy-пошук ──────────────────────────────────────────────────────────────
# Кеш нормалізованих токенів: name → (cache_key, [(page, line_no, raw, [(tok, norm)])])
_CACHE: dict[str, tuple[str, list[Any]]] = {}

#: Скільки попередніх рядків тримати для склейки розірваного прізвища.
#: 1 = лише сусідній (стара поведінка). У табличних бланках сегментація зшиває
#: колонки і половинки розходяться на 2-3 рядки, тому дефолт 3.
LINE_BREAK_WINDOW = 3

#: Від скількох літер половина далекої склейки вважається ПОВНИМ словом.
#:
#: 🔴 Дві повні половини — це не перенос, а хімера з двох цілих слів, які на
#: аркуші стоять за рядок-два одне від одного: «собрание-2⏎дворян»,
#: «дворянского-3⏎дворян», «Гуллецъ-3⏎заскаст». Заміряно на корпусі: такими є
#: 22% усіх далеких склейок, а самі далекі склейки дають 12% кандидатів індексу.
#:
#: Межа 6 підібрана заміром на золотому наборі дослідницького конвеєра (3124
#: аркуші з вердиктом ока), і вона єдина безкоштовна:
#:
#: | межа | аркушів роду над порогом | шум | хітів | втрата |
#: |---|---|---|---|---|
#: | без правила | 499 із 526 | 783 | 11136 | — |
#: | 4 | 493 | 754 | 8175 | 6 |
#: | 5 | 496 | 764 | 8777 | 3 |
#: | **6** | **499** | **773** | **9109** | **0** |
#: | 7 | 499 | 775 | 9435 | 0 |
#:
#: Нижче 6 різати не можна: одиночний токен береться в кандидати від 4 літер,
#: тож половина в 4-5 літер ще буває уламком переносу («доли», «щин»).
WHOLE_WORD = 6

#: Скільки змістовних символів мусить набратись у контексті з кожного боку.
#: 🔴 Огризок контекстом не вважається: сусідній рядок «на», «и», «3» не пояснює
#: нічого, тож вікно розсувається далі, доки не набереться цієї міри. Без такого
#: розсування «контекст» на щільних формулярах виявляється порожнім рівно там,
#: де він найпотрібніший — між колонками таблиці.
MIN_CTX_CHARS = 24
#: Стеля розсування, щоб вікно не з'їло півсторінки на аркуші з обривками.
MAX_CTX_LINES = 4


def line_window(name: str, page: str, line_index: int, *, side: int = 1,
                min_chars: int = MIN_CTX_CHARS) -> dict[str, Any]:
    """Рядок разом із сусідами — розсувне вікно, а не фіксовані ±N.

    🔴 Навіщо вікно, якщо є сам рядок. Рядок-хіт не розрізняє прізвищ зі
    спільним коренем, а в одній парафії їх буває кілька; заміряно на метриках
    одного села: 78 кандидатів верхівки розклались на три різні роди зі
    спільним коренем плюс причт — і за самим рядком вони зливаються в купу
    однаково правдоподібних хітів.

    Розрізняє їх сусідство: перенесена половина слова читається лише разом із
    наступним рядком; стан і роль («крестьянка», «псаломщикомъ») зазвичай
    стоять у сусідньому рядку, а не в тому самому.
    """
    got = read_page_text(name, page) or {}
    lines: list[str] = list(got.get("lines") or [])
    if not lines or not 0 <= line_index < len(lines):
        return {"before": [], "line": "", "after": []}

    def grab(rng: range) -> list[str]:
        out: list[str] = []
        chars = 0
        for i in rng:
            if len(out) >= MAX_CTX_LINES:
                break
            s = lines[i].strip()
            out.append(s)
            chars += len(_TOKEN_RE.sub("", s).strip()) + sum(
                len(t) for t in _TOKEN_RE.findall(s) if len(t) >= 3)
            if chars >= min_chars and len(out) >= side:
                break
        return out

    before = grab(range(line_index - 1, -1, -1))[::-1]
    after = grab(range(line_index + 1, len(lines)))
    return {"before": before, "line": lines[line_index], "after": after}


def voice_pair(name: str) -> str | None:
    """Прогін-побратим тієї самої справи, зроблений іншим рушієм.

    🔴 Два голоси на одному рядку — не надлишок. Там, де вони збіглись, читання
    надійне; де розійшлись — це сигнал, а не шум: рушій із мовною моделлю
    підставляє правдоподібне слово, а CTC калічить локально, зберігаючи корінь.
    Саме розбіжність і показує, що ознака в пікселях, а отже суддя — око.
    """
    meta = load_meta(name) or {}
    # 🔴 Порівнюються ідентичності моделей, а не вид рушія. Вид (`kraken` ·
    # `parseq`) для цього питання завузький одразу з двох боків: латинський
    # Скриба й кириличний Дяк — обидва `kraken`, а прогін «Писар + Дяк» має
    # вид першої моделі й на вигляд не відрізняється від самого Писаря.
    #
    # ⚠ Побратим — це прогін, у якого є рушій, якого немає в мене. Тому
    # різниця несиметрична: у прогону, що вже несе обидва голоси, побратима
    # немає — і це правильна відповідь, а не порожнеча через недогляд.
    mine = set(run_engine_ids(meta)) or {run_engine(meta)}
    key = (meta.get("case_key") or "").strip()
    base = str(meta.get("case_dir") or "")
    # 🔴 По рядках переліку, не по метах: перелік уже несе ключ, теку й рушії
    # кожного прогону, а читання 1326 мет на КОЖЕН прогін із хітами давало
    # 9 хвилин на `find --json --limit 2400` (перевірка живим пошуком 08.09).
    for other in list_cases():
        nm = str(other.get("name") or "")
        if not nm or nm == name:
            continue
        same = ((key and (other.get("case_key") or "").strip() == key)
                or (base and str(other.get("case_dir") or "") == base))
        if not same:
            continue
        theirs = set(other.get("engine_ids") or []) or {str(other.get("engine") or "")}
        if theirs - mine:
            return nm
    return None


def _case_index(name: str) -> list[Any]:
    d = _case_dir(name)
    meta_path = d / "_htr_meta.json" if d else None
    if d is None or meta_path is None or not meta_path.is_file():
        return []
    txts = sorted(d.glob("*.txt"))
    key = f"{meta_path.stat().st_mtime_ns}|{len(txts)}"
    hit = _CACHE.get(name)
    if hit and hit[0] == key:
        return hit[1]
    meta = load_meta(name) or {}
    stem2page = {Path(pg).stem: pg for pg in (meta.get("pages") or {})}
    index = []
    for txt in txts:
        page = stem2page.get(txt.stem, txt.name)
        for ln_no, raw, cands in page_candidates(
                txt.read_text(encoding="utf-8").splitlines()):
            index.append((page, ln_no, raw, cands))
    _CACHE[name] = (key, index)
    return index


def page_candidates(lines: list[str]) -> Iterator[tuple[int, str, list[tuple[str, str]]]]:
    """Рядки сторінки → кандидати на збіг, без походження.

    Вьюха над `page_candidates_full`: та сама послідовність, зрізаний третій
    елемент. Форма збережена, бо її читають споживачі поза пакетом.
    """
    for no, raw, cands in page_candidates_full(lines):
        yield no, raw, [(w, n) for w, n, _kind in cands]


#: Види кандидата — звідки він узявся в рядку.
#:
#: 🔴 Вид потрібен не для звіту, а для СУДУ: далека склейка (`glue2`/`glue3`)
#: поводиться інакше за решту — вона перетинає поріг `partial_ratio` самою
#: довжиною хвоста й тягне бал вікна на голову, якої в збігу немає. Судити її
#: тими самими правилами, що й цілий токен, означає піднімати сміття над
#: правдою. Доти вид відновлювали здогадом по сепаратору в слові.
KIND_TOKEN = "tok"
KIND_PAIR = "pair"
KIND_TRIPLE = "triple"
KIND_GLUE = "glue"          # + номер `back`: glue1, glue2, glue3
FAR_KINDS = ("glue2", "glue3")


def page_candidates_full(lines: list[str]
                         ) -> Iterator[tuple[int, str, list[tuple[str, str, str]]]]:
    """Рядки сторінки → кандидати на збіг із ВИДОМ. Один дім на весь застосунок.

    🔴 Виділено з побудови індексу, бо цих правил склейки потребують два
    читачі: індекс пошуку (гуртом) і розбір знайденого хіта (одна сторінка,
    щоб назвати саме те слово, яке збіглося). Друга копія правил розійшлася б
    із першою тихо — і пошук почав би знаходити не те, що вміє пояснити.

    ⚠ Стан переносів (`prev_toks`) живе В межах сторінки: перенос через
    останній рядок аркуша на перший рядок наступного не буває, а якби ми його
    допустили, склейка йшла б через розворот.
    """
    prev_toks: list[str] = []   # хвости попередніх рядків — для переносів
    for ln_no, raw in enumerate(lines, 1):
        toks = _TOKEN_RE.findall(raw)
        # ⚠ окремий фільтр «рядків-огризків» тут не потрібен — перевірено
        # заміром 2026-07-31, щоб наступний не пішов тим самим хибним
        # шляхом. На порожньому звороті сегментація ріже волокна паперу як
        # рядки, і декод віддає «с / и / св / 1 ; 7 / сащъ». Таких рядків
        # у корпусі 23.7%, і виглядають вони як явне джерело хибних збігів,
        # але кандидатів з них майже не виходить: одиночний токен береться
        # від 4 літер, пара — від 6 сумарно, тож огризок і так відсіюється
        # довжиною. Спроба глушити їх явно прибрала 0.1% кандидатів і
        # нуль хітів на восьми контрольних запитах (рід, Ярошинські,
        # М'ястківка, Ігнатків, Kowalski, Szczurowski).
        # 🔴 А глушити такий рядок цілком (разом із хвостом у `prev_toks`)
        # прямо шкідливо: у вузькій колонці перша половина прізвища буває
        # сама в огризку («doi» / «szczynskiego»), і на ф.792-1-16 такий
        # варіант з'їв три склейки роду.
        cands: list[tuple[str, str, str]] = []
        # 🔴 Прізвище, розірване переносом через рядок. У вузьких колонках
        # метрик це норма: «…Teodor Sikor» / «ski z odnodworką»
        # (костел ф.685, 1847, єдиний підтверджений латинський хіт роду).
        # Цілого слова в тексті не існує, тому пошук по повній формі мовчить
        # при будь-якій якості HTR — 43-50 балів проти порогу 78.
        #
        # 🔴🔴 вікно, А не сусідній рядок (2026-07-29). Сегментація табличного
        # бланку зшиває колонки в один рядок, тож половинки прізвища
        # розповзаються: на еталоні 685-3-106_0273 «Dolsz» стоїть у рядку 31,
        # а «czynski» — аж у 33. Склейка лише з попереднім рядком той запис
        # пропускала (перевірено на бойовому виводі всіх версій Скриби).
        # ⚠ Далекі склейки суворіші за сусідню. Через рядок-два половинки
        # злітаються вже не за законом переносу, а випадково, тож уламок в
        # одну-дві літери («d» + «Jaroszynkim») дає хибний бал на самому лише
        # сусідньому слові. Для back≥2 вимагаємо, щоб обидві частини були
        # осмислені; сусідній рядок лишається як був — там 39% знахідок.
        for back, pt in enumerate(reversed(prev_toks), 1):
            if not toks or len(pt) + len(toks[0]) < 7:
                continue
            if back >= 2 and (len(pt) < 3 or len(toks[0]) < 3):
                continue
            # 🔴 …і не склеюємо два ПОВНИХ слова через рядок: це вже не перенос,
            # а хімера, яка бере поріг `partial_ratio` самою довжиною хвоста й
            # дістає бал вікна на голову, якої в збігу немає. Заміряно: знімає
            # 18% кандидатів і 10 сторінок шуму, не втрачаючи жодного аркуша
            # роду з еталона (`WHOLE_WORD`).
            if back >= 2 and len(pt) >= WHOLE_WORD and len(toks[0]) >= WHOLE_WORD:
                continue
            sep = "-" if back == 1 else f"-{back}⏎"
            cands.append((f"{pt}{sep}{toks[0]}", _norm(pt + toks[0]),
                          f"{KIND_GLUE}{back}"))
        for i, t in enumerate(toks):
            if len(t) >= 4:
                cands.append((t, _norm(t), KIND_TOKEN))
            # прізвище часто розірване пробілом («Lubkow skiego») — клеїмо пару
            if i + 1 < len(toks) and len(t) + len(toks[i + 1]) >= 6:
                pair = t + toks[i + 1]
                cands.append((f"{t} {toks[i + 1]}", _norm(pair), KIND_PAIR))
            # Kraken на невідомих довгих словах іноді рве їх на 3 фрагменти
            # («Siko rski» замість «Sikorski») — пара тоді все ще
            # шум (найкращий склеєний уламок ~65-70), лише трійка виявляє
            # слово. Гард на довжину кожного фрагмента — інакше комбінаторно
            # клеїмо випадкові сусідні слова нормальної прози.
            if (
                i + 2 < len(toks)
                and len(t) <= 8 and len(toks[i + 1]) <= 8 and len(toks[i + 2]) <= 8
                and len(t) + len(toks[i + 1]) + len(toks[i + 2]) >= 9
            ):
                triple = t + toks[i + 1] + toks[i + 2]
                cands.append((f"{t} {toks[i + 1]} {toks[i + 2]}", _norm(triple),
                              KIND_TRIPLE))
        if toks:
            prev_toks.append(toks[-1])
            del prev_toks[:-LINE_BREAK_WINDOW]
        if cands:
            yield ln_no, raw, cands


def search(q: str, name: str | None = None, thresh: int = 78,
           limit: int = 200, context: int = 0, *,
           given: bool = True, folk: bool = False,
           rank: bool = True, profile: bool = True,
           anchors: bool = False) -> dict[str, Any]:
    """Fuzzy-пошук по текстах прогонів. `name=None` — по всіх справах.

    `context` — скільки рядків сусідства додати до кожного хіта (0 = без них).
    Вікно розсувне (`line_window`) і, якщо у справи є прогін другим рушієм,
    несе ще й його читання того самого рядка: збіг голосів означає надійне
    читання, розбіжність — що ознака в пікселях і судити має око.

    `given` — розкривати гніздо написань імені з довідника (`records.names`).
    `folk` — додавати ще й побутових двійників; за замовчуванням вимкнено, бо
    зв'язок там біографічний, а не орфографічний.
    `rank` — опускати вниз те, що профіль пояснює чужим словом (`search.rank`).
    Саме опускати: жоден кандидат не зникає.
    `profile` — додавати написання прізвища з профілю простору, коли запит саме
    про це прізвище.
    `anchors` — ще й канал імен: рядки, де ім'я й по батькові роду стоять поруч.
    Окремим списком, не домішується до прізвищних хітів.

    🔴 Контекст рахується лише для показаних хітів, після зрізу за `limit`.
    Інакше на справі з тисячею збігів кожен пошук читав би тисячу сторінок
    заради вікон, які ніхто не побачить.
    """
    stems = [_norm(w) for w in _TOKEN_RE.findall(q) if len(w) >= 3]
    stems = [s for s in stems if len(s) >= 3]
    if not stems:
        return {"hits": [], "cases": 0, "error": "закороткий запит"}
    # 🔴 Набране людиною лишається окремим числом. Знаменник «шукали ось цим»
    # після розширення перестає збігатися з тим, що набрали, і без обох чисел
    # нуль читається не про те: «не знайшлось по п'яти написаннях» і «не
    # знайшлось по одному» — різні відповіді.
    asked = list(stems)
    origin: dict[str, str] = dict.fromkeys(stems, NAMES.ORIGIN_QUERY)
    if given or folk:
        stems, origin = NAMES.expand_stems(stems, given=given, folk=folk)
    # 🔴 Написання прізвища з профілю простору. Профіль знає 10-13 форм, людина
    # набирає одну; доти жодна з решти в пошук не потрапляла. Два з семи
    # реальних спотворень декоду переходять поріг ЛИШЕ завдяки їм.
    whose = ""
    if profile:
        from nyshporka.core import profile as PROF

        forms, whose = PROF.forms_for_query(q)
        if forms:
            stems, origin = NAMES.add_stems(stems, origin, forms,
                                            NAMES.ORIGIN_PROFILE)
    from nyshporka.search import decode as D

    scope = runs_for_scope(name or "")
    rows = scope["rows"]
    names = [r["name"] for r in rows]
    # 🔴 Індекс однієї справи збирається на місці — це секунди, і людина
    # просила саме цю справу. Індекс усього корпусу — чверть години, і робити
    # це мовчки всередині запиту означає повісити застосунок.
    budget = len(names) if scope["kind"] != "all" else D.INLINE_BUILD
    # 🔴 Стор, а не gzip-індекс, щойно він покриває область не гірше. Заміряно
    # 07.09.2026: той самий свіп по одній справі — 0.6 с проти 4 с, по
    # корпусу — секунди проти хвилини, з якої 52 с ішло на розпакування.
    # Фолбек лишається на час, поки стор доганяє корпус: інакше перший день
    # після появи стору пошук по всьому прочитаному показував би нуль зі
    # знаменником «1294 прогони поза пошуком».
    from nyshporka.search import store as ST

    backend = "gzip"
    backend_why = ""
    if ST.exists():
        try:
            st_stale = ST.stale_count(names)
            gz_stale = sum(1 for n in names if not D.is_fresh(n))
            if st_stale <= budget or st_stale <= gz_stale:
                backend = "store"
        except RuntimeError as exc:
            # Стор чужої схеми: не зносити, не падати — gzip і сказати вголос.
            backend_why = str(exc)
    dropped: list[str] = []
    if backend == "store":
        # 🔴 Фрагменти стема в стор не йдуть. Профіль тримає голови й хвости
        # переносу («doli-», «scinskii», «doli- scinskii») для каналу, що клеїв
        # їх сам; стор уже має склейки серед кандидатів, а хвіст «щинскій» як
        # самостійний стем збігається на 100 з кожним «-щинскій» у книзі:
        # заміряно на 230-1-13 — 2113 хітів, верхівка суцільно чужа.
        # Суфіксне правило — лише для написань із профілю (голови й хвости
        # переносу); набране й гніздо імен з довідника не чіпаються: «Ганна»
        # розкривалась у «anna», і саме її суфіксне правило викидало.
        stems, dropped = ST.whole_stems(
            stems, keep=[s for s in stems if origin.get(s) != NAMES.ORIGIN_PROFILE])
        try:
            got = ST.sweep(stems, names, thresh=thresh, build_budget=budget)
        except RuntimeError as exc:
            backend, backend_why = "gzip", str(exc)
            got = D.sweep(stems, names, thresh=thresh, build_budget=budget)
    else:
        got = D.sweep(stems, names, thresh=thresh, build_budget=budget)
    raw_hits = got["hits"]
    # 🔴 Ранг ставиться ДО зрізу за `limit`. Інакше службовий формуляр і сусідній
    # рід лишались би на верхівці, а знахідка — за межею показаного: замір
    # приватного конвеєра дає 60 сильних кандидатів, у яких три верхні місця за
    # балом займає рубрика книги, а самого роду немає жодного.
    rul = RANK.rules() if rank else RANK.EMPTY
    ranked = RANK.mark(raw_hits, rul)
    raw_hits.sort(key=RANK.sort_key)
    shown = raw_hits[:limit]

    # Рушій кожного прогону — щоб у результатах було видно, хто знайшов. Це і є
    # робочий бік симбіозу: у тримовній справі один аркуш ловить Скриба, сусідній
    # Писар, і за міткою одразу ясно, кому з них вірити на цьому письмі.
    #
    # ⚠ Читається лише для показаних: мета кожного прогону — окремий файл, і на
    # корпусі це тисяча читань заради поля, яке побачать у двадцяти рядках.
    # 🔴 Справа хіта — з переліку прогонів, а не з імені теки. Ім'я прогону не є
    # адресою справи, і доти, доки хіт не ніс ключа, кожен споживач добудовував
    # його сам: гортач слав у облік `h.name` і діставав нормативну відмову, а
    # колонка «шифра» в таблиці показувала назву теки. Ключ народжується тут
    # один раз — і фікції зникають в обох місцях одразу.
    by_run = {r["name"]: r for r in rows}
    engines: dict[str, tuple[str, str, str, list[str]]] = {}
    for h in shown:
        nm = h["name"]
        if nm not in engines:
            m = load_meta(nm) or {}
            engines[nm] = (run_engine(m), m.get("script") or "",
                           run_engine_id(m), run_engine_ids(m))
        eng, scr, eid, eids = engines[nm]
        row = by_run.get(nm) or {}
        h["case_key"] = (row.get("case_key") or "").strip()
        h["shifra"] = row.get("shifra") or ""
        # 🔴 всі рушії прогону, а не один. Прогін двома голосами пише обидві
        # моделі одним полем через «+», і `run_engine_id` віддає з них перший:
        # на теці Дяка мітка виходила «pysar», тобто читання приписувалось не
        # тій моделі. Канал «два голоси» ключується саме цією міткою, тож
        # помилка тут тиха й перевертає висновок про надійність рядка.
        h["engine_ids"] = eids
        # 🔴 два номери того самого рядка, і це не дублювання.
        # `line_no` — номер для людини, з одиниці, як у редакторі; його
        # показує таблиця хітів. `line_index` — індекс рамки в
        # `.lines.json`, з нуля, і саме його чекає гортач.
        #
        # Доти, доки поле було одне, кнопка 👁 у пошуку передавала
        # людський номер туди, де ждали індекс, — і показувала сусідній
        # рядок. Гірше за відсутність кнопки: вона зроблена рівно заради
        # «виявити ≠ перевірити», а віддавала оку не той рядок, який
        # знайшла машина, з тим самим виглядом правильної відповіді.
        h["engine"], h["script"], h["engine_id"] = eng, scr, eid
        # 🔴 Звідки взявся стем, яким знайдено. Хіт по набраному й хіт по
        # двійнику з довідника виглядають однаково, а важать по-різному: другий
        # ще треба звірити з тим, що людина шукала саме цю особу.
        h["stem_origin"] = origin.get(str(h.get("stem") or ""),
                                      NAMES.ORIGIN_QUERY)
    _resolve(shown)
    if context:
        _add_context(shown, side=context)
    phantom_n, blind = mark_phantoms(shown)
    # 🧾 Слід свіпу — щоб наступна сесія знала, чим справу вже шукали. Пишеться
    # лише в межах справи: свіп по корпусу не належить жодній із них.
    before: list[dict[str, Any]] = []
    stale_before: list[dict[str, Any]] = []
    if scope["key"]:
        from nyshporka.search import trace as TRACE

        models = [m for r in rows for m in (r.get("engine_ids") or [])]
        # 🔴 Читаємо ДО запису: інакше «чим шукали раніше» містило б цей самий
        # запит, і кожен свіп підтверджував би сам себе.
        before = TRACE.of(scope["key"])
        stale_before = TRACE.stale(scope["key"], models)
        TRACE.note(scope["key"], q=q, thresh=thresh, hits=len(raw_hits),
                   pages=unique_pages(rows), models=models,
                   channels=["surname"] + (["anchor"] if anchors else []))
    # ⚓ Другий канал іде ОКРЕМИМ списком, а не домішується до першого. Прізвищний
    # нуль мусить лишитись прізвищним нулем: «не знайшлось прізвища, зате поруч
    # стоять наші імена» — це дві різні відповіді, і зливати їх означає втратити
    # обидві. Так само рахує їх і приватний конвеєр.
    anchor: dict[str, Any] = {"on": bool(anchors)}
    if anchors:
        from nyshporka.search import anchors as A

        y1, y2 = case_years(scope["key"]) if scope["key"] else (None, None)
        keys = A.keys(y1, y2)
        found = [] if keys.empty else anchor_hits(rows, keys)
        anchor.update({"hits": found[:limit], "total": len(found),
                       "given": list(keys.given), "patronymic": list(keys.patronymic),
                       "people": keys.people, "undated": keys.undated,
                       "years": list(keys.years) if keys.years else []})
    return {"hits": shown, "total": len(raw_hits), "cases": got["scanned"],
            "stems": stems, "stems_asked": asked,
            "stems_added": [s for s in stems if origin.get(s) != NAMES.ORIGIN_QUERY],
            "folk": bool(folk), "thresh": thresh,
            # Скільки хітів опущено вниз і за що. Числа їдуть у знаменник:
            # «нічого не позначено» і «правил немає» — різні відповіді.
            "ranked": ranked, "rank_rules": len(rul.rank_down),
            "rank_confusers": len(rul.confusers),
            "rank_dead": list(rul.dead), "rank_broken": list(rul.broken),
            # Чиї написання підмішано. Порожньо — профіль не впізнав запит
            # своїм, і це теж відповідь: шукали лише набраним.
            "profile_of": whose, "anchor": anchor,
            # Чим цю справу вже шукали. `stale` — записи іншими моделями: вони
            # виглядають як зроблена робота, а зроблені гіршим рушієм.
            "searched_before": before, "searched_stale": stale_before,
            # 🔴 Знаменник їде звідси ж, із тих самих прогонів, у яких шукали.
            # Порахований окремо, він щоразу розходився з чисельником —
            # див. `runs_for_scope`.
            "pages": unique_pages(rows), "runs_scoped": len(rows),
            "scope": scope["kind"], "scope_key": scope["key"],
            "scope_shifra": scope["shifra"],
            # 🔴 Знаменник індексу, а не лише прогонів. Прочесане й наявне —
            # різні числа доти, доки індекс не догнав корпус, і нуль на
            # частковому індексі означає зовсім не те, що нуль на повному.
            "runs_total": got["runs"], "unindexed": got["unindexed"],
            # Чим прочесано: стор чи gzip-індекс. Нуль на частковому сторі й
            # нуль на повному gzip-індексі — різні відповіді.
            "backend": backend, "backend_why": backend_why,
            # Скільки прогонів узято з кешу свіпів стору, скільки пораховано
            # зараз; чи кандидати стору зроблені чинними правилами.
            "cache": {"runs": int(got.get("cached") or 0),
                      "computed": int(got.get("computed") or 0)} if backend == "store" else None,
            "rules_stale": bool(got.get("rules_stale")),
            # Які написання профілю не пішли в стор і чому — див. `whole_stems`.
            "stems_dropped": dropped,
            # Сторінки ВСІХ хітів понад порогом, а не лише показаних: самоперевірці
            # й журналу потрібен саме цей знаменник, і без нього `find` робив
            # другий повний пошук лише заради нього.
            "hit_pages": sorted({(h["name"], h["page"]) for h in raw_hits}),
            "phantom": phantom_n, "phantom_blind": blind}


def _resolve(hits: list[dict[str, Any]]) -> None:
    """Дописати хітам сам рядок і слово, яке збіглося.

    🔴 Індекс тримає лише нормалізовані форми — саме тому він у двадцять разів
    менший за текст. Показане слово відновлюється тут, і лише для тих кількох
    рядків, які людина побачить: перебудувати кандидатів однієї сторінки
    коштує мілісекунди, а зберігати їх для всіх означало б утричі роздути
    індекс заради даних, що майже ніколи не читаються.

    ⚠ Кандидати рахує `page_candidates` — та сама функція, що будувала індекс.
    Друга копія правил склейки розійшлася б із першою тихо, і пошук почав би
    показувати не те слово, яким знайшов.
    """
    cands_of: dict[tuple[str, str], dict[int, list[tuple[str, str]]]] = {}
    text_of: dict[tuple[str, str], list[str]] = {}
    for h in hits:
        key = (h["name"], h["page"])
        if key not in cands_of:
            got = read_page_text(h["name"], h["page"]) or {}
            text_of[key] = list(got.get("lines") or [])
            cands_of[key] = {ln: cands for ln, _raw, cands
                             in page_candidates(text_of[key])}
        want = h.pop("norm", "")
        cands = cands_of[key].get(h["line_no"]) or []
        h["matched"] = next((w for w, n in cands if n == want), want)
        lines = text_of[key]
        idx = h["line_no"] - 1
        h["line"] = lines[idx] if 0 <= idx < len(lines) else ""


def case_years(key: str) -> tuple[int | None, int | None]:
    """Роки справи: спершу реєстр, далі — те, що занесло око.

    🔴 Вікно якорів будується саме з них, тож джерело мусить бути названим. У
    реєстрі роки приходять із каталогу й сайдкарів, у сховищі сторінок — із
    того, що дослідник побачив на аркуші; друге точніше, але буває порожнім.

    ⚠ Числа-сміття відсіюються діапазоном: у полі «роки» аркуша трапляється
    все, що схоже на рік, включно з номером двору й сучасною датою.
    """
    lo: list[int] = []
    hi: list[int] = []
    with contextlib.suppress(Exception):
        from nyshporka.cases import db as CDB

        for row in CDB.query_rows(q=key, limit=5):
            if str(row.get("key") or "") != key:
                continue
            for fld, box in (("year_from", lo), ("year_to", hi)):
                got = row.get(fld)
                if isinstance(got, int) and 1400 <= got <= 2100:
                    box.append(got)
    with contextlib.suppress(Exception):
        from nyshporka.pagestore import store as PS

        case = PS.load_case(PS.resolve_case(key))
        if case is not None:
            seen = [y for note in case.pages.values()
                    for y in (note.years or []) if 1400 <= int(y) <= 2100]
            for rec in case.records:
                got = re.search(r"(1[4-9]\d\d|20\d\d)",
                                str(getattr(rec.date, "value", "") or ""))
                if got:
                    seen.append(int(got.group(1)))
            if seen:
                lo.append(min(seen))
                hi.append(max(seen))
    if not lo and not hi:
        return None, None
    return (min(lo) if lo else None), (max(hi) if hi else None)


def anchor_hits(rows: list[dict[str, Any]], k: Any) -> list[dict[str, Any]]:
    """Рядки, де ім'я й по батькові роду стоять поруч.

    ⚠ Читає ТЕКСТ прогонів, а не стиснений індекс: індекс тримає самі лише
    нормалізовані кандидати, а тут потрібен порядок токенів у рядку. Тому канал
    і живе в межах справи — на корпусі це було б перечитування всього декоду.
    """
    from nyshporka.search import anchors as A
    from nyshporka.search import store as ST

    out: list[dict[str, Any]] = []
    for row in rows:
        name = row["name"]
        # 🔴 Текст береться зі стору, коли він свіжий: обхід `.txt` теки прогону
        # коштував ~9 с на справу й суперечив усьому задуму стору.
        lines = list(_lines_for_anchors(name, ST))
        for i, t, nxt in A.scan_many([raw for _pg, _no, raw in lines], k):
            page, ln_no, raw = lines[i]
            pair = (t, nxt)
            out.append({"name": name, "page": page, "line_no": ln_no,
                        "line_index": ln_no - 1,
                        # 🔴 Канал названий у самому хіті. Знахідка за іменами
                        # важить інакше, ніж за прізвищем: вона каже «тут наші
                        # люди», а не «тут наше прізвище».
                        "channel": "anchor", "stem": " ".join(pair),
                        "stem_origin": "anchor", "matched": " ".join(pair),
                        "line": raw,
                        "case_key": row.get("case_key") or "",
                        "shifra": row.get("shifra") or ""})
    return out


def _lines_for_anchors(name: str, ST: Any) -> Iterator[tuple[str, int, str]]:
    """Рядки прогону для каналу якорів: зі стору, інакше з файлів."""
    if ST.exists() and ST.is_fresh(name):
        conn = ST.connect(readonly=True)
        try:
            rid = conn.execute("select id from runs where run=?", (name,)).fetchone()
            if rid:
                for pid, page in conn.execute(
                        "select id, page from pages where run_id=? order by id", (rid[0],)):
                    for i, raw in enumerate(ST._raw_lines(conn, int(pid)), 1):
                        if raw.strip():
                            yield str(page), i, raw
                return
        finally:
            conn.close()
    for page, ln_no, raw, _cands in _case_index(name):
        yield page, ln_no, raw


def mark_phantoms(hits: list[dict[str, Any]]) -> tuple[int, float]:
    """🪤 Позначити хіти, що стоять на сторінках без чорнила. НЕ прибирати.

    🔴 Позначка, а не фільтр, і це рішення. Той самий детектор спрацьовує на
    роздільному аркуші метричної книги, де три рядки великого письма лежать
    поверх водяного знака: рядки там зайві, а текст цінний. Викинувши сторінку,
    ми відібрали б у ока рівно те, заради чого воно й дивиться.

    ⚠ Рахуємо тільки для показаних хітів і по одному разу на прогін: детектор
    читає всю мету прогону, і на видачі з п'ятисот справ це були б п'ятсот
    зайвих читань заради позначки на десятку рядків.

    Повертає `(скільки позначено, найгірший `has_contrast`)`. Друге число —
    чесність самого детектора: на старих метах поля `contrast` немає, працює
    лише гілка `enhanced`, і детектор мовчки слабшає. Це треба друкувати, а не
    ховати: інакше «фантомів немає» читається як «сторінки чисті», хоч означає
    «нічим було перевірити».
    """
    cache: dict[str, dict[str, Any]] = {}
    marked, blind = 0, 1.0
    for h in hits:
        nm = h.get("name") or ""
        if nm not in cache:
            try:
                cache[nm] = phantom_pages(nm)
            except Exception:
                cache[nm] = {"pages": {}, "has_contrast": 1.0}
        rep = cache[nm]
        blind = min(blind, float(rep.get("has_contrast") or 0.0))
        info = (rep.get("pages") or {}).get(h.get("page") or "")
        if info:
            h["phantom"] = True
            h["phantom_why"] = info.get("why") or ""
            marked += 1
    return marked, round(blind, 2) if cache else 1.0


def _add_context(hits: list[dict[str, Any]], *, side: int) -> None:
    """Дописати кожному хіту вікно сусідів і читання другого голосу.

    Побратим шукається раз на прогін, а сторінка другого голосу читається раз
    на сторінку: на верхівці пошуку хіти йдуть купками по кілька з одного
    аркуша, і без кешу та сама сторінка перечитувалась би щоразу.
    """
    pairs: dict[str, str | None] = {}
    alt_pages: dict[tuple[str, str], list[str]] = {}
    for h in hits:
        nm, page, idx = h["name"], h["page"], h["line_index"]
        win = line_window(nm, page, idx, side=side)
        h["context"] = {"before": win["before"], "after": win["after"]}
        if nm not in pairs:
            pairs[nm] = voice_pair(nm)
        other = pairs[nm]
        if not other:
            continue
        key = (other, page)
        if key not in alt_pages:
            alt_pages[key] = list((read_page_text(other, page) or {}).get("lines") or [])
        alt = alt_pages[key]
        if 0 <= idx < len(alt):
            # 🔴 Рядок другого голосу беремо за тим самим індексом. Це коректно
            # лише тому, що обидва прогони йдуть по спільному кешу сегментації,
            # тобто ділять ті самі рамки рядків. Якби сегментація рахувалась
            # заново, індекси розійшлись би — і «другий голос» показував би
            # сусідній рядок, що гірше за його відсутність.
            h["alt"] = {"run": other, "line": alt[idx]}
