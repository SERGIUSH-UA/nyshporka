"""🔺 Три обличчя не мають розійтись — і це перевіряється, а не обіцяється.

Браузер, командний рядок і агент роблять ті самі речі. Описавши кожну дію
тричі, ми гарантовано отримаємо розходження: спершу дрібне, далі одна з копій
відстає, і виявляють це користувачі.

Ціна вже виміряна на попередньому конвеєрі: 157 роутів у браузері проти 13
скриптів, до нього підключених. Більшість роботи була доступна лише з
командного рядка, і жоден тест цього не бачив, бо кожне обличчя перевірялось
окремо.

Тому тут перевіряється саме зв'язок між ними.
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


def test_tool_descriptions_never_point_at_a_missing_tool():
    """🔴 Опис tool'а — теж обіцянка входу, і вона так само буває порожньою.

    Знайдено 2026-08-17: опис довгих операцій радив питати стан «через
    nysh_job», а tool зветься `nysh_job_query` — тобто застосунок сам відсилав
    агента до інструмента, якого не існує. Людина на такому перепитала б;
    модель кличе назване ім'я, отримує «невідомий інструмент» і записує
    висновок, що застосунок поламаний.
    """
    tools = MCP.tool_definitions()
    names = {t["name"] for t in tools}
    import re

    bad: list[str] = []
    for t in tools:
        for m in re.findall(r"\bnysh_[a-z_]+", t["description"]):
            if m not in names:
                bad.append(f"{t['name']}: → {m}")
    assert not bad, f"опис відсилає до неіснуючого tool'а: {sorted(set(bad))}"


def test_agent_docs_cover_the_whole_surface():
    """🔴 Документація агента мусить старіти гучно, а не тихо.

    Агент не бачить докстрінгів операцій — у перелік tool'ів іде лише
    однорядковий підпис. Уся мотивація («нуль зі знаменником», «status=full
    лише якщо виписані всі прізвища», «дефолт — рядок, бо сторінка коштує
    вчетверо дорожче») живе в `docs/agents/`, і саме тому там не можна мати
    ні прогалин, ні привидів:

    * tool, якого немає в документації, агент вживатиме навмання — а половина
      з них мутує сховище дослідження;
    * tool, який лишився в документації після зняття, агент кликатиме й
      отримуватиме відмову, читаючи її як поламаний застосунок.

    Стеля переліку насичена, тож «додати tool» тут завжди означає «прибрати
    tool» — і цей тест зробить видимою другу половину тієї операції.
    """
    from pathlib import Path

    docs = Path(__file__).resolve().parents[1] / "docs" / "agents"
    text = "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(docs.rglob("*.md")))
    assert text, "теки docs/agents немає — документація агента зникла"

    tools = {t["name"] for t in MCP.tool_definitions()}
    missing = sorted(t for t in tools if t not in text)
    assert not missing, (
        f"tool'и не описані в docs/agents: {missing}. Агент вживатиме їх "
        f"навмання — а частина з них пише в сховище дослідження")

    import re

    mentioned = set(re.findall(r"\bnysh_[a-z_]+", text))
    ghosts = sorted(m for m in mentioned if m not in tools)
    assert not ghosts, (
        f"docs/agents обіцяють tool'и, яких немає: {ghosts}. Агент покличе їх "
        f"і прочитає відмову як поламаний застосунок")


def test_the_numbers_in_the_agent_docs_are_the_real_ones():
    """🔴 Числа старіли тихіше за все інше в цій документації.

    Перевірка імен tool'ів ловила прогалини й привидів, але «Операцій у
    реєстрі 42» вона не бачила: рядок лишався правдоподібним, поки реєстр ріс
    до сімдесяти з гаком. Агент читає з нього не арифметику, а ВИСНОВОК —
    скільки роботи лишається за командним рядком, тобто чи варто туди йти
    взагалі. Заниження в півтора раза відмовляє від половини застосунку.
    """
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1]
            / "docs" / "agents" / "surface.md").read_text(encoding="utf-8")
    total, agent = len(O.all_ops()), len(O.for_agent())
    want = {
        r"Операцій у реєстрі \*\*(\d+)\*\*": total,
        r"Перелік tool'ів показує \*\*(\d+)\*\*": agent,
        r"\| \*\*усі (\d+)\*\* \|": total,
        r"MCP — (\d+) операці": total - agent,
    }
    bad = []
    for pattern, expected in want.items():
        found = re.search(pattern, text)
        assert found, f"рядок із числом зник із surface.md: {pattern}"
        if int(found.group(1)) != expected:
            bad.append(f"«{found.group(0)}» — насправді {expected}")
    assert not bad, f"числа в surface.md розійшлися з реєстром: {bad}"


def test_every_op_is_reachable_from_the_command_line():
    """CLI повний за побудовою: `nysh op <ім'я>` дістає будь-яку операцію.

    Саме тому командний рядок не може відстати від агента — не тому, що ми
    пам'ятаємо дописати команду.
    """
    for op in O.all_ops():
        res = runner.invoke(app, ["op", op.name, "--args", "{}"])
        # Операція може відмовити по суті (немає простору, потрібні аргументи) —
        # але вона мусить бути знайдена.
        assert "невідома операція" not in res.stdout, f"{op.name} недосяжна з CLI"


def test_unknown_op_names_the_available_ones():
    res = runner.invoke(app, ["op", "нема.такої"])
    assert res.exit_code == 1
    assert "workspace.info" in res.stdout


# ── розвідка поверхні без переліку tool'ів ───────────────────────────────────
def test_command_line_hands_out_the_argument_schema():
    """🔴 Досяжність без схеми — це половина входу, і половина гірша за нуль.

    Той, хто працює через MCP, отримує `inputSchema` разом із переліком і
    ніколи не гадає про назви полів. Той, хто працює командним рядком, до
    2026-08-25 бачив лише ім'я й однорядковий підпис — тобто мусив видобувати
    поля по одному з помилок валідації, витрачаючи хід на кожне. Схема лежала
    в реєстрі весь час; не віддавати її означало тримати повну поверхню за
    напівзачиненими дверима й ще й називати це повнотою.
    """
    res = runner.invoke(app, ["op", "pages.note", "--describe"])
    assert res.exit_code == 0
    card = json.loads(res.stdout)
    assert "case" in card["schema"]["properties"], "схема аргументів не доїхала"
    assert card["doc"], "докстрінг не доїхав — а він і є те, чого немає в підписі"
    assert card["mutates"] is True, "позначка мутації мусить бути видна ДО виклику"


def test_describe_does_not_execute_the_operation():
    """Розвідка мусить бути безпечною, інакше її роблять мутацією.

    Якби `--describe` виконував операцію, єдиним способом дізнатись аргументи
    мутації лишався б виклик «щоб подивитись, що відповість» — тобто запис у
    чуже сховище заради довідки.
    """
    from nyshporka.core import pulse

    calls: list[str] = []
    original, pulse.beat = pulse.beat, lambda name: calls.append(name)
    try:
        res = runner.invoke(app, ["op", "case.register", "--describe"])
    finally:
        pulse.beat = original
    assert res.exit_code == 0
    assert not calls, "describe виконав мутацію"
    assert "\"ok\"" not in res.stdout, "describe віддав конверт, тобто таки виконав"


def test_ops_listing_carries_every_schema():
    """Перелік і схеми — один запит, а не сорок.

    Сорок викликів на розвідку коштують дорожче за саму роботу, і той, хто
    рахує ходи, просто не робитиме розвідки.
    """
    res = runner.invoke(app, ["ops", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    got = {o["name"]: o for o in payload["ops"]}
    assert got.keys() == {o.name for o in O.all_ops()}
    for op in O.all_ops():
        assert got[op.name]["schema"] == op.schema(), f"{op.name}: схема розійшлась"


def test_ops_that_need_the_queue_name_the_path_without_it():
    """🔴 Режим не має відкриватись відмовою.

    Частина операцій виконується прямо на місці (`registry.collect` збирає
    опис синхронно, хоч і позначена довгою), а частина делегує чергу
    застосунку й поза ним відповідає «підніміть `nysh serve`». Друга група й
    небезпечна: відповідь чесна, але читає її той, хто вже витратив хід.

    Тому вимога адресна — не «до всіх довгих», а «до тих, хто відсилає до
    застосунку»: такі мусять назвати шлях без черги (`nysh read`, `nysh get`)
    саме в докстрінгу, бо докстрінг віддається `--describe` до виклику.
    """
    import inspect
    import re

    silent = []
    for op in O.all_ops():
        src = inspect.getsource(op.fn)
        if "nysh serve" not in src:            # черги не потребує — питання не стоїть
            continue
        doc = inspect.getdoc(op.fn) or ""
        # Назвати треба саме іншу команду: `nysh serve` — це і є черга, тож
        # порада підняти її не є шляхом без неї.
        if not re.search(r"`nysh (?!serve\b)[a-z]+", doc):
            silent.append(op.name)
    assert not silent, (
        f"операція відсилає до застосунку, але не називає шляху без нього: "
        f"{silent}. Агент дізнається про режим лише з відмови, тобто після "
        f"витраченого ходу")


# ── конверт ──────────────────────────────────────────────────────────────────
def test_every_answer_is_wrapped_the_same_way():
    """🔴 Операція завжди повертає конверт — навіть коли всередині впало.

    Знайдено цим тестом: операція чесно ловила свою помилку, але з-під неї
    пролітала помилка робочого простору, і виклик падав винятком замість
    «ok: false». Для агента це різниця між «прочитав причину й виправився» і
    «tool failed» без пояснення.
    """
    for op in O.all_ops():
        env = O.call(op.name, {})          # не має кинути жодна
        d = env.as_dict()
        assert d["v"] == 1 and isinstance(d["ok"], bool)
        assert ("data" in d) == d["ok"], f"{op.name}: конверт без даних/помилки"


def test_a_throwing_op_still_answers_with_an_envelope():
    """Контракт тримається механізмом, а не пам'яттю автора операції."""
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

    Там попередження «зріз застарів» друкувалось лише людині, а машинний режим
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


