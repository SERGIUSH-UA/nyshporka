"""📄 Текстовий шар PDF — щоб регекс знаходив рядок у друкованій книзі.

Книгу з бібліотеки качають не заради файла, а заради одного рядка в ній: чи
згадане село, чи стоїть у переліку прізвище. Пошук по каталогу каже лише «слово
є десь у книзі», а `nysh text grep --dir` читає тексти, не PDF. Тут PDF стає
текстом, який той пошук бачить.

🔴 По файлу на СТОРІНКУ, а не один текст на книгу. Знахідка регексу несе файл і
номер рядка — і більше нічого, тож номер сторінки, заради якого до книги
повертаються, видно лише з імені файла (`<книга>.pdf.text/p0012.txt`). Позначки
сторінок усередині одного файла губились би саме тоді, коли знахідка далеко від
позначки, а префікс у кожному рядку ламав би `^` у регексі.

🔴 Порожніх файлів не буває. Сторінка без тексту — скан без шару — не пишеться
зовсім: порожній текст на місці сторінки читався б регексом як «на цій сторінці
цього немає», хоча її ніхто не прочитав. Скільки сторінок має текст, лягає
числом у вердикт, і це знаменник для кожного нуля по цій книзі.

⚠ Вердикт — ознака, не доказ. `garbage` ловить биті шрифти (шар є, а літери —
приватні символи чи латиниця-1 замість кирилиці), але читабельність доводить
лише погляд на сторінку. OCR тут немає навмисно: це окрема важка робота, і
вердикт `image` саме про неї й каже.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

#: Тека тексту поруч із PDF: `<ім'я>.pdf.text/`.
SUFFIX = ".text"

#: Медіана символів на сторінку, нижче якої шару вважай немає. Скан із
#: випадковим колонтитулом у шарі дає одиниці символів на сторінку, книга з
#: текстом — сотні.
MIN_CHARS_PER_PAGE = 50

#: Частка «своїх» знаків (кирилиця, латиниця ASCII, цифри, звичайна пунктуація)
#: серед непробільних, нижче якої шар вважається битим.
#: ⚠ Не частка літер узагалі: кирилиця, прочитана в латиниці-1, дає «Ïîä³ëüñüê»,
#: і кожен знак там формально літера — перевірка на `isalpha` таке пропускала б.
MIN_GOOD_SHARE = 0.7

_PUNCT = frozenset(".,;:!?-–—()[]{}«»\"'’ʼ/\\%№*+=<>§")


@dataclass(frozen=True)
class TextLayer:
    """Що вийшло з PDF: скільки сторінок, скільки з текстом, і чи шар живий."""

    pages: int
    pages_with_text: int
    chars: int
    #: `ok` — шар є на більшості сторінок; `image` — на більшості його немає
    #: (потрібне OCR); `garbage` — шар є, але знаки не ті (биті шрифти).
    verdict: str
    #: Ім'я теки з текстами поруч із PDF; порожньо — не записано жодної сторінки.
    folder: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def explain(self, name: str) -> str:
        """Рядок для людини — лише коли шар неповний або битий."""
        if self.verdict == "image":
            return (f"{name}: текстовий шар лише на {self.pages_with_text} з "
                    f"{self.pages} сторінок — решту бачить тільки OCR, тож нуль "
                    f"регексу по цій книзі нічого не доводить")
        if self.verdict == "garbage":
            return (f"{name}: текстовий шар битий (знаки не ті — ймовірно, "
                    f"шрифти без таблиці Unicode); регекс по ньому ненадійний")
        return ""


def layer_dir(pdf: Path, out_dir: Path | None = None) -> Path:
    """Тека тексту для PDF — поруч із ним, якщо не сказано інакше."""
    return (out_dir or pdf.parent) / (pdf.name + SUFFIX)


def page_texts(pdf: Path) -> list[str]:
    """Текст кожної сторінки як є — порожній рядок, де шару немає."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        out: list[str] = []
        for i in range(len(doc)):
            page = doc[i]
            try:
                tp = page.get_textpage()
                try:
                    # `get_text_bounded()`, а не `get_text_range()`: той без
                    # параметрів сам перенаправляє сюди й друкує попередження
                    # на кожну сторінку.
                    out.append(str(tp.get_text_bounded()))
                finally:
                    tp.close()
            finally:
                page.close()
        return out
    finally:
        doc.close()


def _good(ch: str) -> bool:
    return (ch.isdigit() or ("a" <= ch.lower() <= "z")
            or "Ѐ" <= ch <= "ӿ" or ch in _PUNCT)


def judge(texts: list[str]) -> str:
    """Вердикт шару за текстами сторінок."""
    counts = sorted(len(t.strip()) for t in texts)
    if not counts or counts[len(counts) // 2] < MIN_CHARS_PER_PAGE:
        return "image"
    marks = [c for c in "".join(texts) if not c.isspace()]
    if marks and sum(_good(c) for c in marks) / len(marks) < MIN_GOOD_SHARE:
        return "garbage"
    return "ok"


def _clear(folder: Path) -> None:
    """Прибрати сторінки попереднього витягу — лише наші `p*.txt`.

    Інакше сторінка, що при новому витягу виявилась порожньою, лишилась би зі
    старим текстом і відповідала б регексу за книгу, якої вже немає на диску.
    """
    if folder.is_dir():
        for p in folder.glob("p*.txt"):
            p.unlink()


def extract(pdf: Path, out_dir: Path | None = None) -> TextLayer:
    """Записати текст PDF посторінково й повернути вердикт.

    Сторінки з текстом пишуться завжди, навіть коли на більшості його немає: це
    справжній текст книги, і викинути його означало б загубити знахідку. Межу
    покриття несе вердикт (`pages_with_text` із `pages`), а не відсутність
    файлів.
    """
    texts = page_texts(pdf)
    verdict = judge(texts)
    folder = layer_dir(pdf, out_dir)
    _clear(folder)
    written = 0
    for i, raw in enumerate(texts, 1):
        body = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not body:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"p{i:04d}.txt").write_text(body + "\n", encoding="utf-8")
        written += 1
    return TextLayer(pages=len(texts), pages_with_text=written,
                     chars=sum(len(t.strip()) for t in texts), verdict=verdict,
                     folder=folder.name if written else "")
