/**
 * 🗃 Набори — те, з чого робляться мітки для трену.
 *
 * Екран відповідає на питання «що в мене є для розмітки і в якому стані», і
 * числа тут беруться з диска: скільки кропів лежить, скільки міток у
 * `lines.jsonl`, скільки рядків зведено арбітрами. Набір, який тут не показує
 * злиття, у корпус не потрапить — хоч би скільки рядків для нього звели.
 *
 * Довгі дії (нарізка, голоси, завдання) ідуть роботами в черзі демона, і їхній
 * поступ малюється тут, поруч із формою, а не лише на екрані «Роботи».
 */
import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto, onJob, jobChip, jobNotes } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';
import { attachCombobox } from '/ui/combobox.js';

/** Набори, як їх віддав останній `train.sets` — для селектів у формах. */
let SETS = [];
let _runCb = null;

SCREENS.sets = async () => {
  const gen = curGen();
  setView(`
    <h2>${ic('folder-open')} ${t('nav.sets')}</h2>
    <p class="muted">${t('sets.why')}</p>
    <div id="sets-list"></div>
    <div class="dash-two">
      <div class="dash-box">
        <h3>${t('sets.cut.title')}</h3>
        <p class="muted">${t('sets.cut.why')}</p>
        <form data-act="sets.cut">
          <div class="row">
            <input name="run" placeholder="${t('sets.cut.run')}" required>
            <input name="name" placeholder="${t('sets.cut.name')}" required>
          </div>
          <div class="row">
            <input name="pages" placeholder="${t('sets.cut.pages')}">
            <input name="pick" type="number" min="0" value="6" placeholder="${t('sets.cut.pick')}">
          </div>
          <div class="row">
            <input name="domain" placeholder="${t('sets.cut.domain')}">
            <button type="submit">${t('sets.cut.go')}</button>
          </div>
          <div id="sets-cut-job"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.voices.title')}</h3>
        <p class="muted">${t('sets.voices.why')}</p>
        <form data-act="sets.voices">
          <div class="row"><select name="name" id="sets-v-name"></select></div>
          <div class="row">
            <input name="from_run" placeholder="${t('sets.voices.from_run')}">
            <input name="models" placeholder="${t('sets.voices.models')}">
            <button type="submit">${t('sets.voices.go')}</button>
          </div>
          <div id="sets-voices-job"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.gloss.title')}</h3>
        <p class="muted">${t('sets.gloss.why')}</p>
        <form data-act="sets.gloss">
          <div class="row"><select name="name" id="sets-g-name"></select></div>
          <div class="row">
            <input name="add" placeholder="${t('sets.gloss.add')}" required>
            <input name="why" placeholder="${t('sets.gloss.src')}">
            <button type="submit">${t('sets.gloss.go')}</button>
          </div>
          <div id="sets-gloss"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.arb.title')}</h3>
        <p class="muted">${t('sets.arb.why')}</p>
        <form data-act="sets.export">
          <div class="row">
            <select name="name" id="sets-a-name"></select>
            <button type="submit">${t('sets.export.go')}</button>
            <button type="button" data-act="sets.import">${t('sets.import.go')}</button>
          </div>
          <div id="sets-arb-job"></div>
        </form>
      </div>
    </div>`);
  await setsList();
  if (!alive(gen)) return;
  await setsRunHints();
};

/** Таблиця наборів зі знаменниками — і селекти форм із тих самих імен. */
async function setsList() {
  const box = el('sets-list');
  const env = await callOp('train.sets', { all: true });
  if (!env.ok) return boxError('sets-list', env);
  SETS = env.data.sets || [];
  const opts = SETS.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
  for (const id of ['sets-v-name', 'sets-g-name', 'sets-a-name']) {
    const sel = el(id);
    if (sel) sel.innerHTML = opts;
  }
  if (!SETS.length) {
    box.innerHTML = `<p class="muted">${t('sets.none')}</p>` + renderWarnings(env);
    return undefined;
  }
  const rows = SETS.map((s) => {
    const st = s.by_status || {};
    const merge = s.merge
      ? `${s.n_merged} <span class="muted">(h${s.merge.high}/m${s.merge.med}/l${s.merge.low})</span>`
      : '—';
    const crops = s.crops_present
      ? `${s.n_crops} <span class="muted">/ ${s.n_pages} ${t('common.pages')}</span>`
      : `<span class="warn-inline">${t('sets.nocrops')}</span>`;
    return `<tr>
      <td><b>${esc(s.name)}</b>${s.title ? `<div class="muted">${esc(s.title)}</div>` : ''}</td>
      <td>${s.role === 'holdout' ? '🎯 ' + t('sets.role.holdout') : t('sets.role.train')}</td>
      <td class="num">${crops}</td>
      <td class="num">${s.n_marked} <span class="muted">(ok ${st.ok || 0})</span></td>
      <td class="num">${merge}</td>
      <td>${esc((s.voices || []).join(', ') || '—')}</td>
      <td><button data-act="sets.open" data-arg="${esc(s.name)}">${t('sets.open')}</button></td>
    </tr>`;
  }).join('');
  box.innerHTML = `<div class="tbl-wide"><table>
    <thead><tr><th>${t('sets.col.name')}</th><th>${t('sets.col.role')}</th>
      <th>${t('sets.col.crops')}</th><th>${t('sets.col.marks')}</th>
      <th>${t('sets.col.merge')}</th><th>${t('sets.col.voices')}</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table></div>` + renderWarnings(env);
  return undefined;
}

