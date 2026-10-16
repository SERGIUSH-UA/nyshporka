"""📦 Переїзд уже поставленої Нишпорки в одну теку — `nysh relocate <тека>`.

🔴 Навіщо. До 0.32 інсталятор клав простір у «Документи», а середовище
застосунку й кеш uv — у профіль на C:, і вибрати інше місце не давав. Людина,
у якої C: маленький, отримувала збої посеред встановлення чи прогону
(відеоурок, 16.10.2026). Нова установка вже питає теку; ця команда переводить
стару на ту саму розкладку:

    <тека>\\                простір дослідження
    <тека>\\.program\\      uv, python, tools, bin, cache, data, install-info.ini

Два кроки, і це навмисно:

1. `nysh relocate <тека>` — КОПІЮЄ простір і дані з покаталожною звіркою кожного
   файла (шлях + розмір), ставить програму наново в `<тека>\\.program`,
   перевішує ярлики й «останній простір». Нічого старого не видаляє.
2. `nysh relocate --finish` — запускається вже НОВОЮ програмою (на Windows
   середовище, з якого ти запущений, видалити не можна), ще раз звіряє копію
   й лише після «так» людини прибирає старе.

🔴 Середовище рушіїв (venv у просторі) НЕ копіюється: venv не переноситься, у ньому
абсолютні шляхи. Його збирає наново `nysh htr install` — з кешем uv старого
місця, тож гігабайти torch удруге не качаються.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

def _skip_top() -> tuple[str, ...]:
    """Що в корені простору не копіюється: venv рушіїв (збирається наново) і замок.

    Імена venv — з `doctor`, щоб шлях до рушіїв рахувався в одному місці."""
    from nyshporka.core.lock import LOCK_NAME
    from nyshporka.setup.doctor import _ENGINE_VENV_NAMES

    return (*_ENGINE_VENV_NAMES, LOCK_NAME)


SKIP_TOP = _skip_top()

#: Запис про переїзд у новій теці програми — по ньому працює `--finish`.
RECORD = "relocated-from.json"

#: Скільки місця лишити понад те, що копіюємо: рушії, кеш uv, перші справи.
SPARE = 5 * 1024 ** 3


class RelocateError(RuntimeError):
    """Переїзд неможливий або звірка не зійшлась — нічого старого не чіпали."""


@dataclass
class Plan:
    """Що й куди переїде. Рахується без жодного запису."""

    workspace_from: Path
    workspace_to: Path
    home_from: Path
    home_to: Path
    data_from: Path
    data_to: Path
    #: Простір уже лежить там, куди просять, — переїжджає лише програма.
    workspace_stays: bool = False
    #: Чи був venv рушіїв — тоді його зберемо наново.
    engines: bool = False
    workspace_bytes: int = 0
    data_bytes: int = 0
    free_bytes: int = -1
    problems: list[str] = field(default_factory=list)

    @property
    def need_bytes(self) -> int:
        return (0 if self.workspace_stays else self.workspace_bytes) + self.data_bytes + SPARE


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return str(n)


# ── звірка ───────────────────────────────────────────────────────────────────
def manifest(root: Path, skip_top: tuple[str, ...] = ()) -> dict[str, int]:
    """Кожен файл під `root`: відносний шлях → розмір."""
    out: dict[str, int] = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if here == root:
            dirnames[:] = [d for d in dirnames if d not in skip_top]
            filenames = [f for f in filenames if f not in skip_top]
        for name in filenames:
            p = here / name
            try:
                out[p.relative_to(root).as_posix()] = p.stat().st_size
            except OSError:
                out[p.relative_to(root).as_posix()] = -1
    return out


def diff(src: dict[str, int], dst: dict[str, int]) -> list[str]:
    """Чого в копії немає або що в ній іншого розміру. Порожньо — зійшлось."""
    bad = [f"немає в копії: {k}" for k in src if k not in dst]
    bad += [f"інший розмір: {k} ({src[k]} → {dst[k]})"
            for k in src if k in dst and src[k] != dst[k]]
    return bad


def copy_verified(src: Path, dst: Path, skip_top: tuple[str, ...] = (),
                  echo: Callable[[str], None] = print) -> tuple[int, int]:
    """Скопіювати дерево й звірити ПОФАЙЛОВО. Не зійшлось — `RelocateError`."""
    want = manifest(src, skip_top)
    echo(f"  копіюю {len(want)} файлів, {human(sum(max(v, 0) for v in want.values()))}: "
         f"{src} → {dst}")

    def ignore(d: str, names: list[str]) -> list[str]:
        return [n for n in names if n in skip_top] if Path(d) == src else []

    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True, copy_function=shutil.copy2)
    bad = diff(want, manifest(dst, skip_top))
    if bad:
        raise RelocateError("копія не зійшлась з оригіналом, старе не чіпали:\n  "
                            + "\n  ".join(bad[:20]))
    return len(want), sum(max(v, 0) for v in want.values())


# ── план ─────────────────────────────────────────────────────────────────────
def _free(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return -1


def _inside(a: Path, b: Path) -> bool:
    """Чи `a` лежить у `b` (або це вона сама)."""
    try:
        a.resolve().relative_to(b.resolve())
        return True
    except ValueError:
        return False


def plan(target: str | Path) -> Plan:
    """Порахувати переїзд. Нічого не пише."""
    from nyshporka.core.appdirs import data_dir
    from nyshporka.core.workspace import validate_root, workspace
    from nyshporka.setup.doctor import engine_venv
    from nyshporka.setup.update import install_home
    from nyshporka.setup.wizard import _is_synced

    to = validate_root(Path(target))
    ws = workspace().root
    home_to = to / ".program"
    p = Plan(workspace_from=ws, workspace_to=to, home_from=install_home(),
             home_to=home_to, data_from=data_dir(), data_to=home_to / "data")
    p.workspace_stays = to.resolve() == ws.resolve()
    if _is_synced(to):
        p.problems.append(f"{to} синхронізується з хмарою — оберіть теку поза нею")
    if not p.workspace_stays:
        if _inside(to, ws) or _inside(ws, to):
            p.problems.append("нова тека не може лежати в старому просторі чи містити його")
        elif to.exists() and any(to.iterdir()):
            p.problems.append(f"{to} не порожня — потрібна нова або порожня тека")
    if p.home_from.resolve() == home_to.resolve():
        p.problems.append("програма вже стоїть у цій теці — переїжджати нічого")
    try:
        p.engines = engine_venv().is_dir() and _inside(engine_venv(), ws)
    except Exception:
        p.engines = False
    if not p.workspace_stays:
        p.workspace_bytes = sum(max(v, 0) for v in manifest(ws, SKIP_TOP).values())
    p.data_bytes = sum(max(v, 0) for v in _data_manifest(p.data_from).values())
    p.free_bytes = _free(to)
    if 0 <= p.free_bytes < p.need_bytes:
        p.problems.append(f"на диску {to.anchor} вільно {human(p.free_bytes)}, "
                          f"а треба близько {human(p.need_bytes)}")
    return p


#: Що з теки даних переїжджає. Решта там — стан і ключі (`platformdirs` на
#: Windows кладе їх у ту саму теку), вони маленькі й лишаються на місці.
DATA_PARTS = ("catalog", "Cache")


def _data_manifest(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in DATA_PARTS:
        for k, v in manifest(root / part).items():
            out[f"{part}/{k}"] = v
    return out


# ── слід інсталятора ─────────────────────────────────────────────────────────
def _write_info(path: Path, fields: dict[str, str]) -> None:
    """`install-info.ini` — UTF-16 на Windows (його читає майстер `.exe`)."""
    text = "\n".join(["[nyshporka]", *(f"{k}={v}" for k, v in fields.items())]) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-16" if sys.platform == "win32" else "utf-8")


def _info_at(home: Path) -> dict[str, str]:
    from nyshporka.setup import update as U

    path = home / U.INSTALL_INFO
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = path.read_text(encoding=enc)
        except (OSError, UnicodeError):
            continue
        out = {}
        for line in text.splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith(("[", "#", ";")):
                out[k.strip()] = v.strip()
        if out:
            return out
    return {}


def layout(home: Path) -> dict[str, str]:
    """Теки розкладки «одна тека» під `home` — ті самі імена, що в `windows.ps1`."""
    return {"python_dir": str(home / "python"), "tool_dir": str(home / "tools"),
            "bin_dir": str(home / "bin"), "cache_dir": str(home / "cache"),
            "data_dir": str(home / "data")}


def uv_env(home: Path) -> dict[str, str]:
    from nyshporka.setup.update import UV_DIR_KEYS

    lay = layout(home)
    env = {**os.environ, "UV_PYTHON_INSTALL_BIN": "0", "UV_PYTHON_INSTALL_REGISTRY": "0",
           "NYSHPORKA_DATA_DIR": lay["data_dir"]}
    env.update({var: lay[key] for key, var in UV_DIR_KEYS.items()})
    return env


# ── виконання ────────────────────────────────────────────────────────────────
Runner = Callable[[list[str], dict[str, str]], int]


def _run(cmd: list[str], env: dict[str, str]) -> int:
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, env=env, check=False).returncode


def _old_uv_cache(uv: str) -> str:
    """Тека кешу uv старого місця — з неї рушії зберуться без нового завантаження."""
    env = {k: v for k, v in os.environ.items() if k != "UV_CACHE_DIR"}
    try:
        r = subprocess.run([uv, "cache", "dir"], env=env, capture_output=True,
                           text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _rewrite_case_roots(marker: Path, old: Path, new: Path) -> None:
    """Корені справ, що лежали в старому просторі, — на нове місце."""
    try:
        import tomllib

        cfg = tomllib.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    roots = (cfg.get("workspace") or {}).get("case_roots") or cfg.get("case_roots") or []
    text = marker.read_text(encoding="utf-8")
    changed = False
    for raw in roots:
        p = Path(str(raw))
        if _inside(p, old):
            moved = (new / p.resolve().relative_to(old.resolve())).as_posix()
            for quoted in (f'"{raw}"', f"'{raw}'"):
                if quoted in text:
                    text = text.replace(quoted, f'"{moved}"')
                    changed = True
    if changed:
        marker.write_text(text, encoding="utf-8")


def _retarget_shortcuts(nysh: Path, workdir: Path, echo: Callable[[str], None]) -> None:
    """Ярлики «Нишпорка» на робочому столі й у «Пуску» — на нову команду."""
    if sys.platform != "win32":
        return
    q = lambda x: str(x).replace("'", "''")  # noqa: E731 — лапки PowerShell
    script = (
        "$sh = New-Object -ComObject WScript.Shell;"
        "$dirs = @([Environment]::GetFolderPath('Desktop'),"
        " (Join-Path ([Environment]::GetFolderPath('Programs')) 'Нишпорка'),"
        " [Environment]::GetFolderPath('Programs'));"
        "foreach ($d in $dirs) { if (-not (Test-Path $d)) { continue };"
        " Get-ChildItem -LiteralPath $d -Filter '*.lnk' | ForEach-Object {"
        "  $s = $sh.CreateShortcut($_.FullName);"
        "  if ($s.TargetPath -like '*\\nysh.exe') {"
        f"   $s.TargetPath = '{q(nysh)}'; $s.WorkingDirectory = '{q(workdir)}'; $s.Save();"
        "   Write-Output $_.FullName } } }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, check=False, timeout=60)
        for line in r.stdout.splitlines():
            if line.strip():
                echo(f"  ярлик → нова програма: {line.strip()}")
    except (OSError, subprocess.SubprocessError) as exc:
        echo(f"  ⚠ ярлики не перевішено ({exc}); запускайте `{nysh} serve`")


def run(p: Plan, *, preset: str = "", runner: Runner = _run,
        echo: Callable[[str], None] = print) -> Path:
    """Переїхати: копія із звіркою, нова програма, ярлики. Старе НЕ видаляється.

    Повертає шлях до нової команди `nysh`.
    """
    from nyshporka import __version__
    from nyshporka.core.lock import LockBusy, WorkspaceLock
    from nyshporka.core.workspace import MARKER, state_set
    from nyshporka.setup import update as U

    if p.problems:
        raise RelocateError("\n".join(p.problems))
    old_info = U.install_info()
    uv = old_info.get("uv") or shutil.which("uv") or ""
    if not uv or not Path(uv).exists():
        raise RelocateError("не знайдено uv, яким ставилась Нишпорка — переїзд "
                            "можливий лише для установки інсталятором")

    # 🔴 Застосунок у браузері тримає замок простору: копіювати під живим
    # демоном — це копія, в яку дописують, і звірка, що бреше.
    try:
        lock = WorkspaceLock(p.workspace_from).acquire()
    except LockBusy as exc:
        raise RelocateError(f"{exc} Закрийте вікно Нишпорки (і `nysh serve`) "
                            f"на час переїзду.") from None
    with lock:
        echo("1. простір")
        if p.workspace_stays:
            echo(f"  лишається на місці: {p.workspace_from}")
        else:
            copy_verified(p.workspace_from, p.workspace_to, SKIP_TOP, echo)
            _rewrite_case_roots(p.workspace_to / MARKER, p.workspace_from, p.workspace_to)

    echo("2. довідники й ваги")
    for part in DATA_PARTS:
        if (p.data_from / part).is_dir():
            copy_verified(p.data_from / part, p.data_to / part, (), echo)

    echo("3. програма")
    home = p.home_to
    (home / "uv").mkdir(parents=True, exist_ok=True)
    new_uv = home / "uv" / Path(uv).name
    shutil.copy2(uv, new_uv)
    env = uv_env(home)
    if runner([str(new_uv), "python", "install", "3.12"], env) != 0:
        raise RelocateError("uv не поставив Python 3.12 у нову теку")
    spec = U.command(preset)[-1]
    if "==" not in spec:
        spec = f"{spec}=={__version__}"
    if runner([str(new_uv), "tool", "install", "--python", "3.12", "--force", spec], env) != 0:
        raise RelocateError(f"uv не поставив {spec} у нову теку")
    runner([str(new_uv), "tool", "update-shell"], env)
    lay = layout(home)
    nysh = Path(lay["bin_dir"]) / ("nysh.exe" if sys.platform == "win32" else "nysh")
    _write_info(home / U.INSTALL_INFO, {
        "nysh": str(nysh), "uv": str(new_uv),
        "preset": preset or U.preset_now(old_info.get("preset", "")),
        **lay, "workspace": str(p.workspace_to)})

    # Майстер `.exe` при наступному оновленні бере попередню теку встановлення.
    # Ця позначка каже йому, що програма переїхала, — інакше він поставив би
    # нову версію назад на C:.
    old_ini = p.home_from / U.INSTALL_INFO
    if old_ini.is_file():
        _write_info(old_ini, {**_info_at(p.home_from), "relocated_to": str(home)})
    (home / RECORD).write_text(json.dumps({
        "workspace": str(p.workspace_from) if not p.workspace_stays else "",
        "data": str(p.data_from), "home": str(p.home_from),
        "python_dir": old_info.get("python_dir", ""),
        "tool_dir": old_info.get("tool_dir", ""), "uv": uv,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    state_set(workspace=str(p.workspace_to))
    _retarget_shortcuts(nysh, p.workspace_to, echo)

    if p.engines:
        echo("4. рушії читання — збираю наново з кешу старого місця")
        cache = _old_uv_cache(uv)
        eng_env = {**env, "NYSHPORKA_WORKSPACE": str(p.workspace_to)}
        if cache:
            eng_env["UV_CACHE_DIR"] = cache
        if runner([str(nysh), "htr", "install"], eng_env) != 0:
            echo("  ⚠ рушії не зібрались — повторіть `nysh htr install` у новому вікні")
    runner([str(nysh), "--workspace", str(p.workspace_to), "doctor"],
           {**env, "NYSHPORKA_WORKSPACE": str(p.workspace_to)})
    return nysh


# ── прибрати старе ───────────────────────────────────────────────────────────
@dataclass
class Leftover:
    what: str
    path: Path | None
    size: int = 0
    #: Як знімати: `rmtree` теки чи `uv tool uninstall` (path тоді — uv).
    how: str = "rmtree"


def leftovers(home: Path | None = None) -> tuple[dict[str, str], list[Leftover]]:
    """Що лишилось на старому місці. Звіряє копію простору ще раз."""
    from nyshporka.core.workspace import workspace
    from nyshporka.setup.update import _home_from_prefix

    here = home or _home_from_prefix()
    if here is None or not (here / RECORD).is_file():
        raise RelocateError("запустіть `nysh relocate --finish` НОВОЮ програмою: "
                            "відкрийте нове вікно термінала після `nysh relocate <тека>`")
    rec = json.loads((here / RECORD).read_text(encoding="utf-8"))
    out: list[Leftover] = []
    old_ws = Path(rec["workspace"]) if rec.get("workspace") else None
    if old_ws is not None and old_ws.is_dir():
        new_ws = workspace().root
        if old_ws.resolve() == new_ws.resolve():
            raise RelocateError("активний простір — досі старий; спершу відкрийте новий")
        bad = diff(manifest(old_ws, SKIP_TOP), manifest(new_ws, SKIP_TOP))
        # Новий простір міг піти вперед (ви вже працювали) — це не біда. Біда —
        # файл старого, якого в новому НЕМАЄ.
        missing = [b for b in bad if b.startswith("немає в копії")]
        if missing:
            raise RelocateError("у новому просторі бракує файлів старого — нічого не видаляю:\n  "
                                + "\n  ".join(missing[:20]))
        out.append(Leftover(f"старий простір {old_ws}", old_ws,
                            sum(max(v, 0) for v in manifest(old_ws).values())))
    data = Path(rec["data"]) if rec.get("data") else None
    if data is not None and data.resolve() != (here / "data").resolve():
        for part in DATA_PARTS:
            if (data / part).is_dir():
                out.append(Leftover(f"старі довідники й ваги {data / part}", data / part,
                                    sum(max(v, 0) for v in manifest(data / part).values())))
    if rec.get("uv") and Path(rec["uv"]).exists():
        out.append(Leftover("старе середовище програми (uv tool uninstall)",
                            Path(rec["uv"]), how="uv"))
    pydir = Path(rec["python_dir"]) if rec.get("python_dir") else None
    old_home = Path(rec["home"]) if rec.get("home") else None
    # Лише інтерпретатори НИШПОРКИ (під її старою текою): спільний `%APPDATA%\uv`
    # могли ділити з іншими проєктами людини.
    if pydir is not None and old_home is not None and pydir.is_dir() and _inside(pydir, old_home):
        out.append(Leftover(f"старі інтерпретатори {pydir}", pydir,
                            sum(max(v, 0) for v in manifest(pydir).values())))
    return rec, out


def finish(items: list[Leftover], rec: dict[str, str],
           echo: Callable[[str], None] = print) -> None:
    """Прибрати те, що назвав `leftovers()`. Кликати лише після «так» людини."""
    for it in items:
        if it.how == "uv":
            env = {k: v for k, v in os.environ.items()
                   if k not in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR")}
            if rec.get("tool_dir"):
                env["UV_TOOL_DIR"] = rec["tool_dir"]
            subprocess.run([str(it.path), "tool", "uninstall", "nyshporka"], env=env,
                           check=False)
            echo(f"  ✓ {it.what}")
            continue
        if it.path is not None and it.path.exists():
            _rmtree(it.path)
            echo(f"  ✓ {it.what}")


def _rmtree(path: Path) -> None:
    """`rmtree`, що знімає й файли «лише для читання» (git, venv на Windows)."""
    import stat

    def again(func, target, _exc):  # noqa: ANN001
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)
