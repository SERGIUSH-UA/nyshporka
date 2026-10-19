"""`nysh disk`: що лишити, що прибрати, і зняття прочитаних кадрів без втрати.

Кожен тест нижче — сценарій втрати даних, знайдений рев'ю 18.10.2026 або
передбачений ним: junction на шляху (вміст ЦІЛІ — зовнішній чи архівний диск),
ключ справи з двома теками, кадри поза прочитаним, незчитаний стан хмарних
заходів, слово «outbox» у шляху простору. Перевірки, що захищають від них,
тут ганяються справжні — підміняються лише джерела даних (прогони, пул).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from nyshporka import disk as D
from nyshporka.core import workspace as W

#: До підміни фікстурою — для тестів самої перевірки живих заходів.
SPRAVZHNI_LIVE_RUNS = D._live_runs


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> W.Workspace:
    w = W.Workspace(root=tmp_path / "prostir", name="тест", origin="test")
    w.root.mkdir()
    W.use(w)
    monkeypatch.setattr(D, "_live_runs", lambda: [])
    return w


def _file(p: Path, n: int = 1000, age: float = 0.0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)
    if age:
        t = time.time() - age
        os.utime(p, (t, t))
    return p


def _link(link: Path, target: Path) -> None:
    """Junction на Windows (так лежать справи на зовнішньому диску), симлінк деінде."""
    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True)
        if r.returncode != 0:
            pytest.skip("junction не створився")
    else:
        os.symlink(target, link, target_is_directory=True)


# ── звіт ─────────────────────────────────────────────────────────────────────

def test_zvit_rozkladaie_za_klasamy(ws: W.Workspace) -> None:
    _file(ws.derived / "cloud" / "frames" / "sprava" / "0001.jpg", 2000)
    _file(ws.share / "outbox" / "A_1-1-1.nyshtext", 500)
    _file(ws.htr_reports / "run" / "0001.txt", 10)
    got = D.report()
    by = {i["label"]: i for i in got["items"]}
    assert by["стиснуті кадри для хмари"]["class"] == D.VIDTVORIUVANE
    assert got["rebuildable_bytes"] == 2500
    proch = by["прочитане (декоди й рамки рядків)"]
    assert proch["class"] == D.LYSHYTY
    assert proch["bytes"] is None, "мільйони файлів прочитаного без --full не обходяться"
    assert D.report(full=True)["items"][0]["bytes"] == 10


# ── чистка ───────────────────────────────────────────────────────────────────

def test_chystka_bez_apply_nichoho_ne_vydaliaie(ws: W.Workspace) -> None:
    f = _file(ws.derived / "cloud" / "frames" / "s" / "1.jpg")
    got = D.clean()
    assert got["bytes"] == 1000 and not got["removed"]
    assert f.exists()


def test_chystka_bere_vidtvoriuvane_i_ne_chipaie_reshty(ws: W.Workspace) -> None:
    kadr = _file(ws.derived / "cloud" / "frames" / "s" / "1.jpg")
    asset = _file(ws.derived / "cloud" / "supervised" / "assets" / "a.tgz")
    plan = _file(ws.derived / "cloud" / "supervised" / "runs" / "s1" / "plan.json")
    trening = _file(ws.derived / "train" / "tmp" / "r.result.tar")
    staryi = _file(ws.share / "outbox" / "A_1-1-1.nyshtext", age=2 * 3600)
    svizhyi = _file(ws.share / "outbox" / "A_1-1-2.nyshtext")
    zhurnal = _file(ws.share / "journal.jsonl", 10)
    prochytane = _file(ws.htr_reports / "run" / "0001.txt", 10)
    got = D.clean(apply=True)
    assert not kadr.exists() and not asset.exists() and not staryi.exists()
    assert plan.exists(), "план заходу — єдине, чим розібрати осиротілу машину"
    assert trening.exists(), "забір ваг живого трену не чіпається"
    assert svizhyi.exists(), "свіжий пакет може ще заливатись"
    assert zhurnal.exists() and prochytane.exists()
    assert any("свіжіші" in k["why"] for k in got["kept"])


def test_zhyvyi_zakhid_berezhe_khmarni_teky(ws: W.Workspace,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    class Run:
        run_id = "op1-spr-1__abc"

    monkeypatch.setattr(D, "_live_runs", lambda: [Run()])
    kadr = _file(ws.derived / "cloud" / "frames" / "s" / "1.jpg")
    paket = _file(ws.share / "outbox" / "A.nyshtext", age=2 * 3600)
    got = D.clean(apply=True)
    assert kadr.exists(), "кадри їдуть на машину живого заходу"
    assert not paket.exists(), "outbox від хмари не залежить"
    assert any("op1-spr-1__abc" in k["why"] for k in got["kept"])


def test_nechytnyi_stan_zakhodiv_berezhe_khmarni_teky(ws: W.Workspace,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Закритий при збої: стан заходу не прочитався — живими вважаються всі."""
    from nyshporka.cloud import state as ST

    kadr = _file(ws.derived / "cloud" / "frames" / "s" / "1.jpg")
    runs = ws.root / "runs_test"
    runs.mkdir()
    (runs / "a.json").write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(ST, "runs_dir", lambda: runs)
    monkeypatch.setattr(D, "_live_runs", SPRAVZHNI_LIVE_RUNS)
    assert D._live_runs() is None
    got = D.clean(apply=True)
    assert kadr.exists()
    assert any("не прочитався" in k["why"] for k in got["kept"])


