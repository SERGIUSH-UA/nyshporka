"""🚀 Захід: узяти машину, привезти, прочитати, забрати, звірити, відпустити.

Порядок кроків тут не описовий, а обов'язковий, і два місця в ньому куплені
дорого:

* **проба заліза — ПЕРЕД заливкою.** Усе до неї коштує секунди, усе після —
  хвилини й гігабайти. Машина, яка обіцяла 192 ядра, а дала 48, мусить бути
  відсіяна до того, як на неї поїхали кадри;
* **звірка — ПЕРЕД звільненням.** Забрати й погасити виглядає як одна дія, але
  між ними лежить єдина точка, у якій ще можна врятувати роботу: одного разу
  так забрали 203 сторінки з 323 і погасили машину, на якій лежали решта 120.

🔴 Кожна команда тут повторювана. `start` при живій роботі свого заходу
підхоплює її замість того, щоб брати другу машину; `fetch` докачує; `verify`
взагалі нічого не змінює. Це не зручність, а єдиний спосіб пережити обрив
з'єднання, закритий ноутбук і Ctrl+C — тобто нормальне життя багатогодинної
роботи.

🔴 Робота на машині живе ВІДЧЕПЛЕНО від нашого з'єднання. Нишпорка її не
«тримає», а лише опитує: скільки текстів уже на диску машини й чи живий той
самий pid. Тому вбитий локальний процес не вбиває прогін, а `nysh cloud state`
однаково працює з іншої сесії й навіть з іншого комп'ютера.
"""
from __future__ import annotations

import shlex
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from nyshporka.cloud import state as ST
from nyshporka.cloud.base import Box, CloudError, Session
from nyshporka.cloud.plan import CloudPlan
from nyshporka.cloud.probe import measure
from nyshporka.cloud.registry import load as load_registry

#: Імена на машині. Прості й передбачувані: за ними доводиться ходити з іншої
#: сесії, іноді руками через `ssh`.
CASE_SUB = "case"
OUT_SUB = "out"
MODELS_SUB = "models"
LOGS_SUB = "logs"
GO_SCRIPT = "go.sh"
DONE_FLAG = "_done"
RC_FILE = "_rc"
VENV_SUB = ".venv"

#: Скільки чекати завершення однієї службової команди на машині.
CMD_TIMEOUT = 900.0


class RunError(CloudError):
    """Захід не вдався — з поясненням, на якому кроці."""


# ── команди раннера ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Shard:
    """Один процес прогону: що запускати і з яким середовищем."""

    cmd: list[str]
    #: `CUDA_VISIBLE_DEVICES` та обмежувачі потоків BLAS.
    env: dict[str, str]


