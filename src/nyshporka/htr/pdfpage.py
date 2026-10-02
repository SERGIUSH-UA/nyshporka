"""📄 Сторінка справи-PDF на вимогу — коли рендер, який читав прогін, не зберігся.

Хмарний прогін розгортає PDF у кадри на орендованому боксі й читає їх; на диску
лишається текст, а кадрів немає ніде. Гортач через це сліпий на третині
прогонів — і саме на тій третині, де справи найбільші.

🔴 головне: відповідність «кадр → сторінка PDF» тут доводиться, а не вгадується.
Показати не той аркуш гірше, ніж не показати нічого: людина звіряє прочитане з
оригіналом і робить висновок про рід — по чужій сторінці цей висновок буде
хибним і виглядатиме обґрунтованим.

Доказ дешевий і повний:

1. кадри пронумеровані щільно `1..N` (жодної діри);
2. сума сторінок усіх PDF справи дорівнює рівно `N`.

Обидві умови разом означають, що рендер ішов підряд по файлах, відсортованих
за іменем, — інших варіантів, які дали б ті самі числа, не буває. Не сходиться
бодай одна — відмова з поясненням, а не «спробуємо як вийде».

Заміряно на ДАХмО 315-1-7864: 3772 кадри, три PDF по 1217+1313+1242 = 3772.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Ширина рендера. Сегментація рахувалась на кадрах приблизно такого розміру;
#: дрібніше — не видно скоропису, більше — не додає читабельності, лише ваги.
DEFAULT_WIDTH = 2000

_NUM_RE = re.compile(r"(\d+)")


class PdfPageError(RuntimeError):
    """Сторінку не віддати — з поясненням, чому саме."""


@dataclass(frozen=True)
class Mapping:
    """Доведена відповідність кадрів і сторінок PDF."""

    pdfs: tuple[Path, ...]
    counts: tuple[int, ...]
    frames: int

    def locate(self, frame_no: int) -> tuple[Path, int]:
        """Номер кадру (з одиниці) → (файл PDF, сторінка з нуля)."""
        if not 1 <= frame_no <= self.frames:
            raise PdfPageError(f"кадру {frame_no} немає: у справі їх {self.frames}")
        left = frame_no - 1
        for path, n in zip(self.pdfs, self.counts, strict=True):
            if left < n:
                return path, left
            left -= n
        raise PdfPageError(f"кадр {frame_no} не лягає в жоден PDF")  # недосяжно


def frame_number(page: str) -> int | None:
    """`00042.jpg` → 42. None — якщо в імені немає числа.

    🔴 ОСТАННЄ число в імені, а не перше: `f792-1-55_0042.jpg` — це кадр 42, а
    не 792. З першим числом усі кадри такої теки мапились на одну сторінку
    PDF, і гортач показував той самий чужий аркуш для кожної.
    """
    nums = _NUM_RE.findall(Path(page).stem)
    return int(nums[-1]) if nums else None


def case_pdfs(case_dir: Path) -> list[Path]:
    """PDF справи, відсортовані за іменем — у тому ж порядку, що й рендер."""
    if not case_dir.is_dir():
        return []
    return sorted(p for p in case_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf")


def page_counts(pdfs: list[Path]) -> list[int]:
    import pypdfium2 as pdfium

    out = []
    for p in pdfs:
        doc = pdfium.PdfDocument(str(p))
        try:
            out.append(len(doc))
        finally:
            doc.close()
    return out


def mapping(case_dir: Path, frames: list[str],
            total: int | None = None) -> Mapping:
    """Довести відповідність або відмовитись, назвавши причину.

    `frames` — кадри, які прогін прочитав. `total` — скільки їх було у справі,
    якщо прогін це записав (`frames_total` у меті).

    🔴 Навіщо `total`. Доказ будується на щільності `1..N`, але прогін буває
    частковим — обірваним, точковим, шардованим із утратою сторінки. Тоді
    прочитаних кадрів менше, ніж сторінок у PDF, і сувора перевірка відмовляла
    навіть там, де PDF справи лежить поруч: людина бачила «показати нічим» на
    справі, яку сама ж і читала. Знаючи знаменник, доказ лишається таким самим
    строгим — кадри мусять бути підмножиною `1..total`, а сторінок у PDF рівно
    `total`, — але вже не вимагає, щоб прогін дійшов до кінця.

    Без `total` (старі прогони, які його не писали) поведінка та сама, що й
    була: вимагаємо щільності. Це не регресія, а межа знання — вгадувати
    знаменник тут не можна, бо ціна помилки чужий аркуш.
    """
    nums = sorted(n for n in (frame_number(f) for f in frames) if n is not None)
    if not nums:
        raise PdfPageError("у прогоні немає кадрів із номером в імені")
    if total is not None and total > 0:
        if nums[-1] > total:
            raise PdfPageError(
                f"кадр {nums[-1]} поза межами справи ({total} кадрів) — "
                f"це інший матеріал; показувати не буду")
        if len(set(nums)) != len(nums):
            # Два кадри з одним номером — імена не є нумерацією аркушів, і
            # будь-який мапінг показав би не той аркуш.
            raise PdfPageError(
                "номери кадрів у прогоні повторюються — за іменами файлів "
                "сторінку PDF не визначити; показувати не буду")
        expect = total
    else:
        if nums != list(range(1, len(nums) + 1)):
            # Діра в нумерації означає, що рендер не був суцільним (частину
            # кадрів відкинули, частину доклали окремо) — і зсув пішов би далі
            # по всій справі, тихо.
            holes = [n for i, n in enumerate(nums, 1) if n != i][:3]
            raise PdfPageError(
                f"нумерація кадрів не щільна (перший розрив біля {holes}), а "
                f"скільки кадрів мала справа, прогін не записав — "
                f"відповідність сторінкам PDF недоведена, показувати не буду")
        expect = len(nums)
    pdfs = case_pdfs(case_dir)
    if not pdfs:
        raise PdfPageError(f"у теці справи немає PDF: {case_dir}")
    counts = page_counts(pdfs)
    if sum(counts) != expect:
        raise PdfPageError(
            f"сторінок у PDF {sum(counts)}, а кадрів у справі {expect} — "
            f"це різний матеріал або інший рендер; показувати не буду")
    return Mapping(pdfs=tuple(pdfs), counts=tuple(counts), frames=expect)


def vytiahnuty_kadry(case_dir: Path, width: int = DEFAULT_WIDTH) -> int:
    """Розгорнути PDF справи в кадри `0001.jpg…` поруч. Повертає, скільки записано.

    🔴 Нумерація — рівно та, що доводить `mapping`: щільна `1..N` підряд по
    файлах, відсортованих за іменем. Інакше переглядач показав би не той
    аркуш проти прочитаного.

    Сторінка-скан із ОДНИМ вбудованим JPEG віддає його байти як є — без
    перестиснення, тобто без втрати дрібного скоропису; інша сторінка
    рендериться на `width` пікселів. Наявні кадри не переписуються: обірване
    розгортання дочитується, а не починається наново.

    🔴 Кадр бере час зміни свого PDF, а не мить розгортання. Ворота хмари
    (`cloud.frames.check_frames`) питають за часом кадрів, чи тека ще
    качається, і щойно розгорнута справа виглядала б недокачаною ще п'ять
    хвилин. Питання ж про джерело: докачано PDF — докачано й кадри.
    """
    import os

    import pypdfium2 as pdfium

    from nyshporka.utils.atomic import atomic_write_bytes

    pdfs = case_pdfs(case_dir)
    if not pdfs:
        return 0
    total = sum(page_counts(pdfs))
    digits = max(4, len(str(total)))
    zapysano = 0
    no = 0
    for path in pdfs:
        mtime = path.stat().st_mtime
        doc = pdfium.PdfDocument(str(path))
        try:
            for index in range(len(doc)):
                no += 1
                dest = case_dir / f"{no:0{digits}d}.jpg"
                if dest.exists():
                    continue
                atomic_write_bytes(dest, _storinka_jpeg(doc[index], width))
                os.utime(dest, (mtime, mtime))
                zapysano += 1
        finally:
            doc.close()
    return zapysano


def _storinka_jpeg(page: Any, width: int) -> bytes:
    """JPEG сторінки: вбудований як є, коли він там один, інакше рендер."""
    import pypdfium2 as pdfium

    images = list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE],
                                   max_depth=1))
    if len(images) == 1:
        try:
            if images[0].get_filters() == ["DCTDecode"]:
                raw = bytes(images[0].get_data(decode_simple=True))
                if raw[:2] == b"\xff\xd8":
                    return raw
        except Exception:
            pass    # незвичний образ — рендер нижче впорається
    scale = max(0.5, min(6.0, width / max(1.0, page.get_width())))
    pil = page.render(scale=scale).to_pil()
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def render(case_dir: Path, frames: list[str], page: str,
           width: int = DEFAULT_WIDTH, total: int | None = None) -> bytes:
    """PNG сторінки справи-PDF, що відповідає кадру `page`."""
    import pypdfium2 as pdfium

    no = frame_number(page)
    if no is None:
        raise PdfPageError(f"з імені «{page}» не видно номера кадру")
    path, index = mapping(case_dir, frames, total).locate(no)
    doc = pdfium.PdfDocument(str(path))
    try:
        pdf_page = doc[index]
        scale = max(0.5, min(6.0, width / max(1.0, pdf_page.get_width())))
        pil = pdf_page.render(scale=scale).to_pil()
    finally:
        doc.close()
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
