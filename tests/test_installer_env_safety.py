"""🔴 Інсталятор не переставляє чуже середовище, і зняти його є чим.

Скарга розробника 07.09.2026, дослівно: «розробникам воно ламає env навіть не
питаючи… мені воно перебило мультиверсії python, tensorflow та кастомні nvidia
драйвери». Причина була не в коді застосунку, а в тому, ЯК `install/unix.sh`
кликав `uv`, і складалась із двох частин, кожна з яких мовчазна:

1. офіційний інсталятор uv ЗАВЖДИ кладе поруч із собою файл `env`, а без
   `UV_NO_MODIFY_PATH` ще й дописує `. "$HOME/.local/bin/env"` у півдесятка
   файлів профілю. Той файл ставить `~/.local/bin` на початок PATH — і сам,
   називаючись `env`, заслоняє `/usr/bin/env`;
2. `uv python install` без `UV_PYTHON_INSTALL_BIN=0` кладе туди ж `python3.12`,
   і той стає першим `python3.12` у PATH раніше за pyenv і conda.

Жоден із цих ефектів не видно з коду застосунку, обидва не мають повідомлення,
і зняти їх на Linux/macOS не було чим узагалі. Тому вони накриті текстовими
приймачами: помилка тут не падає в CI, вона доходить до людини у вигляді
машини, яку хтось переставив без питання.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install"
UNIX = INSTALL / "unix.sh"
PS1 = INSTALL / "windows.ps1"
UNINSTALL = INSTALL / "uninstall.sh"


def unix_text() -> str:
    return UNIX.read_text(encoding="utf-8")


def ps1_text() -> str:
    return PS1.read_text(encoding="utf-8-sig")


def _uncommented(text: str, marker: str) -> list[str]:
    """Рядки з підрядком, які не є коментарем.

    ⚠ Без цього приймачі проходили б на самих поясненнях: у цих скриптах
    коментар довший за код, і кожна змінна названа в ньому по кілька разів.
    """
    return [ln for ln in text.splitlines()
            if marker in ln and not ln.lstrip().startswith("#")]


def test_unix_installer_never_lets_uv_edit_the_shell_profiles() -> None:
    """🔴 Голий `curl … install.sh | sh` править півдесятка файлів профілю.

    І кладе в `~/.local/bin` файл на ім'я `env`, який заслоняє `/usr/bin/env`
    для всього, що потім пише `env VAR=1 команда`. Обидві змінні мусять стояти
    ДО завантаження: виставлені після, вони не значать нічого.
    """
    lines = unix_text().splitlines()
    curl = [i for i, ln in enumerate(lines)
            if "astral.sh/uv/install.sh" in ln and not ln.lstrip().startswith("#")]
    assert len(curl) == 1, "інсталятор uv кличеться не один раз — приймач осліп"
    # Виклик через конвеєр, тож змінні стоять на другому боці — беремо обидва
    # рядки конвеєра разом.
    call = "\n".join(lines[curl[0]:curl[0] + 2])
    for var in ("UV_INSTALL_DIR", "UV_NO_MODIFY_PATH"):
        assert var in call, (
            f"unix.sh: {var} не передано інсталятору uv — той покладе `env` у "
            f"~/.local/bin і допише його в профілі оболонки")


def test_the_uv_installer_variables_never_leak_past_it() -> None:
    """🔴 Знайдено прогоном, а не читанням: `UV_NO_MODIFY_PATH` — не лише про
    інсталятор uv.

    Її слухається й `uv tool update-shell`. Експортована на весь скрипт, вона
    мовчки скасовує ЄДИНИЙ допис у PATH, який нам справді потрібен: у
    контейнері встановлення проходило «успішно», а в новій оболонці `nysh` не
    знаходився. Тому змінна стоїть префіксом до однієї команди.
    """
    guilty = [ln.strip() for ln in _uncommented(unix_text(), "UV_NO_MODIFY_PATH")
              if ln.lstrip().startswith("export ") or " export " in ln]
    assert not guilty, (
        "unix.sh: змінна експортована далі за інсталятор uv — вона скасує "
        "`uv tool update-shell`, і команда не знайдеться в новій оболонці:\n  "
        + "\n  ".join(guilty))
    # 🪟 На Windows `$env:` живе до кінця процесу, тож там та сама вада
    # лікується явним прибиранням змінної одразу після інсталятора uv.
    assert _uncommented(ps1_text(), "Remove-Item Env:UV_NO_MODIFY_PATH"), (
        "windows.ps1: змінна лишається в середовищі процесу — `uv tool "
        "update-shell` нижче нічого не зробить")


def test_windows_installer_never_lets_uv_edit_the_user_path() -> None:
    """🔴 Та сама половина скарги на Windows — запис у `HKCU\\Environment`.

    Тека uv там наша (`UV_INSTALL_DIR` стояв і раніше), ми кличемо uv повним
    шляхом, і допис у змінні середовища користувача не дає нічого, крім зайвої
    зміни в чужому середовищі.
    """
    text = ps1_text()
    assert _uncommented(text, "UV_NO_MODIFY_PATH"), (
        "windows.ps1: інсталятор uv дописує свою теку в PATH користувача")
    assert _uncommented(text, "UV_INSTALL_DIR"), (
        "windows.ps1: uv ставиться в типову теку, а не в теку застосунку")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1"])
def test_installers_never_put_a_python_shim_on_path(name: str) -> None:
    """🔴 `python3.12` у теці команд заслоняє pyenv, conda й системний.

    Саме це «перебило мультиверсії python», а за ними — TensorFlow і збірку під
    CUDA: вони зібрані під конкретний інтерпретатор, а `python3.12` почав
    вирішуватись у чужий.

    ⚠ Приймач вимагає ЗМІННОЇ, а не прапорця `--no-bin`: обидва скрипти вміють
    узяти вже наявний на машині uv, і той може бути старіший за 0.8. Невідомий
    прапорець валить установлення, невідому змінну старий uv не помічає.
    """
    text = unix_text() if name == "unix.sh" else ps1_text()
    assert _uncommented(text, "UV_PYTHON_INSTALL_BIN"), (
        f"{name}: `uv python install` покладе виконуваний python3.12 у теку "
        f"команд — потрібна змінна UV_PYTHON_INSTALL_BIN=0")
    assert not _uncommented(text, "--no-bin"), (
        f"{name}: прапорець замість змінної — на чужому uv < 0.8 це відмова "
        f"на другому кроці встановлення")


def test_windows_installer_keeps_its_python_out_of_the_registry() -> None:
    """⚠ Керований інтерпретатор — деталь Нишпорки, а не Python цієї машини.

    Без `UV_PYTHON_INSTALL_REGISTRY=0` uv реєструє його за PEP 514, і він
    з'являється в `py`-лаунчері та в списках інтерпретаторів чужих IDE — там,
    де людина обирає його, не знаючи, звідки він узявся.
    """
    assert _uncommented(ps1_text(), "UV_PYTHON_INSTALL_REGISTRY"), (
        "windows.ps1: керований Python реєструється в реєстрі Windows")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1"])
def test_the_only_path_edit_has_an_off_switch(name: str) -> None:
    """🔴 Допис теки з командою в PATH лишається — але з вимикачем.

    Без нього «прості люди» отримують `command not found` там, де все
    завантажилось (обидва користувачі 28.08.2026). А хто веде PATH сам, ставить
    `NYSH_NO_MODIFY_PATH=1` і отримує рядок для вставки руками.
    """
    text = unix_text() if name == "unix.sh" else ps1_text()
    assert _uncommented(text, "update-shell"), (
        f"{name}: PATH не закріплюється для наступних сеансів")
    assert _uncommented(text, "NYSH_NO_MODIFY_PATH"), (
        f"{name}: єдиний допис у PATH не має вимикача — тобто питання «чи "
        f"можна» людині не ставиться взагалі")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1"])
def test_installers_leave_a_trace_of_what_they_changed(name: str) -> None:
    """🔴 Слід і друкується, і лягає на диск.

    Друкується — бо людина має право знати, що з нею зробили, не читаючи
    скрипта. Лягає на диск — бо саме з нього `nysh uninstall` знімає РІВНО
    поставлене: тека команд налаштовується, і здогад про `~/.local/bin`
    збігається лише з типовим випадком.
    """
    from nyshporka.setup.uninstall import TRACE

    text = unix_text() if name == "unix.sh" else ps1_text()
    assert TRACE in text, (
        f"{name}: слід не пишеться — «nysh uninstall» вгадуватиме шляхи")
    assert "Змінено на цій машині" in text, (
        f"{name}: перелік змін не показується людині")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1", "uninstall.sh",
                                  "nyshporka.iss"])
def test_installers_carry_no_control_characters(name: str) -> None:
    """🔴 Керівний символ у скрипті не видно ні в редакторі, ні в діффі.

    У `windows.ps1` у гілці `-DryRun` замість `'.local\\bin'` лежав байт 0x08
    (backspace) і `in` — слід того, що рядок колись пройшов крізь рядковий
    літерал, де `\\b` означає керівний символ. PowerShell у одинарних лапках
    нічого не екранує, тож перелік «що буде зроблено» на машині без uv друкував
    `C:\\Users\\…\\.localin\\nysh.exe` — теку, якої не існує, — рівно там, де
    людина вирішує, чи можна дозволити встановлення. Помітно лише прогоном.
    """
    raw = (INSTALL / name).read_bytes()
    bad = sorted({b for b in raw if b < 0x20 and b not in (0x09, 0x0A, 0x0D)})
    assert not bad, (
        f"{name}: керівні символи {[hex(b) for b in bad]} — рядок пройшов крізь "
        f"екранування й зіпсувався")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1"])
def test_installers_can_show_without_doing(name: str) -> None:
    """Подивитись, що чіпатимуть, можна ДО того, як щось завантажилось."""
    text = unix_text() if name == "unix.sh" else ps1_text()
    needle = "--dry-run" if name == "unix.sh" else "DryRun"
    assert _uncommented(text, needle), f"{name}: немає режиму «показати й вийти»"


def test_the_unix_uninstaller_does_not_copy_the_logic() -> None:
    """🔴 Друга копія логіки зняття розійшлася б із першою мовчки.

    Те саме рішення, що вже записане в `install/nyshporka.iss` про
    `windows.ps1`: скрипт лише знаходить команду, а знімає `nysh uninstall`.
    """
    text = UNINSTALL.read_text(encoding="utf-8")
    assert "uninstall" in text and "exec" in text, (
        "uninstall.sh не передає роботу команді")
    # ⚠ `rm -rf` усередині `say` — це ПОРАДА людині, коли команди вже немає, а
    # слід лишився; вона й мусить там бути. Ловимо лише справжнє видалення.
    guilty = [ln.strip() for ln in _uncommented(text, "rm -rf")
              if not ln.lstrip().startswith("say ")]
    assert not guilty, ("uninstall.sh видаляє щось сам — знімати мусить "
                        "`nysh uninstall`, у якого є запобіжник простору:\n  "
                        + "\n  ".join(guilty))


# ── команда зняття ───────────────────────────────────────────────────────────
def test_uninstall_never_touches_the_research(tmp_path: Path) -> None:
    """🔴🔴 Найдорожчий приймач у файлі.

    Помилка тут коштує сканів і прочитаного, зібраних роками, і виправити її
    нічим. Виняток рівно один і названий поіменно: середовище рушіїв лежить
    усередині простору й знімається `--engines`.
    """
    from nyshporka.setup import uninstall as U

    ws = tmp_path / "Нишпорка"
    (ws / "data").mkdir(parents=True)
    venv = ws / ".venv_kraken"
    venv.mkdir()

    with pytest.raises(U.Forbidden):
        U.guard(ws, ws, venv)                       # сам простір
    with pytest.raises(U.Forbidden):
        U.guard(ws / "data", ws, venv)              # будь-що всередині
    U.guard(venv, ws, venv)                         # рушії — можна
    U.guard(tmp_path / "чуже", ws, venv)            # поза простором — можна


def test_uninstall_plan_lists_nothing_from_the_workspace(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Навіть `--all` не називає жодного шляху всередині простору, крім рушіїв."""
    from nyshporka.setup import uninstall as U

    ws = tmp_path / "Нишпорка"
    (ws / "data" / "pages").mkdir(parents=True)
    venv = ws / ".venv_kraken"
    venv.mkdir()
    monkeypatch.setattr(U, "_workspace_root", lambda: ws)
    monkeypatch.setattr(U, "_engine_venv", lambda: venv)
    monkeypatch.setattr(U, "traced", lambda: [])

    plan = U.plan(engines=True, models=True, catalog=True, skills=True,
                  state=True)
    for item in plan.items:
        if item.path is None:
            continue
        if ws not in item.path.parents and item.path != ws:
            continue
        assert item.path == venv, (
            f"у плані шлях усередині простору: {item.path}")


