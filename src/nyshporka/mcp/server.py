"""🤖 MCP-сервер: агентна поверхня, згенерована з реєстру операцій.

Tools не пишуться руками. Вони будуються з `core.ops`, тож питання «чи не
розійшлись CLI й агент» не стоїть: розійтись немає чому. Нова операція
з'являється в агента тим самим комітом, що й у людини.

🔴 Два правила, які тримають перелік tool'ів скінченним:

* **Лабораторне не потрапляє сюди ніколи** (`agent=False`). Банк розмітки,
  синтетика, трен — для них у агента є командний рядок. Інакше перелік росте з
  кожною фічею, поки модель не перестане його читати.
* **Операції групуються дискримінатором**, а не плодяться по дії: одна
  `job.query` з полем `action`, а не чотири окремі tool'и.

🔴 Попередження їдуть ТЕКСТОМ, а не лише полем. Модель читає текст надійніше за
службові поля, і саме тут ховається різниця між «знайдено нуль» і «знайдено
нуль, бо зріз застарів».
"""
from __future__ import annotations

import json
from typing import Any

from nyshporka import ops
from nyshporka.core.ops import Op

#: Стеля переліку. Не технічна межа, а рішення: далі агент перестає читати
#: опис і починає вгадувати, а вгадування коштує дорожче за відсутність tool'а.
TOOL_LIMIT = 18

#: Операція, якою питають стан довгої роботи.
JOB_OP = "job.query"


def _job_tool() -> str:
    """Ім'я tool'а стану — З РЕЄСТРУ, а не рядком у тексті опису.

    ⚠ Раніше в описі стояло літеральне `nysh_job` — tool'а з такою назвою не
    існувало ніколи (він `nysh_job_query`). Тобто застосунок сам відсилав агента
    в порожнє, і для моделі це гірше за відсутність підказки: вона кличе назване
    ім'я, отримує «невідомий інструмент» і читає це як поламаний застосунок.
    """
    for op in ops.for_agent():
        if op.name == JOB_OP:
            return op.tool_name
    return "nysh_" + JOB_OP.replace(".", "_")


def tool_definitions() -> list[dict[str, Any]]:
    """Опис tool'ів у формі, яку розуміє MCP."""
    out: list[dict[str, Any]] = []
    for op in ops.for_agent():
        out.append({
            "name": op.tool_name,
            "description": _description(op),
            "inputSchema": op.schema(),
        })
    return out


def _description(op: Op) -> str:
    """Опис для моделі: що робить, і чи міняє щось."""
    parts = [op.summary]
    if op.mutates:
        parts.append("МІНЯЄ стан дослідження.")
    if op.long:
        parts.append(f"Повертає посилання на завдання, а не результат: "
                     f"стан питати через {_job_tool()}.")
    return " ".join(parts)


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Виклик tool'а → вміст відповіді MCP.

    Помилка операції повертається як ЗВИЧАЙНА відповідь із `ok: false`, а не як
    виняток транспорту: агент має прочитати причину й виправитись, а не
    отримати «tool failed» без пояснення.
    """
    op_name = _op_name(name)
    if op_name is None:
        known = ", ".join(o.tool_name for o in ops.for_agent())
        return _content(json.dumps({"ok": False, "error": f"немає такого tool'а: {name}"},
                                   ensure_ascii=False),
                        f"Невідомий tool «{name}». Доступні: {known}")
    env = ops.call(op_name, arguments or {})
    # 🔴 Зображення віддається КАРТИНКОЮ, а не рядком base64 у JSON. Модель не
    # вміє «подивитись» на текст; звірка рядка оком — саме те, заради чого
    # існує `page.view`, і без картинки вона перетворюється на ще один переказ
    # того, що вже сказала машина.
    image = _pop_image(env)
    payload = json.dumps(env.as_dict(), ensure_ascii=False, indent=1, default=str)
    return _content(payload, env.as_agent_text(), image=image)


def _pop_image(env: Any) -> tuple[str, str] | None:
    """Витягти `(base64, mime)` з відповіді, прибравши його з JSON.

    Лишати картинку ще й у полі означало б надіслати ті самі сотні кілобайтів
    двічі — раз як зображення, раз як нечитабельний рядок.
    """
    if not isinstance(env.data, dict):
        return None
    data: dict[str, Any] = env.data
    url = data.get("image")
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    head, _, body = url.partition(",")
    mime = head[5:].split(";", 1)[0] or "image/png"
    data.pop("image", None)
    return body, mime


def _op_name(tool_name: str) -> str | None:
    for op in ops.for_agent():
        if op.tool_name == tool_name:
            return op.name
    return None


def _content(payload: str, note: str,
             image: tuple[str, str] | None = None) -> dict[str, Any]:
    blocks: list[dict[str, str]] = []
    if note:
        blocks.append({"type": "text", "text": note})
    if image is not None:
        blocks.append({"type": "image", "data": image[0], "mimeType": image[1]})
    blocks.append({"type": "text", "text": payload})
    return {"content": blocks}


# ── транспорт ────────────────────────────────────────────────────────────────
def serve() -> int:
    """Підняти сервер по stdio. Потребує пакета `mcp`."""
    try:
        import anyio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import ImageContent, TextContent, Tool
    except ImportError:
        print("Для агентної поверхні потрібен пакет `mcp`:\n"
              "    pip install 'nyshporka[agent]'")
        return 2

    server = Server("nyshporka")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [Tool(name=d["name"], description=d["description"],
                     inputSchema=d["inputSchema"]) for d in tool_definitions()]

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]
                    ) -> list[TextContent | ImageContent]:
        res = call_tool(name, arguments)
        out: list[TextContent | ImageContent] = []
        for b in res["content"]:
            if b.get("type") == "image":
                out.append(ImageContent(type="image", data=b["data"],
                                        mimeType=b["mimeType"]))
            else:
                out.append(TextContent(type="text", text=b["text"]))
        return out

    async def _run() -> None:
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())

    anyio.run(_run)
    return 0


def mcp_config(command: str = "nysh") -> dict[str, Any]:
    """Блок для `.mcp.json` проєкту користувача."""
    return {"mcpServers": {"nyshporka": {"command": command, "args": ["mcp", "serve"]}}}
