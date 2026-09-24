"""Геометрія рядків окремим об'єктом: пакування, приймання, межі.

Рамка рядка прив'язана до пікселів КОНКРЕТНОЇ зйомки. На чужих кадрах вона
ріже кроп не там — тобто геометрія без свого тексту не просто марна, а
шкідлива: помилка виглядає як робота. Звідси все інше в цьому файлі: другий
файл замість прапорця, гард «текст уже мусить бути», переіндекс після.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from _share import make_run, manifest_for

from nyshporka.share import accept, bundle, journal


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


@pytest.fixture(autouse=True)
def _ti_sami_kadry(monkeypatch: Any) -> None:
    """Прив'язка `exact`: геометрія лягає лише на ті самі кадри.

    Тут перевіряється механіка другого об'єкта, а не вимірювання прив'язки —
    воно в `test_share_align`. Відмову на неточній прив'язці сторожить
    `test_heometriia_na_chuzhykh_kadrakh_vidmovliaie`.
    """
    from nyshporka.share import align

    monkeypatch.setattr(accept.align, "grade", lambda *a, **k: align.Alignment(
        align.EXACT, "кадри ті самі (тест)"))


def _pakety(space: Path, tmp_path: Path, *, pages: int = 3) -> tuple[Path, Path]:
    """Текстовий пакет і пакет геометрії тієї самої справи.

    Тека прогону прибирається, щоб приймач не збігся сам із собою, — так само,
    як у `test_share_accept`.
    """
    src = space / "reports" / "htr"
    run = make_run(src, "spr-8433", pages=pages, geometry=True)
    m = manifest_for([bundle.voice_of(run)], pages=pages, frames=pages)
    m.publisher = {"handle": "oksana"}
    text = tmp_path / "pack.nyshtext"
    geom = bundle.geom_path(text)
    bundle.write(text, m, [run])
    bundle.write(geom, m, [run], patterns=bundle.PACKED_GEOM)
    for f in run.iterdir():
        f.unlink()
    run.rmdir()
    return text, geom


# ── пакування ────────────────────────────────────────────────────────────────

def test_pack_pyshe_dva_faily(space: Path, monkeypatch: Any) -> None:
    """Один захід людини — два об'єкти для пулу."""
    from nyshporka.share import publish as PUB

    run = make_run(space / "reports" / "htr", "spr-8433", geometry=True)
    monkeypatch.setattr(PUB, "resolve_runs",
                        lambda scope, **kw: ([run], {"key": "", "shifra": "ДАХмО 315-1-8433"}))

    got = PUB.pack("ДАХмО 315-1-8433")
    assert Path(got["path"]).is_file()
    assert Path(got["geom"]["path"]).is_file()
    assert Path(got["geom"]["path"]).name.endswith(bundle.GEOM_SUFFIX)

    with tarfile.open(got["geom"]["path"]) as tar:
        assert [n for n in tar.getnames() if n.endswith(".lines.json")]


def test_bez_heometrii_tekst_toy_samyi(space: Path, monkeypatch: Any) -> None:
    """🔴 `--no-geometry` не міняє текстовий пакет ні на байт.

    Інакше та сама справа, спакована двічі з різними прапорцями, дала б два
    різні хеші ЗМІСТУ — і пул завів би другий внесок там, де роботи не
    додалось.
    """
    from nyshporka.share import publish as PUB

    run = make_run(space / "reports" / "htr", "spr-8433", geometry=True)
    monkeypatch.setattr(PUB, "resolve_runs",
                        lambda scope, **kw: ([run], {"key": "", "shifra": "ДАХмО 315-1-8433"}))

    z = PUB.pack("ДАХмО 315-1-8433", geometry=True)
    bez = PUB.pack("ДАХмО 315-1-8433", geometry=False)
    assert bez.get("geom") is None
    assert bez["geometry_on_disk"], "на диску вона є — просто не пакувалась"
    assert (z["manifest"]["decode"]["content_sha256"]
            == bez["manifest"]["decode"]["content_sha256"])


# ── приймання ────────────────────────────────────────────────────────────────

def test_heometriia_bez_tekstu_vidmovliaie(space: Path, tmp_path: Path) -> None:
    """🔴 Гард протилежний до текстового: прогін УЖЕ мусить бути."""
    _, geom = _pakety(space, tmp_path)
    with pytest.raises(accept.AcceptError, match="спершу прийміть текст"):
        accept.accept_geometry(str(geom))


def test_heometriia_liahaie_na_pryiniatyi_tekst(space: Path, tmp_path: Path) -> None:
    text, geom = _pakety(space, tmp_path)
    accept.accept(str(text))
    run_dir = space / "reports" / "htr" / "spr-8433"
    assert not list(run_dir.glob("*.lines.json"))

    got = accept.accept_geometry(str(geom))
    assert got["runs"] == ["spr-8433"]
    assert got["pages"] == 3
    assert len(list(run_dir.glob("*.lines.json"))) == 3


def test_heometriia_ne_chipaie_dokazu_pokhodzhennia(space: Path, tmp_path: Path) -> None:
    """🔴 Позначка `shared` каже, ЧИЙ ТЕКСТ лежить у теці, — і лишається.

    Перезаписана іменем geom-файла, вона відповідала б на інше питання —
    «звідки рамки», — і джерело тексту зникло б безслідно.
    """
    text, geom = _pakety(space, tmp_path)
    accept.accept(str(text))
    meta_path = space / "reports" / "htr" / "spr-8433" / bundle.META_NAME
    bulo = json.loads(meta_path.read_text(encoding="utf-8"))["shared"]

    accept.accept_geometry(str(geom))
    stalo = json.loads(meta_path.read_text(encoding="utf-8"))["shared"]
    assert stalo == bulo
    assert stalo["bundle"] == "pack.nyshtext"


