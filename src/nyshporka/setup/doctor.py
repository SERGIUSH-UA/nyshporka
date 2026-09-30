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
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nyshporka.htr.env import EnvReport

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

    🔴 І питається torch СЕРЕДОВИЩА РУШІЇВ, а не той, що поруч із самим
    застосунком. Доти перевірка дивилась `find_spec("torch")` у власному
    процесі, а радила `nysh htr install`, який ставить torch в ІНШИЙ
    інтерпретатор — тобто порада поверталась у себе: виконавши її, людина бачила
    той самий рядок. Читання йде в `.venv_htr`, і осмислене питання лише про
    нього; torch поруч із застосунком у читанні не бере участі взагалі.
    """
    from nyshporka.htr import gpu

    rep = _engine_report()
    if rep is None:
        return Check("Прискорення (GPU)", "warn", "простір не визначено")
    if not rep.torch:
        # ⚠ Шлях тут не називається: його вже назвав рядок про рушії, і той
        # самий шлях двічі поспіль читається як дві різні поломки.
        return Check("Прискорення (GPU)", "warn",
                     "torch у середовищі рушіїв немає",
                     "nysh htr install — читання працюватиме й на процесорі, "
                     "просто ~2 хв на сторінку замість ~20 с")

    if not rep.cuda:
        # 🔴 Карту питає драйвер, а не цей torch. На CPU-збірці він про CUDA не
        # знає за побудовою, тож «карти немає» від нього — не відповідь, а тиша.
        from nyshporka.htr import manifest as _M

        card = gpu.detect_card()
        tag, reason = _M.active().cuda_pick(card.capability if card else "",
                                            card.driver if card else "")
        seen = card.label() if card else "карти драйвер не показує"
        hint = (f"nysh htr install — доставить колесо {tag} під цю карту" if tag
                else gpu.explain(card, reason))
        return Check("Прискорення (GPU)", "warn",
                     f"torch {rep.torch} у рушіях, CUDA недоступна · {seen}", hint)
    card = gpu.detect_card()
    bits = [card.name if card else "", f"torch {rep.torch}",
            f"sm_{rep.capability}" if rep.capability else ""]
    return Check("Прискорення (GPU)", "ok", " · ".join(b for b in bits if b))


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


@lru_cache(maxsize=1)
def _engine_report() -> EnvReport | None:
    """Один огляд середовища рушіїв на прогін доктора; `None` — простору немає.

    ⚠ Кеш не косметичний: `inspect()` це десяток запусків чужого інтерпретатора
    (на Windows — секунди), а питають його ДВІ перевірки — рушії й прискорення.
    Доктор живе один прогін, тож кеш на процес нічого не встигає застарити.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import env as henv

    try:
        return henv.inspect(engine_venv())
    except WorkspaceError:
        return None


def _engines() -> Check:
    """Середовище рушіїв — окремий інтерпретатор.

    Те, що встановлена сама Нишпорка, про нього не каже нічого: там свій пін
    `kraken==7.0.2` під патчі й свій torch.
    """
    rep = _engine_report()
    if rep is None:
        return Check("Рушії читання", "warn", "простір не визначено")
    if not rep.ok:
        from nyshporka.htr import env as henv

        why = "; ".join(rep.problems) or (
            f"бракує: {', '.join(rep.missing)}" if rep.missing else "не зібране")
        # ⚠ Сказано прямо, що середовище живе В ПРОСТОРІ. Інакше в людини з
        # другим дослідженням це читається як «ви ще не ставили», хоч поруч усе
        # стоїть, — а ваги при цьому спільні на машину, тобто розкладка
        # непослідовна, і мовчати про це дорожче, ніж визнати.
        venv = engine_venv()
        if str(venv) not in why:      # «немає інтерпретатора» шлях уже назвав
            why = f"{why} ({venv})"
        hint = ("nysh htr install — рушій ставиться окремо для КОЖНОГО "
                "простору (~2.5 ГБ); ваги при цьому спільні на машину")
        if henv.intel_mac():
            # Intel Mac: PyPI без колес torch, тож команда збирає інакше — і
            # людині варто знати, звідки візьметься інтерпретатор і чому.
            hint += " · Intel Mac: python і torch беруться з conda-forge (micromamba приїде сам)"
        return Check("Рушії читання", "warn", why, hint)
    bits = [f"kraken {rep.kraken}" if rep.kraken else "",
            f"torch {rep.torch}" if rep.torch else "",
            "CUDA" if rep.cuda else "CPU"]
    return Check("Рушії читання", "ok", " · ".join(b for b in bits if b))


