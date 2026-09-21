"""🗂 Каталог пулу: рядок на пакет, і сталий URL, за яким його шукати.

Каталог — звичайний TSV у публічному репозиторії. Вибір не від бідності:
git дає рівно те, чого потребує обмін, і задарма. «Коли й хто» — з історії
комітів, без жодного сервера; премодерація — це pull request, який можна
прийняти словом; а відкотити зіпсований рядок дешевше, ніж полагодити базу.

🔴 Байти лишаються на GitHub, домен дає їм ІМ'Я. `setup/packs.py` пояснює, чому
паки роздаються релізом: «у нього є дзеркала, і він переживе автора проєкту».
Домен — протилежний компроміс: керований, але помирає разом із реєстрацією.
Тому не заміна, а шар поверх — сталий URL веде на реліз або на сховище, і
обидві властивості лишаються. Практичний наслідок: коли обмінник переросте в
пул із чергою приймання, посилання, роздані в дописах і в чужих маніфестах,
лишаться чинними.
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
           "license", "publisher", "contact", "url", "added")


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

    def as_tsv(self) -> str:
        return "\t".join(_clean(getattr(self, c, "")) for c in COLUMNS)

    def as_json(self) -> dict[str, Any]:
        return {c: getattr(self, c, "") for c in COLUMNS}


def _clean(value: Any) -> str:
    """Табуляція й переводи рядка в полі ламають TSV мовчки — знімаємо їх тут."""
    return " ".join(str(value or "").split())


def row_for(manifest: Any, *, sha256: str = "", nbytes: int = 0,
            url: str = "", added: str = "") -> Row:
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
        added=added or time.strftime("%Y-%m-%d"))


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
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
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


def _get(url: str) -> dict[str, Any]:
    """Запит до пулу з розбором відповіді.

    🪤 `Fetcher` ходить із браузерним User-Agent — це видно в `sources/http.py`
    і це не випадковість. Наслідок для пулу: на його домені не можна вмикати
    JS-челендж, бо клієнт виглядає як Chrome, але JS не виконує, дістає 403 і
    НЕ повторює — відступ спрацьовує лише на 429 і 5xx.
    """
    import json

    from nyshporka.sources.http import Fetcher, HttpError

    try:
        resp = Fetcher().get(url)
    except HttpError as exc:
        raise RuntimeError(f"пул за {url} недоступний: {exc}") from exc
    text = resp.text if hasattr(resp, "text") else str(resp)
    try:
        got = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"пул за {url} відповів не JSON: {exc}") from exc
    if not isinstance(got, dict):
        raise RuntimeError(f"пул за {url} відповів не тим, чого чекали")
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
            out.append(Row(**{k: _clean(str(v)) for k, v in raw.items() if k in names}))
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
    return rows, int(got.get("count") or len(rows)), int(got.get("of") or 0)


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
        return _get(f"{base_url(base)}/lookup?{qs}")
    except RuntimeError as exc:
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
            header() + "".join(r.as_tsv() + "\n" for r in out), encoding="utf-8")
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
