"""👁 Командний контракт сховища сторінок — той, який виконують агенти.

🔴 Модуль мав НУЛЬ покриття, а на ньому тримається правило, яке коштує
найдорожче: питати сховище ПЕРЕД тим, як відкривати скани, і заносити кожен
переглянутий аркуш ПІСЛЯ. Тиха помилка тут не падає — вона або змушує
передивитись переглянуте, або записує `status=full` без повного переліку
прізвищ, а це підстава для хибного нуля по ВСІЙ справі.

Перевіряється саме те, що ламалось на живому матеріалі: ключ сторінки, який не
збігається з іменем файла на диску (2026-08-16 так розійшлись 62 ключі у 23
справах), і втрата валідних анотацій через одну одруківку в сусідній.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


@pytest.fixture
def case(tmp_path: Path) -> Path:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    for n in (106, 107, 108):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    return tmp_path


def _run(*args, stdin: str | None = None):
    return runner.invoke(app, list(args), input=stdin)


def _data(res) -> dict:
    """Корисне з відповіді.

    ⚠ Частина команд віддає конверт (`ok`/`data`/`next`), частина — голий
    словник. Тест не повинен закріплювати цю різницю: він про зміст.
    """
    got = json.loads(res.stdout)
    return got.get("data", got) if isinstance(got, dict) else got


def test_status_answers_before_anything_is_opened(case):
    """Питання «що вже дивились» мусить мати відповідь до першого рендера."""
    r = _run("pages", "status", "DAHMO/315/8433", "--json")
    assert r.exit_code == 0, r.output
    got = _data(r)
    assert got["key"] == "DAHMO/315/8433"
    assert got["total_disk"] == 3 and got["noted"] == 0


def test_a_batch_keeps_the_valid_notes_when_one_is_broken(case):
    """🔴 Не втрачати сорок сторінок через одну одруківку.

    Невалідний елемент пропускається зі звітом, валідні лягають.
    """
    batch = json.dumps([
        {"scan": "0106.jpg", "page_type": "birth", "status": "partial",
         "surnames": ["Ковальський"]},
        {"scan": "0107.jpg", "page_type": "не-тип", "status": "partial"},
        {"scan": "0108.jpg", "page_type": "birth", "status": "skipped"},
    ], ensure_ascii=False)
    r = _run("pages", "note-batch", "DAHMO/315/8433", "--json", stdin=batch)
    assert r.exit_code == 0, r.output
    got = _data(r)
    assert got["ok"] == 2 and got["failed"] == 1
    assert got["errors"][0]["scan"] == "0107.jpg", got["errors"]

    after = _data(_run("pages", "status", "DAHMO/315/8433", "--json"))
    assert after["noted"] == 2, "валідні анотації не лягли"


def test_a_key_that_does_not_match_the_scan_on_disk_is_reported(case):
    """🔴 Ключ без розширення проходить валідацію моделі й НЕ матчиться зі
    сканом — сторінка, яку вже дивились оком, лишається в черзі на рендер.

    Саме так 16.08.2026 розійшлись 62 ключі у 23 справах. Модель тут ні до чого:
    впіймати це може лише звірка з диском.
    """
    batch = json.dumps([{"scan": "0106", "page_type": "birth", "status": "partial"}])
    got = _data(_run("pages", "note-batch", "DAHMO/315/8433", "--json", stdin=batch))
    assert got["ok"] == 1, "анотацію все одно приймаємо"
    assert got["off_disk"] == ["0106"], (
        f"розбіжність із диском не названо: {got}")


def test_an_unknown_case_refuses_with_the_accepted_formats(case):
    r = _run("pages", "status", "щось-не-те", "--json")
    assert r.exit_code == 1
    assert "не розпізнав справу" in r.output or "Приймаю" in r.output, r.output


def test_an_empty_batch_is_a_state_not_a_crash(case):
    r = _run("pages", "note-batch", "DAHMO/315/8433", "--json", stdin="")
    assert r.exit_code == 0, r.output
    assert _data(r)["ok"] == 0


def test_json_lines_are_accepted_as_well_as_an_array(case):
    """Агенти пишуть і так, і так; вимагати одного формату — зайвий глухий кут."""
    lines = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"scan": "0106.jpg", "page_type": "birth", "status": "partial"},
        {"scan": "0107.jpg", "page_type": "birth", "status": "partial"},
    ])
    got = _data(_run("pages", "note-batch", "DAHMO/315/8433", "--json", stdin=lines))
    assert got["ok"] == 2, got


def test_the_slash_form_of_a_shifra_reaches_the_same_case(case):
    """🔴 «CDIAK/127/781/534» — форма, яку набирають першою, і вона відмовлялась.

    Тепер вона доходить до тієї самої справи, що й дефісна: розбір адреси в
    пакеті один, а не чотири розбіжні копії.
    """
    got = _data(_run("pages", "status", "DAHMO/315/1/8433", "--json"))
    assert got["key"] == "DAHMO/315/8433"


def test_the_refusal_names_the_rule_not_just_examples(case):
    """Правило словами, а не два приклади, з яких його треба вивести.

    Скарга була дослівна: «повідомлення показує приклад із дефісом, але правила
    не називає, тож із нього треба здогадатись, порівнявши два приклади».
    """
    r = _run("pages", "status", "казна-що", "--json")
    assert r.exit_code == 1
    said = json.loads(r.stdout)["error"]
    assert "порядку" in said and "скісною" in said, said


def test_a_shifra_without_an_archive_is_still_refused_but_names_the_candidate(case):
    """🔴 Сховище ПИШЕ, тож безархівна шифра лишається відмовою.

    Мовчки взятий перший-ліпший архів — це аркуші, дописані в чужу справу. А от
    назвати кандидата, коли він на диску рівно один, відмова може й мусить.
    """
    r = _run("pages", "status", "315-1-8433", "--json")
    assert r.exit_code == 1
    said = json.loads(r.stdout)["error"]
    assert "без архіву" in said
    assert "ДАХмО 315-1-8433" in said, said
