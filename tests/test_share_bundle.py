"""Формат пакета обміну: кільце «спакував → прочитав → розклав».

Приймач кільця — не «не впало», а збіг ТЕКСТУ: рядок, що виїхав із теки
прогону, мусить лягти в теку отримувача незмінним разом зі своїм номером.
Саме на цьому тримається все інше: знайшовши прізвище в чужому пакеті, людина
називає сторінку й рядок, і йде звіряти їх із зображенням у джерелі.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
from _share import make_run, manifest_for

from nyshporka.share import bundle


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def test_round_trip_keeps_text_and_line_numbers(space: Path, tmp_path: Path) -> None:
    src = space / "reports" / "htr"
    run = make_run(src, "spr-8433")
    m = manifest_for([bundle.voice_of(run)])

    dest = tmp_path / "pack.nyshtext"
    bundle.write(dest, m, [run])
    assert dest.is_file()

    back = tmp_path / "taken"
    dirs = bundle.extract(dest, back)
    assert [d.name for d in dirs] == ["spr-8433"]
    for page in sorted(run.glob("*.txt")):
        got = (back / "spr-8433" / page.name).read_text(encoding="utf-8")
        assert got == page.read_text(encoding="utf-8")


def test_manifest_survives_read(space: Path, tmp_path: Path) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433")
    m = manifest_for([bundle.voice_of(run)])
    m.note = "нотатка з апострофом: м'ястківські справи"
    m.extra = {"plivka": "105208823"}
    dest = tmp_path / "pack.nyshtext"
    bundle.write(dest, m, [run])

    got = bundle.read_manifest(dest)
    assert got.shifra == "ДАХмО 315-1-8433"
    assert got.note == m.note
    assert got.extra == {"plivka": "105208823"}
    assert got.pages == 3


def test_heometriia_ide_okremym_faylom(space: Path, tmp_path: Path) -> None:
    """🔴 Два набори взаємовиключні: текст без рамок, рамки без тексту.

    Геометрія важить ×10 і лягає лише тому, у кого ті самі кадри. Всередині
    спільного пакета вона була б платою, яку вносять усі, а користуються нею
    одиниці, — тому окремий об'єкт.
    """
    run = make_run(space / "reports" / "htr", "spr-8433", geometry=True)
    m = manifest_for([bundle.voice_of(run)])

    text = tmp_path / "pack.nyshtext"
    bundle.write(text, m, [run])
    with tarfile.open(text) as tar:
        imena = tar.getnames()
    assert not [n for n in imena if n.endswith(".lines.json")]
    assert [n for n in imena if n.endswith(".txt")]

    geom = tmp_path / "pack.geom.nyshtext"
    bundle.write(geom, m, [run], patterns=bundle.PACKED_GEOM)
    with tarfile.open(geom) as tar:
        imena = tar.getnames()
    assert [n for n in imena if n.endswith(".lines.json")]
    assert not [n for n in imena if n.endswith(".txt")]
    # 🔴 Мети в geom-пакеті немає: вона перетерла б позначку `shared`, тобто
    # доказ, чий текст лежить у теці.
    assert not [n for n in imena if n.endswith(bundle.META_NAME)]


def test_imia_geom_paketa_buduietsia_v_odnomu_mistsi(tmp_path: Path) -> None:
    """Троє будують це ім'я — пакувальник, віддавач і приймач. Правило одне."""
    assert bundle.geom_path(tmp_path / "ДАХмО_315-1-8433.nyshtext").name == (
        "ДАХмО_315-1-8433.geom.nyshtext")
    # Двічі прикладене правило не подвоює розширення: віддавач шукає geom-файл
    # поруч із тим, що йому дали, і дати йому можуть уже geom.
    vzhe = tmp_path / "x.geom.nyshtext"
    assert bundle.geom_path(vzhe) == vzhe


def test_golos_kazhe_pro_disk_a_ne_pro_namir(space: Path) -> None:
    """🔴 `Voice.geometry` — це факт про диск, і саме його читає сервер пулу.

    За ним пул вирішує, чи видавати підписане посилання на другий об'єкт.
    Означало б воно намір пакувальника — і той, хто зібрав текстовий пакет,
    ніколи б геометрії не віддав, хоч вона в нього лежить.
    """
    src = space / "reports" / "htr"
    z_ramkamy = make_run(src, "spr-8433", geometry=True)
    bez = make_run(src, "spr-8434", geometry=False, case_key="DAHMO/315/8434")
    assert bundle.voice_of(z_ramkamy).geometry
    assert not bundle.voice_of(bez).geometry


def test_voices_travel_as_sibling_dirs(space: Path, tmp_path: Path) -> None:
    """Голоси лягають сестринськими теками, як і чекає решта застосунку.

    Складені в одну теку, вони перетирають один одного за іменем файлу — і
    пошук потім чесно віддає нуль без жодної помилки.
    """
    src = space / "reports" / "htr"
    main = make_run(src, "spr-8433")
    voice = make_run(src, "spr-8433-diak_v4", model="diak_cyr_v4.mlmodel")
    m = manifest_for([bundle.voice_of(main),
                      bundle.voice_of(voice)])
    dest = tmp_path / "pack.nyshtext"
    bundle.write(dest, m, [main, voice])

    back = tmp_path / "taken"
    names = sorted(d.name for d in bundle.extract(dest, back))
    assert names == ["spr-8433", "spr-8433-diak_v4"]
    assert (back / "spr-8433-diak_v4" / "0001.txt").is_file()


def test_suggest_name_from_shifra() -> None:
    m = manifest_for([])
    assert bundle.suggest_name(m) == "DAHMO_315-1-8433.nyshtext"


def test_newer_schema_refuses_with_a_reason(tmp_path: Path) -> None:
    """Пакет із майбутнього не розбирається наосліп, а каже, що робити."""
    with pytest.raises(bundle.BundleError, match="оновити"):
        bundle.Manifest.from_json({"schema": bundle.SCHEMA + 1})


def test_readme_carries_the_denominator(space: Path, tmp_path: Path) -> None:
    """Той, хто відкрив пакет без Нишпорки, мусить бачити знаменник."""
    run = make_run(space / "reports" / "htr", "spr-8433")
    m = manifest_for([bundle.voice_of(run)], pages=3, frames=10)
    text = bundle.readme(m)
    assert "кадрів у справі: 10" in text
    assert "сторінок прочитано: 3" in text
