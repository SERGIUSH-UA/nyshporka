/** 🚦 Черга справ: що на якому етапі, чому стоїть і що з цим зробити. */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError,
  renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { ic } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';

/**
 * 🔴 Чергу веде ОКРЕМИЙ процес (`nysh queue run`), а не застосунок: він
 * переживає закриту вкладку й закритий застосунок. Екран лише читає стан раз
 * на кілька секунд і пише рішення людини у файл черги — тому після
 * перезапуску застосунку тут те саме, що було.
 */
const QUEUE_POLL_MS = 4000;
let _queueSeq = 0;

/** Підпис із словника, а коли ключа немає — те, що дав сервер. */
function queueWord(key, fallback) {
  const got = t(key);
  return got === key ? fallback : got;
}

function queueStages(row) {
  return (row.stages || []).map((s) => {
    const cls = s.state === 'done' ? 'chip tight' : 'chip';
    const mark = s.state === 'done' ? '✓ ' : s.state === 'skip' ? '– ' : '';
    const dim = s.state === 'skip' ? ' dim' : '';
    const name = queueWord(`queue.stage.${s.stage}`, s.title);
    return `<span class="${cls}${dim}">${mark}${esc(name)}</span>`;
  }).join(' ');
}

/** Кнопки рішення — за кодом причини: людина не мусить знати прапорців. */
function queueDecisions(row) {
  const id = esc(row.id);
  const bits = [];
  if (row.code === 'pool_needs_decision' || row.code === 'pool_ambiguous'
      || row.code === 'pool_take_failed') {
    bits.push(`<button class="ctl-sm" data-act="queue.pool" data-ref="${id}"
      data-arg="take">${t('queue.pool.take')}</button>`);
    bits.push(`<button class="ctl-sm" data-act="queue.pool" data-ref="${id}"
      data-arg="read">${t('queue.pool.read')}</button>`);
  }
  if (row.code === 'script_unsure') {
    bits.push(`<button class="ctl-sm" data-act="queue.script" data-ref="${id}"
      data-arg="cyrillic">${t('queue.script.cyrillic')}</button>`);
    bits.push(`<button class="ctl-sm" data-act="queue.script" data-ref="${id}"
      data-arg="latin">${t('queue.script.latin')}</button>`);
  }
  if (row.code === 'shifra_needs_eye') {
    bits.push(`<button class="ctl-sm" data-act="queue.shifra"
      data-ref="${id}">${t('queue.shifra.ok')}</button>`);
  }
  if (row.code === 'incomplete' || row.code === 'quarantine') {
    bits.push(`<form class="row" data-act="queue.partial">
      <input type="hidden" name="ref" value="${id}">
      <input name="partial" required placeholder="${esc(t('queue.partial.ph'))}">
      <button class="ctl-sm">${t('queue.partial.go')}</button></form>`);
  }
  if (['blocked', 'failed', 'retry'].includes(row.state)) {
    bits.push(`<button class="ctl-sm" data-act="queue.retry"
      data-ref="${id}">${ic('refresh')} ${t('queue.retry')}</button>`);
  }
  if (row.state !== 'running' && row.state !== 'dropped') {
    bits.push(`<button class="ctl-sm" data-act="queue.drop"
      data-ref="${id}">${ic('trash')} ${t('queue.drop')}</button>`);
  }
  return bits.join(' ');
}

function queueRow(row, pulse) {
  const state = queueWord(`queue.st.${row.state}`, row.state_text || row.state);
  const mine = pulse && pulse.item === row.id && pulse.n;
  const bar = mine
    ? `<progress value="${pulse.i}" max="${pulse.n}"></progress>
       <span class="mono">${pulse.i}/${pulse.n} ${esc(pulse.what || '')}</span>`
    : '';
  const size = row.frames === undefined ? ''
    : `<span class="mono">${row.pages || 0}/${row.frames || '—'}</span>`;
  const why = row.why ? `<div class="warn-inline">${esc(row.why)}</div>` : '';
  const fix = row.fix && ['blocked', 'failed', 'retry'].includes(row.state)
    ? `<div class="muted">${t('queue.next')}: <span class="mono">${esc(row.fix)}</span></div>`
    : '';
  const again = row.state === 'retry' && row.not_before
    ? `<div class="muted">${t('queue.again')} ${esc(row.not_before.slice(11, 16))}</div>`
    : '';
  return `<tr>
    <td><b>${esc(row.id)}</b><div>${queueStages(row)}</div>${why}${fix}${again}</td>
    <td>${esc(state)}</td>
    <td class="num">${size} ${bar}</td>
    <td class="acts">${queueDecisions(row)}</td></tr>`;
}

function queueEta(left) {
  if (!left || !left.cases) return '';
  const sec = left.eta_sec;
  let when = t('queue.eta.unknown');
  if (sec !== null && sec !== undefined) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    when = `≈ ${h ? `${h} ${t('queue.h')} ` : ''}${m} ${t('queue.m')}`;
  }
  const unknown = left.unknown
    ? ` (${t('queue.left.unknown').replace('{n}', left.unknown)})` : '';
  return t('queue.left').replace('{c}', left.cases).replace('{p}', left.pages || 0)
    + `${unknown} · ${when}`;
}

