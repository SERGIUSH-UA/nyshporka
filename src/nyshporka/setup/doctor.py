"""🩺 Доктор: чи справді працює те, що виглядає працюючим.

Кожна перевірка тут існує тому, що відповідна поломка **тиха**. Гучні поломки
доктора не потребують: людина бачить traceback і йде читати. Тихі виглядають як
«у мене просто повільно» або «нічого не знайшлось», і живуть місяцями.

Що саме стережеться:

* **CPU замість карти.** torch без CUDA не падає — він рахує. Просто вп'ятеро
  довше, і виглядає це як «сьогодні гальмує». Тому друкується
  `torch.version.cuda` і `is_available()`, а не «torch встановлено».
* **Простір у хмарній синхронізації.** OneDrive із «файлами на вимогу» робить
  `is_file()` мережевим викликом: обхід 2000 сторінок «зависає» без жодної
  помилки. Ловиться reparse-point'ом на теці простору.
* **Простір у ризикованому корені.** Корінь диска чи домівка як простір
  означають, що гард шляхів накриває півмашини.
* **Немає місця.** Одна справа буває 30 ГБ. «Скінчилось на 80%» посеред ночі —
  найдорожчий спосіб про це дізнатись.
* **Середовище рушіїв.** Це окремий інтерпретатор, і «Нишпорка встановлена» про
  нього не каже нічого.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Level = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str
    fix: str = ""

    @property
    def mark(self) -> str:
        return {"ok": "✅", "warn": "⚠", "fail": "🔴"}[self.level]


def _python() -> Check:
    v = sys.version_info
    if v < (3, 11):
        return Check("Python", "fail", f"{v.major}.{v.minor} — потрібен 3.11+",
                     "інсталятор приносить свій інтерпретатор")
    return Check("Python", "ok", f"{v.major}.{v.minor}.{v.micro}")


def _workspace() -> Check:
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return Check("Робочий простір", "fail", str(exc).splitlines()[0],
                     "nysh init")
    bits = [str(ws.root), f"джерело: {ws.origin}"]
    if not ws.data.is_dir():
        return Check("Робочий простір", "warn", " · ".join(bits) + " — ще порожній",
                     "покладіть скани й запустіть `nysh look <тека>`")
    return Check("Робочий простір", "ok", " · ".join(bits))


def _cloud_sync() -> Check:
    """🔴 Хмарна синхронізація перетворює читання диска на мережу.

    OneDrive/Dropbox із «файлами на вимогу» лишають на диску заглушки-
    reparse-point'и. `is_file()` на такій заглушці тягне файл із мережі — і
    сканування справи на 2000 сторінок «зависає» без жодної помилки, бо
    формально нічого не зламалось.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        root = workspace().root
    except WorkspaceError:
        return Check("Хмарна синхронізація", "warn", "простір не визначено")
    marks = ("onedrive", "dropbox", "google drive", "яндекс", "icloud")
    low = str(root).lower()
    hit = next((m for m in marks if m in low), "")
    if hit:
        return Check("Хмарна синхронізація", "warn",
                     f"простір лежить у «{hit}»",
                     "перенесіть простір поза теку синхронізації — інакше "
                     "обхід справ буде мережевим і виглядатиме як зависання")
    if os.name == "nt":
        try:
            import stat as _stat
            # `st_file_attributes` існує лише на Windows — звідси подвійна
            # позначка: на Linux потрібен `attr-defined`, на Windows вона зайва,
            # а CI ганяє обидві платформи.
            attrs = root.stat().st_file_attributes  # type: ignore[attr-defined, unused-ignore]
            if bool(attrs & _stat.FILE_ATTRIBUTE_REPARSE_POINT):
                return Check("Хмарна синхронізація", "warn",
                             "тека простору — reparse-point (синхронізація "
                             "або junction)",
                             "перевірте, що це не «файли на вимогу»")
        except (OSError, AttributeError):
            pass
    return Check("Хмарна синхронізація", "ok", "простір лежить на локальному диску")


def _disk() -> Check:
    """Одна справа буває 30 ГБ; дізнатись про брак місця на 80% — найдорожче."""
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        root = workspace().root
    except WorkspaceError:
        return Check("Місце на диску", "warn", "простір не визначено")
    try:
        free_gb = shutil.disk_usage(root).free / 2**30
    except OSError as exc:
        return Check("Місце на диску", "warn", str(exc))
    if free_gb < 5:
        return Check("Місце на диску", "fail", f"вільно {free_gb:.1f} ГБ",
                     "одна справа архіву буває 10-30 ГБ")
    if free_gb < 30:
        return Check("Місце на диску", "warn", f"вільно {free_gb:.0f} ГБ",
                     "на велику справу може не вистачити")
    return Check("Місце на диску", "ok", f"вільно {free_gb:.0f} ГБ")


