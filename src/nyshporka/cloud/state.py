"""🗃 Стан заходу — те, завдяки чому кожну команду можна повторити.

Хмарний прогін не вміщається в один виклик: заливка, години роботи, забір,
звірка. Між ними людина закриває ноутбук, агент утрачає сесію, процес отримує
Ctrl+C. Тому єдиний спосіб зробити захід надійним — тримати його **на диску**,
а команди зробити такими, що повтор нічого не ламає:

    start   при живій роботі свого заходу — підхоплює її, а не бере другу машину
    fetch   докачує те, чого немає
    verify  чиста функція від диска
    stop    зупиняє за pid зі стану, ніколи за патерном імені

🔴 `run_id` **детермінований** — похідна від справи, моделі, письма й бекенда.
Випадковий ідентифікатор виглядав би так само, але повторний `start` не
знаходив би попереднього заходу й починав другий: дві машини на ту саму справу,
що б'ються за ті самі сторінки, і жодної помилки при цьому.

🔴 Запис фази йде **перед** дією, а не після. Машина, створена після того, як
ми записали намір, знайдеться навіть якщо процес помер наступної секунди;
машина, створена до запису, стає сиротою — живою, невидимою й оплачуваною. Так
уже згоріло 4.4 години оренди після смерті наглядача.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = 1

#: Фази заходу. Порядок важливий: `fetched` не можна перескочити до `released`.
#: `preparing` — на свіжій орендованій машині збирається середовище рушіїв.
#: Окрема фаза, бо це десяток оплачених хвилин, і «веземо» про них бреше.
PHASES = ("planned", "acquiring", "preparing", "uploading", "running",
          "fetching", "verifying", "done", "failed")

#: Вердикти. `incomplete` — не «майже ok»: це стан, у якому машину гасити ще
#: не можна, бо частина роботи лишилась на ній.
#:
#: `budget_stop` і `deadline` виносить лише автономний захід (`cloud.go`):
#: стеля грошей або годин спрацювала, роботу зупинено, наявне забрано й
#: звірено. 🔴 Вони окремі від `failed` навмисно: прочитане на диску справжнє,
#: і повторний захід дочитає решту, — а «збій» читається як «почни заново».
VERDICTS = ("", "ok", "incomplete", "failed", "cancelled", "budget_stop",
            "deadline")


def runs_dir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / "cloud"


_SLUG_RE = re.compile(r"[^\w.\-]+")


def run_id_for(case_dir: str | Path, *, model: str = "", script: str = "",
               backend: str = "") -> str:
    """Той самий захід — той самий ідентифікатор.

    Модель і письмо входять у ключ навмисно: читання тієї самої справи іншою
    моделлю — це інша робота з іншим виходом, і складати їх в один захід
    означало б, що друга тихо продовжить першу й видасть суміш за результат.
    """
    case = Path(case_dir).expanduser()
    slug = _SLUG_RE.sub("_", case.name)[:40].strip("_") or "case"
    seed = "|".join((str(case).lower(), model.lower(), script, backend))
    stamp = hashlib.blake2b(seed.encode("utf-8"), digest_size=4).hexdigest()
    return f"{slug}__{stamp}"


@dataclass
class RunState:
    """Захід, як він виглядає з диска."""

    run_id: str
    case_dir: str = ""
    case_key: str = ""
    out_dir: str = ""
    backend: str = ""
    target: str = ""
    schema: int = SCHEMA
    phase: str = "planned"
    verdict: str = ""
    why: str = ""
    #: `Box.as_dict()` — щоб звільнити машину міг інший процес, який її не брав.
    box: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(default_factory=dict)
    channel: str = ""
    remote_dir: str = ""
    remote_log: str = ""
    #: pid роботи на машині. Єдиний спосіб її зупинити або впізнати живою.
    pid: int = 0
    frames_total: int = 0
    pages_done: int = 0
    #: Чи звільнено машину. 🔴 Окремо від фази: захід буває завершений, а
    #: машина — жива, і саме цю пару треба вміти побачити.
    released: bool = False
    bills: bool = False
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    #: Оригінальна тека кадрів, коли на машину їхала стиснута копія. Порожньо —
    #: `case_dir` і є оригінал.
    source_dir: str = ""
    # ── відчеплений захід (наглядацький шлях) ────────────────────────────────
    #: Сесія наглядача, який веде цей захід замість нас. Порожньо — захід наш:
    #: машину взяли й тримаємо ми самі. 🔴 Відмінність не косметична: у
    #: відчепленого заходу машину гасить наглядач, і питати про неї треба його,
    #: а не наш запис — свого `box` ми тут не знаємо й знати не можемо.
    supervisor: str = ""
    #: План, відданий наглядачеві. Єдине, що дозволяє розібрати захід руками,
    #: коли наглядач помер разом із машиною.
    supervisor_plan: str = ""
    # ── гроші (заповнює автономний захід; у ручного — порожні) ───────────────
    #: Вилка кошторису: низ — прогноз ринку, верх — він же зі множником на
    #: невідому щільність письма. Бюджет заходу = верх.
    fork_low: float | None = None
    fork_high: float | None = None
    #: Стелі заходу. 🔴 Лежать у стані, а не в пам'яті процесу: нагляд мусить
    #: діяти й після обриву термінала, коли захід підхопив інший процес — інакше
    #: стеля діяла б рівно доти, доки її нікому порушити.
    budget_usd: float | None = None
    max_hours: float | None = None
    #: Коли пішов лічильник оренди й коли його зупинено. Окремо від `started`:
    #: запис заходу переживає невдалі спроби, і рахувати витрати від першої з
    #: них означало б приписати живій машині години, яких вона не працювала.
    rent_started: float = 0.0
    rent_ended: float = 0.0
    #: Коли пішла сама робота (після завантаження боксу, рушіїв і заливки) і
    #: скільки сторінок приїхало на машину вже готовими. З цієї пари рахується
    #: ВИМІРЯНИЙ темп машини — його бекенд пише у свій реєстр боксів.
    run_started: float = 0.0
    pages_seeded: int = 0
    #: Скільки разів доганяли хвіст на живій машині. Догін дозволено один:
    #: другий означає, що сторінки не читаються взагалі, і платити за третю
    #: спробу немає за що.
    catchups: int = 0

    # ── дії ──────────────────────────────────────────────────────────────────
    def note(self, kind: str, detail: str) -> RunState:
        """Записати подію. Стан заходу — єдиний журнал, який переживає машину."""
        self.incidents.append({"ts": round(time.time(), 3), "kind": kind,
                               "detail": detail})
        # Тримаємо хвіст: журнал не має рости нескінченно, але останнє важливе.
        if len(self.incidents) > 200:
            self.incidents = self.incidents[-200:]
        return self

    def enter(self, phase: str, *, why: str = "") -> RunState:
        if phase not in PHASES:
            raise ValueError(f"невідома фаза «{phase}»")
        self.phase = phase
        if why:
            self.why = why
        return save(self)

    def settle(self, verdict: str, *, why: str = "") -> RunState:
        if verdict not in VERDICTS:
            raise ValueError(f"невідомий вердикт «{verdict}»")
        self.verdict = verdict
        self.why = why
        self.phase = "done" if verdict in ("ok", "cancelled") else "failed"
        return save(self)

    @property
    def needs_release(self) -> bool:
        """Чи лишилась жива машина, за яку платять.

        🔴 Питання ставиться саме так, а не «чи завершився захід»: найдорожчий
        стан — це успішно завершена робота при живій машині.
        """
        return bool(self.box) and self.bills and not self.released

    @property
    def price_usd_h(self) -> float | None:
        """Ціна години машини, якою її назвав бекенд. `None` — невідома."""
        raw = self.box.get("price_usd_h") if self.box else None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return float(raw)
        return None

    def rent_hours(self, now: float | None = None) -> float:
        """Скільки годин тече (або текла) оренда цього заходу."""
        if not self.rent_started:
            return 0.0
        end = self.rent_ended or (now if now is not None else time.time())
        return max(0.0, end - self.rent_started) / 3600.0

    def spent_usd(self, now: float | None = None) -> float | None:
        """Скільки вже витрачено — ціна × години. `None` — ціна невідома.

        🔴 Саме `None`, а не нуль: «витрачено $0.00» на машині без названої
        ціни читається як «безплатно», і нагляд за бюджетом мовчки вимикається
        там, де він не має чим рахувати. Невідоме лишається невідомим.
        """
        price = self.price_usd_h
        if price is None:
            return None
        return round(price * self.rent_hours(now), 4)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def human_phase(self) -> str:
        names = {"planned": "заплановано", "acquiring": "беремо машину",
                 "preparing": "ставимо рушії",
                 "uploading": "веземо", "running": "читає",
                 "fetching": "забираємо", "verifying": "звіряємо",
                 "done": "завершено", "failed": "збій"}
        return names.get(self.phase, self.phase)


def path_of(run_id: str) -> Path:
    return runs_dir() / f"{run_id}.json"


# ── власник заходу ───────────────────────────────────────────────────────────
class OwnerBusy(RuntimeError):
    """Захід уже веде інший процес."""

    def __init__(self, run_id: str, pid: int) -> None:
        who = f"pid {pid}" if pid else "pid невідомий"
        super().__init__(f"захід {run_id} веде інший процес ({who})")
        self.run_id, self.pid = run_id, pid


_held = threading.local()


@contextlib.contextmanager
def owned(run_id: str) -> Iterator[None]:
    """Один власник на захід — від оренди до погашеної машини.

    🔴 Стан «машина є, pid немає» — штатний для перших 10-20 хвилин заходу
    (підйом боксу, середовище рушіїв, заливка), і той самий стан лишає по собі
    вбитий процес. Розрізнити їх за файлом стану неможливо, а помилка дорога:
    другий `go` тієї самої справи — навіть `--dry-run` заради кошторису —
    вважав машину сиротою й ГАСИВ бокс, який перший саме готував.

    Замок — файловий і рівня ОС (той самий, що боронить `cloud.json`): він
    зникає разом із процесом, хоч би як той помер, тож «вічного» замка після
    вбитого власника не буває й перевіряти живість pid не треба. Файл поруч із
    pid — лише щоб назвати власника людині.

    Повторний вхід із того самого потоку проходить: `go` тримає замок і кличе
    `run.start`, який бере його ж.
    """
    from nyshporka.core.xrate import LockTimeout, _locked

    mine: set[str] | None = getattr(_held, "ids", None)
    if mine is None:
        mine = _held.ids = set()
    if run_id in mine:
        yield
        return
    lock = runs_dir() / f"{run_id}.owner.lock"
    # Не `.json`: перелік заходів збирається з `*.json` цієї теки.
    who = runs_dir() / f"{run_id}.owner.pid"
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_locked(lock, timeout=0.0))
        except LockTimeout:
            pid = 0
            with contextlib.suppress(OSError, ValueError):
                pid = int(who.read_text(encoding="ascii").strip() or 0)
            raise OwnerBusy(run_id, pid) from None
        with contextlib.suppress(OSError):
            who.write_text(str(os.getpid()), encoding="ascii")
        mine.add(run_id)
        try:
            yield
        finally:
            mine.discard(run_id)
            with contextlib.suppress(OSError):
                who.unlink(missing_ok=True)


def save(state: RunState) -> RunState:
    """Записати атомарно. Обрив посеред запису не має лишати сміття."""
    from nyshporka.utils.atomic import write_json

    state.updated = time.time()
    write_json(path_of(state.run_id), state.as_dict())
    return state


def load(run_id: str) -> RunState | None:
    """Прочитати захід. `None` — такого немає.

    🔴 Побитий файл — виняток, а не «немає»: інакше наступний `start` вирішив
    би, що заходу не існує, і взяв би другу машину при живій першій.
    """
    from nyshporka.utils.atomic import read_json

    raw = read_json(path_of(run_id), default=None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        from nyshporka.utils.atomic import CorruptFileError

        raise CorruptFileError(path_of(run_id), "не об'єкт")
    known = {f for f in RunState.__dataclass_fields__}
    return RunState(**{k: v for k, v in raw.items() if k in known})


def all_runs() -> list[RunState]:
    """Усі заходи простору, новіші першими."""
    try:
        d = runs_dir()
    except Exception:
        return []
    if not d.is_dir():
        return []
    out: list[RunState] = []
    for p in d.glob("*.json"):
        try:
            st = load(p.stem)
        except Exception:
            continue
        if st is not None:
            out.append(st)
    return sorted(out, key=lambda s: s.updated, reverse=True)


def live() -> list[RunState]:
    """Заходи, які ще щось тримають: незавершені або з незвільненою машиною."""
    return [s for s in all_runs()
            if s.phase not in ("done", "failed") or s.needs_release]


def remove(run_id: str) -> bool:
    """Прибрати запис заходу.

    🔴 Відмовляє, поки машина не звільнена. Видалити стан із живою орендою
    означає втратити єдину адресу, якою її можна погасити, — тобто перетворити
    забутий захід на рахунок.
    """
    st = load(run_id)
    if st is not None and st.needs_release:
        raise RuntimeError(
            f"захід {run_id} ще тримає машину ({st.box.get('label') or st.box.get('id')}). "
            f"Спершу `nysh cloud stop {run_id}`")
    path_of(run_id).unlink(missing_ok=True)
    return True
