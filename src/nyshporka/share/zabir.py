"""Забрати результат свого виклику операції Супряги: архіви файлів зі sha256.

Сервер (`/m/vyklyky/<id>/rezultat`) дає перелік архівів: ім'я, розмір,
коротку адресу й sha256 КОЖНОГО файла всередині, а також паспорт — звідки
файли. Клієнт не знає, звідки вони взялися, і не вирішує нічого: качає
архів, розпаковує лише перелічені імена, звіряє кожен файл і лише тоді кладе
його в теку. Після цього каже серверу «забрано», і той прибирає архів зі
сховища.

🔴 Адреса архіву — НЕ пул: вона веде в сховище й живе годину, тож ключ
Супряги туди не йде (`catalog._fetcher` дає ключ лише довіреній адресі), а
прострочена адреса — привід перепитати перелік, а не помилка.

🔴 Архів і імена в ньому — чужі. Ім'я файла береться лише з білого списку,
однаково безпечного на Windows і POSIX; файл, що вже лежить у теці з іншим
вмістом, не затирається; розмір архіву й кожного файла має стелю.
"""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.share import catalog as C

#: Скільки чекати між переглядами живого виклику (`--stezhyty`).
PAUZA_S = 60.0
ZHYVI = ("chekaie", "v_roboti")
PROVENANS = "_supriaha_vyklyk.json"
#: Ім'я файла з чужого архіву: латинка, цифри, `.`, `_`, `-`, з літери чи цифри.
_IMIA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
#: Імена-пристрої Windows: `NUL.jpg` там — не файл у теці, а пристрій.
_PRYSTROI = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})
#: Найбільший файл в архіві: звичайний файл — одиниці мегабайтів, тож це вже явна вада.
FAYL_MAKS = 200 << 20
#: Стільки разів поспіль архів може не збігтися, перш ніж `--stezhyty` його облишить.
SPROB_ARKHIVU = 3
#: Стільки збоїв пулу поспіль (5xx, мережа) терпить `--stezhyty`.
ZBOIV_POSPIL = 10


def stan(vid: int, base: str = "") -> dict[str, Any]:
    return C._get(f"{C.base_url(base)}/m/vyklyky/{vid}")


def rezultat(vid: int, base: str = "") -> dict[str, Any]:
    return C._get(f"{C.base_url(base)}/m/vyklyky/{vid}/rezultat")


def pidtverdyty(vid: int, fayly: dict[str, str], base: str = "") -> dict[str, Any]:
    url = f"{C.base_url(base)}/m/vyklyky/{vid}/zabrano"
    resp = C._fetcher(url, accept_json=True).post(url, json_body={"fayly": fayly})
    try:
        return dict(json.loads(resp.text))
    except ValueError:
        raise C.PoolError("пул відповів на «забрано» не JSON") from None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def _ime_bezpechne(imia: str) -> bool:
    """Лише ім'я файла, безпечне й на Windows: без тек, дисків (`C:x`), потоків NTFS
    (`a:b`), пристроїв (`NUL`), кінцевої крапки; не службові імена самої теки."""
    return (bool(_IMIA.fullmatch(imia)) and not imia.endswith((".", ".part"))
            and imia.split(".")[0].upper() not in _PRYSTROI)


def vzhe_ye(teka: Path, fayly: dict[str, str]) -> bool:
    return all((teka / n).is_file() and sha256(teka / n) == s for n, s in fayly.items())


