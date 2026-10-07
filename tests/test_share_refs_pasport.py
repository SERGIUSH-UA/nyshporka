"""Посилання на скани з паспорта справи — в усіх формах, у яких воно лежить.

28.09.2026 у пулі стояло 822 книги без посилання на скани, хоча для 298 з
них посилання було в паспортах на машині, що заливала: у теці, з якої
сторінки відрендерено, у старому `meta.json`, у мітці чистки бінарників
Commons. Пакувальник цих форм не бачив, і людина, яка знайшла прізвище в
тексті, не могла дійти до скану.
"""
from __future__ import annotations

import json
from pathlib import Path

from nyshporka.share.publish import (
    _ref_z_adresy,
    _refs_from_links,
    _refs_from_sidecar,
    _znamennyk_z_pasporta,
)

UPLOAD = ("https://upload.wikimedia.org/wikipedia/commons/c/cd/"
          "%D0%94%D0%90%D0%A5%D0%BC%D0%9E_315-1-7360._1831.pdf?utm_source=x")


def _json(p: Path, dani: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dani, ensure_ascii=False), encoding="utf-8")


def test_render_z_pdf_bere_meta_json_dzherela(tmp_path: Path) -> None:
    """Тека рендера знає лише «рендер із PDF», а адреса — у `meta.json` поруч із PDF."""
    dzherelo = tmp_path / "dahmo_315" / "spr-7360"
    _json(dzherelo / "meta.json", {"fond": "315", "files": [
        {"file": "x.pdf", "pagecount": 936, "source_url": UPLOAD}]})
    render = tmp_path / "dahmo_315_pages" / "spr-7360"
    _json(render / "_source.json", {"title": "spr-7360 — рендер із PDF для HTR-черги",
                                    "rendered_from": [str(dzherelo / "x.pdf")]})

    refs = _refs_from_sidecar(render)
    assert refs and refs[0]["source"] == "commons"
    assert refs[0]["ref"] == "file:ДАХмО_315-1-7360._1831.pdf"
    assert _znamennyk_z_pasporta({"total": 0, "listed": 0}, render)["total"] == 936


def test_nazva_commons_z_mitky_chystky(tmp_path: Path) -> None:
    """Бінарники прибрано після звірки — назва Commons лишилась лише в мітці."""
    _json(tmp_path / "_source.json", {"source": "wikimedia_commons", "frames": 1702,
                                      "purged_commons_verified": {
                                          "commons_title": "File:ДАХмО_315-1-6664.pdf"}})
    assert _refs_from_sidecar(tmp_path) == [
        {"source": "commons", "ref": "file:ДАХмО_315-1-6664.pdf"}]


def test_bagatotomna_nazva_dilytsia_na_tomy(tmp_path: Path) -> None:
    _json(tmp_path / "_source.json", {
        "commons_title": "ДАХмО_315-1-7864._Частина_1.pdf; File:ДАХмО_315-1-7864._Частина_2.pdf"})
    assert [r["ref"] for r in _refs_from_sidecar(tmp_path)] == [
        "file:ДАХмО_315-1-7864._Частина_1.pdf", "file:ДАХмО_315-1-7864._Частина_2.pdf"]


def test_source_url_na_commons_ne_ide_yak_url(tmp_path: Path) -> None:
    """Вид `url` пул не приймає — адреса Commons мусить стати посиланням Commons."""
    _json(tmp_path / "_source.json", {
        "source_url": "https://commons.wikimedia.org/wiki/File:ДАХмО 230-1-33. 1802.pdf"})
    refs = _refs_from_sidecar(tmp_path)
    assert [r["source"] for r in refs] == ["commons"]


def test_odne_pravylo_dlia_link_i_pasporta() -> None:
    assert _refs_from_links([{"url": UPLOAD}])[0]["source"] == "commons"
    assert _ref_z_adresy("https://www.familysearch.org/search/film/004123456") == {
        "source": "fs", "ref": "dgs:004123456",
        "url": "https://www.familysearch.org/search/film/004123456"}
    assert _ref_z_adresy("https://archium.dahmo.gov.ua/file-viewer/51068/")["ref"] == "file:51068"  # type: ignore[index]
    assert _ref_z_adresy("https://example.org/scan.pdf") is None


AGAD_DIR = "http://agadd2.home.net.pl/metrykalia/MK/0183/dirindex.html"


def test_agad_kadr_i_perelik_dayut_odnu_knygu() -> None:
    """Сервер сканів AGAD: тека, перелік і кадр книги - та сама зйомка `mk:183`."""
    want = {"source": "agad", "ref": "mk:183", "url": AGAD_DIR}
    assert _ref_z_adresy(AGAD_DIR) == want
    assert _ref_z_adresy("http://agadd2.home.net.pl/metrykalia/MK/0183/") == want
    assert _ref_z_adresy(
        "http://agadd2.home.net.pl/metrykalia/MK/0183/PL_1_4_1-183_0258.jpg") == want
    assert _refs_from_links([{"url": AGAD_DIR, "role": "scans"}]) == [want]


def test_agad_chuzhyi_khost_i_bez_knygy() -> None:
    assert _ref_z_adresy("http://agadd2.home.net.pl/metrykalia/MK/") is None
    assert _ref_z_adresy("http://agadd2.home.net.pl/metrykalia/MK/0000/") is None
    assert _ref_z_adresy("https://agad.gov.pl/metrykalia/MK/0183/") is None


def test_agad_z_pasporta_fetched_url(tmp_path: Path) -> None:
    """Паспорт завантаження книги MK: адреса сервера в `fetched_url`."""
    _json(tmp_path / "_source.json", {"fetched_url": AGAD_DIR, "frames_got": 514})
    assert _refs_from_sidecar(tmp_path) == [
        {"source": "agad", "ref": "mk:183", "url": AGAD_DIR}]


def test_agad_ref_nazad() -> None:
    from nyshporka.core import agad

    assert agad.from_ref("mk:183") == agad.Book(183)
    assert agad.from_ref("agad:mk:183").url == AGAD_DIR  # type: ignore[union-attr]
    assert agad.from_ref("mk:0") is None and agad.from_ref("file:183") is None
