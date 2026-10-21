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
  'project.list': { projects: [{ id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', persons: 2,
    color: '#aa3300', glyph: 'С', hypotheses: { open: 1, awaiting: 1, closed: 0 } }] },
  'project.status': { project: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', surname: 'Сидорук',
    persons: 2, hypotheses: { open: 1, awaiting: 0, closed: 0 }, color: '#aa3300', glyph: 'С' },
  'cases.list': { cases: [], shown: 0, total: 3, registry: true },
  'share.push': { rows: [{ case: 'TEST/1/1/1', ok: true }], failed: [], summary: {}, total: 1 },
  'history.save': { rev: null, saved: false },
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
  if (u.endsWith('/api/ops')) {
    return { ok: true, status: 200, json: async () => ({ ops: [
      { name: 'test.long', summary: 'довга', when: 'довга дія', mutates: false, long: true,
        schema: { properties: {} } }] }) };
  }
  const name = u.split('/api/op/')[1] || '';
  if (name === 'text.crop' && globalThis.__CROP_FAIL) {
    (globalThis.__OPS ||= []).push([name, (opts || {}).body || '']);
    return { ok: true, status: 200, json: async () => ({ ok: false, v: 1, warnings: [],
      error: 'text.crop: FileNotFoundError: T:/x/text_store.sqlite' }) };
  }
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
out.siftBtn = document.getElementById('hyp-sift').textContent;
ACTIONS['hyp.sift']();
await tick();
out.siftHits = ST.sift.hits;
globalThis.__CROP_FAIL = true;
await ACTIONS['hyp.open'](null, el('H9001'));
await tick();
globalThis.__CROP_FAIL = false;
out.siftNone = [document.getElementById('hyp-sift').textContent, document.getElementById('hyp-sift').disabled];
out.cropHuman = document.getElementById('hyp-crop-0').innerHTML || '';

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
await ACTIONS['hist.save']();
out.toasts = document.body.children.map((c) => c.textContent);

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
await tick(); ACTIONS['modal.ok'](); await tick();
finish({ verdict: 'detached', case_key: 'TEST/1/1/1', why: '' });
await p;
out.afterYes = sent('cloud.go');
out.runBox = document.getElementById('cloud-go-box').innerHTML || '';
globalThis.__OPS = [];
p = C.openCloudGo('TEST/1/1/2');
await tick();
finish({ verdict: 'dry_run', launch: 'no_credit', case_key: 'TEST/1/1/2', fork_usd: [], estimate: {}, notes: [] });
await p;
out.noCreditDlg = document.getElementById('cloud-go-box').innerHTML || '';
await ACTIONS['cloud.run']();
out.noCreditSent = sent('cloud.go');
globalThis.__OPS = [];
p = C.openCloudGo('TEST/1/1/3');
await tick();
finish({ verdict: 'dry_run', case_key: 'TEST/1/1/3', fork_usd: [], estimate: {}, notes: [] });
await p;
out.noLaunchDlg = document.getElementById('cloud-go-box').innerHTML || '';
const NAV = await import('./core/nav.js');
out.emptyJob = await NAV.jobDone(undefined);

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

await ACTIONS['ask.form'](null, el('test.long'));
globalThis.__OPS = [];
p = ACTIONS['ask.run']({ preventDefault() {}, target: document.createElement('form') });
await tick(); ACTIONS['modal.close'](); await p;
out.longAfterNo = (globalThis.__OPS || []).map(([n]) => n);
out.longConfirm = document.getElementById('dlg-title').textContent;

const VW = await import('./core/view.js');
out.staleLine = VW.renderWarnings({ stale: { is: true, reasons: ['нових тек прогонів: 2'] }, warnings: [] });

