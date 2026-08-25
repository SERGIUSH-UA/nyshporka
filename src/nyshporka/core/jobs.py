"""📋 Черга завдань — одна на простір, із курсором для тих, хто не тримає стрім.

Довгі роботи (читання справи, завантаження плівки, трен) живуть годинами, тож
черга мусить переживати перезапуск, показувати живий прогрес людині й давати
відповідь агентові, який заглядає раз на хвилину. Це три різні читачі одного
стану, і саме тому стан один.

🔴 Чому `enqueue` бере лок ЦІЛКОМ. У попередній реалізації постановка в чергу
робила read-check-append без синхронізації: перевірка дублів, вибір імені,
`append`. Два одночасні запити (два вікна браузера, або людина й агент) могли
дати два завдання з однаковим іменем на ту саму справу — тобто подвоєний прогін,
який б'ється сам із собою за карту й за ті самі сторінки. Помилки при цьому
немає: обидва «успішно поставлені».

Дорогі перевірки (чи є вже декод, чи вільна тека) робляться ДО лока й
повторюються під ним: тримати лок на час читання диска означало б серіалізувати
всіх, а не лише запис.

🔴 Ключ ідемпотентності потрібен саме через агента: він охоче повторює запит
після таймауту мережі, і без ключа кожен ретрай ставив би ще один прогін.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

#: Скільки пам'ятати ключ ідемпотентності. Достатньо, щоб накрити ретраї після
#: обриву, і замало, щоб «той самий ключ через годину» став несподіванкою.
IDEMPOTENCY_TTL_SEC = 600.0
#: Скільки подій тримати для курсорних читачів.
LOG_LIMIT = 2000


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def final(self) -> bool:
        return self in (JobState.DONE, JobState.ERROR, JobState.CANCELLED)


@dataclass
class Progress:
    """Скільки зроблено. `basis` каже, ЧИМ міряно, — бо це різні числа.

    Сторінки, пропущені як уже зроблені (resume), не є роботою: якщо рахувати їх
    у темпі, ETA на початку прогону бреше в рази. Тому доки темп не набрано,
    чесніше сказати «калібрую», ніж показати число.
    """

    i: int = 0
    n: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    rate: float | None = None
    eta_s: int | None = None
    basis: str = "робота"

    @property
    def pct(self) -> float:
        return round(100.0 * self.i / self.n, 1) if self.n else 0.0


@dataclass
class JobRecord:
    id: str
    kind: str
    title: str = ""
    state: JobState = JobState.QUEUED
    cfg: dict[str, Any] = field(default_factory=dict)
    progress: Progress = field(default_factory=Progress)
    result: dict[str, Any] | None = None
    #: Застереження операції, яка цю роботу виконала.
    #:
    #: 🔴 Окремим полем, а не всередині `result`. Саме тут живе знаменник —
    #: «прочесано 876 із 1159», «зріз застарів», — і без нього результат довгої
    #: роботи виглядає повнішим, ніж він є. Доти черга зберігала лише `data`,
    #: тобто рівно ту половину відповіді, яку не можна читати саму.
    warnings: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    idempotency_key: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    seq: int = 0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = str(self.state)
        d["progress"]["pct"] = self.progress.pct
        return d


class JobBus:
    """Черга + журнал подій. Один екземпляр на простір.

    Асинхронна навмисно: усі мутації проходять через один `asyncio.Lock`, тож
    «прочитав-змінив-записав» не може перетнутись саме там, де це найдорожче.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._seq = 0
        self._jobs: dict[str, JobRecord] = {}
        self._log: list[dict[str, Any]] = []
        self._idem: dict[str, tuple[str, float]] = {}
        self._wake = asyncio.Event()
        #: job_id → як спинити роботу НАСПРАВДІ (вбити підпроцес, скасувати
        #: задачу). Без цього `cancel` лише перефарбовував рядок у списку.
        self._stoppers: dict[str, Callable[[], None]] = {}

    # ── читання (без лока: словники читаються атомарно) ──────────────────────
    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def jobs(self, *, state: JobState | None = None) -> list[JobRecord]:
        """Завдання за часом створення.

        ⚠ Метод НЕ називається `list`: усередині тіла класу таке ім'я затуляє
        вбудований тип, і всі наступні анотації `list[...]` починають вказувати
        на метод. mypy це ловить, а читач — ні.
        """
        ordered = sorted(self._jobs.values(), key=lambda j: j.created)
        return [j for j in ordered if state is None or j.state == state]

    @property
    def seq(self) -> int:
        return self._seq

    def since(self, cursor: int) -> tuple[list[dict[str, Any]], int]:
        """Події після `cursor` + новий курсор.

        Курсор, а не підписка: агент не тримає з'єднання, він приходить раз на
        хвилину й питає «що змінилось». Той самий журнал живить і SSE для
        браузера — щоб дві правди не розійшлись.
        """
        return [e for e in self._log if e["seq"] > cursor], self._seq

    async def wait(self, cursor: int,
                   timeout: float = 30.0) -> tuple[list[dict[str, Any]], int]:
        """Дочекатись зміни або таймауту. Завжди повертає стан, не помилку.

        Блокування на СЕРВЕРІ, а не цикл опитувань у клієнта: один виклик
        покриває хвилину очікування замість чотирьох порожніх запитів.
        """
        events, cur = self.since(cursor)
        if events:
            return events, cur
        # Таймаут — це нормальний результат «нічого не змінилось», а не помилка,
        # тож він гаситься, і читач у будь-якому разі отримує стан.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=timeout)
        return self.since(cursor)

    # ── мутації ──────────────────────────────────────────────────────────────
    async def enqueue(self, kind: str, *, title: str = "",
                      cfg: dict[str, Any] | None = None,
                      idempotency_key: str = "",
                      precheck: Callable[[], Awaitable[str | None]] | None = None,
                      ) -> tuple[JobRecord, bool]:
        """Поставити завдання. Повертає (запис, `created`).

        `created=False` означає, що повернуто НАЯВНЕ завдання за ключем
        ідемпотентності — саме те, що потрібно ретраєві після обриву.

        `precheck` виконується ДО лока (там читання диска) і ще раз ПІД локом:
        інакше двоє могли б пройти перевірку одночасно.
        """
        if idempotency_key:
            hit = self._idem_lookup(idempotency_key)
            if hit:
                return hit, False

        if precheck is not None:
            refuse = await precheck()
            if refuse:
                raise ValueError(refuse)

        async with self._lock:
            if idempotency_key:
                hit = self._idem_lookup(idempotency_key)
                if hit:
                    return hit, False
            if precheck is not None:
                refuse = await precheck()
                if refuse:
                    raise ValueError(refuse)

            job = JobRecord(id=uuid.uuid4().hex[:12], kind=kind, title=title,
                            cfg=dict(cfg or {}), idempotency_key=idempotency_key)
            self._jobs[job.id] = job
            if idempotency_key:
                self._idem[idempotency_key] = (job.id, time.time())
            self._bump(job)
            self._persist()
            return job, True

    async def update(self, job_id: str, **fields: Any) -> JobRecord | None:
        """Змінити завдання. Невідомий id — None, а не виняток.

        Прогін міг завершитись і бути прибраним, поки подія йшла з підпроцесу;
        падати на цьому означало б валити воркер через нормальну гонку.
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            # 🔴 Скасоване лишається скасованим. Виконавці доходять до кінця
            # свого тіла й безумовно ставлять DONE/ERROR — тож без цього
            # запобіжника робота, яку людина спинила, через годину сама
            # оголошувала себе виконаною. Решта полів (прогрес, результат)
            # пишеться як є: скільки встигли зробити — корисно знати.
            if (job.state == JobState.CANCELLED and "state" in fields
                    and JobState(fields["state"]) != JobState.CANCELLED):
                fields = {k: v for k, v in fields.items() if k != "state"}
            for k, v in fields.items():
                if k == "state":
                    v = JobState(v)
                setattr(job, k, v)
            self._bump(job)
            self._persist()
            return job

    def on_stop(self, job_id: str, stopper: Callable[[], None]) -> None:
        """Зареєструвати, ЯК спинити цю роботу (вбити підпроцес тощо)."""
        self._stoppers[job_id] = stopper

    def drop_stopper(self, job_id: str) -> None:
        self._stoppers.pop(job_id, None)

    def cancelled(self, job_id: str) -> bool:
        """Чи роботу скасували. Виконавцям — щоб не перефарбувати стан назад."""
        job = self._jobs.get(job_id)
        return job is not None and job.state == JobState.CANCELLED

    async def cancel(self, job_id: str) -> JobRecord | None:
        """Скасувати роботу — з реальною зупинкою того, що вона запустила.

        🔴 Було саме лише виставлення стану: підпроцес раннера жив далі, тримав
        карту годинами, а наприкінці сам перезаписував запис на «готово». Плюс
        ключ ідемпотентності лишався живим 600 с, тож повторний запуск тієї
        самої справи протягом десяти хвилин повертав скасований запис і не
        стартував НІЧОГО — глухий кут без жодної помилки.
        """
        job = self._jobs.get(job_id)
        if job is None or job.state.final:
            return job
        stopper = self._stoppers.pop(job_id, None)
        if stopper is not None:
            # Не вдалось убити підпроцес — стан усе одно виставляємо: приховати
            # скасування було б гірше за осиротілий процес.
            with contextlib.suppress(Exception):
                stopper()
        for key, (jid, _) in list(self._idem.items()):
            if jid == job_id:
                self._idem.pop(key, None)
        return await self.update(job_id, state=JobState.CANCELLED)

    # ── внутрішнє ────────────────────────────────────────────────────────────
    def _idem_lookup(self, key: str) -> JobRecord | None:
        hit = self._idem.get(key)
        if not hit:
            return None
        job_id, when = hit
        if time.time() - when > IDEMPOTENCY_TTL_SEC:
            self._idem.pop(key, None)
            return None
        return self._jobs.get(job_id)

    def _bump(self, job: JobRecord) -> None:
        self._seq += 1
        job.seq = self._seq
        job.updated = time.time()
        self._log.append({"seq": self._seq, "type": "job", "job": job.as_dict()})
        if len(self._log) > LOG_LIMIT:
            del self._log[: len(self._log) - LOG_LIMIT]
        self._wake.set()
        self._wake = asyncio.Event()

    def _persist(self) -> None:
        """Атомарний запис. Помилка запису НЕ валить чергу.

        Диск може бути зайнятий чи повний; втратити стан на рестарті прикро,
        але впасти посеред живого прогону — гірше.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            payload = {"seq": self._seq,
                       "jobs": [j.as_dict() for j in self._jobs.values()]}
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def load(self) -> int:
        """Підняти чергу з диска. Повертає, скільки завдань відновлено.

        🔴 Незавершене завдання відновлюється як ПОМИЛКА, а не як «у черзі».

        Виконавця йому ніхто не повертає: задачі живуть у циклі подій процесу,
        який помер разом із застосунком, і жодного відновлення роботи тут
        немає. «У черзі» означає «буде зроблено» — тож привид у цьому стані
        обіцяє те, чого не станеться: людина чекає, нічого не рухається, і
        виглядає це як зависання, а не як обірваний прогін. Гірше того, така
        робота блокує ЗАПУСК нової: перевірки «чи вже йде» бачать її живою.

        Тому стан чесний, причина написана, а сама робота лишається в журналі
        — вона є доказом того, що прогін починався.
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        for raw in data.get("jobs") or []:
            try:
                prog = Progress(**{k: v for k, v in (raw.get("progress") or {}).items()
                                   if k in Progress.__dataclass_fields__})
                state = JobState(raw.get("state") or "queued")
                err = str(raw.get("error") or "")
                if not state.final:
                    state = JobState.ERROR
                    err = err or ("застосунок зупинився, не докінчивши цю "
                                  "роботу — її треба запустити наново")
                job = JobRecord(
                    id=str(raw["id"]), kind=str(raw.get("kind") or ""),
                    title=str(raw.get("title") or ""), state=state,
                    cfg=dict(raw.get("cfg") or {}), progress=prog,
                    result=raw.get("result"), error=err,
                    created=float(raw.get("created") or time.time()),
                    updated=float(raw.get("updated") or time.time()))
                self._jobs[job.id] = job
            except (KeyError, TypeError, ValueError):
                continue
        self._seq = int(data.get("seq") or 0)
        return len(self._jobs)