def remote_commands(*, remote_dir: str, python: str, model: str,
                    voice: str, script: str, case_key: str, workers: int,
                    device: str, gpus: int = 1, cores: float = 0.0,
                    seg_height: int = 0) -> tuple[list[Shard], list[str]]:
    """Ті самі команди, що й локально, тільки шляхами чужої машини.

    🔴 Рядок команди будує ТА САМА `Plan`, що й локальний прогін. Друга збірка
    поруч розійшлася б із першою від першої ж нової опції — рівно як застерігає
    докстрінг `htr.run`.

    🔴 На ОДНІЙ карті беремо готову `Plan.shards()`: вона тримає інваріанту
    трьох прапорців (`--shard` + спільний `--gpu-lock` + знятий з карти `sato`),
    які народжуються й помирають разом.

    🔴 На КІЛЬКОХ картах цієї інваріанти замало, і це не дрібниця. Спільний лок
    на всі шарди звів би вісім карт до однієї — вони стали б у чергу за правом
    рахувати сегментацію. Тому лок стає ПОКАРТКОВИМ, а шард `k` бачить лише
    карту `k % N`: спільна карта на всі шарди одного разу дала півтори тисячі
    записів про брак пам'яті — і жодної помилки в підсумку, бо шард виходить із
    нульовим кодом.

    ⚠ Шляхи тут `PurePosixPath`, а поля `Plan` анотовані `Path`. Це свідомо:
    `Plan` користується ними ЛИШЕ через `str()`, а `Path` на Windows перетворив
    би `/root/run` на `\\root\\run` — тобто зламав би команду саме на тій
    машині, з якої її найчастіше й запускають.
    """
    from nyshporka.htr.run import Plan, shard_env

    root = PurePosixPath(remote_dir)
    plan = Plan(
        case_dir=root / CASE_SUB,          # type: ignore[arg-type]
        out_dir=root / OUT_SUB,            # type: ignore[arg-type]
        model=PurePosixPath(model),        # type: ignore[arg-type]
        script=script, frames=0,
        python=PurePosixPath(python),      # type: ignore[arg-type]
        runner=root / "runner.py",         # type: ignore[arg-type]
        voice=PurePosixPath(voice) if voice else None,  # type: ignore[arg-type]
        seg_cache=root / "seg_cache",      # type: ignore[arg-type]
        gpu_lock=root / "_gpu.lock")       # type: ignore[arg-type]

    n = max(1, int(workers or 1))
    cards = max(1, int(gpus or 1))
    # 🔴 Ядра — ЧУЖОЇ машини. Порахувати їх нашими означало б поділити вісім
    # ядер орендованої машини за числом ядер ноутбука, з якого її запустили.
    base_env = shard_env(n, cores=int(cores))

    if cards <= 1:
        cmds, notes = plan.shards(n, device=device, case_key=case_key,
                                  seg_height=seg_height)
        return [Shard(cmd=c, env=dict(base_env)) for c in cmds], notes

    shards: list[Shard] = []
    for k in range(n):
        card = k % cards
        env = dict(base_env)
        # Кожен процес бачить РІВНО одну карту, тож `cuda:0` всередині нього —
        # це вже його власна карта. Так раннеру не треба знати про розкладку.
        env["CUDA_VISIBLE_DEVICES"] = str(card)
        shards.append(Shard(
            cmd=plan.command(shard=f"{k + 1}/{n}", case_key=case_key,
                             gpu_lock=f"{root}/_gpu.lock.{card}",
                             gpu_sato=False, seg_height=seg_height),
            env=env))
    return shards, [
        f"{n} процесів на {cards} картах: по одному локу НА КАРТУ, "
        f"шард k бачить карту k%{cards}. Спільний лок звів би карти до однієї"]


def go_script(shards: list[Shard], *, remote_dir: str) -> str:
    """Скрипт, який веде всі процеси й лишає слід свого завершення.

    🔴 Прапорець завершення пишеться ЗАВЖДИ, навіть коли процеси впали. Без
    нього «робота ще йде» і «робота впала» виглядають однаково — як тиша, і
    саме в цій тиші захід або чекають вічно, або кидають зарано.
    """
    lines = ["#!/bin/sh", "set -u", f"cd {shlex.quote(remote_dir)} || exit 90",
             f"mkdir -p {LOGS_SUB} {OUT_SUB}", "rc=0"]
    for k, shard in enumerate(shards):
        log = f"{LOGS_SUB}/shard{k + 1}.log"
        env = " ".join(f"{key}={shlex.quote(val)}"
                       for key, val in sorted(shard.env.items()))
        body = " ".join(shlex.quote(c) for c in shard.cmd)
        lines.append(f"{env + ' ' if env else ''}{body} > {log} 2>&1 &")
        lines.append(f"p{k}=$!")
    for k in range(len(shards)):
        lines.append(f"wait ${{p{k}}} || rc=$?")
    lines += [f"echo $rc > {RC_FILE}", f"touch {DONE_FLAG}", "exit $rc"]
    return "\n".join(lines) + "\n"


# ── підготовка машини ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EngineState:
    """Чи є на машині чим читати."""

    ready: bool
    python: str = ""
    detail: str = ""


def engine_state(session: Session, remote_dir: str) -> EngineState:
    """Перевірити середовище рушіїв на машині — одним заходом."""
    py = f"{PurePosixPath(session.resolve(remote_dir)).parent}/{VENV_SUB}/bin/python"
    code = ("import kraken, torch, PIL, numpy;"
            "print('OK', torch.__version__, torch.cuda.is_available())")
    got = session.run(
        f"{shlex.quote(py)} -c {shlex.quote(code)} 2>&1 || true",
        timeout=300.0)
    if "OK" in got.out:
        return EngineState(ready=True, python=py, detail=got.out.strip())
    return EngineState(ready=False, python=py,
                       detail=got.out.strip()[:300] or "середовища немає")


