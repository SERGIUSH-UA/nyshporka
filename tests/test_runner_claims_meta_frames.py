"""🧲 Раннер: клейм у мить народження, спільна мета, знаменник кадрів, стеми.

Аудит 29.09.2026, чотири вади одного роду — кожна робила справу схожою на
прочитану, коли вона такою не була, або читала сторінку двічі:

  · клейм створюється `O_EXCL`, а pid у нього пишеться ПІСЛЯ: сусід, що читав
    клейм у цей проміжок, бачив власника 0 і знімав його як сирітський; так
    само «мертвим» вважався процес, до якого просто немає прав (Windows);
  · злиття партів у спільну мету вважало нечитану попередню мету відсутньою —
    і назавжди губило сторінки до-шардингових прогонів і `case_key`;
  · обхід рахував кадрами TIFF/WebP, а раннер їх не читає: знаменник більший
    за те, що рушій може прочитати, — справа вічно «часткова»;
  · `0001.jpg` і `0001.png` в одній теці пишуть в один `0001.txt`: другий кадр
    рахувався прочитаним.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nyshporka.htr import runner as R


# ── клейм без імені власника ─────────────────────────────────────────────────
def _claims(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / R.CLAIMS_DIR).mkdir(parents=True)
    return out


def test_a_claim_being_written_is_not_an_orphan(tmp_path: Path) -> None:
    """Клейм щойно створено `O_EXCL`, pid ще не записано — власник живий."""
    out = _claims(tmp_path)
    (out / R.CLAIMS_DIR / "0001.claim").write_bytes(b"")
    (out / R.CLAIMS_DIR / "0002.claim").write_text("не-pid", encoding="utf-8")
    assert R.orphan_claims(out) == []
    assert R.release_orphan_claims(out) == 0
    assert (out / R.CLAIMS_DIR / "0001.claim").exists()
    # і для сусіда це чужа зайнята сторінка, а не його пропуск
    assert R.held_by_live_stranger(out) == {"0001", "0002"}


def test_a_nameless_claim_that_grew_old_is_an_orphan(tmp_path: Path) -> None:
    """Процес помер між `O_EXCL` і записом pid — клейм не мусить жити вічно."""
    out = _claims(tmp_path)
    c = out / R.CLAIMS_DIR / "0001.claim"
    c.write_bytes(b"")
    old = time.time() - R.CLAIM_GRACE_S - 60
    os.utime(c, (old, old))
    assert R.orphan_claims(out) == ["0001"]


class _FakeKernel32:
    """OpenProcess відмовляє, як для процесу без прав або неіснуючого pid."""

    def OpenProcess(self, access, inherit, pid):
        return 0

    def GetExitCodeProcess(self, handle, code):
        raise AssertionError("не мало викликатись")

    def CloseHandle(self, handle):
        return 1


@pytest.mark.parametrize(("err", "alive"), [(5, True), (87, False)])
def test_access_denied_is_alive_missing_pid_is_dead(monkeypatch, err, alive) -> None:
    """ERROR_ACCESS_DENIED — процес є, просто не наш; INVALID_PARAMETER — нема."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(R, "_win_kernel32", lambda: _FakeKernel32())
    monkeypatch.setattr(R, "_win_last_error", lambda: err)
    assert R._pid_alive(4242) is alive


# ── спільна мета ─────────────────────────────────────────────────────────────
def _parts(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "_htr_meta.part1.json").write_text(json.dumps(
        {"pages": {"0002.jpg": {"lines": 3}}, "done": True}), encoding="utf-8")


