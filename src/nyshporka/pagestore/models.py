"""Моделі сховища знань про сторінки (`data/pages/**`).

`PageNote` — результат перегляду ОДНІЄЇ сторінки: тип, ПОВНИЙ перелік прізвищ
(ключова гарантія при `status=full`), географія, коментар. `Record` — структурований
запис метрики/сповідки/ревізії (хто/коли/батьки/восприємники) з посиланням на скани.
`CaseFile` — один git-версіонований JSON на справу.

Прізвища й місця зберігаються ЯК НАПИСАНО в джерелі (будь-яка писемність);
нормалізація для fuzzy-пошуку рахується на льоту (`translit.normalize_archival`) —
щоб покращення нормалізації не «протухали» у збережених даних.
"""
from __future__ import annotations

import datetime as _dt
import re
from hashlib import blake2b
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nyshporka.models.citation import Confidence
from nyshporka.models.common import GedDate

# ⚠ поле Record.date затіняє б ім'я `date` у тілі класу (і в default_factory,
# і в резолюції анотацій pydantic) — тому datetime тільки через `_dt.date`
_today = _dt.date.today

# birth/marriage/death/confession/revision вирівняні з CoverageRecordType (source.py)
PageType = Literal[
    "birth", "marriage", "death",
    "confession", "revision", "census",
    "index", "title", "cover", "flyleaf", "blank",
    "illegible", "mixed", "other",
]

# full = ВСІ прізвища сторінки зафіксовано; partial = бачив, але перелік неповний
# (напр. занотовано лише хіти). Merge підвищує статус, але ніколи не понижує.
PageStatus = Literal["full", "partial", "skipped", "unreadable"]

# text — вичитка не з зображення, а з готового текстового декоду (друга гілка
# консенсусу); знати це важливо, бо така гілка успадковує чужі помилки
Method = Literal["visual", "htr", "ocr", "hybrid", "text"]


class PageNote(BaseModel):
    """Анотація однієї сторінки. Ключ у CaseFile.pages — те саме `scan`."""

    model_config = ConfigDict(extra="forbid")

    scan: str = Field(description="Голе ім'я файлу скана ('0030.JPG') або 'page_003' для PDF (0-based).")
    page_type: PageType
    surnames: list[str] = Field(default_factory=list, description="ЯК НАПИСАНО в джерелі.")
    places: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    sheet: str = Field(default="", description="Архівний аркуш: '31зв–32' (конвенція decode_hits).")
    status: PageStatus = "full"
    method: Method = "visual"
    comment: str = ""
    agent: str = Field(default="", description="Хто/яка сесія записала.")
    noted: _dt.date = Field(default_factory=_today)

    @field_validator("scan")
    @classmethod
    def _bare_filename(cls, v: str) -> str:
        v = v.strip()
        if not v or "/" in v or "\\" in v or v.startswith("."):
            raise ValueError("scan мусить бути голим іменем файлу без шляху")
        return v


Role = Literal[
    "child", "father", "mother", "godfather", "godmother",
    "groom", "bride", "groom_father", "groom_mother", "bride_father", "bride_mother",
    "deceased", "spouse", "witness", "priest", "midwife",
    "head", "member",
    "convert", "sponsor",
    "other",
]

# tally — не подія, а власний підсумок книги («родилось мужеска 5, женска 4»)
# та наскрізна нумерація; єдиний незалежний чексум повноти вичитки.
# conversion — приєднання до православ'я, окрема частина метричної книги: для
# роду однодворців-католиків це саме той запис, що доводить конфесійний перехід.
RecordType = Literal["birth", "marriage", "death", "conversion",
                     "confession_entry", "revision_entry",
                     "tally", "other"]


