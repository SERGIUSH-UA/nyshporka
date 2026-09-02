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

# 🔴 Імпорт розбірника шифри тут відкладений, і це не стиль. `cases/__init__`
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

    🔴 Порядок тут значущий, і це не примха тесту. `library`, `pagestore.store`
    і `cases.db` беруть шляхи на рівні модуля (`ROOT = workspace().root`), тобто
    заморожують їх у мить першого імпорту. Тому простір оголошується першим
    рядком — інакше імпорт падає ще до підміни, — а вже заморожені константи
    підмінюються поіменно: `workspace.use()` після імпорту їх не зрушить, і
    тест мовчки працював би на справжньому просторі розробника, псуючи його
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


def test_a_soviet_fond_is_registered_under_the_same_key_as_the_library() -> None:
    """🔴 Два розбори шифри на пакет — і вони розійшлись.

    Бібліотека навчилась читати літерний префікс радянського фонду, а `nysh
    case` на тій самій шифрі казав «не розібрав»: у нього був ВЛАСНИЙ шаблон
    номера, де фонд це просто число. Тобто на одне питання — «що таке номер
    фонду» — у пакеті було дві відповіді.

    ⚠ Приймач звіряє саме ЗБІГ із бібліотекою, а не окремо взятий результат:
    інакше два місця можуть бути «правильними» кожне по-своєму й далі
    розходитись.
    """
    from nyshporka.library import _norm_fond

    sh = R.parse_shifra("ДАВіО Р-6129-24-5")
    assert (sh.repo, sh.fond, sh.opys, sh.spr) == ("DAVIO", "R-6129", "24", "5")
    assert sh.fond == _norm_fond("Р-6129"), "реєстрація й бібліотека знову різні"
    # Обидва письма дають той самий фонд — інакше та сама справа заходить в
    # облік двома ключами залежно від того, як її набрали.
    assert R.parse_shifra("ДАВіО R-6129-24-5").fond == sh.fond


def test_a_letter_in_the_opys_number_survives() -> None:
    """Опис теж буває з літерою («201-4б-15»), і доти вона зрізалась разом із
    рештою розбору — шифра просто не читалась."""
    sh = R.parse_shifra("ДАХмО 315-4б-15")
    assert (sh.fond, sh.opys, sh.spr) == ("315", "4б", "15")


def test_shifra_without_archive_is_refused(tmp_path: Path) -> None:
    """🔴 Та сама шифра у двох архівах — це різні справи.

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
    """🔴 Опис їде В теці, а не в окремій базі.

    Тека переїжджає між дисками, копіюється на резервний носій і потрапляє до
    колеги — опис мусить їхати з нею. Зовнішня база лишила б після переїзду
    теку без імені, а базу з посиланням у нікуди.
    """
    R.describe(space, shifra="ДАХмО 315-1-8433", title="Метрична книга",
               year_from=1858, place="Борсуківці")
    sc = json.loads((space / R.SIDECAR).read_text(encoding="utf-8"))
    # 🔴 Скороченням, а не кодом. Сайдкар їде з текою до колеги, і `DAHMO
    # 315-1-8433` навчав би писати шифру формою, якої немає в жодному описі
    # архіву. Код лишається окремим полем `repo` — для машини.
    assert sc["shifra"] == "ДАХмО 315-1-8433"
    assert sc["repo"] == "DAHMO", "код мусить лишитись машинним полем"
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
    """🔴 Сайдкар завантажувача несе, звідки качали. Правка його не стирає.

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
    """Сама лише назва теку справою не робить — і відмова каже, чим зарадити."""
    with pytest.raises(R.RegisterError, match="потрібна шифра"):
        R.describe(space, title="Просто назва")


