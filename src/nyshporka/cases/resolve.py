r"""Прив'язка прогону до справи — чотири канали, перший успішний виграє.

🔴 Навіщо це окремий модуль, а не `join` по полю: **66 зі 189 HTR-прогонів не мають
робочого `case_dir`**. Хмарний прогін пише в мету шлях орендованого боксу
(`/tmp/htrcase/pages_dl` — 40+ прогонів), тимчасову теку стейджингу або
junction, який `dejunction()` не покриває. Тобто
третина всього декоду проєкту сьогодні «нічия», і без резолвера реєстр показав би
її як «декоду не було».

🔴 Ім'я прогону розбирається ЗВІРКОЮ З БІБЛІОТЕКОЮ, а не вгадуванням архіву. Прямо
поруч є ціна помилки: `clan_hunt.parse_case` вгадує ДАВО за формою імені, і дев'ять
справ ДАХмО ф.241 (`010241-01-00886`) записані в його реєстрі як ф.904 оп.24 —
звірка з каноном для них іде по неіснуючій справі, а нуль від бага не відрізнити
від чесного нуля. Тут кандидат приймається, лише якщо така справа **є в бібліотеці**
і збіг однозначний.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from nyshporka.cases.model import RunLink
from nyshporka.library import ROOT, _archium_parse, dejunction, load_library, parse_case_code
from nyshporka.utils.atomic import CorruptFileError, read_json, write_json

OVERRIDES_PATH = ROOT / "data" / "cases" / "overrides.json"

#: Суфікси похідних прогонів: другий голос, черга на око, рятувальний прохід,
#: проба версії. Такий прогін описує ТОЙ САМИЙ матеріал, що й базовий, тож
#: прив'язка успадковується (інакше `-diak_v4` половини справ лишились би нічиї).
_DERIVED_SUFFIXES = (
    "-review", "-rescue", "-queued", "-diak_v4", "-churro", "-parseq", "-test",
    "-skryba", "-probe", "-v5probe", "-v6probe",
)
#: Хвіст-версія моделі: `-pysar_cyr_v17`, `-skryba_f792_v6`, `-v12`, `-diak_v4`.
_MODEL_TAIL_RE = re.compile(
    r"-(?:pysar[_a-z]*|skryba[_a-z0-9]*|diak[_a-z]*|v\d+[a-z]*)$", re.IGNORECASE)

#: Число з можливим літерним томом: `7029a`, `206а`. Тому не `\d+`.
_NUM_RE = re.compile(r"(\d+[a-zа-яA-ZА-Я]?)")
#: Окремий токен-номер справи: 3+ цифри й необов'язковий літерний том. Саме
#: «окремий» і «3+» рятують від випадкової цифри в імені прогону (`t1`).
_SOLO_NUM_RE = re.compile(r"\d{3,}[a-zа-яA-ZА-Я]?")
#: Фонд, записаний як `f196` / `f904_op24`.
_FOND_TOKEN_RE = re.compile(r"^f(\d+)$", re.IGNORECASE)
#: Перший токен davo-стилю: `010904` → 904, `010241` → 241 (префікс `01` + фонд).
_DAVO_HEAD_RE = re.compile(r"^0+1?0*(\d{3,4})$")
#: Рік у діапазоні архівних справ — не номер справи.
_YEAR_LO, _YEAR_HI = 1500, 2100

#: Слово-архів у імені прогону → repo-код бібліотеки. Звужує кандидатів там, де
#: номер справи сам по собі неоднозначний (`178-51-418` є і в ДАЖО, і деінде).
_REPO_HINTS = {
    "dazho": "DAZHO", "dahmo": "DAHMO", "davo": "DAVO", "davio": "DAVO",
    "cdiak": "CDIAK", "anrm": "ANRM", "daoo": "DAOO", "kostel": "KOSTEL",
    "csamm": "CSAMM",
}
#: Жанрові префікси — не архіви й не номери: `spov1846`, `met1810`, `rev1854`.
_GENRE_PREFIXES = ("spov", "met", "rev", "rec", "posim", "kazky", "sud", "klir")

#: Сила опису справи — чим вона вища, тим більше про справу знає не лише ім'я теки.
#: Використовується для розв'язання дублікатів ключа (див. `LibraryIndex._pick`).
_DESC_RANK = {
    "canonical": 100, "davo_catalog": 90, "catalog_md": 90, "klirovi_index": 85,
    "source_json": 80, "meta_json": 75, "archium_catalog": 70, "fs_titleread": 65,
    "wikisource": 60, "opys_tsv": 50, "fs_master": 40, "code": 0,
}


def _norm(v: str | None) -> str | None:
    """`00114` → `114`, `7029A` → `7029a`. Порожнє → None."""
    if v is None:
        return None
    s = str(v).strip().lower().lstrip("0")
    return s or ("0" if str(v).strip() else None)


@dataclass(frozen=True)
class _Cand:
    """Кандидат-шифра, здобутий з імені прогону."""

    fond: str
    spr: str
    opys: str | None = None
    repo: str | None = None


class LibraryIndex:
    """Індекси бібліотеки для звірки кандидатів (fond/opys/spr, шлях, ключ)."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else load_library()
        self.by_key: dict[str, dict[str, Any]] = {}
        self.by_path: dict[str, str] = {}
        self._by_fos: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        self._by_fs: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        self._by_spr: dict[str, list[str]] = defaultdict(list)
        for e in self.rows:
            key = e.get("key")
            if not key:
                continue
            self.by_key[key] = e
            for p in (e.get("path"), e.get("raw_path"), *(e.get("extra_paths") or [])):
                if p:
                    self.by_path[str(p).replace("\\", "/").rstrip("/")] = key
            fond, opys, spr = (_norm(e.get("fond")), _norm(e.get("opys")),
                               _norm(e.get("spr")))
            if not (fond and spr):
                continue
            if opys:
                self._by_fos[(fond, opys, spr)].append(key)
            self._by_fs[(fond, spr)].append(key)
            self._by_spr[spr].append(key)

    def _pick(self, keys: list[str], repo: str | None) -> str | None:
        """Однозначний ключ зі списку кандидатів (з урахуванням підказки архіву).

        🔴 Один номер справи законно трапляється у двох записах бібліотеки, і не
        завжди це різні справи: тека зменшених копій `data/raw/dahmo_315_small/`
        тримає входи для хмари з ЧУЖИХ фондів (`m357-1-23`, `m904-24-25`), а slug
        теки каже «DAHMO/315». Наслідок — фантом `DAHMO/357/23` поруч зі справжньою
        `DAVO/357/23` (канон, з назвою), і обидві мають ті самі 323 кадри.
        Тому при кількох кандидатах виграє **сильніший опис**: фантом завжди
        `desc_source="code"`, бо про нього не знає ніхто, крім імені теки.
        Рівна сила — свідомо None: краще нерозв'язане, ніж навмання обране.
        """
        if repo:
            keys = [k for k in keys if (self.by_key[k].get("repo") or "") == repo] or keys
        uniq = sorted(set(keys))
        if len(uniq) == 1:
            return uniq[0]
        if not uniq:
            return None
        ranked = sorted(uniq, key=lambda k: (
            -_DESC_RANK.get(self.by_key[k].get("desc_source") or "code", 0),
            -int(self.by_key[k].get("frames") or 0), k))
        best, second = ranked[0], ranked[1]
        if _DESC_RANK.get(self.by_key[best].get("desc_source") or "code", 0) > \
                _DESC_RANK.get(self.by_key[second].get("desc_source") or "code", 0):
            return best
        return None

    def lookup(self, cand: _Cand) -> str | None:
        """Кандидат → key справи, лише якщо збіг однозначний."""
        if cand.opys:
            hit = self._pick(self._by_fos.get((cand.fond, cand.opys, cand.spr), []),
                             cand.repo)
            if hit:
                return hit
        return self._pick(self._by_fs.get((cand.fond, cand.spr), []), cand.repo)

    def lookup_spr(self, spr: str, repo: str | None = None) -> str | None:
        """Лише номер справи (`spov1846-7864`) — приймаємо, якщо в усій бібліотеці один."""
        return self._pick(self._by_spr.get(spr, []), repo)