def test_slovo_outbox_u_shliakhu_prostoru_ne_minaie_khmari(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Простір у `X:/outbox/prostir`: тип пункту — полем, а не частиною шляху."""
    class Run:
        run_id = "zhyvyi"

    w = W.Workspace(root=tmp_path / "outbox" / "prostir", name="т", origin="test")
    w.root.mkdir(parents=True)
    W.use(w)
    monkeypatch.setattr(D, "_live_runs", lambda: [Run()])
    kadr = _file(w.derived / "cloud" / "frames" / "s" / "1.jpg", age=2 * 3600)
    D.clean(apply=True)
    assert kadr.exists()


@pytest.mark.parametrize("de_link", ["data/derived", "data/derived/cloud", "data/share/outbox"])
def test_link_na_shliakhu_berezhe_tsil(ws: W.Workspace, tmp_path: Path, de_link: str) -> None:
    """🔴 `derived` чи `outbox` — junction на інший диск: ціль не чіпається зовсім."""
    tsil = tmp_path / "zovnishnii"
    link = ws.root / de_link
    _link(link, tsil)
    rel = Path(*Path("data/derived/cloud/frames/s/1.jpg").parts[len(Path(de_link).parts):]) \
        if "derived" in de_link else Path("A.nyshtext")
    kadr = _file(tsil / rel, age=2 * 3600)
    got = D.clean(apply=True)
    assert kadr.exists(), "вміст цілі лінка цілий"
    assert any("лінк" in k["why"] for k in got["kept"])


def test_link_useredyni_znimaietsia_sam(ws: W.Workspace, tmp_path: Path) -> None:
    zovnishnii = tmp_path / "zovnishnii_dysk"
    kadr = _file(zovnishnii / "0001.jpg")
    link = ws.derived / "cloud" / "frames" / "sprava"
    _link(link, zovnishnii)
    D.clean(apply=True)
    assert not D._is_link(link) and not link.exists()
    assert kadr.exists(), "вміст цілі junction лишився цілим"


def test_stara_teka_segmentiv_zi_svizhym_failom_lyshaietsia(ws: W.Workspace) -> None:
    teka = ws.share / "outbox" / "A_1-1-1~segments"
    _file(teka / "seg0.nyshtext", age=3 * 3600)
    svizhyi = _file(teka / "seg1.nyshtext")
    t = time.time() - 3 * 3600
    os.utime(teka, (t, t))
    D.clean(apply=True)
    assert svizhyi.exists()


def test_teka_lyshe_dlia_chytannia_rozbyraietsia(ws: W.Workspace) -> None:
    import stat

    teka = ws.derived / "cloud" / "tmp" / "ro"
    f = _file(teka / "a.tar")
    os.chmod(f, stat.S_IREAD)
    os.chmod(teka, stat.S_IREAD)
    got = D.clean(apply=True)
    assert not got["errors"] and not teka.exists()


# ── зняття кадрів ────────────────────────────────────────────────────────────

KEY = "DAHMO/315/1/8433"
REL = Path("data") / "raw" / "dahmo" / "f315-8433"


def _sprava(root: Path, kadry: tuple[str, ...] = ("0001.jpg", "0002.jpg", "0003.jpg"),
            pasport: bool = True, rel: Path = REL) -> Path:
    d = root / rel
    for n in kadry:
        _file(d / n, 100, age=3600)   # кадр старший за прочитання
    if pasport:
        (d / "_source.json").write_text('{"shifra": "ДАХмО 315-1-8433"}', encoding="utf-8")
    return d


@pytest.fixture
def svit(ws: W.Workspace, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Підмінні джерела: розв'язання шифри, бібліотека, прогони, пул.
    Перевірки `disk` — справжні."""
    from nyshporka import htr_store as S
    from nyshporka import library
    from nyshporka.pagestore import store
    from nyshporka.share import pool as P
    from nyshporka.share import suggest as SG

    s: dict[str, Any] = {"runs": [], "metas": {}, "lib": [], "mine": True, "pool_pages": 10_000}

    monkeypatch.setattr(store, "resolve_case", lambda v: store.CaseRef(
        key=KEY, repo="DAHMO", fond="315", spr="8433", opys="1"))
    monkeypatch.setattr(library, "load_library", lambda: s["lib"])
    monkeypatch.setattr(library, "ROOT", ws.root)
    monkeypatch.setattr(S, "list_cases", lambda: s["runs"])
    monkeypatch.setattr(S, "load_meta", lambda name: s["metas"].get(name))
    monkeypatch.setattr(S, "_canon_case_key", lambda v: v)
    monkeypatch.setattr(P, "meta", lambda: {"at": "x"})
    monkeypatch.setattr(SG, "_pool_key", lambda k: k)

    class Cell:
        @property
        def mine(self) -> Any:
            return s["mine"]

        @property
        def pages(self) -> int:
            return s["pool_pages"]

    monkeypatch.setattr(SG, "_komirka", lambda k: Cell())
    return s


def _prohin(s: dict[str, Any], d: Path, pages: tuple[str, ...], name: str = "run1",
            shared: bool = False, key: str = KEY, row_dir: Path | None = None,
            lines: int = 30, failed: tuple[str, ...] = ()) -> None:
    # Прочитано після появи кадрів. Не «щойно»: мітка часу ФС буває на частку
    # секунди попереду `time.time()`, і тест плавав би (18.10.2026).
    at = time.time() + 2
    s["runs"].append({"name": name, "case_dir": str(row_dir or d), "case_key": key,
                      "shared": shared})
    s["metas"][name] = {"case_dir": str(d), "case_key": key, "failed": list(failed),
                        "pages": {p: {"lines": lines, "at": at} for p in pages}}


VSI = ("0001.jpg", "0002.jpg", "0003.jpg")


def test_znimaiutsia_lyshe_prochytani_kadry(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root, ("0001.jpg", "0002.jpg", "0003.jpg", "0004.tif"))
    _prohin(svit, d, ("0001.jpg", "0002.jpg"))
    proba = D.offload(str(d), restore="диск Seagate")
    assert proba["frames"] == 2 and not proba["applied"] and len(list(d.glob("*.jpg"))) == 3

    got = D.offload(str(d), restore="диск Seagate", apply=True)
    assert sorted(p.name for p in d.iterdir()) == [
        "0003.jpg", "0004.tif", "_offloaded.json", "_source.json"]
    assert got["unread_kept"] == ["0003.jpg"], "непрочитаний кадр лишається й називається"
    marker = json.loads((d / D.OFFLOAD_MARKER).read_text(encoding="utf-8"))
    assert marker["restore"] == "диск Seagate" and marker["frames"] == 2
    assert "in_progress" not in marker


def test_vse_prochytane_sprava_staie_zniatoiu(ws: W.Workspace, svit: dict[str, Any]) -> None:
    from nyshporka.library import _frames_removed

    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    D.offload(str(d), restore="диск", apply=True)
    assert not list(d.glob("*.jpg")) and (d / "_source.json").exists()
    assert _frames_removed(d), "бібліотека бачить справу як «знято», а не як зниклу"


def test_jpeg_u_tetsi_jpg_u_prohoni_znimaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    """Розпакований ZIP лишив `.jpeg`, стискання перед хмарою записало `.jpg`."""
    d = _sprava(ws.root, ("0001.jpeg", "0002.jpeg", "0003.png"))
    _prohin(svit, d, VSI)
    got = D.offload(str(d), restore="диск", apply=True)
    assert got["frames"] == 3 and not list(d.glob("000*"))


def test_dvoznachna_osnova_lyshaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    """Два кадри з однією основою: котрий прочитано, не видно — обидва лишаються."""
    d = _sprava(ws.root, ("0001.jpeg", "0001.png", "0002.jpeg"))
    _prohin(svit, d, ("0001.jpg", "0002.jpg"))
    got = D.offload(str(d), restore="диск", apply=True)
    assert sorted(p.name for p in d.glob("000*")) == ["0001.jpeg", "0001.png"]
    assert got["unread_kept"] == ["0001.jpeg", "0001.png"]


def test_imena_ne_zistavylys_vidmova_kazhe_tse(ws: W.Workspace, svit: dict[str, Any]) -> None:
    """🔴 «Не зміг зіставити» не виглядає як «кадрів немає»."""
    d = _sprava(ws.root, ("000001.jpeg", "000002.jpeg"))
    _prohin(svit, d, ("0001.jpg", "0002.jpg"))
    with pytest.raises(D.DiskError, match=r"жодне ім'я не зіставилось.*000001.jpeg.*0001.jpg"):
        D.offload(str(d), restore="диск", apply=True)
    assert len(list(d.glob("*.jpeg"))) == 2


def test_vidnosnyi_shliakh_vid_korenia_prostoru(ws: W.Workspace, svit: dict[str, Any],
                                                tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Відносний шлях — від кореня простору, а не від поточної теки (резервна копія)."""
    d = _sprava(ws.root)
    rezerv = _sprava(tmp_path / "rezerv")
    _prohin(svit, d, VSI)
    monkeypatch.chdir(tmp_path / "rezerv")
    D.offload(str(REL), restore="диск", apply=True)
    assert not list(d.glob("*.jpg"))
    assert len(list(rezerv.glob("*.jpg"))) == 3, "резервну копію не чіпали"


def test_shliakh_do_faila_vidmova(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="файл"):
        D.offload(str(d / "0001.jpg"), restore="диск", apply=True)


def test_prohin_inshoi_teky_toho_zh_kliucha_ne_rakhuietsia(
        ws: W.Workspace, svit: dict[str, Any]) -> None:
    """🔴 Ключ із двома теками: прочитано archium, а знімати просять FS."""
    d = _sprava(ws.root)
    insha = _sprava(ws.root, rel=Path("data/raw/archium/f315-8433"))
    _prohin(svit, insha, VSI)
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)
    assert len(list(d.glob("*.jpg"))) == 3


def test_teka_z_meti_a_ne_z_pereliku(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    insha = _sprava(ws.root, rel=Path("data/raw/archium/f315-8433"))
    _prohin(svit, insha, VSI, row_dir=d)   # перелік каже d, мета — іншу теку
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)


def test_teka_pid_inshoiu_spravoiu_ne_rakhuietsia(ws: W.Workspace,
                                                  svit: dict[str, Any]) -> None:
    """🔴 Стейджинг перевикористано: прогін старої справи з тими самими іменами."""
    d = _sprava(ws.root)
    _prohin(svit, d, VSI, key="DAVO/904/24/1")
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)
    assert len(list(d.glob("*.jpg"))) == 3



def test_prohin_z_nevidomym_opysom_ne_rakhuietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    """Невідомий опис «сумісний» з будь-яким — і пропустив би іншу книгу фонду."""
    d = _sprava(ws.root)
    _prohin(svit, d, VSI, key="DAHMO/315/_/8433")
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)


def test_novyi_fail_zi_staroiu_datoiu_lyshaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    """Кадр замінили розпаковкою архіву: дата зміни стара, файл — новий."""
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    f = d / "0002.jpg"
    stara = f.stat().st_mtime
    f.unlink()
    _file(f, 120)
    os.utime(f, (stara, stara))
    # прочитано після старої дати зміни, але до появи нового файла
    svit["metas"]["run1"]["pages"]["0002.jpg"]["at"] = stara + 1
    got = D.offload(str(d), restore="диск", apply=True)
    assert f.exists() and got["changed_after_read"] == ["0002.jpg"]


def test_zablokovana_poznachka_vidmova_bez_vtrat(ws: W.Workspace, svit: dict[str, Any],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)

    def _ne_mozhna(self: Path, target: Any) -> Any:
        raise PermissionError("файл відкрито іншим процесом")

    monkeypatch.setattr(Path, "replace", _ne_mozhna)
    with pytest.raises(D.DiskError, match="не записано"):
        D.offload(str(d), restore="диск", apply=True)
    assert len(list(d.glob("*.jpg"))) == 3 and not list(d.glob("*.part"))

def test_prohin_bez_kliucha_ne_rakhuietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI, key="")
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)


def test_chuzhyi_prohin_ne_rakhuietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI, shared=True)
    with pytest.raises(D.DiskError, match="жоден власний прогін"):
        D.offload(str(d), restore="диск", apply=True)


def test_kadr_zaminenyi_pislia_prochytannia_lyshaietsia(ws: W.Workspace,
                                                        svit: dict[str, Any]) -> None:
    """🔴 Обрізаний кадр докачали під тим самим іменем — текст покриває половину."""
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    svizhyi = d / "0002.jpg"
    t = time.time() + 120
    os.utime(svizhyi, (t, t))
    got = D.offload(str(d), restore="диск", apply=True)
    assert svizhyi.exists() and got["changed_after_read"] == ["0002.jpg"]


@pytest.mark.parametrize("info", [{"lines": 0, "at": 1}, {"lines": 30, "error": "oom", "at": 1},
                                  {"lines": 30}])
def test_neprochytana_storinka_lyshaietsia(ws: W.Workspace, svit: dict[str, Any],
                                           info: dict[str, Any]) -> None:
    """Нуль рядків, помилка, немає часу прочитання — кадр лишається."""
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    if "at" in info:
        info = {**info, "at": time.time() + 2}   # прочитано після останньої зміни кадру
    svit["metas"]["run1"]["pages"]["0002.jpg"] = info
    D.offload(str(d), restore="диск", apply=True)
    assert (d / "0002.jpg").exists()


def test_storinka_u_failed_lyshaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI, failed=("0002.jpg",))
    D.offload(str(d), restore="диск", apply=True)
    assert (d / "0002.jpg").exists() and not (d / "0001.jpg").exists()


def test_odnoimennyi_kadr_u_pages_ne_chipaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    inshyi = _file(d / "pages" / "0001.jpg", 50)
    _prohin(svit, d, VSI)
    D.offload(str(d), restore="диск", apply=True)
    assert inshyi.exists()


def test_kliuch_iz_dvoma_tekamy_vymahaie_shliakhu(ws: W.Workspace, svit: dict[str, Any]) -> None:
    svit["lib"] = [{"key": KEY, "path": "data/raw/a/1"}, {"key": KEY, "path": "data/raw/b/1"}]
    with pytest.raises(D.DiskError, match="назвіть теку шляхом"):
        D.offload("ДАХмО 315-1-8433", restore="диск", apply=True)


def test_link_vyshche_teky_spravy_vidmova(ws: W.Workspace, svit: dict[str, Any],
                                          tmp_path: Path) -> None:
    """🔴 data/raw/<архів> — junction на архівний диск: кадри там і є копія."""
    arkhiv = tmp_path / "arkhivnyi_dysk"
    _link(ws.root / "data" / "raw" / "dahmo", arkhiv)
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="фізично лежить"):
        D.offload(str(d), restore="архівний диск", apply=True)
    assert len(list((arkhiv / "f315-8433").glob("*.jpg"))) == 3


@pytest.mark.parametrize("rel", [Path("."), Path("data/raw")])
def test_korin_ne_sprava(ws: W.Workspace, svit: dict[str, Any], rel: Path) -> None:
    d = ws.root / rel
    _file(d / "logo.png")
    (d / "_source.json").write_text("{}", encoding="utf-8")
    _prohin(svit, d, ("logo.png",))
    with pytest.raises(D.DiskError, match="корінь"):
        D.offload(str(d), restore="диск", apply=True)
    assert (d / "logo.png").exists()


def test_poza_mezhamy_prostoru_vidmova(ws: W.Workspace, svit: dict[str, Any],
                                       tmp_path: Path) -> None:
    d = _sprava(tmp_path / "chuzhe")
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="поза data/raw"):
        D.offload(str(d), restore="диск", apply=True)


def test_teka_kilkokh_sprav_vidmova(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root, rel=Path("data/raw/dahmo"))
    _file(d / "f315-9000" / "0001.jpg")
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="кількох справ"):
        D.offload(str(d), restore="диск", apply=True)


def test_bez_pasporta_vidmova(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root, pasport=False)
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="паспорта"):
        D.offload(str(d), restore="диск", apply=True)


@pytest.mark.parametrize("mine", [False, None])
def test_bez_vlasnoho_vneska_vidmova(ws: W.Workspace, svit: dict[str, Any], mine: Any) -> None:
    svit["mine"] = mine
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="ВАШОГО"):
        D.offload(str(d), restore="диск", apply=True)
    assert len(list(d.glob("*.jpg"))) == 3


def test_u_puli_menshe_storinok_nizh_znimaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    svit["pool_pages"] = 2
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    with pytest.raises(D.DiskError, match="2 сторінок"):
        D.offload(str(d), restore="диск", apply=True)


def test_zhyvyi_zakhid_tsiiei_spravy_vidmova(ws: W.Workspace, svit: dict[str, Any],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)

    class Run:
        run_id, case_dir, source_dir = "zhyvyi", "", str(d)

    monkeypatch.setattr(D, "_live_runs", lambda: [Run()])
    with pytest.raises(D.DiskError, match="живий захід"):
        D.offload(str(d), restore="диск", apply=True)


def test_druha_adresa_kopii_vidmova(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root, (*VSI, "0004.jpg"))
    _prohin(svit, d, ("0001.jpg",))
    D.offload(str(d), restore="перша копія", apply=True)
    _prohin(svit, d, ("0002.jpg",), name="run2")
    with pytest.raises(D.DiskError, match="перша копія"):
        D.offload(str(d), restore="друга копія", apply=True)
    D.offload(str(d), restore="перша копія", apply=True)
    marker = json.loads((d / D.OFFLOAD_MARKER).read_text(encoding="utf-8"))
    assert marker["restore"] == "перша копія" and marker["frames"] == 2


def test_bez_adresy_kopii_vidmova(ws: W.Workspace, svit: dict[str, Any]) -> None:
    d = _sprava(ws.root)
    with pytest.raises(D.DiskError, match="копія"):
        D.offload(str(d), restore="  ", apply=True)


def test_kadr_lyshe_dlia_chytannia_znimaietsia(ws: W.Workspace, svit: dict[str, Any]) -> None:
    import stat

    d = _sprava(ws.root)
    os.chmod(d / "0001.jpg", stat.S_IREAD)
    _prohin(svit, d, VSI)
    got = D.offload(str(d), restore="диск", apply=True)
    assert not got["errors"] and not list(d.glob("*.jpg"))


def test_poznachka_kazhe_skilky_znyato_naspravdi(ws: W.Workspace, svit: dict[str, Any],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    d = _sprava(ws.root)
    _prohin(svit, d, VSI)
    spravzhnii = D._unlink_file

    def _zainiatyi(p: Path) -> None:
        if p.name == "0002.jpg":
            raise PermissionError("файл відкрито іншим процесом")
        spravzhnii(p)

    monkeypatch.setattr(D, "_unlink_file", _zainiatyi)
    got = D.offload(str(d), restore="диск", apply=True)
    marker = json.loads((d / D.OFFLOAD_MARKER).read_text(encoding="utf-8"))
    assert got["frames"] == 2 and marker["frames"] == 2 and len(got["errors"]) == 1
