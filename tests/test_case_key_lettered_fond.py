"""Ключ справи з літерним фондом («DAHMO/R-100/7») — те, що пакет сам друкує,
пакет мусить і приймати назад (issue #21).

🔴 Два регекси, що розбирають короткий ключ `repo/фонд/справа` назад у пошук,
знали фонд лише як `\\d+`: `pagestore.store._KEY_RE` і `fonds.registry._KEY_RE`.
Спільна цеглинка `FOND_TOKEN` (`library.py`) фонд із літерним префіксом
(«Р-…», радянські фонди, окрема нумерація) розуміла вже давно — той самий клас
розбіжності, що й issue #6 про адресу справи, лише в іншому місці коду. Хто
копіює ключ із `cases.list` для такого фонду замість того, щоб набирати шифру
вручну, впирався у відмову на рівному місці.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka.pagestore import store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "PAGES_ROOT", tmp_path / "data" / "pages")
    monkeypatch.setattr(S, "load_library", lambda: [
        {"key": "DAHMO/R-100/7", "repo": "DAHMO", "fond": "R-100", "spr": "7",
         "shifra": "ДАХмО Р-100-1-7"},
        {"key": "DAHMO/315/8433", "repo": "DAHMO", "fond": "315", "spr": "8433",
         "shifra": "ДАХмО 315-1-8433"},
        {"key": "DAVIO/R-6129-24/5", "repo": "DAVIO", "fond": "R-6129",
         "opys": "24", "spr": "5", "shifra": "ДАВіО Р-6129-24-5"},
    ])
    for repo in ("DAHMO", "DAVIO"):
        (tmp_path / "data" / "pages" / repo).mkdir(parents=True)
    return S


def test_pagestore_accepts_the_key_it_prints_for_a_lettered_fond(store: Any) -> None:
    """Трисегментний ключ без опису, літерний фонд — саме та відмова з issue #21."""
    ref = store.resolve_case("DAHMO/R-100/7")
    assert (ref.repo, ref.fond, ref.spr) == ("DAHMO", "R-100", "7")
    assert ref.key == "DAHMO/R-100/7"


def test_pagestore_numeric_fond_key_is_unaffected(store: Any) -> None:
    """Регресія: числовий фонд без опису мав і має працювати далі."""
    ref = store.resolve_case("DAHMO/315/8433")
    assert (ref.repo, ref.fond, ref.spr) == ("DAHMO", "315", "8433")


def test_split_fond_opys_handles_letter_and_digit_fonds() -> None:
    """Одиничні перевірки розбору фонду й опису в одному сегменті ключа."""
    from nyshporka.library import split_fond_opys

    assert split_fond_opys("315") == ("315", None)
    assert split_fond_opys("211-3") == ("211", "3")           # старий випадок
    assert split_fond_opys("R-100") == ("R-100", None)         # issue #21
    assert split_fond_opys("R-6129-24") == ("R-6129", "24")    # issue #6 форма


def test_split_fond_opys_is_case_insensitive() -> None:
    """З-2 (ворожа рецензія issue #21): мала літера префікса не повинна
    провалюватись у запасний наївний поділ і тихо різати фонд навпіл —
    `partition("-")` на `r-100` віддав би `('r', '100')`, а не сам фонд."""
    from nyshporka.library import split_fond_opys

    f, opys = split_fond_opys("r-100")
    assert (f.upper(), opys) == ("R-100", None)
    f, opys = split_fond_opys("r-6129-24")
    assert (f.upper(), opys) == ("R-6129", "24")


def test_pagestore_accepts_lowercase_key_for_lettered_fond(store: Any) -> None:
    """З-2: `dahmo/r-100/7` — та сама справа, набрана з малої літери. Пакет уже
    приймає малу літеру в шифрі (`ДАХмО р-100-1-7`) і в адресі справи; ключ не
    повинен лишатись єдиним місцем, де мала літера відмовляє."""
    ref = store.resolve_case("dahmo/r-100/7")
    assert (ref.repo, ref.fond, ref.spr) == ("DAHMO", "R-100", "7")


def test_fonds_registry_accepts_lowercase_key_for_lettered_fond() -> None:
    """З-2: те саме для другого каналу — `fonds.registry.parse_key`."""
    from nyshporka.fonds import registry as FR

    assert FR.parse_key("dahmo/r-100/7") == FR.parse_key("DAHMO/R-100/7")


def test_pagestore_lettered_fond_with_inline_opys_still_resolves(store: Any) -> None:
    """🔴 `DAVIO/R-6129-24/5` — фонд ІЗ описом, вписаний в один сегмент ключа.

    Ця форма приймалась і до issue #21, тільки іншим каналом (`_ADDR_RE`, у
    ланцюжку `resolve_case` — після ключа, issue #6). Виправлення `_KEY_RE`
    додає лише БЕЗопис-овий випадок і не забирає цю форму в сусіднього каналу:
    межу між «R-6129» (фонд) і «24» (опис) в ОДНОМУ сегменті `_KEY_RE`
    однозначно провести не може (лишається два дефіси на розбір), тож рядок і
    далі йде туди, де вже працює.
    """
    ref = store.resolve_case("DAVIO/R-6129-24/5")
    assert (ref.repo, ref.fond, ref.opys, ref.spr) == ("DAVIO", "R-6129", "24", "5")
    assert ref.key == "DAVIO/R-6129-24/5"


