"""Машинописний опис, прочитаний рушієм друку (PaddleOCR-VL, `nysh cloud go --print
--not-an-edition`) → таблиця справ.

Вхід — тека виходу VL опису: `NNNN.md` (сторінка розмітки, таблиця — HTML з `rowspan`/`colspan`)
і `NNNN.blocks.json` (блоки з рамками). Розбір:

1. **Таблиця** розгортається в сітку; клітинка, що лише продовжує об'єднану, у даних не
   повторюється (інакше номер чи дата впали б у кілька справ).
2. **Колонки** — за друкованими підписами шапки («Порядковий номер», «Заголовок…», «Дати…»,
   «Кількість аркушів»); кожна колонка № відкриває свій бік розвороту. Проста таблиця без
   підписів (шапка — лише номери колонок «1 2 3 …») — один бік, клітинки розбираються за
   вмістом. Сторінка без шапки бере розкладку попередньої з тим самим числом колонок.
3. **Справа** — рядок із номером; без номера — продовження назви попередньої справи того самого
   боку (VL губить порожні клітинки й зсуває решту, тож клітинки беруться за вмістом).
4. **Номери** — прочитані VL (колонку номерів рушій читає майже без хиб): підтверджений —
   сусід іде впритул; номер, що повторює попередній, — літерна справа, якій рушій загубив
   літеру («186а»), без підтвердження; номер 1 після довгого ряду — новий розділ опису.
5. **Місце справи на сторінці.** VL дає ОДНУ рамку на всю таблицю. Тіло рамки ділиться між
   справами сторінки пропорційно оцінці висоти (max(1, ⌈довжина назви / `ZNAKIV`⌉) рядків),
   шапка — `SHAPKA` рядка, смуга — із запасом `ZAPAS` px угору (`mistse=vl`). Замір 24.11.2026
   (ДАХмО ф.17 оп.1, проти місця з другого рушія): смуга накриває справу в 95 % випадків.
   Ворота пакета вимагають лише прив'язки до сторінки, а смуга — орієнтир для ока.

Колонки TSV — `KOLONKY`. `y` — пікселі рендеру сторінки (`VYSOTA`). Числа — машинне читання,
НЕ звірене оком.
"""
from __future__ import annotations

import csv
import html
import json
import math
import re
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path
from typing import Any

#: Висота рендеру сторінки для рушія друку (сірий JPEG).
VYSOTA = 2400
#: Знаків назви на рядок таблиці, рядків шапки, запас угору (px) — для смуги справи (замір 24.11).
ZNAKIV = 40
SHAPKA = 1.0
ZAPAS = 60

#: Ролі колонок за друкованими підписами шапки: українська форма 1967 р. і російська 1954 р.
HEAD = [("no", r"поряд|порядк"), ("dv", r"д[іи]л?ов|д[іи]лов|дiлов"),
        ("title", r"заголов|заголо|зберіг|збериг"),
        ("dates", r"дати|^даты|крайн|почат"),
        ("folios", r"к[іi]ль|^количество л|арку|apky|apkу|aркуш"),
        ("note", r"зазнач|3а3н|3a3н|зазна|^отметки$")]
#: Літери, які рушій плутає з цифрами в номерах.
TR = str.maketrans({"I": "1", "l": "1", "і": "1", "O": "0", "О": "0", "о": "0", "З": "3", "з": "3"})

KOLONKY = ["opys", "no", "title", "end", "year_from", "year_to", "folios", "src_page",
           "page", "part", "row", "y", "no_src", "confirmed", "no_read", "no_span", "no_old",
           "golos", "mistse"]


def num(t: str) -> int | None:
    s = t.strip().translate(TR)
    m = re.fullmatch(r"[^\d]{0,2}(\d{1,5})[а-яa-z]?[^\d]{0,2}", s)
    return int(m.group(1)) if m else None


# ── таблиця сторінки ─────────────────────────────────────────────────────────


