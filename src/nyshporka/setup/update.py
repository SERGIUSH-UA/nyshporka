"""⬆️ Оновлення застосунку: чи є новіша версія і чим її поставити.

🔴 Досі шляху оновлення не було ЗОВСІМ. Ні команди, ні перевірки версії, ні
згадки в `doctor` — версія показувалась лише в банері старту в консолі. Людина,
що поставила застосунок `.exe`-майстром, дізнатись про нову збірку не могла
нізвідки: вада, полагоджена вчора, лишалась у неї назавжди, і питання про неї
йшло у спільноту (звіт 29.08.2026).

🔴 **Фонової перевірки немає й не буде.** `PRIVACY.md` обіцяє «фонової
активності в мережі немає», і обіцянка ця дорожча за зручність: запит до PyPI
несе IP-адресу, а людина його не просила. Тому перевірка — рівно на дію:
команда або кнопка. Перевірка, зроблена сама, тут була б порушенням політики,
а не поліпшенням.

⚠ Оновлення саме себе на ходу не робиться. `uv tool install --force` міняє те
саме середовище, з якого зараз запущено `nysh`, і на Windows файл працюючого
процесу заблокований. Тому застосунок каже, ЩО набрати й чому спершу треба
його закрити, — це чесніше за кнопку, яка мовчки не спрацює.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from nyshporka import __version__

#: Звідки береться сам пакет. Той самий хост, що вже названий у `PRIVACY.md`.
PYPI_JSON = "https://pypi.org/pypi/nyshporka/json"

#: 🔴 Стеля очікування МЕНША за звичайну. Запит іде синхронно з обробника
#: демона, а той крутиться в циклі подій: доки він чекає, стоїть усе — SSE,
#: прогрес активного читання, черга робіт. Шість секунд на мертвій мережі
#: означали б шість секунд замороженого застосунку, тож беремо стільки, щоб
#: живий сервер устиг відповісти, а мертвий не тримав нікого.
TIMEOUT = 3.0

#: Слід, який лишає інсталятор: де лежить `uv` і яким набором ставили.
#: Без нього оновлення довелось би вгадувати — а вгаданий набір або тягне
#: 2.5 ГБ рушіїв тому, хто їх не ставив, або мовчки їх знімає в того, хто ставив.
INSTALL_INFO = "install-info.ini"


class UpdateError(RuntimeError):
    """Оновитись не вийшло — з поясненням, що саме завадило."""


@dataclass(frozen=True)
class Release:
    """Що стоїть і що є. `latest` порожній — значить не питали або не дійшли."""

    installed: str
    latest: str = ""
    why: str = ""

    @property
    def newer(self) -> bool:
        if not self.latest:
            return False
        got, mine = _cmp_key(self.latest, self.installed)
        return got > mine

    @property
    def known(self) -> bool:
        """🔴 Третій стан. «Не питали» і «свіжа» — різні відповіді, і зводити
        їх в одну означає показати спокій там, де його ніхто не перевіряв."""
        return bool(self.latest)


def _key(v: str) -> tuple[int, ...]:
    """Версія як кортеж чисел для порівняння.

    🔴 Беруться ПРОВІДНІ цифри частини, а не всі підряд: «0.7.0rc1» інакше дає
    (0, 7, 1), тобто передрелізна збірка рахувалась би новішою за сам 0.7.0 —
    і застосунок кликав би оновлюватись на те, що вже стоїть.

    ⚠ Хвости `post`/`dev` при цьому зводяться до нуля, тобто «0.6.3.post1»
    вважається рівним «0.6.3». Це свідомо: помилка в цей бік мовчить, а в
    протилежний — щодня радить оновитись на ту саму версію.
    """
    out: list[int] = []
    for part in str(v or "").split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _cmp_key(a: str, b: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Дві версії, доповнені нулями до однакової довжини.

    🔴 Без вирівнювання «1.0» і «1.0.0» — різні кортежі, і (1, 0) < (1, 0, 0):
    та сама версія читалась як новіша, тобто застосунок нескінченно радив би
    оновитись на себе самого.
    """
    ka, kb = _key(a), _key(b)
    n = max(len(ka), len(kb))
    return ka + (0,) * (n - len(ka)), kb + (0,) * (n - len(kb))