def _torch() -> Check:
    """🔴 CPU-torch не падає — він просто рахує вп'ятеро довше.

    Тому перевіряється не наявність, а `is_available()`: «встановлено» тут
    нічого не означає.
    """
    from importlib.util import find_spec

    if find_spec("torch") is None:
        return Check("Прискорення (GPU)", "warn", "torch не встановлено",
                     "nysh htr install — читання працюватиме й на процесорі, "
                     "просто ~2 хв на сторінку замість ~20 с")
    import torch

    if not torch.cuda.is_available():
        return Check("Прискорення (GPU)", "warn",
                     f"torch {torch.__version__}, CUDA недоступна "
                     f"(зібрано під {torch.version.cuda or 'CPU'})",
                     "nysh doctor --gpu добере колеса під вашу карту")
    name = torch.cuda.get_device_name(0)
    cap = ".".join(str(x) for x in torch.cuda.get_device_capability(0))
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30
    return Check("Прискорення (GPU)", "ok",
                 f"{name} · CUDA {torch.version.cuda} · sm_{cap} · {vram:.1f} ГБ")


#: Змінна середовища для тих, хто тримає рушії деінде.
ENV_ENGINE_VENV = "NYSHPORKA_HTR_VENV"

#: Імена, під якими середовище рушіїв уже могло бути зібране. Перше — наше;
#: решта — те, що реально трапляється на машинах, де конвеєр збирали руками.
_ENGINE_VENV_NAMES = (".venv_htr", ".venv_kraken")


def engine_venv() -> Path:
    """Тека середовища рушіїв.

    🔴 Шукається СЕРЕД наявних, а не назначається одна. Збірка цього середовища
    коштує кількох гігабайтів і довгого встановлення; вимагати другої копії
    лише тому, що тека зветься інакше, — це змусити людину або ставити те саме
    вдруге, або відмовитись від застосунку. Тому: спершу змінна середовища,
    далі відома тека, яка справді існує, і лише як дефолт — наша назва.
    """
    import os

    from nyshporka.core.workspace import workspace

    override = os.environ.get(ENV_ENGINE_VENV)
    if override:
        return Path(override)
    root = workspace().root
    for name in _ENGINE_VENV_NAMES:
        if (root / name).is_dir():
            return root / name
    return root / _ENGINE_VENV_NAMES[0]


def _engines() -> Check:
    """Середовище рушіїв — ОКРЕМИЙ інтерпретатор.

    Те, що встановлена сама Нишпорка, про нього не каже нічого: там свій пін
    `kraken==7.0.2` під патчі й свій torch.
    """
    from nyshporka.htr import env as henv

    rep = henv.inspect(engine_venv())
    if not rep.ok:
        why = "; ".join(rep.problems) or (
            f"бракує: {', '.join(rep.missing)}" if rep.missing else "не зібране")
        return Check("Рушії читання", "warn", why, "nysh htr install")
    bits = [f"kraken {rep.kraken}" if rep.kraken else "",
            f"torch {rep.torch}" if rep.torch else "",
            "CUDA" if rep.cuda else "CPU"]
    return Check("Рушії читання", "ok", " · ".join(b for b in bits if b))


def _models() -> Check:
    from nyshporka.setup import packs

    have = packs.installed()
    if not have:
        return Check("Моделі письма", "warn", "жодної не завантажено",
                     "nysh models get --all")
    return Check("Моделі письма", "ok", ", ".join(sorted(have)))


CHECKS = (_python, _workspace, _cloud_sync, _disk, _torch, _engines, _models)


def run() -> list[Check]:
    out: list[Check] = []
    for fn in CHECKS:
        try:
            out.append(fn())
        except Exception as exc:  # перевірка не має валити доктора
            out.append(Check(fn.__name__.strip("_"), "warn",
                             f"перевірка не пройшла: {type(exc).__name__}: {exc}"))
    return out


def cuda_tag(capability: str) -> str | None:
    """Compute capability карти → тег колеса torch.

    🔴 Матриця живе в маніфесті рушіїв, а не в коді: cu126 під sm_75
    (GTX 16xx / RTX 20xx) на новіших картах не працює взагалі, і зашитий тег
    зробив би застосунок непрацездатним на половині заліза — мовчки, бо
    встановиться воно однаково. Тут лише тонка обгортка: одне джерело правди
    про залізо мусить лишатись одним.
    """
    from nyshporka.htr import manifest as M

    return M.active().cuda_tag(capability)
