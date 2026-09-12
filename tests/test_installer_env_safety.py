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
