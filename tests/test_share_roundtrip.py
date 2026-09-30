"""Кільце обміну між двома просторами: віддати → знайти → завантажити → прийняти.

🔴 Приймальний сценарій зі звіту користувача 29.09.2026: чужий пакет на ЧИСТІЙ
машині мусить лягти так, щоб текст сторінки знаходив свій скан, а автор,
покриття й причина уривка не губились дорогою. Доти перевірявся лише локальний
огляд пакета, і діра стояла рівно посередині: прийнятий текст називався іменами
кадрів донора, і якщо та сама справа тут лежала під іншими іменами, показати
аркуш до тексту було нічим.

Два простори в одному процесі; пул — у пам'яті, на тих швах, якими клієнт
справді ходить у мережу.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from _share import manifest_for

from nyshporka.core import workspace as W
from nyshporka.share import accept, align, bundle, catalog, journal, upload

BASE = "https://nyshporka.online/v1"
PRYCHYNA = "прочитано лише аркуші шлюбів"
#: id кадрів на сайті архіву — ті самі в обох людей, що качали цю справу.
IDS = (9001, 9002, 9003)


class Pul:
    """Пул у пам'яті: реєстрація → байти → прийняття → пошук → видача."""

    def __init__(self) -> None:
        self.manifest: dict[str, Any] = {}
        self.blobs: dict[str, bytes] = {}
        self.ready = False

    def request(self, method: str, url: str, *, body: Any = None,
                auth: str = "") -> dict[str, Any]:
        if url.endswith("/contributions"):
            self.manifest = dict(body)
            return {"contribution": 7, "upload": {"text": "https://r2.invalid/7/text"}}
        if url.endswith("/complete"):
            assert "https://r2.invalid/7/text" in self.blobs, "байти мусили доїхати"
            self.ready = True
            return {"ready": True, "status": "nove", "contribution": 7}
        raise AssertionError(f"незнайомий запит до пулу: {method} {url}")

    def put(self, url: str, blob: bytes) -> None:
        self.blobs[url] = blob

    @property
    def paket(self) -> bytes:
        return self.blobs["https://r2.invalid/7/text"]

    def get(self, url: str, **kw: Any) -> dict[str, Any]:
        if "/search?" not in url or not self.ready:
            return {"rows": [], "count": 0, "of": 0}
        row = catalog.row_for(
            bundle.Manifest.from_json(self.manifest),
            sha256=hashlib.sha256(self.paket).hexdigest(),
            nbytes=len(self.paket), url=f"{BASE}/d/b/dahmo/315-1-8433/7/text.nyshtext")
        return {"rows": [asdict(row)], "count": 1, "of": 1}

    def download(self, url: str, dest: Path) -> int:
        dest.write_bytes(self.paket)
        return len(self.paket)


@pytest.fixture
def pul(monkeypatch: pytest.MonkeyPatch) -> Pul:
    import nyshporka.sources.http as H

    p = Pul()
    monkeypatch.setattr(upload, "_request", p.request)
    monkeypatch.setattr(upload, "_put", p.put)
    monkeypatch.setattr(upload, "_zapasnyi_put", lambda url, blob, tok: False)
    monkeypatch.setattr(catalog, "_get", p.get)
    monkeypatch.delenv(H.ENV_OFFLINE, raising=False)
    monkeypatch.setattr(H.Fetcher, "download",
                        lambda self, url, dest, **kw: p.download(url, dest))
    return p


def _prostir(root: Path) -> Path:
    W.use(W.Workspace(root=root, name=root.name, origin="test"))
    return root


def _kadry(root: Path, names: list[str]) -> Path:
    d = root / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    for i, name in enumerate(names):
        (d / name).write_bytes(b"JPEG" + bytes([i]) * 16)
    return d


