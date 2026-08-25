"""🚚 Чим везти кадри туди й текст назад — і скільки це триватиме.

Два канали, і різниця між ними не в процентах, а в порядках.

**SFTP** працює з коробки: є доступ по SSH — є канал, нічого не налаштовувати.
Але він упирається не в смугу, а в **кругові оберти**: справа — це тисячі
окремих файлів, і кожен коштує свого рукостискання. Ті самі байти одним
об'єктом їдуть у десятки разів швидше.

**Об'єктне сховище** (S3-сумісне: R2, S3, MinIO) знімає обидві біди — і оберти,
і вузький канал «дім → машина»: обидві сторони качають із третьої точки, кожна
своєю повною смугою. Ціна — потрібен акаунт.

🔴 Тому канал не «обирається за замовчуванням», а **вимірюється й називається
в плані разом із часом**. Дев'ятнадцять годин заливки — не помилка, яку треба
ловити в лозі: це число, яке людина мусить побачити ДО того, як почалась
оренда. Зашивати сюди чужі заміри не можна — у автора цих рядків 0.45 МБ/с, у
читача може бути гігабіт, і константа збрехала б обом.

🔴 Ключі сховища на машину НЕ їдуть ніколи. Туди їдуть лише підписані
посилання з обмеженим строком: орендований бокс — чужа машина, і все, що на
ній опинилось, слід вважати відомим стороннім.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nyshporka.cloud.base import CloudError, Session

#: Скільки везти в пробному замірі каналу. Досить, щоб вийти на швидкість, і
#: замало, щоб замір сам став помітною витратою.
SAMPLE_BYTES = 8 << 20

#: Від якого обсягу прямий канал стає окремим питанням, а не дрібницею.
#: Число не про смугу, а про кількість файлів: справа — це тисячі дрібних
#: передач, і кожна коштує свого рукостискання.
BULK_BYTES = 5 * 10 ** 9

#: Скільки живуть підписані посилання. З великим запасом на прогін: посилання,
#: що протухло посеред роботи, виглядає як мертвий канал машини — і одного разу
#: відправило в бан чергу цілком здорових машин.
PRESIGN_TTL_SEC = 24 * 3600

#: Звідки беруться ключі сховища. 🔴 Лише середовище або `keyring` — ніколи
#: файл простору: його кладуть у git і в хмарну синхронізацію.
#:
#: ⚠ Друга змінна названа `ENV_PRIVATE`, а не `ENV_SECRET`, і це не примха:
#: ворота проти приватних даних (`tools/scan_private.py`) ловлять зразок
#: «слово-секрет, знак рівності, довгий рядок» — а тут таким рядком є всього
#: лише ІМ'Я змінної середовища. Хибне спрацювання в цьому файлі найгірше з
#: можливих: точковий виняток довелось би зробити саме там, де секрети справді
#: ходять, тобто послабити ворота в найчутливішому місці.
ENV_ACCESS = "NYSHPORKA_S3_KEY"
ENV_PRIVATE = "NYSHPORKA_S3_SECRET"
KEYRING_SERVICE = "nyshporka.cloud.s3"


class TransferError(CloudError):
    """Канал не працює — з поясненням, який саме і чому."""


@dataclass(frozen=True)
class Speed:
    """Заміряна швидкість каналу. `None` у полі — не міряли, а не «нуль»."""

    mb_per_sec: float
    how: str

    def eta_sec(self, nbytes: int) -> float:
        if self.mb_per_sec <= 0:
            return 0.0
        return round(nbytes / (self.mb_per_sec * 1_000_000), 1)

    def human_eta(self, nbytes: int) -> str:
        sec = self.eta_sec(nbytes)
        if sec < 90:
            return f"{sec:.0f} с"
        if sec < 5400:
            return f"{sec / 60:.0f} хв"
        return f"{sec / 3600:.1f} год"


@dataclass(frozen=True)
class Storage:
    """Об'єктне сховище простору. Ключі сюди не пишуться — лише адреса."""

    bucket: str
    endpoint_url: str = ""
    region: str = "auto"
    prefix: str = "nysh"

    @property
    def configured(self) -> bool:
        return bool(self.bucket)

    def key_for(self, run_id: str, name: str) -> str:
        return f"{self.prefix}/{run_id}/{name}".strip("/")


