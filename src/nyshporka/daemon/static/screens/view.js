/**
 * 📄 Гортач — читання прогону сторінка за сторінкою.
 *
 * 🔴 Доти сюди треба було НАБРАТИ ім'я прогону й ім'я скана. Тобто щоб
 * подивитись прочитане, треба було вже знати, що саме дивишся: перелік
 * сторінок екран не показував, кроку вперед не мав, а помилка в довгому імені
 * давала «немає такого прогону» — і це читається як «сторінки немає», а не як
 * друкарська помилка.
 *
 * 🔴 Текст стоїть ПОРЯД зі знімком, а не замість нього. Машинне читання
 * скоропису має десятки відсотків помилок, тож рядок сам по собі нічого не
 * доводить; єдине, що доводить, — той самий рядок на знімку. Тому текст і
 * рамки зв'язані наведенням в обидва боки.
 *
 * 🔴 Номери рядків ДВА, і це не дублювання. Людині показується номер з
 * одиниці, як у редакторі; у `data-i` лежить індекс рамки з нуля. Доки поле
 * було одне, кнопка звірки віддавала оку СУСІДНІЙ рядок — з тим самим виглядом
 * правильної відповіді.
 *
 * ⚠ Цілий знімок важить близько мегабайта проти 15 КБ на вирізку рядка, тож
 * лишається окремою дією й НЕ перезавантажується на кожен крок, поки панель
 * згорнута.
 */
import { t, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, failure, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, KEYS } from '../core/registry.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';

/** Усе, що зараз відкрито. Живе в межах екрана, тож тут, а не в спільному стані. */
let VS = {
  run: '', meta: {}, pages: [], i: -1,
  lines: [], geo: {}, zoom: 100, shot: false, alt: null,
};

/** Живий комбобокс — щоб було що прибрати перед наступним. */
let _runCb = null;
let _seq = 0;
/** Слухачі синхронізації чіпляються РАЗ на сеанс, а не на кожен рендер. */
let _syncBound = false;

SCREENS.view = async () => {
  const gen = curGen();
  const v = ST.view || {};
  setView(`
    <h2>${ic('page')} ${t('nav.view')}</h2>
    <p class="muted">${t('view.eye')}</p>
    <form class="row" data-act="view.open">
      <input name="run" placeholder="${t('view.run')}" value="${esc(v.run || '')}"
        ${v.run ? '' : 'autofocus'}>
      <button type="submit">${t('view.open')}</button>
    </form>
    <div id="view-bar"></div>
    <div id="view-split">
      <div id="view-stage"></div>
      <div id="view-text"></div>
    </div>
    <div id="view-line"></div>
    <div id="view-alt"></div>`);
  await viewRunHints();
  if (!alive(gen)) return;
  viewBindSync();
  if (v.run) {
    await viewOpenRun(v.run, v.page || '', v.line);
  }
};

/**
 * Підказки для поля прогону: перелік прочитаного з сервера.
 *
 * 🔴 Імена прогонів довгі й схожі між собою — одну справу читають двічі,
 * латинкою й кирилицею, — тож набраний руками рядок помиляється саме тоді,
 * коли шукають конкретну сторінку.
 *
 * ⚠ Перед новим чіпляємо — старий прибираємо: `setView` щоразу створює НОВЕ
 * поле, і без `destroy()` у `<body>` накопичувались би попапи, а на
 * `document` — слухачі, що тримають посилання на давно викинуті поля.
 */
async function viewRunHints() {
  if (_runCb) { _runCb.destroy(); _runCb = null; }
  const input = el('view').querySelector('input[name="run"]');
  if (!input) return;
  const env = await callOp('runs.list', {});
  if (!env.ok) return;
  const runs = (env.data || {}).runs || [];
  VS.all = runs;
  _runCb = attachCombobox(input, {
    items: runs.map((r) => r.name).filter(Boolean),
    empty: t('view.run.none'),
  });
  // 🔴 Знаменник поруч: порожньо в гортачі означає різне при нулі прочитаних
  // справ і при трьохстах. У першому випадку тут кнопка, а не докір.
  if (!runs.length) {
    el('view-bar').innerHTML = `<div class="warn">${t('view.run.empty')}
      <button data-act="nav" data-arg="read">${t('nav.read')}</button></div>`;
  }
}

