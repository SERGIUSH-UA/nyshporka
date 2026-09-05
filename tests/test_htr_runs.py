"""🚦 Реєстр живих прогонів: чи стає друга справа в чергу.

Скарга, з якої це написано: «запустив дві справи — вони почались паралельно, а
не стали чергою». У застосунку черга була, у командному рядку — ні, і саме
командний рядок несе довгу роботу: прогін ставлять на ніч, часто по ssh.

🔴 Головне, що тут доводиться, — реєстр розрізняє ЧУЖУ справу й ШАРД своєї.
Якби він цього не робив, лікування було б гіршим за хворобу: шардинг однієї
справи (штатний спосіб її прочитати) перестав би працювати взагалі.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def test_a_foreign_case_is_seen_as_busy(space) -> None:
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100", case_key="DAHMO/315/100")
    assert [r.case for r in R.others("spr-200")] == ["spr-100"]


def test_another_shard_of_the_same_case_is_not_a_conflict(space) -> None:
    """🔴 Інакше правка вбила б шардинг — те, чим прогін і прискорюють."""
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100", shard="1/3")
    assert R.others("spr-100") == []


def test_a_dead_entry_is_reaped_by_start_time(space) -> None:
    """🔴 PID перевикористовується, тож сама наявність номера нічого не варта.

    Запис із ЖИВИМ pid, але чужим часом старту, мусить зникнути: інакше через
    тиждень мертвий прогін блокував би справу, бо його номер дістався комусь
    іншому.
    """
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100", created=1.0)
    assert R.alive() == []
    assert R.others("spr-200") == []


def test_the_registry_file_is_cleaned_not_just_filtered(space) -> None:
    """Реап пише на диск, а не лише ховає рядок із відповіді."""
    import json

    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100", created=1.0)
    R.alive()
    assert json.loads(R.path().read_text(encoding="utf-8")) == []


def test_dropping_frees_the_case(space) -> None:
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100")
    assert R.others("spr-200")
    R.drop(os.getpid())
    assert R.others("spr-200") == []


def test_one_pid_holds_one_row(space) -> None:
    """Повторна реєстрація того самого процесу не множить рядків."""
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100")
    R.register(os.getpid(), case="spr-101")
    assert [r.case for r in R.alive()] == ["spr-101"]


def test_a_broken_row_does_not_kill_the_registry(space) -> None:
    """⚠ Битий рядок мусить зникнути мовчки, а не завалити прогін.

    Реєстр — службовий файл; якби його пошкодження спиняло читання, він став би
    новим джерелом відмов замість запобіжника.
    """
    from nyshporka.htr import runs as R

    R.path().parent.mkdir(parents=True, exist_ok=True)
    R.path().write_text('[{"pid": "хто"}, {"нема": 1}]', encoding="utf-8")
    assert R.alive() == []


def test_no_registry_means_nothing_is_running(space) -> None:
    from nyshporka.htr import runs as R

    assert R.alive() == []
    assert R.others("spr-1") == []


def test_the_label_names_the_case_for_a_human(space) -> None:
    """Відмова мусить називати, ЧИМ зайнято, а не просто «зайнято»."""
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="spr-100", case_key="ДАХмО 315-1-100",
               shard="2/3")
    got = R.others("spr-200")[0].label()
    assert "ДАХмО 315-1-100" in got
    assert "2/3" in got
    assert str(os.getpid()) in got