def test_fonds_registry_parses_the_printed_key_of_a_lettered_fond() -> None:
    """Другий канал з issue #21 — `fonds.registry.parse_key`."""
    from nyshporka.fonds import registry as FR

    assert FR.parse_key("DAHMO/R-100/7") == ("DAHMO", "R-100", "1", "7", "")


def test_fonds_registry_numeric_fond_key_is_unaffected() -> None:
    """Регресія: обидві форми з докстрінга `parse_key` мають лишитись цілими."""
    from nyshporka.fonds import registry as FR

    assert FR.parse_key("DAHMO/230/43") == ("DAHMO", "230", "1", "43", "")
    assert FR.parse_key("ДАХмО 230-1-43") == ("DAHMO", "230", "1", "43", "")


def test_fonds_registry_lettered_fond_with_opys_shifra() -> None:
    """Людський запис («ДАВіО Р-6129-24-5») з описом — окремою групою, а не
    дефісом усередині фонду, тож жодної двозначності тут немає.

    Фонд канонізується через `_norm_fond` так само, як і код архіву (`ДАВіО`
    → `DAVIO`) — інакше той самий фонд, набраний кирилицею, ліг би в реєстр
    під іншим ключем (`Р-6129`), ніж латинська форма (`R-6129`)."""
    from nyshporka.fonds import registry as FR

    assert FR.parse_key("ДАВіО Р-6129-24-5") == ("DAVIO", "R-6129", "24", "5", "")


def test_fonds_registry_canonizes_cyrillic_fond_in_slash_key() -> None:
    """З-1 (ворожа рецензія issue #21): `FOND_TOKEN` пропускає кириличний
    префікс і в трисегментному ключі (`DAHMO/Р-100/7`), не лише в шифрі — без
    канонізації цей фонд ліг би в реєстр під іншим ключем, ніж латинська
    форма («R-100»), і рядки `R-100`/`Р-100` на екрані не відрізнити оком."""
    from nyshporka.fonds import registry as FR

    assert FR.parse_key("DAHMO/Р-100/7") == FR.parse_key("DAHMO/R-100/7")
    assert FR.parse_key("DAHMO/Р-100/7")[1] == "R-100"


# ── регресія самої латки: імпорт реєстру не вимагає простору ─────────────────
def test_fonds_registry_import_does_not_require_a_workspace(tmp_path: Path) -> None:
    """🔴🔴 CI «ставиться з нуля» падав рівно тут — цією самою латкою (issue #21).

    `library.py` на рівні модуля виконує `_WS = workspace()`: сам імпорт
    вимагає наявного робочого простору. Латка вище (`FOND_TOKEN` у `_KEY_RE`)
    змусила `fonds/registry.py` імпортувати `FOND_TOKEN` з `library` НА РІВНІ
    СВОГО модуля — і `nysh version` став падати `WorkspaceError` одразу після
    встановлення, ще до першої команди, на будь-якій машині без простору. До
    латки `registry.py` брав усе з `library` лише лениво, всередині функцій
    (`LIBRARY_PATH`, `load_library()` нижче в цьому файлі) — саме тому цей клас
    вади був новим, а не давнім.

    Лагодження: `FOND_TOKEN` (потрібен на рівні модуля — він живе всередині
    `re.compile`) тепер береться з `nyshporka.shifra_tokens`, модуля без
    жодних побічних дій; `_norm_fond` (потрібен лише в `parse_key()`)
    лишається лінивим імпортом усередині функції.

    ⚠ Приймач — окремий процес (`sys.executable -c …`), а не прямий `import`
    тут-таки: до першої фікстури `nyshporka.library`/`nyshporka.fonds.registry`
    уже сидять у `sys.modules` спільного процесу тестів (`conftest.py`
    навмисно піднімає простір ДО збирання, щоб імпорт домінних модулів не
    падав під час нього), тож другий `import` того самого модуля просто
    поверне кеш і не перевірить нічого. Середовище процесу очищене від сліду
    цієї машини — жодної змінної простору, домівка й стан застосунку («останній
    відкритий простір») ведуть у порожню теку, — інакше саме та вада, яку тут
    ловимо (справжній простір розробника маскує помилку), знову замастила б
    приймач: без цього тест зеленів би на машині автора й падав би лише в CI.
    """
    import os
    import subprocess
    import sys

    from nyshporka.core.workspace import ENV_LEGACY_WORKSPACE, ENV_WORKSPACE

    fake_home = tmp_path / "порожня-домівка"
    fake_home.mkdir()
    cwd = tmp_path / "деінде"
    cwd.mkdir()

    env = dict(os.environ)
    for name in (ENV_WORKSPACE, ENV_LEGACY_WORKSPACE,
                 "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        env.pop(name, None)
    # 🔴 Домівка й похідні від неї — на ВСІХ трьох платформах CI (Linux/macOS
    # шукають `~/Нишпорка` і читають стан із `$HOME`-похідної теки; Windows —
    # з `APPDATA`/`LOCALAPPDATA`). Без цього тест бачив би справжню домівку
    # того, хто його запускає, а не голу машину, яку відтворює CI.
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[name] = str(fake_home)

    proc = subprocess.run(
        [sys.executable, "-c",
         "import nyshporka.fonds.registry; import nyshporka.cli; print('OK')"],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and "OK" in proc.stdout, (
        "імпорт `nyshporka.fonds.registry`/`nyshporka.cli` зажадав робочого "
        f"простору там, де його ще нема:\n{proc.stdout}\n{proc.stderr}")
    assert "WorkspaceError" not in proc.stderr, proc.stderr
