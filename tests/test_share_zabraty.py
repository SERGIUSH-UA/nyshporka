"""`nysh share zabraty`: результат свого виклику — архівами, кожен файл проти sha256.

Найдорожча вада тут — не «не забрав», а «поклав не те»: файл, що не збігся з
переліком сервера, ім'я з архіву, що виводить за межі теки, чи «забрано» для
того, чого в теці немає (сервер тоді прибрав би архів, а людина лишилась би ні
з чим). Тому більшість перевірок — про те, чого НЕ сталося.
"""
from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.share import catalog, zabir
from nyshporka.sources.http import Fetcher, HttpError


def _tar(path: Path, fayly: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w") as tf:
        for imia, vmist in fayly.items():
            info = tarfile.TarInfo(imia)
            info.size = len(vmist)
            tf.addfile(info, io.BytesIO(vmist))
    return path


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


#: Паспорт — непрозорий словник від сервера: клієнт не читає в ньому нічого крім `pidkazka`.
PASPORT = {"pidkazka": "Підказка від сервера", "dovilne": {"a": [1, 2]}, "inshe": "x"}


class Pul:
    """Пул і сховище в пам'яті: стани виклику по черзі, архіви за адресою."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp: Path,
                 kroky: list[tuple[str, list[dict[str, Any]], int]]) -> None:
        self.kroky, self.krok = kroky, 0
        self.arkhivy: dict[str, Path] = {}
        self.zabrano: list[dict[str, str]] = []
        self.skachano: list[str] = []
        self.kudy: list[Path] = []
        self.steli: list[int] = []
        self.tmp = tmp
        #: адреси, що на перше качання відповідають 403 (прострочений підпис)
        self.prostrocheni: set[str] = set()
        #: скільки наступних запитів стану відповідають 503
        self.zboiv = 0
        #: сервер не впізнає хешів цих файлів на «забрано»
        self.ne_vpiznaie: set[str] = set()
        self.rezultativ = 0
        self.bez_rezultatu = False
        monkeypatch.setattr(catalog, "_get", self._get)
        monkeypatch.setattr(zabir, "pidtverdyty", self._pidtverdyty)
        monkeypatch.setattr(Fetcher, "download", self._download)

    def _pidtverdyty(self, vid: int, fayly: dict[str, str], base: str = "") -> dict[str, Any]:
        self.zabrano.append(fayly)
        return {"pidtverdzheno": len(fayly), "ne_zbihlos": sorted(set(fayly) & self.ne_vpiznaie),
                "vse_zabrano": False}

    def paka(self, imia: str, fayly: dict[str, bytes], *, perelik: dict[str, str] | None = None
             ) -> dict[str, Any]:
        url = f"https://store.test/{imia}.tar"
        self.arkhivy[url] = _tar(self.tmp / f"src-{imia}.tar", fayly)
        return {"imia": imia, "bajtiv": 1, "url": url,
                "fayly": perelik or {k: _sha(v) for k, v in fayly.items()}}

    def _get(self, url: str, **kw: Any) -> dict[str, Any]:
        stan, paky, chekaie = self.kroky[min(self.krok, len(self.kroky) - 1)]
        if url.endswith("/rezultat"):
            self.rezultativ += 1
            if self.bez_rezultatu:
                raise catalog.PoolError("HTTP 409", status=409)
            self.krok += 1
            return {"vyklyk": {"id": 7, "stan": stan},
                    "rezultat": {"paky": paky, "chekaie_paky": chekaie,
                                 "pasport": PASPORT}}
        if self.zboiv:
            self.zboiv -= 1
            raise catalog.PoolError("HTTP 503", status=503)
        return {"id": 7, "stan": stan, "vidpovid": {"pomylka": "film_not_found"} if stan == "pomylka" else {}}

    def _download(self, url: str, dest: Path, **kw: Any) -> int:
        self.kudy.append(dest)
        self.steli.append(kw.get("max_bytes", 0))
        if url in self.prostrocheni:
            self.prostrocheni.discard(url)
            raise HttpError("HTTP 403", status=403)
        self.skachano.append(url)
        dest.write_bytes(self.arkhivy[url].read_bytes())
        return dest.stat().st_size


def test_kladetsia_lyshe_zvirene_i_zabrano_lyshe_pokladene(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    dobra = pul.paka("c0-b000", {"0001.jpg": b"a" * 50, "0002.jpg": b"b" * 50})
    pidmina = pul.paka("c0-b001", {"0003.jpg": b"zzz"}, perelik={"0003.jpg": _sha(b"c" * 50)})
    pul.kroky = [("hotovo", [dobra, pidmina], 0)]
    teka = tmp_path / "sprava"

    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)})

    # забрано не все — це не успіх: код виходу ненульовий
    assert not env.ok and env.data is not None
    assert (teka / "0001.jpg").read_bytes() == b"a" * 50
    assert not (teka / "0003.jpg").exists() and not list(teka.glob("*.part"))
    assert env.data["ne_zbihlos"] == ["0003.jpg"]
    assert [w.code for w in env.warnings] == ["ne_zbihlos"]
    # «забрано» — лише для архіву, усі файли якого лягли й збіглися
    assert pul.zabrano == [dobra["fayly"]]
    assert (teka / zabir.PROVENANS).is_file() and not (teka / ".zabir").exists()

    # повтор: покладене не качається вдруге
    pul.skachano.clear()
    O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)})
    assert pul.skachano == [pidmina["url"]]


def test_imena_z_arkhivu_ne_vyvodiat_za_teku(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    zlyi = {"../vtecha.jpg": b"x" * 20, "0001.jpg": b"a" * 20, "zaivyi.exe": b"m"}
    paka = pul.paka("c0-b000", zlyi, perelik={"../vtecha.jpg": _sha(b"x" * 20), "0001.jpg": _sha(b"a" * 20)})
    pul.kroky = [("hotovo", [paka], 0)]
    teka = tmp_path / "t" / "sprava"

    assert O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)}).ok
    assert sorted(p.name for p in teka.iterdir()) == ["0001.jpg", zabir.PROVENANS]
    assert not (tmp_path / "t" / "vtecha.jpg").exists()
    # у переліку для «забрано» — лише безпечне ім'я
    assert pul.zabrano == [{"0001.jpg": _sha(b"a" * 20)}]


def test_stezhyty_bere_nove_doky_vyklyk_zhyvyi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    persha = pul.paka("c0-b000", {"0001.jpg": b"a" * 30})
    druha = pul.paka("c1-b000", {"0201.jpg": b"b" * 30})
    pul.kroky = [("v_roboti", [persha], 2), ("hotovo", [persha, druha], 0)]
    pauzy: list[float] = []
    teka = tmp_path / "sprava"

    zvit = zabir.zabraty(7, teka, stezhyty=True, pauza=5, sleep=pauzy.append)

    assert pauzy == [5] and zvit["stan"] == "hotovo"
    assert sorted(p.name for p in teka.glob("*.jpg")) == ["0001.jpg", "0201.jpg"]
    assert pul.skachano == [persha["url"], druha["url"]]


def test_vyklyk_bez_rezultatu_liudskoiu_vidmovoiu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [("pomylka", [], 0)])
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")})
    assert not env.ok and "film_not_found" in (env.error or "")
    assert pul.skachano == [] and pul.zabrano == []


def test_imena_nebezpechni_na_windows_ne_kladutsia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    zli = ["C:evil.jpg", "NUL.jpg", "con.jpg", "a.jpg:potik", "krapka.", zabir.PROVENANS, ".zabir",
           "0002.jpg.part"]
    fayly = {**{n: b"x" * 10 for n in zli}, "0001.jpg": b"a" * 10}
    pul.kroky = [("hotovo", [pul.paka("c0-b000", fayly)], 0)]
    teka = tmp_path / "sprava"

    assert O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)}).ok
    assert sorted(p.name for p in teka.iterdir()) == ["0001.jpg", zabir.PROVENANS]
    assert pul.zabrano == [{"0001.jpg": _sha(b"a" * 10)}]


def test_imia_arkhivu_vid_servera_ne_vede_za_teku(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    paka = pul.paka("dobra", {"0001.jpg": b"a" * 10})
    pul.kroky = [("hotovo", [{**paka, "imia": "../../vtecha"}], 0)]
    teka = tmp_path / "t" / "sprava"

    assert O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)}).ok
    assert all(d.parent == teka / ".zabir" for d in pul.kudy)
    assert not (tmp_path / "vtecha.tar").exists()


def test_prostrochena_adresa_perepytuie_perelik(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    paka = pul.paka("c0-b000", {"0001.jpg": b"a" * 10})
    pul.kroky = [("hotovo", [paka], 0)]
    pul.prostrocheni = {paka["url"]}

    assert O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")}).ok
    assert pul.rezultativ == 2 and pul.skachano == [paka["url"]]
    # стеля розміру — з розміру, який назвав сервер
    assert pul.steli == [1 + (1 << 20)] * 2


def test_chuzhyi_fail_z_tym_samym_imenem_ne_zatyraietsia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    teka = tmp_path / "sprava"
    teka.mkdir()
    (teka / "0001.jpg").write_bytes(b"inshyi fail")
    pul.kroky = [("hotovo", [pul.paka("c0-b000", {"0001.jpg": b"a" * 10})], 0)]

    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(teka)})
    assert not env.ok and env.data["konflikty"] == ["0001.jpg"]
    assert (teka / "0001.jpg").read_bytes() == b"inshyi fail" and pul.zabrano == []
    assert "konflikty" in [w.code for w in env.warnings]


def test_stysnenyi_arkhiv_i_velykyi_fail_ne_rozpakovuiutsia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    paka = pul.paka("c0-b000", {"0001.jpg": b"a" * 10})
    with tarfile.open(pul.arkhivy[paka["url"]], "w:gz") as tf:
        info = tarfile.TarInfo("0001.jpg")
        info.size = 10
        tf.addfile(info, io.BytesIO(b"a" * 10))
    pul.kroky = [("hotovo", [paka], 0)]
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")})
    assert not env.ok and pul.zabrano == []

    monkeypatch.setattr(zabir, "FAYL_MAKS", 5)
    pul.paka("c0-b000", {"0001.jpg": b"a" * 10})
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s2")})
    assert not env.ok and env.data["ne_zbihlos"] == ["0001.jpg"] and pul.zabrano == []


def test_stezhyty_peresydzhuie_zbii_i_ne_kachaie_zipsovane_bez_kintsia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    zipsovana = pul.paka("c0-b000", {"0001.jpg": b"zzz"}, perelik={"0001.jpg": _sha(b"a")})
    pul.kroky = [("v_roboti", [zipsovana], 1)] * 6 + [("hotovo", [zipsovana], 0)]
    pul.zboiv = 2
    pauzy: list[float] = []

    zvit = zabir.zabraty(7, tmp_path / "s", stezhyty=True, pauza=1, sleep=pauzy.append)

    assert zvit["stan"] == "hotovo" and zvit["ne_zbihlos"] == ["0001.jpg"]
    assert len(pul.skachano) == zabir.SPROB_ARKHIVU and pul.zabrano == []


def test_server_ne_vpiznav_heshiv_tse_ne_zabrano(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    pul.kroky = [("hotovo", [pul.paka("c0-b000", {"0001.jpg": b"a" * 10})], 0)]
    pul.ne_vpiznaie = {"0001.jpg"}
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")})
    assert not env.ok and env.data["arkhiviv"] == 0 and env.data["ne_zbihlos"] == ["0001.jpg"]


def test_skasovanyi_viddaie_skachane_a_bez_skachanoho_vidmova(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pul = Pul(monkeypatch, tmp_path, [])
    pul.kroky = [("skasovano", [pul.paka("c0-b000", {"0001.jpg": b"a" * 10})], 0)]
    assert O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")}).ok
    pul.bez_rezultatu = True
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s2")})
    assert not env.ok and "skasovano" in (env.error or "")


def test_pasport_pyshetsia_tsilkom_a_liudyni_lyshe_pidkazka(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import json

    from typer.testing import CliRunner

    from nyshporka.share.cli import app

    pul = Pul(monkeypatch, tmp_path, [])
    pul.kroky = [("hotovo", [pul.paka("c0-b000", {"0001.jpg": b"a" * 10})], 0)]
    teka = tmp_path / "s"

    vyvid = CliRunner().invoke(app, ["zabraty", "7", "--do", str(teka)])

    assert vyvid.exit_code == 0, vyvid.output
    assert "Підказка від сервера" in vyvid.output
    assert "inshe" not in vyvid.output and "паспорт справи" not in vyvid.output
    zapys = json.loads((teka / zabir.PROVENANS).read_text(encoding="utf-8"))
    assert zapys["pasport"] == PASPORT
