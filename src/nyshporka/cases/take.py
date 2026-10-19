"""📥 Узяти справу з реєстру опису — від рядка каталогу до теки на диску.

🔴 Навіщо окремий модуль. Логіка вибору каналу й завантаження була написана
всередині команди командного рядка (`cases/cli.py`), упереміш із друком у
консоль, і тому діставалась лише з термінала приватного конвеєра. У браузері
рядок опису лишався тупиком: людина бачила «скан є, не взято» — і не мала чим
узяти. Питання «чому в описі є кнопки, а взяти нічим» законне, і відповідь на
нього одна: логіка не була відокремлена від друку.

🔴 канал обирається за швидкістю, а не за тим, що першим перевіряється в коді.
Переглядач архіву (ARCHIUM) віддає готові посторінкові JPG, Commons — один файл
на сотні мегабайтів. Доки перевірявся лише Commons, ЦДІАК ф.224 виглядав фондом
майже без сканів (42 справи з 2950), і понад тисяча справ стояла в черзі
«замовлення в архіві», лежачи при цьому онлайн.

⚠ Плівка FamilySearch тут не качається, і це не недогляд: у реєстрі стоїть
номер DGS, а джерело плівок адресується шляхом у дереві регіону. Вигадати цей
шлях із номера неможливо, тож замість тихого «нічого не вийшло» модуль каже,
яким саме джерелом плівка береться.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn


class TakeError(RuntimeError):
    """Узяти не можна — з поясненням, чому саме, і що робити натомість."""


def _row(key: str) -> tuple[str, str, str, str, str, dict[str, Any], Path]:
    """Ключ справи → її рядок у реєстрі опису."""
    from nyshporka.fonds import registry as F

    try:
        repo, fond, opys, spr, letter = F.parse_key(key)
    except ValueError as exc:
        raise TakeError(str(exc)) from None
    if not opys:
        # Опису не названо, а фонд опису за замовчуванням не має. Вгадувати не
        # можна — номери справ між описами повторюються.
        raise TakeError(
            f"у «{key}» немає опису, а фонд {repo} {fond} опису за "
            f"замовчуванням не має — назвіть опис: {repo}/{fond}/<опис>/{spr}{letter}")
    row, path = F.registry_row(repo, fond, opys, spr, letter)
    if row is None:
        raise TakeError(
            f"у реєстрі опису немає {repo} {fond}-{opys}-{spr}{letter} "
            f"({path}) — цей опис у нас не зібраний")
    return repo, fond, opys, spr, letter, row, path


#: Опис за замовчуванням не блокує, але називається вголос: той самий номер в
#: іншому описі — фізично інша справа.
OPYS_ASSUMED = ("опис у ключі не названо — взято {opys}. Якщо справа з іншого "
                "опису фонду {fond}, це інша книга: назвіть опис явно "
                "({repo}/{fond}/<опис>/{spr})")


def opys_named(key: str) -> bool:
    """Чи назвав ключ опис. Ні — взято опис за замовчуванням фонду, і людина мусить це знати.

    Справа береться з реєстру опису, тож рядок під цим описом справді існує.
    Але якщо мали на увазі інший опис того самого фонду, це вже інша справа з
    тим самим номером — і мовчки взяти не ту означає покласти її під чужою шифрою.
    """
    from nyshporka.fonds import registry as F

    m = F._key_re().match(key.strip())
    return bool(m and m.group(3))


def case_dir_for(repo: str, fond: str, spr: str, letter: str, opys: str = "") -> Path:
    """Куди лягає справа: `<архів>_<фонд>/op<опис>-spr-<справа>`.

    🔴 Тека рахується з шифри, а не з адреси, за якою качали. Тека з іменем
    посилання видима лише тому, хто його пам'ятає; тека з шифри знаходиться
    бібліотекою, а отже всім, що йде далі.

    Опис — в імені теки: номери справ між описами повторюються, і тека
    `spr-33` не каже, ДАВіО 904-24-33 у ній чи 904-30-33. Давня тека без
    опису (`spr-<справа>`) лишається справі, якщо її паспорт називає той самий
    опис або не називає жодного: у ній уже лежать кадри цієї справи.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.fonds import registry as F
    from nyshporka.library import _norm_spr, _sidecar_opys

    base = workspace().raw / f"{F.REPO_SLUG.get(repo, repo.lower())}_{fond}"
    plain = base / f"spr-{spr}{letter}"
    if not opys:
        return plain
    own = base / f"op{opys}-spr-{spr}{letter}"
    if own.is_dir() or not plain.is_dir():
        return own
    from nyshporka.cases.register import read_sidecar

    meta: dict[str, Any] = {}
    for name in ("meta.json", "_source.json"):
        f = plain / name
        if f.is_file():
            import json

            try:
                meta = {**json.loads(f.read_text(encoding="utf-8")), **meta}
            except (OSError, ValueError):
                continue
    was = _sidecar_opys(meta) or _sidecar_opys(read_sidecar(plain))
    return plain if not was or was == _norm_spr(opys) else own