def prepare(session: Session, remote_dir: str, *,
            on_line: Any = None) -> EngineState:
    """Зібрати середовище рушіїв на машині. Ідемпотентно.

    🔴 Пакети ставляться ПО ОДНОМУ, а не списком. Причина конкретна: рушій
    сегментації тягне власну збірку суміжної бібліотеки, і встановлення всього
    разом падає на розв'язанні версій — при тому, що кожен пакет окремо
    ставиться без жодних заперечень.

    ⚠ Колесо під карту доставляється лише тоді, коли карту видно й вона в
    відомих межах. Не побачити карту — не помилка: читання піде процесором,
    просто повільніше. Неправильне колесо не працювало б узагалі.
    """
    from nyshporka.htr import manifest as M

    man = M.active()
    remote_dir = session.resolve(remote_dir)
    root = PurePosixPath(remote_dir).parent
    venv = f"{root}/{VENV_SUB}"
    py = f"{venv}/bin/python"

    def step(cmd: str, why: str, timeout: float = 1800.0) -> None:
        got = session.run(cmd, timeout=timeout, on_line=on_line)
        if got.rc != 0:
            raise RunError(f"{why}: rc={got.rc} "
                           f"{(got.err or got.out).strip()[:300]}")

    have_uv = session.run("command -v uv >/dev/null 2>&1 && echo yes || echo no",
                          timeout=60.0)
    if "yes" not in have_uv.out:
        step("curl -LsSf https://astral.sh/uv/install.sh | sh",
             "не вдалось поставити `uv` на машину")
    uv = "$HOME/.local/bin/uv"
    step(f"({uv} --version || uv --version) >/dev/null 2>&1", "`uv` не працює")
    step(f"{uv} venv {shlex.quote(venv)} --python {man.python}",
         "не вдалось створити середовище")

    for spec in man.pip_specs():
        step(f"{uv} pip install --python {shlex.quote(py)} {shlex.quote(spec)}",
             f"не поставився {spec}")

    cap = session.run(
        f"{shlex.quote(py)} -c \"import torch;"
        f"print('%d.%d' % torch.cuda.get_device_capability(0))"
        f" if torch.cuda.device_count() else print('')\" 2>/dev/null || true",
        timeout=300.0)
    tag = man.cuda_tag(cap.out.strip())
    if tag:
        step(f"{uv} pip install --python {shlex.quote(py)} --reinstall "
             f"{' '.join(man.torch_default)} --index-url {man.cuda_index_url(tag)}",
             "не доставилось колесо під карту", timeout=3600.0)
    return engine_state(session, remote_dir)


# ── заливка ──────────────────────────────────────────────────────────────────
def pack_frames(case_dir: Path, dest: Path) -> Path:
    """Скласти кадри в ОДИН архів — без стиснення.

    🔴 Без gzip навмисно: кадри вже стиснуті, і другий прохід з'їдає хвилини
    процесора заради відсотка обсягу. 🔴 Одним архівом, а не файлами: тисяча
    окремих передач упирається не в смугу, а в рукостискання — ті самі байти
    одним об'єктом їдуть у десятки разів швидше.
    """
    from nyshporka.cloud.verify import frames_in

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with tarfile.open(tmp, "w") as tar:
        for p in frames_in(case_dir):
            tar.add(p, arcname=f"{CASE_SUB}/{p.name}")
    tmp.replace(dest)
    return dest


def _upload_assets(session: Session, plan: CloudPlan, remote_dir: str,
                   *, on_line: Any = None) -> None:
    """Раннер, патчі й ваги — усе, чим читатимуть."""
    from nyshporka.htr import runner as _runner_mod

    runner_py = Path(_runner_mod.__file__).resolve()
    session.mkdirs(f"{remote_dir}/{MODELS_SUB}")
    session.mkdirs(f"{remote_dir}/patches")
    session.put(runner_py, f"{remote_dir}/runner.py")
    # 🔴 Патчі їдуть ПОРУЧ із раннером, бо він вантажить їх за шляхом, а не
    # імпортом пакета: на машині `nyshporka` не встановлено й не буде.
    for p in sorted((runner_py.parent / "patches").glob("*.py")):
        session.put(p, f"{remote_dir}/patches/{p.name}")
    session.put(plan.model, f"{remote_dir}/{MODELS_SUB}/{plan.model.name}")
    if plan.voice is not None:
        session.put(plan.voice, f"{remote_dir}/{MODELS_SUB}/{plan.voice.name}")
    if on_line:
        on_line(f"ваги й раннер на місці: {plan.model.name}"
                + (f" + {plan.voice.name}" if plan.voice else ""))


