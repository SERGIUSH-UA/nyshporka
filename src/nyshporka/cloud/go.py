"""🛫 Захід однією командою: від справи до тексту на диску й погашеної машини.

Решта пакета `cloud` — дрібні повторювані кроки, і кожен із них лишає рішення
людині. Тут ті самі кроки зібрані в один захід для випадку, де людини поруч
немає: справа читається на орендованій машині, а дослідник дав лише ключ
провайдера й має баланс.

    справа → кадри цілі? → завеликі — стиснути → план → кошторис вилкою →
    рішення → оренда → середовище рушіїв → заливка → прогін під наглядом двох
    стель → забір → звірка по диску → догін хвоста → гасіння → облік

Автономність тут купується трьома запобіжниками, і всі три — про гроші:

* **стеля автозапуску.** Без людини захід стартує, лише коли ВЕРХ вилки
  кошторису не перевищує стелі простору (типово два долари). Понад неї —
  відмова з кодом 10, доки людина не скаже `--confirm`;
* **дві стелі в роботі** — годинник і гроші. На будь-якій із них роботу
  зупинено, прочитане забрано й звірено, машину погашено. Вердикт
  (`deadline` / `budget_stop`) окремий від збою: текст на диску справжній, і
  повторний захід дочитає решту, а не почне заново;
* **`release` у `finally`.** Машина гаситься на кожному шляху виходу — успіх,
  відмова, виняток, Ctrl+C. Єдине, що стоїть перед гасінням, — спроба забрати
  те, що на ній лежить.

🔴 Порядок `fetch → verify → release` тут той самий, що й у ручних команд, і
перевіряється тим самим кодом (`run.release` відмовляє без вироку). Автономний
захід не обходить це правило, а виконує його сам.

🔴 Обрив термінала — штатна подія. Робота живе на машині відчеплено, стан
заходу — на диску, тож повторний `nysh cloud go` тієї самої справи ПІДХОПЛЮЄ
живий захід разом із його стелями, а не орендує другу машину.
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from nyshporka.cloud import convoy as CV
from nyshporka.cloud import frames as F
from nyshporka.cloud import money as M
from nyshporka.cloud import run as RUN
from nyshporka.cloud import state as ST
from nyshporka.cloud import verify as V
from nyshporka.cloud.base import (
    BoxGone,
    BoxNotReady,
    ChannelDropped,
    CloudError,
    bills,
)

#: Код виходу на кожен вердикт. Частина публічного інтерфейсу: на нього
#: дивиться агент, який пустив захід і пішов.
EXIT_CODES: dict[str, int] = {
    # `detached` — робота ПОЧАЛАСЬ і йде без нас: наглядач орендує машину,
    # читає, забирає й гасить оренду сам. Нуль тут означає «захід пущено», а
    # не «текст на диску»; про готовність питають `nysh cloud state`.
    "ok": 0, "dry_run": 0, "detached": 0, "refused": 2, "failed": 3, "incomplete": 4,
    "budget_stop": 5, "market_empty": 6, "deadline": 7, "no_credit": 8,
    # 🔴 Окремий код, а не «той самий, що у вердикту»: робота могла вдатись, а
    # машина — лишитись живою. Нуль тут означав би «все гаразд» при лічильнику,
    # який іде.
    "release_failed": 9,
    "needs_confirm": 10, "cancelled": 130}

#: Скільки опитувань поспіль машина може мовчати, перш ніж це збій. Свіжий бокс
#: і тихий канал мовчать хвилинами, і гасити на першому ж — рівно той рефлекс,
#: яким уже брали чотири оренди по хвилині поспіль.
POLL_FAILURES_MAX = 10

#: Скільки чекати, поки облік іншого заходу відпустить замок. Перша збірка
#: індексу тексту триває десятки хвилин, звичайна догонка — секунди.
BOOKKEEPING_WAIT_SEC = 1800.0

EventFn = Callable[..., None]


def _now() -> float:
    """Годинник нагляду. Окремою функцією — щоб стелі перевірялись тестом."""
    return time.time()


def _sleep(sec: float) -> None:
    time.sleep(sec)


class GoRefused(CloudError):
    """Причина не починати. Текст — для людини, дослівно."""

    def __init__(self, message: str, *, verdict: str = "refused") -> None:
        super().__init__(message)
        self.verdict = verdict


class Busy(GoRefused):
    """Справу вже веде інший захід — і це стосується ВСІЄЇ партії.

    🔴 Машина в заході одна. Відкинути зайняту справу й поїхати з рештою
    означало б узяти другу машину під роботу, яка вже оплачується, — тож така
    відмова піднімається до самого верху, а не лишається в переліку
    відкинутих.
    """


@dataclass
class GoResult:
    """Чим скінчився захід — для людини й для машини одним об'єктом."""

    verdict: str = "failed"
    why: str = ""
    run_id: str = ""
    case_key: str = ""
    case_dir: str = ""
    out_dir: str = ""
    backend: str = ""
    pages_done: int = 0
    pages_total: int = 0
    missing: int = 0
    quarantined: int = 0
    #: Скільки пішло на оренду. `None` — бекенд не назвав ціни машини.
    spent_usd: float | None = None
    rent_hours: float = 0.0
    fork_low: float | None = None
    fork_high: float | None = None
    budget_usd: float | None = None
    max_hours: float | None = None
    estimate: dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    #: `None` — машини не брали; `False` — брали й НЕ погасили.
    released: bool | None = None
    #: Чи дійшов цей виклик до оренди (або підхопив уже орендовану машину).
    rented: bool = False
    adopted: bool = False
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)
    #: Справи заходу. Одна справа — рівно одна позиція, і верхні поля дублюють
    #: її значення; кілька — верхні `run_id`/`case_dir`/`out_dir` порожні, бо
    #: «перша справа» на їхньому місці читалась би як відповідь про весь захід.
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.released is False:
            return EXIT_CODES["release_failed"]
        return EXIT_CODES.get(self.verdict, EXIT_CODES["failed"])

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "exit_code": self.exit_code,
                "why": self.why, "run_id": self.run_id,
                "case_key": self.case_key, "case_dir": self.case_dir,
                "out_dir": self.out_dir, "backend": self.backend,
                "pages_done": self.pages_done, "pages_total": self.pages_total,
                "missing": self.missing, "quarantined": self.quarantined,
                "spent_usd": self.spent_usd,
                "rent_hours": round(self.rent_hours, 3),
                "fork_usd": [self.fork_low, self.fork_high],
                "budget_usd": self.budget_usd, "max_hours": self.max_hours,
                "estimate": dict(self.estimate), "decision": self.decision,
                "rented": self.rented, "released": self.released,
                "adopted": self.adopted,
                "dry_run": self.dry_run, "notes": list(self.notes),
                "cases": [c.as_dict() for c in self.cases],
                "run_ids": [c.run_id for c in self.cases if c.run_id]}


