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
    if a.kind == "note" and a.share:
        from nyshporka.pagestore.models import NOTE_NEVER_SHARED

        return fail(NOTE_NEVER_SHARED)
    try:
        ref = _ref(a.case)
        n = CaseNote.model_validate({
            "kind": a.kind, "text": a.text, "field": a.field or None,
            "archive_says": a.archive_says, "actually": a.actually,
            "other": a.other, "relation": a.relation or None, "page": a.page,
            "share": a.share, "reader": a.reader, "model": a.model,
            "author": a.author, "supersedes": _full_uid(ref, a.supersedes)})
    except (ValidationError, ValueError) as exc:
        return fail(str(exc))
    return _written(ref, store.add_notes(ref, [n]), [n])


def _full_uid(ref: Any, prefix: str) -> str:
    """Префікс uid (як друкує `note list`) → повний uid свого запису справи.

    Порожньо — порожньо. Немає або неоднозначно — `ValueError` з поясненням.
    """
    prefix = prefix.strip()
    if not prefix:
        return ""
    from nyshporka.pagestore import store

    cf = store.load_case(ref)
    hit = [n.uid for n in (cf.notes if cf else []) if n.uid.startswith(prefix)]
    if len(hit) != 1:
        raise ValueError(f"запису «{prefix}» у нотатнику справи "
                         + ("немає" if not hit else "не один — дайте довший префікс"))
    return hit[0]


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
            "author": a.author, "supersedes": _full_uid(ref, a.supersedes)})
    except (ValidationError, ValueError) as exc:
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
        # 🔴 `model_copy` валідаторів не кличе: особистий запис із позначкою
        # «до віддачі» лягав у файл, і після цього справа не читалась зовсім
        # (перевірка випуску 0.26.0). Тому кожен змінений запис проходить
        # модель заново — відмова тут, а не в наступному читанні.
        if made.kind == "note" and made.share:
            from nyshporka.pagestore.models import NOTE_NEVER_SHARED

            return fail(f"{n.uid[:8]}: {NOTE_NEVER_SHARED}")
        try:
            made = type(made).model_validate(made.model_dump())
        except ValueError as exc:
            return fail(f"{n.uid[:8]}: {exc}")
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
    with_crop = sum(1 for w in entries if w.get("kind") == "reading"
                    and isinstance(w.get("line"), dict) and w["line"].get("bbox"))
    data: dict[str, Any] = {"case": ref.key, "shifra": ref.shifra,
                            "entries": len(entries), "pages": len(pages),
                            "with_crop": with_crop,
                            "refused": refused, "dry_run": a.dry_run}
    if a.dry_run:
        env = ok({**data, "body": body})
        for r in refused:
            env.warn("gate", f"{r['uid'][:8]} ({r['kind']}): {r['why'][0]}")
        if with_crop:
            env.warn("training", TRAINING_NOTICE)
        return env
    if not entries and not pages:
        env = ok(data)
        env.warn("nothing", "нема чого віддавати: позначте записи `note share`")
        return env
    from nyshporka.share import upload

    tok = upload.token()
    if not tok:
        return fail("немає ключа Супряги: nysh share login")
    # 🔴 Пачками: пул приймає до 500 записів за запит і відмовляє ЦІЛОМУ запиту,
    # якщо їх більше. Справа з сотнями звірених рядків інакше не віддавалась би
    # зовсім. Переглянуті аркуші — лише з першою пачкою.
    got: dict[str, Any] = {}
    for i in range(0, max(len(entries), 1), PUSH_BATCH):
        part = {**body, "entries": entries[i:i + PUSH_BATCH],
                "pages": body["pages"] if i == 0 else []}
        try:
            one = upload._request("POST", f"{catalog.base_url(a.base)}/notes",
                                  body=part, auth=tok)
        except upload.UploadError as exc:
            if not got:
                return fail(str(exc))
            got.setdefault("failed_batches", []).append(str(exc))
            continue
        for k, v in one.items():
            if isinstance(v, list):
                got[k] = list(got.get(k) or []) + v
            elif k not in got:
                got[k] = v
    crops = _send_crops(cf, got.get("need_crop") or [], base=catalog.base_url(a.base),
                        tok=tok)
    env = ok({**data, "pool": got, "crops": crops})
    for f in got.get("failed_batches") or []:
        env.warn("batch_failed", f"частина записів не пішла: {f}")
    for r in refused + list(got.get("refused") or []):
        why = r.get("why") or [r.get("text", "")]
        env.warn("gate", f"{str(r.get('uid', ''))[:8]}: {why[0] if why else ''}")
    if crops["sent"] or crops["no_frame"]:
        env.warn("training", TRAINING_NOTICE)
    if crops["no_frame"]:
        env.warn("no_frame", f"{len(crops['no_frame'])} звірених рядків поїхали без кропу: "
                             "кадру на цій машині немає")
    for f in crops["failed"]:
        env.warn("crop_failed", f"{f['uid'][:8]}: {f['why']}")
    return env


