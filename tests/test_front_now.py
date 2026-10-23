"""▶ Панель «Зараз читається» в Node: видно звідусіль, «Спинити» — з другого натискання."""
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
globalThis.location.pathname = '/';
globalThis.location.search = '';
document.body.dataset.token = 'tok';
const ITEMS = [
  { where: 'local', case: 'spr-1', case_key: 'TEST/1/1/1', shifra: 'ТЕСТ 1-1-1', title: 'Сповідка',
    run: 'spr-1', done: 6, total: 27, shards: 2, minutes: 4, via: 'terminal' },
  { where: 'cloud', case: 'spr-2', case_key: 'TEST/1/1/2', run: 'r1', done: 40, total: 120, via: 'cloud',
    phase: 'читає' }];
const asked = [];
const stubFetch = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/jobs/wait')) return new Promise(() => {});
  const name = u.split('/api/op/')[1] || '';
  if (name === 'reading.now' || name === 'read.stop' || name === 'cloud.stop') {
    asked.push([name, JSON.parse((opts || {}).body || '{}')]);
    const data = name === 'reading.now' ? { items: ITEMS } : { stopped: [1] };
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1, warnings: [], data }) };
  }
  return stubFetch(url, opts);
};
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));
const { ACTIONS } = await import('./core/registry.js');
await import('./app.js');
await tick(150);
const V = await import('./core/view.js');
const N = await import('./screens/now.js');
V.setView(`<p>x</p>${N.nowBox()}`);
await N.fillNow(V.curGen()); await tick(20);
const box = document.getElementById('rn-box');
const out = { html: box.innerHTML, hidden: box.hidden };
const btn = { dataset: { kind: 'local', arg: 'spr-1' }, textContent: '' };
await ACTIONS['rn.stop'](null, btn); await tick(10);
out.firstAsked = asked.filter((a) => a[0] === 'read.stop').length;
out.sureText = btn.textContent;
await ACTIONS['rn.stop'](null, btn); await tick(20);
out.stop = (asked.find((a) => a[0] === 'read.stop') || [])[1] || null;
const cbtn = { dataset: { kind: 'cloud', arg: 'r1', sure: '1' }, textContent: '' };
await ACTIONS['rn.stop'](null, cbtn); await tick(20);
out.cloud = (asked.find((a) => a[0] === 'cloud.stop') || [])[1] || null;
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-now")
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
                         capture_output=True, cwd=root, encoding="utf-8", errors="replace",
                         timeout=120)
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, "фронт не виконався:\n" + (res.stderr or res.stdout)[:3000]
    return json.loads(line[2:])


def test_every_live_read_is_shown_with_where_who_and_progress(probe) -> None:
    html = probe["html"]
    assert not probe["hidden"]
    assert "ТЕСТ 1-1-1" in html and "6 / 27" in html and "шардів: 2" in html
    assert "на цій машині" in html and "термінала чи помічником" in html
    assert "у хмарі" in html and "40 / 120" in html and 'data-arg="cloud"' in html


def test_stop_asks_first_then_stops_that_case(probe) -> None:
    assert probe["firstAsked"] == 0 and probe["sureText"] == "Точно спинити?"
    assert probe["stop"] == {"case": "spr-1"}
    assert probe["cloud"] == {"run_id": "r1"}
