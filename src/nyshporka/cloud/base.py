"""☁️ Прогін на ЧУЖІЙ машині — один контракт на всі способи її дістати.

Читання справи впирається не у відеокарту, а в ядра: сторінка на орендованій
RTX 4090 із двома ядрами на шард іде ВДВІЧІ повільніше, ніж на домашній GTX
1650 із шістьма. Тому «хмара» тут означає рівно одне — **машина, де ядер
більше**, а не окремий рушій, окремий формат чи окремий конвеєр.

Звідси й межа. Бекенд відповідає на три питання й більше ні на що:

    acquire   дати робочу машину (орендувати на ринку — або просто описати ту,
              що в людини вже є)
    connect   транспорт до неї: виконати команду, покласти файл, забрати файл
    release   звільнити (там, де це коштує грошей)

Про HTR бекенд не знає нічого. Скільки шардів, яка модель, чим доводиться
повнота — рахує Нишпорка, тими самими функціями, що й для локального прогону.

🔴 Чому вимірювання заліза НЕ в контракті. Спокусливо додати п'ятий метод
`measure()` — і це була б помилка, бо кожен бекенд міряв би по-своєму, а
розходження тут тихе: `nproc` показує ЯДРА ХОСТА (192 при 48 проданих), і
план, побудований на обіцяному числі, дає стільки шардів, скільки машина не
тягне. Проба одна на всіх і живе в `cloud.probe`: їй досить `Session`.

🔴 Чому `id` непрозорий. У ринкового бекенда це номер інстансу, у SSH —
`user@host:port`, у майбутнього кластера — щось третє. Спроба звести їх до
спільної форми ламається на першому ж бекенді з іншою адресацією, тож `id`
лишається рядком, який розуміє тільки той бекенд, що його видав.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

#: Що бекенд уміє понад обов'язкове.
#:
#: `rent`   — машина береться на ринку й ТАРИФІКУЄТЬСЯ. Наслідок не косметичний:
#:            там, де є `rent`, `release` мусить бути викликаний обов'язково, і
#:            саме тому він виноситься у `finally`, а не в кінець щасливого шляху.
#: `cancel` — `release` справді гасить машину (а не просто рве з'єднання).
#: `market` — бекенд уміє показати вибір ДО оренди (кілька пропозицій із цінами).
Capability = Literal["rent", "cancel", "market"]

#: Куди звітувати про поступ. Сигнатура збігається з `core.progress.emit`, щоб
#: завантаження, читання й хмарний прогін виглядали для консолі однаково.
ProgressFn = Callable[..., None]


class CloudError(RuntimeError):
    """Бекенд не зміг — із поясненням для людини."""


class AuthError(CloudError):
    """Немає доступу: ключ, токен, права. Ретраї не допоможуть."""


class BoxGone(CloudError):
    """Машини більше немає.

    ⚠ Свіжий інстанс кілька хвилин «не існує» в API провайдера, і читати це як
    `BoxGone` не можна: саме так конвеєр гасив власні машини на першому ж
    опитуванні й брав нові — чотири оренди по хвилині поспіль. Бекенд кидає це
    ЛИШЕ тоді, коли машина була і зникла, а не тоді, коли її ще не видно.
    """


class BoxNotReady(CloudError):
    """Машина є, але ще не приймає з'єднань. Стан тимчасовий — можна чекати."""


@dataclass(frozen=True)
class Need:
    """Чого потребує прогін. Те, з чим бекенд іде на ринок.

    🔴 `budget_usd` і `max_hours` не послаблюються ніколи. Решту вимог можна
    зважувати (менше ядер — довше, менше VRAM — менше шардів), але гроші й
    строк — це те, чим людина обмежила захід, а не побажання.
    """

    pages: int
    #: Скільки важать кадри. Потрібне ДО оренди: диск замовляється під них, а
    #: канал передачі обирається за обсягом.
    bytes_in: int = 0
    #: Скільки відеопам'яті просить один шард.
    gb_per_shard: float = 2.5
    #: Скільки місця на машині. Кадри × 2 + запас: завищене відсікає здорові
    #: машини як «мало диска» й мовчки звужує ринок.
    disk_gb: int = 0
    max_hours: float | None = None
    budget_usd: float | None = None
    max_price_usd_h: float | None = None
    #: Скільки ядер хотілося б. Саме ядра, а не карта, визначають темп.
    prefer_cores: int = 0

    def with_disk(self, gb: int) -> Need:
        return Need(pages=self.pages, bytes_in=self.bytes_in,
                    gb_per_shard=self.gb_per_shard, disk_gb=gb,
                    max_hours=self.max_hours, budget_usd=self.budget_usd,
                    max_price_usd_h=self.max_price_usd_h,
                    prefer_cores=self.prefer_cores)