class _Tables(HTMLParser):
    """Усі `<table>` сторінки: [[(текст, rowspan, colspan)…] рядок…] таблиця…"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, int, int]]]] = []
        self._cell: list[str] | None = None
        self._span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables and self.tables[-1]:
            self._cell = []
            self._span = (int(a.get("rowspan") or 1), int(a.get("colspan") or 1))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self.tables[-1][-1].append((text, *self._span))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def grid(rows: list[list[tuple[str, int, int]]]) -> list[list[tuple[str, bool]]]:
    """Сітка таблиці: [(текст, перша_клітинка)] — продовження об'єднаної несе той самий
    текст із `False`."""
    out: list[list[tuple[str, bool]]] = []
    carry: dict[tuple[int, int], str] = {}
    for r, row in enumerate(rows):
        line: list[tuple[str, bool]] = []
        c = 0
        cells = iter(row)
        while True:
            while (r, c) in carry:
                line.append((carry.pop((r, c)), False))
                c += 1
            cell = next(cells, None)
            if cell is None:
                break
            text, rs, cs = cell
            for k in range(cs):
                line.append((text, k == 0))
                for dr in range(1, rs):
                    carry[(r + dr, c + k)] = text
            c += cs
        while (r, c) in carry:
            line.append((carry.pop((r, c)), False))
            c += 1
        out.append(line)
    return out


def _role(text: str) -> str | None:
    t = text.lower()
    for role, rx in HEAD:
        if re.search(rx, t):
            return role
    return None


def layout(g: list[list[tuple[str, bool]]]) -> tuple[list[dict[str, int]], int]:
    """Боки розвороту з ролями колонок і індекс першого рядка даних (шапка — рядки згори з
    підписами ролей; бік починається колонкою `no`)."""
    width = max((len(r) for r in g), default=0)
    roles: dict[int, str] = {}
    body = 0
    for i, row in enumerate(g[:4]):
        found = {c: r for c, (t, _) in enumerate(row) if (r := _role(t))}
        if not found:
            break
        for c, r in found.items():
            roles.setdefault(c, r)
        body = i + 1
    if not roles:
        return [], 0
    starts = sorted(c for c, r in roles.items() if r == "no")
    titles = sorted(c for c, r in roles.items() if r == "title")
    if starts and len(titles) > len(starts):
        # підпис «Порядковий номер» одного боку не прочитався, а заголовок — так: колонка №
        # стоїть на тому самому відступі від заголовка
        shift = titles[0] - starts[0]
        for t in titles[len(starts):]:
            if t - shift > starts[-1]:
                starts.append(t - shift)
    if not starts:
        starts = [0]
    sides = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else width
        side = {"no": s}
        for c in range(s, e):
            r = roles.get(c)
            if r and r not in side:
                side[r] = c
        sides.append(side)
    return sides, body


def _nomery_kolonok(g: list[list[tuple[str, bool]]]) -> int | None:
    """Шапка з самих номерів колонок («1 2 3 4 5 6») у перших двох рядках: індекс першого
    рядка даних за нею, інакше None."""
    for i, row in enumerate(g[:2]):
        cyfry = [t.strip() for t, first in row if first and t.strip()]
        if len(cyfry) >= 3 and all(re.fullmatch(r"\d{1,2}", t) for t in cyfry):
            n = [int(t) for t in cyfry]
            if n[0] in (1, 2) and all(b > a for a, b in pairwise(n)) and n[-1] - n[0] <= len(n):
                return i + 1
    return None


def _persha_chysla(g: list[list[tuple[str, bool]]]) -> bool:
    """Перша колонка таблиці — переважно числа (≥ 60 % непорожніх клітинок, хоча б дві)."""
    persha = [r[0][0].strip() for r in g if r and r[0][1] and r[0][0].strip()]
    return len(persha) >= 2 and sum(num(t) is not None for t in persha) >= 0.6 * len(persha)


_MONTH = re.compile(r"(?:янв|фев|мар|апр|ма[яй]|июн|июл|ион|авг|сен|окт|ноя|дек|сiч|січ|лют|бер|"
                    r"кві|тра|чер|лип|сер|вер|жов|лис|гру)", re.I)


def _is_date(t: str) -> bool:
    return bool(_MONTH.search(t) or re.search(r"1[6-9]\d\d", t.translate(TR))) and len(t) < 60


def _starts_case(t: str) -> bool:
    return bool(re.match(r"(?:По|О|Об|Дело|Дѣло|Переписка|Сведения|Ведомост|Список|Журнал|Рапорт|"
                         r"Отчет)", t))


def _split(row: list[tuple[str, bool]], lo: int, hi: int) -> dict[str, Any]:
    """Клітинки одного боку розвороту за ВМІСТОМ: номер — перше число до назви; дата — місяць
    або рік; аркуші — число після дати."""
    out: dict[str, Any] = {"no": None, "no_raw": "", "old": "", "title": [], "dates": [],
                           "folios": []}
    for c in range(lo, min(hi, len(row))):
        text, first = row[c]
        # літеру номера VL пише верхнім індексом LaTeX: «322 $ ^{a} $» — це «322a»
        t = re.sub(r"\s*\$\s*\^\s*\{?\s*([^\W\d_])\s*\}?\s*\$", r"\1", text).strip()
        if not first or not t:
            continue
        n = num(t)
        if n is not None and out["no"] is None and not out["title"] and not out["dates"]:
            out["no"] = n
            out["no_raw"] = t
        elif (out["no"] is not None and not out["old"] and not out["title"] and not out["dates"]
              and re.search(r"\d", t) and len(t) <= 12 and not _is_date(t)):
            out["old"] = t
        elif n is not None and (out["dates"] or out["title"]):
            if re.search(r"\d", t):
                out["folios"].append(t)
        elif _is_date(t) and not (len(re.findall(r"[^\W\d_]", t)) > 25):
            out["dates"].append(t)
        elif len(re.findall(r"[^\W\d_]", t)) >= 6:
            out["title"].append(t)
    return out


def records(md: str, prev: tuple[int, list[dict[str, int]]] | None = None
            ) -> tuple[list[list[dict[str, Any]]], tuple[int, list[dict[str, int]]] | None]:
    """Справи сторінки по боках розвороту і розкладка для наступної сторінки."""
    p = _Tables()
    p.feed(md)
    sides_out: list[list[dict[str, Any]]] = []
    for rows in p.tables:
        g = grid(rows)
        if not g:
            continue
        width = max(len(r) for r in g)
        sides, body = layout(g)
        if not sides:
            if (n := _nomery_kolonok(g)) is not None:
                sides, body = [{"no": 0}], n
            elif prev and prev[0] == width:
                sides, body = prev[1], 0
            elif _persha_chysla(g):
                # шапки немає, а розкладка попередньої не підходить (VL загубив порожню колонку
                # «Примітки» — інша ширина): перша колонка переважно числа — це номери, решту
                # клітинок `_split` розбирає за вмістом. Інакше таблиця сторінки пропадала цілком
                # (машинописний опис ДРАЦС: 179 справ замість 217)
                sides, body = [{"no": 0}], 0
            else:
                continue
        prev = (width, sides)
        per_side: list[list[dict[str, Any]]] = [[] for _ in sides]
        bounds = [s["no"] for s in sides] + [width]
        for row in g[body:]:
            for k in range(len(sides)):
                cell = _split(row, bounds[k], bounds[k + 1])
                recs = per_side[k]
                if cell["no"] is not None:
                    recs.append({"no": cell["no"], "no_raw": cell["no_raw"], "old": cell["old"],
                                 "title": cell["title"], "dates": cell["dates"],
                                 "folios": cell["folios"]})
                elif cell["title"] and recs and recs[-1]["title"] and _starts_case(cell["title"][0]):
                    recs.append({"no": None, "title": cell["title"], "dates": cell["dates"],
                                 "folios": cell["folios"], "lost_no": True})
                elif recs and (cell["title"] or cell["dates"]):
                    recs[-1]["title"] += cell["title"]
                    recs[-1]["dates"] += cell["dates"]
                    recs[-1]["folios"] = recs[-1]["folios"] or cell["folios"]
                elif cell["title"]:
                    recs.append({"no": None, "title": cell["title"], "dates": cell["dates"],
                                 "folios": [], "cont": True})
        sides_out += per_side
    return sides_out, prev


# ── номери ───────────────────────────────────────────────────────────────────

#: Латинська літера номера в читанні VL («136a») — кирилична в оригіналі.
_LITERA = {"a": "а", "b": "б"}
#: Наступна літера літерної справи: «186» → «186а», «136а» → «136б».
_NASTUPNA = {"": "а", "а": "б", "б": "в", "в": "г"}


def _nomer_vl(raw: str) -> tuple[int | None, str]:
    """(номер, літера) з клітинки номера: «136a» → (136, «а»)."""
    m = re.fullmatch(r"\D{0,2}(\d{1,5})\s*([^\W\d_])?\W{0,2}", raw.strip())
    if not m:
        return None, ""
    lit = (m.group(2) or "").lower()
    return int(m.group(1)), _LITERA.get(lit, lit)


def _nomery(recs: list[dict[str, Any]]) -> None:
    """Номери справ із читання VL (див. докстрінг модуля, п. 4)."""
    rozdil = 0
    ostannii: int | None = None
    for r in recs:
        n, _lit = r["_n"]
        if n == 1 and ostannii is not None and ostannii >= 10:
            rozdil += 1
        r["_rozdil"] = rozdil
        if n is not None:
            ostannii = n
    z_nomerom = [r for r in recs if r["_n"][0] is not None]
    for k, r in enumerate(z_nomerom):
        n, lit = r["_n"]
        pered = z_nomerom[k - 1] if k and z_nomerom[k - 1]["_rozdil"] == r["_rozdil"] else None
        if pered is None or lit:
            continue
        pn, plit = pered["_n"]
        dali = z_nomerom[k + 1]["_n"][0] if k + 1 < len(z_nomerom) else None
        if n == pn or (len(str(n)) > 1 and str(n)[:-1] == str(pn) and dali == pn + 1):
            r["_n"] = (pn, _NASTUPNA.get(plit, ""))
            r["_vyvedena"] = True
    skilky: dict[tuple[Any, ...], int] = {}
    for r in recs:
        if r["_n"][0] is not None:
            key = (r["_rozdil"], *r["_n"])
            skilky[key] = skilky.get(key, 0) + 1

    def susid(i: int, krok: int) -> dict[str, Any] | None:
        j = i + krok
        while 0 <= j < len(recs) and recs[j]["_rozdil"] == recs[i]["_rozdil"]:
            if recs[j]["_n"][0] is not None:
                return recs[j]
            j += krok
        return None

    for i, r in enumerate(recs):
        n, lit = r["_n"]
        pered, pislia = susid(i, -1), susid(i, 1)
        p = pered["_n"][0] if pered else None
        q = pislia["_n"][0] if pislia else None
        r.update(no="", no_src="", confirmed="", no_span="")
        lit_pislia = pislia["_n"][1] if pislia is not None else ""
        if r.get("_vyvedena"):
            r.update(no=f"{n}{lit}", no_src="read")
        elif n is not None and skilky[(r["_rozdil"], n, lit)] == 1 and (
                (p is not None and (n == p + 1 or (lit and n == p)))
                or (q is not None and (q == n + 1 or (q == n and lit_pislia)))):
            r.update(no=f"{n}{lit}", no_src="read", confirmed="neighbors")
        elif p is not None and q is not None and q - p == 2 and not lit and not lit_pislia:
            r.update(no=p + 1, no_src="seq", confirmed="between")
        elif n is not None:
            r.update(no=f"{n}{lit}", no_src="read")


def _tochnyi_lantsiuzhok(reads: list[tuple[int, int]], look: int = 200) -> list[tuple[int, int]]:
    """Найдовший ланцюжок прочитаних номерів, де номер росте РІВНО на стільки, скільки рядків між
    ними: опора, між якою й наступною рядків рівно стільки, скільки бракує номерів."""
    n = len(reads)
    best, prev = [1] * n, [-1] * n
    for b in range(n):
        ib, nb = reads[b]
        for a in range(max(0, b - look), b):
            ia, na = reads[a]
            if ib - ia >= 1 and nb - na == ib - ia and best[a] + 1 > best[b]:
                best[b], prev[b] = best[a] + 1, a
    if not n:
        return []
    k = max(range(n), key=lambda i: best[i])
    out = []
    while k >= 0:
        out.append(reads[k])
        k = prev[k]
    return out[::-1]


def _zapovnyty(recs: list[dict[str, Any]], idx: list[int], kotvy: list[tuple[int, int]]) -> None:
    """Між сусідніми опорами, де рядків рівно стільки, скільки номерів, — номери за порядком."""
    for (ka, va), (kb, vb) in pairwise(kotvy):
        if kb - ka < 2 or kb - ka != vb - va:
            continue
        for k in range(ka + 1, kb):
            r = recs[idx[k]]
            if str(r.get("no")) != str(va + k - ka):
                r.update(no=va + k - ka, no_src="seq", confirmed="between")


def _lantsiuzhkom(recs: list[dict[str, Any]]) -> None:
    """Номери, які VL прочитав не з тієї колонки чи переплутав цифри, — ланцюжком у межах розділу.

    Машинописний опис часто має номер за порядком, вписаний ВІД РУКИ над порожньою клітинкою, і
    друкований «№ за старим описом» поруч. VL читає рукописні цифри погано («10, 104, 108, 109»
    замість 136–139) або бере старий номер («14, 15, 16» замість 72–74). Двома проходами:
    1. строгий ланцюжок — опори лише там, де номер росте рівно на число рядків; між ними номери за
       порядком. Випадкове прочитане, що лягло б у звичайний ланцюжок, лічби не ламає;
    2. звичайний ланцюжок (`numbering.chain`) по вже виправлених — де лічба сходиться.
    Літерні справи (номер не росте) розривають строгий ланцюжок: їхні межі лишаються за читанням.
    Замір 25.11.2026 (опис ДРАЦС, 217 справ, звірено оком сторінки 24, 39–42): підтверджено 158 → 207,
    стрибків номерів 24 → 5."""
    from nyshporka.opysy import numbering as NU

    for rozdil in sorted({r["_rozdil"] for r in recs}):
        idx = [i for i, r in enumerate(recs) if r["_rozdil"] == rozdil]
        reads = [(k, recs[i]["_n"][0]) for k, i in enumerate(idx)
                 if recs[i]["_n"][0] is not None and not recs[i]["_n"][1]]
        _zapovnyty(recs, idx, _tochnyi_lantsiuzhok(reads))
        reads2 = [(k, int(v)) for k, i in enumerate(idx) for v in [recs[i].get("no")]
                  if isinstance(v, int) or (isinstance(v, str) and v.isdigit())]
        _zapovnyty(recs, idx, NU.chain(reads2))


def _zlyty(chastyny: list[str]) -> str:
    """Назва з клітинок: перенос зливається лише на МЕЖІ клітинок і лише перед малою літерою;
    дефіси всередині клітинки («м-ко», «1881-1892») лишаються."""
    out = ""
    for ch in (html.unescape(c).strip() for c in chastyny):
        if not ch:
            continue
        if out.endswith(("-", "—")) and ch[:1].islower():
            out = out[:-1] + ch
        else:
            out = f"{out} {ch}" if out else ch
    return out


# ── місце справи й таблиця опису ────────────────────────────────────────────

_ROK = re.compile(r"1[6-9]\d\d")
_SHAPKA_RYADOK = re.compile(r"заголов\w* справ|назва справ|дата початку|кількість арк", re.I)


def _vaha(r: dict[str, Any]) -> float:
    return max(1.0, math.ceil(len(" ".join(r["title"])) / ZNAKIV))


def smuhy(spravy: list[dict[str, Any]], khvist: list[dict[str, Any]],
          blocks: dict[str, Any]) -> list[tuple[int, int]] | None:
    """Смуги справ сторінки (y0, y1) у рамці таблиці VL; без рамки — None."""
    tab = next((b for b in blocks.get("blocks", []) if b.get("label") == "table"), None)
    if tab is None or not spravy:
        return None
    y0, y1 = float(tab["bbox"][1]), float(tab["bbox"][3])
    vagy = [_vaha(r) for r in spravy]
    kh = sum(_vaha(r) for r in khvist)
    krok = (y1 - y0) / (SHAPKA + kh + sum(vagy))
    y = y0 + (SHAPKA + kh) * krok
    out = []
    for v in vagy:
        out.append((max(0, int(y) - ZAPAS), int(y + v * krok)))
        y += v * krok
    return out


def storinky(vl_dir: Path) -> dict[int, tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Справи кожного кадру (`NNNN.md`, з 1) у порядку таблиці й блоки сторінки. Рядок без назви
    й без дат (номери колонок, що не склались у шапку) — не справа."""
    out: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    prev = None
    for p in sorted(Path(vl_dir).glob("[0-9]*.md")):
        n = int(re.search(r"(\d+)", p.stem).group(1))  # type: ignore[union-attr]
        sides, prev = records(p.read_text(encoding="utf-8", errors="replace"), prev)
        bl = p.with_name(f"{p.stem}.blocks.json")
        blocks = json.loads(bl.read_text(encoding="utf-8")) if bl.exists() else {}
        out[n] = ([r for side in sides for r in side if r.get("cont") or r["title"] or r["dates"]],
                  blocks)
    return out


