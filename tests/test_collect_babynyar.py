"""🕯 Бабин Яр: збирач реєстру опису — знаходження фонду, рядки, знаменник."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_sources_babynyar import CASES_HTML, COUNT_API, FUNDS_API, _Cf

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.babynyar import (
    FIELDS,
    BabynYarCollector,
    norm_fond,
    year_span,
    years,
)
from nyshporka.fonds.collect.base import CollectError, Target
from nyshporka.sources.babynyar import BabynYarSource


def _collector(answers: dict[str, str], ws: Path | None = None) -> BabynYarCollector:
    return BabynYarCollector(ws, source=BabynYarSource(ws, client=_Cf(answers)))


ANSWERS = {"/api/archive/funds/": FUNDS_API,
           "/api/archive/descriptions/401/": COUNT_API,
           "/archive/desc/401": CASES_HTML}


# ── розбір полів ─────────────────────────────────────────────────────────────

def test_fond_number_is_compared_as_a_string_not_a_number() -> None:
    """🔴 «Р-6453» і «6453» — два різні фонди того самого архіву."""
    assert norm_fond("R-6453") == norm_fond("Р-6453")
    assert norm_fond("R-6453") != norm_fond("6453")


def test_years_take_the_first_and_the_last_four_digit_number() -> None:
    """⚠ У даті з днями чисел більше двох: «перші два» дали б 16.01 як рік."""
    assert years("1931 - 1932") == ("1931", "1932")
    assert years("16.01.1853 - 16.06.1854") == ("1853", "1854")
    assert years("") == ("", "")


def test_years_fall_back_to_the_title_when_the_date_column_is_empty() -> None:
    """🔴 Цілі фонди тримають роки в назві справи, а колонку лишають пустою.

    Заміряно на ДАМО ф.484: роки в колонці мали 93 справи з 1491 (6%), решта —
    у заголовку. Реєстр без років не фільтрується за роками.
    """
    t = ("Метрична книга: церква, с. Семенівка: про народжених (1853-1857), "
         "про одружених (1853-1857), про померлих (1853-1857)")
    assert years("", t) == ("1853", "1857")
    # ⚠ Найменший і найбільший, а не перший і останній: у назві роки йдуть
    # по типах запису й не в порядку зростання.
    assert years("", "про народжених (1861), про померлих (1858)") == ("1858", "1861")
    # 🔴 Номер справи й число аркушів у заголовку — не роки.
    assert years("", "Справа 1205. Книга реєстрації народжень за 1932 р.") == ("1932", "1932")
    assert years("", "12345 арк., 1901") == ("1901", "1901")
    assert years("", "Справа 1205, 480 арк.") == ("", "")
    # Колонка дат сильніша за заголовок: вона від самого майданчика.
    assert years("1931 - 1932", t) == ("1931", "1932")


# ── збирання ─────────────────────────────────────────────────────────────────

def test_collect_writes_cases_with_scan_counts(tmp_path: Path) -> None:
    res = _collector(ANSWERS, tmp_path).collect(
        Target(repo="DAHMO", fond="R-6453"), dest=tmp_path)
    fields, rows = T.read_tsv(tmp_path / "babynyar.tsv")
    assert fields == list(FIELDS)
    assert [r["spr_int"] for r in rows] == ["1", "2"]
    assert rows[0]["babynyar_scans"] == "529"
    assert rows[0]["babynyar_url"].endswith("/archive/case/26918")
    assert rows[0]["year_from"] == "1931"
    assert res.rows == 2


def test_collect_counts_what_it_refused_to_call_a_case(tmp_path: Path) -> None:
    """🔴 «вільний номер» у реєстрі став би фантомом у черзі замовлення."""
    res = _collector(ANSWERS, tmp_path).collect(
        Target(repo="DAHMO", fond="R-6453"), dest=tmp_path)
    kinds = {b.kind: b.count for b in res.blind}
    assert kinds["void"] == 1
    # Справа без жодної копії теж лишається в знаменнику окремим рядком.
    assert kinds["no_scans"] == 1


def test_collect_refuses_when_the_fund_is_not_on_the_site(tmp_path: Path) -> None:
    """🔴 Порожній реєстр читався б як «у фонді немає справ»."""
    with pytest.raises(CollectError) as exc:
        _collector(ANSWERS, tmp_path).collect(
            Target(repo="DAHMO", fond="315"), dest=tmp_path)
    assert "немає" in str(exc.value)


def test_collect_refuses_an_opys_the_fund_does_not_have(tmp_path: Path) -> None:
    with pytest.raises(CollectError) as exc:
        _collector(ANSWERS, tmp_path).collect(
            Target(repo="DAHMO", fond="R-6453", opys=("7",)), dest=tmp_path)
    assert "описів" in str(exc.value)


def test_plan_refuses_to_guess_the_archive_id() -> None:
    """🔴 Скорочення на майданчику неоднозначні: «ДАЧО» носять три архіви."""
    plan = _collector({}).plan(Target(repo="ANRM", fond="211"))
    assert not plan.ready
    assert "codes.babynyar" in plan.needs


def test_plan_is_ready_for_an_archive_the_pack_knows() -> None:
    assert _collector({}).plan(Target(repo="DAHMO", fond="R-6453")).ready


def test_collect_says_when_the_opys_gave_fewer_cases_than_promised(
        tmp_path: Path) -> None:
    """🔴 Приймач повноти: скільки справ в описі каже сам майданчик.

    Обрізаний перелік інакше виглядав би як повний фонд, і «такої справи у
    фонді немає» пішло б у реєстр як факт. Двійник обіцяє 3 справи; таблиця
    віддає 3 рядки, з яких один не є справою, — тож збігу немає, і збирач
    мусить сказати про це, а не сховати.
    """
    res = _collector(ANSWERS, tmp_path).collect(
        Target(repo="DAHMO", fond="R-6453"), dest=tmp_path)
    assert not any(b.kind == "capped" for b in res.blind), (
        "3 рядки таблиці проти обіцяних 3 — обрізання тут немає")

    short = dict(ANSWERS, **{"/api/archive/descriptions/401/":
                             '{"id": 401, "cases_count": 240}'})
    res2 = _collector(short, tmp_path).collect(
        Target(repo="DAHMO", fond="R-6453"), dest=tmp_path)
    capped = [b for b in res2.blind if b.kind == "capped"]
    assert capped and "240" in capped[0].why


def test_a_year_outside_the_fond_is_named_not_trusted() -> None:
    """🔴 Описка архіву («1993» серед 1892 і 1895) не розтягує діапазон справи.

    Заміряно на ДАМО ф.484 (фонд 1804-1925): шість справ мали роки 19xx серед
    сусідніх 18xx, і реєстр показував метричну книгу XIX ст. до 1996 року.
    Виправляти рік на інше століття не можна — це вигадало б дату.
    """
    t = ("про народжених (1889, 1892, 1993, 1895), "
         "про померлих (1889, 1892, 1993, 1895)")
    assert year_span("", t, bounds=(1804, 1925)) == ("1889", "1895", [1993])
    # Без меж фонду рік ні з чим не звіряється — і лишається як є.
    assert year_span("", t) == ("1889", "1993", [])
    # Усі роки поза межами — діапазону немає, а не вигаданий.
    assert year_span("", "про народжених (1996)", bounds=(1804, 1925)) == (
        "", "", [1996])


DAMO_FUNDS = ('{"total": 1, "page_next": null, "results": [{"id": 96, '
              '"number": "484", "name": "Колекція метричних книг", '
              '"start_date": "1804", "end_date": "1925", '
              '"descriptions": [{"id": 218, "number": "1"}], '
              '"archive": {"id": 36, "short_name": "ДАМО"}}]}')

DAMO_CASES = """<table><tbody>
<tr><td>472</td><td><a href="/archive/case/80472">Метрична книга: Церква св.
Дмитра, с. Краснопілля, Ананьївський повіт: про народжених (1889, 1892, 1993,
1895)</a></td><td></td><td>341</td></tr>
</tbody></table>"""


def test_collect_names_the_years_outside_the_fond(tmp_path: Path) -> None:
    """Збирач звіряє рік справи з межами фонду, які декларує сам архів."""
    answers = {"/api/archive/funds/": DAMO_FUNDS,
               "/api/archive/descriptions/218/": '{"id": 218, "cases_count": 1}',
               "/archive/desc/218": DAMO_CASES}
    res = _collector(answers, tmp_path).collect(
        Target(repo="DAMO", fond="484"), dest=tmp_path)
    _, rows = T.read_tsv(tmp_path / "babynyar.tsv")
    assert (rows[0]["year_from"], rows[0]["year_to"]) == ("1889", "1895")
    assert "1993" in rows[0]["title"], "заголовок лишається як у джерелі"
    odd = [b for b in res.blind if b.kind == "year_out_of_fond"]
    assert odd and odd[0].count == 1
    assert "1993" in odd[0].why and "1804-1925" in odd[0].why


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    _collector(ANSWERS, tmp_path).collect(
        Target(repo="DAHMO", fond="R-6453"), dest=tmp_path, dry_run=True)
    assert not (tmp_path / "babynyar.tsv").exists()