function queueRunner(data) {
  const r = data.runner || {};
  if (r.alive) {
    const stopping = data.stop ? ` · ${t('queue.stopping')}` : '';
    return `<p>${ic('play')} ${t('queue.runner.on').replace('{pid}', r.pid || '—')}${stopping}
      <button class="ctl-sm" data-act="queue.stop">${ic('pause')} ${t('queue.stop')}</button>
      <button class="ctl-sm" data-act="queue.stopnow">${ic('stop')} ${t('queue.stopnow')}</button></p>`;
  }
  return `<p class="muted">${t('queue.runner.off')}
    <button class="btn-solid ok" data-act="queue.start">${ic('play')} ${t('queue.start')}</button></p>`;
}

function queueBody(env) {
  const data = env.data || {};
  const rows = data.rows || [];
  const pulse = (data.runner || {}).pulse || {};
  const table = rows.length
    ? `<table><thead><tr><th>${t('queue.col.case')}</th><th>${t('queue.col.state')}</th>
        <th>${t('queue.col.pages')}</th><th></th></tr></thead>
        <tbody>${rows.map((r) => queueRow(r, pulse)).join('')}</tbody></table>`
    : `<p class="muted">${t('queue.empty')}</p>`;
  return `${queueRunner(data)}
    <p class="muted">${esc(queueEta(data.left))}</p>
    ${renderWarnings(env)}${table}`;
}

/** @param {boolean} full  перемалювати весь екран чи лише перелік. */
async function queueLoad(full = false) {
  const seq = ++_queueSeq;
  const gen = curGen();
  const env = await callOp('queue.status', {});
  if (seq !== _queueSeq || !alive(gen)) return;
  if (!env.ok) {
    if (full) failure(env); else boxError('queue-msg', env);
    return;
  }
  if (!full) {
    const box = el('queue-body');
    // Людина саме набирає причину в рядку справи — перемальовка стерла б набране.
    const typing = box && box.contains(document.activeElement)
      && document.activeElement.tagName === 'INPUT';
    if (box && !typing) swapHtml(box, queueBody(env));
    return;
  }
  setView(`<h2>${ic('skip')} ${t('queue.title')}</h2>
    <p class="muted">${t('queue.why')}</p>
    <form class="row" data-act="queue.add">
      <input name="refs" required placeholder="${esc(t('queue.add.ph'))}">
      <label class="lbl-mini"><input type="checkbox" name="share" value="1">
        ${t('queue.add.share')}</label>
      <button>${ic('plus')} ${t('queue.add')}</button>
    </form>
    <div id="queue-msg"></div>
    <div id="queue-body">${queueBody(env)}</div>`);
}

/** Оновлення, поки екран відкритий; зупиняється саме, щойно з нього пішли. */
async function queuePoll(gen) {
  while (alive(gen)) {
    await new Promise((r) => setTimeout(r, QUEUE_POLL_MS));
    if (!alive(gen)) return;
    await queueLoad(false);
  }
}

SCREENS.queue = async () => {
  const gen = curGen();
  busy();
  await queueLoad(true);
  if (!alive(gen)) return;
  // Без await: `show()` чекає на екран, а цикл живе, доки екран відкритий.
  queuePoll(gen);
};

/** Показати відповідь дії й перечитати перелік. */
async function queueAfter(env) {
  const box = el('queue-msg');
  if (!env.ok) return boxError('queue-msg', env);
  if (box) box.innerHTML = renderWarnings(env);
  await queueLoad(false);
  return undefined;
}

Object.assign(ACTIONS, {
  'queue.add': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const refs = String(fd.refs || '').split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
    const share = fd.share === '1';
    const env = await callOp('queue.add', { refs, share });
    if (env.ok) ev.target.reset();
    await queueAfter(env);
  },

  'queue.start': async () => {
    await queueAfter(await callOp('queue.start', {}));
  },

  'queue.stop': async () => {
    await queueAfter(await callOp('queue.stop', { now: false }));
  },

  'queue.stopnow': async () => {
    await queueAfter(await callOp('queue.stop', { now: true }));
  },

  'queue.retry': async (_ev, elm) => {
    const ref = elm.dataset.ref;
    await queueAfter(await callOp('queue.retry', { ref }));
  },

  'queue.drop': async (_ev, elm) => {
    const ref = elm.dataset.ref;
    await queueAfter(await callOp('queue.drop', { ref }));
  },

  'queue.pool': async (_ev, elm) => {
    const ref = elm.dataset.ref;
    const pool = elm.dataset.arg;
    await queueAfter(await callOp('queue.set', { ref, pool }));
  },

  'queue.script': async (_ev, elm) => {
    const ref = elm.dataset.ref;
    const script = elm.dataset.arg;
    await queueAfter(await callOp('queue.set', { ref, script }));
  },

  'queue.shifra': async (_ev, elm) => {
    const ref = elm.dataset.ref;
    const shifra_ok = true;
    await queueAfter(await callOp('queue.set', { ref, shifra_ok }));
  },

  'queue.partial': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const ref = String(fd.ref || '');
    const partial = String(fd.partial || '').trim();
    await queueAfter(await callOp('queue.set', { ref, partial }));
  },
});
