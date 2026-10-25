"""🕯 «Реабілітовані історією» — іменні довідки про репресованих у томах серії.

Серія науково-документальних книг за областями (понад 140 томів, по 2–9 на
область), викладена на Internet Archive одним записом `reabilitovani`. Кожен том
має «Біографічні довідки про репресованих» — статтю на людину: прізвище, ім'я,
по батькові, рік народження, село, заняття, арешт, звинувачення, вирок,
реабілітація й номер архівно-кримінальної справи `(9731 П)`. Це покажчик на
справу, а не сама справа.

🔴 Що це за дані й чого в них немає
────────────────────────────────────
Тексту томів як окремої бази даних не існує: це OCR скану книги. Тому

* формат статті різний у різних областях. Івано-Франківська: «БАХУР Ім'я
  По-батькові, 1894 р. н., с. Село … району, українець, … Заарештований
  07.02.1949 …»; Вінницька — усе великими літерами й «Арешт.»/«Реабіл.»;
  Тернопільська — «Прізвище Ім'я По-батькові, 1903 р., с. Село …». Початок
  статті розпізнається за «слова з прізвищем, іменем, [по батькові] і роком
  народження на початку рядка»; решта полів — за ключовими словами, і де
  слова немає, поле порожнє. **Сирий текст статті йде завжди.**
* OCR псує написання: «ї/і», «ґ/г», апострофи, пробіли посеред слова, латинські
  двійники літер. Збіг порівнює зведені написання, а не рядки; зайвих пробілів
  у самому прізвищі вилікувати не можна;
* томи є не для всіх областей (Львівська, Одеська, Херсонська — по одному, а
  Харківська — лише другий), і в частині томів статей мало чи зовсім нема
  (вступи, спогади, покажчики). Покриття, на якому шукали, їде у знаменник.

Адреса сторінки
───────────────
Сторінка — ЛИСТ скану (з нуля), той самий, що в адресі переглядача
`…/details/reabilitovani/<том>/page/n<лист>` і в `inside.php`. Порядок листів
дає `_hocr_pageindex.json.gz` (діапазони символів у `_hocr_searchtext.txt.gz`);
друкований номер сторінки — з `_page_numbers.json`, коли він є.

Запит
─────
    nysh find "Шевчук"                  --source reabilitovani      # прізвище
    nysh find "Шевчук Іван Петрович"    --source reabilitovani      # + ім'я, по батькові
    nysh find "село:Гориня"             --source reabilitovani      # населений пункт
    nysh find "Шевчук oblast:Івано-Франківська book:3 --source …"

Межі в запиті: `oblast:<область>` (укр. або латиною: `Ivano-Frankivska`),
`book:<номер тому>`, `село:<назва>` (`place:`), `born:<рік>`, `arrest:<рік>`.
Назву з пробілом — у лапках: `село:"Слобода Болехівська"`.

⚠ Це база ЛЮДЕЙ. Загальний `nysh find` (без `--source`) питає «що є про моє
село», і назва села, підставлена як прізвище, ловила б чужих. Тому джерело
`explicit_only`, як `martyrolog`.

Кеш
───
Текст тому (≈0,5 МБ gz) качається при першому запиті й лягає в
`<простір>/data/raw/reabilitovani/_cache/` разом із розібраними статтями.
Без `--oblast` за один запит докачується не більше `FRESH_MAX` нових томів;
решту видно в `Hits.truncated`, повторний запит продовжує з кешу.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from nyshporka.sources.base import Hit, Hits, SourceAbout, SourceError, SourceScope
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

HOST = "https://archive.org"
ITEM = "reabilitovani"

#: Спільна на машину черга до archive.org — та сама, що в джерела `ia`.
RATE_KEY = "archive.org"
RATE_MAX = 3
RATE_WINDOW = 3.0

#: Версія розбору статей. Зміна означає перерозбір кешованих томів із сирого тексту.
PARSER_VERSION = 5
#: Скільки нових томів докачується за один запит без `oblast:`/`book:`.
FRESH_MAX = 16
#: Скільки днів живе кеш каталогу томів.
CATALOG_TTL_DAYS = 14
#: Стеля на один файл тому (searchtext ≈ 0,5–1,2 МБ gz).
FILE_MAX_BYTES = 60 * 1024 * 1024
#: Довжина статті, довшу за яку вважаємо збоєм межі (кінця статті не знайдено).
ARTICLE_MAX = 3500
#: Скільки знаків статті йде в примітку знахідки.
NOTE_MAX = 1400

#: Назви областей за початком імені файла тому.
OBLASTS: dict[str, str] = {
    "Avtonomna_Respublika_Krym": "Автономна Республіка Крим",
    "Cherkaska_oblast": "Черкаська область",
    "Chernihivska_oblast": "Чернігівська область",
    "Chernivetska_oblast": "Чернівецька область",
    "Dnipropetrovska_oblast": "Дніпропетровська область",
    "Donetska_oblast": "Донецька область",
    "Harkivska_oblast": "Харківська область",
    "Hersonska_oblast": "Херсонська область",
    "Hmelnycka_oblast": "Хмельницька область",
    "Ivano-Frankivska_oblast": "Івано-Франківська область",
    "Kyivska_oblast": "Київська область",
    "Kyrovohradska_oblast": "Кіровоградська область",
    "Luhanska_oblast": "Луганська область",
    "Lvivska_oblast": "Львівська область",
    "Mykolaivska_oblast": "Миколаївська область",
    "Odeska_oblast": "Одеська область",
    "Poltavska_oblast": "Полтавська область",
    "Rivnenska_oblast": "Рівненська область",
    "Sumska_oblast": "Сумська область",
    "Ternopilska_oblast": "Тернопільська область",
    "Vinnycka_oblast": "Вінницька область",
    "Volynska_oblast": "Волинська область",
    "Zakarpatska_oblast": "Закарпатська область",
    "Zaporizka_oblast": "Запорізька область",
    "Zhytomyrska_oblast": "Житомирська область",
}

_VOL_RX = re.compile(r"^(?P<slug>.+)_k\.(?P<n>\d+)_hocr_searchtext\.txt\.gz$")


# ── зведення написань ────────────────────────────────────────────────────────

#: Латинські двійники кириличних літер, які OCR підставляє в слова.
_LATIN = str.maketrans({"a": "а", "c": "с", "e": "е", "i": "і", "o": "о", "p": "р",
                        "x": "х", "y": "у", "k": "к", "t": "т", "m": "м", "h": "н",
                        "b": "в", "u": "и"})
#: Зведення, що стирає різницю, яку OCR і старе правопис плутають.
_FOLD = str.maketrans({"ґ": "г", "ї": "і", "и": "і", "ы": "і", "є": "е", "ё": "е",
                       "й": "і", "ъ": "", "ь": ""})


def norm(s: str) -> str:
    """Зведене написання: без регістру, апострофів, пробілів і розділових знаків."""
    s = (s or "").casefold().translate(_LATIN).translate(_FOLD)
    return "".join(ch for ch in s if ch.isalnum())


def _within_one(a: str, b: str) -> bool:
    """Відстань Левенштейна між зведеними рядками не більша за 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


