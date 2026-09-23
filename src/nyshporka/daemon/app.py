"""🖥 Демон: браузерне обличчя над тим самим реєстром операцій.

🔴 Тут немає окремих роутерів на кожну дію, і це головне рішення файлу. У
дослідницькому конвеєрі було 157 роутів проти 13 підключених скриптів — тобто
браузер і командний рядок описували роботу двічі, розійшлись, і побачили це
користувачі. Тому HTTP тут — тонка обгортка над `core.ops`: список операцій і
один виклик. Додати дію в браузер = оголосити `@op`, а не написати роут.

Три речі, які вирішені саме тут, а не в реєстрі:

1. **Один писар.** Демон тримає замок простору й єдиний має чергу завдань.
   Команда, запущена окремо, до черги не дістається — і чесно каже це замість
   того, щоб мовчки завести другу.
2. **Токен на мутаціях.** Порт локальний, але «локальний» не значить «нікому
   не доступний»: будь-яка сторінка у браузері вміє слати запити на localhost.
   Читання відкрите (там нічого не псується), мутації — за токеном, який
   віддається лише самій сторінці застосунку.
3. **Курсор замість стріму.** Той самий журнал подій живить і браузер, і
   агента; агент не тримає з'єднання, він приходить раз на хвилину.

Мережевий режим (`nysh serve --host`) — окремий клас загроз, і пункт 2 у ньому
не тримає нічого: сторінку з токеном отримує кожен, хто дістався порту. Тому
мережеве з'єднання спершу проходить ворота допуску (`_AccessGate`) — ключ
пристрою в cookie — і лише потім бачить застосунок. Петля лишається такою, як
описано вище.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from fastapi import FastAPI

    from nyshporka.core.workspace import Workspace

#: Заголовок, у якому сторінка передає токен. Не cookie: cookie браузер шле сам,
#: і тоді захист від чужої вкладки зникає рівно там, де він потрібен.
TOKEN_HEADER = "X-Nysh-Token"

#: Дефолтний порт. 8788 — не 8000: на 8000 сидить половина dev-серверів, і
#: сплутати чужий застосунок зі своїм у браузері дуже легко.
DEFAULT_PORT = 8788
DEFAULT_HOST = "127.0.0.1"

#: Імена, під якими застосунок відповідає на ПЕТЛЬОВИХ з'єднаннях. Перелік
#: вичерпний: усе інше — чужий сайт, який перев'язав своє ім'я на нашу адресу.
#:
#: 🔴 `0.0.0.0` тут більше немає. Частина браузерів веде `0.0.0.0` на локальну
#: машину, тож сторінка з інтернету шле такий запит із `Host: 0.0.0.0` — і він
#: проходив перевірку як «свій». Прочитати відповідь чи змінити простір вона не
#: могла (no-cors і перевірка `Origin`), але своїм таке ім'я не є.
#:
#: Мережеві з'єднання цей перелік не розширюють: їхній `Host` звіряє ворота
#: допуску з адресою, на яку з'єднання реально прийшло.
_OWN_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})

#: Адреси «усі інтерфейси». `::` відкривається двома сокетами — див. `bind_addresses`.
WILDCARDS = frozenset({"0.0.0.0", "::"})

#: Маршрут допуску мережевого пристрою.
ACCESS_PATH = "/api/access"
#: Скільки живе код сполучення з посилання в терміналі.
PAIR_TTL_SEC = 600
#: Скільки пристрій лишається сполученим без повторного вводу.
ACCESS_COOKIE_MAX_AGE = 30 * 24 * 3600
#: Хибних спроб допуску з однієї адреси до тимчасового блоку.
FAILS_MAX = 10
#: Скільки триває блок. Тимчасовий, а не до перезапуску: за NAT, VPN чи
#: проброшеним портом одна адреса буває в кількох людей, і блок назавжди
#: перетворився б на спосіб вимкнути доступ самому власнику.
FAIL_BLOCK_SEC = 15 * 60
#: Затримка на кожну хибну спробу. Хибні відповіді віддаються ПО ОДНІЙ (спільний
#: замок), тож паралельний перебір із багатьох адрес сповільнюється так само, як
#: послідовний, а правильний ключ у цю чергу не стає. Ключ і так 256 біт; це
#: запобіжник від шуму, а не межа.
FAIL_DELAY_SEC = 1.0
#: Скільки адрес пам'ятає лічильник. IPv6 рахується за /64: клієнт міняє адресу
#: в межах своєї підмережі, і лічильник на кожну окрему не рахував би нічого.
FAILS_TRACKED_MAX = 1024
#: Найбільше тіло запиту допуску — у байтах, що реально прийшли.
ACCESS_BODY_MAX = 4096
#: Фраза другого підтвердження для «усіх інтерфейсів» чи публічної адреси.
PUBLIC_PHRASE = "відкрити всім"

#: Що бачить мережеве з'єднання БЕЗ допуску — точний перелік, а не `/static/*`:
#: сторінка допуску й рівно те, що вона вантажить.
_GATE_OPEN = frozenset({
    "/static/access.js", "/static/access.css", "/static/core/strings.js",
    "/ui/fonts.css", "/ui/tokens.css", "/ui/base.css", "/favicon.ico",
    "/ui/img/logo.webp", "/ui/img/maskot-kliuch.webp",
    "/ui/img/favicon-32.png", "/ui/img/apple-touch-icon.png",
})
#: Шрифти — префіксом: файлів вісім, і всі вони публічні (OFL).
_GATE_OPEN_PREFIXES = ("/brand/", "/ui/fonts/")

#: Чи поточний запит прийшов мережевим з'єднанням. Ставлять ворота допуску;
#: читають перевірка імені й `call_op`. Контекстна змінна, а не параметр
#: `Request`: анотації тут — рядки (`from __future__`), а `fastapi` — extra, тож
#: імпортувати `Request` на рівні модуля не можна.
_NETWORK_CONN: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "nysh_network_conn", default=False)


class AccessKeyError(RuntimeError):
    """Ключ доступу не можна ні прочитати, ні довірити."""


def is_loopback_host(host: str) -> bool:
    """Петля: `localhost` або IP петлі, зокрема IPv4-mapped (`::ffff:127.0.0.1`).

    ⚠ `ipaddress.is_loopback` для mapped-адрес правильний лише з Python 3.13, а
    пакет підтримує 3.11 — тож mapped розгортається руками. Нечислове ім'я
    (крім `localhost`) — не петля: так його й трактують ворота.
    """
    h = host.strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def network_host(host: str) -> str:
    """Перевірити адресу для `--host` і звести до канонічного запису.

    Лише IP-літерал: ім'я резолвиться на момент старту, а довіряти потім
    доводилось би тому, на що воно вкаже завтра. Link-local IPv6 відхиляється:
    адресу з `%scope` браузер у `Host` не пришле, і демон відбивав би кожен
    запит.
    """
    raw = host.strip().strip("[]")
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        raise ValueError(
            f"--host приймає IP-адресу цієї машини (або 0.0.0.0 / ::), а не ім'я: «{host}»"
        ) from None
    if ip.is_link_local:
        raise ValueError(
            f"link-local адреса {raw} не підходить: браузер не пришле її з зоною "
            f"в `Host`. Візьміть адресу мережі (192.168.… / fd…) або ::")
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # Сокет IPv6 на таку адресу не сяде, і людина бачила б лише невиразне
        # «адреси може не бути на цій машині».
        raise ValueError(
            f"IPv4-mapped адреса {raw} не підходить — дайте саму IPv4: {ip.ipv4_mapped}")
    return str(ip)


def is_public_exposure(host: str) -> bool:
    """Чи потрібне друге підтвердження: усі інтерфейси або адреса з інтернету."""
    if host in WILDCARDS:
        return True
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def bind_addresses(host: str) -> list[str]:
    """На яких адресах слухати мережевий демон.

    🔴 Конкретна адреса — це один інтерфейс, тож поруч завжди стоїть петля:
    вкладка на цій машині й тунелі (`ssh -L`) ходять саме на 127.0.0.1.
    Розширювати конкретний IP до `0.0.0.0` не можна: людина просила одну
    мережу, а отримала б усі, зокрема VPN і публічну.

    🔴 `::` — два сокети, а не один dual-stack. На Windows `IPV6_V6ONLY` за
    замовчуванням увімкнено, і один сокет `::` не приймав би IPv4 зовсім
    (петля й LAN-IPv4 мертві); на Linux — вимкнено, і локальне з'єднання
    приходило б як `::ffff:127.0.0.1`. Два явні сокети однакові всюди.
    """
    if host == "0.0.0.0":
        return ["0.0.0.0"]
    if host == "::":
        return ["0.0.0.0", "::"]
    return ["127.0.0.1", host]


def open_sockets(host: str, port: int) -> list[socket.socket]:
    """Відкрити сокети мережевого демона. Помилка — усе відкрите закривається."""
    socks: list[socket.socket] = []
    try:
        for addr in bind_addresses(host):
            fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
            sock = socket.socket(fam, socket.SOCK_STREAM)
            socks.append(sock)
            # 🔴 На Windows `SO_REUSEADDR` дозволяє ІНШОМУ процесу сісти на той
            # самий порт — у режимі «усі інтерфейси» чужий процес зайняв би
            # точніший `127.0.0.1:порт` і перехопив петлю. Там — ексклюзивний
            # бінд; на POSIX `SO_REUSEADDR` лише знімає TIME_WAIT.
            if sys.platform == "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if fam == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((addr, port))
            sock.set_inheritable(True)
    except OSError:
        for sock in socks:
            sock.close()
        raise
    return socks


def check_tls(cert: str, key: str) -> None:
    """Завантажити сертифікат ДО бінду — щоб відмова була негайною й зрозумілою.

    🔴 `password` повертає порожнє: без цього зашифрований ключ змушує OpenSSL
    питати pass phrase прямо зі stdin — служба просто зависла б. А помилка
    всередині uvicorn прилітала б трасуванням уже з циклу подій.
    """
    import ssl

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.load_cert_chain(cert, key, password=lambda: b"")
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(
            f"сертифікат не завантажився ({cert}, {key}): {exc}. Потрібні PEM-файли, "
            f"ключ без пароля") from None


def access_key_path(root: Path) -> Path:
    """Файл сталого ключа доступу для простору.

    🔴 У конфігу користувача, а не в просторі: простір кладуть у git і в
    хмарну синхронізацію (те саме правило, що для ключів сховища,
    `cloud/transfer.py`). Ім'я — хеш кореня: два простори на одній машині
    мають різні ключі.
    """
    from platformdirs import user_config_dir

    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(user_config_dir("nyshporka", appauthor=False)) / "serve" / f"{digest}.key"


def _write_access_key(path: Path, *, replace: bool) -> None:
    """Записати новий ключ атомарно.

    Спершу тимчасовий файл із правами 0600, потім встановлення: `os.replace`
    для ротації, ексклюзивне (`os.link` / `os.rename` на Windows — обидва
    падають, якщо файл уже є) для першого створення. Процес, що програв гонку,
    читає ключ переможця, а не бачить наполовину записаний файл.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(secrets.token_urlsafe(32))
        if replace:
            os.replace(tmp, path)
        elif sys.platform == "win32":
            os.rename(tmp, path)
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise
            except OSError:
                # ФС без жорстких посилань (FAT, частина мережевих): ексклюзивне
                # встановлення недоступне. Гонки тут немає — ключ пишеться лише
                # під замком простору.
                if not path.exists():
                    os.replace(tmp, path)
    except FileExistsError:
        pass
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def load_access_key(root: Path, *, rotate: bool = False) -> tuple[str, Path]:
    """Сталий ключ доступу простору: прочитати, за потреби створити чи змінити.

    Кликати лише під замком простору: ротація з-під живого демона лишила б його
    зі старим ключем у пам'яті, а людину — з неробочим посиланням.
    """
    path = access_key_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if rotate or not path.exists():
            _write_access_key(path, replace=rotate)
        st = path.stat()
        key = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise AccessKeyError(f"ключ доступу {path} недоступний: {exc}") from None
    # На Windows права 0600 означають лише «тільки читання»; захищає ACL теки
    # профілю користувача, в якій файл лежить.
    if sys.platform != "win32" and st.st_mode & 0o077:
        raise AccessKeyError(
            f"ключ доступу {path} читають інші користувачі "
            f"(права {oct(st.st_mode & 0o777)}) — виправити: chmod 600 {path}")
    if len(key) < 32:
        raise AccessKeyError(
            f"ключ доступу {path} порожній або обрізаний — створити новий: "
            f"nysh serve --host … --rotate-key")
    return key, path