const SF = await import('./core/schemaform.js');
const schema = { properties: {
  case: { type: 'string', description: 'справа' },
  n: { type: 'integer', minimum: 1, default: 20 },
  force: { type: 'boolean', default: false },
  kind: { enum: ['', 'persons', 'places'], default: '' },
  ids: { type: 'array', items: { type: 'string' } },
  budget: { anyOf: [{ type: 'number' }, { type: 'null' }], default: null },
  on: { anyOf: [{ type: 'boolean' }, { type: 'null' }], default: null },
  pages: { type: 'array', items: { type: 'integer' } },
}, required: ['case'] };
out.formHtml = SF.schemaFormHtml(schema);
const vals = { case: 'TEST/1/1/1', n: '5', kind: 'places', ids: 'a, b', budget: '', on: 'false', pages: '3, 7' };
out.formVals = SF.schemaValues(schema, (k) => vals[k] ?? '', (k) => k === 'force');
out.formEmpty = SF.schemaValues(schema, () => '', () => false);

await SCREENS.give();
out.give = view();
const qsa = document.querySelectorAll;
document.querySelectorAll = (sel) => (String(sel).includes('give.pick') ? [{ checked: true, dataset: { arg: '0' } }] : []);
globalThis.__OPS = [];
p = ACTIONS['give.go']();
await tick(); ACTIONS['modal.ok'](); await p;
document.querySelectorAll = qsa;
out.pushSent = sent('share.push');
out.giveBox = document.getElementById('give-box').innerHTML || '';

const PJ = await import('./screens/project.js');
globalThis.__OPS = [];
out.shell = PJ.projectShell();
await PJ.fillProject();
const kv = (id) => [document.getElementById(id).querySelector('.ov-kpi-v').innerHTML,
  document.getElementById(id).querySelector('.ov-kpi-s').innerHTML, document.getElementById(id).className];
out.kpi = { canon: kv('ov-k-canon'), hyp: kv('ov-k-hyp'), mat: kv('ov-k-mat'), hist: kv('ov-k-hist') };
out.decide = document.getElementById('ov-decide').innerHTML || '';
out.feed = document.getElementById('ov-new').innerHTML || '';
out.headCases = sent('cases.list');
out.cards = await PJ.projectCards();
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
    # Підписи й значення людською мовою, а не `sex M → F`.
    assert "Стать" in d and 'class="diff-d">чоловіча<' in d and 'class="diff-a">жіноча<' in d
    assert ">sex<" not in d
    assert "примітки змінено" in d
    assert probe["restoreAfterNo"] == 0, "повернення пішло без підтвердження"
    body = json.loads(probe["restoreBody"][0])
    assert body == {"path": "data/canonical/persons/I9001.md", "rev": "abc1234"}


def test_cloud_rents_only_after_the_second_yes(probe) -> None:
    """🔴 Перший виклик — сухий прогін; оренда — лише після «так», з `confirm` понад стелю."""
    assert "TEST/1/1/1" in probe["cloud"] and 'data-act="cloud.stop"' in probe["cloud"]
    first = [json.loads(b) for b in probe["dryFirst"]]
    assert first == [{"case": ["TEST/1/1/1"], "script": ""}], "перший виклик мусить бути без run"
    assert "понад стелю" in probe["goDlg"] and 'data-act="cloud.run"' in probe["goDlg"]
    assert not any(json.loads(b).get("run") for b in probe["afterNo"]), "орендовано після «ні»"
    runs = [json.loads(b) for b in probe["afterYes"] if json.loads(b).get("run")]
    assert runs == [{"case": ["TEST/1/1/1"], "run": True, "confirm": True, "script": ""}]
    # Відповідь «у черзі» — ще не запуск: вікно показує вердикт роботи.
    assert "Захід запущено" in probe["runBox"] and "detached" in probe["runBox"]


def test_cloud_without_credit_offers_no_launch(probe) -> None:
    assert 'data-act="cloud.run"' not in probe["noCreditDlg"]
    assert not any(json.loads(b).get("run") for b in probe["noCreditSent"])
    # Без рішення сервера — ні кнопки, ні вигаданого «можна».
    assert 'data-act="cloud.run"' not in probe["noLaunchDlg"]
    assert "не назвав рішення" in probe["noLaunchDlg"]


def test_job_wait_without_an_id_does_not_hang(probe) -> None:
    assert probe["emptyJob"]["state"] == "error"


