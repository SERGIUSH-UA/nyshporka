"""🖋 Read-сторона HTR-прогонів — тексти справ, розпізнані Kraken'ом.

Пише їх раннер (`nyshporka.htr.runner`, окремий інтерпретатор рушіїв; запуск —
`nysh read`) у `reports/htr/<name>/`: `<stem>.txt` посторінково +
`_htr_meta.json` (модель, per-page орієнтація/conf).
Цей модуль лише ЧИТАЄ — консоль (роутер htr) віддає тексти, картинки і fuzzy-пошук.

CER Kraken на скорописі XVIII-XIX ст. ~25-35%: «Franciszka Lubkowskiego» →
«Francisrha Lubhoustrio90». Тому пошук — НЕ точний grep, а fuzzy по нормалізованих
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
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from nyshporka.core.workspace import workspace
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
    змінилось лише те, ЗВІДКИ береться перелік: раніше він жив у цій функції й
    тому був невидимий для решти конвеєра.

    Це РОЗШИРЕННЯ зони гарда, тому корені задаються явним списком, а не
    «будь-який абсолютний шлях»: у в'ювері сторінок шлях приходить із запиту.
    """
    return workspace().case_roots()


def under_raw(path: str | Path) -> Path | None:
    """Абсолютний шлях справи, якщо він під дозволеним коренем — інакше None.

    Корені: `data/raw` + архівні (див. `_case_roots`). Ім'я лишилось історичним —
    функція є гардом шляху в трьох місцях (enqueue прогону, читання сторінок
    в'ювером, `decode_hits`).

    🔴 Чому НЕ `.resolve()`. Великі фонди лежать на T: і видні в репо через
    junction (`data/raw/dahmo_196/<spr>` → `D:\\архів\\dahmo_196_fs\\<spr>`,
    memory `disk-layout-t-drive-junctions`). `resolve()` розкриває junction, шлях
    стає `T:\\…`, і перевірка «під data/raw» падає — тобто ВЕСЬ ф.196 (35 справ,
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
def _case_dir(name: str) -> Path | None:
    """Тека прогону за іменем — з гардом від traversal у `?name=`."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    d = (HTR_ROOT / name).resolve()
    if d.parent != HTR_ROOT.resolve() or not d.is_dir():
        return None
    return d


