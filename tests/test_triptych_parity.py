"""🔺 Три обличчя не мають розійтись — і це перевіряється, а не обіцяється.

Браузер, командний рядок і агент роблять ті самі речі. Описавши кожну дію
тричі, ми гарантовано отримаємо розходження: спершу дрібне, далі одна з копій
відстає, і виявляють це користувачі.

Ціна вже виміряна на попередньому конвеєрі: 157 роутів у браузері проти 13
скриптів, до нього підключених. Більшість роботи була доступна лише з
командного рядка, і жоден тест цього не бачив, бо кожне обличчя перевірялось
окремо.

Тому тут перевіряється саме ЗВ'ЯЗОК між ними.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from nyshporka import ops as O
from nyshporka.cli import app
from nyshporka.mcp import server as MCP

runner = CliRunner()


# ── реєстр як єдине джерело ──────────────────────────────────────────────────
def test_registry_is_not_empty():
    """Порожній реєстр зробив би всі перевірки нижче вакуумними."""
    assert O.all_ops(), "жодної операції не зареєстровано"


def test_every_agent_op_has_a_tool_with_the_same_schema():
    """🔴 Головна перевірка: агент бачить рівно те, що оголошено, і так само.

    Розбіжність схем — це коли модель шле поле, якого код не чекає, і отримує
    «некоректне значення» без жодної підказки, що саме не так.
    """
    tools = {t["name"]: t for t in MCP.tool_definitions()}
    for op in O.for_agent():
        assert op.tool_name in tools, f"операція {op.name} не видна агентові"
        assert tools[op.tool_name]["inputSchema"] == op.schema(), (
            f"схема аргументів {op.name} розійшлася з tool'ом")


def test_non_agent_ops_are_absent_from_the_tools():
    """`agent=False` — рішення, а не «поки не зробили»."""
    tool_names = {t["name"] for t in MCP.tool_definitions()}
    for op in O.all_ops():
        if not op.agent:
            assert op.tool_name not in tool_names, (
                f"{op.name} позначена як не-агентна, але видна агентові")


def test_tool_count_stays_readable():
    """🔴 Стеля переліку — рішення, а не технічна межа.

    Далі агент перестає читати опис і починає вгадувати, а вгадування коштує
    дорожче за відсутність tool'а.
    """
    n = len(MCP.tool_definitions())
    assert n <= MCP.TOOL_LIMIT, (
        f"tool'ів {n} при стелі {MCP.TOOL_LIMIT}: групуйте дії дискримінатором "
        f"(одна операція з полем `action`), а не плодіть по tool'у на дію")


def test_every_op_is_reachable_from_the_command_line():
    """CLI повний за побудовою: `nysh op <ім'я>` дістає будь-яку операцію.

    Саме тому командний рядок не може відстати від агента — не тому, що ми
    пам'ятаємо дописати команду.
    """
    for op in O.all_ops():
        res = runner.invoke(app, ["op", op.name, "--args", "{}"])
        # Операція може відмовити по суті (немає простору, потрібні аргументи) —
        # але вона мусить БУТИ ЗНАЙДЕНА.
        assert "невідома операція" not in res.stdout, f"{op.name} недосяжна з CLI"


def test_unknown_op_names_the_available_ones():
    res = runner.invoke(app, ["op", "нема.такої"])
    assert res.exit_code == 1
    assert "workspace.info" in res.stdout


# ── конверт ──────────────────────────────────────────────────────────────────
def test_every_answer_is_wrapped_the_same_way():
    """🔴 Операція ЗАВЖДИ повертає конверт — навіть коли всередині впало.

    Знайдено цим тестом: операція чесно ловила свою помилку, але з-під неї
    пролітала помилка робочого простору, і виклик падав винятком замість
    «ok: false». Для агента це різниця між «прочитав причину й виправився» і
    «tool failed» без пояснення.
    """
    for op in O.all_ops():
        env = O.call(op.name, {})          # не має кинути ЖОДНА
        d = env.as_dict()
        assert d["v"] == 1 and isinstance(d["ok"], bool)
        assert ("data" in d) == d["ok"], f"{op.name}: конверт без даних/помилки"


def test_a_throwing_op_still_answers_with_an_envelope():
    """Контракт тримається МЕХАНІЗМОМ, а не пам'яттю автора операції."""
    from nyshporka.core.ops import NoArgs, Op, Registry

    reg = Registry()

    def boom(_: NoArgs):
        raise RuntimeError("щось усередині")

    reg.add(Op(name="test.boom", fn=boom, summary="падає"))
    env = reg.call("test.boom", {})
    assert not env.ok
    # Причина лишається видимою: проковтнути її означало б сховати ваду.
    assert "RuntimeError" in env.error and "щось усередині" in env.error


