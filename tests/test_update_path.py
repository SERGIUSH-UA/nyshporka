"""⬆️ Шлях оновлення: він мусить існувати й не брехати про мережу.

Звіт дослідника 29.08.2026 — «і інша вада: шлях до апдейту, зручний і
безболісний». Її не було ніде: ні команди `nysh update`, ні перевірки версії
проти pypi.org, ні рядка в `doctor`; версія показувалась лише в банері старту в
консолі. Ціна не косметична — вона замикає всі інші правки: людина сидить на
збірці, де ваду вже полагоджено, не має звідки про це дізнатись і несе питання
у спільноту.
"""
from __future__ import annotations

import pathlib

import pytest

from nyshporka.setup import update as U


def test_a_newer_release_is_recognised_as_newer():
    assert U.Release("0.6.3", "0.6.4").newer
    assert U.Release("0.6.3", "0.7.0").newer
    assert U.Release("0.9.9", "0.10.0").newer, "0.10 старша за 0.9, а не молодша"
    assert not U.Release("0.6.3", "0.6.3").newer
    assert not U.Release("0.6.4", "0.6.3").newer


def test_the_same_version_written_differently_is_not_an_update():
    """🔴 Помилка в цей бік не мовчить — вона щодня радить оновитись на себе.

    «1.0» і «1.0.0» — та сама версія, але кортежі різної довжини, і (1, 0)
    менше за (1, 0, 0). Без вирівнювання нулями застосунок нескінченно кликав
    би оновлюватись на те, що вже стоїть.
    """
    assert not U.Release("1.0", "1.0.0").newer
    assert not U.Release("1.0.0", "1.0").newer
    # `post` і `dev` зводяться до самої версії — свідомо в бік мовчання.
    assert not U.Release("0.6.3", "0.6.3.post1").newer


def test_a_release_candidate_is_not_newer_than_its_own_release():
    """«0.7.0rc1» не новіший за «0.7.0»: інакше провідні цифри хвоста
    («rc1» → 1) виїжджали б у третю позицію й робили передреліз пізнішим."""
    assert not U.Release("0.7.0", "0.7.0rc1").newer
    assert not U.Release("0.7.0rc1", "0.7.0").newer
    # А от відносно старішої гілки він таки пізніший.
    assert U.Release("0.6.3", "0.7.0rc1").newer


def test_not_asked_is_not_the_same_as_up_to_date():
    """🔴 Третій стан. Мовчазне «все свіже» там, де до мережі не дійшли, — це
    той самий нуль без знаменника, лише про власну версію."""
    silent = U.Release("0.6.3", why="мережа мовчить")
    assert not silent.known, "«не питали» вдає перевірену свіжість"
    assert not silent.newer
    assert U.Release("0.6.3", "0.6.3").known


def test_the_update_command_keeps_the_set_of_parts_it_was_installed_with(monkeypatch):
    """🔴 Набір не вгадується.

    `researcher` тягне рушії читання (~2.5 ГБ), `catalog` — ні. Підставити не
    той означає або змусити платити гігабайтами того, хто прийшов дивитись
    каталог справ, або мовчки зняти рушії в того, хто ними читає.
    """
    monkeypatch.setattr(U, "tool_env", lambda: True)
    assert "nyshporka[app,archives]" in U.command("catalog")
    assert "nyshporka[app,archives,htr]" in U.command("researcher")
    assert "--force" in U.command("catalog"), "оновлення мусить переставляти"


def test_the_installer_trace_is_read_in_both_encodings(tmp_path, monkeypatch):
    """Windows пише слід у UTF-16 (його читає майстер), unix.sh — у UTF-8."""
    monkeypatch.setattr(U, "install_home", lambda: tmp_path)
    for enc in ("utf-16", "utf-8"):
        (tmp_path / U.INSTALL_INFO).write_text(
            "[nyshporka]\nnysh=/x/nysh\nuv=/x/uv\npreset=catalog\n", encoding=enc)
        got = U.install_info()
        assert got.get("preset") == "catalog", f"слід не прочитано з {enc}"
        assert got.get("uv") == "/x/uv"


def test_no_trace_is_a_state_not_a_crash(tmp_path, monkeypatch):
    """Сліду немає (ставили руками, `pip install`) — команда все одно є."""
    monkeypatch.setattr(U, "install_home", lambda: tmp_path)
    monkeypatch.setattr(U, "tool_env", lambda: True)
    assert U.install_info() == {}
    assert U.command()[0] == "uv", "без сліду беремо uv із PATH"


def test_the_checker_never_reaches_the_network_on_its_own():
    """🔴🔴 `PRIVACY.md` обіцяє «фонової активності в мережі немає».

    Приймач структурний: жоден модуль, який виконується сам собою (перевірка
    машини, старт демона), не сміє кликати `latest()`. У мережу йде рівно те,
    що людина натиснула, — операція `update.check` і команда `nysh update`.
    """
    import inspect

    from nyshporka.setup import doctor

    src = inspect.getsource(doctor)
    assert "update.latest" not in src and "import latest" not in src, (
        "doctor поліз у мережу — цього обіцяли не робити")
    # А рядок про версію в ньому є: мовчати про неї теж не можна.
    assert any(c.name == "Версія" for c in doctor.run())


