"""Щільний пакет геометрії: ті самі рамки меншими байтами, і старі двері читання.

Геометрія — 84 % бакета Супряги, а пакет ніс її текстом JSON під gzip. Щільний
запис (`share.geomcodec`) під xz — це 39 % того самого обсягу. Тут сторожиться
єдине, що в цій зміні має значення: приймач отримує РІВНО ті самі рамки, і пакет
від незнайомця не може розгорнутись у пам'ять чи диск без стелі.
"""
from __future__ import annotations

import io
import json
import random
import tarfile
from pathlib import Path
from typing import Any

import pytest
from _share import make_run, manifest_for

from nyshporka.htr import layout as HL
from nyshporka.share import accept, bundle, geomcodec


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


def _storinka(seed: int, lines: int = 40) -> dict[str, Any]:
    """Сторінка, схожа на справжню: полігони по 20–40 точок, рамки, дірки `null`."""
    rnd = random.Random(seed)
    polys: list[Any] = []
    boxes: list[Any] = []
    y = 100
    for i in range(lines):
        if i % 17 == 5:
            polys.append(None)
            boxes.append(None)
            continue
        x, pts = 200 + rnd.randint(-20, 20), []
        for _ in range(rnd.randint(20, 40)):
            x += rnd.randint(1, 60)
            pts.append([x, y + rnd.randint(-6, 6)])
        polys.append(pts)
        boxes.append([200, y - 30, x, y + 30])
        y += rnd.randint(55, 70)
    return {"size": [2480, 3508], "polys": polys, "boxes": boxes,
            "baselines": [[[200, 100], [2000, 104]]], "engine": "kraken"}


# ── кодек ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page", [
    _storinka(1), _storinka(2, lines=1), _storinka(3, lines=0),
    {},                                                    # порожня сторінка
    {"polys": [], "boxes": []},                            # порожні списки
    {"polys": [None, [], [[1, 2]], None]},                 # дірки й порожній полігон
    {"polys": [[[1.5, 2], [3, 4]]], "boxes": [[1, 2, 3, 4]]},   # дробові — у залишку
    {"polys": [[[True, 2], [3, 4]]]},                      # bool — не ціле
    {"polys": [[[1, 2], [3, 4, 5]]]},                      # точки різної довжини
    {"boxes": [[-5, 0, 10 ** 12, -(10 ** 12)]]},           # від'ємні й великі
    {"boxes": [[1, 2 ** 70, 3, 4]]},                      # поза int64 — у залишку
    {"polys": [[[0, 0], [40000, -40000], [1, 1]]]},      # різниці ширші за int16
    {"polys": [[[0, 0], [128, -128], [1, 127], [-126, 0], [10 ** 10, 5]]]},  # межі байта
    {"polys": [[[1, 2]], "рядок", None]},               # не список і не null
    {"z": 1, "polys": [[[9, 9]]], "a": {"вкладене": [1, "два", None]}, "boxes": "рядок"},
])
def test_kodek_povertaie_tu_samu_storinku(page: dict[str, Any]) -> None:
    """🔴 Рівність із типами й порядком ключів: `1 == 1.0 == True` тут не рівність."""
    got = geomcodec.decode_page(geomcodec.encode_page(page))
    assert json.dumps(got, ensure_ascii=False) == json.dumps(page, ensure_ascii=False)


def test_kodek_shchilnishyi_za_json() -> None:
    import lzma
    import zlib

    pages = [_storinka(i) for i in range(30)]
    tekst = "".join(json.dumps(p, ensure_ascii=False) for p in pages).encode()
    shchilno = b"".join(geomcodec.encode_page(p) for p in pages)
    assert len(lzma.compress(shchilno)) < 0.75 * len(zlib.compress(tekst, 6))


def _zapys(head: bytes, tail: bytes = b"") -> bytes:
    return geomcodec.MAGIC + len(head).to_bytes(4, "little") + head + tail


def _u32(*values: int) -> bytes:
    return b"".join(v.to_bytes(4, "little") for v in values)


_HEAD = json.dumps({"k": ["polys"], "p": {"polys": 0}}, separators=(",", ":")).encode()


@pytest.mark.parametrize("raw", [
    b"", b"XXX", geomcodec.MAGIC, geomcodec.MAGIC + b"\x05{}",
    _zapys(b"{}"),                                         # заголовок без полів k/p
    _zapys(b"[1,2]"),                                      # заголовок не об'єкт
    _zapys(b'{"k":["x"],"p":{}}'),                         # щільне поле, якого немає
    _zapys(_HEAD),                                         # потоку поля немає
    _zapys(_HEAD, _u32(1, 1) + _u32(0) + b"z" + _u32(0)),          # тип масиву
    # опис обіцяє полігон на 5 точок, а різниць немає
    _zapys(_HEAD, _u32(4, 1, 2, 5, 2) + _u32(0) + b"h" + _u32(0)),
    # мітка великої різниці є, а самої різниці немає
    _zapys(_HEAD, _u32(3, 1, 1, 1) + _u32(1) + b"\x80" + b"h" + _u32(0)),
    # велика різниця є, а мітки на неї немає
    _zapys(_HEAD, _u32(3, 1, 1, 1) + _u32(1) + b"\x05" + b"h" + _u32(1) + b"\x00\x01"),
])
def test_kodek_vidmovliaie_bytomu_zapysu(raw: bytes) -> None:
    with pytest.raises(geomcodec.GeomCodecError):
        geomcodec.decode_page(raw)


