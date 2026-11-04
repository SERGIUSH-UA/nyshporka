"""Картки великої видачі (`nysh share vyklyk-rezultat … --param view=books --vse --do`) —
порціями тексту, які агент читає сам або роздає помічникам.

Агент читає книги, а не JSON: сирий файл замірної видачі — 2,6 МБ, ті самі картки
текстом — 0,73 МБ (04.11.2026). Картка — шифр, роки, назва, рядки з номером першої групи
(`g<номер>`) і сусіднім рядком (`‹…›`), де часто стоять сан і ім'я.

Канон проєкту — підказка, а не вирок: справа, яку канон уже згадує, дістає `CANON: <картки>`.
🔴 Номер справи канон пише по-різному — «11-2-3» і «ф. 11, оп. 2, спр. 3»: пошук лише
першого запису 04.11.2026 знайшов 70 справ із 147.

Що сервер кладе в картку, клієнт не тлумачить: бере `book`, `lines` і показує як є.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: Номер справи будь-яким записом: «11-2-3», «11/2/3», «ф. 11, оп. 2, спр. 3».
TRIIKA = re.compile(r"(?<![\d-])(\d{1,4})\s*[-/,.]?\s*(?:оп\.?\s*)?(\d{1,4})\s*[-/,.]?\s*"
                    r"(?:спр\.?\s*|д\.?\s*)?(\d{1,5})(?!\d)")
_SHYFR = re.compile(r"(\d+)[-/](\d+)[-/](\d+)[^\d/-]*$")
#: Рядків на картку в тексті; решта — числом.
RIADKIV = 8
PORTSIIA = 300


def indeks_kanonu(kanon: Path) -> dict[tuple[str, str, str], set[str]]:
    """(фонд, опис, справа) → картки канону, що її згадують."""
    out: dict[tuple[str, str, str], set[str]] = {}
    if not kanon.is_dir():
        return out
    for p in sorted(kanon.rglob("*.md")):
        try:
            tekst = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in TRIIKA.finditer(tekst):
            out.setdefault((m.group(1), m.group(2), m.group(3)), set()).add(p.stem)
    return out


def u_kanoni(shifra: str, indeks: dict[tuple[str, str, str], set[str]]) -> list[str]:
    m = _SHYFR.search(shifra or "")
    return sorted(indeks.get((m.group(1), m.group(2), m.group(3)), ())) if m else []


#: Факти, що кажуть, хто людина була: сан, служба, стан, де жила.
FAKTY_KHTO = ("occupation", "title", "residence", "ordination", "religion", "education")


def osoby_kanonu(kanon: Path) -> list[str]:
    """Особи канону рядками для помічника: «<id> | Іван Тарасюк; Иванъ Тарасюкъ | 1810–1885 |
    Священик церкви с. … | <село>».

    🔴 Усі особи, а не відібрані за прізвищем: 04.11.2026 відбір за полем `surname` загубив
    осіб, у яких прізвище записано лише у формі імені, і помічник назвав відомих людей
    новими."""
    from nyshporka.storage.files import read_person, read_place

    mistsia: dict[str, str] = {}
    for p in sorted((kanon / "places").glob("*.md")):
        try:
            pl = read_place(p)
        except Exception:  # зламана картка місця не валить перелік осіб
            continue
        mistsia[pl.id] = pl.name
    out = []
    for p in sorted((kanon / "persons").glob("*.md")):
        try:
            o = read_person(p)
        except Exception:  # зламана картка особи — пропуск (`nysh canon check` її покаже)
            continue
        formy = list(dict.fromkeys([o.primary_name, *(n.form for n in o.names)]))[:4]
        roky = sorted({int(m.group(0)) for f in o.facts if f.date
                       for m in [re.match(r"\d{4}", f.date.value or "")] if m})
        khto = [re.sub(r"[*\[\]_`]", "", str(f.value))[:70] for f in o.facts
                if f.type in FAKTY_KHTO and f.value][:2]
        de = sorted({mistsia[f.place_id] for f in o.facts if f.place_id in mistsia})[:4]
        out.append(" | ".join([o.id, "; ".join(formy),
                               f"{roky[0]}–{roky[-1]}" if roky else "", "; ".join(khto),
                               ", ".join(de)]))
    return out


def prochytaty(fayl: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Шапка й картки з файла вивантаження. Не картки (немає `book`/`lines`) — `ValueError`."""
    shapka: dict[str, Any] = {}
    kartky: list[dict[str, Any]] = []
    with fayl.open(encoding="utf-8") as f:
        for riadok in f:
            if not riadok.strip():
                continue
            it = json.loads(riadok)
            if "header" in it and not kartky and not shapka:
                shapka = it["header"]
                continue
            if not isinstance(it.get("book"), dict) or not isinstance(it.get("lines"), list):
                raise ValueError("у файлі не картки книг: вивантажте з --param view=books")
            kartky.append(it)
    return shapka, kartky