def test_the_version_check_is_reachable_from_a_screen():
    """Операція без входу з екрана — це той самий термінал, лише прихованіший."""
    from nyshporka import ops_builtin  # noqa: F401 — реєстрація операцій
    from nyshporka.core.ops import REGISTRY
    from nyshporka.core.sections import OP_SCREEN

    assert "update.check" in REGISTRY.ops
    assert OP_SCREEN.get("update.check") == "settings"


@pytest.mark.parametrize("check", ["Версія"])
def test_the_machine_report_names_the_version(check):
    """Її не було в `doctor` узагалі — тобто найпростіше питання «що в мене
    стоїть» не мало відповіді на тій самій сторінці, де є всі інші."""
    from nyshporka.setup.doctor import run

    row = next(c for c in run() if c.name == check)
    assert row.op == "update.check", "рядок є, а натиснути нічого"


# ── оновлення й чужі дані ────────────────────────────────────────────────────
# 🔴 `uv tool install --force` перезбирає середовище інструмента цілком. Питання
# не в тому, чи воно щось зносить, — зносить, — а в тому, чи лежить у ньому
# бодай щось із роботи дослідника. Відповідь мусить лишатись «ні», і саме тому
# вона перевіряється, а не приймається на віру: одна тека, переїхавши всередину
# пакета, зробила б оновлення знищенням даних без жодного попередження.


