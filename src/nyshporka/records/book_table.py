"""🧪 Книжковий бланк → таблиця актів: рядки рушія по графах, акт = рядок таблиці.

ЕКСПЕРИМЕНТАЛЬНЕ: ні в читання, ні в `nysh form`, ні в облік не вбудовано.
Спробувати — `python -m nyshporka.records.book_table <прогін> <прогін>-cells <кадр>`.

Галицька метрика (Liber natorum / copulatorum / mortuorum) — друкований бланк із
графами, акт займає рядок таблиці. Горизонталей між актами на бланку НЕМАЄ, тож
`form_cells` дає вертикалі граф, але не рядки (його «рядки» — випадкові риски
руки), а `records.form` шукає пари «підпис → значення», яких тут немає. Тому
дві незалежні половини:

- **графи** — з голосу `-cells`: високі вузькі клітинки тіла таблиці, згруповані
  за x; назва графи — за положенням її центру в ширині таблиці (частка `frac`
  шаблону), бо друк шапки рушій читає уривками («MIEאSIS a DIES»);
- **акти** — зі звичайного прогону: рядок рушія лягає в графу за перекриттям
  по x, а межа акту — рядок-закриття, яким бланк закінчує кожен акт (у книзі
  померлих — «Sepelivit … Parochus»). Його рушій калічить («Sepecwit Bruzack»),
  тож регекс шаблону свідомо широкий.

Замір на одній сторінці книги померлих 1880 р. (19 актів): на кадрі 976 px
завширшки два акти злиплись в один рядок, на тому самому кадрі, збільшеному ×2,
усі 19 розділено. Ім'я з по батькові — у всіх актах, прізвище — приблизно в
половині, місяці й галочки граф віросповідання/статі — ні. Це одна сторінка:
межі методу ще не міряно.

🔴 Машинне читання: дата, вік і номер будинку з декоду — не факт. Таблиця — для
пошуку й орієнтації в книзі, звіряє око.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

Box = tuple[int, int, int, int]

#: Клітинка тіла таблиці: вища за таку частку сторінки (шапка й тіло — високі,
#: випадкові «рядки» сітки між рисками руки — теж, а заголовок над таблицею — ні)…
TALL_FRAC = 0.06
#: …і вужча за таку частку ширини (рядок на всю ширину — не графа).
NARROW_FRAC = 0.4
#: Клітинки однієї графи: центри ближчі за таку частку ширини кадру.
SAME_COL_FRAC = 0.015
#: Наскільки центр графи може відійти від `frac` шаблону (частка ширини таблиці).
FRAC_TOL = 0.04
#: Два рядки-закриття ближчі за таку частку висоти — шматки одного рядка.
MERGE_FRAC = 0.016
#: Рядок-закриття — останній в акті; межа — трохи нижче його центру.
CUT_PAD_FRAC = 0.005


@dataclass(frozen=True)
class Column:
    name: str
    #: Центр графи — частка ширини таблиці (від лівої межі першої графи).
    frac: float


@dataclass(frozen=True)
class Template:
    name: str
    columns: tuple[Column, ...]
    #: Рядок, яким закінчується кожен акт.
    closing: str


#: Галицька греко-католицька книга померлих (друк «Liber mortuorum», 1870–1880-ті).
#: Частки — з бланка друкарні Мюллера (Стрий); інша друкарня — інший шаблон.
LIBER_MORTUORUM = Template(
    name="liber_mortuorum",
    columns=(
        Column("nr", 0.015), Column("mortis", 0.064), Column("sepulturae", 0.12),
        Column("domus", 0.177), Column("nomen", 0.352),
        Column("catholica", 0.516), Column("alia", 0.545),
        Column("masculus", 0.575), Column("femina", 0.603),
        Column("dies_vitae", 0.657), Column("morbus", 0.804), Column("margo", 0.956),
    ),
    closing=r"[sS][eęa][pc][eilc]|[Pp]ar[oa][ckr]|zac",
)

TEMPLATES = {t.name: t for t in (LIBER_MORTUORUM,)}


@dataclass
class Act:
    top: float
    bottom: float
    #: графа → [(номер рядка прогону з 1, текст)] згори вниз.
    cells: dict[str, list[tuple[int, str]]] = field(default_factory=dict)

    def text(self, col: str) -> str:
        return " | ".join(t for _n, t in self.cells.get(col, []))


@dataclass
class Table:
    template: str
    #: назва графи → (x0, x1) у координатах кадру прогону.
    columns: dict[str, tuple[int, int]]
    acts: list[Act]
    body_top: float
    why: str = ""

    @property
    def found(self) -> bool:
        return bool(self.acts)


def _load(run_dir: Path, stem: str) -> tuple[dict[str, Any], list[str]]:
    geo = json.loads((run_dir / f"{stem}.lines.json").read_text(encoding="utf-8"))
    texts = (run_dir / f"{stem}.txt").read_text(encoding="utf-8").splitlines()
    return geo, texts


def find_columns(cells_geo: dict[str, Any], template: Template,
                 width: int, height: int) -> tuple[dict[str, tuple[int, int]], float]:
    """Графи з клітинок голосу `-cells`, у координатах кадру `width`×`height`.

    Повертає (назва → межі, верх тіла таблиці). Верх тіла — низ найвищої смуги
    високих клітинок, тобто шапки граф.
    """
    cw, ch = cells_geo.get("size") or (width, height)
    sx, sy = width / cw, height / ch
    tall = [b for b in cells_geo.get("boxes") or []
            if (b[3] - b[1]) > TALL_FRAC * ch and (b[2] - b[0]) < NARROW_FRAC * cw]
    if not tall:
        return {}, 0.0
    groups: list[list[list[int]]] = []
    for b in sorted(tall, key=lambda b: (b[0] + b[2]) / 2):
        c = (b[0] + b[2]) / 2
        if groups and c - (groups[-1][-1][0] + groups[-1][-1][2]) / 2 <= SAME_COL_FRAC * cw:
            groups[-1].append(b)
        else:
            groups.append([b])
    spans = [(statistics.median(b[0] for b in g), statistics.median(b[2] for b in g)) for g in groups]
    left, right = min(s[0] for s in spans), max(s[1] for s in spans)
    out: dict[str, tuple[int, int]] = {}
    for x0, x1 in spans:
        f = ((x0 + x1) / 2 - left) / max(1.0, right - left)
        best = min(template.columns, key=lambda c: abs(c.frac - f))
        name = best.name if abs(best.frac - f) <= FRAC_TOL else f"col_{f:.2f}"
        lo, hi = out.get(name, (x0, x1))
        out[name] = (round(min(lo, x0) * sx), round(max(hi, x1) * sx))
    head = min(tall, key=lambda b: b[1])
    return out, head[3] * sy


def _column_of(box: list[int], cols: dict[str, tuple[int, int]]) -> str:
    """Графа за перекриттям по x; у щілині між графами — найближча.

    Щілина буває на місці вузької графи галочок, якої сітка не побачила.
    Поза таблицею — `margo`.
    """
    over = {k: max(0, min(box[2], hi) - max(box[0], lo)) for k, (lo, hi) in cols.items()}
    k = max(over, key=lambda k: over[k])
    if over[k] > 0:
        return k
    c = (box[0] + box[2]) / 2
    if c < min(lo for lo, _hi in cols.values()) or c > max(hi for _lo, hi in cols.values()):
        return "margo"
    return min(cols, key=lambda k: min(abs(c - cols[k][0]), abs(c - cols[k][1])))


def assemble(run_dir: Path, cells_dir: Path, stem: str,
             template: Template = LIBER_MORTUORUM) -> Table:
    """Сторінка `stem` прогону `run_dir` → акти; графи — з голосу `cells_dir`."""
    geo, texts = _load(run_dir, stem)
    width, height = geo["size"]
    cells_geo, _ = _load(cells_dir, stem)
    cols, body_top = find_columns(cells_geo, template, width, height)
    if not cols:
        return Table(template.name, {}, [], 0.0, why="сітки граф не знайдено")
    lines = [(i + 1, b, t.strip(), (b[1] + b[3]) / 2)
             for i, (b, t) in enumerate(zip(geo["boxes"], texts, strict=False)) if t.strip()]
    lines = [ln for ln in lines if ln[3] > body_top]
    closing = re.compile(template.closing)
    ends = sorted(y for _n, _b, t, y in lines if closing.search(t))
    # шматки одного закриття — одна межа, за НИЖНІМ шматком: інакше нижній іде
    # в наступний акт
    cuts: list[float] = []
    for y in ends:
        if cuts and y - cuts[-1] <= MERGE_FRAC * height:
            cuts[-1] = y
        else:
            cuts.append(y)
    pad = CUT_PAD_FRAC * height
    bounds = [body_top, *(c + pad for c in cuts), float(height)]
    acts: list[Act] = []
    for top, bottom in pairwise(bounds):
        act = Act(top, bottom)
        for n, b, t, y in sorted(lines, key=lambda ln: (ln[3], ln[1][0])):
            if top <= y < bottom:
                act.cells.setdefault(_column_of(b, cols), []).append((n, t))
        if act.cells:
            acts.append(act)
    return Table(template.name, cols, acts, body_top,
                 why="" if cuts else "рядка-закриття не знайдено: уся сторінка — один акт")


def to_rows(table: Table) -> list[dict[str, str]]:
    """Акти рядками для TSV: графи шаблону по порядку, потім невпізнані."""
    names = [c.name for c in TEMPLATES[table.template].columns]
    extra = sorted({k for a in table.acts for k in a.cells} - set(names))
    return [{"act": str(i), **{k: a.text(k) for k in names + extra}}
            for i, a in enumerate(table.acts, 1)]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import csv
    import sys

    ap = argparse.ArgumentParser(prog="python -m nyshporka.records.book_table",
                                 description="🧪 книжковий бланк → таблиця актів (експериментальне)")
    ap.add_argument("run", type=Path, help="тека прогону (рядки рушія)")
    ap.add_argument("cells", type=Path, help="тека голосу `-cells` того самого кадру")
    ap.add_argument("stem", help="кадр без розширення")
    ap.add_argument("--template", default=LIBER_MORTUORUM.name, choices=sorted(TEMPLATES))
    ap.add_argument("--tsv", type=Path, help="записати таблицю сюди")
    a = ap.parse_args(argv)
    t = assemble(a.run, a.cells, a.stem, TEMPLATES[a.template])
    rows = to_rows(t)
    print(f"граф {len(t.columns)} · актів {len(t.acts)}" + (f" · {t.why}" if t.why else ""))
    if a.tsv and rows:
        with a.tsv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
            w.writeheader()
            w.writerows(rows)
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else ["act"], delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
