"""Справа іншого опису — окрема справа з власним ключем, а старі ключі не зрушують.

27.09.2026 «ДАДнО 193-1-213» (Катеринослав 1865–1867) і «ДАДнО 193-3-213»
(Нікополь 1899) мали один ключ `DADNO/193/213`. Другу справу завести було
неможливо, і дослідниця назвала її «213b» — під цим номером вона й поїхала в
Супрягу. Опис — фізично інший підрозділ фонду, тож це дві справи.

🔴 Разом з тим ключ без опису вже лежить рядком у сховищі сторінок, прив'язках
прогонів і метах. Тому власний ключ дістає лише справа, що народилась у
колізії, а перша лишається під своїм — і все, що на неї записано, не підвисає.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

R: Any = None
L: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Порожній простір. Заморожені на імпорті шляхи підмінено поіменно —
    та сама причина, що в `test_register_and_notes.space`."""
    from nyshporka.core import opys_keys as K
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    K.reset()

    global R, L
    from nyshporka import library as lib
    from nyshporka.cases import db as DB
    from nyshporka.cases import register
    from nyshporka.pagestore import store as S

    R, L = register, lib
    for mod, attr, value in (
        (lib, "ROOT", tmp_path), (lib, "RAW_DIR", tmp_path / "data" / "raw"),
        (lib, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (lib, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)
    for fn in ("load_library", "_sidecar_case"):
        got = getattr(lib, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()
    yield tmp_path
    K.reset()


def _folder(root: Path, rel: str) -> Path:
    d = root / "data" / "raw" / rel
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"x")
    return d


def _rebuild() -> list[Any]:
    L._sidecar_case.cache_clear()
    entries = L.build_library()
    L.write_library(entries)
    if hasattr(L.load_library, "cache_clear"):
        L.load_library.cache_clear()
    return entries


def _katerynoslav(root: Path) -> Path:
    d = _folder(root, "катеринослав_1865")
    R.describe(d, shifra="ДАДнО 193-1-213", title="Покровська ц. м. Катеринослава")
    _rebuild()
    return d


def test_without_a_workspace_ledger_keys_are_as_before(space: Path) -> None:
    """Сервер Супряги імпортує ті самі ключі: без реєстру — нуль змін."""
    assert L._mk_key("DADNO", "193", "213", "3") == "DADNO/193/213"
    assert L._mk_key("DADNO", "193", "213") == "DADNO/193/213"
    assert L._mk_key("ANRM", "211", "140", "3") == "ANRM/211-3/140"


def test_a_case_of_another_opys_gets_its_own_key(space: Path) -> None:
    kat = _katerynoslav(space)
    nik = _folder(space, "нікополь_1899")
    R.describe(nik, shifra="ДАДнО 193-3-213", title="Покровська ц. м. Нікополя")

    assert L._mk_key("DADNO", "193", "213", "3") == "DADNO/193-3/213"
    assert L._mk_key("DADNO", "193", "213", "1") == "DADNO/193/213", \
        "перша справа мусить лишитись під своїм ключем"

    by_path = {e.path: e.key for e in _rebuild()}
    rel = lambda d: d.relative_to(space).as_posix()  # noqa: E731
    assert by_path[rel(kat)] == "DADNO/193/213"
    assert by_path[rel(nik)] == "DADNO/193-3/213"


def test_the_ledger_records_why(space: Path) -> None:
    from nyshporka.core import opys_keys as K

    _katerynoslav(space)
    R.describe(_folder(space, "нікополь_1899"), shifra="ДАДнО 193-3-213")
    rows = json.loads(K.path().read_text(encoding="utf-8"))["cases"]
    assert [(r["repo"], r["fond"], r["opys"], r["spr"]) for r in rows] == [
        ("DADNO", "193", "3", "213")]
    assert "193-1-213" in rows[0]["why"]


def test_another_folder_of_the_first_case_does_not_move_its_key(space: Path) -> None:
    """Третя тека тієї самої книги (друга зйомка) — не колізія."""
    from nyshporka.core import opys_keys as K

    _katerynoslav(space)
    R.describe(_folder(space, "катеринослав_перезйомка"), shifra="ДАДнО 193-1-213")
    assert K.rows() == []
    assert L._mk_key("DADNO", "193", "213", "1") == "DADNO/193/213"


def test_re_describing_the_first_case_does_not_move_its_key(space: Path) -> None:
    from nyshporka.core import opys_keys as K

    kat = _katerynoslav(space)
    R.describe(kat, title="уточнена назва")
    assert K.rows() == []


def test_unknown_opys_of_the_first_case_is_not_a_collision(space: Path) -> None:
    """Не знаємо опису першої — не знаємо, що це інша книга. Як сьогодні."""
    from nyshporka.core import opys_keys as K

    d = _folder(space, "dadno_193/spr-213")
    _rebuild()                              # справа без паспорта, опис невідомий
    R.describe(_folder(space, "нікополь_1899"), shifra="ДАДнО 193-3-213")
    assert K.rows() == [], [e.key for e in L.build_library()] + [str(d)]


def test_page_store_keeps_the_two_cases_apart(space: Path) -> None:
    from nyshporka.pagestore import store as S

    _katerynoslav(space)
    R.describe(_folder(space, "нікополь_1899"), shifra="ДАДнО 193-3-213")
    _rebuild()

    old = S.resolve_case("ДАДнО 193-1-213")
    new = S.resolve_case("ДАДнО 193-3-213")
    assert old.key == "DADNO/193/213" and new.key == "DADNO/193-3/213"
    assert S.case_path(old).name == "193-213.json"
    assert S.case_path(new).name == "193-3-213.json"
    # Адреса без опису, записана раніше, і далі веде на першу справу.
    assert S.resolve_case("DADNO/193/213").key == "DADNO/193/213"


def test_register_op_names_the_new_key(space: Path) -> None:
    from nyshporka import ops as O

    _katerynoslav(space)
    nik = _folder(space, "нікополь_1899")
    env = O.call("case.register", {"case_dir": str(nik), "shifra": "ДАДнО 193-3-213",
                                   "reindex": False})
    assert env.ok, env.error
    note = next((w.text for w in env.warnings if w.code == "own_key"), "")
    assert "DADNO/193-3/213" in note and "DADNO/193/213" in note
    assert not any(w.code == "key_mismatch" for w in env.warnings), env.warnings


def _passport(d: Path, shifra: str, opys: str) -> None:
    """Паспорт, який пише завантажувач, а не реєстрація: реєстру ключів він не чіпає."""
    (d / "_source.json").write_text(json.dumps(
        {"shifra": shifra, "opis": opys}, ensure_ascii=False), encoding="utf-8")


def test_a_folder_of_another_opys_is_not_swallowed_as_a_second_shot(space: Path) -> None:
    """Тека `dadno_193/spr-213` (ім'я без опису) з паспортом оп. 3 поруч зі
    справою оп. 1 — окремий запис бібліотеки, а не `extra_paths` чужої книги."""
    kat = _katerynoslav(space)
    nik = _folder(space, "dadno_193/spr-213")
    _passport(nik, "ДАДнО 193-3-213", "3")
    entries = _rebuild()
    rel = nik.relative_to(space).as_posix()
    first = next(e for e in entries if e.path == kat.relative_to(space).as_posix())
    assert rel not in first.extra_paths
    assert any(e.path == rel and e.opys == "3" for e in entries)


def test_doctor_names_two_opysy_under_one_key_and_registration_heals_it(
        space: Path) -> None:
    from nyshporka.setup import doctor as D

    _katerynoslav(space)
    nik = _folder(space, "dadno_193/spr-213")
    _passport(nik, "ДАДнО 193-3-213", "3")
    _rebuild()
    got = D._shared_keys()
    assert got.level == "warn" and "DADNO/193/213" in got.detail, got

    R.describe(nik, shifra="ДАДнО 193-3-213")
    _rebuild()
    assert D._shared_keys().level == "ok"
    assert L._mk_key("DADNO", "193", "213", "1") == "DADNO/193/213"
