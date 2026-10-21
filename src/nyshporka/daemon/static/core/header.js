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
import { show, liveJobs, jobChip } from './nav.js';
import { openModal, closeModal } from './modal.js';

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
  try {
    const res = await apiFetch('/api/projects');
    if (!res.ok) return;
    PROJECTS = await res.json();
  } catch { return; }
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
  box.hidden = false;
}

function projectMenu() {
  const p = PROJECTS || { projects: [] };
  const cur = p.current ?? p.hub_id;
  const row = (id, name, sub) => `<button type="button" data-act="project.go" data-arg="${esc(id)}"${
    id === cur ? ' aria-current="true"' : ''}><span>${esc(name)}<small>${esc(sub)}</small></span></button>`;
  return (p.hub_only ? row(p.hub_id, t('project.hub'), t('project.hub.why')) + '<div class="sep"></div>' : '')
    + p.projects.map((x) => row(x.id, x.name || x.id,
      t(`np.kind.${x.kind === 'order' ? 'order' : 'family'}`))).join('')
    + (p.hub_only ? `<div class="sep"></div><button type="button" data-act="nav" data-arg="newproject"><span>${
      t('stage.act.newproject')}</span></button>` : '');
}

// ── робота ───────────────────────────────────────────────────────────────────
function jobsMenu() {
  const jobs = liveJobs();
  const rows = jobs.map((j) => `<div class="hm-row"><b>${esc(j.title || j.kind)}</b>
      ${j.project ? `<small>${esc(j.project)}</small>` : ''} ${jobChip(j)}</div>`).join('');
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

function meMenu() {
  const m = ME || {};
  return `<div class="hm-head"><b>${esc(m.handle || t('me.anon'))}</b>
      <small>${esc(t('me.stats').replace('{p}', m.packed || 0).replace('{i}', m.taken || 0))}</small>
      ${m.consent ? `<small>${esc(m.consent)}</small>` : ''}</div>
    <div class="sep"></div>
    <a class="hm-link" href="https://nyshporka.online/" target="_blank" rel="noopener">${t('me.portal')}</a>
    <button type="button" data-act="nav" data-arg="settings"><span>${t('sect.title')}</span></button>`;
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
    return `<div class="ask-hit"><div><b>${esc(h.when || h.summary)}</b>
        <small class="mono">nysh ${esc(h.cli)}</small></div>
      ${scr ? `<button type="button" data-act="ask.go" data-arg="${esc(scr)}">${t('ask.open')}</button>`
    : `<span class="muted">${t('ask.cli')}</span>`}</div>`;
  }).join('') : `<p class="muted">${t('ask.none')}</p>`;
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
    m.innerHTML = id === 'proj-menu' ? projectMenu() : id === 'jobs-menu' ? jobsMenu() : meMenu();
    m.hidden = false;
    elm.setAttribute('aria-expanded', 'true');
    OPEN_MENU = id;
  },
  'ask.open': () => { closeMenus(); openAsk(); },
  'ask.find': () => askFind(),
  'ask.go': (_ev, elm) => { closeModal(); show(elm.dataset.arg); },
  'modal.close': () => closeModal(false),
  'modal.ok': () => closeModal(true),
});

/** Клік повз відкрите меню закриває його; `/` відкриває «Що зробити?». */
function wire() {
  document.addEventListener('click', (ev) => {
    if (!OPEN_MENU) return;
    const inside = ev.target.closest && ev.target.closest('.hmenu');
    if (!inside) closeMenus();
    else if (ev.target.closest('.hmenu-pop [data-act]')) closeMenus();
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
}