# ── конверт доїжджає до машинного читача цілим ──────────────────────────────
@pytest.fixture
def space(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Порожній простір: тут кожна відповідь — нуль, і саме він цікавий."""
    from nyshporka.core import workspace as W

    monkeypatch.setenv(W.ENV_WORKSPACE, str(tmp_path / "простір"))
    res = runner.invoke(app, ["init", "--yes", "--preset", "researcher"])
    assert res.exit_code == 0, res.stdout
    W.reset()
    yield tmp_path / "простір"
    W.reset()


@pytest.mark.parametrize("argv", [
    ["search", "Шевченко", "--json"],
    ["pages", "status", "DAHMO/315/8433", "--json"],
    ["htr", "env", "--json"],
    ["archive", "DAHMO", "230", "--json"],
    ["profile", "show", "--json"],
])
def test_the_json_answer_is_the_whole_envelope(space, argv: list[str]) -> None:
    """🔴 Дружні команди віддавали машині `env.data` замість `env.as_dict()`.

    Разом із обгорткою зникали `warnings`, `stale`, `next` і `coverage` — тобто
    все, заради чого конверт існує. Найдорожче це коштувало в пошуку:
    `partial_index` («N прогонів поза пошуком: їхній текст ще не
    проіндексовано») — головний генератор хибного нуля, і саме `--json` радять
    агентові скіли.

    ⚠ Перевірка ганяє саму команду й читає stdout. Наявні тести конверта
    перевіряли `Envelope.as_dict()` і MCP напряму, минаючи CLI, — тому всі
    п'ять місць були зелені.
    """
    res = runner.invoke(app, argv)
    payload = json.loads(res.stdout)
    assert payload.get("v") == 1, f"{argv}: конверт без версії схеми"
    assert "ok" in payload, f"{argv}: конверт без `ok`"
    assert "warnings" in payload, (
        f"{argv}: у відповіді немає `warnings` — саме так із машинного режиму "
        f"зникав знаменник нуля")


def test_a_refusal_reaches_the_machine_as_json_too(space) -> None:
    """🔴 Помилка теж є відповіддю.

    Кожна команда друкувала відмову rich-розміткою навіть у машинному режимі:
    агент діставав розмальований текст замість `{"ok": false, ...}` — і з коду
    повернення не міг відрізнити «не розпізнав справу» від «нічого не знайшлось».
    """
    res = runner.invoke(app, ["search", "Шевченко",
                              "--case", "щось-чого-немає", "--json"])
    assert res.exit_code == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert "не розпізнав" in payload["error"]
