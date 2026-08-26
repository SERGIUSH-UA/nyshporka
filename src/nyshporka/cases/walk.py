"""🚶 Один обхід дерева справ замість одинадцяти.

**Навіщо.** Три сканери — `library._scan_disk_cases`, `collect._ordered_cases` і
`collect._unfiled_material` — кожен ходив деревом власними `glob`-патернами
``*``, ``*/*``, ``*/*/*``, ``*/*/*/*``. Кожен патерн обходить дерево згори наново,
тож тека четвертого рівня відвідувалась усіма чотирма; разом виходило ≈11 повних
обходів. Поверх цього `_count_case` і `_count_frames` робили `iterdir()` з
`p.is_file()` і `p.stat()` на кожен файл — по два системні виклики на кадр.
Заміряно 2026-08-16: 656 584 виклики `nt.stat` і 483 958 `Path.is_dir` на одну
збірку, тобто ~46% часу — сирі звернення до файлової системи.

Тут дерево читається раз, через `os.scandir`: `DirEntry` на Windows несе і
«файл це чи тека», і `stat` із самого читання каталогу, тобто зайвих системних
викликів нуль.

🔴 **Порядок обходу — частина контракту, а не деталь.** Споживачі мають ``seen``
і стелю ``limit``, тож інший порядок дав би інший зріз, а не просто інший темп.
Тому відтворено рівно те, що робив `glob`, і кожен пункт нижче перевірено:

* **обхід по рівнях**: спершу всі теки глибини 1 (відсортовані), потім усі
  глибини 2, і так далі — саме так лягали чотири окремі `glob`-и;
* **сортування об'єктами `Path`, а не рядками**: на Windows `PurePath.__lt__`
  порівнює шляхи в нижньому регістрі, тож `alpha` йде перед `Beta`, а
  `sorted(str(...))` дав би зворотне;
* **приховані теки видно**: `pathlib.glob` не відкидає імена з крапки (на
  відміну від модуля `glob`), тож і ми не відкидаємо;
* **у теки з `_` на початку ми заходимо**: `glob("*/*")` віддає `_foo/bar`, а
  перевірка `name.startswith("_")` у споживачів дивиться лише на останній
  сегмент. Відсіювати піддерево тут означало б загубити справи;
* **обрізається лише `skip_slugs`** — і саме за першим сегментом відносного
  шляху, як у споживачів.

Паритет закріплено тестом, який звіряє обхід із `glob`-перерахунком і на
синтетичному дереві, і на живому `data/raw`.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

#: Розширення, які вважаються кадрами. Тримається тут, щоб обхід міг рахувати
#: одразу, не змушуючи споживача другий раз перебирати імена.
IMG_EXT = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})

#: Сайдкари опису справи, від найсильнішого.
SIDECAR_NAMES = ("_source.json", "meta.json")
_SIDECAR_NC = frozenset(os.path.normcase(n) for n in SIDECAR_NAMES)


@dataclass(frozen=True)
class DirScan:
    """Одне прочитання однієї теки — усе, що з неї потрібно всім споживачам."""

    base: Path
    """Корінь, з якого почався обхід."""
    path: Path
    """Абсолютний шлях теки."""
    rel_parts: tuple[str, ...]
    """Шлях від `base` частинами. `rel_parts[0]` — те, що звіряють зі `skip_slugs`."""
    depth: int
    """1 для прямих дітей `base`."""

    dirs: tuple[str, ...] = ()
    """Імена підтек (відсортовані як `Path`)."""
    n_files: int = 0
    n_img: int = 0
    n_pdf: int = 0
    pdf_names: tuple[str, ...] = ()
    """Імена PDF — їх мало, а `_pdf_pages` потребує саме шляхів."""
    nbytes: int = 0
    newest_ns: int = 0
    """Найновіший `st_mtime_ns` серед файлів теки (0, якщо файлів немає)."""
    dir_ns: int = 0
    """`st_mtime_ns` самої теки."""
    sidecar: str = ""
    """Ім'я знайденого сайдкара або порожньо."""
    names_sha1: str = ""
    """sha1 по відсортованих `ім'я\\tрозмір\\tmtime_ns` — основа дайджесту (етап 6).

    Рахується потоково, самі імена не зберігаються: 188 617 кадрів у пам'яті
    коштували б десятки мегабайтів на кожній збірці й нікому не потрібні.
    """
    unreadable: bool = False
    """Теку не вдалось прочитати. Це стан, а не привід зупинити обхід."""

    _pdf_paths: tuple[Path, ...] = field(default=(), repr=False)

    @property
    def rel_root(self) -> str:
        """Шлях від `base` через `/`."""
        return "/".join(self.rel_parts)

    @property
    def pdf_paths(self) -> tuple[Path, ...]:
        return self._pdf_paths

    def has_material(self) -> bool:
        """Чи є прямо тут кадри або PDF — критерій «це справа, а не картка»."""
        return bool(self.n_img or self.n_pdf)


