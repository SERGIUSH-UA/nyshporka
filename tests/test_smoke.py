"""Пакет установлюється й запускається — те, що доводить крок «скелет».

Приймач тут не `import nyshporka`, а РОБОЧИЙ консольний скрипт: пакет, у якому
імпорт не падає, але `nysh` не запускається, для користувача не існує.
"""
from __future__ import annotations

import subprocess
import sys

from typer.testing import CliRunner

from nyshporka import __version__
from nyshporka.cli import app

runner = CliRunner()


def test_version_command():
    res = runner.invoke(app, ["version"])
    assert res.exit_code == 0
    assert __version__ in res.stdout


def test_info_reports_missing_extras_with_the_fix():
    """Порада має бути ДІЄВОЮ: не «немає», а команда, яка це лагодить.

    🔴 Перевіряється саме наявність назви extra в дужках. Без екранування rich
    з'їдав `[app]` як розмітку, і порада ставала «pip install nyshporka» —
    командою, яка extra НЕ ставить. Користувач виконує її і бачить той самий
    стан, тобто така порада гірша за відсутню.
    """
    res = runner.invoke(app, ["info"])
    assert res.exit_code == 0
    assert "python" in res.stdout
    for label in ("консоль", "архіви", "GEDCOM", "HTR"):
        assert label in res.stdout
    from importlib.util import find_spec

    for module, extra in (("fastapi", "app"), ("aiolimiter", "archives"),
                          ("ged4py", "gedcom"), ("torch", "htr")):
        if find_spec(module) is None:
            assert f"[{extra}]" in res.stdout, (
                f"порада для «{extra}» втратила назву extra — команда не працює")


def test_no_args_shows_help_not_traceback():
    """Голий `nysh` має показати довідку, а не трасу.

    Код виходу 2 — це домовленість typer/click про «неповний виклик», і вона
    доречна: скрипт, що обгортає `nysh` без аргументів, має бачити помилку.
    Важливо інше — що користувач бачить перелік команд, а не стек.
    """
    res = runner.invoke(app, [])
    assert res.exit_code == 2
    out = res.stdout.lower()
    assert "traceback" not in out
    assert "version" in out and "info" in out


def test_console_script_runs_as_subprocess():
    """Найчесніша перевірка встановлюваності — окремий процес, як у користувача."""
    res = subprocess.run([sys.executable, "-m", "nyshporka.cli", "version"],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert __version__ in res.stdout


def test_sources_command_lists_the_local_source():
    res = runner.invoke(app, ["sources"])
    assert res.exit_code == 0
    assert "local" in res.stdout and "manifest" in res.stdout


def test_look_reports_a_folder_of_scans(tmp_path):
    for i in range(3):
        (tmp_path / f"{i:04d}.jpg").write_bytes(b"x" * 10)
    res = runner.invoke(app, ["look", str(tmp_path)])
    assert res.exit_code == 0
    assert "3 кадр" in res.stdout


def test_look_exits_nonzero_on_a_folder_of_cases(tmp_path):
    """🔴 Ненульовий код — щоб скрипт не поїхав далі з «порожньою справою».

    Людина побачить перелік і обере; але автоматика мусить спинитись, інакше
    прогін піде на нуль сторінок і завершиться «успішно».
    """
    (tmp_path / "22").mkdir()
    (tmp_path / "22" / "0001.jpg").write_bytes(b"x")
    res = runner.invoke(app, ["look", str(tmp_path)])
    assert res.exit_code == 1
    assert "не одна справа" in res.stdout


def test_look_on_missing_path_is_a_message_not_a_traceback(tmp_path):
    res = runner.invoke(app, ["look", str(tmp_path / "нема")])
    assert res.exit_code == 1
    assert "traceback" not in res.stdout.lower()
    assert "нічого немає" in res.stdout


def test_core_layer_imports_without_heavy_deps():
    """🔴 `core` не має тягнути ні FastAPI, ні torch.

    Ярусність тут не естетика: щойно ядро почне імпортувати важке, `nysh`
    стартуватиме секундами, а «подивитись каталог справ» вимагатиме 3 ГБ.

    Окремий процес — див. пояснення в `test_cold_core`: читання `sys.modules`
    спільного процесу перевіряло порядок тестів, а не ярусність коду.
    """
    import subprocess

    res = subprocess.run(
        [sys.executable, "-c",
         "import nyshporka.core, sys;"
         " print([h for h in ('fastapi', 'torch') if h in sys.modules])"],
        capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().endswith("[]"), res.stdout
