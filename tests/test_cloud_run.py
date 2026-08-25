"""🚀 Контур заходу: підхопити своє, забрати, звірити, і лише тоді відпустити.

Машина тут фейкова — тека в `tmp_path` і кілька впізнаваних команд. Цього
досить, бо перевіряються не рушії, а рішення контуру, і кожне з них колись
коштувало грошей або роботи:

* повторний `start` брав ДРУГУ машину при живій першій;
* стан заходу писався ПІСЛЯ оренди, тож машина, що вже тарифікується,
  лишалась невидимою;
* `stop` гасив машину до звірки — разом із тим, що на ній ще лежало;
* голоси розпаковувались в одну теку й тихо перетирали один одного.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from nyshporka.cloud import run as RUN
from nyshporka.cloud import state as ST
from nyshporka.cloud.base import Box, Completed, Need

PROBE_OUT = "\n".join([
    "nproc=16", "nproc_all=16", "mem_total_kb=33000000",
    "gpu=8192,8000", "disk_free_gb=100.0", "python=Python 3.12.3",
])


class FakeSession:
    """Тека на диску, яка вдає чужу машину."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.alive_flag = False
        self.killed = False
        self.spawned: list[str] = []
        self.closed = False

    # ── шляхи ────────────────────────────────────────────────────────────────
    HOME = "/opt/nysh-home"

    def resolve(self, remote: str) -> str:
        return (f"{self.HOME}/{remote[2:]}" if remote.startswith("~/")
                else remote)

    def _local(self, remote: str) -> Path:
        return self.root / remote.lstrip("/").replace("~/", "")

    # ── команди ──────────────────────────────────────────────────────────────
    def run(self, cmd: str, *, timeout=None, on_line=None) -> Completed:
        if "nproc=" in cmd and "cgroup" in cmd:
            return Completed(rc=0, out=PROBE_OUT)
        if "import kraken" in cmd:
            return Completed(rc=0, out="OK 2.4.0 True")
        if "tar -xf" in cmd:
            self._extract()
            return Completed(rc=0, out=f"landed={self._count('case', '.jpg')}")
        if "landed=" in cmd:
            return Completed(rc=0, out=f"landed={self._count('case', '.jpg')}")
        if "tar -cf result.tar" in cmd:
            self._pack_result()
            return Completed(rc=0, out="")
        if "echo pages=" in cmd:
            done = 1 if (self._run_dir() / RUN.DONE_FLAG).exists() else 0
            return Completed(rc=0, out=(
                f"pages={self._count('out', '.txt')}\ndone={done}\nrc=0"))
        return Completed(rc=0, out="")

    def _run_dir(self) -> Path:
        for p in sorted(self.root.rglob("runner.py")):
            return p.parent
        return self.root

    def _count(self, sub: str, suffix: str) -> int:
        d = self._run_dir() / sub
        return len([p for p in d.glob(f"*{suffix}")]) if d.is_dir() else 0

    def _extract(self) -> None:
        for tar_path in self._run_dir().glob("*.tar"):
            with tarfile.open(tar_path) as tar:
                tar.extractall(self._run_dir(), filter="data")

    def _pack_result(self) -> None:
        d = self._run_dir()
        with tarfile.open(d / "result.tar", "w") as tar:
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and sub.name.startswith(RUN.OUT_SUB):
                    for f in sorted(sub.rglob("*")):
                        if f.is_file():
                            tar.add(f, arcname=f"{sub.name}/{f.name}")

    # ── роботи ───────────────────────────────────────────────────────────────
    def spawn(self, cmd: str, *, log: str, pidfile: str) -> int:
        self.spawned.append(cmd)
        self.alive_flag = True
        return 4242

    def alive(self, pid: int) -> bool:
        return self.alive_flag

    def kill(self, pid: int) -> None:
        self.killed = True
        self.alive_flag = False

    # ── файли ────────────────────────────────────────────────────────────────
    def put(self, local: Path, remote: str) -> int:
        dest = self._local(remote)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(local).read_bytes())
        return dest.stat().st_size

    def get(self, remote: str, local: Path) -> int:
        src = self._local(remote)
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(src.read_bytes())
        return src.stat().st_size

    def listdir(self, remote: str) -> list[str]:
        d = self._local(remote)
        return [p.name for p in d.iterdir()] if d.is_dir() else []

    def exists(self, remote: str) -> bool:
        return self._local(remote).exists()

    def read_text(self, remote: str, *, limit: int = 1 << 20) -> str:
        p = self._local(remote)
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def mkdirs(self, remote: str) -> None:
        self._local(remote).mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.closed = True

    # ── те, що робив би раннер ───────────────────────────────────────────────
    def pretend_read(self, names: list[str], *, finished: bool = True) -> None:
        out = self._run_dir() / RUN.OUT_SUB
        out.mkdir(parents=True, exist_ok=True)
        for n in names:
            (out / f"{n}.txt").write_text("текст", encoding="utf-8")
        (out / "_htr_meta.json").write_text(
            json.dumps({"frames_total": len(names)}), encoding="utf-8")
        if finished:
            (self._run_dir() / RUN.DONE_FLAG).write_text("")
            self.alive_flag = False


