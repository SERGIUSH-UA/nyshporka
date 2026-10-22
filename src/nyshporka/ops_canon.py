"""⚙️🌳 Канон роду: перевірка, індекс, наступний ID, доказ у стор.

🔴 Команд редагування тут немає і не буде. Картки канону правлять файлами —
агент за скілом `keep-canon` або людина в редакторі. Ці операції — механіка
навколо правки: що зламали, що перебудувати, який ID вільний, куди покласти
кроп так, щоб цитата не провисла.

🔴 Усі — `agent=False` з тієї самої причини, що й `ops_records`: стартовий перелік агента (`nysh ops --agent`)
тримається коротким. Операції доступні як `nysh canon …` і
`nysh op canon.check --args '{…}'`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


def _root() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().proot


class CheckArgs(BaseModel):
    hash: bool = Field(default=False,
                       description="перерахувати sha256 доказів (повільніше, ловить підміну файлу)")


@op("canon.check", summary="Чи цілий канон: схема, зв'язки, хронологія, докази",
    args=CheckArgs, mutates=False, section="research",
    tier="core", scope="project", skill="keep-canon",
    when="перевірити канон після правки картки: схема, зв'язки, докази")
def canon_check(a: CheckArgs) -> Envelope:
    """Перевірка всього канону після правки.

    🔴 Відповідь `ok` навіть коли є помилки: помилки канону — це ДАНІ
    перевірки, а не збій операції. Код повернення 1 ставить командний рядок,
    якщо `errors > 0`, — щоб її можна було вішати на pre-commit.
    """
    from nyshporka.canon import check as C

    root = _root()
    if not (root / "data" / "canonical").is_dir():
        env = ok({"root": str(root / "data" / "canonical"), "loaded": {},
                  "errors": 0, "warnings": 0, "info": 0, "issues": [], "hashed": a.hash})
        env.warn("no_canon", "канону в просторі ще немає: теки data/canonical не існує. "
                             "Засіяти можна з GEDCOM (`nysh canon import`) або першою "
                             "карткою особи за скілом keep-canon")
        return env
    rep = C.check(root, hash_evidence=a.hash)
    data = rep.as_dict()
    data["refs"] = _refs(rep.canon, [(i.get("where"), i.get("text")) for i in data.get("issues", [])])
    env = ok(data)
    if not rep.ok:
        env.warn("canon_errors",
                 f"{rep.count('ERROR')} помилок у каноні — індекс і сайт будуть "
                 f"брехати, доки їх не виправлено")
    else:
        # Зелений канон — точка, до якої варто вміти повернутись: агент кличе
        # перевірку після кожної правки (скіл keep-canon), тож окремого кроку
        # «зберегти» йому не треба. Лише там, де історію завела Нишпорка.
        from nyshporka.core import vcs as V

        V.autosave_env(env, "Канон перевірено — зелений стан збережено")
        if not a.hash:
            env.suggest("canon.index", "канон цілий — перебудувати базу роду")
    return env


@op("canon.index", summary="Перебудувати базу роду з карток канону",
    mutates=True, gui=False, section="research",
    next_hints=(("cases.build", "реєстр справ читає базу роду"),),
    scope="project", skill="keep-canon",
    when="перебудувати базу роду після правки карток канону")
def canon_index(_a: NoArgs) -> Envelope:
    """Картки `data/canonical/**` → `data/derived/nyshporka.sqlite` і JSON для дерева.

    Заразом дописує в маніфест доказів, які картки на який доказ посилаються
    (`cited_by`): руками це поле застаріває першим.
    """
    from nyshporka.canon import check as C
    from nyshporka.canon import evidence as E
    from nyshporka.storage.reindex import reindex

    root = _root()
    if not (root / "data" / "canonical").is_dir():
        return fail("канону в просторі немає (data/canonical) — індексувати нічого")
    try:
        rep = reindex(root)
    except Exception as exc:
        return fail(f"індекс не зібрано: {type(exc).__name__}: {exc}. "
                    f"Причину покаже `nysh canon check`")
    canon = C.load(root)
    cited = E.refresh_cited_by(root, canon.files)
    env = ok({"persons": rep.persons, "families": rep.families, "places": rep.places,
              "sources": rep.sources, "facts": rep.facts,
              "sqlite": str(rep.sqlite_path), "evidence": cited})
    if cited["unreferenced"]:
        env.warn("evidence_unreferenced",
                 f"{len(cited['unreferenced'])} доказів у маніфесті вже не цитує жодна "
                 f"картка — лишити, процитувати чи прибрати вирішує людина")
    from nyshporka.core import vcs as V

    V.autosave_env(env, f"Канон проіндексовано: {rep.persons} осіб, {rep.facts} фактів")
    return env


class NewIdArgs(BaseModel):
    kind: Literal["person", "family", "place", "hypothesis"] = Field(
        description="тип нової картки")


@op("canon.new_id", summary="Наступний вільний ID для нової картки",
    args=NewIdArgs, mutates=False, gui=False, section="research",
    scope="project", skill="keep-canon",
    when="новий ID для картки особи, події чи гіпотези")
def canon_new_id(a: NewIdArgs) -> Envelope:
    """Максимум + 1; дірки не займаються — зниклий ID міг лишитись у нотатках.

    🔴 Нічого не резервує: два виклики підряд дадуть той самий ID, доки картку
    не записано. Писати картку одразу після виклику.
    """
    from nyshporka.canon.ids import new_id

    root = _root()
    return ok({"kind": a.kind, "id": new_id(root / "data" / "canonical", a.kind)})


class NextArgs(BaseModel):
    limit: int = Field(default=3, ge=0, description="скільки рішень показати")


@op("canon.next", summary="Що людині вирішити першим: відкриті гіпотези роду за вагою",
    args=NextArgs, mutates=False, section="research",
    tier="core", scope="project", skill="keep-canon",
    when="що по роду відкрите й чекає рішення людини")
def canon_next(a: NextArgs) -> Envelope:
    """Ранжування з карток `data/canonical/hypotheses`, а не з нотаток.

    Кожне рішення: твердження, що його розв'яже, хіти з готовою командою кропу.
    Людині показувати не більше трьох за раз: решта чекає, доки ці вирішено.
    """
    from nyshporka.canon.next import next_decisions

    root = _root()
    got = next_decisions(root, a.limit)
    env = ok(got)
    if _no_canon(env):
        pass
    elif not (got["open"] or got["awaiting"] or got["closed"]):
        env.warn("no_hypotheses", "карток гіпотез ще немає: відкрите по роду ніде не "
                                  "записано. Як завести — скіл keep-canon, розділ «Гіпотеза»")
    return env


# ── читання канону для консолі ───────────────────────────────────────────────
# Екрани «Канон» і «Гіпотези» лише показують: картку правлять файлом, і
# консоль не має тут жодної кнопки «змінити поле».

#: Кошик канону за видом картки (як теки `data/canonical/<вид>`).
CARD_KINDS = ("persons", "families", "places", "sources", "hypotheses")


def _title(canon: Any, kind: str, ent: Any) -> str:
    if kind == "persons":
        return str(ent.primary_name)
    if kind == "families":
        def who(pid: str | None) -> str:
            p = canon.persons.get(pid) if pid else None
            return str(p.primary_name) if p is not None else (pid or "?")
        return f"{who(ent.husband)} × {who(ent.wife)}"
    if kind == "places":
        return str(ent.name)
    if kind == "sources":
        return str(ent.title)
    return str(ent.claim)


#: ID картки канону в тексті чи значенні поля: особа, родина, місце, гіпотеза, джерело.
_REF = re.compile(r"\b(?:I|F|PL|H)\d{2,}\b|\bS_[A-Za-z0-9_]+\b")


def _refs(canon: Any, *blobs: Any) -> dict[str, str]:
    """ID → назва для кожного ID, що трапився в переданих даних.

    🔴 Консоль показувала «Чоловік I9001 · Дружина I9002», «PL9001», «[[I9012]]»
    там, де людина чекає імен (прохід консолі 22.10.2026). Назви кладе сервер:
    канон у нього вже завантажений, а браузер мусив би тягнути всі картки.
    """
    import json

    text = " ".join(b if isinstance(b, str) else json.dumps(b, ensure_ascii=False, default=str)
                    for b in blobs)
    out: dict[str, str] = {}
    for rid in set(_REF.findall(text)):
        for kind in CARD_KINDS:
            ent = getattr(canon, kind).get(rid)
            if ent is not None:
                out[rid] = _title(canon, kind, ent)
                break
    return out


def _haystack(kind: str, ent: Any, title: str) -> str:
    extra: list[str] = []
    if kind == "persons":
        extra = [n.form for n in ent.names] + list(ent.aliases)
    elif kind == "places":
        extra = list(ent.name_variants.values())
    return " ".join([ent.id, title, *extra]).casefold()


def _citations(ent: Any) -> int:
    own = len(getattr(ent, "citations", None) or [])
    return own + sum(len(f.citations) for f in getattr(ent, "facts", None) or [])


def _no_canon(env: Envelope) -> bool:
    """Проєкт без канону — порожній стан із поясненням, а не відмова.

    Щойно заведений проєкт канону ще не має, і екрани «Канон», «Гіпотези» й
    Огляд показували на ньому червоне «Не вийшло» (прохід консолі 22.10.2026).
    """
    from nyshporka.core import workspace as W

    if W.workspace().canonical.is_dir():
        return False
    env.warn("no_canon", "канону в проєкті ще немає: теки data/canonical не існує. "
                         "Засіяти можна з GEDCOM (`nysh canon import`) або першою "
                         "карткою особи за скілом keep-canon")
    return True


def _loaded() -> tuple[Path, Any]:
    from nyshporka.canon.check import load

    root = _root()
    return root, load(root)


class CardsArgs(BaseModel):
    kind: Literal["", "persons", "families", "places", "sources", "hypotheses"] = Field(
        default="", description="вид карток; порожньо — усі")
    q: str = Field(default="", description="підрядок ID, імені, назви чи варіанта")
    limit: int = Field(default=200, ge=1, le=5000, description="скільки рядків")


@op("canon.cards", summary="Картки канону списком: особи, родини, місця, джерела, гіпотези",
    args=CardsArgs, section="research", tier="situational", scope="project",
    skill="keep-canon", when="перелік карток канону — знайти особу чи родину за іменем")
def canon_cards(a: CardsArgs) -> Envelope:
    root, canon = _loaded()
    q = a.q.strip().casefold()
    rows: list[dict[str, Any]] = []
    for kind in ([a.kind] if a.kind else CARD_KINDS):
        for eid, ent in sorted(getattr(canon, kind).items()):
            title = _title(canon, kind, ent)
            if q and q not in _haystack(kind, ent, title):
                continue
            rows.append({"id": eid, "kind": kind, "title": title,
                         "private": bool(getattr(ent, "private", False)),
                         "facts": len(getattr(ent, "facts", None) or []),
                         "citations": _citations(ent),
                         "file": canon.files[eid].relative_to(root).as_posix()})
    env = ok({"counts": canon.counts(), "found": len(rows), "rows": rows[:a.limit]})
    _no_canon(env)
    return env


class CardArgs(BaseModel):
    id: str = Field(description="ID картки: I…, F…, PL…, S_…, H…")


@op("canon.card", summary="Одна картка канону: поля, докази, гіпотези, що її стосуються",
    args=CardArgs, section="research", tier="rare", scope="project", skill="keep-canon",
    when="подивитись картку канону з доказами й зауваженнями перевірки")
def canon_card(a: CardArgs) -> Envelope:
    from nyshporka.canon.check import check
    from nyshporka.core import workspace as W

    root = _root()
    if not W.workspace().canonical.is_dir():
        return fail("канону в проєкті немає (data/canonical)")
    rep = check(root)
    canon = rep.canon
    kind = next((k for k in CARD_KINDS if a.id in getattr(canon, k)), "")
    if not kind:
        return fail(f"картки «{a.id}» у каноні немає")
    ent = getattr(canon, kind)[a.id]
    rel = canon.files[a.id].relative_to(root).as_posix()
    issues = [i.as_dict() for i in rep.issues
              if i.where == rel or i.where.split(":")[0] == a.id or a.id in i.where.split()]
    hyps = [{"id": hid, "claim": h.claim, "status": h.status}
            for hid, h in sorted(canon.hypotheses.items()) if a.id in h.about]
    card = ent.model_dump(mode="json", exclude={"notes"})
    notes = getattr(ent, "notes", "") or ""
    return ok({"id": a.id, "kind": kind, "title": _title(canon, kind, ent),
               "private": bool(getattr(ent, "private", False)), "file": rel,
               "card": card, "notes": notes,
               "issues": issues, "hypotheses": hyps,
               "refs": _refs(canon, card, notes, issues, hyps)})


class HypsArgs(BaseModel):
    status: Literal["", "open", "awaiting", "closed"] = Field(
        default="", description="лише цей стан; порожньо — усі, закриті в кінці")


@op("canon.hyps", summary="Гіпотези роду: лічильники і список у порядку рішень",
    args=HypsArgs, section="research", tier="situational", scope="project",
    skill="keep-canon", when="усі гіпотези роду зі станом — не лише три найважливіші")
def canon_hyps(a: HypsArgs) -> Envelope:
    from nyshporka.canon.next import rank

    _, canon = _loaded()
    counts = {s: sum(1 for h in canon.hypotheses.values() if h.status == s)
              for s in ("open", "awaiting", "closed")}
    rows = []
    for d in rank(canon, closed=True):
        if a.status and d.status != a.status:
            continue
        h = canon.hypotheses[d.id]
        rows.append({"id": d.id, "claim": d.claim, "status": d.status,
                     "decides": d.decides, "weight": d.weight, "hits": len(d.hits),
                     "strong": any(x["strength"] == "strong" for x in d.hits),
                     "updated": h.updated.isoformat()})
    env = ok({"counts": counts, "rows": rows, "refs": _refs(canon, rows)})
    _no_canon(env)
    return env


@op("canon.hyp", summary="Одна гіпотеза: хіти з командою кропу, факти, що на неї чекають",
    args=CardArgs, section="research", tier="rare", scope="project", skill="keep-canon",
    when="розібрати одну гіпотезу: хіти з кропами й факти, що від неї залежать")
def canon_hyp(a: CardArgs) -> Envelope:
    from nyshporka.canon.next import rank

    root, canon = _loaded()
    h = canon.hypotheses.get(a.id)
    if h is None:
        return fail(f"гіпотези «{a.id}» у каноні немає")
    d = next(x for x in rank(canon, closed=True) if x.id == a.id)
    card = h.model_dump(mode="json", exclude={"notes", "hits"})
    return ok({"id": a.id, "file": canon.files[a.id].relative_to(root).as_posix(),
               "card": card, "notes": h.notes or "", "weight": d.weight, "hits": d.hits,
               "facts": d.facts, "versus": d.versus,
               "refs": _refs(canon, card, h.notes or "", d.facts, d.versus)})


class ImportArgs(BaseModel):
    file: str = Field(description="файл .ged — експорт дерева з іншої програми")
    source_id: str = Field(default="S_GEDCOM", description="ID картки джерела для цього файлу")
    source_title: str = Field(default="", description="назва джерела; порожньо — з імені файлу")
    authority: str = Field(default="", description="звідки експорт: MyHeritage, Geni, …")
    alias_prefix: str = Field(default="GED", description="префікс для RIN записів чужої програми")
    private_born_after: int = Field(default=1946,
                                    description="без смерті й народжені від цього року — живі")
    trust_tree: bool = Field(default=False,
                             description="факти з датою чи місцем — confirmed, а не hypothesis")
    dry_run: bool = Field(default=False, description="лише порахувати, нічого не писати")


@op("canon.import", summary="Засіяти порожній канон із GEDCOM (злиття немає)",
    args=ImportArgs, mutates=True, gui=False, section="research",
    next_hints=(("canon.check", "подивитись, що дерево принесло з собою"),),
    scope="project", skill="keep-canon",
    when="засіяти порожній канон роду з GEDCOM")
def canon_import(a: ImportArgs) -> Envelope:
    """Одноразове засівання: особи, родини, місця й одне джерело — сам файл.

    🔴 Лише в порожній канон; далі канон ведуть файлами. Факти за замовчуванням
    `hypothesis`: дерево з іншої програми — переказ джерел, а не джерело.
    """
    from nyshporka.canon import gedcom as G

    opts = G.Options(source_id=a.source_id, source_title=a.source_title,
                     authority=a.authority, alias_prefix=a.alias_prefix,
                     private_born_after=a.private_born_after, trust_tree=a.trust_tree)
    try:
        rep = G.import_file(_root(), Path(a.file).expanduser(), opts, dry_run=a.dry_run)
    except G.GedcomError as exc:
        return fail(str(exc))
    env = ok(rep.as_dict())
    if rep.private:
        env.warn("private_persons",
                 f"{rep.private} осіб позначено живими (private): без дати смерті й "
                 f"народжені від {a.private_born_after} або без року народження")
    if a.dry_run:
        env.warn("dry_run", "пробний прогін — нічого не записано")
    return env


class EvidenceAddArgs(BaseModel):
    file: str = Field(description="зображення-вирізка (кроп рядка)")
    provenance: str = Field(description="походження: архів чи зібрання, латиницею («dahmo», «oral»)")
    name: str = Field(default="", description="ім'я файлу в сторі; порожньо — як у вихідного")
    overwrite: bool = Field(default=False, description="замінити наявний доказ з іншим вмістом")
    origin_case: str = Field(default="", description="з якої справи вирізано рядок (ключ справи)")
    origin_page: str = Field(default="", description="скан, з якого вирізано рядок")
    origin_line: int | None = Field(default=None, ge=1, description="рядок (з одиниці)")


@op("evidence.add", summary="Покласти доказ-кроп у постійний стор (сірий JPEG ≤ 2 МБ)",
    args=EvidenceAddArgs, mutates=True, section="research",
    tier="core", scope="mixed", skill="keep-canon",
    when="покласти доказ-кроп у стор перед внесенням факту в канон")
def evidence_add(a: EvidenceAddArgs) -> Envelope:
    """Доказ у стор ДО факту в каноні — шлях з відповіді йде в `media[]` і цитату."""
    from nyshporka.canon import evidence as E

    # Походження — лише повне: справа без скану чи рядка нічого не позначить
    # у Пошуку, а виглядала б як позначка.
    parts = (a.origin_case.strip(), a.origin_page.strip(), a.origin_line)
    if any(parts) and not all(parts):
        return fail("походження кропу — разом справа, скан і рядок "
                    "(`--from <справа>:<скан>:<рядок>`)")
    origin = ({"case": parts[0], "page": parts[1], "line": parts[2]}
              if all(parts) else None)
    try:
        got = E.add(_root(), Path(a.file).expanduser(), a.provenance,
                    name=a.name, overwrite=a.overwrite, origin=origin)
    except E.EvidenceError as exc:
        return fail(str(exc))
    env = ok(got.as_dict())
    if got.existed:
        env.warn("already_secured", "цей самий доказ уже лежав у сторі — нічого не змінено")
    return env
