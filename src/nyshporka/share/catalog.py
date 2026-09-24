"""🗂 Каталог пулу: рядок на пакет, і сталий URL, за яким його шукати.

Каталог — JSON API застосунку Супряги (`https://api.nyshporka.online/v1`):
`/search`, `/lookup`, `/stats`. Рядок каталогу (`Row`) і його TSV-форма
(`as_tsv`, `parse`) лишились для офлайн-дзеркала (`fetch(dest=…)`) і для
`nysh share row`.

🔴 Домен, а не адреса сховища: посилання, роздані в дописах і вписані в
чужі маніфести, переживають переїзд сховища — а їх відкликати найдорожче.

🔴 Ключ Супряги їде лише на довірену адресу (`trusted`): адресу пулу можна
перемкнути змінною чи прапорцем, а ключ — це обліковий запис людини.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

#: Домівка пулу. Одна константа, яку знає CLI, — замість імені репозиторію.
#:
#: 🔴 Домен, а не адреса сховища, і саме в цьому сенс. Каталог сьогодні —
#: статичний файл, завтра — відповідь застосунку на власному сервері, а самі
#: пакети можуть переїхати в R2; адреса при цьому не змінюється. Посилання,
#: роздані в дописах і вписані в чужі маніфести, переживають переїзд — а вони
#: якраз і є те, що відкликати найдорожче.
#: Від 0.18 це адреса API, а не тека зі статичним файлом. Сам домен той
#: самий — саме заради цього він і заводився: каталог переїхав із TSV у
#: застосунок, а посилання, роздані в дописах, лишились чинними.
DEFAULT_BASE = "https://api.nyshporka.online/v1"
CATALOG_NAME = "catalog.tsv"

#: Інша домівка — для свого дзеркала або для перевірки клієнта проти тестового
#: сервера, поки той ще не бойовий.
ENV_BASE = "NYSHPORKA_TOLOKA"


def base_url(base: str = "") -> str:
    """Домівка пулу: аргумент → оточення → типова адреса."""
    import os

    return (base or os.environ.get(ENV_BASE) or DEFAULT_BASE).rstrip("/")

#: Порядок колонок. Змінювати можна лише дописуванням у кінець: читач старого
#: каталогу мусить лишатись робочим, інакше оновлення пакета ламає чужі копії.
COLUMNS = ("shifra", "repo", "fond", "opys", "spr", "years", "places",
           "pages", "frames", "voices", "models", "bytes", "sha256",
           "license", "publisher", "contact", "url", "added", "geom_url",
           "geom_sha256")


@dataclass
class Row:
    """Один пакет у каталозі."""

    shifra: str = ""
    repo: str = ""
    fond: str = ""
    opys: str = ""
    spr: str = ""
    years: str = ""
    places: str = ""
    pages: str = ""
    frames: str = ""
    voices: str = ""
    models: str = ""
    bytes: str = ""
    sha256: str = ""
    license: str = ""
    publisher: str = ""
    contact: str = ""
    url: str = ""
    added: str = ""
    #: Адреса другого об'єкта — геометрії рядків. Порожньо означає «пакувальник
    #: її не віддавав», а не «її немає»: рамки без тих самих кадрів марні.
    geom_url: str = ""
    #: sha256 ПРИЙНЯТОГО пулом geom-файла. Порожньо — сервер його ще не
    #: віддає; тоді geom звірити нічим, і це відкритий ризик пулу.
    geom_sha256: str = ""

    def as_tsv(self) -> str:
        return "\t".join(_clean(getattr(self, c, "")) for c in COLUMNS)

    def as_json(self) -> dict[str, Any]:
        return {c: getattr(self, c, "") for c in COLUMNS}


def _clean(value: Any) -> str:
    """Табуляція й переводи рядка в полі ламають TSV мовчки — знімаємо їх тут."""
    return " ".join(str(value or "").split())


def row_for(manifest: Any, *, sha256: str = "", nbytes: int = 0,
            url: str = "", added: str = "", geom_url: str = "") -> Row:
    """Рядок каталогу з маніфесту зібраного пакета."""
    import time

    c = manifest.case
    years = c.get("years") or []
    span = ""
    if isinstance(years, list) and years:
        a, b = str(years[0]), str(years[-1])
        span = a if a == b else f"{a}–{b}"
    places = c.get("places") or []
    pub = manifest.publisher or {}
    return Row(
        shifra=manifest.shifra, repo=str(c.get("repo") or ""),
        fond=str(c.get("fond") or ""), opys=str(c.get("opys") or ""),
        spr=str(c.get("spr") or ""), years=span,
        places="; ".join(str(p) for p in places) if isinstance(places, list) else "",
        pages=str(manifest.pages), frames=str(manifest.frames_total),
        voices=str(len(manifest.voices)), models=", ".join(manifest.models()),
        bytes=str(nbytes or ""), sha256=sha256,
        license=str((manifest.license or {}).get("text") or ""),
        publisher=str(pub.get("handle") or ""),
        contact=str(pub.get("contact") or ""), url=url,
        added=added or time.strftime("%Y-%m-%d"), geom_url=geom_url)


def header() -> str:
    return "\t".join(COLUMNS)


def parse(text: str) -> list[Row]:
    """Розібрати каталог. Зайві колонки ігноруються, відсутні лишаються порожні.

    Саме так, а не суворою перевіркою ширини: каталог живий, у ньому з часом
    з'являться поля, і стара Нишпорка мусить читати новий каталог, а не падати
    на ньому.
    """
    rows: list[Row] = []
    known = {f.name for f in fields(Row)}
    # BOM на початку файлу (Excel, Блокнот) інакше прилипав до першої колонки,
    # і шапка не впізнавалась — ставала рядком даних.
    lines = [ln for ln in (text or "").lstrip("﻿").splitlines() if ln.strip()]
    if not lines:
        return rows
    head = [h.strip() for h in lines[0].split("\t")]
    if "shifra" not in head:               # файл без шапки — читаємо за порядком
        head = list(COLUMNS)
        body = lines
    else:
        body = lines[1:]
    for line in body:
        if line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        got = {h: cells[i].strip() if i < len(cells) else ""
               for i, h in enumerate(head) if h in known}
        rows.append(Row(**got))
    return rows


def find(rows: list[Row], query: str) -> list[Row]:
    """Рядки, що відповідають запиту: шифра, номер справи або назва місця.

    Пошук навмисно поблажливий. Люди пишуть шифру десятком способів, і каталог
    із єдиною правильною формою запиту — це каталог, у якому нічого не знайти.
    """
    q = " ".join((query or "").split()).casefold()
    if not q:
        return list(rows)
    tight = q.replace(" ", "").replace(".", "")
    out: list[Row] = []
    for r in rows:
        hay = " ".join([r.shifra, r.repo, r.fond, r.opys, r.spr, r.places,
                        r.years, r.publisher]).casefold()
        if q in hay or (tight and tight in hay.replace(" ", "").replace(".", "")):
            out.append(r)
    return out


def catalog_url(base: str = "") -> str:
    return f"{base_url(base)}/{CATALOG_NAME}"


class PoolError(RuntimeError):
    """Пул не відповів як слід. `status` — HTTP-код, коли він є."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PotribenKliuch(PoolError):
    """Пул відповів 401: Нишпорка не під'єднана. Текст призначений людині."""


