"""🔗 Ланцюг справи: скани → паспорт → реєстрація → каталог → прогін.

🔴 Привід — звіт стороннього користувача 29.09.2026. Він завантажив двадцять
справ, у кожній теці побачив `meta.json` завантажувача й вважав справу
описаною. Паспорт справи — `_source.json`, пише його лише реєстрація; без
шифри тека не потрапляє ні в каталог, ні в читання, ні у віддачу. Жодне з цих
місць про це не казало — кожне падало зі своєї причини.

Тут стережеться одне: тека, на якій ланцюг обірвано, мусить бути названа
разом із ланкою й командою, що веде далі.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources.base import FetchResult

C: Any = None
L: Any = None
R: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Порожній простір; заморожені на імпорті шляхи підмінено поіменно
    (той самий каркас, що в `test_opys_own_key.space`)."""
    from nyshporka.core import opys_keys as K
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    K.reset()

    global C, L, R
    from nyshporka import library as lib
    from nyshporka.cases import chain, register
    from nyshporka.cases import db as DB
    from nyshporka.pagestore import store as S

    C, L, R = chain, lib, register
    for mod, attr, value in (
        (lib, "ROOT", tmp_path), (lib, "RAW_DIR", tmp_path / "data" / "raw"),
        (lib, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (lib, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)
    for fn in ("load_library", "_sidecar_case"):
        got = getattr(lib, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()
    # Прогонів у тестовому просторі немає; справжній стор читань сюди не дивиться.
    from nyshporka import htr_store

    monkeypatch.setattr(htr_store, "runs_by_case_dir", lambda: {})
    yield tmp_path
    K.reset()


def _kadry(d: Path, n: int = 3) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"jpg" + bytes([i]))
    return d


def _zavantazhena(root: Path, rel: str, *, extra: dict[str, Any] | None = None) -> Path:
    """Тека, якою її лишає `nysh get`: кадри й `meta.json` завантажувача."""
    from nyshporka.cases.acquire import record_fetch

    d = _kadry(root / "data" / "raw" / rel)
    record_fetch(d, FetchResult(dest=d, frames=3), source="archium", ref="file:1",
                 want=3, extra=extra)
    return d


def _rebuild() -> None:
    L._sidecar_case.cache_clear()
    L.write_library(L.build_library())
    if hasattr(L.load_library, "cache_clear"):
        L.load_library.cache_clear()


def _lanka(rows: list[Any], tail: str) -> Any:
    got = [r for r in rows if r.path.endswith(tail)]
    assert len(got) == 1, [(r.path, r.link) for r in rows]
    return got[0]


# ── пастка двох файлів ────────────────────────────────────────────────────────

def test_meta_zavantazhuvacha_ne_pasport_spravy(space: Path) -> None:
    """🔴 `meta.json` є, шифри немає — тека обірвана на реєстрації, і це названо."""
    _zavantazhena(space, "skvyra/knyha_1")
    _rebuild()

    r = _lanka(C.walk(), "skvyra/knyha_1")

    assert r.link == C.LOADER_ONLY and r.broken
    assert r.sidecar == "meta.json" and r.frames == 3
    assert "_source.json" in r.why
    assert r.fix.startswith('nysh case "data/raw/skvyra/knyha_1" --shifra')


def test_pislia_reiestratsii_lantsiuh_tsilyi(space: Path) -> None:
    d = _zavantazhena(space, "skvyra/knyha_1")
    R.describe(d, shifra="ЦДІАК 127-1015-473")
    _rebuild()

    r = _lanka(C.walk(), "skvyra/knyha_1")

    assert r.link == C.NO_RUN and not r.broken
    assert r.sidecar == "_source.json" and r.key


def test_shyfra_zi_storinky_dzherela_lyshe_pidkazka(space: Path) -> None:
    """Те, що назвала сторінка джерела, йде в команду — з позначкою «не звірена»."""
    _zavantazhena(space, "skvyra/knyha_2", extra={
        "shifra_claimed": {"repo": "ЦДІАК", "fond": "127", "opys": "1015", "spr": "473"}})

    r = C.after_fetch(space / "data" / "raw" / "skvyra" / "knyha_2")

    assert r is not None and r.link == C.LOADER_ONLY
    assert '--shifra "ЦДІАК 127-1015-473"' in r.fix
    assert "не звірена" in r.fix


def test_knyzhka_z_biblioteky_ne_sprava(space: Path) -> None:
    """Завантажена книжка теж має `meta.json` завантажувача — справою її не вважаємо."""
    d = _zavantazhena(space, "chtyvo/Krykun", extra={"book": {"title": "Крикун"}})
    _rebuild()

    assert _lanka(C.walk(), "chtyvo/Krykun").link == C.NO_PASSPORT
    assert C.after_fetch(d) is None


# ── решта ланок ───────────────────────────────────────────────────────────────

def test_kadry_bez_pasporta_i_bez_shyfry_v_imeni(space: Path) -> None:
    _kadry(space / "data" / "raw" / "rizne" / "skany_z_fleshky")
    _rebuild()

    r = _lanka(C.walk(), "rizne/skany_z_fleshky")

    assert r.link == C.NO_PASSPORT and r.sidecar == ""
    assert "--shifra" in r.fix


def test_teka_z_shyfroiu_pislia_zbirky_katalohu(space: Path) -> None:
    """Ключ збирається з імені, а каталог зібрано раніше — радимо перезбірку."""
    _kadry(space / "data" / "raw" / "dahmo_315" / "spr-1")
    _rebuild()
    _kadry(space / "data" / "raw" / "dahmo_315" / "spr-8433")     # після збірки

    rows = C.walk()

    assert _lanka(rows, "dahmo_315/spr-1").link == C.NO_RUN
    nova = _lanka(rows, "dahmo_315/spr-8433")
    assert nova.link == C.NOT_IN_LIBRARY and nova.fix == "nysh cases build --rescan"


def test_teka_poza_koreniamy(space: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Завантажили на робочий стіл — каталог туди не ходить, і порада це каже."""
    from nyshporka.cases.acquire import record_fetch

    d = _kadry(tmp_path_factory.mktemp("stil") / "sprava")
    record_fetch(d, FetchResult(dest=d, frames=3), source="archium", ref="file:1", want=3)

    r = C.after_fetch(d)

    assert r is not None and r.link == C.OUTSIDE_ROOTS
    assert "--adopt" in r.fix


def test_pidteka_vrakhovanoi_spravy_ne_okrema_sprava(space: Path) -> None:
    """`pages/` і вирізки всередині справи — не «кадри без шифри»."""
    d = _kadry(space / "data" / "raw" / "dahmo_315" / "spr-8433")
    _kadry(d / "vyrizky")
    _rebuild()

    rows = C.walk()

    assert [r.link for r in rows if "spr-8433" in r.path] == [C.NO_RUN]


def test_prochytana_chastkovo_i_povnistiu(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store

    d = _kadry(space / "data" / "raw" / "dahmo_315" / "spr-8433", n=10)
    _rebuild()

    monkeypatch.setattr(htr_store, "runs_by_case_dir",
                        lambda: {str(d): [{"pages_done": 4}]})
    assert _lanka(C.walk(), "spr-8433").link == C.PARTIAL_RUN
    monkeypatch.setattr(htr_store, "runs_by_case_dir",
                        lambda: {str(d): [{"pages_done": 4}, {"pages_done": 10}]})
    assert _lanka(C.walk(), "spr-8433").link == C.OK


# ── дешевий шлях: реєстр, без обходу диска ────────────────────────────────────

def _reiestr(monkeypatch: pytest.MonkeyPatch, unfiled: list[dict[str, Any]],
             orphans: list[dict[str, Any]] | None = None) -> None:
    from nyshporka.cases import db

    monkeypatch.setattr(db, "query_rows", lambda **kw: list(unfiled))
    monkeypatch.setattr(db, "orphan_runs", lambda *a, **kw: list(orphans or []))


def test_quick_bez_reiestru_kazhe_ne_znaiu(space: Path) -> None:
    """Реєстру немає — не «обривів нуль», а «не питали»."""
    assert C.quick() is None


def test_quick_ne_obkhodyt_dysk(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.cases import walk as W

    _zavantazhena(space, "skvyra/knyha_1")
    _reiestr(monkeypatch,
             [{"path": "data/raw/skvyra/knyha_1", "frames": 3},
              {"path": "data/raw/zniklo", "frames": 9}],       # теки вже немає
             [{"run": "spr-1_pysar", "pages": 40, "case_dir": "D:/x", "resolved_by": "none"},
              {"run": "proba", "pages": 5, "case_dir": "", "resolved_by": "override"}])

    def _ni(*a: Any, **kw: Any) -> Any:
        raise AssertionError("дешевий шлях пішов обходити диск")

    monkeypatch.setattr(W, "walk_root", _ni)
    monkeypatch.setattr(L, "_scan_disk_cases", _ni)

    rows = C.quick()

    assert [(r.path, r.link) for r in rows] == [
        ("data/raw/skvyra/knyha_1", C.LOADER_ONLY), ("spr-1_pysar", C.ORPHAN_RUN)]
    assert rows[1].fix.startswith('nysh cases bind "spr-1_pysar"')


# ── doctor ────────────────────────────────────────────────────────────────────

def test_doctor_poperedzhaie_pro_zavantazhene_bez_reiestratsii(
        space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import doctor as D

    _zavantazhena(space, "skvyra/knyha_1")
    _kadry(space / "data" / "raw" / "rizne" / "skany")
    _reiestr(monkeypatch, [{"path": "data/raw/skvyra/knyha_1", "frames": 3},
                           {"path": "data/raw/rizne/skany", "frames": 3}])

    got = D._chain()

    assert got.level == "warn"
    assert "skvyra/knyha_1" in got.detail and "rizne/skany" not in got.detail
    assert "nysh case" in got.fix and "nysh cases chain" in got.fix


def test_doctor_ne_dokoriaie_tekamy_bez_shyfry(space: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Сотня старих тек без шифри — стан дослідницького простору, не поломка.

    Попередження, яке не гасне ніколи, привчає не читати доктора; тож воно
    лише про те, що людина щойно завантажила й не довела до справи.
    """
    from nyshporka.setup import doctor as D

    _kadry(space / "data" / "raw" / "rizne" / "skany")
    _reiestr(monkeypatch, [{"path": "data/raw/rizne/skany", "frames": 3}],
             [{"run": "r", "pages": 1, "case_dir": "", "resolved_by": "none"}])

    got = D._chain()

    assert got.level == "ok"
    assert "тек без шифри: 1" in got.detail and "прогонів без справи: 1" in got.detail


def test_doctor_bez_reiestru(space: Path) -> None:
    from nyshporka.setup import doctor as D

    got = D._chain()
    assert got.level == "ok" and "не зібрано" in got.detail
    assert D._chain in D.CHECKS


# ── порада одразу після завантаження ──────────────────────────────────────────

def test_nysh_get_kazhe_shcho_dali(space: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from nyshporka import cli

    d = _zavantazhena(space, "skvyra/knyha_1")
    cli._dali_pislia_zavantazhennia(d)
    out = capsys.readouterr().out
    assert "не зареєстровано" in out and "nysh case" in out

    R.describe(d, shifra="ЦДІАК 127-1015-473")
    cli._dali_pislia_zavantazhennia(d)
    assert capsys.readouterr().out == "", "зареєстрована тека — без зайвих порад"


@pytest.mark.asyncio
async def test_demon_kazhe_shcho_dali(space: Path) -> None:
    """Завантаження через застосунок закінчується тим самим словом, що й `nysh get`."""
    from nyshporka.core.jobs import JobBus
    from nyshporka.daemon import workers as W

    dest = _kadry(space / "data" / "raw" / "skvyra" / "knyha_1")

    class _Src:
        id = "archium"

        def fetch(self, ref: str, dest: Path, *, frames: Any = None,
                  on_progress: Any = None) -> FetchResult:
            return FetchResult(dest=dest, frames=3)

    bus = JobBus(space / "jobs.json")
    job, _ = await bus.enqueue("acquire", title="t", cfg={})
    await W._run_acquire(bus, _Src(), job, dest, "file:1", None, 3)

    dali = bus.get(job.id).result["next"]
    assert "не зареєстровано" in dali and "nysh case" in dali


def test_operatsiia_viddaie_znamennyk(space: Path) -> None:
    from nyshporka import ops as O

    _zavantazhena(space, "skvyra/knyha_1")
    _kadry(space / "data" / "raw" / "dahmo_315" / "spr-8433")
    _rebuild()

    env = O.call("cases.chain", {})
    assert env.ok
    assert env.data["folders"] == 2 and env.data["broken"] == 1
    assert [r["link"] for r in env.data["rows"]] == [C.LOADER_ONLY]
    assert any(w.code == "unregistered_downloads" for w in env.warnings)

    vsi = O.call("cases.chain", {"all": True})
    assert sorted(r["link"] for r in vsi.data["rows"]) == sorted([C.LOADER_ONLY, C.NO_RUN])
