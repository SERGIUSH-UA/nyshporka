/**
 * 🧭 Шапка консолі: проєкт, «Що зробити?», «Працює N», профіль Супряги.
 *
 * У шапці лише те, що потрібне з будь-якого екрана (макет хвилі 6, правка
 * дослідника 21.10.2026). Дія конкретного етапу — у рядку його екранів
 * (`nav.stageAction`), а не тут: «Завести справу» в шапці виявилась зайвою.
 */
import { t } from './strings.js';
import { callOp, apiFetch } from './net.js';
import { esc, el } from './view.js';
import { ACTIONS, OP_SCREEN } from './registry.js';
import { show, liveJobs, jobChip, jobDone, screenLabel } from './nav.js';
import { ic } from '/ui/icons.js';
import { openModal, closeModal, confirmAct } from './modal.js';
import { renderWarnings } from './view.js';
import { schemaFormHtml, schemaValues } from './schemaform.js';
import { bellMenu, fillBell } from './bell.js';
import { loadProjects, projectColor, projectChip, projectBadge } from './projects.js';

/** Відкрите меню шапки — щоб клік повз нього закривав його. */
let OPEN_MENU = null;

function closeMenus() {
  if (OPEN_MENU) {
    const m = el(OPEN_MENU);
    if (m) m.hidden = true;
    const b = document.querySelector(`[data-arg="${OPEN_MENU}"][aria-expanded]`);
    if (b) b.setAttribute('aria-expanded', 'false');
  }
  OPEN_MENU = null;
}

/**
 * Меню в межах екрана. На телефоні шапка переноситься, і меню, прив'язане до
 * правого краю чипа, виходило за лівий край: підписи різались (22.10.2026).
 */
function fitMenu(m) {
  if (!m.getBoundingClientRect || !m.style) return;
  m.style.transform = '';
  const r = m.getBoundingClientRect();
  const gap = 8;
  const room = (window.innerWidth || 0) - gap;
  let dx = 0;
  if (r.left < gap) dx = gap - r.left;
  else if (room > 0 && r.right > room) dx = Math.max(gap - r.left, room - r.right);
  if (dx) m.style.transform = `translateX(${Math.round(dx)}px)`;
}

// ── проєкт ───────────────────────────────────────────────────────────────────
/** Майстерня, проєкти й поточний — з `/api/projects` (той самий, що й до хвилі 7). */
let PROJECTS = null;

/**
 * Кнопка проєкту. Один простір без Майстерні — кнопки немає: консоль виглядає
 * так само, як до Майстерні.
 *
 * 🔴 Назва проєкту видна завжди, а не в закритому списку: людина мусить
 * бачити, в якому роді працює, ще до першого кліку — чужі висновки в
 * чужому проєкті коштують дорожче за зайвий рядок у шапці.
 */
async function fillProject() {
  const box = el('proj-box');
  if (!box) return;
  PROJECTS = await loadProjects();
  if (!Array.isArray(PROJECTS?.projects)) return;
  const many = PROJECTS.projects.length + (PROJECTS.hub_only ? 1 : 0);
  if (many < 2 && !PROJECTS.hub_only) return;
  const cur = PROJECTS.current ?? PROJECTS.hub_id;
  const mine = PROJECTS.projects.find((p) => p.id === cur);
  const kind = el('proj-k');
  const name = el('proj-v');
  if (kind) kind.textContent = mine ? t(`np.kind.${mine.kind === 'order' ? 'order' : 'family'}`) : t('project.hub.kind');
  if (name) name.textContent = mine ? (mine.name || mine.id) : t('project.hub.none');
  box.classList.toggle('in-hub', !mine);
  // Кружок зі знаком роду — поруч із назвою, а не замість неї: колір лише
  // підтримує напис (правила інтерфейсу, 22.10.2026).
  const bdg = el('proj-badge');
  if (bdg) bdg.innerHTML = mine ? projectBadge(mine) : '<span class="pj-badge pj-hub">⌂</span>';
  // Колір проєкту — на крапці перемикача й смузі шапки: у чужому роді людина
  // має це бачити ще до першого кліку.
  const color = mine ? projectColor(mine) : '';
  const st = document.documentElement && document.documentElement.style;
  if (st && st.setProperty) {
    if (color) st.setProperty('--proj-color', color);
    else if (st.removeProperty) st.removeProperty('--proj-color');
  }
  box.hidden = false;
}

