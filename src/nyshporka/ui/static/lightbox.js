/**
 * 🔍 Повноекранний переглядач аркуша.
 *
 * Архівний скан — це не картинка, а документ: 4000 px завширшки, скоропис,
 * плями, вицвіле чорнило. Дивитись на нього в колонці шириною пів екрана можна
 * лише щоб упізнати аркуш; читати — ні. Тому переглядач окремий і на весь
 * екран.
 *
 * 🔴 Зум прив'язаний до КУРСОРА, а не до центру. Це не зручність, а різниця
 * між придатним і непридатним: людина наводить на потрібне слово й крутить
 * колесо, і при зумі «в центр» це слово одразу їде за край — доводиться
 * ловити його панорамуванням наосліп. Саме через це від переглядачів
 * відмовляються після третьої спроби.
 *
 * 🔴 Масштаб і зсув ПЕРЕЖИВАЮТЬ перехід на сусідній аркуш. Сторінки однієї
 * книги мають ту саму геометрію: наблизившись до правої колонки, людина гортає
 * саме її через увесь опис. Скидання до вписаного на кожному кроці змушувало б
 * прицілюватись наново — на трьохсот аркушах це і є вся робота.
 *
 * ⚠ Стрілки й смуга спливають на рух миші й ховаються за дві секунди спокою:
 * постійні контроли лежать поверх аркуша, а на сканах текст іде до самого
 * краю — саме там, де кнопка.
 *
 * Модуль нічого не знає ні про справи, ні про прогони: йому дають кількість
 * аркушів і спосіб дістати один. Тому ним однаково користуються перегляд
 * матеріалу й гортач прочитаного.
 */

/** Скільки чекати спокою, перш ніж сховати контроли (мс). */
const IDLE_MS = 2000;

/** Межі масштабу. Нижня — щоб аркуш не зник у крапку, верхня — щоб не з'їсти пам'ять. */
const MIN_Z = 0.05;
const MAX_Z = 12;

const DEFAULT_LABELS = {
  prev: 'Попередній', next: 'Наступний', close: 'Закрити',
  fit: 'Вписати', keys: '← → гортати · колесо — масштаб · тягнути — рухати · Esc — вийти',
  loading: 'Хвилинку…',
};

/**
 * Відкрити переглядач.
 *
 * @param {object}   o
 * @param {number}   o.count   скільки аркушів усього
 * @param {number}   o.index   з якого почати
 * @param {Function} o.load    `async (i) => {image, label}`; порожньо — помилка
 * @param {object}   o.labels  підписи (мова — справа того, хто кличе)
 * @param {Function} o.onIndex зворотний виклик при зміні аркуша
 * @returns {{close: Function}}
 */
