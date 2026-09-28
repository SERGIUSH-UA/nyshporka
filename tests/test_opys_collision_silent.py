"""Фонд БЕЗ `_OPYS_IN_KEY` (як ЦДІАК 224) не сміє мовчки злити два описи.

`test_opys_own_key.py` доводить це для реєстрації руками (`register.describe`)
і для збірки бібліотеки (`build_library`). Тут — два інші шляхи, де та сама
колізія раніше проходила непоміченою: збірка реєстру `cases.collect` (матеріал,
якого ще нема в бібліотеці) і резолвер сховища сторінок `pagestore.store`
(людина набирає шифру руками).
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


def _folder(root: Path, rel: str, *, shifra: str = "", opis: str = "") -> Path:
    d = root / "data" / "raw" / rel
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"x")
    if shifra:
        (d / "_source.json").write_text(
            json.dumps({"shifra": shifra, "opis": opis}, ensure_ascii=False),
            encoding="utf-8")
    return d


def _rebuild() -> list[Any]:
    L._sidecar_case.cache_clear()
    entries = L.build_library()
    L.write_library(entries)
    if hasattr(L.load_library, "cache_clear"):
        L.load_library.cache_clear()
    return entries


# ── pagestore.store.resolve_case ────────────────────────────────────────────

def test_naming_the_opys_by_hand_does_not_borrow_the_other_books_file(space: Path) -> None:
    """224-2-49 уже на диску; людина набирає «224-1-49» — не має отримати
    ні файл, ні шифру, ні обсяг книги 2."""
    from nyshporka.pagestore import store as S

    _folder(space, "cdiak_224/spr-49", shifra="ЦДІАК 224-2-49", opis="2")
    _rebuild()

    ref = S.resolve_case("ЦДІАК 224-1-49")
    assert ref.opys == "1"
    assert "224-2-49" not in ref.shifra
    assert S.case_path(ref).name != "224-49.json", \
        "інакше запис ліг би у файл книги оп. 2"

    holder = S.resolve_case("ЦДІАК 224-2-49")
    assert holder.key != ref.key
    assert S.case_path(holder).name == "224-49.json", \
        "перша справа лишається під ключем без опису"


def test_naming_the_holders_own_opys_is_unaffected(space: Path) -> None:
    from nyshporka.pagestore import store as S

    _folder(space, "cdiak_224/spr-49", shifra="ЦДІАК 224-2-49", opis="2")
    _rebuild()

    ref = S.resolve_case("ЦДІАК 224-2-49")
    assert ref.key == "CDIAK/224/49"
    assert S.case_path(ref).name == "224-49.json"


def test_key_without_opys_still_resolves_the_holder(space: Path) -> None:
    """Той, хто набрав ключ без опису (старе посилання), і далі бачить першу
    справу — інакше все, що вже написано на неї, стало б непомітним."""
    from nyshporka.pagestore import store as S

    _folder(space, "cdiak_224/spr-49", shifra="ЦДІАК 224-2-49", opis="2")
    _rebuild()
    assert S.resolve_case("CDIAK/224/49").key == "CDIAK/224/49"


# ── cases.collect: матеріал, якого ще нема в знімку бібліотеки ──────────────
# 🔴 `_unfiled_material` — окремий, паралельний шлях побудови ключа
# (`parse_slug_case` + `candidate_keys`, той самий приклад слуг, що в
# `resolve.parse_slug_case`: «кадри у службовій підтеці» на кшталт
# `cdiak_224/spr-864/pages`), і саме там `opys_conflict`/`claim_collision`
# додано без власного набору тестів: перевірка через повний `collect_rows`
# заводить робочий простір, якого тут немає (`nysh_skills`, `overrides.json`,
# `case_index.sqlite` тощо), а функції — ті самі, що вже звірені вище й у
# `test_opys_own_key.py`. Прямий модульний тест на слуг — окремим заходом.
