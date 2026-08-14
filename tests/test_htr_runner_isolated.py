"""Раннер і патчі не мають імпортувати пакет — і це перевіряється AST.

🔴 Чому тест, а не домовленість. Раннер їде під ІНШИМ інтерпретатором —
середовищем рушіїв (`kraken==7.0.2`, Python 3.11), де `nyshporka` не
встановлено й не буде. Але імпорт пакета там впаде не одразу: усі імпорти в
раннері ліниві, всередині функцій, тож `from nyshporka.cases…` мовчки падає в
`except Exception` і гілка просто не виконується.

Саме так і сталось у дослідницькому репо: раннер роками мав виклик резолвера
шифри — і **0 із 412** мет на диску отримали `case_key`, бо імпорт падав
щоразу. Помилки в лозі не було; реєстр справ просто не міг прив'язати третину
прогонів, і це виглядало як «прогонів немає».

Тому межа тримається механічно: у цих файлах дозволені лише stdlib та ті
пакети, що стоять у середовищі рушіїв.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

HTR = Path(__file__).resolve().parent.parent / "src" / "nyshporka" / "htr"

#: Що є в середовищі рушіїв — прямо з маніфесту плюс те, що приходить із ним
#: транзитивно (kraken тягне scipy/skimage/shapely/lxml, torch — numpy).
#: Перелік вужчий за реальність навмисно: він має ловити нові залежності, а не
#: пропускати їх, бо додати рядок у `engines.yaml` — свідоме рішення.
ENGINE_ENV = {
    "numpy", "PIL", "torch", "torchvision", "kraken", "strhub", "timm",
    "nltk", "lightning", "pytorch_lightning", "rapidfuzz",
    "scipy", "skimage", "shapely", "lxml", "regex", "yaml", "click",
    "coremltools", "threadpoolctl",
}

#: Сусідні файли, що вантажаться за шляхом (той самий трюк, що й патчі).
LOCAL_MODULES = {"pysar_lines_infer", "gpu_sato", "fast_geom", "seg_ceiling"}

#: 🔴 Перелік ЯВНИЙ, а не `rglob`. У теці живуть модулі двох ярусів: ці їдуть
#: у середовище рушіїв, а `env.py`/`manifest.py` навпаки — керують ним ІЗЗОВНІ,
#: з того інтерпретатора, де пакет стоїть, і мусять його імпортувати. Автоматом
#: цю межу не вгадати, а новий файл тут — рішення, яке треба ухвалити свідомо.
GUEST_FILES = ["runner.py", "pysar_lines_infer.py",
               "patches/gpu_sato.py", "patches/fast_geom.py",
               "patches/seg_ceiling.py",
               # Верифікатори — теж гості: вони ганяють стару й нову версію
               # пліч-о-пліч на ЖИВІЙ сегментації, тобто всередині того самого
               # середовища. Доказ рівності, знятий деінде, нічого не доводить.
               "patches/gpu_sato_verify.py", "patches/fast_geom_verify.py"]

FILES = [HTR / rel for rel in GUEST_FILES]


def test_guest_list_matches_disk() -> None:
    """Перелік гостей не розходиться з диском мовчки."""
    missing = [f for f in FILES if not f.exists()]
    assert not missing, f"у переліку є файли, яких немає: {missing}"
    patches = {f"patches/{p.name}" for p in (HTR / "patches").glob("*.py")
               if p.name != "__init__.py"}
    assert patches <= set(GUEST_FILES), (
        f"патчі поза переліком: {sorted(patches - set(GUEST_FILES))} — "
        f"вони вантажаться в середовище рушіїв і теж не мають знати пакета")


def _roots(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # відносний імпорт (`from . import x`) — це і є імпорт пакета
            if node.level:
                out.add(".")
            elif node.module:
                out.add(node.module.split(".")[0])
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(HTR)))
def test_no_package_imports(path: Path) -> None:
    if path.name == "__init__.py":
        return
    roots = _roots(ast.parse(path.read_text(encoding="utf-8")))
    allowed = set(sys.stdlib_module_names) | ENGINE_ENV | LOCAL_MODULES
    forbidden = sorted(roots - allowed)
    assert not forbidden, (
        f"{path.name} імпортує {forbidden}, чого в середовищі рушіїв немає. "
        f"Імпорт там впаде мовчки (усі імпорти ліниві), і гілка просто не "
        f"виконається — саме так `case_key` не потрапив у жодну з 412 мет.")


def test_no_paths_derived_from_the_code_tree(tmp_path: Path) -> None:
    """Жоден шлях ДАНИХ не рахується від `__file__`.

    🔴 Це та вада, що падає не помилкою, а старим шляхом. Доки раннер лежав у
    `scripts/` дослідницького репо, «два рівні вгору від себе» випадково
    збігалося з коренем даних — і формула прожила роки. У встановленому пакеті
    та сама формула кладе кеш сегментації в дерево КОДУ: прогін іде, помилки
    немає, просто влучань у кеш завжди 0%. Спіймано на живому прогоні:
    `…/src/nyshporka/data/derived/htr_seg/`.
    """
    import importlib.util

    src = (HTR / "runner.py").read_text(encoding="utf-8")
    assert "seg_cache_dir_for(case_dir, Path(__file__)" not in src

    spec = importlib.util.spec_from_file_location("_runner_ws", HTR / "runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        ws = tmp_path / "простір"
        (ws / "reports" / "htr").mkdir(parents=True)
        (ws / mod.WORKSPACE_MARKER).write_text("[workspace]\n", encoding="utf-8")
        out = ws / "reports" / "htr" / "прогін"
        assert mod.workspace_root(out) == ws.resolve()

        # Вихід у чужому місці (стейджинг, орендований бокс) — простір знаходить
        # ДРУГА підказка, тека справи. Саме так ходять хмарні прогони.
        far = tmp_path / "деінде" / "out"
        far.mkdir(parents=True)
        assert mod.workspace_root(far, ws / "data" / "raw" / "справа") == ws.resolve()

        # Маркера немає ніде — фолбек явний, і НЕ в дерево коду.
        got = mod.workspace_root(far)
        assert got == far.parent.resolve()
        assert HTR.parent not in got.parents and got != HTR.parent
    finally:
        sys.modules.pop(spec.name, None)


def test_normalizer_survives_in_engine_env() -> None:
    """Нормалізатор вантажиться в середовище рушіїв ЗА ШЛЯХОМ — і має там жити.

    Раннер не копіює нормалізацію до себе свідомо: це єдине місце, де визначено,
    що дореформене, сучасне й латинізоване написання одного прізвища — те саме
    слово. Дві копії розійшлися б, і пошук почав би бачити не те, що бачив
    декод. Ціна такої прив'язки — модуль мусить лишатись імпортовним ТАМ, а
    середовище рушіїв знає лише те, що перелічено в `engines.yaml`.

    🔴 Впаде це мовчки: імпорт у раннері лінивий, тож рятувальний прохід просто
    нічого не відбере — і виглядатиме як «нема кого рятувати».
    """
    path = HTR.parent / "utils" / "translit.py"
    roots = _roots(ast.parse(path.read_text(encoding="utf-8")))
    allowed = set(sys.stdlib_module_names) | ENGINE_ENV
    forbidden = sorted(roots - allowed)
    assert not forbidden, (
        f"translit.py імпортує {forbidden} — цього немає в середовищі рушіїв. "
        f"Або додати в `engines.yaml`, або не вживати в нормалізації.")


def test_runner_is_runnable_as_a_file() -> None:
    """Наглядач перезапускає САМ ФАЙЛ, а не `-m` пакета.

    Якби він робив `-m nyshporka.htr.runner`, перезапуск падав би там, де
    найпотрібніший: у середовищі рушіїв пакета немає.
    """
    src = (HTR / "runner.py").read_text(encoding="utf-8")
    assert "str(Path(__file__).resolve()), *child_argv" in src
    assert "-m" not in src.split("def supervise")[1].split("def ")[0]


def test_rescue_targets_are_not_hardcoded() -> None:
    """У раннері не лишилось цілей пошуку конкретного роду.

    Прізвище в коді інструмента означає, що для чужого дослідника рятувальний
    прохід відбирав би рядки, схожі на ЧУЖЕ прізвище — тобто гірше за
    відсутність рятунку: витрачений час і хибна впевненість.
    """
    src = (HTR / "runner.py").read_text(encoding="utf-8")
    for token in ("RESCUE_GIVEN", "RESCUE_PATR", "clan_anchors", "clan_review"):
        assert token not in src, f"{token} лишився в раннері"
