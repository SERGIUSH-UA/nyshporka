"""🛡 Клієнт для сайтів за Cloudflare, які відсікають нас по TLS-відбитку.

Звичайний `httpx` тут не проходить, і не через заголовки: Cloudflare у режимі
«managed challenge» дивиться на відбиток самого TLS-рукостискання (JA3/JA4).
Заміряно на `babynyar.org` 09.09.2026 — `httpx` із повним набором браузерних
заголовків дістає 403 «Just a moment…» на КОЖНУ адресу, включно з відкритим
API, тоді як `curl` тим самим заголовкам віддає 200 з першої спроби.

🔴 Cloudflare реагує тут ДВОМА різними способами, і плутати їх дорого:

    відбиток   httpx, будь-який запит    не минає ніколи, скільки не чекай
    темп       curl / curl_cffi, серія   минає за ~20 с (заміряно, див. `get`)

Перше лікується лише іншим клієнтом, друге — лише паузою. Джерело, яке їх не
розрізняє, або радить чекати там, де чекати марно, або валить обхід там, де
досить було постояти двадцять секунд. Саме друге й сталося на першій версії
цього модуля: обхід ~900 сторінок падав кожні 12-24 запити.

Два шляхи, і жоден не вигадує даних:

    curl_cffi   — той самий libcurl, що вміє вдавати рукостискання Chrome.
                  Ставиться як `pip install nyshporka[cfshield]`. Витримує
                  довшу серію без виклику (заміряно: 23 запити проти 12).
    curl        — системний бінарник через `subprocess`. Є майже скрізь, і
                  його рукостискання Cloudflare теж пропускає.

⚠ Немає обох — клієнт каже про це ВГОЛОС і не віддає порожньої відповіді.
Мовчазний нуль тут читався б як «в архіві такого немає», а це найдорожча
відповідь у генеалогії: вона закриває напрям пошуку.

Відповідь навмисно вдає `httpx.Response` рівно в тому, що читають джерела
(`status_code`, `text`, `content`, `.json()`), а помилка транспорту виходить
звідси як `httpx.TransportError` — щоб повтори й відступ на 5xx лишились у
`Fetcher` і не з'явилось другого місця, де живе загальна політика ввічливості.
"""
from __future__ import annotations

import json as _json
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

#: Браузер, якого вдаємо. Версія пінується навмисно: `impersonate="chrome"`
#: означає «найновіший, який знає бібліотека», тобто відбиток мінявся б від
#: оновлення залежності — і день, коли сайт почне відсікати, не мав би причини.
IMPERSONATE = "chrome131"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

#: Заголовки, які браузер шле на навігацію. Самі по собі вони Cloudflare не
#: обманюють (відбиток важливіший), але без них сайт віддає англійську версію.
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

#: Ознака сторінки-виклику. Cloudflare віддає її з кодом 403, але буває й 200 —
#: тобто за самим лише статусом виклик від справжньої сторінки не відрізнити.
CHALLENGE_MARKS = ("Just a moment", "cf_chl_opt", "challenge-platform")


class ShieldError(RuntimeError):
    """Пройти захист не вдалось — і причина сформульована для людини."""


def challenged(body: str) -> bool:
    """Чи це сторінка-виклик Cloudflare, а не відповідь сайту."""
    head = body[:4000]
    return any(m in head for m in CHALLENGE_MARKS)


@dataclass
class Response:
    """Рівно те з `httpx.Response`, що читають джерела."""

    status_code: int
    content: bytes
    url: str = ""
    encoding: str = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> Response:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code))
        return self


def have_curl_cffi() -> bool:
    try:
        import curl_cffi  # noqa: F401
    except Exception:
        return False
    return True


