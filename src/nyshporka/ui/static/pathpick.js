// Нишпорка — вибір шляху: гортач тек, у якому системне вікно є ДІЄЮ, а не заміною.
//
// Чому гортач завжди контейнер, а нативний діалог — кнопка в його шапці. Три
// незалежні причини, кожна з яких сама по собі закриває питання:
//
// 1. Системне вікно регулярно відкривається ПОЗАДУ браузера. Людина бачить
//    сторінку, яка ніби зависла, і жодного слова про те, що сталось. Написати
//    це слово можна тільки у власній модалці — більше нема де.
// 2. Скасувати системний діалог зі сторінки НЕМОЖЛИВО: такого API не існує.
//    Отже мусить бути видимий шлях «вибрати тут замість нього», бо інакше
//    єдиний вихід — перезавантажити вкладку.
// 3. Те, що сервер слухає петлю, НЕ доводить, що браузер на тій самій машині:
//    тунель дає рівно ту саму картину. «Сервер уміє показати вікно» і «людина
//    його побачить» — різні твердження, і друге знає лише людина.
//
// 🔴 Модуль НЕ знає ні про домен, ні про транспорт. Ні `callOp`, ні маршрутів,
// ні словника рядків: усе це приходить ззовні — міст для мережі, `labels` для
// підписів. Це не чистоплюйство: та сама тека `/ui/` віддається другій морді, у
// якої інший бекенд і інший спосіб питати сервер, і перший же прямий `fetch`
// звідси зламав би її тихо.

import { ic } from './icons.js';

const LIMIT = 200;
const DEBOUNCE = 250;
const PREF_KEY = 'nyshporka.pick.native';

//: Підписи. Дефолти живуть ТУТ, бо словник морди цьому шарові недоступний.
const DEFAULT_LABELS = {
  title: { dir: 'Виберіть теку', file: 'Виберіть файл',
           files: 'Виберіть файли', save: 'Куди зберегти' },
  ok: { dir: 'обрати цю теку', file: 'обрати файл',
        files: 'обрати обране', save: 'зберегти сюди' },
  up: 'вгору', close: 'закрити', go: 'перейти',
  path: 'шлях до теки', filter: 'пошук у цій теці', name: 'ім’я файлу',
  drives: 'Диски', places: 'Робочі місця',
  empty: 'тека порожня', denied: 'сюди не пускає система',
  loading: 'дивимось…', more: 'показати ще', selected: 'обрано',
  shown: 'показано {a} з {b} — уточніть пошук',
  frames: 'зображень', pdfs: 'pdf', dirs: 'тек',
  mk: 'нова тека', mkName: 'назва нової теки', cancel: 'скасувати',
  native: 'системне вікно', nativeOff: 'системного вікна тут немає',
  wait: 'Системне вікно відкрито.',
  waitHint: 'Воно могло вилізти ПОЗАДУ браузера — перемкніться на нього.',
  waitHere: 'не бачу вікна — вибрати тут',
  outside: 'Тека поза простором',
  outsideWhy: 'справа звідси не з’явиться ні в бібліотеці, ні в пошуку, '
    + 'доки корінь не взято під облік',
  keys: '↑↓ рух · Enter увійти · Backspace вгору · Esc закрити',
};

let BRIDGE = null;
//: Одна модалка на застосунок. Друге відкриття не плодить друге вікно — воно
//: повертає відмову «зайнято», бо два гортачі одночасно означають лише те, що
//: людина двічі клацнула кнопку.
let OPEN = null;
let uid = 0;

/** Поставити міст до файлової системи. Кличеться РАЗ на старті морди. */
export function setPathBridge(bridge) { BRIDGE = bridge || null; }

/** Чим перевірити, що міст стоїть. */
export function pathBridge() { return BRIDGE; }

