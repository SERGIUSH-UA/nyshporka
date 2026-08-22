"""🧾 Каркас збирачів реєстру опису: спільні правила для всіх джерел."""
from __future__ import annotations

from pathlib import Path

from nyshporka.fonds import collect
from nyshporka.fonds.collect import tsv as T

FIELDS = ("opys", "spr_int", "spr_letter", "title")


def _row(opys: str, num: int, letter: str = "", title: str = "х") -> dict[str, str]:
    return {"opys": opys, "spr_int": str(num), "spr_letter": letter, "title": title}


def test_a_letter_is_glued_to_the_number_not_split_off() -> None:
    """🔴 Номер справи з літерою пишеться ЗЛИТО. Без негативного lookahead
    «2640 Дзічковських» читається як справа «2640д» — фантом, якого в описі
    немає, тоді як справжня справа лишається «без скана»."""
    assert T.split_code("24а") == (24, "а")
    assert T.split_code("8534т") == (8534, "т")
    assert T.split_code("2640 Дзічковських") == (2640, "")
    assert T.split_code("вільний номер") is None


def test_years_and_folios_are_fields_not_part_of_the_title() -> None:
    """Лишити хвіст у назві означає, що фільтр за роками не побачить нічого, а
    заголовок у списку щоразу обриватиметься на півслові."""
    assert T.parse_title_tail("Метрична книга, 1786-1794, 51 арк.") == (
        "Метрична книга", "1786", "1794", "51")
    assert T.parse_title_tail("Списки, 1802 р.") == ("Списки", "1802", "1802", "")
    assert T.parse_title_tail("Без хвоста") == ("Без хвоста", "", "", "")


def test_collecting_one_opys_does_not_erase_the_others(tmp_path: Path) -> None:
    """🔴 Головне правило вливання, і воно вже коштувало фонду.

    Заміряно на живому фонді: запуск із одним описом лишив у реєстрі один опис
    замість сімдесяти п'яти — і виглядало це успіхом, бо файл на місці й рядки
    в ньому є. Знищене помічають не тоді, коли воно зникло, а коли за реєстром
    вирішують, що замовляти в архіві.
    """
    path = tmp_path / "duck.tsv"
    T.write_tsv(path, FIELDS, [_row("1", 5), _row("2", 7), _row("3", 9)])

    kept = T.merge_into(path, FIELDS, [_row("1", 5, title="новий"),
                                       _row("1", 6)], touched=("1",))

    _, rows = T.read_tsv(path)
    assert kept == 2, "чужі описи не збереглись"
    assert {r["opys"] for r in rows} == {"1", "2", "3"}
    assert len(rows) == 4
    got = next(r for r in rows if r["opys"] == "1" and r["spr_int"] == "5")
    assert got["title"] == "новий", "рядок опису, який чіпали, не оновився"


def test_a_non_numeric_opys_does_not_break_sorting(tmp_path: Path) -> None:
    """⚠ Опис буває нечисловим («Л2», «ОРП41») — на `int()` це клало всю
    перезбірку реєстру, тобто одна дивна позиція гасила решту фонду."""
    path = tmp_path / "duck.tsv"
    rows = [_row("Л2", 3), _row("1", 2), {"opys": "ОРП41", "spr_int": "",
                                          "spr_letter": "", "title": "х"}]
    T.write_tsv(path, FIELDS, sorted(rows, key=T.sort_key))
    _, back = T.read_tsv(path)
    assert len(back) == 3


def test_a_half_written_registry_never_lands_under_its_real_name(tmp_path: Path) -> None:
    """Обірваний запис під правильним іменем наступний запуск прочитає як
    повний реєстр — і мовчки недорахує половину фонду."""
    path = tmp_path / "archium.tsv"
    T.write_tsv(path, FIELDS, [_row("1", 1)])
    assert not path.with_name(path.name + ".part").exists()


def test_no_collector_is_a_state_not_a_failure() -> None:
    """Порожній перелік мусить пояснювати себе: пакет і без збирачів уміє
    читати вже зібраний реєстр, тож це не поломка."""
    from nyshporka import ops as O

    env = O.call("registry.collectors", {})
    assert env.ok
    codes = {w.code for w in env.warnings}
    if not (env.data or {}).get("collectors"):
        assert "no_collectors" in codes


def test_a_plugin_cannot_shadow_a_builtin_collector(monkeypatch) -> None:
    """🔴 Тут це гостріше, ніж для джерел: збирач пише в реєстр опису, а за ним
    людина вирішує, що замовляти в архіві. Підмінений збирач — не «інша
    відповідь», а чужий перелік документів, який виглядає як наш."""
    class _Fake:
        id = "archium"
        label = "чужий"
        filename = "archium.tsv"
        source_id = ""
        caps = frozenset({"opys"})

    class _EP:
        name = "fake"

        @staticmethod
        def load() -> object:
            return _Fake()

    monkeypatch.setattr(collect.registry, "_builtin", lambda ws=None: [_Fake()])
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kw: [_EP()])

    reg = collect.load()
    assert len(reg.all()) == 1
    assert any("вбудован" in why for _, why in reg.broken)
