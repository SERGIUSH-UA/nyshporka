"""Пачка справ у Супрягу: `nysh share push`.

Сотня справ, віддана петлею `pack` + `publish`, платить за запуск Нишпорки на
кожен крок і йде строго по одній. Пачка мусить робити те саме, що ці дві
команди, — ті самі ворота, ті самі відповіді пулу, — лише кількома справами
одночасно, і не губити по дорозі ні справ, ні причин.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.share import batch as B
from nyshporka.share import journal
from nyshporka.share import publish as PUB
from nyshporka.share import upload as U


class Pul:
    """Підставний пакувальник і пул: що пакували, що заливали, що відповісти."""

    def __init__(self) -> None:
        self.packed: list[dict[str, Any]] = []
        self.sent: list[str] = []
        self.ne_pakuietsia: set[str] = set()
        self.stelia_pislia: int | None = None
        self.lock = threading.Lock()

    def pack(self, scope: str, dest: Any = None, **kw: Any) -> dict[str, Any]:
        with self.lock:
            self.packed.append({"case": scope, **kw})
        if scope in self.ne_pakuietsia:
            raise PUB.PublishError(f"ворота не пропустили пакет {scope}")
        return {"path": f"/outbox/{scope.replace('/', '_')}.nyshtext",
                "manifest": {"case": {"shifra": f"ШИФРА {scope}"}},
                "gates": {"passed": True, "warnings": [], "refusals": []},
                "opys_check": []}

    def publish(self, path: Path, **kw: Any) -> dict[str, Any]:
        with self.lock:
            if self.stelia_pislia is not None and len(self.sent) >= self.stelia_pislia:
                raise U.UploadError("стеля внесків на добу", status=429, retry_after=3600)
            self.sent.append(str(path))
            n = len(self.sent)
        return {"outcome": U.VIDDANO, "contribution": 100 + n,
                "etapy": [{"etap": "complete", "sec": 2.0 + n}]}


@pytest.fixture
def pul(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Pul:
    p = Pul()
    monkeypatch.setattr(PUB, "pack", p.pack)
    monkeypatch.setattr(U, "publish", p.publish)
    monkeypatch.setattr(U, "token", lambda: "t0k")
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "journal.jsonl")
    monkeypatch.setattr(B, "CHEKATY", (0, 0))
    return p


def _push(**kw: Any) -> Any:
    return O.call("share.push", {"jobs": 1, **kw})


def test_kozhna_sprava_pakuietsia_i_zalyvaietsia(pul: Pul) -> None:
    env = _push(cases=["A/1/1", "A/1/2", "A/1/3"])
    assert env.ok, env.error
    d = env.data
    assert [p["case"] for p in pul.packed] == ["A/1/1", "A/1/2", "A/1/3"]
    assert len(pul.sent) == 3
    assert d["summary"]["viddano"] == 3
    assert [r["case"] for r in d["rows"]] == ["A/1/1", "A/1/2", "A/1/3"]
    assert all(r["ok"] and r["contribution"] for r in d["rows"])
    assert d["rows"][0]["shifra"] == "ШИФРА A/1/1"
    assert d["complete_sec_median"] == 4.0


def test_sprava_shcho_ne_spakuvalas_ne_zupyniaie_reshty(pul: Pul) -> None:
    """🔴 Одна погана справа не коштує решти пачки."""
    pul.ne_pakuietsia = {"A/1/2"}
    env = _push(cases=["A/1/1", "A/1/2", "A/1/3"])
    d = env.data
    assert len(pul.sent) == 2
    assert d["failed"] == ["A/1/2"]
    bad = d["rows"][1]
    assert bad["stage"] == B.PACK and "ворота" in bad["error"]
    assert d["summary"]["pack_failed"] == 1
    assert [w.code for w in env.warnings] == ["not_shared"]
    assert "A/1/2" in env.warnings[0].text


def test_stelia_pulu_zupyniaie_pachku(pul: Pul) -> None:
    """🔴 Після 429 решта отримала б ту саму відмову — і марне пакування."""
    pul.stelia_pislia = 1
    env = _push(cases=["A/1/1", "A/1/2", "A/1/3"])
    d = env.data
    assert len(pul.packed) == 2, "третю справу після стелі не пакують"
    assert d["not_started"] == ["A/1/3"]
    assert d["rate_limited"]["retry_after"] == 3600
    assert d["rows"][1]["rate_limited"] is True
    assert d["rows"][1]["retries"] == 2, "перед зупинкою 429 перечікують"
    assert "rate_limited" in [w.code for w in env.warnings]
    assert any(n.op == "share.push" for n in env.next)


def test_stelia_skasovuie_ne_pochate_v_paraleli(pul: Pul) -> None:
    """Те саме з кількома справами одночасно: початі доходять, решта — ні."""
    pul.stelia_pislia = 2
    items = [{"case": f"A/1/{i}"} for i in range(1, 30)]
    got = B.viddaty(items, jobs=2, pool=lambda n: ThreadPoolExecutor(max_workers=n))
    assert got["rate_limited"] is not None
    assert len(got["rows"]) + len(got["not_started"]) == len(items)
    assert len(got["rows"]) < len(items), "після стелі пачка зупинилась"
    assert len(pul.sent) == 2


def test_paralel_daie_toi_samyi_porjadok_i_vsi_spravy(pul: Pul) -> None:
    items = [{"case": f"A/1/{i}"} for i in range(1, 13)]
    got = B.viddaty(items, jobs=4, pool=lambda n: ThreadPoolExecutor(max_workers=n))
    assert [r["case"] for r in got["rows"]] == [i["case"] for i in items]
    assert got["summary"]["viddano"] == 12 and not got["failed"]


def test_v_pul_odnochasno_ne_bilshe_slotiv(pul: Pul, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Пул тримає на людину три незавершені заливання — четверту відбиває 429.

    Пакується `jobs` справ одразу, а заливається не більше `PUBLISH_SLOTS`.
    """
    import time

    zaraz, naibilshe = 0, 0
    lock = threading.Lock()

    def _povilnyi(path: Path, **kw: Any) -> dict[str, Any]:
        nonlocal zaraz, naibilshe
        with lock:
            zaraz += 1
            naibilshe = max(naibilshe, zaraz)
        time.sleep(0.05)
        with lock:
            zaraz -= 1
        return pul.publish(path)

    monkeypatch.setattr(U, "publish", _povilnyi)
    items = [{"case": f"A/1/{i}"} for i in range(1, 19)]
    got = B.viddaty(items, jobs=6, pool=lambda n: ThreadPoolExecutor(max_workers=n))
    assert got["summary"]["viddano"] == 18
    assert 1 < naibilshe <= B.PUBLISH_SLOTS