def _prohin(root: Path, stems: list[str], *, geometry: bool = False) -> Path:
    """Прогін, як його лишає раннер: сторінки названі стемами кадрів."""
    d = root / "reports" / "htr" / "spr-8433"
    d.mkdir(parents=True)
    for i, stem in enumerate(stems, 1):
        (d / f"{stem}.txt").write_text(f"аркуш {i}\nВишневецкій Григорій\n",
                                       encoding="utf-8")
        if geometry:
            (d / f"{stem}.lines.json").write_text(
                json.dumps({"size": [2000, 3000], "boxes": [[10, 10 * i, 500, 60]]}),
                encoding="utf-8")
    meta = {"version": 3, "case_key": "DAHMO/315/8433", "model": "pysar_cyr_v17.pt",
            "script": "cyrillic", "engine": "parseq", "frames_total": len(stems),
            "pages": {f"{s}.jpg": {"lines": 2, "chars": 40, "conf": 0.8} for s in stems}}
    (d / bundle.META_NAME).write_text(json.dumps(meta, ensure_ascii=False),
                                      encoding="utf-8")
    return d


def _viddaty(root: Path, tmp_path: Path, *, geometry: bool = False) -> Path:
    """Простір А: справа з ARCHIUM, прогін, пакет — і в пул."""
    _prostir(root)
    stems = [f"{n:04d}_f{i}" for n, i in enumerate(IDS, 1)]
    case_dir = _kadry(root, [f"{s}.jpg" for s in stems])
    run = _prohin(root, stems, geometry=geometry)
    frames = align.frames_of(case_dir)
    m = manifest_for([bundle.voice_of(run)], pages=3, frames=30)
    m.frames = {**align.summary(frames), "total": 30}
    m.publisher = {"handle": "oksana", "contact": "t.me/oksana"}
    m.refs = [{"source": "archium", "ref": "file:35112"}]
    m.extra = {"partial": PRYCHYNA}
    dest = tmp_path / "out" / "paket.nyshtext"
    dest.parent.mkdir()
    bundle.write(dest, m, [run], frames=frames)
    if geometry:
        bundle.write(bundle.geom_path(dest), m, [run], frames=frames,
                     patterns=bundle.PACKED_GEOM)
    got = upload.publish(dest, base=BASE, auth="kliuch")
    assert got["outcome"] == upload.VIDDANO
    return dest


def _chysta_mashyna(root: Path, names: list[str]) -> Path:
    """Простір Б: та сама справа, завантажена самостійно, без жодного прогону."""
    from nyshporka import library as L

    _prostir(root)
    case_dir = _kadry(root, names)
    L.LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    L.LIBRARY_PATH.write_text(json.dumps({"cases": [{
        "key": "DAHMO/315/8433", "repo": "DAHMO", "fond": "315", "opys": "1",
        "spr": "8433", "shifra": "ДАХмО 315-1-8433",
        "path": "data/raw/dahmo_315/spr-8433", "frames": len(names)}]},
        ensure_ascii=False), encoding="utf-8")
    if hasattr(L.load_library, "cache_clear"):
        L.load_library.cache_clear()
    return case_dir


def _pryiniaty() -> dict[str, Any]:
    rows, count, _ = catalog.search("315-1-8433", BASE)
    assert count == 1 and rows[0].shifra == "ДАХмО 315-1-8433"
    return accept.accept(rows[0].url, sha256=rows[0].sha256)


def _meta(root: Path) -> dict[str, Any]:
    return json.loads((root / "reports" / "htr" / "spr-8433" / bundle.META_NAME)
                      .read_text(encoding="utf-8"))


def test_kiltse_tekst_liahaie_na_svii_skan(tmp_path: Path, pul: Pul) -> None:
    """🔴 Ті самі кадри під іншими іменами — текст переходить на місцеві імена."""
    _viddaty(tmp_path / "a", tmp_path)
    b = tmp_path / "b"
    # Ті самі три кадри з того самого архіву, але пронумеровані по-своєму.
    case_dir = _chysta_mashyna(b, [f"{100 + n:04d}_f{i}.jpg" for n, i in enumerate(IDS, 1)])

    got = _pryiniaty()

    assert got["alignment"]["label"] == align.EXACT
    assert got["renamed"] == 3
    run = b / "reports" / "htr" / "spr-8433"
    assert sorted(p.name for p in run.glob("*.txt")) == [
        "0101_f9001.txt", "0102_f9002.txt", "0103_f9003.txt"]
    assert "аркуш 2" in (run / "0102_f9002.txt").read_text(encoding="utf-8")
    meta = _meta(b)
    # Кожна сторінка мети знаходить свій скан у теці справи ЦІЄЇ машини.
    assert Path(meta["case_dir"]) == Path(str(case_dir).replace("\\", "/"))
    assert all((case_dir / name).is_file() for name in meta["pages"])
    # Автор, покриття й причина уривка доїхали.
    mark = meta["shared"]
    assert (mark["from"], mark["shifra"]) == ("oksana", "ДАХмО 315-1-8433")
    assert (mark["pages"], mark["frames"], mark["partial"]) == (3, 30, PRYCHYNA)
    assert mark["alignment"] == align.EXACT
    zapys = journal.read(journal.IMPORTED)[-1]
    assert zapys["publisher"] == "oksana" and zapys["alignment"] == align.EXACT


