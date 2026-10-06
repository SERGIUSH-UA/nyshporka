"""🏠 Головна малюється, не чекаючи перевірки машини — і крок усе ж доїжджає.

🔴 Дві половини одного твердження, і кожна ловить свою ваду. Якщо екран
знову чекатиме на `home.machine`, людина на великому просторі дивиться на сірі
смуги 12 с (замір 06.10.2026). Якщо ж відповідь ніхто не вставить у
чекліст, крок «Машина читає рукопис» зникне з головної назавжди — і машина без
карти виглядатиме готовою.

Заглушка DOM — та сама, що в `test_front_boots`; тут лише підміняється
відповідь сервера про машину, і вона навмисно приходить ПІЗНІШЕ за зріз.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from _front import FRONT_DIR, SHARED_DIR
from test_front_boots import STUB

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node немає — виконати фронт нічим")

PROBE = r"""
import './_stub.js';
const stubFetch = globalThis.fetch;
const out = { machineAsked: 0, machineDone: false };
globalThis.fetch = async (url, opts) => {
  if (String(url).endsWith('/api/op/home.machine')) {
    out.machineAsked += 1;
    await new Promise((r) => setTimeout(r, 60));
    out.machineDone = true;
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1, warnings: [],
      data: { ok: true, level: 'fail', ready: false, bad: ['КАРТИ-НЕМА'] } }) };
  }
  return stubFetch(url, opts);
};
const { SCREENS } = await import('./core/registry.js');
await import('./app.js');
await new Promise((r) => setTimeout(r, 200));   // стартова навігація відпрацювала

out.machineAsked = 0;
out.machineDone = false;
// Заглушка не розбирає розмітку, тож вузол чекліста живе між малюваннями; у
// браузері `setView` створив би його наново — порожнім.
document.getElementById('dash-steps').innerHTML = '';
await SCREENS.home();
const view = document.getElementById('view').innerHTML || '';
out.drawnFirst = view.includes('class="tile"') && !out.machineDone;
out.stepsBefore = document.getElementById('dash-steps').innerHTML || '';
await new Promise((r) => setTimeout(r, 200));
out.stepsAfter = document.getElementById('dash-steps').innerHTML || '';
console.log('@@' + JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-home")
    shutil.copytree(FRONT_DIR, root, dirs_exist_ok=True)
    shutil.copytree(SHARED_DIR, root / "ui", dirs_exist_ok=True)
    for p in root.rglob("*.js"):
        depth = len(p.relative_to(root).parts) - 1
        prefix = "./" if depth == 0 else "../" * depth
        s = p.read_text(encoding="utf-8")
        s2 = re.sub(r"from '/ui/", f"from '{prefix}ui/", s)
        if s2 != s:
            p.write_text(s2, encoding="utf-8")
    (root / "_stub.js").write_text(STUB, encoding="utf-8")
    (root / "_probe.mjs").write_text(PROBE, encoding="utf-8")
    res = subprocess.run(["node", "--input-type=module", "-e",
                          f"await import({json.dumps((root / '_probe.mjs').as_uri())})"],
                         capture_output=True, cwd=root, encoding="utf-8", errors="replace")
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, "фронт не виконався:\n" + (res.stderr or res.stdout)[:1500]
    return json.loads(line[2:])


def test_the_dashboard_is_drawn_before_the_machine_answers(probe) -> None:
    assert probe["drawnFirst"], "головна чекала на перевірку машини, перш ніж малюватись"
    assert "КАРТИ-НЕМА" not in probe["stepsBefore"], \
        "крок машини з'явився раніше за відповідь — звідки тоді він узявся?"


def test_the_machine_step_arrives_into_the_checklist(probe) -> None:
    assert probe["machineAsked"] == 1, "головна не спитала про машину зовсім"
    assert "КАРТИ-НЕМА" in probe["stepsAfter"], \
        "відповідь про машину прийшла, але в чекліст не потрапила"
