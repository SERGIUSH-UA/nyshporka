"""🕳 Обіцянка без входу: клас вад, який знаходився лише руками.

Усі три перші випадки були однакові й однаково мовчазні:

* повідомлення радило `nysh cases build`, а такої команди не існувало;
* сховище прочитаного вміло читатись, але писати в нього не було чим;
* довідка про фонд попереджала «у цьому фонді ОПИС входить у ключ» — і не була
  доступна нізвідки, хоч саме цей недогляд один раз уже злив дві різні книги
  в одну справу.

Жодна з них не падає й не помітна в дифі: код є, тести на сам код зелені, а
дійти до нього не можна. Тому перевірка — не про поведінку окремої функції, а
про **зв'язність**: кожна дія має бодай один вхід, і кожна порада веде туди,
де щось є.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka"
STATIC = SRC / "daemon" / "static"
README = Path(__file__).resolve().parents[1] / "README.md"


# ── що є насправді ───────────────────────────────────────────────────────────
def _cli_commands() -> set[str]:
    """Повні імена команд: «cases build», «pages note», «doctor»."""
    from nyshporka.cli import app

    out: set[str] = set()

    def walk(t, prefix: str = "") -> None:
        for c in t.registered_commands:
            name = c.name or c.callback.__name__.replace("_", "-")
            out.add(f"{prefix} {name}".strip())
        for g in t.registered_groups:
            walk(g.typer_instance, f"{prefix} {g.name or ''}".strip())

    walk(app)
    return out


def _ops() -> dict[str, object]:
    from nyshporka import ops as O

    return {o.name: o for o in O.all_ops()}


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _called_from_js() -> set[str]:
    return set(re.findall(r"callOp\(\s*'([^']+)'", _js()))


def _called_from_cli() -> set[str]:
    return set(re.findall(r'O\.call\(\s*"([^"]+)"',
                          (SRC / "cli.py").read_text(encoding="utf-8")))


# 🔴 Виняток дозволений лише з причиною, і причина перевіряється очима на
# рев'ю. Порожній словник тут — норма; рядок у ньому — борг.
REACHABLE_OTHERWISE = {
    # Черга живе на власних роутах (`/api/jobs`, `/api/jobs/wait`): довге
    # очікування мусить блокувати на СЕРВЕРІ, а generic-виклик операції цього
    # не вміє. Агент дістає її як `nysh_job`.
    "job.query": "браузер ходить у /api/jobs напряму, агент має tool",
}


# ── 1. до кожної дії є вхід ──────────────────────────────────────────────────
def test_every_op_has_at_least_one_entrance() -> None:
    """Операція без входу — це код, який ніхто не викличе.

    Три обличчя (агент, командний рядок, екран) не мусять покривати кожну
    операцію — але бодай одне мусить, інакше реєстр обіцяє те, чого немає.
    """
    ops = _ops()
    js, cli = _called_from_js(), _called_from_cli()
    orphans = [n for n, o in ops.items()
               if not getattr(o, "agent", False)
               and n not in js and n not in cli and n not in REACHABLE_OTHERWISE]
    assert not orphans, (
        "до цих операцій не дійти ні агентом, ні командою, ні екраном: "
        f"{sorted(orphans)}")


# ── 2. кожна порада веде кудись ──────────────────────────────────────────────
@pytest.mark.parametrize("where", ["src", "readme"])
def test_advised_commands_exist(where: str) -> None:
    """🔴 Найдешевша брехня застосунку — порада на неіснуючу команду.

    Вона з'являється природно: команду перейменували або ще не написали, а
    текст помилки лишився. Людина копіює пораду, отримує «немає такої
    команди» — і читає це як поламаний застосунок, а не як застарілий рядок.
    """
    cmds = _cli_commands()
    heads = {c.split()[0] for c in cmds}
    files = ([p for p in SRC.rglob("*.py")] + [p for p in SRC.rglob("*.js")]
             if where == "src" else [README])
    bad: list[str] = []
    for path in files:
        if "patches" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"`?nysh ([a-z][a-z-]*(?: [a-z][a-z-]*)?)", text):
            first, full = m.group(1).split()[0], m.group(1).strip()
            if full in cmds or first in heads:
                continue
            bad.append(f"{path.name}: nysh {full}")
    assert not bad, f"порада веде в нікуди: {sorted(set(bad))}"


def test_advised_flags_exist_too() -> None:
    """🔴 Команда може існувати, а прапорець у пораді — ні.

    `nysh doctor` радив `nysh models get --all`; команда була, прапорця не
    було, і перевірка самих імен команд це пропускала. Для людини різниці
    немає: скопійована порада не працює, а вона щойно поставила застосунок.

    ⚠ Backtick перед `nysh` тут НЕ вимагається, і це не дрібниця. Перша редакція
    патерну починалася з backtick'а — і пропустила `nysh doctor --gpu` у полі
    `fix` самого доктора, бо поради в `Check(...)` пишуться голим текстом (їх
    друкує rich, а не markdown). Прапорця `--gpu` не існувало ніколи, тобто
    рівно та вада, від якої стоїть цей тест, жила в його ж підопічному файлі.
    """
    import typer.main

    from nyshporka.cli import app

    flags: dict[str, set[str]] = {}

    def walk(t: object, prefix: str = "") -> None:
        for c in t.registered_commands:  # type: ignore[attr-defined]
            name = f"{prefix} {c.name or c.callback.__name__.replace('_', '-')}".strip()
            got = {o for p in typer.main.get_command(_single(c)).params
                   for o in p.opts}
            flags[name] = got | {"--help"}
        for g in t.registered_groups:  # type: ignore[attr-defined]
            walk(g.typer_instance, f"{prefix} {g.name or ''}".strip())

    def _single(cmd: object) -> object:
        one = typer.Typer()
        one.registered_commands.append(cmd)  # type: ignore[arg-type]
        return one

    walk(app)
    bad: list[str] = []
    pattern = re.compile(r"\bnysh ([a-z][a-z-]*(?: [a-z][a-z-]*)?)((?: --?[\w-]+)+)")
    files = [*SRC.rglob("*.py"), *SRC.rglob("*.js"), README]
    for path in files:
        if "patches" in path.parts:
            continue
        for m in pattern.finditer(path.read_text(encoding="utf-8", errors="replace")):
            cmd, tail = m.group(1).strip(), m.group(2)
            known = flags.get(cmd) or flags.get(cmd.split()[0])
            if known is None:
                continue
            for flag in re.findall(r"--?[\w-]+", tail):
                if flag not in known:
                    # Шлях від кореня, а не `path.name`: файлів `cli.py` у
                    # пакеті сім, і саме одне ім'я змушувало шукати вручну.
                    bad.append(f"{path.relative_to(SRC.parent)}: nysh {cmd} {flag}")
    assert not bad, f"порада з неіснуючим прапорцем: {sorted(set(bad))}"


# ── 3. кнопка щось робить ────────────────────────────────────────────────────
def test_every_button_has_a_handler() -> None:
    """Кнопка без обробника мовчить — а мовчання читається як «зламалось»."""
    js = _js()
    block = re.search(r"const ACTIONS = \{(.*?)\n\};", js, re.S)
    assert block, "реєстр дій не знайдено — перевірка втратила сенс"
    handlers = set(re.findall(r"^  '?([\w.]+)'?:", block.group(1), re.M))
    used = set(re.findall(r'data-act="([\w.]+)"', _html() + js))
    assert not (used - handlers), f"кнопка без дії: {sorted(used - handlers)}"
    assert not (handlers - used), f"дія без кнопки: {sorted(handlers - used)}"


# ── 3b. до кожного екрана веде кнопка, і кожна кнопка має секцію ─────────────
def test_every_screen_is_reachable_and_belongs_to_a_section() -> None:
    """🔴 Новий спосіб розірвати зв'язність — секції.

    Шапку тепер будує `renderNav` із `NAV_ORDER`, а показувати чи ні — вирішує
    секція екрана. Тож розрив може статись у трьох нових місцях: екран без
    кнопки, кнопка без підпису, екран без секції. Усі три однаково лишають
    людину перед дією, до якої не дійти.
    """
    from nyshporka.core import sections as S

    js = _js()
    screens = set(re.findall(r"^SCREENS\.(\w+)\s*=", js, re.M))
    order = set(re.findall(r"'(\w+)'", js.split("const NAV_ORDER")[1].split("];")[0]))
    # Підписи стоять по кілька в рядку, тож прив'язка до початку рядка тут
    # ловила б лише перший і мовчки звужувала перевірку.
    labels = set(re.findall(r"(\w+):\s*'",
                            js.split("const NAV_LABEL")[1].split("};")[0]))

    # `settings` — свідомий виняток: до нього ведуть шестерня в шапці й екран
    # вимкненої секції, а місця в основному переліку він не займає.
    assert not (order - screens), f"кнопка без екрана: {sorted(order - screens)}"
    assert not (screens - order - {"settings"}), \
        f"екран без кнопки: {sorted(screens - order - {'settings'})}"
    assert not (order - labels), f"кнопка без підпису: {sorted(order - labels)}"
    assert not (order - set(S.SCREENS)), \
        f"екран без секції: {sorted(order - set(S.SCREENS))}"


# ── 4. екран кличе те, що існує ──────────────────────────────────────────────
def test_screens_and_cli_call_existing_ops() -> None:
    """Друкарська помилка в імені операції дає 404 вже в руках користувача."""
    ops = set(_ops())
    assert not (_called_from_js() - ops), \
        f"екран кличе неіснуючу операцію: {sorted(_called_from_js() - ops)}"
    assert not (_called_from_cli() - ops), \
        f"CLI кличе неіснуючу операцію: {sorted(_called_from_cli() - ops)}"


# ── 5. екран шле поля, які схема приймає ─────────────────────────────────────
def test_screens_send_only_fields_the_schema_accepts() -> None:
    """Поле, якого схема не знає, відкидається мовчки — і форма «не діє»."""
    from nyshporka import ops as O

    bad: list[str] = []
    for m in re.finditer(r"callOp\(\s*'([^']+)',\s*\{(.*?)\}\)", _js(), re.S):
        op = O.get(m.group(1))
        if op is None or op.args is None:
            continue
        fields = set(op.args.model_fields)
        for key in re.findall(r"(?:^|[{,\s])(\w+)\s*:", m.group(2)):
            if key not in fields:
                bad.append(f"{m.group(1)}.{key}")
    assert not bad, f"екран шле поля, яких схема не має: {sorted(set(bad))}"


# ── 6. розмітка й скрипт узагалі розбираються ────────────────────────────────
@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node немає — синтаксис JS перевірити нічим")
def test_frontend_javascript_parses() -> None:
    """🔴 Синтаксична помилка в консолі не падає НІДЕ, крім браузера користувача.

    Жоден тест не виконує цей файл — його лише читають як текст. Тому зайвий
    апостроф усередині рядка (`'п'яти сховищ'` — звичайне українське слово)
    робить порожню сторінку без єдиної ознаки в тестах, лінті чи типах. Спіймано
    саме так, за годину після того, як перевірку писали.
    """
    res = subprocess.run(["node", "--check", str(STATIC / "app.js")],
                         capture_output=True, text=True)
    assert res.returncode == 0, f"app.js не розбирається:\n{res.stderr[:800]}"


# ── 7. переклад повний в обидва боки ─────────────────────────────────────────
def test_translations_cover_every_key_in_both_languages() -> None:
    """Ключ без перекладу показує сирий `case.edit` замість напису.

    Перевірка симетрична навмисне: зайвий ключ в одній мові — це або мертвий
    напис, або забутий у другій.
    """
    js = _js()
    dicts: dict[str, set[str]] = {}
    for lang in ("uk", "en"):
        m = re.search(rf"\n    {lang}: \{{(.*?)\n  \}}", js, re.S) or \
            re.search(rf"\n  {lang}: \{{(.*?)\n  \}},", js, re.S)
        assert m, f"словник «{lang}» не знайдено"
        dicts[lang] = set(re.findall(r"'([\w.]+)':", m.group(1)))
    only = dicts["uk"] ^ dicts["en"]
    assert not only, f"ключ є лише в одній мові: {sorted(only)}"
    used = set(re.findall(r"\bt\('([\w.]+)'\)", js)) | set(
        re.findall(r'data-i18n="([\w.]+)"', _html()))
    assert not (used - dicts["uk"]), f"ужито без перекладу: {sorted(used - dicts['uk'])}"


def test_the_decode_denominator_is_read_from_the_right_field() -> None:
    """🔴 Знаменник, який сам є нулем, скасовує правило, заради якого він є.

    Перелік прогонів називає число прочитаних сторінок полем `pages_done`.
    Поки пошук додавав `pages`, сума виходила ТОТОЖНО нульова: на просторі з
    506 прогонами й 320 669 сторінками відповідь звучала «не знайшлось у 506
    прогонах (0 сторінок)» — тобто «нічого не прочитано», і напрям пошуку
    закривався висновком, якого ніхто не робив.

    Перевірка тримається за ІМ'Я поля, а не за поведінку на порожньому
    просторі: там обидва варіанти дають нуль і різниці не видно.
    """
    src = (SRC / "ops_builtin.py").read_text(encoding="utf-8")
    block = re.search(r"runs = htr_store\.list_cases\(\).*?\n\s*env = ok", src, re.S)
    assert block, "гілка пошуку по декоду змінилась — перевірку треба переписати"
    assert "pages_done" in block.group(0), \
        "знаменник рахується не з того поля — див. htr_store.list_cases()"


# ── 5. схема аргументів мусить відповідати підпису функції ───────────────────
def test_declared_args_match_the_function_signature() -> None:
    """🔴 Забути `args=` у декораторі — тиха поломка, і вона вже трапилась.

    `@op(...)` дефолтом бере `NoArgs`. Функція при цьому має анотацію
    `a: BindArgs`, тіло читає `a.run` — і все виглядає правильно в трьох місцях
    із чотирьох: mypy задоволений (анотація ж є), тести зв'язності задоволені
    (вхід є), CLI будується. Ламається лише виклик, і не помилкою схеми, а
    `AttributeError: 'NoArgs' object has no attribute 'run'` — тобто причину
    доводиться здогадувати з чужого повідомлення.

    Приймач один і дешевий: те, що оголошено, мусить дорівнювати тому, що
    функція справді приймає.
    """
    import typing

    from nyshporka.core.ops import REGISTRY

    bad: list[str] = []
    for op_ in REGISTRY.all():
        hints = typing.get_type_hints(op_.fn)
        params = [p for p in hints if p != "return"]
        if not params:
            continue
        want = hints[params[0]]
        if want is not op_.args:
            bad.append(f"{op_.name}: оголошено {op_.args.__name__}, "
                       f"а функція приймає {getattr(want, '__name__', want)}")
    assert not bad, "схема аргументів розійшлася з підписом:\n  " + "\n  ".join(bad)
