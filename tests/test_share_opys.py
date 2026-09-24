"""Опис справи в пакеті: жанр, паспорт, сховище сторінок — і нічого приватного.

🔴 Головне, що стережуть ці тести, — що робочі нотатки дослідника не виїжджають
у каталог. Паспорт теки й сховище сторінок пишуться для себе: у `note` і
`clan_relevance` лежать міркування про рід і посилання на осіб дерева, у
`comment` — хід вичитки. Опис бере поля БІЛИМ СПИСКОМ, а ворота відмовляють
пакету, де такі поля все ж опинились.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _share import make_run, manifest_for

from nyshporka.pagestore.models import CaseFile, PageNote
from nyshporka.share import bundle, gates, opys, upload
from nyshporka.share import publish as PUB

PASPORT: dict[str, Any] = {
    "shifra": "ДАХмО 315-1-8433",
    "title": "Ревизские сказки о духовенстве уезда за 1811 год",
    "record_type": "Ревізькі казки причту (7-ма ревізія)",
    "repository": "Держархів Хмельницької області (ДАХмО)",
    "collection": "Подольская духовная консистория",
    "sheets": 183,
    "date_started": "1811-08-01",
    "date_ended": "1811-08-24",
    "year_from": 1811,
    "year_to": 1811,
    "note": "Ковальський Іван [[особа-дерева]] — наш предок, див. гілку",
    "clan_relevance": "прямий предок",
}


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


# ── жанр ─────────────────────────────────────────────────────────────────────

def test_record_type_daie_kod_zhanru() -> None:
    """У дослідницьких паспортах поле зветься `record_type`, і жанр не мусить губитись."""
    code, types = opys.genre({"record_type": "Ревізькі казки причту"})
    assert code == "revision"
    assert types == ["revision"]


def test_metryka_bez_odnoho_kodu() -> None:
    """Зведена метрика — три типи; вибрати один означало б збрехати в картці."""
    code, types = opys.genre({"record_type": "Метрична книга"})
    assert code == ""
    assert set(types) == {"birth", "marriage", "death"}


# ── паспорт ──────────────────────────────────────────────────────────────────

def test_pasport_lyshe_bilym_spyskom() -> None:
    got = opys.sidecar_extras(PASPORT)
    assert got["repository"].startswith("Держархів")
    assert got["dates"] == ["1811-08-01", "1811-08-24"]
    assert got["record_type"].startswith("Ревізькі")
    assert "note" not in got and "clan_relevance" not in got


def test_case_block_ne_vyvozyt_notatok(tmp_path: Path) -> None:
    case_dir = tmp_path / "spr-8433"
    case_dir.mkdir()
    (case_dir / "_source.json").write_text(json.dumps(PASPORT, ensure_ascii=False),
                                           encoding="utf-8")
    case = PUB._case_block({"key": "DAHMO/315/8433"}, case_dir)

    assert case["doc_type"] == "revision"
    assert case["opys"] == "1", "номер опису не сміє затертись описом справи"
    dump = json.dumps(case, ensure_ascii=False)
    assert "предок" not in dump and "[[" not in dump
    assert not gates._private_keys(case)


# ── сховище сторінок ─────────────────────────────────────────────────────────

def _storinky() -> CaseFile:
    return CaseFile(
        key="DAHMO/315/8433", repo="DAHMO", fond="315", spr="8433", opys="1",
        pages={
            "0001.jpg": PageNote(
                scan="0001.jpg", page_type="revision", status="full",
                surnames=["Ковальський Іван (дяк, 40)", "Мельник?", "Ткачъ Петро"],
                places=["Летичів", "Голенищеве(?)"], years=[1811],
                comment="наш рід — див. дерево [[особа-дерева]]", agent="сесія 12"),
            "0002.jpg": PageNote(
                scan="0002.jpg", page_type="revision", status="partial",
                surnames=["Кравченко"], places=["Кудринці"], years=[1790]),
        })


def test_skhovyshche_lyshe_z_povnykh_arkushiv(monkeypatch: pytest.MonkeyPatch) -> None:
    """`partial` — перелік неповний за визначенням; у картці він читався б як повний."""
    monkeypatch.setattr("nyshporka.pagestore.load_case", lambda ref: _storinky())

    got = opys.from_pagestore("ДАХмО 315-1-8433", frames_total=281)

    assert got["surnames"] == ["Ковальський", "Ткачъ"], "непевне й partial не беруться"
    assert got["places"] == ["Летичів"]
    assert got["years"] == [1811, 1811]
    assert (got["pages_noted"], got["pages_full"], got["frames_total"]) == (2, 1, 281)
    dump = json.dumps(got, ensure_ascii=False)
    assert "наш рід" not in dump and "сесія" not in dump


def test_bez_skhovyshcha_ne_padaie(monkeypatch: pytest.MonkeyPatch) -> None:
    def _nemaie(ref: Any) -> None:
        raise RuntimeError("простір не зібраний")

    monkeypatch.setattr("nyshporka.pagestore.load_case", _nemaie)
    assert opys.from_pagestore("ДАХмО 315-1-8433") == {}


def test_pack_nese_opys_i_heometriiu(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433", pages=4, geometry=True)
    monkeypatch.setattr(PUB, "resolve_runs",
                        lambda scope, **kw: ([run], {"key": "", "shifra": "ДАХмО 315-1-8433"}))
    monkeypatch.setattr("nyshporka.pagestore.load_case", lambda ref: _storinky())

    got = PUB.pack("ДАХмО 315-1-8433", dry_run=True)
    details = got["manifest"]["case"]["details"]

    assert details["geometry"] == {"pages": 4, "of": 4}
    assert details["pagestore"]["surnames"] == ["Ковальський", "Ткачъ"]
    assert got["gates"]["passed"]


# ── ворота ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case_extra", [
    {"note": "нотатка"},
    {"details": {"pagestore": {"comment": "хід вичитки"}}},
    {"title": "Ревізія, див. [[особа-дерева]]"},
])
def test_vorota_vidmovliaiut_pryvatnomu(space: Path, case_extra: dict[str, Any]) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433")
    m = manifest_for([bundle.voice_of(run)])
    m.case.update(case_extra)

    v = gates.check(m)
    assert not v.passed
    assert any("нотат" in r or "дерева" in r for r in v.refusals)


# ── дозалив геометрії ────────────────────────────────────────────────────────

def _paket(space: Path, tmp_path: Path) -> Path:
    run = make_run(space / "reports" / "htr", "spr-8433", geometry=True)
    m = manifest_for([bundle.voice_of(run)])
    text = tmp_path / "pack.nyshtext"
    bundle.write(text, m, [run])
    bundle.write(bundle.geom_path(text), m, [run], patterns=bundle.PACKED_GEOM)
    return text


def _pul(monkeypatch: pytest.MonkeyPatch, dubl: dict[str, Any]) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def _req(method: str, url: str, *, body: Any = None, auth: str = "") -> dict[str, Any]:
        calls.append((method, url))
        if url.endswith("/contributions"):
            return dict(dubl)
        if url.endswith("/geometry"):
            return {"upload": {"geom": "https://r2.example/geom"}}
        return {"ready": True}

    monkeypatch.setattr(upload, "_request", _req)
    monkeypatch.setattr(upload, "_put", lambda url, blob: calls.append(("PUT", url)))
    return calls


def test_dubl_bez_heometrii_dozalyvaie(space: Path, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Перші засіяні справи пішли без рамок; повтор тексту мусить їх довезти."""
    calls = _pul(monkeypatch, {"duplicate": True, "contribution": 7,
                               "geometry": False, "mine": True})

    got = upload.publish(_paket(space, tmp_path), base="https://pul.example/v1", auth="k")

    assert got["geometry_attached"]
    assert ("POST", "https://pul.example/v1/contributions/7/geometry") in calls
    assert ("PUT", "https://r2.example/geom") in calls


