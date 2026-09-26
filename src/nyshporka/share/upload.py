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
from collections.abc import Callable
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
    """Не вдалося віддати пакет. Текст призначений людині.

    `status` — код відповіді пулу, коли відмовив саме він. Порожній — до
    сервера не дійшло або відмовило сховище.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


#: Спроби PUT у сховище й паузи між ними. Решта запитів до пулу вже мала
#: відступ на обрив, а заливання — найдовший і найкрихкіший із них — ні:
#: один скинутий конект кидав зареєстрований внесок.
PUT_PAUZY = (2.0, 5.0)


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
    from nyshporka.sources.http import HttpError

    # 🔴 Свій User-Agent, а не браузерний за замовчуванням: пул пише подію на
    # КОЖЕН запит, і клієнт мусить бути в ній відрізнимий від людини у
    # вкладці. Ключ — лише на довірену адресу, 429 («денна норма») — без
    # повторів: шість спроб на відповідь «завтра» лише тримали б людину.
    try:
        fetcher = catalog._fetcher(url, auth=auth, accept_json=True)
        if method == "POST":
            resp = fetcher.post(url, json_body=body if body is not None else {})
        else:
            resp = fetcher.get(url)
    except HttpError as exc:
        # Причина — з тіла відповіді: пул називає, котрі ворота не пустили
        # пакет, і голе «HTTP 400» людині нічого не каже.
        raise UploadError(catalog.reason(exc), status=exc.status) from exc
    except catalog.PoolError as exc:
        raise UploadError(str(exc)) from exc
    text = resp.text if hasattr(resp, "text") else str(resp)
    try:
        got = json.loads(text)
    except ValueError as exc:
        raise UploadError(f"пул відповів не JSON: {text[:200]}") from exc
    if not isinstance(got, dict):
        raise UploadError("пул відповів не тим, чого чекали")
    return got


def publish(path: Path, *, base: str = "", auth: str = "",
            say: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Віддати зібраний пакет у пул.

    Повертає відповідь сервера. Повторний виклик із тим самим змістом
    безпечний: пул упізнає його за хешем змісту й скаже `duplicate`, а не
    заведе другий внесок.

    `say` — куди казати хід заливки. 🔴 Не прикраса: мовчазна заливка на
    повільному каналі триває хвилини, і агент-помічник убивав її за
    тайм-аутом свого інструмента як завислу — внесок лишався без байтів.
    """
    from nyshporka.share import bundle

    path = Path(path)
    if not path.exists():
        raise UploadError(f"немає файлу {path}")
    tok = auth or token()
    if not tok:
        raise UploadError(
            "немає ключа Супряги. Увійдіть: `nysh share login` — або покладіть "
            f"ключ у {ENV_NAME} (видається в кабінеті на nyshporka.online)"
        )

    home = catalog.base_url(base)
    if not catalog.may_send_key(home, explicit=bool(auth)):
        # 🔴 Ключ зі сховища — обліковий запис людини. На чужу адресу він не
        # їде навіть тоді, коли її задала змінна оточення: так його не
        # виманити підміною `NYSHPORKA_TOLOKA`.
        raise UploadError(
            f"ключ Супряги не надсилається на {home}: довірена лише "
            f"https://…{catalog.TRUSTED_DOMAIN}. Для свого сервера покладіть "
            f"ключ явно в {ENV_NAME}")
    try:
        manifest = bundle.read_manifest(path)
    except (OSError, ValueError, bundle.BundleError, EOFError) as exc:
        raise UploadError(f"не прочитати пакет {path.name}: {exc}") from exc

    got = _request("POST", f"{home}/contributions", body=manifest.as_json(), auth=tok)
    if got.get("duplicate"):
        return _public(_attach_geometry(got, path, home=home, tok=tok, manifest=manifest))

    upload = got.get("upload") or {}
    if not upload.get("text") or not got.get("contribution"):
        raise UploadError("пул не видав посилання на заливання")

    # 🔴 Від цього місця внесок уже зареєстровано, і будь-який збій лишає в
    # пулі оболонку без байтів — ні в черзі, ні в каталозі. Байти йдуть у
    # сховище повз сервер, тож сам він про обрив не дізнається ніколи: про
    # це мусить сказати клієнт (`_zvit_pro_zbii`).
    vnesok = got["contribution"]
    kazhy = say or (lambda _: None)
    etap = "put_text"
    try:
        _zalyty(upload["text"], path.read_bytes(), "текст", kazhy)

        # Геометрія їде окремим об'єктом, і лише якщо пул її попросив: вона
        # важить ×10 від тексту й лягає тільки тому, у кого ті самі кадри.
        # 🔴 І лише свіжа: geom-файл від ПОПЕРЕДНЬОГО пакування цієї справи
        # (див. `_geom_fresh`) прив'язаний до іншого тексту.
        geom = bundle.geom_path(path)
        if upload.get("geom") and _geom_fresh(path, geom):
            etap = "put_geom"
            _zalyty(upload["geom"], geom.read_bytes(), "геометрію", kazhy)

        etap = "complete"
        kazhy("пул перевіряє пакет…")
        done = _request("POST", f"{home}/contributions/{vnesok}/complete", auth=tok)
    except UploadError as exc:
        # Відмову самого пулу (ворота, стеля) сервер уже знає й записав, і
        # повтор тут не допоможе — тому й підказки повторити немає.
        if exc.status is None or exc.status >= 500:
            _zvit_pro_zbii(home, tok, vnesok, etap, str(exc))
            raise UploadError(f"{exc}\n{_POVTORYTY.format(vnesok=vnesok)}",
                              status=exc.status) from exc
        raise
    except OSError as exc:
        # Шлях до файлу в причину не йде: у ньому ім'я користувача машини.
        _zvit_pro_zbii(home, tok, vnesok, etap,
                       f"не прочитався файл пакета: {type(exc).__name__}")
        raise UploadError(f"не прочитати пакет: {exc}") from exc
    except KeyboardInterrupt:
        _zvit_pro_zbii(home, tok, vnesok, etap, "перервано (Ctrl+C)")
        raise
    return _public({**got, **done})


