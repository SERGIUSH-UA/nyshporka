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


#: Ключі `install-info.ini` → змінні uv. Однією тичкою «теки Нишпорки» в
#: `uv_python_env()`: кожен виклик uv після встановлення мусить класти туди ж,
#: куди клав інсталятор.
UV_DIR_KEYS = {"python_dir": "UV_PYTHON_INSTALL_DIR", "tool_dir": "UV_TOOL_DIR",
               "bin_dir": "UV_TOOL_BIN_DIR", "cache_dir": "UV_CACHE_DIR"}


def _home_from_prefix() -> Path | None:
    """Тека програми, якщо пакет стоїть у розкладці «одна тека» (з 0.32).

    Інсталятор кладе середовище в `<тека>/.program/tools/nyshporka`, тож
    `sys.prefix.parents[1]` — і є тека програми зі своїм `install-info.ini`.
    Так застосунок знаходить себе без жодної постійної змінної користувача.
    """
    try:
        cand = Path(sys.prefix).resolve().parents[1]
    except (IndexError, OSError):
        return None
    return cand if (cand / INSTALL_INFO).is_file() else None


def install_home() -> Path:
    """Тека встановлення, яку заводить інсталятор."""
    own = _home_from_prefix()
    if own is not None:
        # 🔴 Розкладка «одна тека»: людина обрала теку на D:, і програма лежить
        # у ній. Без цього кроку читач шукав би слід лише в LOCALAPPDATA і
        # `nysh update` ставив би нову версію назад на C: (відеоурок, 16.10.2026).
        return own
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA")
                    or str(Path.home() / "AppData" / "Local"))
        # 🔴 Два кандидати, не один. `windows.ps1` за замовчуванням кладе
        # `install-info.ini` у `%LOCALAPPDATA%\Nyshporka`, а майстер `.exe`
        # передає йому `-Home_ {app}` = `%LOCALAPPDATA%\Programs\Nyshporka`
        # (тека даних навмисно не є текою встановлення — див. `nyshporka.iss`).
        # Читач, який знав лише перший, у користувачів `.exe` не бачив ані
        # `uv=`, ані `preset=` — і `nysh update` вгадував набір.
        for cand in (base / "Programs" / "Nyshporka", base / "Nyshporka"):
            if (cand / "install-info.ini").is_file():
                return cand
        return base / "Nyshporka"
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


#: 🔴 Текст відмови на os error 448 — ДОСЛІВНО той самий, що в
#: `install/windows.ps1` (тест звіряє): людина, якій інсталятор пройшов, а
#: впало `nysh htr install`, має побачити ту саму пораду, а не іншу.
UNTRUSTED_MOUNT_HINT = (
    "Windows не довіряє теці, куди uv ставить Python (os error 448: "
    "перенаправлений AppData чи OneDrive). Поставте Нишпорку наново з текою "
    "інтерпретаторів поза профілем: windows.ps1 -PythonDir D:\\Nyshporka\\python")


def untrusted_mount_hint(output: str) -> str:
    """Порада, якщо вивід uv — це відмова Windows проходити junction (448)."""
    return UNTRUSTED_MOUNT_HINT if "os error 448" in (output or "") else ""


#: Відмови останнього кроку `uv python install` — junction мінорної версії.
#: 🔴 15.10.2026: 448 повторилась і в `{app}\python` (AppData\Local), тобто
#: тека тут ні до чого — Windows не дає робити junction узагалі. Але uv робить
#: його ПІСЛЯ того, як інтерпретатор розпакований і доведений до ладу
#: (`uv-python-commands/src/install.rs`: `ensure_minor_version_link` — після
#: циклу встановлення, відкату немає). Тож тека точної версії
#: (`cpython-3.12.15-windows-x86_64-none`) ціла, і її `python.exe` годиться
#: для `--python` — junction потрібен uv лише для тихих патч-оновлень.
#: Друга фраза — той самий крок під MSIX-віртуалізацією (astral-sh/uv#19622).
LINK_STEP_FAILURES = (
    "Failed to create Python minor version link directory",
    "Missing expected target directory for Python minor version link",
)


def link_step_failed(output: str) -> bool:
    """Чи uv упав саме на junction мінорної версії, а не на завантаженні."""
    return any(s in (output or "") for s in LINK_STEP_FAILURES)


def extracted_python(folder: Path, version: str) -> Path | None:
    """`python.exe` найвищого патча `version` (`3.12`) у теці інтерпретаторів uv.

    Лише справжня тека точної версії: ім'я без патча — це і є той junction
    (або його недоробок), а `+freethreaded` — інший інтерпретатор.
    """
    import re

    pat = re.compile(rf"^cpython-{re.escape(version)}\.(\d+)-windows-[^-]+-none$")
    best: tuple[int, Path] | None = None
    for d in folder.iterdir() if folder.is_dir() else ():
        m = pat.match(d.name)
        exe = d / "python.exe"
        if m and exe.is_file() and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), exe)
    return best[1] if best else None