def load_meta(name: str) -> dict[str, Any] | None:
    d = _case_dir(name)
    if d is None:
        return None
    try:
        meta = json.loads((d / "_htr_meta.json").read_text(encoding="utf-8"))
        return dict(meta) if isinstance(meta, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


#: Розширення моделі → рушій (дзеркало `scripts/htr_case_run._ENGINE_BY_SUFFIX`;
#: продубльовано, бо той скрипт живе в іншому venv і імпортувати його не можна).
_ENGINE_BY_SUFFIX = {".mlmodel": "kraken", ".pt": "parseq",
                     ".ckpt": "parseq", ".pth": "parseq"}


def run_engine(meta: dict[str, Any]) -> str:
    """Рушій прогону. Мети до 2026-07-30 поля `engine` не мають — вгадуємо з
    розширення імені моделі; воно є в кожній меті, включно з прогонами старого
    `pysar_lines_infer.py`."""
    engine = (meta.get("engine") or "").strip()
    if engine:
        return engine
    model = meta.get("model") or ""
    # CHURRO-прогони (VLM, `scripts/churro_*`) пишуть у `model` назву HF-репо без
    # розширення — без цієї гілки вони лишались би «без рушія», і гард змішування
    # не захищав би їхні теки
    if "churro" in model.lower():
        return "churro"
    return _ENGINE_BY_SUFFIX.get(Path(model).suffix.lower(), "")


#: 🪤 ФАНТОМНІ РЯДКИ — скільки символів на рядок мусить лишитись, щоб сторінка
#: не вважалась підозрілою. Частка від МЕДІАНИ САМОЇ СПРАВИ, а не абсолютне
#: число: почерк і формуляр у кожній книзі свої (медіана 25.6 симв/рядок на
#: ДАВіО 474-1-174, 7.4 на ф.726-1-7, 43.9 на ф.792-1-5).
PHANTOM_FRAC = 0.30
#: Нижче цього рядків сторінку не судимо: коротка сторінка — це нормально
#: (титулка, роздільний аркуш). Фантом упізнається саме поєднанням БАГАТО
#: рядків + МАЛО чорнила. Замір на 474-1-174: кадр 00001 (титулка, 15 рядків /
#: 101 символ) відсікається цією умовою і хибнопозитивом не стає.
PHANTOM_MIN_LINES = 25
#: Другий бік умови — ПРИЧИНА. Фантоми родяться там, де сегментація прийняла за
#: рядки не чорнило: просвічування зі звороту на тонкому папері, водяний знак,
#: вотермарк оцифрувальника. Такі сторінки або мають низький контраст, або їх
#: підняв `--enhance auto` (він і підсилює просвічене до рівня сигналу).
PHANTOM_CONTRAST = 40.0


def phantom_pages(name: str, frac: float = PHANTOM_FRAC,
                  min_lines: int = PHANTOM_MIN_LINES,
                  contrast_max: float = PHANTOM_CONTRAST) -> dict[str, Any]:
    """🪤 Сторінки, де кількість рядків НЕ підкріплена чорнилом.

    Навіщо. Сегментація рахує рядки за скелетом темних смуг, а не за текстом,
    тож на аркуші з просвічуванням зі звороту вона чесно віддає 75-117 «рядків»
    там, де чорнилом написано два. Розпізнавач їх слухняно декодує — виходить
    осмислена на вигляд каша, і вона потрапляє в той самий індекс, що й справжній
    текст. Далі фаззі-пошук знаходить у ній прізвище: на ДАВіО 474-1-174 кадр
    00176 дав `htr_clan_scan` найсильніший хіт роду за всю справу («Долщикъ
    Василія», root 90.9) — на аркуші, де в чорнилі є лише «Копію настоящаго
    вводнаго листа получилъ…» і латинський підпис. Такий хіт нічим не
    відрізняється від справжнього, поки не подивишся на скан.

    🔴 Це НЕ «сторінка-сміття». На тому самому детекторі спрацьовує роздільний
    аркуш метричної книги костелу (685-1-410 кадр 0245: «Мястковской церкви за
    септембрь 1800 года… О умершихъ» — три рядки великого письма поверх
    водяного знака-дерева і вотермарку сайту, 50 рядків / 93 символи). Текст
    там цінний, зайві лише рядки. Тому викликач має ПОЗНАЧАТИ хіти звідси як
    такі, що потребують ока, а не мовчки викидати сторінку.

    Ознака рахується з мети прогону, без зображень: `lines`, `chars`,
    `contrast`, `enhanced`. Три умови разом (кожна поодинці шумить):
      1. `lines >= min_lines` — інакше це просто коротка сторінка;
      2. `chars/lines < frac × медіани справи` — рядки є, чорнила нема;
      3. контраст нижчий за `contrast_max` АБО сторінку піднімав `--enhance`
         — тобто відома причина, чому сегментація побачила зайве.

    Замір по 79 наявних прогонах: спрацьовує на 13, максимум 15% сторінок
    (468-1-495, 20 сторінок) і 10.6% (костел 685-1-410), на великих справах —
    частки відсотка (474-1-174: 6 з 364; ф.792-1-16: 1 з 3275). Тобто фільтр
    консервативний і щільні формуляри не чистить.

    ⚠ `has_contrast` < 1.0 означає, що частина мети старіша за поле `contrast`
    (з'явилось разом із `--enhance auto`); для тих сторінок працює лише гілка
    `enhanced`, і детектор мовчки СЛАБШАЄ. Друкувати це число, а не ховати.

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


def list_cases() -> list[dict[str, Any]]:
    """Прогони з reports/htr/* — для списку в'ювера. Назва справи — з бібліотеки."""
    out: list[dict[str, Any]] = []
    if not HTR_ROOT.is_dir():
        return out
    try:
        from nyshporka.library import describe_case
    except Exception:  # бібліотека не критична для списку
        def describe_case(_p: str) -> dict[str, Any] | None:  # type: ignore[misc]
            return None
    for meta_path in sorted(HTR_ROOT.glob("*/_htr_meta.json")):
        name = meta_path.parent.name
        meta = load_meta(name)
        if not meta:
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
            "pages_done": len(meta.get("pages") or {}),
            "failed": len(meta.get("failed") or []),
            "done": bool(meta.get("done")),
            "model": meta.get("model") or "",
            # рушій і письмо прогону: на одну справу їх буває кілька (латинку читає
            # Скриба, кирилицю Писар), і без цього не сказати, ЧИМ прочитана сторінка
            "engine": run_engine(meta),
            "script": meta.get("script") or "",
            "updated": meta.get("updated") or "",
        })
    out.sort(key=lambda c: c["updated"], reverse=True)
    return out


