/**
 * ✍️ Розмітка — ручні мітки рядків для навчання Писаря.
 *
 * Робота людини тут одна: подивитись на смужку і надрукувати те, що на ній.
 * Боксів малювати не треба — кропи вже нарізані з прогону. Тому весь екран
 * побудовано навколо швидкості: клавіатура-first на ПК, великі кнопки й свайп
 * на телефоні, збереження фоном без блокування переходу, префетч наступних
 * кропів, автодоповнення з уже введених фраз.
 *
 * 🔴 Чернетка показується ПОСЛОВНО з підсвіткою: слово, якого немає в жодному
 * голосі рушія, — червоне. Це візуальний детектор домислу: арбітр (чи
 * злиття) міг дописати правдоподібне прізвище, якого на аркуші немає, і саме
 * такі слова людина мусить звірити на кропі, а не прийняти одним Enter.
 */
import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, boxError, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, KEYS } from '../core/registry.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';

const MODES = ['spread', 'useful', 'page', 'sequential', 'names'];
const SPECIAL = { e: 'ѣ', t: 'ъ', i: 'і', f: 'ѳ' };
/** Ширина, з якої поле фокусується саме: на телефоні клавіатура ховає кроп. */
const DESKTOP_MIN = 821;
/** Зсув свайпу, з якого жест рахується рішенням, а не дотиком. */
const SWIPE_PX = 60;

/** Стан екрана: живе між входами, бо набір і режим людина обирає раз. */
const LB = {
  set: '', mode: 'spread', page: '', blank: false,
  queue: [], i: -1, srcs: [], ids: [],
  cache: new Map(), zoom: 0, panel: false, panelZoom: 1,
  t0: 0, sets: [],
};