def test_bez_id_dzherela_imena_ne_vhaduiutsia(tmp_path: Path, pul: Pul) -> None:
    """🔴 Збіглась лише кількість кадрів — текст лишається під іменами донора.

    Покласти його «на кадр за номером» означало б видати здогад за прив'язку:
    текст на сусідньому аркуші гірший за текст без аркуша.
    """
    _viddaty(tmp_path / "a", tmp_path)
    b = tmp_path / "b"
    _chysta_mashyna(b, ["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg"])

    got = _pryiniaty()

    assert got["alignment"]["label"] == align.BY_POSITION
    assert got["renamed"] == 0
    run = b / "reports" / "htr" / "spr-8433"
    assert sorted(p.name for p in run.glob("*.txt")) == [
        "0001_f9001.txt", "0002_f9002.txt", "0003_f9003.txt"]
    assert "page_stems" not in _meta(b)["shared"]


def test_inshi_kadry_toho_samoho_arkhivu_ne_perekladaiutsia(tmp_path: Path, pul: Pul) -> None:
    """Один кадр інший — відповідність не доведена, і не перекладається жоден."""
    _viddaty(tmp_path / "a", tmp_path)
    b = tmp_path / "b"
    _chysta_mashyna(b, ["0101_f9001.jpg", "0102_f9002.jpg", "0103_f7777.jpg"])

    got = _pryiniaty()

    assert got["alignment"]["label"] != align.EXACT and got["renamed"] == 0


def test_heometriia_liahaie_pid_ti_sami_imena(tmp_path: Path, pul: Pul) -> None:
    """Рамки рядків доїжджають другим пакетом — і під ті самі місцеві імена."""
    dest = _viddaty(tmp_path / "a", tmp_path, geometry=True)
    b = tmp_path / "b"
    _chysta_mashyna(b, [f"{100 + n:04d}_f{i}.jpg" for n, i in enumerate(IDS, 1)])
    _pryiniaty()

    accept.accept_geometry(str(bundle.geom_path(dest)), reindex=False)

    run = b / "reports" / "htr" / "spr-8433"
    assert sorted(p.name for p in run.glob("*.lines.json")) == [
        "0101_f9001.lines.json", "0102_f9002.lines.json", "0103_f9003.lines.json"]
    ramky = json.loads((run / "0102_f9002.lines.json").read_text(encoding="utf-8"))
    assert ramky["boxes"][0][1] == 20, "рамки другого аркуша — на другому аркуші"


def test_id_zbihlys_a_zjomka_insha_ne_perekladaie(tmp_path: Path, pul: Pul,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Сильніший доказ (відбиток зйомки) каже «інші кадри» — id самих не досить."""
    _viddaty(tmp_path / "a", tmp_path)
    b = tmp_path / "b"
    _chysta_mashyna(b, [f"{100 + n:04d}_f{i}.jpg" for n, i in enumerate(IDS, 1)])
    monkeypatch.setattr(align, "grade", lambda *a, **kw: align.Alignment(
        align.TEXT_ONLY, "відбиток зйомки не збігся", theirs=3, ours=3))

    got = _pryiniaty()

    assert got["renamed"] == 0
    assert sorted(p.name for p in (b / "reports" / "htr" / "spr-8433").glob("*.txt"))[0] \
        == "0001_f9001.txt"
