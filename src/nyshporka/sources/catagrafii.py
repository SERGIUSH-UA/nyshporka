"""📜 Катаграфії Бессарабії — покажчик «село → справа ANRM ф.134 оп.2 → плівка FS».

Волонтерський покажчик (`index-moldova-revision-lists.github.io`, CC0) до опису 2
фонду 134 «Бессарабська казенна палата» Національного архіву Молдови:
ревізькі казки й поіменні списки 1824-1886. Один рядок — одне село всередині
справи, з аркушами за описом; справа — з плівкою FamilySearch і кадрами на ній.

🔑 **Головна користь — плівка.** Опис архіву називає справу й аркуші, а на якій
плівці FS вона знята й з якого кадру починається, знає лише людина, що плівки
прогорнула. Плівки цього фонду майже всі лежать на вільному дзеркалі
(`fsfilm`, регіон `moldova`), тож за номером плівки справа береться без сесії
FS і без замовлення в архіві. Покажчик самого дзеркала по ф.134 тримає лише
частину справ, і «немає в покажчику дзеркала» там не означає «немає плівки».

🪤 **Катаграфії розкладено за СТАНАМИ**, не за селами: царани, мазили, рупташі,
духовенство, однодворці, міщани — окремими справами. Одне село лежить у
кількох справах того самого року, і шукати треба всі.

🪤 **Аркуш — не кадр.** Кадри покажчик здебільшого дає на всю справу; село
всередині неї шукається за олівцевим номером аркуша в куті сторінки. Кадр села
(`image`) є лише в частини рядків і рахується всередині тому FS, а не по
плівці дзеркала.

Дані — статичні CSV сайту, без ключа; обхід бере їх цілком і кладе в знімок
простору дослівно, тож sha256 знімка збігається з файлами сайту.

Адресація (`ref`): `cat:<справа>` — справа; `cat:<справа>:<том>:<аркуш>` — рядок
села.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.sources.base import Hit, SourceAbout, SourceError, SourceScope
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline
from nyshporka.utils.atomic import atomic_write_bytes
from nyshporka.utils.translit import normalize_for_matching

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://index-moldova-revision-lists.github.io"
#: Файли сайту: ім'я в знімку → шлях на сайті.
FILES = {"dossiers.csv": "/data/dossiers.csv",
         "lignes.csv": "/data/lignes.csv",
         "DICTIONNAIRE.md": "/data/DICTIONNAIRE.md"}

#: Поля, без яких розбір не має сенсу. Решта — як прийшли.
DOSSIER_FIELDS = ("dosar", "year_from", "year_to", "title_ro", "title_ru", "county",
                  "villages", "microfilm", "image_range", "image_count", "confidence",
                  "familysearch_url", "inventory_page")
LINE_FIELDS = ("dosar", "volume", "prefix", "village", "village_ru", "county",
               "folios", "folio_from", "folio_to", "microfilm", "image_range",
               "image_count", "confidence", "image", "familysearch_url")

#: Регіон дзеркала плівок, де лежать плівки фонду.
MIRROR_REGION = "moldova"

#: Як покажчик встановив межі справи на плівці — словами для людини.
#: 🔴 Словник сайту просить не подавати поле як імовірність: це метод, а не
#: відсоток, і так воно тут і названо.
HOW = {"exacte": "", "certain": "", "sur": "",
       "probable": "межі виведено з сусідніх справ плівки",
       "deduit": "межі виведено з сусідніх справ плівки",
       "estime": "межі оцінено інтерполяцією — початок і кінець звіряти карткою "
                 "справи на плівці",
       "volum": "плівку знайдено, межі справи в ній — ні",
       "incertain": "межі непевні"}

#: «Generated: 812 archival files, 9725 inventory lines» у словнику сайту.
_DECLARED = re.compile(r"Generated:\s*([\d\s,]+)\s*archival files,\s*([\d\s,]+)\s*"
                       r"inventory lines", re.I)
_YEAR = re.compile(r"1[6-9]\d\d")
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
          "IX": 9, "X": 10}

#: Румунські літери, які мусять злитися з кириличною передачею ДО загальної
#: нормалізації: â та î — одна літера двома правописами (опис їх і плутає),
#: ţ — це «ц», а не «т».
_PRE = str.maketrans({"â": "î", "Â": "Î", "ţ": "ц", "ț": "ц", "Ţ": "Ц", "Ț": "Ц"})
#: Пари, які плутає сам опис: tz/ţ, gh/g, ch/k, k/c, w/v; і j румунське — це ж.
_PAIRS = (("tz", "c"), ("gh", "g"), ("ch", "c"), ("k", "c"), ("w", "v"),
          ("y", "i"), ("j", "z"))


def _flat(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def safe_url(value: object) -> str:
    """Посилання з чужих даних — лише http(s): рядок іде в `href` консолі."""
    s = _flat(value)
    return s if s.lower().startswith(("http://", "https://")) else ""


def skeleton(s: str) -> str:
    """Назва → форма для збігу підрядком, спільна для румунської й кирилиці.

    «Beşghioz» і «Besgioz», «Sângerei» і «Sîngerei», «Ţahnăuţi» і «Цахнэуць»
    дають одне й те саме. Порядок значущий: румунські літери зводяться до
    загальної нормалізації, бо після неї «ţ» уже не відрізнити від «t».
    """
    t = normalize_for_matching(_flat(s).translate(_PRE))
    for a, b in _PAIRS:
        t = t.replace(a, b)
    return t


def consonants(s: str) -> str:
    """Приголосний кістяк назви: для «схожого написання», не для збігу.

    🔴 Навіщо. Російська передача в покажчику — фонетична з румунської
    («Бравича»), а дослідник приходить з історичною назвою з метрик і
    довідників («Бравичи»); румунське «ău» звучить як «ов» («-ăuca» = «-овка»).
    Голосні тут розходяться, приголосні — ні. Тому голосні знімаються, а «u»
    після голосної стає «v».

    Кістяк дає хибні збіги («Шеркани» ↔ «Soroceni»), і тому він — лише другий
    щабель: питається, коли збігу підрядком немає, і кожна така знахідка
    підписана як схоже написання.
    """
    t = skeleton(s)
    t = re.sub(r"(?<=[aeiou])u", "v", t)
    t = re.sub(r"[aeiou\W\d_]", "", t)
    return re.sub(r"(.)\1+", r"\1", t)


def _tokens(s: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", s)


def reels(films: str, ranges: str) -> list[tuple[str, str]]:
    """«2359501 · 2359502» + «61–1055 · 5–720» → [(плівка, «61-1055»), …].

    Справа буває на двох плівках, а то й двома шматками однієї («2360600 ·
    2360600»), тож пари йдуть за позицією, а не за номером.
    """
    fs = [x.strip() for x in (films or "").split("·") if x.strip()]
    rs = [x.strip().replace("–", "-").replace("—", "-") for x in (ranges or "").split("·")]
    return [(f, rs[i] if i < len(rs) else "") for i, f in enumerate(fs)]


def _vol_order(v: str) -> int:
    return _ROMAN.get(v.strip().upper(), 0 if not v.strip() else 99)


def _int(s: object) -> int | None:
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else None


@lru_cache(maxsize=2)
def _load(folder: Path, stamp: tuple[int, int, int, int]
          ) -> tuple[dict[str, dict[str, str]], tuple[dict[str, str], ...]]:
    """(справи за номером, рядки сіл) зі знімка. Ключ — штампи обох файлів."""
    _ = stamp
    with (folder / "dossiers.csv").open(encoding="utf-8", newline="") as fh:
        dossiers = {r["dosar"].strip(): r for r in csv.DictReader(fh)}
    with (folder / "lignes.csv").open(encoding="utf-8", newline="") as fh:
        lines = tuple(csv.DictReader(fh))
    return dossiers, lines


@lru_cache(maxsize=2)
def _hay(folder: Path, stamp: tuple[int, int, int, int]
         ) -> tuple[tuple[str, frozenset[str]], ...]:
    """Для кожного рядка: кістяк обох написань і множина приголосних кістяків слів."""
    _, lines = _load(folder, stamp)
    out = []
    for r in lines:
        both = f"{r.get('village', '')} {r.get('village_ru', '')}"
        out.append((skeleton(both),
                    frozenset(c for c in map(consonants, _tokens(both)) if c)))
    return tuple(out)


@lru_cache(maxsize=2)
def _film_paths(blob: Path, mtime_ns: int, size: int) -> dict[str, str]:
    """Номер плівки → шлях її теки в дереві регіону дзеркала."""
    from nyshporka.sources.fsfilm import _decode_tree

    _ = (mtime_ns, size)
    out: dict[str, str] = {}
    for key, node in _decode_tree(blob).items():
        if not isinstance(node, dict) or not node.get("files"):
            continue
        last = key.rstrip("/").rsplit("/", 1)[-1]
        if last.isdigit():
            out.setdefault(last, key.rstrip("/"))
    return out


def check(dossiers: list[dict[str, str]], lines: list[dict[str, str]],
          dictionary: str = "") -> tuple[list[str], dict[str, int] | None]:
    """Приймач повноти знімка: (вади, оголошені сайтом числа).

    🔴 Три звірки, і жодна не вимагає довіри до самих чисел файлу. Кожен рядок
    села мусить належати відомій справі; число сіл, яке справа оголошує
    (`villages`), мусить дорівнювати числу її рядків — так обрізаний будь-який
    з двох файлів видно одразу; і, коли словник сайту називає загальні числа,
    вони мусять збігтися з файлами.
    """
    bad: list[str] = []
    for name, rows, need in (("dossiers.csv", dossiers, DOSSIER_FIELDS),
                             ("lignes.csv", lines, LINE_FIELDS)):
        missing = [f for f in need if rows and f not in rows[0]]
        if not rows:
            bad.append(f"{name} порожній")
        elif missing:
            bad.append(f"у {name} немає колонок {', '.join(missing)} — формат змінився")
    if bad:
        return bad, None
    known = {r["dosar"].strip() for r in dossiers}
    orphans = sorted({r["dosar"].strip() for r in lines} - known)
    if orphans:
        bad.append(f"рядки сіл без справи: {', '.join(orphans[:10])}")
    per = Counter(r["dosar"].strip() for r in lines)
    short = [f"спр.{d['dosar']}: {per.get(d['dosar'].strip(), 0)} з {d['villages']}"
             for d in dossiers
             if (d.get("villages") or "").strip().isdigit()
             and int(d["villages"]) != per.get(d["dosar"].strip(), 0)]
    if short:
        bad.append(f"справи, де сіл менше чи більше, ніж оголошено ({len(short)}): "
                   + "; ".join(short[:8]))
    declared = None
    m = _DECLARED.search(dictionary or "")
    if m:
        declared = {"dossiers": int(re.sub(r"\D", "", m.group(1))),
                    "lines": int(re.sub(r"\D", "", m.group(2)))}
        if declared != {"dossiers": len(dossiers), "lines": len(lines)}:
            bad.append(f"словник сайту оголошує справ {declared['dossiers']} і рядків "
                       f"{declared['lines']}, а у файлах {len(dossiers)} і {len(lines)}")
    return bad, declared


class CatagrafiiSource:
    """Покажчик катаграфій ANRM ф.134 оп.2 за селом і за шифрою справи."""

    id = "catagrafii"
    label = "Катаграфії Бессарабії (ревізькі казки ANRM ф.134 за селом)"
    caps = frozenset({"search", "address"})
    about = SourceAbout(
        answers="в якій справі ревізьких казок Бессарабії лежить моє село, на яких "
                "аркушах і на якій плівці FamilySearch",
        gives="справу ANRM ф.134 оп.2 (стан, повіт, рік), аркуші села за описом, "
              "плівку FS і кадри справи на ній, посилання на переглядач FS; адресу "
              "плівки на дзеркалі `fsfilm`, коли дерево регіону в кеші",
        not_gives="імен людей (це покажчик місць, не осіб); метрик (ANRM ф.211); "
                  "кадру села на плівці — кадри здебільшого на всю справу",
        where_class="ревізії, однодворчі списки, волосні правління",
        # Заміряно по знімку 10.10.2026: 812 справ, 9725 рядків сіл, роки
        # 1824-1886; плівку мають 786 справ, з них 246 — на двох плівках; усі
        # 306 плівок є на дзеркалі `fsfilm` (регіон moldova).
        scope=SourceScope(archives=("ANRM",), countries=("MD",), years=(1824, 1886),
                          note="ANRM ф.134 оп.2 — катаграфії Бессарабії, "
                               "розкладені за станами"),
        match_on=("settlement",), match_how="normalized",
        zero_means="у знімку (дата в `basis`) немає рядка опису з такою назвою села "
                   "ні румунською, ні в російській передачі, ні схожого написання; "
                   "опис буває неповним, а село — записаним під іменем маєтку чи "
                   "сусіднього села",
        pitfalls=("без знімка відмовляє: зібрати `nysh crawl catagrafii`",
                  "одне село лежить у кількох справах: катаграфії розкладено за "
                  "станами (царани, мазили, рупташі, духовенство) — дивитись усі",
                  "аркуш — не кадр: кадри здебільшого на всю справу, село шукати "
                  "за олівцевим номером аркуша в куті сторінки",
                  "кадр села в переглядачі FS рахується в томі FS, а не по плівці "
                  "дзеркала",
                  "межа справи, оцінена інтерполяцією, розходиться з плівкою на "
                  "десятки кадрів — звіряти карткою справи",
                  "російська передача фонетична з румунської («Бравича»), а не "
                  "історична («Бравичи»): історична назва знаходиться як схоже "
                  "написання"))

    SNAP_REL = Path("data") / "raw" / "catagrafii" / "_crawl"
    STATE = "state.json"

    NO_CATALOG = (
        "знімка покажчика катаграфій у просторі немає — нуль звідси нічого б не "
        "означав. Зібрати: `nysh crawl catagrafii` (3 запити, ~2 МБ).")

    def __init__(self, workspace: Path | None = None, *,
                 http: Fetcher | None = None) -> None:
        """`http` — двійник сайту в тестах."""
        self.workspace = Path(workspace) if workspace else None
        self._http = http

    # ── знімок ───────────────────────────────────────────────────────────────

    @property
    def snap_dir(self) -> Path | None:
        return (self.workspace / self.SNAP_REL) if self.workspace else None

    def _stamp(self) -> tuple[int, int, int, int] | None:
        d = self.snap_dir
        if d is None:
            return None
        try:
            a, b = (d / "dossiers.csv").stat(), (d / "lignes.csv").stat()
        except OSError:
            return None
        return (a.st_mtime_ns, a.st_size, b.st_mtime_ns, b.st_size)

    def _read_state(self) -> dict[str, Any]:
        d = self.snap_dir
        if d is None:
            return {}
        try:
            data = json.loads((d / self.STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        stamp = self._stamp()
        if stamp is None or self.snap_dir is None:
            return "none", {}
        dossiers, lines = _load(self.snap_dir, stamp)
        state = self._read_state()
        return "workspace", {
            "path": str(self.snap_dir), "rows": len(lines), "cases": len(dossiers),
            "taken": state.get("taken") or _dt.date.fromtimestamp(
                stamp[2] / 1e9).isoformat(),
            "scope": "ANRM ф.134 оп.2, село → справа → плівка"}

    def _data(self) -> tuple[dict[str, dict[str, str]], tuple[dict[str, str], ...],
                             tuple[int, int, int, int]]:
        stamp = self._stamp()
        if stamp is None or self.snap_dir is None:
            raise SourceError(self.NO_CATALOG)
        dossiers, lines = _load(self.snap_dir, stamp)
        return dossiers, lines, stamp

    def dossiers(self) -> dict[str, dict[str, str]]:
        """Справи знімка за номером. Без знімка — `SourceError` з командою обходу."""
        return self._data()[0]

    def _mirror(self) -> tuple[dict[str, str], str]:
        """(плівка → шлях на дзеркалі, дата дерева) — лише з кешу, без мережі.

        Порожньо, коли дерева регіону в кеші немає: тоді про дзеркало нічого не
        стверджується, а не «плівки немає».
        """
        if self.workspace is None:
            return {}, ""
        from nyshporka.sources.fsfilm import FilmMirrorSource

        blob = self.workspace / FilmMirrorSource.CACHE_REL / f"{MIRROR_REGION}.json.gz"
        try:
            st = blob.stat()
        except OSError:
            return {}, ""
        if not st.st_size:
            return {}, ""
        try:
            paths = _film_paths(blob, st.st_mtime_ns, st.st_size)
        except (SourceError, OSError, ValueError, KeyError):
            return {}, ""
        return paths, _dt.date.fromtimestamp(st.st_mtime).isoformat()

    # ── пошук ────────────────────────────────────────────────────────────────

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Рядки сіл, де є всі слова запиту — у румунському написанні опису чи в
        російській передачі. Чотиризначне число в запиті — рік: лишаються справи,
        що його накривають.

        Два щаблі. Перший — підрядок після зведення румунської з кирилицею
        («Besgioz» знаходить «Beşghioz», «Трифешти» — «Trifeşti»). Другий
        питається, лише коли перший дав нуль: збіг приголосного кістяка слова
        («Бравичи» → «Bravicea»), і кожна така знахідка підписана як схоже
        написання — вирішує око.

        🔴 Кількість збігів їде в примітку, коли видачу обрізано.
        """
        words = _flat(q).split()
        years = [int(w) for w in words if _YEAR.fullmatch(w)]
        names = [w for w in words if not _YEAR.fullmatch(w)]
        if not names:
            return []
        dossiers, lines, stamp = self._data()
        assert self.snap_dir is not None
        hay = _hay(self.snap_dir, stamp)
        sk = [skeleton(w) for w in names]
        cs = [consonants(w) for w in names]

        def fits_year(r: dict[str, str]) -> bool:
            if not years:
                return True
            d = dossiers.get(r["dosar"].strip(), {})
            lo, hi = _int(d.get("year_from")), _int(d.get("year_to"))
            if lo is None:
                return True        # справа без років: не відкидати, рік не відомий
            return all(lo <= y <= (hi or lo) for y in years)

        exact = [i for i, (h, _c) in enumerate(hay)
                 if all(s and s in h for s in sk) and fits_year(lines[i])]
        near: list[int] = []
        if not exact:
            # Кістяк із двох приголосних («Томай» → «tm») ловить пів покажчика.
            near = [i for i, (h, c) in enumerate(hay)
                    if all((s and s in h) or (len(k) >= 3 and k in c)
                           for s, k in zip(sk, cs, strict=True))
                    and fits_year(lines[i])]
        found = exact or near
        found.sort(key=lambda i: (_int(lines[i]["dosar"]) or 0,
                                  _vol_order(lines[i].get("volume", "")),
                                  _int(lines[i].get("folio_from")) or 0))
        mirror = self._mirror()
        taken = self.catalog_source()[1].get("taken") or ""
        tail = f" · з {len(found)} за запитом" if len(found) > limit else ""
        return [self._line_hit(lines[i], dossiers, mirror, taken,
                               near=bool(near), tail=tail if n == 0 else "")
                for n, i in enumerate(found[:limit])]

    def find_case(self, fond: str, opys: str, spr: str, *, repo: str = "") -> list[Hit]:
        """Справа й усі її села за порядком томів і аркушів — відповідь на «що
        лежить у цій справі і на якій плівці».

        Покажчик знає лише ANRM ф.134 оп.2; будь-яка інша шифра — порожньо, а не
        здогад.
        """
        if repo and repo.upper() != "ANRM":
            return []
        if _int(fond) != 134 or (str(opys).strip() and _int(opys) != 2):
            return []
        num = _int(spr)
        if num is None or not str(spr).strip().isdigit():
            return []
        dossiers, lines, _stamp = self._data()
        d = dossiers.get(str(num))
        if d is None:
            return []
        mirror = self._mirror()
        taken = self.catalog_source()[1].get("taken") or ""
        rows = sorted((r for r in lines if r["dosar"].strip() == str(num)),
                      key=lambda r: (_vol_order(r.get("volume", "")),
                                     _int(r.get("folio_from")) or 0))
        return [self._case_hit(d, mirror, taken),
                *(self._line_hit(r, dossiers, mirror, taken) for r in rows)]

    # ── знахідки ─────────────────────────────────────────────────────────────

    @staticmethod
    def shifra(dosar: str) -> str:
        return f"ANRM 134-2-{dosar.strip()}"

    @staticmethod
    def _years(d: dict[str, str]) -> str:
        lo, hi = (d.get("year_from") or "").strip(), (d.get("year_to") or "").strip()
        return lo if not hi or hi == lo else f"{lo}-{hi}"

    @staticmethod
    def _reel_note(films: str, ranges: str, confidence: str,
                   mirror: tuple[dict[str, str], str], *, command: bool) -> str:
        """Плівки справи з кадрами, як встановлено межі, і де плівка на дзеркалі."""
        paths, tree_date = mirror
        parts: list[str] = []
        for film, rng in reels(films, ranges):
            s = f"плівка {film}" + (f", кадри {rng}" if rng else "")
            if paths:
                path = paths.get(film)
                if path is None:
                    s += f" (на дзеркалі {MIRROR_REGION} її немає, дерево від {tree_date})"
                elif command:
                    s += (f" — `nysh get fsfilm \"{MIRROR_REGION}/{path}\""
                          + (f" --frames {rng}" if re.fullmatch(r"\d+-\d+", rng) else "")
                          + " --out <тека>`")
                else:
                    s += f" — дзеркало `{MIRROR_REGION}/{path}`"
            parts.append(s)
        how = (confidence or "").strip()
        if parts and how:
            said = HOW.get(how, f"межі: {how}")
            if said:
                parts.append(said)
        return " · ".join(parts)

    def _case_hit(self, d: dict[str, str], mirror: tuple[dict[str, str], str],
                  taken: str) -> Hit:
        reel = self._reel_note(d.get("microfilm", ""), d.get("image_range", ""),
                               d.get("confidence", ""), mirror, command=True)
        no_tree = ("" if mirror[0] or not d.get("microfilm") else
                   f"дзеркало не звірено: дерева регіону {MIRROR_REGION} в кеші немає "
                   f"(`nysh browse fsfilm {MIRROR_REGION}`)")
        note = " · ".join(x for x in (
            f"сіл {d.get('villages')}" if d.get("villages") else "",
            reel or "плівки покажчик не знає",
            no_tree,
            f"опис ANRM с. {d.get('inventory_page')}" if d.get("inventory_page") else "",
            _flat(d.get("title_ru"))[:200],
            f"знімок від {taken}" if taken else "") if x)
        return Hit(
            source=self.id, ref=f"cat:{d['dosar'].strip()}",
            title=_flat(d.get("title_ro"))[:300], years=self._years(d),
            place=_flat(d.get("county")), shifra=self.shifra(d["dosar"]),
            frames=_int(d.get("image_count")), acquirable=False,
            note=note, url=safe_url(d.get("familysearch_url")),
            repo="ANRM", archive="ANRM", fond="134")

    def _line_hit(self, r: dict[str, str], dossiers: dict[str, dict[str, str]],
                  mirror: tuple[dict[str, str], str], taken: str, *,
                  near: bool = False, tail: str = "") -> Hit:
        dosar = r["dosar"].strip()
        d = dossiers.get(dosar, {})
        vol = (r.get("volume") or "").strip()
        own = bool((r.get("microfilm") or "").strip())
        reel = self._reel_note(
            (r if own else d).get("microfilm", ""), (r if own else d).get("image_range", ""),
            (r if own else d).get("confidence", ""), mirror, command=False)
        where = ("кадри села" if own else "кадри на всю справу") if reel else ""
        image = (r.get("image") or "").strip()
        note = " · ".join(x for x in (
            "≈ схоже написання, не збіг — звірити назву" if near else "",
            f"спр.{dosar}" + (f", т.{vol}" if vol else ""),
            f"{where}: {reel}" if reel else "плівки покажчик не знає",
            f"кадр села в переглядачі FS: {image} (рахунок у томі FS, не на плівці)"
            if image else "",
            _flat(d.get("title_ru"))[:120],
            f"знімок від {taken}" if taken else "") if x)
        name = " ".join(x for x in (_flat(r.get("prefix")), _flat(r.get("village"))) if x)
        ru = _flat(r.get("village_ru"))
        folios = _flat(r.get("folios"))
        title = name + (f" ({ru})" if ru else "") + (f" · арк. {folios}" if folios else "")
        place = " · ".join(x for x in (_flat(r.get("village")),
                                        _flat(r.get("county")) or _flat(d.get("county")))
                           if x)
        return Hit(
            source=self.id, ref=f"cat:{dosar}:{vol}:{_flat(r.get('folio_from'))}",
            title=title, years=self._years(d), place=place,
            shifra=self.shifra(dosar) + (f", т.{vol}" if vol else ""),
            frames=_int((r if own else d).get("image_count")), acquirable=False,
            note=(note + tail).strip(" ·"),
            url=safe_url(r.get("familysearch_url") or d.get("familysearch_url")),
            repo="ANRM", archive="ANRM", fond="134", page=_int(r.get("folio_from")))

    # ── обхід ────────────────────────────────────────────────────────────────

    def crawl(self, groups: tuple[str, ...] | None = None, *,
              on_progress: ProgressFn | None = None,
              resume: bool = True) -> dict[str, Any]:
        """Забрати покажчик цілком у знімок простору.

        `groups` і `resume` не мають сенсу: це три статичні файли.

        🔴 Знімок пишеться лише після приймача (`check`). Обрізаний файл
        виглядав би як повний покажчик, і нуль по ньому читався б як «села в
        описі немає». Файли лягають дослівно, тож їх sha256 у `state.json`
        збігається з файлами сайту на дату знімка.
        """
        _ = (groups, resume)
        if self.workspace is None or self.snap_dir is None:
            raise SourceError("для обходу потрібен робочий простір — знімок лягає в нього")
        if offline() and self._http is None:
            raise SourceError("мережу вимкнено в цьому середовищі — покажчик не опитано")
        http = self._http or Fetcher(base=HOST, headers={"User-Agent": app_ua()})
        got: dict[str, bytes] = {}
        for n, (name, path) in enumerate(FILES.items(), 1):
            try:
                body = http.get(path).content
            except (HttpError, OSError) as exc:
                raise SourceError(f"сайт покажчика не віддав {path}: {exc}") from exc
            got[name] = body if isinstance(body, bytes) else str(body).encode("utf-8")
            if on_progress:
                on_progress(done=n, total=len(FILES), unit="файл", note=name)
        try:
            dossiers = list(csv.DictReader(io.StringIO(got["dossiers.csv"].decode("utf-8-sig"))))
            lines = list(csv.DictReader(io.StringIO(got["lignes.csv"].decode("utf-8-sig"))))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise SourceError(f"файли покажчика не читаються як CSV: {exc}") from exc
        bad, declared = check(dossiers, lines, got["DICTIONNAIRE.md"].decode("utf-8", "replace"))
        if bad:
            raise SourceError("знімок не записано: " + "; ".join(bad))
        d = self.snap_dir
        for name, body in got.items():
            atomic_write_bytes(d / name, body)
        taken = _dt.date.today().isoformat()
        atomic_write_bytes(d / self.STATE, json.dumps({
            "taken": taken, "site": HOST, "license": "CC0-1.0",
            "dossiers": len(dossiers), "lines": len(lines), "declared": declared,
            "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in got.items()},
        }, ensure_ascii=False, indent=1).encode("utf-8"))
        films = sum(1 for x in dossiers if (x.get("microfilm") or "").strip())
        return {"summary": f"справ {len(dossiers)} · рядків сіл {len(lines)} · з "
                           f"плівкою {films} · знімок від {taken}",
                "rows": len(lines), "cases": len(dossiers)}
