"""🖋 Маніфест рушіїв, середовище й ізоляція від пакета.

Головне тут — не «читається YAML», а три речі, кожна з яких коштувала часу:
рушій має відповідати письму, а не лише розширенню; середовище має ставити те,
без чого рушій не запуститься; і код, який їде під чужим інтерпретатором, не
сміє імпортувати пакет.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from nyshporka.htr import env
from nyshporka.htr import manifest as M

PATCHES_DIR = Path(env.__file__).resolve().parent / "patches"


@pytest.fixture(scope="module")
def man() -> M.Manifest:
    return M.load()


# ── маніфест ─────────────────────────────────────────────────────────────────
def test_three_engines_with_distinct_roles(man):
    ids = {e.id for e in man.engines}
    assert ids == {"skryba", "pysar", "diak"}
    kinds = {e.id: e.kind for e in man.engines}
    scripts = {e.id: e.script for e in man.engines}
    assert kinds == {"skryba": "kraken", "pysar": "parseq", "diak": "kraken"}
    assert scripts == {"skryba": "latin", "pysar": "cyrillic", "diak": "cyrillic"}


def test_same_suffix_can_mean_two_scripts(man):
    """🔴 `.mlmodel` буває латинкою і кирилицею.

    Тому вибір рушія за самим лише розширенням поставив би на латинську справу
    кириличну модель. Помилка не падає й не просаджує впевненість — текст
    виходить сміттям, схожим на погані скани.
    """
    by_suffix = [e for e in man.engines if e.model_glob.endswith(".mlmodel")]
    assert {e.script for e in by_suffix} == {"latin", "cyrillic"}


@pytest.mark.parametrize("filename, engine_id", [
    ("skryba_f792_v6.mlmodel", "skryba"),
    ("pysar_cyr_v17.pt", "pysar"),
    ("diak_cyr_v4.mlmodel", "diak"),
])
def test_model_name_resolves_to_engine(man, filename, engine_id):
    e = man.engine_for_model(filename)
    assert e is not None and e.id == engine_id


def test_unknown_model_name_is_silent_not_guessed(man):
    """Невідоме ім'я краще лишити без рушія, ніж вгадати письмо."""
    assert man.engine_for_model("something_else.mlmodel") is None
    # але розширення саме по собі рушій називає — це інше питання
    assert man.kind_for_suffix(".mlmodel") == "kraken"
    assert man.kind_for_suffix(".pt") == "parseq"
    assert man.kind_for_suffix(".bin") is None


def test_parseq_dependencies_are_declared(man):
    """🔴 Саме тут була діра: сетап ставив kraken і torch, але не залежності
    PARSeq — і на чистій машині головний кириличний рушій не запускався."""
    specs = " ".join(man.pip_specs())
    for need in ("timm", "nltk", "pytorch-lightning", "parseq"):
        assert need in specs, f"без {need} Писар не завантажиться"


def test_kraken_is_pinned_exactly(man):
    """Пін критичний: патчі підмінюють приватні функції саме цієї версії."""
    pins = [s for s in man.packages if s.startswith("kraken")]
    assert pins == ["kraken==7.0.2"]


def test_every_patch_has_a_verifier(man):
    """Патч чужої бібліотеки без верифікатора — це надія, а не інженерія."""
    assert man.patches
    for p in man.patches:
        assert p.verify, f"{p.id}: немає верифікатора"
        assert p.tested_on, f"{p.id}: не сказано, на якій версії звірено"
        mod = PATCHES_DIR / f"{p.module.rsplit('.', 1)[-1]}.py"
        ver = PATCHES_DIR / f"{p.verify.rsplit('.', 1)[-1]}.py"
        assert mod.is_file(), f"немає модуля патча: {mod}"
        assert ver.is_file(), f"немає верифікатора: {ver}"


# ── вибір колеса torch ───────────────────────────────────────────────────────
@pytest.mark.parametrize("cap, tag", [
    ("7.5", "cu126"),   # GTX 16xx / RTX 20xx
    ("8.6", "cu126"),   # RTX 30xx
    ("8.9", "cu126"),   # RTX 40xx
    ("9.0", "cu128"),
    ("12.0", "cu128"),  # RTX 50xx
])
def test_cuda_tag_follows_the_card(man, cap, tag):
    assert man.cuda_tag(cap) == tag