@dataclass
class CaseResult:
    """Що сталося з ОДНІЄЮ справою заходу.

    🔴 Існує навіть тоді, коли справа одна: інакше читач мусив би розбирати два
    різні формати відповіді залежно від того, скільки справ він назвав.
    """

    run_id: str = ""
    case_key: str = ""
    case_dir: str = ""
    out_dir: str = ""
    verdict: str = ""
    why: str = ""
    pages_done: int = 0
    pages_total: int = 0
    missing: int = 0
    quarantined: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "case_key": self.case_key,
                "case_dir": self.case_dir, "out_dir": self.out_dir,
                "verdict": self.verdict, "why": self.why,
                "pages_done": self.pages_done, "pages_total": self.pages_total,
                "missing": self.missing, "quarantined": self.quarantined}


def _fill_cases(res: GoResult, convoy: CV.Convoy) -> None:
    """Перенести склад заходу в результат.

    🔴 Одна справа лишає верхні поля рівно такими, як були до появи партій:
    на них спирається і скіл, і пам'ять агентів, і `nysh cloud state <run_id>`.
    Кілька — верхні поля порожніють, а правда живе в `cases[]`. Мовчазне
    «беремо першу» привело б читача дивитись в одну теку й вирішити, що решта
    загубилась.
    """
    res.cases = [CaseResult(run_id=leg.plan.run_id, case_key=leg.plan.case_key,
                            case_dir=str(leg.source), out_dir=str(leg.plan.out_dir),
                            pages_total=leg.plan.frames)
                 for leg in convoy.legs]
    # 🔴 Сторінок — СКІЛЬКИ ПРОЧИТАЄ МАШИНА, а не скільки лишилось за нашим
    # обліком. На наглядацькому шляху прочитане локально на машину не їде
    # (захід відновлюється зі СВОЇХ точок), тож «лишилось 50» на справі в 3000
    # аркушів було б обіцянкою, за якою прийде рахунок на всі три тисячі.
    res.pages_total = sum(c.pages_total for c in res.cases)
    if len(convoy.legs) == 1:
        one = convoy.one
        res.run_id, res.out_dir = one.plan.run_id, str(one.plan.out_dir)
        res.case_dir, res.case_key = str(one.source), one.plan.case_key
    else:
        res.run_id = res.out_dir = res.case_dir = res.case_key = ""


def _case_of(res: GoResult, run_id: str) -> CaseResult | None:
    return next((c for c in res.cases if c.run_id == run_id), None)


def _sync_case(res: GoResult) -> None:
    """Звести підсумок заходу на одну справу в її запис у `cases[]`.

    🔴 `cases[]` мусить існувати ЗАВЖДИ й бути правдою: скіл учить агента
    читати саме його. Доти запис заповнювався один раз, до роботи, — і після
    завершеного заходу казав «0 сторінок, вердикту немає», поки верхні поля
    казали `ok`. Знайдено рев'ю 21.09.2026.
    """
    if len(res.cases) != 1:
        return
    one = res.cases[0]
    one.verdict, one.why = res.verdict, res.why
    one.pages_done, one.missing = res.pages_done, res.missing
    one.quarantined = res.quarantined
    if res.run_id:
        one.run_id = res.run_id
    if res.out_dir:
        one.out_dir = res.out_dir

# ── справа ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CaseRef:
    """Що саме читаємо: тека кадрів, шифра (якщо відома) і скільки кадрів чекати."""

    frames_dir: Path
    key: str = ""
    #: Скільки кадрів знає бібліотека. `0` — не знає.
    frames_expected: int = 0


def case_name(frames_dir: Path) -> str:
    """Ім'я справи. Кадри в `pages/` — справа зветься іменем батьківської теки."""
    return frames_dir.parent.name if frames_dir.name == "pages" else frames_dir.name


def _index() -> Any:
    """Індекс бібліотеки або `None`.

    🔴 Порожня чи ще не зібрана бібліотека — звичайний стан, а не відмова:
    людина, яка щойно поставила застосунок і показала теку зі сканами,
    бібліотеки не має, і вимагати її заради читання означало б замкнути двері,
    до яких вона прийшла. Без індексу не працює лише вхід за шифрою.
    """
    try:
        from nyshporka.cases.resolve import LibraryIndex

        return LibraryIndex()
    except Exception:
        return None


def resolve_case(arg: str) -> CaseRef:
    """Тека кадрів або шифра → `CaseRef`."""
    from nyshporka.cloud.verify import frames_in

    given = Path(arg).expanduser()
    if given.is_dir():
        d = given.resolve()
        if not frames_in(d) and (d / "pages").is_dir():
            d = d / "pages"
        key, expected = "", 0
        index = _index()
        if index is not None:
            from nyshporka.cases.resolve import _from_path

            # Батьківська тека — лише для розкладки `<справа>/pages`. Питати її
            # завжди означало б приписати прогін сусідній справі, щойно тека
            # кадрів лежить усередині чужої: текст під чужою шифрою гірший за
            # текст без шифри.
            for cand in ((d, d.parent) if d.name == "pages" else (d,)):
                try:
                    key = _from_path(str(cand), index) or ""
                except Exception:
                    key = ""
                if key:
                    break
            expected = int((index.by_key.get(key) or {}).get("frames") or 0)
        return CaseRef(frames_dir=d, key=key, frames_expected=expected)

    index = _index()
    found = str((index.canonical(arg) if index is not None else "") or "")
    if not found:
        raise GoRefused(
            f"«{arg}»: ні теки з таким шляхом, ні справи з такою шифрою в "
            f"бібліотеці. Покажіть теку з кадрами або зберіть бібліотеку: "
            f"`nysh cases build`.")
    from nyshporka.cases.register import case_path

    key = found
    entry = index.by_key[key]
    best: tuple[int, Path] | None = None
    for raw in (entry.get("path"), entry.get("raw_path"),
                *(entry.get("extra_paths") or [])):
        if not raw:
            continue
        base = case_path(str(raw))
        for d in (base, base / "pages"):
            if d.is_dir():
                n = len(frames_in(d))
                # Найбільша тека, а не перша: зменшені копії та уривки лежать
                # під тією самою шифрою, і читати треба повну.
                if n and (best is None or n > best[0]):
                    best = (n, d)
    if best is None:
        raise GoRefused(f"{key}: справу бібліотека знає, але теки з кадрами на "
                        f"диску немає")
    return CaseRef(frames_dir=best[1], key=key,
                   frames_expected=int(entry.get("frames") or 0))


def already_read(out_dir: Path, *, model: str, frames: int) -> str:
    """Чи справу вже прочитано ЦІЄЮ моделлю повністю — текст причини або "".

    🔴 Судить мета поруч із текстом, а не реєстр справ: реєстр — зріз, і
    прогін, який паралельна сесія дочитала хвилину тому, він ще не бачить.
    Орендувати машину під уже прочитану справу — найдурніший спосіб витратити
    гроші, і саме він уже траплявся.
    """
    meta = V.read_meta(out_dir)
    if not meta:
        return ""
    if Path(str(meta.get("model") or "")).name != Path(model).name:
        return ""
    pages = meta.get("pages")
    n = len(pages) if isinstance(pages, dict) else 0
    if frames and n >= frames:
        return (f"{out_dir.name}: уже прочитано {n} з {frames} сторінок моделлю "
                f"{Path(model).name} ({meta.get('started') or 'дата невідома'})")
    return ""


