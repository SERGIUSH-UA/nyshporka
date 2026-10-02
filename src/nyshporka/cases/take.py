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

    base = workspace().root / "data" / "raw" / f"{F.REPO_SLUG.get(repo, repo.lower())}_{fond}"
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


def plan(key: str) -> dict[str, Any]:
    """Що станеться, якщо взяти цю справу — без жодної мережевої дії.

    Окремо від самого взяття, бо відповідь «каналу немає» коштує нуль секунд, а
    дізнаватись про неї після півгодини качання — марна робота.
    """
    return {**_plan_from(*_row(key)[:6]), "opys_assumed": not opys_named(key)}


def _plan_from(repo: str, fond: str, opys: str, spr: str, letter: str,
               row: dict[str, Any]) -> dict[str, Any]:
    """Те саме, але на вже прочитаному рядку — щоб не читати реєстр двічі."""
    from nyshporka.library import _mk_key

    archium = str(row.get("archium_url") or "").strip()
    name = str(row.get("commons_title") or "").strip()
    film = str(row.get("fs_film") or row.get("fs_dgs") or "").strip()
    mirror = str(row.get("mirror_url") or "").strip()
    channel = "archium" if archium else ("commons" if name else "")
    return {
        "key": _mk_key(repo, fond, f"{spr}{letter}", opys) or "", "repo": repo,
        "fond": fond,
        "opys": opys, "spr": f"{spr}{letter}",
        "title": str(row.get("title") or ""),
        "channel": channel, "ref": archium or name,
        "case_dir": str(case_dir_for(repo, fond, spr, letter, opys)),
        "film": film, "mirror": mirror,
        # DGS окремо від номера плівки: це різні числа FamilySearch, і порада
        # «взяти локальну копію під облік» мусить назвати саме те, що є.
        "dgs": str(row.get("fs_dgs") or "").strip(),
        # 🔴 Номер справи, відновлений інтерполяцією, мусить їхати разом із
        # планом: узяти можна, вірити шифрі — ні, доки її не звірили оком.
        "shifra_needs_eye": row.get("num_src") == "interp",
        "why": _why(channel, film, mirror),
    }


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
         on_progress: ProgressFn | None = None) -> dict[str, Any]:
    """Завантажити справу й зареєструвати її. Повертає, що саме лягло.

    🔴 Приймач — бібліотека, а не код завершення. Тека без `meta.json` невидима
    для бібліотеки, тобто для всього далі: прогін по ній ляже нічиїм, і знайти
    його потім не буде як. Тому після завантаження реєстри перебудовуються, і
    відповідь чесно каже, чи бібліотека справу побачила.
    """
    from nyshporka.cases import acquire as A

    repo, fond, opys, spr_i, letter, row, _ = _row(key)
    p = {**_plan_from(repo, fond, opys, spr_i, letter, row),
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
            got = A.from_commons(case_dir, p["ref"], archive=repo, fond=fond,
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
