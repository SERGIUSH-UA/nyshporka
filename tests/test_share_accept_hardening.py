"""Приймання чужого пакета як даних від незнайомця: межі, які не обходяться.

Кожен тест тут — вада, знайдена рев'ю перед запуском Супряги (24.09.2026) і
відтворена на справжньому коді. Пакет збирається руками, а не пакувальником:
приймач мусить стояти й тоді, коли пакет зібрав не наш інструмент.
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from _share import make_run, manifest_for

from nyshporka.share import accept, align, bundle, journal


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


def _htr(space: Path) -> Path:
    d = space / "reports" / "htr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _add(tar: tarfile.TarFile, name: str, blob: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(blob)
    tar.addfile(info, io.BytesIO(blob))


def _hash(texts: dict[str, bytes]) -> str:
    """Хеш змісту голосу — своїм кодом, а не функцією пакета: тест мусить
    лишатись робочим і проти старого коду (перевірка мутацією)."""
    import hashlib

    h = hashlib.sha256()
    for name in sorted(texts):
        h.update(name.encode("utf-8") + bytes([0]) + texts[name] + bytes([0]))
    return h.hexdigest()


def _texts(pages: int = 3) -> dict[str, bytes]:
    return {f"{i:04d}.txt": f"рядок перший сторінки {i}\nВишневецкій Григорій\n".encode()
            for i in range(1, pages + 1)}


def handmade(dest: Path, *, run: str = "spr-8433", pages: int = 3,
             claim_pages: int | None = None, extra_members: dict[str, bytes] | None = None,
             meta: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None,
             voice_hash: str | None = None) -> Path:
    """Пакет, зібраний руками — так, як його міг би зібрати чужий інструмент."""
    texts = _texts(pages)
    voice = {"run": run, "engine": "parseq", "model": "pysar_cyr_v17.pt",
             "script": "cyrillic", "pages": pages, "lines": pages * 2,
             "chars": pages * 40,
             "content_sha256": voice_hash if voice_hash is not None
             else _hash(texts)}
    m = manifest_for([], pages=claim_pages or pages, frames=pages)
    m.decode["voices"] = [voice]
    m.refs = [{"source": "commons", "ref": "file:Test.djvu"}]
    raw = m.as_json()
    if manifest:
        raw.update(manifest)
    with tarfile.open(dest, "w:gz") as tar:
        _add(tar, bundle.MANIFEST_NAME, json.dumps(raw, ensure_ascii=False).encode())
        for name, blob in texts.items():
            _add(tar, f"runs/{run}/{name}", blob)
        _add(tar, f"runs/{run}/{bundle.META_NAME}",
             json.dumps(meta or {"model": "pysar_cyr_v17.pt", "engine": "parseq"},
                        ensure_ascii=False).encode())
        for name, blob in (extra_members or {}).items():
            _add(tar, name, blob)
    return dest


# ── B1: позначки — лише на прийняте ──────────────────────────────────────────

def test_pryiniattia_ne_chipaie_susidnikh_vlasnykh_prohoniv(space: Path, tmp_path: Path) -> None:
    """🔴 Власний `spr-8433-diak_v4` не дістає чужої шифри й позначки «чуже»."""
    own = make_run(_htr(space), "spr-8433-diak_v4", model="diak_cyr_v4.mlmodel",
                   case_key="MY/KEY")
    bulo = (own / bundle.META_NAME).read_text(encoding="utf-8")

    accept.accept(str(handmade(tmp_path / "p.nyshtext")))

    assert (own / bundle.META_NAME).read_text(encoding="utf-8") == bulo


def test_korotke_imia_ne_zakhoplyuie_inshi_spravy(space: Path, tmp_path: Path) -> None:
    root = _htr(space)
    others = [make_run(root, "010241-01-00886"), make_run(root, "010241-01-00912-diak_v4")]
    before = [(d / bundle.META_NAME).read_text(encoding="utf-8") for d in others]

    accept.accept(str(handmade(tmp_path / "p.nyshtext", run="010241")))

    assert [(d / bundle.META_NAME).read_text(encoding="utf-8") for d in others] == before


# ── B2: зіткнення імен ──────────────────────────────────────────────────────

def test_vlasnyi_prohin_bez_rehistru_ne_perezapysuietsia(space: Path, tmp_path: Path) -> None:
    own = make_run(_htr(space), "SPR-1")
    (own / "0001.txt").write_text("СВОЄ", encoding="utf-8")
    pack = handmade(tmp_path / "p.nyshtext", run="spr-1")

    for force in (False, True):
        with pytest.raises(accept.AcceptError, match="ВАШІ"):
            accept.accept(str(pack), force=force)
    assert (own / "0001.txt").read_text(encoding="utf-8") == "СВОЄ"


def test_kintseva_krapka_v_imeni_vidmova_do_zapysu(space: Path, tmp_path: Path) -> None:
    own = make_run(_htr(space), "spr3")
    (own / "0001.txt").write_text("СВОЄ", encoding="utf-8")
    pack = handmade(tmp_path / "p.nyshtext", run="spr-x",
                    extra_members={"runs/spr3./0001.txt": b"CHUZHE"})
    with pytest.raises(accept.AcceptError, match="не можна розкласти"):
        accept.accept(str(pack), force=True)
    assert (own / "0001.txt").read_text(encoding="utf-8") == "СВОЄ"


def test_force_zaminiuie_ranishe_pryiniatyi_i_prybyraie_staryi(space: Path,
                                                                tmp_path: Path) -> None:
    accept.accept(str(handmade(tmp_path / "a.nyshtext", pages=5)))
    run = _htr(space) / "spr-8433"
    assert len(list(run.glob("*.txt"))) == 5

    with pytest.raises(accept.AcceptError, match="--force"):
        accept.accept(str(handmade(tmp_path / "b.nyshtext", pages=3)))
    accept.accept(str(handmade(tmp_path / "b.nyshtext", pages=3)), force=True)
    assert len(list(run.glob("*.txt"))) == 3, "сторінки старого пакета лишились"


# ── B3: ворота міряють вміст ────────────────────────────────────────────────

def test_zaiava_bez_vmistu_ne_prokhodyt(space: Path, tmp_path: Path) -> None:
    """🔴 Один аркуш, заявлений як три тисячі, — хибний нуль оптом."""
    pack = handmade(tmp_path / "p.nyshtext", pages=1, claim_pages=3000,
                    manifest={"frames": {"total": 3000}})
    seen = accept.look(str(pack))
    assert not seen.verdict.passed
    assert any("3000" in r for r in seen.verdict.refusals)


def test_khesh_holosu_ne_toi(space: Path, tmp_path: Path) -> None:
    pack = handmade(tmp_path / "p.nyshtext", voice_hash="0" * 64)
    seen = accept.look(str(pack))
    assert any("хеш змісту" in r for r in seen.verdict.refusals)


# ── B4: білий список і чистка мети на прийманні ────────────────────────────

def test_zaivi_fajly_i_hlybyna_vidmova(space: Path, tmp_path: Path) -> None:
    pack = handmade(tmp_path / "p.nyshtext", extra_members={
        "evil.bat": b"echo", "runs/spr-8433/a/b/deep.txt": b"x"})
    with pytest.raises(accept.AcceptError, match="не можна розкласти"):
        accept.accept(str(pack))
    assert not (_htr(space) / "spr-8433").exists()


def test_heometriia_v_tekstovomu_paketi_ne_liahaie(space: Path, tmp_path: Path) -> None:
    pack = handmade(tmp_path / "p.nyshtext",
                    extra_members={"runs/spr-8433/0001.lines.json": b"{}"})
    accept.accept(str(pack))
    assert not list((_htr(space) / "spr-8433").glob("*.lines.json"))


def test_chuzha_meta_chystytsia(space: Path, tmp_path: Path) -> None:
    pack = handmade(tmp_path / "p.nyshtext", meta={
        "model": "pysar_cyr_v17.pt", "case_dir": "//attacker/share/x",
        "logs": "C:" + "/Users/victim", "control_why": "нотатка", "rss_mb": 5})
    accept.accept(str(pack))
    meta = json.loads((_htr(space) / "spr-8433" / bundle.META_NAME)
                      .read_text(encoding="utf-8"))
    assert "attacker" not in json.dumps(meta)
    assert "logs" not in meta and "control_why" not in meta
    assert meta["shared"]["bundle"] == "p.nyshtext"


def test_bez_mety_prohin_usie_odno_chuzhyi(space: Path, tmp_path: Path) -> None:
    """Пакет без `_htr_meta.json`: позначка «чуже» заводиться з маніфесту."""
    pack = tmp_path / "p.nyshtext"
    handmade(pack)
    with tarfile.open(pack) as src:
        members = [(m, src.extractfile(m).read()) for m in src.getmembers()  # type: ignore[union-attr]
                   if not m.name.endswith(bundle.META_NAME)]
    with tarfile.open(pack, "w:gz") as tar:
        for m, blob in members:
            _add(tar, m.name, blob)
    accept.accept(str(pack))
    meta = json.loads((_htr(space) / "spr-8433" / bundle.META_NAME)
                      .read_text(encoding="utf-8"))
    assert meta["shared"] and meta["model"] == "pysar_cyr_v17.pt"


# ── B5: exact не з одного хеша ──────────────────────────────────────────────

def test_odyn_spilnyi_khesh_ne_exact(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    for i in range(10):
        (case / f"{i:04d}.jpg").write_bytes(b"x" * (i + 1))
    ours = align.frames_of(case, hash_frames=True)
    theirs = [{"n": i, "name": f"x{i}.jpg", "sha256": f"{i:064x}"} for i in range(500)]
    theirs[0]["sha256"] = ours[0]["sha256"]
    got = align.grade(theirs, case, hash_frames=True)
    assert got.label != align.EXACT and not got.can_crop


def test_vidbytok_z_odnym_slotom_ne_exact(tmp_path: Path) -> None:
    from PIL import Image

    from nyshporka.share import fingerprint as FP

    case = tmp_path / "case"
    case.mkdir()
    for i in range(10):
        Image.new("L", (40, 60), color=20 * i).save(case / f"{i:04d}.png")
    mine = FP.fingerprint(case)
    one = {**mine, "slots": [mine["slots"][2]]}
    got = align.grade([], case, their_fp=one)
    assert got.label != align.EXACT


# ── B6: геометрія лише до свого тексту ──────────────────────────────────────

def test_heometriia_ne_liahaie_u_vlasnyi_prohin(space: Path, tmp_path: Path) -> None:
    own = make_run(_htr(space), "mine-run")
    geom = tmp_path / "g.geom.nyshtext"
    m = manifest_for([])
    with tarfile.open(geom, "w:gz") as tar:
        _add(tar, bundle.MANIFEST_NAME, json.dumps(m.as_json()).encode())
        _add(tar, "runs/mine-run/0001.lines.json", b"{}")
    with pytest.raises(accept.AcceptError, match="власний"):
        accept.accept_geometry(str(geom), force=True)
    assert not list(own.glob("*.lines.json"))


# ── B7, B8, B10: вади пакета — названа відмова, нічого на диску ─────────────

@pytest.mark.parametrize("name", ["runs/spr-8433/0002?.txt", "runs/spr-8433/CON.txt",
                                  "runs/spr-8433/a<b.txt"])
def test_nedopustymi_imena_vidmova_do_zapysu(space: Path, tmp_path: Path, name: str) -> None:
    pack = handmade(tmp_path / "p.nyshtext", extra_members={name: b"x"})
    with pytest.raises(accept.AcceptError, match="не можна розкласти"):
        accept.accept(str(pack))
    assert not (_htr(space) / "spr-8433").exists(), "половина пакета лягла на диск"
    assert not journal.read()


@pytest.mark.parametrize("patch", [
    {"decode": {"pages": "abc"}}, {"decode": {"pages": [1]}},
    {"decode": {"lines": 1e400}}, {"schema": [1]},
    {"frames": {"total": "abc"}},
    {"frames": {"total": 3, "fingerprint": {"version": 1, "frames": 3, "slots": ["x"]}}},
    {"frames": {"total": 3, "fingerprint": {"version": 1, "frames": 3,
                                            "slots": [{"phash": 5}]}}},
])
def test_kryvyi_manifest_nazvana_prychyna(space: Path, tmp_path: Path,
                                          patch: dict[str, Any]) -> None:
    pack = handmade(tmp_path / "p.nyshtext", manifest=patch)
    try:
        seen = accept.look(str(pack))
    except accept.AcceptError:
        return
    assert isinstance(seen.verdict.passed, bool)


@pytest.mark.parametrize("blob", [b"not a gzip at all", b"\x1f\x8b\x08\x00trunc"])
def test_ne_paket_nazvana_prychyna(space: Path, tmp_path: Path, blob: bytes) -> None:
    p = tmp_path / "p.nyshtext"
    p.write_bytes(blob)
    with pytest.raises(accept.AcceptError, match="не прочитати пакет"):
        accept.look(str(p))


def test_frames_ne_v_utf8(space: Path, tmp_path: Path) -> None:
    pack = handmade(tmp_path / "p.nyshtext",
                    extra_members={bundle.FRAMES_NAME: b"\xff\xfe\x00"})
    with pytest.raises(accept.AcceptError, match="UTF-8"):
        accept.look(str(pack))


def test_steli_rozmiru(space: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, "MAX_MEMBER_BYTES", 100)
    pack = handmade(tmp_path / "p.nyshtext",
                    extra_members={"runs/spr-8433/0009.txt": b"x" * 1000})
    with pytest.raises(accept.AcceptError, match="стелю"):
        accept.accept(str(pack))


# ── B9: доказ не перезаписується чужим пакетом ──────────────────────────────

def test_dokaz_z_tym_samym_imenem_ne_zatyraiet(space: Path, tmp_path: Path) -> None:
    (tmp_path / "d1").mkdir()
    (tmp_path / "d2").mkdir()
    a = handmade(tmp_path / "d1" / "text.nyshtext", run="r-a")
    b = handmade(tmp_path / "d2" / "text.nyshtext", run="r-b", pages=2)
    pa = Path(accept.accept(str(a))["proof"])
    pb = Path(accept.accept(str(b))["proof"])
    assert pa != pb
    assert bundle.sha256_of(pa) == bundle.sha256_of(a)
    assert bundle.sha256_of(pb) == bundle.sha256_of(b)


# ── B11: завантаження звіряється з каталогом ────────────────────────────────

def test_zavantazhene_ne_zbihaietsia_z_katalohom(space: Path, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import nyshporka.sources.http as H

    real = handmade(tmp_path / "p.nyshtext")

    def _download(self: Any, url: str, dest: Path, **_: Any) -> int:
        dest.write_bytes(real.read_bytes())
        return dest.stat().st_size

    monkeypatch.delenv(H.ENV_OFFLINE, raising=False)
    monkeypatch.setattr(H.Fetcher, "download", _download)
    with pytest.raises(accept.AcceptError, match="не збігається з каталогом"):
        accept.fetch("https://x.example/b/1/text.nyshtext", tmp_path / "in",
                     sha256="0" * 64)
    got = accept.fetch("https://x.example/b/1/text.nyshtext", tmp_path / "in",
                       sha256=bundle.sha256_of(real))
    assert got.is_file()


@pytest.mark.parametrize("slots", [["x"], [{"phash": 5, "at": 0.5}], [{"phash": "ab"}],
                                   [{"at": [1], "phash": "ab"}], "ne-spysok"])
def test_kryvyi_vidbytok_ne_valyt_zvirku(slots: Any) -> None:
    """Чужий відбиток звіряється, лише коли на диску є кадри, — тож і вада
    в ньому спливала лише там, у людини, а не на пакуванні."""
    from nyshporka.share import fingerprint as FP

    mine = {"version": 1, "frames": 3,
            "slots": [{"at": 0.5, "n": 2, "phash": "0" * 36, "sha256": "a"}]}
    zbihlos, zvireno = FP.compare(mine, {"version": 1, "frames": 3, "slots": slots})
    assert zbihlos == zvireno == 0
