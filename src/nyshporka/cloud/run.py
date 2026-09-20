"""🚀 Захід: узяти машину, привезти, прочитати, забрати, звірити, відпустити.

Порядок кроків тут не описовий, а обов'язковий, і два місця в ньому куплені
дорого:

* **проба заліза — перед заливкою.** Усе до неї коштує секунди, усе після —
  хвилини й гігабайти. Машина, яка обіцяла 192 ядра, а дала 48, мусить бути
  відсіяна до того, як на неї поїхали кадри;
* **звірка — перед звільненням.** Забрати й погасити виглядає як одна дія, але
  між ними лежить єдина точка, у якій ще можна врятувати роботу: одного разу
  так забрали 203 сторінки з 323 і погасили машину, на якій лежали решта 120.

🔴 Кожна команда тут повторювана. `start` при живій роботі свого заходу
підхоплює її замість того, щоб брати другу машину; `fetch` докачує; `verify`
взагалі нічого не змінює. Це не зручність, а єдиний спосіб пережити обрив
з'єднання, закритий ноутбук і Ctrl+C — тобто нормальне життя багатогодинної
роботи.

🔴 Робота на машині живе відчеплено від нашого з'єднання. Нишпорка її не
«тримає», а лише опитує: скільки текстів уже на диску машини й чи живий той
самий pid. Тому вбитий локальний процес не вбиває прогін, а `nysh cloud state`
однаково працює з іншої сесії й навіть з іншого комп'ютера.
"""
from __future__ import annotations

import os
import shlex
import shutil
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from nyshporka.cloud import state as ST
from nyshporka.cloud.base import (
    Box,
    BoxNotReady,
    ChannelDropped,
    CloudError,
    Session,
)
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
                    seg_height: int = 0,
                    extra_voices: tuple[str, ...] | list[str] = (),
                    ) -> tuple[list[Shard], list[str]]:
    """Ті самі команди, що й локально, тільки шляхами чужої машини.

    🔴 Рядок команди будує та сама `Plan`, що й локальний прогін. Друга збірка
    поруч розійшлася б із першою від першої ж нової опції — рівно як застерігає
    докстрінг `htr.run`.

    🔴 На одній карті беремо готову `Plan.shards()`: вона тримає інваріанту
    трьох прапорців (`--shard` + спільний `--gpu-lock` + знятий з карти `sato`),
    які народжуються й помирають разом.

    🔴 На кількох картах цієї інваріанти замало, і це не дрібниця. Спільний лок
    на всі шарди звів би вісім карт до однієї — вони стали б у чергу за правом
    рахувати сегментацію. Тому лок стає покартковим, а шард `k` бачить лише
    карту `k % N`: спільна карта на всі шарди одного разу дала півтори тисячі
    записів про брак пам'яті — і жодної помилки в підсумку, бо шард виходить із
    нульовим кодом.

    ⚠ Шляхи тут `PurePosixPath`, а поля `Plan` анотовані `Path`. Це свідомо:
    `Plan` користується ними лише через `str()`, а `Path` на Windows перетворив
    би `/root/run` на `\\root\\run` — тобто зламав би команду саме на тій
    машині, з якої її найчастіше й запускають.
    """
    from nyshporka.htr.run import Plan, shard_env

    root = PurePosixPath(remote_dir)
    # `Any`, а не `type: ignore` на генераторі: різні версії mypy називають цю
    # невідповідність різними кодами, і коментар під одну з них червонів на іншій.
    voices_extra: Any = tuple(PurePosixPath(v) for v in extra_voices)
    plan = Plan(
        case_dir=root / CASE_SUB,          # type: ignore[arg-type]
        out_dir=root / OUT_SUB,            # type: ignore[arg-type]
        model=PurePosixPath(model),        # type: ignore[arg-type]
        script=script, frames=0,
        python=PurePosixPath(python),      # type: ignore[arg-type]
        runner=root / "runner.py",         # type: ignore[arg-type]
        voice=PurePosixPath(voice) if voice else None,  # type: ignore[arg-type]
        extra_voices=voices_extra,
        seg_cache=root / "seg_cache",      # type: ignore[arg-type]
        gpu_lock=root / "_gpu.lock")       # type: ignore[arg-type]

    n = max(1, int(workers or 1))
    cards = max(1, int(gpus or 1))
    # 🔴 Ядра — чужої машини. Порахувати їх нашими означало б поділити вісім
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
        # Кожен процес бачить рівно одну карту, тож `cuda:0` всередині нього —
        # це вже його власна карта. Так раннеру не треба знати про розкладку.
        env["CUDA_VISIBLE_DEVICES"] = str(card)
        shards.append(Shard(
            cmd=plan.command(shard=f"{k + 1}/{n}", case_key=case_key,
                             gpu_lock=f"{root}/_gpu.lock.{card}",
                             gpu_sato=False, seg_height=seg_height),
            env=env))
    return shards, [
        f"{n} процесів на {cards} картах: по одному локу НА карту, "
        f"шард k бачить карту k%{cards}. Спільний лок звів би карти до однієї"]