function projectMenu() {
  const p = PROJECTS || { projects: [] };
  const cur = p.current ?? p.hub_id;
  // Кружок кольору зі знаком — щоб і серед десятка проєктів свій знаходився оком.
  const row = (id, name, sub, badge = '') => `<button type="button" data-act="project.go" data-arg="${esc(id)}"${
    id === cur ? ' aria-current="true"' : ''}>${badge}<span>${esc(name)}<small>${esc(sub)}</small></span></button>`;
  return (p.hub_only ? row(p.hub_id, t('project.hub'), t('project.hub.why')) + '<div class="sep"></div>' : '')
    + p.projects.map((x) => row(x.id, x.name || x.id,
      t(`np.kind.${x.kind === 'order' ? 'order' : 'family'}`), projectBadge(x))).join('')
    + (p.hub_only ? `<div class="sep"></div><button type="button" data-act="nav" data-arg="newproject"><span>${
      t('stage.act.newproject')}</span></button>` : '');
}

// ── робота ───────────────────────────────────────────────────────────────────
function jobsMenu() {
  const jobs = liveJobs();
  const rows = jobs.map((j) => `<div class="hm-row"><b>${esc(j.title || j.kind)}</b>
      ${j.project ? projectChip(j.project) : ''} ${jobChip(j)}</div>`).join('');
  return `${rows || `<p class="muted">${t('jobs.none')}</p>`}<div class="sep"></div>
    <button type="button" data-act="nav" data-arg="jobs"><span>${t('jobs.all')}</span></button>`;
}

// ── Супряга ──────────────────────────────────────────────────────────────────
/** Профіль і обмін — приватні читання (токен вкладки), без мережі. */
let ME = null;

async function fillMe() {
  const chip = el('me-chip');
  if (!chip) return;
  const [prof, stats] = await Promise.all([
    callOp('share.setup', { show: true }), callOp('share.stats', {})]);
  // Секцію Супряги вимкнено або профілю не прочитати — кружка просто немає.
  if (!prof.ok) return;
  const p = (prof.data || {}).profile || {};
  const local = ((stats.ok && stats.data) || {}).local || {};
  ME = { handle: p.handle || '', packed: (local.packed || {}).cases || 0,
    taken: (local.imported || {}).cases || 0, consent: (prof.data || {}).consent_text || '' };
  const av = el('me-av');
  if (av) av.textContent = initials(ME.handle);
  const name = el('me-t');
  if (name) name.textContent = ME.handle || t('me.anon');
  chip.hidden = false;
}