def install_home() -> Path:
    """Тека встановлення, яку заводить інсталятор."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Nyshporka"
    # ⚠ `XDG_DATA_HOME` читається так само, як його пише `install/unix.sh`.
    # Без цього на машині зі своїм XDG (NixOS, контейнер) слід інсталятора
    # лежав би там, куди читач не дивиться, — і людині з набором `catalog`
    # запропонували б переставитись із рушіями на 2.5 ГБ.
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "nyshporka"


def install_info() -> dict[str, str]:
    """Що лишив інсталятор: шлях до `uv`, до `nysh`, набір. Немає — порожньо.

    ⚠ Файл пишеться в UTF-16LE (його читає й `.exe`-майстер через
    `GetPrivateProfileString`, а той розуміє Unicode лише за BOM UTF-16).
    Кодування вгадується, бо `unix.sh` пише той самий файл звичайним UTF-8.
    """
    path = install_home() / INSTALL_INFO
    # ⚠ `utf-8-sig` перед голим `utf-8`: файл із BOM під кодеком `utf-16`
    # НЕ падає — він просто декодується в сміття без жодного «=», тож розбір
    # мовчки віддавав порожньо або приклеював BOM до першого ключа. А перший
    # ключ там — шлях до `uv`.
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = path.read_text(encoding=enc)
        except (OSError, UnicodeError):
            continue
        out: dict[str, str] = {}
        for line in text.splitlines():
            key, sep, val = line.partition("=")
            if sep and not key.strip().startswith(("[", "#", ";")):
                out[key.strip()] = val.strip()
        if out:
            return out
    return {}


def latest(timeout: float = TIMEOUT) -> Release:
    """Спитати PyPI. Мережа мовчить — це стан «не знаємо», а не поламка."""
    req = Request(PYPI_JSON, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        got = str((body.get("info") or {}).get("version") or "")
    except Exception as exc:
        return Release(installed=__version__,
                       why=f"до pypi.org не дійшли ({type(exc).__name__})")
    if not got:
        return Release(installed=__version__, why="pypi.org не назвав версії")
    return Release(installed=__version__, latest=got)


def command(preset: str = "") -> list[str]:
    """Команда, якою застосунок оновлюється на цій машині.

    🔴 Набір береться зі сліду інсталятора, а не вгадується: `researcher` тягне
    рушії читання (~2.5 ГБ), `catalog` — ні, і підставити не той означає або
    змусити платити гігабайтами того, хто прийшов дивитись каталог, або мовчки
    зняти рушії в того, хто ними читає.
    """
    info = install_info()
    uv = info.get("uv") or "uv"
    got = preset or info.get("preset") or "researcher"
    extras = "app,archives" if got == "catalog" else "app,archives,htr"
    return [uv, "tool", "install", "--python", "3.12", "--force",
            f"nyshporka[{extras}]"]


def how_to_update(preset: str = "") -> str:
    """Рядок для людини — той самий, що виконає `nysh update`.

    🔴 Аргументи беруться в лапки. Перший із них — шлях до `uv` зі сліду
    інсталятора, а на Windows у ньому буває пробіл — тека профілю з іменем
    і прізвищем. Саме цей рядок людина копіює в термінал. Специфікація теж:
    `nyshporka[app,archives,htr]` у zsh без лапок дає «no matches found».
    Та сама вада, що й у підказці `nysh cases bind`, і лікується вона тим самим.
    """
    from nyshporka.htr.view import shell_arg

    return " ".join(shell_arg(x) for x in command(preset))
