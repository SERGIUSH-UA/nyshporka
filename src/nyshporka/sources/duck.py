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
