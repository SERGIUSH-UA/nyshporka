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
3. **CUDA обирається за КАРТОЮ, а не зашивається.** Індекс `cu126` підібраний
   під sm_75; на новіших картах таке колесо не працює. Карта поза відомими
   межами лишається на CPU: повільно, але робочо — краще, ніж колесо, яке не
   запускається.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nyshporka.htr import manifest as M

#: Версія контракту. Піднімається, коли міняється СКЛАД файлу, щоб застосунок
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
    """Що є в середовищі — БЕЗ спроб щось лагодити.

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
        dist = spec.split("==")[0].split(">=")[0].strip()
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
            f"розбіжність буде ТИХОЮ: інші полігони рядків, тобто інший текст")

    return EnvReport(ok=not missing and not problems, python=py, kraken=kraken,
                     torch=torch_v, cuda=cuda, capability=cap or "",
                     missing=tuple(missing), problems=tuple(problems))


def _run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def setup(venv: Path, *, man: M.Manifest | None = None, with_cuda: bool = True,
          uv: str = "uv") -> EnvReport:
    """Створити або доповнити середовище. Ідемпотентно: наявне не чіпається."""
    man = man or M.active()
    py = venv_python(venv)

    if py.exists():
        print(f"✓ середовище є: {venv}")
    else:
        print(f"① створюю {venv.name} (python {man.python})…")
        _run([uv, "venv", str(venv), "--python", man.python])

    rep = inspect(venv, man)
    if rep.missing:
        print(f"② ставлю: {', '.join(rep.missing)}")
        specs = [s for s in man.pip_specs()
                 if any(m in s for m in rep.missing)]
        _run([uv, "pip", "install", "--python", str(venv_python(venv)), *specs])
    else:
        print("✓ пакети на місці")

    if with_cuda:
        _ensure_cuda(venv, man, uv=uv)

    return inspect(venv, man)


def _ensure_cuda(venv: Path, man: M.Manifest, uv: str = "uv") -> None:
    """Доставити CUDA-збірку torch, якщо карта відома й колесо для неї існує."""
    py = venv_python(venv)
    if _probe(py, "import torch; print(torch.cuda.is_available())") == "True":
        print("✓ torch уже бачить карту")
        return
    cap = _probe(py, "import torch;"
                     "print('%d.%d' % torch.cuda.get_device_capability(0))"
                     " if torch.cuda.device_count() else print('')")
    tag = man.cuda_tag(cap or "")
    if not tag:
        # Не помилка. Задача впирається в ядра, не в карту: на CPU все працює,
        # просто повільніше. Неправильне колесо не працювало б узагалі.
        print("⚠ карти не видно або вона поза відомими межами — лишаю CPU-збірку "
              "(читання піде ~2 хв/стор замість ~20 с)")
        return
    print(f"③ доставляю torch під карту (compute {cap} → {tag})…")
    _run([uv, "pip", "install", "--python", str(py), "--reinstall",
          *man.torch_default, "--index-url", man.cuda_index_url(tag)])


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
    a = ap.parse_args(argv)

    venv = Path(a.venv)
    rep = inspect(venv) if a.check else setup(venv, with_cuda=not a.no_cuda)
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
