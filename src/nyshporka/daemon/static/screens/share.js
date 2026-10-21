/**
 * 🤝 Супряга: віддати прочитане в спільний пул, взяти чуже, мої картки, профіль.
 *
 * Запит користувачів №1 — віддача з консолі, а не лише з терміналу. Пул —
 * nyshporka.online: інші шукають у відданих справах, не читаючи їх наново.
 *
 * 🔴 Приватний проєкт не віддається: відмову ставить сама `share.push`, і
 * консоль показує її причину, а не ховає справу з переліку мовчки.
 */

import { t, tOr } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm, renderWarnings, curGen, alive, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, confirmAct, closeModal, modalSeq } from '../core/modal.js';
import { kv, pill, toast } from '../core/bits.js';

/** Стан справи з `share.suggest` (рядок пакета) → ключ підпису. */
const STATUS = { 'готова': 'ready', 'у пулі без рамок': 'noboxes', 'неповна': 'partial',
  'без кадрів': 'noframes', 'збірна': 'multi' };
const READY = ['готова', 'у пулі без рамок'];
const stLabel = (s) => (STATUS[s] ? t(`give.st.${STATUS[s]}`) : s || '');

// ── Віддати ──────────────────────────────────────────────────────────────────
let GIVE = [];

SCREENS.give = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('share.suggest', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  GIVE = (env.data || {}).rows || [];
  const rows = GIVE.map((r, i) => `<tr>
      <td><input type="checkbox" data-act="give.pick" data-arg="${i}"${READY.includes(r.status) ? ' checked' : ''}
        aria-label="${esc(r.shifra || r.case_key)}"></td>
      <td class="mono">${esc(r.shifra || r.case_key)}</td><td>${esc(r.title || '')}</td>
      <td class="num">${esc(r.pages || 0)} / ${esc(r.frames || '?')}</td>
      <td>${pill(READY.includes(r.status) ? 'ok' : 'neutral', stLabel(r.status))}</td></tr>`).join('');
  setView(`<h2>${t('give.title')}</h2>
    <p class="muted">${t('give.why')}</p>
    ${renderWarnings(env)}
    <div class="dash-box">${GIVE.length ? `<table class="tbl-wide"><thead><tr><th></th><th>${t('give.case')}</th>
      <th>${t('give.name')}</th><th>${t('give.pages')}</th><th>${t('give.state')}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="row"><button class="primary" data-act="give.go" id="give-go"></button>
        <span class="muted">${t('give.go.why')}</span></p>
      <div id="give-box"></div>` : `<p class="muted">${t('give.none')}</p>`}</div>`);
  countPicked();
};

function picked() {
  return [...document.querySelectorAll('[data-act="give.pick"]')]
    .filter((b) => b.checked).map((b) => GIVE[Number(b.dataset.arg)]).filter(Boolean);
}

function countPicked() {
  const b = el('give-go');
  if (!b) return;
  const n = picked().length;
  b.textContent = t('give.go').replace('{n}', n);
  b.disabled = !n;
}

// ── Взяти ────────────────────────────────────────────────────────────────────
SCREENS.pull = async () => {
  setView(`<h2>${t('pull.title')}</h2>
    <p class="muted">${t('pull.why')}</p>
    <form class="row" data-act="pull.find">
      ${fld(t('pull.q'), `<input name="query" placeholder="${esc(t('pull.q.ph'))}" required autofocus>`)}
      <button type="submit">${t('pull.find')}</button>
    </form>
    <div class="dash-box" id="pull-box"><p class="muted">${t('pull.hint')}</p></div>`);
};

let FOUND = [];

function pullRows(d) {
  FOUND = d.found || [];
  if (!FOUND.length) return `<p class="muted">${t('pull.none')}</p>`;
  return `<p class="muted">${esc(t('pull.count').replace('{n}', d.count || FOUND.length))}</p>`
    + FOUND.map((r, i) => `<div class="lrow">
      <div><b class="mono">${esc(r.shifra)}</b>
        <small class="muted">${esc([r.years, r.places].filter(Boolean).join(' · '))}</small>
        <small class="muted">${esc(t('pull.pages').replace('{n}', r.pages || '?'))}${
  r.publisher ? ` · ${esc(r.publisher)}` : ''}</small></div>
      <button data-act="pull.take" data-arg="${i}">${t('pull.take')}</button></div>`).join('');
}

// ── Мої картки ───────────────────────────────────────────────────────────────
SCREENS.cards = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('share.list', { what: 'all' });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const rows = ((env.data || {}).rows || []).map((r) => `<div class="lrow">
      <div><b class="mono">${esc(r.shifra || r.case_key || '')}</b>
        <small class="muted">${pill(r.event === 'pack' ? 'ok' : 'info', tOr(`cards.ev.${r.event}`, r.event))}
          ${esc(String(r.at || '').slice(0, 10))}${r.pages ? ` · ${esc(t('pull.pages').replace('{n}', r.pages))}` : ''}</small></div>
      ${r.case_key || r.shifra ? `<button data-act="cards.open" data-arg="${esc(r.case_key || r.shifra)}">${t('cards.card')}</button>` : ''}
    </div>`).join('');
  setView(`<h2>${t('cards.title')}</h2>
    <p class="muted">${t('cards.why')}</p>
    <div class="dash-box">${rows || `<p class="muted">${t('cards.none')}</p>`}</div>`);
};

