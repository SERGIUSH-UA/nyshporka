"""🤖 Агентна поверхня: MCP-сервер поверх реєстру операцій.

Працювати з агентом не обов'язково — без нього застосунок повний. Але коли
агент є, він має бачити рівно те саме, що людина, і не мати власної гілки коду.
"""

from nyshporka.mcp.server import call_tool, mcp_config, serve, tool_definitions

__all__ = ["call_tool", "mcp_config", "serve", "tool_definitions"]