def _models() -> Check:
    """⚠ Шлях названо навмисно: ваги лежать ГЛОБАЛЬНО, одні на машину.

    Поруч стоїть рядок про рушії, які ставляться в кожен простір окремо. Доки
    жоден із двох не каже, де саме він шукає, ця різниця виглядає як випадковість
    («моделі є, а рушія немає»), і людина шукає ваду там, де її нема.
    """
    from nyshporka.setup import packs

    where = packs.target_dir("model").parent
    have = packs.installed()
    if not have:
        return Check("Моделі письма", "warn", f"жодної не завантажено ({where})",
                     "nysh models get")
    return Check("Моделі письма", "ok", f"{', '.join(sorted(have))} · {where}")


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
    except WorkspaceError as exc:
        return Check("Профіль дослідження", "warn", str(exc).splitlines()[0],
                     "nysh profile init <Прізвище>", op="profile.set")
    except ProfileError as exc:
        if not _has_material():
            # 🔴 Порожній простір не має народжуватись поламаним. `nysh init`
            # профілю не створює (і не може: прізвища ніхто ще не називав), тож
            # ⚠ з'являлось у КОЖНОГО в першу хвилину життя простору — а
            # попередження, яке видає щойно зроблена дія, вчить не читати
            # попереджень. У браузері це вже крок чекліста, а не поломка.
            return Check("Профіль дослідження", "ok",
                         "ще не задано — наступний крок, а не поламка",
                         "nysh profile init <Прізвище>", op="profile.set")
        # А от коли матеріал уже є, мовчати не можна: без профілю всі написання
        # доводиться пригадувати самому, а рушій калічить саме середину слова.
        return Check("Профіль дослідження", "warn", str(exc).splitlines()[0],
                     "nysh profile init <Прізвище>", op="profile.set")
    return Check("Профіль дослідження", "ok",
                 f"{p.display or p.name} · написань: {len(p.all_spellings())}")