def rozpakuvaty(arkhiv: Path, teka: Path, fayly: dict[str, str]) -> tuple[int, list[str], list[str]]:
    """(скільки нових файлів покладено, які не збіглися, які зайняті іншим вмістом).

    Лише перелічені імена. Файл пишеться в `.part` і стає на місце лише зі збіглим
    sha256: обірваний чи підмінений файл під правильним іменем наступний запуск
    вважав би забраним. Файл, що вже лежить у теці з іншим вмістом (та сама тека
    для двох викликів), не затирається — це конфлікт, а не оновлення."""
    teka.mkdir(parents=True, exist_ok=True)
    novykh, khybni, konflikty = 0, [], []
    # лише tar без стиснення: «.tar» зі стисненням розпакувався б у будь-що
    with tarfile.open(arkhiv, "r:") as tf:
        for m in tf:
            if not m.isfile() or not _ime_bezpechne(m.name) or m.name not in fayly:
                continue
            ciel = teka / m.name
            if ciel.is_file():
                if sha256(ciel) != fayly[m.name]:
                    konflikty.append(m.name)
                continue
            dzherelo = tf.extractfile(m) if m.size <= FAYL_MAKS else None
            if dzherelo is None:
                khybni.append(m.name)
                continue
            chastyna = ciel.with_name(ciel.name + ".part")
            h = hashlib.sha256()
            with chastyna.open("wb") as out:
                while blok := dzherelo.read(1 << 20):
                    h.update(blok)
                    out.write(blok)
            if h.hexdigest() != fayly[m.name]:
                chastyna.unlink(missing_ok=True)
                khybni.append(m.name)
                continue
            chastyna.replace(ciel)
            novykh += 1
    brak = [n for n in fayly if not (teka / n).is_file() and n not in konflikty]
    return novykh, sorted(set(khybni) | set(brak)), sorted(konflikty)


def _zapysaty_provenans(teka: Path, vid: int, pasport: dict[str, Any],
                        fayly: dict[str, str]) -> None:
    p = teka / PROVENANS
    try:
        bulo = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bulo = {}
    bulo.update(vyklyk=vid, pasport=pasport, zabrano=datetime.now(UTC).isoformat(timespec="seconds"))
    bulo["fayly"] = {**(bulo.get("fayly") or {}), **fayly}
    p.write_text(json.dumps(bulo, ensure_ascii=False, indent=1), encoding="utf-8")


def _zbii(exc: Exception) -> bool:
    """Тимчасовий збій пулу (мережа, 5xx), який `--stezhyty` пересиджує."""
    status = getattr(exc, "status", None)
    return not isinstance(exc, C.PotribenKliuch) and (status is None or status >= 500)


