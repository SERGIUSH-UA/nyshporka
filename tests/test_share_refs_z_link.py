"""`--link` на скани — ідентифікатор зйомки, а не лише посилання для ока.

Людина передала `--link "звідки скани=<файл Commons>"`, а ворота далі
казали `no_refs` із порадою додати той самий `--link`.
"""
from __future__ import annotations

from nyshporka.share.publish import _merge_refs, _refs_from_links


def test_commons_i_familysearch() -> None:
    got = _refs_from_links([
        {"label": "звідки скани",
         "url": "https://commons.wikimedia.org/wiki/File:%D0%94%D0%90%D0%A5%D0%9E_40-141-194.pdf"},
        {"label": "fs", "url": "https://www.familysearch.org/search/film/004123456?i=3"},
        {"label": "Вікіджерела", "url": "https://uk.wikisource.org/wiki/Щось"},
    ])
    assert got[0]["source"] == "commons" and got[0]["ref"] == "file:ДАХО_40-141-194.pdf"
    assert got[1] == {"source": "fs", "ref": "dgs:004123456",
                      "url": "https://www.familysearch.org/search/film/004123456?i=3"}
    assert len(got) == 2, "посилання не на скани в refs не йде"


def test_saidkar_vazhyt_bilshe() -> None:
    saidkar = [{"source": "commons", "ref": "file:A.pdf"}]
    got = _merge_refs(saidkar, [{"source": "commons", "ref": "file:B.pdf"},
                                {"source": "fs", "ref": "dgs:1"}])
    assert [r["ref"] for r in got] == ["file:A.pdf", "dgs:1"]
