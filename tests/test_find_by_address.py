"""🎯 Пошук за ШИФРОЮ: коли запит є адресою справи, а не словом із заголовка.

🔴 Текстовий пошук на шифру не відповідає ніколи — три числа поспіль не
трапляються в жодному заголовку. Тому «127-1078-1662» давало рівний нуль, а
разом із ним і «ДАВіО-172-4-112»: рядок, який САМ застосунок друкує в кожному
хіті як адресу справи. Показане не можна було набрати назад — клас «обіцянка
без входу», проти якого написаний `test_no_dead_ends`.

Друге, що тут стережеться, — чесність знаменника. Адресний маршрут питає інші
місця, ніж текстовий, і мусить це сказати: інакше «знайдено 0» читалося б як
«прочесали всі каталоги», хоч каталогів ніхто не питав.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from nyshporka.core import workspace as W


@pytest.fixture
def space(tmp_path: Path):
    """Простір із однією справою на диску.

    🔴 Простір оголошується ПЕРШИМ рядком, до імпорту бібліотеки: `library`
    бере корінь на рівні модуля, і зворотного порядку досить, щоб тест мовчки
    працював на просторі розробника.
    """
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    (d / "0106.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433", "title": "Ревізькі казки"},
        ensure_ascii=False), encoding="utf-8")

    from nyshporka.library import build_library, write_library
    write_library(build_library())
    return tmp_path


def _call(q: str, **kw) -> dict:
    from nyshporka import ops as O

    env = O.call("catalog.search", {"q": q, **kw})
    return env.as_dict()


def test_a_case_on_disk_is_found_by_its_bare_shifra(space):
    """Справа лежить на цій машині — і не знаходилась за власною шифрою."""
    got = _call("315-1-8433")
    assert got["ok"], got
    addr = got["data"]["address"]
    assert addr["fond"] == "315" and addr["spr"] == "8433"
    assert addr["local"], "справу на диску не знайдено за її ж шифрою"
    assert addr["local"][0]["path"].endswith("spr-8433")


def test_the_form_the_app_prints_is_accepted_here_too(space):
    """Адреса з назвою архіву через дефіс — те, що друкує сам пошук."""
    got = _call("ДАХмО-315-1-8433")
    assert got["ok"] and got["data"]["address"]["local"]


def test_an_address_query_does_not_pretend_it_combed_the_catalogs(space):
    """🔴 Головний приймач: маршрут інший — і знаменник це каже.

    Мовчазний перехід на інший маршрут перетворив би «знайдено 0» на «прочесали
    все», тобто на висновок, якого ніхто не робив.
    """
    got = _call("315-1-8433")
    said = {w["code"] for w in got["warnings"]}
    assert "address_route" in said, got["warnings"]
    searched = got["data"]["coverage"]["searched"]
    assert "library" in searched
    assert "duck" not in searched, "покажчик не питали, а знаменник каже, що питали"


def test_a_source_that_cannot_search_by_address_says_why(space):
    """Джерело, яке вміє лише текстом, іде в `unavailable` з причиною.

    Його нуль — не нуль про цю справу: його про неї не питали.
    """
    got = _call("315-1-8433")
    why = {u["source"]: u["why"] for u in got["data"]["coverage"]["unavailable"]}
    assert any("заголовка" in v for v in why.values()), why


def test_a_query_that_only_looks_like_a_shifra_falls_back_to_text(space):
    """🔴 Дата «1858-03-14» має форму адреси, і це не привід не шукати.

    Відповідь «такої справи немає» на запит, який просили шукати текстом, — це
    відмова від роботи під виглядом результату.
    """
    got = _call("1858-03-14")
    assert got["ok"]
    assert "address" not in got["data"], "адресний маршрут привласнив дату"
    said = {w["code"] for w in got["warnings"]}
    assert "address_not_found" in said, got["warnings"]


def test_text_flag_forces_the_full_text_route(space):
    """`--text` вимикає гілку — на випадок, коли шукають саме рядок."""
    got = _call("315-1-8433", by_address=False)
    assert "address" not in got["data"]


def test_archium_finds_a_case_by_its_numbers(tmp_path: Path):
    """🔴 Каталог носив фонд, опис і справу окремими полями з першого дня.

    Пошук звіряв лише опис і номер справи як ТЕКСТ, тому три числа поспіль не
    знаходили нічого. Дані для цього були — бракувало запиту.
    """
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka.sources.archium import ArchiumSource

    rel = ArchiumSource.CATALOG_REL
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ("group_id\tfond_id\tfond_no\tfond_title\tinv_id\tinv_label\t"
            "file_id\tcase_no\tdate\tsheets\tdescription")
    rows = [
        "1\t900\t230\tДворянські справи\t10\tОпис 1\t555\tСправа 0043\t"
        "1802\t12\tВивід про дворянство",
        "1\t900\t230\tДворянські справи\t10\tОпис 1\t556\tСправа 44\t"
        "1803\t8\tІнша справа",
    ]
    path.write_text("\n".join([head, *rows]), encoding="utf-8")

    src = ArchiumSource(workspace=tmp_path)
    assert "address" in src.caps
    # ⚠ Каталог пише «Опис 1» і «Справа 0043» — людина набирає «1» і «43».
    got = src.find_case("230", "1", "43")
    assert len(got) == 1 and got[0].ref == "file:555"
    assert src.find_case("230", "1", "9999") == []
