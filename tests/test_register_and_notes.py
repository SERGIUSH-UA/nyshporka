"""🗂👁 Дві поверхні, без яких застосунок був наполовину німим.

**Завести справу.** Опис міг з'явитись лише з каталогу архіву або з сайдкара,
який писали скрипти дослідницького конвеєра. Людина зі сканами на диску лишалась
без ключа — а без ключа немає ні обліку прочитаного, ні місця в реєстрі, ні
можливості послатись на знахідку.

**Занести переглянуте.** Сховище прочитаного можна було читати (пошук, експорт),
але не писати: воно лишалось би порожнім назавжди. А саме воно й робить нуль
осмисленим — «не гортати ті самі аркуші вдруге».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# 🔴 Імпорт РОЗБІРНИКА ШИФРИ тут відкладений, і це не стиль. `cases/__init__`
# тягне за собою `library`, а той на рівні модуля кличе `workspace()` — тобто
# просте `from nyshporka.cases import register` вимагає налаштованого простору
# ще на етапі збору тестів. Це та сама «застигла константа», що названа в
# ризиках плану; тут вона обходиться, а не лікується — лікування чіпає
# центральний модуль і має бути окремою свідомою зміною.
R: Any = None


@pytest.fixture(autouse=True)
def _register_module(space):
    global R
    from nyshporka.cases import register

    R = register


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір із текою сканів.

    🔴 Порядок тут ЗНАЧУЩИЙ, і це не примха тесту. `library`, `pagestore.store`
    і `cases.db` беруть шляхи на рівні МОДУЛЯ (`ROOT = workspace().root`), тобто
    заморожують їх у мить першого імпорту. Тому простір оголошується ПЕРШИМ
    рядком — інакше імпорт падає ще до підміни, — а вже заморожені константи
    підмінюються поіменно: `workspace.use()` після імпорту їх не зрушить, і
    тест мовчки працював би на СПРАВЖНЬОМУ просторі розробника, псуючи його
    дані й зеленіючи від чужих.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L
    from nyshporka.cases import db as DB
    from nyshporka.pagestore import store as S

    for mod, attr, value in (
        (L, "ROOT", tmp_path), (L, "RAW_DIR", tmp_path / "data" / "raw"),
        (L, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (L, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)
    L.load_library.cache_clear() if hasattr(L.load_library, "cache_clear") else None
    for fn in ("_opys_merged", "_master_index", "_wikisource_meta", "_describe_index"):
        got = getattr(L, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()

    case = tmp_path / "data" / "raw" / "моя_справа"
    case.mkdir(parents=True)
    for i in (1, 2, 3):
        (case / f"000{i}.jpg").write_bytes(b"x")
    return case


# ── шифра ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "ДАХмО 315-1-8433",
    "дахмо 315-1-8433",
    "ДАХмО ф.315 оп.1 спр.8433",
    "DAHMO 315/1/8433",
])
def test_shifra_accepts_the_forms_people_actually_write(text: str) -> None:
    """Аматор пише шифру як завгодно — і має рацію: єдиного стандарту немає."""
    sh = R.parse_shifra(text)
    assert (sh.repo, sh.fond, sh.opys, sh.spr) == ("DAHMO", "315", "1", "8433")


def test_mirror_style_shifra_is_understood() -> None:
    """Дзеркало плівок пише «Ф. 211 Оп. 3 Д. 140» — те саме іншими словами."""
    sh = R.parse_shifra("Ф. 211 Оп. 3 Д. 140", repo_hint="ANRM")
    assert (sh.repo, sh.fond, sh.opys, sh.spr) == ("ANRM", "211", "3", "140")


def test_shifra_without_archive_is_refused(tmp_path: Path) -> None:
    """🔴 Та сама шифра у двох архівах — це РІЗНІ справи.

    Прийняти «315-1-8433» без архіву означало б злити їх в одну, і виявилось би
    це аж тоді, коли в справі опиняться чужі сторінки.
    """
    with pytest.raises(R.RegisterError, match="архів"):
        R.parse_shifra("315-1-8433")


def test_empty_shifra_explains_why_it_matters() -> None:
    with pytest.raises(R.RegisterError, match="ключ"):
        R.parse_shifra("")


# ── опис ─────────────────────────────────────────────────────────────────────
def test_describe_writes_the_sidecar_into_the_case_folder(space: Path) -> None:
    """🔴 Опис їде В ТЕЦІ, а не в окремій базі.

    Тека переїжджає між дисками, копіюється на резервний носій і потрапляє до
    колеги — опис мусить їхати з нею. Зовнішня база лишила б після переїзду
    теку без імені, а базу з посиланням у нікуди.
    """
    R.describe(space, shifra="ДАХмО 315-1-8433", title="Метрична книга",
               year_from=1858, place="Борсуківці")
    sc = json.loads((space / R.SIDECAR).read_text(encoding="utf-8"))
    assert sc["shifra"] == "DAHMO 315-1-8433"
    assert sc["title"] == "Метрична книга"
    assert sc["year_from"] == 1858
    assert sc["edited_by_hand"] is True


def test_editing_one_field_does_not_wipe_the_others(space: Path) -> None:
    """Правка заголовка не має стирати роки, які хтось уже уточнив."""
    R.describe(space, shifra="ДАХмО 315-1-8433", title="Стара назва",
               year_from=1858, year_to=1860, place="Борсуківці")
    R.describe(space, title="Нова назва")
    sc = json.loads((space / R.SIDECAR).read_text(encoding="utf-8"))
    assert sc["title"] == "Нова назва"
    assert sc["year_from"] == 1858 and sc["year_to"] == 1860
    assert sc["place"] == "Борсуківці"


def test_provenance_of_a_downloaded_case_survives_a_hand_edit(space: Path) -> None:
    """🔴 Сайдкар завантажувача несе, ЗВІДКИ качали. Правка його не стирає.

    Інакше перший же ручний коментар знищив би доказ походження — а він і є
    підстава довіряти шифрі.
    """
    (space / R.SIDECAR).write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "url": "https://archium/…",
        "fetched": "2026-07-02", "desc_source": "archium_catalog"}),
        encoding="utf-8")
    R.describe(space, title="Уточнив рукою")
    sc = json.loads((space / R.SIDECAR).read_text(encoding="utf-8"))
    assert sc["url"] and sc["fetched"], "провенанс затерто"
    assert sc["desc_source"] == "archium_catalog", "походження опису підмінено"
    assert sc["edited_by_hand"] is True, "слід ручної правки не лишився"


def test_describe_without_shifra_on_a_fresh_folder_refuses(space: Path) -> None:
    with pytest.raises(R.RegisterError, match="шифра обов'язкова"):
        R.describe(space, title="Просто назва")


def test_relative_path_from_the_registry_resolves_against_the_workspace(
        space: Path, monkeypatch, tmp_path: Path) -> None:
    """🔴 Реєстр зберігає шляхи ВІДНОСНИМИ — щоб простір можна було перенести.

    Тому кнопка «змінити» подає `data/raw/…`, а не абсолютний шлях. Якщо його
    резолвити від поточної теки процесу, та сама справа з консолі «зникає», а
    з-під `cd` у корені простору знаходиться: помилка залежить не від даних, а
    від того, звідки запущено, — і тому не відтворюється в того, хто її шукає.
    """
    from nyshporka import ops as O

    R.describe(space, shifra="ДАХмО 315-1-8433", title="Метрична книга")
    rel = space.relative_to(tmp_path).as_posix()
    monkeypatch.chdir(tmp_path.parent)  # свідомо НЕ корінь простору

    env = O.call("case.show", {"case_dir": rel})
    assert env.ok, env.error
    assert env.data["described"] is True
    assert env.data["scans"] == 3


def test_forget_removes_only_the_sidecar(space: Path) -> None:
    R.describe(space, shifra="ДАХмО 315-1-8433")
    assert R.forget(space) is True
    assert not (space / R.SIDECAR).exists()
    assert list(space.glob("*.jpg")), "скани зникли разом з описом"
    assert R.forget(space) is False


# ── облік прочитаного ────────────────────────────────────────────────────────
def test_full_cycle_register_note_find(space: Path) -> None:
    """Наскрізь: завести → занести переглянуте → знайти занесене."""
    from nyshporka import ops as O

    env = O.call("case.register", {
        "case_dir": str(space), "shifra": "ДАХмО 315-1-8433",
        "title": "Метрична книга с. Борсуківці"})
    assert env.ok, env.error

    env = O.call("pages.status", {"case": "ДАХмО 315-1-8433"})
    assert env.ok and env.data["total_disk"] == 3
    assert env.data["noted"] == 0

    env = O.call("pages.note", {
        "case": "ДАХмО 315-1-8433", "scan": "0001.jpg", "page_type": "confession",
        "surnames": "Ковальскій,Мельникъ", "status": "full"})
    assert env.ok, env.error

    env = O.call("pages.status", {"case": "ДАХмО 315-1-8433"})
    assert env.data["noted"] == 1 and env.data["unnoted_count"] == 2

    env = O.call("search.run", {"q": "Ковальський", "where": "pages"})
    assert env.ok
    assert env.data["hits"], "занесене прізвище не знаходиться"


def test_a_blank_page_is_worth_noting_too(space: Path) -> None:
    """🔴 БЕЗ ВИНЯТКІВ: пустишка заноситься так само.

    Негативний результат коштує тих самих очей, і без запису наступна сесія
    відкриє той самий аркуш ще раз.
    """
    from nyshporka import ops as O

    O.call("case.register", {"case_dir": str(space), "shifra": "ДАХмО 315-1-8433"})
    env = O.call("pages.note", {
        "case": "ДАХмО 315-1-8433", "scan": "0002.jpg", "page_type": "blank",
        "status": "full", "comment": "порожній аркуш"})
    assert env.ok
    # Порожня сторінка без прізвищ — законна; попередження про це є, і воно
    # не заважає запису.
    assert O.call("pages.status", {"case": "ДАХмО 315-1-8433"}).data["noted"] == 1


def test_full_without_surnames_is_flagged(space: Path) -> None:
    """`status=full` означає «виписано ВСІ прізвища» — від цього залежить нуль."""
    from nyshporka import ops as O

    O.call("case.register", {"case_dir": str(space), "shifra": "ДАХмО 315-1-8433"})
    env = O.call("pages.note", {
        "case": "ДАХмО 315-1-8433", "scan": "0003.jpg",
        "page_type": "confession", "status": "full"})
    assert any(w.code == "full_without_surnames" for w in env.warnings)


def test_reading_the_decode_is_marked_as_not_eye_verified(space: Path) -> None:
    """Гілка «читав декод» успадковує чужі помилки — і має це казати."""
    from nyshporka import ops as O

    O.call("case.register", {"case_dir": str(space), "shifra": "ДАХмО 315-1-8433"})
    env = O.call("pages.note", {
        "case": "ДАХмО 315-1-8433", "scan": "0001.jpg", "page_type": "confession",
        "surnames": "Ковальскій", "method": "htr"})
    assert any(w.code == "not_eye_verified" for w in env.warnings)


def test_unknown_case_folder_is_not_reported_as_zero_scans(tmp_path: Path) -> None:
    """🔴 «0 на диску» й «теки не знайшли» — різні речі.

    Перше означає «справа порожня», друге — «реєстр про неї ще не знає». Перше
    читається як «скани зникли», і людина йде їх шукати.
    """
    from nyshporka import ops as O
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    env = O.call("pages.status", {"case": "ДАХмО 315-1-9999"})
    assert env.ok
    assert env.data["case_dir_known"] is False
    assert any(w.code == "case_dir_unknown" for w in env.warnings)