@pytest.mark.parametrize("cap", ["", "6.1", "99.9", None, "abc"])
def test_unknown_card_stays_on_cpu(man, cap):
    """🔴 Карта поза межами → лишаємось на CPU, а не ставимо навмання.

    Повільно, але робочо. Неправильне колесо не запускається взагалі, і
    користувач бачить це вже після півгодини установки.
    """
    assert man.cuda_tag(cap) is None


def test_cuda_index_is_built_from_the_tag(man):
    assert man.cuda_index_url("cu126").endswith("/cu126")


@pytest.mark.parametrize("cap, driver, expect", [
    ("8.6", "581.15", ("cu126", "ok")),        # RTX 3050 з репорту issue #7
    ("8.6", "", ("cu126", "ok")),              # драйвер невідомий — не привід відмовляти
    ("", "581.15", (None, "no_capability")),
    ("6.1", "581.15", (None, "out_of_range")),
    ("8.6", "460.89", (None, "driver_old:527.41")),
])
def test_cuda_pick_says_not_only_what_but_why(man, cap, driver, expect):
    """🔴 Причина потрібна не менше за тег.

    Одне «не вийшло» на три стани й довелось розплутувати в issue #7: людина з
    робочою RTX 3050 читала «карта поза відомими межами» там, де насправді її
    просто не спитали. Далі за цією причиною будується текст поради, а вони
    різні: оновити драйвер, поставити колесо вручну, лишитись на CPU.
    """
    assert man.cuda_pick(cap, driver) == expect


def test_driver_is_compared_by_parts_not_as_a_number(man):
    """🔴 Версія драйвера — не число: на Linux вона з ТРЬОХ частин.

    `float("550.54.15")` кидає помилку, тобто порівняння числом відсіяло б
    кожну Linux-машину як «драйвер невідомий» — рівно там, де він новіший за
    потрібний.
    """
    assert man.cuda_pick("8.6", "550.54.15")[0] == "cu126"
    assert man.cuda_pick("8.6", "470.223.02")[0] is None


# ── ізоляція від пакета ──────────────────────────────────────────────────────
def _toplevel_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


@pytest.mark.parametrize("name", sorted(
    p.name for p in PATCHES_DIR.glob("*.py") if p.name != "__init__.py"))
def test_patches_do_not_import_the_package(name):
    """🔴 Патчі виконує інший інтерпретатор — той, де стоїть kraken.

    Якби вони імпортували `nyshporka`, у середовищі рушіїв довелося б тримати
    всі залежності застосунку. Умова тримається тестом, а не домовленістю:
    один випадковий `from nyshporka...` зламав би прогін у користувача, а не тут.
    """
    assert "nyshporka" not in _toplevel_imports(PATCHES_DIR / name)


def test_patches_readme_travelled_with_them():
    """Три пастки кожного патча описані поруч із кодом, а не в чужому репо."""
    readme = PATCHES_DIR / "README.md"
    assert readme.is_file()
    assert "7.0.2" in readme.read_text(encoding="utf-8")


# ── контракт середовища ──────────────────────────────────────────────────────
def test_venv_paths_are_platform_correct(tmp_path):
    """Було зашито `Scripts/python.exe` — на Linux і macOS сетап не працював."""
    py = env.venv_python(tmp_path)
    assert py.parent.name == ("Scripts" if os.name == "nt" else "bin")
    assert py.parent.parent == tmp_path


def test_missing_venv_is_reported_not_crashed(tmp_path):
    rep = env.inspect(tmp_path / "nema")
    assert not rep.ok and rep.problems and "немає інтерпретатора" in rep.problems[0]


