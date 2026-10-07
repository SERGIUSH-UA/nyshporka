"""🎯 Перелік кадрів і чесна мітка прив'язки чужого тексту до своїх кадрів.

Ключ справи для обміну не годиться, і це не дрібниця. Він залежить від того,
що знає простір: опис справи без паспорта береться з опису за замовчуванням
фонду, а не встановлений — `_`, тож та сама книга в іншого дослідника може
мати інший ключ. Глобального ключа справи в пакеті немає за рішенням —
`sources/base.py`: «спроба звести їх до спільного ключа ламається на першому ж
архіві з іншою нумерацією».

Тому пакет несе не ключ, а перелік КАДРІВ, і приймач сам вимірює, наскільки
чужий текст лягає на його зйомку. Результат вимірювання оголошується вголос:

  `exact`        збігся sha256 кадру або FS apid — працює все, включно з кропом
  `by-name`      збіглися імена й кількість — працює все, з попередженням
  `by-position`  збіглася лише кількість — сторінка так, кроп під сумнівом
  `text-only`    прив'язки немає: кадрів немає або вони інші

🔴 Мовчазної прив'язки не буває. Збіг імені файлу НЕ означає той самий кадр:
плоский стейджинг перенумеровує сторінки, і `htr_store.frames_match_meta` ловить
це лише за наявності самих зображень. Тому мітка їде в кожну відповідь, а не
лише туди, де щось пішло не так.
"""
from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Розширення, які вважаємо кадром справи.
FRAME_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".jp2")

#: Сайдкар покадрових метаданих FamilySearch: sha256 і глобальний `apid` кадру.
FS_META = "_fs_meta.json"

EXACT = "exact"
BY_NAME = "by-name"
BY_POSITION = "by-position"
TEXT_ONLY = "text-only"

#: Людські пояснення мітки — щоб їх не переписували в кожному місці показу.
LABEL_TEXT = {
    EXACT: "кадри ті самі (звірено хешем)",
    BY_NAME: "кадри збіглися за іменами й кількістю",
    BY_POSITION: "збіглася лише кількість кадрів — порядок прийнято на віру",
    TEXT_ONLY: "текст без прив'язки до кадрів",
}


def frames_sorted(case_dir: Path) -> list[Path]:
    """Кадри теки в порядку, однаковому на будь-якій машині.

    🔴 Сортування за `p.name`, а НЕ за самим `Path`. `PurePath.__lt__`
    порівнює `_str_normcase`: на Windows регістронечутливо, на POSIX —
    чутливо. Тека з `0001.JPG` і `0001b.jpg` дає різний порядок на різних
    системах, тобто `n`-й кадр — це різний кадр, і побудований на позиціях
    відбиток зйомки ламається мовчки.

    Заміна порядку міняє нумерацію `n` у `frames.jsonl`. Це видима зміна
    формату, і вона зроблена свідомо, доки пул не запущено.
    """
    d = Path(case_dir)
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if is_frame(p)), key=lambda p: p.name)


