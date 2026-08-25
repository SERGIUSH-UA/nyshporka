"""Спільна ізоляція тестів від МАШИНИ, на якій вони йдуть.

🔴 Два різні протікання, і обидва мовчазні.

**Змінні середовища.** `NYSHPORKA_WORKSPACE` виставляє в себе кожен, хто
користується застосунком, — тобто і розробник. Тест, який її бачить, перевіряє
не програму, а машину: на CI зелений, у автора червоний (або навпаки), і жоден
із двох результатів нічого не доводить.

**Файл «останній використаний простір».** Він лежить ПОЗА простором (у профілі
ОС), бо мусить пережити те, що простору ще не знайдено. Наслідок: щойно
`wizard.create()` починає його писати, кожен тест, який створює простір,
залишає слід у профілі розробника й CI-раннера — і наступні тести його
знаходять. Порядок тестів стає значущим, а `tmp_path` перестає бути межею.

⚠ `W.reset()` тут НЕ робиться навмисно. Кілька файлів тримають власні фікстури
з `W.use(...)` на `scope="module"` (`test_sources_archium`, `test_archives_pack`,
`test_progress_mirror`, `test_htr_manifest`) плюс свої autouse
(`test_walk_parity`, `test_register_and_notes`). Функційний `reset()` у teardown
зносив би override, поставлений ширшою фікстурою, — тобто ця «прибиральниця»
ламала б рівно те, що мала берегти. Скидання лишається там, де воно вже є.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.core import workspace as W

#: Змінні, які застосунок читає й які тому мусять бути зняті. Легасі-аліаси
#: (`MEGEN_*`) — теж: вони діють нарівні з новими, і забути їх означало б, що
#: ізоляція працює на чистій машині й не працює на машині того, хто переїхав.
_ENV = (
    W.ENV_WORKSPACE, W.ENV_LEGACY_WORKSPACE,
    W.ENV_CASE_ROOTS, W.ENV_LEGACY_CASE_ROOTS,
    "NYSHPORKA_HTR_VENV", "NYSHPORKA_CATALOG",
    "NYSHPORKA_ARCHIVES_PACK", "NYSHPORKA_PROXY_URL", "MEGEN_PROXY_URL",
    "NYSHPORKA_XRATE_DIR", "MEGEN_XRATE_DIR",
)


@pytest.fixture(scope="session")
def _state_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Підмінний файл стану — ОДИН на сесію.

    Тека створюється рівно раз: `mktemp` із незміненим іменем падає на другому
    виклику, а фікстура нижче працює на кожному тесті.
    """
    return tmp_path_factory.mktemp("nysh-state") / "state.json"


@pytest.fixture(scope="session")
def _fake_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Підмінна домівка — ОДНА на сесію, з тієї ж причини, що й файл стану."""
    return tmp_path_factory.mktemp("nysh-home")


@pytest.fixture(autouse=True)
def _isolate_from_the_machine(monkeypatch: pytest.MonkeyPatch,
                              _state_file: Path, _fake_home: Path) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(W, "_state_path", lambda: _state_file)
    # 🔴 Домівка — теж джерело простору, відколи `resolve()` вміє відступати на
    # звичне місце (`~/Нишпорка`, `~/Documents/Нишпорка`). Без підміни тести
    # діставали б СПРАВЖНІЙ простір того, хто їх запустив: «немає простору»
    # мовчки переставало відтворюватись на машині розробника, а гірше — прогін
    # міг писати в чуже дослідження. Тести, яким потрібна своя домівка,
    # підмінюють `Path.home` самі; ця підміна лише прибирає машину.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: _fake_home))


@pytest.fixture
def last_used_state(_state_file: Path) -> Path:
    """Той самий файл — для тестів, які перевіряють САМЕ його вміст."""
    return _state_file
