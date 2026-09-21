"""📤 Віддати пакет у пул: реєстрація → байти в сховище → підтвердження.

Три кроки, а не один, і це не ускладнення заради ускладнення. Байти йдуть
у сховище НАПРЯМУ, повз сервер пулу: пакет на сорок мегабайтів через
застосунок означав би, що один повільний канал тримає всіх інших. Сервер
бачить лише маніфест — кілька кілобайтів JSON, — а тоді забирає залитий
файл сам і перевіряє його своїми воротами.

🔴 Ворота стоять на ОБОХ кінцях і це той самий код. Пакувальник перевіряє
до запису файлу, пул — після заливання, по тому, що справді лежить у
сховищі. Друга перевірка не зайва: між ними лежить мережа.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nyshporka.share import catalog

#: Токен CLI. Береться з оточення, а якщо його там немає — зі сховища
#: ключів операційної системи.
#:
#: 🔴 У файл простору не кладеться. Простір люди пакують і пересилають
#: одне одному (теки справ, звіти, вигрузки) — і токен поїхав би разом із
#: ним. Той самий висновок уже зроблено для ключів хмари в `cloud/transfer`.
#: Ім'я змінної, а не саме значення. Назване `ENV_NAME`, бо сканер секретів
#: репозиторію читає `ENV_TOKEN = "…"` як захардкоджений токен — і має рацію
#: в усіх інших випадках, тож обходити його правило не варто.
ENV_NAME = "NYSHPORKA_SUPRIAHA_TOKEN"
KEYRING_SERVICE = "nyshporka.supriaha"
KEYRING_USER = "token"


class UploadError(RuntimeError):
    """Не вдалося віддати пакет. Текст призначений людині."""


def token() -> str:
    """Токен або порожньо, якщо його ніде немає."""
    got = os.environ.get(ENV_NAME, "").strip()
    if got:
        return got
    try:
        import keyring

        return (keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip()
    except Exception:
        # Сховища ключів може не бути взагалі (сервер без сесії, контейнер),
        # і це не привід падати: відсутній токен — звичайний стан для того,
        # хто лише качає.
        return ""


def _request(method: str, url: str, *, body: Any = None, auth: str = "") -> dict[str, Any]:
    from nyshporka.sources.http import Fetcher, HttpError, app_ua

    # 🔴 Свій User-Agent, а не браузерний за замовчуванням. Пул — наш сервер,
    # і маскуватись перед ним нема від чого; натомість він пише подію на
    # КОЖЕН lookup, і промахи («питали, а в нас нема») — це і є перелік того,
    # що засівати далі. Під браузерним рядком у тій події не відрізнити
    # клієнта перед прогоном від людини у вкладці й від пошукового бота, тож
    # рішення про засів будувалося б на змішаних числах — і помітити це було б
    # нічим.
    headers = {"Accept": "application/json", "User-Agent": app_ua()}
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    fetcher = Fetcher(headers=headers)
    try:
        if method == "POST":
            resp = fetcher.post(url, json_body=body if body is not None else {})
        else:
            resp = fetcher.get(url)
    except HttpError as exc:
        raise UploadError(str(exc)) from exc
    text = resp.text if hasattr(resp, "text") else str(resp)
    try:
        got = json.loads(text)
    except ValueError as exc:
        raise UploadError(f"пул відповів не JSON: {text[:200]}") from exc
    if not isinstance(got, dict):
        raise UploadError("пул відповів не тим, чого чекали")
    return got


def publish(path: Path, *, base: str = "", auth: str = "") -> dict[str, Any]:
    """Віддати зібраний пакет у пул.

    Повертає відповідь сервера. Повторний виклик із тим самим змістом
    безпечний: пул упізнає його за хешем змісту й скаже `duplicate`, а не
    заведе другий внесок.
    """
    from nyshporka.share import bundle

    path = Path(path)
    if not path.exists():
        raise UploadError(f"немає файлу {path}")
    tok = auth or token()
    if not tok:
        raise UploadError(
            f"немає токена. Покладіть його в {ENV_NAME} — узяти в кабінеті на "
            "nyshporka.online"
        )

    manifest = bundle.read_manifest(path)
    home = catalog.base_url(base)

    got = _request("POST", f"{home}/contributions", body=manifest.as_json(), auth=tok)
    if got.get("duplicate"):
        return got

    upload = got.get("upload") or {}
    if not upload.get("text"):
        raise UploadError("пул не видав посилання на заливання")

    _put(upload["text"], path.read_bytes())

    # Геометрія їде окремим об'єктом, і лише якщо пул її попросив: вона
    # важить ×10 від тексту й лягає тільки тому, у кого ті самі кадри.
    geom = bundle.geom_path(path)
    if upload.get("geom") and geom.exists():
        _put(upload["geom"], geom.read_bytes())

    done = _request(
        "POST", f"{home}/contributions/{got['contribution']}/complete", auth=tok
    )
    return {**got, **done}


def _put(url: str, blob: bytes) -> None:
    """Покласти байти за підписаним посиланням.

    ⚠️ Жодного зайвого заголовка: підпис накриває рівно те, що в ньому
    перелічено, і дописаний параметр чи заголовок дає `SignatureDoesNotMatch`
    — помилку, яка читається як «сховище зламалось».
    """
    import httpx

    try:
        resp = httpx.put(url, content=blob, timeout=300.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise UploadError(f"сховище не прийняло байти: {exc}") from exc