async function openCard(key) {
  openModal({ title: key, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('share.card', { case: key });
  if (seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const c = (env.data || {}).card || {};
  const rows = Object.entries(c).filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => [k, esc(Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v))]);
  el('dlg-body').innerHTML = `${kv(rows) || `<p class="muted">${t('cards.empty')}</p>`}
    ${renderWarnings(env)}
    <p class="muted">${t('cards.edit')}</p>
    <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

// ── Профіль (вікно) ──────────────────────────────────────────────────────────
SCREENS.sprofile = async () => {
  setView(`<p class="muted">${t('common.loading')}</p>`);
  const [prof, stats] = await Promise.all([
    callOp('share.setup', { show: true }), callOp('share.stats', {})]);
  if (!prof.ok) return failure(prof);
  const p = (prof.data || {}).profile || {};
  const local = ((stats.ok && stats.data) || {}).local || {};
  const consent = p.consent || 'pytaty';
  setView(`<form data-act="sprofile.save" id="sp-form">
      ${fld(t('sp.handle'), `<input name="handle" value="${esc(p.handle || '')}">`)}
      ${fld(t('sp.consent'), `<select name="consent">${['pytaty', 'zavzhdy', 'nikoly'].map((c) => `<option value="${c}"${
    c === consent ? ' selected' : ''}>${esc(t(`sp.consent.${c}`))}</option>`).join('')}</select>`)}
      <p class="muted fld-hint">${t('sp.private')}</p>
      ${kv([[t('sp.packed'), esc((local.packed || {}).cases || 0)], [t('sp.taken'), esc((local.imported || {}).cases || 0)]])}
      <div class="row dlg-acts"><button type="submit" class="primary">${t('sp.save')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="sp-box"></div>
    </form>`);
};

Object.assign(ACTIONS, {
  'give.pick': () => countPicked(),
  'give.go': async () => {
    const rows = picked();
    if (!rows.length) return;
    const yes = await confirmAct({ title: t('give.confirm').replace('{n}', rows.length), text: t('give.confirm.why'),
      rows: [[t('give.case'), rows.map((r) => r.shifra || r.case_key).join(', ')]], okLabel: t('give.do') });
    if (!yes) return;
    // 🔴 `share.push` — не робота в черзі: відповідь приходить, коли пачка
    // залита. Тому кнопка заблокована на весь час (повторний клік залив би
    // ту саму пачку вдруге), а результат читається з самої відповіді.
    const btn = el('give-go');
    if (btn) btn.disabled = true;
    const box0 = el('give-box');
    if (box0) box0.innerHTML = `<p class="muted">${t('give.going')}</p>`;
    const env = await callOp('share.push', { cases: rows.map((r) => r.case_key) });
    if (btn) btn.disabled = false;
    if (!env.ok) { boxError('give-box', env); return; }
    const d = env.data || {};
    const failed = d.failed || [];
    const given = (d.rows || []).filter((r) => r.ok).length;
    const box = el('give-box');
    if (!box) return;
    box.innerHTML = `<p class="${failed.length ? 'warn-inline' : 'ok-line'}">${esc(t('give.done')
      .replace('{n}', given).replace('{f}', failed.length))}</p>${renderWarnings(env)}`;
    toast(t('give.done').replace('{n}', given).replace('{f}', failed.length));
  },
  'pull.find': async (ev) => {
    ev.preventDefault();
    const q = String(new FormData(ev.target).get('query') || '').trim();
    const done = busyForm(ev.target);
    const env = await callOp('share.pull', { query: q });
    done();
    if (!env.ok) { boxError('pull-box', env); return; }
    const box = el('pull-box');
    if (box) box.innerHTML = pullRows(env.data || {}) + renderWarnings(env);
  },
  'pull.take': async (_ev, elm) => {
    const r = FOUND[Number(elm.dataset.arg)];
    if (!r) return;
    const yes = await confirmAct({ title: t('pull.take.title'), text: t('pull.take.why'),
      rows: [[t('give.case'), r.shifra]], okLabel: t('pull.take') });
    if (!yes) return;
    const box = el('pull-box');
    if (box) box.innerHTML = `<p class="muted">${t('pull.taking')}</p>`;
    const env = await callOp('share.pull', { query: r.shifra, take: true });
    if (!env.ok) { boxError('pull-box', env); return; }
    // «Взято» — лише коли справді щось прийнято: нечіткий запит (кілька справ
    // під шифрою) повертає `ok` з попередженням, але без `imported`.
    const took = !!((env.data || {}).imported);
    if (el('pull-box')) {
      el('pull-box').innerHTML = `${took ? `<p class="ok-line">${t('pull.taken')}</p>`
        : `<p class="warn-inline">${t('pull.nottaken')}</p>`}${renderWarnings(env)}`;
    }
  },
  'cards.open': (_ev, elm) => openCard(elm.dataset.arg),
  'sprofile.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const done = busyForm(ev.target);
    const env = await callOp('share.setup', { handle: String(fd.handle || '').trim(), consent: String(fd.consent || '') });
    done();
    if (!env.ok) { boxError('sp-box', env); return; }
    closeModal(true);
  },
});