export function lightbox({ count, index = 0, load, labels = {}, onIndex } = {}) {
  const L = { ...DEFAULT_LABELS, ...labels };
  const n = Math.max(0, Number(count) || 0);
  if (!n || typeof load !== 'function') return { close() {} };

  let i = Math.max(0, Math.min(n - 1, Number(index) || 0));
  // 🔴 `z === null` означає «ще не вписували». Перший аркуш вписується сам, а
  // далі масштаб тримається — див. пояснення в шапці модуля.
  let z = null;
  let x = 0;
  let y = 0;
  let seq = 0;
  let idle = null;

  const root = document.createElement('div');
  root.className = 'lb';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.innerHTML = `
    <div class="lb-canvas"><img class="lb-img" alt=""></div>
    <button class="lb-nav lb-prev" title="${esc(L.prev)}" aria-label="${esc(L.prev)}">‹</button>
    <button class="lb-nav lb-next" title="${esc(L.next)}" aria-label="${esc(L.next)}">›</button>
    <div class="lb-bar">
      <span class="lb-pos mono"></span>
      <span class="lb-label"></span>
      <span class="lb-zoom mono"></span>
      <button class="lb-fit" title="${esc(L.fit)}">${esc(L.fit)}</button>
      <button class="lb-close" title="${esc(L.close)}" aria-label="${esc(L.close)}">✕</button>
    </div>
    <div class="lb-hint">${esc(L.keys)}</div>`;
  document.body.appendChild(root);

  // 🔴 Прокрутку сторінки під переглядачем блокуємо: інакше колесо, дійшовши
  // до межі масштабу, починає прокручувати документ ПІД ним — і людина
  // виходить із перегляду, не зрозумівши, що сталось.
  const scrollWas = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  const img = root.querySelector('.lb-img');
  const canvas = root.querySelector('.lb-canvas');
  const posEl = root.querySelector('.lb-pos');
  const labEl = root.querySelector('.lb-label');
  const zoomEl = root.querySelector('.lb-zoom');

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function apply() {
    img.style.transform = `translate(${x}px, ${y}px) scale(${z ?? 1})`;
    zoomEl.textContent = z ? `${Math.round(z * 100)}%` : '';
  }

  /** Вписати аркуш у вікно й поставити його по центру. */
  function fit() {
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    const pad = 24;
    z = Math.min((window.innerWidth - pad) / iw, (window.innerHeight - pad) / ih, 1);
    x = 0;
    y = 0;
    apply();
  }

  /**
   * Змінити масштаб, лишивши на місці точку під курсором.
   *
   * Уся арифметика тут заради одного: точка (cx, cy) екрана мусить показувати
   * ту саму точку аркуша до й після зміни. Без цього зум «утікає» від того,
   * на що дивляться.
   */
  function zoomAt(cx, cy, factor) {
    const cur = z ?? 1;
    const next = Math.max(MIN_Z, Math.min(MAX_Z, cur * factor));
    if (next === cur) return;
    const r = canvas.getBoundingClientRect();
    const ox = cx - r.left - r.width / 2;
    const oy = cy - r.top - r.height / 2;
    x = ox - (ox - x) * (next / cur);
    y = oy - (oy - y) * (next / cur);
    z = next;
    apply();
  }

  async function showFrame(k) {
    const my = ++seq;
    i = Math.max(0, Math.min(n - 1, k));
    posEl.textContent = `${i + 1} / ${n}`;
    labEl.textContent = L.loading;
    root.classList.add('busy');
    let got = null;
    try {
      got = await load(i);
    } catch {
      got = null;
    }
    if (my !== seq) return;                 // нас обігнало свіжіше гортання
    root.classList.remove('busy');
    if (!got || !got.image) {
      labEl.textContent = got && got.error ? got.error : '—';
      img.removeAttribute('src');
      return;
    }
    labEl.textContent = got.label || '';
    img.src = got.image;
    root.querySelector('.lb-prev').disabled = i === 0;
    root.querySelector('.lb-next').disabled = i >= n - 1;
    if (typeof onIndex === 'function') onIndex(i);
  }

  img.addEventListener('load', () => {
    // Вписуємо ЛИШЕ перший аркуш: далі масштаб належить людині.
    if (z === null) fit();
    else apply();
  });

  // ── миша ───────────────────────────────────────────────────────────────────
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    // Крок сталий у логарифмі: інакше на великому масштабі один щиглик колеса
    // перестрибує півсторінки, а на малому не робить нічого.
    zoomAt(ev.clientX, ev.clientY, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });

  let drag = null;
  canvas.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    drag = { px: ev.clientX, py: ev.clientY, x, y };
    canvas.setPointerCapture(ev.pointerId);
    root.classList.add('grabbing');
  });
  canvas.addEventListener('pointermove', (ev) => {
    wake();
    if (!drag) return;
    x = drag.x + (ev.clientX - drag.px);
    y = drag.y + (ev.clientY - drag.py);
    apply();
  });
  const endDrag = () => { drag = null; root.classList.remove('grabbing'); };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('dblclick', (ev) => zoomAt(ev.clientX, ev.clientY, 2));

  // ── спливання контролів ────────────────────────────────────────────────────
  function wake() {
    root.classList.remove('idle');
    clearTimeout(idle);
    idle = setTimeout(() => root.classList.add('idle'), IDLE_MS);
  }
  root.addEventListener('mousemove', wake);
  wake();

  // ── клавіші ────────────────────────────────────────────────────────────────
  // 🔴 Слухач на `window` із перехопленням: доки переглядач відкритий, клавіші
  // належать ЙОМУ. Інакше ← → доходили б і до екрана під ним, і сторінка
  // гортала б у двох місцях одночасно.
  function onKey(ev) {
    const k = ev.key;
    const map = {
      ArrowRight: () => showFrame(i + 1), PageDown: () => showFrame(i + 1),
      ' ': () => showFrame(i + 1),
      ArrowLeft: () => showFrame(i - 1), PageUp: () => showFrame(i - 1),
      Home: () => showFrame(0), End: () => showFrame(n - 1),
      '+': () => zoomAt(innerWidth / 2, innerHeight / 2, 1.25),
      '=': () => zoomAt(innerWidth / 2, innerHeight / 2, 1.25),
      '-': () => zoomAt(innerWidth / 2, innerHeight / 2, 1 / 1.25),
      0: fit, f: fit, F: fit,
      Escape: close,
    };
    const fn = map[k];
    if (!fn) return;
    ev.preventDefault();
    ev.stopPropagation();
    wake();
    fn();
  }
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('resize', () => { if (z === null) fit(); });

  root.querySelector('.lb-prev').addEventListener('click', () => showFrame(i - 1));
  root.querySelector('.lb-next').addEventListener('click', () => showFrame(i + 1));
  root.querySelector('.lb-fit').addEventListener('click', fit);
  root.querySelector('.lb-close').addEventListener('click', close);
  // Клік повз аркуш закриває — але лише коли не тягнули: інакше панорамування,
  // що закінчилось на тлі, викидало б із перегляду.
  root.addEventListener('click', (ev) => {
    if (ev.target === root || ev.target === canvas) close();
  });

  function close() {
    seq += 1;                                // недокачане не домалює себе
    clearTimeout(idle);
    window.removeEventListener('keydown', onKey, true);
    document.body.style.overflow = scrollWas;
    root.remove();
  }

  showFrame(i);
  return { close, show: showFrame };
}