def test_uninstall_dry_run_removes_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ Без `--yes` команда мусить бути безшумною для диска."""
    from nyshporka.setup import uninstall as U

    victim = tmp_path / "тека"
    victim.mkdir()
    (victim / "файл.txt").write_text("тримається", encoding="utf-8")
    monkeypatch.setattr(U, "_workspace_root", lambda: None)
    monkeypatch.setattr(U, "_engine_venv", lambda: None)

    plan = U.Plan(items=[U.Item(kind="dir", what="тека", path=victim)])
    lines = U.remove(plan, dry=True)

    assert victim.is_dir() and (victim / "файл.txt").is_file(), (
        "«показати» видалило файли")
    assert any("зняли б" in ln for ln in lines)


def test_uninstall_takes_only_its_own_things_out_of_the_data_dir() -> None:
    """🔴 На Windows тека застосунку і тека ДАНИХ — одна й та сама.

    `%LOCALAPPDATA%\\Nyshporka` є і `install_home()`, і
    `user_data_dir("Nyshporka")`. `rmtree` над нею змив би паки довідників і
    ваги моделей — рівно те, що команда на два рядки нижче обіцяє лишити, і
    змив би мовчки. Тому звідти знімається поіменний перелік.
    """
    from nyshporka.setup import uninstall as U

    assert "catalog" not in U.HOME_OWNED and "Cache" not in U.HOME_OWNED
    assert "uv" in U.HOME_OWNED and U.TRACE in U.HOME_OWNED


def test_uninstall_reads_the_trace_it_was_given(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Слід читається як пари «вид, шлях», і сміття в ньому не валить розбір."""
    from nyshporka.setup import uninstall as U

    uv_dir = tmp_path / "nyshporka" / "uv"
    rc = tmp_path / ".zshrc"
    trace = tmp_path / U.TRACE
    trace.write_text(f"dir {uv_dir}\n"
                     f"shell {rc}\n"
                     "\n"
                     "кривий рядок без пробілу\n", encoding="utf-8")
    monkeypatch.setattr(U, "trace_path", lambda: trace)

    got = U.traced()
    assert ("dir", str(uv_dir)) in got
    assert ("shell", str(rc)) in got
    assert len(got) == 3      # третій — «кривий рядок» без шляху не пройде