class FakeBackend:
    """Бекенд, який рахує, скільки разів у нього просили машину."""

    id = "fake"
    label = "Фейкова машина"
    caps = frozenset({"rent", "cancel"})

    def __init__(self, root: Path) -> None:
        self.root = root
        self.session = FakeSession(root)
        self.acquired = 0
        self.released: list[str] = []

    def acquire(self, need: Need, *, target: str = "") -> Box:
        self.acquired += 1
        return Box(id="box-1", backend=self.id, label="фейк", cores=16,
                   vram_gb=8, gpus=1, price_usd_h=0.10,
                   meta={"host": {"host": "fake", "user": "root",
                                  "workdir": str(self.root / "work")}})

    def connect(self, box: Box) -> FakeSession:
        return self.session

    def release(self, box: Box, *, why: str = "") -> None:
        self.released.append(why)

    def find(self, box_id: str) -> Box | None:
        return self.acquire(Need(pages=0))


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return tmp_path


@pytest.fixture
def wired(space: Path, monkeypatch):
    """Справа, ваги й фейковий бекенд, підставлений у реєстр."""
    from nyshporka.cloud import plan as PL
    from nyshporka.htr import run as R

    case = space / "case"
    case.mkdir()
    for i in range(3):
        (case / f"{i:04d}.jpg").write_bytes(b"\0" * 64)
    model = space / "data" / "spotter" / "models" / "model_v1.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"\0" * 16)

    monkeypatch.setattr(R, "pick_model",
                        lambda script, second_voice=True: (model, None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("ARCH/1/2", "тест"))

    backend = FakeBackend(space / "box")
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)
    # Письмо задаємо явно: без опису справи воно чесно лишається невідомим, а
    # хмарний план на «не знаю» відмовляється — це перевіряє окремий тест.
    plan = PL.build(case, backend="fake", target="fake-host", script="cyrillic")
    return plan, backend


# ── ідемпотентність ──────────────────────────────────────────────────────────
def test_second_start_adopts_instead_of_renting_again(wired) -> None:
    """🔴 Головний тест ідемпотентності.

    Без підхоплення повторний `start` після обриву зв'язку брав би ДРУГУ
    машину при живій першій — два прогони на ту саму справу, які б'ються за ті
    самі сторінки, і жодної помилки при цьому.
    """
    plan, backend = wired
    first = RUN.start(plan)
    assert backend.acquired == 1
    assert first.pid == 4242
    assert first.phase == "running"

    second = RUN.start(plan)
    assert backend.acquired == 1, "другої машини не беремо"
    assert second.run_id == first.run_id


def test_run_id_is_the_same_for_the_same_work(wired) -> None:
    """Той самий захід — те саме ім'я. Випадкове ім'я не знаходило б свого."""
    plan, _ = wired
    again = ST.run_id_for(plan.case_dir, model=plan.model.name,
                          script=plan.script, backend="fake")
    assert again == plan.run_id


def test_another_model_is_another_run(wired) -> None:
    """🔴 Читання іншою моделлю — ІНША робота.

    Складене в один захід, воно тихо продовжило б попереднє й видало суміш
    двох моделей за результат.
    """
    plan, _ = wired
    other = ST.run_id_for(plan.case_dir, model="інша_v9.pt",
                          script=plan.script, backend="fake")
    assert other != plan.run_id


def test_the_box_is_recorded_before_it_exists(wired, monkeypatch) -> None:
    """🔴 Намір пишеться ДО оренди — інакше машина стає сиротою.

    Машина, створена після запису, знайдеться навіть якщо процес помре
    наступної секунди. Створена до нього — лишається живою, невидимою й
    оплачуваною: так уже згоріло 4.4 години після смерті наглядача.
    """
    plan, backend = wired
    seen: list[str] = []

    original = backend.acquire

    def watched(need, *, target=""):
        st = ST.load(plan.run_id)
        seen.append(st.phase if st else "нічого не записано")
        return original(need, target=target)

    monkeypatch.setattr(backend, "acquire", watched)
    RUN.start(plan)
    assert seen == ["acquiring"], "фаза мусить бути на диску ДО оренди"


