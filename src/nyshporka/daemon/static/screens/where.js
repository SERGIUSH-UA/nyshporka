/**
 * 🧭 Де шукати рід: села, роки пошуку, архіви з фондами.
 *
 * Одна форма на два місця — крок «Рід» знайомства і «Профіль роду». Доти ці
 * поля правились лише сирим YAML, і людина, що вперше відкрила профіль, їх
 * просто не бачила (дослідник, 23.10.2026).
 *
 * 🔴 Форма авторитетна для того, що показує: прибраний рядок села зникає з
 * профілю. Поля, яких форма не знає (`eparchy`, `confession`), бере з наявного
 * запису `profile.where` — тут їх не видно, і вони не губляться.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el } from '../core/view.js';
import { ACTIONS } from '../core/registry.js';

function placeRow(p = {}) {
  const also = Array.isArray(p.also) ? p.also.join(', ') : (p.also || '');
  return `<div class="wh-row wh-place">
      <input data-k="name" value="${esc(p.name || '')}" placeholder="${esc(t('wc.f.place.ph'))}" aria-label="${esc(t('wc.f.place'))}">
      <input data-k="also" value="${esc(also)}" placeholder="${esc(t('wc.f.also.ph'))}" aria-label="${esc(t('wc.f.also'))}">
      <input data-k="uezd" value="${esc(p.uezd || '')}" placeholder="${esc(t('wc.f.uezd.ph'))}" aria-label="${esc(t('wc.f.uezd'))}">
    </div>`;
}

function archiveRow(a = {}) {
  return `<div class="wh-row wh-arch">
      <input data-k="repo" value="${esc(a.repo || '')}" list="wh-repos" placeholder="${esc(t('wc.f.repo.ph'))}" aria-label="${esc(t('wc.f.repo'))}">
      <input data-k="fond" value="${esc(a.fond || '')}" placeholder="${esc(t('wc.f.fond.ph'))}" aria-label="${esc(t('wc.f.fond'))}">
    </div>`;
}

/** Поля форми з уже записаним (`profile.show`); порожній профіль — по одному порожньому рядку. */
export function whereFields(d = {}) {
  const places = (d.places || []).length ? d.places : [{}];
  const archives = (d.archives || []).length ? d.archives : [{}];
  const y = d.years || {};
  return `<div class="wh-form" id="wh-form">
      <h3>${esc(t('wc.f.places'))}</h3><p class="muted">${esc(t('wc.f.places.why'))}</p>
      <div id="wh-places">${places.map(placeRow).join('')}</div>
      <button type="button" class="ghost sm" data-act="wh.more" data-arg="place">+ ${esc(t('wc.f.more.place'))}</button>
      <h3>${esc(t('wc.f.years'))}</h3>
      <div class="wh-row wh-years"><input id="wh-y1" type="number" min="1500" max="2100" placeholder="1800"
          value="${esc(y.from || '')}" aria-label="${esc(t('wc.f.from'))}">
        <span>—</span><input id="wh-y2" type="number" min="1500" max="2100" placeholder="1920"
          value="${esc(y.to || '')}" aria-label="${esc(t('wc.f.to'))}"></div>
      <h3>${esc(t('wc.f.archives'))}</h3><p class="muted">${esc(t('wc.f.archives.why'))}</p>
      <div id="wh-archives">${archives.map(archiveRow).join('')}</div>
      <button type="button" class="ghost sm" data-act="wh.more" data-arg="archive">+ ${esc(t('wc.f.more.archive'))}</button>
      <datalist id="wh-repos"></datalist>
    </div>`;
}

/** Довідник архівів: код → назва. Набрана назва («ДАХмО») записується кодом, як і вибрана зі списку. */
let REPOS = [];

/** Довідник архівів у підказку поля — після того, як форма вже на сторінці. */
export async function fillRepos() {
  const env = await callOp('archives.list', {});
  const dl = el('wh-repos');
  if (!env.ok) return;
  REPOS = (env.data || {}).archives || [];
  if (dl) dl.innerHTML = REPOS.map((a) => `<option value="${esc(a.code)}">${esc(a.label)}</option>`).join('');
}

function repoCode(v) {
  const low = v.toLowerCase();
  const hit = REPOS.find((a) => String(a.label || '').toLowerCase() === low || String(a.code || '').toLowerCase() === low);
  return hit ? hit.code : v;
}

/** Що не так із роками — словами мовою вікна; порожньо — усе гаразд. */
export function whereProblem() {
  const y1 = Number((el('wh-y1') || {}).value || 0) || null;
  const y2 = Number((el('wh-y2') || {}).value || 0) || null;
  if (!y1 && !y2) return '';
  if (!y1 || !y2 || y1 < 1500 || y2 > 2100 || y1 > y2) return t('wc.f.years.bad');
  return '';
}

function rows(boxId) {
  const box = el(boxId);
  if (!box || !box.querySelectorAll) return [];
  return Array.from(box.querySelectorAll('.wh-row')).map((r) => Object.fromEntries(
    Array.from(r.querySelectorAll('input')).map((inp) => [inp.dataset.k, String(inp.value || '').trim()])));
}

/**
 * Аргументи `profile.where` із форми.
 *
 * `all` — надіслати й порожні переліки (профіль: прибране має зникнути).
 * Без нього порожнє не надсилається (знайомство: нічого не вписали — нічого не пишемо).
 */
export function whereArgs(all = false) {
  const places = rows('wh-places').filter((p) => p.name);
  const archives = rows('wh-archives').filter((a) => a.repo).map((a) => ({ ...a, repo: repoCode(a.repo) }));
  const y1 = Number((el('wh-y1') || {}).value || 0) || null;
  const y2 = Number((el('wh-y2') || {}).value || 0) || null;
  const args = {};
  if (places.length || all) args.places = places;
  if (archives.length || all) args.archives = archives;
  if (y1 || y2) { args.years_from = y1; args.years_to = y2; }
  return args;
}

Object.assign(ACTIONS, {
  'wh.more': (_ev, elm) => {
    const box = el(elm.dataset.arg === 'place' ? 'wh-places' : 'wh-archives');
    if (box && box.insertAdjacentHTML) box.insertAdjacentHTML('beforeend', elm.dataset.arg === 'place' ? placeRow() : archiveRow());
  },
});
