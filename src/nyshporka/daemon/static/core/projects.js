/**
 * 📁 Проєкти Майстерні для екранів: перелік, поточний і чип «проєкт X».
 *
 * Один запит `/api/projects` на вкладку: шапка, Бібліотека, Пошук, Роботи й
 * Хмара беруть звідси ту саму відповідь. Чип однаковий скрізь — кружок
 * кольору зі знаком і назва, — щоб чужий проєкт читався з першого погляду
 * (розд. 6.5 дизайну: знахідку з іншого проєкту людина бачить повністю, з
 * позначкою й переходом туди).
 */
import { apiFetch } from './net.js';
import { esc } from './view.js';

/** Відповідь `/api/projects` або `null`, поки не прийшла чи не вдалась. */
let DATA = null;
let LOADING = null;

/** Перелік проєктів — один запит на вкладку; повтор віддає той самий. */
export function loadProjects() {
  if (!LOADING) {
    LOADING = (async () => {
      try {
        const res = await apiFetch('/api/projects');
        if (res.ok) DATA = await res.json();
      } catch { /* без переліку чипи показують ім'я як є */ }
      return DATA;
    })();
  }
  return LOADING;
}

/** Уже отримана відповідь (синхронно) — для рядків, що малюються після `loadProjects`. */
export function projectsNow() {
  return DATA;
}

/** Id проєкту вкладки; `''` — Майстерня без проєкту. */
export function currentPid() {
  if (!DATA) return '';
  const cur = DATA.current ?? '';
  return cur === DATA.hub_id ? '' : cur;
}

/** Назва проєкту вкладки для рядків наслідку; `''` — Майстерня без проєкту. */
export function currentName() {
  const p = projectInfo(currentPid());
  return p ? (p.name || p.id) : '';
}

/** Скільки проєктів у Майстерні — зрізи «хто ще» мають сенс лише з двома. */
export function projectCount() {
  return DATA && Array.isArray(DATA.projects) ? DATA.projects.length : 0;
}

export function projectInfo(id) {
  const list = (DATA && DATA.projects) || [];
  return list.find((p) => p.id === id) || null;
}

/** Колір проєкту, якщо він справді `#rrggbb` (поле правлять і руками). */
export function projectColor(p) {
  return p && /^#[0-9a-fA-F]{6}$/.test(p.color || '') ? p.color : '';
}

/** Кружок проєкту: знак (або перша літера) на кольорі проєкту. */
export function projectBadge(p) {
  const color = projectColor(p);
  const mark = p.glyph || String(p.name || p.id || '?').trim().charAt(0).toUpperCase();
  return `<span class="pj-badge"${color ? ` style="--pj:${esc(color)}"` : ''}>${esc(mark)}</span>`;
}

/**
 * Чип проєкту за id. `link` — кнопка, що перемикає вкладку на проєкт
 * (`project.go`); `back` — екран, на який туди йти.
 * Порожній id — Майстерня (підпис без проєкту).
 */
export function projectChip(id, { link = false, back = '', hubLabel = '', compact = false } = {}) {
  if (!id) return hubLabel ? `<span class="pj-chip pj-hub">${esc(hubLabel)}</span>` : '';
  const p = projectInfo(id) || { id, name: id };
  // Стисло — лише кружок, назва в підказці: так у клітинці вміщаються й
  // десять проєктів, а не рядок назв, що розсуває таблицю.
  if (compact) return `<span class="pj-mini" title="${esc(p.name || id)}">${projectBadge(p)}</span>`;
  const inner = `${projectBadge(p)}<span>${esc(p.name || id)}</span>`;
  return link
    ? `<button type="button" class="pj-chip" data-act="project.go" data-arg="${esc(id)}"${
      back ? ` data-back="${esc(back)}"` : ''}>${inner}</button>`
    : `<span class="pj-chip">${inner}</span>`;
}

/**
 * Кілька проєктів у вузькому місці (клітинка таблиці): до `full` — чипи з
 * назвами, більше — кружки зі знаком (назва в підказці), понад `max` — «+N».
 */
export function projectChips(ids, { full = 2, max = 6 } = {}) {
  if (!ids.length) return '';
  const compact = ids.length > full;
  const shown = ids.slice(0, compact ? max : ids.length);
  const more = ids.length - shown.length;
  const names = ids.map((id) => (projectInfo(id) || { name: id }).name || id).join(', ');
  return `<span class="pj-chips${compact ? ' pj-compact' : ''}"${compact ? ` title="${esc(names)}"` : ''}>${
    shown.map((id) => projectChip(id, { compact })).join('')}${
    more ? `<span class="pj-more">+${more}</span>` : ''}</span>`;
}