@lru_cache(maxsize=1)
def load_overrides() -> dict[str, Any]:
    """Ручні рішення реєстру (git). Найвищий пріоритет — це рішення людини.

    Дві секції. `runs` — пряма прив'язка прогону до справи там, де автомат не може
    (ім'я `spov1846-parish56` несе номер ПАРАФІЇ, і автомат прийняв би 56 за номер
    справи). `bundles` — одиниці роботи, які архівною справою не є: прогін `fuzovka`
    покриває ~100 вирізок із РІЗНИХ справ ф.211, зібраних за селом, тож прив'язка
    до однієї справи була б вигадкою, а викидання сховало б 3390 сторінок декоду.

    🔴 Побитий файл кидає `CorruptFileError`, а не порожньо. Цей файл правлять
    ТЕКСТОВИМ РЕДАКТОРОМ (так написано двома абзацами нижче, у `bind_run`), тож
    зайва кома — очікуваний стан, а не екзотика. Читач, що на ній віддавав `{}`,
    у парі з `bind_run` («прочитати → додати ключ → записати») стирав усі
    попередні прив'язки й усі `bundles` на першому ж записі.
    """
    data = read_json(OVERRIDES_PATH, default={})
    if not isinstance(data, dict):
        raise CorruptFileError(OVERRIDES_PATH, "у корені не об'єкт")
    return dict(data)


