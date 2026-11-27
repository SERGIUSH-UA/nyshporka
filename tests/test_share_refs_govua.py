"""Сайт державного архіву (`*.gov.ua`) — відоме джерело сканів (рішення дослідника 27.11.2026).

ДАХО викладає метрики ф.40 на archives.kh.gov.ua (таблиці) і daho.archives.gov.ua (ZIP, DjVu).
Пакет із таким `--link` дістав попередження «хост не входить до відомих джерел сканів», а в каталозі
Супряги скани не показувались (ДАХО 40-105-1а).
"""
from __future__ import annotations

import pytest

from nyshporka.share.publish import _ref_z_adresy, _refs_from_links


@pytest.mark.parametrize("url", [
    "https://archives.kh.gov.ua/?page_id=25659",
    "https://archives.kh.gov.ua/",
    "https://daho.archives.gov.ua/metryky/40_105_1a.zip",
    "http://archive.od.gov.ua/metryka/spr.pdf",
    "https://GOV.UA/x",
])
def test_hosty_gov_ua_vidomi(url: str) -> None:
    got = _ref_z_adresy(url)
    assert got is not None and got["source"] == "govua"
    assert got["ref"].startswith("url:http")
    assert got["url"] == url


def test_ref_bez_fragmenta_i_z_khostom_malymy() -> None:
    got = _ref_z_adresy("https://Archives.KH.gov.ua/?page_id=25659#tab")
    assert got is not None and got["ref"] == "url:https://archives.kh.gov.ua/?page_id=25659"


@pytest.mark.parametrize("url", [
    "https://gov.ua.example.com/x",
    "https://example.com/?next=archives.kh.gov.ua",
    "https://notgov.ua/x",
    "ftp://archives.kh.gov.ua/x",
    "https://user:pw" + "@" + "archives.kh.gov.ua/x",  # логін в адресі (зібрано: сканер пошти)
    "javascript:alert(1)//archives.kh.gov.ua",
])
def test_chuzhi_ne_staiut_dzherelom(url: str) -> None:
    assert _ref_z_adresy(url) is None


def test_archium_lyshaietsia_archium() -> None:
    """ARCHIUM ЦДІАК теж на .gov.ua, але його зйомка — файл переглядача, не адреса."""
    got = _ref_z_adresy("https://archium.cdiak.archives.gov.ua/file-viewer/33914/")
    assert got == {"source": "archium", "ref": "file:33914",
                   "url": "https://archium.cdiak.archives.gov.ua/file-viewer/33914/"}


def test_link_liudyny_staie_ref() -> None:
    got = _refs_from_links([{"label": "звідки скани", "url": "https://archives.kh.gov.ua/?page_id=25659"}])
    assert got == [{"source": "govua", "ref": "url:https://archives.kh.gov.ua/?page_id=25659",
                    "url": "https://archives.kh.gov.ua/?page_id=25659"}]


def test_vorota_radiat_perepakuvaty_a_ne_nevidomyi_host() -> None:
    """Пакет, залитий до 0.49.6 (посилання є, `refs` порожні): порада перепакувати, без «невідомого»."""
    from _share import manifest_for

    from nyshporka.share import gates

    m = manifest_for([], pages=3, frames=3, lines=6, chars=120)
    m.refs = []
    m.links = [{"label": "Скани", "url": "https://archives.kh.gov.ua/?page_id=25659"}]
    text = next(t for code, t in gates.check(m).warnings if code == "no_refs")
    assert "не входить до відомих" not in text
    assert "pack" in text
