"""Геометрія рядків для гілки голосу: звідки її брати й коли відмовити.

🔴 Прогін пише `.lines.json` лише в основну теку, а голоси отримують самий
текст. Це не пропуск: побічні виходи рахуються з ТІЄЇ САМОЇ сегментації й
вирівняні по масці основного тексту, тож рядок N теки голосу — це рядок N
основної теки. Заміряно на двох кампаніях:

    spr-1283:          txt=366  lines=366
    spr-1283-diak_v4:  txt=366  lines=0

Ціна відсутнього правила: інструмент, що бере текст і рамки з ОДНІЄЇ теки, на
гілці голосу лишається без геометрії й падає, звинувачуючи «старі хмарні
прогони».
"""

from __future__ import annotations

import json
from pathlib import Path

from nyshporka.htr.layout import (
    pages_with_geometry,
    parent_run_dir,
    resolve_geometry,
)


def _run(tmp_path: Path, name: str, *, pages: dict[str, int],
         geometry: bool) -> Path:
    """Тека прогону: на сторінку — текст із заданим числом рядків і, може, рамки."""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    for stem, n_lines in pages.items():
        (directory / f"{stem}.txt").write_text(
            "\n".join(f"рядок {i}" for i in range(n_lines)) + "\n", encoding="utf-8")
        if geometry:
            boxes = [[0, i * 10, 100, i * 10 + 9] for i in range(n_lines)]
            (directory / f"{stem}.lines.json").write_text(
                json.dumps({"size": [100, n_lines * 10], "boxes": boxes}),
                encoding="utf-8")
    return directory


def test_own_geometry_wins(tmp_path: Path) -> None:
    run = _run(tmp_path, "spr-1283", pages={"0005": 12}, geometry=True)
    path, why = resolve_geometry(run, "0005")
    assert path == run / "0005.lines.json" and not why


def test_voice_branch_takes_geometry_from_the_main_run(tmp_path: Path) -> None:
    """🔴 Головний випадок: у гілки голосу рамок немає й бути не має."""
    main = _run(tmp_path, "spr-1283", pages={"0005": 366}, geometry=True)
    voice = _run(tmp_path, "spr-1283-diak_v4", pages={"0005": 366}, geometry=False)

    path, why = resolve_geometry(voice, "0005")

    assert path == main / "0005.lines.json", why
    assert not why


def test_a_mismatch_in_line_count_refuses_instead_of_cropping(tmp_path: Path) -> None:
    """🔴🔴 Мовчки різати не можна. Якщо рядків різна кількість, вирівнювання не
    діє, і рамка під індексом N належала б ІНШОМУ рядку — кроп прийшов би не з
    того місця сторінки. Око цього не спіймає: картинка виглядає осмисленою."""
    _run(tmp_path, "spr-1283", pages={"0005": 366}, geometry=True)
    voice = _run(tmp_path, "spr-1283-diak_v4", pages={"0005": 214}, geometry=False)

    path, why = resolve_geometry(voice, "0005")

    assert path is None
    assert "вирівнювання не діє" in why
    assert "366" in why and "214" in why


def test_a_case_name_with_a_dash_is_not_mistaken_for_a_voice(tmp_path: Path) -> None:
    """Ім'я гілки голосу не відрізнити від імені справи з дефісом (`230-1-2а`),
    тож резолв не вгадує: сусідньої теки з рамками немає — немає й підйому."""
    run = _run(tmp_path, "230-1-2", pages={"0005": 12}, geometry=False)
    path, why = resolve_geometry(run, "0005")
    assert path is None and "немає" in why


def test_missing_page_everywhere_says_where_it_looked(tmp_path: Path) -> None:
    _run(tmp_path, "spr-1283", pages={"0005": 12}, geometry=False)
    voice = _run(tmp_path, "spr-1283-diak_v4", pages={"0005": 12}, geometry=False)
    path, why = resolve_geometry(voice, "0005")
    assert path is None
    assert "spr-1283" in why and "spr-1283-diak_v4" in why


def test_parent_of_a_plain_run_is_none(tmp_path: Path) -> None:
    assert parent_run_dir(Path("reports/htr/spr1283")) is None
    assert parent_run_dir(Path("reports/htr/spr-1283")) == Path("reports/htr/spr")


def test_the_denominator_of_pages_is_visible_for_a_voice(tmp_path: Path) -> None:
    """🔴 «Рамок немає для N сторінок із M» — інше твердження, ніж «входжень
    немає», і плутати їх означає будувати висновок на тихому нулі."""
    _run(tmp_path, "spr-1283", pages={"0001": 5, "0002": 7}, geometry=True)
    voice = _run(tmp_path, "spr-1283-diak_v4", pages={"0001": 5, "0002": 7},
                 geometry=False)
    assert pages_with_geometry(voice) == ["0001", "0002"]
