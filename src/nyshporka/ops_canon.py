"""⚙️🌳 Канон роду: перевірка, індекс, наступний ID, доказ у стор.

🔴 Команд редагування тут немає і не буде. Картки канону правлять файлами —
агент за скілом `keep-canon` або людина в редакторі. Ці операції — механіка
навколо правки: що зламали, що перебудувати, який ID вільний, куди покласти
кроп так, щоб цитата не провисла.

🔴 Усі — `agent=False` з тієї самої причини, що й `ops_records`: перелік
MCP-tool'ів має стелю (`mcp.server.TOOL_LIMIT`). Агентові, який правит канон,
MCP і не потрібен — у нього вже є доступ до файлів, а операції доступні як
`nysh canon …` і `nysh op canon.check --args '{…}'`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


def _root() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().root


class CheckArgs(BaseModel):
    hash: bool = Field(default=False,
                       description="перерахувати sha256 доказів (повільніше, ловить підміну файлу)")


@op("canon.check", summary="Чи цілий канон: схема, зв'язки, хронологія, докази",
    args=CheckArgs, mutates=False, agent=False, gui=False, section="research")
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
    env = ok(rep.as_dict())
    if not rep.ok:
        env.warn("canon_errors",
                 f"{rep.count('ERROR')} помилок у каноні — індекс і сайт будуть "
                 f"брехати, доки їх не виправлено")
    elif not a.hash:
        env.suggest("canon.index", "канон цілий — перебудувати базу роду")
    return env


@op("canon.index", summary="Перебудувати базу роду з карток канону",
    mutates=True, agent=False, gui=False, section="research",
    next_hints=(("cases.build", "реєстр справ читає базу роду"),))
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
    return env


class NewIdArgs(BaseModel):
    kind: Literal["person", "family", "place"] = Field(description="тип нової картки")


@op("canon.new_id", summary="Наступний вільний ID для нової картки",
    args=NewIdArgs, mutates=False, agent=False, gui=False, section="research")
def canon_new_id(a: NewIdArgs) -> Envelope:
    """Максимум + 1; дірки не займаються — зниклий ID міг лишитись у нотатках.

    🔴 Нічого не резервує: два виклики підряд дадуть той самий ID, доки картку
    не записано. Писати картку одразу після виклику.
    """
    from nyshporka.canon.ids import new_id

    root = _root()
    return ok({"kind": a.kind, "id": new_id(root / "data" / "canonical", a.kind)})


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
    args=ImportArgs, mutates=True, agent=False, gui=False, section="research",
    next_hints=(("canon.check", "подивитись, що дерево принесло з собою"),))
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


@op("evidence.add", summary="Покласти доказ-кроп у постійний стор (сірий JPEG ≤ 2 МБ)",
    args=EvidenceAddArgs, mutates=True, agent=False, gui=False, section="research")
def evidence_add(a: EvidenceAddArgs) -> Envelope:
    """Доказ у стор ДО факту в каноні — шлях з відповіді йде в `media[]` і цитату."""
    from nyshporka.canon import evidence as E

    try:
        got = E.add(_root(), Path(a.file).expanduser(), a.provenance,
                    name=a.name, overwrite=a.overwrite)
    except E.EvidenceError as exc:
        return fail(str(exc))
    env = ok(got.as_dict())
    if got.existed:
        env.warn("already_secured", "цей самий доказ уже лежав у сторі — нічого не змінено")
    return env
