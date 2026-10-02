"""Перенос обліку на ключі з описом (`nysh cases rekey`): план, перенос, відкат.

Простір тут — такий, яким його лишила 0.21: сховище сторінок під іменами без
опису, ключі без опису в прив'язках, вердиктах, журналі пошуку, картках і
черзі, реєстр колізій `opys_keys.json`, маркер без поля `keys`. Приймач
переносу — людська праця: нотаток і записів після нього не менше, ніж до, а
відкат повертає простір байт у байт.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from _cherha import drop_space, frames, make_space


@pytest.fixture
def old_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Простір 0.21 з обліком двох книг одного номера й однієї справи фонду 315."""
    from nyshporka.cases import register as R
    from nyshporka.core import legacy_key
    from nyshporka.core import workspace as W
    from nyshporka.library import build_library, write_library

    root = make_space(tmp_path, monkeypatch)
    W.use(replace(W.workspace(), keys=1))
    legacy_key.reset()

    R.describe(frames(root, "dahmo_315/spr-8433"), shifra="ДАХмО 315-1-8433")
    R.describe(frames(root, "cdiak_224/spr-49"), shifra="ЦДІАК 224-1-49")
    R.describe(frames(root, "cdiak_224/op2-spr-49"), shifra="ЦДІАК 224-2-49")
    _json(root / "data/cases/opys_keys.json", {"cases": [
        {"repo": "CDIAK", "fond": "224", "opys": "2", "spr": "49"}]})
    write_library(build_library())

    def note(scan: str, surname: str) -> dict[str, Any]:
        return {"scan": scan, "page_type": "birth", "surnames": [surname],
                "noted": "2026-09-01", "status": "full"}

    def case_file(name: str, key: str, opys: str | None, spr: str,
                  pages: dict[str, Any], records: list[Any] | None = None) -> None:
        _json(root / "data/pages" / name.split("/")[0] / name.split("/")[1], {
            "version": 1, "key": key, "repo": name.split("/")[0],
            "fond": key.split("/")[1].split("-")[0], "spr": spr, "opys": opys,
            "pages": pages, "records": records or []})

    # та сама справа під старим іменем і (хтось уже набрав новий ключ) під новим
    case_file("DAHMO/315-8433.json", "DAHMO/315/8433", "1", "8433",
              {"0001.jpg": note("0001.jpg", "Ковальскій")},
              [{"rid": "r1", "kind": "birth", "scans": ["0001.jpg"]}])
    case_file("DAHMO/315-1-8433.json", "DAHMO/315/1/8433", "1", "8433",
              {"0002.jpg": note("0002.jpg", "Ковальский")})
    # супутній файл справи (вичитка села простору): ім'я йде за файлом справи
    _json(root / "data/pages/DAHMO/315-8433.overrides.json",
          {"version": 1, "key": "DAHMO/315/8433", "overrides": [{"act": "a1"}]})
    # власник старого ключа без опису — книга оп.1; книга оп.2 мала ключ з описом
    case_file("CDIAK/224-49.json", "CDIAK/224/49", "1", "49",
              {"0001.jpg": note("0001.jpg", "Петренко")})
    case_file("CDIAK/224-2-49.json", "CDIAK/224-2/49", "2", "49",
              {"0003.jpg": note("0003.jpg", "Іваненко")})
    _json(root / "data/cases/overrides.json", {
        "runs": {"spr-8433": {"key": "DAHMO/315/8433", "why": "людина"}},
        "bundles": {"ANRM/211-11/@razeni": {"label": "Резина", "runs": ["razeni"]}}})
    _json(root / "data/spotter/case_verdicts.json", {"verdicts": {
        "CDIAK/224/49": {"verdict": "no_clan", "date": "2026-09-01"}}})
    _json(root / "data/derived/verdicts.json", {
        "DAHMO/315/8433": {"run|0001|1": {"verdict": "hit"}}})
    _json(root / "data/derived/search_log.json", {
        "DAHMO/315/8433": [{"q": "Ковальскій", "models": ["pysar"], "channels": []}],
        "DAHMO/315/1/8433": [{"q": "Ковальский", "models": ["pysar"], "channels": []}]})
    _json(root / "data/share/cards.json", {"CDIAK/224-2/49": {"title": "Метрика"}})
    _json(root / "data/queue/queue.json", {"schema": 1, "items": [
        {"id": "CDIAK/224/49", "ref": {"key": "CDIAK/224/49", "aka": "CDIAK/224/49"},
         "state": "queued"}]})
    (root / "config").mkdir(exist_ok=True)
    (root / "config/records_profiles.yaml").write_text(
        "# профілі\ncases:\n  DAHMO/315/8433: dahmo_315\n", encoding="utf-8")
    yield root
    drop_space()