def _upload_frames(session: Session, plan: CloudPlan, remote_dir: str, *,
                   storage: Any = None, on_line: Any = None) -> None:
    """Кадри — через сховище, якщо воно є, інакше прямо."""
    from nyshporka.cloud import transfer as T
    from nyshporka.core.workspace import workspace

    tmp_dir = workspace().derived / "cloud" / "tmp"
    tar_path = pack_frames(plan.case_dir, tmp_dir / f"{plan.run_id}.tar")
    try:
        if storage is not None and storage.configured:
            key = storage.key_for(plan.run_id, "case.tar")
            T.upload(storage, tar_path, key)
            url = T.presign(storage, key)
            remote_tar = T.fetch_to_box(session, url, remote_dir)
            if on_line:
                on_line("кадри доїхали через сховище")
        else:
            remote_tar = f"{remote_dir}/case.tar"
            session.put(tar_path, remote_tar)
            if on_line:
                on_line("кадри доїхали напряму")
        got = session.run(
            f"cd {shlex.quote(remote_dir)} && tar -xf {shlex.quote(remote_tar)} "
            f"&& rm -f {shlex.quote(remote_tar)}; "
            f"echo landed=$(ls {CASE_SUB} 2>/dev/null | wc -l)",
            timeout=CMD_TIMEOUT)
        landed = 0
        for line in got.out.splitlines():
            key, sep, val = line.strip().partition("=")
            if sep and key == "landed" and val.strip().isdigit():
                landed = int(val.strip())
        # 🔴 Приймач заливки — число кадрів НА МАШИНІ, а не код розпакування.
        # Обірваний архів розпаковується частково й без помилки.
        if landed < plan.frames:
            raise RunError(
                f"на машину доїхало {landed} кадрів із {plan.frames} — "
                f"заливку треба повторити, читати неповне немає сенсу")
    finally:
        tar_path.unlink(missing_ok=True)


# ── захід ────────────────────────────────────────────────────────────────────
def _backend(name: str) -> Any:
    reg = load_registry()
    got = reg.get(name)
    if got is None:
        known = ", ".join(b.id for b in reg.all()) or "(жодного)"
        extra = ""
        if reg.broken:
            extra = ("; не завантажились: "
                     + "; ".join(f"{n} ({why})" for n, why in reg.broken))
        raise RunError(f"немає бекенда «{name}». Є: {known}{extra}")
    return got


def adopt(st: ST.RunState) -> tuple[Session, Box] | None:
    """Підхопити свій живий захід. `None` — підхоплювати нічого.

    🔴 Саме підхопити, а не почати заново. Без цього кроку повторний `start`
    після обриву брав би другу машину при живій першій — два прогони на ту саму
    справу, які б'ються за ті самі сторінки, і жодної помилки при цьому.
    """
    if not st.box or not st.pid:
        return None
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    try:
        session = backend.connect(box)
    except CloudError:
        return None
    if not session.alive(st.pid):
        session.close()
        return None
    return session, box


