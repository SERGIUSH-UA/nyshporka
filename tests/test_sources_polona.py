"""Polona: об'єкт Biblioteka Narodowa — відоме джерело зйомки.

Нова адреса (картка чи переглядач) і стара `item/…` називають той самий
об'єкт; розійдуться — і пул матиме дві зйомки однієї книги.
"""
from __future__ import annotations

import pytest

from nyshporka.core import polona
from nyshporka.share import publish
from nyshporka.share.publish import _refs_from_links

UUID = "aca2e8b4-8b4f-472d-96ca-0130c4562be1"
PREVIEW = f"https://polona.pl/preview/{UUID}"
OLD = "134805378"  # base64 → MTM0ODA1Mzc4


@pytest.fixture(autouse=True)
def _bez_merezhi(monkeypatch: pytest.MonkeyPatch) -> None:

    def fake(old: str) -> str | None:
        return UUID if old == OLD else None

    monkeypatch.setattr(polona, "_fetch_new_id", fake)


@pytest.mark.parametrize("url", [
    PREVIEW,
    f"https://polona.pl/item-view/{UUID}?page=3",
    f"polona.pl/preview/{UUID.upper()}",
    f"https://www.polona.pl/item-view/{UUID}/",
    "https://polona.pl/item/proza-polska-wieku-xvi,MTM0ODA1Mzc4/0/#info:metadata",
    f"https://polona.pl/item/{OLD}/5",
])
def test_odyn_obiekt_z_usikh_form(url: str) -> None:
    got = _refs_from_links([{"label": "скани", "url": url}])
    assert got == [{"source": "polona", "ref": f"object:{UUID}", "url": PREVIEW}]


@pytest.mark.parametrize("url", [
    "https://polona.pl/",
    "https://polona.pl/search?query=Zrodla",
    "https://polona.pl/preview/not-a-uuid",
    f"https://example.org/preview/{UUID}",
    "https://polona.pl/item/nazwa,ISE/0/",          # base64 не число
    "https://polona.pl/item/nazwa,OTk5OTk5/0/",     # API не знає ID
])
def test_inshe_ne_zjomka(url: str) -> None:
    assert polona.resolve(url) is None


def test_merezha_vpala(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(old: str) -> str | None:
        raise OSError("offline")

    monkeypatch.setattr(polona, "_fetch_new_id", boom)
    assert polona.resolve(f"https://polona.pl/item/{OLD}/0") is None
    # Нова адреса мережі не потребує.
    assert polona.resolve(PREVIEW) == polona.Item(UUID)


def test_ref_tudy_i_nazad() -> None:
    item = polona.from_url(PREVIEW)
    assert item is not None
    assert polona.from_ref(item.ref) == item
    assert polona.from_ref(f"polona:object:{UUID}") == item
    assert polona.from_ref("object:") is None
    assert polona.from_ref("object:../x") is None
    assert polona.from_ref(f"item:{UUID}") is None


def test_stara_adresa_bez_vidpovidi_porada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неперекладена стара адреса — порада дати нову, а не «хост невідомий»."""
    from types import SimpleNamespace

    from nyshporka.share.gates import _no_refs_text

    monkeypatch.setattr(polona, "_fetch_new_id", lambda old: None)
    m = SimpleNamespace(links=[{"url": f"https://polona.pl/item/{OLD}/0"}])
    text = _no_refs_text(m)  # type: ignore[arg-type]
    assert "polona.pl/preview/<uuid>" in text
    assert publish._ref_z_adresy(PREVIEW) is not None