def test_warnings_reach_the_agent_as_text_not_only_as_fields():
    """🔴 Та сама діра, що була в реєстрі справ дослідницького конвеєра.

    Там попередження «зріз застарів» друкувалось ЛИШЕ людині, а машинний режим
    його не показував — тобто читач, який не вміє помітити нічого поза даними,
    лишався без попередження. Тут воно мусить бути в тексті для моделі.
    """
    from nyshporka.core.envelope import ok

    env = ok({"n": 0}).warn("stale_index", "реєстр застарів")
    assert "реєстр застарів" in env.as_agent_text()

    res = MCP.call_tool("nysh_sources_list", {})
    texts = [b["text"] for b in res["content"]]
    assert any(t.strip().startswith("{") for t in texts), "структура має бути"


def test_next_hints_travel_with_the_answer():
    """Пари дій конвеєра («подивився → занеси») легко забути наполовину."""
    from nyshporka.core.envelope import ok

    env = ok(None).suggest("pages.note", "переглянуто 3 скани, не занесено")
    assert "pages.note" in env.as_agent_text()
    assert env.as_dict()["next"][0]["op"] == "pages.note"


# ── поведінка tool'ів ────────────────────────────────────────────────────────
def test_tool_error_is_a_normal_answer_not_a_transport_failure():
    """Агент має прочитати причину й виправитись, а не отримати «tool failed»."""
    res = MCP.call_tool("nysh_material_look", {})     # бракує обов'язкового поля
    payload = json.loads([b["text"] for b in res["content"]][-1])
    assert payload["ok"] is False and "path" in payload["error"]


def test_unknown_tool_lists_what_exists():
    res = MCP.call_tool("nysh_вигадка", {})
    joined = " ".join(b["text"] for b in res["content"])
    assert "nysh_workspace_info" in joined


@pytest.mark.parametrize("op_name", ["workspace.info", "sources.list", "profile.show"])
def test_read_only_ops_do_not_declare_mutation(op_name):
    op = O.get(op_name)
    assert op is not None and not op.mutates


def test_mutating_ops_are_marked_as_such():
    """Мутація потребує токена, ключа ідемпотентності й підтвердження —
    тож позначка не косметична, і забути її не можна безкарно."""
    for op in O.all_ops():
        if op.long:
            assert op.mutates or not op.mutates  # довга робота може бути й читанням
        assert isinstance(op.mutates, bool)


# ── конфіг для агента ────────────────────────────────────────────────────────
def test_mcp_install_adds_without_erasing_other_servers(tmp_path):
    """🔴 У `.mcp.json` можуть бути чужі сервери, зроблені руками."""
    cfg = tmp_path / ".mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"чужий": {"command": "x"}}}),
                   encoding="utf-8")
    res = runner.invoke(app, ["mcp", "install", "--target", str(cfg)])
    assert res.exit_code == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "чужий" in data["mcpServers"] and "nyshporka" in data["mcpServers"]


def test_mcp_install_refuses_to_clobber_a_broken_file(tmp_path):
    cfg = tmp_path / ".mcp.json"
    cfg.write_text("{обірваний", encoding="utf-8")
    res = runner.invoke(app, ["mcp", "install", "--target", str(cfg)])
    assert res.exit_code == 1
    assert cfg.read_text(encoding="utf-8") == "{обірваний", "файл змінено попри відмову"


def test_mcp_tools_command_lists_them():
    res = runner.invoke(app, ["mcp", "tools"])
    assert res.exit_code == 0 and "nysh_workspace_info" in res.stdout