def have_curl() -> bool:
    try:
        r = subprocess.run(["curl", "--version"], capture_output=True, timeout=10,
                           check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def curl_config(options: dict[str, str]) -> bytes:
    """Рядки конфігу curl (`name = "value"`) для `--config -`.

    Значення береться в лапки, а зворотна риска, лапка й переводи рядка
    екрануються: інакше адреса з переводом рядка дописала б у конфіг чужу
    опцію, тобто підмінила б запит.
    """
    lines: list[str] = []
    for name, value in options.items():
        esc = (value.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r"))
        lines.append(f'{name} = "{esc}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


@dataclass
class CfClient:
    """Мінімальний клієнт: `.get(url)` і `.close()`.

    Тримає куки між запитами — Cloudflare видає `cf_clearance` після першої
    вдалої відповіді, і без нього кожен наступний запит починав би все спочатку.
    """

    timeout: float = 60.0
    headers: dict[str, str] = field(default_factory=lambda: dict(HEADERS))
    proxy: str | None = None
    #: Який шлях обрано: curl_cffi | curl. Читається діагностикою джерела.
    via: str = ""
    _session: Any = None
    _jar: Path | None = None
    _tmp: Any = None

    #: Пауза після сторінки-виклику і скільки разів її витримати. Підстава —
    #: замір у `get`: усі виклики минали за 20 с, тож 25 с — із запасом, а три
    #: паузи поспіль, які не допомогли, — уже не темп, а щось надовше.
    CHALLENGE_PAUSE_SEC = 25.0
    CHALLENGE_RETRIES = 3
    #: Чим чекати. Атрибут класу (не поле), щоб тест міг підмінити без годинника.
    _sleep = staticmethod(time.sleep)

    def __post_init__(self) -> None:
        if have_curl_cffi():
            from curl_cffi import requests as _cr

            self.via = "curl_cffi"
            self._session = _cr.Session(impersonate=IMPERSONATE,
                                        headers=self.headers,
                                        timeout=self.timeout,
                                        proxies={"https": self.proxy,
                                                 "http": self.proxy} if self.proxy else None)
            return
        if have_curl():
            self.via = "curl"
            self._tmp = tempfile.TemporaryDirectory(prefix="nysh-cf-")
            self._jar = Path(self._tmp.name) / "cookies.txt"
            return
        raise ShieldError(
            "цей сайт стоїть за Cloudflare, який відсікає клієнта по TLS-відбитку, "
            "а пройти його нічим: немає ні `curl_cffi`, ні системного `curl`. "
            "Полагодити: `pip install nyshporka[cfshield]` (або поставити curl). "
            "⚠ Без цього джерело мовчить не тому, що в архіві нічого немає.")

    # ── запит ────────────────────────────────────────────────────────────────

    def get(self, url: str) -> Response:
        """GET, що пережидає сторінку-виклик; відступ на 5xx лишається `Fetcher`.

        🔴 Виклик Cloudflare на цьому шляху МИНАЄ, і це заміряно, а не
        припущено (09.09.2026, 24 запити поспіль із паузою 0,35 с): `curl_cffi`
        дістав виклик на 24-му запиті, системний `curl` — на 13-му і 16-му; усі
        три рази через 20 с той самий запит пройшов. Тобто це відсічка за
        темпом, а не блокування клієнта, — і обхід без переждання падав би в
        середньому кожні 12-24 сторінки.

        ⚠ Пауза своя, а не відступ `Fetcher`: той розрахований на 5xx (1, 2, 4,
        8, 16 с), і першу чверть хвилини його спроби лише підтверджували б
        виклик, додаючи запитів туди, де сервер уже просить зупинитись.
        """
        for attempt in range(self.CHALLENGE_RETRIES + 1):
            r = self._once(url)
            if not challenged(r.text):
                return r
            if attempt < self.CHALLENGE_RETRIES:
                self._sleep(self.CHALLENGE_PAUSE_SEC)
        hint = ("" if self.via == "curl_cffi" else
                " Шлях `curl_cffi` витримує вдвічі довшу серію без виклику — "
                "`pip install nyshporka[cfshield]`.")
        raise ShieldError(
            f"{url}: Cloudflare тримає сторінку-виклик після "
            f"{self.CHALLENGE_RETRIES} пауз по {self.CHALLENGE_PAUSE_SEC:.0f} с "
            f"(шлях: {self.via}). Одиничний виклик тут минає за ~20 с — це "
            f"заміряно; такий, що не минає, означає, що сервер відсік цю адресу "
            f"надовше або посилив захист. Спробуйте пізніше: обхід продовжиться "
            f"з місця зупинки.{hint}")

    def _once(self, url: str) -> Response:
        """Один запит тим шляхом, що є, — без жодних повторів."""
        if self.via == "curl_cffi":
            return self._get_cffi(url)
        return self._get_curl(url)

    def _get_cffi(self, url: str) -> Response:
        from curl_cffi import requests as _cr

        try:
            r = self._session.get(url)
        except _cr.errors.RequestsError as exc:
            # 🔴 Виходить як помилка транспорту httpx навмисно: повтори, відступ
            # і ліміт живуть у `Fetcher`, і другий їх примірник тут розійшовся б
            # із першим — темп у плані перестав би збігатися з дійсністю.
            raise httpx.TransportError(f"curl_cffi: {exc}") from exc
        return Response(status_code=r.status_code, content=r.content, url=url)

    def _get_curl(self, url: str) -> Response:
        cmd = ["curl", "-s", "--compressed", "-L", "--max-time", str(int(self.timeout)),
               "-w", "\n%{http_code}", "-b", str(self._jar), "-c", str(self._jar)]
        for k, v in self.headers.items():
            cmd += ["-H", f"{k}: {v}"]
        # 🔴 Проксі — конфігом через stdin (`--config -`), а не аргументом.
        # Адреса проксі несе логін і пароль (`socks5://user:pass@host`), а
        # командний рядок процесу видно ВСІМ користувачам машини: `ps`,
        # `/proc/<pid>/cmdline`, диспетчер задач. Аргументом пароль лежав би
        # відкрито весь час запиту; stdin бачить лише сам curl.
        stdin = curl_config({"proxy": self.proxy}) if self.proxy else b""
        if stdin:
            cmd += ["--config", "-"]
        cmd.append(url)
        io: dict[str, Any] = ({"input": stdin} if stdin
                              else {"stdin": subprocess.DEVNULL})
        try:
            done = subprocess.run(cmd, capture_output=True,
                                  timeout=self.timeout + 15, check=False, **io)
        except (OSError, subprocess.SubprocessError) as exc:
            raise httpx.TransportError(f"curl: {exc}") from exc
        if done.returncode != 0:
            raise httpx.TransportError(
                f"curl завершився з кодом {done.returncode}: "
                f"{done.stderr.decode('utf-8', 'replace')[:200]}")
        body, _, tail = done.stdout.rpartition(b"\n")
        try:
            code = int(tail.decode("ascii", "ignore").strip() or 0)
        except ValueError:
            code = 0
        return Response(status_code=code, content=body, url=url)

    def close(self) -> None:
        if self._session is not None:
            with_close = getattr(self._session, "close", None)
            if callable(with_close):
                with_close()
            self._session = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
