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

