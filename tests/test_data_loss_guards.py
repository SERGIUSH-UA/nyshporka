"""🔴 Запобіжники від втрати роботи людини.

Кожен тест тут стереже одну відмову, яка НЕ ПАДАЄ і тому невидима: побитий
файл, прочитаний як порожній, стирає рішення ока при наступному записі;
неатомарний запис лишає обрізаний файл, який далі читається як порожній;
повторний матчинг перезаписує вердикти `nysh review`.

Спільне в них те, що ціна помилки — не збій, а тиша: реєстр виглядає порожнім
рівно так само, як виглядав би чесно порожній.
"""
from __future__ import annotations

import json

import pytest

from nyshporka.utils.atomic import (
    CorruptFileError,
    atomic_write_bytes,
    read_json,
    write_json,
)


# ── спільна утиліта ──────────────────────────────────────────────────────────
def test_read_json_tells_missing_from_corrupt(tmp_path):
    """Немає файла — порожньо; є, але побитий — виняток, а не порожньо."""
    missing = tmp_path / "ніколи-не-було.json"
    assert read_json(missing, default={"cases": {}}) == {"cases": {}}

    broken = tmp_path / "побитий.json"
    broken.write_text('{"cases": {"a": 1},}', encoding="utf-8")  # зайва кома
    with pytest.raises(CorruptFileError):
        read_json(broken, default={"cases": {}})


def test_read_json_treats_empty_file_as_missing(tmp_path):
    """Порожній файл лишається по обірваному запису попередніх версій."""
    p = tmp_path / "порожній.json"
    p.write_text("", encoding="utf-8")
    assert read_json(p, default={}) == {}


def test_atomic_write_leaves_no_tmp_and_keeps_unicode(tmp_path):
    p = tmp_path / "дані.json"
    write_json(p, {"прізвище": "Далещинський"})
    assert json.loads(p.read_text(encoding="utf-8"))["прізвище"] == "Далещинський"
    assert list(tmp_path.iterdir()) == [p], "tmp-файл лишився на диску"


def test_atomic_write_bytes_replaces_whole_file(tmp_path):
    """Кадр або старий, або новий цілий — половини не буває."""
    p = tmp_path / "0001.jpg"
    atomic_write_bytes(p, b"\xff\xd8old")
    atomic_write_bytes(p, b"\xff\xd8new-and-longer")
    assert p.read_bytes() == b"\xff\xd8new-and-longer"
    assert list(tmp_path.iterdir()) == [p]


# ── реєстр вердиктів гортача ─────────────────────────────────────────────────
@pytest.fixture
def space(tmp_path):
    """Простір ОГОЛОШУЄТЬСЯ ДО імпорту: модулі беруть шляхи на рівні модуля."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def test_decode_hits_refuses_to_overwrite_corrupt_registry(space, tmp_path, monkeypatch):
    """🔴 Побитий реєстр НЕ стирається наступним вердиктом.

    Було: `load()` на `JSONDecodeError` віддавав порожній скелет, а `save()`
    писав його поверх — тобто вердикти, поставлені оком із мобільного, зникали
    від однієї зайвої коми.
    """
    from nyshporka import decode_hits as DH

    hits = tmp_path / "decode_hits.json"
    hits.write_text('{"version": 1, "cases": {"DAVO/337/4": {"hits": [}}',
                    encoding="utf-8")
    monkeypatch.setattr(DH, "HITS_PATH", hits)

    with pytest.raises(CorruptFileError):
        DH.load()
    with pytest.raises(CorruptFileError):
        DH.set_verdict("DAVO/337/4", "0030.JPG", "confirmed")
    assert "DAVO/337/4" in hits.read_text(encoding="utf-8"), "файл перезаписано"


def test_decode_hits_roundtrip_keeps_human_verdict(space, tmp_path, monkeypatch):
    from nyshporka import decode_hits as DH

    monkeypatch.setattr(DH, "HITS_PATH", tmp_path / "decode_hits.json")
    DH.add_case("DAVO/337/4", "data/raw/x", hits=[{"scan": "0030.JPG",
                                                   "kind": "clan"}])
    DH.set_verdict("DAVO/337/4", "0030.JPG", "refuted", note="Долинський")
    # повторний декод тієї самої справи не чіпає рішення ока
    DH.add_case("DAVO/337/4", "data/raw/x", hits=[{"scan": "0030.JPG",
                                                   "kind": "clan"}])
    hit = DH.load()["cases"]["DAVO/337/4"]["hits"][0]
    assert hit["verdict"] == "refuted"
    assert hit["verdict_note"] == "Долинський"


# ── ручні прив'язки прогонів ─────────────────────────────────────────────────
def test_overrides_corrupt_file_is_not_wiped_by_bind(space, tmp_path, monkeypatch):
    """🔴 `overrides.json` правлять редактором, тож зайва кома — очікуваний стан."""
    from nyshporka.cases import resolve as R

    path = tmp_path / "overrides.json"
    path.write_text('{"runs": {"spov1846-parish56": {"key": "DAVO/904/24"},},'
                    ' "bundles": {}}', encoding="utf-8")
    monkeypatch.setattr(R, "OVERRIDES_PATH", path)
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()

    with pytest.raises(CorruptFileError):
        R.bind_run("fuzovka", "ANRM/211/1")
    assert "spov1846-parish56" in path.read_text(encoding="utf-8")

    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()


# ── вердикти кандидатів матчингу ─────────────────────────────────────────────
def test_rematch_keeps_reviewed_status_and_notes(tmp_path):
    """🔴 Прохід `nysh review` не зникає від перескрейпленого джерела.

    `_make_candidate_id` детермінований, тож повторний матчинг пише в ТІ САМІ
    файли; без перенесення рішення двісті переглянутих кандидатів верталися в
    стан «new» без нотаток.
    """
    from datetime import UTC, datetime

    from nyshporka.matching.candidate import save_candidates
    from nyshporka.models.candidate import Candidate

    def make(score: float) -> Candidate:
        return Candidate(id="geneteka__deadbeef", source_id="geneteka",
                         raw_path="data/raw/g.html",
                         extracted={"surname": "Далещинський"}, score=score)

    save_candidates([make(0.70)], tmp_path)
    path = tmp_path / "data" / "candidates" / "geneteka__deadbeef.json"

    reviewed = Candidate.model_validate_json(path.read_text(encoding="utf-8"))
    reviewed.status = "rejected"
    reviewed.notes = "інший повіт, не наш"
    reviewed.reviewed_at = datetime(2026, 8, 1, tzinfo=UTC)
    path.write_text(reviewed.model_dump_json(indent=2), encoding="utf-8")

    save_candidates([make(0.91)], tmp_path)          # джерело перескрейпили
    after = Candidate.model_validate_json(path.read_text(encoding="utf-8"))
    assert after.status == "rejected", "рішення людини затерто"
    assert after.notes == "інший повіт, не наш"
    assert after.reviewed_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert after.score == pytest.approx(0.91), "свіжий бал не записався"
