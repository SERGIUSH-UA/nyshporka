"""HTTPS довіряє сертифікатам системи — у точці входу `nysh` і у воркері пачки.

🔴 06.11.2026: антивірус людини перевіряв HTTPS до сховища Супряги, і всі 8 її
внесків пішли запасним шляхом через сервер — без рамок рядків. Його корінь
лежить у сховищі Windows, а `httpx` звіряв лише з `certifi`.

Підміна `ssl` — на весь процес, тому сама вона перевіряється в підпроцесі
(`conftest` вимикає її для процесу паку).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from nyshporka.core import tls

ROOT = Path(__file__).resolve().parents[1]


def _child(code: str, **env: str) -> str:
    base = {k: v for k, v in os.environ.items() if k != tls.ENV}
    r = subprocess.run([sys.executable, "-c", code], env={**base, **env},
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return r.stdout.strip()


PROBE = (
    "import ssl, truststore\n"
    "from nyshporka.core.tls import use_system_trust\n"
    "on = use_system_trust()\n"
    "print(on, isinstance(ssl.create_default_context(), truststore.SSLContext))\n"
)


def test_the_process_asks_the_system_store() -> None:
    assert _child(PROBE) == "True True"


def test_the_switch_keeps_certifi_only() -> None:
    assert _child(PROBE, **{tls.ENV: "0"}) == "False False"


def test_httpx_still_loads_certifi_into_the_system_context() -> None:
    """`certifi` лишається запасним: `httpx` вантажить його в той самий контекст."""
    out = _child(
        "import ssl, certifi, truststore\n"
        "from nyshporka.core.tls import use_system_trust\n"
        "use_system_trust()\n"
        "seen = []\n"
        "orig = truststore.SSLContext.load_verify_locations\n"
        "def spy(self, cafile=None, *a, **k):\n"
        "    seen.append(cafile)\n"
        "    return orig(self, cafile, *a, **k)\n"
        "truststore.SSLContext.load_verify_locations = spy\n"
        "import httpx\n"
        "httpx.Client().close()\n"
        "print(certifi.where() in seen)\n")
    assert out == "True"


def test_the_switch_is_read_without_touching_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    import ssl

    monkeypatch.setenv(tls.ENV, "0")
    before = ssl.SSLContext
    assert tls.use_system_trust() is False
    assert ssl.SSLContext is before


def _function(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^def {name}\(.*?(?=^\S)", text, re.S | re.M)
    assert m, f"{name} у {path.name}"
    return m.group(0)


def test_the_entry_point_turns_it_on_before_any_command() -> None:
    body = _function(ROOT / "src" / "nyshporka" / "cli.py", "main")
    assert body.index("use_system_trust()") < body.index("app()")


def test_the_batch_worker_turns_it_on_itself() -> None:
    """Воркер `spawn` не проходить через `cli.main`, а заливає саме він."""
    body = _function(ROOT / "src" / "nyshporka" / "share" / "batch.py", "_init")
    assert "use_system_trust()" in body


def test_it_is_a_core_dependency() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    core = text[text.index("dependencies = ["):text.index("]", text.index("dependencies = ["))]
    assert '"truststore>=' in core