def go_script(shards: list[Shard], *, remote_dir: str) -> str:
    """Скрипт, який веде всі процеси й лишає слід свого завершення.

    🔴 Прапорець завершення пишеться завжди, навіть коли процеси впали. Без
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


UV_INSTALLER_URL = "https://astral.sh/uv/install.sh"


def uv_install_command(probe_out: str) -> str:
    """Чим завантажити інсталятор `uv` на ЦІЙ машині — за тим, що на ній є.

    `probe_out` — рядки `have=<знаряддя>` від проби. 🔴 `curl` не є даністю:
    образ орендованого боксу — це образ під обчислення, і мережевих утиліт у
    ньому може не бути зовсім. Python там є завжди (це образ із torch), тож
    останній щабель — `urllib`. Немає нічого з переліку — відмова словами, а
    не `sh: curl: not found` посеред оплаченої підготовки.
    """
    have = {ln.strip().partition("=")[2] for ln in probe_out.splitlines()
            if ln.strip().startswith("have=")}
    url = UV_INSTALLER_URL
    if "curl" in have:
        return f"curl -LsSf {url} | sh"
    if "wget" in have:
        return f"wget -qO- {url} | sh"
    for py in ("python3", "python"):
        if py in have:
            code = (f"import sys,urllib.request;"
                    f"sys.stdout.buffer.write(urllib.request.urlopen('{url}',"
                    f"timeout=60).read())")
            return f"{py} -c {shlex.quote(code)} | sh"
    raise RunError(
        "на машині немає чим завантажити `uv`: ні `curl`, ні `wget`, ні Python. "
        "Поставте будь-що з цього (`apt-get install -y curl`) або `uv` руками й "
        "повторіть.")


def _card_range(man: Any) -> str:
    rows = list(getattr(man, "cuda_matrix", ()) or ())
    if not rows:
        return "невідомий перелік карт"
    lo = min(float(r["min_capability"]) for r in rows)
    hi = max(float(r["max_capability"]) for r in rows)
    return f"{lo:g}–{hi:g}"


def _ensure_c_compiler(session: Session, on_line: Any = None) -> None:
    """Компілятор C на машині — без нього torch не читає жодної сторінки.

    🔴 Справжня оренда 19.09.2026: середовище зібралось, моделі завантажились, а
    кожна сторінка впала з «Failed to find C compiler. Please specify via CC
    environment variable» — triton збирає свої ядра на ходу й шукає `gcc`, а
    образ під обчислення (`pytorch:*-runtime`) компілятора не несе. Своя машина
    з `nysh cloud prepare` його зазвичай має, тому на фейках і на власних хостах
    цього не видно.

    Ставимо лише там, де це безпечно й має сенс: є `apt-get` і ми root (так
    влаштований орендований контейнер). Інакше — попередження словами: далі
    встановлення піде, але читання, найпевніше, впаде тією самою помилкою.
    """
    say = on_line or (lambda _s: None)
    have = session.run(
        "(command -v gcc || command -v cc) >/dev/null 2>&1 && echo yes || echo no",
        timeout=60.0)
    if "yes" in have.out:
        return
    can = session.run(
        "command -v apt-get >/dev/null 2>&1 && [ \"$(id -u)\" = 0 ] && echo yes || echo no",
        timeout=60.0)
    if "yes" not in can.out:
        say("⚠ на машині немає компілятора C (gcc), і поставити його нічим — "
            "читання може впасти з «Failed to find C compiler»")
        return
    say("на машині немає компілятора C — ставимо gcc (потрібен torch для збирання ядер)")
    got = session.run(
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get -o DPkg::Lock::Timeout=180 update -qq && "
        "apt-get -o DPkg::Lock::Timeout=180 install -y -qq gcc libc6-dev",
        timeout=1200.0)
    if got.rc != 0:
        raise RunError("не вдалось поставити gcc на машину: "
                       f"rc={got.rc} … {(got.err or got.out).strip()[-300:]}")


#: Скільки разів повторити крок підготовки після обриву каналу.
PREPARE_RETRIES = 3


def prepare(session: Session, remote_dir: str, *,
            on_line: Any = None, reconnect: Any = None) -> EngineState:
    """Зібрати середовище рушіїв на машині. Ідемпотентно.

    🔴 Пакети ставляться по одному, а не списком. Причина конкретна: рушій
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
        # 🔴 Обрив каналу — не вирок кроку. Справжня оренда (19.09.2026):
        # `uv pip install kraken` на пів хвилині завантаження колес повернув
        # rc=-1 — канал SSH закрився, статусу виходу не було. Машину погасили, і
        # оплачений підйом пішов у нуль. Кроки ідемпотентні, а `uv` уже скачане
        # тримає в кеші, тож правильна реакція — перепідключитись і повторити.
        nonlocal session
        got = None
        for attempt in range(1, PREPARE_RETRIES + 1):
            try:
                got = session.run(cmd, timeout=timeout, on_line=on_line)
                dropped = got.rc == -1
            except (OSError, EOFError, CloudError) as exc:
                got, dropped = None, True
                if on_line:
                    on_line(f"канал обірвався: {exc}")
            if not dropped:
                break
            if reconnect is None or attempt == PREPARE_RETRIES:
                break
            if on_line:
                on_line(f"канал до машини обірвався посеред кроку — перепідключаюсь "
                        f"і повторюю ({attempt} з {PREPARE_RETRIES - 1})")
            time.sleep(5.0 * attempt)
            session = reconnect()
        if got is None:
            raise RunError(f"{why}: канал до машини обривається, крок не завершено")
        if got.rc != 0:
            # ХВІСТ виводу, не початок: pip і uv спершу друкують перелік того,
            # що качають, а причину збою («No space left on device») — останнім
            # рядком. Перша справжня оренда показала людині саме перелік.
            raise RunError(f"{why}: rc={got.rc} "
                           f"… {(got.err or got.out).strip()[-400:]}")

    have_uv = session.run("command -v uv >/dev/null 2>&1 && echo yes || echo no",
                          timeout=60.0)
    if "yes" not in have_uv.out:
        tools = session.run(
            "for t in curl wget python3 python; do command -v $t >/dev/null 2>&1 "
            "&& echo have=$t; done; true", timeout=60.0)
        step(uv_install_command(tools.out),
             "не вдалось поставити `uv` на машину")
    _ensure_c_compiler(session, on_line)
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
    tag, why = man.cuda_pick(cap.out.strip())
    if tag is None and why == "out_of_range":
        # 🔴 Карта є, але колеса torch під її архітектуру в маніфесті немає.
        # Мовчки лишити як є — означає «читати» з помилкою CUDA на кожній
        # сторінці й привезти нуль: так закінчилась справжня оренда на GTX
        # TITAN X (19.09.2026). Відмова тут коштує хвилини, а не всього заходу.
        raise RunError(
            f"карта цієї машини має архітектуру {cap.out.strip()}, а середовище рушіїв "
            f"підтримує {_card_range(man)} — читати на ній нема чим; потрібна інша машина")
    if tag:
        step(f"{uv} pip install --python {shlex.quote(py)} --reinstall "
             f"{' '.join(man.torch_default)} --index-url {man.cuda_index_url(tag)}",
             "не доставилось колесо під карту", timeout=3600.0)
    return engine_state(session, remote_dir)


