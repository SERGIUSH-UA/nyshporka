"""⛪ Парафія як окрема сутність покажчика: канал, якого немає в описі.

Опис знає, що справа існує, і мовчить про те, чия вона церква. Через це
помилки тут коштують інакше, ніж у переліку справ: не «трохи не та назва», а
книга повіту, відкладена або прогнана рушієм на підставі неповного переліку
сіл — тобто день машинного часу або пропущене село.
"""
from __future__ import annotations

import json

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.duck import (
    AUTHORS_CEILING,
    CEILING,
    DuckSource,
    name_forms,
)


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник покажчика: віддає підготовлене й запам'ятовує, про що питали."""

    def __init__(self, *, authors: object = None, card: object = None,
                 search: object = None, raw: str = "") -> None:
        self.authors = authors
        self.card = card
        self.search = search
        self.raw = raw
        self.gets: list[str] = []
        self.posts: list[dict[str, object]] = []

    def get(self, url: str, **_: object) -> _Resp:
        self.gets.append(url)
        if self.raw:
            return _Resp(self.raw)
        body = self.authors if "/api/authors" in url else self.card
        return _Resp(json.dumps(body))

    def post(self, url: str, *, data: object = None, json: object = None,
             **_: object) -> _Resp:
        import json as J

        self.posts.append(json if isinstance(json, dict) else {})
        rows = self.search
        if callable(rows):
            rows = rows(json if isinstance(json, dict) else {})
        return _Resp(J.dumps(rows if rows is not None else []))


def _src(api: _Api) -> DuckSource:
    from nyshporka.sources.http import Fetcher

    return DuckSource(fetcher=Fetcher(base="https://п", delay=0.0, client=api))


# ── написання назви ─────────────────────────────────────────────────────────

def test_forms_cover_apostrophe_and_clerical_spelling() -> None:
    """Одне написання дає нуль, який виглядає як відповідь.

    Підрядок звіряється буквально: назва з апострофом не збігається з написанням
    без нього, а сучасна — з формою мови діловодства.
    """
    forms = name_forms("М'ястківка")
    assert "М'ястківка" in forms
    assert "Мястківка" in forms
    assert "Мястковка" in forms
    # Корінь без закінчення — інакше підрядок не переживе жодного відмінка.
    assert any(f.endswith("ковк") for f in forms)


def test_forms_are_unique_and_skip_scraps() -> None:
    assert name_forms("") == []
    assert len(set(name_forms("Городківка"))) == len(name_forms("Городківка"))


# ── парафії ─────────────────────────────────────────────────────────────────

def test_parishes_read_confession_and_book_count() -> None:
    api = _Api(authors=[{"id": "a1", "title": "Синагога, м. Н.",
                         "info": "консисторія", "lat": "48.1", "lng": "28.2",
                         "tags": ["іудаїзм"], "_count": {"file_authors": 5}}])
    got = _src(api).parishes("Н.")
    assert len(got) == 1
    assert got[0].cases == 5
    assert got[0].tags == ("іудаїзм",)
    assert got[0].lat == pytest.approx(48.1)


def test_parish_without_coords_is_empty_not_zero() -> None:
    """🔴 Нуль замість «немає» відправив би парафію в Гвінейську затоку."""
    api = _Api(authors=[{"id": "a1", "title": "Церква", "lat": None, "lng": ""}])
    got = _src(api).parishes("Церква")
    assert got[0].lat is None and got[0].lng is None


def test_parishes_ignore_rows_without_id() -> None:
    api = _Api(authors=[{"title": "без id"}, {"id": "a2", "title": "є"}])
    assert [p.title for p in _src(api).parishes("q")] == ["є"]


# ── картка справи: перелік сіл усередині книги ──────────────────────────────

def _card(authors: list[dict[str, object]], copies: list[dict[str, object]] | None = None
          ) -> dict[str, object]:
    return {"id": "f1", "full_code": "АРХ-1-2-3", "title": "Книга повіту",
            "years": [{"start_year": 1818, "end_year": 1818}],
            "tags": ["метрична книга"], "authors": authors,
            "online_copies": copies or []}


def test_case_card_lists_parishes_inside_the_book() -> None:
    """🔥 Заради цього переліку канал і кличуть: одне питання замість прогону."""
    api = _Api(card=_card([{"author": {"id": "a1", "title": "Церква, с. Перше"}},
                           {"author": {"id": "a2", "title": "Церква, с. Друге"}}]))
    card = _src(api).case_card("АРХ-1-2-3")
    assert [p.title for p in card["parishes"]] == ["Церква, с. Перше",
                                                   "Церква, с. Друге"]
    assert card["years"] == "1818"


