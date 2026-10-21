/**
 * ☁ Хмара: орендовані карти — що крутиться, скільки коштує, що забрати.
 *
 * 🔴 Гроші витрачає лише другий крок. «У хмару» спершу кличе `cloud.go` без
 * `run` — сухий прогін: план, кошторис вилкою, рішення про автозапуск, без
 * оренди. Лише після підтвердження людини йде `run: true`, а понад стелю
 * автозапуску ще й `confirm: true` — дозвіл людини, не агента. Окремої кнопки,
 * що одразу орендує, немає.
 *
 * `cloud.go` — довга операція, тож і сухий прогін іде роботою в черзі:
 * вікно чекає на її результат (`jobDone`), а не на відповідь запиту.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, renderWarnings, curGen, alive, humanError } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show, jobDone, jobChip } from '../core/nav.js';
import { openModal, confirmAct, modalSeq } from '../core/modal.js';
import { kv, pill, dayOf } from '../core/bits.js';

const FINAL = ['done', 'failed'];
const money = (v) => (v === null || v === undefined ? '—' : `$${Number(v).toFixed(2)}`);

/** Заходи з останньої відповіді: дія «Зупинити» бере опис звідси. */
let RUNS = [];

SCREENS.cloud = async () => {
  const gen = curGen();
  busy(5);
  const env = await callOp('cloud.state', { limit: 20 });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data || {};
  RUNS = d.runs || [];
  const live = RUNS.filter((r) => !FINAL.includes(r.phase));
  const past = RUNS.filter((r) => FINAL.includes(r.phase));
  const spent = RUNS.reduce((s, r) => s + Number(r.spent_usd || 0), 0);
  const unreleased = RUNS.filter((r) => r.needs_release).length;
  const tile = (label, value) => `<div class="dash-box"><span class="muted">${esc(label)}</span>
    <b class="num big">${esc(value)}</b></div>`;
  setView(`<h2>${t('cloud.title')}</h2>
    <p class="muted">${t('cloud.why')}</p>
    ${renderWarnings(env)}
    <div class="dash-two">${tile(t('cloud.spent.last').replace('{n}', RUNS.length), money(spent))}${
  tile(t('cloud.live'), d.live || 0)}${
  // Тривога, а не показник: нуль тут нічого не каже, ненульове — оренда тече.
  unreleased ? tile(t('cloud.unreleased'), unreleased) : ''}</div>
    <div class="dash-box"><h3>${t('cloud.now')}</h3>
      ${live.length ? live.map(runRow).join('') : `<p class="muted">${t('cloud.none.live')}</p>`}</div>
    <div class="dash-box"><h3>${t('cloud.past')}</h3>
      ${past.length ? past.map(runRow).join('') : `<p class="muted">${t('cloud.none.past')}</p>`}</div>`);
};

function runRow(r) {
  const done = FINAL.includes(r.phase);
  const frames = r.frames_total ? ` · ${r.pages_done || 0} / ${r.frames_total}` : '';
  return `<div class="lrow">
    <div><b class="mono">${esc(r.case_key || r.run_id)}</b>
      <small class="muted">${esc(r.phase_human || r.phase)}${frames} · ${money(r.spent_usd)}
        · ${esc(dayOf(r.started))}${r.project ? ` · ${esc(r.project)}` : ''}</small>
      ${r.needs_release ? pill('err', t('cloud.release')) : ''}</div>
    <button class="ctl-sm" data-act="cloud.more" data-arg="${esc(r.run_id)}">${t('cloud.more')}</button>
    ${!done ? `<button class="danger" data-act="cloud.stop" data-arg="${esc(r.run_id)}">${t('cloud.stop')}</button>`
    : r.phase === 'failed' ? `<button data-act="cloud.fetch" data-arg="${esc(r.run_id)}">${t('cloud.fetch')}</button>` : ''}
    <span id="cloud-job-${esc(r.run_id)}"></span></div>`;
}