def _json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    """Усе, що перенос може зачепити: облік, реєстри, маркер (без архіву переносу)."""
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith(("data/cases/rekey/", "data/derived/",
                                               "data/raw/")):
            out[rel] = p.read_bytes()
    for rel in ("data/derived/verdicts.json", "data/derived/search_log.json"):
        if (root / rel).is_file():
            out[rel] = (root / rel).read_bytes()
    return out


def _read(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def test_the_plan_writes_nothing_and_names_every_change(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    before = _snapshot(old_space)
    pl = RK.plan()
    assert _snapshot(old_space) == before, "план щось записав"
    moves = {m.src: (m.dst, m.merge) for m in pl.pages}
    assert moves["data/pages/DAHMO/315-8433.json"] == (
        "data/pages/DAHMO/315-1-8433.json", True)
    assert moves["data/pages/CDIAK/224-49.json"][0] == "data/pages/CDIAK/224-1-49.json"
    assert moves["data/pages/CDIAK/224-2-49.json"][0] == "data/pages/CDIAK/224-2-49.json"
    assert ("ANRM/211-11/@razeni", "ANRM/211/11/@razeni") in pl.stores[
        "data/cases/overrides.json"]
    assert "nysh cases rekey --apply" in RK.report(pl)


def test_apply_moves_every_store_and_loses_nothing(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK
    from nyshporka.core import casekey
    from nyshporka.pagestore import store as S

    got = RK.apply()
    assert got["problems"] == [], got
    assert got["census_after"]["page_notes"] == got["census_before"]["page_notes"]
    assert got["census_after"]["records"] == got["census_before"]["records"]
    assert casekey.keys_current()

    pages = old_space / "data/pages"
    assert sorted(p.name for p in pages.glob("*/*.json")) == [
        "224-1-49.json", "224-2-49.json", "315-1-8433.json", "315-1-8433.overrides.json"]
    ovr = _read(old_space, "data/pages/DAHMO/315-1-8433.overrides.json")
    assert ovr == {"version": 1, "key": "DAHMO/315/1/8433", "overrides": [{"act": "a1"}]}
    merged = _read(old_space, "data/pages/DAHMO/315-1-8433.json")
    assert merged["key"] == "DAHMO/315/1/8433"
    assert set(merged["pages"]) == {"0001.jpg", "0002.jpg"}, "злиття загубило аркуш"
    assert [r["rid"] for r in merged["records"]] == ["r1"]
    # старий ключ без опису належав книзі оп.1 — облік не перескочив до оп.2
    assert set(_read(old_space, "data/pages/CDIAK/224-1-49.json")["pages"]) == {"0001.jpg"}
    assert set(_read(old_space, "data/pages/CDIAK/224-2-49.json")["pages"]) == {"0003.jpg"}

    ov = _read(old_space, "data/cases/overrides.json")
    assert ov["runs"]["spr-8433"]["key"] == "DAHMO/315/1/8433"
    assert list(ov["bundles"]) == ["ANRM/211/11/@razeni"]
    assert list(_read(old_space, "data/spotter/case_verdicts.json")["verdicts"]) == [
        "CDIAK/224/1/49"]
    assert list(_read(old_space, "data/derived/verdicts.json")) == ["DAHMO/315/1/8433"]
    log = _read(old_space, "data/derived/search_log.json")
    assert list(log) == ["DAHMO/315/1/8433"] and len(log["DAHMO/315/1/8433"]) == 2
    assert list(_read(old_space, "data/share/cards.json")) == ["CDIAK/224/2/49"]
    item = _read(old_space, "data/queue/queue.json")["items"][0]
    assert item["id"] == item["ref"]["key"] == "CDIAK/224/1/49" and "aka" not in item["ref"]
    assert "DAHMO/315/1/8433: dahmo_315" in (
        old_space / "config/records_profiles.yaml").read_text(encoding="utf-8")
    assert "keys = 2" in (old_space / "nyshporka.toml").read_text(encoding="utf-8")

    moves = _read(old_space, "data/cases/key_moves.json")["moves"]
    assert moves["CDIAK/224/49"] == "CDIAK/224/1/49"
    assert moves["CDIAK/224-2/49"] == "CDIAK/224/2/49"
    # старий ключ і після переносу веде до своєї справи
    assert S.resolve_case("CDIAK/224/49").key == "CDIAK/224/1/49"
    assert S.resolve_case("DAHMO/315/8433").key == "DAHMO/315/1/8433"


def test_a_second_run_changes_nothing(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    RK.apply()
    after = _snapshot(old_space)
    assert RK.plan().empty
    assert RK.apply().get("noop")
    assert _snapshot(old_space) == after


def test_rollback_restores_the_workspace_byte_for_byte(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK
    from nyshporka.core import workspace as W

    before = _snapshot(old_space)
    RK.apply()
    assert _snapshot(old_space) != before
    RK.rollback()
    assert _snapshot(old_space) == before
    assert not (old_space / "data/cases/key_moves.json").exists()
    W.reset()
    W.use(W.Workspace(root=old_space, name="тест", origin="test",
                      keys=W._keys_version(W._read_marker(old_space / W.MARKER))))
    assert W.workspace().keys == 1


def test_a_fresh_lock_stops_the_move(old_space: Path) -> None:
    """Хтось пише в сховище сторінок просто зараз — переносу не буде."""
    from nyshporka.cases import rekey as RK

    (old_space / "data/pages/DAHMO/315-8433.json.lock").write_text("1", encoding="utf-8")
    with pytest.raises(RK.RekeyError, match="пишуть"):
        RK.apply()
    assert not (old_space / "data/cases/rekey").exists()


def test_a_passport_that_names_the_opys_moves_the_record_on_the_next_run(
        old_space: Path) -> None:
    """Справа без опису переїжджає під `_`; дописали опис у паспорт — наступний
    перенос веде облік під ключ з описом, а старий `_`-ключ і далі знаходить її."""
    from nyshporka.cases import register as R
    from nyshporka.cases import rekey as RK
    from nyshporka.core import legacy_key
    from nyshporka.library import build_library, write_library

    d = frames(old_space, "daoo_37/spr-1235")
    write_library(build_library())
    _json(old_space / "data/derived/search_log.json", {
        "DAOO/37/1235": [{"q": "Коваль", "models": ["pysar"], "channels": []}]})
    RK.apply()
    assert list(_read(old_space, "data/derived/search_log.json")) == ["DAOO/37/_/1235"]

    R.describe(d, shifra="ДАОО 37-5-1235")
    write_library(build_library())
    pl = RK.plan()
    assert ("DAOO/37/_/1235", "DAOO/37/5/1235") in pl.stores["data/derived/search_log.json"]
    RK.apply()
    assert list(_read(old_space, "data/derived/search_log.json")) == ["DAOO/37/5/1235"]
    legacy_key.reset()
    assert legacy_key.current_key("DAOO/37/_/1235") == "DAOO/37/5/1235"
    assert legacy_key.current_key("DAOO/37/1235") == "DAOO/37/5/1235"

# ── збій і відкат ────────────────────────────────────────────────────────────
def test_a_failure_halfway_puts_the_workspace_back(old_space: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Файли сторінок уже записано, словники — ні: простір повертається сам, і
    нових файлів, про які відкат не знав би, поруч зі старими не лишається."""
    from nyshporka.cases import rekey as RK

    before = _snapshot(old_space)

    def boom(*a: Any, **k: Any) -> None:
        raise OSError("диск зайнятий")

    monkeypatch.setattr(RK, "_apply_dict", boom)
    with pytest.raises(RK.RekeyError, match="повернуто"):
        RK.apply()
    assert _snapshot(old_space) == before
    (home,) = (old_space / "data/cases/rekey").iterdir()
    journal = _read(old_space, f"data/cases/rekey/{home.name}/journal.json")
    assert "диск зайнятий" in journal["failed"] and journal["rolled_back"]


def test_a_rolled_back_move_is_not_rolled_back_twice(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    RK.apply()
    RK.rollback()
    with pytest.raises(RK.RekeyError, match="немає"):
        RK.rollback()


def test_an_older_move_waits_for_the_later_one(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    first = RK.apply()["stamp"]
    _json(old_space / "data/derived/search_log.json", {
        **_read(old_space, "data/derived/search_log.json"),
        "DAHMO/315/8433": [{"q": "Іваненко", "models": ["pysar"], "channels": []}]})
    second = RK.apply()["stamp"]
    assert first and second and first != second
    with pytest.raises(RK.RekeyError, match="спершу відкотіть"):
        RK.rollback(first, force=True)


def test_rollback_will_not_erase_work_done_after_the_move(old_space: Path) -> None:
    from nyshporka import library as L
    from nyshporka.cases import rekey as RK

    RK.apply()
    L.set_verdict("DAHMO/315/1/8433", "clan_found", note="око", date="2026-10-02")
    with pytest.raises(RK.RekeyError, match=r"case_verdicts\.json"):
        RK.rollback()
    assert "DAHMO/315/1/8433" in L.load_verdicts()
    RK.rollback(force=True)
    assert "DAHMO/315/1/8433" not in L.load_verdicts()


def test_two_moves_in_one_instant_keep_their_own_archives(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    assert len({RK._new_home(old_space).name for _ in range(5)}) == 5


def test_a_move_made_elsewhere_is_seen_without_restart(old_space: Path) -> None:
    """Перенос чи відкат з іншого термінала: процес бачить маркер, а не свій кеш."""
    from nyshporka.core import casekey
    from nyshporka.core import workspace as W

    W.use(W._build(old_space, "test"))
    assert not casekey.keys_current()
    marker = old_space / "nyshporka.toml"
    text = marker.read_text(encoding="utf-8")
    marker.write_text(text + "keys = 2\n", encoding="utf-8")
    assert casekey.keys_current()
    marker.write_text(text, encoding="utf-8")
    assert not casekey.keys_current()


# ── злиття ───────────────────────────────────────────────────────────────────
def test_merged_pages_are_not_reported_as_lost(old_space: Path) -> None:
    """Той самий аркуш в обох файлах справи зливається в один — це не втрата."""
    from nyshporka.cases import rekey as RK

    d = _read(old_space, "data/pages/DAHMO/315-1-8433.json")
    d["pages"]["0001.jpg"] = {"scan": "0001.jpg", "page_type": "birth",
                              "surnames": ["Коваль"], "noted": "2026-09-02",
                              "status": "partial"}
    d["records"] = [{"rid": "r1", "kind": "birth", "scans": ["0001.jpg"]},
                    {"kind": "death", "scans": ["0002.jpg"]},
                    {"kind": "death", "scans": ["0003.jpg"]}]
    _json(old_space / "data/pages/DAHMO/315-1-8433.json", d)
    got = RK.apply()
    assert got["problems"] == [], got
    merged = _read(old_space, "data/pages/DAHMO/315-1-8433.json")
    assert set(merged["pages"]["0001.jpg"]["surnames"]) == {"Коваль", "Ковальскій"}
    # записи без rid — різні записи, а не один
    assert len(merged["records"]) == 3


def test_a_companion_that_cannot_merge_stops_the_move(old_space: Path) -> None:
    """Супутній файл під старим іменем, а під новим уже лежить інший: після
    переносу старий ніхто не читав би. Перенос не починається."""
    from nyshporka.cases import rekey as RK

    _json(old_space / "data/pages/DAHMO/315-1-8433.overrides.json",
          {"version": 1, "key": "DAHMO/315/1/8433", "overrides": [{"act": "b2"}]})
    before = _snapshot(old_space)
    with pytest.raises(RK.RekeyError, match=r"315-8433\.overrides\.json"):
        RK.apply()
    assert _snapshot(old_space) == before
    assert not (old_space / "data/cases/rekey").exists()


def test_queue_items_that_meet_under_one_key_are_named_and_kept_once(
        old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    q = _read(old_space, "data/queue/queue.json")
    q["items"].append({"id": "CDIAK/224/1/49", "ref": {"key": "CDIAK/224/1/49"},
                       "state": "queued"})
    _json(old_space / "data/queue/queue.json", q)
    assert any("двічі" in s for s in RK.plan().stuck["data/queue/queue.json"])
    RK.apply()
    assert [it["id"] for it in _read(old_space, "data/queue/queue.json")["items"]] == [
        "CDIAK/224/1/49"]


def test_a_profile_key_that_already_exists_is_not_doubled(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    (old_space / "config/records_profiles.yaml").write_text(
        "cases:\n  DAHMO/315/8433: old\n  DAHMO/315/1/8433: new\n", encoding="utf-8")
    assert any("уже є" in s for s in RK.plan().stuck["config/records_profiles.yaml"])
    RK.apply()
    text = (old_space / "config/records_profiles.yaml").read_text(encoding="utf-8")
    assert text.count("DAHMO/315/1/8433") == 1


# ── ключ після переносу ──────────────────────────────────────────────────────
def test_a_verdict_under_an_old_key_lands_on_the_case(old_space: Path) -> None:
    from nyshporka import library as L
    from nyshporka.cases import rekey as RK

    RK.apply()
    L.set_verdict("CDIAK/224/49", "clan_found", note="знайшов", date="2026-10-02")
    raw = _read(old_space, "data/spotter/case_verdicts.json")["verdicts"]
    assert list(raw) == ["CDIAK/224/1/49"]
    assert raw["CDIAK/224/1/49"]["verdict"] == "clan_found"
    L.set_verdict("CDIAK/224/49", None)
    assert "CDIAK/224/1/49" not in L.load_verdicts()


def test_a_new_key_beats_an_old_one_for_the_same_case() -> None:
    from nyshporka.core import legacy_key as K

    # старий рядок у файлі ПЕРШИЙ — порядок не вирішує
    d = {"CDIAK/224/49": {"v": "старе"}, "CDIAK/224/1/49": {"v": "нове"}}
    K.reset()
    assert K.rekeyed(d)["CDIAK/224/1/49"] == {"v": "нове"}


def test_a_corrected_opys_carries_the_record_to_the_new_key(old_space: Path) -> None:
    """Після переносу в паспорті виправили опис (224-1-49 → 224-5-49): перебудова
    бібліотеки бачить, що та сама тека змінила ключ, і перенос веде облік за нею."""
    from nyshporka import library as L
    from nyshporka.cases import register as R
    from nyshporka.cases import rekey as RK
    from nyshporka.pagestore import store as S

    RK.apply()
    R.describe(old_space / "data/raw/cdiak_224/spr-49", shifra="ЦДІАК 224-5-49")
    L.write_library(L.build_library())
    assert L.LAST_RENAMED == {"CDIAK/224/1/49": "CDIAK/224/5/49"}
    assert any("rekey --apply" in line for line in L.renamed_report())
    assert [(m.src, m.dst) for m in RK.plan().pages] == [
        ("data/pages/CDIAK/224-1-49.json", "data/pages/CDIAK/224-5-49.json")]
    assert RK.apply()["problems"] == []
    ref = S.resolve_case("ЦДІАК 224-5-49")
    assert ref.key == "CDIAK/224/5/49"
    got = S.load_case(ref)
    assert got is not None and set(got.pages) == {"0001.jpg"}
    assert L.load_verdicts()["CDIAK/224/5/49"]["verdict"] == "no_clan"
    # найстаріший ключ і далі веде до справи
    assert S.resolve_case("CDIAK/224/49").key == "CDIAK/224/5/49"


def test_an_old_key_that_is_a_live_case_again_stays_with_it(old_space: Path) -> None:
    """Справа переїхала з 224-1-49 у 224-5-49, а потім на диску з'явилась
    справжня 224-1-49: її облік за картою переїзду до чужої книги не йде."""
    from nyshporka import library as L
    from nyshporka.cases import register as R
    from nyshporka.cases import rekey as RK

    RK.apply()
    R.describe(old_space / "data/raw/cdiak_224/spr-49", shifra="ЦДІАК 224-5-49")
    L.write_library(L.build_library())
    RK.apply()
    R.describe(frames(old_space, "cdiak_224/op1-spr-49"), shifra="ЦДІАК 224-1-49")
    L.write_library(L.build_library())
    _json(old_space / "data/pages/CDIAK/224-1-49.json", {
        "version": 1, "key": "CDIAK/224/1/49", "repo": "CDIAK", "fond": "224",
        "opys": "1", "spr": "49", "pages": {}, "records": []})
    assert all(m.src != "data/pages/CDIAK/224-1-49.json" for m in RK.plan().pages)


# ── розбір ───────────────────────────────────────────────────────────────────
def test_bundles_of_one_name_in_two_opysy_keep_two_files() -> None:
    from nyshporka.core import casekey as C

    a, b, c = (C.parse(k) for k in ("ANRM/211/11/@ispovidi", "ANRM/211/12/@ispovidi",
                                    "ANRM/211/@ispovidi"))
    assert a and b and c
    assert len({C.stem(a), C.stem(b), C.stem(c)}) == 3


def test_find_takes_no_book_of_another_opys() -> None:
    """Опису не названо — це опис фонду за замовчуванням (ДАХмО 230 → оп.1), і
    єдина справа номера з оп.3 під нього не підходить: те саме правило, що в збірці."""
    from nyshporka import library as L

    lk = L.LibraryLookup.build([{"key": "DAHMO/230/3/13", "repo": "DAHMO", "fond": "230",
                                 "opys": "3", "spr": "13"}])
    assert lk.find("DAHMO", "230", None, "13") is None
    assert lk.find("DAHMO", "230", "3", "13")["key"] == "DAHMO/230/3/13"
    ce = L.CaseEntry(key="DAHMO/230/3/13", repo="DAHMO", fond="230", opys="3", spr="13")
    assert L._same_case({("DAHMO", "230", "13"): [ce]}, "DAHMO", "230", None, "13") is None


def test_an_address_without_opys_does_not_write_into_another_book(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """У бібліотеці лише оп.3 спр.13 фонду 230 (дефолтний опис фонду — 1).
    Адреса без опису веде до оп.1, а не до єдиної книги з тим номером."""
    root = make_space(tmp_path, monkeypatch)
    try:
        from nyshporka.cases import register as R
        from nyshporka.library import build_library, write_library
        from nyshporka.pagestore import store as S

        R.describe(frames(root, "dahmo_230/op3-spr-13"), shifra="ДАХмО 230-3-13")
        write_library(build_library())
        for addr in ("DAHMO/230/_/13", "ДАХмО 230-13"):
            try:
                ref = S.resolve_case(addr)
            except ValueError:
                continue
            assert ref.key != "DAHMO/230/3/13", addr
        assert S.resolve_case("ДАХмО 230-3-13").key == "DAHMO/230/3/13"
    finally:
        drop_space()


# ── знахідки наскрізного прогону (старий простір 0.21.5 → новий код) ─────────
def test_a_lifted_case_moves_in_the_queue_too(old_space: Path) -> None:
    """Справа з `_` дістала опис у паспорті: черга йде за нею, як і решта сховищ."""
    from nyshporka.cases import register as R
    from nyshporka.cases import rekey as RK
    from nyshporka.library import build_library, write_library

    d = frames(old_space, "daoo_37/spr-1235")
    write_library(build_library())
    q = _read(old_space, "data/queue/queue.json")
    q["items"].append({"id": "DAOO/37/1235", "ref": {"key": "DAOO/37/1235"},
                       "state": "queued"})
    _json(old_space / "data/queue/queue.json", q)
    RK.apply()
    R.describe(d, shifra="ДАОО 37-5-1235")
    write_library(build_library())
    RK.apply()
    ids = [it["id"] for it in _read(old_space, "data/queue/queue.json")["items"]]
    assert "DAOO/37/5/1235" in ids and "DAOO/37/_/1235" not in ids


def test_binding_a_run_by_an_old_key_writes_the_new_one(
        old_space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.cases import rekey as RK
    from nyshporka.cases import resolve

    monkeypatch.setattr(resolve, "OVERRIDES_PATH", old_space / "data/cases/overrides.json")
    resolve.load_overrides.cache_clear()
    resolve._run_overrides.cache_clear()
    RK.apply()
    resolve.bind_run("run-8433", "DAHMO/315/8433", why="старий ключ із нотатки")
    ov = _read(old_space, "data/cases/overrides.json")
    assert ov["runs"]["run-8433"]["key"] == "DAHMO/315/1/8433"
    assert RK.plan().empty


def test_a_fresh_lock_on_any_store_stops_the_move(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    (old_space / "data/derived/search_log.json.lock").write_text("1", encoding="utf-8")
    with pytest.raises(RK.RekeyError, match="пишуть"):
        RK.apply()
    assert not (old_space / "data/cases/rekey").exists()


def test_a_broken_store_is_named_not_traced(old_space: Path) -> None:
    from nyshporka.cases import rekey as RK

    (old_space / "data/spotter/case_verdicts.json").write_text("{не json", encoding="utf-8")
    before = _snapshot(old_space)
    with pytest.raises(RK.RekeyError, match=r"case_verdicts\.json"):
        RK.plan()
    with pytest.raises(RK.RekeyError, match=r"case_verdicts\.json"):
        RK.apply()
    assert _snapshot(old_space) == before


def test_rollback_of_a_space_without_a_library_leaves_none(old_space: Path) -> None:
    """Бібліотеку й реєстр, яких до переносу не було, відкат прибирає."""
    from nyshporka.cases import rekey as RK
    from nyshporka.cases.db import DB_PATH
    from nyshporka.library import LIBRARY_PATH

    LIBRARY_PATH.unlink()
    assert not DB_PATH.exists()
    RK.apply()
    assert LIBRARY_PATH.is_file()
    RK.rollback()
    assert not LIBRARY_PATH.exists() and not DB_PATH.exists()


def test_a_bundle_written_without_opys_follows_its_named_bundle(old_space: Path) -> None:
    """До 0.22 облік збірки писався без опису (`ANRM/211/@razeni`), а прив'язка —
    з описом (`ANRM/211-11/@razeni`). Після переносу обидва сховища — під одним ключем."""
    from nyshporka.cases import rekey as RK
    from nyshporka.pagestore import store as S

    # ім'я файла — з `casekey.stem`, як його пише сховище
    pages = old_space / "data/pages/ANRM"
    old_name, new_name = "211-" + "@razeni.json", "211-11-" + "@razeni.json"
    _json(pages / old_name, {
        "version": 1, "key": "ANRM/211/@razeni", "repo": "ANRM", "fond": "211",
        "spr": "@razeni", "pages": {"0001.jpg": {"scan": "0001.jpg", "page_type": "birth",
                                                 "surnames": ["Коваль"], "status": "full",
                                                 "noted": "2026-09-01"}},
        "records": []})
    RK.apply()
    ov = _read(old_space, "data/cases/overrides.json")
    assert list(ov["bundles"]) == ["ANRM/211/11/@razeni"]
    page = _read(old_space, f"data/pages/ANRM/{new_name}")
    assert page["key"] == "ANRM/211/11/@razeni" and "0001.jpg" in page["pages"]
    assert not (pages / old_name).exists()
    assert S.resolve_case("ANRM/211/@razeni").key == "ANRM/211/11/@razeni"


def test_the_plan_names_what_it_joins_and_what_the_file_says(old_space: Path) -> None:
    """Два вердикти однієї справи під різними ключами, і файл обліку, що називає
    опис, якого справа не має: план каже про обидва, а не мовчить."""
    from nyshporka.cases import rekey as RK

    v = _read(old_space, "data/spotter/case_verdicts.json")
    v["verdicts"]["CDIAK/224/1/49"] = {"verdict": "recheck", "date": "2026-09-05"}
    _json(old_space / "data/spotter/case_verdicts.json", v)
    _json(old_space / "data/pages/DAOO/37-1235.json", {
        "version": 1, "key": "DAOO/37/1235", "repo": "DAOO", "fond": "37", "opys": "2",
        "spr": "1235", "pages": {}, "records": []})
    frames(old_space, "daoo_37/spr-1235")
    pl = RK.plan()
    joined = pl.joined["data/spotter/case_verdicts.json"]
    assert any("CDIAK/224/49" in s and "пізніший" in s for s in joined)
    assert any("DAOO/37-1235.json" in s and "опис 2" in s for s in pl.opys_hint)
    text = RK.report(pl)
    assert "вердикти однієї справи" in text and "паспорт" in text
    RK.apply()
    got = _read(old_space, "data/spotter/case_verdicts.json")["verdicts"]["CDIAK/224/1/49"]
    assert got["verdict"] == "recheck"                                # пізніший
    assert [x["verdict"] for x in got["superseded"]] == ["no_clan"]   # і не зник