def test_mynushchyi_429_perechikuietsia(pul: Pul, monkeypatch: pytest.MonkeyPatch) -> None:
    """Слот зайняв сусід (черга, друга сесія) — справа чекає, пачка йде далі."""
    vidbyto: set[str] = set()

    def _raz_429(path: Path, **kw: Any) -> dict[str, Any]:
        if str(path) not in vidbyto:
            vidbyto.add(str(path))
            raise U.UploadError("Завершіть попередні заливання", status=429, retry_after=1200)
        return pul.publish(path)

    monkeypatch.setattr(U, "publish", _raz_429)
    env = _push(cases=["A/1/1", "A/1/2"])
    d = env.data
    assert d["summary"]["viddano"] == 2 and not d["failed"] and not d["not_started"]
    assert d["rate_limited"] is None
    assert d["summary"]["publish_retries"] == 2


def test_khid_drukuietsia_riadkom_na_spravu(pul: Pul) -> None:
    lines: list[str] = []
    B.viddaty([{"case": "A/1/1"}, {"case": "A/1/2"}], jobs=1, say=lines.append)
    assert len(lines) == 2
    assert lines[0].startswith("✓ 1/2 ШИФРА A/1/1 · внесок 101")
    assert lines[0].endswith("(сервер 3.0 с)")