def test_the_tilde_is_expanded_before_anything_uses_it(wired) -> None:
    """🔴 `~/nysh-run` мусить стати справжнім шляхом ДО першої команди.

    Типова тека роботи задається з тильдою, а до оболонки шлях їде в лапках —
    інакше пробіл в імені теки розірвав би команду. У лапках тильда НЕ
    розкривається: `mkdir -p '~/nysh-run'` створює теку з іменем `~` поруч із
    домівкою. Помилки при цьому немає — робота йде, файли пишуться, і
    виявляється це аж тоді, коли по них приходять руками.
    """
    plan, backend = wired
    backend.acquire = lambda need, *, target="": Box(   # type: ignore[method-assign]
        id="box-1", backend="fake", label="фейк", cores=16, vram_gb=8, gpus=1,
        meta={"host": {"host": "fake", "user": "root", "workdir": "~/nysh-run"}})
    st = RUN.start(plan)
    assert "~" not in st.remote_dir, "тильда доїхала до команд нерозкритою"
    assert st.remote_dir.startswith(FakeSession.HOME)


def test_ssh_resolve_is_pure_arithmetic_over_home() -> None:
    """Розкриття шляху перевіряється без жодної машини."""
    from nyshporka.cloud.ssh import Host, SshSession

    # ⚠ Домівка навмисно НЕ схожа на `/home/<ім'я>`: ворота проти приватних
    # даних ловлять такий зразок як шлях із чужої машини, і вони мають рацію —
    # послаблювати їх заради зручності тесту не можна.
    session = SshSession(client=None, host=Host(name="x", user="u", host="h"))
    session._home = "/opt/nysh-home"
    assert session.resolve("~/nysh-run/справа") == "/opt/nysh-home/nysh-run/справа"
    assert session.resolve("~") == "/opt/nysh-home"
    assert session.resolve("/mnt/data/nysh") == "/mnt/data/nysh", "абсолютний — як є"


# ── порядок: забрати → звірити → відпустити ──────────────────────────────────
def test_release_refuses_before_verification(wired) -> None:
    """🔴 Гасити до звірки не можна.

    Забрати й погасити виглядає як одна дія, але між ними лежить єдина точка,
    у якій ще можна врятувати роботу: одного разу так забрали 203 сторінки з
    323 і погасили ту, на якій лежали решта 120.
    """
    plan, backend = wired
    st = RUN.start(plan)
    with pytest.raises(RUN.CloudError, match="не звірено"):
        RUN.release(st)
    assert backend.released == [], "машину не чіпали"


def test_release_goes_through_after_a_verdict(wired) -> None:
    plan, backend = wired
    st = RUN.start(plan)
    st.settle("ok")
    RUN.release(st)
    assert backend.released, "після звірки — можна"
    assert st.released is True
    assert backend.session.killed is True, "роботу зупиняють за pid"


def test_force_is_the_only_way_to_abandon(wired) -> None:
    """Кинути захід можна — але лише сказавши це вголос."""
    plan, backend = wired
    st = RUN.start(plan)
    RUN.release(st, force=True, why="кинуто свідомо")
    assert backend.released == ["кинуто свідомо"]


def test_a_finished_run_with_a_live_box_is_visible(wired) -> None:
    """🔴 Найдорожчий стан — завершена робота при живій машині.

    Тому питання ставиться саме як «чи лишилось що відпускати», а не «чи
    завершився захід».
    """
    plan, _ = wired
    st = RUN.start(plan)
    st.settle("ok")
    assert st.needs_release is True
    with pytest.raises(RuntimeError, match="тримає машину"):
        ST.remove(st.run_id)


# ── повний прохід ────────────────────────────────────────────────────────────
def test_full_pass_reads_fetches_and_verifies(wired) -> None:
    """Захід від початку до вердикту — без жодної справжньої машини."""
    from nyshporka.cloud import verify as V

    plan, backend = wired
    st = RUN.start(plan)

    pulse = RUN.poll(st)
    assert pulse.alive is True and pulse.finished is False

    backend.session.pretend_read(["0000", "0001", "0002"])
    pulse = RUN.poll(st)
    assert (pulse.pages_done, pulse.finished) == (3, True)

    RUN.fetch(st)
    got = V.verify(st.out_dir, case_dir=st.case_dir, expected_hint=st.frames_total)
    assert got.complete is True, got.detail

    meta = json.loads((Path(st.out_dir) / "_htr_meta.json").read_text("utf-8"))
    assert meta["case_key"] == "ARCH/1/2", "шифра штампується після забору"


def test_incomplete_result_is_not_called_done(wired) -> None:
    """Дві сторінки з трьох — це не «прочитано», хоч би що казав прогін."""
    from nyshporka.cloud import verify as V

    plan, backend = wired
    st = RUN.start(plan)
    backend.session.pretend_read(["0000", "0001"])
    RUN.fetch(st)
    got = V.verify(st.out_dir, case_dir=st.case_dir)
    assert got.complete is False
    assert got.missing == ["0002.jpg"]