/** Відкрити прогін: перелік сторінок + перша (або названа) сторінка. */
async function viewOpenRun(run, page = '', line = null) {
  const seq = ++_seq;
  const gen = curGen();
  el('view-bar').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  // Порожня сторінка в запиті — це і є «дай перелік»: операція вміє обидва
  // режими, тож окремого виклику під список не треба.
  const env = await callOp('page.text', { run, page: '' });
  if (seq !== _seq || !alive(gen)) return;
  if (!env.ok) {
    el('view-bar').innerHTML = renderWarnings(env)
      + `<div class="warn err">${esc(env.error || '')}</div>`;
    return;
  }
  const d = env.data || {};
  VS = { ...VS, run, meta: d, pages: d.pages || [], i: -1,
         lines: [], geo: {}, shot: false, alt: null };
  const want = page ? VS.pages.findIndex((p) => p.page === page) : 0;
  if (VS.pages.length && want < 0) {
    // Прогін є, сторінки немає — це РІЗНІ відповіді, і зводити їх до «немає
    // такого прогону» означає послати людину шукати не там.
    el('view-bar').innerHTML =
      `<div class="warn">${t('view.nopage').replace('{p}', esc(page))}</div>`;
  }
  await viewShow(want < 0 ? 0 : want, line);
}

/** Показати сторінку за номером у переліку. */
async function viewShow(i, line = null) {
  const seq = ++_seq;
  const gen = curGen();
  if (!VS.pages.length) {
    el('view-bar').innerHTML = `<div class="warn">${t('view.norun')}</div>`;
    return;
  }
  VS.i = Math.max(0, Math.min(VS.pages.length - 1, i));
  const p = VS.pages[VS.i];
  ST.view = { run: VS.run, page: p.page, line };

  viewBar();
  const env = await callOp('page.text', { run: VS.run, page: p.page });
  if (seq !== _seq || !alive(gen)) return;
  VS.lines = (env.ok && (env.data || {}).lines) || [];
  viewText();
  // Рамки — окремим запитом: їх пише не кожен прогін, і сторінка мусить
  // показатись навіть без них.
  const geo = await callOp('page.lines', { run: VS.run, page: p.page });
  if (seq !== _seq || !alive(gen)) return;
  VS.geo = (geo.ok && geo.data) || {};
  if (VS.shot) await viewShot();
  if (line !== null && line !== undefined) viewMark(Number(line), true);
  viewAltReset();
}