@lru_cache(maxsize=1)
def _run_overrides() -> dict[str, dict[str, Any]]:
    """ім'я прогону → рішення (з обох секцій; `bundles.runs` розгортається)."""
    data = load_overrides()
    out: dict[str, dict[str, Any]] = dict(data.get("runs") or {})
    for key, b in (data.get("bundles") or {}).items():
        for run in b.get("runs") or []:
            out.setdefault(run, {"key": key, "why": b.get("label") or ""})
    return out


def bundles() -> dict[str, dict[str, Any]]:
    """Оголошені збірки: ключ → опис (для рядків реєстру, яких немає в бібліотеці)."""
    return dict(load_overrides().get("bundles") or {})


def bind_run(run: str, key: str, why: str = "") -> dict[str, Any]:
    """Прив'язати прогін до справи руками — і записати ЧОМУ.

    🔴 Досі це можна було зробити лише текстовим редактором у
    `data/cases/overrides.json`, а підказку про сам файл друкував `cases
    orphans`. Тобто найчастіший ремонт («прогін не зводиться до справи, бо в
    меті шлях орендованого боксу») вимагав від людини знати розкладку
    внутрішнього файлу — і саме тому третина декоду лишалась «нічиєю».

    `why` не косметика: рішення людини сильніше за будь-який автомат, тож через
    півроку має бути видно, на чому воно стояло. Порожнє поле тут — та сама
    вигадка, що й прив'язка без підстави.
    """
    if not run or "/" in run or "\\" in run:
        raise ValueError(f"ім'я прогону негодяще: {run!r}")
    if not key:
        raise ValueError("ключ справи обов'язковий")
    data = dict(load_overrides())
    runs = dict(data.get("runs") or {})
    runs[run] = {"key": key, **({"why": why} if why else {})}
    data["runs"] = runs
    write_json(OVERRIDES_PATH, data, indent=1)
    # 🔴 Кеші скидаємо ОБИДВА. `load_overrides` і `_run_overrides` кешовані
    # `lru_cache`, тож без цього правка підхопилась би лише після рестарту
    # процесу — а людина, яка щойно прив'язала прогін, одразу тисне «показати»
    # і бачить ту саму відмову. Виглядає це як «не спрацювало».
    load_overrides.cache_clear()
    _run_overrides.cache_clear()
    return {"run": run, "key": key, "why": why, "path": str(OVERRIDES_PATH)}


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[-_\s]+", name.strip()) if t]