def _cookie_value(key: str) -> str:
    """Що лежить у cookie пристрою: похідне від ключа, а не сам ключ.

    Ключа немає в сховищі браузера, а ротація ключа відкликає всі cookie разом.
    """
    return hmac.new(key.encode("utf-8"), b"nysh-access", hashlib.sha256).hexdigest()


def _cookie_name(port: int, *, tls: bool) -> str:
    """Ім'я cookie. Порт — бо cookie прив'язані до хоста, а не до порту."""
    return f"{'__Host-' if tls else ''}nysh_access_{port}"


def _same(given: object, want: str) -> bool:
    """Порівняння секрету за сталий час — на байтах, як у `require_token`."""
    return isinstance(given, str) and bool(given) and secrets.compare_digest(
        given.encode("utf-8"), want.encode("utf-8"))


def _url_host(addr: str) -> str:
    return f"[{addr}]" if ":" in addr else addr


def _interface_addresses() -> list[str]:
    """Адреси цієї машини — лише для показу в банері й попередженні.

    Перелік неповний (VPN, тимчасові IPv6, зміна DHCP), тож довіра на нього не
    спирається: `Host` звіряється з адресою з'єднання.
    """
    found: set[str] = set()
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None):
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
                if not (ip.is_loopback or ip.is_link_local):
                    found.add(str(ip))
    return sorted(found)