def tekst_kartky(n: int, k: dict[str, Any], kanon: list[str]) -> str:
    b = k["book"]
    roky = "–".join(str(x) for x in dict.fromkeys(b.get("years") or []) if x)
    shapka = f"## K{n} {b.get('shifra')} | {roky} | {str(b.get('title') or '')[:110]}"
    if k.get("own"):
        shapka += " | own"
    if k.get("new"):
        shapka += " | new"
    if kanon:
        shapka += f" | CANON: {','.join(kanon[:4])}"
    out = [shapka]
    riadky = k.get("lines") or []
    for rd in riadky[:RIADKIV]:
        ids = rd.get("group_ids") or []
        dali = f"+{len(ids) - 1}" if len(ids) > 1 else ""
        pered = f" ‹{str(rd['before'])[:60]}›" if rd.get("before") else ""
        out.append(f"- g{ids[0] if ids else '?'}{dali} ×{rd.get('times')} p{rd.get('page')}:"
                   f"{pered} {str(rd.get('line') or '')[:120]}")
    reshta = max(0, len(riadky) - RIADKIV) + int(k.get("more_lines") or 0)
    if reshta:
        out.append(f"- … ще рядків: {reshta}")
    return "\n".join(out)


def porcii(fayl: Path, *, kanon: Path | None, porciia: int = PORTSIIA, vid: int = 0,
           do: Path | None = None) -> dict[str, Any]:
    """Картки текстом. Без `do` — одна порція з картки `vid`; з `do` — усі порції файлами
    `porciia_<n>.md`. Номери карток (`K<n>`) — за порядком у файлі, тож однакові в обох."""
    shapka, kartky = prochytaty(fayl)
    indeks = indeks_kanonu(kanon) if kanon is not None else {}
    teksty = [tekst_kartky(i, k, u_kanoni(str(k["book"].get("shifra") or ""), indeks))
              for i, k in enumerate(kartky)]
    v_kanoni = sum(1 for t in teksty if " | CANON: " in t.split("\n", 1)[0])
    zahal = {"kartok": len(kartky), "v_kanoni": v_kanoni, "kanon": kanon is not None,
             "last_pass": shapka.get("last_pass"), "surname": shapka.get("surname")}
    if do is None:
        chastyna = teksty[vid:vid + porciia]
        dali = vid + porciia if vid + porciia < len(teksty) else None
        return {**zahal, "vid": vid, "dali": dali, "tekst": "\n\n".join(chastyna)}
    do.mkdir(parents=True, exist_ok=True)
    fayly = []
    for n in range(0, len(teksty), porciia):
        p = do / f"porciia_{n // porciia + 1}.md"
        p.write_text("\n\n".join(teksty[n:n + porciia]) + "\n", encoding="utf-8")
        fayly.append({"fayl": str(p), "kartky": [n, min(n + porciia, len(teksty)) - 1]})
    out: dict[str, Any] = {**zahal, "fayly": fayly}
    if kanon is not None and (kanon / "persons").is_dir():
        osoby = osoby_kanonu(kanon)
        p = do / "kanon_osoby.md"
        p.write_text("# Особи канону: id | імена | роки | хто | де\n\n" + "\n".join(osoby) + "\n",
                     encoding="utf-8")
        out["osoby"] = {"fayl": str(p), "osib": len(osoby)}
    return out