def _run_ids(plan: Any, frames_dir: Path) -> set[str]:
    """Ідентифікатори, під якими міг лягти цей самий захід.

    Їх два, бо на машину їде або сама тека кадрів, або її стиснута копія, — а
    котра саме, стає відомо лише після звірки кадрів.
    """
    return {plan.run_id,
            ST.run_id_for(F.shrink_dir_for(frames_dir).resolve(),
                          model=plan.model.name, script=plan.script,
                          backend=plan.backend)}


def _find_live(plan: Any, frames_dir: Path) -> tuple[ST.RunState | None,
                                                    ST.RunState | None]:
    """(свій живий захід, чужий захід у ту саму теку виходу) — або `None`.

    🔴 Свій — лише за `run_id`, тобто за справою, моделлю, письмом і бекендом,
    а не «останній живий»: заходи різних справ ідуть одночасно з різних
    терміналів, і підхопити чужий означало б забрати його результат і
    погасити його машину. Ідентифікаторів-кандидатів два, бо на машину їде
    або сама тека кадрів, або її стиснута копія, — а котра, стане відомо лише
    після звірки кадрів.

    Чужий захід заважає тільки тоді, коли пише в ТУ САМУ теку виходу (та сама
    справа іншим письмом): два прогони в одну теку перетирають тексти один
    одного без жодної помилки.
    """
    ids = _run_ids(plan, frames_dir)
    own: ST.RunState | None = None
    for run_id in sorted(ids):
        st = ST.load(run_id)
        if st is not None and st.needs_release:
            own = st
            break
    out = str(plan.out_dir).replace("\\", "/").rstrip("/").lower()
    clash = next((s for s in ST.live() if s.run_id not in ids and s.out_dir
                  and str(s.out_dir).replace("\\", "/").rstrip("/").lower() == out),
                 None)
    return own, clash


# ── захід ────────────────────────────────────────────────────────────────────
def go(case: str | Sequence[str], *, backend: str = "vast",
       budget: float | None = None,
       max_hours: float | None = None, max_price: float | None = None,
       confirm: bool = False, dry_run: bool = False,
       with_voices: list[str] | tuple[str, ...] = (), second_voice: bool = True,
       script: str = "", model: str = "", case_key: str = "", rerun: bool = False,
       allow_partial: bool = False, rotate_landscape: bool = False,
       thin: bool = False, transport: str = "auto",
       max_usd_per_1000: float = 0.0, params: Sequence[str] = (),
       on_event: EventFn | None = None, tick_sec: float = 60.0) -> GoResult:
    """Прочитати справу (або кілька) на орендованій машині від початку до кінця.

    Кілька справ їдуть ОДНІЄЮ чергою на одну машину: холодний старт коштує
    ~5 хвилин оренди плюс час на ринку, і платити його за кожну справу окремо
    немає за що. Тонкий шлях (`thin`) веде лише одну.

    Не кидає: відмови, збої й Ctrl+C лягають у `GoResult.verdict`, бо викликач
    (командний рядок, агент) мусить дістати ОДИН підсумок на будь-якому шляху —
    зокрема відповідь на питання «чи погашено машину».
    """
    cases = (case,) if isinstance(case, str) else tuple(case)
    res = GoResult(backend=backend, dry_run=dry_run)
    if not cases:
        res.verdict, res.why = "refused", "не названо жодної справи"
        return res

    def say(kind: str, text: str, **data: Any) -> None:
        if on_event is not None:
            on_event(kind, text, **data)

    # Замок власника заходу: бере `_go`, щойно знає `run_id`; відпускаємо тут —
    # після останньої лінії оборони, бо й вона гасить машину.
    owner = contextlib.ExitStack()
    try:
        _go(res, cases, say, owner, backend=backend, budget=budget,
            max_hours=max_hours,
            max_price=max_price, confirm=confirm, dry_run=dry_run,
            with_voices=tuple(with_voices), second_voice=second_voice,
            script=script, model=model, case_key=case_key, rerun=rerun,
            allow_partial=allow_partial, rotate_landscape=rotate_landscape,
            thin=thin, transport=transport,
            max_usd_per_1000=max_usd_per_1000, params=tuple(params),
            tick_sec=tick_sec)
    except GoRefused as exc:
        res.verdict, res.why = exc.verdict, str(exc)
    except KeyboardInterrupt:
        res.verdict, res.why = "cancelled", "перервано з клавіатури"
    except CloudError as exc:
        # `market_empty` і `no_credit` виносяться з кошторису ДО оренди, а не
        # розбором тексту чужої помилки: усе, що впало вже в оренді, — збій.
        res.verdict, res.why = "failed", str(exc)
    except Exception as exc:
        res.verdict, res.why = "failed", f"{type(exc).__name__}: {exc}"
    try:
        _last_line_of_defence(res, say)
    finally:
        owner.close()
    _sync_case(res)
    return res