def _repo_hint(tokens: list[str]) -> str | None:
    for t in tokens:
        hit = _REPO_HINTS.get(t.lower())
        if hit:
            return hit
    return None


def _numbers(tokens: list[str]) -> list[str]:
    """Числа-кандидати з токенів; рік, приліплений до жанру, відкидається.

    `spov1846-7864` → ['7864']: 1846 сидить у жанровому префіксі й означає рік
    книги, а не номер справи. `196-1-5953` → ['196','1','5953'].
    """
    out: list[str] = []
    for t in tokens:
        low = t.lower()
        fm = _FOND_TOKEN_RE.match(low)
        if fm:                                   # `f196` — це фонд
            out.append(_norm(fm.group(1)) or "")
            continue
        glued = any(low.startswith(p) for p in _GENRE_PREFIXES) and not low.isdigit()
        for m in _NUM_RE.finditer(t):
            raw = m.group(1)
            digits = re.sub(r"\D", "", raw)
            if glued and digits.isdigit() and _YEAR_LO <= int(digits) <= _YEAR_HI:
                continue                          # рік у жанровому префіксі
            head = _DAVO_HEAD_RE.match(raw)
            if head and len(raw) >= 5:
                out.append(_norm(head.group(1)) or "")
            else:
                out.append(_norm(raw) or "")
    return [x for x in out if x]


def _strip_all_tails(name: str) -> str:
    """Зняти ВСІ хвости голосу й версії: `…-diak_v4-review` → `…`.

    🔴 Хвіст моделі — це не число справи, і плутати їх дорого. `bershad-678-64`
    розбиралось правильно, а `bershad-678-64-diak_v4` давало числа
    `['678','64','4']`, трійка (678, 64, 4) не знаходилась, і `lookup` падав на
    пару **(678, 4)** — тобто ДРУГИЙ ГОЛОС усіх чотирьох бершадських справ
    прив'язувався до чужої справи 678-1-4 (титульна заглушка на 3 кадри).
    Помилка тиха за побудовою: реєстр показував справу «прогнано одним
    голосом», а другий голос — під чужим шифром.

    Знімаємо ітеративно, бо хвости складаються (`-skryba-test`, `-parseq`).
    """
    cur = name
    for _ in range(4):
        nxt = _strip_derived(cur)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return cur


def name_candidates(name: str) -> list[_Cand]:
    """Ім'я прогону → впорядковані кандидати-шифри (спершу точніші)."""
    tokens = _tokens(_strip_all_tails(name))
    repo = _repo_hint(tokens)
    nums = _numbers(tokens)
    cands: list[_Cand] = []
    # трійки fond-opys-spr: `178-51-418`, `685-3-104`, `010904-24-00214`
    for i in range(len(nums) - 2):
        cands.append(_Cand(fond=nums[i], opys=nums[i + 1], spr=nums[i + 2], repo=repo))
    # пари fond-spr: `315-8059`, `904-25`
    for i in range(len(nums) - 1):
        cands.append(_Cand(fond=nums[i], spr=nums[i + 1], repo=repo))
    return cands


def _strip_derived(name: str) -> str | None:
    """Ім'я базового прогону для похідного (`…-diak_v4` → `…`). None якщо не похідний."""
    for suf in _DERIVED_SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    stripped = _MODEL_TAIL_RE.sub("", name)
    return stripped if stripped != name and stripped else None