def test_pidkynuta_meta_v_geom_paketi_ne_liahaie(space: Path, tmp_path: Path) -> None:
    """🔴 Приймач не вірить чужому tar на слово.

    Пакувальник кладе в geom-пакет лише рамки, але пакет приїхав від людини,
    якої ми не знаємо. Один підкинутий `_htr_meta.json` перетер би позначку
    походження — і прогін тихо став би «прийнятим із geom.nyshtext».
    """
    text, _ = _pakety(space, tmp_path)
    accept.accept(str(text))
    meta_path = space / "reports" / "htr" / "spr-8433" / bundle.META_NAME
    bulo = meta_path.read_text(encoding="utf-8")

    # Зібраний руками пакет: рамки плюс чужа мета.
    ruchnyi = tmp_path / "pidrobka.geom.nyshtext"
    m = manifest_for([])
    with tarfile.open(ruchnyi, "w:gz") as tar:
        bundle._add_bytes(tar, bundle.MANIFEST_NAME,
                          json.dumps(m.as_json(), ensure_ascii=False).encode("utf-8"))
        bundle._add_bytes(tar, f"{bundle.RUNS_SUB}/spr-8433/0001.lines.json",
                          b'{"size": [10, 10], "boxes": []}')
        bundle._add_bytes(tar, f"{bundle.RUNS_SUB}/spr-8433/{bundle.META_NAME}",
                          b'{"shared": {"from": "zlodiy"}}')

    accept.accept_geometry(str(ruchnyi), force=True)
    assert meta_path.read_text(encoding="utf-8") == bulo


def test_povtorna_heometriia_pytaie(space: Path, tmp_path: Path) -> None:
    """Перезапис наявних рамок — рішення людини, а не мовчазний наслідок."""
    text, geom = _pakety(space, tmp_path)
    accept.accept(str(text))
    accept.accept_geometry(str(geom))
    with pytest.raises(accept.AcceptError, match="--force"):
        accept.accept_geometry(str(geom))


def test_povtorna_heometriia_prokhodyt_na_vymohu(space: Path, tmp_path: Path) -> None:
    text, geom = _pakety(space, tmp_path)
    accept.accept(str(text))
    accept.accept_geometry(str(geom))
    got = accept.accept_geometry(str(geom), force=True)
    assert got["overwritten"] == 3


def test_tekstovyi_paket_ne_pryimaietsia_yak_heometriia(
    space: Path, tmp_path: Path
) -> None:
    """Переплутати файли легко; помилка мусить назвати правильну команду."""
    text, _ = _pakety(space, tmp_path)
    with pytest.raises(accept.AcceptError, match="share import"):
        accept.accept_geometry(str(text))


# ── старий формат ────────────────────────────────────────────────────────────

def test_paket_skhemy_1_nese_ramky_vseredyni(space: Path, tmp_path: Path) -> None:
    """🔴 У схемі 1 ті самі поля означали інше — і це мусить бути видно.

    Там геометрія лежала ВСЕРЕДИНІ текстового пакета, а `Voice.geometry`
    казав «пакувальник її туди поклав». Розкладається такий пакет правильно
    (`extract` членів не фільтрує), але прийняти його мовчки за новий не
    можна: окремого geom-пакета до нього не буде ніколи, і той, хто його
    чекатиме, не дочекається без жодної помилки.
    """
    src = space / "reports" / "htr"
    run = make_run(src, "spr-8433", geometry=True)
    m = manifest_for([bundle.voice_of(run)])
    m.schema = 1
    staryi = tmp_path / "staryi.nyshtext"
    # Схема 1 пакувала обидва набори в один файл.
    bundle.write(staryi, m, [run], patterns=(*bundle.PACKED, bundle.PACKED_GEOMETRY))
    for f in run.iterdir():
        f.unlink()
    run.rmdir()

    got = accept.accept(str(staryi))
    assert got["schema"] == 1
    assert len(list((src / "spr-8433").glob("*.lines.json"))) == 3, (
        "рамки старого пакета мусять лягти разом із текстом"
    )


def test_paket_z_maybutnoho_vidmovliaie(space: Path) -> None:
    """Читач старшої версії відмовляє явно, а не розбирає наосліп."""
    with pytest.raises(bundle.BundleError, match="оновити"):
        bundle.Manifest.from_json({"schema": bundle.SCHEMA + 1})


# ── журнал ───────────────────────────────────────────────────────────────────

def test_zhurnal_ne_rakhuie_heometriiu_druhym_pryiomom(
    space: Path, tmp_path: Path
) -> None:
    """🔴 Своя подія, а не `import`.

    Записана тим самим словом, геометрія подвоювала б «справ прийнято»: одна
    справа, два об'єкти — і зведення показувало б удвічі більше роботи, ніж
    її було.
    """
    text, geom = _pakety(space, tmp_path)
    accept.accept(str(text))
    accept.accept_geometry(str(geom))

    assert len(journal.read(journal.GEOMETRY)) == 1
    assert journal.stats()["imported"]["cases"] == 1