def scan_dir(path: Path, base: Path, rel_parts: tuple[str, ...],
             depth: int) -> DirScan:
    """Прочитати одну теку одним `scandir`."""
    try:
        dir_ns = path.stat().st_mtime_ns
    except OSError:
        dir_ns = 0
    dirs: list[str] = []
    pdf_paths: list[Path] = []
    n_files = n_img = n_pdf = 0
    nbytes = 0
    newest_ns = 0
    sidecar = ""
    h = hashlib.sha1()
    rows: list[str] = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    # follow_symlinks за замовчуванням — як у `p.is_dir()`/`p.is_file()`,
                    # які тут стояли. Junction на архівний том мусить лишатись текою.
                    if e.is_dir():
                        dirs.append(e.name)
                        continue
                    if not e.is_file():
                        continue
                    st = e.stat()
                    n_files += 1
                    nbytes += st.st_size
                    if st.st_mtime_ns > newest_ns:
                        newest_ns = st.st_mtime_ns
                    rows.append(f"{e.name}\t{st.st_size}\t{st.st_mtime_ns}")
                    low = e.name.lower()
                    ext = low[low.rfind("."):] if "." in low else ""
                    if ext in IMG_EXT:
                        n_img += 1
                    elif ext == ".pdf":
                        n_pdf += 1
                        pdf_paths.append(path / e.name)
                    elif not sidecar and os.path.normcase(e.name) in _SIDECAR_NC:
                        sidecar = e.name
                except OSError:
                    continue
    except OSError:
        return DirScan(base=base, path=path, rel_parts=rel_parts, depth=depth,
                       dir_ns=dir_ns, unreadable=True)

    # Сайдкар вибирається за силою (`_source.json` > `meta.json`), а не за
    # порядком читання теки. Порівняння через `normcase`, бо споживач робив
    # `(d / "_source.json").is_file()`, а на Windows це знаходить і `_SOURCE.JSON`.
    if sidecar:
        by_nc = {os.path.normcase(r.split("\t", 1)[0]): r.split("\t", 1)[0]
                 for r in rows}
        sidecar = next((by_nc[os.path.normcase(n)] for n in SIDECAR_NAMES
                        if os.path.normcase(n) in by_nc), "")
    for r in sorted(rows):
        h.update(r.encode("utf-8", "surrogatepass"))
        h.update(b"\n")

    return DirScan(
        base=base, path=path, rel_parts=rel_parts, depth=depth,
        dirs=tuple(sorted(dirs, key=lambda n: (path / n))),
        n_files=n_files, n_img=n_img, n_pdf=n_pdf,
        pdf_names=tuple(p.name for p in pdf_paths),
        nbytes=nbytes, newest_ns=newest_ns, dir_ns=dir_ns,
        sidecar=sidecar, names_sha1=h.hexdigest(),
        _pdf_paths=tuple(pdf_paths),
    )


def walk_root(base: Path, *, max_depth: int = 4,
              skip_slugs: frozenset[str] = frozenset()) -> Iterator[DirScan]:
    """Теки під `base` глибиною 1..`max_depth`, у порядку `glob`-перерахунку.

    Тобто: спершу вся глибина 1 (відсортована), потім уся глибина 2, і так далі.
    Саме цей порядок мали чотири окремі `glob`-и, і від нього залежить, які теки
    потраплять під стелю `limit` у споживача.
    """
    if not base.is_dir():
        return
    level: list[tuple[Path, tuple[str, ...]]] = [(base, ())]
    for depth in range(1, max_depth + 1):
        children: list[tuple[Path, tuple[str, ...]]] = []
        for parent, parent_rel in level:
            try:
                with os.scandir(parent) as it:
                    for e in it:
                        try:
                            if not e.is_dir():
                                continue
                        except OSError:
                            continue
                        rel = (*parent_rel, e.name)
                        # 🔴 Обрізаємо лише за першим сегментом — так само, як
                        # споживачі: періодика й описи це тисячі PDF за роками,
                        # а не справи. Теки з `_` на початку не обрізаємо:
                        # `glob` у них заходить, і там бувають справи.
                        if rel[0] in skip_slugs:
                            continue
                        children.append((parent / e.name, rel))
            except OSError:
                continue
        if not children:
            return
        # сортування об'єктами Path: на Windows це нижній регістр, як у `sorted(glob)`
        children.sort(key=lambda pr: pr[0])
        for path, rel in children:
            yield scan_dir(path, base, rel, depth)
        level = children


def walk_case_roots(roots: list[Path], *, max_depth: int = 4,
                    skip_slugs: frozenset[str] = frozenset()
                    ) -> Iterator[DirScan]:
    """Те саме для кількох коренів, по черзі — як робив `_scan_disk_cases`."""
    for base in roots:
        yield from walk_root(base, max_depth=max_depth, skip_slugs=skip_slugs)
