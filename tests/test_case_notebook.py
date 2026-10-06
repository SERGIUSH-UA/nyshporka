"""📓 Нотатник справи: секція `notes` у файлі сховища сторінок.

Що тут бережеться:

  · справа без нотаток пишеться як досі — байт у байт, щоб її читав і пакет,
    що нотатника не знає (модель там полів поза переліком не пускає);
  · журнал лише дописується: заміна й відкликання — нові записи, повтор того
    самого `uid` — не дубль;
  · у пул їде лише позначене й загальне, а особисте не їде ніколи — ні як
    запис, ні як ідентифікатор у ланцюжку замін;
  · зведення сторінок для пулу без коментарів і без імені сесії.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nyshporka.pagestore import notebook as NB
from nyshporka.pagestore import store as S
from nyshporka.pagestore.models import CaseNote, NoteLine, NoteWas, PageNote


def _ref() -> S.CaseRef:
    return S.CaseRef(key="DAVO/904/24/54", repo="DAVO", fond="904", spr="54", opys="24",
                     shifra="ДАВіО 904-24-54")


def _raw(ref: S.CaseRef) -> dict:
    return json.loads(S.case_path(ref).read_text(encoding="utf-8"))


# ── модель ───────────────────────────────────────────────────────────────────
def test_a_personal_note_never_carries_the_share_mark() -> None:
    """Модель знімає позначку, а не відмовляє: файл, де така пара вже лежить
    (0.26.0 пропускав її через `note share`), мусить читатись."""
    assert CaseNote(kind="note", text="тут жив мій дід", share=True).share is False


def test_a_case_with_a_broken_personal_entry_still_loads() -> None:
    ref = _ref()
    S.add_notes(ref, [CaseNote(kind="about", text="опис")])
    p = S.case_path(ref)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["notes"].append({"uid": "b" * 32, "kind": "note", "created": "2026-10-06T00:00:00+00:00",
                         "text": "тут жив мій дід", "share": True})
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    cf = S.load_case(ref)
    assert [n.share for n in cf.notes] == [False, False]
    assert NB.outgoing(cf) == []


def test_splitting_moves_a_whole_chain_and_keeps_a_retraction_retracted() -> None:
    src, dst = _ref(), S.CaseRef(key="DAVO/904/24/55", repo="DAVO", fond="904",
                                  spr="55", opys="24")
    S.annotate_pages(src, [PageNote(scan="0031.jpg", page_type="birth")])
    wrong = CaseNote(kind="reading", page="0031", text="Хибно")
    gone = CaseNote(kind="reading", retracts=wrong.uid)
    a = CaseNote(kind="reading", page="0031", text="Петро")
    b = CaseNote(kind="reading", page="0031", text="Петро Іванів", supersedes=a.uid)
    mixed1 = CaseNote(kind="reading", page="0031", text="Іван")
    mixed2 = CaseNote(kind="reading", page="0040", text="Іван Петрів", supersedes=mixed1.uid)
    S.add_notes(src, [wrong, gone, a, b, mixed1, mixed2])
    got = S.move_pages(src, dst, ["0031.jpg"])
    assert got["notes"] == 4 and got["notes_kept"] == 1
    moved = S.load_case(dst).notes
    assert [n.text for n in NB.live(moved)] == ["Петро Іванів"], \
        "відкликане ожило або заміна загубилась"
    left = S.load_case(src).notes
    assert {n.uid for n in left} == {mixed1.uid, mixed2.uid}, "ланцюжок через межу справ лишається"


def test_rekey_merge_keeps_the_notes_of_both_files() -> None:
    from nyshporka.cases.rekey import _merge_case

    a = {"version": 2, "key": "K", "pages": {}, "records": [],
         "notes": [{"uid": "a", "kind": "about", "text": "a"}]}
    b = {"version": 1, "key": "K", "pages": {}, "records": [],
         "notes": [{"uid": "b", "kind": "about", "text": "b"},
                   {"uid": "a", "kind": "about", "text": "a"}]}
    got = _merge_case(b, a)
    assert [n["uid"] for n in got["notes"]] == ["b", "a"] and got["version"] == 2


@pytest.mark.parametrize(("kw", "missing"), [
    ({"kind": "reading", "text": "Грисюкъ"}, "page"),
    ({"kind": "copy"}, "other"),
    ({"kind": "about"}, "text"),
    ({"kind": "catalog-error", "field": "title"}, "як насправді"),
])
def test_each_kind_names_what_it_is_missing(kw: dict, missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        CaseNote(**kw)


def test_a_retraction_carries_no_content() -> None:
    assert CaseNote(kind="reading", retracts="abc").retracts == "abc"


# ── запис ────────────────────────────────────────────────────────────────────
def test_a_case_without_notes_is_written_exactly_as_before() -> None:
    ref = _ref()
    S.annotate_pages(ref, [PageNote(scan="0001.jpg", page_type="birth")])
    raw = _raw(ref)
    assert "notes" not in raw
    assert raw["version"] == 1


def test_notes_are_written_compactly_and_bump_the_format() -> None:
    ref = _ref()
    n = CaseNote(kind="about", text="Метрична книга Покровської церкви, 1834–1836")
    rep = S.add_notes(ref, [n])
    assert rep.added == [n.uid]
    raw = _raw(ref)
    assert raw["version"] == S.FILE_VERSION
    (got,) = raw["notes"]
    assert set(got) == {"uid", "kind", "created", "text"}, \
        "порожні поля запису роздувають діф у git"
    assert S.load_case(ref).notes[0] == n


def test_the_same_uid_twice_is_not_a_duplicate() -> None:
    ref = _ref()
    n = CaseNote(kind="about", text="опис")
    S.add_notes(ref, [n])
    rep = S.add_notes(ref, [n.model_copy(update={"text": "інший текст"})])
    assert rep.merged == [n.uid] and not rep.added
    assert [x.text for x in S.load_case(ref).notes] == ["опис"]


def test_a_correction_must_point_at_an_existing_entry() -> None:
    rep = S.add_notes(_ref(), [CaseNote(kind="about", text="x", supersedes="нема")])
    assert rep.errors and not rep.added


def test_a_file_from_a_newer_package_is_refused_by_name() -> None:
    ref = _ref()
    p = S.case_path(ref)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"version": 99, "key": ref.key, "repo": "DAVO",
                             "fond": "904", "spr": "54"}), encoding="utf-8")
    with pytest.raises(ValueError, match="новішою версією"):
        S.load_case(ref)


def test_splitting_a_bundle_carries_line_readings_with_their_frame() -> None:
    src, dst = _ref(), S.CaseRef(key="DAVO/904/24/55", repo="DAVO", fond="904",
                                  spr="55", opys="24")
    S.annotate_pages(src, [PageNote(scan="0031.jpg", page_type="birth")])
    moving = CaseNote(kind="reading", page="0031", text="Прухницкая")
    staying = CaseNote(kind="reading", page="0040", text="Пухтицкій")
    about = CaseNote(kind="about", text="про першу справу")
    S.add_notes(src, [moving, staying, about])
    S.move_pages(src, dst, ["0031.jpg"])
    assert [n.uid for n in S.load_case(dst).notes] == [moving.uid]
    assert {n.uid for n in S.load_case(src).notes} == {staying.uid, about.uid}


# ── згортка й віддача ────────────────────────────────────────────────────────
def test_live_drops_superseded_and_retracted() -> None:
    a = CaseNote(kind="about", text="старе")
    b = CaseNote(kind="about", text="нове", supersedes=a.uid)
    c = CaseNote(kind="copy", other="ДАВіО 904-24-55")
    d = CaseNote(kind="copy", retracts=c.uid)
    assert [n.uid for n in NB.live([a, b, c, d])] == [b.uid]


def _cf(*notes: CaseNote):
    from nyshporka.pagestore.models import CaseFile

    return CaseFile(key="DAVO/904/24/54", repo="DAVO", fond="904", spr="54",
                    notes=list(notes))


def test_only_marked_general_entries_leave_and_without_the_author() -> None:
    shared = CaseNote(kind="catalog-error", field="years", archive_says="1834",
                      actually="1834–1836", share=True,
                      author="claude-сесія (пошук Пухтицький)")
    home = CaseNote(kind="about", text="поки не певен")
    personal = CaseNote(kind="note", text="тут записана моя прабаба")
    out = NB.outgoing(_cf(shared, home, personal))
    assert [w["uid"] for w in out] == [shared.uid]
    assert "author" not in out[0] and "share" not in out[0]


def test_unsharing_sends_a_bare_retraction() -> None:
    a = CaseNote(kind="about", text="опис", share=True)
    b = CaseNote(kind="about", text="опис з іменами родичів", supersedes=a.uid)
    out = NB.outgoing(_cf(a, b))
    assert out == [{"retracts": a.uid, "kind": "about"}], \
        "зміст домашньої заміни не має виїхати"


def test_a_home_link_in_the_chain_is_invisible_to_the_pool() -> None:
    a = CaseNote(kind="about", text="v1", share=True)
    b = CaseNote(kind="about", text="v2 домашня", supersedes=a.uid)
    c = CaseNote(kind="about", text="v3", supersedes=b.uid, share=True)
    out = NB.outgoing(_cf(a, b, c))
    assert out == [NB.wire_note(c) | {"supersedes": a.uid}]
    assert b.uid not in json.dumps(out)


def test_the_page_digest_keeps_no_comment_and_no_session_name() -> None:
    from nyshporka.pagestore.models import CaseFile

    cf = CaseFile(key="DAVO/904/24/54", repo="DAVO", fond="904", spr="54")
    cf.pages["0031.jpg"] = PageNote(scan="0031.jpg", page_type="birth", status="full",
                                    surnames=["Прухницкая"], comment="кроп ряд.153",
                                    agent="claude-сесія (пошук Пухтицький)")
    cf.pages["0032.jpg"] = PageNote(scan="0032.jpg", page_type="birth",
                                    surnames=["Ковальскій"])
    full, part = NB.pages_digest(cf)
    assert full["surnames"] == ["Прухницкая"]
    assert "surnames" not in part, "неповний перелік назовні читався б як повний"
    blob = json.dumps([full, part], ensure_ascii=False)
    assert "кроп" not in blob and "Пухтицький" not in blob


# ── імпорт вільних тек ока ───────────────────────────────────────────────────
EYE_SAMPLE = """\
# claude_eye — p0531 — звірено оком 2026-09-23
# джерело: ДАЖО 1-73-492, сповідки 1912, приселок Городище (пар. Вереси)
# коригує: Писар DAZHO-1-73-492-pages

