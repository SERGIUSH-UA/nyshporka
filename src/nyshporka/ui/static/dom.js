// Нишпорка — спільні DOM-хелпери рендеру списків.
//
// Консоль малює все через `innerHTML = …` цілком (≈180 місць). Для великих
// списків це дає три видимі дефекти: контейнер на мить схлопується у нуль
// (сторінка «моргає» і стрибає), скрол усередині списку злітає на початок,
// а сторінка під ним підскакує. Пагінатори Банку/Конфузерів/Форм навіть мали
// милицю `scrollIntoView` саме щоб це компенсувати.
//
// swapHtml() тримає висоту контейнера на час підміни й повертає скрол.

/**
 * Замінити вміст елемента, не давши сторінці стрибнути.
 * @param {HTMLElement} el      контейнер
 * @param {string}      html    нова розмітка
 * @param {{keepScroll?: boolean}} [opts] keepScroll=false — свідомо на початок
 *                                        (напр. після зміни фільтра)
 */
export function swapHtml(el, html, opts = {}) {
  if (!el) return;
  const keepScroll = opts.keepScroll !== false;
  const scroller = _scrollParent(el);
  const prevSelf = el.scrollTop;
  const prevOuter = scroller ? scroller.scrollTop : 0;
  // висота ДО підміни: інакше між очищенням і промальовкою нового вмісту
  // контейнер має нульову висоту і все під ним підстрибує вгору
  //
  // ⚠ `min-height` на елементі табличного боксу (`<tbody>`, `<tr>`) браузер
  // ігнорує — а саме `<tbody id="lib-rows">` тут найдовший список і найбільший
  // стрибок. Для таких випадків тримаємо висоту через `height` на самому боксі:
  // на час підміни це та сама розпірка, і вона знімається тим самим кадром.
  const h = el.offsetHeight;
  const prop = /^(TBODY|THEAD|TFOOT|TR|TABLE)$/.test(el.tagName)
    ? 'height' : 'minHeight';
  if (h) el.style[prop] = h + 'px';

  el.classList.remove('swapped');
  void el.offsetWidth;            // рестарт CSS-анімації проявлення
  el.innerHTML = html;
  el.classList.add('swapped');

  if (keepScroll) {
    el.scrollTop = prevSelf;
    if (scroller) scroller.scrollTop = prevOuter;
  }
  // висоту відпускаємо лише коли новий вміст уже вимірявся
  requestAnimationFrame(() => requestAnimationFrame(() => { el.style[prop] = ''; }));
}

/** Найближчий предок, що реально скролиться (зазвичай <main>). */
function _scrollParent(el) {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const ov = getComputedStyle(p).overflowY;
    if ((ov === 'auto' || ov === 'scroll') && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

/**
 * Скелетон-рядки таблиці. Текстова заглушка «завантаження…» має іншу висоту
 * за реальні дані, тому при кожному завантаженні контент стрибав.
 * @param {number} rows скільки рядків малювати
 * @param {number} cols скільки колонок у таблиці (для colspan)
 */
export function skelRows(rows = 8, cols = 1) {
  const cell = `<td colspan="${cols}" style="padding:4px 8px"><div class="skel skel-cell"></div></td>`;
  return `<tr>${cell}</tr>`.repeat(rows);
}

/** Скелетон-картки для сіток (Банк, Конфузери, Форми, Гортач). */
export function skelCards(n = 8) {
  return `<div class="skel skel-card"></div>`.repeat(n);
}
