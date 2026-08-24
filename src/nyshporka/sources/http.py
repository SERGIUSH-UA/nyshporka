"""🌐 Один HTTP-клієнт на всі мережеві джерела.

Архіви, з якими тут говорять, — не CDN. Це відомчі сайти й приватні дзеркала на
одному сервері, і поводитись із ними треба відповідно: помірний темп, пауза між
запитами, відступ на 429 і 5xx. Спокуса зробити «швидше» тут коштує доступу —
не нашого особисто, а взагалі: сайт архіву лягає від десятка паралельних сесій.

🔴 Недоступність ≠ бан, і сплутати їх легко. `geno-dbase.ru` 2026-08-10
перестав відповідати на все, включно з головною, тоді як фронтенд лишався
живим; після інтенсивного качання це природно читається як відсічка за темпом.
Проба з ІНШОГО IP (SOCKS5 через VPS) дала той самий таймаут — сервер просто
лежав. Тому проксі тут не «обхід», а ПРИЛАД: він розрізняє «нас відсікли» і
«хост упав», і без цієї відповіді решта дій — здогади.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from nyshporka.core.xrate import CrossProcessLimiter

#: Спільна змінна на всі джерела: тунель один, і друга назва для нього лише
#: створювала б стан, коли частина трафіку йде повз прилад.
ENV_PROXY = "NYSHPORKA_PROXY_URL"
_LEGACY_ENV_PROXY = "MEGEN_PROXY_URL"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

#: Куди людина може вписати свій контакт для ввічливих API.
#: 🔴 Порожньо за замовчуванням, і автозаповнення НЕ БУВАЄ. Спокуса взяти пошту
#: з `git config user.email` виглядає турботою, а насправді це витік: адреса
#: поїхала б у кожен запит до чужого сайту, і людина дізналась би про це з
#: чужих логів. Хто хоче назватись — називається сам.
ENV_CONTACT = "NYSHPORKA_CONTACT"
HOMEPAGE = "https://github.com/SERGIUSH-UA/nyshporka"


def app_ua() -> str:
    """User-Agent для API, які вимагають, щоб клієнт назвався.

    Wikimedia і подібні відмовляють браузерному рядку від скрипта (403) — і
    мають рацію: інакше в їхніх логах усі однакові. Тут ідентифікує себе
    ЗАСТОСУНОК, а не людина: назва, версія, посилання на проєкт. Контакт
    додається, лише якщо його вписали в `NYSHPORKA_CONTACT`.

    ⚠ Попередник цього рядка ніс прізвище роду дослідника й особисту пошту, і
    їхав із ними в кожен запит до чужого сайту.
    """
    from nyshporka import __version__

    contact = os.environ.get(ENV_CONTACT, "").strip()
    ua = f"nyshporka/{__version__} (+{HOMEPAGE})"
    return f"{ua} {contact}" if contact else ua

#: Пауза між запитами до одного хоста. Не оптимізується.
DEFAULT_DELAY = 0.35
DEFAULT_TIMEOUT = 60.0
MAX_ATTEMPTS = 6


def proxy_url() -> str | None:
    return os.environ.get(ENV_PROXY) or os.environ.get(_LEGACY_ENV_PROXY) or None


class HttpError(RuntimeError):
    """Запит не вдався після всіх спроб."""


class Fetcher:
    """Тонка обгортка над `httpx.Client`: ввічливість і відступ в одному місці.

    Навмисно НЕ приховує httpx: джерела працюють із його відповідями напряму.
    Ховається рівно те, що інакше довелось би повторювати в кожному джерелі й
    що там неминуче розійшлося б — заголовки, пауза, політика повторів.
    """

    def __init__(self, *, base: str = "", delay: float = DEFAULT_DELAY,
                 timeout: float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None,
                 client: Any = None,
                 limiter: CrossProcessLimiter | None = None) -> None:
        self.base = base.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self._headers = {"User-Agent": UA, "Accept": "*/*", **(headers or {})}
        if base:
            self._headers.setdefault("Referer", f"{self.base}/")
        # Готовий клієнт — вхід для тестів: вони підставляють транспорт із
        # ЗАПИСАНИМИ відповідями. Тест мережевого джерела, що ходить у мережу,
        # перевіряє чужий сервер, а не наш розбір: він червонітиме від того, що
        # архів на профілактиці, і зеленітиме від того, що розмітка ще не
        # змінилась. Ні те, ні те не про наш код.
        self._client = client
        # 🔴 Ліміт, спільний на МАШИНУ, — не те саме, що `delay`. Пауза стримує
        # один процес; сервіси на кшталт Duck рахують темп по клієнту (IP), тож
        # дві сесії з бездоганною паузою дають подвійний темп. Хто ставить
        # лімітер, той зазвичай ставить `delay=0`: два механізми темпу накладно
        # складаються, і час очікування в плані перестає збігатися з дійсністю.
        self.limiter = limiter

    @contextmanager
    def client(self) -> Iterator[Any]:
        if self._client is not None:
            yield self._client
            return
        import httpx

        c = httpx.Client(headers=self._headers, timeout=self.timeout,
                         follow_redirects=True, proxy=proxy_url())
        try:
            yield c
        finally:
            c.close()

    def get(self, url: str, client: Any = None) -> Any:
        """GET із відступом. `url` може бути відносним, якщо задано `base`.

        Тип відповіді навмисно `Any`, а не `httpx.Response`: клієнтом буває
        двійник із записаними відповідями, і обіцяти тут конкретний клас httpx
        означало б збрехати рівно в тому місці, заради якого двійник існує.
        """
        full = url if url.startswith("http") else f"{self.base}{url}"
        if client is not None:
            return self._get_with(client, full)
        with self.client() as c:
            return self._get_with(c, full)

    def post(self, url: str, *, data: dict[str, Any] | None = None,
             json_body: Any = None, client: Any = None) -> Any:
        """POST із тією ж ввічливістю.

        Потрібен не для запису, а для ЧИТАННЯ: батч-запит до Commons на 50
        назв кирилицею не влазить у GET (сервер відповідає 414 на URL понад
        ~8 КБ), а пошук Duck приймає лише тіло.
        """
        full = url if url.startswith("http") else f"{self.base}{url}"
        if client is not None:
            return self._send(full, lambda: client.post(full, data=data, json=json_body))
        with self.client() as c:
            return self._send(full, lambda: c.post(full, data=data, json=json_body))

    def download(self, url: str, dest: Path, *, client: Any = None,
                 on_chunk: Callable[[int], None] | None = None,
                 chunk: int = 1 << 20) -> int:
        """Завантажити у файл потоком. Повертає число байтів.

        🔴 Пишемо в сусідній `.part` і перейменовуємо в кінці. Справа архіву —
        це сотні мегабайтів; обірваний файл, що лежить під правильним іменем,
        наступний запуск порахує завантаженим, а виявиться це через тижні —
        коли по ньому вже щось вирішили.

        ⚠ Повторів тут немає навмисно: половину великого файла не «повторюють»,
        її дочитують, а це інша задача (Range-запити). Обірване завантаження
        видно за розміром — його звіряє той, хто кликав.
        """
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.limiter is not None:
            self.limiter.acquire(url)
        got = 0
        if client is not None:
            got = self._stream_into(client, url, part, on_chunk, chunk)
        else:
            with self.client() as c:
                got = self._stream_into(c, url, part, on_chunk, chunk)
        part.replace(dest)
        return got

    def _stream_into(self, c: Any, url: str, part: Path,
                     on_chunk: Callable[[int], None] | None, chunk: int) -> int:
        got = 0
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with open(part, "wb") as fh:
                for block in r.iter_bytes(chunk):
                    fh.write(block)
                    got += len(block)
                    if on_chunk is not None:
                        on_chunk(got)
        return got

    def _get_with(self, c: Any, url: str) -> Any:
        return self._send(url, lambda: c.get(url))

    def _send(self, url: str, call: Callable[[], Any]) -> Any:
        """Спроби, відступ і ввічливість — в одному місці на GET і POST."""
        import httpx

        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # 🔴 Тікет береться НА КОЖНУ СПРОБУ, включно з повторами: для
            # сервера ретрай — такий самий запит, і саме серія повторів після
            # 429 найлегше перетворює ввічливого клієнта на заблокованого.
            if self.limiter is not None:
                self.limiter.acquire(url)
            try:
                r = call()
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                # 🔴 Відступ рівно на 429 і 5xx. 404 повторювати немає сенсу —
                # це відповідь, а не збій, і шість спроб на неї лише
                # розтягують очікування там, де відповідь уже відома.
                if r.status_code != 429 and r.status_code < 500:
                    # 🔴 Статусна помилка виходить звідси як `HttpError`, а не
                    # як `httpx.HTTPStatusError`. Усі споживачі ловлять
                    # `(HttpError, OSError)`, тож «голий» httpx-виняток
                    # пролітав крізь цикл завантаження плівки: один 404 на
                    # кадрі №300 із 991 валив увесь прогін, губив лічильники
                    # 299 уже взятих кадрів і навіть не давав спрацювати
                    # запобіжнику «10 промахів поспіль».
                    try:
                        r.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise HttpError(f"{url}: HTTP {r.status_code}") from exc
                    if self.delay:
                        time.sleep(self.delay)
                    return r
                last = f"HTTP {r.status_code}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(60.0, 2 ** (attempt - 1)))
        raise HttpError(
            f"{url}: {last} після {MAX_ATTEMPTS} спроб. "
            f"⚠ Це може бути і відсічка за темпом, і те, що хост лежить, — "
            f"розрізняє їх лише проба з іншого IP ({ENV_PROXY}).")