def start(plan: CloudPlan, *, workers: int = 0, seg_height: int = 0,
          on_line: Any = None) -> ST.RunState:
    """Почати або підхопити захід. Повертається одразу — робота лишається жити.

    Повторний виклик на живому заході нічого не робить, а на завершеному —
    веде до `fetch`, а не до другого прогону.
    """
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import transfer as T

    say = on_line or (lambda _s: None)
    st = ST.load(plan.run_id) or ST.RunState(
        run_id=plan.run_id, case_dir=str(plan.case_dir), case_key=plan.case_key,
        out_dir=str(plan.out_dir), backend=plan.backend, target=plan.target,
        frames_total=plan.frames)
    st.frames_total = plan.frames

    live = adopt(st)
    if live is not None:
        session, _box = live
        session.close()
        say(f"захід {st.run_id} уже працює (pid {st.pid}) — підхоплено, "
            f"другої машини не беремо")
        return ST.save(st)

    backend = _backend(plan.backend)
    st.bills = bool(getattr(backend, "caps", frozenset()) & {"rent"})

    # 🔴 Намір записується ДО того, як машина існує. Машина, створена після
    # запису, знайдеться навіть якщо процес помре наступної секунди; створена
    # до нього — стає живою, невидимою й оплачуваною.
    st.enter("acquiring", why=f"беремо машину через «{plan.backend}»")
    box = backend.acquire(plan.need, target=plan.target)
    st.box = box.as_dict()
    st.note("acquired", f"машина {box.label or box.id}")
    ST.save(st)

    session = backend.connect(box)
    try:
        probe = measure(session)
        st.probe = probe.as_dict()
        say(f"машина: {probe.human()}")
        measured = PL.with_probe(plan, probe, shards=workers)
        if measured.sizing is None:                      # pragma: no cover
            raise RunError("не вдалось порахувати розбиття")
        st.sizing = measured.sizing.as_dict()
        for w in measured.warnings:
            st.note("warning", w)
            say(f"⚠ {w}")
        ST.save(st)

        # 🔴 Розкриваємо тильду ОДРАЗУ: далі цей рядок їде і в команди (де він
        # у лапках, тож `~` не розкрилась би), і в SFTP, і в стан заходу, по
        # якому людина потім ходить руками. Один рядок правди на всі три.
        remote_dir = session.resolve(_remote_dir(box, st.run_id))
        st.remote_dir = remote_dir
        engine = engine_state(session, remote_dir)
        if not engine.ready:
            raise RunError(
                f"на машині немає середовища рушіїв ({engine.detail}). "
                f"Зберіть його один раз: `nysh cloud prepare {plan.target or box.id}` "
                f"— далі воно перевикористовується.")

        st.enter("uploading", why="веземо ваги й кадри")
        session.mkdirs(remote_dir)
        _upload_assets(session, plan, remote_dir, on_line=say)
        _upload_frames(session, plan, remote_dir,
                       storage=T.load_storage(), on_line=say)

        device = "cuda:0" if probe.has_gpu else "cpu"
        cmds, notes = remote_commands(
            remote_dir=remote_dir, python=engine.python,
            model=f"{remote_dir}/{MODELS_SUB}/{plan.model.name}",
            voice=(f"{remote_dir}/{MODELS_SUB}/{plan.voice.name}"
                   if plan.voice else ""),
            script=plan.script, case_key=plan.case_key,
            workers=measured.sizing.shards, device=device,
            gpus=probe.gpus if probe.has_gpu else 1, cores=probe.cores,
            seg_height=seg_height)
        for n in notes:
            say(n)
            st.note("shards", n)

        script_path = f"{remote_dir}/{GO_SCRIPT}"
        _put_text(session, script_path, go_script(cmds, remote_dir=remote_dir))
        session.run(f"rm -f {shlex.quote(remote_dir)}/{DONE_FLAG} "
                    f"{shlex.quote(remote_dir)}/{RC_FILE}", timeout=CMD_TIMEOUT)

        st.remote_log = f"{remote_dir}/{LOGS_SUB}/go.log"
        st.enter("running", why=f"{measured.sizing.shards} процесів на {device}")
        st.pid = session.spawn(f"sh {shlex.quote(script_path)}",
                               log=st.remote_log,
                               pidfile=f"{remote_dir}/_pid")
        say(f"пішло: pid {st.pid}, {measured.sizing.shards} процесів, "
            f"~{measured.hours:.1f} год за розрахунком")
        return ST.save(st)
    except Exception as exc:
        st.note("failed", f"{type(exc).__name__}: {exc}")
        st.enter("failed", why=str(exc))
        # 🔴 Машину, яка тарифікується, не лишаємо живою через власну помилку:
        # це рівно той стан, у якому гроші течуть, а роботи не робиться.
        if st.needs_release:
            try:
                backend.release(box, why="збій під час підготовки")
                st.released = True
                ST.save(st)
                say("машину звільнено — до роботи не дійшло")
            except Exception as rel:                     # pragma: no cover
                st.note("release_failed", str(rel))
                ST.save(st)
        raise
    finally:
        session.close()


def _remote_dir(box: Box, run_id: str) -> str:
    raw = box.meta.get("host") if isinstance(box.meta, dict) else None
    workdir = "~/nysh-run"
    if isinstance(raw, dict) and raw.get("workdir"):
        workdir = str(raw["workdir"])
    return f"{workdir.rstrip('/')}/{run_id}"


