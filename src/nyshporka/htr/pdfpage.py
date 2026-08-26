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
    """`00042.jpg` → 42. None — якщо в імені немає числа."""
    m = _NUM_RE.search(Path(page).stem)
    return int(m.group(1)) if m else None


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