def _porozhni(spravy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рядки без назви: продовження колонки дат — до попередньої справи; назва, яку VL поклав у дати, — у
    назву.

    Машинопис ставить дату початку й кінця в два рядки («5 марта / 1828 / 30 декаб / 1828»), і VL робить
    з другого окремий рядок, а уривок року («805», «1806») бере за номер (ДАВіО ф.792: 15 таких).
    Справа ж, у якої VL відніс назву до дат («Книга записи доверенностей», «Решения суда за 1799 г.»), —
    справа."""
    out: list[dict[str, Any]] = []
    for v in spravy:
        if any(t.strip() for t in v.get("title") or []):
            out.append(v)
            continue
        daty = " ".join(v.get("dates") or [])
        if len(re.findall(r"[^\W\d_]", daty)) >= 12:
            out.append({**v, "title": [daty], "dates": []})
            continue
        poperednia = out[-1] if out else None
        n = v.get("no")
        pn = poperednia.get("no") if poperednia else None
        if poperednia is not None and (n is None or n >= 1500 or (isinstance(pn, int) and n > pn + 50)):
            poperednia["dates"] = [*poperednia.get("dates", []), *(v.get("dates") or [])]
            if not poperednia.get("folios") and v.get("folios"):
                poperednia["folios"] = v["folios"]
            continue
        out.append(v)
    return out


def _poriadok_storinok(recs: list[dict[str, Any]]) -> list[int]:
    """Сторінки в порядку опису: сусідні дві, кожна зі своїм послідовним рядом номерів, що стикуються з
    сусідами лише переставленими, — переставлені (порядок файлів ≠ порядок аркушів).

    ДАВіО ф.792 (25.11.2026): кадри 10, 11, 12 мають 59–66, 76–84, 67–75 — VL читав правильно, а ланцюжок
    за порядком файлів «виправляв» правильні номери. Переставляються лише такі пари: ряди з ≥ 3 номерів,
    ≥ 70 % кроків +1 (VL буває задвоює номер), і стик точний з обох боків."""
    storinky: list[int] = []
    for r in recs:
        if r["src_page"] not in storinky:
            storinky.append(r["src_page"])
    riad: dict[int, tuple[int, int] | None] = {}
    for st in storinky:
        nn = [r["_n"][0] for r in recs if r["src_page"] == st and r["_n"][0] is not None and not r["_n"][1]]
        if nn:
            # уривки років між номерами («818», «1824») — геть: від медіани сторінки далі, ніж рядків + 5
            med = sorted(nn)[len(nn) // 2]
            nn = [n for n in nn if abs(n - med) <= len(nn) + 5]
        kroky = [b - a for a, b in pairwise(nn)]
        riad[st] = (nn[0], nn[-1]) if len(nn) >= 3 and sum(k == 1 for k in kroky) >= 0.7 * len(kroky) else None
    p = storinky[:]
    for i in range(1, len(p) - 1):
        pered, a, b = riad.get(p[i - 1]), riad.get(p[i]), riad.get(p[i + 1])
        if pered and a and b and a[0] != pered[1] + 1 and b[0] == pered[1] + 1 and a[0] == b[1] + 1:
            p[i], p[i + 1] = p[i + 1], p[i]
    return p


def _rik_zaholovok(v: dict[str, Any]) -> bool:
    """Рядок таблиці — рік, а не справа: число 1500–2030 у колонці № і без аркушів, а назва — уривок
    сусідньої колонки дат («ЗАНВАРА») чи штамп («ЦИФРОВА КОПІЯ»), коротше 12 літер. Довша назва —
    справа, над якою стояв рік: номер у неї знімається, далі його ставить ланцюжок."""
    n = v.get("no")
    if not (isinstance(n, int) and 1500 <= n <= 2030 and not v.get("folios")):
        return False
    if len(re.findall(r"[^\W\d_]", " ".join(v.get("title") or []))) >= 12:
        # рік над справою злився з її рядком («1803» замість №20 «Протоколы заседаний суда»): справа
        # лишається, номер — з ланцюжка
        v["no"], v["no_raw"] = None, ""
        return False
    return True


def build(vl_dir: Path, out_tsv: Path, opys: str = "") -> dict[str, Any]:
    """Тека виходу VL опису → таблиця справ TSV (`KOLONKY`); підсумок — числа."""
    st = storinky(Path(vl_dir))
    recs: list[dict[str, Any]] = []
    stat = {"sprav": 0, "mistse_vl": 0, "bez_ramky": 0}
    for page in sorted(st):
        stem = f"{page:04d}"
        vse, blocks = st[page]
        khvist = [v for v in vse if v.get("cont")]
        # Рядок, де стоїть лише рік (1799, 1828…), — заголовок року між справами машинопису, не справа:
        # VL дає його рядком таблиці з числом у колонці №. Без цього опис ДАВіО ф.792 мав 169 «справ»
        # замість 114, а роки, що йдуть один за одним, збивали ланцюжок номерів.
        spravy = [v for v in vse if not v.get("cont") and not _rik_zaholovok(v)]
        stat["sprav"] += len(spravy)
        # хвіст справи з попередньої сторінки — до неї
        prev = recs[-1] if recs and recs[-1]["src_page"] == page - 1 else None
        tekst = [t for v in khvist for t in v["title"] if not _SHAPKA_RYADOK.search(t)]
        if prev is not None and tekst:
            prev["title"] = _zlyty([prev["title"], *tekst])
        spravy = _porozhni(spravy)
        sm = smuhy(spravy, khvist, blocks)
        for k, v in enumerate(spravy):
            if sm is not None:
                y0, y1 = sm[k]
                stat["mistse_vl"] += 1
            else:
                y0, y1 = 0, VYSOTA
                stat["bez_ramky"] += 1
            fol = [x for x in re.findall(r"\d+", " ".join(v["folios"])) if x.strip("0")]
            recs.append({
                "page": stem, "part": "0", "row": len(recs), "src_page": page,
                "y": f"{y0}-{max(y1, y0 + 1)}", "mistse": "vl", "golos": "vl",
                "no_read": v.get("no_raw") or ("" if v.get("no") is None else str(v["no"])),
                "no_old": v.get("old") or "", "title": _zlyty(v["title"]),
                "end": " ".join(v["dates"]), "folios": fol[0] if fol else "",
                "_n": (_nomer_vl(v.get("no_raw") or "") if v.get("no") is not None else (None, ""))})
            if recs[-1]["_n"][0] is None and v.get("no") is not None:
                recs[-1]["_n"] = (v["no"], "")
    # номери — у порядку сторінок ОПИСУ: архів буває викладає два аркуші переставленими
    poriadok = _poriadok_storinok(recs)
    za_opysom = sorted(recs, key=lambda r: (poriadok.index(r["src_page"]), r["row"]))
    _nomery(za_opysom)
    _lantsiuzhkom(za_opysom)
    out_tsv = Path(out_tsv)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=KOLONKY, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in recs:
            roky = [int(y) for y in _ROK.findall(r["end"])]
            w.writerow({**r, "opys": opys, "year_from": min(roky) if roky else "",
                        "year_to": max(roky) if roky else ""})
    return {"cases": len(recs), "pages": len(st),
            "z_nomerom": sum(1 for r in recs if r["no"] != ""),
            "pidtverdzheno": sum(1 for r in recs if r["confirmed"]), **stat}