#: Що робити після збою заливки — прямо в тексті помилки. 🔴 Вивід команди —
#: єдине, що гарантовано читає будь-який агент: скіли стоять не в кожного.
_POVTORYTY = ("Внесок {vnesok} уже заведено в пулі. Повторіть ту саму команду "
              "пізніше — пул підхопить цей внесок, другого не створить.")

#: Як часто казати «ще заливаю», поки PUT іде.
PULS_S = 15.0


def _zalyty(url: str, blob: bytes, shcho: str, say: Callable[[str], None]) -> None:
    """PUT із ходом: розмір до, пульс під час, час після."""
    import threading
    import time

    say(f"заливаю {shcho}: {len(blob) / (1 << 20):.1f} МБ…")
    start = time.monotonic()
    stop = threading.Event()

    def _puls() -> None:
        while not stop.wait(PULS_S):
            say(f"…ще заливаю {shcho}, {time.monotonic() - start:.0f} с")

    # Демон: убитий чи перерваний процес не мусить чекати на пульс.
    puls = threading.Thread(target=_puls, daemon=True)
    puls.start()
    try:
        _put(url, blob)
    finally:
        stop.set()
        puls.join(timeout=1.0)
    say(f"✓ {shcho} за {time.monotonic() - start:.0f} с")


def _zvit_pro_zbii(home: str, tok: str, vnesok: Any, etap: str, prychyna: str) -> None:
    """Сказати пулу, що заливання впало. Навмання: одна спроба, без помилок.

    🔴 Звіт не має права зробити збій гіршим — ні затримати людину на
    повторах, ні підмінити справжню причину своєю. Старий пул цього маршруту
    не знає (404), і це теж мовчки.
    """
    from nyshporka.sources.http import app_ua

    try:
        fetcher = catalog._fetcher(home, timeout=10.0, attempts=1, auth=tok,
                                   accept_json=True)
        fetcher.post(f"{home}/contributions/{vnesok}/failed", json_body={
            "stage": etap, "error": prychyna[:500], "client": app_ua()})
    except Exception:
        # Звіт про збій сам не падає.
        pass