SCREENS.label = async () => {
  const gen = curGen();
  const seed = ST.label || {};
  if (seed.set) LB.set = seed.set;
  ST.label = null;
  setView(`
    <h2>${ic('pencil-line')} ${t('nav.label')}</h2>
    <p class="muted">${t('label.why')}</p>
    <form class="row lb-pick" data-act="label.start">
      <select name="set" id="lb-set"></select>
      <select name="mode" id="lb-mode">${MODES.map((m) =>
    `<option value="${m}"${m === LB.mode ? ' selected' : ''}>${t(`label.mode.${m}`)}</option>`).join('')}</select>
      <input name="page" id="lb-pagein" placeholder="${t('label.page')}" value="${esc(LB.page)}">
      <label class="lbl-mini"><input type="checkbox" name="blank"${LB.blank ? ' checked' : ''}> ${t('label.blank')}</label>
      <button type="submit">${t('label.start')}</button>
    </form>
    <div id="lb-stats" class="muted"></div>
    <div id="lb-work"></div>`);
  const env = await callOp('train.sets', { all: false });
  if (!alive(gen)) return;
  if (!env.ok) { boxError('lb-work', env); return; }
  LB.sets = env.data.sets || [];
  const sel = el('lb-set');
  sel.innerHTML = LB.sets.map((s) =>
    `<option value="${esc(s.name)}"${s.name === LB.set ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
  if (!LB.sets.length) {
    el('lb-work').innerHTML = `<p class="muted">${t('sets.none')}</p>`;
    return;
  }
  if (!LB.set) LB.set = LB.sets[0].name;
  // Посів з екрана наборів — одразу в роботу, без зайвого кліку.
  if (seed.set) await ACTIONS['label.start']({ preventDefault() {}, target: el('view').querySelector('form') });
};

// ── черга ────────────────────────────────────────────────────────────────────
async function loadQueue() {
  const env = await callOp('train.queue', { name: LB.set, mode: LB.mode, page: LB.page,
    include_blank: LB.blank });
  if (!env.ok) { boxError('lb-work', env); return false; }
  const d = env.data;
  LB.queue = d.items || [];
  LB.srcs = d.draft_srcs || [];
  LB.ids = d.draft_ids || [];
  LB.i = -1;
  LB.cache.clear();
  el('lb-stats').innerHTML = `${t('label.queue')}: <b>${d.n_queue}</b> · `
    + `${t('label.done')}: <b>${d.n_done}</b> ${t('label.of')} ${d.n_total}`
    + renderWarnings(env);
  return true;
}

function key(it) { return `${it.page}:${it.idx}`; }

/** Рядок із кешу або з сервера; кеш і є префетч. */
async function fetchLine(it) {
  const k = key(it);
  if (!LB.cache.has(k)) {
    LB.cache.set(k, callOp('train.line', { name: LB.set, page: it.page, idx: it.idx }));
  }
  return LB.cache.get(k);
}

function prefetch() {
  for (let j = LB.i + 1; j <= LB.i + 3 && j < LB.queue.length; j += 1) fetchLine(LB.queue[j]);
}

// ── слова: підсвітка домислу ─────────────────────────────────────────────────
function tokens(s) { return String(s || '').toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean); }

function sim(a, b) {
  if (a === b) return 1;
  const m = a.length; const n = b.length;
  if (!m || !n) return 0;
  const prev = new Array(n + 1).fill(0).map((_, j) => j);
  for (let i = 1; i <= m; i += 1) {
    let left = i;
    for (let j = 1; j <= n; j += 1) {
      const cur = Math.min(prev[j] + 1, left + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev[j - 1] = left; left = cur;
    }
    prev[n] = left;
  }
  return 1 - prev[n] / Math.max(m, n);
}

/**
 * Чернетка пословно. `new` — слова, яких немає в жодному голосі рушія (домисел
 * арбітра або злиття), `fix` — є, але в іншій формі. Голос, що показується,
 * порівнюється з РЕШТОЮ голосів, тож на наборі з одним голосом підсвітки
 * немає — і це правильно: порівнювати нема з чим.
 */
function wordsHtml(draft, others) {
  const pool = others.flatMap(tokens);
  return String(draft || '').split(/(\s+)/).map((w) => {
    if (!w.trim()) return esc(w);
    const low = w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
    if (!low || !pool.length) return esc(w);
    let best = 0;
    for (const p of pool) best = Math.max(best, sim(low, p));
    const cls = best >= 0.99 ? '' : (best >= 0.6 ? 'fix' : 'new');
    return cls ? `<span class="w ${cls}">${esc(w)}</span>` : esc(w);
  }).join('');
}

// ── показ рядка ──────────────────────────────────────────────────────────────
function bestDraft(d) {
  // Злиття арбітрів — найкраща чернетка, якщо є; інакше перший непорожній голос.
  const mi = LB.ids.indexOf('merge');
  if (mi >= 0 && d.drafts[mi]) return d.drafts[mi];
  return d.drafts.find((x) => x) || '';
}

async function showLine() {
  const it = LB.queue[LB.i];
  const work = el('lb-work');
  if (!it) {
    work.innerHTML = `<p class="muted">${LB.queue.length ? t('label.fin') : t('label.empty')}</p>`;
    return;
  }
  const env = await fetchLine(it);
  if (!env.ok) { boxError('lb-work', env); return; }
  const d = env.data;
  const draft = bestDraft(d);
  const saved = d.saved;
  const value = saved ? (saved.text || '') : draft;
  const ctx = (d.context || []).map((c) => `<div class="lb-ctx-row${c.cur ? ' cur' : ''}">
      <span class="mono muted">${String(c.idx).padStart(3, '0')}</span>
      ${c.cur ? '<b>·</b>' : esc(c.text || c.draft || '')}
      ${c.status ? `<span class="muted">(${esc(c.status)})</span>` : ''}</div>`).join('');
  const voices = d.drafts.map((v, k) => {
    const others = d.drafts.filter((_, j) => j !== k);
    return `<div class="lb-voice"><span class="muted">${esc(LB.srcs[k] || LB.ids[k] || k)}:</span>
      <span class="lb-vt" data-act="label.use" data-arg="${k}">${wordsHtml(v, others)}</span></div>`;
  }).join('');
  const kind = saved ? saved.kind || 'hand' : 'hand';
  work.innerHTML = `
    <div class="lb-head muted">${esc(it.page)}:${it.idx} · ${LB.i + 1}/${LB.queue.length}
      ${saved ? ` · ${t('label.saved')} (${esc(saved.status)})` : ''}
      <span class="lb-keys">${t('label.keys')}</span></div>
    <div id="lb-swipe" class="lb-swipe">
      <div class="lb-stage" id="lb-stage"><img id="lb-img" alt=""></div>
    </div>
    <div class="lb-ctx">${ctx}</div>
    <div class="lb-voices">${voices}</div>
    <div class="row lb-in-row">
      <input id="lb-in" class="lb-in" value="${esc(value)}" list="lb-sugg"
        autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="off">
      <datalist id="lb-sugg"></datalist>
      <select id="lb-kind" title="${t('label.kind')}">${['hand', 'print', 'mixed'].map((k) =>
    `<option value="${k}"${k === kind ? ' selected' : ''}>${t(`label.kind.${k}`)}</option>`).join('')}</select>
    </div>
    <div class="lb-bottom">
      <button data-act="label.save" class="lb-do">${t('label.save')}</button>
      <button data-act="label.unsure" class="lb-do">${t('label.unsure')}</button>
      <button data-act="label.skip" class="lb-do">${t('label.skip')}</button>
      <button data-act="label.back" class="lb-do">${t('label.back')}</button>
      <button data-act="label.take" title="Ctrl+Enter">${t('label.take')}</button>
      <button data-act="label.panel" aria-pressed="${LB.panel}">${t('label.panel')}</button>
      <button data-act="label.zoomin" title="PageUp">+</button>
      <button data-act="label.zoomout" title="PageDown">−</button>
    </div>
    <div id="lb-page" class="lb-page"${LB.panel ? '' : ' hidden'}></div>`;
  // Сцена гасне до onload: інакше видно попередній кроп під новим підписом.
  const stage = el('lb-stage');
  const img = el('lb-img');
  stage.classList.add('dim');
  img.onload = () => { stage.classList.remove('dim'); applyZoom(); };
  img.src = d.image;
  bindInput(d, draft);
  bindSwipe();
  LB.t0 = Date.now();
  prefetch();
  if (LB.panel) await renderPanel(it);
}

function applyZoom() {
  const img = el('lb-img');
  if (!img) return;
  img.style.height = LB.zoom ? `${LB.zoom}px` : '';
  img.style.width = LB.zoom ? 'auto' : '';
}

/** Поле вводу: клавіші живуть тут, а не в глобальному роутері — він полів не чіпає. */
function bindInput(d, draft) {
  const inp = el('lb-in');
  if (!inp) return;
  inp.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); ACTIONS['label.take'](); return; }
    if (ev.key === 'Enter' && ev.shiftKey) { ev.preventDefault(); ACTIONS['label.unsure'](); return; }
    if (ev.key === 'Enter') { ev.preventDefault(); ACTIONS['label.save'](); return; }
    if (ev.key === 'Tab' && !ev.shiftKey) { ev.preventDefault(); ACTIONS['label.skip'](); return; }
    if (ev.key === 'Escape') { ev.preventDefault(); ACTIONS['label.back'](); return; }
    if (ev.key === 'PageUp') { ev.preventDefault(); ACTIONS['label.zoomin'](); return; }
    if (ev.key === 'PageDown') { ev.preventDefault(); ACTIONS['label.zoomout'](); return; }
    if (ev.altKey && !ev.ctrlKey) {
      const k = ev.key.toLowerCase();
      if (k === 'p') { ev.preventDefault(); ACTIONS['label.panel'](); return; }
      if (SPECIAL[k]) { ev.preventDefault(); insertAtCaret(inp, SPECIAL[k]); }
    }
  });
  let timer = null;
  inp.addEventListener('input', () => {
    clearTimeout(timer);
    const q = inp.value;
    if (q.trim().length < 2) return;
    timer = setTimeout(async () => {
      const env = await callOp('train.suggest', { name: LB.set, q });
      const dl = el('lb-sugg');
      if (env.ok && dl) dl.innerHTML = (env.data.items || []).map((s) => `<option value="${esc(s)}">`).join('');
    }, 200);
  });
  inp.dataset.draft = draft;
  // Автофокус лише на десктопі: на телефоні клавіатура вискакує і ховає кроп.
  if ((globalThis.innerWidth || 0) >= DESKTOP_MIN) inp.focus();
}

function insertAtCaret(inp, ch) {
  const s = inp.selectionStart ?? inp.value.length;
  const e = inp.selectionEnd ?? s;
  inp.value = inp.value.slice(0, s) + ch + inp.value.slice(e);
  inp.selectionStart = s + ch.length;
  inp.selectionEnd = s + ch.length;
}

/** Свайп по смужці: вправо — зберегти, вліво — пропустити. Лише не-миша. */
function bindSwipe() {
  const box = el('lb-swipe');
  if (!box) return;
  let x0 = null;
  box.addEventListener('pointerdown', (ev) => {
    if (ev.pointerType === 'mouse') return;
    x0 = ev.clientX;
  });
  box.addEventListener('pointerup', (ev) => {
    if (x0 === null || ev.pointerType === 'mouse') return;
    const dx = ev.clientX - x0;
    x0 = null;
    if (dx > SWIPE_PX) ACTIONS['label.save']();
    else if (dx < -SWIPE_PX) ACTIONS['label.skip']();
  });
}

// ── сторінка з рамкою ────────────────────────────────────────────────────────
async function renderPanel(it) {
  const box = el('lb-page');
  if (!box || !it) return;
  box.hidden = false;
  box.innerHTML = `<p class="muted">${t('label.loading')}</p>`;
  const px = LB.panelZoom > 1 ? 3600 : 1800;
  const env = await callOp('train.page', { name: LB.set, page: it.page, max_px: px });
  if (!env.ok) { boxError('lb-page', env); return; }
  const d = env.data;
  const size = d.size || [1, 1];
  const boxes = Object.entries(d.boxes || {}).map(([i, b]) => {
    const cur = Number(i) === it.idx;
    return `<rect class="ln${cur ? ' on' : ''}" data-act="label.jump" data-arg="${i}"
      x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}"></rect>`;
  }).join('');
  box.innerHTML = `
    <div class="row">
      <button data-act="label.pz" data-arg="1"${LB.panelZoom === 1 ? ' class="on"' : ''}>1×</button>
      <button data-act="label.pz" data-arg="2"${LB.panelZoom === 2 ? ' class="on"' : ''}>2×</button>
      <button data-act="label.pz" data-arg="4"${LB.panelZoom === 4 ? ' class="on"' : ''}>4×</button>
    </div>
    <div class="stage-wrap lb-pw" style="width:${100 * LB.panelZoom}%">
      <img src="${d.image}" alt="">
      <svg class="stage-ov" viewBox="0 0 ${size[0]} ${size[1]}" preserveAspectRatio="none">${boxes}</svg>
    </div>`;
  const cur = box.querySelector('rect.on');
  if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'center' });
}