function initials(handle) {
  const parts = String(handle || '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '·';
  return parts.slice(0, 2).map((w) => w[0].toUpperCase()).join('');
}

/**
 * Меню Супряги: хто ви в спільноті й що з нею робити — з поясненням.
 *
 * 🔴 «Віддати» й «Взяти» без слова «Супряга» читались як дії над чимось
 * своїм, і було незрозуміло, що це спільний пул (дослідник, 22.10.2026).
 * Тому шапка меню каже, що таке Супряга, а кожен пункт — що він робить.
 */
function meMenu() {
  const m = ME || {};
  const item = (screen, icon, title, why) => `<button type="button" class="hm-item" data-act="nav"
      data-arg="${screen}">${ic(icon, 'ic-o')}<span><b>${esc(t(title))}</b><small>${esc(t(why))}</small></span></button>`;
  return `<div class="hm-head hm-me"><span class="avatar">${esc(initials(m.handle))}</span>
      <span><b>${esc(m.handle || t('me.anon'))}</b>
      <small>${esc(t('me.stats').replace('{p}', m.packed || 0).replace('{i}', m.taken || 0))}</small></span></div>
    <p class="hm-why">${esc(t('me.pool.why'))}</p>
    ${item('give', 'upload', 'me.give', 'me.give.why')}
    ${item('pull', 'download', 'me.take', 'me.take.why')}
    ${item('cards', 'tag', 'nav.cards', 'me.cards.why')}
    <div class="sep"></div>
    ${item('sprofile', 'hand', 'nav.sprofile', 'me.profile.why')}
    ${m.consent ? `<p class="hm-why">${esc(t('me.consent').replace('{c}', m.consent))}</p>` : ''}
    <a class="hm-link" href="https://nyshporka.online/" target="_blank" rel="noopener">${ic('link', 'ic-o')}<span>${
      t('me.portal')} ↗</span></a>`;
}

// ── «Що зробити?» ────────────────────────────────────────────────────────────
/**
 * Палітра дій — консольний `nysh ops find`.
 *
 * 🔴 Дія без екрана не зникає з видачі: вона показується з командою
 * терміналу. Інакше пошук відповідав би «нічого», хоча дія є — той самий
 * хибний нуль, проти якого стоїть уся Нишпорка.
 */
function openAsk() {
  openModal({
    title: t('ask.title'),
    body: `<input id="ask-q" class="ask-q" data-act="ask.find" data-live="1" autocomplete="off"
        placeholder="${t('ask.ph')}" aria-label="${t('ask.ph')}">
      <div id="ask-hits" class="ask-hits"><p class="muted">${t('ask.hint')}</p></div>`,
  });
  const q = el('ask-q');
  if (q && q.focus) q.focus();
}

let ASK_SEQ = 0;

async function askFind() {
  const q = (el('ask-q') || {}).value || '';
  const box = el('ask-hits');
  if (!box) return;
  if (!q.trim()) { box.innerHTML = `<p class="muted">${t('ask.hint')}</p>`; return; }
  const seq = ++ASK_SEQ;
  let got = null;
  try {
    const res = await apiFetch(`/api/ops/find?q=${encodeURIComponent(q)}`);
    if (res.ok) got = await res.json();
  } catch { /* мережі немає — нижче скажемо це */ }
  if (seq !== ASK_SEQ || !el('ask-hits')) return;
  const hits = (got && got.hits) || [];
  if (!got) { box.innerHTML = `<p class="warn">${t('common.error')}</p>`; return; }
  box.innerHTML = hits.length ? hits.map((h) => {
    const scr = h.screen || OP_SCREEN[h.name] || '';
    // Дія з екраном — куди поведе кнопка; команда терміналу — лише для дії, яку
    // інакше як командою чи формою не зробити (людина не читає `nysh op …`).
    const sub = scr ? `<small class="muted">→ ${esc(screenLabel(scr))}</small>`
      : `<small class="mono">nysh ${esc(String(h.cli || '').replace(/^nysh\s+/, ''))}</small>`;
    return `<div class="ask-hit"><div><b>${esc(h.when || h.summary)}</b>
        ${sub}</div>
      ${scr ? `<button type="button" data-act="ask.go" data-arg="${esc(scr)}">${t('ask.open')}</button>`
    : `<button type="button" data-act="ask.form" data-arg="${esc(h.name)}">${t('ask.form')}</button>`}</div>`;
  }).join('') : `<p class="muted">${t('ask.none')}</p>`;
}

// ── «Усі дії»: форма зі схеми ───────────────────────────────────────────────
/** Каталог `/api/ops` — один запит на вкладку. */
let OPS = null;

async function opsCatalog() {
  if (OPS) return OPS;
  try {
    const res = await apiFetch('/api/ops');
    if (res.ok) OPS = ((await res.json()).ops || []);
  } catch { /* без каталогу форма скаже, що схеми немає */ }
  return OPS || [];
}

/** Дія, яку форма зараз показує. */
let FORM_OP = null;

/**
 * Форма дії без екрана. Дії, якої консоль не показує (не `gui` чи вимкнена
 * секція), — лише команда терміналу: форма не обіцяє того, що сервер відмовить.
 */
async function openForm(name) {
  const op = (await opsCatalog()).find((o) => o.name === name);
  FORM_OP = op || null;
  if (!op) {
    openModal({ title: name, body: `<p class="muted">${t('ask.cli')}</p>
      <p class="mono">nysh op ${esc(name)} --help</p>` });
    return;
  }
  openModal({ title: op.when || op.summary || name, body: `<form data-act="ask.run" id="ask-form">${schemaFormHtml(op.schema)}
      <div class="row dlg-acts"><button type="submit" class="${op.mutates ? 'danger' : 'primary'}">${t('ask.run')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
    </form><div id="ask-out"></div>` });
}

/** Виконати дію з форми: `mutates` — після підтвердження, `long` — роботою. */
async function runForm(ev) {
  const op = FORM_OP;
  if (!op) return;
  const form = ev.target;
  const fd = new FormData(ev.target);
  const args = schemaValues(op.schema, (n) => fd.get(n),
    (n) => { const b = form.querySelector(`[name="${n}"]`); return !!(b && b.checked); });
  // 🔴 І довга дія теж: постановка в чергу — уже зміна стану (зайнятий
  // процесор, карта, журнал робіт), як і вважає сервер (`require_token`).
  if (op.mutates || op.long) {
    const yes = await confirmAct({ title: op.when || op.summary || op.name, text: t('ask.run.why'),
      rows: Object.entries(args).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v)]),
      okLabel: t('ask.run'), danger: true });
    if (!yes) return;
    openModal({ title: op.name, body: '<div id="ask-out"></div>' });
  }
  const out = () => el('ask-out');
  if (out()) out().innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  // Ім'я дії — змінною: ця форма не є входом жодної окремої дії.
  let env = await callOp(op.name, args);
  if (env.ok && op.long && (env.data || {}).job_id) {
    const job = await jobDone(env.data.job_id, (j) => { if (out()) out().innerHTML = jobChip(j); });
    env = job.state === 'done' ? { ok: true, data: job.result, warnings: job.warnings || [] }
      : { ok: false, error: job.error || t('job.failed') };
  }
  if (!out()) return;
  out().innerHTML = env.ok
    ? `<p class="ok-line">${t('ask.done')}</p>${renderWarnings(env)}
      <details><summary>${t('ask.data')}</summary><pre>${esc(JSON.stringify(env.data, null, 2))}</pre></details>`
    : `<p class="warn">${esc(env.error || t('common.error'))}</p>${renderWarnings(env)}`;
}