# ── заливка ──────────────────────────────────────────────────────────────────
def pack_frames(case_dir: Path, dest: Path) -> Path:
    """Скласти кадри в один архів — без стиснення.

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
    """Раннер, патчі й ваги — усе, чим читатимуть.

    🔴 Шлях до `runner.py` береться через `find_spec`, а не `import
    nyshporka.htr.runner`. Сам раннер (за власним docstring) виконується
    python-ом СЕРЕДОВИЩА РУШІЇВ — тут потрібен лише його файл, щоб
    відіслати. Звичайний `import` виконує модуль і тягне за собою `numpy`
    top-level; `numpy` не входить у жоден пакет, який ставить `cloud`
    (`paramiko`, `boto3`) — і оркестрація впаде на машині без `htr`-екстри,
    хоча читає не вона, а орендований бокс.
    """
    import importlib.util

    spec = importlib.util.find_spec("nyshporka.htr.runner")
    if spec is None or spec.origin is None:
        raise CloudError("nyshporka.htr.runner не знайдено в пакеті")
    runner_py = Path(spec.origin).resolve()
    session.mkdirs(f"{remote_dir}/{MODELS_SUB}")
    session.mkdirs(f"{remote_dir}/patches")
    session.put(runner_py, f"{remote_dir}/runner.py")
    # 🔴 `pysar_lines_infer.py` — обов'язковий сусід для `.pt` (PARSeq,
    # кирилиця): `runner.py` вантажить його `sys.path.insert` + `import`
    # за файлом поруч, не пакетом. Без цього рядка кожна кирилична сторінка
    # падає в карантин з `ModuleNotFoundError: pysar_lines_infer`, а GPU
    # не бачить жодного навантаження — заміряно живцем на `gpu3060`
    # (14.09.2026, 456 із 457 сторінок пішли в карантин мовчки, доки
    # `nysh cloud state` не показав нуль активних процесів).
    session.put(runner_py.parent / "pysar_lines_infer.py",
               f"{remote_dir}/pysar_lines_infer.py")
    # 🔴 Патчі їдуть поруч із раннером, бо він вантажить їх за шляхом, а не
    # імпортом пакета: на машині `nyshporka` не встановлено й не буде.
    for p in sorted((runner_py.parent / "patches").glob("*.py")):
        session.put(p, f"{remote_dir}/patches/{p.name}")
    session.put(plan.model, f"{remote_dir}/{MODELS_SUB}/{plan.model.name}")
    for v in plan.voices:
        session.put(v, f"{remote_dir}/{MODELS_SUB}/{v.name}")
    if on_line:
        on_line(f"ваги й раннер на місці: {plan.model.name}"
                + "".join(f" + {v.name}" for v in plan.voices))


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
            f"&& rm -f {shlex.quote(remote_tar)}; echo tar_rc=$?; "
            f"echo landed=$(ls {CASE_SUB} 2>/dev/null | wc -l)",
            timeout=CMD_TIMEOUT)
        landed = 0
        for line in got.out.splitlines():
            key, sep, val = line.strip().partition("=")
            if sep and key == "landed" and val.strip().isdigit():
                landed = int(val.strip())
        # 🔴 Приймач заливки — число кадрів на машині, а не код розпакування.
        # Обірваний архів розпаковується частково й без помилки.
        if landed < plan.frames:
            # Причина — у виводі `tar`, і без неї людина бачить лише «0 із N»:
            # перша справжня оренда саме так і закінчилась, і гадати довелось
            # на платній машині.
            said = " · ".join(x for x in (got.err.strip()[-300:],
                                          got.out.strip()[-200:]) if x)
            raise RunError(
                f"на машину доїхало {landed} кадрів із {plan.frames} — "
                f"заливку треба повторити, читати неповне немає сенсу"
                + (f" (машина каже: {said})" if said else ""))
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
    if st.released:
        # 🔴 Відпущена машина вже не наша. Орендований бокс після звільнення
        # або зникає, або мовчить, і «мовчить» нижче читається як `BoxNotReady`
        # → «повторіть пізніше» — тобто невдалий захід назавжди замикав би
        # справу: нової машини не взяти, а стара не відповість ніколи.
        return None
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    try:
        session = backend.connect(box)
    except BoxNotReady as exc:
        # 🔴 «Не відповідає» ≠ «заходу немає». Повернути тут `None` означало б
        # узяти ДРУГУ машину при живій першій, ще й затерти її адресу в стані —
        # сирота, яку далі ніхто не побачить і не погасить.
        raise RunError(
            f"машина заходу {st.run_id} не відповідає ({exc}); повторіть "
            f"пізніше або, якщо вона справді мертва, `nysh cloud stop "
            f"{st.run_id} --force`") from exc
    except CloudError:
        return None
    try:
        alive = session.alive(st.pid)
    except CloudError as exc:
        # Те саме правило, що й вище: «не відповіла» — не «роботи немає».
        session.close()
        raise RunError(
            f"машина заходу {st.run_id} не відповіла, чи жива робота ({exc}); "
            f"повторіть пізніше") from exc
    if not alive:
        session.close()
        return None
    return session, box


def _seed_results(session: Session, plan: CloudPlan, remote_dir: str, *,
                  on_line: Any = None) -> int:
    """Привезти на машину те, що вже прочитано, — щоб вона читала лише решту.

    Раннер пропускає сторінку, чий текст лежить у теці виходу й записаний у
    меті. На свіжій машині тека порожня, тож без засіву захід, зупинений на
    стелі бюджету, при повторі платив би за всі сторінки заново — рівно за те,
    від чого стеля й мала вберегти.

    🔴 Карантин НЕ їде: він наслідок зіткнення щільної сторінки з розбиттям на
    процеси на ТІЙ машині, а не властивість кадру. Привезений, він змусив би
    нову машину пропустити саме ті сторінки, заради яких захід повторюють.
    """
    from nyshporka.cloud.verify import QUARANTINE_NAME, texts_in, voice_dirs
    from nyshporka.core.workspace import workspace

    out = Path(plan.out_dir)
    if texts_in(out) == 0:
        return 0
    tar_path = workspace().derived / "cloud" / "tmp" / f"{plan.run_id}.seed.tar"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    sent = 0
    try:
        with tarfile.open(tar_path, "w") as tar:
            pairs = [(out, OUT_SUB), *((d, OUT_SUB + d.name[len(out.name):])
                                       for d in voice_dirs(out))]
            for d, arc in pairs:
                for p in sorted(d.iterdir()):
                    if (not p.is_file() or p.name == QUARANTINE_NAME
                            or p.suffix in (".part", ".lock")):
                        continue
                    tar.add(p, arcname=f"{arc}/{p.name}")
                    sent += 1
        remote_tar = f"{remote_dir}/seed.tar"
        session.put(tar_path, remote_tar)
        session.run(f"cd {shlex.quote(remote_dir)} && tar -xf seed.tar "
                    f"&& rm -f seed.tar", timeout=CMD_TIMEOUT)
    finally:
        tar_path.unlink(missing_ok=True)
    if on_line:
        on_line(f"уже прочитане поїхало на машину ({texts_in(out)} сторінок) — "
                f"читатиметься лише решта")
    return sent


def start(plan: CloudPlan, *, workers: int = 0, seg_height: int = 0,
          on_line: Any = None, auto_prepare: bool | None = None,
          seed: bool = False) -> ST.RunState:
    """Почати або підхопити захід. Повертається одразу — робота лишається жити.

    Повторний виклик на живому заході нічого не робить, а на завершеному —
    веде до `fetch`, а не до другого прогону.

    `auto_prepare` — зібрати середовище рушіїв самому, якщо його немає. `None`
    (типово) — як каже бекенд: на орендованій машині збираємо, на своїй — ні.
    🔴 На оренді це не зручність, а єдиний робочий шлях. Орендований бокс
    свіжий за побудовою, середовища на ньому немає НІКОЛИ, і відмова «зберіть
    його окремою командою» тут одразу йде в обробник винятків, який гасить
    машину: «орендував → погасив» на кожному старті, з оплаченим завантаженням
    боксу й без жодної сторінки. На своїй машині лишається відмова: ставити
    гігабайти пакетів на чужий сервер без прямого прохання — не те рішення,
    яке ухвалюють мовчки.

    `seed` — привезти на машину вже прочитане (див. `_seed_results`).
    """
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import transfer as T

    say = on_line or (lambda _s: None)
    st = ST.load(plan.run_id) or ST.RunState(
        run_id=plan.run_id, case_dir=str(plan.case_dir), case_key=plan.case_key,
        out_dir=str(plan.out_dir), backend=plan.backend, target=plan.target,
        frames_total=plan.frames)
    st.frames_total = plan.frames
    st.source_dir = str(plan.source_dir) if plan.source_dir else ""

    live = adopt(st)
    if live is not None:
        live_session, _box = live
        live_session.close()
        say(f"захід {st.run_id} уже працює (pid {st.pid}) — підхоплено, "
            f"другої машини не беремо")
        return ST.save(st)

    backend = _backend(plan.backend)
    if st.needs_release:
        # 🔴 У стані лежить жива оплачувана машина, а підхопити на ній нічого.
        # Узяти нову поверх означало б затерти її адресу — єдине, чим її можна
        # погасити: сирота, яка тарифікується, доки хтось не зазирне в рахунок.
        if st.pid:
            # Робота на ній була й скінчилась — там лежить результат.
            raise RunError(
                f"захід {st.run_id} уже відпрацював на машині "
                f"{st.box.get('label') or st.box.get('id')}, і вона ще жива. "
                f"Заберіть і звірте: `nysh cloud fetch {st.run_id}`, "
                f"`nysh cloud verify {st.run_id}`, потім `nysh cloud stop {st.run_id}`.")
        # До роботи не дійшло (процес убито посеред підготовки) — забирати
        # нічого, тож гасимо й починаємо начисто.
        backend.release(Box.from_dict(st.box), why="failed:orphaned")
        st.released = True
        st.rent_ended = time.time()
        st.note("released", "сироту попередньої спроби погашено")
        ST.save(st)
        say("машину попередньої спроби погашено — до роботи на ній не дійшло")
    st.bills = bool(getattr(backend, "caps", frozenset()) & {"rent"})
    if plan.budget_usd is not None:
        st.budget_usd = plan.budget_usd
    if plan.max_hours is not None:
        st.max_hours = plan.max_hours

    # 🔴 Намір записується до того, як машина існує. Машина, створена після
    # запису, знайдеться навіть якщо процес помре наступної секунди; створена
    # до нього — стає живою, невидимою й оплачуваною.
    st.enter("acquiring", why=f"беремо машину через «{plan.backend}»")
    box = backend.acquire(plan.need, target=plan.target)
    st.box = box.as_dict()
    # 🔴 Нова машина — новий лічильник і чистий вирок. Запис заходу переживає
    # невдалі спроби, і `released=True` від попередньої робив щойно орендовану
    # машину невидимою для `needs_release`: жива, оплачувана й відсутня в
    # `nysh cloud state --all`. Так само й старий pid: він із чужого боксу.
    st.released = False
    st.verdict = ""
    st.pid = 0
    st.catchups = 0
    st.rent_started = time.time()
    st.rent_ended = 0.0
    st.run_started = 0.0
    st.note("acquired", f"машина {box.label or box.id}")
    ST.save(st)

    # 🔴 `connect` УСЕРЕДИНІ `try`: свіжий бокс часто ще не приймає SSH, і
    # `BoxNotReady` звідси раніше виходив повз `release` — машина лишалась
    # орендованою у фазі `acquiring`, доки людина не помічала.
    session: Session | None = None
    try:
        session = backend.connect(box)
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

        # 🔴 Розкриваємо тильду одразу: далі цей рядок їде і в команди (де він
        # у лапках, тож `~` не розкрилась би), і в SFTP, і в стан заходу, по
        # якому людина потім ходить руками. Один рядок правди на всі три.
        remote_dir = session.resolve(_remote_dir(box, st.run_id))
        st.remote_dir = remote_dir
        engine = engine_state(session, remote_dir)
        if not engine.ready and (st.bills if auto_prepare is None else auto_prepare):
            st.enter("preparing", why="збираємо середовище рушіїв на машині")
            say("середовища рушіїв на машині немає — збираємо (це хвилини, "
                "і вони вже оплачуються)")
            def _again() -> Session:
                # свіжа сесія на тій самій машині: далі `start` користується нею
                nonlocal session
                session = backend.connect(box)
                return session

            engine = prepare(session, remote_dir, on_line=say, reconnect=_again)
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
        st.pages_seeded = 0
        if seed and _seed_results(session, plan, remote_dir, on_line=say):
            from nyshporka.cloud.verify import texts_in

            st.pages_seeded = texts_in(Path(plan.out_dir))
        _drain_notes(session, st, say)

        device = "cuda:0" if probe.has_gpu else "cpu"
        _launch(session, st, plan, python=engine.python,
                workers=measured.sizing.shards, device=device,
                gpus=probe.gpus if probe.has_gpu else 1, cores=probe.cores,
                seg_height=seg_height, say=say)
        say(f"пішло: pid {st.pid}, {measured.sizing.shards} процесів, "
            f"~{measured.hours:.1f} год за розрахунком")
        return ST.save(st)
    except BaseException as exc:
        # `BaseException`, а не `Exception`: Ctrl+C посеред заливки кадрів —
        # найзвичніший спосіб перервати підготовку, і саме він раніше лишав
        # машину тарифікованою.
        at = st.phase
        st.note("failed", f"{type(exc).__name__}: {exc}")
        st.enter("failed", why=str(exc) or type(exc).__name__)
        # 🔴 Машину, яка тарифікується, не лишаємо живою через власну помилку:
        # це рівно той стан, у якому гроші течуть, а роботи не робиться.
        if st.needs_release:
            try:
                # Причина — коротким машинним словом: бекенд пише її у власний
                # реєстр машин, і за нею потім відсіюють бокси, що не піднялись.
                backend.release(box, why=("cancelled"
                                          if isinstance(exc, KeyboardInterrupt)
                                          else f"failed:{at}"))
                st.released = True
                st.rent_ended = time.time()
                ST.save(st)
                say("машину звільнено — до роботи не дійшло")
            except Exception as rel:                     # pragma: no cover
                st.note("release_failed", str(rel))
                ST.save(st)
        raise
    finally:
        if session is not None:
            session.close()


def _launch(session: Session, st: ST.RunState, plan: CloudPlan, *, python: str,
            workers: int, device: str, gpus: int, cores: float,
            seg_height: int = 0, say: Any = None) -> None:
    """Скласти команди, покласти скрипт і пустити роботу відчеплено.

    Один шлях на перший пуск і на догін: друга збірка команд розійшлася б із
    першою від першої ж нової опції, і догін читав би іншими прапорцями, ніж
    основний прохід, — у ту саму теку.
    """
    say = say or (lambda _s: None)
    remote_dir = st.remote_dir
    cmds, notes = remote_commands(
        remote_dir=remote_dir, python=python,
        model=f"{remote_dir}/{MODELS_SUB}/{plan.model.name}",
        voice=(f"{remote_dir}/{MODELS_SUB}/{plan.voice.name}"
               if plan.voice else ""),
        extra_voices=[f"{remote_dir}/{MODELS_SUB}/{v.name}"
                      for v in plan.extra_voices],
        script=plan.script, case_key=plan.case_key,
        workers=workers, device=device, gpus=gpus, cores=cores,
        seg_height=seg_height)
    for n in notes:
        say(n)
        st.note("shards", n)

    script_path = f"{remote_dir}/{GO_SCRIPT}"
    _put_text(session, script_path, go_script(cmds, remote_dir=remote_dir))
    session.run(f"rm -f {shlex.quote(remote_dir)}/{DONE_FLAG} "
                f"{shlex.quote(remote_dir)}/{RC_FILE}", timeout=CMD_TIMEOUT)

    st.remote_log = f"{remote_dir}/{LOGS_SUB}/go.log"
    # 🔴 Тека журналу мусить існувати ДО запуску. `go.sh` створює її сам, але
    # його власний вивід перенаправляється туди ще оболонкою, що його пускає:
    # немає теки — перенаправлення не вдається, і команда не стартує ВЗАГАЛІ,
    # хоча pid надруковано. Дві справжні оренди (19.09.2026) «читали» так нуль
    # сторінок: ні `out`, ні `logs` на машині не з'явилось, а причини не було
    # де й прочитати.
    session.mkdirs(f"{remote_dir}/{LOGS_SUB}")
    st.enter("running", why=f"{len(cmds)} процесів на {device}")
    if not st.run_started:
        st.run_started = time.time()
    st.pid = session.spawn(f"sh {shlex.quote(script_path)}",
                           log=st.remote_log, pidfile=f"{remote_dir}/_pid")
    ST.save(st)
    # Надрукований pid ще не означає, що робота йде: оболонка друкує його й
    # тоді, коли команда не стартувала. Мертвий одразу після запуску процес без
    # прапорця завершення — це «не запустилось», і сказати про це треба зараз,
    # а не після години опитування нуля сторінок.
    if not session.alive(st.pid) and not session.exists(f"{remote_dir}/{DONE_FLAG}"):
        said = session.read_text(st.remote_log, limit=2000).strip()[-600:] \
            if session.exists(st.remote_log) else "журналу запуску на машині немає"
        raise RunError(f"робота на машині не запустилась (pid {st.pid} уже мертвий): {said}")


def catch_up(st: ST.RunState, plan: CloudPlan, *, on_line: Any = None) -> ST.RunState:
    """Догнати хвіст на ЖИВІЙ машині — одним процесом, у ту саму теку.

    Раннер сам пропускає готове: сторінка, чий текст уже лежить і записана в
    меті, іде в resume-скіп за частки секунди (`htr.runner`, цикл сторінок), —
    тож повторний пуск читає лише те, чого бракує. Кадри, ваги й кеш
    сегментації вже на машині, холодного старту немає; саме тому на живому
    боксі догін дешевий, а «доганяйте вдома» лишається порадою для машини, яку
    вже погашено.

    🔴 Одним процесом, а не тим самим розбиттям. Хвіст — це майже завжди
    сторінки, що не вмістились поруч із сусідами: щільний аркуш упав на браку
    пам'яті або двічі поклав процес. Ті самі кадри в один потік проходять із
    першого разу, а повтор із тим самим числом процесів повторив би й відмову.

    🔴 Карантин відкладається вбік, а не стирається. Він переживає перезапуск,
    і без цього догін чесно пропустив би рівно ті сторінки, заради яких його
    пущено. Файл лишається поруч під іншим іменем — як запис про те, що саме й
    чому не читалось першим проходом; сторінку, яка валить процес і наодинці,
    наглядач раннера покладе в карантин знову.
    """
    from nyshporka.cloud.verify import QUARANTINE_NAME

    say = on_line or (lambda _s: None)
    if not st.box or not st.remote_dir:
        raise RunError("немає машини, на якій доганяти")
    backend = _backend(st.backend)
    box = Box.from_dict(st.box)
    session = backend.connect(box)
    try:
        if st.pid and session.alive(st.pid):
            raise RunError(f"робота заходу {st.run_id} ще йде (pid {st.pid}) — "
                           f"доганяти нема чого, доки вона не скінчилась")
        q = f"{st.remote_dir}/{OUT_SUB}/{QUARANTINE_NAME}"
        session.run(f"test -f {shlex.quote(q)} && mv -f {shlex.quote(q)} "
                    f"{shlex.quote(q + '.before-catchup')} || true",
                    timeout=CMD_TIMEOUT)
        engine = engine_state(session, st.remote_dir)
        if not engine.ready:
            raise RunError(f"середовище рушіїв на машині зникло ({engine.detail})")
        probe = st.probe if isinstance(st.probe, dict) else {}
        has_gpu = bool(probe.get("gpus")) and bool(probe.get("vram_gb_min"))
        cores = probe.get("cores")
        st.catchups += 1
        st.note("catchup", "догін хвоста одним процесом; карантин відкладено")
        _launch(session, st, plan, python=engine.python, workers=1,
                device="cuda:0" if has_gpu else "cpu", gpus=1,
                cores=float(cores) if isinstance(cores, (int, float)) else 0.0,
                say=say)
        say(f"догін пішов: pid {st.pid}")
        return ST.save(st)
    finally:
        session.close()


def stop_job(st: ST.RunState) -> bool:
    """Зупинити роботу на машині, НЕ відпускаючи її. `True` — сигнал пішов.

    Окремо від `release` навмисно: на стелі грошей чи годин між «зупинити» й
    «погасити» мусить улізти забір того, що вже прочитано. Злиті в одну дію,
    вони дають рівно той випадок, від якого стоїть весь модуль, — погашену
    машину з неперевезеними сторінками.
    """
    if not st.box or not st.pid:
        return False
    backend = _backend(st.backend)
    session = backend.connect(Box.from_dict(st.box))
    try:
        session.kill(st.pid)
        st.note("stopped", f"роботу зупинено (pid {st.pid})")
        ST.save(st)
        return True
    finally:
        session.close()


def _remote_dir(box: Box, run_id: str) -> str:
    raw = box.meta.get("host") if isinstance(box.meta, dict) else None
    workdir = "~/nysh-run"
    if isinstance(raw, dict) and raw.get("workdir"):
        workdir = str(raw["workdir"])
    return f"{workdir.rstrip('/')}/{run_id}"


def _drain_notes(session: Session, st: ST.RunState, say: Any) -> None:
    """Забрати сказане транспортом у журнал заходу й на екран.

    Транспорт не знає про захід, тож складає нотатки в себе (`notes`). Поле
    необов'язкове: у сесії стороннього бекенда його може не бути зовсім.
    """
    notes = getattr(session, "notes", None)
    if not isinstance(notes, list):
        return
    while notes:
        text = str(notes.pop(0))
        st.note("transport", text)
        say(f"⚠ {text}")


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

    🔴 Питаємо диск, а не лог. Рядок «готово» в лозі вже двічі був підставою
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
        if not kv.get("pages", "").isdigit() or kv.get("done") not in ("0", "1"):
            # 🔴 Немає відповіді — не «нуль сторінок і робота не скінчилась».
            # Обірваний канал дає rc=-1 і порожній вивід; прочитаний як нуль, він
            # стирав лічильник поступу, а в парі з `alive()` — закривав нагляд.
            raise ChannelDropped(
                f"машина не відповіла на опитування (rc={got.rc}): "
                f"{(got.err or got.out).strip()[-160:] or 'порожній вивід'}")
        pages = int(kv["pages"])
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
        # 🔴 В архів ідуть лише теки, які Є. Доти необов'язкову `out-*` давали
        # tar-ові шаблоном, він «падав» на її відсутності, і запасна гілка
        # ПЕРЕЗАПИСУВАЛА архів самою текою `out` — тобто журнали губились рівно
        # тоді, коли прогін упав, не створивши теки другого голосу. Перша
        # справжня оренда з мертвим раннером привезла додому 0.0 МБ і жодного
        # слова про причину.
        session.run(
            f"cd {shlex.quote(st.remote_dir)} && rm -f result.tar && "
            f"tar -cf result.tar $(ls -d {OUT_SUB} {OUT_SUB}-* {LOGS_SUB} 2>/dev/null)",
            timeout=CMD_TIMEOUT)
        if not session.exists(remote_tar):
            raise RunError("на машині нема чого забирати — тека виходу порожня")
        from nyshporka.core.workspace import workspace

        local_tar = workspace().derived / "cloud" / "tmp" / f"{st.run_id}.result.tar"
        session.get(remote_tar, local_tar)
        _drain_notes(session, st, say)
        say(f"привезено {local_tar.stat().st_size / 1e6:.1f} МБ")
    finally:
        session.close()
    try:
        _drop_stale_quarantine(local_tar, out_dir)
        unpack(local_tar, out_dir)
    finally:
        local_tar.unlink(missing_ok=True)
    stamp_case_key(out_dir, st.case_key)
    stamp_case_dir(out_dir, st.source_dir or st.case_dir)
    ST.save(st)
    _say_why_nothing_was_read(out_dir, say)
    return out_dir


def _say_why_nothing_was_read(out_dir: Path, say: Any) -> None:
    """Нуль сторінок — показати хвіст журналів раннера, привезених із машини.

    Причина мертвого прогону лежить у `logs/shard*.log`, і після гасіння машини
    це єдина її копія. Людина, якій сказали лише «0 з N», піде орендувати вдруге.
    """
    if any(out_dir.glob("*.txt")):
        return
    logs = sorted((out_dir / LOGS_SUB).glob("*.log")) if (out_dir / LOGS_SUB).is_dir() else []
    if not logs:
        say("журналів прогону з машини не привезено — причина нуля невідома")
        return
    for log in logs[:3]:
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]
        except OSError:
            continue
        if tail:
            say(f"── {log.name} (хвіст) ──")
            for line in tail:
                say("  " + line[:300])


def _drop_stale_quarantine(tar_path: Path, out_dir: Path) -> None:
    """Прибрати локальний карантин, якого на машині вже немає.

    Розпакування лише ДОДАЄ файли, тож карантин від попереднього забору
    переживав би догін, який ті сторінки дочитав: звірка бачила б відкладені
    сторінки, яких уже ніхто не відкладав, і справа лишалась би «неповною»
    назавжди. Правду про карантин знає машина, з якої щойно забрали: є він в
    архіві — ляже поверх, немає — локальний застарів.
    """
    from nyshporka.cloud.verify import QUARANTINE_NAME

    with tarfile.open(tar_path, "r") as tar:
        if f"{OUT_SUB}/{QUARANTINE_NAME}" in tar.getnames():
            return
    (Path(out_dir) / QUARANTINE_NAME).unlink(missing_ok=True)


def unpack(tar_path: Path, out_dir: Path) -> Path:
    """Розкласти привезене так, як його чекає решта застосунку.

    🔴 Голоси лягають у сестринські теки `<прогін>-<тег>`, а не всередину
    головної. Складені в одну, вони перетирають один одного за іменем файла —
    і пошук потім чесно віддає нуль знахідок без жодної помилки.
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
            # 🔴 Захист від шляху, що виводить за теку: архів прийшов із чужої
            # машини, і довіряти іменам у ньому підстав немає. Перевірка
            # ПОКОМПОНЕНТНА, а не `".." in rest`: на Windows `joinpath` розбирає
            # `\` і `C:` УСЕРЕДИНІ одного POSIX-компонента, тож
            # `out/..\..\evil` проходив старий фільтр і лягав на два рівні вище.
            if not rest or not all(_safe_member_part(p) for p in rest):
                continue
            if head == OUT_SUB:
                base = out_dir
                dest = base.joinpath(*rest)
            elif head.startswith(f"{OUT_SUB}-"):
                tag = head[len(OUT_SUB):]          # `-diak_v4`
                if not _safe_member_part(tag[1:]):
                    continue
                base = out_dir.with_name(out_dir.name + tag)
                dest = base.joinpath(*rest)
            elif head == LOGS_SUB:
                base = out_dir / LOGS_SUB
                dest = base / rest[-1]
            else:
                continue
            # Другий рубіж — уже на побудованому шляху: що б не пройшло вище,
            # ціль мусить лишитись під своєю базою.
            if not _under(dest, base):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            tmp = dest.with_name(dest.name + ".part")
            # Потоком, а не `read()` цілком: член tar із чужої машини може бути
            # будь-якого розміру, і тримати його в пам'яті нема чого.
            with tmp.open("wb") as fh:
                shutil.copyfileobj(src, fh, 1 << 20)
            # `replace`, а не `rename`: ціль може існувати з попереднього
            # забору, і повторний `fetch` мусить лишатись безпечним.
            tmp.replace(dest)
    return out_dir