/** Підказка прогонів у полі нарізки: імена довгі й схожі, набирати їх руками — описка. */
async function setsRunHints() {
  if (_runCb) { _runCb.destroy(); _runCb = null; }
  const input = el('view').querySelector('input[name="run"]');
  if (!input) return;
  const env = await callOp('runs.list', {});
  if (!env.ok) return;
  const runs = ((env.data || {}).runs || []).map((r) => r.name).filter(Boolean);
  _runCb = attachCombobox(input, { items: runs, empty: t('view.run.none') });
}

/**
 * Довга робота — поруч із формою. Після завершення перелік наборів
 * перечитується: кропів чи голосів побільшало, і таблиця мусить це показати.
 */
function watchHere(box, jobId) {
  if (!box) return;
  box.innerHTML = jobChip({ state: 'queued', progress: {} });
  onJob(jobId, async (j) => {
    if (!document.contains(box)) return;
    box.innerHTML = jobChip(j) + (j.state === 'done' || j.state === 'error' ? jobNotes(j) : '');
    if (j.state === 'done') await setsList();
  });
}

Object.assign(ACTIONS, {
  'sets.cut': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const free = busyForm(ev.target);
    const env = await callOp('train.cut', { run: fd.run, name: fd.name, pages: fd.pages,
      pick: Number(fd.pick || 0), domain: fd.domain });
    free();
    if (!env.ok) return boxError('sets-cut-job', env);
    watchHere(el('sets-cut-job'), (env.data || {}).job_id);
    return undefined;
  },

  'sets.voices': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const free = busyForm(ev.target);
    const env = await callOp('train.voices', { name: fd.name, from_run: fd.from_run,
      models: fd.models });
    free();
    if (!env.ok) return boxError('sets-voices-job', env);
    watchHere(el('sets-voices-job'), (env.data || {}).job_id);
    return undefined;
  },

  'sets.gloss': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('train.glossary', { name: fd.name, add: fd.add, why: fd.why });
    const box = el('sets-gloss');
    if (!env.ok) return boxError('sets-gloss', env);
    const items = Object.entries(env.data.glossary || {});
    box.innerHTML = (items.length
      ? `<p>${items.map(([k, v]) => `<b>${esc(k)}</b>${v ? ` <span class="muted">${esc(v)}</span>` : ''}`).join(' · ')}</p>`
      : `<p class="muted">${t('sets.gloss.empty')}</p>`) + renderWarnings(env);
    const add = ev.target.elements.add;
    if (add) add.value = '';
    return undefined;
  },

  'sets.export': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const free = busyForm(ev.target);
    const env = await callOp('train.export', { name: fd.name });
    free();
    if (!env.ok) return boxError('sets-arb-job', env);
    watchHere(el('sets-arb-job'), (env.data || {}).job_id);
    return undefined;
  },

  /** Імпорт — коротка дія: відповідь приходить одразу, з воротами в `warnings`. */
  'sets.import': async (_ev, elm) => {
    const form = elm.closest('form');
    const name = form ? form.elements.name.value : '';
    const box = el('sets-arb-job');
    box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('train.import', { name });
    if (!env.ok) return boxError('sets-arb-job', env);
    const c = env.data.conf || {};
    box.innerHTML = `<p>${t('sets.import.done')}: <b>${env.data.rows}</b>
      <span class="muted">(high ${c.high || 0} · med ${c.med || 0} · low ${c.low || 0})</span></p>`
      + renderWarnings(env);
    await setsList();
    return undefined;
  },

  'sets.open': (_ev, elm) => goto('label', { set: elm.dataset.arg }),
});

/** Тримаємо `ST` в імпортах: посів екрана читає `goto`, а не цей модуль. */
void ST;
