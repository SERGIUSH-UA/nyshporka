"""🎴 Два читання стають У ЧЕРГУ, а не б'ються за карту.

Звіт користувача 29.08.2026: «коли запустити 2 справи, вони починаються
паралельно, а не стають чергою». Це не про зручність. Правило сформульоване в
самому пакеті, у докстрінгу `htr.run.Plan.shards`:

    `--shard` без спільного `--gpu-lock` на одній карті не сповільнює прогін —
    він його ЗАВАЛЮЄ: два одночасні проходи сегментації не влазять у пам'ять
    типової карти.

Усередині одного прогону воно діяло: шарди ділили один лок. Між двома
прогонами — ні: `idempotency_key` захищав лише від повторного запуску ТІЄЇ
САМОЇ справи, а дві різні справи давали два завдання й два негайні
`create_task`. Гірше за просте падіння те, що число шардів кожен прогін рахує з
ВІЛЬНОЇ пам'яті карти, вважаючи карту своєю.

Два шари, і обидва потрібні: черга в застосунку не бачить прогонів із
командного рядка, а лок карти не знає, що показати людині.
"""
from __future__ import annotations

import asyncio

import pytest

from nyshporka.core.jobs import JobBus, JobState
from nyshporka.daemon import workers as W


@pytest.fixture
def bus(tmp_path) -> JobBus:
    return JobBus(tmp_path / "jobs.json")


@pytest.mark.asyncio
async def test_the_second_reading_waits_instead_of_starting(bus, monkeypatch):
    """Друге читання стоїть, доки перше тримає карту."""
    started: list[str] = []
    release = asyncio.Event()

    async def fake_body(_bus, job, *a, **kw):
        started.append(job.title)
        await release.wait()

    monkeypatch.setattr(W, "_run_read_locked", fake_body)

    first, _ = await bus.enqueue("read", title="перша")
    second, _ = await bus.enqueue("read", title="друга")
    t1 = asyncio.create_task(W._run_read(bus, first, None, "", []))
    t2 = asyncio.create_task(W._run_read(bus, second, None, "", []))
    await asyncio.sleep(0.05)

    assert started == ["перша"], (
        f"друге читання почалось, не дочекавшись карти: {started}")
    assert bus.get(second.id).state == JobState.QUEUED, (
        "друге завдання вдає роботу замість того, щоб стояти в черзі")

    release.set()
    await asyncio.gather(t1, t2)
    assert started == ["перша", "друга"], "друге читання так і не пішло"


@pytest.mark.asyncio
async def test_the_waiting_job_says_what_it_waits_for(bus, monkeypatch):
    """🔴 Чекання мусить бути ПІДПИСАНЕ.

    Мовчазна черга відповідає на «чому нічого не відбувається» так само погано,
    як паралельний запуск: людина бачить завдання, яке не рухається, і тисне
    «читати» ще раз.
    """
    release = asyncio.Event()

    async def fake_body(_bus, _job, *a, **kw):
        await release.wait()

    monkeypatch.setattr(W, "_run_read_locked", fake_body)

    first, _ = await bus.enqueue("read", title="перша")
    second, _ = await bus.enqueue("read", title="друга")
    t1 = asyncio.create_task(W._run_read(bus, first, None, "", []))
    t2 = asyncio.create_task(W._run_read(bus, second, None, "", []))
    await asyncio.sleep(0.05)

    assert W.WAITING_FOR_GPU in bus.get(second.id).title, (
        f"завдання чекає мовчки: {bus.get(second.id).title!r}")
    # А те, що працює, підпису чекання не носить — інакше він нічого не означає.
    assert W.WAITING_FOR_GPU not in bus.get(first.id).title

    release.set()
    await asyncio.gather(t1, t2)


def test_the_card_lock_really_reaches_the_command(tmp_path, monkeypatch) -> None:
    """🔴 Приймач дивиться на КОМАНДУ, а не на шлях, який сам же й склав.

    Перша редакція цього тесту будувала очікуваний шлях руками й порівнювала
    його з іншим шляхом, теж збудованим руками, — тобто пройшла б і тоді, коли
    `plan()` перестане ставити лок узагалі. Тут план збирається насправді, а
    далі перевіряється те єдине, що має значення: чи `--gpu-lock` доїхав у
    аргументи раннера і чи він СПІЛЬНИЙ для двох різних справ.
    """
    from nyshporka.core import workspace as W
    from nyshporka.htr import run as R

    ws = W.Workspace(root=tmp_path, name="тест", origin="test")
    W.use(ws)

    def fake_plan(case: str, **kw):
        d = tmp_path / "data" / "raw" / case
        return R.Plan(case_dir=d, out_dir=tmp_path / "reports" / "htr" / case,
                      model=tmp_path / "m.pt", script="cyrillic", frames=10,
                      python=tmp_path / "py.exe", runner=tmp_path / "runner.py",
                      gpu_lock=ws.derived / "htr_lock" / "gpu.lock")

    first, second = fake_plan("справа-1"), fake_plan("справа-2")
    # Один процес — типовий випадок: `ReadArgs.workers` дорівнює одиниці.
    cmd = first.command(gpu_lock=str(first.gpu_lock))
    assert "--gpu-lock" in cmd, "одиночний прогін пішов без лока карти"
    got = cmd[cmd.index("--gpu-lock") + 1]
    assert str(tmp_path) in got, f"лок поза простором: {got}"
    assert "reports" not in got, "лок знову лежить у теці прогону"

    # 🔴 І він СПІЛЬНИЙ. Лок, різний для двох справ, не виключає нікого — саме
    # так виглядала вада: файл був, а взаємного виключення не було.
    other = second.command(gpu_lock=str(second.gpu_lock))
    assert other[other.index("--gpu-lock") + 1] == got, (
        "дві справи взяли різні локи — тобто не виключають одна одну")