@pytest.mark.parametrize("dubl", [
    {"duplicate": True, "contribution": 7, "geometry": True, "mine": True},
    {"duplicate": True, "contribution": 7, "geometry": False, "mine": False},
    {"duplicate": True, "contribution": 7},
])
def test_dubl_ne_dozalyvaie_zaivoho(space: Path, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch,
                                    dubl: dict[str, Any]) -> None:
    """Геометрія вже є, внесок чужий або пул старий — нічого не заливається."""
    calls = _pul(monkeypatch, dubl)

    got = upload.publish(_paket(space, tmp_path), base="https://pul.example/v1", auth="k")

    assert not got.get("geometry_attached")
    assert [c for c in calls if c[0] == "PUT"] == []


# ── назва ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("own, reg, want", [
    ("spr-655 — рендер із PDF для HTR-черги", "Посімейні списки дворян", "Посімейні списки дворян"),
    ("230-1-652 — Список дворян по уездам", "", "Список дворян по уездам"),
    ("ДАХмО ф.315 оп.1 спр.203г: Протоколи засідань", "", "Протоколи засідань"),
    ("FS-індекс (не звірено з титулкою): Parish Registers", "Метрична книга", "Метрична книга"),
    ("Ревизские сказки о духовенстве", "Церковні документи", "Ревизские сказки о духовенстве"),
    ("", "Церковні документи", "Церковні документи"),
])
def test_nazva_bez_robochykh_notatok(own: str, reg: str, want: str) -> None:
    assert opys.title(own, {"title": reg} if reg else None) == want


