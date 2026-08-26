"""🧾 Збирач реєстру опису: контракт.

🔴 Чому це не джерело, хоч обидва ходять у мережу.

Джерело відповідає на «де взяти цей документ», і його адреса (`ref`) непрозора
за побудовою — розуміти її має лише воно саме. Збирач відповідає на «що взагалі
існує у фонді» й видає рядки в канонічному ключі архівіста
`(опис, справа, літера)`. Це протилежні обіцянки, і тримати їх в одному класі
означало б, що наступний читач знайде дві суперечливі в одному місці.

Множини теж не збігаються, причому рівно посередині: Duck нічого не віддає (це
чистий покажчик, без завантаження), а дзеркало плівок — навпаки, повноцінне
джерело, для якого пофондового реєстру не існує в природі.

І знаменник іншого складу. Завантаження звітує кадрами й байтами; збирачеві
треба сказати «ці 61 позицію я не вважаю справами, і ось чому» — інакше
«вільний номер» і «Справа вибула» стають фантомами в черзі завантаження, за
якою потім замовляють документи в архіві.

Що збирача з джерелом зшиває — поле `source_id`: реєстр каже не лише «скан є»,
а й чим його взяти.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

#: Що збирач уміє дістати. Оголошується, як `caps` у джерела.
CAPABILITIES = ("opys", "titles", "years", "folios", "scans", "online")


class CollectError(RuntimeError):
    """Зібрати не вдалось, і причина сформульована для людини."""


@dataclass(frozen=True)
class Target:
    """Що збираємо: фонд конкретного архіву, можливо не весь."""

    repo: str                       # код архіву в нашому паку: "CDIAK"
    fond: str                       # "224"
    opys: tuple[str, ...] = ()      # порожньо = всі описи

    @property
    def fond_id(self) -> str:
        """Тека фонду в просторі: `cdiak_224`."""
        return f"{self.repo.lower()}_{self.fond}"


@dataclass(frozen=True)
class Blind:
    """Чого джерело не бачить або не вважає справою.

    🔴 Частина знаменника, а не примітка. Позиції «вільний номер» і «Справа
    вибула» приходять рядками нарівні зі справами; пущені в реєстр, вони стають
    фантомами в черзі завантаження — і за ними замовляють документ, якого немає.
    Відсіяне не викидається: `where` каже, куди воно лягло.
    """

    kind: str                       # void | no_shifra | capped | non_numeric_opys
    count: int
    why: str                        # людською, з наслідком
    where: Path | None = None


@dataclass(frozen=True)
class Plan:
    """Що принесе збирання — до того, як воно почалось.

    Те саме, чим `manifest` є для завантаження: збирання фонду на три тисячі
    справ при п'яти запитах на десять секунд — це десятки хвилин, і питання
    «скільки це» мусить мати відповідь до старту, а не після.
    """

    collector: str
    ready: bool
    why: str = ""                   # коли не готові — з командою полагодження
    opys: tuple[str, ...] = ()
    requests: int | None = None
    eta_sec: float | None = None
    needs: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"collector": self.collector, "ready": self.ready, "why": self.why,
                "opys": list(self.opys), "requests": self.requests,
                "eta_sec": self.eta_sec, "needs": dict(self.needs)}


@dataclass(frozen=True)
class CollectResult:
    """Скільки зібрано — і чого не видно.

    🔴 Приймач збирання — не число рядків. Позиційний розбір таблиці опису вже
    одного разу віддав 2944 справи з однаковим заголовком і нулем аркушів, і за
    числом рядків це виглядало повним успіхом. Тому поруч їде `quality`: скільки
    рядків мають роки, аркуші, заголовок.
    """

    collector: str
    out: Path
    extra: tuple[Path, ...] = ()
    rows: int = 0
    kept: int = 0                            # рядки описів, яких запуск не чіпав
    opys_seen: tuple[str, ...] = ()
    opys_collected: tuple[str, ...] = ()
    quality: dict[str, int] = field(default_factory=dict)
    blind: tuple[Blind, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "collector": self.collector, "out": str(self.out),
            "extra": [str(p) for p in self.extra],
            "rows": self.rows, "kept": self.kept,
            "opys_seen": list(self.opys_seen),
            "opys_collected": list(self.opys_collected),
            "quality": dict(self.quality),
            "blind": [{"kind": b.kind, "count": b.count, "why": b.why,
                       "where": str(b.where) if b.where else ""} for b in self.blind],
            "notes": list(self.notes),
        }


@runtime_checkable
class Collector(Protocol):
    """Мінімум, який робить збирача збирачем."""

    id: str
    label: str
    filename: str          # ім'я файла в `registry/`, яке потім читає злиття
    source_id: str         # чим качати знайдене; порожньо — це джерело не віддає
    caps: frozenset[str]

    def plan(self, target: Target) -> Plan: ...

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult: ...