#: Одне формулювання на всі місця, де пул не пустив без ключа.
KLIUCH_TEXT = ("Супряга пускає лише під'єднану Нишпорку. Під'єднайте: "
               "nysh share login — один клік, можна анонімно.")

#: Домен, якому довіряється ключ. Будь-яка інша адреса (`NYSHPORKA_TOLOKA`,
#: `--base`) ключа не отримує.
TRUSTED_DOMAIN = "nyshporka.online"

#: Таймаут і спроби для пулу. 🔴 Не ті шість спроб по хвилині, що в
#: `sources.http` для архівів: пул — наш сервер, і коли він лежить, людина
#: має дізнатись про це за секунди, а не чекати шість з половиною хвилин
#: перед прогоном, який вона однаково зробить сама.
POOL_TIMEOUT = 30.0
POOL_ATTEMPTS = 2
#: Питання «чи вже прочитано» стоїть перед прогоном і ніколи його не спиняє,
#: тож на нього — одна коротка спроба.
LOOKUP_TIMEOUT = 8.0


def trusted(url: str) -> bool:
    """Чи можна везти ключ Супряги на цю адресу.

    🔴 Ключ — це обліковий запис людини. Адресу пулу можна перемкнути
    змінною оточення чи прапорцем, і без цієї перевірки бойовий ключ зі
    сховища ключів їхав би на будь-яке «своє дзеркало», зокрема відкритим
    HTTP. Довіряємо лише HTTPS на домені пулу й петлі цієї машини (тестовий
    сервер розробника; процес на петлі й так може прочитати сховище ключів).
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    return parts.scheme == "https" and (
        host == TRUSTED_DOMAIN or host.endswith("." + TRUSTED_DOMAIN))


def may_send_key(url: str, *, explicit: bool = False) -> bool:
    """Чи їде ключ на цю адресу.

    Довірена адреса — завжди. Чужа — лише коли ключ названо ЯВНО: переданий
    аргументом або покладений людиною в `NYSHPORKA_SUPRIAHA_TOKEN` для свого
    сервера. Ключ зі сховища ключів системи на чужу адресу не їде ніколи.
    """
    import os

    from nyshporka.share.upload import ENV_NAME

    return trusted(url) or explicit or bool(os.environ.get(ENV_NAME, "").strip())


def reason(exc: Exception) -> str:
    """Людська причина відмови пулу — з тіла відповіді, а не голий код.

    Сервер кладе причину в `detail`: рядком або словником із `text` і
    `refusals` (ворота). Без цього людина бачила б «HTTP 400» там, де пул
    назвав, котрі саме ворота пакет не пройшов.
    """
    import json

    body = str(getattr(exc, "body", "") or "")
    status = getattr(exc, "status", None)
    detail: Any = None
    if body:
        try:
            detail = json.loads(body).get("detail")
        except (ValueError, AttributeError):
            detail = None
    parts: list[str] = []
    if isinstance(detail, str):
        parts.append(detail)
    elif isinstance(detail, dict):
        if detail.get("text"):
            parts.append(str(detail["text"]))
        for r in detail.get("refusals") or []:
            parts.append(f"✗ {r}")
    if not parts:
        return str(exc)
    head = f"HTTP {status}: " if status else ""
    return head + "\n".join(parts)


def _fetcher(url: str, *, timeout: float = POOL_TIMEOUT,
             attempts: int = POOL_ATTEMPTS, auth: str | None = None,
             accept_json: bool = False) -> Any:
    """Клієнт до пулу: свій UA, ключ лише на довірену адресу, без повторів 429.

    `auth=None` — узяти ключ зі сховища; порожній рядок — без ключа.
    """
    from nyshporka.share.upload import token
    from nyshporka.sources.http import Fetcher, app_ua, offline

    if offline():
        raise PoolError("мережу вимкнено (NYSHPORKA_NO_NETWORK) — пул не питається")
    headers = {"User-Agent": app_ua()}
    if accept_json:
        headers["Accept"] = "application/json"
    kliuch = token() if auth is None else auth
    if kliuch and may_send_key(url, explicit=bool(auth)):
        headers["Authorization"] = f"Bearer {kliuch}"
    return Fetcher(headers=headers, timeout=timeout, attempts=attempts,
                   retry_429=False)


def _get(url: str, *, timeout: float = POOL_TIMEOUT,
         attempts: int = POOL_ATTEMPTS) -> dict[str, Any]:
    """Запит до пулу з розбором відповіді.

    🔴 Клієнт називається своїм іменем (`app_ua`), а не браузерним рядком
    `Fetcher` за замовчуванням. Пул пише подію на кожен lookup, і найцінніше
    в ній — промахи: «питали, а в нас нема» це і є перелік того, що засівати
    далі. Під браузерним рядком у цій події не відрізнити клієнта перед
    прогоном від людини у вкладці й від пошукового бота.

    🪤 На домені пулу не можна вмикати JS-челендж: клієнт JS не виконує,
    дістане 403 і НЕ повторить — відступ спрацьовує лише на 429 і 5xx.
    Перевірено наживо: і браузерний рядок, і `nyshporka/<версія>` Cloudflare
    пропускає, тож своє ім'я тут нічого не коштує.
    """
    import json

    from nyshporka.sources.http import HttpError

    # 🔴 Шукати й качати через API пул пускає лише з ключем (рішення
    # 23.09.2026). Ключ їде в кожному запиті, якщо він є і адреса довірена, —
    # окремого «режиму з ключем» немає, щоб не було місця, яке його забуло.
    try:
        resp = _fetcher(url, timeout=timeout, attempts=attempts).get(url)
    except HttpError as exc:
        if exc.status == 401:
            raise PotribenKliuch(KLIUCH_TEXT, status=401) from exc
        raise PoolError(f"пул за {url} недоступний: {reason(exc)}",
                        status=exc.status) from exc
    text = resp.text if hasattr(resp, "text") else str(resp)
    try:
        got = json.loads(text)
    except ValueError as exc:
        raise PoolError(f"пул за {url} відповів не JSON: {exc}") from exc
    if not isinstance(got, dict):
        raise PoolError(f"пул за {url} відповів не тим, чого чекали")
    return got


def _rows(payload: dict[str, Any]) -> list[Row]:
    """Рядки з відповіді пулу.

    Зайві поля відкидаються, відсутні лишаються порожніми — те саме правило,
    що й у `parse`: читач старого каталогу мусить лишатись робочим, коли на
    сервері допишуть колонку.
    """
    names = {f.name for f in fields(Row)}
    out: list[Row] = []
    for raw in payload.get("rows") or []:
        if isinstance(raw, dict):
            # 🔴 `_clean`, а не `str(v)`: `null` з JSON інакше ставав рядком
            # «None» — правдивим значенням, і `geom_url=None` читався як «рамки є».
            out.append(Row(**{k: _clean(v) for k, v in raw.items() if k in names}))
    return out


def search(query: str = "", base: str = "", *, limit: int = 50,
           offset: int = 0) -> tuple[list[Row], int, int]:
    """Пошук у пулі → (рядки, скільки збіглося, скільки в пулі всього).

    🔴 Пошук СЕРВЕРНИЙ. Раніше клієнт качав увесь каталог і фільтрував його
    в пам'яті — на сотні пакетів це працювало, на десятках тисяч означало б
    мегабайти на кожен запит про одну справу.

    Третє число — розмір пулу; воно потрібне рядку «пакетів N», і без нього
    людина не бачить, наскільки великою є спільна робота.
    """
    from urllib.parse import urlencode

    qs = urlencode({"q": query, "limit": limit, "offset": offset})
    got = _get(f"{base_url(base)}/search?{qs}")
    rows = _rows(got)
    return rows, as_int(got.get("count")) or len(rows), as_int(got.get("of"))


def as_int(value: Any) -> int:
    """Число з відповіді пулу; нечислове — нуль, а не падіння з трасою."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def stats(base: str = "") -> dict[str, Any]:
    """Зведення по пулу — рахує сервер.

    Раніше для цих трьох чисел качався весь каталог.
    """
    return _get(f"{base_url(base)}/stats")


