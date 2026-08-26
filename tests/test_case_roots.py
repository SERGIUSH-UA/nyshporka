"""🗂 Корені справ: теки зі сканами, які лежать поза простором.

Оголошення такої теки довго було побічним ефектом заведення справи
(`nysh case --adopt`), а воно вимагає шифри. Через це найчастіший вхід —
контейнер із десятками книг на зовнішньому диску — накрити було нічим: шифра на
контейнер злила б усі книги в одну справу, тож лишалось правити `nyshporka.toml`
руками.

🔴 Тут перевіряється не «рядок записався», а те, від чого залежить видимість
матеріалу: оголошений корінь мусить пережити перезапуск (він у маркері, а не в
пам'яті процесу), а зняття мусить лишати маркер таким, ніби його не чіпали, —
інакше наступний читач побачить налаштування, якого людина не робила.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Порожній простір і тека зі сканами поза ним."""
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    (root / W.MARKER).write_text(
        "[workspace]\nschema = 1\nname = \"тест\"\n"
        "# case_roots = [\"D:/архів\"]\n", encoding="utf-8")
    monkeypatch.setenv(W.ENV_WORKSPACE, str(root))
    W.reset()
    yield root
    W.reset()


@pytest.fixture
def scans(tmp_path: Path) -> Path:
    d = tmp_path / "зовнішній" / "Метрики"
    d.mkdir(parents=True)
    return d


def test_declared_root_survives_a_restart(space: Path, scans: Path) -> None:
    """🔴 Головне: корінь живе в маркері, а не в пам'яті процесу.

    Інакше після перезапуску скани «зникають» без жодного повідомлення — той
    самий клас поразки, що й тека поза простором: усе виглядає справним.
    """
    res = runner.invoke(app, ["roots", "add", str(scans)])
    assert res.exit_code == 0, res.stdout

    W.reset()  # ← новий процес побачив би рівно це
    assert scans.resolve() in [p.resolve() for p in W.workspace().case_roots()]
    assert "case_roots" in (space / W.MARKER).read_text(encoding="utf-8")


def test_add_needs_no_shifra_unlike_case_register(space: Path, scans: Path) -> None:
    """Контейнер справою не є: шифри в нього немає й бути не може.

    Саме це відрізняє `roots add` від `case --adopt`, і саме через це контейнер
    раніше лишався невидимим: єдиний шлях оголосити теку вимагав того, чого в
    неї немає.
    """
    declared = runner.invoke(app, ["roots", "add", str(scans)])
    assert declared.exit_code == 0, declared.stdout

    refused = runner.invoke(app, ["case", str(scans)])
    assert refused.exit_code == 1, refused.stdout
    assert "шифра" in refused.stdout.lower()


def test_missing_directory_is_refused(space: Path, tmp_path: Path) -> None:
    """Оголосити те, чого немає, — це оголосити невидимість на потім."""
    res = runner.invoke(app, ["roots", "add", str(tmp_path / "нема")])
    assert res.exit_code == 2

    W.reset()
    assert W.workspace().extra_case_roots == ()


def test_list_names_a_root_whose_disk_is_gone(space: Path, scans: Path) -> None:
    """⚠ Зовнішній диск від'єднують, і справи зникають із реєстру.

    Без окремої позначки причина читається як поламка застосунку, а не як
    невставлений носій.
    """
    runner.invoke(app, ["roots", "add", str(scans)])
    scans.rmdir()
    W.reset()

    res = runner.invoke(app, ["roots", "list"])
    assert res.exit_code == 0, res.stdout
    assert "теки немає" in res.stdout


def test_remove_leaves_the_marker_as_if_untouched(space: Path, scans: Path) -> None:
    """🔴 Знятий останній корінь не лишає по собі `case_roots = []`.

    Порожній перелік читається людиною як налаштування, якого вона не робила, —
    і наступний, хто відкриє маркер, шукатиме, хто його поставив.
    """
    runner.invoke(app, ["roots", "add", str(scans)])
    res = runner.invoke(app, ["roots", "remove", str(scans)])
    assert res.exit_code == 0, res.stdout

    text = (space / W.MARKER).read_text(encoding="utf-8")
    assert "case_roots = [" not in text.replace('# case_roots = ["D:/архів"]', "")
    W.reset()
    assert [p.resolve() for p in W.workspace().case_roots()] == [
        (space / "data" / "raw").resolve()]


