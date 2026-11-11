"""Назва-заглушка не пакується без рішення автора.

11.11.2026 у пулі лежали тисячі карток «Церковні записи (за каталогом
FamilySearch)», а з партії 51 справи ф.315 у 46 стояла назва фонду
«Церковні записи, Подільська духовна консисторія (ф. 315)», переписана обходом
у паспорт, і в 5 — сама «Подільська губ.».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _share import make_run

pytestmark = pytest.mark.zahlushka

ZAHLUSHKA_315 = "Церковні записи, Подільська духовна консисторія (ф. 315)"


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


def _sprava(space: Path, monkeypatch: Any, *, side: dict[str, Any] | None = None,
            row: dict[str, Any] | None = None) -> Any:
    from nyshporka.share import align, opys
    from nyshporka.share import publish as PUB

    root = space / "reports" / "htr"
    root.mkdir(parents=True, exist_ok=True)
    run = make_run(root, "spr-10052", pages=4)
    home = space / "data" / "raw" / "dahmo_315" / "spr-10052"
    home.mkdir(parents=True, exist_ok=True)
    (home / "_source.json").write_text(
        json.dumps({"frames_got": 4, **(side or {})}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(PUB, "resolve_runs", lambda scope, **kw: (
        [run], {"key": "DAHMO/315/1/10052", "shifra": "ДАХмО 315-1-10052"}))
    monkeypatch.setattr(align, "case_home_for", lambda key, *a, **kw: home)
    monkeypatch.setattr(align, "library_frames", lambda key: 0)
    monkeypatch.setattr(opys, "registry_row", lambda shifra: row)
    return PUB


def test_zahlushka_reiestru_v_pasporti_ne_nazva(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import opys

    row = {"title": ZAHLUSHKA_315, "_title_repeats": 400}
    assert opys.title(ZAHLUSHKA_315, row) == "", \
        "заглушка реєстру, переписана в паспорт, — та сама заглушка"
    assert opys.title("Справа про розірвання шлюбу", row) == "Справа про розірвання шлюбу"


def test_same_mistse_ne_nazva() -> None:
    from nyshporka.share import opys

    assert opys.passport_title({"place": "Подільська губ."}) == ""


def test_bez_nazvy_pakuvannia_vidmovliaie(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share.publish import PublishError

    PUB = _sprava(space, monkeypatch, side={"title": ZAHLUSHKA_315},
                  row={"title": ZAHLUSHKA_315, "_title_repeats": 400})
    proba = PUB.pack("DAHMO/315/1/10052", geometry=False, dry_run=True)
    assert proba["title_stub"]
    assert any("--stub-title-ok" in r for r in proba["pack_refusals"]), \
        "відмова мусить казати, як віддати й так"
    with pytest.raises(PublishError, match="share card"):
        PUB.pack("DAHMO/315/1/10052", geometry=False)


def test_kartka_z_nazvoiu_znimaie_vidmovu(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import card as K

    PUB = _sprava(space, monkeypatch, side={"title": ZAHLUSHKA_315},
                  row={"title": ZAHLUSHKA_315, "_title_repeats": 400})
    nazva = "Справа про розірвання шлюбу селянки м. Шаргорода Могилівського повіту"
    got = PUB.pack("DAHMO/315/1/10052", geometry=False,
                   card_fields=K.normalize(title=nazva))
    assert got["manifest"]["case"]["title"] == nazva
    assert "title_stub" not in got


def test_avtor_na_pryntsypi_viddaie_z_zahlushkoiu(space: Path, monkeypatch: Any) -> None:
    PUB = _sprava(space, monkeypatch)
    got = PUB.pack("DAHMO/315/1/10052", geometry=False,
                   stub_title_ok="титулки немає, справа без обкладинки")
    assert got["manifest"]["extra"]["stub_title_ok"] == "титулки немає, справа без обкладинки", \
        "рішення автора їде з пакетом"


def test_spravzhnia_nazva_pasporta_ide(space: Path, monkeypatch: Any) -> None:
    nazva = "Метрична книга церков Проскурівського повіту за 1870 рік"
    PUB = _sprava(space, monkeypatch, side={"title": nazva})
    got = PUB.pack("DAHMO/315/1/10052", geometry=False)
    assert got["manifest"]["case"]["title"] == nazva


def test_perelik_bachyt_te_same_shcho_pakuvannia(space: Path, monkeypatch: Any) -> None:
    """`suggest` ставить «без назви» тим самим ланцюгом, що й пакування."""
    from nyshporka.share import card as K
    from nyshporka.share import opys

    _sprava(space, monkeypatch, side={"title": ZAHLUSHKA_315},
            row={"title": ZAHLUSHKA_315, "_title_repeats": 400})
    assert opys.zahlushka_spravy("DAHMO/315/1/10052", "ДАХмО 315-1-10052")
    K.set_fields("DAHMO/315/1/10052", K.normalize(title="Справа про розірвання шлюбу"))
    assert opys.zahlushka_spravy("DAHMO/315/1/10052", "ДАХмО 315-1-10052") == ""


def test_push_rishennia_na_vsiu_pachku() -> None:
    from nyshporka.ops_share import SharePackArgs, SharePushArgs

    assert "stub_title_ok" in SharePackArgs.model_fields, "рядок файла переліку може нести рішення"
    assert "stub_title_ok" in SharePushArgs.model_fields


@pytest.mark.parametrize("case, kartka, zahl", [
    ({"title": ""}, None, True),
    ({"title": "Церковні записи (за каталогом FamilySearch)", "title_src": "catalog"}, None, True),
    ({"title": "Метрична книга (народження) · Подільська губ.", "title_src": "pasport"}, None, True),
    ({"title": "f. 315-1-1627 Church Records Po obvineniyu"}, None, True),
    ({"title": "Церковні документи"}, None, True),
    ({"title": "Справа про догану вчителю", "title_src": "pasport"},
     {"title": "Справа про догану вчителю"}, False),
    ({"title": "Сповідні розписи церков Уманського повіту"}, None, False),
])
def test_shcho_vvazhaietsia_zahlushkoiu(case: dict[str, Any], kartka: dict[str, Any] | None,
                                        zahl: bool) -> None:
    from nyshporka.share import opys

    assert bool(opys.zahlushka(case, kartka)) is zahl
