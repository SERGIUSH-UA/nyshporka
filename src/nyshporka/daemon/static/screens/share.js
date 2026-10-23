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
import { callOp, staleThenFresh, staleBadge } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm, renderWarnings, curGen, alive, fld, emptyMini, mini, safeHref } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, confirmAct, closeModal, modalSeq } from '../core/modal.js';
import { kv, pill, toast, ratioBar, fmtDay } from '../core/bits.js';
import { bars as chartBars } from '/ui/chart.js';

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
  // Перелік рахується секундами, тож спершу — минула відповідь, потім свіжа
  // (`staleThenFresh`). Галочки, поставлені поки йшло оновлення, лишаються.
  let shown = false;
  const paint = (env, again) => {
    if (!alive(gen)) return;
    const keep = shown ? new Set(picked().map((r) => r.case_key)) : null;
    paintGive(env, again);
    if (keep) {
      document.querySelectorAll('[data-act="give.pick"]').forEach((b) => {
        const r = GIVE[Number(b.dataset.arg)];
        b.checked = !!r && keep.has(r.case_key);
      });
      countPicked();
    }
    shown = true;
  };
  const env = await staleThenFresh('share.suggest', { fast: true }, (e, _stale, again) => paint(e, again));
  // Сервер віддав МИНУЛИЙ перелік (дані змінились, свіжий рахується у фоні) —
  // перепитуємо, доки не прийде свіжий; «Оновлюю…» стоїть увесь цей час.
  // 🔴 Без `await`: екран уже намальовано, а перехід на інший екран чекає,
  // доки завершиться функція поточного, — з очікуванням опитування консоль
  // «не пускала» з «Віддати» до 15 с (замір 23.10.2026).
  giveLate(env, gen, paint);
};

/** Дотягнути свіжий перелік після `refreshing: true`; вихід з екрана — стоп. */
export async function giveLate(first, gen, paint, wait = 2500) {
  const late = (e) => !!(e && e.ok && e.data && e.data.refreshing);
  let env = first;
  if (!late(env)) return;
  staleBadge(true);
  for (let i = 0; late(env) && i < 6; i += 1) {
    await new Promise((r) => setTimeout(r, wait));
    if (!alive(gen)) { staleBadge(false); return; }
    env = await callOp('share.suggest', { fast: true });
  }
  staleBadge(false);
  if (alive(gen) && env.ok) paint(env, true);
}

function paintGive(env, again = false) {
  if (!env.ok) return failure(env);
  GIVE = (env.data || {}).rows || [];
  const rows = GIVE.map((r, i) => `<tr>
      <td><input type="checkbox" data-act="give.pick" data-arg="${i}"${READY.includes(r.status) ? ' checked' : ''}
        aria-label="${esc(r.shifra || r.case_key)}"></td>
      <td class="mono">${shifraCell(r)}</td><td>${esc(r.title || '')}</td>
      <td class="num">${esc(r.pages || 0)} / ${esc(r.frames || '?')}${ratioBar(r.pages, r.frames)}</td>
      <td>${pill(READY.includes(r.status) ? 'ok' : 'neutral', stLabel(r.status))}</td></tr>`).join('');
  setView(`
    <p class="muted">${t('give.why')}</p>
    ${renderWarnings(env)}
    <div class="dash-box">${GIVE.length ? `<table class="tbl-wide tbl-cards"><thead><tr><th></th><th>${t('give.case')}</th>
      <th>${t('give.name')}</th><th>${t('give.pages')}</th><th>${t('give.state')}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="row"><button class="primary" data-act="give.go" id="give-go"></button>
        <span class="muted">${t('give.go.why')}</span></p>
      <div id="give-box"></div>` : emptyMini('zshyvok', t('give.none'))}</div>`, again);
  countPicked();
};

/**
 * Шифра з невизначеним архівом приходить як «? 605-1-59». Знак питання людині
 * нічого не пояснював — тепер це мітка «архів не визначено» поруч із номером.
 */
