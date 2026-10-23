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
import { t } from './strings.js';

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

/**
 * Мальовані значки проєктів (`[project] icon`, аркуш дослідника 23.10.2026),
 * той самий перелік і порядок, що `core/projects.py::ICONS`.
 */
export const ICONS = ['derevo', 'zamok', 'sobor', 'tserkva', 'mlyn', 'mist', 'hory', 'maietok', 'knyha',
  'suvii', 'korabel', 'hodynnyk', 'kolossia', 'kovadlo', 'korona', 'herb', 'mapa', 'koleso', 'hlechyk',
  'vynohrad', 'soniashnyk', 'berezy', 'snihy', 'maiak', 'uzberezhzhia', 'ostriv', 'zemlia'];
export const iconSrc = (icon) => `/ui/img/pj-${icon}.webp`;

/**
 * Картинки проєкту (`[project] scene`), ті самі ключі, що
 * `core/projects.py::SCENES`; порожній — село. Смуга на картці проєкту — з
 * мініатюри `sc-<ключ>-t.webp`. Картина Огляду роду — лише в тих, що мають
 * великий файл (`HERO`): решта з аркуша мініатюрами, і на всю ширину
 * Огляду вони розмиті — там тоді лишається село.
 */
export const SCENES = ['', 'doroha', 'richka', 'dub', 'hata', 'kimnata', 'kraievyd', 'arka', 'stil',
  'svitlytsia', 'arkhiv', 'lis', 'nebo', 'nich'];
const HERO = { '': 'bg-selo', doroha: 'sc-doroha', richka: 'sc-richka', dub: 'sc-dub', hata: 'bg-hata',
  kimnata: 'bg-arkhiv' };
export const sceneThumb = (s) => `/ui/img/sc-${s && SCENES.includes(s) ? s : 'selo'}-t.webp`;
export const sceneSrc = (s) => `/ui/img/${HERO[s] || HERO['']}.webp`;

/** Вибір картинки проєкту — мініатюри, радіо `scene`. */
export function scenePicker(current = '') {
  const cur = SCENES.includes(current) ? current : '';
  return `<div class="fld pj-picker"><span class="fld-l">${esc(t('np.scene'))}</span>
    <div class="sc-picks" role="radiogroup" aria-label="${esc(t('np.scene'))}">${
  SCENES.map((k) => `<label class="sc-pick" title="${esc(t(`sc.${k || 'selo'}`))}">
      <input type="radio" name="scene" value="${k}"${cur === k ? ' checked' : ''} aria-label="${esc(t(`sc.${k || 'selo'}`))}">
      <img src="${sceneThumb(k)}" alt="" loading="lazy"></label>`).join('')}</div></div>`;
}

/**
 * Кружок проєкту. Мальований значок стоїть замість літери, а колір проєкту
 * стає його обідком; без значка — знак (або перша літера) на кольорі.
 */
export function projectBadge(p) {
  const color = projectColor(p);
  const style = color ? ` style="--pj:${esc(color)}"` : '';
  if (ICONS.includes(p.icon)) {
    return `<span class="pj-badge pj-ico${color ? ' pj-ring' : ''}"${style}><img src="${iconSrc(p.icon)}" alt=""></span>`;
  }
  const mark = p.glyph || String(p.name || p.id || '?').trim().charAt(0).toUpperCase();
  return `<span class="pj-badge"${style}>${esc(mark)}</span>`;
}

/** Вибір значка у формі: «Літера» і мальовані кружки — радіо `icon`. */
export function iconPicker(current = '') {
  const cur = ICONS.includes(current) ? current : '';
  const one = (v, inner, label) => `<label class="pj-pick" title="${esc(label)}">
      <input type="radio" name="icon" value="${v}"${cur === v ? ' checked' : ''} aria-label="${esc(label)}">${inner}</label>`;
  return `<div class="fld pj-picker"><span class="fld-l">${esc(t('np.icon'))}</span>
    <div class="pj-picks" role="radiogroup" aria-label="${esc(t('np.icon'))}">${
  one('', `<span class="pj-letter">${esc(t('np.icon.abc'))}</span>`, t('np.icon.letter'))}${
  ICONS.map((k) => one(k, `<img src="${iconSrc(k)}" alt="">`, t(`pj.icon.${k}`))).join('')}</div></div>`;
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