def _has_material() -> bool:
    """Чи є в просторі бодай щось, до чого профіль стосується.

    Дивиться на диск, а не в реєстр справ: реєстр з'являється лише після
    `nysh cases build`, тобто щойно завантажена справа для нього не існує — і
    відповідь «порожньо» була б неправдою рівно там, де робота вже почалась.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        root = workspace().root
    except WorkspaceError:
        return False
    for rel in ("data/raw", "data/pages", "reports/htr"):
        p = root / rel
        try:
            if p.is_dir() and any(p.iterdir()):
                return True
        except OSError:
            continue
    return False



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


def _shared_keys() -> Check:
    """Чи не лежать дві справи РІЗНИХ описів під одним ключем.

    🔴 Опис — фізично інший підрозділ фонду: «ДАДнО 193-1-213» і «193-3-213» —
    різні книги. Ключ без опису їх не розрізняє, і тоді облік прочитаного,
    прив'язки прогонів і шифра в Супрязі однієї книги лягають на іншу — тихо.
    Реєстрація дає другій справі власний ключ, але лише якщо її заводять уже
    поруч із першою; теки, описані раніше чи завантажувачем, ловить ця перевірка.
    """
    from nyshporka.library import load_library

    name = "Справи різних описів"
    try:
        lib = load_library()
    except Exception as exc:
        return Check(name, "warn", f"бібліотека не читається: {exc}")
    if not lib:
        return Check(name, "ok", "бібліотеку ще не зібрано")
    by_key: dict[str, list[dict[str, Any]]] = {}
    for e in lib:
        by_key.setdefault(str(e.get("key") or ""), []).append(e)
    shared = []
    for key, group in sorted(by_key.items()):
        opysy = {str(e.get("opys") or "").strip() for e in group} - {""}
        if key and len(opysy) > 1:
            shared.append((key, group))
    if not shared:
        return Check(name, "ok", f"{len(by_key)} ключів — жоден не тримає справ різних описів")
    head = "; ".join(
        f"{key}: " + ", ".join(sorted(str(e.get("shifra") or "?") for e in group))
        for key, group in shared[:3])
    more = f" і ще {len(shared) - 3}" if len(shared) > 3 else ""
    return Check(
        name, "warn",
        f"{len(shared)} ключів тримають справи різних описів — {head}{more}",
        "зареєструйте теку другої справи ще раз (`nysh case <тека> --shifra "
        "\"<шифра з описом>\"`) — вона отримає власний ключ з описом, а перша "
        "лишиться під своїм")


def _version() -> Check:
    """Яка версія стоїть — і де подивитись, чи є новіша.

    🔴 Мережі тут немає навмисно. `doctor` кличе інсталятор наприкінці
    встановлення й агент у скриптах, а `PRIVACY.md` обіцяє «фонової активності
    в мережі немає» — тож питати pypi.org звідси означало б порушити обіцянку
    рівно там, де людина нічого не просила. Рядок називає версію й дає кнопку;
    у мережу йде вже вона.
    """
    from nyshporka import __version__
    from nyshporka.setup import update as U

    days = U.days_since_check()
    fix = "перевірити, чи вийшла новіша: `nysh update --check`"
    # 🔴 «Не питали» — окремий стан, а не «все свіже». Мовчазний зелений рядок
    # тут показував би спокій там, де його ніхто не перевіряв: людина зі
    # збіркою піврічної давнини бачила б рівно те саме, що людина, яка щойно
    # оновилась. Це та сама вада, що нуль без знаменника, лише про версію.
    #
    # ⚠ Мережі тут немає й не буде: `PRIVACY.md` обіцяє, що фонової активності
    # немає, а `doctor` кличе інсталятор і агент у скриптах. Рядок читає лише
    # ВЛАСНИЙ запис про те, коли питали востаннє; у мережу йде кнопка.
    if days is None:
        return Check("Версія", "warn", f"{__version__} · чи є новіша — не питали",
                     fix, op="update.check")
    if days >= 30:
        return Check("Версія", "warn",
                     f"{__version__} · востаннє питали {days} дн. тому",
                     fix, op="update.check")
    return Check("Версія", "ok", f"{__version__} · питали {days} дн. тому",
                 fix, op="update.check")


def _skills() -> Check:
    """Чи не старші скіли агента за сам пакет.

    🔴 Оновлення пакета скіли не чіпає: вони копіюються разово в теку агента.
    Тобто після `nysh update` людина працює за КАРТКОЮ ПОПЕРЕДНЬОЇ ВЕРСІЇ, і
    помітити це нема як — застарілий скіл виглядає точно так само, як свіжий.
    Дані для перевірки лежали в обліку `.nysh-skills.json` від першого дня;
    бракувало рівно того, щоб їх спитати.
    """
    from nyshporka import __version__
    from nyshporka import skills as S

    got = S.installed()
    if not got:
        return Check("Скіли агента", "ok", "не встановлені",
                     "покласти туди, де їх бачить агент: `nysh skills install`")
    stale = [(d, v) for d, v in got if v != __version__]
    if not stale:
        where = ", ".join(str(d) for d, _ in got)
        return Check("Скіли агента", "ok", f"{__version__} · {where}")
    detail = " · ".join(f"{v} у {d}" for d, v in stale)
    return Check("Скіли агента", "warn",
                 f"старші за пакет ({__version__}): {detail}",
                 "покласти наново: `nysh skills install` — правлене руками "
                 "лишиться як є")


#: Бекенд оренди, про який доктор каже окремим словом: на нього веде типове
#: `nysh cloud go`, тож «його немає» — це відповідь на питання, яке поставлять.
RENT_DEFAULT = "vast"


def _rent() -> Check:
    """Чи є чим орендувати машину під читання — без жодного запиту в мережу.

    🔴 Лише реєстр плагінів і те, що плагін знає локально. Баланс і перелік
    машин, що тарифікуються, сюди не потрапляють навмисно: доктора гукають
    часто й офлайн, а перевірка, яка висить на чужому API, робить повільним і
    крихким увесь звіт. Для них є `nysh cloud rent status`.
    """
    from nyshporka.cloud import registry as REG
    from nyshporka.cloud.base import bills

    reg = REG.load()
    renters = [b for b in reg.all() if bills(b)]
    head = f"бекенди {len(reg.all())}, зламані {len(reg.broken)}"
    broken = "; ".join(f"{n} ({why})" for n, why in reg.broken)
    install = ("поставити плагін оренди: "
               "`pip install \"nyshporka[rent]\"`")
    got = reg.get(RENT_DEFAULT)
    if got is None:
        if any(n == RENT_DEFAULT for n, _ in reg.broken):
            return Check("Оренда", "warn",
                         f"{head}; {RENT_DEFAULT} — плагін зламаний: {broken}",
                         install)
        others = ", ".join(b.id for b in renters)
        # Не `warn`: оренда — необов'язковий шлях, і докоряти нею людині, яка
        # читає на своїй машині, означало б привчити її не читати доктора.
        return Check("Оренда", "ok",
                     f"{head}; {RENT_DEFAULT} — немає плагіна"
                     + (f"; з орендою є: {others}" if others else ""),
                     install)
    # Необов'язковий метод плагіна: чи лежить ключ ЛОКАЛЬНО. Без мережі.
    # Сам `status()` сюди не годиться — він питає баланс і машини в мережі.
    import os

    fn = getattr(got, "configured", None)
    state = None
    if callable(fn):
        try:
            state = bool(fn())
        except Exception:
            state = None
    if state is None and os.environ.get(f"{RENT_DEFAULT.upper()}_API_KEY", "").strip():
        state = True        # ключ у змінній середовища — його бачимо й самі
    tail = f"; зламані: {broken}" if broken else ""
    if state is True:
        return Check("Оренда", "ok", f"{head}; {RENT_DEFAULT} — готовий{tail}")
    if state is False:
        return Check("Оренда", "warn", f"{head}; {RENT_DEFAULT} — немає ключа{tail}",
                     "дати ключ провайдера: `nysh cloud rent login`")
    return Check("Оренда", "ok",
                 f"{head}; {RENT_DEFAULT} — плагін є, чи є ключ — невідомо{tail}",
                 "перевірити ключ і баланс: `nysh cloud rent status`")


def _library() -> Check:
    """Чи не суперечить архів запису в каталозі справ його ж шифрі.

    🔴 Такий запис лишився від давнього правила тек, що вгадувало архів за
    номером (до 0.18.13), і нічим себе не видає: облік справи лежить під
    ключем чужого архіву, а пул про неї питають під чужим ключем.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.pagestore.store import library_conflicts

    try:
        workspace()
    except WorkspaceError:
        return Check("Каталог справ", "warn", "простір не визначено")
    bad = library_conflicts()
    if not bad:
        return Check("Каталог справ", "ok", "архів кожного запису збігається з його шифрою")
    pryklady = "; ".join(f"{c['key']} ↔ «{c['shifra']}»" for c in bad[:3])
    tail = f" і ще {len(bad) - 3}" if len(bad) > 3 else ""
    return Check("Каталог справ", "warn",
                 f"{len(bad)} записів, де архів ключа суперечить шифрі: {pryklady}{tail}",
                 "перезібрати каталог: `nysh cases build`; що лишилось — виправити "
                 "паспорт справи: `nysh case <тека> --shifra \"<архів фонд-опис-справа>\"`. "
                 "Облік, записаний під старим ключем, перенести в новий файл")


