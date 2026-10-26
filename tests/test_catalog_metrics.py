"""📚 Покажчик метрик за селом (пак `metrics`).

Що тут тримається тестом:

1. **Кирилиця з кирилицею — напряму.** Точний збіг, «~» за закінченням, приписне
   село; нечіткий збіг через транслітерацію — лише між різними письмами.
2. **Історична назва зі знахідки шукається далі, але лише точно.** Польська форма
   «Zielonka» з одного каталогу знаходить «Зеленку» іншого, а схожі на неї чужі
   села («Зеленівка») — ні.
3. **Сільрада не стає селом.** Запис «Ковалівська с/р» знаходиться за основою з
   позначкою «сільрада ~», а назва села з прикметника не вигадується.
4. **Повіт звужує, але не ховає записів без повіту.**
5. **Нуль — з підказкою схожих назв і зі знаменником; без пака — не нуль.**
6. **Сусіди по книгах:** село, що лежить у тих самих книгах, і його окремі книги.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

#: Вигадані записи: ні назви, ні шифри не належать жодному джерелу.
RECORDS: list[dict[str, Any]] = [
    {"vol": "cat-a", "source": "Каталог А", "page": 12, "archive": "ДАТЕ",
     "conf": "Греко-католицизм", "gub": "Тестове воєводство",
     "church": "св. Миколая", "place": "Зеленка", "place_alt": "Zielonka",
     "povit": "Долина", "attached": ["Липівці"],
     "refs": [{"kinds": ["народження"], "years": "1835-1840", "fond": "9", "opys": "1", "spr": "10"},
              {"kinds": ["смерть"], "years": "1841-1850", "fond": "9", "opys": "1", "spr": "11"}]},
    {"vol": "geo-b", "source": "Покажчик Б", "page": 3, "archive": "ДАТЕ",
     "church": "ф.9, покажчик", "place": "Зеленка", "povit": "Долинський р-н",
     "refs": [{"kinds": ["народження"], "years": "1866-1938", "fond": "9", "opys": "8", "spr": "52"}]},
    {"vol": "geo-b", "source": "Покажчик Б", "page": 3, "archive": "ДАТЕ",
     "church": "ф.9, покажчик", "place": "Лугове", "povit": "Долинський р-н",
     "refs": [{"kinds": ["народження"], "years": "1866-1938", "fond": "9", "opys": "8", "spr": "52"},
              {"kinds": ["народження"], "years": "1866-1938", "fond": "9", "opys": "8", "spr": "56"}]},
    # інше письмо: польська назва без кириличної — знаходиться лише транслітерацією
    {"vol": "pl-c", "source": "Опис В", "archive": "ARCH", "church": "kościół",
     "place": "Zielonka", "povit": "",
     "refs": [{"kinds": ["шлюб"], "years": "1790", "fond": "456", "opys": "1", "spr": "7"}]},
    # схоже чуже село: не має з'являтись через історичну назву
    {"vol": "cat-a", "source": "Каталог А", "archive": "ДАІН", "church": "церква",
     "place": "Зеленівка", "povit": "Інший",
     "refs": [{"kinds": ["народження"], "years": "1850", "fond": "1", "opys": "1", "spr": "1"}]},
    # сільрада без назви села
    {"vol": "racs", "source": "Опис РАЦС", "archive": "ДАТЕ", "church": "книги РАЦС",
     "place": "Ковалівська с/р", "povit": "Тестовий р-н", "sr_keys": ["ковалів"],
     "refs": [{"kinds": ["народження"], "years": "1925", "fond": "Р100", "opys": "1", "spr": "5"}]},
    # однойменне село іншого повіту і таке саме без повіту
    {"vol": "cat-a", "source": "Каталог А", "archive": "ДАТЕ", "church": "церква",
     "place": "Липник", "povit": "Перший",
     "refs": [{"kinds": ["народження"], "years": "1800", "fond": "2", "opys": "1", "spr": "1"}]},
    {"vol": "cat-a", "source": "Каталог А", "archive": "ДАТЕ", "church": "синагога",
     "place": "Липник", "povit": "",
     "refs": [{"kinds": ["народження"], "years": "1880", "fond": "3", "opys": "1", "spr": "1"}]},
]


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    from nyshporka.catalog import build as B
    from nyshporka.catalog import store as S

    src = tmp_path / "records.jsonl"
    src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in RECORDS) + "\n",
                   encoding="utf-8")
    B.build_metrics(src, cat / "metrics-test-2026.10.sqlite", pack_id="metrics-test-2026.10",
                    taken="2026-10-26", source="https://example.org")
    S.invalidate()
    yield cat
    S.invalidate()


def _find(q: str) -> Any:
    from nyshporka.catalog.query import find_metrics

    return find_metrics(q)


def _places(ans: Any) -> list[tuple[str, str]]:
    return [(r["place"], r["how"]) for r in ans.rows]


def test_exact_and_attached(catalog: Path) -> None:
    got = _places(_find("Зеленка"))
    assert ("Зеленка", "парафія") in got
    assert any(p == "Липівці" or h.startswith("приписне") for p, h in
               _places(_find("Липівці")))


def test_ending_difference_is_near(catalog: Path) -> None:
    assert ("Зеленка", "парафія ~") in _places(_find("Зеленки"))


def test_translit_only_across_scripts(catalog: Path) -> None:
    hows = {h for p, h in _places(_find("Зеленка")) if p == "Zielonka"}
    assert hows and all("транслітерація" in h or "як «" in h for h in hows)
    # кирилиця з кирилицею нечітко не зводиться: «Зеленівка» не відповідь на «Зеленка»
    assert "Зеленівка" not in {p for p, _h in _places(_find("Зеленка"))}


def test_historic_name_exact_only(catalog: Path) -> None:
    ans = _find("Зеленка")
    assert "Zielonka" in ans.alt_names
    assert all("~" not in h for _p, h in _places(ans) if "як «" in h)


def test_silrada_by_stem_not_invented_village(catalog: Path) -> None:
    got = _places(_find("Ковалівка"))
    assert ("Ковалівська с/р", "сільрада ~") in got


def test_povit_narrows_but_keeps_unknown(catalog: Path) -> None:
    ans = _find("Липник, Перший")
    got = _places(ans)
    assert ("Липник", "парафія") in got
    assert any("повіт не вказано" in h for _p, h in got)
    ans2 = _find("Липник, Другий")
    assert ans2.other_povit == 1
    assert all("повіт не вказано" in h for _p, h in _places(ans2))


def test_zero_suggests_similar_and_has_coverage(catalog: Path) -> None:
    ans = _find("Зелинка")
    assert not ans.rows
    assert ans.coverage
    assert "Зеленка" in ans.similar


def test_book_siblings_show_their_own_books(catalog: Path) -> None:
    rows = [r for r in _find("Зеленка").rows if r["vol"] == "geo-b"]
    assert rows and any(s.startswith("Лугове (+9-8-56") for s in rows[0]["siblings"])


def test_missing_pack_is_not_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cat = tmp_path / "empty"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    from nyshporka.catalog import store as S
    from nyshporka.catalog.query import CatalogMissing, find_metrics

    S.invalidate()
    with pytest.raises(CatalogMissing):
        find_metrics("Зеленка")
    S.invalidate()