[рядок 153] Андрей Терешкевъ(?) Грисюкъ 25
  особи: голова двору Андрей ~1887; жена его Любовь Игнатьева 22
  примітка: ПРІЗВИЩЕ «Грисюкъ», НЕ «Гришкунь». Писар прочитав «Грисюнъ».
"""


def test_eye_file_becomes_a_reading_and_a_private_note() -> None:
    notes, skipped = NB.parse_eye_file(EYE_SAMPLE, "p0531", reader="agent",
                                       model="claude-opus-5-5")
    reading, private = notes
    assert reading.kind == "reading" and reading.text.endswith("Грисюкъ 25")
    assert reading.line == NoteLine(run="DAZHO-1-73-492-pages", line_no=153)
    assert reading.uncertain == ["Терешкевъ"]
    assert reading.created.startswith("2026-09-23")
    assert private.kind == "note" and not private.share and "Гришкунь" in private.text
    assert not skipped


def test_reimporting_the_same_folder_adds_nothing(tmp_path: Path) -> None:
    eye = tmp_path / "DAZHO-1-73-492-pages-claude_eye"
    eye.mkdir()
    (eye / "p0531.txt").write_text(EYE_SAMPLE, encoding="utf-8")
    first = NB.import_eye_dir(eye, reader="agent")
    again = NB.import_eye_dir(eye, reader="agent")
    assert [n.uid for n in first["notes"]] == [n.uid for n in again["notes"]]
    assert first["base_run"] == "DAZHO-1-73-492-pages"


def test_was_is_kept_when_the_eye_file_names_it() -> None:
    text = EYE_SAMPLE.replace("  особи:", "  було: Андрей Теретіевъ Грисюнъ 25\n  особи:")
    reading = NB.parse_eye_file(text, "p0531", reader="agent", model="")[0][0]
    assert reading.was == NoteWas(run="DAZHO-1-73-492-pages",
                                  text="Андрей Теретіевъ Грисюнъ 25")