def _drop_link_leftover(folder: Path, version: str) -> None:
    """Прибрати недоробок junction (`cpython-3.12-…`): лише junction чи порожню теку.

    `os.rmdir` не йде за junction і не знімає теку з вмістом — чуже не зачепить.
    """
    from contextlib import suppress

    for d in folder.glob(f"cpython-{version}-windows-*-none"):
        with suppress(OSError):
            os.rmdir(d)


class PythonInstallFailed(RuntimeError):
    """`uv python install` не дав інтерпретатора, яким можна користуватись."""


def ensure_python(uv: str, version: str, env: dict[str, str]) -> str:
    """Поставити керований Python `version` і повернути значення для `--python`.

    Зазвичай це сама версія (`3.11`). Якщо uv упав на junction мінорної версії
    (448 на Windows), а інтерпретатор уже розпакований і запускається, —
    повний шлях до його `python.exe`: так `uv venv` / `uv tool install` не
    качають його вдруге й не повторюють той самий junction.
    """
    import subprocess

    r = subprocess.run([uv, "python", "install", version], env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", check=False)
    out = (r.stdout or "") + (r.stderr or "")
    if out.strip():
        sys.stderr.write(out if out.endswith("\n") else out + "\n")
    if r.returncode == 0:
        return version
    if sys.platform == "win32" and link_step_failed(out):
        folder = env.get("UV_PYTHON_INSTALL_DIR", "").strip()
        if not folder:
            d = subprocess.run([uv, "python", "dir"], env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", check=False)
            folder = (d.stdout or "").strip()
        exe = extracted_python(Path(folder), version) if folder else None
        if exe and _runs_as(exe, version):
            _drop_link_leftover(Path(folder), version)
            sys.stderr.write(f"Python {version}: uv не зміг зробити junction мінорної "
                             f"версії, беру інтерпретатор напряму: {exe}\n")
            return str(exe)
    raise PythonInstallFailed(untrusted_mount_hint(out)
                              or f"uv python install {version}: код {r.returncode}")


def _runs_as(exe: Path, version: str) -> bool:
    """Інтерпретатор запускається й справді тієї мінорної версії."""
    import subprocess

    try:
        r = subprocess.run([str(exe), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == version


def uv_python_env() -> dict[str, str]:
    """Оточення для КОЖНОГО виклику uv Нишпоркою — та сама тека Python, що в інсталятора.

    🔴🔴 os error 448 (ERROR_UNTRUSTED_MOUNT_POINT, 14.10.2026, французька
    Windows): uv кладе керовані інтерпретатори в `%APPDATA%\\uv\\python`
    (Roaming) і робить там junction на мінорну версію, а Windows відмовляється
    його проходити (перенаправлений AppData / OneDrive; astral-sh/uv#19622,
    #19616, фіксу в uv немає). Інсталятор тепер ставить Python у неромінгову
    теку (`python_dir=` в `install-info.ini`), і ту саму теку мусить бачити
    кожен наступний виклик uv: інакше інсталятор пройде, а `nysh htr install`
    (venv рушіїв на іншій мінорній версії) чи оновлення підуть у Roaming і
    впадуть там само.

    ⚠ Явна передача, а не постійна змінна користувача: та перенаправила б УСІ
    `uv python install` людини в теку Нишпорки, і `nysh uninstall` знісся б
    чужі інтерпретатори разом зі своїми.

    🔴 Крім теки Python — теки середовища застосунку, його команди й кешу uv
    (`tool_dir`, `bin_dir`, `cache_dir`, розкладка «одна тека»). Без них
    інсталятор клав усе на обраний диск, а перше ж `nysh update` чи
    `nysh htr install` (кеш torch — гігабайти) знову пішло б у профіль на C:.
    """
    env = {"UV_PYTHON_INSTALL_BIN": "0", "UV_PYTHON_INSTALL_REGISTRY": "0"}
    info = install_info()
    for key, var in UV_DIR_KEYS.items():
        folder = info.get(key, "").strip()
        if folder:
            env[var] = folder
    return env


#: Ключ у стані користувача: коли востаннє ПИТАЛИ pypi.org.
STATE_CHECKED = "update_checked"


def mark_checked() -> None:
    """Записати, що зараз питали. Пишеться на спробу, а не на успіх.

    ⚠ Саме на спробу: «мережа мовчала» теж означає, що людина вже питала, і
    нагадувати їй наступної хвилини нема чого.
    """
    import time

    from nyshporka.core.workspace import state_set

    state_set(**{STATE_CHECKED: time.time()})


def days_since_check() -> int | None:
    """Скільки днів тому питали; `None` — не питали жодного разу.

    🔴 Третій стан обов'язковий. «Не питали» і «питали, все свіже» — різні
    відповіді, і зводити їх в одну означає показати спокій там, де його ніхто
    не перевіряв. Це та сама вада, що нуль без знаменника, тільки про версію.
    """
    import time

    from nyshporka.core.workspace import state_all

    got = state_all().get(STATE_CHECKED)
    try:
        when = float(got)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, int((time.time() - when) / 86400))


def latest(timeout: float = TIMEOUT) -> Release:
    """Спитати PyPI. Мережа мовчить — це стан «не знаємо», а не поламка."""
    from nyshporka.sources.http import offline

    # Заборона мережі діє й тут: `update.check` проходять тести всіх операцій
    # підряд, і без цього рядка кожен прогін питав справжній pypi.org.
    if offline():
        return Release(installed=__version__,
                       why="мережу вимкнено в цьому середовищі — pypi.org не питали")
    mark_checked()
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


def has_htr() -> bool:
    """Чи читає ця людина рукописи: є середовище рушіїв (або старий слід — torch).

    🔴 Питається стан, а не запис. Слід інсталятора фіксує набір НА МОМЕНТ
    УСТАНОВЛЕННЯ, а частини доставляють потім — і оновлення за старим записом
    зняло б у такої людини розділ «Читання». Помилка мовчазна: застосунок
    оновився, «Читання» просто зникло.

    🔴 Ознака — середовище рушіїв, а не torch поруч із застосунком. До 0.24
    extra `htr` ставив torch і в середовище застосунку, де він у читанні не
    бере участі (читає torch рушіїв, `doctor._torch`), — тобто кожен, хто
    читав, тримав ДВА torch по 2.5–4 ГБ. Тепер extra порожній, а torch у
    застосунку лишається ознакою лише для тих, у кого він ще стоїть зі старої
    установки.
    """
    from importlib.util import find_spec

    try:
        from nyshporka.htr.env import venv_python
        from nyshporka.setup.doctor import engine_venv

        if venv_python(engine_venv()).is_file():
            return True
    except Exception:
        pass                    # простору немає — питаємо старий слід
    try:
        return find_spec("torch") is not None
    except (ImportError, ValueError):
        return False


def preset_now(recorded: str = "") -> str:
    """Набір, який треба поставити: спершу стан, потім запис, потім типовий.

    ⚠ Порядок саме такий. Запис може застаріти в один бік (доставили рушії) і
    не може в інший: чого немає, того `find_spec` не побачить.

    🔴 Стан лише ПІДНІМАЄ запис, а не підміняє його. Доти рушії на місці
    завжди давали `researcher`, і людина з набором `lab` оновлювалась без
    extra `train` — SSH-клієнт трену зникав мовчки, а «Лабораторія» падала
    вже на першому виносі на свій сервер.
    """
    if has_htr():
        return recorded if recorded in ("amateur", "researcher", "lab") else "researcher"
    return recorded or "catalog"


def has_rent() -> bool:
    """Чи стоїть плагін оренди (extra `rent`, пакет `gpuhire`) у цьому середовищі.

    🔴 Оренди немає в жодному наборі, тож без цієї ознаки оновлення її не
    бачило: `pip install --upgrade` лишав старий плагін, а `uv tool install
    --force` перезбирав середовище без нього — `nysh cloud go` після
    оновлення зникав.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        distribution("gpuhire")
    except PackageNotFoundError:
        return False
    return True


def tool_env() -> bool:
    """Чи запущено з середовища інструмента uv (`uv tool install`, `.exe`, скрипти).

    Ознака — `uv-receipt.toml` у корені середовища: його кладе сам uv і лише
    туди. Слід інсталятора для цього не годиться — його немає в того, хто ставив
    `uv tool install` руками, і він лишається від установки, поверх якої вже
    стоїть звичайний `pip`-venv.
    """
    return (Path(sys.prefix) / "uv-receipt.toml").is_file()


def runs_in_place() -> bool:
    """Чи може `nysh update` виконати оновлення сам, не лише назвати команду.

    🔴 На Windows — ні, і перевірено живим прогоном 12.09.2026: `uv tool
    install --force`, запущений із `nysh update`, переставляє пакет, а тоді
    падає на копіюванні `nysh.exe` («файл зайнятий іншим процесом», код 2) —
    бо саме з цього файла й запущено команду. Людина бачила «оновлення не
    завершилось, закрийте `nysh serve`», хоча застосунок не був запущений, а
    пакет уже стояв новий. На Linux і macOS файл працюючого процесу
    замінюється, і там оновлення на місці працює.

    ⚠ `pip`-середовище не оновлюється тут ніде: `pip install --upgrade` у чужий
    venv — рішення людини, а не застосунку, і на Windows воно впирається в той
    самий зайнятий `nysh.exe`.
    """
    return tool_env() and sys.platform != "win32"


def command(preset: str = "") -> list[str]:
    """Команда, якою застосунок оновлюється на цій машині.

    🔴 Набір не вгадується: `researcher` тягне рушії читання (~2.5 ГБ),
    `catalog` — ні, і підставити не той означає або змусити платити
    гігабайтами того, хто прийшов дивитись каталог, або мовчки зняти рушії в
    того, хто ними читає.

    🔴 І спосіб установки не вгадується. Доти команда була ЗАВЖДИ `uv tool
    install`, тож у того, хто ставив `pip install` у свій venv, `nysh update`
    ставив ДРУГУ копію інструментом uv поруч, а його середовище лишалось старим
    — і `nysh` у ньому далі казав «є новіша». Тепер середовище uv оновлюється
    uv, а решта — тим pip, яким її ставили.

    ⚠ `--force` перезбирає СЕРЕДОВИЩЕ ІНСТРУМЕНТА, і це не зачіпає ні простір,
    ні рушії (вони в окремому venv поруч із простором), ні моделі
    (`<простір>/data/spotter/models`), ні паки довідників (`user_data_dir`).
    Але пакети, дописані туди руками через `uv tool install --with`, воно
    змиває — їх доведеться назвати знову.
    """
    from nyshporka.core.sections import install_target

    info = install_info()
    got = preset or preset_now(info.get("preset", ""))
    spec = install_target(got)
    if has_rent():
        spec = (spec[:-1] + ",rent]") if spec.endswith("]") else spec + "[rent]"
    if not tool_env():
        return [sys.executable, "-m", "pip", "install", "--upgrade", spec]
    uv = info.get("uv") or "uv"
    return [uv, "tool", "install", "--python", "3.12", "--force", spec]


def command_env() -> dict[str, str]:
    """Оточення для `command()`: без теки інтерпретаторів `uv tool install
    --force` поставив би Python у Roaming і впав там на 448."""
    return {**os.environ, **uv_python_env()}


def how_to_update(preset: str = "") -> str:
    """Рядок для людини — той самий, що виконає `nysh update`.

    🔴 Аргументи беруться в лапки. Перший із них — шлях до `uv` зі сліду
    інсталятора, а на Windows у ньому буває пробіл — тека профілю з іменем
    і прізвищем. Саме цей рядок людина копіює в термінал. Специфікація теж:
    `nyshporka[app,archives,htr]` у zsh без лапок дає «no matches found».
    Та сама вада, що й у підказці `nysh cases bind`, і лікується вона тим самим.

    🔴 На Windows — лапки PowerShell, а не POSIX. Туди саме й веде документація
    («Пуск → PowerShell»), а POSIX-форма там не виконується взагалі: `\\`
    подвоювався (`"C:\\\\Users\\\\…\\\\uv.exe"`), а програма в лапках без
    оператора `&` — це рядок, не команда («Unexpected token 'tool'»). Тобто в
    КОЖНОГО, хто ставив `.exe` (шлях до uv зі сліду завжди з `\\`), рядок у
    кнопці «Перевірити оновлення» не запускався. Знайдено живим прогоном.
    """
    from nyshporka.htr.view import shell_arg

    parts = command(preset)
    # Рядок, який людина копіює, мусить нести ті самі теки, що й `nysh update`
    # (`command_env`) — інакше повертається 448 або нова версія лягає на C:.
    env = uv_python_env() if parts[1:2] == ["tool"] else {}
    dirs = [(v, env[v]) for v in UV_DIR_KEYS.values() if env.get(v)]
    if sys.platform == "win32":
        pre = "".join(f"$env:{v}={_ps_quote(f)}; " for v, f in dirs)
        return pre + _powershell_line(parts)
    line = " ".join(shell_arg(x) for x in parts)
    pre = "".join(f"{v}={shell_arg(f)} " for v, f in dirs)
    return pre + line


def _ps_quote(x: str) -> str:
    """Одинарні лапки PowerShell: апостроф у шляху подвоюється."""
    return "'" + x.replace("'", "''") + "'"


def _powershell_line(parts: list[str]) -> str:
    """Рядок, який PowerShell виконає як набрано.

    ⚠ Одинарні лапки, а не подвійні: у подвійних PowerShell розкриває `$` і
    зворотну лапку, а апостроф в імені профілю («Ім'я») подвоюється за правилом
    самої мови. Кома без лапок робить з аргументу масив — тому
    `nyshporka[app,archives]` береться в лапки завжди.
    """
    def quote(x: str) -> str:
        if x and not any(c in x for c in " \t'\"`$,;()[]{}&|<>@#"):
            return x
        return "'" + x.replace("'", "''") + "'"

    line = " ".join(quote(x) for x in parts)
    return f"& {line}" if parts and quote(parts[0]) != parts[0] else line