def exposure_warnings(host: str, port: int, *, tls: bool, key_path: Path) -> list[str]:
    """Що саме відкриває `nysh serve --host` — конкретно, до підтвердження."""
    lines = [
        f"⚠ Вихід у мережу: {host}, порт {port}. Прочитайте перед підтвердженням.",
        "• Відкривається весь простір: канон із даними про живих людей, скани, "
        "нотатки — на читання й на запис.",
        "• Хто пройде допуск, працює з файлами цієї машини від вашого імені "
        "(гортач диска, запис куди завгодно) і може запустити платну оренду "
        "обчислень.",
    ]
    if tls:
        lines.append("• З'єднання шифроване (TLS). Сертифікат виписаний не на "
                     "127.0.0.1, тож вкладка на цій машині попередить про нього.")
    else:
        lines.append("• Без шифрування (HTTP): код сполучення, ключ і все, що ви "
                     "переглядаєте, ідуть мережею відкритим текстом — будь-хто в "
                     "цій мережі може їх перехопити. Не робіть цього в гостьовій чи "
                     "публічній мережі; шифрування — --tls-cert і --tls-key.")
    lines.append(f"• Пристрій пускається лише з ключем доступу. Ключ сталий і лежить "
                 f"у {key_path}; він дає повний доступ тому, в кого опиниться. "
                 f"Відкликати всі пристрої — --rotate-key.")
    if host in WILDCARDS:
        seen = ", ".join(_interface_addresses()) or "перелічити не вдалося"
        lines.append(f"• {host} — усі інтерфейси машини, зокрема VPN, docker і "
                     f"публічні, а також ті, що з'являться, поки демон працює. "
                     f"Видно зараз: {seen}.")
    elif is_public_exposure(host):
        lines.append(f"• {host} — публічна адреса: застосунок буде видно з інтернету.")
    lines += [
        "• Проксі чи тунель на цій машині приходять через петлю 127.0.0.1, а петлю "
        "ключ не перевіряє — закривати доступ мусять вони самі.",
        f"• Те саме без усього цього: ssh -L {port}:127.0.0.1:{port} <ця машина> "
        f"і nysh serve без --host.",
    ]
    return lines


def _conn_server(scope: dict[str, Any]) -> tuple[str, int]:
    server = scope.get("server")
    if not server:
        return "", 0
    return str(server[0]), int(server[1] or 0)


def _conn_is_loopback(scope: dict[str, Any]) -> bool:
    """🔴 Петля — за ЛОКАЛЬНОЮ адресою з'єднання, а не за адресою клієнта.

    `scope["server"]` uvicorn бере з `getsockname()` прийнятого сокета: з петлі
    це 127.0.0.1 навіть на сокеті «усі інтерфейси», з мережі — адреса
    інтерфейсу. Заголовком її не підробити, і `ProxyHeadersMiddleware` її не
    чіпає — на відміну від `scope["client"]`, який від петлі переписується
    за `X-Forwarded-For`.
    """
    return is_loopback_host(_conn_server(scope)[0])