function shifraCell(r) {
  const s = String(r.shifra || r.case_key || '');
  // Збірка (`ARCH/0/@slug`) шифри не має — архів і слово «збірка», ключ у підказці.
  if (!r.shifra && s.includes('/@')) {
    return `<span title="${esc(s)}">${esc(s.split('/')[0])} · ${esc(t('give.bundle'))}</span>`;
  }
  if (s.includes('@') && /\?-@|-@/.test(s)) {
    return `<span title="${esc(s)}">${esc(s.split(' ')[0])} · ${esc(t('give.bundle'))}</span>`;
  }
  if (!s.startsWith('? ')) return esc(s);
  return `${esc(s.slice(2))} <span class="tag warn">${esc(t('give.norepo'))}</span>`;
}

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
  setView(`
    <p class="muted">${t('pull.why')}</p>
    <form class="row" data-act="pull.find">
      ${fld(t('pull.q'), `<input name="query" placeholder="${esc(t('pull.q.ph'))}" required autofocus>`)}
      <button type="submit">${t('pull.find')}</button>
    </form>
    <div class="dash-box" id="pull-box"><p class="muted">${t('pull.hint')}</p></div>
    <div id="pull-stats"></div>`);
  pullStats(curGen());
};

/**
 * Що вже взято із Супряги й від кого — підсумком і стовпчиками, а не голим
 * полем пошуку на порожній сторінці.
 */
async function pullStats(gen) {
  const env = await callOp('share.stats', {});
  const box = el('pull-stats');
  if (!alive(gen) || !box || !env.ok) return;
  const loc = (env.data || {}).local || {};
  const imp = loc.imported || {};
  const from = (loc.from || []).map((x) => ({ label: x.publisher, n: x.cases }));
  if (!imp.cases) return;
  box.innerHTML = `<div class="dash-box pull-stats">
    <div class="cards-head">${mini('kartky', 52)}<div>
      <b>${esc(t('pull.sum').replace('{n}', imp.cases).replace('{p}', from.length))}</b>
      <small class="muted">${esc(t('pull.sum.pages').replace('{n}', Number(imp.pages || 0).toLocaleString('uk')))}</small></div></div>
    ${from.length ? `<h4>${t('pull.from')}</h4>${chartBars(from, { rows: 8, restLabel: t('dash.rest') })}` : ''}</div>`;
}

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
  // Журнал віддачі — подія на кожне пакування й заливку, тож одна справа
  // стояла десятками рядків (понад 470 тис. знаків на сторінці, QA 23.10.2026).
  // Тепер справа — один рядок з останньою подією, пошук і порції по 60.
  const seen = new Map();
  [...((env.data || {}).rows || [])]
    .sort((x, y) => String(y.at || '').localeCompare(String(x.at || '')))
    .forEach((r) => {
      const k = r.case_key || r.shifra || '';
      if (k && !seen.has(k)) seen.set(k, { ...r, events: 0 });
      if (k) seen.get(k).events += 1;
    });
  CARDS = [...seen.values()];
  CARDS_Q = '';
  CARDS_LIMIT = 60;
  const last = CARDS[0] ? fmtDay(String(CARDS[0].at || '').slice(0, 10)) : '';
  setView(`
    <p class="muted">${t('cards.why')}</p>
    ${CARDS.length ? `<div class="cards-head">${mini('kartky', 52)}<div>
      <b>${esc(t('cards.sum').replace('{n}', CARDS.length))}</b>
      ${last ? `<small class="muted">${esc(t('cards.last').replace('{d}', last))}</small>` : ''}</div>
      <input id="cards-q" data-act="cards.find" data-live="1" placeholder="${esc(t('cards.find'))}"></div>` : ''}
    <div class="dash-box" id="cards-list"></div>`);
  drawCards();
};

let CARDS = [];
let CARDS_Q = '';
let CARDS_LIMIT = 60;