#: Що людина погоджується віддати, поширюючи звірений рядок. 🔴 Кажеться
#: щоразу, коли кроп їде, а не лише в документації: згода дається дією.
TRAINING_NOTICE = ("звірені рядки їдуть разом із кропом рядка; власник Нишпорки може "
                   "використати їх для навчання моделей розпізнавання. На сторінці "
                   "книги кропи не показуються й іншим не віддаються")

#: Записів в одному запиті `note push`: пул приймає до 500.
PUSH_BATCH = 400

#: Стеля кропа: пул більшого не прийме.
CROP_MAX_BYTES = 256 * 1024
CROP_MAX_WIDTH = 2000


def crop_jpeg(n: Any) -> bytes:
    """Сірий JPEG рядка за рамкою рушія — у межах стелі пулу."""
    import io

    from nyshporka.search import textops as T

    piece = T.line_image(n.line.run, n.page, n.line.bbox).convert("L")
    if piece.width > CROP_MAX_WIDTH:
        piece = piece.resize((CROP_MAX_WIDTH,
                              max(1, round(piece.height * CROP_MAX_WIDTH / piece.width))))
    for q in (85, 70, 55, 40):
        buf = io.BytesIO()
        piece.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= CROP_MAX_BYTES:
            return buf.getvalue()
    raise ValueError("кроп не вміщається в 256 КБ навіть на найнижчій якості")


def _send_crops(cf: Any, need: list[Any], *, base: str, tok: str) -> dict[str, Any]:
    """Кропи тих звірених рядків, яких пул ще не має (`need_crop` у відповіді)."""
    from nyshporka.search import textops as T
    from nyshporka.share import upload

    want = {str(u) for u in need}
    out: dict[str, Any] = {"sent": 0, "no_frame": [], "failed": []}
    for n in cf.notes:
        if n.uid not in want or n.kind != "reading" or n.line is None or not n.line.bbox:
            continue
        try:
            blob = crop_jpeg(n)
        except T.FrameError:
            out["no_frame"].append(n.uid)
            continue
        except ValueError as exc:
            out["failed"].append({"uid": n.uid, "why": str(exc)})
            continue
        try:
            upload._put_bytes(f"{base}/notes/{n.uid}/crop", blob, auth=tok,
                              content_type="image/jpeg")
        except upload.UploadError as exc:
            out["failed"].append({"uid": n.uid, "why": str(exc)})
            continue
        out["sent"] += 1
    return out


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
    cf = store.load_case(ref)
    have = {n.uid for n in cf.notes} if cf else set()
    notes, bad = [], []
    for e in got.get("entries") or []:
        if not isinstance(e, dict):
            continue
        try:
            notes.append(CaseNote.model_validate(_from_pool(e, base, known=have)))
        except ValueError as exc:
            bad.append(f"{str(e.get('uid', ''))[:8]}: {exc}")
    report = store.add_notes(ref, notes) if notes else None
    if report is not None:
        bad += [f"{str(x.get('uid', ''))[:8]}: {x.get('error')}" for x in report.errors]
    env = ok({"case": ref.key, "shifra": ref.shifra, "book": got.get("book"),
              "received": len(notes), "added": report.added if report else [],
              "known": report.merged if report else [],
              "pages_by_others": got.get("pages_total", 0)})
    for b in bad:
        env.warn("bad_entry", b)
    return env


def _from_pool(e: dict[str, Any], base: str, *,
               known: set[str] | None = None) -> dict[str, Any]:
    """Запис пулу → наш запис: поля білого списку + походження + прив'язка.

    🔴 Пул віддає порожні поля як `null` (`"supersedes": null`), а модель їх не
    приймає — тож порожнє відкидається. І заміна лишається лише тоді, коли
    замінений запис уже лежить у нас: пул віддає тільки чинні записи, без
    предків, і заміна невідомого означала б відмову всього запису.
    """
    from nyshporka.pagestore.notebook import WIRE_FIELDS

    out = {k: e[k] for k in WIRE_FIELDS if e.get(k) not in (None, "", [], {})}
    if out.get("supersedes") and out["supersedes"] not in (known or set()):
        out.pop("supersedes")
    out.pop("retracts", None)
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