def _chain() -> Check:
    """Чи не лежать завантажені теки без реєстрації.

    🔴 Завантажувач лишає в теці `meta.json` — запис про завантаження. Паспорт
    справи (`_source.json`) пише лише реєстрація, і без шифри тека не
    потрапляє ні в каталог, ні в читання, ні у віддачу. Це рівно те, на чому
    спіткнувся сторонній користувач із двадцятьма справами (29.09.2026), і
    жодна перевірка цього не казала.

    Диск тут не обходиться: доктора гукають часто, зокрема головна застосунку.
    Береться те, що реєстр справ уже знає як матеріал без справи. Решта тек без
    шифри й нічиї прогони — довідкою, не попередженням: у дослідницькому
    просторі це звичайний стан, а не поломка.
    """
    from nyshporka.cases import chain as C

    name = "Ланцюг справи"
    rows = C.quick()
    if rows is None:
        return Check(name, "ok", "реєстр справ ще не зібрано",
                     "зібрати: `nysh cases build`")
    lich = C.summary(rows)
    dovidka = (f"тек без шифри: {lich[C.NO_PASSPORT]}, прогонів без справи: "
               f"{lich[C.ORPHAN_RUN]}")
    zavantazheni = [r for r in rows if r.link == C.LOADER_ONLY]
    if not zavantazheni:
        return Check(name, "ok", f"завантажених тек без реєстрації немає · {dovidka}",
                     "перелік по теках: `nysh cases chain`")
    pryklady = "; ".join(r.path for r in zavantazheni[:3])
    tail = f" і ще {len(zavantazheni) - 3}" if len(zavantazheni) > 3 else ""
    return Check(
        name, "warn",
        f"{len(zavantazheni)} завантажених тек без реєстрації — у каталог і в "
        f"читання вони не потраплять: {pryklady}{tail} · {dovidka}",
        "дати кожній шифру: `nysh case <тека> --shifra \"<архів фонд-опис-справа>\"` "
        "(`meta.json` у теці — запис про завантаження, не паспорт справи); "
        "перелік із готовими командами: `nysh cases chain`")


