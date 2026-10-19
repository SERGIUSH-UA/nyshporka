"""📜 «Staropolskie Księgi Sądowe» — покажчики осіб і місць гродських книг XVII–XVIII ст.

Укладач (Marcin Kowal, genealogie-kresowe.pl) транскрибує гродські книги ЦДІАК
акт за актом і до кожної дає покажчик осіб і місцевостей: гасло, роль у
документі («wielmożny, miecznik urzędowski; strona kontraktu…»), номери актів.
Поруч — покажчики до книг Київського центрального архіву, яких більше немає
(KAC): від них лишились друковані описи 1869–1909 рр., і покажчик складено з
перекладу опису.

Це відповідь на питання, якого не ставить жоден опис фонду: **хто з роду чи
села стояв перед гродом у XVII–XVIII ст. і в якому акті**. Метрики Поділля й
Брацлавщини до 1790-х майже не вціліли, а гродська книга знає шляхтича,
міщанина, орендаря, попа й підданого поіменно.

🔴 **Це покажчик, а не звірений текст.** Транскрипції, переклади й резюме
укладач готував із мовною моделлю й позначив невпевнене `[?]`. Ім'я чи дата
звідси йде в канон лише після звірки зі сканом (номер скану — у метриці акта
на сторінці укладача; скани — у теці Google Drive укладача).

🔴 **Знаменник вузький**: 8 книг ф.44 (Вінниця) і ф.40 (Летичів) та 70
загублених книг Київщини й Волині. Нуль тут — «немає в ЦИХ книгах», а не «роду
в гродських книгах немає».

Два джерела з одного пака `courtbooks`:

    sks         місця — питається загальним `nysh find` («де згадане моє село»)
    sks-osoby   особи — лише явно, `--source sks-osoby`: назва села,
                підставлена як прізвище, ловила б чужих людей (як `martyrolog`)

Адресація (`ref`): `place:<sig>:<rowid>` / `person:<sig>:<rowid>`.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nyshporka.sources.base import Hit, SourceAbout, SourceError, SourceScope

DOMAIN = "courtbooks"

#: `[?]` укладача, дужки з варіантами й позначки «(nazwisko nieodczytane)».
_UNSURE = re.compile(r"\s*\[\?\]")
_PAREN = re.compile(r"\(([^()]*)\)")
_WORD = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)
#: Закінчення прізвищ, якими різняться мови, а не роди: -ський/-ский/-ski,
#: -цький/-cki. Зводяться до однієї основи після `fold`.
_SURNAME_END = re.compile(r"(sk|ck|zk)(ii|ij|yj|i|y)$")


def _base(s: str) -> str:
    from nyshporka.geog.rkparish import _norm, fold

    return fold(_norm(s))


def surname_key(word: str) -> str:
    """Прізвище будь-якою мовою → згорнута основа для порівняння.

        Jaroszyński → arosinski      Ярошинський → arosinski
        Czetwertyński → cetvertinski Четвертинський → cetvertinski
    """
    s = _base(word)
    return _SURNAME_END.sub(r"\1i", s)


def _clean(s: str) -> str:
    return " ".join(_UNSURE.sub("", str(s or "")).split())


def person_forms(haslo: str) -> tuple[list[str], list[str]]:
    """(форми прізвища, згорнуті слова імені) з гасла укладача.

    Гасло — «Прізвище Ім'я (варіант; з дому …)»: «Czetwertynski (Czetwertyński) Iwan»,
    «Jaroszyńska Agata (z Bębnowskich [?])». Прізвищем вважається перше слово
    й однослівні варіанти в дужках; дівоче прізвище в родовому відмінку
    («z Bębnowskich») не береться — воно інший рід, і склалося б зі збігу.
    Гасло без прізвища («Andrzej (nazwisko nieodczytane)») прізвища не має.
    """
    raw = _clean(haslo)
    if "nazwisko nieodczytane" in raw:
        head = ""
    else:
        head = (_WORD.findall(_PAREN.sub(" ", raw)) or [""])[0]
    alts = [w for inner in _PAREN.findall(raw) for w in [inner.strip()]
            if _WORD.fullmatch(w) and w[:1].isupper()]
    forms: list[str] = []
    for w in [head, *alts]:
        k = surname_key(w) if w else ""
        if k and k not in forms:
            forms.append(k)
    given = [_base(w) for w in _WORD.findall(_PAREN.sub(" ", raw))[1:]]
    return forms, [g for g in given if g]


def place_forms(haslo: str) -> list[str]:
    """Згорнуті форми назви місця: гасло й однослівні варіанти в дужках.

    Форми з рукопису в описі («w Derażni; Derażniach») не беруться: це відмінки,
    і кожен з них дав би фаззі-збіг із чужим селом.
    """
    from nyshporka.geog.rkparish import forms

    raw = _clean(haslo)
    names = [_PAREN.sub("", raw).strip(" ,;")]
    names += [x.strip() for inner in _PAREN.findall(raw) for x in re.split(r"[;,]", inner)
              if x.strip() and not x.strip().lower().startswith(("w ", "inaczej", "na "))]
    # польське -ow- перед суфіксом українською — -ів- (Hrabowce ↔ Грабівці,
    # Hrabowka ↔ Грабівка): та сама ікавізація, що `ó → і`, але без діакритики
    names += [v for n in names for v in [re.sub(r"ow(?=c|k|\b)", "iw", n)] if v != n]
    out: list[str] = []
    for n in names:
        for f in forms(n, "pl"):
            if f and f not in out:
                out.append(f)
    return out


def _years(s: str) -> tuple[int | None, int | None]:
    ys = [int(y) for y in re.findall(r"1[5-9]\d\d", str(s or ""))]
    return (min(ys), max(ys)) if ys else (None, None)


def _csv(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8").lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def records(src: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Тека збирача → рядки пака: ("book" | "act" | "person" | "place", рядок).

    Тека: `books.json`, `acts.tsv`, `osoby.csv`, `miejsca.csv` (`;`, як у
    джерелі). Гасло з шифрою, якої немає серед книг, їде теж: книга без картки
    — це вада переліку, а не підстава губити людину.
    """
    for b in json.loads((src / "books.json").read_text(encoding="utf-8")):
        yf, yt = b.get("year_from"), b.get("year_to")
        if yf is None:
            yf, yt = _years(b.get("years") or "")
        yield "book", {"sig": str(b["sig"]), "kind": str(b.get("kind") or ""),
                       "title": str(b.get("title") or ""), "genre": str(b.get("genre") or ""),
                       "office": str(b.get("office") or ""),
                       "voivodeship": str(b.get("voivodeship") or ""),
                       "years": str(b.get("years") or ""), "year_from": yf, "year_to": yt,
                       "about": str(b.get("about") or ""), "url": str(b.get("url") or "")}
    acts = src / "acts.tsv"
    if acts.is_file():
        with acts.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                yield "act", {"sig": r["sygnatura"], "akt": r["akt"], "url": r["url"]}
    for r in _csv(src / "osoby.csv"):
        forms, given = person_forms(r["haslo"])
        yield "person", {"sig": r["sygnatura"], "name": r["haslo"], "descr": r["opis"],
                         "acts": r["akty"], "forms": " | ".join(forms),
                         "given": " | ".join(given)}
    for r in _csv(src / "miejsca.csv"):
        yield "place", {"sig": r["sygnatura"], "name": r["haslo"], "descr": r["opis"],
                        "acts": r["akty"], "forms": " | ".join(place_forms(r["haslo"]))}


