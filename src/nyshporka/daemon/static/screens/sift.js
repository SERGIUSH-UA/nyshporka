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
// Сам стан розбору живе в `core/state.js`: його заповнює пошук, а читає цей
// екран, тож він не належить жодному з двох.

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
  // 🔴 Бейдж робиться з `engine_id` (ідентичність моделі: Писар · Дяк ·
  // Скриба), а не з `engine` (ВИД рушія: kraken · parseq). Доти тут стояв
  // вид — а таблиця бейджів ключована ідентичністю, тож збігу не було ніколи
  // й бейдж не з'являвся ЖОДНОГО разу. `<use>` на неіснуючий символ мовчить,
  // тому вада виглядала як «тут просто нічого не показують».
  const badge = h.engine_id ? eng(h.engine_id, true, LANG) : '';
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
  siftCtx(h);
}

/**
 * Сусідні рядки й читання другого голосу — З ТОГО САМОГО конверта.
 *
 * 🔴 Доти тут стояв ДРУГИЙ запит (`page.text` на всю сторінку) заради ±1
 * рядка, які пошук уже приніс: `search.run` має поле `context` і повертає
 * вікно на кожен хіт, а разом із ним — прочитання того самого рядка другим
 * рушієм. Фронт просто не просив контексту, тож платив зайвим читанням
 * сторінки на кожен крок гортання й будував вікно сам — ±1 рядок замість
 * РОЗСУВНОГО, який пропускає огризки («на», «и», «3») і шукає змістовне.
 *
 * 🔴 Другий голос тут не прикраса: збіг двох рушіїв означає надійне читання,
 * а розбіжність саме на прізвищі означає, що ознака в пікселях — і судити має
 * око, а не третій алгоритм.
 */
function siftCtx(h) {
  const cbox = el('sift-ctx');
  if (!cbox) return;
  const ctx = h.context || {};
  const near = [...(ctx.before || []), h.line || '', ...(ctx.after || [])];
  const alt = h.alt
    ? `<p class="muted">${esc(t('sift.alt'))}</p><pre class="alt">${esc(h.alt.line)}</pre>`
    : '';
  cbox.innerHTML = (ctx.before || ctx.after)
    ? `<p class="muted">${t('sift.context')}</p><pre>${near
        .map((l) => esc(l)).join('\n')}</pre>${alt}`
    : alt;
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