def test_the_update_touches_nothing_of_the_researchers(tmp_path, monkeypatch):
    """Команда оновлення не сміє називати жодного шляху з простору."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(U, "install_home", lambda: tmp_path / "install")
    monkeypatch.setattr(U, "tool_env", lambda: True)
    cmd = U.command("researcher")
    assert all(str(tmp_path) not in part for part in cmd), (
        f"оновлення цілиться в простір: {cmd}")
    # І це саме встановлення пакета, а не щось, що ходить файловою системою.
    assert cmd[1:4] == ["tool", "install", "--python"], cmd


def test_everything_expensive_lives_outside_the_tool_environment(tmp_path):
    """🔴 Чотири речі, втрата яких коштує днів, і жодна не в середовищі пакета.

    Рушії читання (кілька ГБ і довге встановлення), ваги моделей, паки
    довідників і сам простір. Якби бодай одне з них лежало під пакетом,
    `--force` зносив би його мовчки — а людина дізнавалась би про це на
    наступному прогоні.
    """
    from nyshporka.catalog.store import catalog_dir
    from nyshporka.core import workspace as W
    from nyshporka.setup.doctor import engine_venv

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    pkg = pathlib.Path(U.__file__).resolve().parent.parent      # nyshporka/

    for what, path in (("рушії", engine_venv()),
                       ("моделі", tmp_path / "data" / "spotter" / "models"),
                       ("паки довідників", catalog_dir()),
                       ("простір", tmp_path)):
        assert pkg not in path.resolve().parents and path.resolve() != pkg, (
            f"{what} лежать усередині пакета — оновлення їх знесе: {path}")


def test_the_set_of_parts_follows_the_state_not_a_stale_note(monkeypatch):
    """🔴 Доставлені потім рушії не сміють зникнути при оновленні.

    Слід інсталятора фіксує набір НА МОМЕНТ УСТАНОВЛЕННЯ. Хто поставив
    `catalog`, а потім доставив читання, за старим записом дістав би
    `nyshporka[app,archives]` — тобто torch на 2.5 ГБ знявся б мовчки, і
    «Читання» просто зникло б з інтерфейсу.
    """
    monkeypatch.setattr(U, "has_htr", lambda: True)
    assert U.preset_now("catalog") == "researcher"
    assert "nyshporka[app,archives,htr]" in U.command()

    # А чого немає — того й не додаємо: запис лишається джерелом для другого боку.
    monkeypatch.setattr(U, "has_htr", lambda: False)
    assert U.preset_now("catalog") == "catalog"
    assert U.preset_now("researcher") == "researcher"


def test_an_explicit_preset_still_wins():
    """Людина, яка сказала набір руками, головніша за будь-яке визначення."""
    assert "nyshporka[app,archives]" in U.command("catalog")
    assert "nyshporka[app,archives,htr]" in U.command("researcher")


def test_never_asked_is_its_own_answer(tmp_path, monkeypatch):
    """🔴 «Не питали» і «питали, все свіже» — різні відповіді.

    Мовчазний зелений рядок про версію показував би спокій там, де його ніхто
    не перевіряв: людина зі збіркою піврічної давнини бачила б рівно те саме,
    що людина, яка щойно оновилась.
    """
    import time

    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_state_path", lambda: tmp_path / "state.json")
    assert U.days_since_check() is None

    U.mark_checked()
    assert U.days_since_check() == 0

    W.state_set(**{U.STATE_CHECKED: time.time() - 40 * 86400})
    assert U.days_since_check() == 40


def test_a_broken_stamp_reads_as_never_asked(tmp_path, monkeypatch):
    """Битий запис не сміє прикидатись свіжою перевіркою."""
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_state_path", lambda: tmp_path / "state.json")
    W.state_set(**{U.STATE_CHECKED: "вчора"})
    assert U.days_since_check() is None


def test_remembering_a_workspace_does_not_wipe_the_stamp(tmp_path, monkeypatch):
    """🔴 Латентна вада, яку тут і стережемо.

    Єдиний писар стану перезаписував файл ЦІЛКОМ, тож будь-яке друге поле в
    ньому зникало б при наступному відкритті простору — мовчки, бо на вигляд
    стан лишався справним.
    """
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_state_path", lambda: tmp_path / "state.json")
    U.mark_checked()
    W.remember(W.Workspace(root=tmp_path, name="тест", origin="test"))

    assert U.days_since_check() == 0, "запис про перевірку затерли"
    assert W.state_all()["workspace"] == str(tmp_path)


# ── спосіб установки й те, що бачить людина ─────────────────────────────────
# 🔴 Живий прогін 12.09.2026 (чисті venv і ізольована тека інструментів uv)
# знайшов три вади, яких жоден тест вище не бачив: команда оновлення завжди
# була `uv tool install` — і в pip-venv ставила другу копію поруч; надрукований
# рядок губив extras у розмітці rich; на Windows `nysh update` падав на власному
# зайнятому `nysh.exe`, хоча пакет уже переставив.


def test_a_pip_install_is_updated_by_pip_not_by_a_second_uv_tool(tmp_path, monkeypatch):
    """🔴 Середовище без квитанції uv оновлюється тим інтерпретатором, що в ньому."""
    import sys

    monkeypatch.setattr(U, "install_home", lambda: tmp_path / "немає")
    monkeypatch.setattr(U.sys, "prefix", str(tmp_path))
    assert not U.tool_env()
    cmd = U.command("catalog")
    assert cmd[:5] == [sys.executable, "-m", "pip", "install", "--upgrade"], cmd
    assert cmd[-1] == "nyshporka[app,archives]"
    assert not U.runs_in_place(), "pip-середовище оновлюємо не самі"

    (tmp_path / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert U.tool_env(), "квитанцію uv не впізнано"
    assert U.command("catalog")[1:3] == ["tool", "install"]


def test_the_lab_set_keeps_its_training_extra(monkeypatch):
    """🔴 Рушії на місці не сміють опускати `lab` до `researcher`.

    Інакше оновлення мовчки знімало extra `train` — SSH-клієнт трену, — і
    «Лабораторія» падала на першому виносі на свій сервер.
    """
    monkeypatch.setattr(U, "has_htr", lambda: True)
    monkeypatch.setattr(U, "tool_env", lambda: True)
    assert U.preset_now("lab") == "lab"
    assert U.preset_now("amateur") == "amateur"
    assert U.preset_now("catalog") == "researcher", "доставлені рушії лишаються"
    assert "nyshporka[app,archives,htr,train]" in U.command("lab")


def test_windows_never_tries_to_replace_the_running_command(monkeypatch):
    """🔴 `nysh.exe` зайнятий процесом, який саме й кличе оновлення."""
    monkeypatch.setattr(U, "tool_env", lambda: True)
    monkeypatch.setattr(U.sys, "platform", "win32")
    assert not U.runs_in_place()
    monkeypatch.setattr(U.sys, "platform", "linux")
    assert U.runs_in_place()


def _fake_release(monkeypatch):
    monkeypatch.setattr(U, "latest", lambda *a, **k: U.Release("0.1.0", "9.9.9"))


def test_the_printed_command_keeps_its_extras(monkeypatch):
    """🔴 Rich читав `[app,archives]` як розмітку й з'їдав його.

    Людина копіювала `uv tool install … nyshporka` і ставила пакет без консолі:
    після такого «оновлення» `nysh serve` уже не стартував.
    """
    from typer.testing import CliRunner

    from nyshporka.cli import app

    _fake_release(monkeypatch)
    monkeypatch.setattr(U, "tool_env", lambda: True)
    monkeypatch.setattr(U, "has_htr", lambda: False)
    monkeypatch.setattr(U, "install_info", lambda: {"preset": "catalog"})
    got = CliRunner().invoke(app, ["update", "--check"])
    assert got.exit_code == 0, got.output
    assert "nyshporka[app,archives]" in got.output, got.output


def test_update_that_cannot_run_here_names_the_line_and_runs_nothing(monkeypatch):
    """Там, де оновлення на місці не вдасться, команда не кличе нічого."""
    import subprocess

    from typer.testing import CliRunner

    from nyshporka.cli import app

    _fake_release(monkeypatch)
    monkeypatch.setattr(U, "runs_in_place", lambda: False)
    monkeypatch.setattr(U, "install_info", lambda: {"preset": "catalog"})

    def _boom(*_a, **_k):
        raise AssertionError("оновлення запущено там, де воно не може вдатись")

    monkeypatch.setattr(subprocess, "call", _boom)
    got = CliRunner().invoke(app, ["update"])
    assert got.exit_code == 1, got.output
    assert "nyshporka[app,archives]" in got.output
    assert "не ставлю" in got.output