def create_app(ws: Workspace | None = None, *, token: str = "",
               host: str | None = None, access_key: str = "",
               tls: bool = False) -> FastAPI:
    """Зібрати застосунок. `token` порожній — згенерувати новий.

    `host` не петля — мережевий режим: мережеві з'єднання проходять ворота
    допуску з `access_key` (без нього застосунок не збирається), а `tls`
    робить cookie допуску `Secure`. Петльові з'єднання поводяться однаково в
    обох режимах.
    """
    network = bool(host) and not is_loopback_host(host or "")
    if network and not access_key:
        raise ValueError("мережевий режим без ключа доступу не піднімається")
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Query
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.requests import Request
    except ImportError as exc:  # pragma: no cover — extras `app`
        raise RuntimeError(
            "браузерна консоль потребує extras: pip install 'nyshporka[app]'"
        ) from exc

    class _NoCacheStatic(StaticFiles):
        """Статика, яку браузер зобов'язаний перепитати.

        🔴 Без цього фронт застряє В пам'яті браузера. Відколи консоль стала
        набором ES-модулів, сторінка тягне два десятки файлів, і жоден із них
        не має ні версії в імені, ні заголовка кешу: після оновлення
        застосунку людина бачить стару консоль проти нового бекенду. Виглядає
        це як «кнопка не працює» або «екран порожній», а не як застарілий кеш,
        і лікується жорстким перезавантаженням, про яке ніхто не здогадується.

        ⚠ Версія в запиті (`?v=…`) цього не закриває: вона переписує посилання
        в розмітці, а `import` усередині самого модуля лишається без неї —
        тобто півміри, яка робить збій періодичним замість постійного. Тут
        коштує це відповіді 304 на кілька байтів по локальній петлі.

        ⚠ Клас оголошений тут, а не на рівні модуля: `fastapi` —
        необов'язковий extra, і модульне успадкування від `StaticFiles`
        зробило б імпорт пакета неможливим у того, хто поставив його без
        застосунку.
        """

        async def get_response(self, path: str, scope: Any) -> Any:
            res = await super().get_response(path, scope)
            res.headers["Cache-Control"] = "no-cache, must-revalidate"
            return res

    from nyshporka import ops as O
    from nyshporka import ui
    from nyshporka.core.jobs import JobBus
    from nyshporka.core.workspace import use as _use
    from nyshporka.core.workspace import workspace as _workspace
    from nyshporka.daemon import workers
    from nyshporka.runtime import set_bus

    space = ws or _workspace()
    # 🔴 Простір оголошується на процес, а не лишається знанням цього об'єкта.
    # Операції резолвлять його самі (їх кличуть і з CLI, і з агента), тож демон,
    # який знає простір лише «для себе», віддавав би відповіді про інший
    # простір — той, що резолвиться від поточної теки. Помилки при цьому немає:
    # відповідь просто стосується не того архіву.
    _use(space)
    tok = token or secrets.token_urlsafe(24)
    bus = JobBus(space.derived / "jobs.json")
    bus.load()
    set_bus(bus)

    app = FastAPI(title="Нишпорка", docs_url=None, redoc_url=None)
    app.state.workspace = space
    app.state.token = tok
    app.state.bus = bus
    # Код сполучення — одноразовий і короткий: посилання з ним лягає в
    # месенджер і в історію браузера, тож сталий ключ туди не йде.
    app.state.pair_code = secrets.token_urlsafe(18) if network else ""
    app.state.pair_expires = time.monotonic() + PAIR_TTL_SEC

    static_dir = Path(__file__).resolve().parent / "static"

    def _envelope(error: str) -> dict[str, Any]:
        return {"ok": False, "v": 1, "data": {}, "warnings": [], "error": error}

    @app.middleware("http")
    async def only_this_machine(request, call_next):  # type: ignore[no-untyped-def]
        """Відповідати лише на власне ім'я — інакше чужий сайт читає простір.

        🔴 Це не параноя про мережу: петльове з'єднання приходить лише з цієї
        машини. Це захист від перев'язування імені. Сайт із коротким TTL віддає
        спершу свою адресу, а через секунду — `127.0.0.1`; для браузера це
        лишається той самий origin, тож ані CORS, ані `SameSite` не
        спрацьовують, і його скрипт починає говорити з нашим демоном як своя ж
        сторінка.

        Найдорожче тут те, що токен цього не спиняє: `GET /` віддає сторінку з
        ушитим токеном, тобто перший же запит його й видає. Тобто до цієї
        перевірки вся токенна схема трималась на тому, що ніхто не спробує.

        Браузер не дозволяє скриптові підмінити `Host`, тож перевірка повна.
        Тунель (`ssh -L`) шле `localhost` і проходить; іншого імені в петлі бути
        не може. Мережеве з'єднання сюди доходить уже звіреним воротами
        допуску — його `Host` мусить назвати адресу, на яку воно прийшло.
        """
        raw_host = request.headers.get("host") or ""
        if not _NETWORK_CONN.get():
            host_name = raw_host.rsplit(":", 1)[0].strip("[]").lower()
            if host_name and host_name not in _OWN_NAMES:
                return JSONResponse(
                    _envelope(f"застосунок відповідає лише на 127.0.0.1, а запит "
                              f"прийшов з іменем «{host_name}»"),
                    status_code=403)
        # 🔴 Запис — лише зі своєї сторінки. Ім'я в `Host` чесне й тоді, коли
        # POST шле ЧУЖА вкладка: вона звертається саме на 127.0.0.1. Токен
        # стоїть не на всіх операціях (частина лише читає, але вміє покласти
        # файл туди, куди скаже `out`), а тіло без `Content-Type` браузер шле
        # без попереднього запиту — і старіші FastAPI (заміряно на 0.115)
        # розбирають таке тіло як JSON. Тобто залежність `fastapi>=0.115`
        # лишала відкритим виклик
        # операції з аргументами чужого сайту. `Origin` браузер ставить на
        # кожен POST і скриптові підмінити не дає; інструменти без браузера
        # (агент, `curl`) його не шлють і проходять як раніше.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            foreign = _foreign_origin(request.headers.get("origin"),
                                      request.headers.get("sec-fetch-site"), raw_host)
            if foreign:
                return JSONResponse(
                    _envelope(f"запит прийшов з чужої сторінки ({foreign}) — "
                              f"змінювати простір може лише сама консоль застосунку"),
                    status_code=403)
        return await call_next(request)

    if network:
        _install_gate(app, access_key=access_key, tls=tls, static_dir=static_dir,
                      envelope=_envelope, json_response=JSONResponse,
                      html_response=HTMLResponse, request_cls=Request)

    def require_token(given: str | None) -> None:
        # `compare_digest` навмисно: порівняння рядків «у лоб» витікає довжиною
        # збігу. Тут це параноя, але дешева.
        #
        # 🔴 Порівнюються байти. На рядках `compare_digest` кидає `TypeError`,
        # щойно в них трапиться не-ASCII, — і замість чесної відмови 403
        # клієнт отримував 500 Internal Server Error. Токен приходить ззовні,
        # тобто будь-який зіпсований копіпаст перетворював відмову на збій
        # сервера, до якого фронт не має жодного пояснення.
        if not _same(given, tok):
            raise HTTPException(status_code=403, detail="потрібен токен застосунку")

    # ── сторінка ─────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # Токен вшивається в сторінку, а не видається окремим запитом: інакше
        # його міг би попросити будь-хто, і сенс токена зникав би.
        #
        # 🔴 Спрайт значків вставляється В тіло, а не підключається файлом:
        # `<use href>` до зовнішнього SVG забороняє успадкування currentColor у
        # Chrome, і всі значки стали б чорними — на темному полотні це просто
        # порожні місця. Та сама підстановка є в консолі дослідника.
        # 🔴 Сама сторінка теж без кешу. Статику ми вже закрили, але HTML
        # віддається окремим маршрутом, і без заголовка браузер кешує його
        # евристично — на свій розсуд. Тоді після оновлення застосунку
        # людина дістає стару розмітку (інший токен, інші місця під
        # модулі) при свіжих модулях, і збій виглядає як завгодно, крім
        # застарілого кешу.
        return HTMLResponse(ui.with_sprite(html.replace("{{TOKEN}}", tok)),
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    app.mount("/static", _NoCacheStatic(directory=static_dir), name="static")

    # 🔴 Спільний шар обох морд: токени, примітиви, значки, компоненти. Лежить у
    # пакеті й монтується звідти, а не копіюється у фронт: консоль дослідника
    # монтує рівно цю саму теку, і копія розійшлася б із нею тихо.
    app.mount("/ui", _NoCacheStatic(directory=ui.static_dir()), name="ui")

    # 🔴 Асети бренду віддаються з `brand/data/assets`, а не копіюються сюди.
    # Копія знака жила б у двох місцях і розходилась би тихо: у вкладці одна
    # лапка, у шапці інша. Ті самі файли йдуть у README й на сайт документації.
    from nyshporka.brand import ASSETS

    app.mount("/brand", StaticFiles(directory=ASSETS), name="brand")

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        # Ім'я `.ico` лишається історичним: браузери просять саме його, а
        # віддаємо SVG — він один на всі розміри вкладки.
        return FileResponse(ASSETS / "favicon.svg", media_type="image/svg+xml")

    # ── секції ───────────────────────────────────────────────────────────────
    def active_sections() -> frozenset[str]:
        """Ввімкнені секції зараз, а не на старті демона.

        `sections.set` міняє профіль на живому застосунку, тож знімок `space`,
        узятий при створенні, застарів би одразу після першої зміни — і
        навігація розходилась би з тим, що справді дозволено.
        """
        return _workspace().sections

    @app.get("/api/sections")
    def list_sections() -> dict[str, Any]:
        """Що ввімкнено — звідси фронт будує навігацію.

        Кнопки не зашиті в розмітку саме тому: другий перелік розходився б із
        цим тихо, і розходження виглядало б як зникла кнопка.
        """
        env = O.call("sections.show")
        return env.as_dict()

    # ── операції ─────────────────────────────────────────────────────────────
    @app.get("/api/ops")
    def list_ops() -> dict[str, Any]:
        """Перелік дій зі схемами.

        Фронт будує форми звідси, а не з переписаних вручну полів. Переписані
        розходяться з реальними — і розходяться тихо: поле, яке більше не
        приймається, лишається на екрані й мовчки не діє.
        """
        return {"ops": [{"name": o.name, "summary": o.summary,
                         "mutates": o.mutates, "long": o.long, "gui": o.gui,
                         "section": o.section, "schema": o.schema()}
                        for o in O.for_sections(active_sections())]}

    @app.post("/api/op/{name}")
    async def call_op(name: str, payload: dict[str, Any] | None = Body(default=None),
                      token_hdr: str | None = Header(default=None, alias=TOKEN_HEADER),
                      ) -> JSONResponse:
        op = O.get(name)
        if op is None:
            raise HTTPException(status_code=404, detail=f"немає операції «{name}»")
        # 🔴 Перевірка тут, а не лише в `core.ops.call()`. Довгі операції йдуть
        # повз реєстр — у чергу демона (`workers.start` нижче), тож фільтр, який
        # стоїть тільки в `call()`, пропустив би саме найдорожчі з них: читання
        # справи й завантаження з архіву.
        from nyshporka.core import sections as S

        if op.section not in active_sections():
            sec = S.get(op.section)
            label = sec.label() if sec else op.section
            raise HTTPException(
                status_code=404,
                # ⚠ Ані слова про термінал: цей самий стан застосунок уже
                # вміє показати банером із кнопкою «Увімкнути»
                # (`core/nav.js`). Два різні виходи з однієї ситуації, і
                # гірший із них показувався частіше.
                detail=(f"секція «{label}» вимкнена у профілі простору, тож "
                        f"«{name}» недоступна. Увімкнути її можна в "
                        f"«Налаштування → Частини застосунку»."))
        # 🔴 `private` тут поруч із `mutates` не випадково: читання теж буває
        # таким, якого чужа вкладка бачити не має, — розкладка диска людини
        # нічим не безпечніша за запис у нього.
        # 🔴 І `long` теж: постановка в чергу — це вже зміна стану простору
        # (журнал робіт, зайнятий процесор, зайнята карта). Довга операція без
        # `mutates` (`search.sweep`) інакше ставала в чергу з чужої вкладки
        # без жодної перевірки походження.
        if op.mutates or op.private or op.long:
            require_token(token_hdr)
        # 🔴 Системне вікно вибору відкривається на ЕКРАНІ СЕРВЕРА. Людина з
        # телефона його не побачить, а той, хто сидить за сервером, побачить
        # вікно, якого не відкривав. Перевірка стоїть до `workers.start`:
        # `pick.ask` — довга операція і пішла б у чергу.
        if _NETWORK_CONN.get() and (
                name == "pick.ask"
                or (name == "pick.can" and bool((payload or {}).get("deep")))):
            return JSONResponse(
                _envelope("системне вікно вибору відкрилось би на екрані сервера, а не "
                          "на цьому пристрої — скористайтесь гортачем тек"),
                status_code=403)
        if op.long:
            # 🔴 Причина відмови мусить дійти до людини. Постановка в чергу
            # робить справжню роботу до старту (шукає теку, рахує кадри, добирає
            # модель) — і саме там ловляться найчастіші перші помилки: не та
            # тека, порожня тека, немає ваг. Без цього перехоплення вони
            # прилітали як «Internal Server Error»: екран показував «Не вийшло»
            # без жодного слова про те, що саме, хоч слово було написане.
            try:
                job = await workers.start(bus, space, name, payload or {})
            except Exception as exc:
                text = str(exc) or type(exc).__name__
                return JSONResponse({"ok": False, "v": 1, "error": text,
                                     "warnings": [], "data": {}},
                                    status_code=400)
            return JSONResponse({"ok": True, "v": 1,
                                 "data": {"job_id": job.id, "state": str(job.state)}})
        env = O.call(name, payload or {})
        if _NETWORK_CONN.get() and name == "pick.can" and env.ok:
            # Вікна не буде саме для ЦЬОГО пристрою, хоч сервер його вміє: кнопка
            # «системне вікно» інакше вела б у відмову вище.
            env.data["can"] = False
            env.data["why"] = "системне вікно відкрилось би на екрані сервера"
        return JSONResponse(env.as_dict(), status_code=200 if env.ok else 400)

    # ── завдання ─────────────────────────────────────────────────────────────
    @app.get("/api/jobs")
    def jobs(since: int = Query(default=0)) -> dict[str, Any]:
        events, cursor = bus.since(since)
        return {"jobs": [j.as_dict() for j in bus.jobs()],
                "events": events, "seq": cursor}

    @app.get("/api/jobs/wait")
    async def jobs_wait(since: int = Query(default=0),
                        timeout_s: int = Query(default=25, ge=1, le=60),
                        ) -> dict[str, Any]:
        """Довге очікування на сервері.

        Один виклик замість чотирьох порожніх опитувань — і для браузера, і для
        агента. Таймаут це нормальна відповідь «нічого не змінилось».
        """
        events, cursor = await bus.wait(since, timeout=float(timeout_s))
        return {"jobs": [j.as_dict() for j in bus.jobs()],
                "events": events, "seq": cursor}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str,
                         token_hdr: str | None = Header(default=None,
                                                        alias=TOKEN_HEADER),
                         ) -> dict[str, Any]:
        require_token(token_hdr)
        job = await bus.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"немає завдання {job_id}")
        return job.as_dict()

    @app.post("/api/jobs/forget")
    async def forget_jobs(token_hdr: str | None = Header(default=None,
                                                         alias=TOKEN_HEADER),
                          ) -> dict[str, Any]:
        """Прибрати завершені роботи з переліку.

        🔴 Журнал переживає перезапуски, тож «Що зараз робиться» ставало
        історією всього, що колись запускали, — і свою щойно запущену роботу
        доводилось шукати серед десятка однакових рядків.
        """
        require_token(token_hdr)
        return {"forgotten": await bus.forget_finished()}

    # ── службове ─────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "workspace": str(space.root), "name": space.name,
                "jobs": len(bus.jobs())}

    return app


