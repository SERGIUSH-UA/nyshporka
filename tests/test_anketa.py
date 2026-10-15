"""Анкета: прізвище з поля бланка, а не з частоти слів.

Будова сторінок — як у справжній картотеці 15.10.2026 (облікові картки
1949 року, два голоси); прізвища вигадані.
"""
from collections.abc import Iterator
from pathlib import Path

import pytest

from nyshporka.records import anketa as A
from nyshporka.share import bundle, gates

#: Підпис поля в тому ж рядку, значення після нього.
V_RIADKU = "т\n1. Фам. Дмитренко\n2. Имя Семен\n3. Отч. Ефимович\n4. Год Рожд. 5. Место рожД."

#: Підпис поля зіпсований рушієм («.МИЛИА»), значення рядком нижче.
NYZHCHE = "на СОВ. ГРАЖ\n.МИЛИА\nКовтуненко\nПетро\n2 ИимяМ 3. ОтчестВо\n4. Год рождения 1924."

#: Склади, рознесені рушієм.
SKLADY = "1. Фамилия\nдм ит ре нко\n2. Имя\nИван"

#: Бланк, де всі підписи першими, а значення під ними.
PIDPYSY_PERSHYMY = "2. Имя\n3. Отч.\n4. ГодРОжд\nОдмитренкова\n\nМария\nфедоровна"

#: Зворот картки — поля «Имя» в шапці немає.
ZVOROT = ("13. В каких странах проживал и что делал\nГермания\n"
          "14. Где и когда прошел фильтрацию\n16. Решение фильтрационного органа")

#: Німецький бланк: «Vorname», «Имя отца» — не лице картки з прізвищем.
NIMETSKYI = "9. Vогпатe дes Vаteгs:\nИмя отца\nАким\n10. Нате дег Минeг:\nИмя матери"


@pytest.mark.parametrize("text,want", [
    (V_RIADKU, "Дмитренко"),
    (NYZHCHE, "Ковтуненко"),
    (SKLADY, "Дмитренко"),
    (PIDPYSY_PERSHYMY, "Одмитренкова"),
])
def test_pole_prizvyshcha(text: str, want: str) -> None:
    assert A.pole_prizvyshcha(text) == want


@pytest.mark.parametrize("text", [ZVOROT, NIMETSKYI, "", "Метрична книга\n1. Родился Иван"])
def test_ne_anketa_nichoho_ne_daie(text: str) -> None:
    assert A.pole_prizvyshcha(text) == ""


def test_prizvyshche_na_ram_ne_pidpys() -> None:
    """«Рам…» — початок прізвища, а не скорочення «Фам.».

    Якби «Рамзин» вважався підписом поля, значенням став би наступний рядок.
    """
    assert A.pole_prizvyshcha("Рамзин\nКовтун\n2. Имя\n3. Отч.") == ""
    assert A.pole_prizvyshcha("1. Фамилия\nРамзин\n2. Имя\nОлег") == "Рамзин"


def test_imia_i_po_batkovi_ne_prizvyshche() -> None:
    assert A.pole_prizvyshcha("2. Имя\n3. Отч.\nИван\nПетрович\nДмитренко") == "Дмитренко"


def test_varianty_bez_pershoi_litery() -> None:
    """Рушій калічить першу літеру: «Рабченко» має знаходитись як «Абченко»."""
    assert A.varianty("Рабченко") == ["Рабченко", "Абченко"]
    assert A.varianty("Абич") == ["Абич"]
    assert A.varianty("Аб") == []


def test_zibraty_z_anket() -> None:
    got = A.zibraty_z_anket([V_RIADKU, V_RIADKU, ZVOROT, NYZHCHE])
    assert got["Дмитренко"] == 2
    assert got["Митренко"] == 2
    assert got["Ковтуненко"] == 1
    assert not any("Герман" in k for k in got)


def test_doreformenist() -> None:
    vyhadka = "Ольгопольскаго Ѳеономъ Святомъ Сумская обл. г. Сумы Петренко Иван"
    assert A.doreformenist(vyhadka) == pytest.approx(3 / 8)
    assert A.doreformenist("Сумская обл. Петренко Иван") == 0.0
    assert A.doreformenist("") == 0.0


# ── брама «голос пише дореформеним правописом» ───────────────────────────────

def _manifest(years: list[int], share: float) -> bundle.Manifest:
    return bundle.Manifest(
        case={"shifra": "ДАСО Р-7641-1-1", "years": years},
        decode={"pages": 10, "lines": 100, "chars": 3000,
                "voices": [{"run": "r", "model": "pysar_cyr_v19.pt", "prereform": share}]},
        frames={"total": 10}, license={"text": "CC0-1.0"})


def _era(m: bundle.Manifest) -> list[str]:
    return [c for c, _ in gates.check(m).warnings if c == "prereform_voice"]


def test_brama_ery() -> None:
    assert _era(_manifest([1942, 1945], 0.127)) == ["prereform_voice"]
    assert _era(_manifest([1942, 1945], 0.027)) == [], "Дяк на тих самих картках"
    assert _era(_manifest([1850, 1855], 0.5)) == [], "до реформи ъ — норма"
    assert _era(_manifest([], 0.5)) == [], "років не знаємо — не судимо"


@pytest.fixture()
def run_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "run"
    d.mkdir()
    (d / "0001.txt").write_text("Ольгопольскаго Ѳеономъ Петренко Иван\n", encoding="utf-8")
    (d / "0002.txt").write_text("Сумская область Петренко\n", encoding="utf-8")
    yield d


def test_holos_nese_chastku(run_dir: Path) -> None:
    v = bundle.voice_of(run_dir)
    assert v.prereform == pytest.approx(2 / 7)
    assert v.as_json()["prereform"] == pytest.approx(2 / 7, abs=1e-4)
