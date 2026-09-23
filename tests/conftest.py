"""Спільна ізоляція тестів від машини, на якій вони йдуть.

🔴 Два різні протікання, і обидва мовчазні.

**Змінні середовища.** `NYSHPORKA_WORKSPACE` виставляє в себе кожен, хто
користується застосунком, — тобто і розробник. Тест, який її бачить, перевіряє
не програму, а машину: на CI зелений, у автора червоний (або навпаки), і жоден
із двох результатів нічого не доводить.

**Файл «останній використаний простір».** Він лежить поза простором (у профілі
ОС), бо мусить пережити те, що простору ще не знайдено. Наслідок: щойно
`wizard.create()` починає його писати, кожен тест, який створює простір,
залишає слід у профілі розробника й CI-раннера — і наступні тести його
знаходять. Порядок тестів стає значущим, а `tmp_path` перестає бути межею.

⚠ `W.reset()` тут не робиться навмисно. Кілька файлів тримають власні фікстури
з `W.use(...)` на `scope="module"` (`test_sources_archium`, `test_archives_pack`,
`test_progress_mirror`, `test_htr_manifest`) плюс свої autouse
(`test_walk_parity`, `test_register_and_notes`). Функційний `reset()` у teardown
зносив би override, поставлений ширшою фікстурою, — тобто ця «прибиральниця»
ламала б рівно те, що мала берегти. Скидання лишається там, де воно вже є.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import typer.testing as typer_testing

from nyshporka.core import workspace as W
from nyshporka.skills import ENV_NO_SYNC as SKILL_SYNC_OFF

# 🔴🔴 Системне вікно вибору теки вимикається на рівні модуля, а не у фікстурі.
# Фікстура діє лише в межах тесту, а вікно встигає відкритись і поза ними: під
# час збирання, у підпроцесі, у чужому потоці. Наслідок бачить людина, а не
# прогін, — діалог посеред екрана, який чекає на клік і якого ніхто не просив.
# Виявлено дослідником, який закривав їх один за одним, поки тести йшли.
os.environ["NYSHPORKA_NO_NATIVE_PICKER"] = "1"

# 🔴🔴 Так само на рівні модуля: синхронізація скілів пише в ТЕКУ АГЕНТА
# (`~/.claude/skills`), а вона в тестах справжня — `tmp_path` її не накриває.
# Без цього рядка прогін тестів переписував би скіли розробника його ж
# складанням, і помітив би він це не тут, а в наступній сесії з агентом.
os.environ[SKILL_SYNC_OFF] = "1"

# 🔴🔴 Простір оголошується НА РІВНІ МОДУЛЯ, і це третє протікання — найгірше з
# трьох, бо його не видно на машині розробника взагалі.
#
# Доменні модулі (`library`, `pagestore`, `cases.db`) беруть шляхи в мить
# імпорту, а pytest імпортує ВСІ тестові файли на збиранні — тобто ще до першої
# фікстури. Наслідки розходяться в два боки, і обидва мовчазні:
#
#   • там, де простір Є (машина розробника), модулі замерзають на ньому, і тест
#     із тимчасовою текою бачить СПРАВЖНЮ бібліотеку — 54 справи замість однієї
#     з фікстури, тобто зеленіє від чужих даних;
#   • там, де простору НЕМА (CI, свіжий клон), збирання просто падає
#     `WorkspaceError` — файл не запускається жодним тестом.
#
# Перше спіймано на `test_case_roots`, друге — на CI 2026-08-26, де через це не
# зібрались два файли цілком. `conftest` імпортується ПЕРЕД тестовими модулями,
# тож саме тут — єдине місце, де оголошення ще встигає подіяти; сама
# `workspace.use()` цього й вимагає: «викликати до імпорту доменних модулів».
#
# ⚠ Тека одна на прогін і навмисно порожня: вона не для роботи тестів (кожен
# бере свій `tmp_path`), а лише щоб заморожені константи вказували в НІКУДИ, а
# не в чиєсь дослідження.
_MARKER_BODY = '[workspace]\nschema = 1\nname = "збирання"\n'
_BOOT = Path(tempfile.mkdtemp(prefix="nysh-boot-"))
(_BOOT / W.MARKER).write_text(_MARKER_BODY, encoding="utf-8")
W.use(W.Workspace(root=_BOOT, name="збирання", origin="test"))

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


def _app_shape(app) -> tuple:
    """Відбиток складу Typer-застосунку: кожна команда, група й колбек."""
    cb = app.registered_callback
    return (
        id(cb.callback) if cb else None,
        tuple((id(c), id(c.callback)) for c in app.registered_commands),
        tuple((id(g), g.name, _app_shape(g.typer_instance))
              for g in app.registered_groups if g.typer_instance is not None),
    )


_BUILT: dict[int, tuple] = {}
_build_command = typer_testing._get_command


def _get_command_once(app):
    """`CliRunner.invoke` щоразу збирав ВСЕ дерево CLI наново: ~270 команд,
    `get_type_hints` на кожну — 0.15 с на виклик, а викликів у наборі сотні.

    Збірка кешується за застосунком і його складом: тест, що додав чи
    підмінив команду, отримує свіжу збірку. Сам застосунок тримається в кеші
    — інакше `id` після збирання сміття міг би дістатися іншому об'єкту.
    """
    shape = _app_shape(app)
    hit = _BUILT.get(id(app))
    if hit is None or hit[0] is not app or hit[1] != shape:
        hit = (app, shape, _build_command(app))
        _BUILT[id(app)] = hit
    return hit[2]


typer_testing._get_command = _get_command_once


@pytest.fixture(scope="session")
def _state_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Підмінний файл стану — один на сесію.

    Тека створюється рівно раз: `mktemp` із незміненим іменем падає на другому
    виклику, а фікстура нижче працює на кожному тесті.
    """
    return tmp_path_factory.mktemp("nysh-state") / "state.json"


