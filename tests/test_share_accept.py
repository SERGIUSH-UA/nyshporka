"""Приймання чужого пакета: кільце цілком і позначка «це не моє».

Приймач кільця — збіг тексту після переїзду плюс те, що прогін уперто
лишається впізнаваним як чужий. Друге важливіше, ніж здається: свій нуль і
чужий нуль — різні відповіді, бо чужий декод читала інша модель, і відповідати
за його повноту тут нікому.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from _share import make_run, manifest_for

from nyshporka.share import accept, bundle, journal


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


def a_bundle(where: Path, dest: Path, *, runs: int = 1) -> Path:
    src = where / "reports" / "htr"
    dirs = [make_run(src, "spr-8433")]
    if runs > 1:
        dirs.append(make_run(src, "spr-8433-diak_v4", model="diak_cyr_v4.mlmodel"))
    m = manifest_for([bundle.voice_of(d) for d in dirs])
    m.refs = [{"source": "commons", "ref": "file:Test.djvu"}]
    m.publisher = {"handle": "oksana", "contact": "t.me/oksana"}
    m.note = "читала Дяком, м'ястківські аркуші наприкінці"
    bundle.write(dest, m, dirs, frames=[{"n": 1, "name": "0001.jpg"}])
    for d in dirs:                      # прибрати джерело, щоб приймач не збігся сам
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    return dest


def test_accept_lands_runs_and_keeps_the_text(space: Path, tmp_path: Path) -> None:
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    got = accept.accept(str(pack))
    assert got["runs"] == ["spr-8433"]
    page = space / "reports" / "htr" / "spr-8433" / "0001.txt"
    assert "Вишневецкій" in page.read_text(encoding="utf-8")


def test_accepted_run_is_marked_as_someone_elses(space: Path, tmp_path: Path) -> None:
    from nyshporka import htr_store as S

    pack = a_bundle(space, tmp_path / "pack.nyshtext", runs=2)
    accept.accept(str(pack))
    for name in ("spr-8433", "spr-8433-diak_v4"):
        meta = json.loads(
            (space / "reports" / "htr" / name / bundle.META_NAME)
            .read_text(encoding="utf-8"))
        assert meta["shared"]["from"] == "oksana"
        assert S.shared_of(meta) == "oksana"


def test_unnamed_publisher_still_counts_as_someone_elses() -> None:
    """Порожнє ім'я не робить чужий прогін своїм."""
    from nyshporka import htr_store as S

    assert S.shared_of({"shared": {"bundle": "x.nyshtext"}}) == "?"
    assert S.shared_of({}) == ""


def test_bundle_is_kept_as_proof(space: Path, tmp_path: Path) -> None:
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    got = accept.accept(str(pack))
    assert Path(got["proof"]).is_file()
    assert Path(got["proof"]).parent == journal.inbox()


def test_import_is_written_down(space: Path, tmp_path: Path) -> None:
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    accept.accept(str(pack))
    rows = journal.read(journal.IMPORTED)
    assert len(rows) == 1
    assert rows[0]["publisher"] == "oksana"
    assert rows[0]["alignment"] == "text-only"


def test_second_import_refuses(space: Path, tmp_path: Path) -> None:
    """Прийняти поверх свого — рішення людини, а не мовчазний наслідок.

    Гард саме такий — «прогону ще НЕ мусить бути», — і протилежний до гарда
    геометрії, яка лягає лише туди, де прогін УЖЕ є (`test_share_geometry`).
    Спільна функція мусила б відмовляти за обома правилами водночас.
    """
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    accept.accept(str(pack))
    with pytest.raises(accept.AcceptError, match="--force"):
        accept.accept(str(pack))


def test_second_import_passes_when_asked_twice(space: Path, tmp_path: Path) -> None:
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    accept.accept(str(pack))
    assert accept.accept(str(pack), force=True)["runs"] == ["spr-8433"]


def test_pakety_z_pulu_ne_pereteryraiut_odyn_odnoho() -> None:
    """🔴 inbox — це доказ, а не кеш.

    У пулі КОЖЕН пакет зветься `b/<справа>/<внесок>/text.nyshtext`. За
    останньою ланкою адреси всі вони лягали б в один `inbox/text.nyshtext`,
    і друга прийнята книга мовчки робила б доказ першої хибним: у журналі
    лишається шлях і sha256, шлях є, байти вже чужі, хеш не сходиться.
    Геометрія додає другий такий самий загальний `geom.nyshtext`.
    """
    cdn = "https://cdn.nyshporka.online"
    a = accept._name_for(f"{cdn}/b/dahmo/315-1-8433/7/text.nyshtext")
    g = accept._name_for(f"{cdn}/b/dahmo/315-1-8433/7/geom.nyshtext")
    # 🔴 Та сама шифра в іншому архіві — інша справа. «315-1-8433 є в кожному
    # другому архіві країни», тож саме цей випадок і має розрізнятись.
    inshyi_arkhiv = accept._name_for(f"{cdn}/b/tsdial/315-1-8433/9/text.nyshtext")
    assert len({a, g, inshyi_arkhiv}) == 3
    assert a.startswith("dahmo-315-1-8433-7")
    assert a.endswith(bundle.SUFFIX) and g.endswith(bundle.SUFFIX)
    # Та сама адреса — те саме ім'я: повторне завантаження не плодить копій.
    assert a == accept._name_for(f"{cdn}/b/dahmo/315-1-8433/7/text.nyshtext")


def test_gates_stop_a_bad_bundle_at_the_door(space: Path, tmp_path: Path) -> None:
    src = space / "reports" / "htr"
    run = make_run(src, "spr-8433", pages=3)
    m = manifest_for([bundle.voice_of(run)])
    m.license = {}                      # пакувальник був не наш
    dest = tmp_path / "bad.nyshtext"
    bundle.write(dest, m, [run])
    with pytest.raises(accept.AcceptError, match="ліценз"):
        accept.accept(str(dest), force=False)


def test_look_does_not_unpack_anything(space: Path, tmp_path: Path) -> None:
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    seen = accept.look(str(pack))
    assert seen.manifest.shifra == "ДАХмО 315-1-8433"
    assert not (space / "reports" / "htr" / "spr-8433").exists()


def test_publishers_note_travels_but_stays_data(space: Path, tmp_path: Path) -> None:
    """Нотатка чужа: вона доїжджає окремим полем, а не змішується з нашим."""
    pack = a_bundle(space, tmp_path / "pack.nyshtext")
    seen = accept.look(str(pack)).as_json()
    assert seen["note"].startswith("читала Дяком")
    assert seen["publisher"]["handle"] == "oksana"