def test_evidence_crops_secures_and_hands_a_task_to_the_agent(probe) -> None:
    assert probe["prov"] == ["test", ""]
    assert 'data-act="ev.secure"' in probe["evForm"] and "Сидорукъ Іоаннъ" in probe["evForm"]
    names = [n for n, _ in probe["evOps"]]
    assert names == ["text.crop", "evidence.add"], names
    crop, add = (json.loads(b) for _, b in probe["evOps"])
    assert crop == {"case": "TEST/1/1/1", "page": "0005", "line": 4}
    assert add == {"file": "C:/t/crops/0005_l4.png", "provenance": "test",
                   "name": "TEST-1-1-1_0005_l4"}
    box = probe["evBox"]
    assert "data/citations/test/0005_l4.jpg" in box and "I9001" in box and "народження" in box
    assert "nysh canon check" in box


def test_schema_form_builds_fields_and_typed_values(probe) -> None:
    h = probe["formHtml"]
    assert 'name="case"' in h and 'type="number"' in h and 'min="1"' in h
    assert 'type="checkbox"' in h and "<select" in h and 'value="places"' in h
    assert probe["formVals"] == {"case": "TEST/1/1/1", "n": 5, "force": True,
                                 "kind": "places", "ids": ["a", "b"], "on": False,
                                 "pages": [3, 7]}
    assert 'value="false"' in h, "bool | None мусить мати стан «ні», не лише галочку"
    # 🔴 Порожнє необов'язкове не шлеться: інакше перебило б дефолт операції.
    assert probe["formEmpty"] == {"case": ""}


def test_give_lists_unshared_cases(probe) -> None:
    g = probe["give"]
    assert "TEST 1-1-1" in g and "готова" in g and 'id="give-go"' in g


def test_stale_registry_is_a_quiet_line_with_a_button(probe) -> None:
    """Реєстр відстав — тихий рядок із кнопкою, а не жовтий банер «на кожен пчих»."""
    h = probe["staleLine"]
    assert 'class="stale-line"' in h and 'data-act="cases.build"' in h
    assert "нових тек прогонів: 2" in h and 'class="warn' not in h


def test_long_action_from_the_form_asks_first(probe) -> None:
    """🔴 Довга дія — теж зміна стану: без «так» вона не йде в чергу."""
    assert "test.long" not in probe["longAfterNo"], "довга дія пішла без підтвердження"


def test_give_reads_the_answer_without_a_job(probe) -> None:
    """🔴 `share.push` відповідає одразу — екран показує результат, а не чекає роботу."""
    assert [json.loads(b) for b in probe["pushSent"]] == [{"cases": ["TEST/1/1/1"]}]
    assert "Віддано: 1" in probe["giveBox"]


def test_hypothesis_without_a_run_explains_instead_of_silence(probe) -> None:
    assert probe["siftBtn"] == "На звірку"
    text, disabled = probe["siftNone"]
    assert disabled and "Прочитаного рядка ще немає" in text
    assert "Прочитаного для цієї справи ще немає" in probe["cropHuman"]
    assert "FileNotFoundError" not in probe["cropHuman"].split("<details")[0]


def test_actions_say_what_happened(probe) -> None:
    assert "Повернуто" in probe["toasts"] and "Змін немає — зберігати нічого" in probe["toasts"]


def test_project_overview_kpis_and_feed(probe) -> None:
    k = probe["kpi"]
    assert "2" in k["canon"][0] and "ok" in k["canon"][2]
    assert "1" in k["hyp"][0]
    # Матеріал: «не прошукано з N прочитаних», а не голий нуль.
    assert "3" in k["mat"][0] and "прочитаних" in k["mat"][1]
    assert "2026-10-20" in k["hist"][0]
    assert "Іван — син Петра" in probe["decide"]
    assert "Канон перевірено" in probe["feed"] and "Двори роду" in probe["feed"]
    sent = [json.loads(b) for b in probe["headCases"]]
    assert {"htr": "read", "searched": "not_here", "limit": 1} in sent
    assert {"htr": "read", "limit": 1} in sent
    assert 'id="ov-k-mat"' in probe["shell"] and "skel-cell" in probe["shell"]


def test_project_cards_stand_out_with_counts(probe) -> None:
    c = probe["cards"]
    assert 'class="pj-card"' in c and "--pj:#aa3300" in c
    assert "Рід Сидоруків" in c and ">2<" in c.split("pj-stats")[1]