/** Смуга стану: де ми, що це за сторінка й чим вона підозріла. */
function viewBar() {
  const p = VS.pages[VS.i] || {};
  const m = VS.meta || {};
  const badge = m.engine_id ? eng(m.engine_id, false, LANG) : '';
  const bits = [
    `<b>${VS.i + 1}</b>/${VS.pages.length}`,
    `<span class="mono">${esc(p.page || '')}</span>`,
    p.lines ? `${esc(p.lines)} ${t('view.lines')}` : '',
    p.conf ? `conf ${esc(p.conf)}` : '',
    p.orient ? `↻${esc(p.orient)}°` : '',
    badge,
    m.model ? `<span class="mono dim">${esc(m.model)}</span>` : '',
  ].filter(Boolean);

  // 🔴 Позначки якості — гучні, бо вони міняють ВИСНОВОК про сторінку, а не
  // прикрашають його. Конфабуляція означає, що текст може бути вигаданим при
  // нормальній упевненості; фантомні рядки — що їх узагалі не було в чорнилі.
  const warns = [];
  if (p.suspect_confab) warns.push(`<div class="warn err">${t('view.confab')}</div>`);
  if (p.gap_loop) warns.push(`<div class="warn">${t('view.gaploop')}</div>`);
  if (!VS.geo.has && VS.lines.length) {
    warns.push(`<p class="dim">${t('view.noboxes')}</p>`);
  }

  el('view-bar').innerHTML = `
    <div class="row view-nav">
      <button data-act="view.step" data-arg="-1"${VS.i ? '' : ' disabled'}
        title="${esc(t('view.prev.key'))}">${ic('arrow-left', 'ic-sm')} ${t('view.prev')}</button>
      <select id="view-page" data-act="view.goto">
        ${VS.pages.map((x, k) => `<option value="${k}"${k === VS.i ? ' selected' : ''}
          >${k + 1}. ${esc(x.page)}${x.lines ? ` · ${x.lines} р.` : ''}</option>`).join('')}
      </select>
      <button data-act="view.step" data-arg="1"
        ${VS.i + 1 < VS.pages.length ? '' : ' disabled'}
        title="${esc(t('view.next.key'))}">${t('view.next')}</button>
      <button data-act="view.page" title="${esc(t('view.page.why'))}">
        ${ic('image', 'ic-sm')} ${t('view.page')}</button>
    </div>
    <p class="muted">${bits.join(' · ')}</p>
    ${warns.join('')}`;
}

/**
 * Текст сторінки з номерами.
 *
 * 🔴 `data-i` з НУЛЯ (індекс рамки), підпис — з одиниці (номер для людини).
 * Злиття цих двох чисел уже раз показувало в пошуку сусідній рядок, і саме це
 * найдорожче: відповідь виглядає правильною.
 */
function viewText() {
  const box = el('view-text');
  if (!box) return;
  if (!VS.lines.length) {
    swapHtml(box, `<p class="muted">${t('view.notext')}</p>`);
    return;
  }
  swapHtml(box, `<pre class="lines">${VS.lines.map((ln, i) =>
    `<span class="vln" data-i="${i}"><span class="no">${i + 1}</span>${
      esc(typeof ln === 'string' ? ln : (ln || {}).text || '')}</span>`).join('\n')}</pre>`);
}

/** Ціла сторінка зі знімком і рамками — окремою дією. */
async function viewShot() {
  const box = el('view-stage');
  const p = VS.pages[VS.i];
  if (!box || !p) return;
  box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  const env = await callOp('page.view',
    { run: VS.run, page: p.page, region: 'page' });
  if (!env.ok || !(env.data || {}).image) {
    box.innerHTML = `<div class="warn err">${esc(env.error || t('sift.crop.fail'))}</div>`;
    return;
  }
  box.innerHTML = `
    <div class="row">
      <button data-act="view.zoom" data-arg="-25">${t('view.zoom.out')}</button>
      <button data-act="view.zoom" data-arg="fit">${t('view.zoom.fit')}</button>
      <button data-act="view.zoom" data-arg="25">${t('view.zoom.in')}</button>
      <button data-act="view.stage.close">${t('view.close')}</button>
    </div>
    ${VS.geo.has ? `<p class="dim">${t('view.overlay')}</p>` : ''}
    <div class="stage"><div class="stage-wrap" style="width:${VS.zoom}%">
      <img id="stage-img" src="${esc(env.data.image)}" alt="${esc(p.page)}">
      ${stageOverlay(VS.geo)}
    </div></div>`;
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
    // «сторінка цілком» назавжди лишається на «Хвилинку…».
    //
    // ⚠ Індекс береться з `map`, а не з лічильника вцілілих: він же номер
    // рядка в тексті, і зсунувши його, клік показував би чужий рядок.
    if (!Array.isArray(sh) || !sh.length) return '';
    const attrs = `class="ln" data-i="${i}"`;
    return Array.isArray(sh[0])
      ? `<polygon ${attrs} points="${sh.map((pt) => pt.join(',')).join(' ')}"/>`
      : `<rect ${attrs} x="${sh[0]}" y="${sh[1]}"
           width="${sh[2] - sh[0]}" height="${sh[3] - sh[1]}"/>`;
  });
  return `<svg class="stage-ov" viewBox="0 0 ${w} ${h}"
    preserveAspectRatio="none">${shapes.join('')}</svg>`;
}

