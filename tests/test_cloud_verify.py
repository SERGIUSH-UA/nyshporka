"""✅ Звірка привезеного: єдине місце, де «прочитано» стає доказом.

Кожен тест тут відповідає випадку, коли захід рапортував успіх, а сторінок не
було:

* карантин переживає перезапуск, тож другий захід їх не повторює — і чесно
  каже «повністю» при тринадцятьох відкладених сторінках;
* знаменники розходяться, коли читали не те, що збирались, — і саме це
  розходження й є діагнозом;
* порожня тека без знаменника проходить як бездоганно виконана робота;
* голоси, складені в одну теку, дають нуль знахідок при пошуку без помилки.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.cloud import verify as V


def _case(root: Path, n: int) -> Path:
    case = root / "case"
    case.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (case / f"{i:04d}.jpg").write_bytes(b"\0" * 32)
    return case


def _out(root: Path, names: list[str], *, meta: dict | None = None) -> Path:
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    for n in names:
        (out / f"{n}.txt").write_text("текст", encoding="utf-8")
    if meta is not None:
        (out / V.META_NAME).write_text(json.dumps(meta, ensure_ascii=False),
                                       encoding="utf-8")
    return out


def test_full_case_is_complete(tmp_path: Path) -> None:
    case = _case(tmp_path, 3)
    out = _out(tmp_path, ["0000", "0001", "0002"],
               meta={"frames_total": 3, "case_key": "ARCH/1/2"})
    got = V.verify(out, case_dir=case)
    assert got.complete is True
    assert (got.got, got.expected) == (3, 3)


def test_quarantined_pages_are_not_done(tmp_path: Path) -> None:
    """🔴 Головний тест модуля.

    Карантин переживає перезапуск: другий захід не бере відкладені сторінки й
    рапортує «повністю». Виміряний випадок: вердикт `ok`, «дев'ять справ
    повністю», а на диску 518 із 531 — тринадцять сторінок відклав ще нічний
    прогін. Карантин — не властивість кадру, а наслідок зіткнення щільної
    сторінки з розбиттям на процеси: ті самі кадри в один потік проходять.
    """
    case = _case(tmp_path, 3)
    out = _out(tmp_path, ["0000", "0001", "0002"], meta={"frames_total": 3})
    (out / V.QUARANTINE_NAME).write_text(
        json.dumps({"0002.jpg": {"why": "не влізло в пам'ять"}}),
        encoding="utf-8")

    got = V.verify(out, case_dir=case)
    assert got.complete is False, "текст є, але сторінка не прочитана"
    assert got.quarantined == ["0002.jpg"]
    assert "карантині" in got.detail


def test_missing_page_is_found_by_name_not_by_count(tmp_path: Path) -> None:
    """🔴 Звірка покадрова, а не «однаково штук».

    Три кадри й три тексти — це ще не прочитана справа: тексти можуть бути не
    тих сторінок. Локальному прогону такого не трапляється (тека та сама, прогін
    один), а хмарному — постійно: кадри розпаковувала чужа машина, прогонів було
    кілька, результат приїхав частинами.
    """
    case = _case(tmp_path, 3)
    out = _out(tmp_path, ["0000", "0001", "9999"], meta={"frames_total": 3})
    got = V.verify(out, case_dir=case)
    assert got.complete is False
    assert got.missing == ["0002.jpg"]
    assert got.got == 2, "чужий текст не зараховується"


def test_disagreeing_denominators_are_an_event(tmp_path: Path) -> None:
    """🔴 Розходження знаменників — діагноз, а не дрібниця.

    Воно означає, що читали не те, що збирались, — або тека справи змінилась
    після прогону. Мовчки взяти менше число означало б оголосити справу
    прочитаною.
    """
    case = _case(tmp_path, 10)
    out = _out(tmp_path, [f"{i:04d}" for i in range(4)], meta={"frames_total": 4})
    got = V.verify(out, case_dir=case)
    assert got.disagree is True
    assert got.expected == 10, "беремо більший знаменник"
    assert got.complete is False
    assert "розходяться" in got.detail


def test_zero_denominator_is_not_completeness(tmp_path: Path) -> None:
    """🔴 «Нема з чим звіряти» ≠ «повно».

    Порожня тека, з якої нічого не очікували, інакше проходить як бездоганно
    виконана робота — і напрям закривається назавжди.
    """
    out = tmp_path / "out"
    out.mkdir()
    got = V.verify(out)
    assert got.complete is False
    assert got.expected == 0
    assert "нема з чим звіряти" in got.detail


def test_voice_branches_must_be_sibling_folders(tmp_path: Path) -> None:
    """🔴 Голоси лягають поруч, а не всередину.

    Складені в одну теку, вони перетирають один одного за іменем файла — і
    пошук потім чесно віддає нуль знахідок без жодної помилки.
    """
    case = _case(tmp_path, 2)
    out = _out(tmp_path, ["0000", "0001"], meta={"frames_total": 2})
    side = tmp_path / "out-diak_v4"
    side.mkdir()
    (side / "0000.txt").write_text("другий голос", encoding="utf-8")

    got = V.verify(out, case_dir=case)
    assert got.complete is False, "другий голос недочитав сторінку"
    assert got.missing == ["0001.jpg"]
    assert "out-diak_v4" in got.detail


def test_service_files_are_not_counted_as_pages(tmp_path: Path) -> None:
    """Службовий файл — не сторінка. Інакше знаменник тихо роздувається."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "_notes.txt").write_text("x", encoding="utf-8")
    assert V.texts_in(out) == 0


def test_small_tail_is_cheaper_at_home(tmp_path: Path) -> None:
    """🔴 Холодний старт чужої машини коштує ~8 хв незалежно від обсягу.

    На дрібному хвості весь захід і є ці вісім хвилин, тож доганяти його
    другою орендою — це платити за підготовку більше, ніж за роботу.
    """
    big = V.Completeness(complete=False, expected=1000, got=990,
                         missing=[f"{i}.jpg" for i in range(10)])
    assert V.tail_is_small(big) is True

    huge = V.Completeness(complete=False, expected=1000, got=500,
                          missing=[f"{i}.jpg" for i in range(500)])
    assert V.tail_is_small(huge) is False

    done = V.Completeness(complete=True, expected=10, got=10)
    assert V.tail_is_small(done) is False, "нема чого доганяти"


def test_it_mirrors_the_runner_acceptor() -> None:
    """🔴 Приймач повноти мусить бути один, хоч і записаний двічі.

    Раннер їде під інтерпретатором середовища рушіїв, де пакета немає, тож
    звірка тут — дзеркало його `missing_pages`. Рівність доводить тест, а не
    домовленість, — так само, як для каналу прогресу.
    """
    runner = pytest.importorskip(
        "nyshporka.htr.runner",
        reason="раннер тягне numpy/PIL — вони є лише з extra `htr`")
    import inspect

    ours = inspect.getsource(V.missing_pages)
    theirs = inspect.getsource(runner.missing_pages)

    def body(src: str) -> list[str]:
        lines = src.splitlines()
        start = next(i for i, x in enumerate(lines) if x.strip().startswith("gone"))
        return [x.strip() for x in lines[start:] if x.strip()]

    assert body(ours) == body(theirs), (
        "звірка розійшлася з приймачем раннера — виправляти треба обидва")
