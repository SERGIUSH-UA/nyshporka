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