def test_material_whose_shifra_is_not_established_yet_can_be_described(
        space: Path) -> None:
    """🔴 «Ще не ототожнено» — це стан, а не пропуск.

    Справу знайдено за селом у дзеркалі плівок: номер плівки відомий, фонд і
    опис — ще ні. Доти вибір був недобрий: вигадати шифру, а потім розгрібати
    неправду в обліку, — або відкласти роботу. Ключа цей стан не отримує
    навмисно: провізорний ключ виглядав би як архівна шифра й розтікся б по
    обліку сторінок, реєстру й меті прогонів.
    """
    sc = R.describe(space, film="007548742", note="перепис 1897 за селом")
    assert sc["unidentified"] is True and sc["film"] == "007548742"
    assert "shifra" not in sc, "шифри немає — вигадувати її нема з чого"

    # А коли шифра встановилась, вона пишеться в той самий паспорт, і стан
    # знімається сам: переносити нема чого, бо під провізорним ключем нічого
    # не накопичувалось.
    sc = R.describe(space, shifra="ДАХмО 315-1-8433")
    assert sc["shifra"] == "ДАХмО 315-1-8433" and "unidentified" not in sc
    assert sc["film"] == "007548742", "плівка лишається — це те, як справу взяли"


def test_relative_path_from_the_registry_resolves_against_the_workspace(
        space: Path, monkeypatch, tmp_path: Path) -> None:
    """🔴 Реєстр зберігає шляхи відносними — щоб простір можна було перенести.

    Тому кнопка «змінити» подає `data/raw/…`, а не абсолютний шлях. Якщо його
    резолвити від поточної теки процесу, та сама справа з консолі «зникає», а
    з-під `cd` у корені простору знаходиться: помилка залежить не від даних, а
    від того, звідки запущено, — і тому не відтворюється в того, хто її шукає.
    """
    from nyshporka import ops as O

    R.describe(space, shifra="ДАХмО 315-1-8433", title="Метрична книга")
    rel = space.relative_to(tmp_path).as_posix()
    monkeypatch.chdir(tmp_path.parent)  # свідомо не корінь простору

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
    """🔴 без винятків: пустишка заноситься так само.

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
    """`status=full` означає «виписано всі прізвища» — від цього залежить нуль."""
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


def test_a_folder_outside_the_workspace_is_flagged_not_silently_accepted(
        space: Path, tmp_path: Path) -> None:
    """🔴 Мовчазна поразка всього подальшого шляху.

    Збірка бібліотеки дивиться лише в `<простір>/data/raw`. Тека на робочому
    столі чи на флешці — а саме туди й показує людина, яка щойно поставила
    застосунок, — лишається невидимою. Без цього застереження заведення
    проходило з ✅, опис писався, і на цьому все: реєстр порожній, обліку
    прочитаного нема куди лягти, пошук нічого не знаходить, вивантаження
    відмовляє. Кожен наступний крок падав з окремої причини, і жодна з них не
    називала справжню.
    """
    from nyshporka import ops as O

    outside = tmp_path.parent / "стороння_тека"
    outside.mkdir(exist_ok=True)
    (outside / "0001.jpg").write_bytes(b"x")

    env = O.call("case.register", {"case_dir": str(outside),
                                   "shifra": "ДАХмО 315-1-8433", "reindex": False})
    assert env.ok, env.error
    assert env.data["reachable"] is False
    warn = next((w for w in env.warnings if w.code == "outside_workspace"), None)
    assert warn is not None, "тека поза простором прийнята мовчки"
    # Сказати «не з'явиться» й не сказати, що з цим робити, — половина роботи.
    # Спершу тут перевірялось, чи названо куди перенести теку; відтоді з'явився
    # кращий вихід — узяти її під облік там, де вона лежить, — і перевірка
    # тримається за наявність виходу, а не за конкретний із них.
    assert "облік" in warn.text.lower(), \
        "сказали «не з'явиться», але не сказали, ЩО з цим робити"


def test_a_folder_inside_the_workspace_is_not_flagged(space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("case.register", {"case_dir": str(space),
                                   "shifra": "ДАХмО 315-1-8433", "reindex": False})
    assert env.ok and env.data["reachable"] is True
    assert not any(w.code == "outside_workspace" for w in env.warnings)


@pytest.mark.parametrize("where", ["decode", "pages", "records"])
def test_a_zero_always_carries_its_denominator(space: Path, where: str) -> None:
    """🔴 Головне правило проєкту — і воно довго трималось лише в одній гілці.

    Порожній результат — найдорожча відповідь у генеалогії: «немає» закриває
    напрям назавжди. Пошук по декоду знаменник давав, а пошук по виписаному
    оком і по розібраних записах віддавав голий нуль — саме там, де його читає
    людина, а не агент.
    """
    from nyshporka import ops as O

    O.call("case.register", {"case_dir": str(space), "shifra": "ДАХмО 315-1-8433",
                             "reindex": False})
    env = O.call("search.run", {"q": "Неіснуючий", "where": where})
    assert env.ok, env.error
    assert not env.data["hits"]
    assert "coverage" in env.data, "нуль без знаменника"
    assert any(w.code == "zero_with_denominator" for w in env.warnings), \
        "нуль не сказав, який обсяг переглянуто"


# ── розташування сканів ──────────────────────────────────────────────────────
def test_an_adopted_folder_outside_the_workspace_becomes_a_visible_case(
        space: Path, tmp_path: Path) -> None:
    """🔴 Скани не мусять переїжджати в простір, щоб їх було видно.

    Збірка бібліотеки довго дивилась лише в `data/raw`. Для дослідника, який
    сам будував дерево, це природно; для людини зі сканами на зовнішньому диску
    означало, що заведена справа не з'являлась ніде — без жодної помилки.

    Корені поза простором уже були описані (`case_roots` у `nyshporka.toml`),
    але обхід їх не використовував. Тепер використовує — і зона лишається
    явним переліком: тека потрапляє в неї лише за прямою згодою.
    """
    from nyshporka import library as L
    from nyshporka import ops as O

    outside = tmp_path.parent / "зовнішній_диск" / "Метрики 1858"
    outside.mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3, 4):
        (outside / f"000{i}.jpg").write_bytes(b"x")

    env = O.call("case.register", {"case_dir": str(outside),
                                   "shifra": "ДАХмО 315-1-9001",
                                   "adopt": True, "reindex": False})
    assert env.ok, env.error
    assert env.data["reachable"] is True
    assert env.data.get("adopted"), "теку не оголошено коренем"

    for fn in ("_sidecar_case", "_sidecar_village"):
        getattr(L, fn).cache_clear()
    found = [e for e in L.build_library() if e.key == "DAHMO/315/9001"]
    assert found, "оголошена тека так і не стала справою"
    assert found[0].frames == 4, "кадри порахувались не там"


def test_paths_inside_the_workspace_stay_relative(space: Path) -> None:
    """🔴 Простір переносять на інший диск і віддають колезі.

    Тому шлях справи, що лежить усередині, лишається відносним: абсолютний
    пережив би переїзд лише на тій самій машині. Абсолютний з'являється рівно
    там, де відносного не існує, — для теки за межами простору.
    """
    from nyshporka import library as L

    R.describe(space, shifra="ДАХмО 315-1-8433")
    for fn in ("_sidecar_case", "_sidecar_village"):
        getattr(L, fn).cache_clear()
    entry = next(e for e in L.build_library() if e.key == "DAHMO/315/8433")
    assert not Path(entry.path).is_absolute(), f"шлях став абсолютним: {entry.path}"


def test_declaring_a_root_refuses_a_whole_drive(space: Path) -> None:
    """Оголошення кореня — розширення зони гарда, і воно не безмежне.

    Шлях у гортач приходить із HTTP-запиту; корінь диска перетворив би
    перевірку «чи під дозволеним коренем» на «дозволено все».
    """
    from nyshporka.core.workspace import WorkspaceError, add_case_root

    with pytest.raises(WorkspaceError):
        add_case_root(Path(space.anchor))


def test_a_field_can_be_erased_and_an_empty_one_still_keeps(tmp_path) -> None:
    """🔴 Зворотної дії не було ЗОВСІМ.

    Порожнє поле лишає попереднє значення — правильно: правка заголовка не має
    стирати роки, які хтось уточнив. Але помилково введена назва через це
    лишалась назавжди, і підказка у формі чесно радила «правкою файлу
    `_source.json` у теці» — тобто єдиний вихід із застосунку вів у текстовий
    редактор.
    """
    d = tmp_path / "справа"
    d.mkdir()
    R.describe(d, shifra="ДАХмО 315-1-8433", title="Метрична книга",
               place="М'ястківка", note="куплено 2026")

    # Порожнє — не чіпає.
    got = R.describe(d, title="")
    assert got["title"] == "Метрична книга", "порожнє поле затерло наявне"

    # Тире — стирає, і саме те поле, яке назвали.
    got = R.describe(d, title="-")
    assert "title" not in got, "тире не стерло поля"
    assert got["place"] == "М'ястківка", "стерлось не те, що просили"
    assert got["note"] == "куплено 2026"

    # Довге тире й ен-теш працюють так само: на клавіатурі трапляються всі три.
    assert "place" not in R.describe(d, place="—")
    assert "note" not in R.describe(d, note="–")


def test_a_wrong_year_can_be_erased_like_any_other_field(tmp_path) -> None:
    """🔴 Обіцянка «тире стирає поле» не сміє мати мовчазних винятків.

    Роки йшли окремою гілкою `if val is not None`, а форма перетворювала «-» на
    `Number('-')` → `NaN` → `null`, тобто на «не чіпай». Підказка казала одне,
    поле робило інше, і помилковий рік лишався назавжди.
    """
    d = tmp_path / "справа"
    d.mkdir()
    R.describe(d, shifra="ДАХмО 315-1-8433", year_from=1858, year_to=1860)

    got = R.describe(d, year_from="-")
    assert "year_from" not in got, "рік не стерся"
    assert got["year_to"] == 1860, "стерлось не те, що просили"

    # Рядок із числом приймається — форма шле саме рядок.
    assert R.describe(d, year_from="1858")["year_from"] == 1858
    # А сміття називається сміттям, а не мовчазно ковтається.
    with pytest.raises(R.RegisterError) as e:
        R.describe(d, year_from="позаминулого")
    assert "не рік" in str(e.value)


def test_an_address_is_not_taken_for_a_folder(space: Path) -> None:
    """🔴 Відмова не сміє називати шлях, якого немає на диску.

    `nysh case "ДАХмО 315-1-8433"` мовчки склеював шифру з поточною текою й
    видавав «теки немає: <cwd>/ДАХмО 315-1-8433» — відповідь про стан диска,
    вигаданий самою командою. Ціна заміряна на живому читачі: побачивши той
    рядок, він спитав, чому тека архіву лежить не на місці, хоч матеріал лежав
    рівно там, де мав.

    Резолвити адресу в теку автоматично не можна — `describe` ПИШЕ паспорт, і
    помилка на один номер видала б його чужій теці. Тому команда називає
    різницю й той шлях, який знає.
    """
    with pytest.raises(R.RegisterError) as got:
        R.describe("ДАХмО 315-1-8433")
    said = str(got.value)
    assert "адреса справи" in said
    assert "--shifra" in said and "pages status" in said
    assert "теки немає" not in said, "стара відмова про вигаданий шлях лишилась"


def test_a_missing_folder_is_still_reported_as_a_missing_folder(space: Path) -> None:
    """Шлях, який справді є шляхом, лишається шляхом: підказка точкова."""
    with pytest.raises(R.RegisterError, match="теки немає"):
        R.describe("data/raw/немає-такої")