def _put_text(session: Session, remote: str, text: str) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / Path(remote).name
        # LF навмисно: скрипт виконує `sh` на машині, а CRLF там дає
        # «not found» на кожному рядку — помилку, яка не називає причини.
        p.write_text(text, encoding="utf-8", newline="\n")
        session.put(p, remote)


@dataclass(frozen=True)
class Pulse:
    """Що зараз на машині. Усе — з диска машини, нічого з нашої пам'яті."""

    alive: bool
    finished: bool
    pages_done: int
    frames_total: int
    rc: int | None = None
    detail: str = ""

    @property
    def pct(self) -> float:
        return round(100.0 * self.pages_done / self.frames_total, 1) \
            if self.frames_total else 0.0


def poll(st: ST.RunState) -> Pulse:
    """Спитати машину, як справи.

    🔴 Питаємо ДИСК, а не лог. Рядок «готово» в лозі вже двічі був підставою
    забрати недороблену справу: лог пише процес, а сторінки лежать окремо, і
    розходяться вони саме тоді, коли щось пішло не так.
    """
    if not st.box:
        return Pulse(alive=False, finished=False, pages_done=st.pages_done,
                     frames_total=st.frames_total, detail="машини немає")
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    session = backend.connect(box)
    try:
        # 🔴 Кожне число під своїм іменем. Три голі рядки поспіль розбираються
        # за порядком — і розбір мовчки з'їжджає, щойно машина додасть від себе
        # хоч один рядок (привітання оболонки, попередження locale).
        d = shlex.quote(st.remote_dir)
        got = session.run(
            f"echo pages=$(ls {d}/{OUT_SUB}/*.txt 2>/dev/null | wc -l); "
            f"echo done=$(test -f {d}/{DONE_FLAG} && echo 1 || echo 0); "
            f"echo rc=$(cat {d}/{RC_FILE} 2>/dev/null || echo -)",
            timeout=CMD_TIMEOUT)
        kv: dict[str, str] = {}
        for line in got.out.splitlines():
            key, sep, val = line.strip().partition("=")
            if sep:
                kv[key] = val.strip()
        pages = int(kv["pages"]) if kv.get("pages", "").isdigit() else 0
        finished = kv.get("done") == "1"
        rc = int(kv["rc"]) if kv.get("rc", "").lstrip("-").isdigit() else None
        alive = session.alive(st.pid) if st.pid else False
        return Pulse(alive=alive, finished=finished, pages_done=pages,
                     frames_total=st.frames_total, rc=rc)
    finally:
        session.close()


def fetch(st: ST.RunState, *, on_line: Any = None) -> Path:
    """Забрати результат. Повторний виклик безпечний і докачує.

    🔴 Одним архівом, а не файлами. Справа — це тисячі дрібних текстів, і
    забір по одному впирається не в смугу, а в рукостискання: черга з кількох
    справ так їхала десятками хвилин там, де ті самі байти одним об'єктом
    їдуть секунди.
    """
    say = on_line or (lambda _s: None)
    if not st.box:
        raise RunError("немає машини, з якої забирати")
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    out_dir = Path(st.out_dir)
    st.enter("fetching")
    session = backend.connect(box)
    try:
        remote_tar = f"{st.remote_dir}/result.tar"
        # `|| true` на самому tar: він повертає ненульове й тоді, коли просто
        # не знайшов однієї з необов'язкових тек голосів.
        session.run(
            f"cd {shlex.quote(st.remote_dir)} && rm -f result.tar && "
            f"tar -cf result.tar {OUT_SUB} {OUT_SUB}-* {LOGS_SUB} 2>/dev/null "
            f"|| tar -cf result.tar {OUT_SUB} 2>/dev/null || true",
            timeout=CMD_TIMEOUT)
        if not session.exists(remote_tar):
            raise RunError("на машині нема чого забирати — тека виходу порожня")
        from nyshporka.core.workspace import workspace

        local_tar = workspace().derived / "cloud" / "tmp" / f"{st.run_id}.result.tar"
        session.get(remote_tar, local_tar)
        say(f"привезено {local_tar.stat().st_size / 1e6:.1f} МБ")
    finally:
        session.close()
    try:
        unpack(local_tar, out_dir)
    finally:
        local_tar.unlink(missing_ok=True)
    stamp_case_key(out_dir, st.case_key)
    ST.save(st)
    return out_dir