async function runMore(id) {
  openModal({ title: id, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('cloud.state', { run_id: id });
  if (seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const r = ((env.data || {}).runs || [])[0] || {};
  const inc = (r.incidents || []).map((x) => `<li>${esc(x.text || x.kind || JSON.stringify(x))}</li>`).join('');
  el('dlg-body').innerHTML = `${kv([[t('cloud.case'), esc(r.case_key || '')],
    [t('cloud.phase'), esc(r.phase_human || r.phase || '')], [t('cloud.backend'), esc(r.backend || '')],
    [t('cloud.frames'), esc(`${r.pages_done || 0} / ${r.frames_total || 0}`)],
    [t('cloud.spent'), money(r.spent_usd)], [t('cloud.hours'), esc(r.rent_hours || 0)],
    [t('cloud.why.stop'), esc(r.why || '')]])}
    ${inc ? `<h4>${t('cloud.incidents')}</h4><ul>${inc}</ul>` : ''}
    <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

// ── «У хмару»: кошторис → підтвердження → оренда ─────────────────────────────
/**
 * Вікно хмарного прогону справи. Викликає екран «Читання» з ключем чи текою.
 * Повертає Promise, що закінчується разом із вікном — для тесту.
 */
export async function openCloudGo(caseRef, script = '') {
  GO = null;
  openModal({ title: t('cloud.go.title'), body: `<p class="muted" id="cloud-go-plan">${t('cloud.go.plan')}</p>
    <div id="cloud-go-box"></div>` });
  // 🔴 Кошторис належить вікну, яке його просило: відповідь, що прийшла після
  // закриття (чи вже до іншої справи), не має права стати `GO`.
  const seq = modalSeq();
  const mine = () => seq === modalSeq();
  const dry = await callOp('cloud.go', { case: [caseRef], script });
  if (!mine()) return;
  if (!dry.ok) { boxError('cloud-go-box', dry); return; }
  const job = await jobDone((dry.data || {}).job_id, (j) => {
    const b = el('cloud-go-box');
    if (b && mine()) b.innerHTML = jobChip(j);
  });
  const box = el('cloud-go-box');
  if (!box || !mine()) return;
  const plan = el('cloud-go-plan');
  if (plan) plan.textContent = '';
  if (job.state !== 'done' || !job.result) {
    box.innerHTML = `<div class="warn err">${humanError(job.error || t('job.failed'))}</div>`;
    return;
  }
  const g = job.result;
  const est = g.estimate || {};
  const fork = (g.fork_usd || []).filter((x) => x !== null && x !== undefined);
  box.innerHTML = `${kv([[t('cloud.case'), esc(g.case_key || caseRef)],
    [t('cloud.frames'), esc(g.pages_total || est.frames || '')],
    [t('cloud.price'), esc(fork.length ? fork.map(money).join(' – ') : '—')],
    [t('cloud.hours'), esc(est.hours || g.max_hours || '')],
    [t('cloud.decision'), esc(LAUNCHES.includes(g.launch) ? t(`cloud.launch.${g.launch}`) : t('cloud.launch.unknown'))]])}
    ${(g.notes || []).length ? `<ul>${g.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
    <div class="row dlg-acts">
      ${canRun(g.launch) ? `<button class="primary" data-act="cloud.run">${t('cloud.run')}</button>` : ''}
      <button class="ghost" data-act="modal.close">${t('modal.no')}</button></div>`;
  // Без відомого рішення сервера кнопки запуску немає: вигадане «можна» тут
  // показало б людині рішення, якого ніхто не ухвалював.
  GO = canRun(g.launch) ? { caseRef, script, launch: g.launch, fork } : null;
}

const LAUNCHES = ['ok', 'needs_confirm', 'no_credit'];
const canRun = (launch) => launch === 'ok' || launch === 'needs_confirm';

/** Кошторис, на який людина дивилась, — другий крок іде рівно з ним. */
let GO = null;

/** Другий крок: підтвердження називає ціну, і лише тоді — `run: true`. */
async function runCloud() {
  if (!GO || !canRun(GO.launch)) return;
  const { caseRef, script, launch, fork } = GO;
  const yes = await confirmAct({ title: t('cloud.run.title'),
    text: launch === 'needs_confirm' ? t('cloud.run.over') : t('cloud.run.why'),
    rows: [[t('cloud.case'), caseRef], [t('cloud.price'), fork.length ? fork.map(money).join(' – ') : '—']],
    okLabel: t('cloud.run'), danger: launch === 'needs_confirm' });
  if (!yes) return;
  GO = null;
  openModal({ title: t('cloud.go.title'), body: `<div id="cloud-go-box"><p class="muted">${t('cloud.run.going')}</p></div>` });
  const seq = modalSeq();
  const env = await callOp('cloud.go', { case: [caseRef], run: true, confirm: launch === 'needs_confirm', script });
  if (!env.ok) { boxError('cloud-go-box', env); return; }
  // 🔴 Відповідь «поставлено в чергу» — ще не запуск: відмова чи збій
  // наглядача приходять уже з роботи. Тож вікно чекає на неї й показує
  // вердикт, а не перекидає людину на перелік, де нового заходу ще немає.
  const job = await jobDone((env.data || {}).job_id, (j) => {
    const b = el('cloud-go-box');
    if (b && seq === modalSeq()) b.innerHTML = jobChip(j);
  });
  if (seq !== modalSeq()) return;
  const box = el('cloud-go-box');
  if (!box) return;
  const g = job.result || {};
  box.innerHTML = job.state === 'done'
    ? `<p class="ok-line">${esc(t('cloud.run.started'))}</p>
       ${kv([[t('cloud.case'), esc(g.case_key || caseRef)], [t('cloud.decision'), esc(g.verdict || '')],
    [t('cloud.why.stop'), esc(g.why || '')]])}
       <div class="row dlg-acts"><button class="primary" data-act="nav" data-arg="cloud">${t('nav.cloud')}</button></div>`
    : `<div class="warn err">${humanError(job.error || t('job.failed'))}</div>`;
}

Object.assign(ACTIONS, {
  'cloud.more': (_ev, elm) => runMore(elm.dataset.arg),
  'cloud.run': () => runCloud(),
  /** 🔴 Зупинка — після підтвердження: прочитане до цієї миті лишається, оренда гасне. */
  'cloud.stop': async (_ev, elm) => {
    const id = elm.dataset.arg;
    const r = RUNS.find((x) => x.run_id === id) || {};
    const yes = await confirmAct({ title: t('cloud.stop.title'), text: t('cloud.stop.why'),
      rows: [[t('cloud.case'), r.case_key || id], [t('cloud.spent'), money(r.spent_usd)]],
      okLabel: t('cloud.stop'), danger: true });
    if (!yes) return;
    const env = await callOp('cloud.stop', { run_id: id });
    if (!env.ok) { openModal({ title: t('cloud.stop'), body: `<p class="warn">${esc(env.error || '')}</p>` }); return; }
    if ((env.warnings || []).length) {
      openModal({ title: t('cloud.stop'), body: renderWarnings(env) });
      return;
    }
    await show('cloud');
  },
  'cloud.fetch': async (_ev, elm) => {
    const id = elm.dataset.arg;
    const env = await callOp('cloud.fetch', { run_id: id });
    const box = el(`cloud-job-${id}`);
    if (!env.ok) { if (box) box.innerHTML = `<span class="warn-inline">${esc(env.error || '')}</span>`; return; }
    const job = await jobDone((env.data || {}).job_id, (j) => {
      const b = el(`cloud-job-${id}`);
      if (b) b.innerHTML = jobChip(j);
    });
    const b2 = el(`cloud-job-${id}`);
    if (b2) b2.innerHTML = jobChip(job);
  },
});