def is_frame(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in FRAME_SUFFIXES


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fs_sidecar(case_dir: Path) -> dict[str, dict[str, Any]]:
    """Покадрові метадані FS: `{"0001": {"apid": …, "sha256": …}}` або порожньо."""
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(Path(case_dir) / FS_META, default={})
    except CorruptFileError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def frames_of(case_dir: Path, *, hash_frames: bool = False) -> list[dict[str, Any]]:
    """Перелік кадрів теки: порядок, ім'я, розмір і — де є — hash та FS apid.

    🔴 sha256 за замовчуванням НЕ рахується. На справі в 3772 кадри це кілька
    гігабайтів читання з диска заради поля, яке в більшості випадків однаково
    не збігається: штатне стискання перед хмарним прогоном (`cloud/frames.py`)
    міняє байти. Хеш береться задарма з сайдкара FS, якщо той є, і рахується
    лише на явну вимогу.
    """
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        return []
    from nyshporka.core import framename

    fs = _fs_sidecar(case_dir)
    source = _fetched_from(case_dir)
    spreads = _skanoteka_map(case_dir)
    cuts = _skanoteka_boxes(case_dir) if spreads else {}
    out: list[dict[str, Any]] = []
    for n, path in enumerate(frames_sorted(case_dir), 1):
        row: dict[str, Any] = {"n": n, "name": path.name}
        # id кадру в джерелі — той самий у кожного, хто качав цю справу звідти,
        # хоч би як він потім назвав файли. Карта Сканотеки, коли вона є,
        # важить більше за форму імені: вона записана при різанні розворотів.
        hit = spreads.get(path.name)
        if hit is not None:
            from nyshporka.core import skanoteka

            src = skanoteka.src_of(*hit)
        else:
            src = framename.parse(path.name, source).src
        if src:
            row["src"] = src
        if path.name in cuts:
            # Де пройшов різ розвороту: без цього «той самий кадр» за `src`
            # міг бути іншими пікселями (`page_names`).
            row["box"] = cuts[path.name]
        with contextlib.suppress(OSError):
            row["bytes"] = path.stat().st_size
        side = fs.get(path.stem) or {}
        if side.get("apid"):
            row["apid"] = str(side["apid"])
        if side.get("sha256"):
            row["sha256"] = str(side["sha256"])
        elif hash_frames:
            with contextlib.suppress(OSError):
                row["sha256"] = _sha256(path)
        out.append(row)
    return out


def _fetched_from(case_dir: Path) -> str:
    """З якого джерела завантажено теку — з її паспорта; невідомо — порожньо.

    Паспорт завантажувача Сканотеки поля `fetched_from` не пише, зате несе
    адресу одиниці в `source.url` — за нею джерело й упізнається.
    """
    from nyshporka.cases.register import read_sidecar
    from nyshporka.core import skanoteka

    for d in _passport_dirs(Path(case_dir)):
        try:
            side = read_sidecar(d)
        except Exception:
            continue
        if side.get("fetched_from"):
            return str(side["fetched_from"])
        if skanoteka.unit_of(side) is not None:
            return skanoteka.SOURCE
    return ""


def _passport_dirs(case_dir: Path) -> list[Path]:
    """Тека кадрів і, коли це `pages/`, сама справа: паспорт лежить там."""
    if case_dir.name.lower() == FRAMES_SUBDIR:
        return [case_dir, case_dir.parent]
    return [case_dir]


def _skanoteka_boxes(case_dir: Path) -> dict[str, list[int]]:
    from nyshporka.core import skanoteka, szukaj

    for d in _passport_dirs(Path(case_dir)):
        got = skanoteka.page_boxes(d) or szukaj.page_boxes(d)
        if got:
            return got
    return {}


def _skanoteka_map(case_dir: Path) -> dict[str, tuple[str, str]]:
    """Карта «сторінка → скан, бік» поруч із кадрами або при паспорті.

    Дві карти однієї форми: Сканотеки (`_skanoteka.json`) і Szukaj w Archiwach
    (`_szukaj.json`) — обидва джерела ріжуть розвороти тим самим детектором.
    """
    from nyshporka.core import skanoteka, szukaj

    for d in _passport_dirs(Path(case_dir)):
        got = skanoteka.read_map(d) or szukaj.read_map(d)
        if got:
            return got
    return {}


def summary(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Шапка переліку кадрів для маніфесту."""
    out = {"total": len(frames), "listed": len(frames),
           "with_sha256": sum(1 for f in frames if f.get("sha256")),
           "with_apid": sum(1 for f in frames if f.get("apid"))}
    with_src = sum(1 for f in frames if f.get("src"))
    if with_src:
        out["with_src"] = with_src
    return out


# ── вимірювання прив'язки ────────────────────────────────────────────────────

@dataclass
class Alignment:
    """Наскільки чужий текст ліг на кадри цієї машини."""

    label: str
    why: str
    case_dir: str = ""
    theirs: int = 0
    ours: int = 0
    matched: int = 0

    @property
    def can_crop(self) -> bool:
        """Чи можна різати кроп без застереження. Лише `exact`."""
        return self.label == EXACT

    def as_json(self) -> dict[str, Any]:
        return {"label": self.label, "text": LABEL_TEXT.get(self.label, ""),
                "why": self.why, "case_dir": self.case_dir,
                "frames_theirs": self.theirs, "frames_ours": self.ours,
                "matched": self.matched,
                # 🔴 Рішення, а не мітка. Той, хто вирішує, чи тягти
                # геометрію, бачить лише цей JSON, і без готової відповіді
                # він порівнював би рядок сам — тобто завів би другу копію
                # правила «кроп лише при `exact`». Дві копії розходяться
                # мовчки, і розійдуться вони в бік «ріжемо, коли не можна».
                "can_crop": self.can_crop}


def _keyset(frames: list[dict[str, Any]], field: str) -> set[str]:
    return {str(f[field]) for f in frames if f.get(field)}


def _fingerprint_grade(their_fp: dict[str, Any], case_dir: Path,
                       theirs: int, ours: int) -> Alignment | None:
    """Мітка за відбитком зйомки, або `None` — якщо він нічого не довів.

    🔴 `exact` ставиться ТІЛЬКИ при збігу всіх звірених слотів і кількості
    кадрів. Збіг чотирьох із п'яти — це вже `by-position`, і кроп під
    сумнівом: різниця в одному слоті означає, що десь у зйомці є зайвий або
    пропущений аркуш, і далі за ним усе з'їхало на одиницю.

    `None` замість мітки, коли звірити не вдалося нічого: відсутній доказ не
    є доказом відсутності, і рішення переходить до наступних каналів.
    """
    from nyshporka.share import fingerprint as FP
    from nyshporka.share.bundle import as_count

    mine = FP.fingerprint(case_dir)
    zbihlos, zvireno = FP.compare(mine, their_fp)
    if not zvireno:
        return None

    same_count = as_count(their_fp.get("frames")) == mine.get("frames")
    dosyt = zvireno >= FP.required(int(mine.get("frames") or 0))
    if zbihlos == zvireno and same_count and dosyt:
        return Alignment(EXACT, f"відбиток зйомки збігся ({zbihlos} з {zvireno} кадрів)",
                         case_dir=str(case_dir), theirs=theirs, ours=ours,
                         matched=zbihlos)
    if zbihlos == zvireno and same_count:
        return Alignment(
            BY_POSITION,
            f"відбиток збігся, але звірено лише {zvireno} кадр(и) — для «ті самі "
            f"кадри» замало", case_dir=str(case_dir), theirs=theirs, ours=ours,
            matched=zbihlos)
    if zbihlos:
        return Alignment(
            BY_POSITION,
            f"відбиток збігся частково ({zbihlos} з {zvireno}"
            + ("" if same_count else ", і кількість кадрів різна")
            + ") — десь зйомка розійшлась на аркуш",
            case_dir=str(case_dir), theirs=theirs, ours=ours, matched=zbihlos)
    return Alignment(TEXT_ONLY,
                     f"відбиток зйомки не збігся жодним із {zvireno} кадрів — "
                     f"це інша зйомка тієї самої справи",
                     case_dir=str(case_dir), theirs=theirs, ours=ours)


def grade(theirs: list[dict[str, Any]], case_dir: Path | None, *,
          hash_frames: bool = False,
          their_fp: dict[str, Any] | None = None) -> Alignment:
    """Виміряти прив'язку. `case_dir=None` або порожня тека → `text-only`.

    🔴 Мітка не підвищується здогадом. Кількість кадрів, що збіглася, доводить
    лише кількість: справа, знята двічі різними людьми, дає ту саму кількість
    аркушів при цілком іншій нумерації.
    """
    if case_dir is None:
        return Alignment(TEXT_ONLY, "кадрів цієї справи на диску немає",
                         theirs=len(theirs))
    ours = frames_of(case_dir, hash_frames=hash_frames)
    if not ours:
        return Alignment(TEXT_ONLY, f"у теці {case_dir} немає кадрів",
                         case_dir=str(case_dir), theirs=len(theirs))

    # Відбиток зйомки — перший і найсильніший доказ, бо єдиний, що переживає
    # перекодування. Питається до інших саме тому: `sha256` цілих кадрів
    # ламається від будь-якого стискання, а імена ламаються від плоского
    # стейджингу.
    if their_fp:
        got = _fingerprint_grade(their_fp, case_dir, len(theirs), len(ours))
        if got is not None:
            return got

    for field, why in (("apid", "ідентифікатори кадрів FamilySearch"),
                       ("src", "ідентифікатори кадрів у джерелі"),
                       ("sha256", "хеші кадрів")):
        a, b = _keyset(theirs, field), _keyset(ours, field)
        both = a & b
        if not both:
            continue
        # 🔴 `exact` — лише коли збіглися ВСІ кадри з обох боків. Доти вистачало
        # одного спільного хеша на всю справу: 500 кадрів у пакеті, 10 на
        # диску, один спільний — і `can_crop`, за яким `share.take` сам тягнув
        # чужу геометрію на чужі аркуші.
        if a == b and len(a) == len(theirs) == len(ours):
            return Alignment(EXACT, f"збіглися {why} — усі {len(both)}",
                             case_dir=str(case_dir), theirs=len(theirs),
                             ours=len(ours), matched=len(both))
        return Alignment(BY_POSITION,
                         f"збіглися {why} лише частково: {len(both)} із "
                         f"{len(theirs)} у пакеті й {len(ours)} на диску",
                         case_dir=str(case_dir), theirs=len(theirs),
                         ours=len(ours), matched=len(both))

    names_a = _keyset(theirs, "name")
    names_b = _keyset(ours, "name")
    common = names_a & names_b
    if common and len(theirs) == len(ours) and names_a == names_b:
        return Alignment(BY_NAME, "імена й кількість кадрів збіглися",
                         case_dir=str(case_dir), theirs=len(theirs),
                         ours=len(ours), matched=len(common))
    if len(theirs) == len(ours) and theirs:
        return Alignment(BY_POSITION,
                         "кількість кадрів збіглася, імена — ні; порядок "
                         "прийнято на віру",
                         case_dir=str(case_dir), theirs=len(theirs),
                         ours=len(ours), matched=len(common))
    if common:
        return Alignment(TEXT_ONLY,
                         f"кадрів у пакеті {len(theirs)}, на диску {len(ours)} — "
                         f"це різні зйомки однієї справи",
                         case_dir=str(case_dir), theirs=len(theirs),
                         ours=len(ours), matched=len(common))
    return Alignment(TEXT_ONLY,
                     f"жоден кадр не впізнано: у пакеті {len(theirs)}, "
                     f"на диску {len(ours)}",
                     case_dir=str(case_dir), theirs=len(theirs), ours=len(ours))


#: Підтека кадрів у теці справи: так кладе їх `cases take` з ARCHIUM, поруч із
#: `meta.json`. Перевірка лише верхнього рівня бачила тут «справу без кадрів».
FRAMES_SUBDIR = "pages"


def _key_parts(key: str) -> tuple[str, str, str, str] | None:
    """`CDIAK/224/2/49` → `("CDIAK", "224", "2", "49")`; опис невідомий — порожній.

    Старий ключ (до 0.22, з мети прогону чи давнього пакета) теж розбирається:
    `CDIAK/224-2/49`, `DAVIO/R-6129-24/5` (літерний фонд — один сегмент).
    """
    from nyshporka.core import casekey

    ck = casekey.parse(key)
    if ck is not None:
        return ck.repo, ck.fond, ck.opys if ck.opys_known else "", ck.spr
    old = casekey.parse_legacy(key)
    return (old[0], old[1], old[2] or "", old[3]) if old else None


def _row_matches(row: dict[str, Any], key: str) -> bool:
    """Рядок бібліотеки — саме ця справа (старий ключ — через карту переїзду)."""
    from nyshporka.core import legacy_key

    return str(row.get("key") or "") == legacy_key.current_key(key)


def _frames_dir(p: Path) -> Path | None:
    """Тека, де лежать самі кадри: `p` або `p/pages`."""
    for d in (p, p / FRAMES_SUBDIR):
        if d.is_dir() and any(is_frame(x) for x in d.iterdir()):
            return d
    return None


def page_names(theirs: list[dict[str, Any]], case_dir: Path | None) -> dict[str, str]:
    """Ім'я кадру донора → ім'я ТОГО САМОГО кадру на цій машині. Порожньо — не доведено.

    🔴 Лише за id кадру в джерелі й лише коли збіглися ВСІ кадри з обох
    боків, по одному на id. За позицією й за схожістю імен не зіставляється
    нічого: збіг кількості доводить лише кількість, а текст, покладений на
    сусідній аркуш, гірший за текст без аркуша — він виглядає прив'язаним.
    """
    if case_dir is None:
        return {}
    ours = frames_of(case_dir)
    a = {str(f["src"]): str(f["name"]) for f in theirs if f.get("src") and f.get("name")}
    b = {str(f["src"]): str(f["name"]) for f in ours if f.get("src")}
    if not a or len(a) != len(theirs) or len(b) != len(ours) or set(a) != set(b):
        return {}
    # 🔴 Той самий `src` при іншому різі розвороту — інші пікселі: рамки рядків
    # донора лягли б зі зсувом. Межі звіряються, коли їх знають обидва боки;
    # допуск — кілька пікселів оригіналу (той самий різ на тих самих байтах дає 0).
    a_box = {str(f["src"]): f.get("box") for f in theirs if f.get("src")}
    b_box = {str(f["src"]): f.get("box") for f in ours if f.get("src")}
    for s in a:
        x, y = a_box.get(s), b_box.get(s)
        if (isinstance(x, list) and isinstance(y, list) and len(x) == len(y)
                and max(abs(int(i) - int(j)) for i, j in zip(x, y, strict=True)) > CUT_TOLERANCE):
            return {}
    return {a[s]: b[s] for s in a}


#: Допуск розбіжності меж різу (пікселі оригіналу скана). Той самий різ на тих
#: самих байтах дає нуль; дві редакції детектора згину розходились на 38-56 px.
CUT_TOLERANCE = 4


def case_home_for(case_key: str, opys: str = "") -> Path | None:
    """Тека СПРАВИ — паспорт, навіть коли кадрів у ній уже немає.

    🔴 Кадри після прочитання прибирають (`_frames_removed.json`), і тоді
    `case_dir_for` мовчить — а з ним мовчав і паспорт: пакет їхав без
    посилання на скани й без знаменника, хоча `_source.json` знає і перше, і
    друге. Шукає бібліотекою, а потім за адресою з шифри (`cases take`) у
    кожному корені справ простору.

    `opys` — коли ключ опису не несе (старий ключ, `_`): тека чужого опису з
    тим самим номером справи не береться.
    """
    from nyshporka.cases.register import read_sidecar
    from nyshporka.library import _norm_spr, _sidecar_opys

    key = (case_key or "").strip()
    got = case_dir_for(key)
    if got is not None:
        return got.parent if got.name == FRAMES_SUBDIR else got
    parts = _key_parts(key)
    if parts is None:
        return None
    repo, fond, opys_key, spr = parts
    want = _norm_spr(opys_key or opys.strip())
    got = _library_home(key, want)
    if got is not None:
        return got
    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.fonds import registry as F
        ws = workspace()
    except Exception:
        return None
    slug = f"{F.REPO_SLUG.get(repo, repo.lower())}_{fond}"
    # Тека справи з описом в імені (`op3-spr-213`, так бере `cases take`) і
    # давня, без нього (`spr-213`) — паспорт вирішує, чия вона.
    names = ([f"op{want}-spr-{spr}"] if want else []) + [f"spr-{spr}"]
    for d in (base / slug / name for base in ws.case_roots() for name in names):
        if not d.is_dir():
            continue
        have = _sidecar_opys(read_sidecar(d))
        if want and have and have != want:
            continue
        return d
    return None


def _library_home(key: str, want_opys: str) -> Path | None:
    """Тека справи за шляхом бібліотеки — коли кадрів у ній уже немає.

    🔴 Бібліотека знає шлях справи й тоді, коли кадри знято: тека з паспортом
    лишається. Без цього кроку тека з іменем не за домовленістю
    (`agad_4/1-183` замість `op1-spr-183`) губилась, щойно кадри знімали, і
    пакет переставав збиратися: «числа кадрів немає ніде», хоча паспорт його
    знає (07.10.2026, MK 180–189).
    """
    from nyshporka.cases.register import read_sidecar
    from nyshporka.library import _norm_spr

    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.library import load_library

        root = workspace().root
        rows = load_library()
    except Exception:
        return None
    for row in rows:
        if not _row_matches(row, key):
            continue
        have = _norm_spr(str(row.get("opys") or ""))
        if want_opys and have and have != want_opys:
            continue
        for rel in [row.get("path"), *(row.get("extra_paths") or [])]:
            if not rel:
                continue
            p = Path(rel)
            p = p if p.is_absolute() else root / p
            if p.is_dir() and read_sidecar(p):
                return p
    return None


def library_frames(case_key: str) -> int:
    """Скільки кадрів знає про справу бібліотека — навіть коли зображень немає.

    🔴 Справа, прочитана з PDF, кадрів-зображень на диску не має, і
    `case_dir_for` її не бачить. А бібліотека рахує сторінки PDF як кадри
    (`library._count_case`) — саме заради того, щоб PDF-справа не ставала
    невідрізненною від голої картки опису. Без цього числа пакет їхав із
    «кадрів не названо»: 28.09.2026 так у пулі стояли всі 46 справ одного
    видавця, читані з PDF.
    """
    key = (case_key or "").strip()
    if not key:
        return 0
    try:
        from nyshporka.library import load_library

        rows = load_library()
    except Exception:
        return 0
    best = 0
    for row in rows:
        if not _row_matches(row, key):
            continue
        try:
            best = max(best, int(row.get("frames") or 0))
        except (TypeError, ValueError):
            continue
    return best


def case_dir_for(case_key: str) -> Path | None:
    """Тека кадрів цієї справи на ЦІЙ машині — або нічого.

    Бібліотека, а не здогад за іменем: саме вона знає, що справа може лежати
    кількома теками (`extra_paths`), і саме її шлях потім іде в мету прогону.
    """
    key = (case_key or "").strip()
    if not key:
        return None
    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.library import load_library
    except Exception:
        return None
    root = workspace().root
    try:
        rows = load_library()
    except Exception:
        return None
    for row in rows:
        if not _row_matches(row, key):
            continue
        for rel in [row.get("path"), *(row.get("extra_paths") or [])]:
            if not rel:
                continue
            p = Path(rel)
            p = p if p.is_absolute() else root / p
            got = _frames_dir(p)
            if got is not None:
                return got
    return None