def plan(key: str, commons_file: str = "") -> dict[str, Any]:
    """Що станеться, якщо взяти цю справу — без жодної мережевої дії.

    Окремо від самого взяття, бо відповідь «каналу немає» коштує нуль секунд, а
    дізнаватись про неї після півгодини качання — марна робота.
    """
    return {**_plan_from(*_row(key)[:6], commons_file=commons_file),
            "opys_assumed": not opys_named(key)}


def _plan_from(repo: str, fond: str, opys: str, spr: str, letter: str,
               row: dict[str, Any], commons_file: str = "") -> dict[str, Any]:
    """Те саме, але на вже прочитаному рядку — щоб не читати реєстр двічі."""
    from nyshporka.library import _mk_key

    archium = str(row.get("archium_url") or "").strip()
    name = str(row.get("commons_title") or "").strip()
    film = str(row.get("fs_film") or row.get("fs_dgs") or "").strip()
    mirror = str(row.get("mirror_url") or "").strip()
    channel = "archium" if archium else ("commons" if name else "")
    parts: list[str] = []
    conflict = ""
    if channel == "commons":
        try:
            parts = commons_volumes(row, commons_file)
        except TakeError as exc:
            # 🔴 Не кидаємо: `plan` читають і черга, і консоль, і для них це не
            # «справи немає в реєстрі», а «каналу немає, поки людина не вибрала».
            conflict, channel, name = str(exc), "", ""
    return {
        "parts": parts, "conflict": conflict,
        "key": _mk_key(repo, fond, f"{spr}{letter}", opys) or "", "repo": repo,
        "fond": fond,
        "opys": opys, "spr": f"{spr}{letter}",
        "title": str(row.get("title") or ""),
        "channel": channel, "ref": archium or (parts[0] if len(parts) == 1 else name),
        "case_dir": str(case_dir_for(repo, fond, spr, letter, opys)),
        "film": film, "mirror": mirror,
        # DGS окремо від номера плівки: це різні числа FamilySearch, і порада
        # «взяти локальну копію під облік» мусить назвати саме те, що є.
        "dgs": str(row.get("fs_dgs") or "").strip(),
        # 🔴 Номер справи, відновлений інтерполяцією, мусить їхати разом із
        # планом: узяти можна, вірити шифрі — ні, доки її не звірили оком.
        "shifra_needs_eye": row.get("num_src") == "interp",
        "why": conflict or _why(channel, film, mirror),
    }


def _pick_by_years(row: dict[str, Any], files: list[str]) -> str:
    """Єдиний файл, чиї роки в назві потрапляють у роки опису; інакше відмова."""
    from nyshporka.fonds.merge.scans import file_years

    def _y(v: Any) -> int:
        return int(v) if str(v or "").strip().isdigit() else 0

    lo = _y(row.get("year_from"))
    hi = _y(row.get("year_to")) or lo
    listing = "\n".join(
        f"  {f}  (роки в назві: {', '.join(map(str, sorted(file_years(f)))) or '—'})"
        for f in files)
    ask = ('Назвіть файл: --commons-file "<назва або її унікальна частина>". '
           "Файли — різні книги під однією шифрою, найбільший не обирається.")
    if not lo:
        raise TakeError("під цією шифрою на Commons кілька різних книг, а опис не "
                        f"називає років справи, щоб вибрати.\n{listing}\n{ask}")
    hit = [f for f in files if any(lo <= y <= hi for y in file_years(f))]
    if len(hit) != 1:
        raise TakeError(
            f"під цією шифрою на Commons кілька різних книг; роки справи за описом "
            f"{lo}–{hi} "
            + ("не збігаються з жодним файлом" if not hit
               else "збігаються з кількома файлами")
            + f".\n{listing}\n{ask}")
    return hit[0]


