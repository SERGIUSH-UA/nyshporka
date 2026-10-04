"""🖋 Середовище рушіїв читання: створення, перевірка, контракт.

Рушії живуть в окремому venv (kraken конфліктує резолвером з основним пакетом,
а torch ставиться під конкретну карту). Застосунок говорить із ним лише через
підпроцес, тож єдине, що їх пов'язує, — файл-контракт `htr_env.json`.

🔴 Три речі, які тут виправлено проти попереднього сетапу:

1. **Ставиться те, що справді потрібно.** Попередній ставив kraken і torch, але
   не `strhub`/`timm`/`nltk` — і на чистій машині kraken-рушії працювали, а
   PARSeq не запускався взагалі. Перелік тепер у маніфесті, де дірку видно.
2. **Шляхи крос-платформні.** Було зашито `Scripts/python.exe`, тобто на Linux
   і macOS сетап не працював у принципі.
3. **CUDA обирається за картою, а не зашивається.** Індекс `cu126` підібраний
   під sm_75; на новіших картах таке колесо не працює. Карта поза відомими
   межами лишається на CPU: повільно, але робочо — краще, ніж колесо, яке не
   запускається. ⚠ Про карту питається ДРАЙВЕР (`htr/gpu.py` → `nvidia-smi`), а
   не torch: у CPU-колеса, яке ставиться кроком вище, CUDA немає за побудовою,
   тож його відповідь «карти немає» нічого не означає (issue #7).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nyshporka.htr import gpu
from nyshporka.htr import manifest as M

#: Версія контракту. Піднімається, коли міняється склад файлу, щоб застосунок
#: міг відрізнити «середовища немає» від «середовище зі старої версії».
ENV_SCHEMA = 2
ENV_FILENAME = "htr_env.json"


def venv_python(venv: Path) -> Path:
    """Інтерпретатор усередині venv — там, де його кладе платформа."""
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_bin(venv: Path, name: str) -> Path:
    exe = f"{name}.exe" if os.name == "nt" else name
    return venv / ("Scripts" if os.name == "nt" else "bin") / exe


@dataclass(frozen=True)
class EnvReport:
    """Що вдалося з'ясувати про середовище. Порожні поля — це теж відповідь."""

    ok: bool
    python: Path | None = None
    kraken: str = ""
    torch: str = ""
    cuda: bool = False
    capability: str = ""
    missing: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    #: Стоїть, але не тієї версії, що закріплена в маніфесті (`==`). Не
    #: «зламано», а «застаріло»: `setup()` оновлює це на місці.
    stale: tuple[str, ...] = ()


#: Змінні, якими батьківський Python каже дитині, ДЕ її стандартна бібліотека.
#: Для чужого інтерпретатора вони брехня.
_PARENT_PYTHON_VARS = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
                       "__PYVENV_LAUNCHER__", "VIRTUAL_ENV", "UV_INTERNAL__PYTHONHOME")