def runs_by_case_dir() -> dict[str, list[dict[str, Any]]]:
    """Мапа resolved-case_dir → прогони цієї теки. Для масового збагачення пікера
    файлового браузера (десятки тек за один запит) — щоб НЕ пере-читувати всі
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
    enqueue) — щоб пікер показав «прогін уже був» ще ДО постановки в чергу."""
    case = (case or "").strip()
    if not case:
        return []
    case_dir = Path(os.path.abspath(
        Path(case) if Path(case).is_absolute() else ROOT / case))
    return runs_by_case_dir().get(str(case_dir), [])


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
            "engine": run_engine(meta), "script": meta.get("script") or "",
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
    """🖼 Геометрія рядків сторінки — щоб в'ювер міг показати, ЗВІДКИ рядок тексту.

    Джерело — `<стем>.lines.json`, який пише прогін: `boxes` (AABB, ним ріжуть
    кропи) і `polys` (полігон рядка — рядок скоропису йде похило, тож його bbox
    накриває сусідів; підсвічувати треба фігуру). Індекс рамки == номер рядка в
    `.txt`, вирівнювання гарантує сам прогін.

    Рамки лежать у координатах ПОВЕРНУТОГО зображення — того самого, яким
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
    boxes = data.get("boxes") or []
    if not boxes:
        return {"page": page, "has": False}
    size = data.get("size")
    if not size:
        got = resolve_scan(name, page)
        if got is not None:
            src, orient = got
            wh = _image_size(src)
            if wh:
                size = [wh[1], wh[0]] if orient in (90, 270) else wh
    if not size:
        # 🔴 Рамки Є, але масштаб невідомий — і це РІЗНІ речі, які досі
        # виглядали однаково. Так буває саме на PDF-прогонах: старий
        # `.lines.json` без `size`, а скану, з якого можна доміряти, на цій
        # машині немає (кадри жили на орендованому боксі). Накласти рамку на
        # рендер тут нічим — але сказати «рамок немає» означає збрехати про
        # причину, а причина ЛІКУЄТЬСЯ по-різному: рамки додає перепрогін,
        # масштаб — поява самого скану.
        return {"page": page, "has": False, "boxes_known": True,
                "why": "прогін не записав розміру зображення, тож рамку рядка "
                       "накласти нічим — показано всю сторінку (рамки в цьому "
                       "прогоні є, бракує лише масштабу)"}
    polys = data.get("polys") or None
    if polys is not None and len(polys) != len(boxes):
        polys = None            # довжини розійшлись — краще прямокутник, ніж не той рядок
    return {"page": page, "has": True, "size": size,
            "boxes": boxes, "polys": polys}


def _image_size(path: Path) -> list[int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return [int(im.width), int(im.height)]
    except (ImportError, OSError):
        return None


def resolve_scan(name: str, page: str) -> tuple[Path, int] | None:
    """Оригінальний скан сторінки + кут повороту, яким користувався OCR.

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
            return target, orient

    # 🔴 Фолбек через реєстр справ, і він ПОДВОЮЄ зону видимості гортача.
    # Хмарний прогін пише в мету шлях ОРЕНДОВАНОГО БОКСА
    # (`/tmp/htrcase/pages_dl`) або стейджингу — теки, якої на цій машині немає
    # й не було. Текст такого прогону є, рамки рядків є, а подивитись оком
    # нічим: `case_dir` веде в нікуди. Резолвер саме для цього й існує — він
    # зводить ім'я прогону до справи бібліотеки, а в неї шлях уже справжній.
    #
    # Заміряно 2026-08-15 на 478 прогонах: скан лежить там, де каже мета, у
    # 161; ще 165 знаходяться цим фолбеком (34% → 68%). Решта 150 — справи, що
    # лежать PDF-ом: прогін читав РЕНДЕР, якого на цій машині ніколи не було,
    # і вгадувати відповідність «кадр → сторінка PDF» тут не можна — показати
    # не той аркуш гірше, ніж не показати нічого.
    for cand in _case_dirs_via_registry(name):
        target = Path(os.path.abspath(cand / page))
        if target.parent == cand and target.is_file():
            return target, orient
    return None


