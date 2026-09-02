"""🗂 Реєстр джерел: вбудовані + сторонні через entry points.

Архівів більше, ніж ми колись реалізуємо, і половина з них цікава рівно одному
досліднику. Тому джерело — плагін: сторонній пакет оголошує
`nyshporka.sources` у своїх entry points, і його архів з'являється в застосунку
без жодної правки тут.

🔴 Збій одного плагіна не має гасити решту. Сторонній пакет може бути зламаний,
несумісний або просто недописаний; якби реєстр падав на першому такому, один
чужий архів забирав би з собою всі решта — разом із локальною текою, тобто
головним шляхом користувача.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from nyshporka.sources.base import Capability, Source, supports
from nyshporka.sources.local import LocalSource

ENTRY_POINT_GROUP = "nyshporka.sources"


@dataclass
class Registry:
    sources: dict[str, Source] = field(default_factory=dict)
    #: Плагіни, які не завантажились: (ім'я, причина). Ховати їх не можна —
    #: «мого архіву немає в списку» інакше не має пояснення.
    broken: list[tuple[str, str]] = field(default_factory=list)

    def get(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def all(self) -> list[Source]:
        return [self.sources[k] for k in sorted(self.sources)]

    def with_cap(self, cap: Capability) -> list[Source]:
        return [s for s in self.all() if supports(s, cap)]


def _builtin(workspace: Path | None = None) -> list[Source]:
    """Вбудовані джерела. Мережеві потребують простору — для кешів і каталогів.

    🔴 Простір передається, а не резолвиться всередині джерела. Джерело, яке
    саме шукає простір, стає другим резолвером поруч із головним — і вони
    розходяться тихо: каталог кладеться в один корінь, а шукається в іншому,
    після чого пошук чесно віддає нуль.
    """
    from nyshporka.archives import active
    from nyshporka.sources.archium import ArchiumSource
    from nyshporka.sources.commons import CommonsSource
    from nyshporka.sources.duck import DuckSource
    from nyshporka.sources.fsfilm import FilmMirrorSource
    from nyshporka.sources.ridni import RidniSource

    out: list[Source] = [LocalSource()]
    # 🏛 ARCHIUM — один рушій на кілька архівів, тож джерел стільки, скільки
    # майданчиків описано в паку. Окремими id, а не одним із параметром: `id`
    # їде в «де шукали» кожної відповіді, і спільне ім'я на два різні архіви
    # зробило б знаменник пошуку неправдивим.
    sites = active().sites("archium")
    if sites:
        out += [ArchiumSource(workspace, site=site, repo=repo) for repo, site in sites]
    else:
        out.append(ArchiumSource(workspace))   # пак без майданчиків — старий шлях
    out.append(CommonsSource(workspace))
    out.append(FilmMirrorSource(workspace))
    # 🦆 Зведений покажчик. Єдине джерело, яке шукає без попереднього обходу і
    # бачить справу незалежно від того, чи її оцифровано, — тобто відповідає
    # там, де решта віддає нуль на голій установці.
    out.append(cast("Source", DuckSource(workspace)))
    # 🗺 Каталог за СЕЛОМ. Питання «які книги є про моє село» описи фондів не
    # ставлять узагалі: вони перелічують справи фонду. Тут же відповідь приходить
    # разом із прямими адресами копій — і, головне, з роками, яких у фонді немає.
    out.append(cast("Source", RidniSource(workspace)))
    return out


def _from_entry_points() -> tuple[list[Source], list[tuple[str, str]]]:
    out: list[Source] = []
    broken: list[tuple[str, str]] = []
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover — Python без importlib.metadata
        return out, broken
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:
        return out, [("<entry_points>", f"{type(exc).__name__}: {exc}")]
    for ep in eps:
        try:
            factory = ep.load()
            src = factory() if callable(factory) else factory
            if not getattr(src, "id", ""):
                raise ValueError("джерело не має `id`")
            out.append(src)
        except Exception as exc:
            broken.append((ep.name, f"{type(exc).__name__}: {exc}"))
    return out, broken


def load(workspace: Path | None = None) -> Registry:
    """Зібрати реєстр. Вбудовані джерела не перекриваються плагінами.

    Плагін із тим самим `id` відкидається, а не заміщає вбудоване: інакше
    сторонній пакет міг би мовчки підмінити локальну теку — шлях, яким
    користувач кладе свої скани.
    """
    reg = Registry()
    for src in _builtin(workspace):
        reg.sources[src.id] = src
    plugins, broken = _from_entry_points()
    reg.broken.extend(broken)
    for src in plugins:
        if src.id in reg.sources:
            reg.broken.append((src.id, "збігається з іменем вбудованого джерела"))
            continue
        reg.sources[src.id] = src
    return reg
