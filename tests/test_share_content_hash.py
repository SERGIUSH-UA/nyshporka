"""Хеш змісту: те, чого не вміє хеш файла.

🔴 Причина, з якої це поле взагалі заведено: `sha256` пакета ідентифікує
ФАЙЛ, а не прочитане. Той самий прогін, спакований двічі, дає різні байти —
час пакування в маніфесті, `mtime` у членах tar, час у заголовку gzip. Тобто
на питання «це вже віддавали» хеш файла відповісти не може, і найчастіший
повтор — «залив удруге, бо перший раз обірвалось» — без хеша змісту лягає в
пул другим внеском.
"""
from __future__ import annotations

import time
from pathlib import Path

from _share import make_run

from nyshporka.share import bundle


def test_khesh_zmistu_stalyi(tmp_path: Path) -> None:
    """Двічі порахований на тій самій теці — той самий."""
    run = make_run(tmp_path, "prohin", pages=4)
    assert bundle.content_sha256(run) == bundle.content_sha256(run)


def test_khesh_zmistu_perezhyvaie_perepakuvannia(tmp_path: Path) -> None:
    """🔴 Головне: файли різні, зміст той самий.

    Якби цей тест колись почав падати на першому твердженні — значить,
    пакет став відтворюваним, і поле стало зайвим. Це добра новина, але
    дізнатись про неї треба тут, а не на боці пулу.
    """
    run = make_run(tmp_path, "prohin", pages=3)
    voice = bundle.voice_of(run, geometry=False)
    manifest = bundle.Manifest(
        case={"shifra": "ДАХмО 315-1-8433"},
        decode={"pages": voice.pages, "lines": voice.lines, "chars": voice.chars,
                "blank_pages": 0, "voices": [voice.as_json()]},
        frames={"total": 3, "listed": 3, "with_sha256": 0, "with_apid": 0},
        license={"text": "CC0-1.0"},
    )

    a = bundle.write(tmp_path / "a.nyshtext", manifest, [run])
    time.sleep(1.1)   # секунда — крок часу в заголовку gzip і в mtime членів
    b = bundle.write(tmp_path / "b.nyshtext", manifest, [run])

    assert a["sha256"] != b["sha256"], "хеш файла раптом став сталим — див. докстрінг"
    assert bundle.content_sha256(run) == bundle.voice_of(run, geometry=False).content_sha256


def test_khesh_zmistu_lovyt_pravku(tmp_path: Path) -> None:
    """Змінився бодай один символ тексту — змінився хеш."""
    run = make_run(tmp_path, "prohin", pages=3)
    bulo = bundle.content_sha256(run)
    (run / "0002.txt").write_text("зовсім інший текст", encoding="utf-8")
    assert bundle.content_sha256(run) != bulo


def test_khesh_zmistu_ne_zalezhyt_vid_heometrii(tmp_path: Path) -> None:
    """Геометрія не входить: вона похідна від кадрів, а не від прочитаного.

    Практичний бік: той самий текст, спакований раз із геометрією і раз без,
    не має виглядати як два різні внески.
    """
    bez = make_run(tmp_path / "bez", "prohin", pages=3)
    z_heo = make_run(tmp_path / "z", "prohin", pages=3, geometry=True)
    assert bundle.content_sha256(bez) == bundle.content_sha256(z_heo)


def test_khesh_zmistu_v_manifesti(tmp_path: Path) -> None:
    """Поле доїжджає до маніфесту — саме звідти його читає пул."""
    run = make_run(tmp_path, "prohin", pages=3)
    voice = bundle.voice_of(run, geometry=False)
    assert voice.as_json()["content_sha256"] == bundle.content_sha256(run)