def _prepare(res: GoResult, case: str, say: EventFn, owner: contextlib.ExitStack, *,
             backend: str, script: str, model: str, case_key: str,
             second_voice: bool, with_voices: tuple[str, ...],
             max_price: float | None, rerun: bool, allow_partial: bool,
             rotate_landscape: bool, dry_run: bool, thin: bool,
             batch: bool) -> tuple[CV.Leg | None, ST.RunState | None]:
    """Підготувати ОДНУ справу заходу: від теки кадрів до готового до відправки.

    Повертає `(справа заходу, живий захід)`. Другий елемент непорожній лише
    тоді, коли цю саму роботу вже веде наш власний захід і його можна
    підхопити — рішення про підхоплення ухвалює викликач, бо в партії воно
    неможливе.

    Кидає `Busy`, коли справу веде хтось інший: така відмова стосується всього
    заходу, бо машина одна.
    """
    from nyshporka.cloud import plan as PL

    ref = resolve_case(case)
    key = case_key or ref.key
    if not batch:
        res.case_dir, res.case_key = str(ref.frames_dir), key
    say("case", f"{key or case_name(ref.frames_dir)} · {ref.frames_dir}")

    def build(frames_dir: Path, **kw: Any) -> PL.CloudPlan:
        kw.setdefault("script", script)
        try:
            return PL.build(
                frames_dir, backend=backend, case_key=key,
                second_voice=second_voice, also=list(with_voices), model=model,
                out_name=case_name(ref.frames_dir),
                max_price_usd_h=max_price, **kw)
        except PL.PlanError as exc:
            raise GoRefused(str(exc)) from None

    # 1а. живий захід ЦІЄЇ роботи — підхопити, а не орендувати вдруге
    plan = build(ref.frames_dir)
    # 🔴 Власник — ПЕРЕД читанням стану. Без замка другий `go` тієї самої справи
    # (зокрема `--dry-run` заради кошторису) бачив «машина є, pid немає» —
    # штатний стан перших 10-20 хвилин підготовки — і гасив бокс, який перший
    # саме готував. Зайнято — відмова без жодної дії над машиною. Ключ — від
    # теки оригіналів: котра тека поїде на машину, стане відомо пізніше.
    try:
        owner.enter_context(ST.owned(plan.run_id))
    except ST.OwnerBusy as exc:
        raise Busy(
            f"{exc} — другий наглядач забрав би його результат і погасив би його "
            f"машину. Стан: `nysh cloud state {exc.run_id}`.") from None
    # 🔴 Відчеплений захід тієї самої роботи живе БЕЗ нашого процесу, і його
    # машини в нашому записі немає — питати треба наглядача. Без цієї перевірки
    # повторна команда (звична дія після обриву термінала) брала б другу машину
    # під справу, яку вже читає перша.
    if not thin:
        from nyshporka.cloud import supervised as SUP

        found = SUP.find_live(_run_ids(plan, ref.frames_dir))
        if found is not None:
            st, data = found
            if not batch:
                res.run_id, res.out_dir = st.run_id, st.out_dir
            if not data:
                raise Busy(
                    f"цю справу веде наглядач {st.supervisor}, але він мовчить "
                    f"— стану немає. Мовчання не означає, що заходу немає: "
                    f"машина може працювати, і друга оренда коштувала б стільки "
                    f"ж. Погляньте самі (`nysh cloud state {st.run_id}`) і "
                    f"перевірте, чи щось тарифікується (`nysh cloud rent "
                    f"status`); якщо захід справді мертвий — згорніть його "
                    f"(`nysh cloud stop {st.run_id} --force`) і повторіть.")
            raise Busy(
                f"цю справу вже читає відчеплений наглядач {st.supervisor} "
                f"(фаза {data.get('phase') or '?'}): {data.get('why') or ''}. "
                f"Стан: `nysh cloud state {st.run_id}`; спинити: "
                f"`nysh cloud stop {st.run_id}`.".replace("  ", " "))

    live, clash = _find_live(plan, ref.frames_dir)
    if clash is not None:
        raise Busy(
            f"у теку {plan.out_dir} уже пише інший захід — {clash.run_id} (та "
            f"сама справа іншою моделлю чи письмом). Два прогони в одну теку "
            f"перетирають тексти один одного. Дочекайтесь його або киньте: "
            f"`nysh cloud stop {clash.run_id} --force`.")
    if live is not None and not live.pid:
        # Машина є, роботи на ній немає: попередній процес убито посеред
        # підготовки. Забирати нічого, а лічильник іде — гасимо ДО кошторису,
        # бо відмова на ньому (брак балансу, потрібен `--confirm`) лишила б
        # сироту тарифікуватись далі.
        say("release", f"машина попередньої спроби ({live.run_id}) жива, а "
                       f"роботи на ній немає — гасимо")
        _release(live, res, say, why="failed:orphaned")
        if res.released is False:
            raise Busy(f"машину попередньої спроби ({live.run_id}) погасити "
                       f"не вдалось — нову поверх неї не беремо")
        res.released = None     # те було про чужу спробу, не про цей захід
        live = None
    if live is not None:
        if dry_run:
            raise Busy(f"захід {live.run_id} уже йде — сухий прогін нічого "
                       f"не покаже. Стан: `nysh cloud state {live.run_id}`.")
        return None, live

    # 2. уже прочитано?
    if not rerun:
        done = already_read(plan.out_dir, model=plan.model.name, frames=plan.frames)
        if done:
            raise GoRefused(f"{done}. Перечитати — `--rerun`; спершу "
                            f"`nysh cases build` і пошук по готовому.")

    # 3. кадри
    rep = F.check_frames(ref.frames_dir)
    say("frames", f"{rep.n} кадрів · {rep.total_mb:.0f} МБ "
                  f"(медіана {rep.median_mb:.1f} МБ)", **rep.as_dict())
    if rep.bad:
        raise GoRefused(
            f"битих кадрів {len(rep.bad)}: " + "; ".join(rep.bad[:5])
            + (" …" if len(rep.bad) > 5 else "") + ". Докачайте їх і повторіть.")
    if rep.still_writing_min is not None and not allow_partial:
        raise GoRefused(
            f"останній кадр записано {rep.still_writing_min} хв тому — тека ще "
            f"качається. Дочекайтесь кінця завантаження (частину справи — "
            f"лише з `--allow-partial`).")
    if ref.frames_expected and rep.n < ref.frames_expected and not allow_partial:
        raise GoRefused(
            f"кадрів {rep.n}, а бібліотека знає {ref.frames_expected} — "
            f"завантаження не дійшло? Частину справи — лише з `--allow-partial`.")

    notes: list[str] = []
    pack = ref.frames_dir
    if rep.heavy:
        dst = F.shrink_dir_for(ref.frames_dir)
        why = (f"кадри завеликі (медіана {rep.median_mb:.1f} МБ)"
               if rep.median_mb > F.SHRINK_MEDIAN_MB else
               f"{len(rep.alien)} кадрів у форматі, якого читач на машині не "
               f"бере (напр. {rep.alien[0]})")
        say("shrink", f"{why} — переводимо в сірий JPEG висотою "
                      f"{F.TARGET_HEIGHT} у {dst}; оригінали не чіпаються")
        got = F.shrink(ref.frames_dir, dst, rotate_landscape=rotate_landscape,
                       on_line=lambda s: say("shrink", s))
        if got.landscape and not rotate_landscape:
            note = (f"{got.landscape} із {got.total} кадрів ширші за висоту. Якщо "
                    f"це зйомка з книгою на боці — повторіть із "
                    f"`--rotate-landscape`: без повороту висота рядка падає "
                    f"вдвічі. Якщо кадр — розворот на два аркуші, усе правильно.")
            notes.append(note)
            res.notes.append(note)
            say("warning", f"⚠ {note}")
        say("shrink", f"стиснуто {got.done}, уже було {got.skipped}"
                      + (f", ×{got.ratio:g} за обсягом" if got.ratio else ""))
        pack = dst

    # 4. план і кошторис
    # Уже прочитане ЦІЄЮ моделлю їде на машину, і вона читає лише решту. З
    # `--rerun` — ні: людина просить перечитати, а привезений текст раннер
    # чесно пропустив би. Текст іншої моделі не їде теж: раннер відмовляється
    # писати в теку з чужим читанням, і захід скінчився б на першій сторінці.
    before = V.verify(plan.out_dir, case_dir=ref.frames_dir)
    meta_model = Path(str(V.read_meta(plan.out_dir).get("model") or "")).name
    seed = not rerun and before.got > 0 and meta_model == plan.model.name
    # Множиною, а не сумою: відкладена сторінка зазвичай і без тексту, тож у
    # двох переліках вона та сама.
    left = len(set(before.missing) | set(before.quarantined)) if seed else None
    # 🔴 Письмо БЕРЕТЬСЯ З ПЕРШОГО плану, а не вгадується вдруге. Здогад
    # дивиться на опис справи поруч із кадрами, а стиснута копія лежить у
    # робочій теці, де опису немає, — тож другий здогад чесно каже «не знаю» і
    # валить справу вже ПІСЛЯ стискання. Спіймано 21.09.2026 на живому заході:
    # `DAHMO/196-8/22` випала з черги, хоч письмо було визначене з першого разу.
    plan = build(pack, script=plan.script,
                 source_dir=ref.frames_dir if pack != ref.frames_dir else "",
                 lines_per_page=F.lines_per_page(plan.out_dir), pages_left=left)
    for w in plan.warnings:
        notes.append(w)
        res.notes.append(w)
        say("warning", f"⚠ {w}")
    if left is not None and thin:
        say("plan", f"уже прочитано {before.got} з {plan.frames} — на машину "
                    f"поїде готове, читатиметься решта ({left})")
    elif left is not None:
        # 🔴 Кажемо правду, а не те, що звучить краще: готове на машину везе
        # лише тонкий шлях (`RUN.start(seed=…)`). Відчеплений захід відновиться
        # з точок відновлення попереднього ЗАХОДУ, якщо вони є, — а прочитане
        # локально їх не лишає, і тоді ці сторінки читатимуться (й оплатяться)
        # наново. Обіцяти тут економію означало б брехати про гроші.
        say("plan", f"уже прочитано {before.got} з {plan.frames} локально, але "
                    f"на машину готове НЕ їде: відчеплений захід відновлюється "
                    f"лише зі своїх точок. Дочитати вдома — `nysh read "
                    f"{ref.frames_dir}`; везти все — просто далі")

    # 5. перечитування: готова сегментація першого прогону їде на машину
    seg_seed: Path | None = None
    coverage = 0.0
    if plan.base_out is not None:
        from nyshporka.htr import seg as SEG

        cache = SEG.inspect(ref.frames_dir, SEG.frames_of(pack), base_out=plan.base_out)
        say("plan", f"{'✓' if cache.usable else '⚠'} сегментація: {cache.why}")
        if cache.usable and cache.path is not None:
            seg_seed, coverage = cache.path, cache.coverage

    return CV.Leg(ref=ref, plan=plan, pack=pack, source=ref.frames_dir,
                  frames=rep, seed=seg_seed, coverage=coverage, resume=seed,
                  notes=tuple(notes)), None