def test_corrupt_shared_meta_is_kept_aside_and_reported(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    _parts(out)
    broken = '{"pages": {"0001.jpg": {"lines": 5}}, "case_key": "DAHMO/1/2"'
    (out / "_htr_meta.json").write_text(broken, encoding="utf-8")

    R.merge_meta(out, {"version": 1, "case_key": ""})

    kept = list(out.glob("_htr_meta.json.corrupt-*"))
    assert len(kept) == 1, "побиту мету перезаписано без копії"
    assert kept[0].read_text(encoding="utf-8") == broken
    merged = json.loads((out / "_htr_meta.json").read_text(encoding="utf-8"))
    assert set(merged["pages"]) == {"0002.jpg"}
    assert "побита" in capsys.readouterr().out


def test_busy_shared_meta_is_reread_not_treated_as_absent(tmp_path: Path,
                                                          monkeypatch) -> None:
    """Перше читання падає (в'ювер тримає) — сторінки й шифра не губляться."""
    out = tmp_path / "out"
    _parts(out)
    shared = out / "_htr_meta.json"
    shared.write_text(json.dumps({"pages": {"0001.jpg": {"lines": 5}},
                                  "case_key": "DAHMO/1/2"}), encoding="utf-8")
    real = Path.read_text
    calls = {"n": 0}

    def busy_once(self, *a, **kw):
        if self == shared:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(13, "зайнято", str(self))
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", busy_once)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    R.merge_meta(out, {"version": 1, "case_key": ""})

    merged = json.loads(real(shared, encoding="utf-8"))
    assert set(merged["pages"]) == {"0001.jpg", "0002.jpg"}
    assert merged["case_key"] == "DAHMO/1/2"


def test_unreadable_shared_meta_is_left_untouched(tmp_path: Path, monkeypatch) -> None:
    """Не прочиталась і після повторів — злиття пропускається, файл не чіпаємо."""
    out = tmp_path / "out"
    _parts(out)
    shared = out / "_htr_meta.json"
    body = json.dumps({"pages": {"0001.jpg": {"lines": 5}}, "case_key": "DAHMO/1/2"})
    shared.write_text(body, encoding="utf-8")
    real = Path.read_text

    def always_busy(self, *a, **kw):
        if self == shared:
            raise PermissionError(13, "зайнято", str(self))
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", always_busy)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    R.merge_meta(out, {"version": 1, "case_key": ""})
    assert real(shared, encoding="utf-8") == body


# ── знаменник кадрів ─────────────────────────────────────────────────────────
def test_frame_ext_parity() -> None:
    """Раннер тримає дзеркало набору пакета — вони не мають розійтись мовчки."""
    from nyshporka.cases.walk import READ_EXT

    assert R.FRAME_EXT == READ_EXT


def _mixed(root: Path) -> Path:
    d = root / "case"
    d.mkdir(parents=True)
    for n in range(1, 4):
        (d / f"{n:04}.jpg").write_bytes(b"x")
    (d / "cover.tif").write_bytes(b"x")          # обкладинка, рушій її не читає
    (d / "colorcheck.webp").write_bytes(b"x")
    return d


def test_all_counters_agree_on_a_mixed_folder(tmp_path: Path, monkeypatch) -> None:
    """Обхід, пряме читання теки, сховище сторінок і раннер — одне число."""
    from nyshporka.cases import collect as C
    from nyshporka.cases.walk import scan_dir
    from nyshporka.pagestore import store as S

    d = _mixed(tmp_path)
    scan = scan_dir(d, tmp_path, ("case",), 1)
    assert scan.n_frames == 3

    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "_FRAMES_INDEX", {})
    assert C._count_frames_exact("case") == (3, True)
    monkeypatch.setattr(C, "_FRAMES_INDEX", C._frames_index([scan]))
    assert C._count_frames_exact("case") == (3, True)

    monkeypatch.setattr(S, "ROOT", tmp_path)
    assert S._disk_scans(SimpleNamespace(path="case")) == [
        "0001.jpg", "0002.jpg", "0003.jpg"]

    assert len(R.select_pages(d, "", 0, 0, 1)) == 3


def test_a_tiff_only_folder_is_still_material(tmp_path: Path) -> None:
    """Самі TIFF — матеріал, ще не перегнаний, а не порожня картка."""
    from nyshporka.cases.walk import scan_dir

    d = tmp_path / "case"
    d.mkdir()
    for n in range(1, 3):
        (d / f"{n:04}.tif").write_bytes(b"x")
    scan = scan_dir(d, tmp_path, ("case",), 1)
    assert scan.has_material() and scan.n_frames == 2 and scan.n_img == 0


# ── однакові стеми ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("pair", [("0001.jpg", "0001.png"), ("0001.jpg", "0001.JPEG")])
def test_two_frames_with_one_stem_are_refused(tmp_path: Path, pair) -> None:
    d = tmp_path / "case"
    d.mkdir()
    for name in (*pair, "0002.jpg"):
        (d / name).write_bytes(b"x")
    with pytest.raises(R.StemCollision) as exc:
        R.select_pages(d, "", 0, 0, 1)
    assert "0001" in str(exc.value)