def _queue() -> Check:
    """Чи не стоїть черга справ: обірваний виконавець або справи, що чекають людину.

    Черга нічого не каже сама — її ставлять на ніч. Уранці перше, що людина
    відкриває, — доктор або головна застосунку, і «три справи чекають вашого
    рішення» мусить бути видно там, а не лише в `nysh queue`.
    """
    from nyshporka.queue import state as Q

    name = "Черга справ"
    try:
        q = Q.load()
    except Q.QueueError as exc:
        return Check(name, "warn", str(exc))
    items = [it for it in q["items"] if it.get("state") != Q.DROPPED]
    if not items:
        return Check(name, "ok", "черга порожня")
    alive = Q.runner_alive()
    skilky = {s: sum(1 for it in items if it.get("state") == s) for s in Q.NAZVY}
    live = sum(skilky[s] for s in Q.LIVE)
    pidsumok = f"у черзі {live}, зроблено {skilky[Q.DONE]}"
    obirvani = [str(it["id"]) for it in items if it.get("state") == Q.RUNNING]
    if obirvani and not alive:
        return Check(name, "warn",
                     f"виконавця обірвано на справі «{obirvani[0]}» · {pidsumok}",
                     "продовжити з того самого етапу: `nysh queue run`")
    chekaie = skilky[Q.BLOCKED] + skilky[Q.FAILED]
    if chekaie:
        return Check(name, "warn",
                     f"справ чекає вашого рішення: {chekaie} · {pidsumok}",
                     "причина й команда для кожної: `nysh queue`")
    if live and not alive:
        return Check(name, "ok", f"{pidsumok} · виконавець не запущений",
                     "вести чергу: `nysh queue run`")
    return Check(name, "ok", pidsumok + (" · виконавець працює" if alive else ""))


CHECKS = (_version, _skills, _python, _workspace, _cloud_sync, _disk, _profile,
          _library, _chain, _queue, _decode_visible, _shared_keys, _torch, _engines,
          _models, _rent)

#: Перевірки, які мають сенс лише при ввімкненій секції. 🔴 Не косметика:
#: «⚠ рушії не встановлені» на машині того, хто прийшов подивитись каталог
#: справ, — це порада полагодити те, чого він не ставив і не збирався. Доктор
#: мусить казати про готовність до тієї роботи, яку тут справді роблять.
SECTION_OF_CHECK = {_torch: "htr", _engines: "htr", _models: "htr",
                    _rent: "htr", _profile: "research", _queue: "htr"}


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
    # 🔴 Кеш огляду рушіїв живе рівно один прогін. У демоні процес не вмирає
    # тижнями, і без цього рядка доктор показував би стан, який був на першому
    # відкритті сторінки, — тобто відповідав би «рушіїв немає» тому, хто щойно
    # їх поставив і натиснув «перевірити ще раз».
    _engine_report.cache_clear()
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
