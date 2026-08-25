/**
 * 🖼 Аркуші справи — подивитись на те, що завантажив.
 *
 * 🔴 Найпростіше, чого чекають від застосунку, і чого в ньому не було. Досі
 * побачити скан можна було ЛИШЕ через прогін: спершу прочитай справу рушієм —
 * година чи ніч, — і аж тоді дивись. Тобто щоб глянути на папери, які вже
 * лежать на диску, треба було спершу їх обробити.
 *
 * 🔴 Тут навмисно немає ні тексту, ні рамок рядків: це не «гортач без декоду»,
 * а відповідь на інше питання — ЩО ЦЕ ЗА ПАПЕРИ. Домішавши сюди машинне
 * читання, ми зробили б перегляд неможливим доти, доки прогону немає.
 *
 * Справа буває кадрами й PDF, і обидва трапляються самі по собі. Коли є і те,
 * і те — показуються кадри: саме їх читатиме рушій, а сторінки PDF це інший
 * рендер того самого, з іншою нумерацією.
 */
import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, KEYS } from '../core/registry.js';
import { show } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';
import { attachCombobox } from '/ui/combobox.js';
import { lightbox } from '/ui/lightbox.js';


/**
 * Підписи переглядача. Спільний модуль словника не має й мати не мусить: він
 * нічого не знає ні про справи, ні про мови — підписи дає той, хто кличе.
 */
function lbLabels() {
  return {
    prev: t('view.prev'), next: t('view.next'), close: t('lb.close'),
    fit: t('view.zoom.fit'), keys: t('lb.keys'), loading: t('common.loading'),
  };
}

/** Відкрита справа. Живе в межах екрана. */
let FS = { case: '', kind: '', frames: [], i: -1, zoom: 100, wide: false };

let _cb = null;
let _seq = 0;

SCREENS.frames = async () => {
  const gen = curGen();
  const seed = (ST.frames || {}).case || FS.case || '';
  ST.frames = null;
  setView(`
    <h2>${ic('image')} ${t('frames.title')}</h2>
    <p class="muted">${t('frames.why')}</p>
    <form class="row" data-act="frames.open">
      <input name="case" placeholder="${esc(t('frames.case'))}"
        value="${esc(seed)}"${seed ? '' : ' autofocus'}>
      <button type="submit">${t('frames.show')}</button>
    </form>
    <div id="fr-bar"></div>
    <div id="fr-stage"></div>`);
  await framesHints();
  if (!alive(gen)) return;
  if (seed) await framesOpen(seed);
};

/**
 * Підказка справ: те, що лежить на диску.
 *
 * ⚠ Вільний текст лишається: тека поза бібліотекою — законний випадок, і
 * вимагати опису до першого ж погляду означало б замкнути двері перед тим,
 * хто щойно завантажив скани.
 */
async function framesHints() {
  if (_cb) { _cb.destroy(); _cb = null; }
  const input = el('view').querySelector('input[name="case"]');
  if (!input) return;
  const env = await callOp('library.list', { on_disk: true, page_size: 200 });
  if (!env.ok) return;
  const items = ((env.data || {}).cases || []).map((c) => c.path).filter(Boolean);
  if (items.length) _cb = attachCombobox(input, { items, empty: t('frames.none') });
}

async function framesOpen(caseDir) {
  const seq = ++_seq;
  const gen = curGen();
  el('fr-bar').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  el('fr-stage').innerHTML = '';
  const env = await callOp('case.frames', { case: caseDir });
  if (seq !== _seq || !alive(gen)) return;
  if (!env.ok) {
    el('fr-bar').innerHTML = `<div class="warn err">${esc(env.error || '')}</div>`;
    return;
  }
  const d = env.data || {};
  FS = { ...FS, case: caseDir, kind: d.kind, frames: d.frames || [], i: -1 };
  el('fr-bar').innerHTML = renderWarnings(env);
  if (!FS.frames.length) {
    el('fr-bar').innerHTML += `<div class="warn">${t('frames.empty')}</div>`;
    return;
  }
  await framesShow(0);
}

async function framesShow(i) {
  const seq = ++_seq;
  const gen = curGen();
  if (!FS.frames.length) return;
  FS.i = Math.max(0, Math.min(FS.frames.length - 1, i));
  const f = FS.frames[FS.i];
  framesBar();
  const box = el('fr-stage');
  if (box) box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  // 🔴 Ширину просимо РОЗУМНУ, а не «як є». Архівний скан буває 4000 px і
  // важить мегабайти; на екрані стільки не видно, зате кожен крок гортання
  // коштував би цих мегабайтів. Повну ширину дає окрема кнопка.
  const width = FS.wide ? 3000 : 1400;
  const env = await callOp('case.frame', { case: FS.case, frame: f.id, width });
  if (seq !== _seq || !alive(gen)) return;
  const stage = el('fr-stage');
  if (!stage) return;
  if (!env.ok) {
    stage.innerHTML = `<div class="warn err">${esc(env.error || '')}</div>`;
    return;
  }
  const d = env.data || {};
  stage.innerHTML = `
    <div class="stage"><div class="stage-wrap" style="width:${FS.zoom}%">
      <img src="${esc(d.image || '')}" alt="${esc(f.label || f.id)}"
        class="zoomable" title="${esc(t('lb.open'))}">
    </div></div>
    <p class="muted mono">${esc(d.width)}×${esc(d.height)} ·
      ${Math.round((d.bytes || 0) / 1024)} КБ</p>`;
  // Клік по аркушу — у повний екран. Це найочевидніший жест над зображенням,
  // і вимагати замість нього окремої кнопки означало б ховати головний режим
  // перегляду за другим кроком.
  const shot = stage.querySelector('img.zoomable');
  if (shot) shot.addEventListener('click', framesFull);
}

