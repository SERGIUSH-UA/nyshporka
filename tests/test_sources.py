"""📥 Джерела: розпізнавання входу, реєстр плагінів, канал прогресу.

Найважливіше тут — форма «тека з підтеками». Вона виглядає як порожня справа, і
прийняти її за справу означає прогін на нуль сторінок, який завершується
«успішно», лишаючи людину без тексту й без пояснення.
"""
from __future__ import annotations

import io

import pytest

from nyshporka.core import progress as P
from nyshporka.sources import base, load, registry
from nyshporka.sources.local import LocalSource, inspect


def _touch(path, name: str, size: int = 8):
    f = path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * size)
    return f


# ── розпізнавання входу ──────────────────────────────────────────────────────
def test_folder_of_images_is_a_case(tmp_path):
    for i in range(3):
        _touch(tmp_path, f"{i:04d}.jpg")
    sh = inspect(tmp_path)
    assert sh.kind == "images" and sh.images == 3 and sh.usable
    assert "3 кадр" in sh.explain()


def test_folder_of_subfolders_is_MANY_cases_not_an_empty_one(tmp_path):
    """🔴 Найдорожча плутанина цього шару.

    Тека, всередині якої лежать теки-справи, зображень не містить — тобто
    виглядає порожньою. Прийняти її за справу означає прогін на нуль сторінок,
    який завершується успішно: ні помилки, ні тексту, ні пояснення.
    """
    for name in ("22", "131", "7"):
        _touch(tmp_path / name, "0001.jpg")
    sh = inspect(tmp_path)
    assert sh.kind == "cases" and not sh.usable
    assert len(sh.cases) == 3
    assert "не одна справа" in sh.explain()


def test_numeric_case_folders_sort_as_numbers(tmp_path):
    """22 перед 131 — інакше перелік нечитабельний саме там, де його читають."""
    for name in ("22", "131", "7"):
        _touch(tmp_path / name, "0001.jpg")
    sh = inspect(tmp_path)
    assert [c.label for c in sh.cases] == ["7", "22", "131"]


def test_single_image_is_treated_as_its_folder(tmp_path):
    """«Справа з одного кадру» не має ставати окремим випадком усюди."""
    img = _touch(tmp_path, "0001.jpg")
    _touch(tmp_path, "0002.jpg")
    assert inspect(img).kind == "images"
    assert inspect(img).images == 2


def test_empty_folder_explains_itself(tmp_path):
    sh = inspect(tmp_path)
    assert sh.kind == "empty" and not sh.usable
    assert "немає ні зображень, ні PDF" in sh.explain()


def test_missing_path_is_an_answer_not_a_crash(tmp_path):
    sh = inspect(tmp_path / "нема")
    assert sh.kind == "missing"
    assert "нічого немає" in sh.explain()


def test_pdf_without_reader_reports_unknown_page_count(tmp_path, monkeypatch):
    """🔴 `None` — це чесне «не знаю», і воно краще за вигадане число.

    Оцінку часу без нього просто не показують; вигадана зіпсувала б планування
    на кілька годин уперед.
    """
    pdf = _touch(tmp_path, "справа.pdf", size=100)
    monkeypatch.setitem(__import__("sys").modules, "pypdfium2", None)
    monkeypatch.setitem(__import__("sys").modules, "fitz", None)
    sh = inspect(pdf)
    assert sh.kind == "pdf" and sh.pages is None
    assert "один PDF" in sh.explain()


def test_folder_with_images_and_pdfs_prefers_images(tmp_path):
    """Скани важать більше за супровідний PDF-опис, який часто лежить поруч."""
    _touch(tmp_path, "0001.jpg")
    _touch(tmp_path, "опис.pdf")
    sh = inspect(tmp_path)
    assert sh.kind == "images" and sh.pdfs == 1


# ── локальне джерело ─────────────────────────────────────────────────────────
def test_local_manifest_counts_frames_and_size(tmp_path):
    for i in range(4):
        _touch(tmp_path, f"{i:04d}.jpg", size=1000)
    m = LocalSource().manifest(str(tmp_path))
    assert m.frames == 4 and m.bytes_estimate >= 4000
    assert m.source == "local" and m.title == tmp_path.name


def test_local_manifest_refuses_a_folder_of_cases_with_a_reason(tmp_path):
    _touch(tmp_path / "22", "0001.jpg")
    with pytest.raises(base.SourceError, match="не одна справа"):
        LocalSource().manifest(str(tmp_path))


def test_local_browse_lists_subcases(tmp_path):
    for name in ("a", "b"):
        _touch(tmp_path / name, "0001.jpg")
    nodes = LocalSource().browse(str(tmp_path))
    assert {n.label for n in nodes} == {"a", "b"}
    assert all(n.kind == "case" for n in nodes)


def test_local_browse_without_ref_does_not_walk_the_disk(tmp_path):
    assert LocalSource().browse(None) == []


def test_local_fetch_refuses_to_copy_gigabytes(tmp_path):
    """Друга копія архівної справи з'їла б диск заради нічого."""
    with pytest.raises(base.SourceError, match="уже на диску"):
        LocalSource().fetch("x", tmp_path)