// ── дії ──────────────────────────────────────────────────────────────────────
async function advance(delta) {
  LB.i += delta;
  if (LB.i < 0) LB.i = 0;
  await showLine();
}

/** Збереження фоном: перехід не чекає мережі, інакше Enter упирався б у неї. */
function saveCurrent(status) {
  const it = LB.queue[LB.i];
  const inp = el('lb-in');
  if (!it || !inp) return;
  const secs = LB.t0 ? (Date.now() - LB.t0) / 1000 : 0;
  const kind = (el('lb-kind') || {}).value || 'hand';
  const text = status === 'skip' ? '' : inp.value;
  const draft = inp.dataset.draft || '';
  LB.cache.delete(key(it));
  callOp('train.save', { name: LB.set, page: it.page, idx: it.idx, text, status,
    kind, draft, secs: Math.round(secs * 10) / 10 }).then((env) => {
    if (!env.ok) boxError('lb-stats', env);
  });
}

Object.assign(ACTIONS, {
  'label.start': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    LB.set = fd.get('set') || LB.set;
    LB.mode = fd.get('mode') || 'spread';
    LB.page = fd.get('page') || '';
    LB.blank = !!fd.get('blank');
    el('lb-work').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    if (await loadQueue()) await advance(1);
  },
  'label.save': async () => { saveCurrent('ok'); await advance(1); },
  'label.unsure': async () => { saveCurrent('unsure'); await advance(1); },
  'label.skip': async () => { saveCurrent('skip'); await advance(1); },
  'label.back': async () => { await advance(-1); },
  /** Ctrl+Enter — взяти чернетку (злиття або перший голос) у поле. */
  'label.take': () => {
    const inp = el('lb-in');
    if (inp) { inp.value = inp.dataset.draft || ''; inp.focus(); }
  },
  /** Клік по голосу — взяти саме його. */
  'label.use': (_ev, elm) => {
    const inp = el('lb-in');
    if (inp) { inp.value = elm.textContent; inp.focus(); }
  },
  'label.zoomin': () => { LB.zoom = Math.min(400, (LB.zoom || (el('lb-img') || {}).naturalHeight || 60) * 1.25); applyZoom(); },
  'label.zoomout': () => { LB.zoom = Math.max(24, (LB.zoom || (el('lb-img') || {}).naturalHeight || 60) / 1.25); applyZoom(); },
  'label.panel': async () => {
    LB.panel = !LB.panel;
    const box = el('lb-page');
    if (!LB.panel) { if (box) box.hidden = true; return; }
    await renderPanel(LB.queue[LB.i]);
  },
  'label.pz': async (_ev, elm) => {
    LB.panelZoom = Number(elm.dataset.arg) || 1;
    await renderPanel(LB.queue[LB.i]);
  },
  /** Клік по рамці на сторінці — перейти до цього рядка. */
  'label.jump': async (_ev, elm) => {
    const idx = Number(elm.dataset.arg);
    const cur = LB.queue[LB.i];
    if (!cur) return;
    const at = LB.queue.findIndex((q) => q.page === cur.page && q.idx === idx);
    if (at >= 0) { LB.i = at; } else {
      LB.queue.splice(LB.i + 1, 0, { page: cur.page, idx, draft: '', drafts: [], score: 0 });
      LB.i += 1;
    }
    await showLine();
  },
});

/** Клавіші поза полем: зум і сторінка працюють і без фокуса в полі. */
KEYS.label = {
  PageUp: () => ACTIONS['label.zoomin'](),
  PageDown: () => ACTIONS['label.zoomout'](),
};
