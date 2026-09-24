"""🤝 Супрягу запущено: команда, операції й сторінка документації — видні.

Тест сторожить РІШЕННЯ, як і його попередник, що стеріг ворота: або обмін
відчинено цілком, або не відчинено взагалі. Напіввідчинене (команда є, а
сторінки немає; сторінка є, а команда відмовляє) — гірше за обидва стани.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nyshporka.core import ops

ROOT = Path(__file__).resolve().parents[1]


def test_share_in_help() -> None:
    """Команда видна в загальній довідці й працює без жодного прапорця."""
    from nyshporka.cli import app

    res = CliRunner().invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "share" in res.output
    res = CliRunner().invoke(app, ["share", "--help"])
    assert res.exit_code == 0
    for cmd in ("pack", "card", "publish", "import", "pull", "sync"):
        assert cmd in res.output


def test_no_dev_flag_left() -> None:
    """Прапорця розробки більше немає — ні в коді, ні в поведінці."""
    import nyshporka.share.cli as SC

    assert not hasattr(SC, "DEV_FLAG")
    src = (ROOT / "src" / "nyshporka" / "cli.py").read_text(encoding="utf-8")
    assert "NYSHPORKA_SUPRIAHA\"" not in src and "DEV_FLAG" not in src


def test_ops_open_to_the_app_not_to_the_agent() -> None:
    """Застосунок бачить операції обміну; агент — ні (стеля MCP, див. ops_share)."""
    found = [o for o in ops.REGISTRY.all() if o.name.startswith("share.")]
    assert found, "операції обміну зникли з реєстру"
    for o in found:
        assert o.gui, f"{o.name}: gui=False"
        assert not o.agent, f"{o.name}: agent=True"


def test_ops_with_key_or_journal_are_private() -> None:
    """Усе, що бачить профіль, журнал чи ключ, — не для чужої вкладки."""
    want_private = {"share.setup", "share.suggest", "share.publish", "share.autoshare",
                    "share.inspect", "share.import", "share.geometry", "share.list",
                    "share.stats", "share.sync", "share.pull", "share.card"}
    got = {o.name: o for o in ops.REGISTRY.all() if o.name.startswith("share.")}
    for name in want_private:
        assert got[name].private, f"{name}: private=False"
    assert got["share.pull"].mutates, "pull --take пише в простір"


def test_docs_page_published() -> None:
    """Сторінка обміну — у навігації й у збірці."""
    cfg = yaml.safe_load(
        # `!ENV` — тег MkDocs для адреси з оточення; safe_load його не знає.
        (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        .replace("!!python/name:", "").replace("!ENV ", "")
    )
    assert "share.md" not in (cfg.get("exclude_docs") or "")
    assert "share.md" in yaml.dump(cfg.get("nav") or [], allow_unicode=True)