def test_local_declares_only_what_it_can(tmp_path):
    src = LocalSource()
    assert base.supports(src, "manifest") and base.supports(src, "browse")
    assert not base.supports(src, "fetch") and not base.supports(src, "search")


# ── покажчик ─────────────────────────────────────────────────────────────────
def test_manifest_finds_frames_by_index_label():
    """🔴 Покажчик відповідає «де метрики мого села» БЕЗ завантаження."""
    m = base.Manifest(source="x", ref="r", sheets=(
        base.Sheet(1, 5, "лідер плівки"),
        base.Sheet(11, 13, "Жаврени"),
        base.Sheet(132, 223, "Резина"),
    ))
    assert m.frames_for("резина") == (132, 223)
    assert m.frames_for("ЖАВРЕНИ") == (11, 13)
    assert m.frames_for("Кишинів") is None


# ── реєстр ───────────────────────────────────────────────────────────────────
def test_registry_has_local_out_of_the_box():
    reg = load()
    assert reg.get("local") is not None
    assert "local" in {s.id for s in reg.with_cap("manifest")}


def test_broken_plugin_does_not_take_down_the_rest(monkeypatch):
    """🔴 Один зламаний сторонній архів не має гасити локальну теку."""
    class FakeEP:
        name = "поганий"

        def load(self):
            raise ImportError("немає модуля")

    monkeypatch.setattr(registry, "_from_entry_points",
                        lambda: ([], [(FakeEP.name, "ImportError: немає модуля")]))
    reg = load()
    assert reg.get("local") is not None
    assert reg.broken and reg.broken[0][0] == "поганий"


def test_plugin_cannot_shadow_a_builtin(monkeypatch):
    """Сторонній пакет не має підміняти шлях, яким користувач кладе свої скани."""
    class Impostor:
        id = "local"
        label = "підробка"
        caps = frozenset({"fetch"})

    monkeypatch.setattr(registry, "_from_entry_points", lambda: ([Impostor()], []))
    reg = load()
    assert reg.get("local").label == LocalSource().label
    assert any(name == "local" for name, _ in reg.broken)


def test_plugin_without_id_is_rejected_by_name(monkeypatch):
    """Джерело без `id` не має потрапити в реєстр і не має валити збірку.

    Перевіряється через СПРАВЖНІЙ шлях завантаження (підміняється лише
    `entry_points`), інакше тест доводив би працездатність підміни, а не коду.
    """
    import importlib.metadata as meta

    class NoId:
        id = ""
        caps = frozenset()

    class FakeEP:
        name = "безіменний"

        def load(self):
            return lambda: NoId()

    class GoodEP:
        name = "добрий"

        def load(self):
            def factory():
                src = NoId()
                src.id = "чужий_архів"
                return src
            return factory

    monkeypatch.setattr(meta, "entry_points", lambda **_: [FakeEP(), GoodEP()])
    srcs, broken = registry._from_entry_points()
    assert [s.id for s in srcs] == ["чужий_архів"], "справний плагін мав пройти"
    assert [n for n, _ in broken] == ["безіменний"]
    assert "id" in broken[0][1]


# ── канал прогресу ───────────────────────────────────────────────────────────
def test_progress_roundtrip():
    buf = io.StringIO()
    P.emit(phase="fetch", i=12, n=300, item="0012.jpg", stream=buf)
    ev = P.parse(buf.getvalue().strip())
    assert ev and ev.phase == "fetch" and ev.i == 12 and ev.n == 300
    assert ev.item == "0012.jpg" and ev.pct == 4.0


def test_human_lines_are_not_events():
    assert P.parse("[fetch] качаю 0012.jpg") is None
    assert P.parse("") is None


def test_split_routes_each_line_exactly_once():
    buf = io.StringIO()
    P.emit(phase="fetch", i=1, n=2, stream=buf)
    ev, human = P.split(buf.getvalue().strip())
    assert ev is not None and human is None
    ev2, human2 = P.split("звичайний рядок")
    assert ev2 is None and human2 == "звичайний рядок"


def test_foreign_schema_is_ignored_not_misread():
    """🔴 Показник, що бреше, гірший за відсутній.

    Поля прогресу міняються; читач старої версії, який мовчки візьме число
    іншого сенсу, покаже впевнено неправильний відсоток.
    """
    import json
    line = f"{P.PREFIX} {json.dumps({'v': P.SCHEMA + 1, 'i': 5, 'n': 10})}"
    assert P.parse(line) is None


def test_broken_json_does_not_crash_the_reader():
    assert P.parse(f"{P.PREFIX} {{обірваний") is None


def test_event_is_one_line_even_with_cyrillic():
    """Рядок мусить лишитись одним рядком: читач розбирає потік по `\\n`."""
    buf = io.StringIO()
    P.emit(phase="читання", item="справа/аркуш 12", message="усе гаразд", stream=buf)
    assert buf.getvalue().count("\n") == 1


def test_zero_total_does_not_divide_by_zero():
    ev = P.Event(i=0, n=0)
    assert ev.pct == 0.0
