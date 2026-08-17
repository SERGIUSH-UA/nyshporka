"""📦 Де лежать паки каталогу і як їх відкрити.

Одиниця тут — **пак**: незмінний файл із одним зрізом одного джерела. Кілька
паків одного домену читаються **віялом**: той самий SQL проти кожного, зведення
в Python.

🔴 **Чому віяло, а не `ATTACH`.** Стеля `SQLITE_MAX_ATTACHED` — 10 баз за
замовчуванням; на двадцяти фондах схема просто зламалась би. Але головне навіть
не це: віяло **дає покриття задарма** — перелік паків, які відповіли, і Є
відповіддю на питання «де саме шукали». З `ATTACH` це довелось би вести окремо,
тобто з ризиком, що воно розійдеться з дійсністю.

🔴 **З'єднання не кешуються між викликами.** Консоль виконує читання через
`asyncio.to_thread`, тобто в РІЗНИХ потоках, а з'єднання `sqlite3` прив'язане до
потоку, що його створив. Кешоване з'єднання дало б `ProgrammingError` посеред
запиту — помилку, яка виглядає як «каталог зламався». Кешується натомість
ДИСКАВЕРІ (перелік паків і їхня мета): воно й коштує, а відкриття read-only
з'єднання — частки мілісекунди.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.catalog import schema

#: Ескейп-хетч: каталог на спільному диску родини, каталог із флешки в читальні.
ENV_CATALOG = "NYSHPORKA_CATALOG"

#: Ім'я теки всередині `user_data_dir`.
DIR_NAME = "catalog"


class CatalogMissing(RuntimeError):
    """Питаного домену в каталозі немає — і нуль тут нічого не означав би."""


@dataclass(frozen=True)
class InstalledPack:
    pack_id: str
    domain: str
    path: Path
    taken: str = ""
    rows: int = 0
    size: int = 0
    note: str = ""
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem


@dataclass(frozen=True)
class Coverage:
    """«Де саме шукали» — машиночитно. Їде в кожній відповіді каталогу."""

    pack_id: str
    domain: str
    taken: str
    rows: int
    scope: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"pack": self.pack_id, "domain": self.domain, "taken": self.taken,
                "rows": self.rows, "scope": self.scope}

    def human(self) -> str:
        taken = f", зріз {self.taken}" if self.taken else ""
        scope = f" · {self.scope}" if self.scope else ""
        return f"{self.pack_id}{taken}{scope}"


#: Де беруть паки довідників. Тримається тут, а не в тексті повідомлення:
#: адресу називають і `catalog list`, і `geog build`, і реєстр опису, а три
#: копії рядка розходяться тихо — і рівно тоді, коли людині нікуди піти.
RELEASES_URL = "https://github.com/SERGIUSH-UA/nyshporka/releases"


def catalog_dir() -> Path:
    """Тека каталогу. `user_data_dir`, а не `user_cache_dir` — див. `__init__`."""
    env = os.environ.get(ENV_CATALOG)
    if env:
        return Path(env)
    from platformdirs import user_data_dir

    return Path(user_data_dir("Nyshporka", appauthor=False)) / DIR_NAME


def own_path() -> Path | None:
    """Власна база користувача — ПОВЕРХ привезеного каталогу, у ЙОГО просторі.

    🔴 У просторі, а не в каталозі, бо це його робота: він транскрибував опис
    свого фонду, він прочитав обкладинки. Спільний каталог можна знести й
    поставити заново — власне при цьому не має зникнути. Дзеркалить наявне
    правило про `registry/{conflicts,resolutions}.tsv`: людські вердикти
    перезбірка не змиває.
    """
    try:
        from nyshporka.core.workspace import workspace

        return workspace().data / "catalog" / "own.sqlite"
    except Exception:
        return None


# ── дискавері ────────────────────────────────────────────────────────────────

#: memo переліку паків за (шлях теки, набір штампів файлів)
_DISCO: tuple[Any, list[InstalledPack]] | None = None


def _stamps(d: Path) -> tuple[Any, ...]:
    try:
        return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                            for p in d.glob("*.sqlite")))
    except OSError:
        return ()


def _read_meta(path: Path) -> dict[str, str]:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        return {str(k): str(v) for k, v in con.execute("SELECT k, v FROM meta")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def installed(domain: str = "") -> list[InstalledPack]:
    """Паки на диску. Зіпсовані НЕ ховаються — вони мають `problem`.

    ⚠ «Немає» і «зіпсоване» тут різні стани: перше лікується встановленням,
    друге — повторним, і плутати їх означає радити не те.
    """
    global _DISCO
    d = catalog_dir()
    stamp = (str(d), _stamps(d))
    if _DISCO is not None and _DISCO[0] == stamp:
        packs = _DISCO[1]
    else:
        packs = []
        for p in sorted(d.glob("*.sqlite")) if d.is_dir() else []:
            meta = _read_meta(p)
            dom = meta.get("domain", "")
            problem = ""
            if not meta:
                problem = "файл не читається як пак каталогу"
            elif meta.get("schema") != str(schema.SCHEMA_VERSION):
                problem = (f"схема v{meta.get('schema')}, застосунок знає "
                           f"v{schema.SCHEMA_VERSION}")
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            packs.append(InstalledPack(
                pack_id=meta.get("pack_id") or p.stem, domain=dom, path=p,
                taken=meta.get("taken", ""), rows=int(meta.get("rows") or 0),
                size=size, note=meta.get("note", ""), problem=problem))
        _DISCO = (stamp, packs)
    return [p for p in packs if not domain or p.domain == domain]


def invalidate() -> None:
    """Скинути memo дискавері — після встановлення/зняття пака й у тестах."""
    global _DISCO
    _DISCO = None


def coverage(domain: str) -> list[Coverage]:
    """Що саме покриють відповіді цього домену. Порожньо = шукати нема де."""
    return [Coverage(pack_id=p.pack_id, domain=p.domain, taken=p.taken,
                     rows=p.rows, scope=p.note)
            for p in installed(domain) if p.ok]


def require(domain: str) -> list[InstalledPack]:
    """Паки домену — або відмова з поясненням, ЩО поставити.

    🔴 Саме тут живе правило «нуль мусить щось означати»: джерело, яке не може
    шукати, не додає нуль до суми. Порожній список замість відмови означав би
    «такого села немає в жодному фонді» — а це закриває напрям назавжди.
    """
    packs = [p for p in installed(domain) if p.ok]
    if packs:
        return packs
    broken = [p for p in installed(domain) if not p.ok]
    if broken:
        what = "; ".join(f"{p.pack_id}: {p.problem}" for p in broken)
        raise CatalogMissing(
            f"паки домену «{domain}» є, але непридатні ({what}). "
            f"Полагодити: nysh catalog update")
    raise CatalogMissing(
        f"у каталозі немає жодного пака домену «{domain}», тож шукати ніде — "
        f"і нуль тут нічого не означав би. Поставити: nysh catalog install "
        f"--domain {domain}")


def open_packs(domain: str, *, with_own: bool = True
               ) -> list[tuple[str, sqlite3.Connection]]:
    """[(pack_id, з'єднання)] для віялового запиту. Закривати — викликачу.

    `own.sqlite` (робота самого дослідника) додається ОСТАННІМ і під власним
    `pack_id`, щоб у відповіді було видно, що прийшло з привезеного каталогу, а
    що людина зібрала сама.
    """
    out: list[tuple[str, sqlite3.Connection]] = []
    for p in require(domain):
        try:
            con = sqlite3.connect(f"file:{p.path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            out.append((p.pack_id, con))
        except sqlite3.Error:
            continue
    if with_own:
        own = own_path()
        if own is not None and own.is_file():
            try:
                con = sqlite3.connect(f"file:{own}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                if not schema.check(con, domain):
                    out.append(("own", con))
                else:
                    con.close()
            except sqlite3.Error:
                pass
    return out


def close_all(packs: list[tuple[str, sqlite3.Connection]]) -> None:
    """Закрити всі з'єднання віяла. Помилка закриття нікого не рятує й не губить."""
    import contextlib

    for _, con in packs:
        with contextlib.suppress(sqlite3.Error):
            con.close()