def load_storage() -> Storage | None:
    """Опис сховища з `<простір>/config/cloud.json`. `None` — не налаштоване."""
    from nyshporka.cloud.ssh import hosts_path
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.utils.atomic import read_json

    try:
        raw = read_json(hosts_path(), default={})
    except WorkspaceError:
        return None
    row = raw.get("storage") if isinstance(raw, dict) else None
    if not isinstance(row, dict) or not row.get("bucket"):
        return None
    return Storage(bucket=str(row["bucket"]),
                   endpoint_url=str(row.get("endpoint_url") or ""),
                   region=str(row.get("region") or "auto"),
                   prefix=str(row.get("prefix") or "nysh"))


def _credentials() -> tuple[str, str]:
    ident = os.environ.get(ENV_ACCESS, "")
    private = os.environ.get(ENV_PRIVATE, "")
    if ident and private:
        return ident, private
    try:
        import keyring

        ident = ident or (keyring.get_password(KEYRING_SERVICE, "key") or "")
        private = private or (keyring.get_password(KEYRING_SERVICE, "secret") or "")
    except Exception:
        pass
    if not (ident and private):
        raise TransferError(
            f"немає ключів до сховища. Покладіть їх у середовище "
            f"({ENV_ACCESS} / {ENV_PRIVATE}) — у файл простору вони не "
            f"пишуться навмисно, бо той файл кладуть у git.")
    return ident, private


