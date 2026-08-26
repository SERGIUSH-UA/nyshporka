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

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = 1

#: Фази заходу. Порядок важливий: `fetched` не можна перескочити до `released`.
PHASES = ("planned", "acquiring", "uploading", "running", "fetching",
          "verifying", "done", "failed")

#: Вердикти. `incomplete` — не «майже ok»: це стан, у якому машину гасити ще
#: не можна, бо частина роботи лишилась на ній.
VERDICTS = ("", "ok", "incomplete", "failed", "cancelled")


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def human_phase(self) -> str:
        names = {"planned": "заплановано", "acquiring": "беремо машину",
                 "uploading": "веземо", "running": "читає",
                 "fetching": "забираємо", "verifying": "звіряємо",
                 "done": "завершено", "failed": "збій"}
        return names.get(self.phase, self.phase)


def path_of(run_id: str) -> Path:
    return runs_dir() / f"{run_id}.json"


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
