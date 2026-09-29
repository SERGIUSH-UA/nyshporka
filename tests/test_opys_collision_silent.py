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


# ── Шифру справи виправили після прочитання ─────────────────────────────────

def test_run_of_a_case_whose_opys_was_corrected_still_packs(space: Path) -> None:
    """Раннер пише в `case_key` мети шифру паспорта НА МИТЬ прогону. Людина
    виправила опис (`nysh case --shifra`) — прогін лишається прочитанням ЦІЄЇ
    справи, а не «іншої» (29.09: сімнадцять справ Нікополя, оп. 1 → оп. 3)."""
    from _share import make_run

    from nyshporka.core import opys_keys as K
    from nyshporka.share.publish import choose_voices

    folder = _folder(space, "dadno_193/spr-201", shifra="ДАДнО 193-3-201", opis="3")
    _rebuild()
    root = space / "reports" / "htr"
    run = make_run(root, "1885-spr201", case_key="ДАДнО 193-1-201")
    voice = make_run(root, "1885-spr201-diak", case_key="ДАДнО 193-1-201",
                     model="diak.mlmodel")
    other = make_run(root, "1885-spr201-01-00886", case_key="DAHMO/315/886")
    for d in (run, voice):
        _meta(d, case_dir=str(folder))

    got, skipped = choose_voices([run, voice, other], "DADNO/193/201", own=[run.name])

    assert got == [run, voice], skipped
    assert [s["run"] for s in skipped] == [other.name], "сусід іншої справи не їде"
    assert not K.has("DADNO", "193", "1", "201"),         "стара шифра з мети не заводить привидної справи в реєстрі ключів"


def _meta(d: Path, **extra: Any) -> None:
    from nyshporka.share import bundle

    p = d / bundle.META_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    m.update(extra)
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


def test_normalising_a_stale_meta_key_writes_nothing(space: Path) -> None:
    """Нормалізація ключа з мети — читання: колізію в реєстр вона не пише,
    а ключ справи іншого опису називає так само, як набрана руками шифра."""
    from nyshporka import htr_store as H
    from nyshporka.core import opys_keys as K

    _folder(space, "dadno_193/spr-202", shifra="ДАДнО 193-3-202", opis="3")
    _rebuild()
    H._canon_case_key.cache_clear()

    assert H._canon_case_key("ДАДнО 193-1-202") == "DADNO/193-1/202"
    assert not K.has("DADNO", "193", "1", "202")
