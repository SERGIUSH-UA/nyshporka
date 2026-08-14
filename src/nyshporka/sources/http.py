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
    from collections.abc import Iterator

#: Спільна змінна на всі джерела: тунель один, і друга назва для нього лише
#: створювала б стан, коли частина трафіку йде повз прилад.
ENV_PROXY = "NYSHPORKA_PROXY_URL"
_LEGACY_ENV_PROXY = "MEGEN_PROXY_URL"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

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
                 client: Any = None) -> None:
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

    def _get_with(self, c: Any, url: str) -> Any:
        import httpx

        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                r = c.get(url)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                # 🔴 Відступ рівно на 429 і 5xx. 404 повторювати немає сенсу —
                # це відповідь, а не збій, і шість спроб на неї лише
                # розтягують очікування там, де відповідь уже відома.
                if r.status_code != 429 and r.status_code < 500:
                    r.raise_for_status()
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