def _foreign_origin(origin: str | None, fetch_site: str | None, raw_host: str) -> str:
    """Чим запит видає чужу сторінку — порожньо, якщо нічим."""
    site = (fetch_site or "").lower()
    if site in ("cross-site", "same-site"):
        return site
    if origin is not None and urlsplit(origin).netloc.lower() != raw_host.lower():
        return origin
    return ""


def _host_names_connection(raw_host: str, server_addr: str) -> bool:
    """Чи `Host` мережевого запиту називає адресу, на яку з'єднання прийшло.

    Або ім'я цієї машини. Переліку інтерфейсів на старті тут немає свідомо: він
    неповний і старіє (VPN, DHCP), а адреса з'єднання — завжди правда. Від
    перев'язування імені це захищає так само: чужий сайт шле своє ім'я.
    """
    if not raw_host:
        return False
    try:
        name = (urlsplit("//" + raw_host).hostname or "").lower()
    except ValueError:
        return False
    if not name:
        return False
    try:
        return ipaddress.ip_address(name) == ipaddress.ip_address(server_addr)
    except ValueError:
        machine = socket.gethostname().lower()
        return name in (machine, f"{machine}.local")


def _install_gate(app: Any, *, access_key: str, tls: bool, static_dir: Path,
                  envelope: Any, json_response: Any, html_response: Any,
                  request_cls: Any) -> None:
    """Ворота допуску мережевих з'єднань — чисте ASGI-middleware над усім застосунком.

    🔴 Не `@app.middleware("http")`: той пропускає все, що не `http`, тобто
    websocket проходив би повз ключ. Сьогодні WS-маршрутів немає, але
    `uvicorn[standard]` ставить `websockets`, і перший же такий маршрут тихо
    обійшов би допуск. Ворота стоять ДО розгалуження за методом — GET, HEAD,
    OPTIONS і довге очікування `/api/jobs/wait` проходять через них так само.
    """
    cookie_want = _cookie_value(access_key)
    fails: dict[str, tuple[int, float]] = {}
    fail_lock = asyncio.Lock()

    def blocked(peer: str) -> bool:
        count, until = fails.get(peer, (0, 0.0))
        if until and time.monotonic() >= until:
            fails.pop(peer, None)
            return False
        return count >= FAILS_MAX

    def evict() -> None:
        """Звільнити місце в лічильнику.

        🔴 Спершу протухлі блоки, далі найстаріший НЕзаблокований запис. Доти
        витіснявся просто найстаріший, тож тисяча одноразових спроб з інших
        адрес знімала блок нападника раніше строку. Якщо заблоковані всі —
        витісняється найстаріший блок; це вже понад десять тисяч хибних спроб.
        """
        now = time.monotonic()
        for key, (_count, until) in list(fails.items()):
            if until and now >= until:
                del fails[key]
        if len(fails) < FAILS_TRACKED_MAX:
            return
        for key, (count, _until) in fails.items():
            if count < FAILS_MAX:
                del fails[key]
                return
        fails.pop(next(iter(fails)))

    def attempt(peer: str) -> int:
        """Зарахувати спробу ДО перевірки ключа; успіх лічильник скидає.

        🔴 Рахувати лише після відповіді не можна: паралельні запити з однієї
        адреси всі проходили `blocked()` раніше, ніж зараховувався перший
        провал, і сорок одночасних спроб давали сорок перевірок ключа.
        """
        if peer not in fails and len(fails) >= FAILS_TRACKED_MAX:
            evict()
        count = fails.get(peer, (0, 0.0))[0] + 1
        until = time.monotonic() + FAIL_BLOCK_SEC if count >= FAILS_MAX else 0.0
        fails[peer] = (count, until)
        return count

    def announce_block(peer: str) -> None:
        from rich.markup import escape

        from nyshporka import brand

        brand.err().print(f"[warn]адреса {escape(peer)}: {FAILS_MAX} хибних спроб допуску — "
                          f"заблоковано на {FAIL_BLOCK_SEC // 60} хв[/warn]",
                          emoji=False, highlight=False)

    class _AccessGate:
        # Параметр зветься `app`: так його передає `add_middleware`.
        def __init__(self, app: Any) -> None:
            self.asgi = app

        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            if scope["type"] not in ("http", "websocket") or _conn_is_loopback(scope):
                await self.asgi(scope, receive, send)
                return
            server_addr, port = _conn_server(scope)
            headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope.get("headers") or []}
            raw_host = headers.get("host", "")
            cookie_ok = any(_same(value, cookie_want) for value in _read_cookies(
                headers.get("cookie", ""), _cookie_name(port, tls=tls)))
            if scope["type"] == "websocket":
                if cookie_ok and _host_names_connection(raw_host, server_addr):
                    await self._inner(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
            if not _host_names_connection(raw_host, server_addr):
                await json_response(
                    envelope(f"мережевий запит мусить звертатись на адресу, на яку "
                             f"прийшов ({server_addr}), а прийшов з іменем "
                             f"«{raw_host or 'без імені'}»"),
                    status_code=403)(scope, receive, send)
                return
            path = scope.get("path", "")
            method = scope.get("method", "GET")
            if path == ACCESS_PATH:
                await self._access(scope, receive, send, headers, cookie_ok, port)
                return
            if cookie_ok:
                await self._inner(scope, receive, send)
                return
            if path == "/" and method in ("GET", "HEAD"):
                html = (static_dir / "access.html").read_text(encoding="utf-8")
                await html_response(html, headers={"Cache-Control": "no-store"})(
                    scope, receive, send)
                return
            if method in ("GET", "HEAD") and (
                    path in _GATE_OPEN or path.startswith(_GATE_OPEN_PREFIXES)):
                # Через `_inner`: перевірка імені нижче знає мережеве з'єднання
                # лише за цією позначкою, а без неї відбила б LAN-`Host` як чужий.
                await self._inner(scope, receive, send)
                return
            await json_response(
                envelope("цей пристрій ще не має допуску — відкрийте посилання з "
                         "терміналу `nysh serve` або введіть ключ доступу"),
                status_code=401)(scope, receive, send)

        async def _inner(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            mark = _NETWORK_CONN.set(True)
            try:
                await self.asgi(scope, receive, send)
            finally:
                _NETWORK_CONN.reset(mark)

        async def _access(self, scope: dict[str, Any], receive: Any, send: Any,
                          headers: dict[str, str], cookie_ok: bool, port: int) -> None:
            method = scope.get("method", "GET")
            if method == "GET":
                await json_response({"ok": True, "v": 1, "warnings": [], "error": "",
                                     "data": {"valid": cookie_ok}},
                                    headers={"Cache-Control": "no-store"})(scope, receive, send)
                return
            if method != "POST":
                await json_response(envelope("допуск — лише POST"),
                                    status_code=405)(scope, receive, send)
                return
            foreign = _foreign_origin(headers.get("origin"), headers.get("sec-fetch-site"),
                                      headers.get("host", ""))
            if foreign:
                await json_response(envelope(f"допуск запитано з чужої сторінки ({foreign})"),
                                    status_code=403)(scope, receive, send)
                return
            client = scope.get("client")
            peer = _peer_key(str(client[0])) if client else ""
            if blocked(peer):
                await json_response(
                    envelope(f"забагато хибних спроб з цієї адреси — спробуйте за "
                             f"{FAIL_BLOCK_SEC // 60} хв"),
                    status_code=429)(scope, receive, send)
                return
            too_big = json_response(envelope("завелике тіло запиту"), status_code=413)
            with contextlib.suppress(ValueError):
                if int(headers.get("content-length") or 0) > ACCESS_BODY_MAX:
                    await too_big(scope, receive, send)
                    return
            count = attempt(peer)
            raw = await _read_body(receive, ACCESS_BODY_MAX)
            if raw is None:
                await too_big(scope, receive, send)
                return
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            state = app.state
            granted = _same(body.get("key"), access_key)
            if not granted and state.pair_code and time.monotonic() < state.pair_expires:
                granted = _same(body.get("code"), state.pair_code)
                if granted:
                    state.pair_code = ""     # одноразовий
            if not granted:
                if count == FAILS_MAX:
                    announce_block(peer)
                if FAIL_DELAY_SEC:
                    async with fail_lock:
                        await asyncio.sleep(FAIL_DELAY_SEC)
                await json_response(
                    envelope("ключ чи код не підійшов (код сполучення діє "
                             f"{PAIR_TTL_SEC // 60} хв і один раз)"),
                    status_code=401)(scope, receive, send)
                return
            fails.pop(peer, None)
            res = json_response({"ok": True, "v": 1, "warnings": [], "error": "",
                                 "data": {"valid": True}},
                                headers={"Cache-Control": "no-store"})
            res.set_cookie(_cookie_name(port, tls=tls), cookie_want,
                           max_age=ACCESS_COOKIE_MAX_AGE, path="/", secure=tls,
                           httponly=True, samesite="strict")
            await res(scope, receive, send)

    app.add_middleware(_AccessGate)


def _read_cookies(header: str, name: str) -> list[str]:
    """Усі значення cookie з цим ім'ям, а не лише перше.

    Cookie не розрізняють порти: інший сервіс на тому самому хості може
    поставити однойменну, і браузер пришле обидві. Перше-збіжне тоді відбивало
    б справжній допуск.
    """
    found = []
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            found.append(v)
    return found


def _peer_key(addr: str) -> str:
    """Ключ лічильника хибних спроб: IPv4 — сама адреса, IPv6 — її /64."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return addr
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{ip}/64", strict=False))
    return str(ip)


async def _read_body(receive: Any, limit: int) -> bytes | None:
    """Тіло запиту, не більше `limit` байтів; більше — `None`.

    🔴 Лічильник — за байтами, що прийшли, а не за `Content-Length`: chunked-тіло
    заголовка довжини не має, а `Request.json()` тримав у пам'яті скільки
    завгодно. Пристрій без жодного допуску так роздував пам'ять демона
    сотнями мегабайтів.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        msg = await receive()
        if msg["type"] == "http.disconnect":
            return b"".join(chunks)
        if msg["type"] != "http.request":
            continue
        part = msg.get("body", b"")
        size += len(part)
        if size > limit:
            return None
        chunks.append(part)
        if not msg.get("more_body"):
            return b"".join(chunks)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *,
          open_browser: bool = True, confirmed: bool = False,
          rotate_key: bool = False, tls_cert: str | None = None,
          tls_key: str | None = None, show_secret: bool = True) -> None:
    """Підняти застосунок і взяти замок простору.

    🔴 Дефолт — петля, і лише вона. Це застосунок з архівом однієї людини:
    канонічні дані про живих родичів, скани, нотатки. Мережевий `host` — клас
    загроз, у якому токен не захищає нічого, тож він вимагає `confirmed=True`
    (його ставить `nysh serve --host` після застереження й підтвердження), і
    мережеві з'єднання пускаються лише зі сталим ключем доступу простору.
    `show_secret=False` — код сполучення не друкується (вивід не в термінал).
    """
    network = not is_loopback_host(host)
    if network:
        if not confirmed:
            raise ValueError("вихід у мережу підтверджується явно — `nysh serve --host` "
                             "друкує застереження й питає підтвердження")
        host = network_host(host)
        if (tls_cert is None) != (tls_key is None):
            raise ValueError("--tls-cert і --tls-key задаються лише разом")
        if tls_cert and tls_key:
            check_tls(tls_cert, tls_key)
    elif rotate_key or tls_cert or tls_key:
        raise ValueError("ключ доступу й TLS мають сенс лише з мережевим --host")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover — extras `app`
        # Повідомлення мусить назвати що поставити. «No module named uvicorn»
        # для генеалога зі сканами не є інструкцією.
        raise RuntimeError(
            "браузерна консоль потребує сервера: pip install 'nyshporka[app]'"
        ) from exc

    from nyshporka.core.lock import LockBusy, WorkspaceLock
    from nyshporka.core.workspace import workspace as _workspace

    space = _workspace()
    socks: list[socket.socket] = []
    try:
        with WorkspaceLock(space.root, port=port).acquire() as held:
            scheme = "https" if tls_cert else "http"
            if network:
                # Ключ — лише під замком: ротація з-під живого демона лишила б
                # його зі старим ключем, а людину — з неробочим посиланням.
                try:
                    key, key_path = load_access_key(space.root, rotate=rotate_key)
                except AccessKeyError as exc:
                    raise SystemExit(f"🔴 {exc}") from None
                app = create_app(space, host=host, access_key=key, tls=bool(tls_cert))
                try:
                    socks = open_sockets(host, port)
                except OSError as exc:
                    raise SystemExit(
                        f"🔴 не вдалося слухати {host}:{port}: {exc}. Адреси може не "
                        f"бути на цій машині, або порт уже зайнятий.") from None
                url = f"{scheme}://127.0.0.1:{port}/"
            else:
                app = create_app(space)
                url = f"http://{host}:{port}/"
            # Старт застосунку — те саме перше враження, що й `nysh info`, тож
            # знак і лінія бренду тут ті самі. Далі вивід перехоплює uvicorn.
            from nyshporka import __version__, brand

            out = brand.console()
            out.print(brand.banner(__version__))
            out.print(f"  [accent]{url}[/accent]")
            out.print(f"  [muted]простір: {space.root}[/muted]")
            if network:
                _print_network_banner(out, host, port, scheme=scheme,
                                      pair_code=app.state.pair_code, key_path=key_path,
                                      show_secret=show_secret, rotated=rotate_key,
                                      tls=bool(tls_cert))
            if open_browser:
                import threading
                import webbrowser
                # У мережевому режимі вкладка — завжди петля: посилання з кодом
                # сполучення в історію цієї машини не йде.
                threading.Timer(1.0, lambda: webbrowser.open(url)).start()
            # 🔴 Серце мусить битись, а не вдаритись один раз. Тут стояв
            # єдиний `held.beat()` перед `uvicorn.run`, тобто через
            # `STALE_SEC` (45 с) замок живого демона виглядав покинутим.
            # Нитка — daemon=True: вона не тримає shutdown, а `uvicorn.run`
            # блокує потік до кінця життя процесу.
            import threading as _threading

            from nyshporka.core.lock import HEARTBEAT_SEC

            stop = _threading.Event()

            def _pulse() -> None:
                while not stop.wait(HEARTBEAT_SEC):
                    # диск смикнувся — наступний удар за 10 с
                    with contextlib.suppress(OSError):
                        held.beat()

            held.beat()
            hb = _threading.Thread(target=_pulse, name="nysh-lock-beat",
                                   daemon=True)
            hb.start()
            try:
                if network:
                    # 🔴 `proxy_headers=False`: інакше uvicorn довіряє
                    # `X-Forwarded-For` від 127.0.0.1 і переписує адресу
                    # клієнта, за якою рахуються хибні спроби допуску.
                    config = uvicorn.Config(app, log_level="warning", proxy_headers=False,
                                            ssl_certfile=tls_cert, ssl_keyfile=tls_key)
                    server = uvicorn.Server(config)
                    server.run(sockets=socks)
                    # З переданими сокетами uvicorn не перевіряє, чи піднявся
                    # (на відміну від `uvicorn.run`) — без цього збій старту
                    # виглядав би як тихий вихід із кодом 0.
                    if not server.started:
                        raise SystemExit("🔴 застосунок не піднявся — причина вище")
                else:
                    uvicorn.run(app, host=host, port=port, log_level="warning")
            finally:
                stop.set()
    except LockBusy as busy:
        raise SystemExit(
            f"🔴 простір {space.root} уже зайнятий: {busy}. "
            f"Двоє писарів на один простір — це затерті нотатки, тож не піднімаю."
        ) from None
    finally:
        for sock in socks:
            sock.close()


def _print_network_banner(out: Any, host: str, port: int, *, scheme: str, pair_code: str,
                          key_path: Path, show_secret: bool, rotated: bool,
                          tls: bool) -> None:
    """Посилання для пристроїв і де взяти ключ.

    🔴 Адреси й шляхи екрануються, а емодзі вимкнено: rich читав `[fd00::5]` як
    тег розмітки й з'їдав адресу з посилання, а `:ab:` усередині IPv6 підміняв
    на 🆎 — посилання сполучення для IPv6 виходило непридатним.
    """
    from rich.markup import escape

    def say(text: str) -> None:
        out.print(text, emoji=False, highlight=False)

    addrs = _interface_addresses() if host in WILDCARDS else [host]
    say("  [warn]мережевий режим: пристрої пускаються лише з допуском[/warn]")
    for addr in addrs:
        link = f"{scheme}://{_url_host(addr)}:{port}/"
        if show_secret:
            link += f"#pair={pair_code}"
        say(f"  [accent]{escape(link)}[/accent]")
    if show_secret:
        say(f"  [muted]код сполучення в посиланні діє {PAIR_TTL_SEC // 60} хв і "
            f"один раз[/muted]")
    else:
        say("  [muted]код сполучення не друкується: вивід іде не в термінал[/muted]")
    say(f"  [muted]ключ для ручного вводу: {escape(str(key_path))}[/muted]")
    if rotated:
        say("  [warn]ключ змінено — усі сполучені пристрої вийшли[/warn]")
    if tls:
        say("  [muted]сертифікат виписаний не на 127.0.0.1 — вкладка на цій "
            "машині попередить про нього[/muted]")