def test_a_trace_written_with_a_bom_is_read_as_the_same_trace(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴🔴 BOM від PowerShell 5.1 не сміє перетворити допис у PATH на теку.

    `windows.ps1` пише слід `Set-Content -Encoding UTF8`, і 5.1 кладе BOM. Під
    голим `utf-8` перший вид читався як `\\ufeffpath`, план бачив у ньому
    звичайну теку — і `nysh uninstall --yes` зносив би теку команд uv цілком.
    """
    from nyshporka.setup import uninstall as U

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "чужий-інструмент.exe").write_text("", encoding="utf-8")
    trace = tmp_path / U.TRACE
    trace.write_bytes(f"path {bin_dir}\r\nbin {bin_dir / 'nysh.exe'}\r\n"
                      .encode("utf-8-sig"))
    monkeypatch.setattr(U, "trace_path", lambda: trace)
    monkeypatch.setattr(U, "_workspace_root", lambda: None)
    monkeypatch.setattr(U, "_engine_venv", lambda: None)
    monkeypatch.setattr(U, "_skill_dirs", lambda: [])
    monkeypatch.setattr("nyshporka.setup.update.install_home",
                        lambda: tmp_path / "home")

    assert U.traced()[0] == ("path", str(bin_dir)), U.traced()
    plan = U.plan()
    assert not [i for i in plan.items if i.path == bin_dir and i.kind in ("dir", "file")], (
        "допис у PATH прочитано як теку — uninstall знесе теку команд цілком")


@pytest.mark.parametrize("name", ["unix.sh", "windows.ps1"])
def test_a_second_run_keeps_the_trace_of_the_first(name: str) -> None:
    """🔴 Повторний запуск інсталятора не сміє затирати слід першого.

    Друга спроба й оновлення тим самим рядком (на Windows — новим `.exe`)
    бачать uv і теку команд уже на місці, тож самі не записують ні `dir`, ні
    допису в PATH чи профіль. Перезапис файла лишав `nysh uninstall` без
    того єдиного рядка, який він мав прибрати з чужого середовища.
    """
    text = unix_text() if name == "unix.sh" else ps1_text()
    write = ('mv -f "$TRACE_FILE.new" "$TRACE_FILE"' if name == "unix.sh"
             else "Set-Content -LiteralPath $traceFile")
    read = ('cat "$TRACE_FILE"' if name == "unix.sh"
            else "Get-Content -LiteralPath $traceFile")
    assert _uncommented(text, write), f"{name}: слід більше не пишеться там, де чекали"
    assert _uncommented(text, read), f"{name}: слід попереднього запуску не читається"
    assert text.index(read) < text.index(write), (
        f"{name}: слід пишеться раніше, ніж прочитано попередній — перезапис")


def test_the_unix_trace_merge_keeps_old_lines_once(tmp_path: Path) -> None:
    """Сам фрагмент злиття з `unix.sh`, прогнаний оболонкою: старе лишається, дублів немає."""
    import shutil
    import subprocess

    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("немає POSIX-оболонки")
    lines = unix_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("{ if [ -f \"$TRACE_FILE\" ]"))
    snippet = "\n".join(lines[start:start + 3])
    trace = tmp_path / "install-trace.txt"
    trace.write_text("shell /x/.bashrc\nbin /x/nysh\n", encoding="utf-8")
    script = (f'TRACE_FILE="{trace.as_posix()}"\n'
              'TRACE="bin /x/nysh\nfile /x/install-info.ini\n"\n' + snippet + "\n")
    subprocess.run([sh, "-c", script], check=True, timeout=60)
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "shell /x/.bashrc", "bin /x/nysh", "file /x/install-info.ini"]


def test_uninstall_keeps_a_copy_before_editing_a_shell_profile(
        tmp_path: Path) -> None:
    """🔴 Правка профілю — рівно те, за що прийшла скарга.

    Тому вона зачіпає лише рядок про теку команд, а попередній вміст лягає
    поруч копією: людина мусить мати чим повернути своє.
    """
    from nyshporka.setup import uninstall as U

    rc = tmp_path / ".zshrc"
    rc.write_text('export EDITOR=vim\n'
                  '# uv\n'
                  'export PATH="$HOME/.local/bin:$PATH"\n'
                  'source ~/моє.sh\n', encoding="utf-8")

    U._drop_shell_line(rc, dry=False)

    left = rc.read_text(encoding="utf-8")
    assert "EDITOR=vim" in left and "моє.sh" in left, "прибрано чуже"
    assert ".local/bin" not in left, "рядок PATH лишився"
    assert "# uv" not in left, "маркер лишився без того, що він коментує"
    backup = rc.with_suffix(rc.suffix + U.BACKUP_SUFFIX)
    assert backup.is_file() and ".local/bin" in backup.read_text(encoding="utf-8")


def test_uv_is_found_even_when_it_is_not_on_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Наслідок того, що uv більше не лягає в теку команд.

    Він тепер у теці застосунку й у PATH його немає — саме заради того, щоб не
    класти туди файл `env`. Але `nysh htr install` шукав його лише в PATH, і
    без цього містка відмовляв би «uv не знайдено» на машині, де uv щойно
    поставили МИ, а порада вела б на другу копію.
    """
    from nyshporka.htr import env as E

    uv = tmp_path / "uv"
    uv.write_text("", encoding="utf-8")
    monkeypatch.setattr(E.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr("nyshporka.setup.update.install_info",
                        lambda: {"uv": str(uv)})

    assert E._resolve_tool("uv") == str(uv)
    assert E._resolve_tool("git") == "", "решту інструментів вгадувати не можна"


def test_the_command_is_reachable() -> None:
    """⚠ Команда, якої немає в довідці, не існує для людини."""
    from typer.main import get_command

    from nyshporka.cli import app

    assert "uninstall" in get_command(app).commands  # type: ignore[attr-defined]


def test_docs_tell_a_developer_how_to_be_careful() -> None:
    """🔴 `AGENTS.md` читає агент, і саме агент виконував те встановлення.

    Скарга прийшла від людини, чий агент поставив застосунок за цим файлом; без
    рядка тут виправлення інсталятора лишиться невидимим саме там, де його
    читають.
    """
    for name in ("AGENTS.md", "README.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert re.search(r"NYSH_NO_MODIFY_PATH|--dry-run", text), (
            f"{name}: не сказано, як поставити застосунок, не чіпаючи PATH")


# ── лапки без фігурних дужок і bash 3.2 в UTF-8-локалі ───────────────────────
# 🔴 `«$_bin»` без фігурних дужок: під `set -u` bash 3.2 (system `/bin/sh` на
# macOS) в UTF-8-локалі бере перший байт «»» ЗА ЧАСТИНУ ІМЕНІ змінної — `_bin»:
# unbound variable» — і `--dry-run` падав рівно на останньому рядку зведення,
# тож підказка «Нічого не зроблено — це --dry-run.» не друкувалась НІКОЛИ.
# Відтворено локально: `LC_ALL=uk_UA.UTF-8 sh install/unix.sh --dry-run` падає,
# `LC_ALL=C` — ні. dash (типовий `/bin/sh` на Linux) цієї вади не має, тож
# приймач нижче ловить регресію саме там, де вона стається, — на macOS.
_UNBRACED_VAR_BEFORE_NON_ASCII = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^ -~]")


@pytest.mark.parametrize("name", ["unix.sh", "uninstall.sh"])
def test_no_unbraced_var_touches_a_multibyte_char(name: str) -> None:
    """🔴 Статичний приймач: `$ім'я`, за яким одразу йде небайтовий символ.

    Без фігурних дужок межа імені змінної для оболонки — це non-word байт, а
    перший байт багатобайтового UTF-8 символу (наприклад, «»») ним не є. У
    `set -u` це не тихий збіг символів, а `unbound variable` і код виходу 1.
    """
    text = (INSTALL / name).read_text(encoding="utf-8")
    guilty = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _UNBRACED_VAR_BEFORE_NON_ASCII.search(line)
        if m:
            guilty.append(f"{name}:{lineno}: {line.strip()}")
    assert not guilty, (
        "$ім'я впритул до небайтового символу — під bash 3.2 в UTF-8-локалі "
        "це `unbound variable` (потрібні фігурні дужки ${ім'я}):\n  "
        + "\n  ".join(guilty))


def _first_available_utf8_locale() -> str | None:
    import subprocess

    try:
        out = subprocess.run(["locale", "-a"], capture_output=True,
                              text=True, timeout=10)
    except OSError:
        return None
    have = {ln.strip() for ln in out.stdout.splitlines()}
    for candidate in ("C.UTF-8", "en_US.UTF-8"):
        if candidate in have:
            return candidate
    return None


def test_unix_dry_run_survives_a_utf8_locale_on_bash_32() -> None:
    """🔴🔴 Прогін самого скрипта — приймач вище читає текст, цей запускає його.

    Статичний приймач ловить рівно цей патерн; якби регресія прийшла іншим
    шляхом (інша непарна лапка, інший небайтовий символ у новому рядку поза
    патерном), він міг би не помітити. Цей приймач байдужий ДО причини:
    `--dry-run` мусить дійти до кінця й нічого не зробити на диску.
    """
    import os
    import shutil
    import subprocess

    if os.name == "nt":
        pytest.skip("system /bin/sh на bash 3.2 — вада macOS/Linux, не Windows")
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("немає POSIX-оболонки")
    loc = _first_available_utf8_locale()
    if loc is None:
        pytest.skip("немає встановленої UTF-8-локалі (C.UTF-8 / en_US.UTF-8)")

    env = dict(os.environ)
    env["LC_ALL"] = loc
    # ⚠ Байти, не `text=True`: сама вада ламає рядок посеред багатобайтового
    # символу («_bin» + перший байт «»»), і суворий UTF-8-декодер `subprocess`
    # впав би на цьому власним `UnicodeDecodeError` замість зрозумілого
    # `assert` — репортер побачив би внутрішню помилку тесту, а не діагноз.
    proc = subprocess.run([sh, str(UNIX), "--dry-run"], cwd=ROOT,
                          capture_output=True, timeout=60, env=env)
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, (
        f"unix.sh --dry-run під LC_ALL={loc} упав (код {proc.returncode}):\n"
        + out + err)
    assert "Нічого не зроблено" in out, (
        "unix.sh --dry-run не дійшов до прикінцевого рядка зведення:\n" + out)


# ── пак довідників з останнього релізу catalog-* ─────────────────────────────
# 🔴 `.exe` везе пак УСЕРЕДИНІ (release.yml тягне його для Windows), а
# `unix.sh` без цього блоку мовчав би на macOS/Linux завжди: поруч зі скриптом
# пака не буває ніколи, ні в клоні, ні тим паче через `curl … | sh`. Приймачі
# нижче не ходять у справжню мережу — фальшиві `curl` і `nysh` на PATH,
# фальшива видача GitHub API. Логіка живе в двох функціях unix.sh
# (`_sha256`, `_catalog_from_release`) саме для того, щоб приймач міг
# підвантажити їх окремо від решти скрипта (той тягне справжній `uv` і
# ставить пакет — цього офлайн-тест робити не повинен).
def _unix_snippet(start_prefix: str, end_prefix: str) -> str:
    """Суцільний шматок `unix.sh` між першим рядком, що починається на
    `start_prefix`, і першим НАСТУПНИМ рядком на `end_prefix` (не включно)."""
    lines = unix_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(start_prefix))
    end = next(i for i, ln in enumerate(lines)
               if i > start and ln.startswith(end_prefix))
    return "\n".join(lines[start:end])


