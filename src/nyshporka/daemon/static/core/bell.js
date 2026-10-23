/**
 * 🔔 Дзвіночок у шапці: вийшла версія, є нові моделі, сповіщення Супряги.
 *
 * Стан береться з пам'яті сервера (`notices.state`) — без мережі. Сама
 * консоль у мережу не ходить, поки людина не ввімкне перевірку в
 * Налаштуваннях (PRIVACY.md: «фонової активності немає», третій виняток
 * типово вимкнено). «Перевірити зараз» — дія людини, вона йде завжди.
 *
 * 🔴 Крапка — лише коли є що сказати. Дзвіночок, що світиться завжди, перестають
 * помічати так само, як смугу з трьохсот «перевірено» в кабінеті Супряги.
 */

import { t, LANG } from './strings.js';
import { callOp } from './net.js';
import { esc, el, mini, emptyMini } from './view.js';
import { ACTIONS } from './registry.js';
import { ST } from './state.js';
import { toast, fmtDay } from './bits.js';

/** Останній стан новин; `null` — ще не питали сервер. */
let NEWS = null;
let TIMER = null;

/** Раз на годину перечитуємо стан (сервер сам вирішує, чи пора в мережу). */
const EVERY_MS = 3600 * 1000;

export function news() { return NEWS; }

/**
 * Таймер, що не тримає процес живим (`unref` є лише в Node, у браузері — ні).
 * Без цього Node-тести фронту, які чекають природного виходу, висіли вічно на
 * щогодинному перечитуванні дзвіночка (23.10.2026).
 */
function quiet(h) {
  if (h && typeof h.unref === 'function') h.unref();
  return h;
}

/** Перший показ і далі щогодини. */
export async function fillBell() {
  await bellLoad();
  if (!TIMER) TIMER = quiet(setInterval(() => { bellLoad(); }, EVERY_MS));
}

/** Перечитати стан (або взяти готову відповідь `env`) і перемалювати крапку. */
export async function bellLoad(env) {
  const got = env || await callOp('notices.state', { lang: LANG });
  if (!got || !got.ok) return;
  NEWS = got.data || {};
  ST.news = NEWS;
  paintBadge();
  const pop = el('bell-menu');
  if (pop && !pop.hidden) pop.innerHTML = bellMenu();
  // Сервер запустив фонову перевірку й не чекав її — перечитати трохи згодом.
  if (NEWS.refreshing) quiet(setTimeout(() => { bellLoad(); }, 8000));
}

function paintBadge() {
  const n = Number((NEWS || {}).badge || 0);
  const b = el('bell-n');
  if (b) { b.hidden = !n; b.textContent = n > 9 ? '9+' : String(n); }
  const chip = el('bell-chip');
  if (chip && chip.classList) chip.classList.toggle('lit', n > 0);
  const dot = el('update-dot');
  if (dot) dot.hidden = !((NEWS || {}).newer || ((NEWS || {}).models || []).length);
}

/** «щойно», «12 хв тому», «3 год тому», далі — дата. */
export function ago(iso) {
  const ms = Date.now() - Date.parse(iso || '');
  if (!Number.isFinite(ms)) return '';
  const min = Math.round(ms / 60000);
  if (min < 1) return t('bell.ago.now');
  if (min < 60) return t('bell.ago.min').replace('{n}', min);
  if (min < 24 * 60) return t('bell.ago.h').replace('{n}', Math.round(min / 60));
  return fmtDay(String(iso).slice(0, 10));
}

/** Вміст попапа дзвіночка. */
export function bellMenu() {
  const d = NEWS || {};
  const s = d.settings || {};
  const parts = [];
  if (d.newer) {
    const top = (d.releases || [])[0] || {};
    parts.push(`<div class="bell-news">${mini('teleskop', 44)}<div>
        <b>${esc(t('bell.new').replace('{v}', d.latest))}</b>
        <small>${esc(t('bell.have').replace('{v}', d.installed))}${top.title ? ` · ${esc(top.title)}` : ''}</small>
        <button class="primary ctl-sm" data-act="nav" data-arg="update">${esc(t('bell.go'))}</button></div></div>`);
  }
  const models = d.models || [];
  if (models.length) {
    parts.push(`<div class="bell-news">${mini('kolba', 44)}<div>
        <b>${esc(t('bell.models').replace('{n}', models.length))}</b>
        <small>${esc(models.map((m) => m.label).join(' · '))}</small>
        <button class="ctl-sm" data-act="nav" data-arg="update">${esc(t('bell.models.go'))}</button></div></div>`);
  }
  const sup = d.supriaha || {};
  const items = sup.items || [];
  if (d.logged_in && s.supriaha && items.length) {
    parts.push(`<div class="hm-head"><b>${esc(t('bell.sup'))}</b>${sup.unread
      ? `<button class="ghost ctl-sm" data-act="bell.readall">${esc(t('bell.readall'))}</button>` : ''}</div>`
      + items.map((x) => `<button class="hm-item bell-item${x.read ? '' : ' unread'}${x.alert ? ' alert' : ''}"
          data-act="bell.open" data-arg="${esc(x.id)}" data-url="${esc(x.url || '')}">
          <span><b>${esc(x.title || '')}</b><small>${esc(ago(x.at))}${x.count > 1 ? ` · ×${esc(x.count)}` : ''}</small></span></button>`).join(''));
  }
  // Що вимкнено — одним рядком із переходом, без нав'язливого банера.
  const off = [];
  if (!s.updates) off.push(t('bell.off.updates'));
  if (d.logged_in && !s.supriaha) off.push(t('bell.off.sup'));
  if (!parts.length) parts.push(emptyMini('lihtar', esc(t('bell.empty'))));
  return `<div class="bell-body">${parts.join('')}</div>
    <div class="sep"></div>
    ${off.length ? `<p class="hm-why">${esc(off.join(' · '))} ·
      <button class="linkish" data-act="nav" data-arg="settings">${esc(t('bell.turnon'))}</button></p>` : ''}
    <div class="row bell-foot"><button class="ghost ctl-sm" data-act="bell.check">${esc(t('bell.check'))}</button>
      <button class="ghost ctl-sm" data-act="nav" data-arg="update">${esc(t('nav.update'))}</button></div>`;
}

Object.assign(ACTIONS, {
  /** Сповіщення Супряги: відкрити на порталі й позначити прочитаним. */
  'bell.open': async (_ev, elm) => {
    const url = elm.dataset.url || '';
    if (/^https:\/\//.test(url) && typeof window !== 'undefined' && window.open) window.open(url, '_blank', 'noopener');
    const env = await callOp('notices.read', { ids: [Number(elm.dataset.arg)], lang: LANG });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    await bellLoad();
    const pop = el('bell-menu');
    if (pop) pop.innerHTML = bellMenu();
  },
  'bell.readall': async () => {
    const env = await callOp('notices.read', { lang: LANG });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    await bellLoad();
    toast(t('bell.readall.done'), { tone: 'ok' });
  },
  /** Явна перевірка — іде й з вимкненою фоновою (людина сама натиснула). */
  'bell.check': async () => {
    const env = await callOp('notices.check', { lang: LANG });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    await bellLoad(env);
    toast(env.data && env.data.newer ? t('bell.new').replace('{v}', env.data.latest) : t('bell.checked'),
      { tone: env.data && env.data.newer ? 'info' : 'ok' });
  },
});
