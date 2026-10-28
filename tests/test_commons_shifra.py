"""📚 Шифра справи з назви файла Commons — для паспорта `nysh get`."""
from __future__ import annotations

import pytest

from nyshporka.sources.commons import shifra_of_ref, shifra_of_title


def _d(inv: str, spr: str, fond: str = "227") -> dict[str, str]:
    return {"archive": "DAHMO", "fond": fond, "inv": inv, "spr": spr}


@pytest.mark.parametrize("title,want", [
    ("ДАХмО 227-2д-905 Объявления о торгах (1899).pdf", _d("2д", "905")),
    ("ДАХмО 227-1-6563а Справи про щось.pdf", _d("1", "6563а")),
    ("ДАХмО 227-1d-356. 1851 рік. Метричні книги.pdf", _d("1д", "356")),
    ("ДАХмО Ф.227, о.2, с.6026 Списки мешканців.pdf", _d("2", "6026")),
    ("ДАХмО Ф. 227 О. 5доп С. 291 Статистичний опис.pdf", _d("5доп", "291")),
    ("1845 год. ДАХМО. Фонд 227, опись 6д, дело 34. Метрическая книга.pdf",
     _d("6д", "34")),
    ("ДАХмО 227-1-355а.pdf", _d("1", "355а")),
])
def test_shifra_z_nazvy(title, want):
    assert shifra_of_title(title) == want


@pytest.mark.parametrize("title", [
    "ДАХмО фонд 227 опис 1 том 1.pdf",          # опис фонду, не справа
    "ДАХмО 227-1-261Справа про призначення.pdf",  # злита назва — фантом справи 26
    "НЕВІДОМИЙ 227-1-5.pdf",                    # архів, якого пак не знає
    "Просто книга.pdf",
    "",
])
def test_ne_vygadue(title):
    assert shifra_of_title(title) == {}


def test_z_adresy_commons():
    ref = "file:ДАХмО 227-2д-905 Объявления (1899).pdf"
    assert shifra_of_ref("commons", ref) == _d("2д", "905")
    assert shifra_of_ref("commons", "https://commons.wikimedia.org/wiki/File:"
                         "ДАХмО_227-1-6563а_Справи.pdf") == _d("1", "6563а")
    assert shifra_of_ref("archium", ref) == {}
    assert shifra_of_ref("commons", "щось без префікса") == {}


def test_passport_gets_shifra(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    res = FetchResult(dest=tmp_path, frames=1)
    record_fetch(tmp_path, res, source="commons",
                 ref="file:ДАХмО 227-2д-905 Объявления (1899).pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert (meta["archive"], meta["fond"], meta["inv"], meta["spr"]) == (
        "DAHMO", "227", "2д", "905")


def test_passport_keeps_existing_shifra(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    (tmp_path / "meta.json").write_text(json.dumps(
        {"archive": "DAHMO", "fond": "230", "inv": "1", "spr": "1539"}),
        encoding="utf-8")
    record_fetch(tmp_path, FetchResult(dest=tmp_path, frames=1), source="commons",
                 ref="file:ДАХмО 227-2д-905 X.pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert (meta["fond"], meta["inv"], meta["spr"]) == ("230", "1", "1539")


def test_passport_without_shifra_writes_no_fields(tmp_path):
    import json

    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    record_fetch(tmp_path, FetchResult(dest=tmp_path, frames=1), source="commons",
                 ref="file:ДАХмО фонд 227 опис 1 том 1.pdf", want=1)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert not {"archive", "fond", "inv", "spr"} & meta.keys()
