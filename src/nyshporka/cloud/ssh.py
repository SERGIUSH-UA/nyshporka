"""🔌 Машина, яку людина вже має, — по SSH.

Вбудований бекенд і єдиний, що працює без акаунтів, ключів API й згоди
провайдера: свій сервер, робоча станція в іншій кімнаті, вже орендований бокс.
Він нічого не орендує й нічого не гасить, тому `caps` порожній, а `release`
лише закриває з'єднання.

🔴 Прогін запускається ВІДЧЕПЛЕНО, і це не оптимізація. Читання справи триває
годинами, а SSH-сесія стільки не живе: обрив каналу вбив би роботу, яку вже
оплачено часом машини. Тому команда йде через `setsid nohup … &`, а Нишпорка
далі лише ЧИТАЄ те, що процес пише на диск машини. Наслідок цінніший за сам
захист від обриву: `start` перестає бути очікуванням і стає дією, яку можна
повторити — саме на цьому тримається ідемпотентність усього заходу.

🔴 `pkill -f` за іменем раннера тут не з'явиться ніде. Патерн ловить і ВЛАСНУ
оболонку, яка містить той самий рядок у своєму командному рядку: одного разу
так упало 15 шардів із 16, і разом із ними тихо помер вивантажувач
результатів. Зупинка — тільки за pid, записаним у стані заходу.
"""
from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.cloud.base import (
    AuthError,
    Box,
    BoxNotReady,
    CloudError,
    Completed,
    Need,
)

#: Де простір тримає описи машин. Не в маркері `nyshporka.toml`: маркер описує
#: ПРОСТІР, а машини — це знаряддя, яких у того самого простору може бути
#: кілька, і міняються вони частіше.
HOSTS_FILE = "cloud.json"

#: Стандартна тека роботи на машині, якщо в описі не сказано інше.
DEFAULT_WORKDIR = "~/nysh-run"

#: Скільки чекати на з'єднання. Орендований бокс піднімається до хвилини;
#: довше чекати немає сенсу — це вже не «вантажиться», а «не пускає».
CONNECT_TIMEOUT = 30.0

#: Як часто нагадувати про себе, щоб NAT і провайдер не рвали тихий канал.
KEEPALIVE_SEC = 30


class SshUnavailable(CloudError):
    """Немає `paramiko` — бекенд є, але працювати нічим."""

    def __init__(self) -> None:
        super().__init__(
            "для роботи по SSH потрібен `paramiko`: "
            "`pip install nyshporka[cloud]`. Без нього хмарний прогін "
            "недоступний, локальне читання (`nysh read`) працює як завжди.")


@dataclass(frozen=True)
class Host:
    """Записана машина.

    🔴 Тут лежить ШЛЯХ до ключа, а не ключ і ніколи не пароль. Файл цей
    потрапляє в теку простору, яку люди кладуть у git і в хмарну синхронізацію;
    секрет, покладений сюди один раз, витікає назавжди й тихо.
    """

    name: str
    user: str
    host: str
    port: int = 22
    key: str = ""
    workdir: str = DEFAULT_WORKDIR
    python: str = "python3"
    #: Заявлене залізо — щоб показати план ДО з'єднання. Факт дає `cloud.probe`.
    cores: float = 0.0
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    gpus: int = 1

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "user": self.user, "host": self.host,
                "port": self.port, "key": self.key, "workdir": self.workdir,
                "python": self.python, "cores": self.cores,
                "vram_gb": self.vram_gb, "ram_gb": self.ram_gb, "gpus": self.gpus}


_TARGET_RE = re.compile(
    r"^(?:(?P<user>[^@/\s]+)@)?(?P<host>[^@:/\s]+)(?::(?P<port>\d+))?$")


def parse_target(target: str) -> Host | None:
    """`user@host:port` → `Host`. `None` — не схоже на адресу."""
    m = _TARGET_RE.match(target.strip())
    if not m:
        return None
    host = m.group("host")
    # 🔴 Відкидаємо те, що адресою не є, але під шаблон підходить: голе слово
    # без крапки — це майже завжди ІМ'Я записаної машини, і мовчки поїхати за
    # ним у DNS означало б давати «не знайдено хост» замість «немає такої
    # машини в переліку».
    if "." not in host and host not in ("localhost",):
        return None
    return Host(name=target, user=m.group("user") or "root", host=host,
                port=int(m.group("port") or 22))


def hosts_path() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().config / HOSTS_FILE


