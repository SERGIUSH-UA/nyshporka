"""👁 Гортач: вартість перегляду рахується геометрією, а не бажанням.

Правило, на якому тримається весь пошук: **виявити ≠ перевірити**. Машина подає
кандидата, вирішує око — і другий рушій тут не суддя, бо ознака в пікселях.

Тому дефолт — РЯДОК. Ціла сторінка коштує моделі приблизно вчетверо дорожче за
вирізку рядка (а в байтах на реальному скані різниця виходила в десятки разів),
і при десятках звірок за сеанс це вирішує, скільки їх узагалі відбудеться.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import view as V

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture
def run(tmp_path: Path, monkeypatch):
    """Прогін із однією сторінкою, текстом і рамками рядків."""
    # 🔴 Простір оголошується ПЕРШИМ, до імпорту сховища: `htr_store` бере
    # корені на рівні МОДУЛЯ, тож після його імпорту перемикати вже пізно.
    # Це та сама «застигла константа», через яку тест інакше читав би простір
    # розробника — і зеленів би від чужих даних.
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import htr_store as S

    case = tmp_path / "data" / "raw" / "справа"
    out = tmp_path / "reports" / "htr" / "прогін"
    case.mkdir(parents=True)
    out.mkdir(parents=True)

    img = Image.new("RGB", (600, 400), (250, 248, 244))
    img.save(case / "0001.jpg")

    (out / "0001.txt").write_text("перший рядок\nдругий рядок\nтретій рядок\n",
                                  encoding="utf-8")
    (out / "0001.lines.json").write_text(json.dumps({
        "size": [600, 400],
        "boxes": [[40, 30, 560, 80], [40, 120, 560, 170], [40, 210, 560, 260]],
    }), encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": str(case), "model": "pysar_cyr_v17.pt",
        "engine": "parseq", "script": "cyrillic",
        "pages": {"0001.jpg": {"orient": 0, "lines": 3, "conf": 0.9}},
    }), encoding="utf-8")

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    monkeypatch.setattr(S, "_case_roots", lambda: [tmp_path / "data" / "raw"])
    return "прогін", "0001.jpg"


def test_line_crop_is_far_lighter_than_the_page(run) -> None:
    """🔴 Головна властивість: рядок дешевий, сторінка дорога."""
    name, page = run
    line = V.shot(name, page, line=1)
    whole = V.shot(name, page, region="page")
    assert line.region == "line" and whole.region == "page"
    assert len(line.png) < len(whole.png)
    assert line.height < whole.height


def test_crop_carries_its_own_line_of_text(run) -> None:
    """Разом із пікселями їде саме той рядок, який оцінюють."""
    name, page = run
    assert V.shot(name, page, line=0).text == "перший рядок"
    assert V.shot(name, page, line=2).text == "третій рядок"


def test_pad_widens_the_crop_because_cursive_has_tails(run) -> None:
    """Виносні елементи скоропису («д», «р», «у») виходять за рамку рядка."""
    name, page = run
    tight = V.shot(name, page, line=1, pad=0, annotate=False)
    loose = V.shot(name, page, line=1, pad=30, annotate=False)
    assert loose.width > tight.width and loose.height > tight.height


def test_annotation_marks_which_line_is_being_judged(run) -> None:
    """🔴 Без рамки модель бачить кілька рядків і оцінює НЕ ТОЙ.

    Саме тому `pad` і `annotate` йдуть парою: щойно взяли із запасом — треба
    сказати, який саме рядок питають.
    """
    name, page = run
    plain = V.shot(name, page, line=1, pad=40, annotate=False)
    marked = V.shot(name, page, line=1, pad=40, annotate=True)
    assert plain.png != marked.png, "рамку не домальовано"


def test_missing_boxes_fall_back_to_the_page_and_say_so(run, tmp_path) -> None:
    """Прогони до 2026-08-09 рамок не писали — це не помилка, але й не мовчання.

    Мовчки віддати сторінку замість рядка не можна: вона коштує інакше.
    """
    name, page = run
    (tmp_path / "reports" / "htr" / "прогін" / "0001.lines.json").unlink()
    s = V.shot(name, page, line=1)
    assert s.region == "page"
    assert "рамок" in s.note


def test_line_out_of_range_is_a_message_not_a_crash(run) -> None:
    name, page = run
    with pytest.raises(V.ViewError, match="рядка 9"):
        V.shot(name, page, line=9)


def test_missing_scan_explains_where_it_was_looked_for(run, tmp_path) -> None:
    """Скан міг переїхати; сказати про це треба прямо, а не порожнім екраном."""
    name, page = run
    (tmp_path / "data" / "raw" / "справа" / "0001.jpg").unlink()
    with pytest.raises(V.ViewError, match="скан"):
        V.shot(name, page, line=0)


def test_view_returns_a_data_url_for_the_browser(run) -> None:
    name, page = run
    s = V.shot(name, page, line=0)
    assert s.data_url.startswith("data:image/png;base64,")
    assert "image" not in s.as_dict(), "картинка не має дублюватись у полях"


def test_mcp_sends_the_image_as_an_image_not_as_text() -> None:
    """🔴 Модель не вміє «подивитись» на base64-рядок.

    Якщо картинка їде текстом, звірка оком перетворюється на ще один переказ
    того, що вже сказала машина.
    """
    from nyshporka.core.envelope import ok
    from nyshporka.mcp.server import _pop_image

    env = ok({"line": 3, "image": "data:image/png;base64,QUJD"})
    got = _pop_image(env)
    assert got == ("QUJD", "image/png")
    assert "image" not in env.data, "картинка лишилась ще й у JSON"