def _case_dirs_via_registry(run: str) -> list[Path]:
    """Теки, де МОЖУТЬ лежати скани цього прогону, за реєстром справ.

    Справа часто лежить у кількох теках — оригінали, зменшені копії для хмари,
    посторінковий рендер PDF, — і сторінка з тим самим іменем є не в кожній.
    Тому повертається перелік, а не одна тека.
    """
    try:
        from nyshporka.cases.resolve import LibraryIndex, resolve_run
        from nyshporka.library import load_library
    except Exception:
        return []
    try:
        link = resolve_run(run)
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

#: Скільки змістовних символів мусить набратись у контексті з кожного боку.
#: 🔴 Огризок контекстом НЕ вважається: сусідній рядок «на», «и», «3» не пояснює
#: нічого, тож вікно розсувається далі, доки не набереться цієї міри. Без такого
#: розсування «контекст» на щільних формулярах виявляється порожнім рівно там,
#: де він найпотрібніший — між колонками таблиці.
MIN_CTX_CHARS = 24
#: Стеля розсування, щоб вікно не з'їло півсторінки на аркуші з обривками.
MAX_CTX_LINES = 4


def line_window(name: str, page: str, line_index: int, *, side: int = 1,
                min_chars: int = MIN_CTX_CHARS) -> dict[str, Any]:
    """Рядок разом із сусідами — РОЗСУВНЕ вікно, а не фіксовані ±N.

    🔴 Навіщо вікно, якщо є сам рядок. Рядок-хіт не розрізняє прізвищ зі
    спільним коренем, а в одній парафії їх буває кілька; заміряно на метриках
    одного села: 78 кандидатів верхівки розклались на три різні роди зі
    спільним коренем плюс причт — і за самим рядком вони зливаються в купу
    однаково правдоподібних хітів.

    Розрізняє їх СУСІДСТВО: перенесена половина слова читається лише разом із
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
    """Прогін-побратим тієї самої справи, зроблений ІНШИМ рушієм.

    🔴 Два голоси на одному рядку — не надлишок. Там, де вони збіглись, читання
    надійне; де розійшлись — це сигнал, а не шум: рушій із мовною моделлю
    підставляє правдоподібне слово, а CTC калічить локально, зберігаючи корінь.
    Саме розбіжність і показує, що ознака в пікселях, а отже суддя — око.
    """
    meta = load_meta(name) or {}
    mine = run_engine(meta)
    key = meta.get("case_key")
    base = str(meta.get("case_dir") or "")
    for other in list_cases():
        nm = other.get("name") if isinstance(other, dict) else str(other)
        if not nm or nm == name:
            continue
        om = load_meta(nm) or {}
        same = (key and om.get("case_key") == key) or (base and om.get("case_dir") == base)
        if same and run_engine(om) != mine:
            return str(nm)
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
        prev_toks: list[str] = []   # хвости попередніх рядків — для переносів
        for ln_no, raw in enumerate(txt.read_text(encoding="utf-8").splitlines(), 1):
            toks = _TOKEN_RE.findall(raw)
            # ⚠ ОКРЕМИЙ ФІЛЬТР «РЯДКІВ-ОГРИЗКІВ» ТУТ НЕ ПОТРІБЕН — перевірено
            # заміром 2026-07-31, щоб наступний не пішов тим самим хибним
            # шляхом. На порожньому звороті сегментація ріже волокна паперу як
            # рядки, і декод віддає «с / и / св / 1 ; 7 / сащъ». Таких рядків
            # у корпусі 23.7%, і виглядають вони як явне джерело хибних збігів,
            # але кандидатів з них майже не виходить: одиночний токен береться
            # від 4 літер, пара — від 6 сумарно, тож огризок і так відсіюється
            # довжиною. Спроба глушити їх явно прибрала 0.1% кандидатів і
            # НУЛЬ хітів на восьми контрольних запитах (рід, Ярошинські,
            # М'ястківка, Ігнатків, Kowalski, Szczurowski).
            # 🔴 А глушити такий рядок ЦІЛКОМ (разом із хвостом у `prev_toks`)
            # прямо шкідливо: у вузькій колонці перша половина прізвища буває
            # сама в огризку («doi» / «szczynskiego»), і на ф.792-1-16 такий
            # варіант з'їв три склейки роду.
            cands: list[tuple[str, str]] = []
            # 🔴 Прізвище, РОЗІРВАНЕ ПЕРЕНОСОМ через рядок. У вузьких колонках
            # метрик це норма: «…Teodor Sikor» / «ski z odnodworką»
            # (костел ф.685, 1847, єдиний підтверджений латинський хіт роду).
            # Цілого слова в тексті НЕ ІСНУЄ, тому пошук по повній формі мовчить
            # при будь-якій якості HTR — 43-50 балів проти порогу 78.
            #
            # 🔴🔴 ВІКНО, А НЕ СУСІДНІЙ РЯДОК (2026-07-29). Сегментація табличного
            # бланку ЗШИВАЄ КОЛОНКИ в один рядок, тож половинки прізвища
            # розповзаються: на еталоні 685-3-106_0273 «Dolsz» стоїть у рядку 31,
            # а «czynski» — аж у 33. Склейка лише з попереднім рядком той запис
            # ПРОПУСКАЛА (перевірено на бойовому виводі всіх версій Скриби).
            # ⚠ Далекі склейки СУВОРІШІ за сусідню. Через рядок-два половинки
            # злітаються вже не за законом переносу, а випадково, тож уламок в
            # одну-дві літери («d» + «Jaroszynkim») дає хибний бал на самому лише
            # сусідньому слові. Для back≥2 вимагаємо, щоб ОБИДВІ частини були
            # осмислені; сусідній рядок лишається як був — там 39% знахідок.
            for back, pt in enumerate(reversed(prev_toks), 1):
                if not toks or len(pt) + len(toks[0]) < 7:
                    continue
                if back >= 2 and (len(pt) < 3 or len(toks[0]) < 3):
                    continue
                sep = "-" if back == 1 else f"-{back}⏎"
                cands.append((f"{pt}{sep}{toks[0]}", _norm(pt + toks[0])))
            for i, t in enumerate(toks):
                if len(t) >= 4:
                    cands.append((t, _norm(t)))
                # прізвище часто розірване пробілом («Lubkow skiego») — клеїмо пару
                if i + 1 < len(toks) and len(t) + len(toks[i + 1]) >= 6:
                    pair = t + toks[i + 1]
                    cands.append((f"{t} {toks[i + 1]}", _norm(pair)))
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
                    cands.append((f"{t} {toks[i + 1]} {toks[i + 2]}", _norm(triple)))
            if toks:
                prev_toks.append(toks[-1])
                del prev_toks[:-LINE_BREAK_WINDOW]
            if cands:
                index.append((page, ln_no, raw, cands))
    _CACHE[name] = (key, index)
    return index


def search(q: str, name: str | None = None, thresh: int = 78,
           limit: int = 200, context: int = 0) -> dict[str, Any]:
    """Fuzzy-пошук по текстах прогонів. `name=None` — по всіх справах.

    `context` — скільки рядків сусідства додати до кожного хіта (0 = без них).
    Вікно розсувне (`line_window`) і, якщо у справи є прогін другим рушієм,
    несе ще й ЙОГО читання того самого рядка: збіг голосів означає надійне
    читання, розбіжність — що ознака в пікселях і судити має око.

    🔴 Контекст рахується лише для ПОКАЗАНИХ хітів, після зрізу за `limit`.
    Інакше на справі з тисячею збігів кожен пошук читав би тисячу сторінок
    заради вікон, які ніхто не побачить.
    """
    stems = [_norm(w) for w in _TOKEN_RE.findall(q) if len(w) >= 3]
    stems = [s for s in stems if len(s) >= 3]
    if not stems:
        return {"hits": [], "cases": 0, "error": "закороткий запит"}
    names = [name] if name else [c["name"] for c in list_cases()]
    # Рушій кожного прогону — щоб у результатах було видно, ХТО знайшов. Це і є
    # робочий бік симбіозу: у тримовній справі один аркуш ловить Скриба, сусідній
    # Писар, і за міткою одразу ясно, кому з них вірити на цьому письмі.
    engines = {}
    for nm in names:
        m = load_meta(nm) or {}
        engines[nm] = (run_engine(m), m.get("script") or "")
    hits = []
    scanned = 0
    for nm in names:
        index = _case_index(nm)
        if not index:
            continue
        scanned += 1
        for page, ln_no, raw, cands in index:
            # 0.0, а не 0: rapidfuzz рахує у float, і ціле тут лише прикидалось
            # би типом — поріг `thresh` порівнюється саме з цим числом.
            best_sc, best_word = 0.0, ""
            for word, norm in cands:
                for stem in stems:
                    # закороткий токен не може легітимно матчити довгий стем
                    # (інакше 4-літерні уламки типу «Luib» шумлять на 86)
                    if len(norm) < max(4, int(len(stem) * 0.6)):
                        continue
                    sc = fuzz.ratio(norm, stem)
                    if len(norm) >= len(stem):
                        # partial дозволяє відмінкові хвости («-iego», «-ого»)
                        sc = max(sc, fuzz.partial_ratio(norm, stem))
                    if sc > best_sc:
                        best_sc, best_word = sc, word
            if best_sc >= thresh:
                eng, scr = engines.get(nm, ("", ""))
                # 🔴 ДВА номери того самого рядка, і це не дублювання.
                # `line_no` — номер ДЛЯ ЛЮДИНИ, з одиниці, як у редакторі; його
                # показує таблиця хітів. `line_index` — індекс рамки в
                # `.lines.json`, з нуля, і саме його чекає гортач.
                #
                # Доти, доки поле було одне, кнопка 👁 у пошуку передавала
                # людський номер туди, де ждали індекс, — і показувала СУСІДНІЙ
                # рядок. Гірше за відсутність кнопки: вона зроблена рівно заради
                # «виявити ≠ перевірити», а віддавала оку не той рядок, який
                # знайшла машина, з тим самим виглядом правильної відповіді.
                hits.append({"name": nm, "page": page, "line_no": ln_no,
                             "line_index": ln_no - 1,
                             "line": raw, "matched": best_word,
                             "engine": eng, "script": scr,
                             "score": round(best_sc)})
    hits.sort(key=lambda h: -h["score"])
    shown = hits[:limit]
    if context:
        _add_context(shown, side=context)
    return {"hits": shown, "total": len(hits), "cases": scanned,
            "stems": stems, "thresh": thresh}


def _add_context(hits: list[dict[str, Any]], *, side: int) -> None:
    """Дописати кожному хіту вікно сусідів і читання другого голосу.

    Побратим шукається РАЗ на прогін, а сторінка другого голосу читається раз
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
            # 🔴 Рядок другого голосу беремо ЗА ТИМ САМИМ індексом. Це коректно
            # лише тому, що обидва прогони йдуть по спільному кешу сегментації,
            # тобто ділять ті самі рамки рядків. Якби сегментація рахувалась
            # заново, індекси розійшлись би — і «другий голос» показував би
            # сусідній рядок, що гірше за його відсутність.
            h["alt"] = {"run": other, "line": alt[idx]}
