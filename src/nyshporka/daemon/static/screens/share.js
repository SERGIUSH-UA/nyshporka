/**
 * 🤝 Супряга: віддати прочитане в спільний пул, взяти чуже, мої картки, профіль.
 *
 * Запит користувачів №1 — віддача з консолі, а не лише з терміналу. Пул —
 * nyshporka.online: інші шукають у відданих справах, не читаючи їх наново.
 *
 * 🔴 Приватний проєкт не віддається: відмову ставить сама `share.push`, і
 * консоль показує її причину, а не ховає справу з переліку мовчки.
 */

import { t, tOr, tn } from '../core/strings.js';
import { callOp, staleThenFresh, staleBadge, apiFetch, TOKEN } from '../core/net.js';
import { listView } from '../core/listview.js';
import { onJob } from '../core/nav.js';
import { esc, el, setView, busy, failure, boxError, busyForm, renderWarnings, curGen, alive, fld, emptyMini, mini, safeHref } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { ST } from '../core/state.js';
import { openModal, confirmAct, closeModal, modalSeq } from '../core/modal.js';
import { kv, pill, toast, ratioBar, fmtDay } from '../core/bits.js';
import { bars as chartBars } from '/ui/chart.js';

/** Стан справи з `share.suggest` (рядок пакета) → ключ підпису. */
const STATUS = { 'готова': 'ready', 'у пулі без рамок': 'noboxes', 'неповна': 'partial',
  'без кадрів': 'noframes', 'збірна': 'multi' };
const READY = ['готова', 'у пулі без рамок'];
const stLabel = (s) => (STATUS[s] ? t(`give.st.${STATUS[s]}`) : s || '');

// ── Віддати ──────────────────────────────────────────────────────────────────
/**
 * Справи групами за архівом, плитки за станом, пошук; нічого не позначено
 * саме; липка смуга «Позначено N · сторінок · Віддати N». Віддача — робота
 * `share.give`: «справа i з n», «Зупинити», «Повторити невдалі» (дослідник,
 * 23.10.2026: 659 справ одним полотном і 589 галочок, що стояли самі).
 */
let GIVE = [];
let GIVE_LV = null;

/** Архів справи — перше слово шифри; невизначений — окремою групою. */
function giveRepo(r) {
  const s = String(r.shifra || r.case_key || '');
  const head = s.startsWith('? ') ? '' : (s.split(/[\s/]/)[0] || '');
  return head ? { id: head, label: head } : { id: '?', label: t('give.norepo') };
}

const pagesOf = (rows) => rows.reduce((a, r) => a + Number(r.pages || 0), 0);

