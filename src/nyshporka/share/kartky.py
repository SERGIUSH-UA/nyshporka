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
#: 🔴 Роздільник між номерами обов'язковий: без нього «скан 0128» читалось як справа 1-2-8,
#: і будь-яке трицифрове число в каноні давало хибне «справа в каноні».
TRIIKA = re.compile(r"(?<![\d-])(\d{1,4})\s*(?:[-/,.]\s*|\s+)(?:оп\.?\s*)?(\d{1,4})\s*"
                    r"(?:[-/,.]\s*|\s+)(?:спр\.?\s*|д\.?\s*)?(\d{1,5})(?!\d)")
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


# ── Сторінка в каноні ────────────────────────────────────────────────────────────────
# 🔴 04.11.2026: із чотирьох «нових» кандидатів розбору три вже лежали в каноні —
# доказ-кропом із підписом «спр.3 скан 0128 …», без факту й без цитати. Позначка «справа в
# каноні» (вище) їх не відрізняла від решти сотні сторінок тієї самої книги, тож
# сторінка звіряється окремо: цитати фактів (джерело + «скан N»), доказ-кропи (ім'я файла
# й підпис) і маніфест доказів (рядок, з якого кроп, `--from`).

_STOR = re.compile(r"(?:скан|кадр|scan|frame)\w*\.?\s*(?:№\s*)?(\d{1,5}(?:\s*[-–,]\s*\d{1,5})*)",
                   re.I)
_CHYSLO = re.compile(r"\d{1,5}")
_SPR = re.compile(r"спр\.?\s*(\d{1,5})", re.I)
#: Доказ-кроп `arkh_11-2-3_1849_0013_…`: справа, далі числа — рік і/або сторінка.
_DOKAZ = re.compile(r"(?<![\d-])(\d{1,4})-(\d{1,4})-(\d{1,5})((?:_\d{1,5})+)_")
#: Старі кропи `d3_0128_…`: лише справа й сторінка; фонд і опис — з цитат тієї самої картки.
_DOKAZ_SPR = re.compile(r"(?:^|[/_\\])d(\d{1,5})_(\d{3,5})_")
_DATA = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}")

Triika = tuple[str, str, str]


def _n(x: str) -> str:
    return x.lstrip("0") or "0"


def _triika(m: re.Match[str]) -> Triika:
    return (_n(m.group(1)), _n(m.group(2)), _n(m.group(3)))


def _triika_v_teksti(tekst: str) -> Triika | None:
    """Перша справа в тексті; дата «5.12.1904» справою не вважається."""
    for m in TRIIKA.finditer(tekst or ""):
        if not _DATA.fullmatch(m.group(0).strip()):
            return _triika(m)
    return None


def _storinky(tekst: str) -> set[int]:
    return {int(x) for m in _STOR.finditer(tekst or "") for x in _CHYSLO.findall(m.group(1))}


def _z_dokazu(shliakh: str) -> tuple[Triika, int] | None:
    m = _DOKAZ.search(Path(shliakh).name)
    if not m:
        return None
    chysla = [x for x in m.group(4).split("_") if x]
    # «…_1849_0013_» — рік, далі сторінка; «…_0013_» — одразу сторінка.
    if len(chysla) >= 2 and len(chysla[0]) == 4 and 1500 <= int(chysla[0]) <= 1950:
        return _triika(m), int(chysla[1])
    return _triika(m), int(chysla[0])


def _shapka_md(p: Path) -> dict[str, Any]:
    import yaml

    try:
        tekst = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not tekst.startswith("---"):
        return {}
    kin = tekst.find("\n---", 3)
    try:
        dani = yaml.safe_load(tekst[3:kin if kin > 0 else None])
    except yaml.YAMLError:
        return {}
    return dani if isinstance(dani, dict) else {}