def _last_line_of_defence(res: GoResult, say: EventFn) -> None:
    """Якщо цей виклик брав машину — переконатись, що вона погашена.

    Оренда й заливка живуть у `run.start`, і він гасить машину на власному
    збої сам. Тут те саме питання ставиться ще раз, уже по запису на диску: шлях,
    яким виняток оминув обидва `finally`, дешевше перекрити, ніж довести, що
    його не існує.
    """
    if not res.rented or not res.run_id or res.released is not None:
        return
    try:
        st = ST.load(res.run_id)
    except Exception:
        return
    if st is None or not st.box or not st.bills:
        return
    if st.released:
        res.released = True
        res.spent_usd, res.rent_hours = st.spent_usd(), st.rent_hours()
        return
    _release(st, res, say, why=f"failed:{res.verdict}")
    res.spent_usd, res.rent_hours = st.spent_usd(), st.rent_hours()


def _go(res: GoResult, cases: tuple[str, ...], say: EventFn,
        owner: contextlib.ExitStack, *,
        backend: str, budget: float | None, max_hours: float | None, max_price: float | None,
        confirm: bool, dry_run: bool, with_voices: tuple[str, ...],
        second_voice: bool, script: str, model: str, case_key: str, rerun: bool,
        allow_partial: bool, rotate_landscape: bool, thin: bool,
        transport: str, max_usd_per_1000: float, params: tuple[str, ...],
        tick_sec: float) -> None:
    from nyshporka.cloud import plan as PL

    # 0. бекенд
    try:
        b = RUN._backend(backend)
    except RUN.RunError as exc:
        raise GoRefused(
            f"{exc}. Оренду дає окремий пакет-плагін: "
            f"`pip install \"nyshporka[rent]\"`, далі "
            f"`nysh cloud rent login`.") from None
    if not bills(b):
        raise GoRefused(
            f"«{backend}» нічого не орендує — `nysh cloud go` веде захід з "
            f"орендою від початку до гасіння. Для своєї машини: "
            f"`nysh cloud start <тека> --host <машина>`.")

    def build_for(live: ST.RunState) -> PL.CloudPlan:
        """План для заходу, який ми підхоплюємо: тека й шифра — з його запису."""
        origin = Path(live.source_dir or live.case_dir)
        try:
            return PL.build(
                Path(live.case_dir), backend=backend, script=script,
                case_key=case_key or live.case_key, second_voice=second_voice,
                also=list(with_voices), model=model, out_name=case_name(origin),
                source_dir=live.source_dir or "", max_price_usd_h=max_price)
        except PL.PlanError as exc:
            raise GoRefused(str(exc)) from None

    # 1. справи: кожна готується окремо, і кожна може випасти зі свого приводу
    if case_key and len(cases) > 1:
        # 🔴 Відмова, а не мовчазне відкидання. Шифра — властивість ОДНІЄЇ
        # справи, і прийнявши її для черги, ми або підписали б чужу книгу
        # чужим шифром, або тихо викинули б те, що людина щойно набрала
        # (знайдено рев'ю 21.09.2026).
        raise GoRefused(
            "`--case-key` стосується однієї справи, а названо "
            f"{len(cases)}. Пустіть їх окремо або покладіть `_source.json` "
            f"у теки — шифру візьме бібліотека.")
    legs: list[CV.Leg] = []
    dropped: list[tuple[str, str]] = []
    for arg in cases:
        try:
            leg, live = _prepare(res, arg, say, owner, backend=backend,
                                 script=script, model=model,
                                 case_key=case_key,
                                 second_voice=second_voice, with_voices=with_voices,
                                 max_price=max_price, rerun=rerun,
                                 allow_partial=allow_partial,
                                 rotate_landscape=rotate_landscape,
                                 dry_run=dry_run, thin=thin, batch=len(cases) > 1)
        except Busy:
            # 🔴 Зайнята справа спиняє ВЕСЬ захід: машина одна, і поїхати з
            # рештою означало б узяти другу під роботу, що вже оплачується.
            raise
        except GoRefused as exc:
            if len(cases) == 1:
                raise
            dropped.append((arg, str(exc)))
            say("warning", f"⚠ {arg}: {exc} — справа випадає, решта їде")
            continue
        if live is not None:
            if len(cases) > 1:
                raise Busy(
                    f"{arg}: захід {live.run_id} уже йде. Партію з підхопленням "
                    f"не поєднуємо — повторіть команду для цієї справи окремо, "
                    f"і вона підхопить свою машину")
            plan = build_for(live)
            res.adopted = True
            # Підхоплений захід теж мусить мати запис справи: агент читає
            # `cases[]` незалежно від того, як робота почалась.
            res.cases = [CaseResult(run_id=live.run_id, case_key=live.case_key,
                                    case_dir=live.source_dir or live.case_dir,
                                    out_dir=live.out_dir,
                                    pages_total=live.frames_total)]
            say("adopt", f"захід {live.run_id} уже йде — підхоплено разом зі "
                         f"стелями, другої машини не беремо")
            _supervise(live, plan, res, say, tick_sec=tick_sec)
            return
        if leg is not None:
            legs.append(leg)
    for arg, why in dropped:
        res.notes.append(f"{arg}: {why}")
    if not legs:
        raise GoRefused("жодна справа заходу не поїхала: "
                        + "; ".join(f"{arg} — {why}" for arg, why in dropped))
    try:
        convoy = CV.of(legs, dropped)
    except CV.ConvoyError as exc:
        # Дві справи з однаковим іменем теки — помилка людини, яку ми вміємо
        # назвати, а не наш збій: вердикт `refused`, а не `failed` із класом
        # винятку, приклеєним до ретельно написаного тексту.
        raise GoRefused(str(exc)) from None
    if thin and params:
        # 🔴 Відмова, а не мовчазне ігнорування: тонкий шлях складає команду
        # раннера сам і каналу для параметрів роботи не має. Прийняти прапорець
        # і не передати його означало б дати людині думати, що вона керує
        # прогоном, який іде з дефолтами (знайдено рев'ю 21.09.2026).
        raise GoRefused(
            "`-p` працює лише на наглядацькому шляху: тонкий складає команду "
            "раннера сам і параметрів роботи не передає. Приберіть `--thin` "
            "або `-p`.")
    if thin and len(convoy.legs) > 1:
        # 🔴 Відмова, а не мовчазне «візьму першу»: тонкий шлях тримає ОДНЕ
        # з'єднання, один віддалений каталог і один pid. Оренди ще не було,
        # тож це безплатно.
        raise GoRefused(
            f"тонкий шлях веде одну справу, а названо {len(convoy.legs)}. "
            f"Черга справ їде наглядацьким шляхом — просто без `--thin`.")
    _fill_cases(res, convoy)

    # 4а. наглядацький шлях: далі захід веде відчеплений наглядач, а ми виходимо
    if not thin:
        from nyshporka.cloud import supervised as SUP

        SUP.launch(convoy, res, say, budget=budget, max_hours=max_hours,
                   confirm=confirm, dry_run=dry_run, transport=transport,
                   max_usd_per_1000=max_usd_per_1000, params=params)
        return

    # 4б. тонкий шлях веде ОДНУ справу: одне з'єднання, один віддалений
    # каталог, один pid. Партія сюди не заходить — її спинили ще в `go`.
    leg = convoy.one
    plan, seed = leg.plan, leg.resume

    est = M.ask_estimate(b, plan.need)
    if est is not None:
        res.estimate = est.as_dict()
        say("estimate", est.human(), **est.as_dict())
        if est.empty:
            raise GoRefused(est.human(), verdict="market_empty")
    cost = est.cost if est is not None else None
    if cost is None and budget is None:
        raise GoRefused(
            "кошторису немає: бекенд не назвав ні вартості, ні ціни з годинами. "
            "Вгадувати суму не станемо — назвіть стелю витрат самі: `--budget`.")
    if cost is not None:
        # Вилку звужує лише щільність, яку бекенд справді врахував (відлуння
        # `lines_per_page` у кошторисі), а не та, яку ми йому лише передали.
        known = (plan.lines_per_page is not None and est is not None
                 and est.lines_per_page is not None)
        res.fork_low, res.fork_high = M.budget_fork(cost, density_known=known)
    high = budget if budget is not None else res.fork_high
    assert high is not None
    hours = max_hours if max_hours is not None else (
        M.max_hours_for(est.hours) if est is not None and est.hours is not None
        else M.MAX_HOURS_CAP)
    res.budget_usd, res.max_hours = round(high, 2), hours

    ceiling = M.autostart_ceiling()
    decision = M.decide_launch(high, est.balance_usd if est is not None else None,
                               ceiling, confirm)
    res.decision = decision.why
    fork = (f"${res.fork_low:.2f}–${res.fork_high:.2f}"
            if res.fork_high is not None else "вилки немає (кошторис невідомий)")
    say("money", f"вилка {fork} · бюджет заходу ${high:.2f} · стеля часу "
                 f"{hours:g} год · рішення: {decision.why}")
    _say_burning(b, say)
    if dry_run:
        res.verdict, res.why = "dry_run", "сухий прогін: оренди не було"
        return
    if not decision.launch:
        raise GoRefused(decision.why, verdict=decision.kind)

    # 5. оренда → середовище → заливка → пуск
    plan = replace(plan, budget_usd=round(high, 2), max_hours=hours)
    res.rented = True
    st = RUN.start(plan, auto_prepare=True, seed=seed,
                   on_line=lambda s: say("start", s))
    st.fork_low, st.fork_high = res.fork_low, res.fork_high
    ST.save(st)
    raw_meta = st.box.get("meta")
    doom = raw_meta.get("autodestroy_at") if isinstance(raw_meta, dict) else None
    if doom:
        # Страховка бекенда, не наша: бокс знищить себе сам, навіть якщо ця
        # машина помре. Кажемо вголос — забір мусить устигнути до цієї миті.
        say("start", f"машина сама знищиться не пізніше {doom}")

    # 6–9. нагляд, забір, звірка, догін, гасіння, облік
    _supervise(st, plan, res, say, tick_sec=tick_sec)