#: Чим закінчилась віддача — одне слово на всі обличчя.
VIDDANO = "viddano"          # новий внесок прийнято
VZHE_Ye = "vzhe_ye"          # такий самий текст уже в каталозі
VIDKHYLENO = "vidkhyleno"    # такий самий текст подавали, і пул його відхилив
NE_HOTOVO = "ne_hotovo"      # такий самий текст заведено, але не прийнято


def outcome(got: dict[str, Any]) -> str:
    """Що насправді сталося з віддачею.

    🔴 `duplicate` сам по собі НЕ означає «текст у Супрязі». Сервер каже
    `duplicate` і на свій ВІДХИЛЕНИЙ внесок, і на чужий незавершений — тож
    «цей текст уже в Супрязі» на такій відповіді означав би, що людина
    вважає справу відданою, а в каталозі її немає.
    """
    if got.get("duplicate"):
        if str(got.get("status") or "") == "vidkhyleno":
            return VIDKHYLENO
        if got.get("ready") is False:
            return NE_HOTOVO
        return VZHE_Ye
    if str(got.get("status") or "") == "vidkhyleno":
        return VIDKHYLENO
    return VIDDANO if got.get("ready", True) else NE_HOTOVO


OUTCOME_TEXT = {
    VIDDANO: "віддано в Супрягу",
    VZHE_Ye: "цей текст уже в Супрязі",
    VIDKHYLENO: "такий самий текст пул уже відхиляв — у каталозі його немає",
    NE_HOTOVO: "такий самий текст заведено в пулі, але ще не прийнято — "
               "у каталозі його поки немає",
}


def _public(got: dict[str, Any]) -> dict[str, Any]:
    """Відповідь пулу без підписаних посилань на заливання.

    🔴 Посилання на двадцять хвилин дає право писати в сховище від імені
    внеску. Потрібне воно лише тут, а далі потрапляло б у `--json`, у
    результат завдання демона й у журнали — тобто в місця, які люди
    копіюють у чати.
    """
    out = {k: v for k, v in got.items() if k not in ("upload", "expires")}
    out["outcome"] = outcome(out)
    return out


def _geom_fresh(text_path: Path, geom: Path) -> bool:
    """Чи geom-файл зібрано разом із цим текстовим, а не колись раніше.

    Ім'я geom-пакета детерміноване, тож `pack --no-geometry` після давнього
    пакування з геометрією лишав поруч чужі рамки — і віддача підхоплювала
    їх до нового тексту. Свіжий — той, чий маніфест несе той самий хеш
    змісту, що й текстовий.
    """
    from nyshporka.share import bundle

    if not geom.is_file():
        return False
    try:
        a = bundle.read_manifest(text_path)
        b = bundle.read_manifest(geom)
    except Exception:
        return False
    ha, hb = a.decode.get("content_sha256"), b.decode.get("content_sha256")
    if ha or hb:
        return bool(ha) and ha == hb
    # Пакет без хеша змісту (старий голос): тоді «той самий захід пакування» —
    # однаковий час збірки маніфесту, який пишеться в обидва файли разом.
    return bool(a.created) and a.created == b.created and a.shifra == b.shifra


def _attach_geometry(got: dict[str, Any], path: Path, *, home: str, tok: str,
                     manifest: Any) -> dict[str, Any]:
    """Текст уже в пулі, геометрії при ньому немає — довезти її окремо.

    🔴 Без цього кроку геометрію до залитого тексту не додати НІЯК: той самий
    текст пул упізнає за хешем змісту й відповідає `duplicate`, не видаючи
    посилань. Саме так перші десять засіяних справ лишились без рамок.
    """
    from nyshporka.share import bundle

    geom = bundle.geom_path(path)
    # Старий пул полів `geometry`/`mine` не віддає — тоді нічого не робимо.
    if (got.get("geometry") is not False or not got.get("mine")
            or got.get("ready") is False or not _geom_fresh(path, geom)):
        return got
    attach = _request(
        "POST", f"{home}/contributions/{got['contribution']}/geometry",
        body=manifest.as_json(), auth=tok)
    url = (attach.get("upload") or {}).get("geom")
    if not url:
        return {**got, "geometry_attach": attach}
    _put(url, geom.read_bytes())
    done = _request(
        "POST", f"{home}/contributions/{got['contribution']}/complete", auth=tok)
    return {**got, **done, "geometry_attached": True}