#: Тека-слug `<архів>_<фонд>` із необов'язковим суфіксом: `dahmo_315_pages`
#: (посторінковий рендер PDF), `dahmo_315_small` (зменшені копії), `cdiak_224`.
_SLUG_SUFFIXED_RE = re.compile(r"^([a-z]+)_(\d+)(?:_[a-z]+)?$", re.IGNORECASE)
#: Номер справи в імені теки: `spr-7864`, `spr7864_parish56_1846`, `m357-1-23`.
_SPR_IN_NAME_RE = re.compile(r"(?:^|[-_])(?:spr|m)[-_]?0*(\d+[a-zа-я]?)", re.IGNORECASE)
#: Службові підтеки: кадри лежать усередині, а ім'я справи — на рівень вище
#: (`cdiak_224/spr-864/pages` — метрики М'ястківки 1752-1777).
_SERVICE_DIRS = {"pages", "images", "scans", "jpg", "jpeg", "img", "frames"}


def parse_slug_case(rel: str) -> tuple[str, str, str | None, str] | None:
    """Тека → (repo, fond, opys|None, spr) там, де `library.parse_case_path` мовчить.

    🔴 Два випадки, і обидва коштували видимості цілих фондів:
    · слуг із суфіксом — `data/raw/dahmo_315_pages/spr-7864` (3773 кадри рендеру
      сповідки 1846): бібліотека розбирає слуг лише як `<архів>_<фонд>`;
    · кадри у службовій підтеці — `data/raw/cdiak_224/spr-864/pages`: розбирається
      останній сегмент, тобто слово «pages». Саме так зникли метрики М'ястківки
      1752-1777 — найраніший зріз, який узагалі є в проєкті.
    """
    parts = [p for p in re.split(r"[\\/]+", rel.strip()) if p]
    if "raw" in parts:
        parts = parts[parts.index("raw") + 1:]
    if len(parts) < 2:
        return None
    m = _SLUG_SUFFIXED_RE.match(parts[0])
    if not m:
        return None
    repo, fond = m.group(1).upper(), _norm(m.group(2))
    # Кадри можуть лежати у службовій підтеці — тоді ім'я справи на рівень вище.
    leaf = parts[-1]
    if leaf.lower() in _SERVICE_DIRS and len(parts) > 2:
        leaf = parts[-2]
    ms = _SPR_IN_NAME_RE.search(leaf)
    if not (fond and ms):
        return None
    spr = _norm(ms.group(1))
    if not spr:
        return None
    # Ім'я може нести ЧУЖИЙ фонд (`dahmo_315_small/m357-1-23` — це ДАВіО ф.357):
    # шифра з імені сильніша за фонд зі слуга.
    inner = re.match(r"^m(\d+)[-_](\d+)[-_](\d+)$", leaf, re.IGNORECASE)
    if inner:
        return (repo, _norm(inner.group(1)) or fond, _norm(inner.group(2)),
                _norm(inner.group(3)) or spr)
    return (repo, fond, None, spr)


def slug_case(rel: str, index: LibraryIndex) -> str | None:
    """Те саме, але одразу зведене до наявної справи бібліотеки."""
    parsed = parse_slug_case(rel)
    if not parsed:
        return None
    repo, fond, opys, spr = parsed
    return index.lookup(_Cand(fond=fond, spr=spr, opys=opys, repo=repo))


def _from_path(path: str, index: LibraryIndex) -> str | None:
    """Шлях (rel, абсолютний, крізь junction) → key справи."""
    if not path:
        return None
    rel = str(path).replace("\\", "/").rstrip("/")
    if rel in index.by_path:
        return index.by_path[rel]
    dj = dejunction(path)
    if dj and dj in index.by_path:
        return index.by_path[dj]
    for cand in (dj, rel):
        if not cand:
            continue
        parsed = parse_case_code(cand)
        if parsed:
            hit = index.lookup(_Cand(fond=_norm(parsed[1]) or "", spr=_norm(parsed[3]) or "",
                                     opys=_norm(parsed[2]), repo=parsed[0]))
            if hit:
                return hit
        hit = slug_case(cand, index)
        if hit:
            return hit
    return None


