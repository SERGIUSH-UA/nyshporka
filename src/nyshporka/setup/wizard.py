"""🧭 Перший запуск: створити простір, не питаючи нічого зайвого.

🔴 Простір НІКОЛИ не створюється мовчки. Тека, що з'явилась сама собі, — це
дослідження, яке потім не можуть знайти: людина шукає свої скани там, де
поклала, а застосунок пише в інше місце. Тому майстер називає шлях і питає
підтвердження, а `--yes` існує лише для інсталятора.

🔴 Дефолт свідомо НЕ в теці синхронізації. `Documents` в багатьох машинах
перенаправлено в OneDrive, а «файли на вимогу» перетворюють обхід справи на
мережеві виклики: 2000 сторінок «зависають» без жодної помилки. Тому дефолт
перевіряється й, якщо він синхронізується, майстер пропонує сусідній шлях.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Ім'я теки простору за замовчуванням. Кирилицею: її бачить людина, а не код.
DEFAULT_DIRNAME = "Нишпорка"

_CLOUD_MARKS = ("onedrive", "dropbox", "google drive", "яндекс", "icloud")


@dataclass(frozen=True)
class Plan:
    """Що майстер збирається зробити. Показується ДО того, як робиться."""

    root: Path
    creating: bool
    warning: str = ""
    #: Звідки взявся `root` — значення з того самого словника, що `Workspace.origin`
    #: (`explicit` · `env:…` · `marker` · `last-used` · `default`). Без нього ні
    #: людина, ні тест не відрізнять «шлях зі змінної» від «типового місця», а
    #: саме ця різниця й була непомітною, доки майстер знав одне джерело з п'яти.
    origin: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"root": str(self.root), "creating": self.creating,
                "warning": self.warning, "origin": self.origin}


def _is_synced(path: Path) -> bool:
    return any(m in str(path).lower() for m in _CLOUD_MARKS)


def default_root() -> Path:
    """Куди покласти простір, якщо його не назвало ЖОДНЕ джерело.

    ⚠ Свідомо не читає середовища: це питання про МАШИНУ (де тут тека
    документів і чи вона не синхронізується), а не про волю людини. Драбина
    джерел живе в `core.workspace.propose()`; тут — лише її останній щабель.
    """
    home = Path.home()
    for candidate in (home / "Documents" / DEFAULT_DIRNAME,
                      home / "Документи" / DEFAULT_DIRNAME,
                      home / DEFAULT_DIRNAME):
        if candidate.parent.is_dir() and not _is_synced(candidate):
            return candidate
    # Усі звичні місця синхронізуються — тоді краще поруч із домівкою, ніж у
    # хмарі: повільний обхід виглядає як зависання, і причину не видно.
    return home / DEFAULT_DIRNAME


def plan(root: str | Path | None = None) -> Plan:
    """Порахувати, що станеться. Нічого не створює."""
    from nyshporka.core.workspace import MARKER, propose

    # 🔴 Драбина джерел — одна на застосунок. Доки майстер рахував шлях сам, він
    # знав ОДНЕ джерело з п'яти: `nysh init` усередині наявного простору
    # пропонував створити новий, а виставлена змінна не діяла зовсім.
    # `propose()` повертає вже перевірений АБСОЛЮТНИЙ шлях — тому відносний
    # аргумент більше не залежить від того, звідки запущено процес.
    target, origin = propose(root, default=default_root())
    exists = (target / MARKER).is_file()
    warning = ""
    if _is_synced(target):
        warning = ("тека синхронізується з хмарою — обхід справ стане мережевим "
                   "і виглядатиме як зависання")
    elif target.exists() and any(target.iterdir()) and not exists:
        warning = "тека не порожня — простір ляже поруч із наявними файлами"
    return Plan(root=target, creating=not exists, warning=warning, origin=origin)


def origin_phrase(origin: str) -> str:
    """Людською: звідки взявся запропонований шлях.

    Тут, а не в `cli.py`: ту саму фразу читатиме екран першого запуску.
    """
    from nyshporka.core.workspace import MARKER

    if origin == "explicit":
        return "вказано вами"
    if origin.startswith("env:"):
        return f"зі змінної {origin.split(':', 1)[1]}"
    if origin == "marker":
        return f"з {MARKER} у поточній теці або вище"
    if origin == "last-used":
        return "простір, відкритий востаннє"
    if origin == "default":
        return "типове місце"
    return origin


def create(root: str | Path | None = None, *, name: str = "",
           preset: str = "") -> Path:
    """Створити простір: тека, маркер, кістяк. Ідемпотентно.

    `preset` — які частини застосунку ввімкнути (`core.sections`). Порожній
    рядок означає «як досі»: у маркер нічого не пишеться, діє дефолт. Так
    простір, створений без питання про пресет, лишається повним.
    """
    import tomllib  # noqa: F401  (перевірка, що stdlib має читач TOML)

    from nyshporka.core import sections as S
    from nyshporka.core.workspace import MARKER, remember, use

    if preset and preset not in S.PRESETS:
        raise ValueError(
            f"невідомий пресет «{preset}». Є: {', '.join(sorted(S.PRESETS))}")

    target = plan(root).root
    target.mkdir(parents=True, exist_ok=True)
    for sub in ("data/raw", "data/derived", "data/pages", "reports", "config"):
        (target / sub).mkdir(parents=True, exist_ok=True)
    marker = target / MARKER
    if not marker.is_file():
        # 🔴 Пресет записується ІМЕНЕМ, а не розгорнутим переліком: тоді секція,
        # додана в майбутній версії, приїде до цього простору сама. Застиглий
        # перелік лишив би людину без неї, і дізнатись про це було б нізвідки.
        chosen = (f"\n# Які частини застосунку ввімкнено (`nysh sections`).\n"
                  f'preset = "{preset}"\n') if preset else ""
        marker.write_text(
            "# Маркер робочого простору Нишпорки.\n"
            "# Він тут не для краси: саме за цим файлом застосунок і всі\n"
            "# команди знаходять ваше дослідження, підіймаючись від поточної\n"
            "# теки вгору. Переносити простір можна разом із ним.\n"
            "[workspace]\n"
            "schema = 1\n"
            f'name = "{name or target.name}"\n'
            f"{chosen}"
            "\n"
            "# Скани, що лежать ПОЗА простором (зовнішній диск, мережева теку):\n"
            "# case_roots = [\"D:/архів\"]\n",
            encoding="utf-8")
    # 🔴 Запам'ятати — інакше наступна КОМАНДА простору не знайде. `use()` діє
    # лише в цьому процесі, а `nysh init` одразу завершується; обидва
    # інсталятори наступним рядком кличуть `nysh doctor`, і той стартує з іншої
    # теки, без змінної та без маркера над собою. Тобто останній крок успішного
    # встановлення показував червоне «робочий простір не знайдено» з порадою
    # виконати `nysh init` — команду, яку щойно виконали.
    #
    # ⚠ Саме тут, а не в `use()`: її кличе кожен запуск із `--workspace` і кожен
    # тест. Писати стан там означало б, що прапорець «на один запуск» мовчки
    # стає липким і перевизначає всі наступні команди.
    remember(use(target))
    return target