def test_inspector_names_the_missing_engine_dependency(tmp_path, monkeypatch):
    """🔴 Приймач головного виправлення цього кроку.

    Попередній сетап ставив kraken і torch, але не залежності PARSeq — і на
    чистій машині Скриба з Дяком працювали, а Писар не запускався. Помітити це
    можна було лише на реальному прогоні, бо ніщо не питало «а чи все на місці».

    Тут середовище підроблене: інтерпретатор існує, `kraken` є, `strhub` немає.
    Інспектор мусить назвати саме те, чого бракує, — не «щось не так».
    """
    py = env.venv_python(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")

    def fake_probe(_py, code, timeout=120):
        if "version('kraken')" in code:
            return "7.0.2"
        if "import strhub" in code:
            return None                    # саме та діра
        if code.startswith("import importlib.metadata"):
            return "1.0"
        if "cuda.is_available" in code:
            return "False"
        return ""

    monkeypatch.setattr(env, "_probe", fake_probe)
    rep = env.inspect(tmp_path)
    assert not rep.ok
    assert "strhub" in rep.missing, rep.missing
    assert rep.kraken == "7.0.2", "решта середовища мала лишитись справною"


def test_inspector_flags_wrong_kraken_version_as_a_silent_risk(tmp_path, monkeypatch):
    """Невідповідність версії kraken — не «попередження», а тиха зміна тексту."""
    py = env.venv_python(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(env, "_probe", lambda *a, **k: "7.1.0")
    rep = env.inspect(tmp_path)
    assert not rep.ok
    assert any("тихою" in p for p in rep.problems), rep.problems


def test_contract_roundtrip_and_schema_guard(tmp_path):
    """🔴 Контракт старої схеми читається як відсутній.

    Мовчки працювати за версією, де поля могли змінити зміст, гірше, ніж чесно
    сказати «перестворіть середовище».
    """
    path = tmp_path / env.ENV_FILENAME
    env.write_contract(path, tmp_path / "venv")
    data = env.read_contract(path)
    assert data and data["schema"] == env.ENV_SCHEMA
    assert [e["id"] for e in data["engines"]] == ["skryba", "pysar", "diak"]

    import json
    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["schema"] = env.ENV_SCHEMA - 1
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert env.read_contract(path) is None


def test_broken_contract_reads_as_absent(tmp_path):
    path = tmp_path / env.ENV_FILENAME
    path.write_text("{не json", encoding="utf-8")
    assert env.read_contract(path) is None


def test_setup_names_the_missing_tool_instead_of_a_traceback(tmp_path, monkeypatch):
    """🔴 `uv` і `git` — не залежності пакета, тож у того, хто ставив pip-ом, їх
    може не бути зовсім, і саме він найімовірніше запустить `nysh htr install`.

    Досі це давало `FileNotFoundError` із надр `subprocess`, текстом ОС мовою
    системи і без назви інструмента — тобто трасу стека замість одного рядка.
    """
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(env.ToolMissing) as exc:
        env.setup(tmp_path / "venv")
    assert "uv" in str(exc.value)
    # Не лише діагноз, а й ліки: рядок мусить казати, як це полагодити.
    assert "astral.sh" in str(exc.value)

    # git перевіряється теж — PARSeq ставиться з репозиторію, не з PyPI.
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "git" else "/usr/bin/uv")
    with pytest.raises(env.ToolMissing) as exc:
        env.setup(tmp_path / "venv")
    assert "git" in str(exc.value) and "strhub" in str(exc.value)


# ── що саме доїжджає в pip ───────────────────────────────────────────────────
def test_the_package_name_is_cut_by_one_function_only():
    """🔴 Вираз, що ріже ім'я зі специфікації, жив копією у двох місцях.

    І копії розійшлись: `inspect` різала за `==`/`>=`, а `setup` не різала
    взагалі — шукала ім'я підрядком. Дві відповіді на одне питання, і саме на
    їхній розбіжності PARSeq тихо не ставився.
    """
    assert M.dist_name("kraken==7.0.2") == "kraken"
    assert M.dist_name("pytorch-lightning>=2.0") == "pytorch-lightning"
    assert M.dist_name("foo[extra]>=1") == "foo", "екстри старий вираз не знав"
    assert M.dist_name("bar~=1.2") == "bar", "і `~=` не знав теж"
    # 🔴 Головне: у формі PEP 508 ім'я стоїть ЛІВОРУЧ від «@», і різати спершу
    # за версією означало б віддати цілий URL замість імені.
    assert M.dist_name("strhub @ git+https://github.com/baudm/parseq.git") == "strhub"


def test_every_missing_name_can_be_installed_by_something(man):
    """🔴 Інваріант, якого бракувало: кожне ім'я, яке пакет здатен назвати
    відсутнім, мусить мати чим ставитись.

    Саме його порушення й було вадою — `strhub` потрапляв у «бракує», але не
    мав відповідної специфікації, бо її шукали підрядком в URL. Тепер це
    перевіряється для ВСЬОГО маніфесту, тож наступна git-залежність не повторить
    історію мовчки.
    """
    plan = man.install_specs()
    for spec in man.packages:
        assert M.dist_name(spec) in plan, f"{spec}: ім'я не веде до специфікації"
    for v in man.vcs_packages:
        assert v["name"] in plan, f"{v['name']}: git-залежність без специфікації"
        assert plan[v["name"]] == v["spec"]
    # Стільки ж ключів, скільки пакетів: жоден не з'їв сусіда збігом імені.
    assert len(plan) == len(man.packages) + len(man.vcs_packages)


def _fake_env(tmp_path, monkeypatch, missing):
    """Середовище, у якому бракує рівно `missing`, а інструменти на місці."""
    import shutil

    venv = tmp_path / "venv"
    py = env.venv_python(venv)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(env, "inspect",
                        lambda *a, **k: env.EnvReport(ok=False, missing=tuple(missing)))
    calls: list[list[str]] = []
    monkeypatch.setattr(env, "_run", lambda cmd, **k: calls.append([str(c) for c in cmd]))
    return venv, calls


def test_a_git_dependency_actually_reaches_pip(tmp_path, monkeypatch):
    """🔴 Приймач самої вади (issue #1), і він мусить падати на старому коді.

    ⚠ Маніфест тут ПІДРОБЛЕНИЙ, із голим git-URL без форми PEP 508. Це навмисно:
    у справжньому маніфесті специфікацію вже переписано як `strhub @ git+…`, і
    старий підрядковий фільтр на ній випадково спрацював би — тобто тест на
    реальних даних доводив би сам себе, а не правку.

    Тут ім'я пакета (`strhub`) у специфікації не зустрічається взагалі: у ній є
    лише ім'я репозиторію (`parseq`). Рівно так воно й було, коли PARSeq не
    ставився жодного разу.
    """
    venv, calls = _fake_env(tmp_path, monkeypatch, ["strhub"])
    url = "git+https://github.com/baudm/parseq.git"
    fake = M.Manifest(python="3.11", packages=("kraken==7.0.2",),
                      vcs_packages=({"name": "strhub", "spec": url, "note": ""},),
                      torch_default=(), cuda_index="", cuda_matrix=())

    env.setup(venv, man=fake, with_cuda=False)

    pip = [c for c in calls if "install" in c]
    assert pip, "pip не викликано взагалі"
    assert url in pip[0], (
        f"git-залежність не доїхала в pip: {pip[0]}. Саме так PARSeq і зникав")
    assert "kraken==7.0.2" not in pip[0], "поставилось зайве — kraken на місці"


def test_nothing_installable_does_not_run_pip_empty_handed(tmp_path, monkeypatch):
    """⚠ `uv pip install` без жодного пакета виходить ненульовим кодом, а `_run`
    іде з `check=True`.

    Тобто порожній список ронив команду трасуванням саме там, де насправді
    просто нема чого ставити, — і це був другий наслідок тієї самої вади: коли
    бракувало ЛИШЕ `strhub`, після фільтра не лишалось нічого.
    """
    venv, calls = _fake_env(tmp_path, monkeypatch, ["чогось-такого-немає"])
    fake = M.Manifest(python="3.11", packages=("kraken==7.0.2",), vcs_packages=(),
                      torch_default=(), cuda_index="", cuda_matrix=())

    env.setup(venv, man=fake, with_cuda=False)

    assert not [c for c in calls if "install" in c], "pip покликано ні з чим"


def test_the_real_manifest_installs_parseq_by_its_own_name(tmp_path, monkeypatch):
    """Той самий шлях, але на справжньому маніфесті: те, що назвали відсутнім,
    те й ставиться."""
    venv, calls = _fake_env(tmp_path, monkeypatch, ["strhub"])

    env.setup(venv, with_cuda=False)

    pip = [c for c in calls if "install" in c]
    assert pip and any("parseq" in a for a in pip[0]), pip
