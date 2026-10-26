"""📏 Бенч бланка: слово-істина видне в голосі, «разом» — хоч в одному.

Вигадані сторінки й імена.
"""
from __future__ import annotations

import json
from pathlib import Path


def _voice(root: Path, name: str, pages: dict[str, str]) -> Path:
    d = root / name
    d.mkdir()
    for stem, text in pages.items():
        (d / f"{stem}.txt").write_text(text, encoding="utf-8")
    return d


def test_each_voice_and_together(tmp_path: Path) -> None:
    from nyshporka.htr import form_bench as B

    a = _voice(tmp_path, "основний", {"0001": "Мирончук Остап\nшум шум\n",
                                       "0002": "нічого схожого\n"})
    b = _voice(tmp_path, "основний-cells", {"0001": "Мирончукъ\nОрися\n"})
    truth = {"0001": ["Мирончук", "Остап", "Орися"], "0002": ["Дзвінка"]}
    got = B.score(truth, {"основний": a, "основний-cells": b}).as_dict()
    assert got["words"] == 4 and got["pages"] == 2
    seen = {v["name"]: v["seen"] for v in got["voices"]}
    assert seen == {"основний": 2, "основний-cells": 2}
    assert got["together"]["seen"] == 3
    assert [m["word"] for m in got["missed"]] == ["Дзвінка"]
    pages = {v["name"]: v["pages"] for v in got["voices"]}
    assert pages == {"основний": 2, "основний-cells": 1}


def test_a_word_split_by_a_cell_border_is_still_seen(tmp_path: Path) -> None:
    from nyshporka.htr import form_bench as B

    v = _voice(tmp_path, "cells", {"0001": "Миро нчук\n"})
    got = B.score({"0001": ["Мирончук"]}, {"cells": v}).as_dict()
    assert got["voices"][0]["seen"] == 1


def test_short_words_are_not_measured(tmp_path: Path) -> None:
    from nyshporka.htr import form_bench as B

    v = _voice(tmp_path, "cells", {"0001": "і et\n"})
    assert B.score({"0001": ["і", "et"]}, {"cells": v}).words == 0


def test_truth_from_notes_takes_live_readings_and_single_words() -> None:
    from nyshporka.htr import form_bench as B
    from nyshporka.pagestore.models import CaseNote, NoteLine, NoteWord

    old = CaseNote(kind="reading", page="0003.jpg", text="Хибне Читання",
                   line=NoteLine(run="r", line_no=1))
    new = CaseNote(kind="reading", page="0003.jpg", text="Остап Мирончук",
                   line=NoteLine(run="r", line_no=1), supersedes=old.uid)
    word = CaseNote(kind="reading", page="0004.jpg", text="рядок рушія Орися",
                    line=NoteLine(run="r", line_no=2), word=NoteWord(index=3, text="Орися"))
    about = CaseNote(kind="about", text="опис справи")
    got = B.truth_from_notes([old, new, word, about])
    assert got == {"0003": ["Остап", "Мирончук"], "0004": ["Орися"]}


def test_truth_file_keys_are_page_stems(tmp_path: Path) -> None:
    from nyshporka.htr import form_bench as B

    p = tmp_path / "t.json"
    p.write_text(json.dumps({"0005.jpg": ["Остап"], "0006": ["Орися"]}), encoding="utf-8")
    assert B.truth_from_file(p) == {"0005": ["Остап"], "0006": ["Орися"]}