function framesBar() {
  const f = FS.frames[FS.i] || {};
  el('fr-bar').innerHTML = `
    <div class="row view-nav">
      <button data-act="frames.step" data-arg="-1"${FS.i ? '' : ' disabled'}
        title="${esc(t('view.prev.key'))}">${ic('arrow-left', 'ic-sm')} ${t('view.prev')}</button>
      <select id="fr-page" data-act="frames.goto">
        ${FS.frames.map((x, k) => `<option value="${k}"${k === FS.i ? ' selected' : ''}
          >${k + 1}. ${esc(x.label)}</option>`).join('')}
      </select>
      <button data-act="frames.step" data-arg="1"
        ${FS.i + 1 < FS.frames.length ? '' : ' disabled'}
        title="${esc(t('view.next.key'))}">${t('view.next')}</button>
      <button data-act="frames.zoom" data-arg="-25">${t('view.zoom.out')}</button>
      <button data-act="frames.zoom" data-arg="fit">${t('view.zoom.fit')}</button>
      <button data-act="frames.zoom" data-arg="25">${t('view.zoom.in')}</button>
      <button data-act="frames.wide" title="${esc(t('frames.wide.why'))}">
        ${FS.wide ? t('frames.wide.off') : t('frames.wide.on')}</button>
      <button data-act="frames.full" title="${esc(t('lb.open.why'))}">
        ${ic('expand', 'ic-sm')} ${t('lb.open')}</button>
    </div>
    <p class="muted"><b>${FS.i + 1}</b>/${FS.frames.length} ·
      <span class="mono">${esc(f.label || '')}</span>
      ${FS.kind === 'pdf' ? `· <span class="dim">${t('frames.frompdf')}</span>` : ''}</p>`;
}

/**
 * Повний екран.
 *
 * 🔴 Тут просимо ПОВНУ ширину, а не показову. Вбудований перегляд свідомо
 * бере зменшену копію — на кожен крок гортання це мегабайти, — але в повному
 * екрані аркуш саме роздивляються, і зум по зменшеній копії впирається в
 * розмитість рівно там, де починається робота.
 */
function framesFull() {
  // 🔴 Порожній стан називається вголос. Мовчазне повернення з цієї функції
  // виглядало б рівно як мертва кнопка — і саме так його й прочитали.
  if (!FS.frames.length) {
    const bar = el('fr-bar');
    if (bar) bar.innerHTML = `<div class="warn">${t('frames.nothing')}</div>` + bar.innerHTML;
    return;
  }
  lightbox({
    count: FS.frames.length,
    index: FS.i,
    labels: lbLabels(),
    // Гортання в повному екрані веде за собою екран під ним: вийшовши, людина
    // лишається на тому аркуші, який дивилась, а не на тому, з якого зайшла.
    onIndex: (k) => { FS.i = k; },
    load: async (k) => {
      const fr = FS.frames[k];
      if (!fr) return null;
      const env = await callOp('case.frame',
        { case: FS.case, frame: fr.id, width: 3000 });
      if (!env.ok) return { error: env.error || '' };
      return { image: (env.data || {}).image, label: fr.label || fr.id };
    },
  });
}

Object.assign(ACTIONS, {
  'frames.full': () => framesFull(),

  'frames.open': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    await framesOpen(String(fd.get('case') || '').trim());
  },

  'frames.step': (_ev, elm) => framesShow(FS.i + Number(elm.dataset.arg || 0)),

  'frames.goto': () => framesShow(Number((el('fr-page') || {}).value || 0)),

  'frames.zoom': (_ev, elm) => {
    const wrap = document.querySelector('#fr-stage .stage-wrap');
    if (!wrap) return;
    FS.zoom = elm.dataset.arg === 'fit'
      ? 100
      : Math.max(25, Math.min(600, FS.zoom + Number(elm.dataset.arg)));
    wrap.style.width = `${FS.zoom}%`;
  },

  /** Повна ширина — окремою дією, бо коштує мегабайтами на кожен аркуш. */
  'frames.wide': () => {
    FS.wide = !FS.wide;
    return framesShow(FS.i);
  },
});

// Гортання клавішами: справа на триста аркушів мишею не гортається.
Object.assign(KEYS, {
  frames: {
    ArrowRight: () => framesShow(FS.i + 1),
    ArrowLeft: () => framesShow(FS.i - 1),
    PageDown: () => framesShow(FS.i + 1),
    PageUp: () => framesShow(FS.i - 1),
    Home: () => framesShow(0),
    End: () => framesShow(FS.frames.length - 1),
    Enter: () => framesFull(),
    f: () => framesFull(),
    '+': () => ACTIONS['frames.zoom'](null, { dataset: { arg: '25' } }),
    '-': () => ACTIONS['frames.zoom'](null, { dataset: { arg: '-25' } }),
    0: () => ACTIONS['frames.zoom'](null, { dataset: { arg: 'fit' } }),
  },
});
