"""Робоча тека пакета опису — `manifest.json`, `pages.jsonl`, `rows.jsonl` — з прочитаного.

Що збирається:
- **сторінки** — текст кожної сторінки з прогонів цілих сторінок усіма голосами: головна тека
  прогону й сестринські `<тека>-<модель>` (`nysh read … --with`);
- **рядки справ** — таблиця (`ruled.build`): `page`, `part` (половина розвороту), `y` у пікселях
  кадру → частки сторінки за розміром кадру з `lines.json.gz`. Справа, що переходить на наступну
  сторінку (`y` = `2390-3100; 0002_0:631-3100`), — кілька шматків місця;
- **нормалізація** — `title_norm` за ключем сирої назви (`norm_batches.key`), якщо є.

Далі — `nysh opys pack <тека>`: ворота й `.nyshopys`.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from nyshporka.opysy import norm_batches as NB

LICENSE = "CC-BY-NC-SA-4.0"
#: Позначка номера таблиці → `Row.no_status`; решта — «звірити».
STATUS = {"neighbors": "neighbors", "between": "between", "chain": "chain", "eye": "eye"}
_SEG = re.compile(r"^\s*(?:(\d{4})_(\d):)?\s*(\d+)-(\d+)\s*$")


def run_voices(main: Path) -> list[tuple[str, Path]]:
    """(голос, тека) прогонів цілих сторінок: головна + сестринські `<ім'я>-<модель>`."""
    main = Path(main)
    name = main.name
    out: list[tuple[str, Path]] = []
    for d in [main, *sorted(main.parent.glob(f"{name}-*"))]:
        meta = d / "_htr_meta.json"
        if not meta.exists():
            continue
        if d == main:
            model = str(json.loads(meta.read_text(encoding="utf-8")).get("model") or d.name)
            out.append((Path(model).stem, d))
        else:
            # 🔴 Сестринський голос — з назви теки (`…-diak_v16`), не з `model`: там
            # «pysar_cyr_v31.pt+diak_v16», і `Path(…).stem` дав би ім'я головного голосу —
            # текст другого голосу затер би текст першого в тій самій сторінці.
            out.append((d.name[len(name) + 1:], d))
    return out


def page_size(run: Path, stem: str) -> tuple[int, int] | None:
    """[ширина, висота] кадру, як його бачив рушій (`ruled.page_lines` бере те саме)."""
    from nyshporka.htr.layout import load_geometry

    d = load_geometry(Path(run), stem)
    if d is None:
        return None
    w, h = d.get("size") or (d.get("width"), d.get("height"))
    return (int(w), int(h)) if w and h else None


def regions(rec: dict[str, Any], sizes: dict[str, tuple[int, int]], spread: bool) -> list[dict[str, Any]]:
    """Шматки місця справи (`y` таблиці) у частках сторінки; сторінка без розміру — пропуск."""
    out = []
    for seg in str(rec.get("y") or "").split(";"):
        m = _SEG.match(seg)
        if not m:
            continue
        stem = m.group(1) or rec["page"]
        part = int(m.group(2)) if m.group(2) is not None else int(rec.get("part") or 0)
        y0, y1 = int(m.group(3)), int(m.group(4))
        size = sizes.get(stem)
        if size is None:
            continue
        h = size[1]
        y0, y1 = max(0, min(y0, h - 1)), max(1, min(y1, h))
        if y1 <= y0:
            continue
        out.append({"page": int(stem), "half": part if spread else None,
                    "y0": round(y0 / h, 4), "y1": round(y1 / h, 4)})
    return out


def no_of(rec: dict[str, Any]) -> tuple[int | None, str]:
    """(номер, літера) з колонки `no` таблиці: «12а» → (12, «а»)."""
    m = re.match(r"^\s*(\d+)\s*([^\d\s]*)", str(rec.get("no") or ""))
    return (int(m.group(1)), m.group(2)) if m else (None, "")


def language(pages: list[dict[str, Any]], default: str) -> str:
    """Мова опису з тексту: українські (і ї є ґ) проти російських (ы э ъ ё) літер."""
    tekst = " ".join(v for p in pages for v in p["voices"].values()).lower()
    uk = sum(tekst.count(c) for c in "іїєґ")
    ru = sum(tekst.count(c) for c in "ыэъё")
    if uk > 2 * ru and uk >= 20:
        return "uk"
    if ru > 2 * uk and ru >= 20:
        return "ru"
    return default


def pages_from_voices(voices: list[tuple[str, Path]], total: int) -> list[dict[str, Any]]:
    """Сторінки 1…`total` з текстом кожного голосу; сторінки без жодного тексту — пропуск."""
    pages = []
    for i in range(1, total + 1):
        s = f"{i:04d}"
        vv = {}
        for name, d in voices:
            t = Path(d) / f"{s}.txt"
            if t.exists():
                vv[name] = t.read_text(encoding="utf-8")
        if not vv:
            continue
        pages.append({"page": i, "voices": vv, "blank": not any(x.strip() for x in vv.values())})
    return pages


def is_spread(sizes: dict[str, tuple[int, int]]) -> bool:
    """Більшість кадрів — розвороти (ширина > 1.2 висоти)."""
    return sum(1 for w, h in sizes.values() if w > 1.2 * h) > len(sizes) / 2


def rows_from_table(tsv: Path, sizes: dict[str, tuple[int, int]], spread: bool,
                    norm: dict[tuple[str, str, str], str]) -> list[dict[str, Any]]:
    """Рядки пакета з таблиці справ: місце, номер і його позначка, назва сира й нормалізована."""
    rows: list[dict[str, Any]] = []
    tsv = Path(tsv)
    if not tsv.exists():
        return rows
    with tsv.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            regs = regions(r, sizes, spread)
            if not regs or not (r.get("title") or "").strip():
                continue
            # 🔴 Нормалізація — за ТЕКСТОМ сирої назви на тій самій сторінці й половині, а не за
            # номером рядка: перебудова таблиці зсуває номери рядків, і старі нормалізації лягли
            # б на чужі справи.
            key = NB.key(r["page"], r["part"], r["title"])
            if key in norm and not norm[key].strip():
                # Нормалізатор лишив порожньо — сміття бланка (штамп, «Проверено», шапка), не
                # справа. Рядок геть, текст сторінки лишається для пошуку.
                continue
            no, letter = no_of(r)
            rows.append({
                "regions": regs, "no_raw": str(r.get("no_read") or ""), "no": no,
                "letter": letter, "no_status": STATUS.get(str(r.get("confirmed") or ""), "unconfirmed"),
                "title_raw": r["title"].strip(),
                "title_norm": norm.get(key, ""),
                "years": str(r.get("year") or "") or "–".join(
                    dict.fromkeys(x for x in (r.get("year_from"), r.get("year_to")) if x)),
                "folios": str(r.get("folios") or ""),
                "end": str(r.get("end") or ""),
                # Рядок на кілька номерів (`numbering.number`): у видачі — «звірте номер».
                "no_span": str(r.get("no_span") or "")})
    return rows


def manifest(*, repo: str, fond: str, opys: str, language: str, source: dict[str, Any], pages: int,
             spread: bool, engines: list[str], quality: dict[str, Any], tool: str,
             norm_model: str = "", normalized: bool = False) -> dict[str, Any]:
    """Маніфест пакета. `norm_model` — модель, що нормалізувала назви (її називає агент учасника);
    з нормалізованими рядками без моделі маніфест не складається."""
    from nyshporka.opysy.schema import SCHEMA

    m: dict[str, Any] = {
        "schema": SCHEMA, "repo": repo, "fond": fond, "opys": opys, "language": language,
        "sources": [{**source, "pages": pages, "spread": spread}],
        "engines": engines, "license": LICENSE, "quality": quality, "tool": tool,
    }
    if normalized:
        if not norm_model:
            raise ValueError("назви нормалізовано, а модель нормалізації не названо")
        from nyshporka.opysy import normalize as NZ

        m["normalization"] = {"prompt": NZ.PROMPT_ID, "version": NZ.VERSION, "model": norm_model}
    return m


def write(work: Path, man: dict[str, Any], pages: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Path:
    """Записати робочу теку пакета."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1),
                                        encoding="utf-8", newline="\n")
    (work / "pages.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pages), encoding="utf-8",
        newline="\n")
    (work / "rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8",
        newline="\n")
    return work