def foreign_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Оточення для процесу в ІНШОМУ інтерпретаторі — середовищі рушіїв.

    🔴 `uv run` ставить `PYTHONHOME` на свій Python, і дитина його успадковує.
    Інтерпретатор рушіїв іншої версії (3.11 проти 3.13) тоді бере чужу
    стандартну бібліотеку й падає ще на `import re` («SRE module mismatch»).
    Назовні це виглядало як «середовище рушіїв не готове (бракує: kraken…)» —
    при тому, що все стояло (знайдено живим прогоном черги 30.09.2026).
    """
    import os

    env = {k: v for k, v in os.environ.items() if k not in _PARENT_PYTHON_VARS}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # власні triton-ядра torch 2.14 без gcc роняють читання — див. `runner.py`
    env.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
    env.update(extra or {})
    return env


def _probe(py: Path, code: str, timeout: int = 120) -> str | None:
    """Виконати рядок у чужому інтерпретаторі; None — якщо не вийшло."""
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           env=foreign_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _version_of(py: Path, dist: str) -> str:
    return _probe(py, f"import importlib.metadata as m; print(m.version({dist!r}))") or ""


#: «torch рахує на карті» — справжнім ядром, а не `is_available()`.
#: 🔴 `is_available()` каже True і тоді, коли в колесі немає ядер під цю карту:
#: колесо torch 2.14 з PyPI на Linux зібране під CUDA 13 (cu130), де найдавніша
#: архітектура — sm_75: V100 (sm_70) і GTX 10xx (sm_61) лишаються без ядер.
#: Тоді крок під карту пропускався, а читання падало аж на прогоні з «no kernel
#: image is available» (Vast V100, 04.10.2026: torch 2.14.0+cu130, усі `nysh
#: read` — rc=1 при GPU 0%).
CUDA_WORKS = ("import torch; print(torch.cuda.is_available() and "
              "float((torch.ones(4, device='cuda') * 2).sum()) == 8.0)")


def inspect(venv: Path, man: M.Manifest | None = None) -> EnvReport:
    """Що є в середовищі — без спроб щось лагодити.

    Розділення огляду й полагодження тут не косметичне: `doctor` мусить уміти
    сказати правду, не змінюючи стану, інакше діагностика й лікування зливаються
    в одну дію, яку страшно запускати.
    """
    man = man or M.active()
    py = venv_python(venv)
    if not py.exists():
        return EnvReport(ok=False, problems=(f"немає інтерпретатора: {py}",))

    missing: list[str] = []
    for spec in man.packages:
        # 🔴 Ріже `manifest.dist_name`, а не власний вираз. Доти тут стояла
        # копія, і саме розбіжність між нею і тим, як ім'я шукав `setup`,
        # давала тиху ваду. Копія до того ж не знала ні `~=`, ні екстр.
        dist = M.dist_name(spec)
        if not _version_of(py, dist):
            missing.append(dist)
    for v in man.vcs_packages:
        if _probe(py, f"import {v['name']}") is None:
            missing.append(v["name"])

    kraken = _version_of(py, "kraken")
    torch_v = _probe(py, "import torch; print(torch.__version__)") or ""
    cuda = _probe(py, CUDA_WORKS) == "True"
    cap = _probe(py, "import torch; print('%d.%d' % torch.cuda.get_device_capability(0))") \
        if cuda else ""

    problems: list[str] = []
    stale: list[str] = []
    for spec in man.packages:
        if "==" not in spec:
            continue
        dist, want = M.dist_name(spec), spec.split("==", 1)[1].strip()
        have = kraken if dist == "kraken" else _version_of(py, dist)
        if have and have != want:
            stale.append(dist)
    want_k = next((s.split("==")[1] for s in man.packages
                   if s.startswith("kraken==")), "")
    if kraken and want_k and kraken != want_k:
        problems.append(
            f"kraken {kraken}, а патчі сегментації звірені на {want_k} — "
            f"розбіжність буде тихою: інші полігони рядків, тобто інший текст. "
            f"`nysh htr install` оновить середовище на місці")

    return EnvReport(ok=not missing and not problems, python=py, kraken=kraken,
                     torch=torch_v, cuda=cuda, capability=cap or "",
                     missing=tuple(missing), problems=tuple(problems),
                     stale=tuple(stale))


class ToolMissing(RuntimeError):
    """Зовнішнього інструмента немає на машині — з назвою і що з цим робити.

    🔴 Окремий тип, а не голий `FileNotFoundError` із надр `subprocess`. Той
    приходить із текстом ОС мовою системи («Не удается найти указанный файл»),
    без назви інструмента й без жодної підказки — тобто на найчастішому шляху
    («поставив pip-ом, запустив `nysh htr install`») людина отримує трасу стека
    замість одного рядка про те, чого бракує.
    """


def intel_mac() -> bool:
    """Mac з процесором Intel — або Python під Rosetta на Apple Silicon.

    🔴 Issue #10. PyTorch перестав випускати колеса для macOS x86_64 після
    torch 2.2.2 / torchvision 0.17.2, а `kraken==7.1.1` — пін під патчі, який
    знімати не можна, — вимагає torch ≥ 2.9. З PyPI цю пару не скласти ніколи,
    тож тут середовище створюється інакше: інтерпретатор і torch беруться з
    conda-forge (`Manifest.conda_*`), а решта ставиться pip'ом, як усюди.

    ⚠ Питається ІНТЕРПРЕТАТОР, а не залізо: Python під Rosetta теж каже
    `x86_64`, і йому теж потрібні x86-колеса.
    """
    import platform

    return sys.platform == "darwin" and platform.machine() == "x86_64"


#: Статичний micromamba для Intel Mac — один файл, без Python і без установки.
MICROMAMBA_URL = "https://micro.mamba.pm/api/micromamba/osx-64/latest"


def _conda_tool() -> str:
    """Чим створювати conda-середовище: те, що вже є, або власний micromamba.

    Порядок: `micromamba` → `mamba` → `conda` з PATH; далі — той micromamba, що
    його вже приносили сюди; далі — завантажити. 🔴 Приносити самим, а не
    радити «поставте conda»: uv інсталятор теж приносить сам, і людина, яка
    щойно поставила застосунок одним рядком, не мусить на другому кроці йти
    по інший пакетний менеджер. Лягає в теку застосунку поруч із uv, і
    `nysh uninstall` знімає її разом з рештою.
    """
    for name in ("micromamba", "mamba", "conda"):
        found = _resolve_tool(name)
        if found:
            return found
    own = _micromamba_home() / "bin" / "micromamba"
    if own.is_file():
        return str(own)
    return _fetch_micromamba(own)


def _micromamba_home() -> Path:
    from nyshporka.setup.update import install_home

    return install_home() / "micromamba"


def _fetch_micromamba(target: Path) -> str:
    """Завантажити статичний micromamba у теку застосунку; шлях до бінарника."""
    import tarfile
    import tempfile

    import httpx

    print(f"⬇ micromamba ({MICROMAMBA_URL})…")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "micromamba.tar.bz2"
        with httpx.stream("GET", MICROMAMBA_URL, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with archive.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        with tarfile.open(archive, "r:bz2") as tar:
            member = next((m for m in tar.getmembers()
                           if m.name.endswith("bin/micromamba")), None)
            if member is None:
                raise ToolMissing("micromamba: в архіві немає bin/micromamba — "
                                  "формат роздачі змінився; поставте вручну: "
                                  "brew install micromamba")
            src = tar.extractfile(member)
            assert src is not None
            target.write_bytes(src.read())
    target.chmod(0o755)
    print(f"✓ micromamba: {target}")
    return str(target)


def _create_conda_env(venv: Path, man: M.Manifest, tool: str) -> None:
    """Середовище з conda-forge: інтерпретатор і torch звідти, решта — pip.

    ⚠ `MAMBA_ROOT_PREFIX` показує в теку застосунку: інакше micromamba завів
    би `~/micromamba` з кешем пакетів у домівці людини — рівно те, чого
    інсталятор навчився не робити 07.09.2026.
    """
    if not man.conda_packages:
        raise ToolMissing("у маніфесті рушіїв немає блоку conda — на цій машині "
                          "torch не поставити: PyPI не має колес для macOS x86_64")
    env = {**os.environ, "MAMBA_ROOT_PREFIX": str(_micromamba_home() / "root")}
    _run([tool, "create", "--yes", "-p", str(venv), "--override-channels",
          "-c", man.conda_channel or "conda-forge",
          f"python={man.python}", *man.conda_packages], env=env)


def _need_tool(name: str, why: str, how: str) -> None:
    """Перевірити перед запуском, а не впасти всередині.

    Обидві перевірки тут не про педантизм: `uv` і `git` у цьому пакеті — не
    залежності збірки, тож у людини, яка ставила `pip install`, їх може не бути
    зовсім. Збірка середовища рушіїв — єдине місце, де вони потрібні, і саме там
    їхня відсутність досі виглядала як поломка застосунку.
    """
    if _resolve_tool(name):
        return
    raise ToolMissing(f"{name} не знайдено — {why}\n"
                      f"  {how}")


def _resolve_tool(name: str) -> str:
    """Голе ім'я інструмента → абсолютний шлях, і НЕ з поточної теки.

    🔴 На Windows і `shutil.which`, і `CreateProcess` для імені без шляху
    дивляться спершу в cwd. Людина, що стоїть у теці щойно розпакованої чужої
    зйомки і запускає `nysh htr install`, виконала б `uv.exe` звідти. Знайдене
    під cwd відкидається, решта повертається абсолютним шляхом — саме він і
    йде в `subprocess`.
    """
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return name                        # уже шлях — людина знає, що робить
    found = shutil.which(name)
    if not found:
        # 🔴 `uv` може бути й НЕ в PATH — і це не збій, а норма з 07.09.2026:
        # інсталятор кладе його у власну теку застосунку саме для того, щоб не
        # чіпати чуже середовище, і сам кличе повним шляхом. Без цього рядка
        # `nysh htr install` відмовляв би «uv не знайдено» на машині, де uv
        # щойно поставили ми, і порада «поставте uv» вела б на другу копію.
        return _from_install_info(name)
    try:
        if Path(found).resolve().parent == Path.cwd().resolve():
            return ""
    except OSError:
        return ""
    return found


def _from_install_info(name: str) -> str:
    """Інструмент за слідом інсталятора: `uv=` в `install-info.ini`.

    ⚠ Тільки `uv`: більше інсталятор нічого не приносить, а вгадувати шляхи
    решти означало б підсунути чужий бінарник під знайомим іменем.
    """
    if name != "uv":
        return ""
    try:
        from nyshporka.setup.update import install_info

        got = install_info().get("uv", "")
    except Exception:
        return ""
    return got if got and Path(got).is_file() else ""


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Команда установки — в оточенні без змінних батьківського Python.

    🔴 Python у venv, створеному uv на Windows, сам ставить собі `PYTHONHOME`.
    `uv pip install` передає його далі, і пакет без колеса під Windows
    (`coremltools`, залежність kraken) збирався інтерпретатором 3.11 зі
    стандартною бібліотекою 3.12/3.13 застосунку: `SyntaxError` у `typing.py`,
    і свіже `nysh htr install` падало (пісочниця оновлення, 04.10.2026).
    """
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True, env=env if env is not None else foreign_env())