def test_ocr_nazva_reiestru_ne_ide() -> None:
    """Сирий OCR опису — не назва: ні в картку, ні в опис справи."""
    row = {"title": "Саокт дворян по Баптскому", "title_src": "ocr", "folios": "670"}
    assert opys.title("", row) == ""
    assert opys.from_registry(row) == {"folios": "670"}


def test_nazva_z_biblioteky_ostannoiu() -> None:
    """Паспорт і реєстр мовчать — назву знає бібліотека справ."""
    assert opys.title("", None, "Ревізькі казки однодворців повіту") == \
        "Ревізькі казки однодворців повіту"
    assert opys.title("", None, "spr-655 — рендер із PDF") == ""


def test_reviziina_komisiia_ne_perepys() -> None:
    """Протоколи ревізійної комісії — не ревізькі казки."""
    assert opys.genre({"title": "Протоколи Київської ревізійної комісії за 1838 рік"}) == ("", [])
    assert opys.genre({"title": "Ревизионная комиссия, журналы"}) == ("", [])
    assert opys.genre({"title": "Ревізькі казки однодворців"})[0] == "revision"


def test_seriia_ne_pakuietsia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нерозібрана шифра стає серією фонду — і тягне чужий прогін за хвостом цифр."""
    monkeypatch.setattr("nyshporka.htr_store.runs_for_scope", lambda scope: {
        "rows": [{"name": "25-1-182"}], "kind": "cases", "key": "",
        "shifra": scope, "keys": ["DAVO/25/182"]})

    with pytest.raises(PUB.PublishError, match="не розпізнано як одну справу"):
        PUB.resolve_runs("ДАВіО ф.792 оп.1 спр.25")


@pytest.mark.parametrize("own, want", [
    ("spr-2462 — рендер із PDF для HTR-черги (Dekanat Bialocerkowski, 1750–1750)",
     "Dekanat Bialocerkowski"),
    ("spr-3 — рендер із PDF для HTR-черги (Акти Радомисльського духовного суду, 1754–1756)",
     "Акти Радомисльського духовного суду"),
    ("spr-655 — рендер із PDF для HTR-черги", ""),
])
def test_nazva_z_duzhok_rendera(own: str, want: str) -> None:
    """Паспорт рендера несе справжню назву в дужках — її й брати."""
    assert opys.title(own, None) == want


# ── архів поза довідником ────────────────────────────────────────────────────

def test_nevidomyi_arkhiv_poperedzhaie(space: Path) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433")
    m = manifest_for([bundle.voice_of(run)])
    m.case.update(repo="XYZARCH", shifra="XYZARCH 1-1-5")

    assert "unknown_archive" in [c for c, _ in gates.check(m).warnings]
    m.case["repo_name"] = "Архів міста Кракова"
    assert "unknown_archive" not in [c for c, _ in gates.check(m).warnings]


def test_vidomyi_arkhiv_movchyt(space: Path) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433")
    m = manifest_for([bundle.voice_of(run)])
    assert "unknown_archive" not in [c for c, _ in gates.check(m).warnings]


def test_archive_name_ide_v_manifest(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = make_run(space / "reports" / "htr", "spr-8433")
    monkeypatch.setattr(PUB, "resolve_runs",
                        lambda scope, **kw: ([run], {"key": "", "shifra": "ДАХмО 315-1-8433"}))
    got = PUB.pack("ДАХмО 315-1-8433", dry_run=True, archive_name="  Архів міста Кракова ")
    assert got["manifest"]["case"]["repo_name"] == "Архів міста Кракова"


@pytest.mark.parametrize("row", [
    {"title": "Церковні записи, Подільська духовна консисторія (ф. 315)",
     "title_src": "duck", "_title_repeats": 412},
    {"title": "f. 315-1-3574 Church Records Delo", "title_src": "fs"},
])
def test_zahlushka_kataloho_ne_nazva(row: dict[str, Any]) -> None:
    """Назва, що стоїть на сотнях справ фонду, називає фонд, а не справу."""
    assert opys.title("", row) == ""


def test_fs_zahlushka_z_biblioteky_ne_nazva() -> None:
    assert opys.title("", None, "f  315-1-1121  Church Records BMD  Delo") == ""


# ── шифра, яку паспорт записав по-своєму ─────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "ДАХмО ф.315 оп.1 спр.8433",
    "315-1-8433",
    "ДАХмО 315-1-8433 (арк. окремої секції)",
])
def test_nerozibrana_shyfra_staie_kanonichnoiu(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог шукає за шифрою, яку розбирає резолвер; запис паспорта лишається поруч."""
    from nyshporka.pagestore.store import CaseRef

    ref = CaseRef(key="DAHMO/315/8433", repo="DAHMO", fond="315", spr="8433", opys="1",
                  shifra=raw, title="", path="")

    def _resolve(value: str) -> CaseRef:
        if value in ("DAHMO/315/8433", "ДАХмО 315-1-8433"):
            return ref
        raise ValueError("не розпізнав")

    monkeypatch.setattr("nyshporka.pagestore.resolve_case", _resolve)
    got = PUB._normalize_shifra({"shifra": raw}, "DAHMO/315/8433")

    assert got["shifra"] == "ДАХмО 315-1-8433"
    assert got["shifra_pasport"] == raw
    assert (got["repo"], got["fond"], got["opys"], got["spr"]) == ("DAHMO", "315", "1", "8433")


