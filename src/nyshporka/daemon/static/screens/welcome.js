/**
 * 👋 Знайомство: перший запуск порожньої Нишпорки.
 *
 * Мова → вигляд → помічник → перший проєкт → рід → справи (рішення дослідника
 * 23.10.2026: «хіба те, що на головній, — це перше, що треба людині?»). Поки
 * воно відкрите, бічного меню й шапки немає: людині, що вперше відкрила
 * застосунок, вони нічого не кажуть, а відволікають.
 *
 * Вигляд — «розворот» (варіант B із трьох, вибір дослідника): ліворуч мальована
 * річ кроку, його назва й пояснення, праворуч поля.
 *
 * 🔴 Мова й вигляд живуть лише в браузері (`localStorage`), тож крок мови
 * перезавантажує сторінку одразу на наступний крок. Перший проєкт так само:
 * після нього вкладка переходить у проєкт (`?p=`), і рід записується вже в
 * його профіль. Крок у адресі (`?step=`), а не в хеші: навігація хеш переписує.
 */

import { t, LANG, LANGS, DISABLED, setLang } from '../core/strings.js';
import { callOp, PROJECT } from '../core/net.js';
import { esc, el, setView, mini, boxError, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openProject, slugOf } from './project.js';
import { themeMode, setThemeMode } from '/ui/theme.js';
import { whereFields, whereArgs, whereProblem, fillRepos } from './where.js';
import { projectInfo } from '../core/projects.js';

export const DONE_KEY = 'nysh.welcome.done';
const STEPS = ['lang', 'theme', 'agent', 'project', 'family', 'cases'];
const STEP_MINI = { lang: 'globus', theme: 'lihtar', agent: 'pero', project: 'derevo',
  family: 'mapa', cases: 'viazka' };

export function welcomeDone() {
  try { return localStorage.getItem(DONE_KEY) === '1'; } catch { return false; }
}

function markDone() {
  try { localStorage.setItem(DONE_KEY, '1'); } catch { /* приватний режим — то й то */ }
}

function stepOf() {
  const m = /[?&]step=(\w+)/.exec(location.search);
  return m && STEPS.includes(m[1]) ? m[1] : 'lang';
}

/** Інший крок без перезавантаження: адреса йде за кроком, щоб «Назад» браузера не губив його. */
function go(step) {
  const q = new URLSearchParams(location.search);
  q.set('step', step);
  history.replaceState(null, '', `${location.pathname}?${q.toString()}#welcome`);
  paint(step);
  // Новий крок — з початку: на телефоні «Далі» стоїть унизу довгого кроку.
  const main = document.querySelector('main');
  if (main) main.scrollTop = 0;
  if (typeof window.scrollTo === 'function') window.scrollTo(0, 0);
}

/** Після знайомства — у проєкт (якщо вже є) на потрібний екран. */
function leave(screen = 'home') {
  markDone();
  document.body.classList.remove('welcome-on');
  const q = new URLSearchParams(location.search);
  q.delete('step');
  location.href = `${location.pathname}${q.toString() ? `?${q.toString()}` : ''}#${screen}`;
}

let AGENT = null;

// ── кроки ────────────────────────────────────────────────────────────────────
function langBody() {
  return `<div class="wc-langs">${LANGS.filter(([c]) => !DISABLED.includes(c)).map(([c, name]) => `
    <button type="button" class="wc-lang${c === LANG ? ' on' : ''}" data-act="wc.lang" data-arg="${c}"
      lang="${c}">${esc(name)}</button>`).join('')}</div>`;
}

function themeBody() {
  const m = themeMode();
  const card = (mode) => `<button type="button" class="wc-theme${m === mode ? ' on' : ''}" data-act="wc.theme"
      data-arg="${mode}"><span class="wc-swatch wc-sw-${mode}" aria-hidden="true"><i></i><i></i><i></i></span>
      <b>${esc(t(`wc.theme.${mode}`))}</b><small>${esc(t(`wc.theme.${mode}.why`))}</small></button>`;
  return `<div class="wc-themes">${card('light')}${card('dark')}${card('auto')}</div>`;
}

function agentBody() {
  const doc = `https://nyshporka.online/docs/${LANG === 'uk' ? '' : `${LANG}/`}install/#pomichnyk`;
  const status = AGENT === null ? ''
    : AGENT ? `<p class="ok-line">✓ ${esc(t('wc.agent.yes'))}</p>`
      : `<p class="muted">${esc(t('wc.agent.no'))}</p>`;
  return `<ol class="wc-howto">
      <li>${esc(t('wc.agent.s1'))}</li>
      <li>${esc(t('wc.agent.s2'))} <code>nysh skills install</code></li>
      <li>${esc(t('wc.agent.s3'))}</li></ol>
    <p><a href="${esc(doc)}" target="_blank" rel="noopener">${esc(t('wc.agent.doc'))} ↗</a></p>
    <div id="wc-agent">${status}</div>
    <p><button type="button" class="ghost" data-act="wc.agent">${esc(t('wc.agent.check'))}</button></p>`;
}

