"""📁 Локальна тека або PDF — те, з чого починає більшість.

Найчастіший вхід не з архіву, а з диска: людина вже має теку JPEG із читального
залу, або PDF, скачаний із сайту архіву, або десяток PDF по одному на розділ.
Для застосунку це має бути таким самим джерелом, як дзеркало плівок, — інакше
шлях «у мене вже є скани» довелося б робити окремою гілкою всюди.

Розпізнаються чотири форми входу, і різниця між ними не косметична:

    тека з зображеннями   → справа як є
    один PDF              → справа, сторінки якої треба відрендерити
    тека з PDF            → одна справа, зібрана з кількох файлів підряд
    тека з підтеками      → масив справ (архів віддає так цілий фонд)

🔴 Остання форма — та, на якій найлегше помилитись. Тека, всередині якої лежать
теки-справи, виглядає як порожня справа: зображень у ній немає. Прийняти її за
справу означає прогін на нуль сторінок, який завершується «успішно», і людину,
яка не розуміє, чому текст порожній.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    ProgressFn,
    SourceError,
)

IMG_EXT = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})
PDF_EXT = ".pdf"
#: Скільки PDF ще має сенс відкривати заради підрахунку сторінок. Більше —
#: оцінка коштує довше, ніж вартує: користувач чекає на форму, а не на точність.
PDF_PROBE_LIMIT = 50


@dataclass(frozen=True)
class Shape:
    """Що це за вхід і що з ним робити далі."""

    kind: str          # images | pdf | pdfs | cases | empty | missing
    path: Path
    images: int = 0
    pdfs: int = 0
    pages: int | None = None
    cases: tuple[Node, ...] = ()

    @property
    def usable(self) -> bool:
        return self.kind in ("images", "pdf", "pdfs")

    def explain(self) -> str:
        """Людською мовою — що знайдено й що буде далі."""
        if self.kind == "missing":
            return f"нічого немає за шляхом {self.path}"
        if self.kind == "empty":
            return (f"у теці {self.path.name} немає ні зображень, ні PDF — "
                    f"можливо, скани лежать глибше")
        if self.kind == "cases":
            n = len(self.cases)
            return (f"це не одна справа, а {n}: усередині лежать теки зі сканами. "
                    f"Оберіть потрібну або поставте всі в чергу")
        if self.kind == "images":
            return f"{self.images} кадрів"
        if self.kind == "pdf":
            pages = f", {self.pages} стор." if self.pages else ""
            return f"один PDF{pages}"
        return f"{self.pdfs} PDF" + (f", {self.pages} стор. разом" if self.pages else "")


def _count(d: Path) -> tuple[int, int]:
    imgs = pdfs = 0
    try:
        for p in d.iterdir():
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in IMG_EXT:
                imgs += 1
            elif ext == PDF_EXT:
                pdfs += 1
    except OSError:
        pass
    return imgs, pdfs


def _natural_key(name: str) -> tuple[int, object]:
    """Числові імена сортуються числом: 22 перед 131, а не після.

    Архіви масово віддають теки-справи іменами-номерами, і лексичний порядок
    робить перелік нечитабельним саме там, де його читають очима.
    """
    return (0, int(name)) if name.isdigit() else (1, name.casefold())


def _subcases(p: Path) -> tuple[Node, ...]:
    out: list[Node] = []
    try:
        subs = [q for q in p.iterdir() if q.is_dir()]
    except OSError:
        return ()
    for q in sorted(subs, key=lambda d: _natural_key(d.name)):
        imgs, pdfs = _count(q)
        if imgs or pdfs:
            out.append(Node(ref=str(q), label=q.name, kind="case",
                            frames=imgs or pdfs))
    return tuple(out)


def _pdf_pages(paths: list[Path]) -> int | None:
    """Сумарна кількість сторінок. None — якщо порахувати не вийшло.

    None тут не помилка, а чесне «не знаю»: оцінка часу без нього просто не
    показується, тоді як вигадане число зіпсувало б планування.
    """
    if not paths or len(paths) > PDF_PROBE_LIMIT:
        return None
    try:
        import pypdfium2 as pdfium
    except ImportError:
        try:
            import fitz
        except ImportError:
            return None
        total = 0
        for pdf in paths:
            try:
                with fitz.open(pdf) as doc:
                    total += doc.page_count
            except Exception:
                return None
        return total
    total = 0
    for pdf in paths:
        try:
            doc = pdfium.PdfDocument(pdf)
            try:
                total += len(doc)
            finally:
                doc.close()
        except Exception:
            return None
    return total


def inspect(raw: str | Path) -> Shape:
    """Що це за вхід. Ніколи не кидає — невизначеність теж є відповіддю."""
    p = Path(raw).expanduser()
    if not p.exists():
        return Shape(kind="missing", path=p)

    if p.is_file():
        if p.suffix.lower() == PDF_EXT:
            return Shape(kind="pdf", path=p, pdfs=1, pages=_pdf_pages([p]))
        if p.suffix.lower() in IMG_EXT:
            # Одиноке зображення — це тека, у якій воно лежить: інакше «справа з
            # одного кадру» ставала б окремим випадком у кожного споживача.
            return inspect(p.parent)
        return Shape(kind="empty", path=p)

    imgs, pdfs = _count(p)
    if imgs:
        return Shape(kind="images", path=p, images=imgs, pdfs=pdfs)
    if pdfs:
        files = sorted((q for q in p.iterdir()
                        if q.is_file() and q.suffix.lower() == PDF_EXT),
                       key=lambda q: _natural_key(q.stem))
        return Shape(kind="pdfs", path=p, pdfs=pdfs, pages=_pdf_pages(files))
    subs = _subcases(p)
    if subs:
        return Shape(kind="cases", path=p, cases=subs)
    return Shape(kind="empty", path=p)


def frames_of(path: Path) -> list[Path]:
    """Кадри теки, у порядку читання."""
    try:
        return sorted((p for p in path.iterdir()
                       if p.is_file() and p.suffix.lower() in IMG_EXT),
                      key=lambda p: _natural_key(p.stem))
    except OSError:
        return []


class LocalSource:
    """Диск як джерело: нічого не качає, лише описує наявне."""

    id = "local"
    label = "Тека або PDF на цьому комп'ютері"
    caps = frozenset({"browse", "manifest"})

    def browse(self, ref: str | None = None) -> list[Node]:
        """Підтеки-справи. Без `ref` — нічого: диск цілком не гортається."""
        if not ref:
            return []
        shape = inspect(ref)
        if shape.kind == "cases":
            return list(shape.cases)
        if shape.usable:
            return [Node(ref=str(shape.path), label=shape.path.name, kind="case",
                         frames=shape.images or shape.pdfs)]
        return []

    def manifest(self, ref: str) -> Manifest:
        shape = inspect(ref)
        if not shape.usable:
            raise SourceError(shape.explain())
        # 🔴 `shape.pages is None` означає «PDF є, а читача сторінок немає».
        # Падати з нього на `shape.pdfs` — підставляти число файлів замість
        # числа сторінок: знаменник виходив у сотні разів меншим за наявне
        # й мовчки доводив «повноту» на першому ж кадрі.
        if shape.images:
            frames: int | None = shape.images
        elif shape.pages is not None:
            frames = shape.pages
        else:
            frames = None
        total = 0
        try:
            total = sum(p.stat().st_size for p in shape.path.iterdir() if p.is_file())
        except OSError:
            total = 0
        return Manifest(source=self.id, ref=str(shape.path), title=shape.path.name,
                        frames=frames, bytes_estimate=total or None,
                        meta={"kind": shape.kind, "pdfs": shape.pdfs,
                              "images": shape.images})

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Диск не шукається — це справа файлового менеджера, не наша."""
        return []

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        """Нічого не качає: матеріал уже тут.

        Копіювати теку «до себе» було б найгіршим із можливого — архівна справа
        важить гігабайти, і друга копія з'їла б диск заради нічого.
        """
        raise SourceError(
            "локальний матеріал не завантажується — він уже на диску; "
            "передайте шлях напряму")
