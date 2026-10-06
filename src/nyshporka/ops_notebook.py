"""📓 Операції нотатника справи (`nysh note …`).

Нотатник — секція `notes` у файлі сховища сторінок (`pagestore.notebook`):
звірене оком читання рядка, опис справи, помилка опису архіву, копія деінде,
особисте. Загальне знання їде в пул окремо від тексту (`note.push`), особисте
не їде ніколи.

🔴 Усі — `agent=False`: стартовий перелік агента тримається коротким, а
агентові вистачає командного рядка; скіл `case-notebook` веде саме туди.

🔴 `push`/`pull` — `private=True`: вони йдуть у пул від імені людини з її
ключем, і чужа вкладка цього робити не може.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "research"


def _ref(case: str) -> Any:
    from nyshporka.pagestore import store

    return store.resolve_case(case)


def _brief(n: Any) -> dict[str, Any]:
    """Запис для відповіді: ключові поля, без порожніх."""
    raw = {k: v for k, v in n.model_dump(mode="json").items()
           if v not in (None, "", [], {})}
    raw["share"] = n.share
    return raw


# ── дописати ─────────────────────────────────────────────────────────────────
class NoteAddArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    kind: str = Field(description="about | catalog-error | copy | note")
    text: str = Field(default="", description="текст запису")
    field: str = Field(default="", description="catalog-error: title|years|shifra|extent|other")
    archive_says: str = Field(default="", description="catalog-error: як в описі архіву")
    actually: str = Field(default="", description="catalog-error: як насправді")
    other: str = Field(default="", description="copy: шифра або ключ іншої справи")
    relation: str = Field(default="", description="copy: copy|draft|duplicate|continuation|original|other")
    page: str = Field(default="", description="сторінка, якщо запис про неї")
    share: bool = Field(default=False, description="позначити до віддачі в пул")
    reader: str = Field(default="agent", description="agent | human | agent+human")
    model: str = Field(default="", description="модель агента")
    author: str = Field(default="", description="хто записав (у пул не їде)")
    supersedes: str = Field(default="", description="uid запису, який цей замінює")


@op("note.add", summary="Дописати запис у нотатник справи", args=NoteAddArgs,
    mutates=True, agent=False, section=SECTION)
def note_add(a: NoteAddArgs) -> Envelope:
    """Опис справи, помилка опису архіву, копія деінде або особисте.

    🔴 Особисте («тут жив мій дід») — `--kind note`, і воно лишається вдома
    навіть із `--share`. Загальне знання про справу пишеться окремим записом:
    тоді його можна віддати, не віддаючи родинного.
    """
    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import CaseNote

    if a.kind == "reading":
        return fail("читання рядка пишеться через `note read`: йому потрібні "
                    "прогін, сторінка й номер рядка")
    try:
        ref = _ref(a.case)
        n = CaseNote.model_validate({
            "kind": a.kind, "text": a.text, "field": a.field or None,
            "archive_says": a.archive_says, "actually": a.actually,
            "other": a.other, "relation": a.relation or None, "page": a.page,
            "share": a.share, "reader": a.reader, "model": a.model,
            "author": a.author, "supersedes": a.supersedes})
    except (ValidationError, ValueError) as exc:
        return fail(str(exc))
    return _written(ref, store.add_notes(ref, [n]), [n])


def _written(ref: Any, report: Any, notes: list[Any]) -> Envelope:
    if report.errors:
        return fail("; ".join(e["error"] for e in report.errors))
    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict(),
              "notes": [_brief(n) for n in notes]})
    if any(n.share for n in notes):
        from nyshporka.pagestore.notebook import wire_note
        from nyshporka.share.gates import check_note

        for n in notes:
            v = check_note(wire_note(n)) if n.share else None
            if v is not None and not v.passed:
                env.warn("gate", f"{n.uid[:8]}: у пул не пройде — {v.refusals[0]}")
        env.suggest("note.push", "віддати позначене в пул")
    return env


class NoteReadArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    page: str = Field(description="сторінка прогону: 0031, p0531")
    line: int = Field(description="номер рядка з 1, як у `text ctx`")
    text: str = Field(description="звірене читання рядка, дослівно")
    run: str = Field(default="", description="прогін; порожньо — перший прогін справи")
    confidence: str = Field(default="", description="high | medium | low")
    uncertain: str = Field(default="", description="кома-список непевних слів")
    share: bool = Field(default=False, description="позначити до віддачі в пул")
    reader: str = Field(default="agent", description="agent | human | agent+human")
    model: str = Field(default="", description="модель агента")
    author: str = Field(default="", description="хто записав (у пул не їде)")
    supersedes: str = Field(default="", description="uid запису, який цей замінює")


@op("note.read", summary="Записати звірене оком читання рядка", args=NoteReadArgs,
    mutates=True, agent=False, section=SECTION)
def note_read(a: NoteReadArgs) -> Envelope:
    """Читання рядка з прив'язкою до прогону, рамки й того, що прочитав рушій.

    🔴 Не голос прогону: око читає вибрані рядки, а не сторінку. Тому запис
    іде в нотатник, пошук показує його поряд із рядком, а знаменник справи
    від нього не змінюється.
    """
    from pydantic import ValidationError

    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import CaseNote

    try:
        ref = _ref(a.case)
    except ValueError as exc:
        return fail(str(exc))
    got = NB.line_anchor(a.run or ref.key, a.page, a.line)
    if got.get("error"):
        return fail(got["error"])
    try:
        n = CaseNote.model_validate({
            "kind": "reading", "page": got["page"], "text": a.text.strip(),
            "line": {"run": got["run"], "line_no": a.line, "bbox": got["bbox"]},
            "was": {"run": got["run"], "text": got["text"]} if got["text"] else None,
            "confidence": a.confidence or None,
            "uncertain": [w.strip() for w in a.uncertain.split(",") if w.strip()],
            "share": a.share, "reader": a.reader, "model": a.model,
            "author": a.author, "supersedes": a.supersedes})
    except ValidationError as exc:
        return fail(str(exc))
    env = _written(ref, store.add_notes(ref, [n]), [n])
    if env.ok and got["bbox"] is None:
        env.warn("no_bbox", f"у прогоні {got['run']} рамки рядка немає — запис "
                            "лишиться текстовим і на чужих кадрах не ляже на рядок")
    if env.ok and got["text"].strip() == n.text:
        env.warn("same_as_engine", "читання збігається з рушієм — запис нічого не "
                                   "виправляє; це підтвердження, а не правка")
    return env


# ── подивитись ───────────────────────────────────────────────────────────────
class NoteListArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    kind: str = Field(default="", description="лише цей тип")
    shared: bool = Field(default=False, description="лише позначене до віддачі")
    pool: str = Field(default="all", description="all | own | pool")
    history: bool = Field(default=False, description="усі записи журналу, з заміненими")


@op("note.list", summary="Нотатник справи: чинні записи, хто й коли",
    args=NoteListArgs, mutates=False, agent=False, section=SECTION)
def note_list(a: NoteListArgs) -> Envelope:
    """Згортка журналу: замінене й відкликане не показується без `history`."""
    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store

    try:
        ref = _ref(a.case)
    except ValueError as exc:
        return fail(str(exc))
    cf = store.load_case(ref)
    notes = list(cf.notes) if cf else []
    own = {"own": True, "pool": False}.get(a.pool)
    picked = notes if a.history else NB.live(notes, own=own)
    if a.history and own is not None:
        picked = [n for n in picked if (n.origin is None) == own]
    if a.kind:
        picked = [n for n in picked if n.kind == a.kind]
    if a.shared:
        picked = [n for n in picked if n.share]
    by_kind: dict[str, int] = {}
    for n in picked:
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
    return ok({"case": ref.key, "shifra": ref.shifra, "total": len(notes),
               "shown": len(picked), "by_kind": by_kind,
               "pages_noted": len(cf.pages) if cf else 0,
               "notes": [_brief(n) for n in picked]})


# ── позначка віддачі й відкликання ───────────────────────────────────────────
class NoteShareArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    uids: list[str] = Field(description="uid записів (досить перших 8 знаків)")
    share: bool = Field(default=True, description="false — повернути додому")


@op("note.share", summary="Позначити записи до віддачі в пул або повернути додому",
    args=NoteShareArgs, mutates=True, agent=False, section=SECTION)
def note_share(a: NoteShareArgs) -> Envelope:
    """Позначка — новий запис журналу, що замінює старий тим самим змістом.

    Так відкликання вже відданого доходить до пулу (`note.push` пошле голе
    `retracts`), а зміст домашньої заміни назовні не потрапляє.
    """
    return _rewrite(a.case, a.uids, lambda n: n.model_copy(
        update={"share": a.share}), skip=lambda n: n.share == a.share)


class NoteRetractArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    uids: list[str] = Field(description="uid записів (досить перших 8 знаків)")


@op("note.retract", summary="Відкликати записи нотатника", args=NoteRetractArgs,
    mutates=True, agent=False, section=SECTION)
def note_retract(a: NoteRetractArgs) -> Envelope:
    """Відкликання — запис журналу; віддане пул прибере після `note.push`."""
    from nyshporka.pagestore.models import CaseNote

    return _rewrite(a.case, a.uids,
                    lambda n: CaseNote(kind=n.kind, retracts=n.uid, author=n.author),
                    skip=lambda n: False, chain=False)


def _rewrite(case: str, uids: list[str], make: Any, *, skip: Any,
             chain: bool = True) -> Envelope:
    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import _new_uid, _utcnow

    try:
        ref = _ref(case)
    except ValueError as exc:
        return fail(str(exc))
    cf = store.load_case(ref)
    alive = NB.live(cf.notes, own=True) if cf else []
    new: list[Any] = []
    missing: list[str] = []
    for u in uids:
        hit = [n for n in alive if n.uid.startswith(u.strip())]
        if len(hit) != 1:
            missing.append(u)
            continue
        n = hit[0]
        if skip(n):
            continue
        made = make(n)
        if chain:
            made = made.model_copy(update={"uid": _new_uid(), "created": _utcnow(),
                                           "supersedes": n.uid})
        new.append(made)
    if missing:
        return fail(f"чинних своїх записів не знайдено (або префікс неоднозначний): "
                    f"{', '.join(missing)}")
    if not new:
        return ok({"case": ref.key, "shifra": ref.shifra, "added": [], "notes": []})
    return _written(ref, store.add_notes(ref, new), new)


# ── пул ──────────────────────────────────────────────────────────────────────
class NotePushArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    pages: bool = Field(default=True, description="віддати й зведення переглянутих сторінок")
    dry_run: bool = Field(default=False, description="показати, що поїде, нічого не слати")
    base: str = Field(default="", description="інша домівка пулу")


@op("note.push", summary="Віддати загальне знання про справу в пул",
    args=NotePushArgs, mutates=True, agent=False, section=SECTION, private=True)
def note_push(a: NotePushArgs) -> Envelope:
    """Позначені записи + зведення переглянутих сторінок → нотатник книги в пулі.

    🔴 Окремо від тексту: дописати нотатник можна й до справи, яку віддав
    хтось інший. 🔴 Ворота — ті самі, що в пулі: запис, якого вони не
    пустять, сюди не відправляється й названий у відповіді поштучно.
    """
    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store
    from nyshporka.share import catalog
    from nyshporka.share.gates import check_note

    try:
        ref = _ref(a.case)
    except ValueError as exc:
        return fail(str(exc))
    cf = store.load_case(ref)
    if cf is None:
        return fail(f"у сховищі сторінок справи {ref.shifra or ref.key} нічого немає")
    entries, refused = [], []
    for w in NB.outgoing(cf):
        v = check_note(w)
        if v.passed:
            entries.append(w)
        else:
            refused.append({"uid": w.get("uid", ""), "kind": w.get("kind", ""),
                            "why": v.refusals})
    pages = NB.pages_digest(cf) if a.pages else []
    body = {"wire": NB.WIRE_VERSION, "key": ref.key, "shifra": ref.shifra,
            "entries": entries, "pages": pages}
    data: dict[str, Any] = {"case": ref.key, "shifra": ref.shifra,
                            "entries": len(entries), "pages": len(pages),
                            "refused": refused, "dry_run": a.dry_run}
    if a.dry_run:
        env = ok({**data, "body": body})
        for r in refused:
            env.warn("gate", f"{r['uid'][:8]} ({r['kind']}): {r['why'][0]}")
        return env
    if not entries and not pages:
        env = ok(data)
        env.warn("nothing", "нема чого віддавати: позначте записи `note share`")
        return env
    from nyshporka.share import upload

    tok = upload.token()
    if not tok:
        return fail("немає ключа Супряги: nysh share login")
    try:
        got = upload._request("POST", f"{catalog.base_url(a.base)}/notes",
                              body=body, auth=tok)
    except upload.UploadError as exc:
        return fail(str(exc))
    env = ok({**data, "pool": got})
    for r in refused + list(got.get("refused") or []):
        why = r.get("why") or [r.get("text", "")]
        env.warn("gate", f"{str(r.get('uid', ''))[:8]}: {why[0] if why else ''}")
    return env


class NotePullArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    base: str = Field(default="", description="інша домівка пулу")


@op("note.pull", summary="Забрати чужі записи нотатника справи з пулу",
    args=NotePullArgs, mutates=True, agent=False, section=SECTION, private=True)
def note_pull(a: NotePullArgs) -> Envelope:
    """Чужі записи лягають у нотатник із позначкою `origin` — лише для читання.

    🔴 Рамка рядка лишається тільки там, де чужий прогін лежить у нас із
    прив'язкою `exact` (або це наш власний прогін). Інакше запис стає
    текстовим: сторінка перекладається через `page_stems` прийнятого
    прогону, а рамку з чужої нарізки на наші кадри не кладемо — так само, як
    геометрію (`share.align`).
    """
    from urllib.parse import quote

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import CaseNote
    from nyshporka.share import catalog, upload

    try:
        ref = _ref(a.case)
    except ValueError as exc:
        return fail(str(exc))
    base = catalog.base_url(a.base)
    try:
        got = upload._request("GET", f"{base}/notes?key={quote(ref.key)}"
                                     f"&shifra={quote(ref.shifra)}", auth=upload.token())
    except upload.UploadError as exc:
        return fail(str(exc))
    notes, bad = [], []
    for e in got.get("entries") or []:
        try:
            notes.append(CaseNote.model_validate(_from_pool(e, base)))
        except ValueError as exc:
            bad.append(f"{str(e.get('uid', ''))[:8]}: {exc}")
    report = store.add_notes(ref, notes) if notes else None
    env = ok({"case": ref.key, "shifra": ref.shifra, "book": got.get("book"),
              "received": len(notes), "added": report.added if report else [],
              "known": report.merged if report else [],
              "pages_by_others": got.get("pages_total", 0)})
    for b in bad:
        env.warn("bad_entry", b)
    return env


def _from_pool(e: dict[str, Any], base: str) -> dict[str, Any]:
    """Запис пулу → наш запис: поля білого списку + походження + прив'язка."""
    from nyshporka.pagestore.notebook import WIRE_FIELDS

    out = {k: e[k] for k in WIRE_FIELDS if k in e}
    alignment = "text-only"
    line = out.get("line") if isinstance(out.get("line"), dict) else None
    if line and line.get("run"):
        stems, al = _run_binding(str(line["run"]))
        if out.get("page"):
            out["page"] = stems.get(str(out["page"]), out["page"])
        alignment = al
        if al != "exact":
            line = {k: v for k, v in line.items() if k != "bbox"}
        out["line"] = line
    out["origin"] = {"pool": base, "by": str(e.get("by") or ""),
                     "pool_id": str(e.get("id") or ""), "alignment": alignment}
    out["share"] = False
    return out


