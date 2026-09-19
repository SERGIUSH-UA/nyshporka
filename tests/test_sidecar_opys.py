"""Опис справи з паспорта теки читає тільки `_sidecar_opys`.

Підстава — випадок 18.09.2026. Дві справи того самого фонду з однаковими
паспортами (`"opis": 1`) лягли в реєстр різними шифрами: ДАЧО 1462-1-11357 і
ДАЧО 1462-11348. Бібліотека обидві бачила правильно. Різниця була в тому, котрий
шлях зібрав рядок: перша вже була в знімку бібліотеки, друга — ні, і її рядок
складала гілка «матеріал на диску» в `cases/collect.py` зі своїм власним
читанням паспорта. Там поле опису шукали як `opys` / `inv`, а завантажувачі FS
і скіл `fond-case` пишуть `opis`. У `library._fallback_name` цей самий пропуск
виправили раніше — а два інші читачі паспорта лишились без виправлення.

Лікування не в тому, щоб дописати `opis` ще раз: читачів паспорта було три,
кожен зі своїм списком імен поля. Тепер список один — `_sidecar_opys`, — і
структурний тест нижче не дає завести четвертий.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src" / "nyshporka"


@pytest.fixture
def lib(tmp_path: Path):
    """Бібліотека на ТИМЧАСОВОМУ просторі (див. `test_case_key_builder.lib`)."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L

    return L


@pytest.mark.parametrize("field", ["inv", "opys", "opis"])
@pytest.mark.parametrize("value", ["1", 1, "01"])
def test_sidecar_opys_knows_every_field_name(lib, field: str, value) -> None:
    """Кожне з трьох імен поля дає опис; число й провідні нулі не заважають."""
    assert lib._sidecar_opys({field: value}) == "1"


def test_sidecar_opys_empty_is_none(lib) -> None:
    """Паспорт без опису — None, а не порожній рядок: далі йде `or` дефолту."""
    assert lib._sidecar_opys({}) is None
    assert lib._sidecar_opys({"opis": ""}) is None


#: `.get("opis")` / `.get("opys")` / `.get("inv")` — читання поля опису зі словника.
FIELD_READ = re.compile(r'\.get\(\s*"(opis|opys|inv)"\s*\)')


def test_passport_opys_read_only_through_helper() -> None:
    """Жоден модуль не збирає власний список імен поля опису з паспорта.

    Ознака власного списку — два з трьох імен на одному рядку (`inv or opys`).
    Рядок з одним іменем — це читання рядка реєстру опису чи власного
    `meta.json` завантажувача, де поле одне й інших назв не має.
    """
    findings: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, 1):
            names = set(FIELD_READ.findall(line))
            if len(names) < 2:
                continue
            # сама функція-читач — єдине законне місце
            if path.name == "library.py" and "_sidecar_opys" in "".join(lines[max(0, n - 20):n]):
                continue
            findings.append(f"{path.relative_to(PKG)}:{n}: {line.strip()}")
    assert not findings, (
        "опис паспорта читається повз `_sidecar_opys` — власний список імен поля "
        "розійдеться з рештою, як розійшовся `opis`:\n" + "\n".join(findings))


def test_unfiled_row_takes_opys_and_shifra_from_passport(lib, tmp_path: Path,
                                                         monkeypatch) -> None:
    """Гілка «матеріал на диску» бере з паспорта і опис, і людську шифру.

    Саме ця гілка складає рядок для справи, якої ще немає в знімку бібліотеки,
    — тобто для кожної щойно завантаженої.
    """
    from nyshporka.cases import collect as C

    monkeypatch.setattr(C, "ROOT", tmp_path)
    case = tmp_path / "data" / "raw" / "dacho_1462" / "spr-11348"
    case.mkdir(parents=True)
    (case / "_source.json").write_text(json.dumps({
        "fond": 1462, "opis": 1, "sprava": "11348",
        "shifra": "ДАЧО 1462-1-11348",
        "title": "Сповідна книга Миколаївської церкви с. Озеряни, 1764",
    }, ensure_ascii=False), encoding="utf-8")

    side = C._sidecar_near("data/raw/dacho_1462/spr-11348")
    assert side.get("opys") == "1", "опис із поля `opis` загубився"
    assert side.get("shifra") == "ДАЧО 1462-1-11348", "шифру паспорта не передано"