/** Закрити те, що відкрито (перехід екрана, вихід зі сторінки). */
export function closePathPick(why) {
  if (!OPEN) return false;
  OPEN.finish({ ok: false, why: why || 'gone' });
  return true;
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function pref() {
  // localStorage кидає в приватному вікні й за жорсткої політики — звичка
  // людини не варта того, щоб через неї не відкривався вибір теки.
  try { return localStorage.getItem(PREF_KEY) === '1'; } catch (e) { return false; }
}
function setPref(on) {
  try { localStorage.setItem(PREF_KEY, on ? '1' : '0'); } catch (e) { /* нема — то й нема */ }
}

/**
 * Вибрати шлях. Один акт — одна відповідь.
 *
 * @param {{mode?: 'dir'|'dirs'|'file'|'files'|'save', start?: string,
 *          name?: string, patterns?: string[], purpose?: string, title?: string,
 *          labels?: object, native?: 'auto'|'never', fs?: object,
 *          showHidden?: boolean, pageSize?: number}} [opts]
 * @returns {Promise<{ok: boolean, why?: string, path?: string, paths?: string[],
 *                    outside?: object}>}
 */
export function pickPath(opts = {}) {
  const fs = opts.fs || BRIDGE;
  // 🔴 Гучно, не мовчки. Відсутній міст означає, що морду зібрали неправильно,
  // і мовчазне «нічого не сталось» тут — найдорожчий спосіб про це дізнатись.
  if (!fs || typeof fs.list !== 'function') {
    if (typeof console !== 'undefined' && console.error) {
      console.error('pathpick: міст до файлової системи не поставлено '
        + '(setPathBridge) — вибір шляху неможливий');
    }
    return Promise.resolve({ ok: false, why: 'nobridge' });
  }
  if (OPEN) {
    OPEN.focus();
    return Promise.resolve({ ok: false, why: 'busy' });
  }
  return new Promise((resolve) => { open(opts, fs, resolve); });
}

function open(opts, fs, resolve) {
  const L = { ...DEFAULT_LABELS, ...(opts.labels || {}) };
  const mode = opts.mode || 'dir';
  const many = mode === 'dirs' || mode === 'files';
  const wantFiles = mode === 'file' || mode === 'files' || mode === 'save';
  const id = 'pp' + (++uid);
  const pageSize = opts.pageSize || LIMIT;

  const root = document.createElement('div');
  root.className = 'pp';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', opts.title || L.title[mode] || L.title.dir);

  let cur = null;           // остання відповідь моста
  let rows = [];            // видимі записи
  let active = -1;
  let offset = 0;
  const chosen = new Map(); // для мультивибору: шлях → true
  let timer = null;
  let ctl = null;           // AbortController поточного лістингу
  let dialogSeq = 0;        // лічильник відповідей системного вікна
  let waiting = false;
  const wasFocused = document.activeElement;
  const prevOverflow = document.body.style.overflow;

  document.body.appendChild(root);
  document.body.style.overflow = 'hidden';

  const state = { finish, focus: () => { const b = box(); if (b && b.focus) b.focus(); } };
  OPEN = state;

  function box() { return document.getElementById(id + '-list'); }
  function el(sfx) { return document.getElementById(id + sfx); }

  function finish(res) {
    if (OPEN !== state) return;
    OPEN = null;
    if (ctl) { try { ctl.abort(); } catch (e) { /* уже нема */ } }
    clearTimeout(timer);
    // Слухач знімається В ТІЙ САМІЙ фазі, у якій вішався, — інакше він лишиться
    // жити після закриття й ковтатиме Esc у застосунку назавжди.
    window.removeEventListener('keydown', onKey, true);
    document.body.style.overflow = prevOverflow;
    root.remove();
    // `activeElement` є не в кожному середовищі — перевірка, а не віра.
    if (wasFocused && wasFocused.focus) wasFocused.focus();
    resolve(res);
  }

  // ── малювання ──────────────────────────────────────────────────────────
  function render() {
    root.innerHTML = `
      <div class="pp-box">
        <div class="pp-top">
          <button type="button" class="ctl-sm pp-up" data-do="up"
            title="${esc(L.up)}">${ic('arrow-up', 'ic-o ic-sm')}</button>
          <div class="pp-crumbs">${crumbs()}</div>
          ${nativeBtn()}
          <button type="button" class="ctl-sm pp-x" data-do="close"
            title="${esc(L.close)}">✕</button>
        </div>
        <div class="pp-body">
          <div class="pp-side">${places()}</div>
          <div class="pp-main">
            <div class="pp-tools">
              <input id="${id}-q" class="pp-filter" placeholder="${esc(L.filter)}">
              <span class="pp-count">${count()}</span>
              ${fs.mkdir && mode !== 'file' && mode !== 'files'
                ? `<button type="button" class="ctl-sm" data-do="mk">＋ ${esc(L.mk)}</button>`
                : ''}
            </div>
            <div id="${id}-list" class="pp-list" role="listbox" tabindex="0"
              aria-label="${esc(L.title[mode] || '')}">${list()}</div>
            ${cur && cur.truncated
              ? `<button type="button" class="pp-more" data-do="more">${esc(L.more)}</button>`
              : ''}
          </div>
        </div>
        ${outside()}
        <div class="pp-foot">
          <input id="${id}-path" class="pp-path" value="${esc(cur ? cur.path : '')}"
            placeholder="${esc(L.path)}">
          <button type="button" class="ctl-sm" data-do="go">${esc(L.go)}</button>
          ${mode === 'save'
            ? `<input id="${id}-name" class="pp-name" value="${esc(opts.name || '')}"
                 placeholder="${esc(L.name)}">` : ''}
          ${many ? `<span class="pp-sel">${esc(L.selected)}: ${chosen.size}</span>` : ''}
          <button type="button" class="pp-ok btn-solid go" data-do="ok">${okLabel()}</button>
        </div>
        <div class="pp-hint">${esc(L.keys)}</div>
      </div>
      ${waiting ? wait() : ''}`;
    const q = el('-q');
    if (q) q.value = lastQ;
    paint();
  }

  function crumbs() {
    if (!cur || !cur.crumbs) return '';
    return cur.crumbs.map((c, i) => `<button type="button" class="pp-crumb${
      i === cur.crumbs.length - 1 ? ' on' : ''}" data-do="crumb" data-i="${i}"
      >${esc(c.label)}</button>`).join('<span class="pp-sep">›</span>');
  }

  function places() {
    if (!cur || !cur.roots) return '';
    const groups = [['places', (r) => r.kind !== 'drive'], ['drives', (r) => r.kind === 'drive']];
    return groups.map(([key, pick]) => {
      const items = cur.roots.filter(pick);
      if (!items.length) return '';
      return `<div class="pp-side-h">${esc(L[key])}</div>` + items.map((r) => {
        const k = cur.roots.indexOf(r);
        return `<button type="button" class="pp-place is-${esc(r.kind)}${
          r.gone ? ' is-gone' : ''}" data-do="place" data-i="${k}"
          title="${esc(r.path)}${r.gone ? ' — зараз недоступна' : ''}"
          >${esc(r.label)}${r.gone ? ' ⚠' : ''}</button>`;
      }).join('');
    }).join('');
  }

  function list() {
    if (!cur) return `<div class="pp-empty">${esc(L.loading)}</div>`;
    if (cur.error) return `<div class="pp-denied">${esc(L.denied)}: ${esc(cur.error)}</div>`;
    if (!rows.length) return `<div class="pp-empty">${esc(L.empty)}</div>`;
    return rows.map((e, i) => {
      const dir = e.kind === 'dir';
      const mark = many && dir ? `<span class="pp-check">${chosen.has(e.path) ? '☑' : '☐'}</span>` : '';
      return `<div class="pp-row ${dir ? 'is-dir' : 'is-file'}${
        e.locked ? ' is-denied' : ''}${i === active ? ' on' : ''}${
        chosen.has(e.path) ? ' is-picked' : ''}"
        role="option" id="${id}-o${i}" aria-selected="${i === active}"
        data-do="row" data-i="${i}" title="${esc(e.why || e.path)}">
        ${mark}<span class="pp-ico">${dir ? '📁' : '📄'}</span>
        <span class="pp-name-t">${esc(e.name)}</span>
        ${e.note ? `<span class="pp-badge">${esc(e.note)}</span>` : ''}
        <span class="pp-meta">${esc(meta(e))}</span>
      </div>`;
    }).join('');
  }

  // 🔴 Тека справи часто тримає кадри не в собі, а в підтеці — самий лише
  // лічильник кадрів показав би там нуль, тобто повна справа виглядала б
  // порожньою. Тому коли кадрів немає, кажемо про теки.
  function meta(e) {
    if (e.locked) return e.why || '';
    if (e.kind === 'file') return e.size ? human(e.size) : '';
    const bits = [];
    if (e.frames) bits.push(`${e.frames} ${L.frames}`);
    if (e.pdfs) bits.push(`${e.pdfs} ${L.pdfs}`);
    if (!bits.length && e.subdirs) bits.push(`${e.subdirs} ${L.dirs}`);
    return bits.join(' · ');
  }

  function human(n) {
    if (n < 1024) return n + ' Б';
    if (n < 1024 * 1024) return Math.round(n / 1024) + ' КБ';
    return (n / 1048576).toFixed(1) + ' МБ';
  }

  function count() {
    if (!cur) return '';
    // Знаменник їде завжди: обрізаний список, який виглядає повним, читається
    // як уся відповідь — та сама вада, що нуль без знаменника.
    if (!cur.truncated) return cur.total ? `${cur.total}` : '';
    return esc(L.shown.replace('{a}', cur.shown + cur.offset).replace('{b}', cur.total));
  }

  function okLabel() {
    const base = L.ok[mode] || L.ok.dir;
    if (many) return `${esc(base)} (${chosen.size})`;
    if (!cur) return esc(base);
    const bits = [];
    if (cur.frames) bits.push(`${cur.frames} ${L.frames}`);
    if (cur.pdfs) bits.push(`${cur.pdfs} ${L.pdfs}`);
    return bits.length ? `${esc(base)} — ${esc(bits.join(', '))}` : esc(base);
  }

  function nativeBtn() {
    if (opts.native === 'never' || !fs.dialog) return '';
    if (cur && cur.native === false) {
      return `<span class="pp-native-off muted" title="${esc(cur.nativeWhy || '')}"
        >${esc(L.nativeOff)}</span>`;
    }
    // Без значка навмисно: у дрібному розмірі «розгорнути» читається як порожня
    // рамка й до підпису нічого не додає, зате з'їдає ширину в ряду, де крихти
    // й так обрізаються.
    return `<button type="button" class="ctl-sm pp-native${pref() ? ' on' : ''}"
      data-do="native">${esc(L.native)}</button>`;
  }

  function outside() {
    if (!cur || !cur.adopt || !cur.adopt.length) return '';
    const first = cur.adopt[0];
    return `<div class="pp-outside">⚓ <b>${esc(L.outside)}</b> — ${esc(L.outsideWhy)}
      <span class="mono">${esc(first.path)}</span>${
      first.cases ? ` (${first.cases})` : ''}</div>`;
  }

  function wait() {
    return `<div class="pp-wait"><div class="pp-wait-box">
      <b>${esc(L.wait)}</b>
      <p>${esc(L.waitHint)}</p>
      <button type="button" class="btn-solid" data-do="here">${esc(L.waitHere)}</button>
      <button type="button" class="ctl-sm" data-do="unwait">${esc(L.cancel)}</button>
    </div></div>`;
  }

  function paint() {
    const b = box();
    if (!b) return;
    b.setAttribute('aria-activedescendant', active >= 0 ? `${id}-o${active}` : '');
  }

  // ── дані ───────────────────────────────────────────────────────────────
  let lastQ = '';

  async function go(path, opt = {}) {
    if (ctl) { try { ctl.abort(); } catch (e) { /* уже нема */ } }
    ctl = typeof AbortController === 'function' ? new AbortController() : null;
    if (!opt.keepOffset) offset = 0;
    const req = {
      path: path === undefined || path === null ? (cur ? cur.path : (opts.start || '')) : path,
      want: wantFiles ? 'all' : 'dirs',
      patterns: opts.patterns || [],
      q: lastQ,
      limit: pageSize,
      offset,
      show_hidden: !!opts.showHidden,
    };
    if (!cur) render();
    let got;
    try {
      got = await fs.list(req, { signal: ctl ? ctl.signal : undefined });
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      cur = { path: req.path, parent: null, crumbs: [], roots: (cur && cur.roots) || [],
              entries: [], shown: 0, total: 0, offset: 0, truncated: false,
              error: String((e && e.message) || e) };
      rows = [];
      render();
      return;
    }
    if (OPEN !== state) return;
    cur = got || {};
    const fresh = cur.entries || [];
    rows = opt.append ? rows.concat(fresh) : fresh;
    active = rows.length ? 0 : -1;
    render();
  }

  // ── дії ────────────────────────────────────────────────────────────────
  function pick(entry) {
    if (!entry) return;
    if (entry.locked) return;
    if (entry.kind === 'dir') {
      if (many) { toggle(entry); return; }
      go(entry.path);
      return;
    }
    if (wantFiles) finish({ ok: true, mode, path: entry.path, paths: [entry.path],
                            native: false, outside: outsideInfo() });
  }

  function toggle(entry) {
    if (chosen.has(entry.path)) chosen.delete(entry.path);
    else chosen.set(entry.path, true);
    render();
  }

  function outsideInfo() {
    if (!cur || !cur.adopt || !cur.adopt.length) return null;
    return { is: true, suggest: cur.adopt };
  }

  function confirm() {
    if (many) {
      const paths = [...chosen.keys()];
      if (!paths.length) return;
      finish({ ok: true, mode, path: paths[0], paths, native: false,
               outside: outsideInfo() });
      return;
    }
    if (mode === 'save') {
      const nm = el('-name');
      const name = nm ? String(nm.value || '').trim() : '';
      if (!name) { if (nm && nm.focus) nm.focus(); return; }
      const sep = (cur.path || '').indexOf('\\') >= 0 ? '\\' : '/';
      const full = (cur.path || '').replace(/[\\/]+$/, '') + sep + name;
      finish({ ok: true, mode, path: full, paths: [full], native: false,
               outside: outsideInfo() });
      return;
    }
    if (mode === 'file') {
      const e = rows[active];
      if (e && e.kind === 'file') pick(e);
      return;
    }
    finish({ ok: true, mode, path: cur.path, paths: [cur.path], native: false,
             outside: outsideInfo() });
  }

  async function askNative() {
    if (!fs.dialog) return;
    setPref(true);
    waiting = true;
    render();
    const seq = ++dialogSeq;
    let got;
    try {
      got = await fs.dialog({ mode: mode === 'dirs' ? 'dir' : mode,
                              start: cur ? cur.path : (opts.start || ''),
                              name: opts.name || '', patterns: opts.patterns || [],
                              title: opts.title || '', purpose: opts.purpose || '' });
    } catch (e) {
      got = { state: 'error', error: String((e && e.message) || e) };
    }
    // 🔴 Пізня відповідь ВИКИДАЄТЬСЯ. Людина натиснула «не бачу вікна», обрала
    // теку тут, а через хвилину знайшла те вікно й натиснула в ньому
    // «Скасувати» — без цієї перевірки щойно обраний шлях затерло б.
    if (seq !== dialogSeq || OPEN !== state) return;
    waiting = false;
    if (got && got.state === 'picked' && got.paths && got.paths.length) {
      finish({ ok: true, mode, path: got.paths[0], paths: got.paths, native: true,
               outside: null });
      return;
    }
    if (got && got.state !== 'cancelled') {
      cur = { ...(cur || {}), error: got.why || got.error || '' };
    }
    render();
  }

  async function mkdir() {
    if (!fs.mkdir) return;
    const name = window.prompt ? window.prompt(L.mkName) : '';
    if (!name) return;
    let got;
    try {
      got = await fs.mkdir({ path: cur.path, name });
    } catch (e) {
      got = { error: String((e && e.message) || e) };
    }
    if (got && got.error) { cur = { ...cur, error: got.error }; render(); return; }
    go(got && got.path ? got.path : cur.path);
  }

  // ── події ──────────────────────────────────────────────────────────────
  function target(ev) {
    const t = ev.target;
    if (!t) return null;
    // `closest` є не в кожному середовищі — тоді читаємо сам елемент.
    if (t.closest) { const hit = t.closest('[data-do]'); if (hit) return hit; }
    return t.dataset && t.dataset.do ? t : null;
  }

  root.addEventListener('click', (ev) => {
    const hit = target(ev);
    if (!hit) return;
    const i = Number(hit.dataset.i);
    switch (hit.dataset.do) {
      case 'close': finish({ ok: false, why: 'cancel' }); break;
      case 'up': if (cur && cur.parent) go(cur.parent); break;
      case 'crumb': if (cur && cur.crumbs[i]) go(cur.crumbs[i].path); break;
      case 'place': if (cur && cur.roots[i]) go(cur.roots[i].path); break;
      case 'row': active = i; pick(rows[i]); if (!many) paint(); else render(); break;
      case 'ok': confirm(); break;
      case 'go': { const p = el('-path'); if (p) go(p.value); break; }
      case 'more': offset += pageSize; go(cur.path, { append: true, keepOffset: true }); break;
      case 'native': askNative(); break;
      case 'here': waiting = false; dialogSeq++; setPref(false); render(); break;
      case 'unwait': dialogSeq++; finish({ ok: false, why: 'cancel' }); break;
      case 'mk': mkdir(); break;
      default: break;
    }
  });

  root.addEventListener('input', (ev) => {
    const t = ev.target;
    if (!t || !t.classList || !t.classList.contains('pp-filter')) return;
    lastQ = String(t.value || '');
    clearTimeout(timer);
    // Дошук на СЕРВЕРІ: у теці з тисячами кадрів фіксована пачка в пам'яті
    // мовчки ховає більшість, і «нічого не знайшлось» стає неправдою.
    timer = setTimeout(() => go(cur ? cur.path : null), DEBOUNCE);
  });

  function move(step) {
    if (!rows.length) return;
    active = (active + step + rows.length) % rows.length;
    render();
    const row = document.getElementById(`${id}-o${active}`);
    if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
  }

  function onKey(ev) {
    if (OPEN !== state) return;
    const inField = ev.target && ev.target.classList
      && (ev.target.classList.contains('pp-path')
        || ev.target.classList.contains('pp-name')
        || ev.target.classList.contains('pp-filter'));
    const stop = () => { ev.preventDefault(); ev.stopPropagation(); };
    switch (ev.key) {
      case 'Escape':
        // 🔴 Ковтаємо подію обома руками. Інакше в одній морді спрацює роутер
        // клавіш, а в другій — ланцюжок «закрити все», і одне натискання
        // закриє заодно вікно ПІД пікером.
        stop();
        if (inField && ev.target.value) { ev.target.value = ''; return; }
        finish({ ok: false, why: 'cancel' });
        return;
      case 'ArrowDown': if (!inField) { stop(); move(1); } return;
      case 'ArrowUp': if (!inField) { stop(); move(-1); } return;
      case 'Home': if (!inField && rows.length) { stop(); active = 0; render(); } return;
      case 'End': if (!inField && rows.length) { stop(); active = rows.length - 1; render(); } return;
      case 'Backspace': if (!inField && cur && cur.parent) { stop(); go(cur.parent); } return;
      case 'ArrowRight': if (!inField) { stop(); pick(rows[active]); } return;
      case ' ':
        if (!inField && many && rows[active]) { stop(); toggle(rows[active]); }
        return;
      case 'Enter':
        stop();
        if (ev.ctrlKey) { confirm(); return; }
        if (ev.target && ev.target.classList
            && ev.target.classList.contains('pp-path')) { go(ev.target.value); return; }
        if (inField) { confirm(); return; }
        pick(rows[active]);
        return;
      default:
    }
  }

  // Слухач на ВІКНІ у фазі захоплення: подія мусить дійти сюди раніше, ніж до
  // глобальних клавіш морди.
  window.addEventListener('keydown', onKey, true);

  render();
  go(opts.start || null).then(() => {
    if (OPEN === state && pref() && fs.dialog && opts.native !== 'never'
        && cur && cur.native !== false) {
      // Той, хто вже користувався системним вікном, дістає його одразу — але
      // разом із видимою накладкою, з якої є вихід назад у гортач.
      askNative();
    }
  });
  const b = box();
  if (b && b.focus) b.focus();
}
