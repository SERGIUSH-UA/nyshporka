"""Розкласти забрані кадри плівки на справи за картою, яку дав сервер.

Плівка зазвичай несе кілька справ. Сервер кладе їхні межі в паспорт виклику
(`pasport.spravy`: шифр і номери кадрів, що збігаються з іменами файлів), тож читати
картки зйомки не треба. Сама розкладка — `nysh cases split`: тут лише карта для неї,
і все, що той уміє, діє й тут: кадри не переміщуються, є журнал і `--undo`.

🔴 Забране не псується. Будь-який сумнів лишає кадри цілою текою, а причина йде в
звіт: кадри вже в людини, і другий раз за них платити не можна. Тому `rozklasty` нічого
не кидає назовні.

🔴 Архів не вгадується. Шифр із джерела часто голий (`224-1-53`), а той самий номер є
в багатьох архівах. Сервер назвав архів, який знає пак, — добре; ні — кажемо людині
назвати його, і тека чекає: текст, покладений під чужий архів, гірший за збірну теку.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from nyshporka.share.zabir import PROVENANS

#: Лише фонд-опис-справа. Рядок на кшталт `Volume 211-2/381 (cont` парсер шифр витягнув би
#: сам, і вгаданий номер ліг би в реєстр як факт.
_FORMA = re.compile(r"\w+(-\w+){2,3}")
#: Роки в кінці шифру джерела: `_1851`, `_1850-1852`, `_ca. 1873–ca. 1873`.
_ROKY = re.compile(r"_(ca\.\s*)?\d{4}([-–](ca\.\s*)?\d{4})?$")


def _spravy(teka: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        dani = json.loads((teka / PROVENANS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    pasport = dani.get("pasport") if isinstance(dani, dict) else None
    pasport = pasport if isinstance(pasport, dict) else {}
    spravy = pasport.get("spravy")
    return ([s for s in spravy if isinstance(s, dict)] if isinstance(spravy, list) else []), pasport


def _imia(nomer: int) -> str:
    return f"{nomer:04d}.jpg"


def _arkhiv(spravy: list[dict[str, Any]], nazvanyi: str) -> str:
    """Канонічний код архіву: названий людиною, інакше з джерела, якщо пак його знає."""
    from nyshporka.cases import register as REG

    if nazvanyi.strip():
        return REG._repo_of_word(nazvanyi.strip())
    kody = {REG._repo_of_word(chastyna.strip())
            for s in spravy for chastyna in str(s.get("arkhiv") or "").split("|") if chastyna.strip()}
    kody.discard("")
    return kody.pop() if len(kody) == 1 else ""


def shifr_iz_dzherela(ref: str) -> str:
    """Шифр джерела → фонд-опис-справа: `246-1-122_1851`, `2_8_2453`, `132-1- 4018`.

    Роки живуть у паспорті, а не в шифрі. Простий поділ за `_` зробив би з `2_8_2453` шифр `2`."""
    s = re.sub(r"\s*-\s*", "-", ref.strip())
    return s.replace("_", "-") if re.fullmatch(r"\d+_\d+_\w+", s) else _ROKY.sub("", s)


def karta(spravy: list[dict[str, Any]], imena: list[str], arkhiv: str) -> list[tuple[str, str, str]]:
    """Карта для `cases.split`. Кадри поза справами йдуть у `-`: це обкладинки плівки."""
    from nyshporka.cases.split import LEFTOVER

    specs: list[tuple[str, str, str]] = []
    pozytsiia = 0
    poriadok = sorted(imena)
    for s in sorted(spravy, key=lambda x: int(x["vid"])):
        pershyi, ostannii = _imia(int(s["vid"])), _imia(int(s["do"]))
        a, b = poriadok.index(pershyi), poriadok.index(ostannii)
        if a > pozytsiia:
            specs.append((LEFTOVER, poriadok[pozytsiia], poriadok[a - 1]))
        specs.append((f"{arkhiv} {shifr_iz_dzherela(str(s['shifr']))}", pershyi, ostannii))
        pozytsiia = b + 1
    if pozytsiia < len(poriadok):
        specs.append((LEFTOVER, poriadok[pozytsiia], poriadok[-1]))
    return specs


def _opys(s: dict[str, Any]) -> dict[str, Any]:
    return {"title": str(s.get("nazva") or ""), "place": str(s.get("misce") or ""),
            "year_from": str(s.get("rik_vid") or ""), "year_to": str(s.get("rik_do") or "")}


def _kopiiuvaty(teka: Path) -> bool:
    """Жорстке посилання не перетинає том: тоді кадри копіюються."""
    from nyshporka.core.workspace import workspace

    return os.stat(teka).st_dev != os.stat(workspace().hub).st_dev


def _dzherelo(d: Path, pasport: dict[str, Any]) -> None:
    """Звідки кадри: людина мусить мати чим процитувати знайдене."""
    side = d / "_source.json"
    meta = json.loads(side.read_text(encoding="utf-8"))
    meta.update(fetched_from=str(pasport.get("source") or ""), fetched_url=str(pasport.get("url") or ""))
    side.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _odna_na_mistse(d: Path, shifra: str, imena: list[str]) -> tuple[Path, str]:
    """Куди лягає єдина справа: теку поза простором облік не бачить, тож кадри йдуть у теку
    справи жорсткими посиланнями, як і в розкладці. Там уже лежать кадри цієї справи з іншої
    плівки: нічого не змішуємо, тека лишається, а людина зводить їх сама."""
    from nyshporka.cases import register as REG
    from nyshporka.cases import take

    if REG.reachable(d):
        return d, ""
    sh = REG.parse_shifra(shifra)
    tsil = take.case_dir_for(sh.repo, sh.fond, sh.spr, "", sh.opys or "")
    if tsil.is_dir() and any(tsil.glob("*.jpg")):
        return d, (f"справа вже має кадри в {tsil}: можливо, вона розірвана між плівками. "
                   f"Нічого не змішано; звести: nysh cases join")
    tsil.mkdir(parents=True, exist_ok=True)
    kopiia = _kopiiuvaty(d)
    for imia in [*imena, PROVENANS]:
        if kopiia:
            shutil.copy2(d / imia, tsil / imia)
        else:
            os.link(d / imia, tsil / imia)
    return tsil, ""


def _vidmova(stan: str, prychyna: str, **rest: Any) -> dict[str, Any]:
    return {"stan": stan, "prychyna": prychyna, "spravy": [], **rest}


def rozklasty(teka: str | Path, arkhiv: str = "", *, dry_run: bool = False) -> dict[str, Any]:
    """Розкласти теку забраного виклику. Стани: `nemaie` (карти немає, нічого робити),
    `rozkladeno`, `odna` (одна справа, тека лишилась), `vzhe`, `potriben_arkhiv`, `ne_mozhna`,
    `plan` (`dry_run`)."""
    from nyshporka.cases import register as REG
    from nyshporka.cases import split as SPL

    # Абсолютна зразу: `--do zb/x` рахується від поточної теки, а `cases.split` — від простору.
    d = Path(teka).resolve()
    spravy, pasport = _spravy(d)
    if not spravy:
        return _vidmova("nemaie", "сервер не назвав справ на цій плівці")
    if SPL._read_journal(d / SPL.JOURNAL).get("state") == "done":
        return _vidmova("vzhe", f"теку вже розкладено; зняти: nysh cases split \"{d}\" --undo")
    try:
        neповні = [str(s.get("shifr")) for s in spravy if not s.get("povna")]
        if neповні:
            return _vidmova("ne_mozhna", f"забрано лише частину справ {', '.join(neповні)}: "
                                         "тека лишається цілою")
        imena = sorted(p.name for p in d.glob("*.jpg"))
        brak = [_imia(n) for s in spravy for n in range(int(s["vid"]), int(s["do"]) + 1)
                if _imia(n) not in imena]
        if brak:
            return _vidmova("ne_mozhna", f"бракує {len(brak)} кадрів, перший {brak[0]}: "
                                         "спершу доберіть, потім nysh share rozklasty")
        kod = _arkhiv(spravy, arkhiv)
        if arkhiv.strip() and not kod:
            return _vidmova("ne_mozhna", f"архіву «{arkhiv}» пак не знає")
        if not kod:
            return _vidmova(
                "potriben_arkhiv",
                f"шифр без архіву: справ {len(spravy)}, кадри лежать цілою текою. "
                f"Назвіть архів: nysh share rozklasty \"{d}\" --arkhiv <архів>",
                shyfry=[str(s.get("shifr")) for s in spravy])
        syri = [str(s.get("shifr")) for s in spravy
                if not _FORMA.fullmatch(shifr_iz_dzherela(str(s.get("shifr"))))]
        if syri:
            return _vidmova("ne_mozhna", f"джерело дало не шифр, а опис: «{syri[0]}». "
                                         "Тека лишається цілою; опишіть її: nysh case")
        specs = karta(spravy, imena, kod)
        dgs = str(pasport.get("dgs") or "")
        if len(spravy) == 1 and len(specs) == 1:
            if dry_run:
                return {"stan": "plan", "prychyna": "", "spravy": [specs[0][0]]}
            tsil, poperedzhennia = _odna_na_mistse(d, specs[0][0], imena)
            REG.describe(tsil, shifra=specs[0][0], dgs=dgs, **_opys(spravy[0]))
            _dzherelo(tsil, pasport)
            return {"stan": "odna", "prychyna": poperedzhennia,
                    "spravy": [{"shifra": REG.parse_shifra(specs[0][0]).as_text(), "teka": str(tsil),
                                "kadriv": len(imena)}]}
        if dry_run:
            pl = SPL.plan(d, specs)
            return {"stan": "plan", "prychyna": "",
                    "spravy": [p.shifra for p in pl.parts if p.shifra]}
        REG.describe(d, film=f"група {dgs}", dgs=dgs)
        _dzherelo(d, pasport)  # `cases.split` перенесе це в паспорт кожної справи
        zroblene = SPL.split(d, specs, copy=_kopiiuvaty(d))
        chastyny = [p for p in zroblene["parts"] if p.get("shifra")]
        vykhid = []
        for s, p in zip(sorted(spravy, key=lambda x: int(x["vid"])), chastyny, strict=True):
            REG.describe(p["dir"], **_opys(s))
            vykhid.append({"shifra": p.get("shifra"), "teka": p.get("dir"), "kadriv": int(s["kadriv"])})
        return {"stan": "rozkladeno", "prychyna": "", "spravy": vykhid}
    except (SPL.SplitError, REG.RegisterError, OSError, ValueError, KeyError, TypeError) as exc:
        return _vidmova("ne_mozhna", f"{type(exc).__name__}: {exc}: кадри лишаються цілою текою")
