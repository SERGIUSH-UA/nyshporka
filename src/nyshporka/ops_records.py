"""⚙️📋 Розбір актів у поля: нарізка, прийом чужої вичитки, чексуми, звід.

🔴 Усі чотири — `agent=False`, і це не про недовіру до агента. Перелік MCP-tool'ів
має стелю (`mcp.server.TOOL_LIMIT`), за якою модель перестає читати описи й
починає вгадувати; він за побудовою вужчий за реєстр. Агентові MCP і не
потрібен: `nysh op records.prep --describe` віддає повну схему, а `nysh op
records.prep --args '{…}'` виконує. Писати результат агент може вже наявними
`records.add` і `pages.note`.

🔴 Сам розбір тут не робиться. Аркуш читає модель — коштом того, хто її кличе;
вбудований виклик чужого API витрачав би гроші дослідника з коду, який він
поставив подивитись каталог. Тому `records.prep` готує тайли й НАЗИВАЄ ЦІНУ, а
читає агент користувача.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

#: Заміряно на цьому конвеєрі: вичитка одного розвороту по тайлах, дві сторінки
#: на виклик агента. Менше сторінок на виклик — дорожче (146 тис. при одній),
#: більше — насичення й дорожчий обрив. Цифра тут щоб її бачила ЛЮДИНА до того,
#: як почне книгу на дві сотні аркушів, а не після рахунку.
TOKENS_PER_SCAN = 84_000

#: Ціна за мільйон токенів, вхід+вихід усередненo. Не таблиця тарифів: тарифи
#: змінюються частіше за код, і застарілий тариф гірший за відсутній — тут
#: потрібен ПОРЯДОК величини, і саме так він і підписаний у виводі.
USD_PER_MTOK_ROUGH = 8.0


def _case(case: str) -> tuple[Any, Any] | Envelope:
    from nyshporka.pagestore import store

    try:
        ref = store.resolve_case(case)
    except ValueError as exc:
        return fail(str(exc))
    return ref, store.load_case(ref)


def _profile(name: str | None, key: str) -> Any:
    from nyshporka.records import profile as P

    return P.load(name or None, case_key=key)


def estimate(scans: int) -> dict[str, Any]:
    """Скільки коштуватиме вичитка стількох сканів — порядок величини."""
    tokens = scans * TOKENS_PER_SCAN
    usd = tokens / 1_000_000 * USD_PER_MTOK_ROUGH
    return {"scans": scans, "tokens": tokens, "usd_rough": round(usd, 2),
            "tokens_per_scan": TOKENS_PER_SCAN}


def _cost_note(env: Envelope, scans: int) -> None:
    """🔴 Ціну називають ПЕРЕД роботою, а не показують у рахунку після.

    Вичитка — єдиний крок конвеєра, який коштує грошей на кожному аркуші, і
    єдиний, ціну якого застосунок може порахувати заздалегідь.
    """
    if not scans:
        return
    est = estimate(scans)
    env.warn("extraction_cost",
             f"вичитка {scans} сканів — це близько {est['tokens'] // 1000} тис. "
             f"токенів на прохід (~${est['usd_rough']} за порядком величини, "
             f"залежно від моделі), і проходів мусить бути ДВА: один не є "
             f"джерелом істини. Платить той, чий агент читає")


# ── нарізка ──────────────────────────────────────────────────────────────────
class PrepArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    scans: str = Field(default="all",
                       description="«0022-0024,0461» або «all»")
    profile: str = Field(default="", description="профіль книги; типово — за справою")
    rows: int = Field(default=0, description="смуг на сторінку; 0 = з профілю")
    only: str = Field(default="",
                      description="лише ці види тайлів: head/full/left/right")
    force: bool = Field(default=False, description="різати й вичитані (status=full)")
    refresh: bool = Field(default=False, description="перерізати, ігноруючи кеш")


@op("records.prep", summary="Нарізати розворот на тайли, які модель справді читає",
    args=PrepArgs, mutates=False, agent=False, section="research")
def records_prep(a: PrepArgs) -> Envelope:
    """Скан → смуги, у яких скоропис лишається читабельним.

    🔴 Крок не косметичний. Розворот метричної книги — це ~4000×3000, модель
    стискає його до ~1568px і бачить у 0.39×; скоропис на такому масштабі
    розсипається, а провал виглядає не помилкою, а впевнено неправильним
    текстом. Смуга лівої сторінки повертає рядкам майже натуральну величину.

    Тайли лягають у кеш простору й звіряються з часом зміни скана, тож
    повторний виклик нічого не переробляє.
    """
    from nyshporka.records import tiles

    got = _case(a.case)
    if isinstance(got, Envelope):
        return got
    ref, cf = got
    if not ref.path:
        # Порада — структурою, а не командою в тексті: конверт уміє назвати
        # наступний крок операцією, і фронт малює з неї кнопку.
        return fail(f"у бібліотеці немає теки сканів для {ref.shifra} — "
                    f"справу треба завести").suggest(
            "case.register", "описати теку зі сканами цієї справи")

    from nyshporka.core.workspace import workspace

    case_dir = Path(ref.path)
    if not case_dir.is_absolute():
        case_dir = workspace().root / case_dir
    if not case_dir.is_dir():
        return fail(f"теки сканів немає на диску: {case_dir}")

    try:
        prof = _profile(a.profile, ref.key)
    except ValueError as exc:
        return fail(str(exc))

    wanted = None if a.scans.strip() == "all" else tiles.expand_range(a.scans)
    files = tiles.scan_files(case_dir, wanted)
    if not files:
        return fail(f"жодного скана не підійшло під «{a.scans}» у {case_dir}")

    # Уже вичитане не ріжеться повторно: нарізка книги — це гігабайти, і
    # найдорожче тут не час, а те, що людина бачить сотні тайлів і не знає,
    # які з них потрібні.
    done = {s for s, n in (cf.pages if cf else {}).items() if n.status == "full"}
    skipped = [f.name for f in files if f.name in done] if not a.force else []
    if not a.force:
        files = [f for f in files if f.name not in done]

    base = tiles.default_out_dir() / ref.key.replace("/", "_")
    only = {s.strip() for s in a.only.split(",") if s.strip()} or None
    prepared = []
    for f in files:
        tile_dir = base / f.stem
        cached = not a.refresh and tiles.cached_tiles(f, tile_dir) is not None
        made = tiles.slice_scan(f, tile_dir, rows=a.rows or None,
                                cfg=prof.tiles, refresh=a.refresh, only=only)
        prepared.append({"scan": f.name, "dir": str(tile_dir),
                         "tiles": len(made), "cached": cached})

    from nyshporka.records import CONTRACT

    env = ok({"case": ref.key, "shifra": ref.shifra, "profile": prof.name,
              "contract": str(CONTRACT),
              "prepared": prepared, "skipped_done": skipped,
              "estimate": estimate(len(prepared))})
    _cost_note(env, len(prepared))
    if skipped:
        env.warn("already_read",
                 f"{len(skipped)} сканів уже вичитано начисто (status=full) — "
                 f"не різались; `force` щоб перерізати")
    env.suggest("records.audit",
                "після вичитки — чексуми книги: «прочитав усе» без них лишається "
                "самозвітом")
    return env


# ── прийом чужої вичитки ─────────────────────────────────────────────────────
class IngestArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    payload: str = Field(
        default="",
        description='JSON {"pages": [...], "records": [...]} — вивід вичитки')
    dir: str = Field(default="", description="тека з JSON-файлами: усі за раз")
    replace: bool = Field(default=False,
                          description="замінити анотації сторінок повністю")


@op("records.ingest", summary="Прийняти вивід вичитки: сторінки й акти разом",
    args=IngestArgs, mutates=True, agent=False, section="research")
def records_ingest(a: IngestArgs) -> Envelope:
    """Чужий JSON → сховище, з валідацією поштучно.

    🔴 Невалідний елемент не валить батч. Модель однаково охоче шле `"sex": ""`
    і `null`, «summary» замість «tally», поле, якого в схемі немає, — і втратити
    сорок розібраних актів через одруківку в сорок першому означало б платити за
    ту сторінку двічі. Що саме не пройшло, повертається переліком.

    Записи ідемпотентні: `rid` детермінований (сторінка + секція + номер), тож
    повторний прийом того самого виводу ОНОВЛЮЄ акти, а не подвоює справу.
    """
    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import PageNote, Record
    from nyshporka.records import sanitize

    got = _case(a.case)
    if isinstance(got, Envelope):
        return got
    ref, _ = got

    texts: list[str] = []
    if a.dir:
        folder = Path(a.dir).expanduser()
        if not folder.is_dir():
            return fail(f"теки немає: {folder}")
        texts = [f.read_text(encoding="utf-8") for f in sorted(folder.glob("*.json"))]
        if not texts:
            return fail(f"у {folder} немає жодного .json")
    elif a.payload.strip():
        texts = [a.payload]
    else:
        return fail("нема чого заносити: дайте payload або dir")

    merged: dict[str, list[Any]] = {"pages": [], "records": []}
    unreadable = 0
    for text in texts:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            if len(texts) == 1:
                return fail(f"не JSON: {exc}")
            unreadable += 1
            continue
        cleaned = sanitize.clean_payload(raw)
        merged["pages"].extend(cleaned["pages"])
        merged["records"].extend(cleaned["records"])

    notes: list[PageNote] = []
    records: list[Record] = []
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(merged["pages"]):
        try:
            notes.append(PageNote.model_validate(item))
        except ValidationError as exc:
            errors.append({"kind": "page", "index": i, "error": str(exc)[:400]})
    for i, item in enumerate(merged["records"]):
        try:
            records.append(Record.model_validate(item))
        except ValidationError as exc:
            errors.append({"kind": "record", "index": i, "error": str(exc)[:400]})

    rep_pages = store.annotate_pages(ref, notes, replace=a.replace) if notes else None
    rep_recs = store.add_records(ref, records) if records else None
    if not (notes or records):
        return fail("жоден елемент не пройшов перевірку; "
                    + "; ".join(e["error"][:120] for e in errors[:3]))

    env = ok({"case": ref.key, "shifra": ref.shifra, "files": len(texts),
              "pages": len(notes), "records": len(records),
              "failed": len(errors), "errors": errors[:20],
              "path": getattr(rep_pages or rep_recs, "path", "")})
    if errors:
        env.warn("some_refused",
                 f"{len(errors)} елементів не пройшли перевірку — решта занесена; "
                 f"виправте й додайте окремо")
    if unreadable:
        env.warn("unreadable_files",
                 f"{unreadable} файлів не читаються як JSON — їх пропущено")
    env.suggest("records.audit", "чексуми книги: чи немає дір у нумерації")
    return env


# ── чексуми ──────────────────────────────────────────────────────────────────
class AuditArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    profile: str = Field(default="", description="профіль книги; типово — за справою")


@op("records.audit", summary="Чексуми книги: діри в нумерації й розбіжність із підсумком",
    args=AuditArgs, mutates=False, agent=False, section="research")
def records_audit(a: AuditArgs) -> Envelope:
    """🔴 Єдиний доказ повноти, який не є самозвітом того, хто читав.

    Метрична книга нумерує народження й смерті двома незалежними лічильниками
    (мужеска / женска) і сама себе рахує наприкінці місяця. Діра в нумерації —
    це пропущений акт із точністю до номера; розбіжність із підсумком — або
    пропуск, або неправильно прочитаний рік.

    Секція без дір і зі збіжним підсумком **доведено повна**. Це інша річ, ніж
    «агент сказав, що все прочитав».
    """
    from nyshporka.records import checksum

    got = _case(a.case)
    if isinstance(got, Envelope):
        return got
    ref, cf = got
    if cf is None:
        return fail(f"по справі {ref.shifra} ще нічого не занесено")

    try:
        prof = _profile(a.profile, ref.key)
    except ValueError as exc:
        return fail(str(exc))

    result = checksum.audit(cf, prof)
    env = ok(result)
    if not result["clean"]:
        env.warn("book_checksum_failed",
                 "; ".join(result["problems"][:5])
                 + (f" (+{len(result['problems']) - 5})"
                    if len(result["problems"]) > 5 else ""))
        env.suggest("records.prep",
                    "нарізати саме ті скани, де діри, і перечитати їх точково")
    return env


# ── звід двох вичиток ────────────────────────────────────────────────────────
class MergeArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    a: str = Field(description="тека JSON першої вичитки")
    b: str = Field(description="тека JSON другої вичитки")
    profile: str = Field(default="", description="профіль книги; типово — за справою")
    apply: bool = Field(default=False,
                        description="занести узгоджене; без цього — сухий прогін")
    tasks: str = Field(default="", description="куди скласти чергу спірних місць")


@op("records.merge", summary="Звести дві незалежні вичитки: збіг у сховище, спір у чергу",
    args=MergeArgs, mutates=True, agent=False, section="research")
def records_merge(a: MergeArgs) -> Envelope:
    """🔴 Один прохід джерелом істини не є, і це виміряно.

    Модель подає помилкове прочитання так само впевнено, як правильне: у пілоті
    на цьому матеріалі одна гілка дала повнішу структуру, але гірші прізвища —
    і хіт роду в ній був загублений мовчки. Тому в сховище без ескалації йде
    тільки те, на чому дві незалежні вичитки зійшлися, а розбіжність лягає в
    чергу на людський розсуд.

    Орфографічні варіанти («Мурлыка»/«Мурлика») відсіюються нормалізацією й
    чергу не засмічують.
    """
    from nyshporka.records import consensus

    got = _case(a.case)
    if isinstance(got, Envelope):
        return got
    ref, _ = got

    dirs = {}
    for label, raw in (("a", a.a), ("b", a.b)):
        folder = Path(raw).expanduser()
        if not folder.is_dir():
            return fail(f"гілки «{label}» немає на диску: {folder}")
        dirs[label] = folder

    try:
        prof = _profile(a.profile, ref.key)
    except ValueError as exc:
        return fail(str(exc))

    from nyshporka.pagestore import store
    from nyshporka.records import tiles

    prefer = prof.consensus.get("prefer", "a")
    recs_a, notes_a, err_a = consensus.load_branch(dirs["a"])
    recs_b, notes_b, err_b = consensus.load_branch(dirs["b"])
    if not (recs_a or recs_b):
        return fail("в обох гілках жодного розібраного акту — нема чого зводити")

    res = consensus.merge(recs_a, recs_b, notes_a, notes_b,
                          prefer_a=(prefer == "a"), profile=prof)
    # Черга ескалації несе адресу тайла, а не лише текст: спірне поле вирішує
    # око, і воно мусить дивитись саме на той рядок, а не шукати його по книзі.
    queue = consensus.conflict_tasks(res.conflicts, tiles.default_out_dir(), ref.key)

    if a.apply:
        store.annotate_pages(ref, res.notes)
        store.add_records(ref, res.records)
    if a.tasks:
        dest = Path(a.tasks).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(queue, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    env = ok({"case": ref.key, "shifra": ref.shifra, "applied": a.apply,
              "profile": prof.name, "prefer": prefer,
              "records_a": len(recs_a), "records_b": len(recs_b),
              "merged": len(res.records), "agreed_fields": res.agreed_fields,
              "conflicts": len(res.conflicts), "scans_to_escalate": len(queue),
              "only_a": res.only_a, "only_b": res.only_b,
              "tasks_path": str(Path(a.tasks).expanduser()) if a.tasks else "",
              "load_errors": err_a + err_b})
    if not a.apply:
        env.warn("dry_run", "сухий прогін — у сховище нічого не занесено; "
                            "додайте apply, коли перелік спірних місць влаштує")
    if res.only_a or res.only_b:
        # 🔴 Акт, який побачила лише одна гілка, — не дрібниця: або друга його
        # пропустила, або перша вигадала. Мовчазне злиття ховає обидва випадки.
        env.warn("seen_by_one_branch",
                 f"лише гілка A бачила {len(res.only_a)} актів, лише B — "
                 f"{len(res.only_b)}: це або пропуск однієї, або вигадка другої")
    if err_a + err_b:
        env.warn("branch_load_errors",
                 f"{len(err_a + err_b)} файлів гілок не прочитались: "
                 + "; ".join((err_a + err_b)[:3]))
    env.suggest("records.audit", "після зводу — чексуми книги")
    return env