def test_case_card_keeps_copy_availability() -> None:
    api = _Api(card=_card([], [{"url": "https://x/1", "availability": "PUBLIC",
                                "checked_availability_at": "2026-08-30T00:00:00Z"},
                               {"availability": "PUBLIC"}]))
    copies = _src(api).case_card("АРХ-1-2-3")["copies"]
    # Копія без адреси — не копія: показана, вона обіцяла б перехід у нікуди.
    assert len(copies) == 1
    assert copies[0]["checked"] == "2026-08-30"


def test_case_card_needs_full_code() -> None:
    with pytest.raises(SourceError):
        _src(_Api()).case_card("АРХ-1-2")


def test_missing_case_is_refusal_not_empty_card() -> None:
    api = _Api(card={"message": "not found"})
    with pytest.raises(SourceError):
        _src(api).case_card("АРХ-1-2-3")


# ── пошук ───────────────────────────────────────────────────────────────────

def test_annotation_travels_into_the_hit() -> None:
    """`place` шукає в анотації — і саме там сидять село й учасники."""
    api = _Api(search=[{"full_code": "АРХ-442-1-9", "title": "Дело о краже",
                        "info": "Н-ко, Ольгопольский у.", "is_online": False,
                        "tags": ["поліція"]}])
    hits = _src(api).find_files(place="Н-ко")
    assert hits[0].place.startswith("Н-ко")
    assert hits[0].fond == "442"
    # 🔴 Покажчик нічого не віддає: обіцяти завантаження там, де за ним немає
    # файлу, гірше за відсутність кнопки.
    assert hits[0].acquirable is False


def test_geo_wins_over_place_instead_of_400() -> None:
    """Сервіс віддає 400 на обидва поля разом — гео задане числами й точніше."""
    api = _Api(search=[])
    _src(api).find_files(place="Н-ко", lat="48.1", lng="28.2", radius_m=10000)
    assert "place" not in api.posts[0]
    assert api.posts[0]["radius_m"] == 10000


def test_latin_is_caught_before_the_request() -> None:
    """Латинка — жорстка відмова сервісу, а не порожня видача."""
    api = _Api(search=[])
    with pytest.raises(SourceError):
        _src(api).find_files(title="Miastkowka")
    assert api.posts == []


def test_fuzziness_below_floor_is_raised_not_sent() -> None:
    """Нижче межі сервіс відповідає 500, тобто запит не виконується зовсім."""
    api = _Api(search=[])
    _src(api).find_files(title="Мястковка", fuzziness=0.3)
    assert api.posts[0]["fuzziness"] >= 0.45


def test_empty_query_costs_no_request() -> None:
    api = _Api(search=[])
    assert _src(api).find_files() == []
    assert api.posts == []


# ── стеля ───────────────────────────────────────────────────────────────────

def test_ceiling_is_broken_by_year_windows() -> None:
    """🔴 Рівно стеля — «обрізано», а не «знайдено»: беремо більше вікнами."""
    def answer(body: dict[str, object]) -> list[dict[str, object]]:
        if "year_from" not in body:
            return [{"full_code": f"АРХ-1-1-{i}"} for i in range(CEILING)]
        year = str(body["year_from"])
        return [{"full_code": f"АРХ-1-1-{year}"}]

    api = _Api(search=answer)
    hits = _src(api).near("48.1", "28.2", radius_m=25000, split_years=True)
    assert len(hits) > CEILING
    assert len(api.posts) > 1


def test_no_extra_requests_when_result_fits() -> None:
    api = _Api(search=[{"full_code": "АРХ-1-1-1"}])
    _src(api).near("48.1", "28.2", radius_m=25000, split_years=True)
    assert len(api.posts) == 1


def test_authors_ceiling_is_declared() -> None:
    """Стеля переліку парафій оголошена — на неї спирається попередження."""
    assert AUTHORS_CEILING == 200


# ── не-JSON ─────────────────────────────────────────────────────────────────

def test_html_answer_is_refusal_not_silence() -> None:
    """🔴 Зниклий ендпоінт віддає сторінку з кодом 200.

    Порожній результат тут читався б як «такого в архівах немає» — тобто як
    знаменник негативу.
    """
    api = _Api(raw="<!DOCTYPE html><html>")
    with pytest.raises(SourceError):
        _src(api).parishes("Н.")
