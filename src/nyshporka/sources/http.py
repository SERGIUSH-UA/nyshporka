"""🌐 Один HTTP-клієнт на всі мережеві джерела.

Архіви, з якими тут говорять, — не CDN. Це відомчі сайти й приватні дзеркала на
одному сервері, і поводитись із ними треба відповідно: помірний темп, пауза між
запитами, відступ на 429 і 5xx. Спокуса зробити «швидше» тут коштує доступу —
не нашого особисто, а взагалі: сайт архіву лягає від десятка паралельних сесій.

🔴 Недоступність ≠ бан, і сплутати їх легко. `geno-dbase.ru` 2026-08-10
перестав відповідати на все, включно з головною, тоді як фронтенд лишався
живим; після інтенсивного качання це природно читається як відсічка за темпом.
Проба з іншого IP (SOCKS5 через VPS) дала той самий таймаут — сервер просто
лежав. Тому проксі тут не «обхід», а прилад: він розрізняє «нас відсікли» і
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
#: 🔴 Порожньо за замовчуванням, і автозаповнення не буває. Спокуса взяти пошту
#: з `git config user.email` виглядає турботою, а насправді це витік: адреса
#: поїхала б у кожен запит до чужого сайту, і людина дізналась би про це з
#: чужих логів. Хто хоче назватись — називається сам.
ENV_CONTACT = "NYSHPORKA_CONTACT"
HOMEPAGE = "https://github.com/SERGIUSH-UA/nyshporka"


def app_ua() -> str:
    """User-Agent для API, які вимагають, щоб клієнт назвався.

    Wikimedia і подібні відмовляють браузерному рядку від скрипта (403) — і
    мають рацію: інакше в їхніх логах усі однакові. Тут ідентифікує себе
    застосунок, а не людина: назва, версія, посилання на проєкт. Контакт
    додається, лише якщо його вписали в `NYSHPORKA_CONTACT`.

    ⚠ Попередник цього рядка ніс прізвище роду дослідника й особисту пошту, і
    їхав із ними в кожен запит до чужого сайту.
    """
    from nyshporka import __version__

    contact = os.environ.get(ENV_CONTACT, "").strip()
    ua = f"nyshporka/{__version__} (+{HOMEPAGE})"
    return f"{ua} {contact}" if contact else ua

#: Скільки чекати на з'єднання по IPv4, перш ніж спробувати звичайний шлях.
IPV4_CONNECT_S = 15.0

#: Процес уже бачив, що IPv4 не з'єднується, а звичайний шлях — так. Далі
#: IPv4 першим не пробується: кожна спроба коштувала б зайвого відмовлення.
_IPV4_NE_PRATSIUIE = False


def _sertyfikat(exc: Exception) -> bool:
    nyzh = str(exc).lower()
    return "certificate_verify_failed" in nyzh or "certificate verify failed" in nyzh


def transport(proxy: str | None = None) -> Any:
    """Транспорт httpx: спершу IPv4, звичайний шлях — запасний.

    🔴 28.09.2026 у людини кожне нове з'єднання Нишпорки висіло ~43 с: DNS
    віддає Cloudflare (і пул, і сховище) по дві IPv6-адреси, Windows пробує
    їх першими, а IPv6 у тій мережі мертвий — дві адреси по ~21 с таймауту
    SYN, і лише тоді IPv4. Три з'єднання на внесок (PUT тексту, PUT
    геометрії, `complete`) давали 129 с на справу будь-якого розміру, хоча
    сам пул відповідав за секунду. Браузер цього не бачить — він перемикається
    за частки секунди (Happy Eyeballs), httpx — ні.

    IPv4 першим, бо без нього нині не живе жоден сайт, з яким говорить
    Нишпорка. Запасний шлях — для мережі лише з IPv6: там прив'язка до
    0.0.0.0 відмовляє одразу (`getaddrinfo`), а не таймаутом.
    """
    import urllib.request

    import httpx

    # Проксі з оточення чи з налаштувань системи httpx підхоплює лише тоді,
    # коли транспорт не задано. Тоді й не задаємо: з'єднання однаково йде до
    # проксі, а не до IPv6-адрес сховища.
    if proxy is None and {"https", "http", "all"} & set(urllib.request.getproxies()):
        return None

    class _SpershuIpv4(httpx.BaseTransport):
        def __init__(self) -> None:
            self._v4: httpx.HTTPTransport | None = None
            self._zvychainyi: httpx.HTTPTransport | None = None

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            global _IPV4_NE_PRATSIUIE
            if not _IPV4_NE_PRATSIUIE:
                if self._v4 is None:
                    self._v4 = httpx.HTTPTransport(local_address="0.0.0.0", proxy=proxy)
                # Коротший ліміт на з'єднання лише для IPv4-спроби: мертвий
                # IPv4 не мусить тримати людину всі п'ять хвилин PUT.
                orig = request.extensions.get("timeout")
                if orig is not None:
                    limit_z = orig.get("connect")
                    if limit_z is None or limit_z > IPV4_CONNECT_S:
                        request.extensions["timeout"] = {**orig, "connect": IPV4_CONNECT_S}
                try:
                    return self._v4.handle_request(request)
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    # Перехоплений HTTPS однаковий на будь-якому шляху —
                    # запасний лише затримав би людину й сховав причину.
                    if _sertyfikat(exc):
                        raise
                finally:
                    if orig is not None:
                        request.extensions["timeout"] = orig
                # До з'єднання не пішло жодного байта, тож повтор безпечний.
                if self._zvychainyi is None:
                    self._zvychainyi = httpx.HTTPTransport(proxy=proxy)
                # Упав і він — віддаємо його помилку: саме її дав би httpx без
                # цієї обгортки, і за нею класифікують збій (`_klas_obryvu`).
                resp = self._zvychainyi.handle_request(request)
                _IPV4_NE_PRATSIUIE = True
                return resp
            if self._zvychainyi is None:
                self._zvychainyi = httpx.HTTPTransport(proxy=proxy)
            return self._zvychainyi.handle_request(request)

        def close(self) -> None:
            for t in (self._v4, self._zvychainyi):
                if t is not None:
                    t.close()

    return _SpershuIpv4()


#: Пауза між запитами до одного хоста. Не оптимізується.
DEFAULT_DELAY = 0.35
DEFAULT_TIMEOUT = 60.0
MAX_ATTEMPTS = 6


def proxy_url() -> str | None:
    return os.environ.get(ENV_PROXY) or os.environ.get(_LEGACY_ENV_PROXY) or None


#: Заборона ходити в мережу. Ставиться середовищем, а не людиною.
ENV_OFFLINE = "NYSHPORKA_NO_NETWORK"


def offline() -> bool:
    """Чи заборонено мережу в цьому середовищі.

    🔴 Потрібне тестам, і не з міркувань швидкості. Джерело, яке шукає живим
    запитом, перетворює кожен прогін набору на стук у чужий сервер: `catalog.
    search` кличуть і тест конверта, і той, що проходить усіма операціями
    реєстру підряд. Волонтерський покажчик просить п'ять запитів на десять
    секунд і блокує без попередження — тобто зелений набір на машині
    розробника оплачувався б чужою інфраструктурою й закінчився б баном.

    ⚠ Це не «режим офлайну» для людини: жодного інтерфейсу тут немає навмисно.
    Джерело, яке впирається в цей прапорець, мусить сказати про це вголос
    (`SourceError`), а не віддати порожній результат — інакше вимкнена мережа
    читалася б як «в архівах такого немає».
    """
    return bool(os.environ.get(ENV_OFFLINE, "").strip())


class HttpError(RuntimeError):
    """Запит не вдався після всіх спроб.

    `status` і `body` — що саме відповів сервер. 🔴 Тіло несе причину: пул
    пише в нього, котрі саме ворота не пропустили внесок чи що денна норма
    вичерпана, і без нього людина бачила б голе «HTTP 400».
    """

    def __init__(self, message: str, *, status: int | None = None,
                 body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _body_of(r: Any, limit: int = 2000) -> str:
    """Тіло відповіді для звіту про помилку — обрізане й без падінь."""
    try:
        return str(r.text or "")[:limit]
    except Exception:
        return ""


class TooLarge(HttpError):
    """Відповідь більша за дозволену стелю — качання обірвано."""


def _capped_get(c: Any, url: str, max_bytes: int) -> Any:
    """GET, що читає тіло потоком і не бере більше `max_bytes`.

    Повертає звичайну відповідь httpx із уже прочитаним тілом, тож далі з нею
    працюють як завжди (`.content`, `.text`, `.json()`). Двійник без `stream`
    (тести) віддає тіло цілком — тоді стеля звіряється вже по ньому.
    """
    import httpx

    if not hasattr(c, "stream"):
        r = c.get(url)
        if len(getattr(r, "content", b"") or b"") > max_bytes:
            raise TooLarge(f"{url}: більше {max_bytes} байт — відповідь відкинуто")
        return r
    with c.stream("GET", url) as r:
        declared = str(r.headers.get("content-length") or "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise TooLarge(f"{url}: сервер заявляє {declared} байт — більше "
                           f"стелі {max_bytes}")
        got = 0
        chunks: list[bytes] = []
        for block in r.iter_bytes():
            got += len(block)
            if got > max_bytes:
                raise TooLarge(f"{url}: більше {max_bytes} байт — качання обірвано")
            chunks.append(block)
        # Тіло вже розпаковане (`iter_bytes` знімає gzip транспорту), тож
        # заголовки кодування й довжини в нову відповідь не переносяться:
        # інакше httpx спробував би розпакувати його вдруге.
        headers = [(k, v) for k, v in r.headers.multi_items()
                   if k.lower() not in ("content-encoding", "content-length",
                                        "transfer-encoding")]
        return httpx.Response(r.status_code, headers=headers,
                              content=b"".join(chunks), request=r.request)


class Fetcher:
    """Тонка обгортка над `httpx.Client`: ввічливість і відступ в одному місці.

    Навмисно не приховує httpx: джерела працюють із його відповідями напряму.
    Ховається рівно те, що інакше довелось би повторювати в кожному джерелі й
    що там неминуче розійшлося б — заголовки, пауза, політика повторів.
    """

    def __init__(self, *, base: str = "", delay: float = DEFAULT_DELAY,
                 timeout: float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None,
                 client: Any = None,
                 limiter: CrossProcessLimiter | None = None,
                 attempts: int = MAX_ATTEMPTS, retry_429: bool = True) -> None:
        self.base = base.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        # 🔴 Шість спроб із відступом — для архівів, які лежать хвилинами.
        # Свій сервер, що відповідає «норму вичерпано» (429) або лежить, під
        # тим самим правилом тримав би людину пів хвилини перед кожним
        # прогоном; тому число спроб і повтор на 429 — ручки виклику.
        self.attempts = max(1, int(attempts))
        self.retry_429 = retry_429
        self._headers = {"User-Agent": UA, "Accept": "*/*", **(headers or {})}
        if base:
            self._headers.setdefault("Referer", f"{self.base}/")
        # Готовий клієнт — вхід для тестів: вони підставляють транспорт із
        # записаними відповідями. Тест мережевого джерела, що ходить у мережу,
        # перевіряє чужий сервер, а не наш розбір: він червонітиме від того, що
        # архів на профілактиці, і зеленітиме від того, що розмітка ще не
        # змінилась. Ні те, ні те не про наш код.
        self._client = client
        # 🔴 Ліміт, спільний на машину, — не те саме, що `delay`. Пауза стримує
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
                         follow_redirects=True, transport=transport(proxy_url()))
        try:
            yield c
        finally:
            c.close()

    def get(self, url: str, client: Any = None, *, max_bytes: int = 0) -> Any:
        """GET із відступом. `url` може бути відносним, якщо задано `base`.

        Тип відповіді навмисно `Any`, а не `httpx.Response`: клієнтом буває
        двійник із записаними відповідями, і обіцяти тут конкретний клас httpx
        означало б збрехати рівно в тому місці, заради якого двійник існує.

        `max_bytes` — стеля тіла. 🔴 Без неї `get` читає відповідь цілком у
        пам'ять, скільки б сервер не прислав: адреса, взята з чужої сторінки
        (дзеркало плівок), могла вести на гігабайти (аудит 29.09.2026). Зі
        стелею тіло читається потоком і обривається `TooLarge`, щойно її
        перейдено, — ще до того, як зайвий байт ліг у пам'ять.
        """
        full = url if url.startswith("http") else f"{self.base}{url}"
        if client is not None:
            return self._get_with(client, full, max_bytes)
        with self.client() as c:
            return self._get_with(c, full, max_bytes)

    def post(self, url: str, *, data: dict[str, Any] | None = None,
             json_body: Any = None, client: Any = None) -> Any:
        """POST із тією ж ввічливістю.

        Потрібен не для запису, а для читання: батч-запит до Commons на 50
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
                 chunk: int = 1 << 20, max_bytes: int = 0) -> int:
        """Завантажити у файл потоком. Повертає число байтів.

        🔴 Пишемо в сусідній `.part` і перейменовуємо в кінці. Справа архіву —
        це сотні мегабайтів; обірваний файл, що лежить під правильним іменем,
        наступний запуск порахує завантаженим, а виявиться це через тижні —
        коли по ньому вже щось вирішили.

        ⚠ Повторів тут немає навмисно: половину великого файла не «повторюють»,
        її дочитують, а це інша задача (Range-запити). Обірване завантаження
        видно за розміром — його звіряє той, хто кликав.

        🔴 Будь-яка відмова виходить як `HttpError`, а не сирий виняток httpx:
        споживачі ловлять `(HttpError, OSError)`, і 404 на одному файлі інакше
        валив увесь цикл завантаження — та сама вада, що вже була в `_send`.

        `max_bytes` — стеля: файл від незнайомця (пакет обміну) не має права
        заповнити диск. Перевищення обриває качання й прибирає `.part`.
        """
        import httpx

        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.limiter is not None:
            self.limiter.acquire(url)
        got = 0
        try:
            if client is not None:
                got = self._stream_into(client, url, part, on_chunk, chunk, max_bytes)
            else:
                with self.client() as c:
                    got = self._stream_into(c, url, part, on_chunk, chunk, max_bytes)
        except httpx.HTTPStatusError as exc:
            part.unlink(missing_ok=True)
            code = exc.response.status_code
            raise HttpError(f"{url}: HTTP {code}", status=code,
                            body=_body_of(exc.response)) from exc
        except httpx.HTTPError as exc:
            part.unlink(missing_ok=True)
            raise HttpError(f"{url}: {type(exc).__name__}: {exc}") from exc
        except HttpError:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)
        return got

    def _stream_into(self, c: Any, url: str, part: Path,
                     on_chunk: Callable[[int], None] | None, chunk: int,
                     max_bytes: int = 0) -> int:
        got = 0
        with c.stream("GET", url) as r:
            if int(getattr(r, "status_code", 200) or 200) >= 400:
                # Тіло відмови — у звіт (`HttpError.body`): потокова відповідь
                # без `read()` його не віддає.
                r.read()
            r.raise_for_status()
            with open(part, "wb") as fh:
                for block in r.iter_bytes(chunk):
                    got += len(block)
                    if max_bytes and got > max_bytes:
                        raise TooLarge(f"{url}: більше {max_bytes} байт — "
                                       f"качання обірвано")
                    fh.write(block)
                    if on_chunk is not None:
                        on_chunk(got)
        return got

    def _get_with(self, c: Any, url: str, max_bytes: int = 0) -> Any:
        if not max_bytes:
            return self._send(url, lambda: c.get(url))
        return self._send(url, lambda: _capped_get(c, url, max_bytes))

    def _send(self, url: str, call: Callable[[], Any]) -> Any:
        """Спроби, відступ і ввічливість — в одному місці на GET і POST."""
        import httpx

        last = ""
        status: int | None = None
        body = ""
        for attempt in range(1, self.attempts + 1):
            # 🔴 Тікет береться на кожну спробу, включно з повторами: для
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
                if r.status_code == 429 and not self.retry_429:
                    raise HttpError(f"{url}: HTTP 429", status=429, body=_body_of(r))
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
                        raise HttpError(f"{url}: HTTP {r.status_code}",
                                        status=r.status_code, body=_body_of(r)) from exc
                    if self.delay:
                        time.sleep(self.delay)
                    return r
                last = f"HTTP {r.status_code}"
                status, body = r.status_code, _body_of(r)
            if attempt < self.attempts:
                time.sleep(min(60.0, 2 ** (attempt - 1)))
        raise HttpError(
            f"{url}: {last} після {self.attempts} спроб. "
            f"⚠ Це може бути і відсічка за темпом, і те, що хост лежить, — "
            f"розрізняє їх лише проба з іншого IP ({ENV_PROXY}).",
            status=status, body=body)
