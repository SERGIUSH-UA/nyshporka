"""Режим черги шарда: моделі один раз, справи по черзі.

🔴 23.09.2026 бокс-раннер піднімав шарди заново на кожну справу черги: 194
справи по ~15 сторінок, шард жив 20 с, із них 7 с — моделі, а флот стояв на
хвості кожної справи. У режимі черги процес вантажить моделі раз і сам іде до
наступної справи, щойно дочитав свою частину попередньої.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import runner as R


def _queue(tmp_path: Path, entries: list[dict]) -> Path:
    # Теки справ мусять існувати: закриту (прибрану) справу шард пропускає.
    for e in entries:
        if e.get("case_dir"):
            Path(e["case_dir"]).mkdir(parents=True, exist_ok=True)
    q = tmp_path / "queue.jsonl"
    q.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return q


def _args(queue: Path):
    import argparse
    return argparse.Namespace(queue=str(queue), case_dir="", out_dir="", case_key="", shard="1/4",
                              seg_cache_dir="", progress_json=False)


def test_one_process_walks_the_queue_with_one_model_cache(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int, int]] = []
    p = [str(tmp_path / f"p{n}") for n in (1, 2, 3)]

    def fake_case(args, cache=None):
        seen.append((args.case_dir, id(cache), R._EMIT_EXTRA.get("qi")))
        cache.setdefault("loads", 0)
        cache["loads"] += 1 if "rec" not in cache else 0
        cache["rec"] = "модель"
        return 0

    monkeypatch.setattr(R, "_main_case", fake_case)
    q = _queue(tmp_path, [
        {"case_dir": p[0], "out_dir": "/o/1", "index": 1},
        {"case_dir": p[1], "out_dir": "/o/2", "index": 2},
        {"case_dir": p[2], "out_dir": "/o/3", "index": 3},
        {"end": True},
    ])
    assert R.run_queue(_args(q)) == 0
    assert [c for c, _, _ in seen] == p
    assert len({cid for _, cid, _ in seen}) == 1, "кеш моделей — один на всю чергу"
    assert [qi for _, _, qi in seen] == [1, 2, 3], "події несуть номер справи"
    assert R._EMIT_EXTRA == {}, "після черги позначка справи не лишається"


def test_incomplete_from_this_shards_view_is_not_a_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """3 = решту читають сусіди; повноту доводить бокс-раннер із диска."""
    monkeypatch.setattr(R, "_main_case", lambda a, cache=None: 3)
    q = _queue(tmp_path, [{"case_dir": str(tmp_path / "a"), "out_dir": "b"}, {"end": True}])
    assert R.run_queue(_args(q)) == 0


def test_a_drained_shard_leaves_the_queue(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_case(args, cache=None):
        calls.append(args.case_dir)
        cache["drained"] = True
        return 0

    monkeypatch.setattr(R, "_main_case", fake_case)
    a, c = str(tmp_path / "a"), str(tmp_path / "c")
    q = _queue(tmp_path, [{"case_dir": a, "out_dir": "b"},
                          {"case_dir": c, "out_dir": "d"}, {"end": True}])
    R.run_queue(_args(q))
    assert calls == [a], "злитий регулятором шард не бере наступних справ"


def test_emit_carries_the_queue_index(capsys: pytest.CaptureFixture) -> None:
    R._EMIT_EXTRA["qi"] = 7
    try:
        R.emit(True, "htr", page="0001.jpg")
    finally:
        R._EMIT_EXTRA.clear()
    line = capsys.readouterr().out.strip()
    event = json.loads(line[len(R.PROGRESS_PREFIX):])
    assert event["qi"] == 7 and event["page"] == "0001.jpg"


def test_the_cache_loads_once() -> None:
    cache: dict = {}
    loads: list[int] = []
    for _ in range(3):
        R._cached(cache, ("rec", "m", "cuda:0"), lambda: loads.append(1) or "модель")
    assert len(loads) == 1
    assert R._cached(None, ("x",), lambda: "свіже") == "свіже"


def test_a_queue_level_drain_reaches_the_shard(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Регулятор не знає, у якій справі шард: злив — на рівні черги."""
    q = _queue(tmp_path, [{"case_dir": str(tmp_path / "a"), "out_dir": str(tmp_path / "o1")}])
    (tmp_path / R.DRAIN_DIR).mkdir()
    (tmp_path / R.DRAIN_DIR / "2").write_text("t", encoding="utf-8")
    monkeypatch.setattr(R, "_main_case", lambda a, cache=None: 0)
    args = _args(q)
    args.shard = "2/64"
    R.run_queue(args)              # без рядка `end`: вийти мусить сам злив
    assert R.drain_requested(tmp_path / "o1", 1)
    R._QUEUE_DIR = None


def test_a_closed_case_is_skipped_by_a_revived_shard(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Піднятий заново шард іде чергою з початку; кадри закритих справ уже
    прибрано — він їх пропускає, а не падає на відсутній теці."""
    calls: list[str] = []
    monkeypatch.setattr(R, "_main_case", lambda a, cache=None: calls.append(a.case_dir) or 0)
    live = str(tmp_path / "live")
    q = _queue(tmp_path, [{"case_dir": live, "out_dir": "o"}, {"end": True}])
    lines = q.read_text(encoding="utf-8")
    gone = {"case_dir": str(tmp_path / "gone"), "out_dir": "g"}
    q.write_text(json.dumps(gone) + chr(10) + lines, encoding="utf-8")
    assert R.run_queue(_args(q)) == 0
    assert calls == [live]