def unpack(tar_path: Path, out_dir: Path) -> Path:
    """Розкласти привезене так, як його чекає решта застосунку.

    🔴 Голоси лягають у СЕСТРИНСЬКІ теки `<прогін>-<тег>`, а не всередину
    головної. Складені в одну, вони перетирають один одного за іменем файла —
    і пошук потім чесно віддає нуль знахідок БЕЗ жодної помилки.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            if not parts:
                continue
            head, rest = parts[0], parts[1:]
            if head == OUT_SUB:
                dest = out_dir.joinpath(*rest)
            elif head.startswith(f"{OUT_SUB}-"):
                tag = head[len(OUT_SUB):]          # `-diak_v4`
                dest = out_dir.with_name(out_dir.name + tag).joinpath(*rest)
            elif head == LOGS_SUB:
                dest = out_dir / LOGS_SUB / PurePosixPath(*rest).name
            else:
                continue
            # 🔴 Захист від шляху, що виводить за теку: архів прийшов із чужої
            # машини, і довіряти іменам у ньому підстав немає.
            if ".." in rest:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(src.read())
            # `replace`, а не `rename`: ціль може існувати з попереднього
            # забору, і повторний `fetch` мусить лишатись безпечним.
            tmp.replace(dest)
    return out_dir


def stamp_case_key(out_dir: Path, case_key: str) -> int:
    """Вписати шифру в мету прогону — і в теки голосів теж.

    🔴 Облік рахує сторінки з мети, а не з текстів на диску. Прогін без шифри
    лишається «нічиїм»: текст є, а до якої справи належить — невідомо, і
    зшивати це потім доводиться правкою файлів руками.
    """
    if not case_key:
        return 0
    from nyshporka.cloud.verify import META_NAME, voice_dirs
    from nyshporka.utils.atomic import CorruptFileError, read_json, write_json

    touched = 0
    for d in (Path(out_dir), *voice_dirs(Path(out_dir))):
        meta_path = d / META_NAME
        try:
            meta = read_json(meta_path, default=None)
        except CorruptFileError:
            continue
        if not isinstance(meta, dict):
            continue
        if meta.get("case_key") == case_key:
            continue
        meta["case_key"] = case_key
        write_json(meta_path, meta)
        touched += 1
    return touched


def release(st: ST.RunState, *, why: str = "", force: bool = False,
            on_line: Any = None) -> ST.RunState:
    """Відпустити машину.

    🔴 Відмовляє, поки роботу не звірено, — і це головний запобіжник модуля.
    `force` існує для випадку, коли людина свідомо кидає захід; мовчазного
    шляху сюди немає.
    """
    say = on_line or (lambda _s: None)
    if not st.box:
        st.released = True
        return ST.save(st)
    if not force and st.verdict not in ("ok", "cancelled", "failed"):
        raise RunError(
            f"захід {st.run_id} ще не звірено — спершу `nysh cloud verify "
            f"{st.run_id}`. Гасити машину до звірки не можна: саме так одного "
            f"разу забрали 203 сторінки з 323 і погасили ту, на якій лежали "
            f"решта. Якщо кидаєте захід свідомо — `--force`.")
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    if st.pid:
        try:
            session = backend.connect(box)
            try:
                session.kill(st.pid)
            finally:
                session.close()
        except CloudError as exc:
            st.note("kill_failed", str(exc))
    backend.release(box, why=why or "захід завершено")
    st.released = True
    st.note("released", why or "звільнено")
    say("машину звільнено" if st.bills else "з'єднання закрито (машина не наша)")
    return ST.save(st)


def wait(st: ST.RunState, *, tick_sec: float = 60.0, timeout_sec: float = 0.0,
         on_pulse: Any = None) -> Pulse:
    """Дочекатись завершення, опитуючи машину.

    ⚠ Це зручність для того, хто сидить перед екраном, а не спосіб керувати
    заходом: робота живе на машині незалежно від того, чекає її хтось чи ні.
    Перервати очікування безпечно завжди.
    """
    started = time.monotonic()
    while True:
        pulse = poll(st)
        st.pages_done = pulse.pages_done
        ST.save(st)
        if on_pulse:
            on_pulse(pulse)
        if pulse.finished or not pulse.alive:
            return pulse
        if timeout_sec and time.monotonic() - started > timeout_sec:
            return pulse
        time.sleep(tick_sec)
