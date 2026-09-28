"""Друковане видання в пулі: ключ `VYD/<код>/<рік>`, пакет, прийом.

Приймач — те саме кільце, що й для справи: рік газети, спакований із теки
сторінок, проходить ворота без шифри архіву, а прийнятий лягає в стор під
ключем видання, за яким його знаходить `--case`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka import vydannia
from nyshporka.share import bundle, gates
from nyshporka.share.print_pack import pack_print, run_name
from nyshporka.share.publish import PublishError


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def _pages(root: Path, n: int = 3) -> Path:
    src = root / "pev_1880"
    src.mkdir(parents=True)
    for i in range(1, n + 1):
        (src / f"{i:04d}.txt").write_text(
            f"ПОДОЛЬСКІЯ ЕПАРХІАЛЬНЫЯ ВѢДОМОСТИ\nсвященникъ Григорій Вишневецкій, стор. {i}\n",
            encoding="utf-8")
    return src


def test_kliuch_vydannia_rozbyraietsia_i_skladaietsia() -> None:
    assert vydannia.key("pev", 1880) == "VYD/PEV/1880"
    assert vydannia.parse("VYD/PEV/1880") == ("PEV", 1880)
    assert vydannia.parse("vyd khev-1911") == ("KHEV", 1911)
    assert vydannia.parse("DAHMO/315/8433") is None
    assert vydannia.parse("VYD/PEV/188") is None
    with pytest.raises(ValueError):
        vydannia.key("ПЕВ", 1880)


def test_resolve_case_znaie_vydannia(space: Path) -> None:
    from nyshporka.pagestore import resolve_case

    ref = resolve_case("VYD/PEV/1880")
    assert (ref.key, ref.repo, ref.fond, ref.spr, ref.opys) == (
        "VYD/PEV/1880", "VYD", "PEV", "1880", None)
    # Шифра розбирається назад у той самий ключ — на ній тримається сервер.
    assert resolve_case(ref.shifra).key == ref.key


def test_pakunok_vydannia_prokhodyt_vorota_bez_shyfry_arkhivu(space: Path) -> None:
    src = _pages(space)
    issues = [{"no": 1, "first_page": 1, "source_url": "https://archive.org/details/PEV.1880"}]
    got = pack_print(src, "PEV", 1880, title="Подольские епархиальные ведомости",
                     ocr_by="archive.org", ocr_layer="djvu", issues=issues,
                     places=["Поділля"], dest=space / "out" / "p.nyshtext")
    assert got["gates"]["passed"], got["gates"]
    m = bundle.read_manifest(Path(got["path"]))
    assert m.shifra == "VYD/PEV/1880"
    assert m.case["title"] == "Подольские епархиальные ведомости, 1880"
    assert m.case["years"] == [1880, 1880]
    assert m.pages == 3
    assert m.models() == ["OCR · archive.org (djvu)"]
    assert m.extra["publication"]["issues"][0]["source_url"].endswith("PEV.1880")
    assert m.refs == [{"source": "url", "ref": "PEV 1880 №1",
                       "url": "https://archive.org/details/PEV.1880"}]
    assert bundle.run_names(Path(got["path"])) == [run_name("PEV", 1880)]


def test_readme_vydannia_nazyvaie_dzherelo_a_ne_rushii(space: Path) -> None:
    src = _pages(space)
    got = pack_print(src, "PEV", 1880, title="ПЕВ", ocr_by="archive.org",
                     issues=[{"no": 7, "source_url": "https://example.org/7.pdf"}],
                     dest=space / "p.nyshtext")
    import tarfile

    with tarfile.open(got["path"], "r:gz") as tar:
        readme = tar.extractfile(bundle.README_NAME).read().decode("utf-8")
    assert "текстовий шар: archive.org" in readme
    assert "№7 — https://example.org/7.pdf" in readme
    assert "рушій" not in readme


def test_bez_dzherela_tekstu_ne_pakuietsia(space: Path) -> None:
    with pytest.raises(PublishError, match="текстовий шар"):
        pack_print(_pages(space), "PEV", 1880, title="ПЕВ", ocr_by=" ")


def test_vorota_vse_shche_vidmovliaiut_smittiu(space: Path) -> None:
    src = space / "trash"
    src.mkdir()
    for i in range(1, 4):
        (src / f"{i:04d}.txt").write_text("а\nб\nв\n", encoding="utf-8")
    got = pack_print(src, "BEV", 1880, title="БЕВ", ocr_by="pdf", dry_run=True)
    assert not got["gates"]["passed"]
    assert any("середній рядок" in r for r in got["gates"]["refusals"])


def test_pryiniatyi_rik_liahaie_pid_kliuchem_vydannia(space: Path) -> None:
    from nyshporka.share.accept import accept

    got = pack_print(_pages(space), "PEV", 1880, title="ПЕВ", ocr_by="archive.org",
                     dest=space / "p.nyshtext")
    back = accept(got["path"])
    assert back["case_key"] == "VYD/PEV/1880"
    assert back["runs"] == ["vyd_pev_1880"]


def test_gate_check_na_manifesti_vydannia_bez_modeli_vidmovliaie(space: Path) -> None:
    got = pack_print(_pages(space), "PEV", 1880, title="ПЕВ", ocr_by="archive.org",
                     dry_run=True)
    m = bundle.Manifest.from_json(got["manifest"])
    m.decode = {**m.decode, "voices": [{**m.voices[0], "model": ""}]}
    assert not gates.check(m).passed


def test_pull_vydannia_bere_po_odnomu_paketu_na_rik(space: Path, monkeypatch) -> None:
    from nyshporka import ops_share
    from nyshporka.share import accept as A
    from nyshporka.share import catalog as C

    rows = [C.Row(shifra="VYD/PEV/1881", url="u81b", sha256="b"),
            C.Row(shifra="VYD/PEV/1880", url="u80", sha256="a"),
            C.Row(shifra="VYD/PEV/1881", url="u81a", sha256="c"),
            C.Row(shifra="VYD/PEVX/1880", url="x", sha256="x"),
            C.Row(shifra="VYD/PEV/1900", url="u00", sha256="d")]

    def fake_search(q, base="", *, limit=50, offset=0):
        return (rows[offset:offset + limit], len(rows), 99)

    taken: list[str] = []
    monkeypatch.setattr(C, "search", fake_search)
    monkeypatch.setattr(A, "accept", lambda url, sha256="": taken.append(url) or
                        {"case_key": "k", "pages": 1, "runs": []})
    env = ops_share.share_pull(ops_share.SharePullArgs(
        vydannia="pev", years="1880-1890", take=True))
    assert env.ok, env
    assert env.data["years"] == [1880, 1881]
    assert taken == ["u80", "u81b"]
    assert json.dumps(env.data, ensure_ascii=False)


def test_seriia_vydannia_ie_oblastiu_poshuku(space: Path, monkeypatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.share.accept import accept

    monkeypatch.setattr(S, "HTR_ROOT", space / "reports" / "htr")
    monkeypatch.setattr(S, "_RUNS_CACHE", None)

    assert vydannia.parse_series("VYD/PEV") == "PEV"
    assert vydannia.parse_series("VYD/PEV/1880") is None
    for rik in (1880, 1881):
        src = space / f"s{rik}"
        src.mkdir()
        (src / "0001.txt").write_text("священникъ Григорій Вишневецкій, строка\n",
                                      encoding="utf-8")
        got = pack_print(src, "PEV", rik, title="ПЕВ", ocr_by="archive.org",
                         dest=space / f"p{rik}.nyshtext")
        accept(got["path"])
    scope = S.runs_for_scope("VYD/PEV")
    assert sorted(r["name"] for r in scope["rows"]) == ["vyd_pev_1880", "vyd_pev_1881"]
