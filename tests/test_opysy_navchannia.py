"""Матеріал для навчання з робочої теки опису: що їде (перелік дозволених файлів, без локальних
шляхів) і як його перевіряє приймач (той самий код на сервері)."""
from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from nyshporka.opysy import navchannia as NV

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64


def _teka(tmp: Path) -> Path:
    d = tmp / "opys"
    (d / "run").mkdir(parents=True)
    (d / "run-diak_v16").mkdir()
    (d / "dochyt" / "kropy").mkdir(parents=True)
    (d / "dochyt" / "kropy_out").mkdir()
    (d / "pages").mkdir()
    (d / "opys.json").write_text(json.dumps({
        "repo": "ДАОО", "fond": "445", "opys": "5", "form": "hand_ruled", "pages": 2,
        "pdf": "D:/Dokumenty/Ivan Petrenko/opys.pdf", "published": "D:/Dokumenty/Ivan/o.djvu",
        "source": {"kind": "archive_site", "url": "https://archive.example/o.djvu", "page_link": "",
                   "label": "o.djvu", "sha256": "a" * 64}}), encoding="utf-8")
    (d / "opys_meta.json").write_text(json.dumps({"forma": "blank", "sprav": 3}), encoding="utf-8")
    (d / "table.tsv").write_text("page\tno\tno_src\tconfirmed\n0001\t1313\tdobudova\tchain\n",
                                 encoding="utf-8")
    (d / "run" / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v31.pt", "engine": "parseq", "enhance": "auto",
        "case_dir": "D:/Dokumenty/Ivan Petrenko/opys/pages", "device": "cuda:0"}), encoding="utf-8")
    for stem in ("0001", "0002"):
        (d / "run" / f"{stem}.txt").write_text("1313\nДело о ...", encoding="utf-8")
        # mtime=0: `gzip.open` пише в заголовок поточний час, і дві однакові теки різнились би
        (d / "run" / f"{stem}.lines.json.gz").write_bytes(gzip.compress(json.dumps(
            {"size": [1000, 1400], "boxes": [[10, 10, 50, 40]]}).encode(), mtime=0))
        (d / "run-diak_v16" / f"{stem}.txt").write_text("313", encoding="utf-8")
        (d / "pages" / f"{stem}.jpg").write_bytes(JPEG)
    (d / "dochyt" / "dochyt.json").write_text(json.dumps(
        {"0001": {"nomery": [{"id": "0001__n000", "i": 0, "box": [5, 10, 50, 40]}]}}),
        encoding="utf-8")
    (d / "dochyt" / "kropy" / "0001__n000.jpg").write_bytes(JPEG)
    (d / "dochyt" / "kropy_out" / "0001__n000.txt").write_text("313", encoding="utf-8")
    (d / "dochyt" / "kropy_out" / "0001__n000.lines.json.gz").write_bytes(b"x")
    (d / "norm").mkdir()
    (d / "norm" / "model.txt").write_text("agent", encoding="utf-8")
    return d