# ── розкладка привезеного ────────────────────────────────────────────────────
def test_unpack_puts_voices_in_sibling_folders(tmp_path: Path) -> None:
    """🔴 `out-<тег>` лягає ПОРУЧ, а не всередину.

    Складені в одну теку голоси перетирають один одного за іменем файла — і
    пошук потім віддає нуль знахідок без жодної помилки.
    """
    src = tmp_path / "src"
    (src / "out").mkdir(parents=True)
    (src / "out-diak_v4").mkdir()
    (src / "out" / "0001.txt").write_text("перший", encoding="utf-8")
    (src / "out-diak_v4" / "0001.txt").write_text("другий", encoding="utf-8")
    tar_path = tmp_path / "r.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(src / "out" / "0001.txt", arcname="out/0001.txt")
        tar.add(src / "out-diak_v4" / "0001.txt", arcname="out-diak_v4/0001.txt")

    out_dir = tmp_path / "reports" / "sprava"
    RUN.unpack(tar_path, out_dir)
    assert (out_dir / "0001.txt").read_text(encoding="utf-8") == "перший"
    sibling = out_dir.with_name("sprava-diak_v4")
    assert sibling.is_dir(), "голос мусить бути сестринською текою"
    assert (sibling / "0001.txt").read_text(encoding="utf-8") == "другий"


def test_unpack_refuses_to_escape_the_folder(tmp_path: Path) -> None:
    """🔴 Архів прийшов із ЧУЖОЇ машини — довіряти іменам у ньому підстав немає."""
    payload = tmp_path / "evil.txt"
    payload.write_text("шкода", encoding="utf-8")
    tar_path = tmp_path / "r.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(payload, arcname="out/../../стороннє.txt")

    out_dir = tmp_path / "reports" / "sprava"
    RUN.unpack(tar_path, out_dir)
    assert not (tmp_path / "стороннє.txt").exists()


def test_fetch_can_be_repeated(wired) -> None:
    """Повторний забір безпечний: він перезаписує, а не падає на наявному."""
    plan, backend = wired
    st = RUN.start(plan)
    backend.session.pretend_read(["0000", "0001", "0002"])
    RUN.fetch(st)
    RUN.fetch(st)
    assert len(list(Path(st.out_dir).glob("*.txt"))) == 3


# ── реєстр бекендів ──────────────────────────────────────────────────────────
def test_a_broken_plugin_does_not_kill_the_registry(monkeypatch) -> None:
    """🔴 Чужий недописаний пакет не має забирати з собою вбудований SSH.

    Інакше один зламаний плагін відрізає головний шлях користувача — роботу зі
    своєю ж машиною.
    """
    from nyshporka.cloud import registry as REG

    def broken():
        raise RuntimeError("не зібрався")

    class FakeEP:
        name = "zzz-broken"

        def load(self):
            return broken

    monkeypatch.setattr(REG, "_from_entry_points",
                        lambda: ([], [("zzz-broken", "RuntimeError: не зібрався")]))
    reg = REG.load()
    assert reg.get("ssh") is not None, "вбудований бекенд лишається"
    assert reg.broken == [("zzz-broken", "RuntimeError: не зібрався")]


def test_a_plugin_cannot_shadow_the_builtin(monkeypatch) -> None:
    """Підмінити `ssh` стороннім пакетом не можна — це шлях до своєї машини."""
    from nyshporka.cloud import registry as REG

    class Impostor:
        id = "ssh"
        label = "чужий"
        caps = frozenset()

        def acquire(self, need, *, target=""): ...
        def connect(self, box): ...
        def release(self, box, *, why=""): ...
        def find(self, box_id): ...

    monkeypatch.setattr(REG, "_from_entry_points", lambda: ([Impostor()], []))
    reg = REG.load()
    assert reg.get("ssh").label != "чужий"
    assert any("вбудован" in why for _, why in reg.broken)


def test_a_plugin_without_release_is_refused_up_front(monkeypatch) -> None:
    """🔴 Форма перевіряється ОДРАЗУ, а не при першому виклику.

    Плагін без `release` виявився б інакше в найгіршу мить — коли машина вже
    орендована й тарифікується, а звільнити її нічим.
    """
    from nyshporka.cloud import registry as REG

    class Half:
        id = "half"
        label = "недороблений"
        caps = frozenset({"rent"})

        def acquire(self, need, *, target=""): ...
        def connect(self, box): ...

    class EP:
        name = "half"

        def load(self):
            return Half()

    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda group=None: [EP()])
    got, broken = REG._from_entry_points()
    assert got == [], "недороблений плагін до реєстру не потрапляє"
    assert broken and "release" in broken[0][1], "причина називається вголос"
