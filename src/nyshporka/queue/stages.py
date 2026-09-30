"""Етапи справи в черзі: кадри → паспорт → каталог → пул → читання → облік → віддача.

Кожен етап — три функції: `applies` (чи стосується справи), `done` (предикат
по диску, без побічних дій) і `run` (зробити). Етап не знає про чергу: він
бере справу й каже, чим скінчилось.

🔴 Чим скінчилось — п'ять відповідей, і від них залежить, що черга робить далі:

* `ok` — зроблено, далі наступний етап;
* `retry` — тимчасова відмова (хост лежить, карта зайнята, пул відсікає за
  темпом): справа сама повториться, черга тим часом бере наступну;
* `blocked` — потрібна людина: причина й точна команда;
* `failed` — остаточно: повтор не допоможе;
* `stopped` — зупинено на прохання посеред етапу.

Етапи кличуть наявні функції пакета й нічого в них не дублюють.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OK = "ok"
RETRY = "retry"
BLOCKED = "blocked"
FAILED = "failed"
STOPPED = "stopped"

#: Рішення людини про пул для однієї справи.
POOL_AUTO = "auto"    # брати лише певне; решта — питати
POOL_TAKE = "take"    # узяти з пулу те, що є
POOL_READ = "read"    # пул не питати, читати своїм рушієм
POOL_MODES = (POOL_AUTO, POOL_TAKE, POOL_READ)

#: Карта зайнята іншою справою — глянути знову за стільки секунд.
GPU_BUSY_AFTER = 600.0


@dataclass(frozen=True)
class Outcome:
    kind: str
    code: str = ""
    why: str = ""
    fix: str = ""
    #: Для `retry`: не раніше ніж за стільки секунд; `None` — за розкладом черги,
    #: 0 — одразу (догін недочитаного).
    after: float | None = None
    #: Для `retry`: чекання, яке не є збоєм (карта зайнята) — спроб не рахувати.
    patient: bool = False
    #: Що покласти в `evidence` справи — те, чого диск сам не скаже.
    evidence: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def ok(note: str = "", **evidence: Any) -> Outcome:
    return Outcome(OK, note=note, evidence=evidence)


def retry(code: str, why: str, *, after: float | None = None,
          patient: bool = False) -> Outcome:
    return Outcome(RETRY, code, why, after=after, patient=patient)


def blocked(code: str, why: str, fix: str = "") -> Outcome:
    return Outcome(BLOCKED, code, why, fix)


def failed(code: str, why: str, fix: str = "") -> Outcome:
    return Outcome(FAILED, code, why, fix)


@dataclass
class Ctx:
    """Що виконавець дає етапові."""

    say: Callable[[str], None] = lambda _t: None
    progress: Callable[[int, int, str], None] = lambda _i, _n, _t: None
    should_stop: Callable[[], bool] = lambda: False
    #: `queue run --share`: віддавати кожну справу цього заходу.
    share_all: bool = False


# ── де справа лежить ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Where:
    case_dir: Path | None     # тека справи (паспорт лежить тут)
    frames_dir: Path | None   # де самі кадри: тека або її `pages/`
    frames: int
    key: str                  # ключ справи, якщо каталог його знає або він із реєстру опису
    plan: dict[str, Any]      # план узяття для справи з реєстру опису; інакше порожньо


def where(item: dict[str, Any]) -> Where:
    """Де лежить справа черги й що про неї відомо без жодної дії."""
    from nyshporka.cases.register import case_path
    from nyshporka.htr.run import count_frames
    from nyshporka.share import align

    ref = item.get("ref") or {}
    plan: dict[str, Any] = {}
    case_dir: Path | None = None
    key = ""
    if ref.get("key"):
        from nyshporka.cases import take

        try:
            plan = take.plan(str(ref["key"]))
        except take.TakeError:
            plan = {}
        key = str(plan.get("key") or ref["key"])
        if plan.get("case_dir"):
            case_dir = Path(plan["case_dir"])
    if ref.get("dir"):
        case_dir = case_path(str(ref["dir"]))
    frames_dir = align._frames_dir(case_dir) if case_dir and case_dir.is_dir() else None
    frames = count_frames(frames_dir) if frames_dir else 0
    return Where(case_dir, frames_dir, frames, key, plan)


def _judge(w: Where) -> Any:
    """Ланка справи (`cases.chain`) — із прогонами й числом кадрів."""
    from nyshporka import htr_store as S
    from nyshporka.cases import chain as C

    assert w.case_dir is not None
    C._forget_caches()
    return C.judge(w.case_dir, frames=w.frames, runs=S.runs_by_case_dir())


def case_key(item: dict[str, Any], w: Where) -> str:
    """Ключ справи: з каталогу, з реєстру опису або з паспорта теки.

    Каталог — перший: лише він знає, чи входить опис у ключ саме цієї справи.
    """
    if w.case_dir is not None and w.case_dir.is_dir():
        got = _judge(w).key
        if got:
            return str(got)
    if w.key:
        return w.key
    if w.case_dir is None:
        return ""
    from nyshporka.htr.run import case_key_for

    return case_key_for(w.case_dir)[0]


def _name(item: dict[str, Any]) -> str:
    return str(item.get("id") or "")


# ── 1. кадри ─────────────────────────────────────────────────────────────────
def fetch_applies(item: dict[str, Any], ctx: Ctx) -> bool:
    return bool((item.get("ref") or {}).get("key"))


def _loader_meta(case_dir: Path | None) -> dict[str, Any]:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    if case_dir is None:
        return {}
    try:
        raw = read_json(case_dir / "meta.json", default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def opys_clash(w: Where) -> str:
    """Чому тека справи не її: у ній уже лежить справа ІНШОГО опису. Порожньо — її.

    🔴 Тека зветься за номером справи без опису (`spr-124`), а номери між
    описами повторюються. Кадри 224-1-124, що вже лежать у теці, для справи
    224-2-124 — не «кадри вже на диску», а чужа книга під її іменем.
    """
    from nyshporka.cases import acquire as A

    opys = str(w.plan.get("opys") or "")
    if not opys or w.case_dir is None or not w.case_dir.is_dir():
        return ""
    try:
        A.guard_inventory(w.case_dir, opys)
    except A.AcquireError as exc:
        return str(exc)
    return ""


def fetch_done(item: dict[str, Any], ctx: Ctx) -> bool:
    w = where(item)
    if not w.frames or opys_clash(w):
        return False
    state = str(_loader_meta(w.case_dir).get("fetch_state") or "")
    if state:
        return state == "complete"
    # Кадри без паспорта завантажувача поклала людина — качати нічого.
    # 🔴 Але не тоді, коли їх почала класти сама черга: паспорт завантаження
    # пишеться наприкінці, і взяття, обірване посередині, лишає кілька кадрів
    # без нього — рівно той самий вигляд. Знайдено живим прогоном 30.09.2026:
    # справа з одним кадром із чотирнадцяти пішла б у читання як повна.
    return not (item.get("evidence") or {}).get("fetch_started")


def _remember(item: dict[str, Any], **evidence: Any) -> None:
    """Записати в справу черги те, що мусить пережити обрив посеред етапу."""
    from nyshporka.queue import state as Q

    item.setdefault("evidence", {}).update(evidence)
    with Q.edit() as q:
        for it in q["items"]:
            if it["id"] == item["id"] and it.get("state") != Q.DROPPED:
                it.setdefault("evidence", {}).update(evidence)


def fetch_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    from nyshporka.cases import take
    from nyshporka.sources import base as B

    key = str(item["ref"]["key"])
    try:
        plan = take.plan(key)
    except take.TakeError as exc:
        return failed("no_registry_row", str(exc),
                      "справи немає в реєстрі опису — додайте теку з кадрами: "
                      "nysh queue add <тека>")
    chuzha = opys_clash(where(item))
    if chuzha:
        return blocked("opys_conflict", chuzha,
                       f'зняти цю справу з черги: nysh queue drop "{_name(item)}"')
    if plan.get("shifra_needs_eye") and not (item.get("opts") or {}).get("shifra_ok"):
        return blocked(
            "shifra_needs_eye",
            "номер справи в реєстрі опису відновлено інтерполяцією — шифру треба "
            "звірити оком, перш ніж класти під неї кадри й текст",
            f'nysh queue set "{_name(item)}" --shifra-ok')
    if not plan.get("channel"):
        return blocked("no_channel", str(plan.get("why") or "каналу взяття немає"),
                       f'покладіть кадри в теку й додайте її: nysh queue add <тека>; '
                       f'цю зняти: nysh queue drop "{_name(item)}"')
    from nyshporka.queue.state import now

    _remember(item, fetch_started=now())

    def _progress(done: int = 0, total: int = 0, **_: Any) -> None:
        ctx.progress(int(done), int(total), "кадри")

    try:
        got = take.take(key, reindex=False, on_progress=_progress)
    except take.TakeError as exc:
        meta = _loader_meta(Path(plan["case_dir"]))
        causes = dict(meta.get("fetch_causes") or {})
        text = str(exc)
        if B.DENIED in causes:
            return blocked("denied", text,
                           "джерело не віддає без входу чи з цієї мережі — візьміть "
                           "кадри інакше й додайте теку")
        if B.HOST_DOWN in causes or B.RATE_LIMITED in causes:
            return retry("host_down" if B.HOST_DOWN in causes else "rate_limited", text)
        if B.NOT_FOUND in causes and set(causes) == {B.NOT_FOUND}:
            return failed("not_found", text, "адреса в реєстрі опису застаріла")
        if str(meta.get("fetch_state") or "") == "partial":
            return retry("partial", text)
        return blocked("fetch_refused", text, f'nysh cases take "{key}"')
    ctx.say(f"кадрів: {got.get('pages')}, нових файлів: {got.get('files')}")
    return ok()


# ── 2. паспорт ───────────────────────────────────────────────────────────────
def passport_done(item: dict[str, Any], ctx: Ctx) -> bool:
    from nyshporka.cases import chain as C

    w = where(item)
    if w.case_dir is None or not w.case_dir.is_dir():
        return False
    return _judge(w).link not in (C.OUTSIDE_ROOTS, C.BUNDLE_FOLDER, C.LOADER_ONLY,
                                  C.NO_PASSPORT)


def passport_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    """🔴 Шифру черга не вигадує і `shifra_claimed` не приймає: це точка, де
    потрібне око. Етап лише називає, чого бракує, і команду."""
    w = where(item)
    if w.case_dir is None or not w.case_dir.is_dir():
        return failed("no_dir", f"теки справи немає: {w.case_dir or item.get('ref')}")
    if not w.frames:
        return blocked("no_frames", f"у теці {w.case_dir} немає кадрів",
                       "покладіть кадри в теку (не в підтеки) і повторіть")
    lanka = _judge(w)
    return blocked(lanka.link, lanka.why, lanka.fix)


# ── 3. каталог ───────────────────────────────────────────────────────────────
def catalog_done(item: dict[str, Any], ctx: Ctx) -> bool:
    from nyshporka import library as L
    from nyshporka.cases import chain as C

    w = where(item)
    lanka = _judge(w)
    if lanka.link == C.NOT_IN_LIBRARY:
        return False
    # Каталог міг зібратись, поки кадри ще качались: запис є, а кадрів у ньому
    # — скільки лежало тоді. Знаменник покриття з такого запису бреше.
    if not L.LIBRARY_PATH.exists() or not lanka.key:
        return True
    entry = L.library_lookup().by_key.get(lanka.key)
    if entry is None or str(getattr(entry, "path", "") or "") != lanka.path:
        return True
    return int(getattr(entry, "frames", 0) or 0) == w.frames


def catalog_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    from nyshporka.cases import db

    try:
        db.rebuild(rescan=True)
    except OSError as exc:
        return retry("catalog_busy", f"каталог справ не перезібрався: {exc}")
    if not catalog_done(item, ctx):
        lanka = _judge(where(item))
        return blocked(lanka.link, lanka.why or "каталог теку не побачив", lanka.fix)
    return ok()


# ── 4. пул ───────────────────────────────────────────────────────────────────
def _profile() -> Any:
    try:
        from nyshporka.share import profile as P

        return P.load()
    except Exception:
        return None


def pool_mode(item: dict[str, Any]) -> str:
    """Як справа поводиться з пулом: рішення людини по справі або профіль.

    🔴 Без рішення по справі пул питається лише тоді, коли людина ввімкнула це
    в профілі (`nysh share setup --lookup`): запит несе шифру, тобто сервер
    бачить, яку справу читають, а `PRIVACY.md` обіцяє, що таких запитів немає,
    доки їх не дозволено. Черга цієї обіцянки не обходить.
    """
    mode = str((item.get("opts") or {}).get("pool") or "")
    if mode in POOL_MODES:
        return mode
    prof = _profile()
    return POOL_AUTO if prof is not None and prof.lookup else POOL_READ


def pool_applies(item: dict[str, Any], ctx: Ctx) -> bool:
    return pool_mode(item) != POOL_READ


def pool_done(item: dict[str, Any], ctx: Ctx) -> bool:
    from nyshporka.share import pool

    if read_done(item, ctx):
        return True
    seen = (item.get("evidence") or {}).get("pool") or {}
    if not seen.get("at"):
        return False
    # 🔴 Звірка мусить бути свіжою саме перед читанням: справа могла простояти
    # тиждень на іншому етапі, а за цей час її хтось віддав.
    from nyshporka.queue.state import stamp

    return time.time() - stamp(seen["at"]) <= pool.SVIZHYI_DNIV * 86400


def pool_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    from nyshporka import ops as O
    from nyshporka.cases.collect import _COVERAGE_OK
    from nyshporka.queue.state import now
    from nyshporka.share import catalog as C
    from nyshporka.share import pool
    from nyshporka.share.suggest import _pool_key

    w = where(item)
    key = case_key(item, w)
    name = _name(item)
    quad = _pool_key(key) if key else None
    if not quad:
        # Без повного ключа (архів, фонд, опис, справа) пул питати нема чим:
        # чесніше сказати «не звірено», ніж видати мовчання за «немає».
        return ok("пул не звірено: шифра не зводиться до повного ключа",
                  pool={"at": now(), "verdict": "unkeyed"})
    repo, fond = quad.split("/")[0], quad.split("/")[1]
    try:
        pool.sync(repo=repo, fond=fond)
    except Exception as exc:
        return retry("pool_unavailable",
                     f"свіжого зрізу пулу взяти не вийшло: {exc}. Читати без "
                     f'звірки: nysh queue set "{name}" --pool read')
    cell = pool.by_key(quad)
    if cell is None or not cell.pages:
        return ok("у пулі цієї справи немає", pool={"at": now(), "verdict": "absent"})

    frames = cell.frames or w.frames
    share = cell.coverage if cell.coverage is not None else (
        cell.pages / frames if frames else 0.0)
    chyie = "ваше" if cell.mine else (", ".join(cell.publishers) or "без підпису")
    maie = (f"у пулі вже є прочитання: {cell.pages} стор."
            + (f" із {frames} кадрів ({share:.0%})" if frames else "") + f" · {chyie}")
    choose = (f'узяти з пулу: nysh queue set "{name}" --pool take · '
              f'читати своїм рушієм: nysh queue set "{name}" --pool read')
    mode = pool_mode(item)
    if mode == POOL_AUTO and share < _COVERAGE_OK:
        return blocked("pool_needs_decision", f"{maie} — покриття неповне", choose)

    try:
        found, _count, _of = C.search(key)
    except RuntimeError as exc:
        return retry("pool_unavailable", f"каталог пулу не відповів: {exc}")
    rows = [r for r in found
            if pool.quad_key(r.repo, r.fond, r.opys, r.spr) == quad and r.url]
    if len(rows) != 1:
        return blocked("pool_ambiguous",
                       f"{maie}; пакетів цієї справи в каталозі — {len(rows)}, "
                       f"вибрати між ними має людина",
                       f'nysh share pull "{key}" — переглянути й прийняти потрібний; '
                       f'або читати своїм: nysh queue set "{name}" --pool read')
    row = rows[0]
    seen = O.call("share.inspect", {"src": row.url})
    if not seen.ok:
        return retry("pool_unavailable", f"пакет із пулу не відкрився: {seen.error}")
    label = str(((seen.data or {}).get("alignment") or {}).get("label") or "")
    if mode == POOL_AUTO and label != "exact":
        why = str(((seen.data or {}).get("alignment") or {}).get("why") or "")
        return blocked("pool_needs_decision",
                       f"{maie}; прив'язка до ваших кадрів — «{label or 'невідома'}»"
                       + (f" ({why})" if why else "")
                       + ": чужий текст ляже не напевно на ті самі аркуші", choose)
    got = O.call("share.pull", {"query": row.shifra or key, "take": True})
    taken = (got.data or {}).get("imported") if got.ok else None
    if not taken:
        notes = "; ".join(w_.text for w_ in got.warnings) or got.error or "не прийнято"
        return blocked("pool_take_failed", f"узяти з пулу не вийшло: {notes}", choose)
    ctx.say(f"узято з пулу: {taken.get('pages')} стор., прив'язка «{label}»")
    return ok("узято з пулу",
              pool={"at": now(), "verdict": "taken", "label": label,
                    "runs": list(taken.get("runs") or [])})


# ── 5. читання ───────────────────────────────────────────────────────────────
def _own_out(w: Where) -> Path | None:
    """Тека власного прогону справи — та сама, яку взяв би план читання."""
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.run import case_key_for
    from nyshporka.htr.runname import run_name

    if w.frames_dir is None:
        return None
    return workspace().htr_reports / run_name(w.frames_dir, case_key_for(w.frames_dir)[0])


def _taken_covers(item: dict[str, Any], w: Where) -> bool:
    """Чи текст, узятий із пулу, накриває справу."""
    from nyshporka.cases.collect import _COVERAGE_OK
    from nyshporka.cloud.verify import texts_in
    from nyshporka.core.workspace import workspace

    seen = (item.get("evidence") or {}).get("pool") or {}
    if seen.get("verdict") != "taken" or not w.frames:
        return False
    runs = [workspace().htr_reports / str(r) for r in seen.get("runs") or []]
    return any(texts_in(d) / w.frames >= _COVERAGE_OK for d in runs if d.is_dir())


def read_done(item: dict[str, Any], ctx: Ctx) -> bool:
    from nyshporka.cloud.verify import texts_in, verify

    w = where(item)
    out = _own_out(w)
    if out is None:
        return False
    if _taken_covers(item, w):
        return True
    if not out.is_dir():
        return False
    if (item.get("opts") or {}).get("partial_why"):
        # Людина прийняла неповне читання з причиною — далі воно йде як уривок.
        return texts_in(out) > 0
    got = verify(out, case_dir=w.frames_dir or "", check_voices=True)
    return bool(got.complete) and not got.quarantined


def read_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    from nyshporka.cloud.verify import verify
    from nyshporka.htr import run as HR
    from nyshporka.htr import runs as R
    from nyshporka.htr import session as S

    w = where(item)
    opts = item.get("opts") or {}
    name = _name(item)
    assert w.frames_dir is not None
    try:
        plan = HR.plan(w.frames_dir, script=str(opts.get("script") or ""),
                       second_voice=not opts.get("one_voice"),
                       also=tuple(opts.get("with") or ()))
    except HR.ReadError as exc:
        return blocked("read_refused", str(exc),
                       f'усунути причину й повторити: nysh queue retry "{name}"')
    if plan.script_trust == "unknown" and not opts.get("script"):
        return blocked(
            "script_unsure",
            f"письмо справи не визначено ({plan.script_why or 'підказок немає'}) — "
            f"читати книгу не тим письмом означає години на текст, якому не можна вірити",
            f'nysh queue set "{name}" --script cyrillic (або latin)')
    busy = R.others(plan.case_dir.name)
    if busy:
        return retry("gpu_busy", "карту читає інша справа: "
                     + "; ".join(r.label() for r in busy), after=GPU_BUSY_AFTER,
                     patient=True)

    ctx.say(f"{plan.frames} кадрів · письмо {plan.script} · {plan.model.name}"
            + "".join(f" + {v.name}" for v in plan.voices))

    def _event(ev: Any, human: str | None) -> None:
        if ev is not None and ev.n:
            ctx.progress(int(ev.i), int(ev.n), "сторінки")
        elif human:
            ctx.say(human)

    workers = int(opts.get("workers") or 1)
    got = S.read_case(plan, case_key=case_key(item, w), workers=workers,
                      device="cuda" if workers > 1 else "",
                      on_event=_event, should_stop=ctx.should_stop)
    if got.stopped:
        return Outcome(STOPPED, "stopped",
                       f"зупинено на прохання: прочитано {got.done} із {got.frames}")
    v = verify(plan.out_dir, case_dir=w.frames_dir, check_voices=True)
    if v.complete and not v.quarantined:
        return ok(f"прочитано {v.got} із {v.expected}")
    detail = (f"прочитано {v.got} із {v.expected}"
              + (f", без тексту {v.missing_count}" if v.missing_count else "")
              + (f", відкладено {len(v.quarantined)}: {', '.join(v.quarantined[:5])}"
                 if v.quarantined else "")
              + (f" (код раннера {got.rc})" if got.rc else ""))
    if v.quarantined:
        return blocked("quarantine", detail,
                       f'прийняти як уривок: nysh queue set "{name}" --partial "чому"; '
                       f'спробувати ще: nysh queue retry "{name}"')
    # Недочитане без карантину — повтор дочитує: готові сторінки раннер пропустить.
    return Outcome(RETRY, "incomplete", detail,
                   fix=(f'прийняти як уривок: nysh queue set "{name}" --partial "чому"; '
                        f'спробувати ще: nysh queue retry "{name}"'), after=0.0)


# ── 6. облік ─────────────────────────────────────────────────────────────────
def _run_stamp(item: dict[str, Any], w: Where) -> str:
    """Що саме обліковано: тека прогону й час її мети."""
    from nyshporka.cloud.verify import META_NAME

    out = _own_out(w)
    if out is None or _taken_covers(item, w) or not (out / META_NAME).is_file():
        runs = ((item.get("evidence") or {}).get("pool") or {}).get("runs") or []
        return "taken:" + ",".join(str(r) for r in runs) if runs else ""
    return f"{out.name}:{int((out / META_NAME).stat().st_mtime)}"


def books_done(item: dict[str, Any], ctx: Ctx) -> bool:
    got = _run_stamp(item, where(item))
    return bool(got) and (item.get("evidence") or {}).get("books") == got


def books_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    """Каталог справ і текстовий стор — щоб прочитане було видно пошуку."""
    from nyshporka.cloud.go import bookkeeping

    w = where(item)
    got = _run_stamp(item, w)
    out = _own_out(w)
    notes = bookkeeping(out.name if out is not None else "")
    if notes:
        return retry("books_busy", "; ".join(notes))
    return ok(books=got)


# ── 7. віддача ───────────────────────────────────────────────────────────────
def share_applies(item: dict[str, Any], ctx: Ctx) -> bool:
    if _taken_covers(item, where(item)):
        return False          # чуже, взяте з пулу, назад не віддається
    if (item.get("opts") or {}).get("share") or ctx.share_all:
        return True
    prof = _profile()
    return bool(prof is not None and prof.auto)


def share_done(item: dict[str, Any], ctx: Ctx) -> bool:
    return bool(((item.get("evidence") or {}).get("shared") or {}).get("sha256"))


def share_run(item: dict[str, Any], ctx: Ctx) -> Outcome:
    from nyshporka import ops as O
    from nyshporka.queue.state import now
    from nyshporka.share.upload import TYMCHASOVYI, VIDDANO, VZHE_Ye

    w = where(item)
    key = case_key(item, w)
    name = _name(item)
    why = str((item.get("opts") or {}).get("partial_why") or "")
    args: dict[str, Any] = {"case": key, "partial": why}
    probe = O.call("share.pack", {**args, "dry_run": True})
    if not probe.ok:
        return blocked("pack_refused", str(probe.error),
                       f'nysh share pack "{key}" --dry-run')
    d = probe.data or {}
    refusals = list((d.get("gates") or {}).get("refusals") or []) + list(
        d.get("pack_refusals") or [])
    if refusals:
        return blocked("pack_refused", "; ".join(str(x) for x in refusals),
                       f'виправити й повторити: nysh share pack "{key}" --dry-run; '
                       f'далі nysh queue retry "{name}"')
    packed = O.call("share.pack", args)
    if not packed.ok:
        return blocked("pack_refused", str(packed.error), f'nysh share pack "{key}" --dry-run')
    path = str((packed.data or {}).get("path") or "")
    sent = O.call("share.publish", {"path": path})
    if not sent.ok:
        info = sent.data or {}
        if info.get("rate_limited") or info.get("klas") == TYMCHASOVYI:
            wait = info.get("retry_after")
            return retry("upload_retry", str(sent.error),
                         after=float(wait) if wait else None)
        if info.get("refusals"):
            return failed("pool_refused", str(sent.error),
                          f'nysh share pack "{key}" --dry-run — що саме не пройшло')
        return blocked("upload_failed", str(sent.error),
                       f'nysh share publish "{path}"')
    outcome = str((sent.data or {}).get("outcome") or "")
    if outcome not in (VIDDANO, VZHE_Ye):
        text = "; ".join(w_.text for w_ in sent.warnings) or outcome
        if outcome == "vidkhyleno":
            return failed("pool_refused", text)
        return retry("upload_retry", text)
    return ok("віддано" if outcome == VIDDANO else "у пулі вже є",
              shared={"at": now(), "sha256": (packed.data or {}).get("sha256") or "",
                      "outcome": outcome, "path": path})


# ── перелік ──────────────────────────────────────────────────────────────────
Fn = Callable[[dict[str, Any], Ctx], Any]


@dataclass(frozen=True)
class Stage:
    name: str
    title: str
    done: Fn
    run: Fn
    applies: Fn = lambda _item, _ctx: True


STAGES: tuple[Stage, ...] = (
    Stage("fetch", "кадри", fetch_done, fetch_run, fetch_applies),
    Stage("passport", "паспорт", passport_done, passport_run),
    Stage("catalog", "каталог", catalog_done, catalog_run),
    Stage("pool", "пул", pool_done, pool_run, pool_applies),
    Stage("read", "читання", read_done, read_run),
    Stage("books", "облік", books_done, books_run),
    Stage("share", "віддача", share_done, share_run, share_applies),
)

TITLES = {s.name: s.title for s in STAGES}


def progress_of(item: dict[str, Any], ctx: Ctx | None = None) -> list[dict[str, Any]]:
    """Етапи справи зі станом кожного — з диска: `done` · `todo` · `skip`."""
    ctx = ctx or Ctx()
    out = []
    for s in STAGES:
        try:
            state = ("skip" if not s.applies(item, ctx)
                     else "done" if s.done(item, ctx) else "todo")
        except Exception as exc:
            state = "todo"
            out.append({"stage": s.name, "title": s.title, "state": state,
                        "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"stage": s.name, "title": s.title, "state": state})
    return out