function projectBody() {
  // Проєкт уже заведено (повернулись «Назад» із кроку «Рід»): вдруге його не
  // створити — тека є, — тож крок лише називає його й веде далі.
  if (PROJECT) {
    const name = (projectInfo(PROJECT) || {}).name || PROJECT;
    return `<p>${esc(t('wc.p.made').replace('{name}', name))}</p><div id="wc-box"></div>`;
  }
  return `<form id="wc-form" data-act="wc.project" class="wc-form">
      <div class="wc-kinds" role="radiogroup">
        <label class="wc-kind"><input type="radio" name="kind" value="family" checked data-act="wc.kind">
          <b>${esc(t('wc.kind.family'))}</b><small>${esc(t('wc.kind.family.why'))}</small></label>
        <label class="wc-kind"><input type="radio" name="kind" value="order" data-act="wc.kind">
          <b>${esc(t('wc.kind.order'))}</b><small>${esc(t('wc.kind.order.why'))}</small></label>
      </div>
      ${fld(t('wc.p.title'), `<input name="title" id="wc-title" required placeholder="${esc(t('wc.p.title.ph'))}">`)}
      ${fld(t('wc.p.surname'), `<input name="surname" id="wc-surname" required placeholder="${esc(t('wc.p.surname.ph'))}">`)}
      ${fld(t('wc.p.variants'), `<input name="variants" id="wc-variants" placeholder="${esc(t('wc.p.variants.ph'))}">`)}
      <div id="wc-box"></div>
    </form>`;
}

function familyBody() {
  if (!PROJECT) return `<p class="muted">${esc(t('wc.f.noproject'))}</p>`;
  return `<div id="wc-where">${whereFields()}</div><div id="wc-box"></div>`;
}

function casesBody() {
  const door = (act, icon, title, why) => `<button type="button" class="wc-door" data-act="wc.door" data-arg="${act}">
      ${mini(icon, 56)}<span><b>${esc(t(title))}</b><small>${esc(t(why))}</small></span></button>`;
  return `<div class="wc-doors">
      ${door('scans', 'teka', 'wc.c.scans', 'wc.c.scans.why')}
      ${door('find', 'lupa', 'wc.c.find', 'wc.c.find.why')}
      ${door('pull', 'kartky', 'wc.c.pull', 'wc.c.pull.why')}
      ${door('sample', 'knyha', 'wc.c.sample', 'wc.c.sample.why')}
    </div><div id="wc-box"></div>`;
}

const BODY = { lang: langBody, theme: themeBody, agent: agentBody, project: projectBody,
  family: familyBody, cases: casesBody };

function acts(step) {
  const back = step === 'lang' ? '' : `<button type="button" class="ghost" data-act="wc.back">← ${esc(t('wc.back'))}</button>`;
  const skip = ['agent', 'project', 'family'].includes(step)
    ? `<button type="button" class="ghost" data-act="wc.skip">${esc(t('wc.skip'))}</button>` : '';
  const next = step === 'cases'
    ? `<button type="button" class="primary" data-act="wc.door" data-arg="later">${esc(t('wc.finish'))}</button>`
    : `<button type="button" class="primary" data-act="wc.next">${esc(t('wc.next'))} →</button>`;
  return `<div class="wc-acts">${back}<span class="wc-sp"></span>${skip}${next}</div>`;
}

function paint(step) {
  document.body.classList.add('welcome-on');
  const i = STEPS.indexOf(step);
  setView(`<div class="wc wc-b">
      <div class="wc-spread">
        <div class="wc-page wc-left">${mini(STEP_MINI[step], 200, 'wc-mini')}
          <small class="wc-count">${esc(t('wc.count').replace('{i}', i + 1).replace('{n}', STEPS.length))}</small>
          <h2>${esc(t(`wc.${step}`))}</h2><p>${esc(t(`wc.${step}.why`))}</p>
          <div class="wc-bar" aria-hidden="true"><span style="width:${Math.round(((i + 1) / STEPS.length) * 100)}%"></span></div>
          <button type="button" class="wc-out" data-act="wc.out">${esc(t('wc.out'))}</button></div>
        <div class="wc-page wc-right">${BODY[step]()}${acts(step)}</div>
      </div></div>`);
  ARMED = '';
  if (step === 'family') { SNAP = JSON.stringify(whereArgs()); fillFamily(); }
}

/** Знімок форми «Рід» після малювання — щоб «Пропустити» знало, чи щось вписали. */
let SNAP = '';
/** Крок, на якому «Пропустити» вже попередило про втрату введеного. */
let ARMED = '';

