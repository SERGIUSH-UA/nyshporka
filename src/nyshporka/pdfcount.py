"""📄 Сторінки PDF: один лічильник на весь пакет, і він пам'ятає між запусками.

🔴 Число сторінок PDF рахується відкриттям файла. Доти, доки кеш жив лише в
пам'яті процесу (`lru_cache`), кожна перебудова реєстру відкривала КОЖЕН PDF
кожної справи заново. На локальному диску це мілісекунди. Але якщо файл
лежить у теці OneDrive чи iCloud і хмара вже вивантажила його («лише онлайн»,
у macOS `dataless`), відкриття стягує файл цілком. Процес при цьому висить на
0% CPU, бо чекає мережу. Сторонній користувач (macOS, 0.18.1, жовтень 2026):
15 PDF, разом 2,9 ГБ, тягнулися лише заради числа сторінок, яке з минулої
перебудови не змінилось. Через це не заводилась навіть нова справа, ніяк із
цими PDF не пов'язана: `nysh case` перебудовує реєстр. Коли диск заповнений
на 97%, OneDrive вивантажує стягнуте назад за кілька хвилин, тож обхід
«стягнути перед перебудовою» теж не допомагав.

Тому тут два правила:

1. **Число запам'ятовується на диску** (`data/derived/pdf_pages.json`) з
   ключем «шлях + розмір + mtime_ns». Розмір і час зміни дає `stat`, а він у
   хмарного файла вмісту не стягує. Незмінений PDF друга перебудова вже не
   відкриває. Записується одразу після підрахунку, а не наприкінці
   перебудови: за хвилину до кінця OneDrive може встигнути вивантажити файл
   знову, а обірвана перебудова не повинна губити вже пораховане.
2. **Хмарну заглушку без числа в кеші реєстр не відкриває.** Справа отримує
   «знаменник неточний» (та сама позначка, що й для битого PDF), а перебудова
   називає ці файли, каже, скільки ГБ довелося б стягнути, і дає пораду. Явна
   дія над конкретною справою (показати сторінку, розгорнути PDF у кадри)
   файл стягує: людина сама попросила саме його.
"""
from __future__ import annotations

import contextvars
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

FILE = "pdf_pages.json"

#: macOS / iOS: вміст файла в хмарі, на диску лише запис (`ls -lO` → `dataless`).
SF_DATALESS = 0x40000000

#: Windows: заглушка, яка стягує вміст при читанні (OneDrive «лише онлайн»,
#: Files On-Demand), стягує його при відкритті, або файл на зовнішньому сховищі.
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_OFFLINE = 0x00001000
_WIN_CLOUD = (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN
              | FILE_ATTRIBUTE_OFFLINE)


class PdfCountError(RuntimeError):
    """Сторінок не порахувати: файла немає, він битий або нема чим відкрити."""


class CloudPdf(PdfCountError):
    """Файл у хмарі, а відкриття стягнуло б його цілком. Не відкривали."""

    def __init__(self, path: str, size: int) -> None:
        super().__init__(f"PDF у хмарі, сторінок не пораховано: {path}")
        self.path = path
        self.size = size


def cloud_placeholder(st: os.stat_result) -> bool:
    """Чи вміст файла лежить у хмарі, а не на диску.

    Читаються лише атрибути `stat`, тож файл від цього не стягується. На Linux
    таких атрибутів немає, і там відповідь завжди «ні».
    """
    if int(getattr(st, "st_flags", 0) or 0) & SF_DATALESS:
        return True
    return bool(int(getattr(st, "st_file_attributes", 0) or 0) & _WIN_CLOUD)


@dataclass
class Session:
    """Одна перебудова: чи можна стягувати і які заглушки пропущено."""

    fetch: bool = False
    #: шлях → розмір у байтах (стільки довелося б стягнути)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def nbytes(self) -> int:
        return sum(self.skipped.values())


_SESSION: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "nysh_pdfcount_session", default=None)

#: файл кешу → {шлях: [розмір, mtime_ns, сторінок]}. Читається з диска раз на
#: процес; дописи йдуть і сюди, і на диск.
_MEM: dict[str, dict[str, list[int]]] = {}
_LOCK = threading.Lock()


@contextmanager
def session(*, fetch: bool = False, record: bool = True) -> Iterator[Session]:
    """Перебудова реєстру: зібрати пропущені заглушки й записати їх для doctor.

    `record` пише перелік пропущених у кеш, щоб `nysh doctor` показав його без
    обходу диска. Записується лише після успішного проходу: обірвана
    перебудова бачила не всі справи, і її перелік був би неповним.
    """
    s = Session(fetch=fetch)
    token = _SESSION.set(s)
    try:
        yield s
    finally:
        _SESSION.reset(token)
    if record:
        _record_cloud(s.skipped)