def test_remove_of_a_root_that_was_never_declared_is_not_silent(
        space: Path, scans: Path) -> None:
    """Мовчазне «готово» на дію, якої не сталось, гірше за відмову."""
    runner.invoke(app, ["roots", "add", str(scans)])
    before = (space / W.MARKER).read_text(encoding="utf-8")

    res = runner.invoke(app, ["roots", "remove", str(scans.parent / "чуже")])
    assert res.exit_code == 1
    assert "не оголошено" in res.stdout
    assert (space / W.MARKER).read_text(encoding="utf-8") == before


def test_second_root_does_not_replace_the_first(space: Path, tmp_path: Path) -> None:
    """Дві теки на диску — типовий вхід, а не рідкість."""
    a, b = tmp_path / "Метрики", tmp_path / "Сповідки"
    a.mkdir()
    b.mkdir()
    runner.invoke(app, ["roots", "add", str(a)])
    runner.invoke(app, ["roots", "add", str(b)])

    W.reset()
    got = {p.resolve() for p in W.workspace().case_roots()}
    assert {a.resolve(), b.resolve()} <= got


def test_an_adopted_folder_shows_up_before_data_raw_exists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 «Взято під облік ✅» над порожньою бібліотекою — на першому запуску.

    Обхід видає лише вміст теки, тож оголошений корінь, який сам є справою,
    обробляється окремою гілкою. Ознакою «це не data/raw» був індекс у списку
    (`if i`), а список відсіює неіснуючі теки — і в щойно створеному просторі,
    де `data/raw` ще немає, оголошена тека ставала нульовою й тихо випадала.

    Тобто вада вражала рівно той сценарій, заради якого дію й зробили: людина
    показує на свою теку сканів на зовнішньому диску, бачить ✅ і порожню
    бібліотеку — і три різні екрани брешуть узгоджено.

    ⚠ Простір ставиться через `W.use`, а не через змінну середовища: читання
    простору з маркера саме створює `data/raw`, і на такому просторі вада не
    відтворюється взагалі. Перша редакція перевірки була зелена й на зламаному
    коді рівно через це.
    """
    root = tmp_path / "простір"
    root.mkdir()
    (root / W.MARKER).write_text(
        '[workspace]\nschema = 1\nname = "тест"\n', encoding="utf-8")
    case = tmp_path / "тримач" / "Метрики 1858"
    case.mkdir(parents=True)
    for i in range(1, 4):
        (case / f"{i:04d}.jpg").write_bytes(b"x")

    W.reset()
    W.use(W.Workspace(root=root, name="тест", origin="test"))

    import nyshporka.library as L

    # ⚠ `RAW_DIR` обчислюється на імпорті модуля, тож у прогоні тестів вона
    # показує на чужий простір — той, що існує. Без цієї підміни `_scan_roots`
    # віддає два корені, оголошена тека дістає індекс 1, і зламана перевірка
    # `if i` проходить: умова вади (raw ще немає) просто не відтворюється.
    monkeypatch.setattr(L, "RAW_DIR", root / "data" / "raw")
    # 🔴 `RAW_DIR` не єдина константа, обчислена на імпорті. Доки підмінялась
    # тільки вона, `build_library()` читав ЗІБРАНУ бібліотеку чужого простору
    # (`case_library.json` розробника) і віддавав його справи — тест падав у
    # повному прогоні й проходив окремо, тобто результат вирішував порядок
    # імпортів, а не код. Спіймано 2026-08-26.
    monkeypatch.setattr(L, "ROOT", root)
    monkeypatch.setattr(L, "SOURCES_DIR", root / "data" / "source" / "sources")
    monkeypatch.setattr(L, "LIBRARY_PATH", root / "data" / "derived" / "case_library.json")
    monkeypatch.setattr(L, "VERDICTS_PATH", root / "data" / "spotter" / "case_verdicts.json")
    for fn in ("load_library", "_opys_merged", "_master_index",
               "_wikisource_meta", "_describe_index"):
        got = getattr(L, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()
    assert not L.RAW_DIR.exists(), "фікстура: raw не мусить існувати"

    from nyshporka import ops as O

    env = O.call("case.register", {"case_dir": str(case),
                                   "shifra": "ДАХмО 315-1-159",
                                   "adopt": True, "reindex": True})
    assert env.ok, env.error
    assert len(L._scan_roots()) == 1, (
        "фікстура: у списку мусить лишитись лише оголошена тека — інакше вада "
        "не відтворюється, бо тека дістає ненульовий індекс")

    lib = L.build_library()
    assert [e.key for e in lib] == ["DAHMO/315/159"], (
        f"оголошена тека не дійшла до бібліотеки: {[e.key for e in lib]}")
    assert lib[0].frames == 3