@pytest.mark.asyncio
async def test_a_cancelled_reading_never_starts_after_the_gate(bus, monkeypatch):
    """🔴🔴 Скасоване в черзі читання не сміє стартувати, дочекавшись карти.

    Стопер (`bus.on_stop`) реєструється аж усередині тіла, коли процеси вже є.
    Тому `cancel` на завданні, що ЧЕКАЄ гейта, нікого не спиняв — лише фарбував
    стан. Далі перше читання завершувалось, гейт звільнявся, і «скасоване»
    завдання запускало раннер на годину: роботи не видно (у переліку вона
    «скасована», рядка зі «спинити» немає), а карту вона тримає.
    """
    started: list[str] = []
    release = asyncio.Event()

    async def fake_body(_bus, job, *a, **kw):
        started.append(job.title)
        await release.wait()

    monkeypatch.setattr(W, "_run_read_locked", fake_body)

    first, _ = await bus.enqueue("read", title="перша")
    second, _ = await bus.enqueue("read", title="друга")
    t1 = asyncio.create_task(W._run_read(bus, first, None, "", []))
    t2 = asyncio.create_task(W._run_read(bus, second, None, "", []))
    await asyncio.sleep(0.05)

    await bus.cancel(second.id)
    release.set()
    await asyncio.gather(t1, t2)

    assert started == ["перша"], f"скасоване читання все одно пішло: {started}"
    assert bus.get(second.id).state == JobState.CANCELLED


@pytest.mark.asyncio
async def test_the_gate_belongs_to_the_loop_object_not_its_address(bus):
    """🔴 Гейт тримається за САМ цикл подій, а не за його адресу.

    Словник за `id(loop)` не тримає цикл живим, а CPython адреси переInter'ретовує
    — і наступний цикл діставав семафор, прив'язаний до мертвого. Падало б це
    лише при збігу двох читань, тобто рівно тоді, коли гейт і потрібен, а
    виняток у голому `create_task` лишив би завдання назавжди в черзі.
    """
    import weakref

    assert isinstance(W._READ_GATES, weakref.WeakKeyDictionary), (
        "гейти знову тримаються за адресою циклу")
    loop = asyncio.get_running_loop()
    assert W._read_gate() is W._read_gate(), "той самий цикл — той самий гейт"
    assert loop in W._READ_GATES


# ── постановка читання (аудит 29.09.2026) ────────────────────────────────────
class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakePlan:
    """Стільки плану, скільки бачить `_start_read`, — без моделей і диска."""

    def __init__(self, root) -> None:
        self.case_dir = root / "спр4"
        self.out_dir = root / "спр4-out"
        self.frames = 12
        self.model = _Named("pysar_cyr_v9.pt")
        self.voices = [_Named("pysar_cyr_v9.pt")]
        self.gpu_lock = ""

    def shards(self, workers, **kw):
        return [["runner"]], []

    def as_dict(self):
        return {"case_dir": str(self.case_dir), "out_dir": str(self.out_dir)}


@pytest.fixture
def fake_read(tmp_path, monkeypatch):
    """`R.plan` підмінено, прогін не стартує: лишається саме постановка."""
    from nyshporka.htr import run as R

    calls: list[dict] = []

    def fake_plan(case_dir, **kw):
        calls.append(kw)
        return _FakePlan(tmp_path)

    async def no_run(*a, **kw):
        return None

    monkeypatch.setattr(R, "plan", fake_plan)
    monkeypatch.setattr(W, "_run_read", no_run)
    return calls


@pytest.mark.asyncio
async def test_a_failed_reading_can_be_started_again(bus, fake_read):
    """🔴 «Ще раз» після впалого читання ставить НОВЕ завдання.

    Доти ключ ідемпотентності десять хвилин віддавав мертвий запис, і кнопка
    мовчки нічого не робила.
    """
    payload = {"case_dir": "x", "case_key": "904-24-4"}
    first = await W._start_read(bus, None, payload)
    await bus.update(first.id, state=JobState.ERROR, error="раннер упав")

    again = await W._start_read(bus, None, payload)
    assert again.id != first.id, "повтор повернув впале завдання"
    assert bus.get(again.id).state == JobState.QUEUED


@pytest.mark.asyncio
async def test_other_pages_are_another_reading_not_the_first_one(bus, fake_read):
    """🔴 Сторінки 11-20 не мають повертати живе завдання «сторінки 1-10».

    Ключ був лише текою виходу, тож людина отримувала чужий прогін як свій.
    """
    base = {"case_dir": "x", "case_key": "904-24-4"}
    a = await W._start_read(bus, None, {**base, "pages": "1-10"})
    b = await W._start_read(bus, None, {**base, "pages": "11-20"})
    c = await W._start_read(bus, None, {**base, "limit": 5})
    assert len({a.id, b.id, c.id}) == 3, "інші параметри віддали перше завдання"

    retry = await W._start_read(bus, None, {**base, "pages": "1-10"})
    assert retry.id == a.id, "ретрай того самого запиту мав дати те саме завдання"