def test_rozibrana_shyfra_ne_chipaietsia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nyshporka.pagestore.resolve_case", lambda v: object())
    case = {"shifra": "ДАХмО 315-1-8433"}
    assert PUB._normalize_shifra(case, "DAHMO/315/8433") is case


def test_vikirozmitka_ne_nazva() -> None:
    assert opys.title("[[File:ДАХмО 315-1-7195. 1823. Сповід", {"title": "Сповідні розписи, 1823",
                                                                 "title_src": "wikisource"}) \
        == "Сповідні розписи, 1823"


def test_holos_bez_mety_ne_ide(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Голос без мети валив би ворота всьому пакету — він просто не пакується."""
    root = space / "reports" / "htr"
    run = make_run(root, "spr-8433")
    holos = root / "spr-8433-diak_v4"
    holos.mkdir(parents=True)
    (holos / "0001.txt").write_text("рядок\n", encoding="utf-8")
    monkeypatch.setattr("nyshporka.htr_store.runs_for_scope", lambda scope: {
        "rows": [{"name": "spr-8433"}], "kind": "case", "key": "DAHMO/315/8433",
        "shifra": "ДАХмО 315-1-8433"})
    monkeypatch.setattr("nyshporka.cloud.verify.voice_dirs", lambda d: [holos])

    dirs, _ = PUB.resolve_runs("DAHMO/315/8433")
    assert dirs == [run]


@pytest.mark.parametrize("own, want", [
    ("🔥 Подільська палата цивільного суду", "Подільська палата цивільного суду"),
    ("🏆 ⚠ Ревізькі казки", "Ревізькі казки"),
    ("«Выписи из книг»", "«Выписи из книг»"),
])
def test_poznachky_doslidnyka_ne_v_nazvi(own: str, want: str) -> None:
    assert opys.title(own, None) == want