# ── розбір статей ────────────────────────────────────────────────────────────

_CAP = "А-ЯҐІЇЄЁ"
_LOW = "а-яґіїєё"
_AP = "'’ʼ`‘´"
#: Прізвище: ВЕЛИКИМИ або з великої; дефіс, апостроф, пробіл навколо дефіса.
_SURN = rf"[{_CAP}Ь](?:[{_CAP}{_LOW}{_AP}Ь]|\s?-\s?[{_CAP}]){{1,}}"
_NAME = rf"[{_CAP}][{_CAP}{_LOW}{_AP}\-]+"
#: Сміття між словами в OCR: коми, зірочки, лапки, дужки на місці крапки.
_JUNK = r"[\s,;.:*!?„\"'^()\[\]|«»>/]*"
#: Рік народження. OCR розриває цифри пробілами («1 926») і міняє першу на літеру
#: («І 902», «Л 921»); решта трьох цифр мусить бути цифрами.
_YEAR = r"(?P<born>[1ІIlЛДТ]\s?[89]\s?\d\s?\d)"
#: Перед прізвищем OCR іноді лишає шматок сусіднього рядка («л ДЗЕСА Михайло…»).
_LEAD = rf"(?:[{_LOW}a-z]{{1,2}}\s+|[^\w\s]{{1,3}}\s*)?"
_START = re.compile(
    rf"^{_LEAD}(?P<sn>{_SURN})\s+(?P<fn>{_NAME})(?:[\s,.*]+(?P<pn>{_NAME}))?{_JUNK}(?:[1l]\s+)?{_YEAR}"
    rf"(?=\D{{0,8}}?(?:[рнф]|року|рік))")

_MONTHS = {"січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5,
           "червня": 6, "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10,
           "листопада": 11, "грудня": 12}
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*[.:,;]\s*(\d{1,2})\s*[.:,;]\s*"
                       r"(\d\s?\d\s?\d\s?\d)(?!\d)")
_DATE_TXT = re.compile(r"(?<!\d)(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+"
                       r"(\d\s?\d\s?\d\s?\d)(?!\d)")

#: Скорочення, після яких крапка не кінчає речення.
_ABBR = frozenset({"с", "м", "смт", "х", "сел", "обл", "ст", "ім", "вол", "пов", "губ",
                   "кол", "теп", "тис", "пр", "вул", "р-ну", "р-н", "рр", "ч", "п",
                   "т", "д", "ін", "напр", "див", "тощо", "ум", "прож", "реабіл",
                   "арешт", "звинувач", "засудж", "ув'язн", "гр", "ред", "м-ко"})
_PLACE_HINT = re.compile(r"(?:^|\W)(?:с|м|смт|х|сел|кол|теп|хут)\.|район|р-н|р-ну|обл|"
                         r"повіт|пов\.|вол\.|губ|округ|Польща|Румун|Чехо|Словач|"
                         r"Угорщ|Німеч|хутір|місто|село|селищ", re.IGNORECASE)
_VERDICT = re.compile(r"засуд|осужд|расстрел|выслан|приговор|розстр|ув.?яз|заслан|висла|вирок|вироком|страчен|"
                      r"позбавлен|ВМП|табор", re.IGNORECASE)
_NOT_JOB = re.compile(r"^(?:За|Ар|Зв|Вій|Особ|Пост|Реаб|Рішен|Суд|Вирок|Ув|Заслан|"
                      r"Трійк|Колег|Спец|Нарад|Помер|Загин)", re.IGNORECASE)
#: Позначка після року («р. н.», «р.», «року народження», «г. р.») — не частина місця.
_AFTER_YEAR = re.compile(
    r"^[\s,.;:!*'\"|/]*(?:(?:року|рік|р)\s*\.?\s*народження|року|рік|г\.\s*р\.|"
    r"р\s*\.?\s*н\s*\.?|р\s*\.?|[нф]\.?)?[\s,.;:!]*", re.IGNORECASE)
_RESIDES = re.compile(r"(?:Прожива[вл]\w*|Прож\.|проживає|место жит\.? до ареста)\s*:?\s*"
                      r"(?:у|в|на)?\s+", re.IGNORECASE)