def _signed_headers(url: str) -> set[str]:
    """Заголовки, які накриває підпис presigned-посилання (`X-Amz-SignedHeaders`)."""
    from urllib.parse import parse_qs, urlsplit

    q = {k.lower(): v for k, v in parse_qs(urlsplit(url).query).items()}
    raw = (q.get("x-amz-signedheaders") or [""])[0]
    return {h.strip().lower() for h in raw.split(";") if h.strip()}


def _put(url: str, blob: bytes) -> None:
    """Покласти байти за підписаним посиланням.

    ⚠️ Жодного зайвого заголовка: підпис накриває рівно те, що в ньому
    перелічено, і дописаний параметр чи заголовок дає `SignatureDoesNotMatch`
    — помилку, яка читається як «сховище зламалось».

    🔴 `If-None-Match: *` — лише коли його вписав у підпис сервер. Умовний
    PUT закриває вікно підміни: після прийняття внеску власник посилання ще
    хвилини мав би право перезалити файл, і качали б не те, що пройшло
    ворота. Захищає він, лише коли заголовок ПІДПИСАНИЙ (нечесний клієнт
    свого просто не пошле), тож рішення за сервером, а клієнт іде за
    підписом: підписано — шле, ні — не шле, і нічого не ламається.

    412 на такому PUT означає «об'єкт уже лежить» — найчастіше це повтор
    після обриву, коли перша спроба встигла дописати. Тоді далі йде
    `complete`, і сервер сам звірить те, що лежить, своїми воротами.
    """
    import time

    import httpx

    from nyshporka.sources.http import proxy_url

    headers: dict[str, str] = {}
    conditional = "if-none-match" in _signed_headers(url)
    if conditional:
        headers["If-None-Match"] = "*"
    ostannia = ""
    for sproba in range(len(PUT_PAUZY) + 1):
        if sproba:
            time.sleep(PUT_PAUZY[sproba - 1])
        try:
            # 🔴 Через той самий проксі, що й решта запитів Нишпорки. Без
            # нього в людини, якій мережа доступна лише тунелем, реєстрація
            # проходила, а байти — ні.
            resp = httpx.put(url, content=blob, headers=headers, timeout=300.0,
                             proxy=proxy_url())
        except httpx.TransportError as exc:
            ostannia = f"{type(exc).__name__}: {_bez_posylannia(str(exc), url)}"
            continue
        except httpx.HTTPError as exc:
            raise UploadError(f"сховище не прийняло байти: {type(exc).__name__}: "
                              f"{_bez_posylannia(str(exc), url)}") from None
        # 412 на повторі після обриву — перша спроба встигла дописати.
        if conditional and resp.status_code == 412:
            return
        if resp.status_code >= 500:
            ostannia = f"HTTP {resp.status_code}"
            continue
        if resp.status_code >= 400:
            raise UploadError(f"сховище не прийняло байти: HTTP {resp.status_code}"
                              + _kod_s3(resp))
        return
    raise UploadError(f"сховище не прийняло байти після {len(PUT_PAUZY) + 1} "
                      f"спроб: {ostannia}")


def _bez_posylannia(tekst: str, url: str) -> str:
    """Причина збою без підписаного посилання.

    🔴 Посилання дає право писати в сховище, а причина їде в журнали, у
    `--json` і на сервер. Вирізається будь-яка адреса, а не лише ця: httpx
    буває цитує її з іншими параметрами.
    """
    import re

    return re.sub(r"https?://\S+", "<посилання>", tekst.replace(url, "<посилання>"))[:300]


def _kod_s3(resp: Any) -> str:
    """Код відмови S3 із тіла (`SignatureDoesNotMatch`, `AccessDenied`…)."""
    import re

    try:
        found = re.search(r"<Code>([A-Za-z]+)</Code>", resp.text or "")
    except Exception:
        return ""
    return f" ({found.group(1)})" if found else ""