def zabraty(vid: int, teka: Path, *, base: str = "", stezhyty: bool = False,
            pauza: float = PAUZA_S, sleep: Callable[[float], Any] = time.sleep,
            log: Callable[[str], Any] = lambda _s: None) -> dict[str, Any]:
    """Забрати все готове; з `stezhyty` — чекати, доки виклик не скінчиться."""
    from nyshporka.sources.http import Fetcher, HttpError, app_ua

    zvit: dict[str, Any] = {"teka": str(teka), "arkhiviv": 0, "novykh": 0, "fayliv": 0,
                            "ne_zbihlos": [], "konflikty": [], "pasport": None, "stan": None}
    kachalka = Fetcher(headers={"User-Agent": app_ua()}, attempts=3, retry_429=True)
    tymchasova = teka / ".zabir"
    nevdachi: dict[str, int] = {}
    zboiv = 0
    while True:
        try:
            v = stan(vid, base)
            zvit["stan"] = v.get("stan")
            if v.get("stan") not in (*ZHYVI, "hotovo", "skasovano"):
                zvit["vidmova"] = (v.get("vidpovid") or {}).get("pomylka") or v.get("stan")
                return zvit
            try:
                r = rezultat(vid, base)
            except C.PoolError as exc:
                if exc.status != 409:
                    raise
                if v.get("stan") not in ZHYVI:
                    zvit["vidmova"] = v.get("stan")  # скасоване, з якого не скачано нічого
                    return zvit
                if not stezhyty:
                    return zvit  # ще нічого не готово: `shche_ide`
                r = {"vyklyk": v, "rezultat": {"paky": [], "chekaie_paky": 1}}
        except (C.PoolError, HttpError) as exc:
            zboiv += 1
            if not stezhyty or not _zbii(exc) or zboiv >= ZBOIV_POSPIL:
                raise
            log(f"пул не відповів ({exc}) — чекаю")
            sleep(pauza)
            continue
        zboiv = 0
        rez = r.get("rezultat") or {}
        zvit["pasport"] = rez.get("pasport") or zvit["pasport"]
        ne_zbihlos: list[str] = []
        for n, paka in enumerate(rez.get("paky") or []):
            imia = str(paka.get("imia") or "")
            fayly = {str(k): str(s) for k, s in (paka.get("fayly") or {}).items()
                     if _ime_bezpechne(str(k))}
            if not fayly:
                continue
            if nevdachi.get(imia, 0) >= SPROB_ARKHIVU:
                ne_zbihlos += list(fayly)  # той самий архів не збігся кілька разів поспіль — облишити
                continue
            if not vzhe_ye(teka, fayly):
                if not paka.get("url"):
                    ne_zbihlos += list(fayly)
                    continue
                tymchasova.mkdir(parents=True, exist_ok=True)
                # ім'я тимчасового файла — своє: ім'я архіву від сервера могло б вивести за теку
                arkhiv = tymchasova / f"{n:04d}.tar"
                log(f"архів {imia}: {len(fayly)} файлів")
                _skachaty(kachalka, vid, base, paka, arkhiv)
                try:
                    novykh, khybni, konflikty = rozpakuvaty(arkhiv, teka, fayly)
                finally:
                    arkhiv.unlink(missing_ok=True)
                zvit["novykh"] += novykh
                zvit["konflikty"] = sorted(set(zvit["konflikty"]) | set(konflikty))
                if khybni or konflikty:
                    nevdachi[imia] = nevdachi.get(imia, 0) + 1
                    ne_zbihlos += khybni
                    continue  # «забрано» — лише для звіреного; архів лишається на сервері
            odp = pidtverdyty(vid, fayly, base)
            if odp.get("ne_zbihlos"):
                # сервер не впізнав хеші: архів у нього лишається, і людина має це бачити
                ne_zbihlos += [str(x) for x in odp["ne_zbihlos"]]
                continue
            zvit["arkhiviv"] += 1
            zvit["fayliv"] += len(fayly)
            _zapysaty_provenans(teka, vid, zvit["pasport"] or {}, fayly)
        zvit["ne_zbihlos"] = sorted(set(ne_zbihlos))
        if tymchasova.exists() and not any(tymchasova.iterdir()):
            tymchasova.rmdir()
        zhyvyi = (r.get("vyklyk") or v).get("stan") in ZHYVI
        if not stezhyty or (not zhyvyi and not rez.get("chekaie_paky")):
            return zvit
        sleep(pauza)


def _skachaty(kachalka: Any, vid: int, base: str, paka: dict[str, Any], arkhiv: Path) -> None:
    """Архів у файл зі стелею розміру; прострочена адреса — свіжа з переліку, один раз."""
    from nyshporka.sources.http import HttpError

    bajtiv = int(paka.get("bajtiv") or 0)
    stelia = bajtiv + (1 << 20) if bajtiv > 0 else len(paka.get("fayly") or {}) * FAYL_MAKS
    try:
        kachalka.download(str(paka["url"]), arkhiv, max_bytes=stelia)
        return
    except HttpError as exc:
        if getattr(exc, "status", None) not in (401, 403):
            raise
    # адреса живе годину: перепитати перелік і взяти свіжу адресу того самого архіву
    svizha = next((p for p in ((rezultat(vid, base).get("rezultat") or {}).get("paky") or [])
                   if p.get("imia") == paka.get("imia") and p.get("url")), None)
    if svizha is None:
        raise C.PoolError(f"архіву {paka.get('imia')} у переліку вже немає")
    kachalka.download(str(svizha["url"]), arkhiv, max_bytes=stelia)