/**
 * Зв'язок тексту й рамок — ДВА делегованих слухачі, прив'язані раз.
 *
 * 🔴 Не `data-act` на кожній рамці: сторінка щільного формуляра має до двохсот
 * рядків, і двісті атрибутів через глобальний диспетчер заради наведення — не
 * той інструмент. Диспетчер існує для ДІЙ, а наведення дією не є.
 */
function viewBindSync() {
  if (_syncBound) return;
  _syncBound = true;
  document.addEventListener('mouseover', (ev) => {
    const n = ev.target.closest('#view-text .vln, .stage-ov .ln');
    if (!n) return;
    viewMark(Number(n.dataset.i), false);
  });
  document.addEventListener('mouseout', (ev) => {
    if (!ev.target.closest('#view-text .vln, .stage-ov .ln')) return;
    document.querySelectorAll('.vln.hot, .ln.hot').forEach(
      (x) => x.classList.remove('hot'));
  });
  document.addEventListener('click', (ev) => {
    const n = ev.target.closest('#view-text .vln, .stage-ov .ln');
    if (!n) return;
    viewMark(Number(n.dataset.i), true);
  });
}

/** Підсвітити рядок з обох боків; `pick` — ще й прокрутити та взяти вирізку. */
function viewMark(i, pick) {
  const cls = pick ? 'on' : 'hot';
  document.querySelectorAll(`.vln.${cls}, .ln.${cls}`).forEach(
    (x) => x.classList.remove(cls));
  const txt = document.querySelector(`#view-text .vln[data-i="${i}"]`);
  const box = document.querySelector(`.stage-ov .ln[data-i="${i}"]`);
  if (txt) txt.classList.add(cls);
  if (box) box.classList.add(cls);
  if (!pick) return;
  if (txt) txt.scrollIntoView({ block: 'nearest' });
  if (box) box.scrollIntoView({ block: 'nearest' });
  viewCrop(i);
}

/**
 * 🔴 Вирізка РЯДКА, а не сторінки: 15 КБ проти приблизно мегабайта, а звірок
 * за сеанс бувають десятки.
 */
async function viewCrop(i) {
  const p = VS.pages[VS.i];
  const box = el('view-line');
  if (!p || !box) return;
  const env = await callOp('page.view',
    { run: VS.run, page: p.page, line: i, region: 'line' });
  if (!env.ok) {
    box.innerHTML = `<div class="warn err">${esc(env.error || '')}</div>`;
    return;
  }
  const d = env.data || {};
  box.innerHTML = `
    ${renderWarnings(env)}
    <img class="crop" src="${esc(d.image || '')}"
      alt="${esc(t('sift.crop'))}">
    <p class="muted mono">${esc(d.text || '')}</p>`;
}

/**
 * 🔴 Другий голос — сусідній прогін ТІЄЇ САМОЇ справи іншим рушієм.
 *
 * Збіг двох рушіїв означає надійне читання; розбіжність саме на прізвищі
 * означає, що ознака в пікселях — і судити має око, а не третій алгоритм.
 *
 * 🔴 Вирівнювання за номером рядка законне ЛИШЕ тому, що обидва прогони йдуть
 * по спільному кешу сегментації, тобто ділять ті самі рамки. Якщо рядків
 * різна кількість, порівняння за номером мовчки показувало б чужий рядок —
 * гірше за відсутність порівняння. Тому в такому разі кажемо про це прямо.
 */
