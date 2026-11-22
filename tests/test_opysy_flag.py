"""Флаг описів: без `NYSH_OPYSY` функції не видно ні в `nysh`, ні в операціях.

Реєстрація відбувається при імпорті `nyshporka.cli` і `nyshporka.ops`, тож
перемкнути її всередині одного процесу pytest не можна — кожен стан у
власному процесі (рівно два запуски: вимкнено й увімкнено).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from nyshporka import features

_PROBE = r"""
import json, sys
from typer.main import get_command
from typer.testing import CliRunner
from nyshporka.cli import app
from nyshporka import ops as O

cmd = get_command(app)
out = {"groups": sorted(cmd.commands), "ops": sorted(o.name for o in O.all_ops()
                                                     if o.name.startswith("opysy."))}
res = CliRunner().invoke(app, ["opys", "policy", "ЦДІАК", "442", "--json"])
out["policy_exit"] = res.exit_code
out["policy_out"] = res.output[-2000:]
print("PROBE" + json.dumps(out, ensure_ascii=False))
"""


def _probe(flag: str | None) -> dict:
    env = dict(os.environ)
    env.pop(features.OPYSY, None)
    if flag is not None:
        env[features.OPYSY] = flag
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env["PYTHONIOENCODING"] = "utf-8"
    got = subprocess.run([sys.executable, "-c", _PROBE], env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=180)
    line = next((x for x in got.stdout.splitlines() if x.startswith("PROBE")), "")
    assert line, f"проба впала: {got.stderr[-3000:]}"
    return json.loads(line[len("PROBE"):])


def test_off_hides_everything_on_shows_it() -> None:
    off = _probe(None)
    assert "opys" not in off["groups"]
    assert off["ops"] == []
    assert off["policy_exit"] != 0

    on = _probe("1")
    assert "opys" in on["groups"]
    # Перелік схованого (`features.HIDDEN`) — рівно те, що флаг реєструє.
    assert on["ops"] == sorted(features.HIDDEN[features.OPYSY]["ops"])
    assert on["policy_exit"] == 0, on["policy_out"]
    assert '"open": false' in on["policy_out"]
