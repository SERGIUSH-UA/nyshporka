"""Картки-мішені на плівці: `nysh cases cards`.

Плівка FamilySearch (ДАЧкО ф.931, 17.10.2026) несе дев'ять справ підряд;
межі видно лише за чорними картками зйомки. Тут стережеться те, що на живій
плівці виявилось пасткою: чорна обкладинка книги тоном не відрізняється від
картки й не мусить випадати зі справи, номер котушки на першому кадрі межі не
ставить, а незаповнений «?» у карті не стає справою.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.cases import cards as C
from nyshporka.cases import split as SPL

#: тон кадру: "P" — аркуш книги, "K" — картка (білий друк на чорному),
#: "B" — чорна обкладинка (тоном як картка)
FILM = ("K" "PPP"            # номер котушки + ракорд
        "KK" "PPPP"          # початкова д.923 + «CONTINUED» → справа
        "KK" "BPPPP"         # END 923 + початкова 924 → справа з чорною обкладинкою
        "KKB" "PPP"          # END 924 + початкова 925 + обкладинка → справа
        "KK" "PP")           # END 925 + END котушки → ракорд


def _frame(path: Path, kind: str) -> None:
    from PIL import Image, ImageDraw

    if kind == "P":
        im = Image.new("L", (400, 300), 205)
        ImageDraw.Draw(im).rectangle((40, 40, 360, 60), fill=40)
    elif kind == "G":                      # сіра картка зйомки 2001 р.
        im = Image.new("L", (400, 300), 45)
        ImageDraw.Draw(im).rectangle((200, 40, 380, 70), fill=200)
    else:
        im = Image.new("L", (400, 300), 10)
        if kind == "K":
            ImageDraw.Draw(im).rectangle((200, 40, 380, 70), fill=250)
    im.save(path, "JPEG", quality=90)


@pytest.fixture
def film(tmp_path: Path) -> Path:
    d = tmp_path / "007803999"
    d.mkdir()
    for i, kind in enumerate(FILM, 1):
        _frame(d / f"{i:04d}.jpg", kind)
    return d


def test_segments_follow_cards(film: Path) -> None:
    f = C.scan(film)
    got = [(s.kind, s.names[0], s.names[-1]) for s in f.segments]
    assert got == [
        ("cards", "0001.jpg", "0001.jpg"),
        ("leader", "0002.jpg", "0004.jpg"),
        ("cards", "0005.jpg", "0005.jpg"),   # перша група — лише початкова картка
        ("case", "0006.jpg", "0010.jpg"),    # «CONTINUED FROM» — у справі, не поза нею
        ("cards", "0011.jpg", "0012.jpg"),
        ("case", "0013.jpg", "0017.jpg"),     # чорна обкладинка 0013 — у справі
        ("cards", "0018.jpg", "0019.jpg"),
        ("case", "0020.jpg", "0023.jpg"),     # третій темний кадр групи — теж у справі
        ("cards", "0024.jpg", "0025.jpg"),
        ("leader", "0026.jpg", "0027.jpg"),
    ]
    assert len(f.cases) == 3


def test_draft_map_covers_every_frame(film: Path, tmp_path: Path) -> None:
    f = C.scan(film)
    rows = json.loads(C.write_map(f, tmp_path / "m.json").read_text(encoding="utf-8"))
    assert [r["spr"] for r in rows].count("?") == 3
    names = sorted(p.name for p in film.glob("*.jpg"))
    covered = []
    for r in rows:
        a, b = names.index(r["first"]), names.index(r["last"])
        covered += names[a:b + 1]
    assert covered == names


def test_sheet_one_row_per_card_group(film: Path, tmp_path: Path) -> None:
    from PIL import Image

    f = C.scan(film)
    sheets = C.sheet(f, tmp_path / "sheets", cell=200)
    assert len(sheets) == 1
    with Image.open(sheets[0]) as im:
        assert im.height == 5 * int(200 * 0.66)


def test_apply_numbers_counts(film: Path) -> None:
    f = C.scan(film)
    C.apply_numbers(f, ["923", "924", "925"])
    assert [s.spr for s in f.cases] == ["923", "924", "925"]
    with pytest.raises(C.CardsError):
        C.apply_numbers(f, ["923"])


def test_no_cards_one_case(tmp_path: Path) -> None:
    d = tmp_path / "plain"
    d.mkdir()
    for i in range(1, 9):
        _frame(d / f"{i:04d}.jpg", "P")
    f = C.scan(d)
    assert [s.kind for s in f.segments] == ["case"]
    assert not f.runs


def test_split_refuses_unfilled_number(film: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nyshporka.cases.chain.sidecar_of", lambda d: (None, {}))
    with pytest.raises(SPL.SplitError, match="не заповнено"):
        SPL.plan(film, [("?", "0007.jpg", "0010.jpg")])


def test_numbering_gaps() -> None:
    assert C.numbering_gaps(["0001.jpg", "0002.jpg", "0005.jpg"]) == [3, 4]
    assert C.numbering_gaps(["0001.jpg", "0002.jpg"]) == []
    assert C.numbering_gaps(["a.jpg", "b.jpg"]) == []


def test_lone_card_warned_only_inside(tmp_path: Path) -> None:
    d = tmp_path / "lone"
    d.mkdir()
    for i, kind in enumerate("KK" "PPPPPPP" "K" "PPPPPPP" "KK" "PPPPPPP" "K" "P" "K", 1):
        _frame(d / f"{i:04d}.jpg", kind)
    f = C.scan(d)
    # 0010 — між двома справами; 0001 (перша початкова), 0029 і 0031 (хвіст) — край
    assert [s.names[0] for s in f.lone_inside] == ["0010.jpg"]


def test_film_head_two_service_cards_and_black_cover(tmp_path: Path) -> None:
    """Голова плівки ДАЧкО 007803997: «SOME EXPOSURES…» + номер котушки, ракорд,
    початкова картка й одразу чорна обкладинка першої книги."""
    d = tmp_path / "head"
    d.mkdir()
    for i, kind in enumerate("KK" "PPP" "KB" "PPPP" "KK" "PPPP" "KK" "P" "K", 1):
        _frame(d / f"{i:04d}.jpg", kind)
    got = [(s.kind, s.names[0], s.names[-1]) for s in C.scan(d).segments]
    assert got[:4] == [("cards", "0001.jpg", "0002.jpg"),
                       ("leader", "0003.jpg", "0005.jpg"),
                       ("cards", "0006.jpg", "0006.jpg"),
                       ("case", "0007.jpg", "0011.jpg")]    # обкладинка 0007 — у справі
    assert got[-3:] == [("cards", "0018.jpg", "0019.jpg"),
                        ("leader", "0020.jpg", "0020.jpg"),
                        ("cards", "0021.jpg", "0021.jpg")]


def test_grey_cards_found_by_loose_threshold(tmp_path: Path) -> None:
    """ДАЧкО 007821789 (зйомка 2001 р.): картки сірі, строгий поріг їх не бачить."""
    d = tmp_path / "grey"
    d.mkdir()
    for i, kind in enumerate("G" "PPP" "G" "PPPPPPP" "GG" "PPPPPPP" "GG" "PP" "G", 1):
        _frame(d / f"{i:04d}.jpg", kind)
    f = C.scan(d)
    assert f.loose
    cases = [(s.names[0], s.names[-1]) for s in f.cases]
    assert cases == [("0006.jpg", "0012.jpg"), ("0015.jpg", "0021.jpg")]


def test_black_cards_keep_strict_threshold(film: Path) -> None:
    assert not C.scan(film).loose