function unsaved(step) {
  if (step === 'project' && !PROJECT) {
    return ['wc-title', 'wc-surname', 'wc-variants'].some((id) => String((el(id) || {}).value || '').trim());
  }
  if (step === 'family') return JSON.stringify(whereArgs()) !== SNAP;
  return false;
}

/**
 * «Пропустити» з уже вписаним — спершу попередження, і лише друге натискання
 * пропускає. Доти введене мовчки зникало (холодний прохід 23.10.2026).
 */
function guardSkip(then) {
  const step = stepOf();
  if (ARMED !== step && unsaved(step)) {
    ARMED = step;
    const box = el('wc-box');
    if (box) box.innerHTML = `<div class="warn">${esc(t('wc.skip.lose'))}</div>`;
    return;
  }
  ARMED = '';
  then();
}

/** Крок «Рід» показує вже записане — після «Назад» форма не порожня. */
async function fillFamily() {
  if (PROJECT) {
    const env = await callOp('profile.show', {});
    const d = (env.ok && env.data) || {};
    const box = el('wc-where');
    if (box && stepOf() === 'family' && ((d.places || []).length || (d.archives || []).length || d.years)) {
      box.innerHTML = whereFields(d);
      SNAP = JSON.stringify(whereArgs());
    }
  }
  fillRepos();
}

// ── збір і запис ─────────────────────────────────────────────────────────────
async function saveProject() {
  if (PROJECT) { go('family'); return; }
  const title = String((el('wc-title') || {}).value || '').trim();
  const surname = String((el('wc-surname') || {}).value || '').trim();
  if (!title || !surname) {
    const box = el('wc-box');
    if (box) box.innerHTML = `<div class="warn">${esc(t('wc.p.need'))}</div>`;
    const miss = el(title ? 'wc-surname' : 'wc-title');
    if (miss && miss.focus) miss.focus();
    return;
  }
  const k = document.querySelector('#wc-form input[name="kind"]:checked');
  const variants = String((el('wc-variants') || {}).value || '').split(',').map((s) => s.trim()).filter(Boolean);
  // Назва без жодної літери, що дає латинську теку («Łoś»), — тека з прізвища, далі «rid».
  const name = slugOf(title) || slugOf(surname) || 'rid';
  const env = await callOp('project.new', { name, kind: k ? k.value : 'family', title, surname, variants });
  if (!env.ok) { boxError('wc-box', env); return; }
  openProject(name, 'welcome', { step: 'family' });
}

async function saveFamily() {
  const bad = whereProblem();
  if (bad) { const box = el('wc-box'); if (box) box.innerHTML = `<div class="warn">${esc(bad)}</div>`; return; }
  const args = whereArgs();
  if (!Object.keys(args).length) { go('cases'); return; }
  const env = await callOp('profile.where', args);
  if (!env.ok) { boxError('wc-box', env); return; }
  go('cases');
}

SCREENS.welcome = async () => { paint(stepOf()); };

Object.assign(ACTIONS, {
  'wc.lang': (_ev, elm) => {
    setLang(elm.dataset.arg);
    const q = new URLSearchParams(location.search);
    q.set('step', 'theme');
    location.href = `${location.pathname}?${q.toString()}#welcome`;
  },
  'wc.theme': (_ev, elm) => { setThemeMode(elm.dataset.arg); paint('theme'); },
  'wc.agent': async () => {
    const env = await callOp('home.pulse', {});
    AGENT = !!(env.ok && ((env.data || {}).agent || {}).connected);
    paint('agent');
  },
  'wc.next': async () => {
    const step = stepOf();
    if (step === 'project') return saveProject();
    if (step === 'family') return saveFamily();
    return go(STEPS[STEPS.indexOf(step) + 1]);
  },
  'wc.project': async (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); return saveProject(); },
  'wc.back': () => go(STEPS[Math.max(0, STEPS.indexOf(stepOf()) - 1)]),
  // Без проєкту крок «Рід» нема куди записати — пропуск проєкту веде одразу до справ.
  'wc.skip': () => guardSkip(() => go(stepOf() === 'project' ? 'cases' : STEPS[STEPS.indexOf(stepOf()) + 1])),
  'wc.out': () => guardSkip(() => leave('home')),
  // Назва-приклад іде за видом: «Рід Сидоруків» для замовлення звучить як помилка.
  'wc.kind': (_ev, elm) => {
    const inp = el('wc-title');
    if (inp) inp.placeholder = t(elm.value === 'order' ? 'wc.p.title.ph.order' : 'wc.p.title.ph');
  },
  'wc.door': async (_ev, elm) => {
    const d = elm.dataset.arg;
    if (d === 'sample') {
      const env = await callOp('sample.install', {});
      if (!env.ok) { boxError('wc-box', env); return; }
      leave('library');
      return;
    }
    leave({ scans: 'newcase', find: 'sources', pull: 'pull', later: 'home' }[d] || 'home');
  },
});
