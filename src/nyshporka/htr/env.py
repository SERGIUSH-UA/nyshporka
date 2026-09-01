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


def _probe(py: Path, code: str, timeout: int = 120) -> str | None:
    """Виконати рядок у чужому інтерпретаторі; None — якщо не вийшло."""
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _version_of(py: Path, dist: str) -> str:
    return _probe(py, f"import importlib.metadata as m; print(m.version({dist!r}))") or ""


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
    cuda = _probe(py, "import torch; print(torch.cuda.is_available())") == "True"
    cap = _probe(py, "import torch; print('%d.%d' % torch.cuda.get_device_capability(0))") \
        if cuda else ""

    problems: list[str] = []
    want = next((s.split("==")[1] for s in man.packages
                 if s.startswith("kraken==")), "")
    if kraken and want and kraken != want:
        problems.append(
            f"kraken {kraken}, а патчі сегментації звірені на {want} — "
            f"розбіжність буде тихою: інші полігони рядків, тобто інший текст")

    return EnvReport(ok=not missing and not problems, python=py, kraken=kraken,
                     torch=torch_v, cuda=cuda, capability=cap or "",
                     missing=tuple(missing), problems=tuple(problems))


class ToolMissing(RuntimeError):
    """Зовнішнього інструмента немає на машині — з назвою і що з цим робити.

    🔴 Окремий тип, а не голий `FileNotFoundError` із надр `subprocess`. Той
    приходить із текстом ОС мовою системи («Не удается найти указанный файл»),
    без назви інструмента й без жодної підказки — тобто на найчастішому шляху
    («поставив pip-ом, запустив `nysh htr install`») людина отримує трасу стека
    замість одного рядка про те, чого бракує.
    """


def _need_tool(name: str, why: str, how: str) -> None:
    """Перевірити перед запуском, а не впасти всередині.

    Обидві перевірки тут не про педантизм: `uv` і `git` у цьому пакеті — не
    залежності збірки, тож у людини, яка ставила `pip install`, їх може не бути
    зовсім. Збірка середовища рушіїв — єдине місце, де вони потрібні, і саме там
    їхня відсутність досі виглядала як поломка застосунку.
    """
    if shutil.which(name):
        return
    raise ToolMissing(f"{name} не знайдено — {why}\n"
                      f"  {how}")


def _run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def setup(venv: Path, *, man: M.Manifest | None = None, with_cuda: bool = True,
          uv: str = "uv", force_tag: str = "") -> EnvReport:
    """Створити або доповнити середовище. Ідемпотентно: наявне не чіпається."""
    man = man or M.active()
    _need_tool(uv, "ним створюється й наповнюється середовище рушіїв",
               "Windows: winget install astral-sh.uv · "
               "Linux/macOS: curl -LsSf https://astral.sh/uv/install.sh | sh")
    if man.vcs_packages:
        # PARSeq (`strhub`) ставиться з репозиторію, а не з PyPI — його там немає.
        _need_tool("git", "з нього ставиться "
                          + ", ".join(v["name"] for v in man.vcs_packages),
                   "https://git-scm.com/downloads")
    py = venv_python(venv)

    if py.exists():
        print(f"✓ середовище є: {venv}")
    else:
        print(f"① створюю {venv.name} (python {man.python})…")
        _run([uv, "venv", str(venv), "--python", man.python])

    rep = inspect(venv, man)
    if rep.missing:
        print(f"② ставлю: {', '.join(rep.missing)}")
        # 🔴 За КЛЮЧЕМ, а не підрядком. Доти рядок звучав
        # `if any(m in s for m in rep.missing)` і мовчки викидав усе, чиє ім'я
        # не є підрядком власної специфікації, — тобто рівно git-залежності:
        # `strhub` проти `git+https://github.com/baudm/parseq.git`. PARSeq не
        # ставився ніколи, `pip` виходив із нуля, а `doctor` слав по колу назад
        # у цю саму команду.
        plan = man.install_specs()
        specs = [plan[m] for m in rep.missing if m in plan]
        unknown = [m for m in rep.missing if m not in plan]
        if unknown:
            # Пакет, якого бракує, але ставити його нема чим. Мовчати про це
            # найгірше: далі буде «поставив» і те саме «бракує» — без причини.
            print(f"⚠ у маніфесті немає, чим ставити: {', '.join(unknown)}")
        if specs:
            _run([uv, "pip", "install", "--python", str(venv_python(venv)), *specs])
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
    if _probe(py, "import torch; print(torch.cuda.is_available())") == "True":
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
              *man.torch_default, "--index-url", man.cuda_index_url(tag)])
    except subprocess.CalledProcessError:
        # ⚠ Не трасою назовні: набір CUDA-індексів PyTorch зсувається від релізу
        # до релізу, а матриця з версією torch ніяк не звірена — тобто колеса
        # `tag` під ту версію, яку резолвнув `uv`, на індексі може вже не бути.
        # CPU-збірка при цьому лишається робочою, і команда це має сказати.
        print(f"⚠ колесо {tag} не встало з {man.cuda_index_url(tag)} — {gpu.CPU_NOTE}.\n"
              f"  Ймовірно, під цю версію torch колеса {tag} на індексі вже немає: "
              f"спробуйте інший тег через `nysh htr install --cuda …`")
        return
    if _probe(py, "import torch; print(torch.cuda.is_available())") == "True":
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
                     "model_glob": e.model_glob} for e in man.engines],
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