def _run_binding(run: str) -> tuple[dict[str, str], str]:
    """Як чужий прогін лежить у нас: стеми сторінок і мітка прив'язки."""
    from nyshporka import htr_store as S

    try:
        meta = S.load_meta(run) or {}
    except Exception:
        meta = {}
    if not meta:
        return {}, "text-only"
    shared = meta.get("shared") or {}
    if not shared:
        return {}, "exact"                  # прогін наш: рамки наші
    return dict(shared.get("page_stems") or {}), str(shared.get("alignment") or "text-only")


# ── імпорт вільних тек ока ───────────────────────────────────────────────────
class NoteImportEyeArgs(BaseModel):
    folder: str = Field(description="тека `<прогін>-claude_eye` з файлами сторінок")
    case: str = Field(default="", description="справа; порожньо — з мети базового прогону")
    reader: str = Field(default="agent", description="agent | human | agent+human")
    model: str = Field(default="", description="модель, яка звіряла")
    base_run: str = Field(default="", description="базовий прогін, якщо ім'я теки його не каже")
    dry_run: bool = Field(default=False, description="показати й нічого не писати")


@op("note.import_eye", summary="Перенести вільні теки звірки оком у нотатник",
    args=NoteImportEyeArgs, mutates=True, agent=False, section=SECTION)