def commons_volumes(row: dict[str, Any], commons_file: str = "") -> list[str]:
    """Файли Commons, з яких складається справа: усі томи або один файл.

    🔴 Справа у двох томах («Частина 1», «Частина 2») — один рядок реєстру з
    `commons_kind=volumes`, а `commons_title` у ньому — лише найбільший том. Доти
    `take` брав саме його, і половина справи лишалась на Commons, хоча реєстр
    знав обидва томи (06.10.2026, ДАХмО 315-1-7300: 1512 сторінок із 2992).
    `variants` — це різні файли ОДНОГО змісту, тож береться найбільший, як і
    рахує обсяг `aggregate_commons`.

    🔴 `conflict` — файли під однією шифрою мають різні роки чи деканати, тобто
    це різні книги (ДАВіО 904-31-5: файл 1873 насправді спр.6). Найбільший файл
    тут нічого не каже: береться той, чий рік у назві збігається з роками опису,
    а коли збігу немає чи їх кілька — `TakeError` з переліком кандидатів, бо
    вгадана не та книга лягає під чужу шифру і виглядає правдоподібно.
    `commons_file` — явний вибір людини (назва або унікальна частина назви).
    """
    from nyshporka.fonds.merge.scans import is_conflict

    name = str(row.get("commons_title") or "").strip()
    kind = str(row.get("commons_kind") or "")
    try:
        parts = json.loads(str(row.get("commons_parts") or "") or "[]")
    except ValueError:
        parts = []
    files = [str(p.get("file") or "") for p in parts
             if isinstance(p, dict) and p.get("file")]
    if commons_file:
        files = files or ([name] if name else [])
        want = commons_file.strip()
        hit = [f for f in files if f == want] or [f for f in files if want in f]
        if len(hit) != 1:
            raise TakeError(
                f"--commons-file «{want}»: "
                + ("збігів немає" if not hit else "збігів кілька")
                + ". Файли справи:\n" + "\n".join(f"  {f}" for f in files))
        return hit
    # Реєстр міг бути зібраний до появи виду `conflict`: такий рядок має
    # `variants`, але склад файлів той самий, тож конфлікт видно і з нього.
    if kind == "conflict" or (kind == "variants" and is_conflict(parts)):
        return [_pick_by_years(row, files)]
    if kind != "volumes":
        return [name] if name else []
    vols = [str(p.get("file") or "") for p in parts
            if isinstance(p, dict) and p.get("sum") and p.get("file")]
    # Порядок томів — за назвою: «Частина 1» лягає раніше за «Частину 2», і
    # кадри, розгорнуті з теки, ідуть у порядку справи.
    return sorted(vols) or ([name] if name else [])


def _why(channel: str, film: str, mirror: str) -> str:
    """Чому саме так — одним реченням для людини."""
    if channel == "archium":
        return ("переглядач архіву: посторінкові JPG, найшвидший канал")
    if channel == "commons":
        return "Wikimedia Commons: один файл на всю справу"
    if film:
        return (f"каналу для автоматичного взяття немає, але є плівка "
                f"FamilySearch DGS {film} — вона береться джерелом «плівки FS» "
                f"(потрібен шлях у дереві регіону, а не номер)")
    if mirror:
        return ("є лише дзеркало, а воно обрізає великі справи — качати руками "
                "свідомо")
    return "жодного каналу: справу замовляють в архіві"


def take(key: str, *, force: bool = False, reindex: bool = True,
         on_progress: ProgressFn | None = None,
         commons_file: str = "") -> dict[str, Any]:
    """Завантажити справу й зареєструвати її. Повертає, що саме лягло.

    🔴 Приймач — бібліотека, а не код завершення. Тека без `meta.json` невидима
    для бібліотеки, тобто для всього далі: прогін по ній ляже нічиїм, і знайти
    його потім не буде як. Тому після завантаження реєстри перебудовуються, і
    відповідь чесно каже, чи бібліотека справу побачила.
    """
    from nyshporka.cases import acquire as A

    repo, fond, opys, spr_i, letter, row, _ = _row(key)
    p = {**_plan_from(repo, fond, opys, spr_i, letter, row, commons_file),
         "opys_assumed": not opys_named(key)}
    if not p["channel"]:
        raise TakeError(p["why"])
    spr = p["spr"]
    case_dir = Path(p["case_dir"])
    year = str(row.get("year_from") or "")
    try:
        if p["channel"] == "archium":
            got = A.from_archium(case_dir, p["ref"], archive=repo, fond=fond,
                                 opys=opys, spr=spr, repo=repo,
                                 title=p["title"], year=year,
                                 on_progress=on_progress)
        else:
            got = A.from_commons(case_dir, p["parts"] or p["ref"], archive=repo, fond=fond,
                                 opys=opys, spr=spr, title=p["title"],
                                 year=year, on_progress=on_progress)
    except A.AcquireError as exc:
        raise TakeError(str(exc)) from None

    out = {**p, "pages": got.pages, "bytes": got.bytes,
           "case_dir": str(got.case_dir), "files": len(got.files),
           "skipped": got.skipped, "reindexed": False, "in_library": None}
    if not reindex:
        return out

    # 🔴 Приймач — свіжозібрана бібліотека, а не реєстр опису: колонка `on_disk`
    # у реєстрі опису оновиться лише наступним злиттям, тож перевірка по ньому
    # завжди кричала б «не видима» одразу після завантаження.
    from nyshporka.cases import db
    from nyshporka.library import build_library, write_library

    entries = build_library()
    write_library(entries)
    db.build_index()
    out["reindexed"] = True
    mine = [e for e in entries
            if str(e.fond) == fond and str(e.spr) == spr
            and (e.repo or "").upper() == repo]
    out["in_library"] = bool(mine)
    # Письмо — лише з паспорта справи (`script`/`langs`), не з жанру й років:
    # підказка «далі» інакше радила б рушій навмання.
    out["script"] = next((e.script for e in mine if e.script), "")
    _ = force  # перезапис вирішує сам `acquire`: він звіряє sha256 файлів
    return out
