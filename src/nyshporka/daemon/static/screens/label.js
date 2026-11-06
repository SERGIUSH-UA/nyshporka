/**
 * ✍️ Розмітка — ручні мітки рядків для навчання Писаря.
 *
 * Робота людини тут одна: подивитись на смужку і надрукувати те, що на ній.
 * Боксів малювати не треба — кропи вже нарізані з прогону. Тому весь екран
 * побудовано навколо швидкості: клавіатура-first на ПК, великі кнопки
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
import { esc, el, setView, boxError, renderWarnings, curGen, alive, emptyMini } from '../core/view.js';
import { SCREENS, ACTIONS, KEYS } from '../core/registry.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';

const MODES = ['spread', 'useful', 'page', 'sequential', 'names'];
const SPECIAL = { e: 'ѣ', t: 'ъ', i: 'і', f: 'ѳ' };
/**
 * Кнопки літер під полем — для телефона, де Alt+літери немає, а розкладка має або
 * і/ї/є (українська), або ъ/ы/э (російська), і жодна — ѣ, ѳ, ѵ.
 */
const CHARS = ['ѣ', 'ъ', 'і', 'ї', 'ѳ', 'ѵ', 'ы', 'э', 'є', 'Ѣ', 'І', 'Ѳ'];
/** Ширина, з якої поле фокусується саме: на телефоні клавіатура ховає кроп. */
const DESKTOP_MIN = 821;
/** Висота кропа на телефоні: природні 50–100 px нечитні, а збільшений кроп гортається
 *  пальцем убік. Кнопки +/− міняють її, як і на ПК. */
const PHONE_H = 110;

/** Стан екрана: живе між входами, бо набір і режим людина обирає раз. */
const LB = {
  set: '', qSet: '', pack: '', packs: [], mode: 'spread', page: '', blank: false, minChars: 10, fresh: true,
  scen: '', mergedOnly: false, limit: 400, pages: [], q: null, session: 0,
  queue: [], i: -1, srcs: [], ids: [],
  cache: new Map(), zoom: 0, panel: false, panelZoom: 1,
  t0: 0, sets: [],
};

/**
 * Сценарії замість режимів-шифрів. Кожен — готовий набір параметрів черги; точні
 * значення видно й міняються під «Точні параметри».
 *  - `merge` — перевірка злиття: лише рядки, які арбітри вже звели (їх міряє
 *    `nysh train stats`), врозкид з різних сторінок, невелика пачка;
 *  - `new` — те, чого ще ніхто не зводив, з найкорисніших сторінок;
 *  - `page` — одна сторінка підряд, у порядку аркуша.
 */
const SCEN = {
  merge: { mode: 'spread', mergedOnly: true, fresh: false, limit: 25 },
  new: { mode: 'useful', mergedOnly: false, fresh: true, limit: 400 },
  page: { mode: 'page', mergedOnly: false, fresh: false, limit: 400 },
};