function drawCards() {
  const box = el('cards-list');
  if (!box) return;
  if (!CARDS.length) { box.innerHTML = emptyMini('kartky', t('cards.none')); return; }
  const q = CARDS_Q.trim().toLowerCase();
  const all = q ? CARDS.filter((r) => `${r.shifra || ''} ${r.case_key || ''} ${r.title || ''}`.toLowerCase().includes(q)) : CARDS;
  const rows = all.slice(0, CARDS_LIMIT).map((r) => `<div class="lrow">
      <div><b class="mono">${shifraCell(r)}</b>
        <small class="muted">${pill(r.event === 'pack' ? 'ok' : 'info', tOr(`cards.ev.${r.event}`, r.event))}
          ${esc(fmtDay(String(r.at || '').slice(0, 10)))}${r.pages ? ` · ${esc(t('pull.pages').replace('{n}', r.pages))}` : ''}</small></div>
      ${r.case_key || r.shifra ? `<button data-act="cards.open" data-arg="${esc(r.case_key || r.shifra)}">${t('cards.card')}</button>` : ''}
    </div>`).join('');
  const more = all.length > CARDS_LIMIT
    ? `<p class="row"><button class="ghost" data-act="cards.more">${esc(t('rs.more').replace('{n}', Math.min(60, all.length - CARDS_LIMIT)))}</button>
        <span class="muted">${esc(t('rs.shown').replace('{n}', Math.min(CARDS_LIMIT, all.length)).replace('{all}', all.length))}</span></p>` : '';
  box.innerHTML = rows ? rows + more : `<p class="muted">${t('rs.nomatch')}</p>`;
}

async function openCard(key) {
  openModal({ title: key, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('share.card', { case: key });
  if (seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  const c = d.card || {};
  if (d.shifra) el('dlg-title').textContent = d.shifra;
  el('dlg-body').innerHTML = `${cardRows(c, d.frames) || `<p class="muted">${t('cards.empty')}</p>`}
    ${renderWarnings(env)}
    <p class="muted">${t('cards.edit')}</p>
    <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

/**
 * Картка справи полями: назва, роки, місця, жанр, кадри, «де кадри».
 * Доти вікно показувало сирі ключі (`doc_type`, `scans`) і JSON посилання
 * (прохід провтиків 22.10.2026). Перелік полів закритий (`share.card.FIELDS`).
 */
export function cardRows(c, frames) {
  const years = Array.isArray(c.years) ? c.years.join(c.years.length === 2 ? '–' : ', ') : c.years;
  const places = Array.isArray(c.places) ? c.places.join(', ') : c.places;
  const f = frames || {};
  const total = f.total || c.frames;
  const kadry = total ? `<span title="${esc(f.source || '')}">${esc(total)}</span>`
    : c.frames_unknown ? `${esc(t('cardf.frames.none'))} <small class="muted">${esc(c.frames_unknown)}</small>` : '';
  const s = c.scans && typeof c.scans === 'object' ? c.scans : null;
  const href = s ? safeHref(s.url) : '';
  const scans = s && href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(s.label || s.url)}</a>` : '';
  return kv([
    [t('cardf.title'), c.title ? esc(c.title) : ''],
    [t('cardf.years'), years ? esc(years) : ''],
    [t('cardf.places'), places ? esc(places) : ''],
    [t('cardf.doc_type'), c.doc_type ? esc(tOr(`ptype.${c.doc_type}`, c.doc_type)) : ''],
    [t('cardf.frames'), kadry],
    [t('cardf.scans'), scans],
  ]);
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
  'cards.find': () => { CARDS_Q = String((el('cards-q') || {}).value || ''); CARDS_LIMIT = 60; drawCards(); },
  'cards.more': () => { CARDS_LIMIT += 60; drawCards(); },
  'sprofile.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const done = busyForm(ev.target);
    const env = await callOp('share.setup', { handle: String(fd.handle || '').trim(), consent: String(fd.consent || '') });
    done();
    if (!env.ok) { boxError('sp-box', env); return; }
    toast(t('toast.saved'), { tone: 'ok' });
    closeModal(true);
  },
});