def load_hosts() -> list[Host]:
    """Записані машини простору. Немає файла — порожньо, це нормальний стан."""
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.utils.atomic import read_json

    try:
        raw = read_json(hosts_path(), default={})
    except WorkspaceError:
        return []
    rows = raw.get("hosts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[Host] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("host"):
            continue
        out.append(Host(
            name=str(row.get("name") or row.get("host")),
            user=str(row.get("user") or "root"),
            host=str(row["host"]),
            port=int(row.get("port") or 22),
            key=str(row.get("key") or ""),
            workdir=str(row.get("workdir") or DEFAULT_WORKDIR),
            python=str(row.get("python") or "python3"),
            cores=float(row.get("cores") or 0.0),
            vram_gb=float(row.get("vram_gb") or 0.0),
            ram_gb=float(row.get("ram_gb") or 0.0),
            gpus=int(row.get("gpus") or 1)))
    return out


def save_hosts(rows: list[Host]) -> Path:
    from nyshporka.utils.atomic import write_json

    return write_json(hosts_path(), {"hosts": [h.as_dict() for h in rows]})


def find_host(target: str) -> Host | None:
    """Машина за іменем із переліку, або розібрана адреса."""
    name = target.strip()
    if not name:
        return None
    for h in load_hosts():
        if h.name == name:
            return h
    return parse_target(name)


class SshSession:
    """Транспорт по SSH. Створюється `SshBackend.connect`."""

    def __init__(self, client: Any, host: Host) -> None:
        self._client = client
        self._sftp: Any = None
        self.host = host

    # ── команди ──────────────────────────────────────────────────────────────
    def run(self, cmd: str, *, timeout: float | None = None,
            on_line: Callable[[str], None] | None = None) -> Completed:
        """Виконати й дочекатись. Рядки віддаються по ходу, а не в кінці."""
        _, stdout, stderr = self._client.exec_command(cmd, timeout=timeout,
                                                      get_pty=False)
        out: list[str] = []
        for raw in iter(stdout.readline, ""):
            line = raw.rstrip("\r\n")
            out.append(line)
            if on_line is not None:
                on_line(line)
        rc = int(stdout.channel.recv_exit_status())
        err = stderr.read().decode("utf-8", "replace")
        return Completed(rc=rc, out="\n".join(out), err=err)

    def spawn(self, cmd: str, *, log: str, pidfile: str) -> int:
        """Пустити ВІДЧЕПЛЕНО і повернути pid.

        🔴 `setsid` обов'язковий: без нього процес лишається в групі сесії SSH
        і вмирає разом із нею — тобто рівно тоді, коли обірветься канал, заради
        переживання якого все це й робиться.
        """
        wrapped = (f"setsid nohup sh -c {shlex.quote(cmd)} "
                   f"> {shlex.quote(log)} 2>&1 < /dev/null & "
                   f"echo $! | tee {shlex.quote(pidfile)}")
        got = self.run(wrapped, timeout=CONNECT_TIMEOUT)
        pid = "".join(ch for ch in got.out if ch.isdigit())
        if not pid:
            raise CloudError(
                f"не вдалось запустити роботу на машині: rc={got.rc} "
                f"{got.err.strip() or got.out.strip()}")
        return int(pid)

    def alive(self, pid: int) -> bool:
        """Чи живий ТОЙ процес. Перевірка за pid, ніколи не за патерном."""
        if pid <= 0:
            return False
        got = self.run(f"kill -0 {int(pid)} 2>/dev/null && echo A || echo D",
                       timeout=CONNECT_TIMEOUT)
        return got.out.strip().endswith("A")

    def kill(self, pid: int) -> None:
        """Зупинити роботу за pid — разом із групою, яку створив `setsid`."""
        if pid > 0:
            self.run(f"kill -TERM -{int(pid)} 2>/dev/null || kill -TERM {int(pid)}"
                     f" 2>/dev/null || true", timeout=CONNECT_TIMEOUT)

    # ── файли ────────────────────────────────────────────────────────────────
    @property
    def sftp(self) -> Any:
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
            # ⚠ Без цього великий файл рветься на тихому каналі: качання йде
            # без жодного пакета в зворотний бік, і NAT вважає сесію мертвою.
            self._sftp.get_channel().settimeout(300.0)
        return self._sftp

    def put(self, local: Path, remote: str) -> int:
        local = Path(local)
        self.mkdirs(str(Path(remote).parent).replace("\\", "/"))
        self.sftp.put(str(local), remote)
        # 🔴 Звіряємо розмір ОДРАЗУ. Обірвана заливка лишає файл, який виглядає
        # як покладений, і виявляється це вже на боксі — після оренди, після
        # встановлення рушія, тобто найдорожчим способом.
        got = int(self.sftp.stat(remote).st_size)
        want = local.stat().st_size
        if got != want:
            raise CloudError(
                f"файл доїхав неповним: {local.name} — {got} байт замість {want}")
        return got

    def get(self, remote: str, local: Path) -> int:
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        # Качаємо у тимчасовий і перейменовуємо: обірване качання не має
        # виглядати як привезений результат.
        tmp = local.with_name(local.name + ".part")
        self.sftp.get(remote, str(tmp))
        tmp.replace(local)
        return local.stat().st_size

    def listdir(self, remote: str) -> list[str]:
        try:
            return list(self.sftp.listdir(remote))
        except FileNotFoundError:
            return []

    def exists(self, remote: str) -> bool:
        try:
            self.sftp.stat(remote)
            return True
        except FileNotFoundError:
            return False

    def read_text(self, remote: str, *, limit: int = 1 << 20) -> str:
        """Прочитати невеликий файл машини (лог, стан, підсумок)."""
        try:
            with self.sftp.open(remote, "r") as fh:
                return bytes(fh.read(limit)).decode("utf-8", "replace")
        except FileNotFoundError:
            return ""

    def mkdirs(self, remote: str) -> None:
        self.run(f"mkdir -p {shlex.quote(remote)}", timeout=CONNECT_TIMEOUT)

    def close(self) -> None:
        try:
            if self._sftp is not None:
                self._sftp.close()
        finally:
            self._sftp = None
            self._client.close()


def _load_key(path: Path) -> Any:
    """Ключ явним типом.

    🔴 Не `key_filename=`. Paramiko при ньому перебирає типи сам і спотикається
    на розборі DSA — виняток летить із парсера ЧУЖОГО формату, а виглядає як
    відмова автентифікації, тобто веде розслідування зовсім не туди.
    """
    import paramiko

    last: Exception | None = None
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(str(path))
        except Exception as exc:      # не той тип — пробуємо наступний
            last = exc
    raise AuthError(f"ключ {path} не читається жодним відомим типом "
                    f"(ed25519/rsa/ecdsa): {last}")


class SshBackend:
    """Машина, яка в людини вже є."""

    id = "ssh"
    label = "Своя машина по SSH"
    #: Порожньо: не орендує, не тарифікує, гасити нічого.
    caps: frozenset[str] = frozenset()

    def acquire(self, need: Need, *, target: str = "") -> Box:
        host = find_host(target)
        if host is None:
            known = ", ".join(h.name for h in load_hosts()) or "(жодної)"
            raise CloudError(
                f"не знаю машини «{target}». Записані: {known}. "
                f"Додати: `nysh cloud hosts add <ім'я> <user@host[:порт]>`, "
                f"або вкажіть адресу прямо.")
        return self._box(host)

    def connect(self, box: Box) -> SshSession:
        host = self._host_of(box)
        try:
            import paramiko
        except ImportError:
            raise SshUnavailable() from None

        client = paramiko.SSHClient()
        # ⚠ Свідомо `AutoAdd`: орендований бокс щоразу новий, і питати людину
        # про відбиток машини, яку вона щойно взяла на годину, — обряд без
        # змісту. Для постійного сервера ключ і так уже в `known_hosts`.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, Any] = {
            "hostname": host.host, "port": host.port, "username": host.user,
            "timeout": CONNECT_TIMEOUT, "banner_timeout": CONNECT_TIMEOUT,
            "auth_timeout": CONNECT_TIMEOUT}
        if host.key:
            kwargs["pkey"] = _load_key(Path(host.key).expanduser())
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        try:
            client.connect(**kwargs)
        except Exception as exc:
            name = type(exc).__name__
            if "Authentication" in name:
                raise AuthError(
                    f"{host.target} не прийняв ключ. Перевірте `key` в описі "
                    f"машини й доступ: `ssh {host.user}@{host.host}`") from exc
            raise BoxNotReady(
                f"{host.target} не відповідає ({name}: {exc})") from exc
        tr = client.get_transport()
        if tr is not None:
            tr.set_keepalive(KEEPALIVE_SEC)
        return SshSession(client, host)

    def release(self, box: Box, *, why: str = "") -> None:
        """Нічого не гасить — машина не наша.

        Мовчки й без помилки: `release` кличеться з `finally` на кожному шляху,
        і бекенд, який тут відмовляє, перетворював би звичайне завершення на
        збій.
        """
        return None

    def find(self, box_id: str) -> Box | None:
        host = find_host(box_id)
        return self._box(host) if host is not None else None

    # ── внутрішнє ────────────────────────────────────────────────────────────
    def _box(self, host: Host) -> Box:
        return Box(id=host.name, backend=self.id, label=host.target,
                   cores=host.cores, vram_gb=host.vram_gb, ram_gb=host.ram_gb,
                   gpus=host.gpus, price_usd_h=None,
                   meta={"host": json.loads(json.dumps(host.as_dict()))})

    def _host_of(self, box: Box) -> Host:
        raw = box.meta.get("host") if isinstance(box.meta, dict) else None
        if isinstance(raw, dict) and raw.get("host"):
            return Host(
                name=str(raw.get("name") or raw["host"]),
                user=str(raw.get("user") or "root"), host=str(raw["host"]),
                port=int(raw.get("port") or 22), key=str(raw.get("key") or ""),
                workdir=str(raw.get("workdir") or DEFAULT_WORKDIR),
                python=str(raw.get("python") or "python3"),
                cores=float(raw.get("cores") or 0.0),
                vram_gb=float(raw.get("vram_gb") or 0.0),
                ram_gb=float(raw.get("ram_gb") or 0.0),
                gpus=int(raw.get("gpus") or 1))
        # Стан заходу пережив зміну опису машини — беремо з переліку заново.
        host = find_host(box.id)
        if host is None:
            raise CloudError(f"машина «{box.id}» зникла з переліку — "
                             f"опис заходу є, а адреси немає")
        return host