def setup(venv: Path, *, man: M.Manifest | None = None, with_cuda: bool = True,
          uv: str = "uv", force_tag: str = "") -> EnvReport:
    """Створити, доповнити або оновити на місці. Ідемпотентно.

    Наявне й правильне не чіпається; відсутнє ставиться; закріплене (`==`)
    іншої версії — оновлюється в тому самому venv. Нового середовища поруч зі
    старим не з'являється ніколи: це був би другий torch на 2.5–4 ГБ.
    """
    man = man or M.active()
    _need_tool(uv, "ним створюється й наповнюється середовище рушіїв",
               "Windows: winget install astral-sh.uv · "
               "Linux/macOS: curl -LsSf https://astral.sh/uv/install.sh | sh")
    uv = _resolve_tool(uv) or uv
    if man.vcs_packages:
        # PARSeq (`strhub`) ставиться з репозиторію, а не з PyPI — його там немає.
        _need_tool("git", "з нього ставиться "
                          + ", ".join(v["name"] for v in man.vcs_packages),
                   "https://git-scm.com/downloads")
    py = venv_python(venv)

    if py.exists():
        print(f"✓ середовище є: {venv}")
    elif intel_mac():
        # 🔴 Intel Mac: `uv venv` + pip дали б відмову резолвера на torch уже
        # після того, як усе інше стало. Інтерпретатор і torch — з conda-forge.
        print(f"① створюю {venv.name} з conda-forge (python {man.python} + torch: "
              f"PyPI не має колес torch для macOS x86_64)…")
        _create_conda_env(venv, man, _conda_tool())
    else:
        print(f"① створюю {venv.name} (python {man.python})…")
        _run([uv, "venv", str(venv), "--python", man.python])

    rep = inspect(venv, man)
    need = [*rep.missing, *rep.stale]
    if need:
        if rep.stale:
            print(f"② оновлюю на місці: {', '.join(rep.stale)}"
                  + (f"; ставлю: {', '.join(rep.missing)}" if rep.missing else ""))
        else:
            print(f"② ставлю: {', '.join(rep.missing)}")
        # 🔴 За КЛЮЧЕМ, а не підрядком. Доти рядок звучав
        # `if any(m in s for m in rep.missing)` і мовчки викидав усе, чиє ім'я
        # не є підрядком власної специфікації, — тобто рівно git-залежності:
        # `strhub` проти `git+https://github.com/baudm/parseq.git`. PARSeq не
        # ставився ніколи, `pip` виходив із нуля, а `doctor` слав по колу назад
        # у цю саму команду.
        plan = man.install_specs()
        unknown = [m for m in need if m not in plan]
        if unknown:
            # Пакет, якого бракує, але ставити його нема чим. Мовчати про це
            # найгірше: далі буде «поставив» і те саме «бракує» — без причини.
            print(f"⚠ у маніфесті немає, чим ставити: {', '.join(unknown)}")
        if any(m in plan for m in need):
            # 🔴 У резолвер іде ВЕСЬ маніфест, а не лише відсутнє. `uv pip install`
            # не зважає на обмеження вже встановлених пакетів, яких немає в
            # запиті: доставлений окремо `nltk` підняв `click` до 8.5, хоча
            # kraken 7.1.1 тримає `click<8.3` (спіймано 04.10.2026 сухим прогоном).
            # Задоволене uv не чіпає, тож зайвого це не ставить — зокрема torch:
            # якщо наявний у межах kraken, він лишається, і оновлення kraken
            # коштує десятки МБ, а не 2.5 ГБ нового колеса.
            _run([uv, "pip", "install", "--python", str(venv_python(venv)),
                  *plan.values()])
        else:
            # ⚠ `uv pip install` без жодного пакета виходить ненульовим кодом,
            # а `_run` іде з `check=True` — тобто порожній список ронив команду
            # трасуванням там, де насправді просто нема чого ставити.
            print("⚠ ставити нема чого — жодної специфікації не знайшлось")
    else:
        print("✓ пакети на місці")

    if with_cuda:
        _ensure_cuda(venv, man, uv=uv, force_tag=force_tag)

    return inspect(venv, man)


