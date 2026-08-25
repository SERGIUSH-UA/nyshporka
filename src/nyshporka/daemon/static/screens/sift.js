/** 🔬 Розбір знахідок. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav,
  refreshJobs } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';




/**
 * 🔬 Розбір знахідок — те місце, де машина віддає рішення людині.
 *
 * Пошук подає рядки, схожі на запит; чи це справді шукане прізвище, видно лише
 * на самому знімку. Тому картка несе ВИРІЗКУ, а не самий декод: рушій калічить
 * середину слова, і текст, у якому «не той корінь», може бути рівно тим
 * прізвищем, по яке пошук і кликали.
 *
 * 🔴 Два правила стоять НА ЕКРАНІ, а не в документації, бо порушують їх саме
 * тут: вирішує око, і відсівати за коренем не можна.
 */
let ST.sift = { hits: [], i: 0, q: '', crop: null, ctx: null };

SCREENS.sift = async () => {
  const gen = curGen();
  if (!ST.sift.hits.length) {
    setView(`<h2>${ic('crop-check')} ${t('sift.title')}</h2>
      <div class="warn">${t('sift.empty')}
        <button data-act="nav" data-arg="search">${t('nav.search')}</button></div>`);
    return;
  }
  siftDraw();
  if (!alive(gen)) return;
  await siftLoadCrop();
};

function siftDraw() {
  const h = ST.sift.hits[ST.sift.i] || {};
  const badge = h.engine ? eng(h.engine, true, LANG) : '';
  const pos = t('sift.togo').replace('{i}', ST.sift.i + 1).replace('{n}', ST.sift.hits.length);
  // Збіг підсвічується в рядку, але НЕ вирізається з нього: сусідні слова —
  // це роль і відмінок, тобто половина того, за чим упізнають запис.
  const line = esc(h.line || '');
  const lit = h.matched
    ? line.replace(esc(h.matched), `<mark>${esc(h.matched)}</mark>`)
    : line;
  setView(`<h2>${ic('crop-check')} ${t('sift.title')}</h2>
    <div class="row">
      <button data-act="sift.step" data-arg="-1"${ST.sift.i ? '' : ' disabled'}>
        ${ic('arrow-left', 'ic-sm')} ${t('sift.prev')}</button>
      <span class="muted">${esc(pos)}</span>
      <button data-act="sift.step" data-arg="1"${
        ST.sift.i + 1 < ST.sift.hits.length ? '' : ' disabled'}>${t('sift.next')}</button>
    </div>
    <div class="warn">${t('sift.rule')}</div>
    <p class="mono">${esc(h.name || '')} · ${t('common.page')} ${esc(h.page || '')}
       · ${badge} · ${t('sift.score')} ${esc(h.score || '')}</p>
    <div id="sift-crop"><p class="muted">${t('sift.crop.load')}…</p></div>
    <p class="mono">${lit}</p>
    <div id="sift-ctx"></div>
    <p class="muted">${t('sift.stem')}</p>
    <div class="row">
      <button data-act="sift.view">${ic('eye', 'ic-sm')} ${t('sift.view')}</button>
      <button data-act="sift.note">${ic('pencil-line', 'ic-sm')} ${t('sift.note')}</button>
    </div>
    <p class="dim">${t('sift.keys')}</p>`);
}

/**
 * Вирізка поточного рядка. Окремим кроком: сторінка коштує ~1.1 МБ, рядок 15 КБ.
 *
 * 🔴 Лічильник обов'язковий. Кожен крок гортача шле ДВА запити (нарізка
 * зображення на сервері й текст сторінки), і порядок відповідей не
 * гарантований: на утриманій «→» (автоповтор ~30/с) контекст від хіта N−1
 * лягав під вирізку хіта N. Це не косметика — саме за сусідніми рядками
 * виносять вердикт «наш / не наш», і вони мовчки належали чужому запису.
 */
let _siftSeq = 0;

async function siftLoadCrop() {
  const seq = ++_siftSeq;
  const h = ST.sift.hits[ST.sift.i] || {};
  if (!el('sift-crop') || !h.name) return;
  const env = await callOp('page.view', {
    run: h.name, page: h.page, line: h.line_index, region: 'line',
  });
  // Вузли резолвимо ПІСЛЯ кожного await і лише коли крок ще актуальний:
  // захоплений до await `box` — вже від'єднаний, і запис у нього не видно.
  if (seq !== _siftSeq) return;
  const box = el('sift-crop');
  if (!box) return;
  if (!env.ok || !(env.data || {}).image) {
    box.innerHTML = `<p class="muted">${t('sift.crop.fail')}</p>`;
    return;
  }
  box.innerHTML = `<img src="${esc(env.data.image)}" alt="${esc(t('sift.crop'))}"
    style="max-width:100%;background:var(--paper);border:1px solid var(--paper-edge);
           border-radius:var(--r-m)">`;
  // Сусідні рядки — той самий «контекст двох голосів»: роль і відмінок стоять
  // поряд, а не в самому слові.
  const ctx = await callOp('page.text', { run: h.name, page: h.page });
  if (seq !== _siftSeq) return;
  const cbox = el('sift-ctx');
  if (!cbox || !ctx.ok) return;
  const lines = (ctx.data || {}).lines || [];
  const near = lines.slice(Math.max(0, (h.line_index || 0) - 1), (h.line_index || 0) + 2);
  cbox.innerHTML = near.length
    ? `<p class="muted">${t('sift.context')}</p><pre>${near
        .map((l) => esc(typeof l === 'string' ? l : l.text || '')).join('\n')}</pre>`
    : '';
}

Object.assign(ACTIONS, {
  /** Вхід у розбір із видачі пошуку. */
  'sift.open': () => show('sift'),

  'sift.step': async (_ev, elm) => {
    const next = ST.sift.i + Number(elm.dataset.arg || 0);
    if (next < 0 || next >= ST.sift.hits.length) return;
    ST.sift.i = next;
    siftDraw();
    await siftLoadCrop();
  },

  /** У гортач — на ту саму сторінку й той самий рядок. */
  'sift.view': () => {
    const h = ST.sift.hits[ST.sift.i] || {};
    ST.view = { run: h.name, page: h.page, line: h.line_index };
    return show('view');
  },

  /** В облік — зі справою й сканом уже підставленими. */
  'sift.note': () => {
    const h = ST.sift.hits[ST.sift.i] || {};
    ST.eye = { ...(ST.eye || {}), case: h.key || h.shifra || h.name, scan: h.page };
    return show('eye');
  },
});
