"""🗺 `ridni.org` — зведений каталог книг ЗА СЕЛОМ.

Джерело відповідає на питання, якого не ставлять описи фондів: «які книги
взагалі є про моє село». Опис перелічує справи фонду, покажчик — справи за
назвою; тут же ключем є саме село, а у відповіді разом із шифрою приходять
прямі посилання — viewer-id ARCHIUM і номер плівки FamilySearch.

🔑 **Головна користь не в посиланнях, а в ЗНАМЕННИКУ.** Рік, якого немає у двох
незалежних каталогах, — це лакуна фонду, а не невдалий пошук. Замір по Шупиках
(02.09.2026): 109 метричних книг за 1795-1917, і років 1902, 1904, 1906 немає ні
тут, ні в газетирі ЦДІАК. Без цього знання том-кандидат за 1902 качали й шукали
в ньому книгу, якої не існує.

🪤 **Звуження на сервері немає жодного.** `povit`, `county`, `koatuu`, `limit`
приймаються й ігноруються — працює рівно `settlement`, і збіг іде за назвою по
всій країні. Замір: «Іванівка» → 13 171 запис, 100 різних губерній-повітів,
26 МБ. Тобто однойменні села злипаються, і без відсіву на нашому боці книга
чужої Іванівки читалась би як своя. Тому запит приймає форму
«<село>, <повіт або губернія>», а вибірка звужується тут.

⚠ Каталог ведуть люди, і тип запису написаний чотирма способами — «сповідний
розпис», «сповідний розпіс» і «cповідний розпис» із ЛАТИНСЬКОЮ `c`. Фільтр за
типом без нормалізації мовчки втратив би третину сповідок.

Адресація (`ref`): `case:<архів>-<фонд>-<опис>-<справа>`, як у покажчика.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from nyshporka.sources.base import Hit, SourceError
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

HOST = "https://ridni.org"

#: Індекси полів у рядку відповіді. Каталог віддає СПИСКИ, не словники, тож
#: імена полів існують лише тут — і зсув на одну колонку мовчки підмінив би
#: повіт губернією.
F_ARCHIVE, F_CODE, F_TYPE, F_YEAR = 0, 1, 2, 3
F_CHURCH, F_PLACE, F_ATTACHED, F_COUNTY, F_GUBERNIA = 4, 5, 6, 7, 8
F_FS, F_ARCHIUM = 16, 17

#: Скільки записів каталог віддає за раз — усе, що знайшлось за назвою; стелі
#: немає, зате є 26 МБ на поширеній назві. Обрізаємо ми, і кажемо про це.
FIELDS_MIN = 18


def _clean(value: object) -> str:
    """Порожнеча в цьому каталозі буває трьох видів: `None`, `""` і пробіли."""
    return " ".join(str(value or "").split())


def _norm_type(raw: str) -> str:
    """Тип запису до одного написання.

    ⚠ Латинська `c` на початку «cповідний» — не помилка розбору, а те, що
    справді лежить у даних. Разом із «розпіс» це три різні рядки на один тип.
    """
    text = _clean(raw).lower().replace("c", "с").replace("розпіс", "розпис")
    return text


def _place_of(row: list[Any]) -> str:
    """«Шупики · Канівський повіт · Київська губернія» — з того, що є."""
    село = _clean(row[F_PLACE]).rstrip(",").removesuffix(", с.").strip()
    повіт = _clean(row[F_COUNTY]).rstrip(",")
    губ = _clean(row[F_GUBERNIA]).rstrip(",").removesuffix(" губернія").strip()
    parts = [село]
    if повіт:
        parts.append(f"{повіт} пов.")
    if губ:
        parts.append(f"{губ} губ.")
    return " · ".join(p for p in parts if p)


def _dgs(url: str) -> str:
    """Номер плівки FamilySearch із посилання. Він же — ключ замовлення образів."""
    marker = "imageGroupNumbers="
    if marker not in (url or ""):
        return ""
    tail = url.split(marker, 1)[1]
    num = "".join(ch for ch in tail if ch.isdigit())
    return num


@dataclass(frozen=True)
class Book:
    """Книга каталогу: шифра, місце й адреси копій в одному рядку."""

    archive: str
    code: str          # «127-1078-1649», а буває й «1975-1-св. Іоанна — 101»
    rtype: str
    year: str
    church: str
    place: str
    attached: str
    county: str
    gubernia: str
    archium_url: str
    fs_url: str

    @property
    def full_code(self) -> str:
        return f"{self.archive}-{self.code}" if self.archive else self.code

    @property
    def fond(self) -> str:
        """Номер фонду — лише коли шифра справді розбирається.

        🔴 Поле каталогу вільне, і в ньому трапляється «, оп. -, спр. -» або
        назва церкви замість номера опису. Наївний `split("-")[0]` віддав би
        звідти сміття, а `Hit.fond` їде у зведення по фондах: один такий рядок
        створив би фонд, якого немає.
        """
        head = self.code.split("-")[0].strip()
        return head if head.isdigit() else ""

    def mentions(self, name: str) -> str:
        """Де в цьому рядку згадано шукане село: `«»` · `«парафія»` · `«приписне»`."""
        needle = name.lower()
        if needle and needle in self.place.lower():
            return "парафія"
        if needle and needle in self.attached.lower():
            return "приписне"
        return ""


def parse_rows(rows: object) -> list[Book]:
    """Відповідь каталогу → книги. Рядок не тієї форми пропускається мовчки."""
    out: list[Book] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, list) or len(row) < FIELDS_MIN:
            continue
        code = _clean(row[F_CODE])
        if not code:
            continue
        out.append(Book(
            archive=_clean(row[F_ARCHIVE]), code=code,
            rtype=_norm_type(row[F_TYPE]), year=_clean(row[F_YEAR]),
            church=_clean(row[F_CHURCH]), place=_place_of(row),
            attached=_clean(row[F_ATTACHED]),
            county=_clean(row[F_COUNTY]).rstrip(","),
            gubernia=_clean(row[F_GUBERNIA]).rstrip(","),
            archium_url=_clean(row[F_ARCHIUM]), fs_url=_clean(row[F_FS])))
    return out


def split_query(q: str) -> tuple[str, str]:
    """«Іванівка, Канівський» → («Іванівка», «канівський»).

    🔴 Звуження питається в людини, бо сервер його не вміє. Без другої частини
    на поширеній назві приходять книги ста різних повітів, і всі вони виглядають
    як відповідь про твоє село.
    """
    head, _, tail = (q or "").partition(",")
    return _clean(head), _clean(tail).lower()


class RidniSource:
    """Каталог `ridni.org`. Живий запит, каталогу на диску немає."""

    id = "ridni"
    label = "ridni.org (каталог книг за селом)"
    caps = frozenset({"search"})

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        # Публічний волонтерський каталог: називаємось своїм ім'ям і не б'ємо
        # чергою. Один пошук — один запит, тож окремої черги, як у покажчика,
        # тут не заводимо; темп тримає стандартна пауза `Fetcher`.
        return Fetcher(base=HOST, headers={"User-Agent": app_ua()})

    @staticmethod
    def _our_repo(archive_code: str) -> str:
        """«ЦДІАК» → `CDIAK`.

        ⚠ Через `resolve_code` паку, а не через `codes.ridni`: цей каталог зве
        архіви тими самими українськими скороченнями, які пак уже знає разом із
        псевдонімами й мішаним письмом. Заводити на кожен архів ще один рядок
        перекладу означало б тримати другу копію того самого знання — і саме
        вона першою й розійшлася б.
        """
        from nyshporka.archives import active

        pk = active()
        code = pk.resolve_code(_clean(archive_code))
        return pk.canon_repo(code) if code else ""

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Живий запит: нуль означає «немає в каталозі зараз», а не «на дату зрізу»."""
        return "live", {"taken": "", "rows": None,
                        "scope": "книги за селом (ЦДІАК та інші)", "host": HOST}

    def books(self, settlement: str) -> list[Book]:
        """Усе, що каталог знає про цю назву. Без звуження — його сервер не вміє."""
        name = _clean(settlement)
        if not name:
            return []
        if offline() and self._fetcher is None:
            raise SourceError(
                "мережу вимкнено в цьому середовищі — каталог не опитано")
        path = ("/catalog/api/getCatalogData2.php"
                f"?settlement={quote(name.lower())}&searchType=all")
        try:
            r = self._http().get(path)
            rows = json.loads(getattr(r, "text", "") or "[]")
        except (HttpError, OSError) as exc:
            raise SourceError(f"каталог не відповів: {exc}") from exc
        except ValueError:
            raise SourceError(
                "каталог відповів не JSON — адреса запиту змінилась") from None
        return parse_rows(rows)

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Книги села. Запит: «Шупики» або «Шупики, Канівський».

        🔴 Знаменник їде в примітці кожної знахідки. Каталог шукає за назвою по
        всій країні, тож «показано 30» без «з 13 171 у ста повітах» читалось би
        як повний перелік книг села — тобто як підстава закрити напрям.
        """
        name, narrow = split_query(q)
        if not name:
            return []
        books = self.books(name)
        if not books:
            return []
        keep = [b for b in books
                if not narrow or narrow in b.county.lower()
                or narrow in b.gubernia.lower()]
        # ⚠ Каталог тримає ту саму книгу двічі, коли парафія має приписні села:
        # рядок повторюється на кожне з них. У видачі це виглядало б як дві
        # різні справи з однією шифрою — тобто як подвоєний знаменник.
        seen: set[tuple[str, str, str]] = set()
        unique: list[Book] = []
        for b in keep:
            key = (b.full_code, b.year, b.rtype)
            if key not in seen:
                seen.add(key)
                unique.append(b)
        keep = unique
        # Своя парафія першою, приписне село — за нею, далі часткові збіги
        # назви («Іванівка Друга»). Інакше порядок задає каталог, і своє село
        # може не влізти у видачу взагалі.
        _rank = {"парафія": 0, "приписне": 1}
        keep.sort(key=lambda b: (_rank.get(b.mentions(name), 2), b.year))
        places = {(b.county, b.gubernia) for b in keep}
        tail = ""
        if len(keep) > limit or len(places) > 1:
            tail = (f" · з {len(keep)} за цією назвою"
                    + (f" у {len(places)} повітах — звузьте: «{name}, <повіт>»"
                       if len(places) > 1 else ""))
        out: list[Hit] = []
        for b in keep[:limit]:
            note = " · ".join(x for x in (b.rtype, b.church) if x)
            if b.mentions(name) == "приписне":
                # 🔑 Не шум, а окремий канал: книга ЧУЖОЇ парафії, до якої це
                # село приписане. Саме там і трапляються земляки — але сказати
                # це треба вголос, бо в рядку стоятиме інша назва села.
                note += f" · {name} тут приписне село"
            dgs = _dgs(b.fs_url)
            if dgs:
                note += f" · FamilySearch DGS {dgs}"
            out.append(Hit(
                source=self.id, ref=f"case:{b.full_code}",
                title=" ".join(x for x in (b.rtype.capitalize(), b.church) if x)[:200],
                years=b.year, place=b.place,
                shifra=f"{b.archive} {b.code}".strip(),
                repo=self._our_repo(b.archive), archive=b.archive, fond=b.fond,
                # Качати вміє інше джерело: підміняти тут `source` не можна —
                # тоді знаходив би ridni, а в знаменнику «шукали в» стояв би чужий.
                acquirable=False,
                url=b.archium_url or b.fs_url,
                note=(note + tail).strip(" ·")))
        return out