def test_pokrokovyi_khid_zalyvky_ne_zmishuietsia_z_pachkoiu(
        pul: Pul, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Від кількох воркерів «заливаю текст…» перемішалось би — у stderr лише рядок на справу."""
    def _balakuchyi(path: Path, *, say: Any = None, **kw: Any) -> dict[str, Any]:
        say("заливаю текст: 0.2 МБ…")
        return pul.publish(path)

    monkeypatch.setattr(U, "publish", _balakuchyi)
    _push(cases=["A/1/1"])
    err = capsys.readouterr().err
    assert "заливаю текст" not in err
    assert "✓ 1/1 ШИФРА A/1/1" in err


def test_perelik_z_faila(pul: Pul, tmp_path: Path) -> None:
    f = tmp_path / "perelik.txt"
    f.write_text("# коментар\nA/1/1\n\n"
                 '{"case": "A/1/2", "partial": "прочитано 290 із 408 кадрів", '
                 '"skip_run": ["r-diak"]}\n', encoding="utf-8")
    env = _push(from_file=str(f))
    assert env.ok, env.error
    assert [p["case"] for p in pul.packed] == ["A/1/1", "A/1/2"]
    assert pul.packed[1]["partial_why"] == "прочитано 290 із 408 кадрів"
    assert pul.packed[1]["skip_runs"] == ["r-diak"]


def test_nevidome_pole_v_pereliku_vidmova_do_zalyvky(pul: Pul, tmp_path: Path) -> None:
    """🔴 `skip_runs` замість `skip_run` не має мовчки віддати зайвий голос."""
    f = tmp_path / "perelik.txt"
    f.write_text('A/1/1\n{"case": "A/1/2", "skip_runs": ["r-diak"]}\n', encoding="utf-8")
    env = _push(from_file=str(f))
    assert not env.ok
    assert "skip_runs" in env.error
    assert pul.packed == [], "перелік перевіряється цілим до першої справи"


def test_ne_json_u_pereliku_nazyvaie_riadok(pul: Pul, tmp_path: Path) -> None:
    f = tmp_path / "perelik.txt"
    f.write_text('A/1/1\n{"case": "A/1/2",\n', encoding="utf-8")
    env = _push(from_file=str(f))
    assert not env.ok and "рядок 2" in env.error


def test_dry_run_u_pachtsi_vidmova(pul: Pul, tmp_path: Path) -> None:
    f = tmp_path / "perelik.txt"
    f.write_text('{"case": "A/1/1", "dry_run": true}\n', encoding="utf-8")
    env = _push(from_file=str(f))
    assert not env.ok and "dry_run" in env.error


def test_dubli_spravy_viddaiutsia_raz(pul: Pul) -> None:
    env = _push(cases=["A/1/1", "A/1/1", "A/1/2"])
    assert [p["case"] for p in pul.packed] == ["A/1/1", "A/1/2"]
    assert env.data["total"] == 2


def test_heometriia_za_profilem(pul: Pul) -> None:
    """Хто вимкнув геометрію в профілі, не розсилає її й пачкою."""
    from nyshporka.share import profile as P

    prof = P.load()
    prof.geometry = False
    P.save(prof)
    _push(cases=["A/1/1"])
    assert pul.packed[0]["geometry"] is False


def test_bez_sprav_vidmova(pul: Pul) -> None:
    env = _push()
    assert not env.ok and "--ready" in env.error


def test_bez_kliucha_ne_pakuie(pul: Pul, monkeypatch: pytest.MonkeyPatch) -> None:
    """Без ключа кожна справа спакувалась би й упала на заливці."""
    monkeypatch.setattr(U, "token", lambda: "")
    env = _push(cases=["A/1/1"])
    assert not env.ok and "share login" in env.error
    assert pul.packed == []


def test_jobs_u_mezhakh(pul: Pul) -> None:
    env = O.call("share.push", {"cases": ["A/1/1"], "jobs": 50})
    assert env.data["jobs"] == B.MAX_JOBS
    assert "jobs_capped" in [w.code for w in env.warnings]


def test_vidkhylenyi_dubl_ne_rakhuietsia_viddanym(pul: Pul,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 «Пул відповів» ≠ «справа в каталозі»."""
    monkeypatch.setattr(U, "publish", lambda path, **kw: {"outcome": U.VIDKHYLENO,
                                                          "contribution": 7})
    env = _push(cases=["A/1/1"])
    row = env.data["rows"][0]
    assert row["ok"] is False and env.data["failed"] == ["A/1/1"]
    assert row["error"] == U.OUTCOME_TEXT[U.VIDKHYLENO]


@pytest.fixture
def notatnyky(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Сховище сторінок є лише в A/1/1; `note.push` для A/1/3 відмовляє."""
    from nyshporka.core.envelope import fail, ok
    from nyshporka.pagestore import store

    stan: dict[str, Any] = {"pushed": [], "sklad": {"A/1/1", "A/1/3"}}
    monkeypatch.setattr(store, "resolve_case", lambda c: c)
    monkeypatch.setattr(store, "load_case", lambda ref: object() if ref in stan["sklad"] else None)
    spravzhnii = O.call

    def _call(name: str, payload: dict[str, Any] | None = None) -> Any:
        if name != "note.push":
            return spravzhnii(name, payload)
        stan["pushed"].append(payload["case"])
        return fail("пул не прийняв нотатник") if payload["case"] == "A/1/3" else ok({})

    monkeypatch.setattr(O, "call", _call)
    return stan


def test_notatnyk_lyshe_koly_poprosyly(pul: Pul, notatnyky: dict[str, Any]) -> None:
    _push(cases=["A/1/1"])
    assert notatnyky["pushed"] == []


def test_notatnyk_pislia_zalyvky(pul: Pul, notatnyky: dict[str, Any]) -> None:
    """🔴 Справа без сховища сторінок — не збій; відмова нотатника — не невіддана справа."""
    env = _push(cases=["A/1/1", "A/1/2", "A/1/3"], notes=True)
    d = env.data
    assert notatnyky["pushed"] == ["A/1/1", "A/1/3"], "без сховища сторінок не кличемо"
    assert [r["notes"] for r in d["rows"]] == [B.NOTES_OK, B.NOTES_NONE,
                                                "пул не прийняв нотатник"]
    assert all(r["ok"] for r in d["rows"]) and not d["failed"]
    assert d["summary"]["notes_sent"] == 1 and d["summary"]["notes_failed"] == 1
    assert [w.code for w in env.warnings] == ["notes_failed"]
    assert "A/1/3" in env.warnings[0].text and "A/1/2" not in env.warnings[0].text


def test_notatnyk_ne_ide_pislia_nevdaloi_zalyvky(pul: Pul, notatnyky: dict[str, Any]) -> None:
    pul.ne_pakuietsia = {"A/1/1"}
    _push(cases=["A/1/1"], notes=True)
    assert notatnyky["pushed"] == []


def test_vorker_bere_prostir_batka(tmp_path: Path) -> None:
    """🔴 `--workspace` живе лише в батьківському процесі — воркер бере його явно."""
    from nyshporka.core import workspace as W

    was = W.workspace()
    inshyi = W.Workspace(root=tmp_path, name="інший", origin="test")
    try:
        B._init(inshyi)
        assert W.workspace() is inshyi
    finally:
        W.use(was)


def test_zhurnal_pyshe_pid_zamkom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Дозапис журналу — під замком у `data/derived`, а не поруч із журналом."""
    from nyshporka.core import xrate
    from nyshporka.core.workspace import workspace

    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "share" / "journal.jsonl")
    zamky: list[Path] = []
    spravzhnii = xrate._locked

    def _shpyhun(path: Path, timeout: float = 300.0) -> Any:
        zamky.append(path)
        return spravzhnii(path, timeout)

    monkeypatch.setattr(xrate, "_locked", _shpyhun)
    journal.record(journal.PACKED, case_key="A/1/1")
    assert zamky == [workspace().derived / "share" / "journal.lock"]
    assert len(journal.read(journal.PACKED)) == 1
    assert not list((tmp_path / "share").glob("*.lock"))
