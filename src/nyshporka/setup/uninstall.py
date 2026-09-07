"""🧹 Зняти застосунок: рівно те, що поставили, і нічого з дослідження.

🔴 Досі шляху зняття на Linux і macOS не було ЗОВСІМ. На Windows це робить
майстер (`install/nyshporka.iss`), а на Unix людина лишалась із командою, якої
ніхто не пропонував прибрати: тестувальник (07.09.2026) мусив просити агента
знести застосунок «повністю, разом з усім, що воно притягло». Установлення,
яке не знімається, — це половина встановлення, і саме та половина, через яку
пробувати застосунок страшно.

🔴🔴 **Робочий простір не чіпається ніде й ніколи.** Там скани, прочитане й
роками зібране дослідження, і жоден прапорець цієї команди його не видаляє. Те
саме рішення вже записане в `install/nyshporka.iss` — тут воно продубльоване не
для симетрії, а тому, що ціна помилки однакова. Виняток рівно один і названий
поіменно: середовище рушіїв (`.venv_kraken`) лежить усередині простору, і його
знімає `--engines`. Приймач — `test_uninstall_never_touches_the_research`.

⚠ Що знімається типово, а що лише поіменним прапорцем, вирішує **чи можна це
поставити наново одним рядком**. Пакет — можна. Рушії (2.5 ГБ), моделі,
довідники — теж можна, але це години завантаження, і людині, яка знімає
застосунок, щоб поставити свіжий, вони потрібні на місці.
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Слід, який лишає інсталятор: по рядку `<вид> <шлях>` на кожну зміну.
#: Пишуть його обидва інсталятори (`install/unix.sh`, `install/windows.ps1`).
TRACE = "install-trace.txt"

#: Резервна копія профілю оболонки перед тим, як прибрати з нього рядок.
#: 🔴 Правка чужого файла профілю — рівно те, за що прийшла скарга, з якої
#: почалась ця команда. Тому вона робиться лише за явним «так», лише над
#: рядком, який назвав слід інсталятора, і завжди з копією поруч.
BACKUP_SUFFIX = ".nysh.bak"

#: Що в теці застосунку поклав саме інсталятор — і тільки це звідти знімається.
#: 🔴 Перелік поіменний, бо на Windows та сама тека є `user_data_dir`
#: застосунку: там же лежать паки довідників і кеш ваг. Див. коментар у `plan`.
HOME_OWNED = ("uv", "install-info.ini", TRACE, "install.log",
              "install-error.txt")


@dataclass
class Item:
    """Одна річ, яку можна зняти."""

    kind: str                 # tool | dir | file | shellpath | winpath
    what: str                 # як це назвати людині
    path: Path | None = None
    #: Прапорець, яким це вмикається. Порожньо — знімається типово.
    flag: str = ""
    #: Байтів на диску; 0 — не рахували або не файл.
    size: int = 0
    note: str = ""


@dataclass
class Plan:
    """Що знімемо, що лишиться і чому."""

    items: list[Item] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    #: Простір досліджень — щоб команда могла показати, чого НЕ чіпає.
    workspace: Path | None = None


# ── де що лежить ─────────────────────────────────────────────────────────────
def trace_path() -> Path:
    """Файл сліду. Тека — та сама, куди його клав інсталятор."""
    from nyshporka.setup.update import install_home

    return install_home() / TRACE


def traced() -> list[tuple[str, str]]:
    """Слід інсталятора як пари «вид, шлях». Немає файла — порожньо.

    ⚠ Відсутність сліду не є помилкою: застосунок могли поставити `pip install`
    або `uv tool install` руками, і тоді знімати треба лише пакет. Але тоді ж
    не можна й вгадувати: тека команд налаштовується (`UV_TOOL_BIN_DIR`,
    `XDG_BIN_HOME`), і здогад про `~/.local/bin` збігається лише з типовим
    випадком. Тому чого немає в сліді — того ця команда не чіпає.
    """
    try:
        text = trace_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        kind, sep, rest = line.strip().partition(" ")
        if sep and rest:
            out.append((kind, rest))
    return out


def _size_of(path: Path) -> int:
    """Скільки місця займає. Тека рахується покаталогово, помилки — не важать."""
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0
    return 0


def human(size: int) -> str:
    """Байти в те, що читається оком."""
    step = 1024.0
    val = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if val < step or unit == "ГБ":
            return f"{val:.0f} {unit}" if unit == "Б" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} ГБ"


def _workspace_root() -> Path | None:
    """Корінь простору — щоб ЗАХИСТИТИ його, а не щоб щось у ньому робити."""
    try:
        from nyshporka.core.workspace import workspace

        return workspace().root.resolve()
    except Exception:
        # ⚠ Простору може не бути взагалі (знімають після невдалого
        # встановлення). Це не привід відмовитись знімати пакет.
        return None


def _engine_venv() -> Path | None:
    try:
        from nyshporka.setup.doctor import engine_venv

        got = engine_venv()
        return got if got.is_dir() else None
    except Exception:
        return None


# ── план ─────────────────────────────────────────────────────────────────────
def plan(*, engines: bool = False, models: bool = False, catalog: bool = False,
         skills: bool = False, state: bool = False) -> Plan:
    """Що саме знімемо за цих прапорців. Нічого не робить — лише рахує."""
    from nyshporka.setup.update import install_home, install_info

    p = Plan(workspace=_workspace_root())
    info = install_info()
    uv = info.get("uv", "")

    # 1. сам пакет — те, заради чого команду й кличуть
    p.items.append(Item(
        kind="tool", what="пакет nyshporka (середовище інструмента uv)",
        note=f"{uv or 'uv'} tool uninstall nyshporka"))

    # 2. слід інсталятора: тека застосунку разом із власним uv, якщо він там
    home = install_home()
    for kind, raw in traced():
        path = Path(raw)
        if kind == "shell":
            p.items.append(Item(kind="shellpath", what=f"рядок PATH у {path.name}",
                                path=path))
        elif kind == "path":
            p.items.append(Item(kind="winpath",
                                what="допис у PATH користувача", path=path))
        elif kind == "bin":
            # Команду знімає сам uv разом із середовищем інструмента; окремо
            # видаляти її означало б перегнати uv і лишити його облік кривим.
            continue
        elif path.resolve() == home.resolve() or home.resolve() in path.resolve().parents:
            continue          # усе, що всередині теки застосунку, знімемо нижче
        else:
            p.items.append(Item(kind="dir" if path.is_dir() else "file",
                                what=str(path), path=path, size=_size_of(path)))
    if home.exists():
        if _by_wizard(home):
            # 🔴 Установлення майстром знімає САМ майстер: він тримає запис у
            # «Програмах і засобах», і тека, знесена повз нього, лишає в
            # системі мертвий рядок із деінсталятором, якого вже немає.
            p.kept.append(f"тека застосунку {home} — знімається в «Програми і "
                          f"засоби» → Нишпорка")
        else:
            # 🔴🔴 Тека застосунку знімається ПОІМЕННО, а не цілком. На Windows
            # `install_home()` і `user_data_dir("Nyshporka")` — це ОДНА Й ТА
            # САМА тека `%LOCALAPPDATA%\\Nyshporka`, тож `rmtree` над нею змив
            # би паки довідників і ваги моделей — рівно те, що на два рядки
            # нижче обіцяно лишити. Помилка мовчазна: команда сказала б
            # «лишається 170 МБ» і знесла їх тим самим прогоном.
            for name in HOME_OWNED:
                owned = home / name
                if not owned.exists():
                    continue
                p.items.append(Item(
                    kind="dir" if owned.is_dir() else "file",
                    what=f"{owned}", path=owned, size=_size_of(owned)))
            # Порожню теку прибираємо, непорожню лишаємо: у ній чужі дані.
            p.items.append(Item(kind="prune", what=f"тека застосунку {home}, "
                                                   f"якщо в ній нічого не лишилось",
                                path=home))

    # 3. те, що знімається лише поіменно
    venv = _engine_venv()
    if venv is not None:
        item = Item(kind="dir", what=f"середовище рушіїв {venv}", path=venv,
                    flag="--engines", size=_size_of(venv))
        if engines:
            p.items.append(item)
        else:
            p.kept.append(f"рушії читання ({human(item.size)}) — {venv} · --engines")

    for on, flag, what, getter in (
        (models, "--models", "ваги моделей письма", _models_dir),
        (catalog, "--catalog", "паки довідників", _catalog_dir),
        (state, "--state", "стан застосунку", _state_file),
    ):
        got = getter()
        if got is None or not got.exists():
            continue
        size = _size_of(got)
        if on:
            p.items.append(Item(kind="dir" if got.is_dir() else "file",
                                what=f"{what} {got}", path=got,
                                flag=flag, size=size))
        else:
            p.kept.append(f"{what} ({human(size)}) — {got} · {flag}")

    for dest, version in _skill_dirs():
        if skills:
            p.items.append(Item(kind="skills", what=f"скіли агента в {dest}",
                                path=dest, flag="--skills"))
        else:
            p.kept.append(f"скіли агента (версія {version}) — {dest} · --skills")

    # 4. те, що не знімається ніколи, і про що треба сказати вголос
    if p.workspace is not None:
        p.kept.append(f"🔴 простір досліджень — {p.workspace} (не знімається ніколи)")
    p.kept.append("керовані інтерпретатори uv — `uv python uninstall 3.12`")
    return p


def _by_wizard(home: Path) -> bool:
    """Чи це встановлення майстром `.exe`.

    ⚠ Ознака — тека `Programs`, у яку кладе Inno Setup (`{autopf}`); саме її
    шукає `install_home()` першою. Скрипт, запущений руками, кладе поруч —
    просто «Nyshporka» в `%LOCALAPPDATA%`, — і його теку знімати нам можна.
    """
    return sys.platform == "win32" and home.parent.name.lower() == "programs"


def _models_dir() -> Path | None:
    try:
        from nyshporka.setup.packs import target_dir

        return target_dir("model")
    except Exception:
        return None


def _catalog_dir() -> Path | None:
    try:
        from nyshporka.catalog.store import catalog_dir

        return catalog_dir()
    except Exception:
        return None


def _state_file() -> Path | None:
    """Саме ФАЙЛ стану, а не його тека.

    🔴 `user_state_dir("Nyshporka")` на Windows збігається з текою даних
    застосунку, тож `--state` над текою зніс би паки довідників і кеш ваг —
    те, що людина цим прапорцем не просила. Стан — це один `state.json`.
    """
    try:
        from nyshporka.core.workspace import _state_path

        return _state_path()
    except Exception:
        return None


def _skill_dirs() -> list[tuple[Path, str]]:
    try:
        from nyshporka import skills as S

        return S.installed()
    except Exception:
        return []


# ── запобіжник ───────────────────────────────────────────────────────────────
class Forbidden(RuntimeError):
    """Спроба зняти те, що знімати не можна."""


def guard(path: Path, workspace: Path | None, engine: Path | None) -> None:
    """🔴🔴 Ніщо всередині простору не видаляється, крім названого рушійного venv.

    Помилка тут коштує дослідження, зібраного роками, і виправити її нічим.
    Тому перевірка стоїть не в команді, а тут — на єдиному шляху до видалення,
    і кожен виклик `_remove` проходить крізь неї.
    """
    if workspace is None:
        return
    try:
        target = path.resolve()
    except OSError:
        raise Forbidden(f"не вдалося перевірити шлях {path}") from None
    if target == workspace:
        raise Forbidden(f"простір досліджень не знімається: {workspace}")
    if workspace in target.parents:
        if engine is not None and target == engine.resolve():
            return
        raise Forbidden(f"це всередині простору досліджень: {target}")


# ── виконання ────────────────────────────────────────────────────────────────
def remove(p: Plan, *, dry: bool = True) -> list[str]:
    """Зняти заплановане. `dry` — лише сказати, що зробили б.

    Повертає рядки звіту; пакет знімається ОСТАННІМ, бо з нього ж і запущено
    цю команду.
    """
    out: list[str] = []
    engine = _engine_venv()
    tool: Item | None = None
    # ⚠ Порядок не косметичний. `prune` прибирає теку застосунку лише порожню,
    # тож він мусить іти ПІСЛЯ всього, що з неї виносять (на Windows це та сама
    # тека, де лежать довідники й ваги). А пакет — останнім: із нього ж і
    # запущено цю команду.
    prune: list[Item] = []
    for item in p.items:
        if item.kind == "tool":
            tool = item
        elif item.kind == "prune":
            prune.append(item)
        else:
            out.extend(_apply(item, p, engine, dry=dry))
    for item in prune:
        out.extend(_apply(item, p, engine, dry=dry))
    if tool is not None:
        out.extend(_drop_tool(tool, dry=dry))
    return out


def _apply(item: Item, p: Plan, engine: Path | None, *, dry: bool) -> list[str]:
    if item.path is None:
        return []
    if item.kind == "shellpath":
        return _drop_shell_line(item.path, dry=dry)
    if item.kind == "winpath":
        return _drop_windows_path(item.path, dry=dry)
    if item.kind == "skills":
        return _drop_skills(item.path, dry=dry)
    guard(item.path, p.workspace, engine)
    if item.kind == "prune":
        # Порожню — прибрати, непорожню — лишити мовчки: у ній чужі дані.
        if dry:
            return [f"прибрали б {item.path}, якщо вона спорожніє"]
        try:
            item.path.rmdir()
        except OSError:
            return []
        return [f"знято: {item.path}"]
    if not item.path.exists():
        return []
    if dry:
        return [f"зняли б: {item.what}"]
    try:
        if item.path.is_dir():
            shutil.rmtree(item.path)
        else:
            item.path.unlink()
    except OSError as exc:
        return [f"⚠ не вдалося зняти {item.path}: {exc}"]
    return [f"знято: {item.what}"]


def _drop_tool(item: Item, *, dry: bool) -> list[str]:
    """`uv tool uninstall nyshporka` — тим uv, який назвав слід інсталятора."""
    import subprocess

    from nyshporka.setup.update import install_info

    uv = install_info().get("uv") or "uv"
    cmd = [uv, "tool", "uninstall", "nyshporka"]
    if dry:
        return [f"зняли б: {item.what}  ({' '.join(cmd)})"]
    try:
        rc = subprocess.call(cmd)
    except OSError as exc:
        return [f"⚠ не вдалося запустити uv ({exc}) — зніміть руками: "
                f"{' '.join(cmd)}"]
    if rc != 0:
        # ⚠ Найчастіша причина на Windows — файл працюючого процесу
        # заблокований. Та сама межа, що й в оновленні (`setup/update`).
        return [f"⚠ uv повернув {rc}. Якщо застосунок запущено — закрийте його "
                f"й повторіть: {' '.join(cmd)}"]
    return [f"знято: {item.what}"]


def _drop_shell_line(rc_file: Path, *, dry: bool) -> list[str]:
    """Прибрати з профілю рядок, який дописав `uv tool update-shell`.

    🔴 Знімаються ЛИШЕ рядки, що правлять PATH і згадують теку команд uv, плюс
    коментар-маркер `# uv` безпосередньо над ними. Все інше в чужому файлі
    лишається як було, а сам файл спершу копіюється поруч: правка профілю — це
    рівно те, за що прийшла скарга, з якої почалась ця команда.
    """
    try:
        text = rc_file.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines(keepends=True)
    keep: list[str] = []
    dropped: list[str] = []
    for line in lines:
        bare = line.strip()
        ours = (
            (".local/bin" in bare or "uv/tools" in bare or "uv tool" in bare)
            and ("PATH" in bare or bare.startswith("fish_add_path"))
        )
        if ours:
            # Маркер `# uv` над рядком — теж наш; інакше в профілі лишиться
            # коментар без того, що він коментує.
            if keep and keep[-1].strip() in ("# uv", "#uv"):
                dropped.append(keep.pop())
            dropped.append(line)
            continue
        keep.append(line)
    if not dropped:
        return []
    shown = ", ".join(repr(d.strip()) for d in dropped)
    if dry:
        return [f"прибрали б із {rc_file}: {shown}"]
    try:
        rc_file.with_suffix(rc_file.suffix + BACKUP_SUFFIX).write_text(
            text, encoding="utf-8")
        rc_file.write_text("".join(keep), encoding="utf-8")
    except OSError as exc:
        return [f"⚠ не вдалося виправити {rc_file}: {exc}"]
    return [f"прибрано з {rc_file}: {shown}",
            f"  копія попереднього: {rc_file.name}{BACKUP_SUFFIX}"]


def _drop_windows_path(bin_dir: Path, *, dry: bool) -> list[str]:
    """Прибрати теку команд зі змінної PATH користувача (`HKCU\\Environment`)."""
    if sys.platform != "win32":
        return []
    import winreg

    want = str(bin_dir).rstrip("\\")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            value, vtype = winreg.QueryValueEx(key, "PATH")
            parts = [p for p in str(value).split(";") if p]
            left = [p for p in parts if p.rstrip("\\").lower() != want.lower()]
            if len(left) == len(parts):
                return []
            if dry:
                return [f"прибрали б із PATH користувача: {want}"]
            winreg.SetValueEx(key, "PATH", 0, vtype, ";".join(left))
    except OSError as exc:
        return [f"⚠ не вдалося виправити PATH користувача: {exc}"]
    return [f"прибрано з PATH користувача: {want}",
            "  нові вікна побачать зміну; відкриті — ні"]


def _drop_skills(dest: Path, *, dry: bool) -> list[str]:
    """Зняти скіли, які клали МИ, — за обліком і за збігом вмісту.

    ⚠ Правлений руками скіл лишається на місці: облік тримає sha256 кожного
    файла саме для того, щоб чужу роботу не змило (`skills.sync`).
    """
    from nyshporka import skills as S

    ledger = dest / S.LEDGER
    try:
        import json

        files = json.loads(ledger.read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError):
        return []
    gone, kept = 0, 0
    for rel, want in files.items():
        path = dest / rel
        if not path.is_file():
            continue
        if S.sha256(path) != want:
            kept += 1
            continue
        gone += 1
        if not dry:
            try:
                path.unlink()
            except OSError:
                kept += 1
    if dry:
        note = f"зняли б {gone} файлів скілів у {dest}"
        return [note + (f"; {kept} правлених руками лишили б" if kept else "")]
    # Порожні теки прибираємо знизу вгору; непорожню лишає сам `rmdir` — там
    # або правлений руками скіл, або чуже, що ми туди не клали.
    for folder in sorted((d for d in dest.rglob("*") if d.is_dir()),
                         key=lambda d: len(d.parts), reverse=True):
        with contextlib.suppress(OSError):
            folder.rmdir()
    with contextlib.suppress(OSError):
        ledger.unlink()
    return [f"знято {gone} файлів скілів у {dest}"
            + (f"; {kept} правлених руками лишили" if kept else "")]


def uv_python_hint() -> str:
    """Чим зняти керовані інтерпретатори, якщо вони більше не потрібні."""
    from nyshporka.setup.update import install_info

    uv = install_info().get("uv") or "uv"
    return f"{uv} python uninstall 3.12"


__all__ = ["TRACE", "Forbidden", "Item", "Plan", "guard", "human", "plan",
           "remove", "trace_path", "traced", "uv_python_hint"]
