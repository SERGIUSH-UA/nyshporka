"""📦 Паки: ваги моделей і каталоги — качаються при першому запуску.

У колесі їх немає навмисно. Ваги трьох моделей — сотні мегабайтів, а pip-пакет
на 300 МБ ставиться довго, оновлюється боляче й тягне все три навіть тому, хто
читатиме лише латинку.

🔴 sha256 перевіряється завжди, і це не про зловмисника. Обірвана закачка лишає
файл, який виглядає як модель: `torch.load` на ньому впаде десь усередині, з
повідомленням про формат тензора — тобто причину («не докачалось») доведеться
здогадувати. Дешевше звірити хеш і сказати прямо.

🔴 Версія в імені файлу — частина контракту. «Найновіша» не означає «найкраща»:
у дослідницькому конвеєрі бойовими лишались не останні версії, бо пізніші
програвали на голдовому зрізі. Тому пак називає версію, а не «latest».
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: Звідки качаються паки. Реліз на GitHub, а не власний хост: у нього є
#: дзеркала, і він переживе автора проєкту.
BASE_URL = "https://github.com/SERGIUSH-UA/nyshporka/releases/download"

#: Лічильник завантажень: записує подію й відповідає 302 на той самий ассет
#: релізу. Код — `app/vahy.py` у репо nyshporka-online.
#: 🔴 Лічильник ніколи не сміє зламати встановлення: недоступний домен, 5xx,
#: таймаут чи дивна відповідь — і пак качається з `BASE_URL` напряму.
COUNTER_URL = "https://nyshporka.online/w"
COUNTER_TIMEOUT = 5.0

MANIFEST_NAME = "packs.json"


@dataclass(frozen=True)
class Pack:
    """Один завантажуваний артефакт."""

    id: str
    kind: str            # model | catalog
    filename: str
    sha256: str
    size: int
    release: str         # тег релізу
    label: str = ""
    script: str = ""     # для моделей: письмо (latin / cyrillic)
    engine: str = ""     # kraken | parseq
    note: str = ""
    #: Пак попереднього покоління. Не качається за замовчуванням — новий
    #: користувач не платить за ваги, якими вже ніхто не читає, — але якщо він
    #: УЖЕ лежить у людини, то лишається кандидатом нижчого пріоритету. Так
    #: оновлений застосунок читає й тоді, коли нові ваги ще не довантажені
    #: (офлайн, обірване `nysh models get`): гірше, але не «читати нічим».
    superseded: bool = False

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.release}/{self.filename}"

    @property
    def counter_url(self) -> str:
        return f"{COUNTER_URL}/{self.release}/{self.filename}"


def manifest_path() -> Path:
    return Path(__file__).resolve().parent / "data" / MANIFEST_NAME


def catalog() -> list[Pack]:
    """Що взагалі можна завантажити. Перелік їде з пакетом, самі файли — ні."""
    raw = json.loads(manifest_path().read_text(encoding="utf-8"))
    return [Pack(**p) for p in raw.get("packs", [])]


#: Види паків, чия втрата тиха → лягають у дані, а не в кеш.
_DATA_KINDS = {"catalog"}


def target_dir(kind: str) -> Path:
    """Куди кладеться пак.

    🔴 Не в простір дослідження. Ваги — річ відтворювана й спільна для всіх
    просторів; класти їх у простір означало б і дублювати сотні мегабайтів на
    кожен архів, і тягнути їх у резервну копію дослідження, де їм не місце.

    🔴 А от `user_cache_dir` проти `user_data_dir` вирішується не зручністю, а
    тим, як гучно чути втрату. Кеш операційна система має право прибрати:
      • ваги зникли — читання не запуститься, `doctor` скаже, і людина поставить
        їх заново; втрата гучна, кеш тут доречний;
      • **каталог зник — пошук просто знайде менше**, і «метрик цього села
        немає» стане неправдою, якої ніхто не помітить.
    Тобто саме правило «нуль мусить щось означати» забороняє класти довідники в
    кеш. Тека каталогу збігається з `catalog.store.catalog_dir()`.
    """
    from nyshporka.core.appdirs import cache_dir, data_dir

    if kind == "catalog":
        # Та сама тека, що читає `catalog_dir()`, з її змінною включно: інакше
        # `NYSHPORKA_CATALOG` перенаправляв читача, а пак лягав деінде.
        from nyshporka.catalog.store import catalog_dir

        return catalog_dir()
    return (data_dir() if kind in _DATA_KINDS else cache_dir()) / kind


def path_of(pack: Pack) -> Path:
    return target_dir(pack.kind) / pack.filename


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def verify(pack: Pack) -> bool:
    """Файл на місці й цілий.

    🔴 Пак без хеша не вважається цілим ніколи. Це не формальність: маніфест
    у дереві коду має заглушки доти, доки реліз не складено, і «пропустити
    перевірку, якщо хеша немає» означало б, що застосунок мовчки приймає
    будь-що з тим іменем — включно з половиною файлу.
    """
    if not pack.sha256 or not pack.size:
        return False
    p = path_of(pack)
    try:
        st = p.stat()
    except OSError:
        return False
    if st.st_size != pack.size:
        return False
    # ⏱ Хеш файлу рахується раз на його стан (розмір + час зміни), а не на кожне
    # питання: план читання питав про шість паків щоразу — секунда на кнопку.
    # Підмінений чи дописаний файл міняє час зміни, і хеш рахується наново.
    key = (str(p), st.st_size, st.st_mtime_ns, pack.sha256)
    got = _VERIFIED.get(key)
    if got is None:
        got = sha256_of(p) == pack.sha256
        _VERIFIED[key] = got
    return got


#: Звірені паки: (шлях, розмір, час зміни, очікуваний хеш) → чи збігся хеш.
_VERIFIED: dict[tuple[str, int, int, str], bool] = {}


def installed() -> list[str]:
    """Id паків, які лежать на диску Й проходять звірку.

    Недокачаний файл у перелік не потрапляє: «модель є» про нього було б
    брехнею, яка проявиться аж посеред прогону.
    """
    return [p.id for p in catalog() if verify(p)]


def missing(kind: str = "", *, include_superseded: bool = False) -> list[Pack]:
    """Чого бракує. Замінені паки сюди не входять: їх ніхто не мусить качати."""
    return [p for p in catalog()
            if (not kind or p.kind == kind) and (include_superseded or not p.superseded)
            and not verify(p)]


#: Запас над розміром пака з маніфесту: розмір там може бути округлений.
PACK_SIZE_SLACK = 1 << 20

#: Заголовки, які лічильник узагалі може отримати. 🔴 Жодного іншого: ні ID
#: встановлення, ні хешу машини, ні шляхів, ні `NYSHPORKA_CONTACT`. Тест
#: звіряє запит саме з цим переліком.
COUNTER_HEADERS = frozenset({"User-Agent", "X-Nysh-Reason", "X-Nysh-From", "X-Nysh-CI"})


def download_reason(pack: Pack, *, force: bool = False) -> tuple[str, str]:
    """Чому качається пак: `(reason, from)`.

    • repair — цей самий файл уже лежить, але не пройшов звірку, або `force`;
    • update — лежить інша версія тієї ж моделі (той самий вид, письмо й
      рушій), замінена теж; `from` — тег її релізу;
    • install — нічого з цього.
    Рахується ДО качання: після нього кожне встановлення виглядало б ремонтом.
    """
    if force or path_of(pack).exists():
        return "repair", ""
    olds = [p for p in catalog()
            if p.id != pack.id and p.kind == pack.kind and p.script and p.engine
            and p.script == pack.script and p.engine == pack.engine
            and path_of(p).exists()]
    if not olds:
        return "install", ""
    return "update", max(olds, key=lambda p: _release_rank(p.release)).release


def _release_rank(tag: str) -> tuple[int, str]:
    """`weights-v3` > `weights-v2`; тег без номера — найнижчий."""
    import re

    m = re.search(r"(\d+)$", tag)
    return (int(m.group(1)) if m else -1, tag)


def _os_name() -> str:
    import sys

    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux" if sys.platform.startswith("linux") else "other"


def download_ua() -> str:
    """UA для ваг: застосунок, ОС і версія Python — і більше нічого.

    🔴 Не `app_ua()`: той додає `NYSHPORKA_CONTACT`, а лічильнику особа не
    потрібна.
    """
    import sys

    from nyshporka import __version__
    from nyshporka.sources.http import HOMEPAGE

    return (f"nyshporka/{__version__} (+{HOMEPAGE}) {_os_name()} "
            f"py{sys.version_info.major}.{sys.version_info.minor}")


def counter_headers(reason: str, frm: str = "") -> dict[str, str]:
    import os

    h = {"User-Agent": download_ua(), "X-Nysh-Reason": reason}
    if reason == "update" and frm:
        h["X-Nysh-From"] = frm
    if os.environ.get("NYSH_CI") == "1":
        h["X-Nysh-CI"] = "1"
    return h


def _count(pack: Pack, reason: str, frm: str) -> bool:
    """Зарахувати завантаження. Повертає, чи лічильник відповів як слід.

    Лічильник питаємо без переходу за редиректом і з коротким таймаутом: його
    302 веде рівно на `pack.url`, тож байти все одно качаються з GitHub, а від
    лічильника потрібна лише сама подія. Чужий `Location` не приймається
    ніколи — зламаний чи підмінений домен не може підсунути інший хост.
    🔴 Будь-яка біда лічильника тут ковтається: встановлення від неї не
    залежить.
    """
    import httpx

    from nyshporka.sources.http import offline

    if offline():
        return False
    try:
        r = httpx.get(pack.counter_url, headers=counter_headers(reason, frm),
                      follow_redirects=False, timeout=COUNTER_TIMEOUT)
    except (httpx.HTTPError, OSError):
        return False
    return r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location") == pack.url


def _stream_to(pack: Pack, url: str, tmp: Path,
               on_progress: Callable[..., None] | None) -> None:
    import httpx

    got = 0
    # 🔴 Розмір пака відомий з маніфесту — він і стеля (із запасом на
    # округлення в маніфесті). Доти качання читало скільки дадуть, і підмінена
    # чи зациклена відповідь заповнювала диск раніше, ніж звірка sha256
    # встигала відмовити (аудит 29.09.2026).
    cap = pack.size + PACK_SIZE_SLACK if pack.size else 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes():
                got += len(chunk)
                if cap and got > cap:
                    raise RuntimeError(
                        f"{pack.filename}: сервер віддає понад {cap} байт при "
                        f"заявлених {pack.size} — це не той файл, качання обірвано")
                fh.write(chunk)
                if on_progress:
                    on_progress(done=got, total=pack.size, unit="Б")


def fetch(pack: Pack, *, on_progress: Callable[..., None] | None = None,
          force: bool = False) -> Path:
    """Завантажити пак і звірити хеш. Повертає шлях.

    Запис іде через сусідній тимчасовий файл: обрив на самому записі не має
    лишати напівфабрикату під бойовим іменем — саме він потім і виглядає як
    «модель зламана».
    """
    dst = path_of(pack)
    if not force and verify(pack):
        return dst
    if not pack.sha256:
        # Відмова, а не «завантажимо й повіримо». Модель, про цілість якої ми
        # не можемо нічого сказати, читатиме справу годинами й видасть текст,
        # який не відрізнити від поганого почерку.
        raise RuntimeError(
            f"{pack.id}: у маніфесті немає sha256 — цей пак ще не входить у "
            f"складений реліз. Качати без звірки не буду.")
    reason, frm = download_reason(pack, force=force)
    _count(pack, reason, frm)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        _stream_to(pack, pack.url, tmp, on_progress)
        digest = sha256_of(tmp)
        if digest != pack.sha256:
            raise RuntimeError(
                f"{pack.filename}: sha256 не збігся "
                f"(очікували {pack.sha256[:12]}…, отримали {digest[:12]}…). "
                f"Найімовірніше — обірвана закачка; спробуйте ще раз.")
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def iter_needed(kind: str = "") -> Iterator[Pack]:
    yield from missing(kind)


def as_dict() -> dict[str, Any]:
    """Стан паків для звіту й для екрана.

    ⚠ Розділяє «немає» і «зіпсоване»: перше лікується завантаженням, друге —
    повторним, і плутати їх означає радити не те.
    """
    rows = []
    for p in catalog():
        path = path_of(p)
        rows.append({
            "id": p.id, "kind": p.kind, "label": p.label or p.id,
            "size": p.size, "script": p.script, "engine": p.engine,
            "superseded": p.superseded,
            "state": ("ok" if verify(p)
                      else "broken" if path.exists()
                      else "superseded" if p.superseded else "absent"),
            "path": str(path),
        })
    return {"dir": str(target_dir("model").parent), "packs": rows}