class RecordPerson(BaseModel):
    """Учасник запису — узагальнені ролі покривають метрики/сповідки/ревізії."""

    model_config = ConfigDict(extra="forbid")

    role: Role = "other"
    name: str = Field(default="", description="Повний рядок як у джерелі: 'Іоаннъ Григорьевъ Сікорскій'.")
    surname: str | None = Field(default=None, description="Виділене прізвище — по ньому records grep.")
    given: str | None = None
    patronymic: str | None = Field(
        default=None,
        description="Як у джерелі ('Григорьевъ') — ключовий розрізнювач при зводі осіб.")
    sex: Literal["m", "f"] | None = Field(
        default=None,
        description="Стать; для дитини/померлого обов'язкова — по ній звіряються "
                    "чоловічий і жіночий лічильники книги.")
    estate: str | None = Field(
        default=None,
        description="Стан як у джерелі: 'крестьянинъ', 'однодворецъ', 'мѣщанинъ'.")
    age: str | None = Field(default=None, description="Як написано: '40', 'около 50'.")
    place: str | None = None
    note: str | None = None

    @field_validator("surname", "given", "patronymic", "sex", "estate",
                     "age", "place", "note", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        """Порожній рядок = «не вказано», а не невалідне значення.

        Агенти рівно так само охоче шлють `"sex": ""`, як і `null`; валити
        через це весь акт разом з іменами й прізвищами — надто дорого.
        """
        return None if isinstance(v, str) and not v.strip() else v


class Record(BaseModel):
    """Один структурований запис джерела (акт метрики, двір сповідки, сім'я ревізії)."""

    model_config = ConfigDict(extra="forbid")

    rid: str = Field(default="", description="Стабільний id (ключ upsert); авто '<scan_stem>-<hex8>'.")
    rtype: RecordType
    date: GedDate | None = Field(
        default=None, description="Дата самої події: народження / вінчання / смерті.")
    date2: GedDate | None = Field(
        default=None, description="Друга дата акту: хрещення / поховання.")
    scans: list[str] = Field(min_length=1, description="Сторінки запису (може йти через розворот).")
    sheet: str = ""
    row: str = Field(
        default="",
        description="№ запису в книзі. У метриках лічильники окремі за статтю — "
                    "пиши 'м38' / 'ж36'; у шлюбах наскрізний — '9'.")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Лише для rtype='tally': підсумок книги {'m': 5, 'f': 4}.")
    cause: str | None = Field(
        default=None,
        description="Причина смерті ЯК У ДЖЕРЕЛІ: 'отъ падучей болѣзни', 'старость'. "
                    "Демографічно найцінніша графа книги смертей — епідемії "
                    "видно тільки по ній.")
    persons: list[RecordPerson] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    quote: str | None = Field(default=None, description="Дослівний фрагмент транскрипції.")
    confidence: Confidence = "direct"
    comment: str = ""
    agent: str = ""
    noted: _dt.date = Field(default_factory=_today)

    @field_validator("row", "sheet", "comment", "agent", mode="before")
    @classmethod
    def _none_to_blank(cls, v):
        """Агенти регулярно шлють null там, де поле просто відсутнє в акті.
        Валити через це весь запис — втрачати вичитану сторінку на дрібниці."""
        return "" if v is None else v

    @field_validator("counts", mode="before")
    @classmethod
    def _clean_counts(cls, v):
        """Нечислові значення викидаємо, а не валимо запис.

        Агент, який чесно не розібрав цифру підсумку, пише `{"m": "нрзб"}` —
        і раніше через це гинув увесь підсумок разом із тим, що прочиталось.
        Краще неповний чексум, ніж жодного.
        """
        if not isinstance(v, dict):
            return v
        out = {}
        for k, val in v.items():
            if isinstance(val, bool):
                continue
            if isinstance(val, int):
                out[k] = val
            elif isinstance(val, str) and val.strip().isdigit():
                out[k] = int(val.strip())
        return out

    @field_validator("date", "date2", mode="before")
    @classmethod
    def _date_from_str(cls, v):
        """Зручність для агентів: '1858-03-14' / '1858-03' / '1858' → GedDate.

        Порожній рядок — це «дати немає», а не помилка: агенти шлють `""`
        приблизно так само часто, як `null`.
        """
        if isinstance(v, str):
            iso = v.strip()
            if not iso:
                return None
            precision = {1: "year", 2: "month", 3: "day"}.get(len(iso.split("-")), "day")
            return GedDate(value=iso, precision=precision)
        return v

    @model_validator(mode="after")
    def _auto_rid(self):
        """rid ДЕТЕРМІНОВАНИЙ — інакше конвеєр не ідемпотентний.

        Раніше тут стояв `uuid4`, і повторний `ingest` того самого виводу
        агента створював другий комплект записів замість оновлення наявних:
        обірвана й перезапущена сесія тихо подвоювала справу. Ключ акту —
        сторінка + секція + номер у книзі; він стабільний між прогонами, бо
        це і є природний ідентифікатор запису в самому джерелі.

        Коли номера немає (агент не розібрав), падаємо на підпис учасників:
        гірше за номер, але все одно відтворюване для того самого прочитання.
        """
        if not self.rid:
            stem = Path(self.scans[0]).stem
            row = re.sub(r"\s+", "", (self.row or "")).lower()
            # «[нрзб]» — це не номер, а зізнання, що номера не видно. Як ключ
            # він однаковий для всіх нерозібраних актів сторінки, тож вони
            # перезаписували одне одного: на калібрувальній справі так тихо
            # зникло 22 записи зі 120. Немає цифри — падаємо на підпис учасників.
            if not re.search(r"\d", row):
                row = ""
            if row:
                self.rid = f"{stem}-{self.rtype[:1]}{row}"
            else:
                sig = "|".join(f"{p.role}:{p.name}" for p in self.persons)
                digest = blake2b(sig.encode(), digest_size=4).hexdigest()
                self.rid = f"{stem}-{self.rtype[:1]}x{digest}"
        return self


class CaseFile(BaseModel):
    """Уміст `data/pages/<REPO>/<fond>-<spr>.json` — сторінки + записи однієї справи."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    key: str = Field(description="Канонічний ключ 'DAHMO/315/8433' (repo/fond/spr, як у бібліотеці).")
    repo: str
    fond: str
    spr: str
    opys: str | None = None
    shifra: str = ""
    title: str = ""
    path: str = Field(default="", description="Rel-шлях теки сканів (збагачення з бібліотеки).")
    pages: dict[str, PageNote] = Field(default_factory=dict)
    records: list[Record] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_scan_keys(self):
        for scan, note in self.pages.items():
            if note.scan != scan:
                raise ValueError(f"ключ pages «{scan}» ≠ note.scan «{note.scan}»")
        return self