def resolve_run(name: str, case_dir: str = "", index: LibraryIndex | None = None,
                _depth: int = 0, meta_key: str = "") -> RunLink:
    """Прогін → `RunLink`. `key=None` означає «не прив'язався» і це видимий стан."""
    idx = index or LibraryIndex()
    ov = _run_overrides().get(name)
    if ov is not None:                                   # 1) рішення людини
        return RunLink(run=name, key=ov.get("key") or None, resolved_by="override",
                       note=ov.get("why") or ov.get("label") or "", case_dir=case_dir)
    # 2) ключ, записаний самим прогоном (`case_key` у меті) — його рахували там,
    # де тека справи ще була під рукою, тож він надійніший за будь-який здогад.
    # ⚠ Ключ збірки має вигляд `DAVO/904/@opys24` — «@» стоїть у ТРЕТЬОМУ
    # сегменті, а не на початку рядка. Доки перевірка була `startswith("@")`,
    # проставлена в меті збірка не приймалась і прогін ішов далі на розбір
    # імені — тобто ремонт мети для збірок не діяв узагалі.
    if meta_key and (meta_key in idx.by_key or meta_key.startswith("@")
                     or "/@" in meta_key):
        return RunLink(run=name, key=meta_key, resolved_by="meta_key", case_dir=case_dir)
    hit = _from_path(case_dir, idx)                      # 3) шлях із мети прогону
    if hit:
        return RunLink(run=name, key=hit, resolved_by="case_dir", case_dir=case_dir)
    for cand in name_candidates(name):                   # 3) шифра в імені прогону
        hit = idx.lookup(cand)
        if hit:
            return RunLink(run=name, key=hit, resolved_by="run_name", case_dir=case_dir,
                           note=f"{cand.fond}-{cand.opys or '?'}-{cand.spr}")
    # archium-стиль `f794_spr_16736`: номер у імені — id файлу на сайті, не справа
    arch = _archium_parse(re.sub(r"^f\d+[_-]", "", name))
    if arch:
        hit = idx.lookup(_Cand(fond=_norm(arch[1]) or "", spr=_norm(arch[3]) or "",
                               opys=_norm(arch[2]), repo=arch[0]))
        if hit:
            return RunLink(run=name, key=hit, resolved_by="archium", case_dir=case_dir)
    # 4) самотній номер справи — але ЛИШЕ з окремого числового токена на 3+ цифри.
    # 🔴 Без цієї умови будь-яка цифра в імені ставала номером справи: тека
    # `cdiak_224/spr-864/pages` під прогоном `t1` прив'язалась до «DAVO/885/1»,
    # бо «1» з імені знайшлась у бібліотеці як єдина справа №1. Такий промах
    # гірший за нерозв'язаний прогін: він тихий і приписує чужий декод.
    tokens = _tokens(name)
    # ⚠ Літерний том — частина номера, а не сміття: `spov1816-7029a` це справа
    # 7029 том А, і вимога «чисто цифровий токен» відрізала б її.
    solo = [t for t in tokens if _SOLO_NUM_RE.fullmatch(t)]
    nums = _numbers(tokens)
    if len(solo) == 1 and len(nums) == 1:
        hit = idx.lookup_spr(_norm(solo[0]) or "", _repo_hint(tokens))
        if hit:
            return RunLink(run=name, key=hit, resolved_by="run_name",
                           case_dir=case_dir, note=f"справа {solo[0]}, збіг єдиний")
    base = _strip_derived(name)                          # 5) успадкувати від базового
    if base and _depth < 3:
        parent = resolve_run(base, "", idx, _depth + 1)
        if parent.key:
            return RunLink(run=name, key=parent.key, resolved_by="derived",
                           note=f"від «{base}»", case_dir=case_dir)
    return RunLink(run=name, key=None, resolved_by="none", case_dir=case_dir)
