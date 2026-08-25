/** 📄 Гортач сторінок. */

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




SCREENS.view = async () => {
  // Значення підставляє САМ екран, а не той, хто на нього переходить: інакше
  // перехід із пошуку мусив би підробляти подію форми, і будь-яка зміна
  // розмітки тихо ламала б саме цей шлях.
  const v = ST.view || {};
  setView(`
    <h2>${t('nav.view')}</h2>
    <p class="muted">${t('view.eye')}</p>
    <form class="row" data-act="view.open">
      <input name="run" placeholder="${t('view.run')}" value="${esc(v.run || '')}"
        ${v.run ? '' : 'autofocus'}>
      <input name="page" placeholder="00003.JPG" value="${esc(v.page || '')}">
      <button type="submit">${t('view.open')}</button>
      <button type="button" data-act="view.page" title="${esc(t('view.page.why'))}">
        ${ic('image', 'ic-sm')} ${t('view.page')}</button>
    </form>
    <div id="stage"></div>
    <div id="hits"></div>`);
  // 🔴 Підказка, а не вільний рядок. Імена прогонів довгі й схожі між собою
  // (одна справа читається двічі — латинка й кирилиця), тож набраний руками
  // рядок помиляється саме тоді, коли шукають конкретну сторінку: гортач
  // відповідає «немає такого прогону», і це читається як «сторінки немає».
  // Список береться з сервера; не приїхав — поле лишається звичайним.
  await viewRunHints();
  if (v.run && v.page) {
    await ACTIONS['view.open']({
      preventDefault() {}, target: el('view').querySelector('form') });
    if (v.line !== null && v.line !== undefined) {
      await ACTIONS['view.line']({}, { dataset: { line: String(v.line) } });
    }
  }
};

/**
 * 🖼 Сторінка цілком.
 *
 * 🔴 Окремою дією, а не одразу: вирізка рядка важить 15 КБ, ціла сторінка —
 * близько мегабайта, і при розборі десятків знахідок різниця вирішує. Але
 * рядок сам по собі не каже, ЧИЙ це запис: роль, відмінок і сусідні імена
 * стоять поруч, а не в самому слові.
 *
 * Зум — шириною зображення, без канви: канва потрібна там, де по знімку
 * МАЛЮЮТЬ, а тут на нього дивляться.
 */
let ZOOM = 100;

/** Живий комбобокс гортача — щоб було що прибрати перед наступним. */
let _runCb = null;

/**
 * Підказки для поля прогону: перелік прочитаного з сервера.
 *
 * ⚠ Перед новим чіпляємо — старий прибираємо. `setView` щоразу створює НОВЕ
 * поле, тож внутрішній гард `input._cb` не спрацьовує, і без `destroy()` у
 * `<body>` накопичувались би попапи, а на `document` — слухачі, що тримають
 * посилання на давно викинуті поля.
 */
async function viewRunHints() {
  if (_runCb) { _runCb.destroy(); _runCb = null; }
  const input = el('view').querySelector('input[name="run"]');
  if (!input) return;
  const env = await callOp('runs.list', {});
  if (!env.ok) return;
  const runs = (env.data || {}).runs || [];
  _runCb = attachCombobox(input, {
    items: runs.map((r) => r.name).filter(Boolean),
    empty: t('view.run.none'),
  });
  // Знаменник поруч: «нічого не знайшлось» у гортачі означає різне при
  // нулі прочитаних справ і при трьохстах.
  const box = el('stage');
  if (box && !runs.length) {
    box.innerHTML = `<div class="warn">${t('view.run.empty')}</div>`;
  }
}

async function viewWholePage() {
  const box = el('stage');
  const form = el('view').querySelector('form');
  if (!box || !form) return;
  const run = form.run.value.trim();
  const page = form.page.value.trim();
  if (!run || !page) return;
  box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  const env = await callOp('page.view', { run, page, region: 'page' });
  if (!env.ok || !(env.data || {}).image) {
    box.innerHTML = `<div class="warn err">${esc(env.error || t('sift.crop.fail'))}</div>`;
    return;
  }
  ZOOM = 100;
  // Рамки рядків — окремим запитом: вони є не в кожного прогону, і сторінка
  // мусить показатись навіть тоді, коли їх немає.
  const geo = await callOp('page.lines', { run, page });
  const g = (geo.ok && geo.data) || {};
  box.innerHTML = `
    <div class="row">
      <button data-act="view.zoom" data-arg="-25">${t('view.zoom.out')}</button>
      <button data-act="view.zoom" data-arg="fit">${t('view.zoom.fit')}</button>
      <button data-act="view.zoom" data-arg="25">${t('view.zoom.in')}</button>
      <button data-act="view.stage.close">${t('view.close')}</button>
    </div>
    ${g.has ? `<p class="dim">${t('view.overlay')}</p>`
            : renderWarnings(geo)}
    <div class="stage"><div class="stage-wrap" style="width:${ZOOM}%">
      <img id="stage-img" src="${esc(env.data.image)}" alt="${esc(page)}">
      ${stageOverlay(g)}
    </div></div>
    <div id="stage-line"></div>`;
}

/**
 * 🖼 Рамки рядків поверх знімка.
 *
 * SVG у тих самих координатах, що й зображення (`viewBox` = розмір сторінки),
 * тож масштаб бере на себе браузер — при зумі нічого перераховувати не треба.
 *
 * ⚠ `pointer-events: fill` навмисно: фігура намальована без заливки, і без
 * цього клік ловився б лише самою лінією обведення — тобто попадати треба було
 * б у два пікселі. Правило живе в base.css поруч із рештою примітивів.
 */
