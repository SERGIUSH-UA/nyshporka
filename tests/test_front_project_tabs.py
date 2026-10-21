"""📚 Екрани хвилі 7в у Node: закладки роду, хмара, Супряга, доказ, форма зі схеми.

Заглушка DOM — та сама, що в `test_front_boots`; тут підміняються відповіді
операцій вигаданим родом (Сидорук, `I9001`, `H9001`, справа `TEST/1/1/1`).

🔴 Найдорожчі твердження тут — про гроші й незворотне: хмарна оренда й
повернення картки йдуть лише після «так» людини. Тест відповідає «ні» і
перевіряє, що запит із `run: true` (чи `history.restore`) не пішов зовсім.
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
const DATA = {
  'canon.check': { loaded: { persons: 2, families: 1, places: 1, sources: 1 }, errors: 1, warnings: 0,
    issues: [{ severity: 'ERROR', code: 'x', where: 'I9001', text: 'мати без джерела' }] },
  'canon.next': { open: 1, awaiting: 0, closed: 0,
    next: [{ id: 'H9001', claim: 'Іван — син Петра', status: 'open', decides: 'сповідка 1838',
             weight: 3, facts: [], hits: [], versus: [] }] },
  'canon.cards': { counts: {}, found: 1, rows: [{ id: 'I9001', kind: 'persons', title: 'Іван Сидорук',
    private: false, facts: 1, citations: 1, file: 'data/canonical/persons/I9001.md' }] },
  'canon.card': { id: 'I9001', kind: 'persons', title: 'Іван Сидорук', private: false,
    file: 'data/canonical/persons/I9001.md',
    card: { id: 'I9001', sex: 'M', facts: [{ type: 'birth', date: { raw: '~1817' }, status: 'hypothesis',
      citations: [{ source_id: 'S_TEST', page: 'арк. 5', quote: 'Сидорукъ Іоаннъ' }] }] },
    notes: '', issues: [], hypotheses: [{ id: 'H9001', claim: 'Іван — син Петра', status: 'open' }] },
  'canon.hyps': { counts: { open: 1, awaiting: 0, closed: 0 }, rows: [{ id: 'H9001', claim: 'Іван — син Петра',
    status: 'open', decides: 'сповідка 1838', weight: 3, hits: 1, strong: true, updated: '2026-10-01' }] },
  'canon.hyp': { id: 'H9001', file: 'x', card: { claim: 'Іван — син Петра', status: 'open', basis: 'вік',
    decides: 'сповідка 1838', about: ['I9001'] }, notes: '', weight: 3,
    hits: [{ case: 'TEST/1/1/1', scan: '0005', line: 4, reading: 'Сидорукъ Іоаннъ', strength: 'strong',
             eye: false, crop: 'nysh text crop' }], facts: ['I9001'], versus: [] },
  'text.crop': { run: 'прогін-тест', page: '0005.jpg', line: 4, out: 'C:/t/crops/0005_l4.png', text: 'Сидорукъ Іоаннъ' },
  'page.view': { image: 'data:image/jpeg;base64,AA' },
  'evidence.add': { path: 'data/citations/test/0005_l4.jpg', sha256: 'aa', size: 9, existed: false },
  'reports.list': { rows: [
    { path: 'research/dvory.md', title: 'Двори роду', kind: 'research', mtime: 1760000000, size: 10 },
    { path: 'plans/dali.md', title: 'Куди далі', kind: 'plans', mtime: 1750000000, size: 10 }] },
  'reports.read': { path: 'research/dvory.md', title: 'Двори роду',
    text: '# Двори\n\nТекст **жирно** <script>x</script>\n\n- один\n- два' },
  'history.auto': { git: true, repo: true, own: false, auto: true },
  'history.log': { path: '', rows: [{ rev: 'abc1234', date: '2026-10-20', subject: 'Канон перевірено',
    files: ['data/canonical/persons/I9001.md'], more: 0 }] },
  'history.diff': { kind: 'fields', fields: [{ field: 'sex', before: 'M', after: 'F' }], notes_changed: true },
  'history.restore': { path: 'x', to: 'abc1234', rev: 'def5678' },
  'cloud.state': { runs: [{ run_id: 'r1', case_key: 'TEST/1/1/1', phase: 'running', phase_human: 'читає',
    frames_total: 100, pages_done: 40, spent_usd: 0.3, needs_release: false, started: 1760000000 }],
    live: 1, total: 1 },
  'cloud.go': { job_id: 'cg1', state: 'queued' },
  'share.suggest': { rows: [{ case_key: 'TEST/1/1/1', shifra: 'TEST 1-1-1', title: 'Сповідка', pages: 9,
    frames: 9, status: 'готова' }], count: 1, total: 1 },
  'project.status': { project: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', surname: 'Сидорук',
    persons: 2, hypotheses: { open: 1, awaiting: 0, closed: 0 }, color: '#aa3300', glyph: 'С' },
  'cases.list': { cases: [], shown: 0, total: 3, registry: true },
};
let JOB = null;
let wake = null;
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/jobs/wait')) {
    if (JOB) { const jobs = [JOB]; JOB = null; return { ok: true, status: 200, json: async () => ({ seq: 9, jobs }) }; }
    return new Promise((r) => { wake = () => { const jobs = [JOB]; JOB = null; wake = null;
      r({ ok: true, status: 200, json: async () => ({ seq: 9, jobs }) }); }; });
  }
  const name = u.split('/api/op/')[1] || '';
  if (name && Object.hasOwn(DATA, name)) {
    (globalThis.__OPS ||= []).push([name, (opts || {}).body || '']);
    const data = name === 'cloud.go' && globalThis.__GO_FAIL ? null : DATA[name];
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1, warnings: [], data }) };
  }
  return stubFetch(url, opts);
};
const finish = (result) => { JOB = { id: 'cg1', state: 'done', result, warnings: [] }; if (wake) wake(); };
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const view = () => document.getElementById('view').innerHTML || '';
const dlg = () => document.getElementById('dlg-body').innerHTML || '';
const sent = (op) => (globalThis.__OPS || []).filter(([n]) => n === op).map(([, b]) => b);
const el = (arg, extra = {}) => ({ ...extra, dataset: { arg, ...(extra.dataset || {}) } });

const { SCREENS, ACTIONS } = await import('./core/registry.js');
const { ST } = await import('./core/state.js');
await import('./app.js');
await tick(150);
const out = {};

await SCREENS.canon();
await tick();
out.canon = view() + (document.getElementById('cn-list').innerHTML || '') + (document.getElementById('cn-check').innerHTML || '');
await ACTIONS['canon.card'](null, el('I9001'));
out.card = dlg();

await SCREENS.hyp();
out.hyp = view();
await ACTIONS['hyp.open'](null, el('H9001'));
await tick();
out.hypDlg = dlg();
out.hypCrop = document.getElementById('hyp-crop-0').innerHTML || '';
ACTIONS['hyp.sift']();
await tick();
out.siftHits = ST.sift.hits;

const R = await import('./screens/research.js');
out.filtered = R.filterReports(DATA['reports.list'].rows, 'двори', '').map((r) => r.path);
out.filteredKind = R.filterReports(DATA['reports.list'].rows, '', 'plans').map((r) => r.path);
await SCREENS.research();
await ACTIONS['rs.read'](null, el('research/dvory.md'));
out.report = dlg();

await SCREENS.history();
await tick();
out.histLog = document.getElementById('hist-log').innerHTML || '';
out.histAuto = view();
await ACTIONS['hist.diff'](null, el('0'));
out.diff = dlg();
let p = ACTIONS['hist.restore'](null, el('0', { dataset: { file: 'data/canonical/persons/I9001.md' } }));
await tick(); ACTIONS['modal.close'](); await p;
out.restoreAfterNo = sent('history.restore').length;
p = ACTIONS['hist.restore'](null, el('0', { dataset: { file: 'data/canonical/persons/I9001.md' } }));
await tick(); ACTIONS['modal.ok'](); await p;
out.restoreBody = sent('history.restore');

await SCREENS.cloud();
out.cloud = view();
const C = await import('./screens/cloud.js');
globalThis.__OPS = [];
p = C.openCloudGo('TEST/1/1/1');
await tick();
out.dryFirst = sent('cloud.go');
finish({ verdict: 'dry_run', launch: 'needs_confirm', case_key: 'TEST/1/1/1', fork_usd: [0.2, 0.4],
         pages_total: 100, estimate: {}, notes: [] });
await p;
out.goDlg = document.getElementById('cloud-go-box').innerHTML || '';
p = ACTIONS['cloud.run']();
await tick(); ACTIONS['modal.close'](); await p;
out.afterNo = sent('cloud.go');
p = ACTIONS['cloud.run']();
await tick(); ACTIONS['modal.ok'](); await p;
out.afterYes = sent('cloud.go');
globalThis.__OPS = [];
p = C.openCloudGo('TEST/1/1/2');
await tick();
finish({ verdict: 'dry_run', launch: 'no_credit', case_key: 'TEST/1/1/2', fork_usd: [], estimate: {}, notes: [] });
await p;
out.noCreditDlg = document.getElementById('cloud-go-box').innerHTML || '';
await ACTIONS['cloud.run']();
out.noCreditSent = sent('cloud.go');

const E = await import('./screens/evidence.js');
out.prov = [E.provenanceOf('TEST/1/1/1'), E.provenanceOf('прогін-тест')];
E.openEvidence({ case: 'TEST/1/1/1', page: '0005', line: 4, text: 'Сидорукъ Іоаннъ' });
out.evForm = dlg();
globalThis.__FORM = { case: 'TEST/1/1/1', page: '0005', line: '4', card: 'I9001', provenance: 'test', what: 'народження' };
globalThis.__OPS = [];
await ACTIONS['ev.secure']({ preventDefault() {}, target: document.createElement('form') });
globalThis.__FORM = null;
out.evOps = (globalThis.__OPS || []).map(([n, b]) => [n, b]);
out.evBox = document.getElementById('ev-box').innerHTML || '';

const SF = await import('./core/schemaform.js');
const schema = { properties: {
  case: { type: 'string', description: 'справа' },
  n: { type: 'integer', minimum: 1, default: 20 },
  force: { type: 'boolean', default: false },
  kind: { enum: ['', 'persons', 'places'], default: '' },
  ids: { type: 'array', items: { type: 'string' } },
  budget: { anyOf: [{ type: 'number' }, { type: 'null' }], default: null },
}, required: ['case'] };
out.formHtml = SF.schemaFormHtml(schema);
const vals = { case: 'TEST/1/1/1', n: '5', kind: 'places', ids: 'a, b', budget: '' };
out.formVals = SF.schemaValues(schema, (k) => vals[k] ?? '', (k) => k === 'force');
out.formEmpty = SF.schemaValues(schema, () => '', () => false);

await SCREENS.give();
out.give = view();

const PJ = await import('./screens/project.js');
globalThis.__OPS = [];
out.head = await PJ.projectHead();
out.headCases = sent('cases.list');
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-tabs")
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


def test_canon_shows_check_cards_and_decisions(probe) -> None:
    c = probe["canon"]
    assert "Іван Сидорук" in c and "I9001" in c
    assert "помилок: 1" in c and "мати без джерела" in c
    assert 'data-act="canon.hyp" data-arg="H9001"' in c


def test_canon_card_window_has_facts_evidence_and_hypotheses(probe) -> None:
    d = probe["card"]
    assert "~1817" in d and "Сидорукъ Іоаннъ" in d and "S_TEST" in d
    assert 'data-arg="H9001"' in d
    assert 'data-act="canon.evidence"' in d
    # 🔴 Консоль канон не править: жодної кнопки «змінити поле».
    assert "canon.set" not in d and "contenteditable" not in d


def test_hypothesis_crops_and_goes_to_sift_with_the_run(probe) -> None:
    assert "Іван — син Петра" in probe["hyp"]
    assert "сповідка 1838" in probe["hypDlg"]
    assert "<img" in probe["hypCrop"], "кроп кандидата не намалювався"
    hits = probe["siftHits"]
    assert hits and hits[0]["name"] == "прогін-тест"
    assert hits[0]["line_index"] == 3 and hits[0]["case_key"] == "TEST/1/1/1"


def test_research_filters_and_renders_markdown_safely(probe) -> None:
    assert probe["filtered"] == ["research/dvory.md"]
    assert probe["filteredKind"] == ["plans/dali.md"]
    r = probe["report"]
    assert "<b>жирно</b>" in r and "<li>один</li>" in r
    assert "<script>" not in r and "&lt;script&gt;" in r


def test_history_log_diff_and_restore_only_after_yes(probe) -> None:
    assert "abc1234" in probe["histLog"] and "I9001.md" in probe["histLog"]
    assert 'data-act="hist.auto"' in probe["histAuto"]
    d = probe["diff"]
    assert "sex" in d and 'class="diff-d">M<' in d and 'class="diff-a">F<' in d
    assert "примітки змінено" in d
    assert probe["restoreAfterNo"] == 0, "повернення пішло без підтвердження"
    body = json.loads(probe["restoreBody"][0])
    assert body == {"path": "data/canonical/persons/I9001.md", "rev": "abc1234"}


def test_cloud_rents_only_after_the_second_yes(probe) -> None:
    """🔴 Перший виклик — сухий прогін; оренда — лише після «так», з `confirm` понад стелю."""
    assert "TEST/1/1/1" in probe["cloud"] and 'data-act="cloud.stop"' in probe["cloud"]
    first = [json.loads(b) for b in probe["dryFirst"]]
    assert first == [{"case": ["TEST/1/1/1"]}], "перший виклик мусить бути без run"
    assert "понад стелю" in probe["goDlg"] and 'data-act="cloud.run"' in probe["goDlg"]
    assert not any(json.loads(b).get("run") for b in probe["afterNo"]), "орендовано після «ні»"
    runs = [json.loads(b) for b in probe["afterYes"] if json.loads(b).get("run")]
    assert runs == [{"case": ["TEST/1/1/1"], "run": True, "confirm": True}]


def test_cloud_without_credit_offers_no_launch(probe) -> None:
    assert 'data-act="cloud.run"' not in probe["noCreditDlg"]
    assert not any(json.loads(b).get("run") for b in probe["noCreditSent"])


def test_evidence_crops_secures_and_hands_a_task_to_the_agent(probe) -> None:
    assert probe["prov"] == ["test", ""]
    assert 'data-act="ev.secure"' in probe["evForm"] and "Сидорукъ Іоаннъ" in probe["evForm"]
    names = [n for n, _ in probe["evOps"]]
    assert names == ["text.crop", "evidence.add"], names
    crop, add = (json.loads(b) for _, b in probe["evOps"])
    assert crop == {"case": "TEST/1/1/1", "page": "0005", "line": 4}
    assert add == {"file": "C:/t/crops/0005_l4.png", "provenance": "test"}
    box = probe["evBox"]
    assert "data/citations/test/0005_l4.jpg" in box and "I9001" in box and "народження" in box
    assert "nysh canon check" in box


def test_schema_form_builds_fields_and_typed_values(probe) -> None:
    h = probe["formHtml"]
    assert 'name="case"' in h and 'type="number"' in h and 'min="1"' in h
    assert 'type="checkbox"' in h and "<select" in h and 'value="places"' in h
    assert probe["formVals"] == {"case": "TEST/1/1/1", "n": 5, "force": True,
                                 "kind": "places", "ids": ["a", "b"]}
    # 🔴 Порожнє необов'язкове не шлеться: інакше перебило б дефолт операції.
    assert probe["formEmpty"] == {"case": ""}


def test_give_lists_unshared_cases(probe) -> None:
    g = probe["give"]
    assert "TEST 1-1-1" in g and "готова" in g and 'id="give-go"' in g


def test_project_head_shows_decisions_and_unsearched(probe) -> None:
    h = probe["head"]
    assert "Рід Сидоруків" in h and "Іван — син Петра" in h
    assert "не прошукано: 3" in h
    assert json.loads(probe["headCases"][0]) == {"htr": "read", "searched": "not_here", "limit": 1}
