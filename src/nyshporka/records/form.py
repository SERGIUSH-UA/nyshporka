"""📋 Бланк → запис: клітинки голосу `-cells` за шаблоном у записи з ролями.

Читання поклітинно дає на сторінку перелік клітинок з адресою (сторінка
розвороту, рядок таблиці, колонка) і текстом. Шаблон (`data/forms.yaml`, у
просторі — `config/forms.yaml`) каже, який друкований підпис що означає і куди
лягає значення праворуч від нього. Зіставлення — за підписами, а не
координатами: друк рушій читає добре, а сітка двох редакцій бланка різна.

🔴 Це машинне читання: запис іде з `confidence: indirect`, `agent: form:<шаблон>`
і переліком рядків, з яких узято кожне поле (`Record.lines`). Дата й вік з
декоду — не факт: вони лягають рядком як прочитано (`comment`, `age`), а не в
`date` запису.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PACKAGED = Path(__file__).resolve().parent / "data" / "forms.yaml"
#: Свої шаблони — у просторі; накладаються за іменем шаблону.
WORKSPACE_CONFIG = "forms.yaml"

#: Поріг схожості підпису (0–100) і наскільки клітинка-підпис може бути довшою
#: за сам підпис у нормалізованих літерах (номер графи й розділові знаки
#: нормалізація вже прибрала) — довша вже не підпис, а підпис зі значенням.
LABEL_SCORE = 82
LABEL_SLACK = 6
#: І не коротшою за таку частку підпису: «пр.» — підрядок «Прізвища», але не він.
LABEL_MIN = 0.6
#: Поріг напису, за яким упізнається сам бланк на сторінці.
MATCH_SCORE = 80

PERSON_FIELDS = ("surname", "given", "patronymic", "sex", "age", "place", "note")


@dataclass(frozen=True)
class Field_:
    labels: tuple[str, ...]
    to: tuple[str, ...]
    section: str = ""
    inline: bool = True
    #: Регекс значення: що не підходить — не значення (номер акта — цифри).
    pattern: str = ""
    #: Підпис може стояти посеред клітинки, а не лише на початку (заголовок акта
    #: з номером, злитий сіткою з сусіднім текстом).
    anywhere: bool = False


@dataclass(frozen=True)
class Template:
    name: str
    title: str = ""
    rtype: str = "other"
    match: tuple[str, ...] = ()
    sections: dict[str, tuple[str, ...]] = field(default_factory=dict)
    fields: tuple[Field_, ...] = ()


@dataclass
class Cell:
    line: int            # номер рядка сторінки голосу з 1
    addr: tuple[int, ...]
    text: str


def _norm(s: str) -> str:
    from nyshporka.utils.translit import normalize_archival

    s = re.sub(r"['’ʼ`]", "", s or "")             # «Ім'я» = «Імя»: апостроф рушій губить
    return re.sub(r"[^a-z]+", " ", normalize_archival(s).lower()).strip()


def _workspace_file() -> Path | None:
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        return workspace().config / WORKSPACE_CONFIG
    except WorkspaceError:
        return None


def templates(extra: Path | None = None) -> dict[str, Template]:
    """Шаблони пакета, поверх них — простору (і `extra`, якщо дано)."""
    raw: dict[str, Any] = {}
    for p in (PACKAGED, _workspace_file(), extra):
        if p is not None and Path(p).is_file():
            data = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
            raw.update(data.get("forms") or {})
    out: dict[str, Template] = {}
    for name, t in raw.items():
        out[name] = Template(
            name=name, title=str(t.get("title") or ""), rtype=str(t.get("rtype") or "other"),
            match=tuple(t.get("match") or ()),
            sections={k: tuple(v or ()) for k, v in (t.get("sections") or {}).items()},
            fields=tuple(Field_(labels=tuple(f.get("label") or ()), to=tuple(f.get("to") or ()),
                                section=str(f.get("section") or ""),
                                inline=bool(f.get("inline", True)),
                                pattern=str(f.get("pattern") or ""),
                                anywhere=bool(f.get("anywhere")))
                         for f in t.get("fields") or ()))
    return out


def read_page(run_dir: Path, stem: str) -> list[Cell]:
    """Клітинки сторінки голосу `-cells` у порядку читання (сторінка, рядок, колонка)."""
    txt = run_dir / f"{stem}.txt"
    if not txt.is_file():
        return []
    texts = txt.read_text(encoding="utf-8").splitlines()
    try:
        geo = json.loads((run_dir / f"{stem}.lines.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        geo = {}
    addrs = [tuple(a) for a in geo.get("cells") or []]
    cells = [Cell(line=i + 1, addr=addrs[i] if i < len(addrs) else (0, i, 0), text=t)
             for i, t in enumerate(texts)]
    return sorted(cells, key=lambda c: c.addr)


def _score(label: str, text: str) -> int:
    from rapidfuzz import fuzz

    a, b = _norm(label), _norm(text)
    if not a or not b:
        return 0
    return round(fuzz.partial_ratio(a, b))


def is_label(label: str, text: str) -> bool:
    """Клітинка — це сам підпис (з номером графи чи двокрапкою), а не текст із ним."""
    a, b = _norm(label), _norm(text)
    return (bool(b) and len(a) * LABEL_MIN <= len(b) <= len(a) + LABEL_SLACK
            and _score(label, text) >= LABEL_SCORE)


def _inline_value(label: str, text: str, pattern: str = "", anywhere: bool = False) -> str:
    """Значення після підпису в тій самій клітинці: «2. Ім'я Розалія» → «Розалія»,
    «… ЗАПИС АКТА ПРО НАРОДЖЕННЯ № 12» → «12». Підпис шукається вирівнюванням по
    тексту клітинки, значення — те, що праворуч від нього (і `pattern`, якщо дано)."""
    from rapidfuzz import fuzz

    low = re.sub(r"['’ʼ`]", " ", text.lower())
    al = fuzz.partial_ratio_alignment(re.sub(r"['’ʼ`]", " ", label.lower()), low)
    if al is None or al.score < LABEL_SCORE:
        return ""
    # підпис мусить стояти на початку клітинки (після номера графи): усередині
    # довгого друкованого пояснення трилітерне «Вік» знайдеться де завгодно
    if not anywhere and re.sub(r"[\d\s.,:№-]+", "", low[:al.dest_start]):
        return ""
    rest = text[al.dest_end:].strip(" .:;,")
    if pattern:
        m = re.search(pattern, rest)
        return m.group(0) if m else ""
    return rest


def page_matches(t: Template, cells: list[Cell]) -> bool:
    return any(_score(m, c.text) >= MATCH_SCORE for m in t.match for c in cells
               if len(_norm(c.text)) >= len(_norm(m)) * 0.6)


def extract(t: Template, cells: list[Cell]) -> dict[str, tuple[str, int]]:
    """Клітинки сторінки → {'father.surname': (значення, рядок голосу)}.

    Розділ бланка (`sections`) змінюється, щойно трапилась клітинка з його
    якорем; поле шукається серед підписів поточного розділу і полів без розділу.
    Значення — клітинки праворуч у тому ж рядку таблиці, доки не трапиться інший
    підпис; з `inline` — ще й решта клітинки самого підпису.
    """
    labels_all = [lb for f in t.fields for lb in f.labels]
    # Розділи, чиї якорі на сторінці є. Якоря не видно (рушій його зіпсував) —
    # однакові підписи різних розділів розбираються за порядком полів шаблону:
    # перше «Прізвище» — дитини, друге — батьків.
    seen_sections: set[str] = set()
    for c in cells:
        best = max(((_score(a, c.text), name) for name, anchors in t.sections.items()
                    for a in anchors if len(_norm(c.text)) <= len(_norm(a)) * 2),
                   default=(0, ""))
        if best[0] >= MATCH_SCORE:
            seen_sections.add(best[1])
    section = ""
    got: dict[str, tuple[str, int]] = {}
    row_of: dict[tuple[int, ...], list[Cell]] = {}
    for c in cells:
        row_of.setdefault(c.addr[:2], []).append(c)
    for c in cells:
        # «…ПРО ДИТИНУ» і «…ПРО БАТЬКІВ» схожі на дві третини: перемагає найкращий якір
        best = max(((_score(a, c.text), name) for name, anchors in t.sections.items()
                    for a in anchors if len(_norm(c.text)) <= len(_norm(a)) * 2),
                   default=(0, ""))
        if best[0] >= MATCH_SCORE:
            section = best[1]
        for i, f in enumerate(t.fields):
            if any(k in got for k in f.to):
                continue
            if f.section and f.section != section:
                if f.section in seen_sections:
                    continue
                # за порядком: раніше поле з тим самим підписом ще не заповнене
                if any(set(e.labels) & set(f.labels) and not any(k in got for k in e.to)
                       for e in t.fields[:i]):
                    continue
            hit = next((lb for lb in f.labels if is_label(lb, c.text)), None)
            inline = ""
            if f.inline:
                for lb in f.labels:
                    inline = _inline_value(lb, c.text, f.pattern, f.anywhere)
                    # залишок чистого підпису («Прізвищеч» → «ч») — не значення:
                    # він зсунув би батька на місце матері
                    if hit and not f.pattern and len(_norm(inline).replace(" ", "")) < 3:
                        inline = ""
                    if inline:
                        hit = hit or lb
                        break
            if hit is None:
                continue
            # «Прізвище, ім'я та адреса заявника» — це підпис іншого поля, а не
            # «Прізвище» зі значенням «ім'я та …»
            if inline and any(_score(lb, inline) >= LABEL_SCORE for lb in labels_all
                              if len(_norm(lb)) >= 3):
                continue
            values: list[tuple[str, int]] = []
            if inline:
                values.append((inline, c.line))
            row = row_of[c.addr[:2]]
            for n in row[row.index(c) + 1:]:
                if len(values) >= len(f.to):
                    break
                if any(is_label(lb, n.text) for lb in labels_all):
                    break
                val = n.text.strip(" -.—")
                if f.pattern:
                    m = re.search(f.pattern, val)
                    val = m.group(0) if m else ""
                if val:
                    values.append((val, n.line))
            if not values:
                continue
            for key, pair in zip(f.to, values, strict=False):
                got[key] = pair
            break
    return got


_SEX = {"f": ("жін", "жiн", "дівч", "жінка", "ж"), "m": ("чол", "хлоп", "муж", "ч")}


def _sex(value: str) -> str | None:
    v = (value or "").strip().lower()
    for sex, heads in _SEX.items():
        if any(v.startswith(h) for h in heads):
            return sex
    return None


def to_record(t: Template, got: dict[str, tuple[str, int]], *, scan: str,
              run: str) -> dict[str, Any]:
    """Поля → JSON запису для `records.ingest` (машинне читання, не звірене)."""
    persons: dict[str, dict[str, Any]] = {}
    rec: dict[str, Any] = {"rtype": t.rtype, "scans": [scan], "confidence": "indirect",
                           "agent": f"form:{t.name}", "lines": []}
    comment = [f"машинне читання бланка «{t.title or t.name}», оком не звірено"]
    for key, (value, line) in got.items():
        role, _, fld = key.partition(".")
        rec["lines"].append({"run": run, "line": line, "field": key})
        if role == "record":
            if fld == "row":
                m = re.search(r"\d+", value)
                rec["row"] = m.group(0) if m else ""
            elif fld == "date_text":
                comment.append(f"дата як прочитано: «{value}»")
            continue
        p = persons.setdefault(role, {"role": role})
        if fld == "sex":
            sex = _sex(value)
            if sex:
                p["sex"] = sex
            continue
        if fld == "note":
            p["note"] = f"{p['note']}; {value}" if p.get("note") else value
        elif fld in PERSON_FIELDS:
            p[fld] = value
    for p in persons.values():
        p["name"] = " ".join(x for x in (p.get("surname"), p.get("given"), p.get("patronymic"))
                             if x)
    rec["persons"] = list(persons.values())
    rec["comment"] = "; ".join(comment)
    return rec


def pick(templates_: dict[str, Template], cells: list[Cell], want: str = "") -> Template | None:
    """Шаблон сторінки: названий явно — він; інакше перший, чий напис є на сторінці."""
    if want:
        return templates_.get(want)
    return next((t for t in templates_.values() if page_matches(t, cells)), None)