function stageOverlay(g) {
  if (!g.has || !g.size) return '';
  const [w, h] = g.size;
  const shapes = (g.polys || g.boxes || []).map((sh, i) => {
    // 🔴 `null` тут — законне значення, а не поламані дані: рядок без обведення
    // й без базової лінії рамки не має, і раннер пише в масив саме `null`,
    // зберігаючи довжину. Без цієї перевірки `sh[0]` кидає TypeError ПОСЕРЕД
    // обчислення шаблона, тобто `innerHTML` не присвоюється зовсім — і
    // «сторінка цілком» назавжди лишається на «Хвилинку…», без картинки й без
    // кнопки «Згорнути».
    //
    // ⚠ Індекс береться з `map`, а не з лічильника вцілілих: він же номер
    // рядка в тексті, і зсунувши його, клік показував би чужий рядок.
    if (!Array.isArray(sh) || !sh.length) return '';
    const attrs = `class="ln" data-act="view.line.pick" data-arg="${i}"`;
    return Array.isArray(sh[0])
      ? `<polygon ${attrs} points="${sh.map((pt) => pt.join(',')).join(' ')}"/>`
      : `<rect ${attrs} x="${sh[0]}" y="${sh[1]}"
           width="${sh[2] - sh[0]}" height="${sh[3] - sh[1]}"/>`;
  });
  return `<svg class="stage-ov" viewBox="0 0 ${w} ${h}"
    preserveAspectRatio="none" aria-hidden="true">${shapes.join('')}</svg>`;
}

Object.assign(ACTIONS, {
  'view.page': () => viewWholePage(),

  'view.zoom': (_ev, elm) => {
    // 🔴 Зум міняє ОБГОРТКУ, а не картинку. Оверлей рамок розтягнутий по
    // обгортці (`.stage-ov { inset: 0 }`), тож зміна ширини самого `<img>`
    // роз'їжджає рамки з рядками — і клік по рамці віддає текст іншого рядка.
    // Помітно це лише після першого «+», а «вписати» випадково лікує, тобто
    // вада виглядає плаваючою.
    const wrap = document.querySelector('.stage-wrap');
    if (!wrap) return;
    // «Вписати» — не 100%, а ширина контейнера: сторінка з архіву буває
    // 4000 px завширшки, і сотня відсотків від неї не влазить нікуди.
    ZOOM = elm.dataset.arg === 'fit'
      ? 100
      : Math.max(25, Math.min(600, ZOOM + Number(elm.dataset.arg)));
    wrap.style.width = `${ZOOM}%`;
  },

  /** Клік по рамці на знімку — показати текст саме цього рядка. */
  'view.line.pick': async (_ev, elm) => {
    const i = Number(elm.dataset.arg);
    const form = el('view').querySelector('form');
    const box = el('stage-line');
    if (!form || !box) return;
    document.querySelectorAll('.stage-ov .ln.on').forEach(
      (n) => n.classList.remove('on'));
    elm.classList.add('on');
    const env = await callOp('page.text',
      { run: form.run.value.trim(), page: form.page.value.trim() });
    if (!env.ok) return;
    const lines = (env.data || {}).lines || [];
    const one = lines[i];
    box.innerHTML = `<p class="mono">${esc(
      typeof one === 'string' ? one : (one || {}).text || '')}</p>`;
  },

  'view.stage.close': () => { const b = el('stage'); if (b) b.innerHTML = ''; },

  'view.open': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    ST.view = { run: fd.get('run'), page: fd.get('page') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('page.text', ST.view);
    if (!env.ok) return boxError('hits', env);
    const lines = env.data.lines || [];
    const geo = env.data.geometry || {};
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p class="muted">${lines.length} ${t('view.lines')}${geo.has ? '' : ' · без рамок'}</p>
      <div id="shot"></div>
      <table><tbody>${lines.map((ln, i) => `<tr>
        <td class="num mono">${i}</td>
        <td><button data-act="view.line" data-line="${i}">👁</button></td>
        <td>${esc(ln)}</td></tr>`).join('')}</tbody></table>`;
  },

  // 🔴 Рядок, а не сторінка. Вирізка легша в десятки разів (виміряно: 15 КБ
  // проти 1.1 МБ), а звірок за сеанс бувають десятки.
  'view.line': async (_ev, elm) => {
    if (!ST.view) return;
    const env = await callOp('page.view',
      { ...ST.view, line: Number(elm.dataset.line), region: 'line' });
    if (!env.ok) return alert(env.error);
    const d = env.data;
    // Коробки може не бути: сюди доходять і тоді, коли `view.open` упав, а
    // нарізка того самого прогону — ні. Без перевірки це незловлений TypeError,
    // причому мовчазний (дії в `dispatch` не await'яться).
    const shot = el('shot');
    if (!shot) return;
    // `esc` і в атрибуті: зараз тут data-URL, але єдине місце у файлі, де
    // значення з відповіді йшло в атрибут сире, — саме це.
    shot.innerHTML = `
      ${renderWarnings(env)}
      <img src="${esc(d.image || '')}" alt="${esc(`рядок ${d.line}`)}" style="max-width:100%">
      <p class="muted mono">${esc(d.text || '')}</p>`;
    shot.scrollIntoView({ block: 'nearest' });
  },
});
