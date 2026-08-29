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
    #: 🔴 Операція, якою це лагодиться З ЕКРАНА. Без неї колонка «чим це
    #: ставиться» лишалась суцільним терміналом: дев'ять рядків `<code>` і
    #: жодної кнопки — під написом «нижче — чого бракує і ЧИМ ЦЕ СТАВИТЬСЯ».
    #: Людина, яка ставила застосунок майстром, командного рядка не має в полі
    #: зору взагалі, тож порада виконувалась рівно ніким.
    #: ⚠ Порожньо означає «дії немає», а не «дія та сама, що в `fix`»: частина
    #: порад — це справді робота в терміналі, і вдавати кнопку там гірше, ніж
    #: чесно показати команду.
    op: str = ""

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
                     "покладіть скани й запустіть `nysh look <тека>`",
                     op="material.look")
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
                     # ⚠ Тут стояв `doctor` із прапорцем «--gpu», якого немає й
                     # ніколи не було. Порада, що вказує в порожнє, гірша за
                     # відсутню: людина виконує її, бачить помилку і вирішує, що
                     # зламався застосунок. Колеса під карту добирає саме
                     # `htr install` (`_ensure_cuda` читає compute capability).
                     "nysh htr install добере колеса під вашу карту")
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

    🔴 Шукається серед наявних, а не назначається одна. Збірка цього середовища
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
    """Середовище рушіїв — окремий інтерпретатор.

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
                     "nysh models get")
    return Check("Моделі письма", "ok", ", ".join(sorted(have)))


def _profile() -> Check:
    """Чи названо, чий рід шукаємо.

    🔴 Рівень `warn`, а не `fail`: на свіжій установці профілю немає ніде — ні
    `nysh init`, ні майстер його не створюють, шаблону в комплекті теж немає.
    Червоне тут читалось би як поламка щойно поставленого застосунку.

    🔴 Тут стояло «пошук працює на прізвищі чужого дослідження, яке приїхало зі
    зразком». Це неправда: зразок конфігу не несе, `q` у пошуку обов'язкове, а
    дефолтного прізвища в пакеті немає ніде. Фраза лишилась від конвеєра, де рід
    жив константами в модулях, — і лякала вигаданим ризиком, заразом ховаючи
    справжній: без профілю всі написання доводиться пригадувати самому, а рушій
    калічить саме середину слова.
    """
    from nyshporka.core.profile import ProfileError, active
    from nyshporka.core.workspace import WorkspaceError

    try:
        p = active()
    except (ProfileError, WorkspaceError) as exc:
        return Check("Профіль дослідження", "warn", str(exc).splitlines()[0],
                     "nysh profile init <Прізвище>", op="profile.set")
    return Check("Профіль дослідження", "ok",
                 f"{p.display or p.name} · написань: {len(p.all_spellings())}")



def _decode_visible() -> Check:
    """Чи видно декоди звичайному пошуку по файлах.

    🔴 Простір, розгорнутий усередині git-репо, ховає прочитане від `rg`:
    `/reports/` і `/data/` стоять у `.gitignore` пакета, а ripgrep його
    поважає. Пошук Нишпорки це не зачіпає — він ходить по диску, — але людина
    (і агент) частіше тягнеться до `rg`, і дістає хибний нуль по всій справі,
    не отримавши жодного натяку, що теку просто не читали.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        root = workspace().root
    except WorkspaceError:
        return Check("Декоди видимі для grep", "warn", "простір не визначено")
    for base in (root, *root.parents):
        if not (base / ".git").exists():
            continue
        ignore = base / ".gitignore"
        try:
            text = ignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return Check("Декоди видимі для grep", "ok",
                         f"простір у репозиторії {base.name}, .gitignore нечитний")
        hidden = [ln.strip() for ln in text.splitlines()
                  if ln.strip().strip("/") in ("reports", "data")]
        if hidden:
            return Check(
                "Декоди видимі для grep", "warn",
                f"простір лежить у git-репозиторії {base.name}, а "
                f"{', '.join(sorted(set(hidden)))} під .gitignore — `rg` туди "
                f"не зайде й віддасть порожньо",
                "шукати через `nysh search`, а голим ripgrep — лише з --no-ignore")
        break
    return Check("Декоди видимі для grep", "ok", "простір поза git-репозиторієм")


def _version() -> Check:
    """Яка версія стоїть — і де подивитись, чи є новіша.

    🔴 Мережі тут немає навмисно. `doctor` кличе інсталятор наприкінці
    встановлення й агент у скриптах, а `PRIVACY.md` обіцяє «фонової активності
    в мережі немає» — тож питати pypi.org звідси означало б порушити обіцянку
    рівно там, де людина нічого не просила. Рядок називає версію й дає кнопку;
    у мережу йде вже вона.
    """
    from nyshporka import __version__

    return Check("Версія", "ok", __version__,
                 "перевірити, чи вийшла новіша: `nysh update --check`",
                 op="update.check")


CHECKS = (_version, _python, _workspace, _cloud_sync, _disk, _profile,
          _decode_visible, _torch, _engines, _models)

#: Перевірки, які мають сенс лише при ввімкненій секції. 🔴 Не косметика:
#: «⚠ рушії не встановлені» на машині того, хто прийшов подивитись каталог
#: справ, — це порада полагодити те, чого він не ставив і не збирався. Доктор
#: мусить казати про готовність до тієї роботи, яку тут справді роблять.
SECTION_OF_CHECK = {_torch: "htr", _engines: "htr", _models: "htr",
                    _profile: "research"}


def _active_sections() -> frozenset[str] | None:
    """Ввімкнені секції або `None`, якщо простору ще немає.

    `None` означає «не звужувати»: доктора часто гукають до `nysh init`, саме
    щоб дізнатись, чого бракує, — і мовчати там про рушії було б найгіршим
    моментом для мовчання.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        return workspace().sections
    except WorkspaceError:
        return None


def run() -> list[Check]:
    out: list[Check] = []
    active = _active_sections()
    for fn in CHECKS:
        need = SECTION_OF_CHECK.get(fn)
        if need and active is not None and need not in active:
            continue
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