function viewAltReset() {
  const box = el('view-alt');
  if (!box) return;
  const mine = (VS.all || []).find((r) => r.name === VS.run) || {};
  const twin = (VS.all || []).find(
    (r) => r.name !== VS.run && r.case_dir && r.case_dir === mine.case_dir
      && r.engine_id && r.engine_id !== mine.engine_id);
  VS.alt = twin || null;
  box.innerHTML = twin
    ? `<details id="alt-box"><summary>${t('view.alt')} ${
        eng(twin.engine_id, true, LANG)}</summary>
        <div id="alt-body"><p class="muted">${t('view.alt.open')}</p></div></details>`
    : '';
  const det = el('alt-box');
  if (det) det.addEventListener('toggle', () => { if (det.open) viewAltLoad(); },
                                { once: true });
}

async function viewAltLoad() {
  const p = VS.pages[VS.i];
  const box = el('alt-body');
  if (!VS.alt || !p || !box) return;
  const env = await callOp('page.text', { run: VS.alt.name, page: p.page });
  if (!env.ok) {
    box.innerHTML = `<div class="warn">${esc(env.error || '')}</div>`;
    return;
  }
  const other = (env.data || {}).lines || [];
  if (other.length !== VS.lines.length) {
    box.innerHTML = `<div class="warn">${t('view.alt.mismatch')
      .replace('{a}', VS.lines.length).replace('{b}', other.length)}</div>`;
    return;
  }
  box.innerHTML = `<pre class="lines alt">${other.map((ln, i) =>
    `<span class="vln${ln !== VS.lines[i] ? ' differs' : ''}" data-i="${i}"
      ><span class="no">${i + 1}</span>${esc(ln)}</span>`).join('\n')}</pre>`;
}

Object.assign(ACTIONS, {
  'view.open': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    await viewOpenRun(String(fd.get('run') || '').trim());
  },

  'view.step': (_ev, elm) => viewShow(VS.i + Number(elm.dataset.arg || 0)),

  'view.goto': () => viewShow(Number((el('view-page') || {}).value || 0)),

  'view.page': async () => {
    // Перемикач, а не «завантажити ще раз»: знімок лишається відкритим на всі
    // кроки далі, бо людина в цей момент саме звіряє текст зі сканом.
    VS.shot = !VS.shot;
    if (VS.shot) await viewShot();
    else el('view-stage').innerHTML = '';
  },

  'view.zoom': (_ev, elm) => {
    // 🔴 Зум міняє ОБГОРТКУ, а не картинку. Оверлей рамок розтягнутий по
    // обгортці, тож зміна ширини самого `<img>` роз'їжджає рамки з рядками —
    // і клік по рамці віддає текст іншого рядка. Помітно це лише після
    // першого «+», а «вписати» випадково лікує, тобто вада виглядає плаваючою.
    const wrap = document.querySelector('.stage-wrap');
    if (!wrap) return;
    VS.zoom = elm.dataset.arg === 'fit'
      ? 100
      : Math.max(25, Math.min(600, VS.zoom + Number(elm.dataset.arg)));
    wrap.style.width = `${VS.zoom}%`;
  },

  'view.stage.close': () => {
    VS.shot = false;
    const b = el('view-stage');
    if (b) b.innerHTML = '';
  },
});

// 🔴 Клавіші гортання — головний спосіб читати справу: сотні аркушів мишею не
// гортають. Роутер сам не спрацьовує в полях уводу, тож поле прогону лишається
// придатним для набору.
Object.assign(KEYS, {
  view: {
    ArrowRight: () => viewShow(VS.i + 1),
    ArrowLeft: () => viewShow(VS.i - 1),
    PageDown: () => viewShow(VS.i + 1),
    PageUp: () => viewShow(VS.i - 1),
    Home: () => viewShow(0),
    End: () => viewShow(VS.pages.length - 1),
    p: () => ACTIONS['view.page'](),
    '+': () => ACTIONS['view.zoom'](null, { dataset: { arg: '25' } }),
    '-': () => ACTIONS['view.zoom'](null, { dataset: { arg: '-25' } }),
    0: () => ACTIONS['view.zoom'](null, { dataset: { arg: 'fit' } }),
  },
});
