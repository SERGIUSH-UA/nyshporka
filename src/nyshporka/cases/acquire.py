"""📥 Покласти завантажене в теку справи — з паспортом і перевірками.

🔴 Навіщо окремий модуль, коли є `nysh get`. Той віддає файли в довільну теку й
на цьому закінчує. Справа ж мусить стати ОБЛІКОВАНОЮ: без `meta.json` вона
невидима для бібліотеки, а отже для всього далі — прогін по ній ляже «нічиїм»,
і знайти його потім не буде як.

Досі це робив зовнішній скрипт, і пакет запускав його підпроцесом за шляхом
усередині робочого простору. Тобто ПУБЛІЧНИЙ пакет залежав від приватного
репозиторію за файловим шляхом: на чужій машині тієї теки немає, і команда
падала з «файл не знайдено» — виглядала поламаною, а не відсутньою.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn


class AcquireError(RuntimeError):
    """Класти не можна, і причина сформульована для людини."""


@dataclass
class Acquired:
    """Що саме лягло в теку справи."""

    case_dir: Path
    files: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0

    @property
    def pages(self) -> int:
        return sum(int(f.get("pagecount") or 0) for f in self.files)

    @property
    def bytes(self) -> int:
        return sum(int(f.get("size") or 0) for f in self.files)


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def page_count(path: Path) -> int:
    """Скільки сторінок у PDF — з ФАЙЛА, а не з обіцянки каталогу.

    Рахується тим самим читачем, що й усюди в пакеті (`pypdfium2`): тягнути
    заради одного числа важчу бібліотеку немає підстав.
    """
    if path.suffix.lower() != ".pdf":
        return 0
    from nyshporka.htr.pdfpage import page_counts

    try:
        return page_counts([path])[0]
    except Exception:
        return 0


def guard_inventory(case_dir: Path, opys: str) -> None:
    """🔴 Тека справи належить ОДНОМУ опису, і це не формальність.

    Номери справ між описами повторюються: у ДАВіО ф.904 «спр.33» є і в описі
    30, і в описі 24. Якщо покласти другу поверх першої, тека виглядатиме
    справною — файли на місці, паспорт на місці, — а насправді в ній лежатимуть
    дві різні справи під однією шифрою. Помітять це не тоді, коли клали, а коли
    шукатимуть у ній запис і не знайдуть.
    """
    meta_path = case_dir / "meta.json"
    if not meta_path.is_file():
        return
    try:
        was = str(json.loads(meta_path.read_text(encoding="utf-8")).get("inv") or "")
    except (OSError, ValueError):
        return
    if was and was != str(opys):
        raise AcquireError(
            f"у теці {case_dir.name} уже лежить справа опису {was}, а кладеться "
            f"опис {opys}. Номери справ між описами повторюються, тож це РІЗНІ "
            f"справи — покладіть нову в окрему теку або приберіть стару.")


def write_meta(case_dir: Path, *, archive: str, fond: str, opys: str, spr: str,
               files: list[dict[str, Any]], source: str, title: str = "",
               year: str = "", extra: dict[str, Any] | None = None) -> Path:
    """Паспорт справи. Доповнює наявний, а не заміщає його.

    ⚠ Заміщення стерло б те, що дописала людина (нотатку про звірку шифри,
    власний заголовок), — а дізналась би вона про це, лише не знайшовши їх.
    """
    path = case_dir / "meta.json"
    meta: dict[str, Any] = {}
    if path.is_file():
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    meta.update({"archive": archive, "fond": fond, "inv": opys, "spr": spr,
                 "title": title, "year": year, "files": files, "source": source})
    meta.update(extra or {})
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def from_commons(case_dir: Path, file_name: str, *, archive: str, fond: str,
                 opys: str, spr: str, title: str = "", year: str = "",
                 on_progress: ProgressFn | None = None,
                 source: Any = None) -> Acquired:
    """Завантажити справу з Commons у теку справи й описати її.

    Приймач — не «файл є», а ВИМІРЯНЕ: розмір звіряє саме джерело, а сторінки
    й `sha256` рахуються з диска. Обіцянка каталогу тут не доказ: обірвана
    закачка під правильним іменем лягла б в облік як повна справа.
    """
    from nyshporka.sources.commons import CommonsSource

    src = source or CommonsSource()
    guard_inventory(case_dir, opys)
    case_dir.mkdir(parents=True, exist_ok=True)

    res = src.fetch(f"file:{file_name}", case_dir, on_progress=on_progress)
    if res.errors:
        raise AcquireError("; ".join(res.errors))

    got = case_dir / file_name.replace("/", "_")
    if not got.is_file():
        raise AcquireError(f"після завантаження файла немає: {got}")

    files = [{"file": got.name, "pagecount": page_count(got),
              "size": got.stat().st_size, "sha256": sha256_of(got),
              "source_url": f"https://commons.wikimedia.org/wiki/File:{file_name}"}]
    write_meta(case_dir, archive=archive, fond=fond, opys=opys, spr=spr,
               files=files, source="Wikimedia Commons", title=title, year=year)
    return Acquired(case_dir=case_dir, files=files, skipped=res.skipped)


def from_archium(case_dir: Path, viewer: str, *, archive: str, fond: str,
                 opys: str, spr: str, repo: str = "", title: str = "",
                 year: str = "", on_progress: ProgressFn | None = None,
                 source: Any = None) -> Acquired:
    """Завантажити справу з переглядача архіву — посторінковими кадрами.

    🔴 Найшвидший канал: кадри приходять готовими JPG, тоді як Commons віддає
    один файл на сотні мегабайтів. Тому в `cases take` він перевіряється
    ПЕРШИМ — колонка каналу має радити найшвидший шлях, а не найдавніше
    реалізований.

    ⚠ Паспорт тут описує саме КАДРИ, а не один файл, і `sha256` рахується по
    кожному: обірваний набір інакше не відрізнити від повного — файлів просто
    менше, і за іменами це не видно.
    """
    from nyshporka.archives import active
    from nyshporka.sources.archium import ArchiumSource

    ident = viewer.rstrip("/").rsplit("/", 1)[-1] if "/" in viewer else viewer
    if not ident.isdigit():
        raise AcquireError(
            f"з адреси «{viewer}» не видно номера справи в переглядачі — "
            f"очікується `.../file-viewer/<номер>/` або сам номер")

    repo = (repo or archive).upper()
    src = source or ArchiumSource(site=active().site(repo, "archium"), repo=repo)
    guard_inventory(case_dir, opys)
    pages_dir = case_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    res = src.fetch(f"file:{ident}", pages_dir, on_progress=on_progress)
    if res.errors:
        raise AcquireError("; ".join(res.errors[:3]))

    files = [{"file": f"pages/{p.name}", "pagecount": 1,
              "size": p.stat().st_size, "sha256": sha256_of(p)}
             for p in sorted(pages_dir.glob("*.jpg"))]
    if not files:
        raise AcquireError(f"кадрів не завантажено: {pages_dir}")

    write_meta(case_dir, archive=archive, fond=fond, opys=opys, spr=spr,
               files=files, source="ARCHIUM", title=title, year=year,
               extra={"viewer_id": ident, "viewer_url": viewer,
                      "n_pages": len(files)})
    return Acquired(case_dir=case_dir, files=files, skipped=res.skipped)