def _say_burning(backend: object, say: EventFn) -> None:
    """Сказати, що на акаунті вже тарифікується, — і не відмовляти через це.

    Паралельні заходи штатні, тож чужий бокс не привід зупинятись. Але рядок
    мусить бути: це єдине місце, де людина, яка пускає третій захід, бачить
    забуту машину від учорашнього. Необов'язковий `status()` бекенда; його
    відмова нічого не ламає.
    """
    fn = getattr(backend, "status", None)
    if not callable(fn):
        return
    try:
        raw = fn()
    except Exception as exc:
        say("burning", f"що вже тарифікується на акаунті — невідомо ({exc})")
        return
    burning = raw.get("burning") if isinstance(raw, dict) else None
    if burning is None:
        say("burning", "що вже тарифікується на акаунті — невідомо: спитати в "
                       "провайдера не вдалось")
        return
    rows = [r for r in burning if isinstance(r, dict)] if isinstance(burning, list) else []
    if not rows:
        return
    prices = [M.as_number(r.get("dph_total")) for r in rows]
    total = (f"${sum(p for p in prices if p is not None):.3f}/год"
             if all(p is not None for p in prices) else "сума невідома")
    say("burning", f"на акаунті вже тарифікується {len(rows)} боксів ({total}) — "
                   f"паралельні заходи штатні; чужі видно в `nysh cloud rent status`")


def _ceiling_hit(st: ST.RunState, now: float) -> tuple[str, str]:
    """Яка стеля спрацювала: (`budget_stop` | `deadline` | "", пояснення)."""
    spent = st.spent_usd(now)
    if (st.budget_usd is not None and spent is not None
            and spent >= st.budget_usd - M.STOP_MARGIN_USD):
        return "budget_stop", (f"витрачено ${spent:.2f} з бюджету "
                               f"${st.budget_usd:.2f}")
    hours = st.rent_hours(now)
    if st.max_hours is not None and st.rent_started and hours >= st.max_hours:
        return "deadline", f"минуло {hours:.1f} год зі стелі {st.max_hours:g} год"
    return "", ""


#: Коротший прогін темпу не називає: крок опитування (хвилина) на ньому — це
#: вже десятки відсотків похибки, а число піде в реєстр машин як факт.
PPH_MIN_RUN_SEC = 600.0


def measured_pph(st: ST.RunState, now: float) -> int | None:
    """Виміряний темп машини, сторінок за годину. `None` — міряти нема з чого.

    Рахується лише з того, що ця машина прочитала сама (без привезеного
    готовим), і лише за час роботи, без завантаження боксу й заливки.
    """
    if not st.run_started:
        return None
    sec = now - st.run_started
    pages = st.pages_done - st.pages_seeded
    if sec < PPH_MIN_RUN_SEC or pages <= 0:
        return None
    return max(1, round(pages / (sec / 3600.0)))