// ── дії ──────────────────────────────────────────────────────────────────────
Object.assign(ACTIONS, {
  /** Меню шапки: проєкт, робота, профіль. Друге відкриття закриває. */
  'menu.toggle': (ev, elm) => {
    if (ev && ev.stopPropagation) ev.stopPropagation();
    const id = elm.dataset.arg;
    const was = OPEN_MENU === id;
    closeMenus();
    if (was) return;
    const m = el(id);
    if (!m) return;
    // Меню ⚙ стоїть у розмітці (мова, тема): його вміст не перебудовується.
    if (id !== 'set-menu') {
      m.innerHTML = id === 'proj-menu' ? projectMenu() : id === 'jobs-menu' ? jobsMenu()
        : id === 'bell-menu' ? bellMenu() : meMenu();
    }
    m.hidden = false;
    fitMenu(m);
    elm.setAttribute('aria-expanded', 'true');
    OPEN_MENU = id;
  },
  'ask.open': () => { closeMenus(); openAsk(); },
  'ask.find': () => askFind(),
  'ask.go': (_ev, elm) => { closeModal(); show(elm.dataset.arg); },
  'ask.form': (_ev, elm) => openForm(elm.dataset.arg),
  'ask.run': (ev) => { ev.preventDefault(); return runForm(ev); },
  'modal.close': () => closeModal(false),
  'modal.ok': () => closeModal(true),
});

/** Клік повз відкрите меню закриває його; `/` відкриває «Що зробити?». */
function wire() {
  document.addEventListener('click', (ev) => {
    if (!OPEN_MENU) return;
    const inside = ev.target.closest && ev.target.closest('.hmenu');
    if (!inside) closeMenus();
    // Перелік мов — теж `data-act`, але клік лише розкриває його: закрити меню
    // тут означало б забрати перелік з-під пальця.
    // Тема теж лишає меню відкритим: її перемикають кілька разів поспіль.
    else if (ev.target.closest('.hmenu-pop [data-act]:not(select):not(#theme-btn)')) closeMenus();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeMenus();
    const tag = (ev.target.tagName || '').toLowerCase();
    if (ev.key === '/' && !['input', 'textarea', 'select'].includes(tag)
        && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
      ev.preventDefault();
      openAsk();
    }
  });
}

export function fillHeader() {
  wire();
  fillProject();
  fillMe();
  fillBell();
}