def _pinned_torch(py: Path, man: M.Manifest) -> list[str]:
    """torch і torchvision під карту — ТИХ САМИХ версій, що вже стоять.

    🔴 Без піну `--reinstall torch torchvision` з CUDA-індексу бере найновіше, і
    обмеження kraken (`torch<=2.14` у 7.1.1) резолвер уже не бачить: заміряно
    02.10.2026 — на місце версії, яку поставив крок ②, приїхала 2.14.1+cu126,
    `uv pip check` — «incompatible». Патчі сегментації звірені на тому, що
    резолвить kraken, тож колесо під карту має бути тією самою версією.
    Локальна мітка (`+cpu`) відкидається: `==2.10.0` бере й `2.10.0+cu126`.
    """
    out: list[str] = []
    for dist in man.torch_default:
        have = _version_of(py, dist).split("+", 1)[0]
        out.append(f"{dist}=={have}" if have else dist)
    return out


def _ensure_cuda(venv: Path, man: M.Manifest, uv: str = "uv", force_tag: str = "") -> None:
    """Доставити CUDA-збірку torch за карткою, яку показує ДРАЙВЕР, не torch.

    🔴 Доти capability питали в самого torch — щойно поставленого кроком вище з
    PyPI, тобто на Windows у CPU-колесі, де CUDA немає взагалі. `device_count()`
    віддавав 0, карта «зникала», і людина з робочою RTX 3050 читала «карти не
    видно» (issue #7). На Linux це працювало випадково: там дефолтне колесо
    тягне бандл `nvidia-*-cu12`. Питає тепер `htr/gpu.py` — через `nvidia-smi`,
    який приїжджає з драйвером і про torch не знає.

    ⚠ Приймач кроку — НЕ код повернення `uv`, а повторна проба: колесо може
    стати без помилки й усе одно не побачити карту.
    """
    py = venv_python(venv)
    if sys.platform == "darwin":
        # CUDA на macOS немає за побудовою — ні колеса, ні драйвера; питати
        # `nvidia-smi` тут означало б друкувати «карти не видно» на кожному Mac.
        print(f"✓ macOS: {gpu.CPU_NOTE}")
        return
    if _probe(py, CUDA_WORKS) == "True":
        print("✓ torch уже бачить карту")
        return

    if force_tag:
        tag, what = force_tag, "вибрано вручну"
    else:
        card = gpu.detect_card()
        picked, reason = man.cuda_pick(card.capability if card else "",
                                       card.driver if card else "")
        if not picked:
            # Не помилка. Задача впирається в ядра, не в карту: на CPU все
            # працює, просто повільніше. Неправильне колесо не працювало б
            # узагалі, тому навмання не ставимо — але й не мовчимо про причину.
            print("⚠ " + gpu.explain(card, reason))
            return
        tag, what = picked, card.label() if card else "карта"

    print(f"③ доставляю torch під карту ({what} → {tag})…")
    try:
        _run([uv, "pip", "install", "--python", str(py), "--reinstall",
              *_pinned_torch(py, man), "--index-url", man.cuda_index_url(tag)])
    except subprocess.CalledProcessError:
        # ⚠ Не трасою назовні: набір CUDA-індексів PyTorch зсувається від релізу
        # до релізу, а матриця з версією torch ніяк не звірена — тобто колеса
        # `tag` під ту версію, яку резолвнув `uv`, на індексі може вже не бути.
        # CPU-збірка при цьому лишається робочою, і команда це має сказати.
        print(f"⚠ колесо {tag} не встало з {man.cuda_index_url(tag)} — {gpu.CPU_NOTE}.\n"
              f"  Ймовірно, під цю версію torch колеса {tag} на індексі вже немає: "
              f"спробуйте інший тег через `nysh htr install --cuda …`")
        return
    if _probe(py, CUDA_WORKS) == "True":
        print(f"✓ карта підхопилась ({tag})")
    else:
        print(f"⚠ колесо {tag} стало, але torch усе одно не бачить карту — {gpu.CPU_NOTE}.\n"
              f"  Це вже не детект: пишіть в issue разом із виводом `nysh doctor`")