@pytest.fixture(scope="session")
def _fake_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Підмінна домівка — одна на сесію, з тієї ж причини, що й файл стану."""
    return tmp_path_factory.mktemp("nysh-home")


@pytest.fixture(autouse=True)
def _isolate_from_the_machine(monkeypatch: pytest.MonkeyPatch,
                              _state_file: Path, _fake_home: Path) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    # 🔴 Системне вікно вибору теки — заборонене в тестах, і це не косметика.
    # `test_triptych_parity` кличе кожну операцію реєстру напряму, щоб довести,
    # що жодна не падає винятком; для `pick.ask` це означає справжній діалог
    # посеред прогону — вікно, яке чекає на людину й яке доводиться закривати
    # руками. Виявлено дослідником, який закривав їх одне за одним.
    monkeypatch.setenv("NYSHPORKA_NO_NATIVE_PICKER", "1")
    # 🔴 Мережа в тестах — заборонена, і теж не з міркувань швидкості. Відколи
    # серед джерел є таке, що шукає живим запитом, кожен прогін набору стукав
    # би в чужий сервер: `catalog.search` кличе і тест конверта, і той, що
    # проходить усіма операціями реєстру підряд. Волонтерський покажчик просить
    # п'ять запитів на десять секунд і блокує без попередження — зелений набір
    # оплачувався б чужою інфраструктурою й закінчився б баном.
    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    monkeypatch.setattr(W, "_state_path", lambda: _state_file)
    # 🔴 Домівка — теж джерело простору, відколи `resolve()` вміє відступати на
    # звичне місце (`~/Нишпорка`, `~/Documents/Нишпорка`). Без підміни тести
    # діставали б справжній простір того, хто їх запустив: «немає простору»
    # мовчки переставало відтворюватись на машині розробника, а гірше — прогін
    # міг писати в чуже дослідження. Тести, яким потрібна своя домівка,
    # підмінюють `Path.home` самі; ця підміна лише прибирає машину.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: _fake_home))


@pytest.fixture(autouse=True)
def _own_derived_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Сховище сторінок і файли бібліотеки — свої в кожного тесту.

    🔴 `pagestore.store.PAGES_ROOT` і шляхи `library` заморожуються на імпорті,
    тобто на завантажувальному просторі вище, — одному на весь процес. Тест,
    що писав туди й не перенаправив шлях сам, лишав слід, а наступний бачив
    його як свій: `test_pagestore_cli` отримував «вже нотовано 3» після
    `test_text_ops`, а `test_share_accept` знаходив «свою» справу в бібліотеці,
    яку записав `test_pagestore_cli`. Послідовно це ховав порядок за абеткою;
    вилізло, щойно xdist роздав файли інакше (23.09.2026). Тест, якому потрібен
    свій шлях, і далі ставить його сам — поверх цього.
    """
    from nyshporka import library as L
    from nyshporka.pagestore import store as PS

    monkeypatch.setattr(PS, "PAGES_ROOT", tmp_path / "data" / "pages")
    derived = tmp_path / "data" / "derived"
    monkeypatch.setattr(L, "LIBRARY_PATH", derived / "case_library.json")
    monkeypatch.setattr(L, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json")
    monkeypatch.setattr(L, "SCAN_TARGETS_PATH", tmp_path / "data" / "spotter" / "scan_targets.json")
    L._describe_index.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_profile_cache():
    """Профіль дослідження — з простору цього тесту, а не з попереднього.

    `core.profile._raw()` і `active()` кешуються на процес і простору не
    знають: профіль «Ковальський», заведений одним тестом, доктор наступного
    бачив як свій. Звичний порядок це ховав (23.09.2026, спіймано xdist).
    """
    from nyshporka.core import profile

    profile.reset()
    yield
    profile.reset()


@pytest.fixture
def last_used_state(_state_file: Path) -> Path:
    """Той самий файл — для тестів, які перевіряють саме його вміст."""
    return _state_file


try:
    import xdist  # noqa: F401
except ImportError:  # xdist не стоїть — хук не оголошується, інакше pytest його відкидає
    pass
else:
    def pytest_xdist_auto_num_workers(config) -> int | None:
        """`-n auto` лише для пака: вузол чи один файл ідуть в одному процесі.

        Старт воркера — ще один інтерпретатор з імпортами (~6-8 с на Windows);
        для одного тесту це чисте очікування. `None` — хай xdist рахує ядра сам.
        """
        paths = [a for a in config.invocation_params.args if not a.startswith("-")]
        if any("::" in a for a in paths):
            return 0
        if len(paths) == 1 and paths[0].endswith(".py"):
            return 0
        return None