_ARRESTED = re.compile(r"(?:Заарештован\w*|Арештован\w*|Заарешт\.|Арешт\.?|арест\.|"
                       r"Затримано)\s*:?\s*")
_REHAB = re.compile(r"Реабіл\w*\.?|Реабилит\w*\.?", re.IGNORECASE)
#: Номер архівно-кримінальної справи після дати реабілітації: «(9731 П)», «(7127-П)».
#: Приймається лише чисте число; «(1Ї456)» з літерою замість цифри — порожньо,
#: бо цифру вгадувати не можна. «П» додається, лише якщо OCR її зберіг.
_CASE = re.compile(r"[(\[/Р]\s*(?P<n>\d[\d\s]{0,8}\d|\d)\s*"
                   r"(?:[-–,.]?\s*(?P<s>[ПпΠ])|[-–,.]?\s*\S{0,3})?\s*[)\]]")
_HEADER_LINE = re.compile(
    rf"^(?:\d{{1,4}}|[{_CAP}{_AP}\-.]{{1,22}}|"
    rf"Біографічні довідки про репресованих|"
    rf"[{_CAP}][{_LOW}{_AP}\- ]+\s(?:район|область))$")


def _num_date(m: re.Match[str]) -> str:
    d, mo, y = int(m.group(1)), int(m.group(2)), re.sub(r"\s", "", m.group(3))
    return f"{d:02d}.{mo:02d}.{y}" if 1 <= mo <= 12 and 1 <= d <= 31 else ""


def _txt_date(m: re.Match[str]) -> str:
    year = re.sub(r"\s", "", m.group(3))
    return f"{int(m.group(1)):02d}.{_MONTHS[m.group(2)]:02d}.{year}"


def first_date(s: str) -> str:
    """Перша дата в рядку, зведена до «дд.мм.рррр»; порожньо, якщо дати немає."""
    best: tuple[int, str] | None = None
    for rx, conv in ((_DATE_NUM, _num_date), (_DATE_TXT, _txt_date)):
        m = rx.search(s)
        if m:
            v = conv(m)
            if v and (best is None or m.start() < best[0]):
                best = (m.start(), v)
    return best[1] if best else ""


def _sentences(text: str) -> list[str]:
    """Речення статті; «р.» після року кінчає речення, «с.», «обл.» — ні."""
    out: list[str] = []
    start = 0
    for m in re.finditer(r"[.!?][,;]?\s+(?=[А-ЯҐІЇЄ])", text):
        before = text[start:m.start()]
        word = re.split(r"[\s(]", before)[-1].casefold() if before else ""
        if word in _ABBR or (len(word) == 1 and word.isalpha() and word != "р"):
            continue
        if word == "р" and not re.search(r"\d\s*$", before[:-1]):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


_BOUND = re.compile(r",\s|;\s*|\.(?=\s+[А-ЯҐІЇЄ])|\.\s*$|$")


def _clause_end(s: str, pos: int) -> re.Match[str]:
    """Кінець ланки: кома, «;» чи крапка, що не стоїть після скорочення."""
    for m in _BOUND.finditer(s, pos):
        if m.group(0).startswith("."):
            word = re.split(r"[\s(]", s[pos:m.start()])[-1].casefold()
            if word in _ABBR:
                continue
        return m
    raise AssertionError("_BOUND завжди збігається на кінці рядка")


def _take_place(s: str) -> tuple[str, str]:
    """Місце з початку рядка: кілька ланок через кому, поки вони схожі на місце.

    «с. Лісове Вигаданського району, українець, …» → («с. Лісове Вигаданського
    району», «українець, …»). Повертає (місце, решта після місця).
    """
    s = s.lstrip(" ,.;:")
    parts: list[str] = []
    pos = 0
    while pos < len(s):
        m = _clause_end(s, pos)
        seg = s[pos:m.start()].strip()
        if parts and not (_PLACE_HINT.search(seg) and len(seg) <= 70
                          and not _VERDICT.search(seg)):
            break
        parts.append(seg)
        pos = m.end()
        if m.group(0).startswith("."):
            break
    return ", ".join(p for p in parts if p), s[pos:].strip()


@dataclass
class Article:
    """Стаття на людину. Порожнє поле — у тексті не знайдено, а не «невідомо»."""

    surname: str
    name: str
    patronymic: str
    born: str
    birth_place: str
    residence: str
    occupation: str
    arrest: str
    charge: str
    verdict: str
    rehab: str
    case_no: str
    leaf: int
    leaf_end: int
    text: str

    @property
    def full_name(self) -> str:
        return " ".join(x for x in (_title(self.surname), self.name, self.patronymic) if x)


def _title(s: str) -> str:
    if s.isupper():
        return "-".join(p[:1].upper() + p[1:].lower() for p in s.split("-"))
    return s


def _tidy(s: str) -> str:
    return " ".join((s or "").replace("¬", "").split()).strip(" ,;:")