def write_contract(path: Path, venv: Path, *, model_path: Path | None = None,
                   man: M.Manifest | None = None) -> dict[str, object]:
    """Записати `htr_env.json` — єдине, що пов'язує застосунок із середовищем.

    🔴 Шляхи тут абсолютні за потребою (їх виконує підпроцес), але сам файл
    належить робочому простору, а не пакету: у різних дослідників різні
    середовища, і спільний файл був би брехнею для одного з них.
    """
    man = man or M.active()
    rep = inspect(venv, man)
    payload = {
        "schema": ENV_SCHEMA,
        "python": str(venv_python(venv)),
        "venv": str(venv),
        "kraken": rep.kraken,
        "torch": rep.torch,
        "cuda": rep.cuda,
        "capability": rep.capability,
        "model_path": str(model_path) if model_path else "",
        "engines": [{"id": e.id, "kind": e.kind, "script": e.script,
                     "model_glob": e.model_glob, "model_globs": list(e.globs())}
                    for e in man.engines],
        "patches": [{"id": p.id, "tested_on": p.tested_on} for p in man.patches],
        "missing": list(rep.missing),
        "problems": list(rep.problems),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return payload


def read_contract(path: Path) -> dict[str, object] | None:
    """Контракт або None. Стара схема — теж None, і це навмисно.

    Мовчки працювати за контрактом іншої версії гірше, ніж чесно сказати
    «перестворіть середовище»: поля могли змінити зміст.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if int(data.get("schema") or 0) == ENV_SCHEMA else None


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="середовище рушіїв читання")
    ap.add_argument("--venv", required=True, help="тека venv рушіїв")
    ap.add_argument("--contract", help=f"куди писати {ENV_FILENAME}")
    ap.add_argument("--check", action="store_true", help="лише огляд, нічого не ставити")
    ap.add_argument("--no-cuda", action="store_true", help="не чіпати torch")
    ap.add_argument("--cuda", default="", metavar="ТЕГ",
                    help="поставити колесо вручну, напр. cu126 (замість детекту карти)")
    a = ap.parse_args(argv)

    venv = Path(a.venv)
    rep = inspect(venv) if a.check else setup(venv, with_cuda=not a.no_cuda,
                                              force_tag=a.cuda)
    print(f"\npython     : {rep.python or '—'}")
    print(f"kraken     : {rep.kraken or '—'}")
    print(f"torch      : {rep.torch or '—'}  cuda={rep.cuda} capability={rep.capability or '—'}")
    if rep.missing:
        print(f"🔴 бракує  : {', '.join(rep.missing)}")
    for p in rep.problems:
        print(f"⚠ {p}")
    if a.contract:
        write_contract(Path(a.contract), venv)
        print(f"✓ контракт : {a.contract}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
