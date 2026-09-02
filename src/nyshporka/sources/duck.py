"""🦆 Duck Inspector — зведений покажчик українських архівів як джерело пошуку.

Навіщо поруч із ARCHIUM і дзеркалом плівок
──────────────────────────────────────────
Решта каталогів тут описує те, що вже виставлене в мережу, і кожен — свій
майданчик. Вкладений зріз ARCHIUM (ДАХмО) на дев'ять тисяч справ має по
ф.230 рівно одну позицію з 229, які існують в описі; дзеркало плівок накриває
лише ті регіони, де зібрано поаркушевий покажчик. Тобто запит про справу, яку
не оцифровано, обидва віддають нулем — і цей нуль читається як «такого немає»,
хоча означає «немає серед виставленого».

Покажчик відповідає на інше питання: **що взагалі існує**. Він перелічує справи
незалежно від оцифрування, накриває 43 архіви тими самими кодами, що й ми, і
шукає по заголовках одним запитом без жодного попереднього обходу — тобто дає
відповідь там, де решта джерел мовчить, ще й на голій установці.

🔴 що це джерело не вміє. Воно нічого не віддає: покажчик, а не сховище. Тому
`acquirable` у знахідок завжди хибний, а `caps` — самий лише `search`. Обіцяти
кнопку «завантажити» там, де за нею немає файлу, гірше за її відсутність.

🔴 стеля видачі — 50, І пагінації В пошуку немає. Рівно п'ятдесят — це не
«знайшлось п'ятдесят», а «обрізано»; мовчазна обрізка тут читалась би як повний
перелік, тобто як знаменник для негативу. Стеля оголошена в `search_ceiling`,
і на неї спирається попередження на рівні `catalog.search`.

🔴🔴 ліміт запитів — на клієнта, А не на процес. Дока просить 5 запитів на
10 секунд і попереджає, що зловживання карається блокуванням без попередження.
Це безкоштовний волонтерський сервіс, тож пауза всередині процесу тут нічого не
доводить: дві сесії з бездоганною паузою кожна дають подвійний темп. Черга
спільна на всю машину (`core.xrate`) і та сама, що в збирача реєстру, — інакше
пошук з застосунку й обхід фонду з CLI склали б темп удвічі.

Адресація (`ref`): `case:<повний код>` — напр. `case:ДАХмО-230-1-2А`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from nyshporka.sources.base import Hit, SourceError
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

HOST = "https://inspector.duckarchive.com"

#: Ключ спільної черги. Один на весь застосунок — бюджет міряється по IP.
RATE_KEY = "duck-inspector"
RATE_MAX = 5
RATE_WINDOW = 10.0

#: Скільки справ найбільше віддає `POST /api/search`. Пагінації немає.
CEILING = 50

#: Скільки парафій найбільше віддає `GET /api/authors`. Теж без пагінації.
AUTHORS_CEILING = 200

#: 🔴 Дока обіцяє, що `fuzziness` нижче 0.3 підіймається до 0.3. Насправді все,
#: що менше цього значення, віддає HTTP 500 — тобто запит не виконується зовсім.
#: Замір 02.09.2026: 0.3 і 0.4 — 500; 0.45, 0.5, 0.7 і 1 — відповідь.
FUZZ_MIN = 0.45

#: Вікна років, якими обходять стелю видачі. Кожне вікно має власну стелю, тож
#: розбитий запит бачить більше за суцільний: замір на колі 25 км — 50 справ
#: одним запитом проти 172 шістьма вікнами.
YEAR_WINDOWS: tuple[tuple[int, int], ...] = (
    (1700, 1800), (1801, 1830), (1831, 1860),
    (1861, 1890), (1891, 1920), (1921, 1960))


@dataclass(frozen=True)
class Parish:
    """Парафія покажчика — церква, костел, синагога з її координатами.

    🔑 Головне, чого немає в жодному описі. Опис каже «Сповідальні відомості
    церков повіту», а покажчик знає, ЯКІ саме церкви в тій книзі, — і те саме
    знання працює у зворотний бік: від парафії до всіх її книг.

    ⚠ `cases` — число прив'язаних справ за самим покажчиком. Перелік цих справ
    у відповіді НЕ приходить (там лише один зразковий id), його дає окремий
    пошук за назвою парафії.
    """

    id: str
    title: str
    info: str = ""
    lat: float | None = None
    lng: float | None = None
    tags: tuple[str, ...] = ()
    cases: int = 0
    #: Справи, у яких ця парафія трапилась, коли їх уже питали.
    books: tuple[str, ...] = field(default=())


def case_page(full_code: str) -> str:
    """Адреса справи на сайті покажчика.

    🔴 Саме сторінка покажчика, а не пряме посилання на копію. Цього просить
    дока сервісу, і причина практична: адреси копій переїжджають, потрапляють
    за скорочувачі й ламаються без попередження, а сторінка покажчика лишається.
    """
    parts = [p for p in (full_code or "").split("-") if p]
    if len(parts) != 4:
        return f"{HOST}/archives"
    return f"{HOST}/archives/" + "/".join(quote(p) for p in parts)


def split_code(full_code: str) -> tuple[str, str, str, str]:
    """«ДАХмО-230-1-2А» → (архів, фонд, опис, справа). Порожньо — не розібрали.

    ⚠ Розбір рівно на чотири частини. Шифра з дефісом усередині номера справи
    («2-а») зустрічається, і тоді розбір мовчки з'їхав би на один сегмент —
    фонд став би описом. Хай краще така знахідка лишиться без фонду, ніж
    припишеться чужому.
    """
    parts = (full_code or "").split("-")
    if len(parts) != 4 or not all(p.strip() for p in parts):
        return ("", "", "", "")
    return (parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip())


def _years(raw: Any) -> str:
    """`[{start_year, end_year}]` → «1802-1841». Порожньо — коли років немає."""
    if not isinstance(raw, list) or not raw:
        return ""
    first = raw[0] if isinstance(raw[0], dict) else {}
    y1 = str(first.get("start_year") or "")
    y2 = str(first.get("end_year") or y1)
    if not y1:
        return ""
    return y1 if y1 == y2 else f"{y1}-{y2}"


def _num(raw: Any) -> float | None:
    """Координата з відповіді. Не число — порожньо, а не нуль.

    🔴 Нуль замість «немає» відправив би парафію в Гвінейську затоку, і
    гео-запит навколо неї віддав би чужі справи мовчки.
    """
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _no_latin(body: dict[str, Any]) -> None:
    """Латинська літера в текстовому полі — жорстке 400, а не порожня видача.

    У каталозі латинських даних немає взагалі, тож це вхідне правило сервісу, а
    не здогад. Ловимо до запиту: інакше відмова прийде як помилка мережі й
    читатиметься як «сервіс не відповів».
    """
    for key in ("title", "place", "author"):
        val = str(body.get(key) or "")
        if any("a" <= ch.lower() <= "z" for ch in val):
            raise SourceError(
                f"поле «{key}» латинкою («{val}») — покажчик приймає лише "
                "кирилицю й відповідає на таке відмовою")


def name_forms(name: str) -> list[str]:
    """Написання назви поселення, під якими його міг записати набірник.

    🔴 Покажчик зводить чужі описи, а описи писані ким завгодно і коли завгодно:
    те саме містечко стоїть там і сучасною назвою з апострофом, і без нього, і
    формою мови діловодства XIX ст. Пошук іде підрядком і звіряє буквально, тож
    один запит одним написанням дає нуль, який виглядає як відповідь.

    Що робиться: знімається апостроф, суфікс -ків переходить у -ков, «і», «ї»,
    «є», «ґ» — у свої відповідники, і до кожного написання додається корінь без
    закінчення (інакше підрядок не переживе жодного відмінка).

    ⚠ Це розширення пошуку, а не переклад: форма-здогад годиться, щоб знайти,
    і не годиться, щоб щось стверджувати. Історичну назву — ту, що змінилась, а
    не переписалась, — жодне правило не виведе, її подає той, хто питає.
    """
    base = " ".join((name or "").split())
    if not base:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = value.strip(" ,.")
        if len(v) >= 4 and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)

    plain = base.replace("'", "").replace("’", "")
    add(base)
    add(plain)
    add(plain.replace("ків", "ков").replace("і", "и").replace("ї", "и")
        .replace("є", "е").replace("ґ", "г"))
    for value in list(out):
        if len(value) > 5 and value[-1] in "аяоеиіу":
            add(value[:-1])
    return out

class DuckSource:
    """Пошук по зведеному покажчику. Живий запит, без каталогу на диску."""

    id = "duck"
    label = "Duck Inspector (зведений покажчик)"
    caps = frozenset({"search"})

    #: Стеля видачі сервісу. Читається ззовні: рівно стільки знахідок означає
    #: обрізку, а не повний перелік.
    search_ceiling = CEILING

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        # `delay=0`, бо темп тримає черга: два механізми складалися б, і
        # обіцяний час перестав би збігатися з дійсністю.
        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        return Fetcher(base=HOST, delay=0.0, limiter=lim,
                       headers={"User-Agent": app_ua()})

    @staticmethod
    def _our_repo(archive_code: str) -> str:
        """Код архіву покажчика → наш код. Порожньо, коли архів нам невідомий.

        Порожній рядок тут кращий за чужий код: підставлений замість нашого,
        він завів би архів, якого в паку немає, і питання «чи є цей фонд у нас»
        отримало б відповідь про фонд, якого ми не тримаємо.
        """
        from nyshporka.archives import active

        return active().repo_for_code("duck", archive_code)

    def fond_card(self, archive_code: str, fond: str) -> dict[str, Any]:
        """Картка фонду покажчика: назва, описи, роки — одним запитом.

        🔴 Це те, чим фонд оцінюють ПЕРЕД тим, як збирати його реєстр. Пошук
        віддає окремі справи, а рішення приймають про фонд цілком: чи той це
        архів, чи ті роки, скільки в ньому описів і чи є там взагалі те, заради
        чого його збирати. Доти між знахідкою і збиранням реєстру не було
        нічого — тобто оцінювали навмання або не оцінювали зовсім.

        ⚠ Один запит, і саме про фонд. Порахувати справи в кожному описі коштує
        запиту на опис, тобто десятків секунд під лімітом сервісу; для рішення
        «варте / не варте» вистачає переліку описів із роками, а точний обсяг
        рахує вже сам збирач реєстру.
        """
        if offline() and self._fetcher is None:
            raise SourceError(
                "мережу вимкнено в цьому середовищі — покажчик не опитано")
        code = " ".join((archive_code or "").split())
        num = " ".join((fond or "").split())
        if not code or not num:
            raise SourceError("картка фонду потребує і архіву, і номера фонду")
        path = f"/api/catalog/{quote(code)}/{quote(num)}"
        try:
            data = json.loads(getattr(self._http().get(path), "text", "") or "{}")
        except (HttpError, OSError) as exc:
            raise SourceError(f"покажчик не відповів: {exc}") from exc
        except ValueError:
            raise SourceError(
                f"у покажчику немає фонду {code}-{num}") from None
        if not isinstance(data, dict) or not data.get("code"):
            raise SourceError(f"у покажчику немає фонду {code}-{num}")
        opys = []
        for i in data.get("inventories") or []:
            if not isinstance(i, dict):
                continue
            opys.append({"opys": str(i.get("code") or ""),
                         "title": " ".join(str(i.get("title") or "").split()),
                         "years": _years(i.get("years"))})
        return {"archive": code, "fond": num,
                "title": " ".join(str(data.get("title") or "").split()),
                "years": _years(data.get("years")),
                "opys": opys,
                "url": f"{HOST}/archives/{quote(code)}/{quote(num)}"}

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """На чому шукає. Тут — ні на чому з диска: запит іде в сервіс.

        🔴 Окремий стан `live`, а не «вкладений зріз» із порожньою датою.
        Різниця в тому, що саме означає нуль: у зрізі — «не було на дату
        зняття», у живому запиті — «немає в покажчику зараз». Звести їх до
        одного рядка означало б приписати живій відповіді чужу давність.
        """
        return "live", {"taken": "", "rows": None,
                        "scope": "43 архіви України", "host": HOST}

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Пошук по заголовках справ у всіх архівах покажчика.

        ⚠ Запит іде без звуження на архів навмисно: сенс цього джерела саме в
        тому, що воно відповідає «де взагалі є», коли архів наперед невідомий.
        Ціна — стеля 50 на широкому слові, і про неї попереджають окремо.
        """
        needle = " ".join((q or "").split())
        if not needle:
            return []
        # 🔴 Вимкнена мережа — це відмова, а не порожня видача: інакше вона
        # читалася б як «в архівах такого немає», і саме в тому джерелі, яке
        # додано, щоб цього висновку не робили передчасно.
        if offline() and self._fetcher is None:
            raise SourceError(
                "мережу вимкнено в цьому середовищі — покажчик не опитано")
        http = self._http()
        try:
            r = http.post("/api/search", json_body={"title": needle})
            rows = json.loads(getattr(r, "text", "") or "[]")
        except (HttpError, OSError) as exc:
            raise SourceError(f"покажчик не відповів: {exc}") from exc
        except ValueError:
            # Сервіс віддає HTML сторінки там, де шляху не існує, — мовчазний
            # порожній результат тут читався б як «такого немає в архівах».
            raise SourceError(
                "покажчик відповів не JSON — ендпоінт пошуку змінився") from None
        if not isinstance(rows, list):
            raise SourceError("покажчик відповів не переліком справ")
        out: list[Hit] = []
        # 🔴 Стеля сервісу не ховається за `limit`. Різати рівно по `limit`
        # означало б, що при `limit=40` видача з рівно п'ятдесяти повертається
        # сорока — і обрізка, зроблена сервісом, стає невидимою: перелік
        # виглядає повним, хоч ним не є. Зайві рядки все одно відсіє виклик
        # вище, а ознака обрізки доживе до попередження.
        for x in rows[:max(limit, CEILING)]:
            if not isinstance(x, dict):
                continue
            code = str(x.get("full_code") or "")
            arch, fond, _opys, _spr = split_code(code)
            # 🌐 Позначка «є копія онлайн» — це причина відкрити сторінку, а не
            # обіцянка завантаження: адреси копій покажчик тримає в себе.
            mark = "🌐 копія онлайн" if x.get("is_online") else ""
            out.append(Hit(
                source=self.id,
                ref=f"case:{code}",
                title=str(x.get("title") or "")[:200],
                years=_years(x.get("years")),
                shifra=code,
                repo=self._our_repo(arch),
                archive=arch,
                fond=fond,
                # 🔴 Нічого не віддає: покажчик, а не сховище.
                acquirable=False,
                note=mark,
                url=case_page(code)))
        return out

    # ── канали понад пошук по заголовку ──────────────────────────────────────
    #
    # 🔑 Усе нижче спирається на прив'язку справи до ПАРАФІЇ, і саме її немає в
    # жодному описі. Заголовок каже «Сповідальні відомості церков повіту»;
    # покажчик на ту саму справу каже, які саме церкви в ній, — і на питання
    # «чи варто відкривати цю книгу» відповідає один запит замість прогону.

    def _fetch(self, path: str, *, body: Any = None, what: str = "") -> Any:
        """Один вихід у покажчик. Не-JSON — відмова, а не порожня відповідь.

        🔴 Сервіс віддає HTML сторінки там, де шляху не існує (Next.js ковтає
        сегмент як «локаль»), і з кодом 200. Порожній результат тут читався б
        як «такого в архівах немає» — тобто як знаменник негативу.
        """
        if offline() and self._fetcher is None:
            raise SourceError(
                "мережу вимкнено в цьому середовищі — покажчик не опитано")
        http = self._http()
        try:
            r = (http.post(path, json_body=body) if body is not None
                 else http.get(path))
            return json.loads(getattr(r, "text", "") or "null")
        except (HttpError, OSError) as exc:
            raise SourceError(f"покажчик не відповів: {exc}") from exc
        except ValueError:
            tail = f" на {what}" if what else ""
            raise SourceError(
                f"покажчик відповів не JSON{tail} — такого ендпоінта немає"
            ) from None

    def parishes(self, q: str) -> list[Parish]:
        """Парафії за підрядком назви — церква, костел і синагога окремо.

        🕍 Три конфесії одного містечка — три різні записи, і книги їхні лежать
        у різних справах. Питати одну означає систематично не бачити решти:
        замір по містечку Подільської губернії — 10 книг православної парафії,
        4 костельні, 5 рабинату.

        ⚠ Тег конфесії буває хибний (костел трапляється з тегом православ'я) —
        вірити назві парафії, не тегові.

        🔴 Підрядок звіряється буквально: написання з апострофом не збігається
        з написанням без нього, а історична назва — із сучасною. Форми назви
        готує той, хто кличе, а не цей метод.
        """
        needle = " ".join((q or "").split())
        if not needle:
            return []
        rows = self._fetch(f"/api/authors?q={quote(needle)}", what="/api/authors")
        if not isinstance(rows, list):
            raise SourceError("покажчик відповів не переліком парафій")
        out: list[Parish] = []
        for x in rows:
            if not isinstance(x, dict) or not x.get("id"):
                continue
            count = x.get("_count")
            out.append(Parish(
                id=str(x.get("id") or ""),
                title=" ".join(str(x.get("title") or "").split()),
                info=" ".join(str(x.get("info") or "").split()),
                lat=_num(x.get("lat")), lng=_num(x.get("lng")),
                tags=tuple(str(t) for t in (x.get("tags") or [])),
                cases=int(count.get("file_authors") or 0)
                if isinstance(count, dict) else 0))
        return out

    def find_files(self, *, title: str = "", place: str = "", author: str = "",
                   archive: str = "", fond: str = "", inventory: str = "",
                   tags: tuple[str, ...] = (), year_from: str = "",
                   year_to: str = "", online: bool | None = None,
                   lat: str = "", lng: str = "", radius_m: int = 0,
                   fuzziness: float = 0.0) -> list[Hit]:
        """Пошук справ усіма полями, які приймає сервіс.

        Канали, яких немає в пошуку по заголовку:

        * `place` шукає в **анотації** справи, а не в назві, — тобто знаходить
          світські справи, де село згадане в описі події, а в заголовку його
          немає ніколи;
        * `author` дає повний перелік книг названої парафії;
        * `lat`/`lng`/`radius_m` — коло сусідніх сіл одразу справами;
        * `tags` — тип документа: метрична книга, сповідальні відомості, роль
          акту, конфесія.

        🔴 `place` і гео взаємно виключні — сервіс віддає 400. Тут перемагає
        гео: воно задане числами й помилитись у ньому нічим, а `place`
        лишається окремим запитом.
        """
        body: dict[str, Any] = {}
        for key, val in (("title", title), ("place", place), ("author", author),
                         ("archive", archive), ("fond", fond),
                         ("inventory", inventory), ("year_from", year_from),
                         ("year_to", year_to)):
            if str(val).strip():
                body[key] = str(val).strip()
        if tags:
            body["tags"] = [t for t in tags if t]
        if online is not None:
            body["is_online"] = online
        if lat and lng and radius_m > 0:
            body.pop("place", None)
            body["lat"], body["lng"] = str(lat), str(lng)
            body["radius_m"] = int(radius_m)
        if fuzziness:
            # Нижче межі сервіс віддає 500, тобто запит не виконається зовсім.
            body["fuzziness"] = max(float(fuzziness), FUZZ_MIN)
        if not body:
            return []
        _no_latin(body)
        rows = self._fetch("/api/search", body=body, what="/api/search")
        if not isinstance(rows, list):
            raise SourceError("покажчик відповів не переліком справ")
        return [h for h in (self._hit(x) for x in rows) if h is not None]

    def near(self, lat: str, lng: str, *, radius_m: int,
             split_years: bool = False, **rest: Any) -> list[Hit]:
        """Справи в колі навколо точки, з обходом стелі за потреби.

        🔴 Знаменник цього каналу — не «скільки справ у радіусі», а «скільки
        парафій кола взагалі прив'язано»: справа без прив'язки до церкви з
        координатами в гео-пошук не потрапляє ніколи. Нуль тут не є нулем
        архіву, і звітувати ним не можна.
        """
        first = self.find_files(lat=lat, lng=lng, radius_m=radius_m, **rest)
        if not split_years or len(first) < CEILING or rest.get("year_from"):
            return first
        seen: dict[str, Hit] = {h.ref: h for h in first}
        narrow = {k: v for k, v in rest.items() if k not in ("year_from", "year_to")}
        for y1, y2 in YEAR_WINDOWS:
            for h in self.find_files(lat=lat, lng=lng, radius_m=radius_m,
                                     year_from=str(y1), year_to=str(y2), **narrow):
                seen.setdefault(h.ref, h)
        return list(seen.values())

    def case_card(self, full_code: str) -> dict[str, Any]:
        """Картка справи: роки, теги, ПАРАФІЇ всередині, всі онлайн-копії.

        🔥 Заради переліку парафій це й кличуть: зведена книга повіту віддає
        сотні церков поіменно (заміряно 157 і 186 у двох справах), тож питання
        «чи є моє село в цій книзі» коштує один запит замість прогону рушієм.

        ⚠ Порожній перелік парафій означає, що покажчик цю справу не розбирав,
        а не «села в ній немає». Знаменника в такому разі просто немає.
        """
        arch, fond, opys, spr = split_code(full_code)
        if not arch:
            raise SourceError(
                f"«{full_code}» не схоже на повний код справи "
                "(архів-фонд-опис-справа)")
        path = "/api/catalog/" + "/".join(quote(p) for p in (arch, fond, opys, spr))
        data = self._fetch(path, what=path)
        if not isinstance(data, dict) or not data.get("id"):
            raise SourceError(f"у покажчику немає справи {full_code}")
        parishes: list[Parish] = []
        for link in data.get("authors") or []:
            raw = link.get("author") if isinstance(link, dict) else None
            if not isinstance(raw, dict):
                continue
            parishes.append(Parish(
                id=str(raw.get("id") or ""),
                title=" ".join(str(raw.get("title") or "").split()),
                info=" ".join(str(raw.get("info") or "").split()),
                lat=_num(raw.get("lat")), lng=_num(raw.get("lng")),
                tags=tuple(str(t) for t in (raw.get("tags") or []))))
        copies: list[dict[str, str]] = []
        for c in data.get("online_copies") or []:
            if not isinstance(c, dict) or not c.get("url"):
                continue
            copies.append({
                "url": str(c.get("url") or ""),
                "availability": str(c.get("availability") or ""),
                "checked": str(c.get("checked_availability_at") or "")[:10]})
        code = str(data.get("full_code") or full_code)
        return {"code": code, "archive": arch, "fond": fond, "opys": opys,
                "spr": spr, "repo": self._our_repo(arch),
                "title": " ".join(str(data.get("title") or "").split()),
                "info": " ".join(str(data.get("info") or "").split()),
                "years": _years(data.get("years")),
                "tags": [str(t) for t in (data.get("tags") or [])],
                "updated": str(data.get("updated_at") or "")[:10],
                "parishes": parishes, "copies": copies, "url": case_page(code)}

    def _hit(self, x: Any) -> Hit | None:
        """Рядок видачі → знахідка. Не словник — пропускаємо, а не падаємо."""
        if not isinstance(x, dict):
            return None
        code = str(x.get("full_code") or "")
        arch, fond, _opys, _spr = split_code(code)
        online = "🌐 копія онлайн" if x.get("is_online") else ""
        tags = ", ".join(str(t) for t in (x.get("tags") or []))
        return Hit(source=self.id, ref=f"case:{code}",
                   title=str(x.get("title") or "")[:200],
                   years=_years(x.get("years")),
                   # 🔑 Анотація їде в `place`, і це не косметика: саме в ній
                   # сидять село й прізвища учасників у світських справах,
                   # заголовок яких про село не каже нічого.
                   place=" ".join(str(x.get("info") or "").split())[:200],
                   shifra=code, repo=self._our_repo(arch), archive=arch,
                   fond=fond, acquirable=False,
                   note=" · ".join(m for m in (online, tags) if m),
                   url=case_page(code))