def parse_article(text: str, leaf: int, leaf_end: int, m: re.Match[str]) -> Article:
    """Поля статті за ключовими словами. `text` — уже зведені пробіли й переноси."""
    after = _AFTER_YEAR.sub("", text[m.end():], count=1)
    birth_place, _rest = _take_place(after)
    birth_place = _RESIDES.split(birth_place)[0].strip(" ,;")
    residence, occupation = "", ""
    pm = _RESIDES.search(text)
    if pm:
        residence, rest = _take_place(text[pm.end():])
        # заняття: решта речення після місця, якщо воно коротке й не з наступної теми
        tail = rest.split(". ")[0] if rest else ""
        if not tail and rest:
            tail = rest
        tail = tail.strip(" ,;.")
        if tail and len(tail) <= 80 and not _NOT_JOB.match(tail):
            occupation = tail
    am = _ARRESTED.search(text)
    arrest = first_date(text[am.end():am.end() + 40]) if am else ""
    rm = _REHAB.search(text)
    rehab = ""
    if rm:
        seg = text[rm.end():rm.end() + 120]
        rehab = first_date(seg)
        if not rehab:
            ym = re.search(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", seg)
            rehab = ym.group(1) if ym else ""
    sents = _sentences(text)
    v_idx = next((i for i, s in enumerate(sents)
                  if i > 0 and _VERDICT.search(s) and not _REHAB.match(s)), -1)
    r_idx = next((i for i, s in enumerate(sents) if _REHAB.search(s[:40])), len(sents))
    c_idx = next((i for i, s in enumerate(sents) if re.match(r"Звинувач", s)), -1)
    charge = ""
    if c_idx >= 0:
        end = v_idx if v_idx > c_idx else min(r_idx, c_idx + 1)
        charge = re.sub(r"^Звинувач\w*\.?\s*:?\s*", "", " ".join(sents[c_idx:end])).strip()
    verdict = ""
    if v_idx >= 0:
        verdict = " ".join(sents[v_idx:max(v_idx + 1, r_idx)]).strip()
    case_no = ""
    cm = _CASE.search(text, rm.end()) if rm else None
    if cm:
        case_no = re.sub(r"\s", "", cm.group("n")) + (" П" if cm.group("s") else "")
    sn = re.sub(r"\s*-\s*", "-", m.group("sn"))
    return Article(
        surname=sn, name=m.group("fn"), patronymic=m.group("pn") or "",
        born="1" + re.sub(r"\s", "", m.group("born"))[1:], birth_place=_tidy(birth_place),
        residence=_tidy(residence), occupation=_tidy(occupation), arrest=arrest,
        charge=_tidy(charge)[:500], verdict=_tidy(verdict)[:500], rehab=rehab,
        case_no=case_no, leaf=leaf, leaf_end=leaf_end, text=text)


def _clean_line(ln: str) -> str:
    """Зайві пробіли; м'який перенос усередині рядка («Реабі¬ літований»)."""
    ln = " ".join(ln.split())
    ln = re.sub(r"¬\s+(?=\S)", "", ln)
    # «с . Лісове», «у,с. Лісове» → «с. Лісове», «у, с. Лісове»
    ln = re.sub(rf"(?<![{_CAP}{_LOW}])(с|м|х|смт)\s+\.", r"\1.", ln)
    ln = re.sub(r"(?<=[ув]),(?=\s*[смх]\.)", ", ", ln)
    # «Ста- ніславської» → «Станіславської»; цифри й великі літери не чіпаємо
    return re.sub(rf"(?<=[{_LOW}])-\s+(?=[{_LOW}])", "", ln)


def _page_lines(page: str) -> list[str]:
    """Рядки сторінки без колонтитула: номер, «Біографічні довідки…», дороговказ."""
    lines = [_clean_line(ln) for ln in page.split("\n")]
    lines = [ln for ln in lines if ln]
    head = 0
    while head < min(5, len(lines)) and _HEADER_LINE.match(lines[head]):
        head += 1
    return lines[head:]


def _join_soft(lines: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Склеїти переноси: «про¬» + «голошення», «Тисів-» + «ської»."""
    out: list[tuple[str, int]] = []
    carry = ""
    carry_leaf = 0
    for ln, leaf in lines:
        if carry:
            ln = carry + ln
            leaf = carry_leaf
            carry = ""
        if ln.endswith("¬"):
            carry, carry_leaf = ln[:-1], leaf
            continue
        out.append((ln, leaf))
    if carry:
        out.append((carry, carry_leaf))
    # дефіс наприкінці рядка: наступний рядок продовжує слово, якщо починається з малої
    merged: list[tuple[str, int]] = []
    for ln, leaf in out:
        if merged and re.search(rf"[{_LOW}{_CAP}]-$", merged[-1][0]) \
                and re.match(rf"[{_LOW}]", ln):
            merged[-1] = (merged[-1][0][:-1] + ln, merged[-1][1])
            continue
        merged.append((ln, leaf))
    return merged


def _header(text: str) -> str:
    """Шапка статті — від початку до арешту: ім'я, народження, проживання, заняття."""
    m = _ARRESTED.search(text)
    return text[:m.start()] if m and m.start() > 40 else text[:400]


def _article_end(body: str) -> int:
    """Де кінчається стаття: за номером справи після реабілітації.

    Далі в тому ж «шматку» йде сміття колонок, дороговказ чи таблиця; номер
    справи в дужках стаття завершує завжди. Без нього (і без пошкодженого
    «(1Ї456)») — до наступного початку.
    """
    rm = _REHAB.search(body)
    if rm is None:
        return len(body)
    cm = _CASE.search(body, rm.end())
    if cm is not None and cm.start() - rm.end() <= 40:
        end = cm.end()
    else:
        pm = re.compile(r"\([^()]{1,14}\)").search(body, rm.end())
        end = pm.end() if pm is not None and pm.start() - rm.end() <= 40 else len(body)
    return end + 1 if body[end:end + 1] == "." else end


def parse_volume(text: str, spans: list[tuple[int, int]]) -> tuple[list[Article], list[str]]:
    """Текст тому й межі сторінок → статті й райони, названі в колонтитулах.

    `spans[i]` — діапазон символів листа `i` у `text`. Лист статті — той, де
    вона починається; `leaf_end` — де закінчується.
    """
    lines: list[tuple[str, int]] = []
    for leaf, (a, b) in enumerate(spans):
        for ln in _page_lines(text[a:b]):
            lines.append((ln, leaf))
    lines = _join_soft(lines)
    starts: list[tuple[int, re.Match[str]]] = []
    for i, (ln, _leaf) in enumerate(lines):
        m = _START.match(ln)
        if m is None and len(ln) <= 60 and i + 1 < len(lines):
            m = _START.match(f"{ln} {lines[i + 1][0]}")
        if m is not None:
            starts.append((i, m))
    arts: list[Article] = []
    for k, (i, _m) in enumerate(starts):
        j = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        chunk = lines[i:j]
        body = " ".join(c[0] for c in chunk)
        end = _article_end(body)
        leaf_end = chunk[-1][1]
        if end < len(body):
            pos = 0
            for ln, leaf in chunk:
                pos += len(ln) + 1
                if pos > end:
                    leaf_end = leaf
                    break
            body = body[:end]
        if len(body) > ARTICLE_MAX:
            body = body[:ARTICLE_MAX]
        # група збігу рахувалась на кандидаті «рядок + наступний»; перераховуємо на тілі
        mm = _START.match(body)
        if mm is None:
            continue
        arts.append(parse_article(body, chunk[0][1], leaf_end, mm))
    districts: dict[str, int] = {}
    for ln, _leaf in lines:
        dm = re.match(rf"^([{_CAP}][{_LOW}{_AP}\-]+)\sрайон$", ln)
        if dm:
            districts[dm.group(1)] = districts.get(dm.group(1), 0) + 1
    names = [d for d, n in sorted(districts.items(), key=lambda kv: -kv[1]) if n >= 3]
    return arts, names


# ── запит ────────────────────────────────────────────────────────────────────

_FILTER_RX = re.compile(
    r"(?<!\S)(?P<key>oblast|область|book|том|кн|село|place|born|arrest):"
    r"(?:\"(?P<q>[^\"]*)\"|(?P<w>\S*))", re.IGNORECASE)
_FILTER_KEYS = {"oblast": "oblast", "область": "oblast", "book": "book", "том": "book",
                "кн": "book", "село": "place", "place": "place", "born": "born",
                "arrest": "arrest"}


@dataclass(frozen=True)
class Query:
    surname: str = ""
    name: str = ""
    patronymic: str = ""
    place: str = ""
    oblast: str = ""
    book: str = ""
    born: str = ""
    arrest: str = ""

    @property
    def has_person(self) -> bool:
        return bool(self.surname)


def parse_query(q: str) -> Query:
    """«Шевчук Іван oblast:Івано-Франківська book:3» → розібраний запит."""
    vals: dict[str, str] = {}
    rest = q or ""
    for m in _FILTER_RX.finditer(rest):
        key = _FILTER_KEYS[m.group("key").casefold()]
        vals[key] = (m.group("q") if m.group("q") is not None else m.group("w") or "").strip()
    rest = _FILTER_RX.sub(" ", rest)
    words = rest.split()
    for key in ("born", "arrest"):
        if vals.get(key) and not re.fullmatch(r"1[89]\d\d", vals[key]):
            raise SourceError(f"{key}: очікується рік (1900), а не «{vals[key]}»")
    if vals.get("book") and not vals["book"].isdigit():
        raise SourceError(f"book: очікується номер тому, а не «{vals['book']}»")
    return Query(
        surname=words[0] if words else "", name=words[1] if len(words) > 1 else "",
        patronymic=" ".join(words[2:]), place=vals.get("place", ""),
        oblast=vals.get("oblast", ""), book=vals.get("book", ""),
        born=vals.get("born", ""), arrest=vals.get("arrest", ""))


def resolve_oblast(text: str) -> str:
    """Назва області (укр. чи лат., будь-який початок) → ключ у `OBLASTS`."""
    want = norm(text)
    if not want:
        return ""
    found = [slug for slug, ukr in OBLASTS.items()
             if norm(ukr).startswith(want) or norm(slug).startswith(want)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise SourceError(f"області «{text}» немає серед томів серії; є: "
                          f"{', '.join(sorted(OBLASTS.values()))}")
    raise SourceError(f"«{text}» підходить до кількох областей: "
                      f"{', '.join(OBLASTS[s] for s in found)}")


# ── томи ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Volume:
    slug: str
    book: int
    md5: str = ""
    size: int = 0
    index_md5: str = ""
    index_size: int = 0

    @property
    def doc(self) -> str:
        return f"{self.slug}_k.{self.book}"

    @property
    def oblast(self) -> str:
        return OBLASTS.get(self.slug, self.slug.replace("_", " "))

    @property
    def label(self) -> str:
        return f"{self.oblast}, кн. {self.book}"


@dataclass
class VolumeData:
    volume: Volume
    articles: list[Article] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    leaves: int = 0
    #: Скільки днів тому дані взято (з кешу — старіші).
    from_cache: bool = False


def spans_of_pageindex(raw: Any, text_len: int) -> list[tuple[int, int]]:
    """Межі листів у тексті з `_hocr_pageindex.json.gz`; чужа форма — відмова."""
    if not isinstance(raw, list) or not raw:
        raise SourceError("індекс сторінок тому не схожий на перелік діапазонів")
    out: list[tuple[int, int]] = []
    prev = 0
    for row in raw:
        try:
            a, b = int(row[0]), int(row[1])
        except (TypeError, ValueError, IndexError):
            raise SourceError("індекс сторінок тому має рядок не з діапазоном") from None
        if a < prev or b < a or b > text_len:
            raise SourceError(
                "діапазони індексу сторінок не лягають на текст тому "
                f"(лист {len(out)}: {a}–{b} при довжині {text_len}) — нумерацію "
                "листів звірити не можна, і сторінка була б вигаданою")
        out.append((a, b))
        prev = b
    return out


def _md5(blob: bytes) -> str:
    return hashlib.md5(blob, usedforsecurity=False).hexdigest()


class ReabilitovaniSource:
    """Статті «Реабілітовані історією» з OCR томів на Internet Archive."""

    id = "reabilitovani"
    CACHE_REL = Path("data") / "raw" / "reabilitovani" / "_cache"
    label = "Реабілітовані історією (томи серії, OCR на Internet Archive)"
    caps = frozenset({"search"})
    #: Не опитується загальним `catalog.search`: база осіб, а не справ за селом.
    explicit_only = True
    about = SourceAbout(
        answers="чи був репресований цей предок чи хто з цього села потрапив до "
                "репресованих, і яка в нього архівно-кримінальна справа",
        gives="статтю на людину з тому серії: рік і місце народження, проживання, "
              "заняття, арешт, звинувачення, вирок, реабілітацію, номер справи, "
              "том і сторінку (з адресою листа в переглядачі) і повний текст статті",
        not_gives="самої справи; репресованих, яких немає в томах; томів областей, "
                  "яких серія ще не видала чи яких немає на Internet Archive; "
                  "точних слів — це OCR із пошкодженими прізвищами й датами",
        where_class="іменна база репресованих",
        scope=SourceScope(years=(1920, 1959), genres=("архівно-слідчі справи",),
                          note="томи серії за областями (кн. 1–9 на область, не всі "
                               "області й томи); покриття — у знаменнику відповіді"),
        match_on=("person_name", "settlement"), match_how="normalized",
        zero_means="у ЦИХ томах (їхній перелік і число статей — у знаменнику) немає "
                   "статті з такою людиною чи селом у зведеному написанні; томи "
                   "є не для всіх областей, а OCR міг скалічити саме це слово — "
                   "нуль не означає, що репресій у роду чи селі не було",
        pitfalls=("формат статей різний в областях: у частини полів може не бути, "
                  "сирий текст є завжди",
                  "OCR калічить прізвища: збіг нечутливий до ї/і, ґ/г, апострофа, "
                  "регістра, латинських двійників; наближений (на одну літеру) "
                  "позначається в примітці",
                  "без `oblast:` за запит докачується не більше "
                  f"{FRESH_MAX} нових томів — покриття видно в знаменнику",
                  "стаття на розриві сторінок має лист початку; кінець — у примітці",
                  "загальний `nysh find` цю базу не питає — лише `--source reabilitovani`"))

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher
        self._catalog: list[Volume] | None = None
        self._catalog_note = ""
        self._loaded: dict[str, VolumeData] = {}
        #: Покриття останнього пошуку — знаменник нуля.
        self._coverage: dict[str, int] = {}
        self._covered: dict[str, Any] = {}

    # ── транспорт і кеш ─────────────────────────────────────────────────────

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        return Fetcher(base=HOST, delay=0.0, limiter=lim, headers={"User-Agent": app_ua()})

    def _cache_dir(self) -> Path | None:
        if self.workspace is None:
            return None
        return self.workspace / self.CACHE_REL

    def _get(self, url: str, what: str, *, max_bytes: int = FILE_MAX_BYTES) -> bytes:
        # 🔴 Вимкнена мережа — відмова, а не порожня видача.
        if offline() and self._fetcher is None:
            raise SourceError("мережу вимкнено в цьому середовищі — archive.org не опитано")
        try:
            r = self._http().get(url, max_bytes=max_bytes)
        except (HttpError, OSError) as exc:
            raise SourceError(f"archive.org не відповів ({what}): {exc}") from exc
        blob = getattr(r, "content", None)
        if blob is None:
            blob = str(getattr(r, "text", "") or "").encode("utf-8")
        return bytes(blob)

    def _download_url(self, name: str) -> str:
        return f"{HOST}/download/{ITEM}/{quote(name)}"

    # ── каталог томів ───────────────────────────────────────────────────────

    def catalog(self) -> list[Volume]:
        """Томи серії з метаданих запису; кеш живе `CATALOG_TTL_DAYS` днів.

        Том є, лише якщо поруч лежать і текст (`_hocr_searchtext.txt.gz`), і
        індекс сторінок: без другого лист статті не назвеш.
        """
        if self._catalog is not None:
            return self._catalog
        cache = self._cache_dir()
        path = cache / "catalog.json" if cache else None
        stale: dict[str, Any] | None = None
        if path is not None and path.is_file():
            try:
                stale = json.loads(path.read_text(encoding="utf-8"))
                age = (time.time() - float(stale.get("fetched", 0))) / 86400
                if age < CATALOG_TTL_DAYS and stale.get("volumes"):
                    self._catalog = [Volume(**v) for v in stale["volumes"]]
                    return self._catalog
            except (ValueError, TypeError, OSError):
                stale = None
        try:
            body = self._get(f"{HOST}/metadata/{ITEM}", "перелік томів",
                             max_bytes=20 * 1024 * 1024)
            data = json.loads(body.decode("utf-8", errors="replace"))
            files = data["files"]
            if not isinstance(files, list):
                raise TypeError("files")
        except (SourceError, ValueError, KeyError, TypeError) as exc:
            if stale and stale.get("volumes"):
                # Кеш каталогу старий, але чесний: томи не зникають; дату кажемо.
                self._catalog = [Volume(**v) for v in stale["volumes"]]
                self._catalog_note = (
                    f"перелік томів взято з кешу (оновити не вдалось: {exc})")
                return self._catalog
            if isinstance(exc, SourceError):
                raise
            raise SourceError(
                "метадані запису reabilitovani не схожі на перелік файлів — "
                "API archive.org змінився") from exc
        by_name = {str(f.get("name")): f for f in files if isinstance(f, dict)}
        vols: list[Volume] = []
        for name, f in by_name.items():
            m = _VOL_RX.match(name)
            if not m:
                continue
            idx = by_name.get(f"{m.group('slug')}_k.{m.group('n')}_hocr_pageindex.json.gz")
            if idx is None:
                continue
            vols.append(Volume(
                slug=m.group("slug"), book=int(m.group("n")),
                md5=str(f.get("md5") or ""), size=int(f.get("size") or 0),
                index_md5=str(idx.get("md5") or ""),
                index_size=int(idx.get("size") or 0)))
        if not vols:
            raise SourceError("у записі reabilitovani не знайдено жодного тому з "
                              "текстом і індексом сторінок")
        vols.sort(key=lambda v: (OBLASTS.get(v.slug, v.slug), v.book))
        self._catalog = vols
        if path is not None:
            from nyshporka.utils.atomic import write_json

            write_json(path, {"fetched": time.time(),
                              "volumes": [asdict(v) for v in vols]}, indent=None)
        return vols

    def select(self, q: Query) -> list[Volume]:
        vols = self.catalog()
        if q.oblast:
            slug = resolve_oblast(q.oblast)
            vols = [v for v in vols if v.slug == slug]
            if not vols:
                raise SourceError(f"для області «{OBLASTS[slug]}» у записі reabilitovani "
                                  f"томів із текстом немає")
        if q.book:
            vols = [v for v in vols if v.book == int(q.book)]
            if not vols:
                raise SourceError(f"тому {q.book} у вибраних областях немає")
        return vols

    # ── том ─────────────────────────────────────────────────────────────────

    def _parsed_path(self, vol: Volume) -> Path | None:
        c = self._cache_dir()
        return c / f"{vol.doc}.articles.json.gz" if c else None

    def _load_cached(self, vol: Volume) -> VolumeData | None:
        path = self._parsed_path(vol)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            if raw.get("parser") != PARSER_VERSION or raw.get("md5") != vol.md5:
                return None
            return VolumeData(vol, [Article(**a) for a in raw["articles"]],
                              list(raw.get("districts") or []), int(raw.get("leaves", 0)),
                              from_cache=True)
        except (ValueError, TypeError, KeyError, OSError):
            return None

    def _raw_pair(self, vol: Volume) -> tuple[bytes, bytes]:
        """Текст і індекс тому: з кешу або з мережі, із перевіркою сум."""
        cache = self._cache_dir()
        out: list[bytes] = []
        for suffix, md5, size in (("_hocr_searchtext.txt.gz", vol.md5, vol.size),
                                  ("_hocr_pageindex.json.gz", vol.index_md5,
                                   vol.index_size)):
            name = f"{vol.doc}{suffix}"
            path = cache / name if cache else None
            blob = b""
            if path is not None and path.is_file():
                blob = path.read_bytes()
                if (md5 and _md5(blob) != md5) or (size and len(blob) != size):
                    blob = b""
            if not blob:
                blob = self._get(self._download_url(name), f"{name}")
                if size and len(blob) != size:
                    raise SourceError(f"{name}: отримано {len(blob)} байт замість {size} — "
                                      f"файл неповний, у кеш не ліг")
                if md5 and _md5(blob) != md5:
                    raise SourceError(f"{name}: контрольна сума не зійшлась із тією, що "
                                      f"назвав сервер — файл пошкоджений, у кеш не ліг")
                if path is not None:
                    from nyshporka.utils.atomic import atomic_write_bytes

                    atomic_write_bytes(path, blob)
            out.append(blob)
        return out[0], out[1]

    def volume_data(self, vol: Volume) -> VolumeData:
        if vol.doc in self._loaded:
            return self._loaded[vol.doc]
        data = self._load_cached(vol)
        if data is None:
            text_gz, index_gz = self._raw_pair(vol)
            try:
                text = gzip.decompress(text_gz).decode("utf-8", errors="replace")
                index = json.loads(gzip.decompress(index_gz).decode("utf-8"))
            except (OSError, EOFError, ValueError) as exc:
                raise SourceError(f"{vol.doc}: файл тому не читається: {exc}") from exc
            spans = spans_of_pageindex(index, len(text))
            arts, districts = parse_volume(text, spans)
            data = VolumeData(vol, arts, districts, len(spans))
            path = self._parsed_path(vol)
            if path is not None:
                from nyshporka.utils.atomic import atomic_write_bytes

                payload = {"parser": PARSER_VERSION, "md5": vol.md5, "leaves": len(spans),
                           "districts": districts, "articles": [asdict(a) for a in arts]}
                atomic_write_bytes(path, gzip.compress(
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"), 6))
        self._loaded[vol.doc] = data
        return data

    def _cached_only(self, vol: Volume) -> bool:
        return vol.doc in self._loaded or self._load_cached(vol) is not None

    def printed_page(self, vol: Volume, leaf: int) -> str:
        """Друкований номер сторінки для листа; порожньо, якщо його немає."""
        cache = self._cache_dir()
        name = f"{vol.doc}_page_numbers.json"
        path = cache / name if cache else None
        raw: Any = None
        try:
            if path is not None and path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                blob = self._get(self._download_url(name), name, max_bytes=5 * 1024 * 1024)
                raw = json.loads(blob.decode("utf-8", errors="replace"))
                if path is not None:
                    from nyshporka.utils.atomic import atomic_write_bytes

                    atomic_write_bytes(path, blob)
            for p in raw["pages"]:
                if int(p["leafNum"]) == leaf:
                    return str(p.get("pageNumber") or "")
        except (SourceError, ValueError, KeyError, TypeError):
            return ""
        return ""

    # ── пошук ───────────────────────────────────────────────────────────────

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Живий запит; покриття останнього пошуку — у `by_archive`.

        🔴 Знаменник нуля: скільки томів шукали і скільки статей у них
        розібрано. Ключ — область і номери томів, значення — число статей.
        """
        return "live", {"taken": "", "rows": sum(self._coverage.values()) or None,
                        "host": HOST, "by_archive": dict(self._coverage) or None,
                        "scope": "томи серії «Реабілітовані історією» на Internet Archive"}

    @staticmethod
    def _match(a: Article, q: Query, fuzzy: bool) -> bool:
        if q.has_person:
            sn = norm(a.surname)
            want = norm(q.surname)
            if want not in sn and not (fuzzy and len(want) >= 5 and _within_one(want, sn)):
                return False
            if q.name and norm(q.name) not in norm(a.name):
                return False
            if q.patronymic and norm(q.patronymic) not in norm(a.patronymic):
                return False
        # Поля місця розібрані за ключовими словами й ламаються на OCR
        # («с : Тихе», «у,с.»); тож шукаємо й у шапці статті — до арешту.
        if q.place and norm(q.place) not in norm(f"{a.birth_place} {a.residence}") \
                and norm(q.place) not in norm(_header(a.text)):
            return False
        if q.born and a.born != q.born:
            return False
        return not (q.arrest and not a.arrest.endswith(q.arrest))

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        query = parse_query(q)
        if not query.has_person and not query.place:
            if (q or "").strip():
                raise SourceError("потрібне прізвище або `село:<назва>`; самі межі "
                                  "(oblast:, book:) не запит")
            return Hits()
        vols = self.select(query)
        fresh = 0
        searched: list[VolumeData] = []
        skipped: list[Volume] = []
        for vol in vols:
            if not self._cached_only(vol):
                if fresh >= FRESH_MAX and not (query.oblast or query.book):
                    skipped.append(vol)
                    continue
                fresh += 1
            searched.append(self.volume_data(vol))
        self._coverage = {}
        by_oblast: dict[str, list[VolumeData]] = {}
        for vd in searched:
            by_oblast.setdefault(vd.volume.slug, []).append(vd)
        for slug, group in by_oblast.items():
            total = sum(1 for v in self.catalog() if v.slug == slug)
            books = ", ".join(str(g.volume.book) for g in group)
            self._coverage[f"{OBLASTS.get(slug, slug)} · кн. {books} із {total}"] = \
                sum(len(g.articles) for g in group)
        exact: list[tuple[VolumeData, Article]] = []
        near: list[tuple[VolumeData, Article]] = []
        for vd in searched:
            for a in vd.articles:
                if self._match(a, query, fuzzy=False):
                    exact.append((vd, a))
                elif query.has_person and self._match(a, query, fuzzy=True):
                    near.append((vd, a))
        ranked = [(vd, a, False) for vd, a in exact] + [(vd, a, True) for vd, a in near]
        out = Hits()
        for vd, a, approx in ranked[:max(0, limit)]:
            out.append(self._hit(vd, a, approx))
        reasons: list[str] = []
        if len(ranked) > len(out):
            reasons.append(f"показано {len(out)} із {len(ranked)} статей за запитом")
        if skipped:
            reasons.append(
                f"шукали в {len(searched)} із {len(vols)} томів: решту {len(skipped)} "
                f"не докачано (за запит — не більше {FRESH_MAX} нових) — вкажіть "
                f"`oblast:<область>` або повторіть запит, кеш продовжить")
        if self._catalog_note:
            reasons.append(self._catalog_note)
        out.truncated = "; ".join(reasons)
        return out

    def _hit(self, vd: VolumeData, a: Article, approx: bool) -> Hit:
        from nyshporka.sources.ia import viewer_url

        vol = vd.volume
        printed = self.printed_page(vol, a.leaf)
        where = f"{vol.label}" + (f", с. {printed}" if printed else "") + \
                f" (лист n{a.leaf}" + (f"–n{a.leaf_end}" if a.leaf_end != a.leaf else "") + ")"
        facts = " · ".join(x for x in (
            f"нар. {a.born}" + (f", {a.birth_place}" if a.birth_place else ""),
            f"проживав: {a.residence}" if a.residence else "",
            a.occupation,
            f"арешт {a.arrest}" if a.arrest else "",
            f"звинувачення: {a.charge}" if a.charge else "",
            f"вирок: {a.verdict}" if a.verdict else "",
            f"реабілітація {a.rehab}" if a.rehab else "") if x)
        note = (("наближений збіг (прізвище відрізняється на літеру — OCR чи інше "
                 "написання) · " if approx else "")
                + f"{where} · {facts} · «{a.text}»")
        return Hit(
            source=self.id, ref=f"{vol.doc}:n{a.leaf}:{norm(a.surname)}-{a.born}",
            title=a.full_name, years=a.born,
            place=a.residence or a.birth_place,
            shifra=" ".join(x for x in (f"спр. {a.case_no}" if a.case_no else "",
                                        f"({vol.label})") if x),
            archive="", acquirable=False, page=a.leaf,
            url=viewer_url(ITEM, vol.doc, a.leaf), note=note[:NOTE_MAX])