def lookup(shifra: str, *, frames: int = 0, base: str = "") -> dict[str, Any]:
    """Чи є вже текст цієї книги — питання ПЕРЕД прогоном.

    Ніколи не кидає: пул лежить — повертається «не знайдено» з причиною.
    Прогін не має падати через те, що пул недоступний.
    """
    from urllib.parse import urlencode

    qs = urlencode({"shifra": shifra, "frames": frames})
    try:
        return _get(f"{base_url(base)}/lookup?{qs}", timeout=LOOKUP_TIMEOUT,
                    attempts=1)
    except PotribenKliuch as exc:
        return {"found": False, "why": str(exc), "need_key": True}
    except Exception as exc:
        return {"found": False, "why": str(exc), "offline": True}


def fetch(base: str = "", *, dest: Path | None = None) -> list[Row]:
    """Забрати ввесь каталог — для офлайн-дзеркала.

    Лишається окремо від `search`, бо в нього інша задача: не відповісти на
    питання, а зняти копію. Гортання сторінками, а не один великий запит:
    стеля видачі стоїть на сервері й не обходиться.
    """
    out: list[Row] = []
    offset = 0
    while True:
        rows, _, of = search("", base, limit=100, offset=offset)
        out.extend(rows)
        offset += len(rows)
        if not rows or offset >= of:
            break
    if dest is not None:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(
            header() + "\n" + "".join(r.as_tsv() + "\n" for r in out),
            encoding="utf-8")
    return out


def summarize(rows: list[Row]) -> dict[str, Any]:
    """Зведення по каталогу: скільки справ, сторінок, хто скільки вніс."""
    people: dict[str, dict[str, int]] = {}
    fonds: dict[str, int] = {}
    pages = frames = 0
    for r in rows:
        p = int(r.pages or 0)
        pages += p
        frames += int(r.frames or 0)
        who = r.publisher or "без імені"
        slot = people.setdefault(who, {"cases": 0, "pages": 0})
        slot["cases"] += 1
        slot["pages"] += p
        key = f"{r.repo} {r.fond}".strip() or "?"
        fonds[key] = fonds.get(key, 0) + 1
    return {
        "cases": len(rows), "pages": pages, "frames": frames,
        "publishers": sorted(
            ({"publisher": k, **v} for k, v in people.items()),
            key=lambda x: -int(x["pages"])),
        "fonds": sorted(({"fond": k, "cases": v} for k, v in fonds.items()),
                        key=lambda x: -int(x["cases"])),
    }