def note_import_eye(a: NoteImportEyeArgs) -> Envelope:
    """`[рядок N] …` → `reading`; примітки → особистий `note`. Нічого не віддається.

    🔴 Усе лягає домашнім: у примітках вільних тек — висновки дослідження й
    імена родичів, і що з цього загальне знання, вирішує людина
    (`note share`). Нерозпізнані рядки названо у відповіді, а не загублено.
    """
    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store

    folder = Path(a.folder)
    if not folder.is_dir():
        return fail(f"теки {folder} немає")
    got = NB.import_eye_dir(folder, reader=a.reader, model=a.model, base_run=a.base_run)
    case = a.case
    if not case and got["base_run"]:
        from nyshporka import htr_store as S

        case = str((S.load_meta(got["base_run"]) or {}).get("case_key") or "")
    if not case:
        return fail("справу не визначено: ні --case, ні `case_key` у меті базового "
                    f"прогону «{got['base_run'] or '?'}»")
    try:
        ref = _ref(case)
    except ValueError as exc:
        return fail(str(exc))
    notes = got["notes"]
    data = {"case": ref.key, "shifra": ref.shifra, "files": got["files"],
            "base_run": got["base_run"],
            "readings": sum(n.kind == "reading" for n in notes),
            "private": sum(n.kind == "note" for n in notes),
            "skipped": got["skipped"], "dry_run": a.dry_run}
    if a.dry_run:
        return ok(data)
    report = store.add_notes(ref, notes)
    env = ok({**data, "added": len(report.added), "known": len(report.merged)})
    if got["skipped"]:
        n = sum(len(v) for v in got["skipped"].values())
        env.warn("skipped", f"{n} рядків у {len(got['skipped'])} файлах не розпізнано — "
                            "вони лишились лише в теці")
    return env