def _write_exec(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _zip_bytes(mark: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("MARK.txt", mark)
    return buf.getvalue()


# Фальшивий `curl`: пише кожен виклик у лог, тягне не з мережі, а з файлів на
# диску. `--max-time N` і `-o ФАЙЛ` — єдині прапорці з власним значенням у
# цьому скрипті, тож позиційний розбір, а не справжній парсер аргументів,
# достатній.
#
# Сторінки видачі API — окремі файли `page-N.json` у `$FAKE_RELEASES_DIR`;
# `_catalog_from_release` завжди звертається за `<RELEASES_API>&page=N`, тож
# фальшивка впізнає такий URL за префіксом і бере номер сторінки з хвоста.
# Немає файла для сторінки — те саме, що 404 у справжньому curl: код 22,
# і виклик, що зробив запит, сам вирішує, чи це кінець списку, чи збій.
_FAKE_CURL = """
printf '%s\\n' "$*" >> "$FAKE_CURL_LOG"
skip=""
url=""
out=""
for a in "$@"; do
  case "$skip" in
    maxtime) skip=""; continue ;;
    out) out="$a"; skip=""; continue ;;
  esac
  case "$a" in
    --max-time) skip=maxtime ;;
    -o) skip=out ;;
    -*) ;;
    *) url="$a" ;;
  esac
done
case "$url" in
  "$FAKE_RELEASES_URL_PREFIX"'&page='*)
    page="${url##*&page=}"
    f="$FAKE_RELEASES_DIR/page-$page.json"
    if [ -f "$f" ]; then cp "$f" "$out"; exit 0; fi
    exit 22
    ;;
esac
base=$(basename "$url")
if [ -f "$FAKE_ZIP_DIR/$base" ]; then
  cp "$FAKE_ZIP_DIR/$base" "$out"
  exit 0
fi
exit 22
"""

# Фальшивий `nysh`: пише виклик у лог і дописує вміст маркера з пака, який
# щойно розпакували, — так тест бачить, який САМЕ пак дійшов до встановлення,
# а не лише те, що команда викликалась.
_FAKE_NYSH = """
printf '%s\\n' "$*" >> "$FAKE_NYSH_LOG"
prev=""
dir=""
for a in "$@"; do
  [ "$prev" = "--from" ] && dir="$a"
  prev="$a"
done
if [ -n "$dir" ] && [ -f "$dir/MARK.txt" ]; then
  cat "$dir/MARK.txt" >> "$FAKE_NYSH_LOG"
fi
exit 0
"""


def _release_block(tag: str, draft: bool, asset_name: str | None,
                   digest: str | None, url: str | None) -> str:
    """Один елемент масиву `releases`, з тим самим кроком відступу, що й
    справжня видача GitHub API (перевірено прогоном проти справжнього
    репозиторію: 2 простори на рівень вкладеності)."""
    head = (f'  {{\n'
           f'    "tag_name": "{tag}",\n'
           f'    "draft": {"true" if draft else "false"}')
    if asset_name is None:
        return head + "\n  }"
    return (head + ',\n'
           '    "assets": [\n'
           '      {\n'
           f'        "name": "{asset_name}",\n'
           f'        "digest": "{digest}",\n'
           f'        "browser_download_url": "{url}"\n'
           '      }\n'
           '    ]\n'
           '  }')


def _releases_json(blocks: list[str]) -> str:
    return "[\n" + ",\n".join(blocks) + "\n]\n"


def _write_releases_pages(dir_path: Path, *pages: str) -> None:
    """Пише сторінки видачі GitHub API як `page-1.json`, `page-2.json`, …

    Сторінка, якої тут немає, для фальшивого `curl` — 404 (код 22): цим
    користуються приймачі, де достатньо однієї сторінки, — далі просто
    нічого не заводять."""
    dir_path.mkdir(exist_ok=True)
    for i, content in enumerate(pages, start=1):
        (dir_path / f"page-{i}.json").write_text(content, encoding="utf-8")


def _catalog_env(bin_dir: Path, log_dir: Path) -> dict[str, str]:
    """Середовище з фальшивими `curl`/`nysh` ПЕРЕД справжнім PATH."""
    import os

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_CURL_LOG"] = str(log_dir / "curl.log")
    env["FAKE_NYSH_LOG"] = str(log_dir / "nysh.log")
    return env


def _require_shell_tools() -> str:
    import shutil

    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("немає POSIX-оболонки")
    if shutil.which("unzip") is None:
        pytest.skip("немає unzip")
    return sh


def test_catalog_from_release_picks_the_newest_non_draft_tag(
        tmp_path: Path) -> None:
    """Серед кількох `catalog-*` і одного НЕ-catalog тега бере найновішу дату.

    Тег без каталожного імені (`v1.0.0`) і чернетка з найпізнішою датою мусять
    програти навіть тому, хто формально «більший» рядком чи датою: перший —
    не той клас тега, другий — `draft`. Перевіряється не лише повернений код,
    а й ЩО САМЕ дійшло до `nysh catalog install --from` — маркер усередині
    пака.
    """
    sh = _require_shell_tools()

    curl_sh, nysh_sh = tmp_path / "curl", tmp_path / "nysh"
    _write_exec(curl_sh, _FAKE_CURL)
    _write_exec(nysh_sh, _FAKE_NYSH)

    zips = tmp_path / "zips"
    zips.mkdir()
    old_zip = _zip_bytes("catalog-2026-01-01")
    new_zip = _zip_bytes("catalog-2026-09-01")
    (zips / "old.zip").write_bytes(old_zip)
    (zips / "new.zip").write_bytes(new_zip)
    import hashlib
    old_digest = "sha256:" + hashlib.sha256(old_zip).hexdigest()
    new_digest = "sha256:" + hashlib.sha256(new_zip).hexdigest()

    releases_url = "https://example.invalid/api/releases"
    releases_json = _releases_json([
        _release_block("v1.0.0", draft=False, asset_name=None,
                       digest=None, url=None),
        _release_block("catalog-2026-01-01", draft=False,
                       asset_name="nyshporka-catalog-2026-01-01.zip",
                       digest=old_digest,
                       url="https://example.invalid/dl/old.zip"),
        _release_block("catalog-2026-12-01", draft=True,
                       asset_name="nyshporka-catalog-2026-12-01.zip",
                       digest="sha256:" + "0" * 64,
                       url="https://example.invalid/dl/draft.zip"),
        _release_block("catalog-2026-09-01", draft=False,
                       asset_name="nyshporka-catalog-2026-09-01.zip",
                       digest=new_digest,
                       url="https://example.invalid/dl/new.zip"),
    ])
    releases_dir = tmp_path / "releases"
    _write_releases_pages(releases_dir, releases_json)  # усе на сторінці 1

    helpers = _unix_snippet("_sha256() {", "# 🗂 Довідники")
    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -eu\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        f'RELEASES_API="{releases_url}"\n'
        f"{helpers}\n"
        "if _catalog_from_release; then rc=0; else rc=$?; fi\n"
        "rm -rf \"${_CAT_TMP:-}\" 2>/dev/null || true\n"
        'printf "RC:%s\\n" "$rc"\n',
        encoding="utf-8")

    # Мапа «URL з видачі → фікстура на диску» — через саме ім'я файла, яке
    # бере фальшивий curl (`basename`), тож посилання вище узгоджені з
    # іменами файлів у `zips/`. Сторінки 2 немає — фальшивий curl віддасть
    # 404, і саме цього тут і треба: усе вже на сторінці 1.
    env = _catalog_env(tmp_path, tmp_path)
    env["FAKE_RELEASES_URL_PREFIX"] = releases_url
    env["FAKE_RELEASES_DIR"] = str(releases_dir)
    env["FAKE_ZIP_DIR"] = str(zips)

    import subprocess
    proc = subprocess.run([sh, str(driver)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
    assert "RC:0" in proc.stdout, (
        f"нову catalog-* не поставлено:\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}")

    nysh_log = (tmp_path / "nysh.log").read_text(encoding="utf-8")
    assert "catalog-2026-09-01" in nysh_log, (
        f"у пак дійшов не найновіший недрафтовий catalog-*:\n{nysh_log}")
    assert "catalog-2026-01-01" not in nysh_log

    curl_log = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert "dl/new.zip" in curl_log
    assert "dl/old.zip" not in curl_log, (
        "качало старіший пак замість тільки найновішого:\n" + curl_log)
    assert "dl/draft.zip" not in curl_log, (
        "чернетку не мали чіпати взагалі:\n" + curl_log)


def test_catalog_from_release_paginates_past_the_first_page(
        tmp_path: Path) -> None:
    """🔴🔴 `catalog-*` виходить рідко, звичайні релізи — щотижня.

    Репозиторій на момент цього приймача мав 32 релізи, і єдиний `catalog-*`
    був НАЙСТАРІШИМ з них — тобто вже сьогодні сторінки 1 (`per_page=100`)
    вистачає лише тому, що релізів менше сотні. Ще ~68 звичайних релізів — і
    `catalog-*` тихо випав би за межу першої сторінки: не помилка, не
    попередження, просто порожній каталог. Тут сторінка 1 не містить жодного
    `catalog-*` взагалі, пак лежить на сторінці 2, а сторінка 3 — порожній
    масив (`[]`), яким API сигналізує кінець списку.
    """
    sh = _require_shell_tools()

    curl_sh, nysh_sh = tmp_path / "curl", tmp_path / "nysh"
    _write_exec(curl_sh, _FAKE_CURL)
    _write_exec(nysh_sh, _FAKE_NYSH)

    zips = tmp_path / "zips"
    zips.mkdir()
    zip_bytes = _zip_bytes("catalog-2026-09-01")
    (zips / "pack.zip").write_bytes(zip_bytes)
    import hashlib
    digest = "sha256:" + hashlib.sha256(zip_bytes).hexdigest()

    page1 = _releases_json([
        _release_block(f"v0.{n}.0", draft=False, asset_name=None,
                       digest=None, url=None)
        for n in range(1, 6)
    ])
    page2 = _releases_json([
        _release_block("catalog-2026-09-01", draft=False,
                       asset_name="nyshporka-catalog-2026-09-01.zip",
                       digest=digest,
                       url="https://example.invalid/dl/pack.zip"),
    ])
    page3 = "[]\n"
    releases_url = "https://example.invalid/api/releases"
    releases_dir = tmp_path / "releases"
    _write_releases_pages(releases_dir, page1, page2, page3)

    helpers = _unix_snippet("_sha256() {", "# 🗂 Довідники")
    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -eu\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        f'RELEASES_API="{releases_url}"\n'
        f"{helpers}\n"
        "if _catalog_from_release; then rc=0; else rc=$?; fi\n"
        "rm -rf \"${_CAT_TMP:-}\" 2>/dev/null || true\n"
        'printf "RC:%s\\n" "$rc"\n',
        encoding="utf-8")

    env = _catalog_env(tmp_path, tmp_path)
    env["FAKE_RELEASES_URL_PREFIX"] = releases_url
    env["FAKE_RELEASES_DIR"] = str(releases_dir)
    env["FAKE_ZIP_DIR"] = str(zips)

    import subprocess
    proc = subprocess.run([sh, str(driver)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
    assert "RC:0" in proc.stdout, (
        f"пак зі сторінки 2 не поставлено:\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}")

    nysh_log = (tmp_path / "nysh.log").read_text(encoding="utf-8")
    assert "catalog-2026-09-01" in nysh_log, (
        f"пак зі сторінки 2 не дійшов до встановлення:\n{nysh_log}")

    curl_log = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert "page=1" in curl_log and "page=2" in curl_log, (
        "не гортало сторінок — обмежилось першою:\n" + curl_log)


def test_catalog_digest_mismatch_skips_install_and_exits_clean(
        tmp_path: Path) -> None:
    """🔴 Розбіжна контрольна сума — не встановлюємо, і скрипт не падає.

    Обірваний файл виглядає як пак: на місці, з іменем, навіть
    розпаковується. Приймач ганяє ввесь блок «🗂 Довідники» (не саму лише
    функцію), бо саме там перевіряється друга половина вимоги — після
    невдалого качання встановлення в цілому доходить до кінця (`exit 0`),
    так, як воно доходить у справжньому `unix.sh` після цього блоку.
    """
    sh = _require_shell_tools()

    curl_sh, nysh_sh = tmp_path / "curl", tmp_path / "nysh"
    _write_exec(curl_sh, _FAKE_CURL)
    _write_exec(nysh_sh, _FAKE_NYSH)

    zips = tmp_path / "zips"
    zips.mkdir()
    (zips / "pack.zip").write_bytes(_zip_bytes("catalog-2026-05-01"))
    wrong_digest = "sha256:" + "ab" * 32  # 64 hex, свідомо не той

    releases_url = "https://example.invalid/api/releases"
    releases_json = _releases_json([
        _release_block("catalog-2026-05-01", draft=False,
                       asset_name="nyshporka-catalog-2026-05-01.zip",
                       digest=wrong_digest,
                       url="https://example.invalid/dl/pack.zip"),
    ])
    releases_dir = tmp_path / "releases"
    _write_releases_pages(releases_dir, releases_json)

    fetch = _unix_snippet("_sha256() {", "# 🗂 Довідники")
    call_site = _unix_snippet("# 🗂 Довідники", "# ── що змінилось")
    # ⚠ `$0` у блоці задає теку пошуку "поруч лежачого" пака (SEED) — фікстури
    # вище тому НЕ в теці, де лежатиме сам driver-скрипт, інакше SEED знайшов
    # би їх першим і до `_catalog_from_release` узагалі не дійшло б.
    workdir = tmp_path / "work"
    workdir.mkdir()
    driver = workdir / "driver.sh"
    driver.write_text(
        "set -eu\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        f'RELEASES_API="{releases_url}"\n'
        'CATALOG_URL="https://example.invalid/releases"\n'
        'NO_CATALOG="${NYSH_NO_CATALOG:-0}"\n'
        f"{fetch}\n\n{call_site}\n"
        'exit 0\n',
        encoding="utf-8")

    env = _catalog_env(tmp_path, tmp_path)
    env["FAKE_RELEASES_URL_PREFIX"] = releases_url
    env["FAKE_RELEASES_DIR"] = str(releases_dir)
    env["FAKE_ZIP_DIR"] = str(zips)

    import subprocess
    proc = subprocess.run([sh, str(driver)], cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, (
        f"невдала звірка sha256 звалила встановлення:\n{proc.stdout}\n"
        f"{proc.stderr}")
    assert "не збіглася" in proc.stdout, proc.stdout
    assert "довідників поруч немає" in proc.stdout, (
        "після невдачі не показано пораду «взяти … / далі …»:\n" + proc.stdout)

    nysh_log_path = tmp_path / "nysh.log"
    assert not nysh_log_path.exists() or not nysh_log_path.read_text(
        encoding="utf-8").strip(), (
        "«nysh catalog install» покликано на паку з невірною сумою")


def test_catalog_no_catalog_env_skips_the_network_entirely(
        tmp_path: Path) -> None:
    """`NYSH_NO_CATALOG=1` — жодного звернення до GitHub API, навіть перелік."""
    sh = _require_shell_tools()

    curl_sh, nysh_sh = tmp_path / "curl", tmp_path / "nysh"
    _write_exec(curl_sh, _FAKE_CURL)
    _write_exec(nysh_sh, _FAKE_NYSH)

    call_site = _unix_snippet("# 🗂 Довідники", "# ── що змінилось")
    workdir = tmp_path / "work"
    workdir.mkdir()
    driver = workdir / "driver.sh"
    driver.write_text(
        "set -eu\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        'RELEASES_API="https://example.invalid/api/releases"\n'
        'CATALOG_URL="https://example.invalid/releases"\n'
        'NO_CATALOG="${NYSH_NO_CATALOG:-0}"\n'
        f"{call_site}\n"
        'exit 0\n',
        encoding="utf-8")

    env = _catalog_env(tmp_path, tmp_path)
    env["NYSH_NO_CATALOG"] = "1"
    env["FAKE_RELEASES_URL_PREFIX"] = "https://example.invalid/api/releases"
    env["FAKE_RELEASES_DIR"] = str(tmp_path / "releases")  # не читається
    env["FAKE_ZIP_DIR"] = str(tmp_path)

    import subprocess
    proc = subprocess.run([sh, str(driver)], cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "не ставляться (NYSH_NO_CATALOG=1)" in proc.stdout, proc.stdout

    curl_log = tmp_path / "curl.log"
    assert not curl_log.exists(), (
        "NYSH_NO_CATALOG=1 і все одно кликав curl:\n"
        + (curl_log.read_text(encoding="utf-8") if curl_log.exists() else ""))


# ── windows.ps1: той самий пак з останнього релізу catalog-* ─────────────────
# 🔴 Майстер `.exe` везе пак із собою, а `windows.ps1`, завантажений без клону
# (`irm … -OutFile`), — ні: поруч із ним пака не буває, і `nysh find` по
# каталогах архівів мовчав би. Логіка — в одній функції
# `Install-CatalogFromRelease`, щоб приймач міг узяти її з файла розбором AST
# і прогнати окремо від решти інсталятора (той ставить uv і пакет). Мережа
# фальшива: `Invoke-RestMethod` і `Invoke-WebRequest` підміняються функціями
# (функція в PowerShell має перевагу над cmdlet'ом з тим самим іменем),
# `nysh` — фальшивим `Invoke-Logged`.
_PS_CATALOG_DRIVER = r"""
$ErrorActionPreference = 'Stop'
$src = [IO.File]::ReadAllText($env:PS1_PATH)
$e = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$null, [ref]$e)
$fn = $ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Install-CatalogFromRelease' }, $true) | Select-Object -First 1
if (-not $fn) { 'NO-FUNCTION'; exit 3 }
. ([scriptblock]::Create($fn.Extent.Text))

$CatalogApi = 'https://example.invalid/api/releases?per_page=100'
function Say($t, $c = 'White') { Write-Host $t }
function Invoke-RestMethod {
    param([string]$Uri, $TimeoutSec, [switch]$UseBasicParsing)
    Add-Content -LiteralPath $env:FAKE_NET_LOG -Value "api $Uri"
    if ($env:FAKE_API_DOWN -eq '1') { throw 'мережа недоступна' }
    $page = [regex]::Match($Uri, '&page=(\d+)$').Groups[1].Value
    $f = Join-Path $env:FAKE_RELEASES_DIR "page-$page.json"
    if (-not (Test-Path -LiteralPath $f)) { throw "404 $Uri" }
    Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json
}
function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, $TimeoutSec, [switch]$UseBasicParsing)
    Add-Content -LiteralPath $env:FAKE_NET_LOG -Value "dl $Uri"
    $f = Join-Path $env:FAKE_ZIP_DIR ($Uri -split '/')[-1]
    if (-not (Test-Path -LiteralPath $f)) { throw "404 $Uri" }
    Copy-Item -LiteralPath $f -Destination $OutFile
}
function Invoke-Logged {
    param([string]$Exe, [Parameter(ValueFromRemainingArguments)] [object[]]$Arguments)
    Add-Content -LiteralPath $env:FAKE_NYSH_LOG -Value "$Exe $Arguments"
    $mark = Join-Path $Arguments[-1] 'MARK.txt'
    if (Test-Path -LiteralPath $mark) {
        Add-Content -LiteralPath $env:FAKE_NYSH_LOG -Value (Get-Content -LiteralPath $mark -Raw)
    }
    return 0
}

$r = Install-CatalogFromRelease -Nysh 'nysh'
"RESULT:$(@($r).Count):$($r.GetType().Name):$r"
"""


def _powershell() -> str:
    """Windows PowerShell 5.1 там, де він є (саме в ньому інсталятор працює в
    людей), інакше `pwsh`; немає жодного — пропуск."""
    import os
    import shutil

    if os.name == "nt":
        ps51 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) \
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if ps51.exists():
            return str(ps51)
    ps = shutil.which("pwsh") or shutil.which("powershell")
    if ps is None:
        pytest.skip("PowerShell недоступний")
    return ps


def _gh_release(tag: str, *, draft: bool = False, asset: str | None = None,
                digest: str | None = None, url: str | None = None) -> dict:
    rel: dict = {"tag_name": tag, "draft": draft, "assets": []}
    if asset is not None:
        a: dict = {"name": asset, "browser_download_url": url}
        if digest is not None:
            a["digest"] = digest
        rel["assets"].append(a)
    return rel


def _run_ps_catalog(tmp_path: Path, pages: list[list[dict]],
                    zips: dict[str, bytes],
                    extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Проганяє `Install-CatalogFromRelease` проти фальшивого GitHub.

    Повертає відповідь функції, її вивід і журнали мережі та `nysh`."""
    import json
    import os
    import subprocess

    ps = _powershell()
    rel_dir = tmp_path / "releases"
    rel_dir.mkdir()
    for i, page in enumerate(pages, start=1):
        (rel_dir / f"page-{i}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_dir = tmp_path / "zips"
    zip_dir.mkdir()
    for name, data in zips.items():
        (zip_dir / name).write_bytes(data)
    driver = tmp_path / "driver.ps1"
    # BOM — той самий захист від ANSI-читання, що й у самого інсталятора.
    driver.write_text(_PS_CATALOG_DRIVER, encoding="utf-8-sig")

    net_log, nysh_log = tmp_path / "net.log", tmp_path / "nysh.log"
    env = dict(os.environ)
    env.update({"PS1_PATH": str(PS1), "FAKE_RELEASES_DIR": str(rel_dir),
                "FAKE_ZIP_DIR": str(zip_dir), "FAKE_NET_LOG": str(net_log),
                "FAKE_NYSH_LOG": str(nysh_log)})
    env.update(extra_env or {})
    proc = subprocess.run(
        [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver)],
        capture_output=True, timeout=120, env=env)
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    m = re.search(r"RESULT:(\d+):(\w+):(\w+)", out)
    assert proc.returncode == 0 and m, (
        f"драйвер не дійшов до відповіді (код {proc.returncode}):\n{out}\n{err}")
    # 🔴 Відповідь мусить бути ОДНИМ Boolean: зайвий об'єкт у конвеєрі робить
    # з `$false` масив, а непорожній масив для `if` — істина.
    assert (m.group(1), m.group(2)) == ("1", "Boolean"), (
        f"функція писала в конвеєр щось, крім відповіді:\n{out}")
    return {"result": m.group(3), "out": out,
            "net": net_log.read_text(encoding="utf-8") if net_log.exists() else "",
            "nysh": nysh_log.read_text(encoding="utf-8") if nysh_log.exists() else ""}


def _sha256_digest(data: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_ps1_catalog_picks_newest_non_draft_across_pages(tmp_path: Path) -> None:
    """Найновіший недрафтовий `catalog-*`, і лише він, навіть на сторінці 2.

    Сторінка 1 — звичайні релізи й старий `catalog-*`; сторінка 2 —
    новіший і ще новіша ЧЕРНЕТКА; сторінка 3 — порожня (кінець списку).
    """
    old, new = _zip_bytes("catalog-2026-01-01"), _zip_bytes("catalog-2026-09-01")
    page1 = [_gh_release(f"v0.{n}.0") for n in range(1, 4)] + [
        _gh_release("catalog-2026-01-01", asset="nyshporka-catalog-2026-01-01.zip",
                    digest=_sha256_digest(old),
                    url="https://example.invalid/dl/old.zip")]
    page2 = [
        _gh_release("catalog-2026-12-01", draft=True,
                    asset="nyshporka-catalog-2026-12-01.zip",
                    digest="sha256:" + "0" * 64,
                    url="https://example.invalid/dl/draft.zip"),
        _gh_release("catalog-2026-09-01", asset="nyshporka-catalog-2026-09-01.zip",
                    digest=_sha256_digest(new),
                    url="https://example.invalid/dl/new.zip")]
    r = _run_ps_catalog(tmp_path, [page1, page2, []],
                        {"old.zip": old, "new.zip": new})

    assert r["result"] == "True", r["out"]
    assert "page=1" in r["net"] and "page=2" in r["net"], (
        "не гортало сторінок — обмежилось першою:\n" + r["net"])
    assert "dl/new.zip" in r["net"]
    assert "dl/old.zip" not in r["net"] and "dl/draft.zip" not in r["net"], r["net"]
    assert "catalog install --from" in r["nysh"], r["nysh"]
    assert "catalog-2026-09-01" in r["nysh"], (
        "у `nysh catalog install` дійшов не той пак:\n" + r["nysh"])


def test_ps1_catalog_digest_mismatch_is_not_installed(tmp_path: Path) -> None:
    """🔴 Сума не збіглась — `nysh catalog install` не кличеться, відповідь False."""
    page = [_gh_release("catalog-2026-05-01", asset="nyshporka-catalog-2026-05-01.zip",
                        digest="sha256:" + "ab" * 32,
                        url="https://example.invalid/dl/pack.zip")]
    r = _run_ps_catalog(tmp_path, [page], {"pack.zip": _zip_bytes("x")})
    assert r["result"] == "False", r["out"]
    assert "не збіглася" in r["out"], r["out"]
    assert not r["nysh"].strip(), "пак із невірною сумою пішов у встановлення"


def test_ps1_catalog_without_digest_is_not_even_downloaded(tmp_path: Path) -> None:
    """Асет без `digest` — звіряти нічим, тож і качати його нема чого."""
    page = [_gh_release("catalog-2026-05-01", asset="nyshporka-catalog-2026-05-01.zip",
                        url="https://example.invalid/dl/pack.zip")]
    r = _run_ps_catalog(tmp_path, [page], {"pack.zip": _zip_bytes("x")})
    assert r["result"] == "False", r["out"]
    assert "dl/" not in r["net"], "качало асет, який однаково не звірити:\n" + r["net"]
    assert not r["nysh"].strip()


def test_ps1_catalog_network_failure_does_not_throw(tmp_path: Path) -> None:
    """🔴 Мережа лежить — відповідь False, а не виняток.

    Виняток із функції під `$ErrorActionPreference = 'Stop'` дійшов би до
    `trap` інсталятора, і людина, в якої застосунок уже стоїть, побачила б
    «установлення не завершилось».
    """
    r = _run_ps_catalog(tmp_path, [[]], {}, extra_env={"FAKE_API_DOWN": "1"})
    assert r["result"] == "False", r["out"]
    assert "мережа чи ліміт API" in r["out"], r["out"]


def test_ps1_catalog_is_wired_with_opt_out_before_the_advice() -> None:
    """Виклик стоїть між паком «поруч» і старою порадою, і його можна вимкнути.

    Порядок має значення: пак поруч (майстер `.exe`) не підміняється мережею,
    `-NoCatalog` / `NYSH_NO_CATALOG=1` — не ходити в мережу взагалі, а порада
    «взяти / далі» лишається для будь-якої відмови.
    """
    text = ps1_text()
    assert re.search(r"^\s*\[switch\]\$NoCatalog,", text, re.M), (
        "windows.ps1: немає параметра -NoCatalog")
    assert "$env:NYSH_NO_CATALOG -eq '1'" in text, (
        "windows.ps1: не слухає NYSH_NO_CATALOG=1, як unix.sh")
    seed = text.index("if ($seed) {")
    no_cat = text.index("} elseif ($NoCatalog) {", seed)
    fetch = text.index("} elseif (Install-CatalogFromRelease -Nysh $nysh) {", no_cat)
    advice = text.index("довідників поруч немає", fetch)
    assert seed < no_cat < fetch < advice