def _obkhid(vuzol: Any, tsytaty: list[dict[str, Any]], media: list[dict[str, Any]]) -> None:
    if isinstance(vuzol, dict):
        if vuzol.get("source_id"):
            tsytaty.append(vuzol)
        elif vuzol.get("path") and "caption" in vuzol:
            media.append(vuzol)
        for v in vuzol.values():
            _obkhid(v, tsytaty, media)
    elif isinstance(vuzol, list):
        for v in vuzol:
            _obkhid(v, tsytaty, media)


def indeks_storinok(kanon: Path, manifest: Path | None = None
                    ) -> dict[tuple[str, str, str, int], set[str]]:
    """(фонд, опис, справа, сторінка) → картки канону, що вже мають цю сторінку."""
    out: dict[tuple[str, str, str, int], set[str]] = {}
    if not kanon.is_dir():
        return out

    def dodaty(t: Triika, s: int, kartka: str) -> None:
        out.setdefault((*t, s), set()).add(kartka)

    dzherela: dict[str, Triika] = {}
    for p in sorted((kanon / "sources").glob("*.md")):
        h = _shapka_md(p)
        for pole in ("title", "repository_ref"):
            t = _triika_v_teksti(str(h.get(pole) or ""))
            if t:
                dzherela[str(h.get("id") or p.stem)] = t
                break
    kartky_kanonu: set[str] = set()
    for p in sorted(kanon.rglob("*.md")):
        if p.parent.name == "sources":
            continue
        kartky_kanonu.add(p.stem)
        tsytaty: list[dict[str, Any]] = []
        media: list[dict[str, Any]] = []
        _obkhid(_shapka_md(p), tsytaty, media)
        svoi: list[Triika] = []
        for c in tsytaty:
            t = dzherela.get(str(c.get("source_id") or ""))
            if t is None:
                continue
            svoi.append(t)
            for s in _storinky(str(c.get("page") or "")):
                dodaty(t, s, p.stem)
            for shliakh in re.findall(r"[\w./\\-]+\.(?:jpe?g|png)", str(c.get("note") or "")):
                z = _z_dokazu(shliakh)
                if z:
                    dodaty(z[0], z[1], p.stem)
        for m in media:
            shliakh, pidpys = str(m.get("path") or ""), str(m.get("caption") or "")
            z = _z_dokazu(shliakh)
            if z:
                dodaty(z[0], z[1], p.stem)
                continue
            t = _triika_v_teksti(pidpys)
            stor = _storinky(pidpys)
            ms = _DOKAZ_SPR.search(shliakh)
            if t is None:
                spr = (ms.group(1) if ms else None) or next(
                    (x.group(1) for x in _SPR.finditer(pidpys)), None)
                t = next((x for x in svoi if spr and x[2] == _n(spr)), None)
            if ms:
                stor.add(int(ms.group(2)))
            if t is not None:
                for s in stor:
                    dodaty(t, s, p.stem)
    if manifest is not None and manifest.is_file():
        try:
            zapysy = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            zapysy = {}
        for v in (zapysy.values() if isinstance(zapysy, dict) else []):
            pokhid = (v or {}).get("origin") or {}
            m = _SHYFR.search(str(pokhid.get("case") or ""))
            s = re.search(r"(\d+)\D*$", str(pokhid.get("page") or ""))
            if not (m and s):
                continue
            for kto in (v.get("cited_by") or []):
                # «<проєкт>:<картка>.md» — лише картки ЦЬОГО канону: чужий проєкт — не наш висновок.
                kartka = Path(str(kto).split(":", 1)[-1]).stem
                if kartka in kartky_kanonu:
                    dodaty((_n(m.group(1)), _n(m.group(2)), _n(m.group(3))), int(s.group(1)), kartka)
    return out


def storinka_v_kanoni(shifra: str, storinka: Any,
                      indeks: dict[tuple[str, str, str, int], set[str]]) -> list[str]:
    m = _SHYFR.search(shifra or "")
    s = re.search(r"(\d+)\D*$", str(storinka or ""))
    if not (m and s):
        return []
    return sorted(indeks.get((_n(m.group(1)), _n(m.group(2)), _n(m.group(3)), int(s.group(1))), ()))