SCREENS.label = async () => {
  const gen = curGen();
  const seed = ST.label || {};
  if (seed.set) { LB.set = seed.set; LB.pack = ''; }
  ST.label = null;
  setView(`
    <p class="muted">${t('label.why')}</p>
    <form class="lb-pick" id="lb-ctl" data-act="label.start">
      <div class="row">
        <label class="lbl-mini">${t('label.set')}
          <select name="set" id="lb-set" data-act="label.pick"></select></label>
      </div>
      <div class="lb-scen" id="lb-scen">
        ${['merge', 'new', 'page'].map((k) => `<button type="button" class="lb-sc" data-act="label.scen" data-arg="${k}"
          id="lb-sc-${k}"><b>${t(`label.scen.${k}`)}</b><span class="muted">${t(`label.scen.${k}.hint`)}</span></button>`).join('')}
        <label class="lbl-mini lb-pgpick" id="lb-pgwrap">${t('label.page')}
          <select name="pg" id="lb-pg" data-act="label.pg"></select></label>
      </div>
      <details class="lb-more" id="lb-more">
        <summary>${t('label.more')}</summary>
        <div class="row">
          <label class="lbl-mini">${t('label.mode')}
            <select name="mode" id="lb-mode">${MODES.map((m) =>
    `<option value="${m}"${m === LB.mode ? ' selected' : ''}>${t(`label.mode.${m}`)}</option>`).join('')}</select></label>
          <label class="lbl-mini" id="lb-blank"><input type="checkbox" name="blank"${LB.blank ? ' checked' : ''}> ${t('label.blank')}</label>
          <label class="lbl-mini" id="lb-fresh"><input type="checkbox" name="fresh"${LB.fresh ? ' checked' : ''}> ${t('label.fresh')}</label>
          <label class="lbl-mini" id="lb-mo"><input type="checkbox" name="mo"${LB.mergedOnly ? ' checked' : ''}> ${t('label.merged_only')}</label>
          <label class="lbl-mini">${t('label.minchars')} <input type="number" name="minchars" min="0" max="200"
            inputmode="numeric" style="width:4.5em" value="${LB.minChars}"></label>
          <label class="lbl-mini">${t('label.limit')} <input type="number" name="limit" min="1" max="2000"
            inputmode="numeric" style="width:5.5em" value="${LB.limit}"></label>
          <button type="submit">${t('label.start')}</button>
        </div>
      </details>
    </form>
    <div id="lb-bar" class="lbq-bar" hidden></div>
    <div id="lb-stats" class="muted"></div>
    <div id="lb-work"></div>`);
  // 🔴 Пакети розмітки — людські назви черг, вони першими у виборі; поруч — усі
  // набори, свіжі вгорі. Перемикатись можна завжди: і з меню, і з кнопки «Розмітити».
  // Прихований набір у списку не стоїть, але посів з екрана «Набори» може вести саме
  // на нього — тоді він лишається у виборі, інакше сценарій пішов би на чужий набір.
  const [penv, env] = await Promise.all([callOp('train.packs', {}), callOp('train.sets', { all: !!seed.set })]);
  if (!alive(gen)) return;
  LB.packs = (penv.ok && penv.data.packs) || [];
  if (!env.ok) { boxError('lb-work', env); return; }
  LB.sets = (env.data.sets || []).filter((s) => !s.hidden || s.name === seed.set)
    .sort((a, b) => Number(b.touched || 0) - Number(a.touched || 0));
  if (!LB.sets.length && !LB.packs.length) {
    el('lb-work').innerHTML = emptyMini('kolba', t('sets.none'));
    return;
  }
  if (LB.pack && !LB.packs.some((p) => p.name === LB.pack)) LB.pack = '';
  if (LB.set && !LB.sets.some((s) => s.name === LB.set)) LB.set = '';
  if (!LB.pack && !LB.set) {
    if (LB.packs.length) LB.pack = LB.packs[0].name; else LB.set = LB.sets[0].name;
  }
  fillSetSelect();
  await refreshPages();
  if (!alive(gen)) return;
  // Посів з екрана наборів — одразу в роботу: який сценарій, там і сказано.
  if (seed.set) await runScenario(SCEN[seed.scen] ? seed.scen : 'new');
};

