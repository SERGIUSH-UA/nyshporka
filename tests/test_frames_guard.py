"""🖼 Гард шляху на екрані «Аркуші»: що можна попросити показати.

🔴 Модуль мав НУЛЬ покриття, а `case_dir()` перетворює рядок ІЗ ЗАПИТУ БРАУЗЕРА
на шлях у файловій системі. Це рівно те місце, де відсутність приймача коштує не
незручності: без гарда сюди можна попросити будь-що з диска, а з надто суворим
гардом перестають відкриватись власні теки дослідника на зовнішньому носії.

Обидві межі перевіряються тут, бо вони одна без одної не мають сенсу.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.cases import frames as FR
from nyshporka.core import workspace as W


@pytest.fixture
def space(tmp_path: Path) -> Path:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    for n in range(3):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "нотатки.txt").write_text("не кадр", encoding="utf-8")
    return tmp_path


def test_a_folder_under_raw_opens(space):
    got = FR.case_dir("data/raw/dahmo_315/spr-8433")
    assert got == space / "data" / "raw" / "dahmo_315" / "spr-8433"


@pytest.mark.parametrize("evil", [
    "../../../Windows/System32",
    "/etc",
    "data/raw/../../..",
    "C:/Users",
])
def test_nothing_outside_the_declared_roots_opens(space, evil):
    """🔴 Шлях приходить із запиту, тож «показати» не сміє означати «будь-що».

    Дозволені корені ОГОЛОШЕНІ простором, а не вгадуються з того, що існує.
    """
    with pytest.raises(FR.FrameError):
        FR.case_dir(evil)


def test_an_empty_request_says_what_is_missing(space):
    with pytest.raises(FR.FrameError) as e:
        FR.case_dir("")
    assert "яку справу" in str(e.value)


def test_the_refusal_points_at_the_screen_that_fixes_it(space):
    """Порада мусить бути виконуваною тим, хто її читає.

    Коренями справ керує розділ у налаштуваннях — кнопками, обома напрямками.
    Слати в термінал того, хто про термінал не знає, означає лишити глухий кут.
    """
    with pytest.raises(FR.FrameError) as e:
        FR.case_dir("десь/не/тут")
    msg = str(e.value)
    assert "Корені справ" in msg, msg
    assert "nysh " not in msg, f"порада знову веде в термінал: {msg}"


def test_only_images_count_as_frames(space):
    """Текстова нотатка поруч зі сканами кадром не є."""
    got = FR.images(space / "data" / "raw" / "dahmo_315" / "spr-8433")
    assert [p.name for p in got] == ["0000.jpg", "0001.jpg", "0002.jpg"]


def test_subfolders_are_not_walked(space):
    """🔴 Так само, як їх не обходить раннер.

    Показати те, чого читання не візьме, означає пообіцяти прогін, якого не
    буде: для раннера тека з підтеками порожня.
    """
    d = space / "data" / "raw" / "dahmo_315" / "spr-8433"
    (d / "глибше").mkdir()
    (d / "глибше" / "9999.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    assert len(FR.images(d)) == 3, "кадр із підтеки просочився у видачу"


def test_a_missing_folder_is_empty_not_an_error(space):
    """Відсутня тека — стан, а не поламка: її могли від'єднати разом із диском."""
    assert FR.images(space / "нема") == []