@dataclass(frozen=True)
class Box:
    """Машина, на якій буде прогін, — якою її ОБІЦЯЄ бекенд.

    🔴 Числа тут — заявка, а не факт. Реальні ядра й пам'ять дає `cloud.probe`
    вже по з'єднанню, і розбіжність між цими двома наборами чисел є окремою
    подією, яку видно в плані. Складати їх в один об'єкт означало б втратити
    саме ту різницю, заради якої проба існує.
    """

    id: str
    backend: str
    label: str = ""
    cores: float = 0.0
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    disk_gb: float = 0.0
    gpus: int = 1
    price_usd_h: float | None = None
    #: Довільні поля бекенда — їдуть у стан заходу як є, щоб `release` після
    #: перезапуску процесу мав чим адресувати машину.
    meta: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "backend": self.backend, "label": self.label,
                "cores": self.cores, "vram_gb": self.vram_gb,
                "ram_gb": self.ram_gb, "disk_gb": self.disk_gb,
                "gpus": self.gpus, "price_usd_h": self.price_usd_h,
                "meta": dict(self.meta)}

    @staticmethod
    def from_dict(d: dict[str, object]) -> Box:
        meta = d.get("meta")
        return Box(
            id=str(d.get("id") or ""), backend=str(d.get("backend") or ""),
            label=str(d.get("label") or ""),
            cores=float(d.get("cores") or 0.0),
            vram_gb=float(d.get("vram_gb") or 0.0),
            ram_gb=float(d.get("ram_gb") or 0.0),
            disk_gb=float(d.get("disk_gb") or 0.0),
            gpus=int(d.get("gpus") or 1),
            price_usd_h=(float(d["price_usd_h"])       # type: ignore[arg-type]
                         if d.get("price_usd_h") is not None else None),
            meta=dict(meta) if isinstance(meta, dict) else {})


@dataclass(frozen=True)
class Completed:
    """Результат команди на машині."""

    rc: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0


@runtime_checkable
class Session(Protocol):
    """Транспорт до машини. Усе, що потрібно Нишпорці, щоб там працювати.

    🔴 `run` віддає рядки ПО ХОДУ через `on_line`, а не лише в кінці. Прогін
    справи триває годинами, і єдиний канал, яким видно поступ, — вивід самого
    раннера (`@@PROGRESS@@`). Команда, яка віддає все на завершенні, робить
    багатогодинну роботу невидимою — а невидима робота виглядає як зависла.
    """

    def run(self, cmd: str, *, timeout: float | None = None,
            on_line: Callable[[str], None] | None = None) -> Completed: ...

    #: 🔴 Пустити ВІДЧЕПЛЕНО й повернути pid. Окремо від `run` навмисно:
    #: багатогодинна робота не має гинути разом зі з'єднанням, яким її
    #: почали. Без цього методу «прогін» означав би «сиди й тримай канал».
    def spawn(self, cmd: str, *, log: str, pidfile: str) -> int: ...

    #: Чи живий ТОЙ процес — за pid, ніколи за іменем. Пошук за патерном ловить
    #: і власну оболонку: одного разу так упало 15 шардів із 16.
    def alive(self, pid: int) -> bool: ...

    def kill(self, pid: int) -> None: ...

    def put(self, local: Path, remote: str) -> int: ...

    def get(self, remote: str, local: Path) -> int: ...

    def listdir(self, remote: str) -> list[str]: ...

    def exists(self, remote: str) -> bool: ...

    def read_text(self, remote: str, *, limit: int = 1 << 20) -> str: ...

    def mkdirs(self, remote: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class CloudBackend(Protocol):
    """Контракт бекенда. Що вміє понад обов'язкове — каже `caps`.

    Незаявлена можливість не викликається; писати заглушки, які кидають «не
    підтримується», не треба.
    """

    id: str
    label: str
    caps: frozenset[str]

    #: `target` — те, що людина написала в `--host`: ім'я записаної машини,
    #: `user@host:port`, назва пропозиції на ринку. 🔴 Порожній рядок мусить
    #: лишатись осмисленим: у ринкового бекенда це «шукай сам за `need`», і
    #: саме цей випадок робить контракт спільним для оренди й для своєї машини.
    def acquire(self, need: Need, *, target: str = "") -> Box: ...

    def connect(self, box: Box) -> Session: ...

    def release(self, box: Box, *, why: str = "") -> None: ...

    def find(self, box_id: str) -> Box | None: ...


def supports(backend: object, cap: Capability) -> bool:
    return cap in getattr(backend, "caps", frozenset())


def bills(backend: object) -> bool:
    """Чи тече лічильник, поки машина жива.

    Окрема функція, а не читання `caps` на місці: від цієї відповіді залежить,
    чи є `release` обов'язковим, і забути її в одній із гілок дорожче, ніж
    вона виглядає — рахунок за 4.4 години машини, що горіла після смерті
    процесу, вже виставлявся.
    """
    return supports(backend, "rent")