def split_acts(acts: str) -> list[str]:
    """«91, 92» → ['91', '92']; «II/20, 47/72» лишаються як є."""
    return [a.strip() for a in str(acts or "").split(",") if a.strip()]


# ── джерела для `nysh find` ──────────────────────────────────────────────────

_SCOPE = SourceScope(
    archives=("CDIAK",), countries=("UA",), years=(1544, 1798),
    genres=("гродські книги", "судові книги"),
    note="ЦДІАК ф.44 (Вінницький грод, 1732–1790) і ф.40 (Летичівський грод, "
         "1663–1701) — 8 транскрибованих книг; 70 загублених книг Київщини й Волині "
         "(KAC) — за друкованими описами")
_PITFALLS = (
    "покажчик, а не звірений текст: транскрипції й переклади укладач робив із "
    "мовною моделлю, невпевнене позначено [?] — перед каноном звірити скан",
    "KAC — переклад друкованого опису XIX ст.; оригіналу книги немає, звіряти нема з чим",
    "однойменні села: опис місця несе воєводство й повіт — дивитись його, а не назву "
    "(Miastkowce Любомирського ≠ Miastkówka)",
    "без пака `courtbooks` відмовляє, а не дає нуль: `nysh catalog install`")


class _SksBase:
    id = ""
    caps = frozenset({"search"})
    _kind = ""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        from nyshporka.catalog.store import installed

        packs = [p for p in installed(DOMAIN) if p.ok]
        if not packs:
            return "none", {}
        return "bundled", {"taken": max(p.taken for p in packs),
                           "rows": sum(p.rows or 0 for p in packs),
                           "scope": packs[0].note}

    def _hit(self, r: dict[str, Any]) -> Hit:
        lost = r.get("book_kind") == "lost"
        fond = r["sig"].split("-")[0] if not lost else ""
        # один акт з адресою — на акт; кілька чи загублена книга — на книгу
        urls = [a["url"] for a in r.get("act_links") or [] if a.get("url")]
        url = urls[0] if len(urls) == 1 else (r.get("book_url") or "")
        note = " · ".join(x for x in (
            r.get("descr") or "",
            f"акти {r.get('acts')}" if r.get("acts") else "",
            "загублена книга — за друкованим описом" if lost else "",
            "Marcin Kowal, genealogie-kresowe.pl") if x)
        return Hit(source=self.id, ref=f"{self._kind}:{r['sig']}:{r['rowid']}",
                   title=f"{_clean(r['name'])} — {r.get('book_title') or r['sig']}"[:200],
                   years=r.get("book_years") or "",
                   place=r.get("voivodeship") or "",
                   shifra=f"ЦДІАК {r['sig']}" if not lost else r["sig"],
                   repo="CDIAK" if not lost else "", archive="ЦДІАК" if not lost else "KAC",
                   fond=fond, acquirable=False, url=url, note=note)