def _chleny(blob: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        out: dict[str, bytes] = {}
        for m in tar:
            fh = tar.extractfile(m)
            out[m.name] = fh.read() if fh else b""
        return out


def test_zbyraie_dozvolene_bez_lokalnykh_shliakhiv(tmp_path: Path) -> None:
    blob, zvit = NV.zibraty(_teka(tmp_path), paket_sha256="b" * 64, tool="nyshporka test")
    ch = _chleny(blob)
    assert set(ch) == {
        "navchannia.json", "opys.json", "opys_meta.json", "table.tsv",
        "run/model.json", "run/0001.txt", "run/0002.txt", "run/0001.lines.json.gz",
        "run/0002.lines.json.gz", "run-diak_v16/model.json", "run-diak_v16/0001.txt",
        "run-diak_v16/0002.txt", "dochyt/dochyt.json", "dochyt/kropy/0001__n000.jpg",
        "dochyt/kropy_out/0001__n000.txt"}, "сторінки, нормалізація й службове не їдуть"
    vse = b"".join(ch.values()).decode("utf-8", "replace")
    assert "Ivan" not in vse and "D:/Dokumenty" not in vse, "жодного локального шляху"
    assert json.loads(ch["run/model.json"]) == {"model": "pysar_cyr_v31.pt", "engine": "parseq",
                                                "enhance": "auto"}
    pas = json.loads(ch["opys.json"])
    assert pas["source"]["sha256"] == "a" * 64 and "pdf" not in pas and "published" not in pas
    assert zvit.kropiv == 1 and zvit.storinok == 2 and zvit.golosy == ["run", "run-diak_v16"]
    assert NV.perevirka(blob).as_json() == zvit.as_json()
    assert NV.zibraty(_teka(tmp_path / "b"), paket_sha256="b" * 64,
                      tool="nyshporka test")[0] == blob, "ті самі дані — ті самі байти"


def _arkhiv(chleny: dict[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in chleny.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


DOBRYI = {"navchannia.json": json.dumps({"schema": NV.SCHEMA}).encode(), "opys.json": b"{}"}


@pytest.mark.parametrize("chleny, prychyna", [
    ({**DOBRYI, "pages/0001.jpg": JPEG}, "чужий файл"),
    ({**DOBRYI, "../opys.json": b"{}"}, "чужий файл"),
    ({**DOBRYI, "dochyt/kropy/0001__n000.jpg": b"<svg/>"}, "не JPEG"),
    ({**DOBRYI, "dochyt/kropy/0001__n000.jpg": JPEG + b"\0" * NV.MAX_KROP}, "стелю"),
    ({"opys.json": b"{}"}, "немає navchannia.json"),
    ({**DOBRYI, "navchannia.json": json.dumps({"schema": 99}).encode()}, "онови Нишпорку"),
    ({"navchannia.json": DOBRYI["navchannia.json"]}, "немає opys.json"),
])
def test_perevirka_vidkydaie(chleny: dict[str, bytes], prychyna: str) -> None:
    with pytest.raises(NV.NavchanniaError, match=prychyna):
        NV.perevirka(_arkhiv(chleny))


def test_perevirka_ne_arkhiv() -> None:
    with pytest.raises(NV.NavchanniaError, match="не архів"):
        NV.perevirka(b"not a tar")


def test_vlasnyk_zabyraie_peredachi_zi_zvirkoiu(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """`nysh opys peredachi zabraty`: файл лише зі збіглим відбитком, і лише тоді «забрано» (сервер
    прибирає об'єкт зі сховища); відбиток не збігся — файлу немає, сховище не чіпається."""
    import hashlib

    import httpx
    from typer.testing import CliRunner

    from nyshporka.opysy import remote as R
    from nyshporka.opysy.cli import app as opys_app
    from nyshporka.sources import http as H

    dobre, zle = b"%PDF-1.4 skan", b"tar.gz bytes"
    skhovyshche = {"https://r2.example/1": dobre, "https://r2.example/2": b"pidmineno"}
    monkeypatch.setattr(H, "transport", lambda proxy=None: httpx.MockTransport(
        lambda req: httpx.Response(200, content=skhovyshche[str(req.url)])))
    rows = [{"peredacha": 1, "vyd": "skan", "imia": "opys_1_9.pdf", "vnesok": 7,
             "url": "https://r2.example/1", "sha256": hashlib.sha256(dobre).hexdigest(), "bytes": 13},
            {"peredacha": 2, "vyd": "navchannia", "imia": "", "vnesok": 8,
             "url": "https://r2.example/2", "sha256": hashlib.sha256(zle).hexdigest(), "bytes": 12}]
    zabrano: list[tuple[int, str]] = []
    monkeypatch.setattr(R, "peredachi", lambda **kw: {"rows": rows})
    monkeypatch.setattr(R, "peredacha_zabrano",
                        lambda pid, sha, **kw: zabrano.append((pid, sha)) or {})
    monkeypatch.setenv("NYSH_OPYSY", "1")
    res = CliRunner().invoke(opys_app, ["peredachi", "zabraty", str(tmp_path / "z")])
    assert res.exit_code == 1, res.output
    assert (tmp_path / "z" / "skan" / "1-opys_1_9.pdf").read_bytes() == dobre
    assert not list((tmp_path / "z").rglob("2-*")), "чужі байти не лишаються на диску"
    assert zabrano == [(1, hashlib.sha256(dobre).hexdigest())]
