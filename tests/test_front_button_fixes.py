"""🖱 Кнопки, що «нічого не робили» (прохід консолі 22.10.2026), — у Node.

Майстерня з двома вигаданими проєктами, вкладка відкрита як `?p=_hub` —
саме так її відкриває перемикач «Майстерня». Справи `TEST/…`.
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
globalThis.location.search = '?p=_hub';
// Токен у справжньому заголовку — ASCII (Headers з кирилицею не будуються).
document.body.dataset.token = 'tok';
const stubFetch = globalThis.fetch;
const PROJECTS = { projects: [
  { id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', color: '#aa3300', glyph: 'С' },
  { id: 'kovalchuk', name: 'Рід Ковальчуків', kind: 'family', color: '#0055aa', glyph: 'К' }],
  current: null, default: null, hub_only: true, hub_id: '_hub' };
const DATA = {
  'library.list': { built: true, cases: [{ key: 'TEST/1/1/1', shifra: 'ТЕСТ 1-1-1', title: 'Сповідка',
      htr_stage: 'pysar', searched_by: {}, verdict: 'recheck', verdict_note: 'глянути ще',
      verdict_pages: 40, on_disk: true, frames: 9, path: 'data/raw/t1' }],
    shown: 1, total: 1, page: 0, pages: 1, library_total: 1, facets: {},
    summary: { all: 1, has_layers: true }, kinds: {} },
  'queue.status': { items: [], runner: null, counts: {} },
  'queue.add': { rows: [{ asked: 'TEST/9/9/9', added: false, why: 'такої справи немає ніде' }],
    added: 0, dry_run: false },
  'profile.show': { present: false },
};
globalThis.__HDR = [];
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  const h = (opts || {}).headers;
  if (h && h.get) globalThis.__HDR.push(h.get('X-Nysh-Project'));
  if (u.includes('/api/jobs/wait')) return new Promise(() => {});
  if (u.endsWith('/api/projects')) return { ok: true, status: 200, json: async () => PROJECTS };
  const name = u.split('/api/op/')[1] || '';
  if (name && Object.hasOwn(DATA, name)) {
    (globalThis.__OPS ||= []).push([name, (opts || {}).body || '']);
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1, warnings: [], data: DATA[name] }) };
  }
  return stubFetch(url, opts);
};
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const view = () => document.getElementById('view').innerHTML || '';
const called = (op) => (globalThis.__OPS || []).filter(([n]) => n === op).length;

const NET = await import('./core/net.js');
const { SCREENS, ACTIONS } = await import('./core/registry.js');
await import('./app.js');
await tick(150);
const out = { project: NET.PROJECT, header: globalThis.__HDR.includes('_hub') };

globalThis.__OPS = [];
await SCREENS.search();
await tick();
out.profileAsked = called('profile.show');

await SCREENS.queue();
await tick();
document.getElementById('queue-body').contains = () => false;
const StubForm = globalThis.FormData;
globalThis.FormData = class { entries() { return [['refs', 'TEST/9/9/9']]; } };
await ACTIONS['queue.add']({ preventDefault() {}, target: { reset() {} } });
globalThis.FormData = StubForm;
await tick();
out.queueMsg = document.getElementById('queue-msg').innerHTML;

await SCREENS.library();
await tick();
await ACTIONS['lib.verdict'](null, { dataset: { arg: 'TEST/1/1/1' } });
out.verdictForm = view();

const menu = document.getElementById('me-menu');
menu.getBoundingClientRect = () => ({ left: menu.style.transform ? 8 : -82, right: 143, width: 225 });
globalThis.window.innerWidth = 390;
await ACTIONS['menu.toggle']({ stopPropagation() {} }, { dataset: { arg: 'me-menu' }, setAttribute() {} });
out.menuShift = menu.style.transform || '';
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-buttons")
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


def test_hub_from_the_switcher_is_the_hub_for_screens(probe) -> None:
    """`?p=_hub` — Майстерня: екрани не кличуть проєктних операцій."""
    assert probe["project"] == ""
    # Заголовок іде як є: демон міг стартувати з теки проєкту.
    assert probe["header"]


def test_search_in_the_hub_does_not_ask_for_a_family_profile(probe) -> None:
    assert probe["profileAsked"] == 0


def test_queue_shows_why_a_case_was_not_added(probe) -> None:
    msg = probe["queueMsg"]
    assert "такої справи немає ніде" in msg and "warn err" in msg


def test_verdict_form_opens_with_the_current_verdict(probe) -> None:
    """Порожня форма й «Зберегти» мовчки знімали чинний вердикт."""
    f = probe["verdictForm"]
    assert re.search(r'value="recheck"\s+selected', f)
    assert 'value="глянути ще"' in f and 'value="40"' in f


def test_header_menu_stays_on_screen(probe) -> None:
    assert probe["menuShift"] == "translateX(90px)"


def test_hidden_attribute_beats_any_display_class() -> None:
    css = (FRONT_DIR / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css)