class SksPlacesSource(_SksBase):
    """Місця покажчиків гродських книг: де згадане село в XVII–XVIII ст."""

    id = "sks"
    label = "Staropolskie Księgi Sądowe — місця (гродські книги XVII–XVIII ст., Коваль)"
    _kind = "place"
    about = SourceAbout(
        answers="де моє село згадане в гродських книгах XVII–XVIII ст. і в якому акті",
        gives="назву місця як у покажчику, опис (воєводство, повіт, власник, ключ), "
              "книгу ЦДІАК чи загублену KAC з роками й номери актів з адресою акта "
              "на сторінці укладача",
        not_gives="тексту акта (він на сторінці укладача); книг поза 8 транскрибованими "
                  "й 70 загубленими; метрик",
        where_class="суди, нотаріат",
        scope=_SCOPE, match_on=("settlement",), match_how="normalized",
        zero_means="у покажчиках 8 гродських книг ф.44/ф.40 і 70 загублених книг KAC "
                   "немає місця з такою назвою за жодною з форм; гродських книг інших "
                   "років і гродів це не стосується",
        pitfalls=_PITFALLS, card="sks")

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        from nyshporka.catalog.query import CatalogMissing, find_court_places

        try:
            ans = find_court_places(q, limit=limit)
        except CatalogMissing as exc:
            raise SourceError(str(exc)) from exc
        return [self._hit(r) for r in ans.rows]


class SksPersonsSource(_SksBase):
    """Особи покажчиків гродських книг: хто з роду стояв перед гродом."""

    id = "sks-osoby"
    label = "Staropolskie Księgi Sądowe — особи (гродські книги XVII–XVIII ст., Коваль)"
    _kind = "person"
    #: База ОСІБ: загальний пошук «що є про моє село» її не питає.
    explicit_only = True
    about = SourceAbout(
        answers="хто з роду стояв перед гродом у XVII–XVIII ст., у якій ролі й у якому акті",
        gives="гасло особи як у покажчику (прізвище, ім'я, варіанти), роль у документі "
              "(титул, уряд, сторона, рік), книгу й номери актів з адресою акта",
        not_gives="тексту акта; осіб поза покажчиками цих книг; звіреного читання — "
                  "[?] укладача лишається сумнівом",
        where_class="суди, нотаріат",
        scope=_SCOPE, match_on=("person_name",), match_how="normalized",
        zero_means="у покажчиках 8 гродських книг ф.44/ф.40 і 70 загублених книг KAC "
                   "немає прізвища, близького за згорнутою формою; прізвище, скалічене "
                   "в транскрипції, могло не зійтися — перебрати написання",
        pitfalls=(*_PITFALLS,
                  "загальний `nysh find` цю базу не питає — лише `--source sks-osoby`",
                  "дівоче прізвище в родовому відмінку («z Bębnowskich») не шукається "
                  "як прізвище — шукати вільним текстом у описах"),
        card="sks")

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        from nyshporka.catalog.query import CatalogMissing, find_court_persons

        try:
            ans = find_court_persons(q, limit=limit)
        except CatalogMissing as exc:
            raise SourceError(str(exc)) from exc
        return [self._hit(r) for r in ans.rows]