SCREENS.give = async () => {
  const gen = curGen();
  busy(6);
  // Перелік рахується секундами, тож спершу — минула відповідь, потім свіжа
  // (`staleThenFresh`). Позначене, поки йшло оновлення, тримає сам перелік.
  const paint = (env, again) => { if (alive(gen)) paintGive(env, again); };
  const env = await staleThenFresh('share.suggest', { fast: true }, (e, _stale, again) => paint(e, again));
  // Сервер віддав МИНУЛИЙ перелік (дані змінились, свіжий рахується у фоні) —
  // перепитуємо, доки не прийде свіжий; «Оновлюю…» стоїть увесь цей час.
  // 🔴 Без `await`: екран уже намальовано, а перехід на інший екран чекає,
  // доки завершиться функція поточного, — з очікуванням опитування консоль
  // «не пускала» з «Віддати» до 15 с (замір 23.10.2026).
  giveLate(env, gen, paint);
  // Віддача, запущена раніше, ще йде — показати її хід, а не чисту сторінку.
  giveResume(gen);
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
  setView(`<p class="muted">${t('give.why')}</p>
    ${renderWarnings(env)}
    <div id="give-run"></div>
    ${GIVE.length ? '<div id="give-lv"></div>' : `<div class="dash-box">${emptyMini('zshyvok', t('give.none'))}</div>`}`, again);
  if (!GIVE.length) return undefined;
  const statuses = [...new Set(GIVE.map((r) => r.status))];
  const order = ['готова', 'неповна', 'без кадрів', 'у пулі без рамок', 'збірна'];
  statuses.sort((a, b) => (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99);
  GIVE_LV = listView(el('give-lv'), {
    id: 'give',
    rows: GIVE,
    key: (r) => r.case_key,
    text: (r) => `${r.shifra || ''} ${r.case_key || ''} ${r.title || ''}`,
    placeholder: t('give.ph'),
    chips: statuses.map((s) => ({ id: s, label: stLabel(s), test: (r) => r.status === s,
      tone: READY.includes(s) ? 'ok' : '' })),
    toggles: [{ id: 'notpool', label: t('give.notpool'), test: (r) => !Number(r.pool_n || 0) }],
    group: giveRepo,
    groupSummary: (rows) => esc(t('give.group.sum')
      .replace('{cnt}', tn('lv.n.cases', rows.length))
      .replace('{r}', rows.filter((r) => READY.includes(r.status)).length)
      .replace('{p}', pagesOf(rows).toLocaleString('uk'))),
    // «Позначити групу» бере лише готові: неповне й без кадрів людина
    // позначає сама, по одній, знаючи, що йде.
    groupPick: (r) => READY.includes(r.status),
    head: `<th>${t('give.case')}</th><th>${t('give.name')}</th><th>${t('give.pages')}</th><th>${t('give.state')}</th>`,
    cells: (r) => `<td class="mono lv-nw">${shifraCell(r, true)}</td><td>${esc(r.title || '')}</td>
      <td class="num">${esc(r.pages || 0)} / ${esc(r.frames || '?')}${ratioBar(r.pages, r.frames)}</td>
      <td>${pill(READY.includes(r.status) ? 'ok' : 'neutral', stLabel(r.status))}${Number(r.pool_n || 0)
    ? ` <small class="muted">${esc(t('give.inpool').replace('{n}', r.pool_n))}</small>` : ''}</td>`,
    select: true,
    selHint: t('give.sel.hint'),
    selSummary: (sel) => t('give.pages.n').replace('{n}', pagesOf(sel).toLocaleString('uk')),
    actions: (sel) => `<button type="button" class="primary" data-act="give.go" id="give-go"${sel.length ? '' : ' disabled'}>${
      esc(t('give.go').replace('{n}', sel.length))}</button>`,
  });
  return undefined;
}

/**
 * Шифра з невизначеним архівом приходить як «? 605-1-59». Знак питання людині
 * нічого не пояснював — тепер це мітка «архів не визначено» поруч із номером.
 */
function shifraCell(r, inGroup = false) {
  const s = String(r.shifra || r.case_key || '');
  // У групі архіву назва архіву вже стоїть у заголовку — у рядку лише номер.
  const repo = giveRepo(r).id;
  if (inGroup && repo !== '?' && s.startsWith(`${repo} `) && !s.includes('@')) return esc(s.slice(repo.length + 1));
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

// ── хід віддачі ──
/** Робота віддачі, за якою стежить екран, і що віддавали (для «Повторити»). */
let GIVE_JOB = null;

/** Знайти віддачу, що ще йде, і стежити за нею — після переходу з екрана й назад. */
async function giveResume(gen) {
  try {
    const res = await apiFetch('/api/jobs');
    if (!res.ok || !alive(gen)) return;
    const j = ((await res.json()).jobs || []).find((x) => x.kind === 'share.give'
      && (x.state === 'queued' || x.state === 'running'));
    if (j) giveWatch(j.id, j);
  } catch { /* перелік робіт — підказка, не умова */ }
}

function giveWatch(jid, first = null) {
  GIVE_JOB = jid;
  if (GIVE_LV) GIVE_LV.setBusy(true);
  const draw = (j) => {
    const box = el('give-run');
    if (!box || GIVE_JOB !== jid) return;
    box.innerHTML = giveRunBox(j);
    if (['done', 'error', 'cancelled'].includes(j.state)) {
      GIVE_JOB = null;
      if (GIVE_LV) GIVE_LV.setBusy(false);
      if (j.state === 'done') {
        const d = j.result || {};
        const ok = (d.rows || []).filter((r) => r.ok).length;
        toast(t('give.done').replace('{n}', ok).replace('{f}', (d.failed || []).length),
          { tone: (d.failed || []).length ? 'warn' : 'ok' });
        // Віддане з переліку зникає: перелік — те, що ще не віддано.
        refreshGive();
      }
    }
  };
  if (first) draw(first);
  onJob(jid, draw);
}

async function refreshGive() {
  const env = await callOp('share.suggest', { fast: true });
  if (env.ok && el('give-lv')) {
    const run = (el('give-run') || {}).innerHTML || '';
    paintGive(env, true);
    const box = el('give-run');
    if (box) box.innerHTML = run;
  }
}

function giveRunBox(j) {
  const p = j.progress || {};
  const n = Number(p.n || 0);
  const i = Number(p.i || 0);
  if (j.state === 'queued' || j.state === 'running') {
    return `<div class="card give-run">
      <p><b>${esc(n ? t('give.run.going').replace('{i}', i).replace('{n}', n) : t('give.going'))}</b>${
  p.basis && n ? ` <span class="muted mono">${esc(p.basis)}</span>` : ''}</p>
      ${ratioBar(i, n)}
      <p class="row"><button type="button" class="ghost" data-act="give.stop" data-job="${esc(j.id)}">${esc(t('give.run.stop'))}</button>
        <span class="muted">${esc(t('give.run.stop.why'))}</span></p></div>`;
  }
  if (j.state === 'error') {
    return `<div class="warn"><b>${esc(t('give.run.error'))}</b> ${esc(j.error || '')}</div>`;
  }
  const d = j.result || {};
  const rows = d.rows || [];
  const ok = rows.filter((r) => r.ok).length;
  const bad = rows.filter((r) => !r.ok);
  const ns = (d.not_started || []).length;
  const fails = bad.length ? `<details class="give-fails"><summary>${esc(t('give.run.failed').replace('{n}', bad.length))}</summary>
      <ul>${bad.map((r) => `<li><b class="mono">${esc(r.shifra || r.case)}</b> — ${esc(String(r.error || '').split('\n')[0])}</li>`).join('')}</ul></details>` : '';
  const again = bad.length || ns ? `<button type="button" data-act="give.retry"
      data-cases="${esc(JSON.stringify([...bad.map((r) => r.case), ...(d.not_started || [])]))}">${
  esc(t('give.run.retry').replace('{n}', bad.length + ns))}</button>` : '';
  return `<div class="card give-run ${bad.length ? 'give-run-bad' : 'give-run-ok'}">
    <p><b>${esc(d.stopped ? t('give.run.stopped') : t('give.run.finished'))}</b>
      ${esc(t('give.run.sum').replace('{ok}', ok).replace('{f}', bad.length).replace('{ns}', ns))}</p>
    ${fails}<p class="row">${again}</p></div>`;
}

async function giveStart(cases) {
  const env = await callOp('share.give', { cases });
  if (!env.ok) { boxError('give-run', env); return; }
  const jid = (env.data || {}).job_id;
  if (GIVE_LV) GIVE_LV.clear();
  if (jid) giveWatch(jid, { id: jid, state: 'queued', progress: { i: 0, n: cases.length } });
}

// ── Взяти ────────────────────────────────────────────────────────────────────
SCREENS.pull = async () => {
  // Прийшли з Каталогів з тим самим запитом — шукаємо одразу, не змушуючи набирати вдруге.
  const seed = (ST.pull && ST.pull.q) || '';
  ST.pull = null;
  setView(`
    <p class="muted">${t('pull.why')}</p>
    <form class="row" data-act="pull.find" id="pull-form">
      ${fld(t('pull.q'), `<input name="query" placeholder="${esc(t('pull.q.ph'))}" required autofocus
        value="${esc(seed)}">`)}
      <button type="submit">${t('pull.find')}</button>
    </form>
    <div class="dash-box" id="pull-box"><p class="muted">${t('pull.hint')}</p></div>
    <div id="pull-stats"></div>`);
  pullStats(curGen());
  const form = el('pull-form');
  if (seed && form) await ACTIONS['pull.find']({ preventDefault() {}, target: form });
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
/**
 * Журнал обміну: справа — один рядок, групи за архівом, плитки «віддано /
 * взято / за тиждень», пошук. Справ тисячі (у Майстерні — 6302 з 8354 подій),
 * тож перелік спільний (`listView`), а не стовпчик по 60.
 */
SCREENS.cards = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('share.list', { what: 'all' });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const cards = cardsOf((env.data || {}).rows || []);
  const last = cards[0] ? fmtDay(String(cards[0].at || '').slice(0, 10)) : '';
  setView(`
    <p class="muted">${t('cards.why')}</p>
    ${cards.length ? `<div class="cards-head">${mini('kartky', 52)}<div>
      <b>${esc(t('cards.sum').replace('{n}', cards.filter((r) => r.given).length))}</b>
      ${last ? `<small class="muted">${esc(t('cards.last').replace('{d}', last))}</small>` : ''}</div></div>
    <div id="cards-list"></div>` : `<div class="dash-box">${emptyMini('kartky', t('cards.none'))}</div>`}`);
  if (!cards.length) return;
  const weekAgo = new Date(Date.now() - 7 * 86400e3).toISOString().slice(0, 10);
  listView(el('cards-list'), {
    id: 'cards',
    rows: cards,
    key: (r) => r.case_key || r.shifra,
    text: (r) => `${r.shifra || ''} ${r.case_key || ''} ${r.publisher || ''}`,
    placeholder: t('cards.find'),
    chips: [
      { id: 'given', label: t('cards.ev.pack'), test: (r) => r.given, tone: 'ok' },
      { id: 'taken', label: t('cards.ev.import'), test: (r) => r.taken, tone: 'info' },
      { id: 'week', label: t('rs.lv.week'), test: (r) => String(r.at || '').slice(0, 10) >= weekAgo },
    ],
    // Архів — від сервера, за кодом у ключі справи: шифра прийнятого з Супряги
    // буває латинкою («DAZHO»), і за першим словом той самий архів двоївся.
    group: (r) => (r.archive ? { id: r.archive, label: r.archive } : giveRepo(r)),
    groupSummary: (rows) => esc(t('cards.gsum').replace('{cnt}', tn('lv.n.cases', rows.length))
      .replace('{p}', pagesOf(rows).toLocaleString('uk'))),
    head: `<th>${t('give.case')}</th><th>${t('cards.lv.event')}</th><th class="num">${t('cards.lv.pages')}</th><th></th>`,
    cells: (r) => `<td class="mono lv-nw">${shifraCell(r, true)}</td>
      <td>${pill(r.event === 'pack' ? 'ok' : 'info', tOr(`cards.ev.${r.event}`, r.event))}
        <small class="muted">${esc(fmtDay(String(r.at || '').slice(0, 10)))}${r.publisher ? ` · ${esc(r.publisher)}` : ''}</small></td>
      <td class="num">${esc(r.pages || '')}</td>
      <td class="lv-nw"><button data-act="cards.open" data-arg="${esc(r.case_key || r.shifra)}">${t('cards.card')}</button></td>`,
  });
};

/**
 * Журнал обміну → справа одним рядком з останньою подією. Подія пишеться на
 * кожне пакування й заливку, тож одна справа стояла десятками рядків (понад
 * 470 тис. знаків на сторінці, QA 23.10.2026). `given`/`taken` — чи справу
 * хоч раз віддано чи взято: остання подія цього не каже.
 */
export function cardsOf(rows) {
  const seen = new Map();
  [...rows]
    .sort((x, y) => String(y.at || '').localeCompare(String(x.at || '')))
    .forEach((r) => {
      const k = r.case_key || r.shifra || '';
      if (!k) return;
      if (!seen.has(k)) seen.set(k, { ...r, events: 0, given: false, taken: false });
      const c = seen.get(k);
      c.events += 1;
      if (r.event === 'pack') c.given = true;
      if (r.event === 'import') c.taken = true;
    });
  return [...seen.values()];
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
  'give.go': async () => {
    const rows = GIVE_LV ? GIVE_LV.selected() : [];
    if (!rows.length) return;
    if (GIVE_JOB) { toast(t('give.run.busy'), { tone: 'warn' }); return; }
    const names = rows.map((r) => r.shifra || r.case_key);
    const yes = await confirmAct({ title: t('give.confirm').replace('{n}', rows.length), text: t('give.confirm.why'),
      rows: [[t('give.case'), names.slice(0, 12).join(', ') + (names.length > 12 ? ` … +${names.length - 12}` : '')],
        [t('give.pages'), t('give.pages.n').replace('{n}', pagesOf(rows).toLocaleString('uk'))]],
      okLabel: t('give.do') });
    if (!yes) return;
    await giveStart(rows.map((r) => r.case_key));
  },
  /** «Зупинити»: розпочаті справи доходять до кінця, решта лишається не початою. */
  'give.stop': async (_ev, elm) => {
    const res = await apiFetch(`/api/jobs/${encodeURIComponent(elm.dataset.job)}/cancel`,
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    if (!res.ok) { toast(`${t('common.error')}: HTTP ${res.status}`, { tone: 'err' }); return; }
    toast(t('give.run.stopping'), { tone: 'info' });
  },
  /** Повторити те, що не вдалось або не почалось, — тим самим шляхом. */
  'give.retry': async (_ev, elm) => {
    let cases = [];
    try { cases = JSON.parse(elm.dataset.cases || '[]'); } catch { cases = []; }
    if (!cases.length) return;
    if (GIVE_JOB) { toast(t('give.run.busy'), { tone: 'warn' }); return; }
    await giveStart(cases);
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
    // 🔴 Підтвердження називає, що саме ляже: обсяг, роки, чиє й на яких умовах.
    // Доти у вікні стояла сама шифра (прохід новачка 23.10.2026).
    const rows = [[t('give.case'), r.shifra],
      [t('pull.take.pages'), String(r.pages || '?')],
      ...(r.years ? [[t('pull.take.years'), r.years]] : []),
      ...(r.publisher ? [[t('pull.take.from'), r.publisher]] : []),
      ...(r.license ? [[t('pull.take.license'), r.license]] : [])];
    const yes = await confirmAct({ title: t('pull.take.title'), text: t('pull.take.why'),
      rows, okLabel: t('pull.take') });
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
    toast(t('toast.saved'), { tone: 'ok' });
    closeModal(true);
  },
});
