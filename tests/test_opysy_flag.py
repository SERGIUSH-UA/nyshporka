"""Флаг описів: без `NYSH_OPYSY` функції не видно ні в `nysh`, ні в операціях.

Реєстрація відбувається при імпорті `nyshporka.cli` і `nyshporka.ops`, тож
перемкнути її всередині одного процесу pytest не можна — кожен стан у
власному процесі (рівно два запуски: вимкнено й увімкнено). Увімкнений процес
заразом проганяє команди `nysh opys check/pack` так, як їх кличе людина й агент:
імпорт `ops_opysy` у процесі pytest зареєстрував би операції для решти тестів.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from nyshporka import features

_PROBE = r"""
import json, sys
from typer.main import get_command
from typer.testing import CliRunner
from nyshporka.cli import app
from nyshporka import ops as O

good, bad, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = get_command(app)
out = {"groups": sorted(cmd.commands), "ops": sorted(o.name for o in O.all_ops()
                                                     if o.name.startswith("opysy."))}
r = CliRunner()


def run(*args):
    res = r.invoke(app, list(args))
    return {"exit": res.exit_code, "out": res.output[-6000:]}


out["policy"] = run("opys", "policy", "ЦДІАК", "442", "--json")
if "opys" in cmd.commands:
    out["check_good"] = run("opys", "check", good)
    out["pack_good_json"] = run("opys", "pack", good, "--out", out_dir, "--json")
    out["check_bad"] = run("opys", "check", bad)
    out["pack_bad_json"] = run("opys", "pack", bad, "--out", out_dir, "--json")
print("PROBE" + json.dumps(out, ensure_ascii=False))
"""


def _workdir(root: Path, name: str, *, repo: str, fond: str, pages: int) -> Path:
    work = root / name
    work.mkdir()
    manifest = {
        "schema": 1, "repo": repo, "fond": fond, "opys": "1", "language": "ru",
        "sources": [{"kind": "archive_site", "url": "https://archive.example/o.djvu",
                     "sha256": "c" * 64, "pages": 3, "label": "o.djvu"}],
        "engines": ["pysar_v31"], "license": "CC-BY-4.0",
        "quality": {"klass": "mid", "form": "hand_ruled"},
    }
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    lines = [json.dumps({"page": i, "voices": {"p": f"текст {i}"}}, ensure_ascii=False)
             for i in range(1, pages + 1)]
    (work / "pages.jsonl").write_text("\n".join(lines), encoding="utf-8")
    rows = [{"regions": [{"page": 1, "y0": 0.1, "y1": 0.2}], "no": 1, "no_status": "chain",
             "title_raw": "Дело о крестьянине"},
            {"regions": [], "title_raw": "без місця"},
            {"regions": [{"page": 9, "y0": 0.1, "y1": 0.2}], "title_raw": "не та сторінка"}]
    if repo == "DAOO":
        rows = rows[:1]
    (work / "rows.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    return work


def _probe(flag: str | None, tmp: Path) -> dict:
    env = dict(os.environ)
    env.pop(features.OPYSY, None)
    if flag is not None:
        env[features.OPYSY] = flag
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env["PYTHONIOENCODING"] = "utf-8"
    good = _workdir(tmp, f"good-{flag}", repo="DAOO", fond="445", pages=3)
    # Чотири відмови разом: закритий фонд, рядок без місця, сторінка поза
    # джерелом, непройдена сторінка — людина мусить побачити всі.
    bad = _workdir(tmp, f"bad-{flag}", repo="ЦДІАК", fond="442", pages=2)
    got = subprocess.run([sys.executable, "-c", _PROBE, str(good), str(bad), str(tmp / "out")],
                         env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    line = next((x for x in got.stdout.splitlines() if x.startswith("PROBE")), "")
    assert line, f"проба впала: {got.stderr[-3000:]}"
    return json.loads(line[len("PROBE"):])


def test_off_hides_everything_on_shows_it(tmp_path: Path) -> None:
    # Засіки запущено в 0.49.0: без змінної — увімкнено, `NYSH_OPYSY=0` ховає
    off = _probe("0", tmp_path)
    assert "opys" not in off["groups"]
    assert off["ops"] == []
    assert off["policy"]["exit"] != 0

    on = _probe("1", tmp_path)
    assert "opys" in on["groups"]
    # Перелік схованого (`features.HIDDEN`) — рівно те, що флаг реєструє.
    assert on["ops"] == sorted(features.HIDDEN[features.OPYSY]["ops"])
    assert on["policy"]["exit"] == 0, on["policy"]["out"]
    assert '"open": false' in on["policy"]["out"]

    assert on["check_good"]["exit"] == 0, on["check_good"]["out"]
    assert "ворота пройдено" in on["check_good"]["out"]
    packed = json.loads(on["pack_good_json"]["out"])
    assert packed["ok"] and packed["data"]["file"].endswith(".nyshopys")

    human = on["check_bad"]["out"]
    assert on["check_bad"]["exit"] != 0
    assert "(4)" in human, human
    for needle in ("не приймає", "без прив'язки", "якої в джерелі немає", "не пройшов"):
        assert needle in human, (needle, human)
    assert "--partial" not in human  # такого прапорця в `nysh opys` немає
    refused = json.loads(on["pack_bad_json"]["out"])
    assert not refused["ok"]
    rules = {w["code"] for w in refused["warnings"] if w["level"] == "alert"}
    assert rules == {"excluded_fond", "row_unbound", "row_bad_page", "coverage"}, refused
    assert not list((tmp_path / "out").glob("bad-*"))
