"""🔒 Позначка `private` у паспорті справи — фільтр «нікуди з машини».

Автоматика (автовіддача, готове з `--ready`) приватну справу пропускає з
попередженням; ручна віддача в Супрягу відмовляє, доки автор не скаже
`--private-ok`. Помилка тут дорога: вміст справи замовника, що ліг у
відкритий пул, звідти вже не забрати.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _share import make_run, manifest_for

from nyshporka import ops as O
from nyshporka.cases import privacy
from nyshporka.core import workspace as W

pytestmark = pytest.mark.real_paths

KEY = "DAHMO/315/1/8433"


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    (hub / W.MARKER).write_text('[workspace]\nname = "Майстерня"\nkeys = 2\n',
                                encoding="utf-8")
    return hub


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


@pytest.fixture
def marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Приватна справа в бібліотеці Майстерні; повертає її паспорт."""
    import nyshporka.library as L

    hub = _hub(tmp_path)
    W.use(W._build(hub, "test"))
    d = hub / "data" / "raw" / "dahmo_315" / "op1-spr-8433"
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"\xff\xd8")
    passport = d / "_source.json"
    passport.write_text(json.dumps({"shifra": "ДАХмО 315-1-8433", "private": True}),
                        encoding="utf-8")
    rows = [{"key": KEY, "repo": "DAHMO", "fond": "315", "opys": "1", "spr": "8433",
             "path": "data/raw/dahmo_315/op1-spr-8433"}]
    monkeypatch.setattr(L, "load_library", lambda: rows)
    return passport


# ── запис ────────────────────────────────────────────────────────────────────
def test_register_sets_clears_and_order_marks_new_cases(tmp_path: Path) -> None:
    from nyshporka.cases.register import describe, read_sidecar

    hub = _hub(tmp_path)
    for pid, kind in (("rid", "family"), ("order-1", "order")):
        from nyshporka.project import create

        create(hub, pid, kind=kind, title=pid, version="0")
    raw = hub / "data" / "raw" / "dahmo_315"
    a, b = raw / "spr-1", raw / "spr-2"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    W.use(W._build(hub / "projects" / "order-1", "test"))
    assert describe(a, shifra="ДАХмО 315-1-1").get("private") is True
    assert "private" not in describe(a, private=False)
    assert "private" not in describe(a), "наявний паспорт позначка сама не чіпає"
    W.use(W._build(hub / "projects" / "rid", "test"))
    assert "private" not in describe(b, shifra="ДАХмО 315-1-2")
    assert describe(b, private=True)["private"] is True
    assert read_sidecar(b)["private"] is True


def test_is_private_reads_the_passport_live(marked: Path) -> None:
    assert privacy.is_private(KEY) == marked
    assert privacy.is_private("DAHMO/315/1/9999") is None
    marked.write_text(json.dumps({"shifra": "ДАХмО 315-1-8433"}), encoding="utf-8")
    assert privacy.is_private(KEY) is None, "реєстр не потрібен: читається паспорт"


def test_split_parts_inherit_the_mark() -> None:
    from nyshporka.cases import split

    assert "private" in split._PROVENANCE


# ── Супряга ──────────────────────────────────────────────────────────────────
def test_pack_refuses_unless_the_author_says_so(marked: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import publish as PUB

    run = make_run(W.workspace().htr_reports, "dahmo-315-1-8433", case_key=KEY)
    monkeypatch.setattr(PUB, "resolve_runs", lambda scope, skip=(): ([run], {"key": KEY}))
    env = O.call("share.pack", {"case": KEY, "dry_run": True})
    assert not env.ok and "private" in env.error and "--private-ok" in env.error
    assert env.data == {"refusal": "private", "case": KEY, "passport": str(marked)}
    env = O.call("share.pack", {"case": KEY, "dry_run": True, "private_ok": True})
    assert "private" not in (env.error or ""), env.error


def test_publish_is_the_last_line_for_an_old_package(marked: Path, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import bundle
    from nyshporka.share import catalog as C
    from nyshporka.share import upload as U

    run = make_run(tmp_path / "runs", "dahmo-315-1-8433", case_key=KEY)
    m = manifest_for([bundle.voice_of(run)])
    m.case["key_local"] = KEY
    pack = tmp_path / "old.nyshtext"
    bundle.write(pack, m, [run])
    monkeypatch.setattr(U, "token", lambda: "t")
    monkeypatch.setattr(C, "may_send_key", lambda home, explicit=False: True)

    def reached(*_a: object, **_k: object) -> dict[str, object]:
        raise RuntimeError("дійшло до пулу")

    monkeypatch.setattr(U, "_request", reached)
    with pytest.raises(U.UploadError) as exc:
        U.publish(pack)
    assert exc.value.klas == "private"
    with pytest.raises(RuntimeError, match="дійшло до пулу"):
        U.publish(pack, private_ok=True)


def test_note_push_refuses_even_on_dry_run(marked: Path) -> None:
    env = O.call("note.push", {"case": KEY, "dry_run": True})
    assert not env.ok and env.data["refusal"] == "private"


def test_push_checks_the_whole_list_and_skips_private_from_ready(
        marked: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import nyshporka.ops_share as OS
    from nyshporka.share import batch as B
    from nyshporka.share import suggest as SG
    from nyshporka.share import upload as U

    env = O.call("share.push", {"cases": [KEY]})
    assert not env.ok and env.data["refusal"] == "private" and env.data["cases"] == [KEY]

    monkeypatch.setattr(SG, "nepodileni",
                        lambda: [{"case_key": KEY, "status": next(iter(SG.READY_STATUSES))}])
    monkeypatch.setattr(U, "token", lambda: "t")
    sent: list[list[dict[str, object]]] = []

    def viddaty(cherha: list[dict[str, object]], **_k: object) -> dict[str, object]:
        sent.append(cherha)
        return {"summary": {"notes_failed": 0}, "rows": [], "failed": [], "jobs": 1,
                "total": 0}

    monkeypatch.setattr(B, "viddaty", viddaty)
    env = O.call("share.push", {"ready": True})
    assert env.ok, env.error
    assert sent == [[]]
    assert any(w.code == "private" for w in env.warnings)
    assert OS._private_in([{"case": KEY, "private_ok": True}]) == []


def test_autoshare_skips_with_a_warning(marked: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import profile as P

    monkeypatch.setattr(P, "load", lambda: SimpleNamespace(auto=True, consent="zavzhdy"))
    env = O.call("share.autoshare", {"case": KEY})
    assert env.ok and env.data["refusal"] == "private"
    assert any(w.code == "private" for w in env.warnings)