def arkushi_v_obliku(shifra: str) -> dict[int, str]:
    """Сторінка → коротко, що про аркуш уже записано у сховищі сторінок («partial 25.10:
    Китраръ, Лесникъ»). 04.11.2026 кадр ревізії повертали з FamilySearch, хоча аркуш
    стояв в обліку з 25.10 з переліком прізвищ."""
    from nyshporka.pagestore import store as PS

    try:
        cf = PS.load_case(PS.resolve_case(shifra))
    except Exception:      # справа не з цього простору чи не розпізнана — обліку немає
        return {}
    out: dict[int, str] = {}
    for scan, note in ((cf.pages if cf else None) or {}).items():
        s = re.search(r"(\d+)\D*$", Path(str(scan)).stem)
        if not s:
            continue
        prizv = ", ".join(list(getattr(note, "surnames", None) or [])[:3])
        koly = str(getattr(note, "noted", "") or "")[5:10]
        out[int(s.group(1))] = (f"{getattr(note, 'status', '')} {koly}".strip()
                                + (f": {prizv}" if prizv else ""))
    return out


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


def tekst_kartky(n: int, k: dict[str, Any], kanon: list[str],
                 storinky: dict[tuple[str, str, str, int], set[str]] | None = None,
                 oblik: dict[int, str] | None = None) -> str:
    """Картка текстом. На рядку: `@N` — номер рядка сторінки; `⟨…⟩` — той самий рядок
    іншим голосом; `CANON-PAGE:` — сторінку вже має канон (цитата, кроп чи маніфест);
    `SEEN:` — що про сторінку вже є у сховищі сторінок."""
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
        riadok = f"@{rd['row']}" if rd.get("row") is not None else ""
        inshi = [str(x)[:80] for x in rd.get("readings") or []]
        dod = f" ⟨{' | '.join(inshi)}⟩" if inshi else ""
        vk = storinka_v_kanoni(str(b.get("shifra") or ""), rd.get("page"), storinky or {})
        if vk:
            dod += f" | CANON-PAGE: {','.join(vk[:4])}"
        s = re.search(r"(\d+)\D*$", str(rd.get("page") or ""))
        if oblik and s and int(s.group(1)) in oblik:
            dod += f" | SEEN: {oblik[int(s.group(1))][:80]}"
        out.append(f"- g{ids[0] if ids else '?'}{dali} ×{rd.get('times')} p{rd.get('page')}{riadok}:"
                   f"{pered} {str(rd.get('line') or '')[:120]}{dod}")
    reshta = max(0, len(riadky) - RIADKIV) + int(k.get("more_lines") or 0)
    if reshta:
        out.append(f"- … ще рядків: {reshta}")
    return "\n".join(out)


def porcii(fayl: Path, *, kanon: Path | None, porciia: int = PORTSIIA, vid: int = 0,
           do: Path | None = None, manifest: Path | None = None,
           oblik: bool = True) -> dict[str, Any]:
    """Картки текстом. Без `do` — одна порція з картки `vid`; з `do` — усі порції файлами
    `porciia_<n>.md`. Номери карток (`K<n>`) — за порядком у файлі, тож однакові в обох."""
    shapka, kartky = prochytaty(fayl)
    indeks = indeks_kanonu(kanon) if kanon is not None else {}
    storinky = indeks_storinok(kanon, manifest) if kanon is not None else {}
    teksty = [tekst_kartky(i, k, u_kanoni(str(k["book"].get("shifra") or ""), indeks), storinky,
                           arkushi_v_obliku(str(k["book"].get("shifra") or "")) if oblik else None)
              for i, k in enumerate(kartky)]
    v_kanoni = sum(1 for t in teksty if " | CANON: " in t.split("\n", 1)[0])
    zahal = {"kartok": len(kartky), "v_kanoni": v_kanoni, "kanon": kanon is not None,
             "riadkiv_storinka_v_kanoni": sum(t.count(" | CANON-PAGE: ") for t in teksty),
             "riadkiv_arkush_v_obliku": sum(t.count(" | SEEN: ") for t in teksty),
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