def _progress(st: ST.RunState, pulse: RUN.Pulse, now: float) -> str:
    spent = st.spent_usd(now)
    money = "витрати невідомі (бекенд не назвав ціни)" if spent is None else (
        f"витрачено ${spent:.2f}"
        + (f", до стелі ${max(0.0, st.budget_usd - spent):.2f}"
           if st.budget_usd is not None else ""))
    clock = (f" · {st.rent_hours(now):.1f} з {st.max_hours:g} год"
             if st.max_hours is not None else "")
    return (f"{st.human_phase()} · {pulse.pages_done} з {pulse.frames_total} "
            f"({pulse.pct}%) · {money}{clock}")


def _wait(st: ST.RunState, say: EventFn, *,
          tick_sec: float) -> tuple[str, str, bool]:
    """Чекати кінця роботи під двома стелями.

    Повертає (стеля, пояснення, чи бачили роботу живою). Третє потрібне
    виміряному темпу: захід, підхоплений після ночі без термінала, застає
    роботу давно скінченою, і «сторінки ÷ час до цієї миті» було б числом ні
    про що.
    """
    failures = 0
    saw_alive = False
    while True:
        now = _now()
        try:
            pulse = RUN.poll(st)
            failures = 0
        except BoxGone:
            raise
        except (CloudError, OSError, EOFError) as exc:
            # 🔴 Разом із `CloudError` — сирі винятки транспорту. Вбудований SSH
            # обгортає їх сам (`ChannelDropped`), але сесію дає й сторонній
            # бекенд, а ціна промаху тут — здорова робота, вбита аварійним
            # обробником через хвилинний обрив. Кожне опитування відкриває нове
            # з'єднання, тож повтор — це й є перепідключення.
            failures += 1
            say("warning", f"⚠ машина не відповідає ({failures} з "
                           f"{POLL_FAILURES_MAX}): {exc}")
            if failures >= POLL_FAILURES_MAX:
                raise
            pulse = None
        if pulse is not None:
            st.pages_done = pulse.pages_done
            ST.save(st)
            say("progress", _progress(st, pulse, now),
                pages_done=pulse.pages_done, pages_total=pulse.frames_total,
                spent_usd=st.spent_usd(now))
            if pulse.finished or not pulse.alive:
                return "", "", saw_alive
            saw_alive = True
        # 🔴 Стелі перевіряються й тоді, коли машина мовчить: лічильник від
        # нашого зв'язку з нею не залежить.
        hit, why = _ceiling_hit(st, now)
        if hit:
            return hit, why, saw_alive
        _sleep(tick_sec)


#: Паузи між спробами забору, секунд; остання повторюється, доки не стеля.
FETCH_RETRY_PAUSES: tuple[float, ...] = (15.0, 30.0, 60.0, 120.0, 300.0)

#: Скільки спроб забору лишається, коли стеля ВЖЕ спрацювала. Нуль означав би,
#: що зупинений на бюджеті захід втрачає все прочитане через один збій мережі;
#: без ліку — що стеля перестає бути стелею.
FETCH_TRIES_PAST_CEILING = 3


def _fetch_with_retries(st: ST.RunState, say: EventFn) -> None:
    """Забрати результат, переживаючи обриви зв'язку.

    🔴 Один збій мережі в мить забору раніше означав погашену машину з
    неперевезеним текстом: виняток ішов в аварійний обробник, той пробував ще
    раз тим самим каналом у ту саму секунду — і далі стояло гасіння. Машина при
    цьому жива, робота на ній скінчена, а результат лежить на її диску; чекати
    тут коштує центи, а не чекати — всю оплачену справу.

    Повторюються лише відмови ЗВ'ЯЗКУ (`BoxNotReady`, `ChannelDropped`). Решта —
    «машини більше немає», «нема чого забирати», відмова ключа — від повтору не
    зміниться. Межа повторів — ті самі дві стелі, що й у роботи: годинник і
    гроші. Після стелі лишається кілька спроб, і далі гасимо без забору.
    """
    attempt = past_ceiling = 0
    while True:
        try:
            RUN.fetch(st, on_line=lambda s: say("fetch", s))
            return
        except (BoxNotReady, ChannelDropped) as exc:
            attempt += 1
            hit, hit_why = _ceiling_hit(st, _now())
            if hit:
                past_ceiling += 1
                if past_ceiling >= FETCH_TRIES_PAST_CEILING:
                    say("warning", f"⚠ забрати не вдалось і стеля спрацювала "
                                   f"({hit_why}) — далі не чекаємо")
                    raise
            if not FETCH_RETRY_PAUSES:
                raise
            pause = FETCH_RETRY_PAUSES[min(attempt, len(FETCH_RETRY_PAUSES)) - 1]
            st.note("fetch_retry", f"{type(exc).__name__}: {exc}")
            say("warning", f"⚠ забір не вдався (спроба {attempt}): {exc} — машина "
                           f"жива, результат на ній; повтор за {pause:g} с")
            _sleep(pause)


def _fetch_and_verify(st: ST.RunState, res: GoResult, say: EventFn) -> V.Completeness:
    _fetch_with_retries(st, say)
    st.enter("verifying")
    # Звіряємо з ОРИГІНАЛАМИ, коли їхала стиснута копія: правда про те, що мало
    # бути прочитано, лежить там, а імена кадрів у копії ті самі.
    got = V.verify(st.out_dir, case_dir=st.source_dir or st.case_dir,
                   expected_hint=st.frames_total)
    st.pages_done = got.got
    ST.save(st)
    res.pages_done, res.pages_total = got.got, got.expected or st.frames_total
    res.missing, res.quarantined = got.missing_count, len(got.quarantined)
    say("verify", got.human() + (f" · {got.detail}" if got.detail else ""))
    return got


def _release(st: ST.RunState, res: GoResult, say: EventFn, *, why: str) -> None:
    """Погасити машину й записати, чи вдалось. Не кидає ніколи."""
    try:
        try:
            # Спершу — за правилом: із вироком `run.release` пускає сам.
            RUN.release(st, why=why, on_line=lambda s: say("release", s))
        except RUN.RunError:
            # Вирок «неповно» (або його не вдалось записати): забрано все, що
            # на машині було, догін уже зроблено — тримати її далі означає
            # платити за машину, з якої більше нема чого взяти.
            RUN.release(st, why=why, force=True,
                        on_line=lambda s: say("release", s))
        res.released = True
    except Exception as exc:
        res.released = False
        st.note("release_failed", f"{type(exc).__name__}: {exc}")
        ST.save(st)
        # 🔴 Єдиний випадок, коли гроші горять без нагляду, — тому великими
        # літерами і з усіма трьома способами це перевірити й зупинити.
        note = (f"🔴 МАШИНУ НЕ ВДАЛОСЬ ПОГАСИТИ — ЛІЧИЛЬНИК ІДЕ ({exc}). "
                f"Повторіть гасіння: `nysh cloud stop {st.run_id} --force`; "
                f"звірте, що тарифікується: `nysh cloud rent status`; якщо "
                f"машина лишилась — погасіть її в кабінеті провайдера оренди.")
        res.notes.append(note)
        say("release", note)