def test_kodek_ne_viryt_lichylnyku() -> None:
    """🔴 Кілька байтів, що оголошують мільярд чисел, не мають виділити пам'ять під них."""
    raw = _zapys(_HEAD, (10 ** 9).to_bytes(4, "little"))
    with pytest.raises(geomcodec.GeomCodecError, match="лічильник"):
        geomcodec.decode_page(raw)
    raw = _zapys(_HEAD, _u32(1, 0) + _u32(10 ** 9))
    with pytest.raises(geomcodec.GeomCodecError, match="лічильник"):
        geomcodec.decode_page(raw)
    raw = _zapys(_HEAD, _u32(1, 0) + _u32(0) + b"q" + _u32(10 ** 9))
    with pytest.raises(geomcodec.GeomCodecError, match="лічильник"):
        geomcodec.decode_page(raw)


def test_kodek_obrizanyi_zapys_vidmovliaie() -> None:
    raw = geomcodec.encode_page(_storinka(4))
    for cut in (len(raw) - 1, len(raw) // 2, 10):
        with pytest.raises(geomcodec.GeomCodecError):
            geomcodec.decode_page(raw[:cut])
    with pytest.raises(geomcodec.GeomCodecError, match="лишились байти"):
        geomcodec.decode_page(raw + b"\x00")


# ── пакет ───────────────────────────────────────────────────────────────────

def _progin(space: Path, pages: int = 4) -> tuple[Path, Any, dict[str, Any]]:
    run = make_run(space / "reports" / "htr", "spr-8433", pages=pages, geometry=True)
    spravzhnie: dict[str, Any] = {}
    for i, stem in enumerate(sorted(HL.geometry_stems(run))):
        HL.write_geometry(run, stem, _storinka(100 + i))
        spravzhnie[stem] = HL.load_geometry(run, stem)
    m = manifest_for([bundle.voice_of(run)], pages=pages, frames=pages)
    return run, m, spravzhnie


def _vmist(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with bundle._open(path) as tar:
        for member in tar.getmembers():
            if member.name.endswith(".lines.json"):
                fh = tar.extractfile(member)
                assert fh is not None
                out[member.name] = json.loads(fh.read().decode("utf-8"))
    return out


def test_shchilnyi_paket_nese_ti_sami_ramky(space: Path, tmp_path: Path) -> None:
    run, m, spravzhnie = _progin(space)
    prostyi, shchilnyi = tmp_path / "a.geom.nyshtext", tmp_path / "b.geom.nyshtext"
    bundle.write(prostyi, m, [run], patterns=bundle.PACKED_GEOM, compact=False)
    bundle.write(shchilnyi, m, [run], patterns=bundle.PACKED_GEOM, compact=True)

    assert not bundle.is_compact(prostyi)
    assert bundle.is_compact(shchilnyi)
    assert shchilnyi.stat().st_size < prostyi.stat().st_size
    assert bundle.members(shchilnyi) == bundle.members(prostyi)
    a, b = _vmist(prostyi), _vmist(shchilnyi)
    assert list(a) == list(b) and len(a) == 4
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)
    for name, page in b.items():
        stem = HL.geometry_stem(Path(name).name)
        assert stem is not None
        assert json.dumps(page, ensure_ascii=False) == json.dumps(spravzhnie[stem], ensure_ascii=False)
    # усередині файла — саме щільні записи, а не JSON під іншим стисненням
    with tarfile.open(shchilnyi, "r:xz") as tar:
        imena = [n for n in tar.getnames() if n.startswith("runs/")]
    assert imena and all(n.endswith(bundle.GEOM_BIN_SUFFIX) for n in imena)


def test_tekstovyi_paket_lyshaietsia_tar_gz(space: Path, tmp_path: Path) -> None:
    """🔴 Текст беруть усі клієнти, зокрема старі: щільним стає лише пакет геометрії."""
    run, m, _ = _progin(space)
    dest = tmp_path / "t.nyshtext"
    bundle.write(dest, m, [run], compact=True)
    assert not bundle.is_compact(dest)
    with tarfile.open(dest, "r:gz") as tar:
        assert any(n.endswith(".txt") for n in tar.getnames())


def test_typovo_paket_ne_shchilnyi(space: Path, tmp_path: Path, monkeypatch: Any) -> None:
    """Старі клієнти щільного не відкриють, тож без явної вимоги він не пишеться."""
    run, m, _ = _progin(space)
    monkeypatch.delenv(bundle.ENV_GEOM_PACK, raising=False)
    a = tmp_path / "a.geom.nyshtext"
    bundle.write(a, m, [run], patterns=bundle.PACKED_GEOM)
    assert not bundle.is_compact(a)
    monkeypatch.setenv(bundle.ENV_GEOM_PACK, "xz")
    b = tmp_path / "b.geom.nyshtext"
    bundle.write(b, m, [run], patterns=bundle.PACKED_GEOM)
    assert bundle.is_compact(b)


def test_shchilna_heometriia_liahaie_na_pryiniatyi_tekst(
        space: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from nyshporka.share import align

    monkeypatch.setattr(accept.align, "grade", lambda *a, **k: align.Alignment(
        align.EXACT, "кадри ті самі (тест)"))
    run, m, spravzhnie = _progin(space, pages=3)
    m.publisher = {"handle": "oksana"}
    text = tmp_path / "pack.nyshtext"
    geom = bundle.geom_path(text)
    bundle.write(text, m, [run])
    bundle.write(geom, m, [run], patterns=bundle.PACKED_GEOM, compact=True)
    for f in run.iterdir():
        f.unlink()
    run.rmdir()

    accept.accept(str(text))
    got = accept.accept_geometry(str(geom))
    assert got["runs"] == ["spr-8433"] and got["pages"] == 3
    run_dir = space / "reports" / "htr" / "spr-8433"
    assert len(list(run_dir.glob("*.lines.json.gz"))) == 3
    for stem, page in spravzhnie.items():
        assert json.dumps(HL.load_geometry(run_dir, stem), ensure_ascii=False) == \
            json.dumps(page, ensure_ascii=False)


def _xz_tar(dest: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(dest, "w:xz") as tar:
        for name, blob in members:
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))


def test_bytyi_shchilnyi_paket_vidmovliaie_z_prychynoiu(tmp_path: Path) -> None:
    dest = tmp_path / "x.geom.nyshtext"
    _xz_tar(dest, [("runs/r/0001.lines.bin", b"ne zapys")])
    with pytest.raises(bundle.BundleError, match=r"0001\.lines\.bin"):
        bundle.members(dest)
    dest.write_bytes(b"\xfd7zXZ\x00" + b"smittia" * 10)
    with pytest.raises(bundle.BundleError, match="не пакет обміну"):
        bundle.members(dest)


def test_shchilnyi_paket_maie_steliu(tmp_path: Path, monkeypatch: Any) -> None:
    """🔴 xz із нулів жметься в тисячі разів: стеля мусить спрацювати на розгортанні."""
    dest = tmp_path / "x.geom.nyshtext"
    _xz_tar(dest, [(f"runs/r/{i:04d}.txt", b"\0" * 4096) for i in range(8)])
    monkeypatch.setattr(bundle, "MAX_TOTAL_BYTES", 16_000)
    with pytest.raises(bundle.BundleError, match="стелю"):
        bundle.members(dest)
    monkeypatch.setattr(bundle, "MAX_TOTAL_BYTES", 4 << 30)
    monkeypatch.setattr(bundle, "MAX_MEMBER_BYTES", 1000)
    with pytest.raises(bundle.BundleError, match="стелю файла"):
        bundle.members(dest)


def test_perekoduvannia_tudy_i_nazad(space: Path, tmp_path: Path) -> None:
    """Сервер пулу робить старий пакет щільним без автора — і може віддати звичайний назад."""
    run, m, _ = _progin(space)
    a, b, c = (tmp_path / f"{n}.geom.nyshtext" for n in "abc")
    bundle.write(a, m, [run], patterns=bundle.PACKED_GEOM, compact=False)
    got = bundle.recode(a, b, compact=True)
    assert got["pages"] == 4 and got["bytes"] == b.stat().st_size < a.stat().st_size
    assert got["sha256"] == bundle.sha256_of(b)
    assert bundle.is_compact(b) and not list(tmp_path.glob("*.part"))
    bundle.recode(b, c, compact=False)
    assert not bundle.is_compact(c)
    with tarfile.open(a, "r:gz") as ta, tarfile.open(c, "r:gz") as tc:
        assert ta.getnames() == tc.getnames()
        for name in ta.getnames():
            fa, fc = ta.extractfile(name), tc.extractfile(name)
            assert fa is not None and fc is not None
            ba, bc = fa.read(), fc.read()
            if name.endswith(".lines.json"):
                assert json.loads(ba) == json.loads(bc)
            else:
                assert ba == bc, name
    assert bundle.read_manifest(b).as_json() == bundle.read_manifest(a).as_json()