def pages(path: str | Path, *, fetch: bool | None = None) -> int:
    """Сторінок у PDF. Кидає `PdfCountError` (і `CloudPdf` для заглушки).

    `fetch=None` бере рішення з поточної перебудови (`session`). Поза нею
    хмарний файл не відкривається: стягувати 3 ГБ без прохання не повинен ні
    реєстр, ні будь-хто, хто кличе цей лічильник за замовчуванням.
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError as exc:
        raise PdfCountError(f"файл не читається: {p} ({exc})") from exc
    key = os.path.abspath(p)
    cache = _cache_path()
    files = _load(cache)
    hit = files.get(key)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns and hit[2] > 0:
        return hit[2]
    sess = _SESSION.get()
    if fetch is None:
        fetch = sess.fetch if sess is not None else False
    if not fetch and cloud_placeholder(st):
        if sess is not None:
            sess.skipped[key] = int(st.st_size)
        raise CloudPdf(key, int(st.st_size))
    n = _open_count(str(p))
    row = [int(st.st_size), int(st.st_mtime_ns), n]
    with _LOCK:
        files[key] = row
    _save(cache, {key: row})
    return n


def cloud_report() -> dict[str, Any] | None:
    """Що пропустила остання перебудова, мінус уже пораховане згодом.

    None: перебудова з цим лічильником ще не йшла. Обходу диска тут немає,
    бо doctor кличуть часто.
    """
    cache = _cache_path()
    if cache is None:
        return None
    data = _read(cache)
    cloud = data.get("cloud")
    if not isinstance(cloud, dict):
        return None
    known = data.get("files") or {}
    left = {k: int(v) for k, v in (cloud.get("files") or {}).items()
            if k not in known}
    return {"at": str(cloud.get("at") or ""), "files": left}


def describe(skipped: dict[str, int]) -> str:
    """Попередження для людини: скільки, де і що з цим робити."""
    folders: list[str] = []
    for path in skipped:
        name = Path(path).parent.name
        if name not in folders:
            folders.append(name)
    shown = ", ".join(folders[:3]) + (f" і ще {len(folders) - 3}" if len(folders) > 3 else "")
    gb = sum(skipped.values()) / 1e9
    return (f"сторінок не пораховано в {len(skipped)} PDF ({gb:.1f} ГБ; справи: {shown}): "
            f"файли вивантажено в хмару (OneDrive / iCloud, «лише онлайн»), а відкриття "
            f"стягнуло б їх цілком. Знаменник цих справ поки що неточний. Щоб виправити, "
            f"позначте теки «Always Keep on This Device» або один раз виконайте "
            f"`nysh cases build --fetch-cloud`. Число сторінок запам'ятається, і далі "
            f"ці файли не відкриватимуться")


# ── кеш на диску ─────────────────────────────────────────────────────────────
def _cache_path() -> Path | None:
    """Файл кешу в похідних простору; None — простору немає (лише пам'ять)."""
    try:
        from nyshporka.core.workspace import workspace

        return workspace().derived / FILE
    except Exception:
        return None


def _load(cache: Path | None) -> dict[str, list[int]]:
    tag = str(cache)
    with _LOCK:
        got = _MEM.get(tag)
        if got is None:
            raw = _read(cache).get("files") if cache is not None else None
            got = {str(k): [int(x) for x in v] for k, v in (raw or {}).items()
                   if isinstance(v, list) and len(v) == 3}
            _MEM[tag] = got
        return got


def _read(cache: Path) -> dict[str, Any]:
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(cache: Path | None, rows: dict[str, list[int]] | None = None,
          cloud: dict[str, Any] | None = None) -> None:
    """Дописати рядки (і/або перелік пропущених) у файл кешу.

    Зливається з тим, що вже на диску: паралельний процес (демон і термінал
    водночас) міг дописати свої рядки. Невдача ковтається, бо без кешу
    лічильник працює так само, лише повільніше.
    """
    if cache is None:
        return
    with _LOCK:
        try:
            data = _read(cache)
            got = data.get("files")
            files: dict[str, Any] = got if isinstance(got, dict) else {}
            files.update(rows or {})
            out: dict[str, Any] = {"files": files}
            if cloud is not None:
                out["cloud"] = cloud
            elif isinstance(data.get("cloud"), dict):
                out["cloud"] = data["cloud"]
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache)
        except OSError:
            pass


def _record_cloud(skipped: dict[str, int]) -> None:
    _save(_cache_path(), cloud={"at": datetime.now().isoformat(timespec="seconds"),
                                "files": dict(skipped)})


def _open_count(path: str) -> int:
    """Відкрити й порахувати. `pypdfium2` — залежність пакета; `fitz` — запасний,
    бо стоїть у частини споживачів."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        try:
            import fitz
        except ImportError:
            raise PdfCountError("немає чим відкрити PDF (pypdfium2 не встановлено)") from None
        try:
            with fitz.open(path) as doc:
                n = int(doc.page_count)
        except Exception as exc:
            raise PdfCountError(f"PDF не відкривається: {path} ({exc})") from exc
    else:
        try:
            doc = pdfium.PdfDocument(path)
            try:
                n = len(doc)
            finally:
                doc.close()
        except Exception as exc:
            raise PdfCountError(f"PDF не відкривається: {path} ({exc})") from exc
    if n <= 0:
        raise PdfCountError(f"у PDF немає сторінок: {path}")
    return n


def _reset() -> None:
    """Для тестів: забути прочитаний кеш (як новий процес)."""
    with _LOCK:
        _MEM.clear()