_BAD_MEMBER_CHARS = frozenset("\\:\x00")


def _safe_member_part(part: str) -> bool:
    """Компонент імені з чужого tar, який можна класти на диск як є."""
    if not part or part in (".", "..") or part.strip() != part:
        return False
    return not any(ch in _BAD_MEMBER_CHARS for ch in part)


def _under(dest: Path, base: Path) -> bool:
    try:
        return Path(os.path.abspath(dest)).is_relative_to(Path(os.path.abspath(base)))
    except (OSError, ValueError):
        return False


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


def stamp_case_dir(out_dir: Path, case_dir: str | Path) -> int:
    """Вписати в мету теку кадрів ЦІЄЇ машини — замість шляху орендованого боксу.

    🔴 Раннер пише `case_dir` там, де працює, тож із хмари мета приїжджає зі
    шляхом машини, якої вже немає. Кроп і гортач шукають кадр саме за цим
    полем — і або не знаходять нічого, або (гірше) беруть кадр із випадково
    наявної теки з тим самим іменем. Шлях боксу не стирається, а переїжджає в
    `case_dir_cloud`: раннер переносить це поле крізь перезбірку мети.

    🔴 Пишеться ОРИГІНАЛ, а не стиснута копія, що їздила на машину: кроп зі
    стиснутого кадру вдвічі дрібніший, а знахідку звіряють саме кропом.
    """
    if not str(case_dir):
        return 0
    from nyshporka.cloud.verify import META_NAME, voice_dirs
    from nyshporka.utils.atomic import CorruptFileError, read_json, write_json

    local = str(case_dir).replace("\\", "/")
    touched = 0
    for d in (Path(out_dir), *voice_dirs(Path(out_dir))):
        meta_path = d / META_NAME
        try:
            meta = read_json(meta_path, default=None)
        except CorruptFileError:
            continue
        if not isinstance(meta, dict) or meta.get("case_dir") == local:
            continue
        was = str(meta.get("case_dir") or "")
        if was and not meta.get("case_dir_cloud"):
            meta["case_dir_cloud"] = was
        meta["case_dir"] = local
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
    # `budget_stop` і `deadline` виносяться лише після забору й звірки наявного
    # (`cloud.go`), тож гасити з ними так само безпечно, як з `ok`.
    if not force and st.verdict not in ("ok", "cancelled", "failed",
                                        "budget_stop", "deadline"):
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
        except Exception as exc:
            # 🔴 `Exception`, а не лише `CloudError`: це крок ввічливості перед
            # гасінням, і будь-яка його відмова (чужий бекенд кидає своє) не
            # має права стати між нами й `release` — далі стоїть лічильник.
            st.note("kill_failed", f"{type(exc).__name__}: {exc}")
    backend.release(box, why=why or "захід завершено")
    st.released = True
    st.rent_ended = time.time()
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