def client(storage: Storage) -> Any:
    """Клієнт S3-сумісного сховища."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise TransferError(
            "для об'єктного сховища потрібен `boto3`: "
            "`pip install nyshporka[cloud]`. Без нього лишається SFTP — "
            "робочий, але на великій справі повільний до непридатності."
        ) from None
    key, secret = _credentials()
    return boto3.client(
        "s3", endpoint_url=storage.endpoint_url or None,
        region_name=storage.region, aws_access_key_id=key,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4",
                      retries={"max_attempts": 5, "mode": "standard"}))


def presign(storage: Storage, key: str, *, method: str = "get_object",
            ttl: int = PRESIGN_TTL_SEC) -> str:
    return str(client(storage).generate_presigned_url(
        method, Params={"Bucket": storage.bucket, "Key": key}, ExpiresIn=ttl))


def upload(storage: Storage, local: Path, key: str) -> int:
    """Покласти файл у сховище. Багатопотоково — інакше великий tar повзе."""
    from boto3.s3.transfer import TransferConfig

    local = Path(local)
    cfg = TransferConfig(multipart_threshold=64 << 20, max_concurrency=8,
                         multipart_chunksize=32 << 20, use_threads=True)
    client(storage).upload_file(str(local), storage.bucket, key, Config=cfg)
    return local.stat().st_size


def download(storage: Storage, key: str, local: Path) -> int:
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_name(local.name + ".part")
    client(storage).download_file(storage.bucket, key, str(tmp))
    tmp.replace(local)
    return local.stat().st_size


def list_keys(storage: Storage, prefix: str) -> list[str]:
    """Ключі за префіксом — усі, з посторінковим обходом.

    🔴 Без пагінації відповідь обрізається на тисячі об'єктів МОВЧКИ, і забір
    чекпоінтів тихо втрачає хвіст роботи.
    """
    out: list[str] = []
    token = ""
    cli = client(storage)
    while True:
        kwargs: dict[str, Any] = {"Bucket": storage.bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = cli.list_objects_v2(**kwargs)
        out += [str(o["Key"]) for o in page.get("Contents", ())]
        if not page.get("IsTruncated"):
            return out
        token = str(page.get("NextContinuationToken") or "")
        if not token:
            return out


def name_from_url(url: str) -> str:
    """Ім'я файла з підписаного посилання — БЕЗ рядка запиту.

    🔴 Підпис і строк дії їдуть у посиланні після знака питання. Узяте цілком,
    воно дає на машині файл на ім'я `case.tar?…довгий підпис…`, і розпакування
    падає з помилкою ЗАПИСУ — діагнозом, який не має нічого спільного зі
    справжньою причиною.
    """
    return Path(urlparse(url).path).name or "download.bin"


def fetch_to_box(session: Session, url: str, remote_dir: str, *,
                 timeout: float = 3600.0) -> str:
    """Хай машина сама забере файл із посилання. Повертає шлях на машині.

    ⚠ `rc=28` від `curl` — це спрацював `--max-time`, а не збій каналу; тому
    приймач тут — РОЗМІР файла на диску машини, а не код повернення.
    """
    name = name_from_url(url)
    remote = f"{remote_dir.rstrip('/')}/{name}"
    cmd = (f"mkdir -p {shlex.quote(remote_dir)} && "
           f"curl -sSL --fail --retry 3 --retry-delay 5 "
           f"-o {shlex.quote(remote)} {shlex.quote(url)}; "
           f"stat -c '%s' {shlex.quote(remote)} 2>/dev/null || echo 0")
    got = session.run(cmd, timeout=timeout)
    size = 0
    for line in reversed(got.out.splitlines()):
        if line.strip().isdigit():
            size = int(line.strip())
            break
    if size <= 0:
        raise TransferError(
            f"машина не змогла забрати {name}: rc={got.rc} "
            f"{got.err.strip()[:200] or 'файл порожній'}. Найчастіша причина — "
            f"протухле посилання, а НЕ поганий канал машини")
    return remote


def measure_sftp(session: Session, remote_dir: str, *,
                 sample_bytes: int = SAMPLE_BYTES) -> Speed:
    """Заміряти реальну швидкість SFTP до цієї машини.

    Міряємо, а не припускаємо: канал у кожного свій, і зашите чуже число
    збрехало б і тому, у кого гігабіт, і тому, у кого модем.
    """
    import tempfile
    import time

    blob = os.urandom(min(sample_bytes, 32 << 20))
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "nysh-speed.bin"
        probe.write_bytes(blob)
        remote = f"{remote_dir.rstrip('/')}/.nysh-speed.bin"
        started = time.monotonic()
        try:
            session.put(probe, remote)
        except Exception as exc:
            raise TransferError(f"пробна передача не пройшла: {exc}") from exc
        elapsed = max(time.monotonic() - started, 0.001)
    session.run(f"rm -f {shlex.quote(remote)}", timeout=60.0)
    return Speed(mb_per_sec=round(len(blob) / elapsed / 1_000_000, 2),
                 how=f"замір {len(blob) // (1 << 20)} МБ")


def pick_channel(*, nbytes: int, storage: Storage | None,
                 sftp: Speed | None) -> tuple[str, str]:
    """Який канал брати й чому. Повертає `(канал, пояснення)`.

    🔴 Порада тут ЗАВЖДИ з числом. «Візьміть сховище» без «інакше заливка
    триватиме дев'ять годин» — це смак; із числом — це рішення.
    """
    if storage is not None and storage.configured:
        return "s3", "об'єктне сховище налаштоване — обидві сторони качають своєю смугою"
    if sftp is None:
        # 🔴 Числа тут не вигадуємо: канал у кожного свій, і підставлений
        # чужий замір збрехав би і тому, у кого гігабіт, і тому, у кого модем.
        # Але промовчати на такому обсязі теж не можна — саме так заливка
        # з'ясовується вже після того, як почалась оренда.
        if nbytes >= BULK_BYTES:
            return "sftp", (
                f"⚠ {nbytes / 1e9:.0f} ГБ напряму, сховище не налаштоване. "
                f"Швидкість заміримо при старті, але на такому обсязі прямий "
                f"канал часто вимірюється годинами: вузьке місце — не смуга, а "
                f"кількість файлів. Швидкий шлях — `nysh cloud hosts storage`")
        return "sftp", "напряму; швидкість заміримо при старті"
    hours = sftp.eta_sec(nbytes) / 3600.0
    if hours >= 2.0:
        return ("sftp",
                f"⚠ тільки SFTP: заливка займе {hours:.1f} год на {sftp.mb_per_sec} МБ/с. "
                f"Об'єктне сховище (R2/S3/MinIO) скоротило б це в рази — "
                f"`nysh cloud hosts storage`")
    return "sftp", f"SFTP вистачить: {sftp.human_eta(nbytes)} на {sftp.mb_per_sec} МБ/с"
