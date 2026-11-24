"""Добудова прочитаних номерів справ (`numbering.dobuduvaty`, `number(dobudova=True)`): рушій губить
першу цифру на краю колонки («313» замість 1313) і плутає цифру, затерту виправленням («1920» замість
1120); без добудови ланцюжок їх відкидає й рахунок зсувається."""
from __future__ import annotations

from typing import Any

from nyshporka.opysy import numbering as NU


def _recs(reads: list[str]) -> list[dict[str, Any]]:
    return [{"page": "0001", "part": "0", "y": f"{i * 100}-{i * 100 + 90}", "no_read": n,
             "title": f"Дело №{i}", "end": "", "year": "", "folios": ""} for i, n in enumerate(reads)]


def test_starsha_tsyfra_i_pliama() -> None:
    # справу 1302 рушій злив із 1301 (рядка немає): без добудови рахунок від 1301 зсуває
    # наступні на одиницю, як ДАОО ф.445 оп.1 кадр 77 (1309 замість 1313)
    reads = ["1300", "1301", "303", "304", "1905", "1306", "1307"]
    bez = NU.number(_recs(reads))
    z = NU.number(_recs(reads), dobudova=True)
    assert [r["no"] for r in bez][2:5] == [1302, 1303, 1304]
    assert [r["no"] for r in z] == [1300, 1301, 1303, 1304, 1305, 1306, 1307]
    # добудовані стали якорями з підтвердженням сусідами; поле прочитаного не змінилось
    assert all(r["confirmed"] == "neighbors" for r in z[2:5]) and z[2]["no_read"] == "303"
    assert sum(bool(r["confirmed"]) for r in z) > sum(bool(r["confirmed"]) for r in bez)


def test_daleke_chytannia_ne_dobudovuietsia() -> None:
    # «349» на місці 1306 — за вікном ±10 від очікуваного; однозначне «7» — не чіпається
    out = NU.dobuduvaty([(0, 1300), (1, 1301), (2, 349), (3, 7), (4, 1304), (5, 1305)])
    assert dict(out)[2] == 349 and dict(out)[3] == 7


def test_bez_dobudovy_iak_bulo() -> None:
    reads = ["1300", "1301", "1302", "303", "304", "305", "1906", "1307", "1308"]
    a = NU.number(_recs(reads))
    b = NU.number(_recs(reads), dobudova=False)
    assert a == b
