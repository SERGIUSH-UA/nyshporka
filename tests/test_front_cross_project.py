"""🧭 Міжпроєктні зрізи (хвиля 7г) у Node: хто шукав, чий канон, для кого прогін.

Майстерня з двома вигаданими проєктами — `sydoruk` (вкладка) і `kovalchuk`.
Справи `TEST/…`, картки `I9…`.

🔴 Найдорожче тут — щоб чужий проєкт читався як чужий: чип з його назвою й
перехід туди, а не мовчазний рядок, який людина прийме за свій.
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
const PROJECTS = { projects: [
  { id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', color: '#aa3300', glyph: 'С' },
  { id: 'kovalchuk', name: 'Рід Ковальчуків', kind: 'family', color: '#0055aa', glyph: 'К' }],
  current: 'sydoruk', default: null, hub_only: true, hub_id: '_hub' };
const row = (key, stage, by) => ({ key, shifra: key, title: 'Сповідка', htr_stage: stage,
  searched_by: by, verdict: '', on_disk: true, frames: 9, path: 'data/raw/' + key });
const DATA = {
  'library.list': { built: true, cases: [
      row('TEST/1/1/1', 'pysar', { sydoruk: '2026-10-20T10:00', kovalchuk: '2026-10-21T10:00' }),
      row('TEST/1/1/2', 'pysar', { kovalchuk: '2026-10-21T10:00' }),
      row('TEST/1/1/3', 'none', {})],
    shown: 3, total: 3, page: 0, pages: 1, library_total: 3, facets: {},
    summary: { all: 3, has_layers: true }, kinds: {} },
  'cloud.go': { job_id: 'cg1', state: 'queued' },
  'cloud.state': { runs: [
    { run_id: 'r1', case_key: 'TEST/1/1/1', phase: 'done', spent_usd: 0.5, project: 'sydoruk', started: 1760000000 },
    { run_id: 'r2', case_key: 'TEST/1/1/2', phase: 'done', spent_usd: 0.25, project: 'kovalchuk', started: 1760000000 },
    { run_id: 'r3', case_key: 'TEST/1/1/3', phase: 'done', spent_usd: 0.1, project: '', started: 1760000000 }],
    live: 0, total: 3 },
};
globalThis.fetch = async (url, opts) => {
  const u = String(url);
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
const sent = (op) => (globalThis.__OPS || []).filter(([n]) => n === op).map(([, b]) => JSON.parse(b));

const { SCREENS, ACTIONS } = await import('./core/registry.js');
await import('./app.js');
await tick(150);
const out = {};

await SCREENS.library();
await tick();
out.lib = view();
document.getElementById('lib-searched').value = 'todo';
globalThis.__OPS = [];
await ACTIONS['lib.filter']();
out.libTodo = sent('library.list');

const S = await import('./screens/search.js');
out.ownCanon = S.inCanon({ in_canon: [{ project: 'sydoruk', name: 'Рід Сидоруків', card: 'I9001' }] });
out.otherCanon = S.inCanon({ in_canon: [{ project: 'kovalchuk', name: 'Рід Ковальчуків', card: 'I9002' }] });
out.noCanon = S.inCanon({});
out.known = S.inCanonNote({ in_canon_known: 4 });

const PJ = await import('./core/projects.js');
out.chips2 = PJ.projectChips(['sydoruk', 'kovalchuk']);
out.chips9 = PJ.projectChips(['sydoruk', 'kovalchuk', 'a', 'b', 'c', 'd', 'e', 'f', 'g']);

const RD = await import('./screens/read.js');
out.forField = RD.forField();
out.forMine = RD.forArg();
await ACTIONS['read.for'](null, { value: '__hub' });
out.forHub = RD.forArg();
await ACTIONS['read.for'](null, { value: 'kovalchuk' });
out.forOther = RD.forArg();

const C = await import('./screens/cloud.js');
globalThis.__OPS = [];
C.openCloudGo('TEST/1/1/2', '', { for_project: 'kovalchuk' });
await tick();
out.cloudDry = sent('cloud.go');
await SCREENS.cloud();
out.cloud = view();
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-cross")
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


def _row(html: str, key: str) -> str:
    return html.split(f'data-arg="{key}"')[1].split("</tr>")[0]


def test_library_shows_who_searched(probe) -> None:
    lib = probe["lib"]
    assert "Прошукано для «Рід Сидоруків»" in lib
    one, two, three = (_row(lib, f"TEST/1/1/{i}") for i in (1, 2, 3))
    # Свій рід шукав — «так», і сусідній рід видно чипом.
    assert 'class="pill ok"' in one and "Рід Ковальчуків" in one and "також:" in one
    # Прочитане, але свій рід ще не шукав — жовте «ні», сусід — чипом.
    assert 'class="pill warn"' in two and "Рід Ковальчуків" in two
    # Непрочитане — не «ні»: шукати ще нема в чому.
    assert "pill" not in three


def test_library_filter_read_but_not_searched_here(probe) -> None:
    """«Прочитані, не прошукані» — це прошукане тут І хоч якийсь декод."""
    body = probe["libTodo"][-1]
    assert body["searched"] == "not_here" and body["htr"] == "any"


def test_search_marks_lines_already_in_a_canon(probe) -> None:
    own, other = probe["ownCanon"], probe["otherCanon"]
    assert "уже в нашому каноні" in own and 'data-act="canon.card"' in own and "I9001" in own
    # Чужий проєкт: чип з назвою й перехід туди, а не картка «тут».
    assert "уже в каноні «Рід Ковальчуків»" in other and 'class="pj-chip"' in other
    assert 'data-act="project.card"' in other and 'data-arg="kovalchuk"' in other
    assert 'data-card="I9002"' in other and 'data-act="canon.card"' not in other
    assert probe["noCanon"] == ""
    assert "таких 4" in probe["known"]


def test_reading_says_for_whom(probe) -> None:
    f = probe["forField"]
    assert "Для кого" in f and 'value="kovalchuk"' in f and 'value="__hub"' in f
    # Свій проєкт — без поля (сервер підпише сам); Майстерня — порожньо.
    assert probe["forMine"] == {}
    assert probe["forHub"] == {"for_project": ""}
    assert probe["forOther"] == {"for_project": "kovalchuk"}


def test_cloud_carries_for_whom_and_splits_spend(probe) -> None:
    assert probe["cloudDry"] == [{"case": ["TEST/1/1/2"], "script": "",
                                  "for_project": "kovalchuk"}]
    c = probe["cloud"]
    assert "За проєктами:" in c and "Рід Ковальчуків" in c and "$0.25" in c
    assert "Майстерня" in c, "захід без проєкту — підписаний Майстернею, а не порожнім"


def test_many_projects_fold_into_badges(probe) -> None:
    """Десять проєктів у клітинці — кружки з «+N», а не рядок назв на півекрана."""
    assert probe["chips2"].count('class="pj-chip"') == 2 and "Рід Ковальчуків" in probe["chips2"]
    nine = probe["chips9"]
    assert 'class="pj-chip"' not in nine and nine.count('class="pj-mini"') == 6 and "+3" in nine
    assert 'title="Рід Сидоруків, Рід Ковальчуків, a, b' in nine
