"""🔑 Вхід у Супрягу з браузера: ключ приходить сам, копіювати нічого.

Нишпорка слухає `127.0.0.1:<вільний порт>` і відкриває сторінку сайту з цим
портом і випадковим `state`. Там дві кнопки — увійти (лист чи Google) або
анонімно. Після кліку сторінка відправляє ключ формою POST сюди, на петлю;
ключ лягає у сховище ключів системи, і далі `publish` бере його звідти.

🔴 Слухаємо лише `127.0.0.1`, не `0.0.0.0`: інакше ключ міг би прийти з
сусідньої машини в мережі, а `state` був би єдиним захистом.

🔴 `state` звіряється завжди. Без нього будь-яка сторінка в браузері могла б
надіслати на цей порт СВІЙ ключ, і внески людини пішли б у чужий акаунт.

Ключ не друкується і не пишеться у файл простору — з тієї самої причини, що
в `upload.py`: простір люди пересилають одне одному.
"""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode

from nyshporka.share.upload import ENV_NAME, KEYRING_SERVICE, KEYRING_USER, UploadError

#: Сайт, де стоїть сторінка входу. Інший — для перевірки клієнта проти
#: тестового сервера, як `NYSHPORKA_TOLOKA` для API.
DEFAULT_SITE = "https://nyshporka.online"
ENV_SITE = "NYSHPORKA_SUPRIAHA_SITE"

#: Скільки чекати кліку. Людина може піти по лист, тож не хвилина.
TIMEOUT = 600.0

#: Форма несе лише ключ і state; більше — це вже не наша сторінка.
_MAX_BODY = 4096

_GOTOVO = """<!doctype html><meta charset="utf-8"><title>Нишпорка</title>
<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem">
<h1>{title}</h1><p>{text}</p></body>"""


def site_url(site: str = "") -> str:
    return (site or os.environ.get(ENV_SITE) or DEFAULT_SITE).rstrip("/")


def _keyring() -> Any:
    """Сховище ключів, придатне для запису, або `UploadError`.

    Перевіряється ДО відкриття браузера: анонімний акаунт народжується на
    кліку, і якщо ключ потім нікуди покласти, акаунт лишається сиротою.
    """
    try:
        import keyring
        from keyring.backends import fail
    except Exception as exc:
        raise UploadError(f"немає сховища ключів системи ({exc}). "
                          f"Покладіть ключ у {ENV_NAME} руками.") from exc
    if isinstance(keyring.get_keyring(), fail.Keyring):
        raise UploadError("у цій системі немає сховища ключів (сервер без сесії, "
                          f"контейнер?). Покладіть ключ у {ENV_NAME} руками — "
                          "видати його можна в кабінеті на nyshporka.online.")
    return keyring


def save(token: str) -> None:
    _keyring().set_password(KEYRING_SERVICE, KEYRING_USER, token)


def forget() -> bool:
    """Прибрати ключ зі сховища. False — його там і не було."""
    kr = _keyring()
    if not kr.get_password(KEYRING_SERVICE, KEYRING_USER):
        return False
    kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
    return True


class _Pryimach(HTTPServer):
    state: str
    token: str
    done: threading.Event


class _Handler(BaseHTTPRequestHandler):
    server: _Pryimach

    def log_message(self, format: str, *args: object) -> None:
        # Типовий обробник пише кожен запит у stderr — посеред виводу команди.
        return

    def _page(self, code: int, title: str, text: str) -> None:
        body = _GOTOVO.format(title=title, text=text).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._page(200, "Нишпорка чекає",
                   "Поверніться на вкладку nyshporka.online і завершіть вхід.")

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > _MAX_BODY:
            self._page(400, "Не вийшло", "Нишпорка отримала не те, на що чекала.")
            return
        form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        state = (form.get("state") or [""])[0]
        token = (form.get("token") or [""])[0].strip()
        # Порівнюються байти: на рядках `compare_digest` падає на не-ASCII.
        if not token or not hmac.compare_digest(state.encode(), self.server.state.encode()):
            self._page(400, "Не вийшло",
                       "Ця сторінка не з того входу, який запускала Нишпорка. "
                       "Запустіть <code>nysh share login</code> ще раз.")
            return
        self.server.token = token
        self._page(200, "Готово",
                   "Нишпорка отримала ключ. Цю вкладку можна закрити.")
        self.server.done.set()


def login(
    *,
    site: str = "",
    timeout: float = TIMEOUT,
    open_browser: bool = True,
    on_url: Callable[[str], None] | None = None,
) -> str:
    """Провести вхід і покласти ключ у сховище. Повертає ключ.

    `on_url` отримує адресу сторінки ДО очікування — щоб людина могла
    відкрити її сама, якщо браузер не відкрився.
    """
    _keyring()

    srv = _Pryimach(("127.0.0.1", 0), _Handler)
    srv.state = secrets.token_urlsafe(24)
    srv.token = ""
    srv.done = threading.Event()
    port = srv.server_address[1]

    url = f"{site_url(site)}/cli?{urlencode({'port': port, 'state': srv.state})}"
    thread = threading.Thread(target=srv.serve_forever, name="supriaha-login", daemon=True)
    thread.start()
    try:
        if on_url is not None:
            on_url(url)
        if open_browser:
            webbrowser.open(url)
        if not srv.done.wait(timeout):
            raise UploadError(f"за {int(timeout // 60)} хв ключ не прийшов. "
                              "Запустіть `nysh share login` ще раз.")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)

    save(srv.token)
    return srv.token