/** Вибір набору: пакети першими, далі набори. */
function fillSetSelect() {
  const sel = el('lb-set');
  if (!sel) return;
  const packs = LB.packs.length ? `<optgroup label="${esc(t('label.group.packs'))}">${LB.packs.map((p) =>
    `<option value="pack:${esc(p.name)}"${p.name === LB.pack ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</optgroup>` : '';
  const sets = `<optgroup label="${esc(t('label.group.sets'))}">${LB.sets.map((s) =>
    `<option value="${esc(s.name)}"${!LB.pack && s.name === LB.set ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</optgroup>`;
  sel.innerHTML = packs + sets;
}

/** Набір, обраний у списку зараз (ще не обов'язково запущений). */
function picked() {
  const v = String((el('lb-set') || {}).value || '');
  return v.startsWith('pack:') ? { pack: v.slice(5), set: '' } : { pack: '', set: v };
}

/** Сторінки набору зі станом — вибір сторінки списком, а не вільним полем. */
async function refreshPages() {
  // 🔴 Лише вибір у списку: `LB.set`/`LB.pack` — набір ЗАПУЩЕНОЇ черги, і їх міняє
  // тільки старт. Інакше «змінити» → інший набір → Enter писав мітку рядка старої
  // черги в новий набір.
  const { set } = picked();
  const wrap = el('lb-pgwrap');
  LB.pages = [];
  if (!set) {
    if (wrap) wrap.hidden = true;
    paintScenButtons();
    return;
  }
  if (wrap) wrap.hidden = false;
  const env = await callOp('train.pages', { name: set });
  if (picked().set !== set) return;
  LB.pages = (env.ok && env.data.pages) || [];
  const sel = el('lb-pg');
  if (sel) {
    // Типово — перша сторінка, де ще лишились нерозмічені рядки.
    const open = LB.pages.find((p) => p.n_ok < p.n_lines) || LB.pages[0];
    const want = LB.pages.some((p) => p.page === LB.page) ? LB.page : (open ? open.page : '');
    sel.innerHTML = LB.pages.map((p) => `<option value="${esc(p.page)}"${p.page === want ? ' selected' : ''}>${esc(pageLabel(p))}</option>`).join('');
  }
  paintScenButtons();
}

/** «0113 · зведено 12 з 12 · ручних 3»: де злиття є, а де ні — видно в списку. */
function pageLabel(p) {
  const merged = p.n_merged ? t('label.pg.merged').replace('{m}', p.n_merged).replace('{n}', p.n_lines) : t('label.pg.nomerge');
  return `${p.page} · ${merged} · ${t('label.pg.hand').replace('{k}', p.n_marked)}`;
}

/** Сценарій недоступний, коли для нього нема чого брати (злиття, сторінки, пакет). */
function paintScenButtons() {
  const { pack, set } = picked();
  const st = LB.sets.find((s) => s.name === set);
  const off = {
    merge: !pack && !(st && st.merge),
    new: false,
    page: !set || !LB.pages.length,
  };
  for (const k of Object.keys(SCEN)) {
    const b = el(`lb-sc-${k}`);
    if (b) { b.disabled = !!off[k]; b.title = off[k] ? t(`label.scen.${k}.off`) : ''; }
  }
}

/** Запустити сценарій: параметри лягають і в стан, і в поля «Точних параметрів». */
async function runScenario(key) {
  const sc = SCEN[key];
  if (!sc) return;
  const { pack, set } = picked();
  LB.pack = pack; LB.set = set; LB.scen = key;
  LB.mode = sc.mode; LB.mergedOnly = sc.mergedOnly; LB.fresh = sc.fresh; LB.limit = sc.limit;
  LB.blank = false;
  LB.page = key === 'page' ? String((el('lb-pg') || {}).value || '') : '';
  syncMoreFields();
  await startQueue();
}

function syncMoreFields() {
  const f = el('lb-ctl');
  if (!f || !f.elements) return;
  const set = (n, v) => { if (f.elements[n]) f.elements[n].value = v; };
  const chk = (n, v) => { if (f.elements[n]) f.elements[n].checked = !!v; };
  set('mode', LB.mode); set('minchars', LB.minChars); set('limit', LB.limit);
  chk('blank', LB.blank); chk('fresh', LB.fresh); chk('mo', LB.mergedOnly);
}

async function startQueue() {
  el('lb-work').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  if (await loadQueue()) {
    const f = el('lb-ctl');
    if (f) f.hidden = true;        // керування згортається в рядок стану, «змінити» повертає
    await advance(1);
  }
}

/** Липкий рядок стану: що за черга зараз, скільки в ній і з чого вона. */
function paintBar() {
  const bar = el('lb-bar');
  if (!bar) return;
  if (!LB.q) { bar.hidden = true; return; }
  const q = LB.q;
  const modeName = LB.scen ? t(`label.scen.${LB.scen}`) : t(`label.mode.${LB.mode}`);
  const what = LB.pack ? `${t('label.bar.pack')}: ${LB.pack}` : `${t('label.bar.set')}: ${LB.set}`;
  const pg = LB.mode === 'page' && LB.page ? LB.page : t('label.bar.pages');
  // Рахуємо те, що людина справді отримає (черга обрізана стелею), а не все, що є на сервері.
  const n = LB.queue.length;
  const merged = LB.queue.filter((it) => it.conf).length;
  const plain = n - merged;
  const avail = Number(q.n_queue || 0) > n ? ` · ${t('label.bar.avail').replace('{n}', q.n_queue)}` : '';
  bar.hidden = false;
  bar.innerHTML = `<span class="lbq-what"><b>${esc(what)}</b></span>
    <span>${esc(modeName)}</span>
    <span class="muted">${esc(t('label.bar.page'))}: ${esc(pg)}</span>
    <span>${esc(t('label.bar.queue').replace('{n}', n))}
      <span class="muted">(${esc(t('label.bar.merged').replace('{a}', merged))}, ${esc(t('label.bar.plain').replace('{b}', plain))}${esc(avail)})</span></span>
    <span class="muted">${esc(t('label.done'))}: ${Number(q.n_done || 0) + LB.session}</span>
    <button type="button" class="ghost ctl-sm" data-act="label.change">${esc(t('label.bar.change'))}</button>`;
}

// ── черга ────────────────────────────────────────────────────────────────────
async function loadQueue() {
  const base = { mode: LB.mode, min_chars: LB.minChars, fresh: LB.fresh, merged_only: LB.mergedOnly,
    include_blank: LB.blank, limit: LB.limit };
  const env = LB.pack
    ? await callOp('train.queue', { ...base, pack: LB.pack })
    : await callOp('train.queue', { ...base, name: LB.set, page: LB.page });
  if (!env.ok) { boxError('lb-work', env); return false; }
  const d = env.data;
  LB.qSet = LB.pack ? '' : LB.set;
  LB.queue = d.items || [];
  LB.srcs = d.draft_srcs || [];
  LB.ids = d.draft_ids || [];
  LB.i = -1;
  LB.q = { n_queue: d.n_queue, n_merged: d.n_merged, n_done: d.n_done, n_total: d.n_total };
  LB.session = 0;
  LB.cache.clear();
  paintBar();
  el('lb-stats').innerHTML = `${t('label.done')}: <b>${d.n_done}</b> ${t('label.of')} ${d.n_total}`
    + renderWarnings(env);
  return true;
}

function key(it) { return `${it.set || ''}:${it.page}:${it.idx}`; }

/** Набір рядка: у черзі пакета кожен рядок несе свій. */
function setOf(it) { return (it && it.set) || LB.qSet; }

/** Рядок із кешу або з сервера; кеш і є префетч. */
async function fetchLine(it) {
  const k = key(it);
  if (!LB.cache.has(k)) {
    LB.cache.set(k, callOp('train.line', { name: setOf(it), page: it.page, idx: it.idx }));
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
  if (it.draft_ids) { LB.ids = it.draft_ids; LB.srcs = it.draft_srcs || []; }
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
  // Порожнє «Злиття:» — не помилка, а сторінка, яку арбітри ще не зводили; у полі тоді
  // чернетка першого голосу, і людина має це бачити, а не гадати.
  const mi = LB.ids.indexOf('merge');
  const noMerge = mi >= 0 && !d.drafts[mi];
  const used = noMerge ? d.drafts.findIndex((x) => x) : -1;
  const usedName = used >= 0 ? (LB.srcs[used] || LB.ids[used] || '') : '';
  const voices = d.drafts.map((v, k) => {
    const others = d.drafts.filter((_, j) => j !== k);
    const why = noMerge && k === mi
      ? ` <span class="lb-nomerge">${esc(!saved && usedName ? t('label.nomerge.draft').replace('{v}', usedName) : t('label.nomerge'))}</span>` : '';
    return `<div class="lb-voice"><span class="muted">${esc(LB.srcs[k] || LB.ids[k] || k)}:</span>
      <span class="lb-vt" data-act="label.use" data-arg="${k}">${wordsHtml(v, others)}</span>${why}</div>`;
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
    <div class="lb-chars" id="lb-chars">${CHARS.map((c) =>
    `<button type="button" class="lb-ch" data-act="label.char" data-arg="${c}">${c}</button>`).join('')}</div>
    <div class="lb-bottom">
      <button data-act="label.save" class="lb-do">${t('label.save')}</button>
      <button data-act="label.unsure" class="lb-do">${t('label.unsure')}</button>
      <button data-act="label.skip" class="lb-do">${ic('skip', 'ic-sm')} ${t('label.skip')}</button>
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
  LB.t0 = Date.now();
  prefetch();
  if (LB.panel) await renderPanel(it);
}

function applyZoom() {
  const img = el('lb-img');
  if (!img) return;
  const phone = (globalThis.innerWidth || 0) < DESKTOP_MIN;
  const h = LB.zoom || (phone && img.naturalHeight && img.naturalHeight < PHONE_H ? PHONE_H : 0);
  img.style.height = h ? `${h}px` : '';
  img.style.width = h ? 'auto' : '';
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
      const env = await callOp('train.suggest', { name: setOf(LB.queue[LB.i]), q });
      const dl = el('lb-sugg');
      if (env.ok && dl) dl.innerHTML = (env.data.items || []).map((s) => `<option value="${esc(s)}">`).join('');
    }, 200);
  });
  // Курсор запам'ятовується: на телефоні дотик до кнопки літери знімає фокус з поля,
  // і без цього літера лягала б у кінець рядка, а не туди, де людина правила.
  const keep = () => {
    inp.dataset.s = String(inp.selectionStart ?? inp.value.length);
    inp.dataset.e = String(inp.selectionEnd ?? inp.dataset.s);
  };
  for (const e of ['keyup', 'click', 'input', 'select', 'blur']) inp.addEventListener(e, keep);
  const chars = el('lb-chars');
  if (chars) chars.addEventListener('mousedown', (ev) => ev.preventDefault());
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

/*
 * 🔴 Свайпу-рішення на кропі немає (13.10.2026). Він ішов через `touch-action: pan-y`:
 * кроп не гортався пальцем убік, а рух убік зберігав або пропускав рядок. Рішення — лише
 * кнопками; розмір кропа — +/− (щипок збільшував би всю сторінку).
 */

// ── сторінка з рамкою ────────────────────────────────────────────────────────
async function renderPanel(it) {
  const box = el('lb-page');
  if (!box || !it) return;
  box.hidden = false;
  box.innerHTML = `<p class="muted">${t('label.loading')}</p>`;
  const px = LB.panelZoom > 1 ? 3600 : 1800;
  const env = await callOp('train.page', { name: setOf(it), page: it.page, max_px: px });
  if (!env.ok) { boxError('lb-page', env); return; }
  const d = env.data;
  // Розмір і рамки йдуть у розмітку через innerHTML, а беруться з `_cut.json`
  // — лише числа, інакше рядок у файлі став би HTML (аудит 29.09.2026).
  const num = (v) => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const size = Array.isArray(d.size) && num(d.size[0]) > 0 && num(d.size[1]) > 0
    ? [num(d.size[0]), num(d.size[1])] : [1, 1];
  const boxes = Object.entries(d.boxes || {}).map(([i, b]) => {
    const cur = Number(i) === it.idx;
    const [x0, y0, x1, y1] = [0, 1, 2, 3].map((k) => num(b[k]));
    return `<rect class="ln${cur ? ' on' : ''}" data-act="label.jump" data-arg="${num(i)}"
      x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"></rect>`;
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
  LB.session += 1;
  paintBar();
  callOp('train.save', { name: setOf(it), page: it.page, idx: it.idx, text, status,
    kind, draft, secs: Math.round(secs * 10) / 10 }).then((env) => {
    if (!env.ok) boxError('lb-stats', env);
  });
}

Object.assign(ACTIONS, {
  /** «Точні параметри»: черга зі значень полів, без сценарію. */
  'label.start': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(el('lb-ctl'));
    const { pack, set } = picked();
    LB.pack = pack; LB.set = set; LB.scen = '';
    LB.mode = fd.get('mode') || 'spread';
    LB.page = LB.mode === 'page' ? String(fd.get('pg') || '') : '';
    LB.blank = !!fd.get('blank');
    LB.minChars = Math.max(0, parseInt(fd.get('minchars'), 10) || 0);
    LB.fresh = !!fd.get('fresh');
    LB.mergedOnly = !!fd.get('mo');
    LB.limit = Math.max(1, Math.min(2000, parseInt(fd.get('limit'), 10) || 400));
    await startQueue();
  },
  'label.scen': async (_ev, elm) => { await runScenario(elm.dataset.arg); },
  'label.pick': async () => { await refreshPages(); },
  'label.pg': () => { /* вибір сторінки лише запам'ятовується: черга стартує кнопкою сценарію */ },
  /** «змінити»: показати керування й піднятись до нього. */
  'label.change': () => {
    const f = el('lb-ctl');
    if (!f) return;
    f.hidden = false;
    f.scrollIntoView({ block: 'start' });
    const sel = el('lb-set');
    if (sel) sel.focus({ preventScroll: true });
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
  'label.char': (_ev, elm) => {
    const inp = el('lb-in');
    if (!inp || !elm) return;
    const ch = elm.dataset.arg || '';
    const s = Math.min(inp.value.length, Number(inp.dataset.s ?? inp.value.length));
    const e = Math.min(inp.value.length, Math.max(s, Number(inp.dataset.e ?? s)));
    inp.value = inp.value.slice(0, s) + ch + inp.value.slice(e);
    const pos = s + ch.length;
    inp.dataset.s = String(pos);
    inp.dataset.e = String(pos);
    inp.focus();
    inp.setSelectionRange(pos, pos);
  },
  'label.use': (_ev, elm) => {
    const inp = el('lb-in');
    if (inp) { inp.value = elm.textContent; inp.focus(); }
  },
  // від ПОТОЧНОЇ висоти: на телефоні кроп уже збільшений, і від природної «+» зменшував би його
  'label.zoomin': () => { LB.zoom = Math.min(400, (LB.zoom || (el('lb-img') || {}).clientHeight || 60) * 1.25); applyZoom(); },
  'label.zoomout': () => { LB.zoom = Math.max(24, (LB.zoom || (el('lb-img') || {}).clientHeight || 60) / 1.25); applyZoom(); },
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
