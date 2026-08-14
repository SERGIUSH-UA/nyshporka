"""📥 Джерело матеріалу — один контракт на архіви, дзеркала й локальні теки.

Досі кожен архів мав власний скрипт із власними прапорцями, і жоден із них не
було видно з застосунку: вкладка «звідки взяти справу» не існувала, бо не
існувало спільної форми. Тут ця форма з'являється.

Одне джерело відповідає на чотири питання, і кожне з них опційне:

    search    «де взагалі є щось про моє село» — пошук по каталогу
    browse    «що лежить у цьому фонді» — дерево
    manifest  «що саме принесе завантаження» — скільки кадрів, який покажчик
    fetch     власне завантаження, з прогресом

🔴 Чому `manifest` окремо від `fetch`. Справа буває на кілька гігабайтів, і
питання «скільки це» мусить мати відповідь ДО того, як почалось качання. Без
цього єдиний спосіб дізнатись обсяг — почати й подивитись, а перервана закачка
лишає теку в невизначеному стані.

🔴 Чому `ref` непрозорий. У кожного архіву своя адресація: у ARCHIUM це номер
справи, у дзеркала плівок — ідентифікатор теки, у локальної теки — шлях.
Спроба звести їх до спільного «ключа справи» ламається на першому ж архіві з
іншою нумерацією, тож `ref` лишається рядком, який розуміє тільки те джерело,
що його видало.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

Capability = Literal["search", "browse", "manifest", "fetch"]

#: Куди джерело звітує про поступ. Сигнатура навмисно збігається з
#: `core.progress.emit`, щоб завантаження, читання й трен виглядали однаково.
ProgressFn = Callable[..., None]


@dataclass(frozen=True)
class Hit:
    """Знахідка в каталозі — те, що показують у списку результатів."""

    source: str
    ref: str
    title: str = ""
    years: str = ""
    place: str = ""
    shifra: str = ""
    frames: int | None = None
    #: Чи можна це завантажити прямо звідси. Каталог часто знає про справу
    #: більше, ніж уміє дати: опис є, а сканів немає. Показати таку справу
    #: корисно (це відповідь «де шукати»), але обіцяти завантаження — ні.
    acquirable: bool = False
    note: str = ""


@dataclass(frozen=True)
class Node:
    """Вузол дерева при перегляді джерела."""

    ref: str
    label: str
    kind: Literal["folder", "case", "file"] = "folder"
    frames: int | None = None
    size: int | None = None


@dataclass(frozen=True)
class Sheet:
    """Рядок поаркушевого покажчика: які кадри що накривають.

    🔴 Це найцінніше, що може дати джерело, і воно рідко буває. Покажчик
    відповідає «де метрики мого села» БЕЗ жодного завантаження — тобто закриває
    найбільшу аудиторію одним запитом.
    """

    frm: int
    to: int
    label: str = ""


@dataclass(frozen=True)
class Manifest:
    """Що саме принесе завантаження."""

    source: str
    ref: str
    title: str = ""
    frames: int = 0
    bytes_estimate: int | None = None
    sheets: tuple[Sheet, ...] = ()
    #: Довільні поля джерела — потраплять у сайдкар теки як є.
    meta: dict[str, object] = field(default_factory=dict)

    def frames_for(self, label_part: str) -> tuple[int, int] | None:
        """Діапазон кадрів за фрагментом підпису покажчика."""
        needle = label_part.casefold()
        for s in self.sheets:
            if needle in s.label.casefold():
                return (s.frm, s.to)
        return None


@dataclass
class FetchResult:
    dest: Path
    frames: int = 0
    bytes: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.frames > 0 and not self.errors


class SourceError(RuntimeError):
    """Джерело не змогло виконати запит — із поясненням для людини."""


@runtime_checkable
class Source(Protocol):
    """Контракт джерела. Реалізація оголошує, що вміє, через `caps`.

    Незаявлена можливість не викликається; реалізовувати заглушки, які кидають
    «не підтримується», не треба — застосунок питає `caps` і не пропонує
    користувачу того, чого джерело не вміє.
    """

    id: str
    label: str
    caps: frozenset[str]

    def search(self, q: str, *, limit: int = 30) -> list[Hit]: ...

    def browse(self, ref: str | None = None) -> list[Node]: ...

    def manifest(self, ref: str) -> Manifest: ...

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult: ...


def supports(src: object, cap: Capability) -> bool:
    return cap in getattr(src, "caps", frozenset())