def _supervise(st: ST.RunState, plan: Any, res: GoResult, say: EventFn, *,
               tick_sec: float) -> None:
    """Від живої роботи до погашеної машини й обліку."""
    res.run_id, res.out_dir = st.run_id, st.out_dir
    res.case_key = res.case_key or st.case_key
    res.pages_total = res.pages_total or st.frames_total
    res.budget_usd, res.max_hours = st.budget_usd, st.max_hours
    res.fork_low, res.fork_high = st.fork_low, st.fork_high
    res.rented = True
    verdict, why, release_why = "failed", "захід обірвано", "failed:interrupted"
    fetched = False
    pph: int | None = None
    try:
        try:
            while True:
                hit, hit_why, saw_alive = _wait(st, say, tick_sec=tick_sec)
                if pph is None and saw_alive and not hit and st.catchups == 0:
                    pph = measured_pph(st, _now())
                if hit:
                    say("ceiling", f"стеля: {hit_why} — зупиняємо роботу й "
                                   f"забираємо прочитане")
                    RUN.stop_job(st)
                got = _fetch_and_verify(st, res, say)
                fetched = True
                if hit:
                    verdict, why, release_why = hit, f"{hit_why}; {got.human()}", hit
                    break
                if got.complete:
                    # Виміряний темп їде бекенду разом із вироком: він пише його
                    # у свій реєстр машин. Невідомий — просто `ok`, без числа.
                    verdict, why = "ok", got.detail
                    release_why = f"ok pph={pph}" if pph else "ok"
                    break
                if V.tail_is_small(got) and st.catchups < 1:
                    say("catchup",
                        f"бракує {got.missing_count + len(got.quarantined)} "
                        f"сторінок — доганяємо на живій машині одним процесом")
                    RUN.catch_up(st, plan, on_line=lambda s: say("catchup", s))
                    continue
                verdict, why = "incomplete", got.human()
                release_why = "failed:incomplete"
                break
        except KeyboardInterrupt:
            verdict, why, release_why = ("cancelled", "перервано з клавіатури",
                                         "cancelled")
            say("cancel", "перервано — забираємо прочитане й гасимо машину "
                          "(ще один Ctrl+C пропустить забір, але не гасіння)")
            fetched = _salvage(st, res, say) or fetched
        except Exception as exc:
            verdict, why = "failed", f"{type(exc).__name__}: {exc}"
            release_why = f"failed:{type(exc).__name__}"
            say("failed", f"🔴 {why} — забираємо, що є, і гасимо машину")
            fetched = _salvage(st, res, say) or fetched
    finally:
        # 🔴 Гасіння — у `finally` зовнішнього блока, тож його не обходить ні
        # виняток із аварійного забору, ні другий Ctrl+C посеред нього. Вирок
        # пишеться ДО гасіння: `run.release` без нього відмовляє, і це правило
        # автономний захід виконує, а не обходить.
        _settle(st, verdict, why)
        _release(st, res, say, why=release_why)
    _finish(st, res, verdict, why, fetched, say)


def _salvage(st: ST.RunState, res: GoResult, say: EventFn) -> bool:
    """Аварійний забір: зупинити роботу й привезти, що є. Не кидає."""
    try:
        RUN.stop_job(st)
    except Exception as exc:
        st.note("stop_failed", f"{type(exc).__name__}: {exc}")
    try:
        _fetch_and_verify(st, res, say)
        return True
    except Exception as exc:
        st.note("salvage_failed", f"{type(exc).__name__}: {exc}")
        res.notes.append(f"забрати прочитане не вдалось: {exc}")
        return False


def _settle(st: ST.RunState, verdict: str, why: str) -> None:
    # Запис вироку не має стати між нами й гасінням машини.
    with contextlib.suppress(Exception):
        st.settle(verdict, why=why)


def _finish(st: ST.RunState, res: GoResult, verdict: str, why: str,
            fetched: bool, say: EventFn) -> None:
    res.verdict, res.why = verdict, why
    res.spent_usd = st.spent_usd()
    res.rent_hours = st.rent_hours()
    if fetched:
        # 🔴 Облік — ПІСЛЯ гасіння: індексація тексту триває хвилини, і робити
        # її при живій машині означало б платити оренду за роботу власного диска.
        for note in bookkeeping(Path(st.out_dir).name):
            res.notes.append(note)
            say("books", f"⚠ {note}")
    spent = "невідомо" if res.spent_usd is None else f"${res.spent_usd:.2f}"
    say("done", f"{verdict} · сторінок {res.pages_done} з {res.pages_total} · "
                f"витрачено {spent} за {res.rent_hours:.2f} год · {st.out_dir}")


def bookkeeping(run_name: str) -> list[str]:
    """Реєстр справ і індекс тексту — те саме, що `nysh cases build` і
    `nysh text index`. Повертає нотатки про збої; порожньо — усе пройшло.

    🔴 Збій обліку не валить захід. Текст уже на диску, машина погашена, і
    «захід не вдався» через зайнятий файл індексу було б неправдою, яка ще й
    спонукає перечитати справу за гроші. Але й мовчати не можна: без
    перебудови реєстр казатиме «декоду немає» про щойно прочитану справу.
    """
    # 🔴 Один облік на простір за раз. Заходи різних справ ідуть паралельно й
    # нерідко кінчаються в одну хвилину; дві перебудови реєстру в той самий файл
    # дали б зріз, у якому бракує справи того, хто писав першим. Замок із
    # ОЧІКУВАННЯМ, а не відмовою: другий просто стає в чергу. Не дочекався —
    # нотатка, і облік однаково пробуємо: пропущена перебудова гірша за ризик.
    from nyshporka.core.workspace import workspace
    from nyshporka.core.xrate import LockTimeout, _locked

    notes: list[str] = []
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_locked(
                workspace().derived / "cloud" / "_bookkeeping.lock",
                timeout=BOOKKEEPING_WAIT_SEC))
        except (LockTimeout, OSError) as exc:
            notes.append(f"облік іншого заходу не скінчився за "
                         f"{BOOKKEEPING_WAIT_SEC:.0f} с ({exc}) — перевірте: "
                         f"`nysh cases build`, `nysh text index`")
        notes += _bookkeeping(run_name)
    return notes


def _bookkeeping(run_name: str) -> list[str]:
    notes: list[str] = []
    try:
        from nyshporka.cases import db

        db.rebuild(rescan=True)
    except Exception as exc:
        notes.append(f"реєстр справ не перебудувався ({type(exc).__name__}: "
                     f"{exc}) — виконайте `nysh cases build`")
    try:
        from nyshporka import ops as O

        env = O.call("text.index", {"case": run_name, "rebuild": False,
                                    "accept_rules": False})
        if not env.ok:
            notes.append(f"індекс тексту не догнано ({env.error}) — виконайте "
                         f"`nysh text index`")
    except Exception as exc:
        notes.append(f"індекс тексту не догнано ({type(exc).__name__}: {exc}) "
                     f"— виконайте `nysh text index`")
    return notes
