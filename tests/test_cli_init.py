"""🧭 `nysh init` — команда, яку виконують рівно один раз, і саме тому вона
найдорожча в помилці.

Тестів на неї не було взагалі. Через це вада прожила довго й тихо: майстер
рахував шлях сам і знав одне джерело з п'яти, тож простір створювався в
типовому місці навіть тоді, коли людина явно назвала інше змінною середовища.
Далі всі команди йшли за драбиною резолвера — тобто в іншу теку, ніж та, яку
щойно створили. Обидві сторони поводились «правильно», а разом давали розлад.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


def _marker(root: Path) -> Path:
    return root / W.MARKER


def test_init_without_a_path_uses_the_variable(monkeypatch, tmp_path: Path) -> None:
    """🔴 Найдорожчий випадок: обидва інсталятори кличуть `nysh init --yes` без
    шляху. Доки майстер не бачив змінної, це означало, що виставлена людиною
    тека мовчки ігнорувалась саме там, де вона не могла це помітити."""
    target = tmp_path / "дослідження"
    monkeypatch.setenv(W.ENV_WORKSPACE, str(target))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "домівка"))

    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])

    assert res.exit_code == 0, res.stdout
    assert _marker(target).is_file()
    # І нічого не з'явилось у типовому місці.
    assert not (tmp_path / "домівка" / "Нишпорка").exists()


def test_init_says_where_the_path_came_from(monkeypatch, tmp_path: Path) -> None:
    """Сенс `Plan.origin`: людина бачить не лише куди, а й чому туди. З `--yes`
    питань немає зовсім, тож цей рядок — єдина нагода помітити чужий шлях."""
    monkeypatch.setenv(W.ENV_WORKSPACE, str(tmp_path / "дослідження"))
    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])
    assert res.exit_code == 0, res.stdout
    assert W.ENV_WORKSPACE in res.stdout


def test_init_inside_a_workspace_does_not_offer_a_new_one(monkeypatch, tmp_path: Path) -> None:
    """`nysh init`, запущений у наявному просторі, пропонував створити новий у
    типовому місці — тобто роздвоював дослідження рівно тим рухом, яким людина
    намагалась його полагодити."""
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    _marker(root).write_text("[workspace]" + chr(10) + "schema = 1" + chr(10),
                             encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "домівка"))

    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])

    assert res.exit_code == 0, res.stdout
    assert "уже існує" in res.stdout
    assert not (tmp_path / "домівка" / "Нишпорка").exists()


def test_init_refuses_a_dangerous_path_from_the_variable(monkeypatch, tmp_path: Path) -> None:
    """Змінна не обходить перевірку кореня, і відмова називає джерело."""
    monkeypatch.setenv(W.ENV_WORKSPACE, str(Path.home()))
    res = runner.invoke(app, ["init", "--yes", "--preset", "catalog"])
    assert res.exit_code == 2
    assert W.ENV_WORKSPACE in res.stdout


def test_doctor_finds_the_workspace_created_a_moment_ago(monkeypatch, tmp_path: Path) -> None:
    """🔴 Рівно два рядки обох інсталяторів, один за одним:

        nysh init --yes --preset researcher
        nysh doctor

    `init` створював простір і забував його; `doctor` — новий процес, стартує з
    іншої теки, без змінної й без маркера над собою, — не мав звідки взяти шлях
    і радив виконати `nysh init`, тобто команду, яку щойно виконали. Останній
    крок успішного встановлення показував червоне.
    """
    import json

    root = tmp_path / "дослідження"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "домівка"))
    assert runner.invoke(app, ["init", "--yes", "--preset", "catalog",
                               str(root)]).exit_code == 0

    # Новий процес: скидаємо все, що жило в пам'яті, і йдемо в сторонню теку.
    W.reset()
    away = tmp_path / "деінде"
    away.mkdir()
    monkeypatch.chdir(away)

    res = runner.invoke(app, ["doctor", "--json"])
    checks = {c["name"]: c for c in json.loads(res.stdout)}
    space = checks["Робочий простір"]

    assert space["level"] != "fail", space
    assert str(root) in space["detail"]
    assert "last-used" in space["detail"]


def test_workspace_is_found_after_a_smoke_run_stole_the_state(monkeypatch,
                                                              tmp_path: Path) -> None:
    """🔴 «Застосунок загубив моє дослідження» — а воно лежить удома.

    Запис «останній відкритий простір» перебиває будь-який `nysh init`, у тому
    числі зроблений смоук-прогоном у тимчасовій теці. Таку теку прибирають, і
    далі драбина джерел не мала куди відступити: змінної немає, маркера над
    поточною текою немає, стан веде в нікуди, а щабля «звичне місце» в
    `resolve()` не було — хоч у `propose()` він є. Тому майстер простір
    знаходив, а кожна команда відповідала «робочий простір не знайдено» про
    дослідження, яке нікуди не зникало.
    """
    import json

    home = tmp_path / "домівка"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    # Дослідження людини — там, куди його кладе майстер.
    mine = home / "Нишпорка"
    assert runner.invoke(app, ["init", "--yes", "--preset", "catalog",
                               str(mine)]).exit_code == 0

    # Смоук-прогін завів свій простір і забрав собі «останній відкритий».
    scratch = tmp_path / "smoke"
    assert runner.invoke(app, ["init", "--yes", "--preset", "catalog",
                               str(scratch)]).exit_code == 0
    shutil.rmtree(scratch)

    W.reset()
    away = tmp_path / "деінде"
    away.mkdir()
    monkeypatch.chdir(away)

    res = runner.invoke(app, ["doctor", "--json"])
    space = {c["name"]: c for c in json.loads(res.stdout)}["Робочий простір"]
    assert space["level"] != "fail", space
    assert str(mine) in space["detail"], space


def test_a_vanished_workspace_is_named_not_just_missed(monkeypatch,
                                                       tmp_path: Path) -> None:
    """Коли відступати нікуди, помилка мусить сказати, що зник саме той шлях.

    «Не знайдено» на місці дослідження, яке ще вчора відкривалось, читається як
    втрата даних. Різниця між «шукати теку» і «шукати бекап» — один рядок.
    """
    home = tmp_path / "домівка"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    scratch = tmp_path / "smoke"
    assert runner.invoke(app, ["init", "--yes", "--preset", "catalog",
                               str(scratch)]).exit_code == 0
    shutil.rmtree(scratch)

    W.reset()
    away = tmp_path / "деінде"
    away.mkdir()
    monkeypatch.chdir(away)

    with pytest.raises(W.WorkspaceError) as exc:
        W.resolve()
    assert str(scratch) in str(exc.value), str(exc.value)


# ── дві найтихіші перевірки доктора ─────────────────────────────────────────
def test_the_doctor_notices_a_workspace_hidden_from_ripgrep(
        tmp_path: Path, monkeypatch) -> None:
    """🔴 Простір усередині git-репо ховає прочитане від `rg`.

    `/reports/` і `/data/` стоять у `.gitignore` пакета, а ripgrep його
    поважає — і віддає порожньо по всій справі, не натякнувши, що теку просто
    не читав. Пошук Нишпорки це не зачіпає, але тягнеться людина (і агент)
    частіше до `rg`, тож хибний нуль приходить саме звідти.
    """
    from nyshporka.core import workspace as W
    from nyshporka.setup import doctor

    repo = tmp_path / "репо"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text("/reports/\n/data/\n", encoding="utf-8")
    space = repo / "простір"
    space.mkdir()

    monkeypatch.setenv(W.ENV_WORKSPACE, str(space))
    res = runner.invoke(app, ["init", "--yes", "--preset", "researcher"])
    assert res.exit_code == 0, res.stdout
    W.reset()

    got = doctor._decode_visible()
    assert got.level == "warn", got
    assert "--no-ignore" in got.fix
    W.reset()


def test_the_doctor_asks_whose_clan_we_are_looking_for(
        tmp_path: Path, monkeypatch) -> None:
    """🔴 Без профілю пошук працює — але на неповному наборі написань.

    Поломка тиха рівно в тому сенсі, який стереже доктор: людина пригадує
    форми сама, половина з них не спадає на думку, і нуль із неповного набору
    виглядає як нуль по всьому роду.

    ⚠ `nysh init` профілю НЕ створює — і це нормальний стан свіжої установки,
    тож рівень тут `warn`, а не `fail`.
    """
    from nyshporka.core import workspace as W
    from nyshporka.setup import doctor

    monkeypatch.setenv(W.ENV_WORKSPACE, str(tmp_path / "простір"))
    res = runner.invoke(app, ["init", "--yes", "--preset", "researcher"])
    assert res.exit_code == 0, res.stdout
    W.reset()

    got = doctor._profile()
    # Порада звіряється початком, а не дослівно: у ній стоїть ще й місце під
    # аргумент («<Прізвище>»), бо команда без нього не виконається — а порада,
    # яку не можна скопіювати й запустити, це та сама половина відповіді.
    assert got.level == "warn" and got.fix.startswith("nysh profile init"), got
    W.reset()
