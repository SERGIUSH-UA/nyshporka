/**
 * 🔍 Повноекранна читалка аркуша.
 *
 * Архівний скан — це не картинка, а документ: 4000 px завширшки, скоропис,
 * плями, вицвіле чорнило. Дивитись на нього в колонці шириною пів екрана можна
 * лише щоб упізнати аркуш; читати — ні.
 *
 * 🔴 Прочитаний текст показується НА СВОЄМУ МІСЦІ, а не списком під знімком.
 * Рядок формуляра — це короткий шматок усередині графи, і в списку він втрачає
 * єдине, що робить його зрозумілим: де він стояв. Читати такий список означає
 * щоразу шукати очима, звідки взявся рядок; саме тому текст тут спливає над
 * своєю рамкою, а бічна панель дає або один рядок, або весь аркуш підряд.
 *
 * 🔴 Зум прив'язаний до КУРСОРА, а не до центру. Це не зручність, а різниця
 * між придатним і непридатним: людина наводить на потрібне слово й крутить
 * колесо, і при зумі «в центр» це слово одразу їде за край — доводиться
 * ловити його панорамуванням наосліп. Саме через це від переглядачів
 * відмовляються після третьої спроби.
 *
 * 🔴 Масштаб і зсув ПЕРЕЖИВАЮТЬ перехід на сусідній аркуш. Сторінки однієї
 * книги мають ту саму геометрію: підібравши збільшення, за якого скоропис
 * розбирається, читач гортає ним увесь опис. Скидати його на кожному кроці —
 * означає змушувати підбирати наново, а на трьохстах аркушах це і є вся робота.
 *
 * 🔴 Наближення дозволене ГЛИБШЕ за 100%. Скоропис часто читається лише на
 * збільшенні, і розмиття тут менша біда, ніж неможливість роздивитись.
 *
 * ⚠ Стрілки й смуга спливають на рух миші й ховаються за дві секунди спокою:
 * постійні контроли лежать поверх аркуша, а на сканах текст іде до самого
 * краю — саме там, де кнопка.
 *
 * Модуль нічого не знає ні про справи, ні про прогони: йому дають кількість
 * аркушів і спосіб дістати один. Тому ним однаково користуються перегляд
 * матеріалу (самі знімки) і гортач прочитаного (знімок разом із текстом).
 */

/** Скільки чекати спокою, перш ніж сховати контроли (мс). */
const IDLE_MS = 2000;

/** Межі масштабу. Нижня — щоб аркуш не зник у крапку, верхня — щоб не з'їсти пам'ять. */
const MIN_Z = 0.05;
const MAX_Z = 12;

/** Поріг у пікселях, нижче якого рух вважається тремтінням руки, а не жестом. */
const DRAG_SLOP = 4;

const DEFAULT_LABELS = {
  prev: 'Попередній', next: 'Наступний', close: 'Закрити', fit: 'Вписати',
  text: 'Текст аркуша', notext: 'цей аркуш не прочитано',
  boxes: 'Рамки', boxesWhy: 'показувати рамки рядків на скані (клавіша B)',
  alt: 'другий голос',
  keys: '← → гортати · колесо — масштаб · тягнути — рухати · T — текст · Esc — вийти',
  loading: 'Хвилинку…',
};

const NS = 'http://www.w3.org/2000/svg';

/**
 * Чи показувати рамки рядків. Живе поза окремим відкриттям читалки навмисно:
 * це не властивість аркуша, а звичка читача — вимкнувши їх на одній справі,
 * він не хоче вмикати їх знову на наступній.
 *
 * ⚠ У сховищі браузера, а не в пам'яті: читалку відкривають десятки разів за
 * сеанс, і між ними сторінку перезавантажують.
 */
let SHOW_BOXES = true;
try {
  SHOW_BOXES = localStorage.getItem('nysh.lb.boxes') !== '0';
} catch {
  // Приватне вікно чи заборонене сховище — лишаємо дефолт. Читалка не має
  // права не відкритись через налаштування, якого нема де тримати.
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/**
 * Відкрити читалку.
 *
 * `load(i)` віддає `{image, label}` і — коли є що — `size: [w, h]`,
 * `shapes: [полігон | рамка | null]`, `lines: [текст]`, `alt: [текст]`.
 * Порожні `shapes` — законна відповідь: аркуш просто ще не читали.
 *
 * @returns {{ok: boolean, why?: string, close: Function}}
 */
export function lightbox({ count, index = 0, load, labels = {}, onIndex } = {}) {
  const L = { ...DEFAULT_LABELS, ...labels };
  const n = Math.max(0, Number(count) || 0);
  // 🔴 Мовчазної відмови тут бути не може. Кнопка, яка нічого не робить і
  // нічого не каже, читається як зламаний застосунок — а найчастіша причина
  // прозаїчна: показувати ще нічого, бо справу не відкрито.
  if (!n) return { ok: false, why: 'empty', close() {} };
  if (typeof load !== 'function') return { ok: false, why: 'noload', close() {} };

  let i = Math.max(0, Math.min(n - 1, Number(index) || 0));
  // `z === null` — «ще не вписували». Перший аркуш вписується сам, далі
  // масштаб належить читачеві.
  let z = null;
  let x = 0;
  let y = 0;
  let seq = 0;
  let idle = null;
  let drag = null;
  let press = { moved: false, backdrop: false };
  let cur = {};            // те, що віддав `load` для поточного аркуша
  let pinned = null;       // закріплений рядок
  let sideOpen = false;

  const root = document.createElement('div');
  root.className = 'lb';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.innerHTML = `
    <div class="lb-canvas">
      <div class="lb-stage">
        <img class="lb-img" alt="">
        <svg class="lb-ov" preserveAspectRatio="none"></svg>
      </div>
    </div>
    <div class="lb-tip" hidden></div>
    <aside class="lb-side" hidden><div class="lb-side-body"></div></aside>
    <button class="lb-nav lb-prev" title="${esc(L.prev)}" aria-label="${esc(L.prev)}">‹</button>
    <button class="lb-nav lb-next" title="${esc(L.next)}" aria-label="${esc(L.next)}">›</button>
    <div class="lb-bar">
      <span class="lb-pos mono"></span>
      <span class="lb-label"></span>
      <span class="lb-zoom mono"></span>
      <button class="lb-boxes" title="${esc(L.boxesWhy)}">${esc(L.boxes)}</button>
      <button class="lb-text" title="${esc(L.text)}">${esc(L.text)}</button>
      <button class="lb-fit" title="${esc(L.fit)}">${esc(L.fit)}</button>
      <button class="lb-close" title="${esc(L.close)}" aria-label="${esc(L.close)}">✕</button>
    </div>
    <div class="lb-hint">${esc(L.keys)}</div>`;
  document.body.appendChild(root);

  // 🔴 Прокрутку сторінки під читалкою блокуємо: інакше колесо, дійшовши до
  // межі масштабу, починає прокручувати документ ПІД нею — і людина виходить
  // із перегляду, не зрозумівши, що сталось.
  const scrollWas = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  const canvas = root.querySelector('.lb-canvas');
  const stage = root.querySelector('.lb-stage');
  const img = root.querySelector('.lb-img');
  const ov = root.querySelector('.lb-ov');
  const tip = root.querySelector('.lb-tip');
  const side = root.querySelector('.lb-side');
  const sideBody = root.querySelector('.lb-side-body');
  const posEl = root.querySelector('.lb-pos');
  const labEl = root.querySelector('.lb-label');
  const zoomEl = root.querySelector('.lb-zoom');

  function apply() {
    stage.style.transform = `translate(${x}px, ${y}px) scale(${z ?? 1})`;
    zoomEl.textContent = z ? `${Math.round(z * 100)}%` : '';
  }

  /**
   * Показувати рамки чи ні.
   *
   * 🔴 Разом із рамками зникає й підказка на наведення — інакше текст спливав
   * би над невидимою фігурою, і аркуш «сам собою» показував би написи там, де
   * читач щойно попросив чистий папір.
   *
   * Панель тексту при цьому лишається: вимикають саме РОЗМІТКУ ПОВЕРХ скану, а
   * не доступ до прочитаного.
   */
  function applyBoxes() {
    root.classList.toggle('no-boxes', !SHOW_BOXES);
    if (!SHOW_BOXES) hideTip();
    const btn = root.querySelector('.lb-boxes');
    if (btn) btn.classList.toggle('on', SHOW_BOXES);
  }

  function toggleBoxes(on) {
    SHOW_BOXES = on === undefined ? !SHOW_BOXES : !!on;
    try {
      localStorage.setItem('nysh.lb.boxes', SHOW_BOXES ? '1' : '0');
    } catch {
      // Не змогли запам'ятати — вибір діє до кінця сеансу. Це гірше за
      // запам'ятований, але незрівнянно краще за відмову перемкнути.
    }
    applyBoxes();
  }

  /** Вписати аркуш у вікно й поставити його по центру. */
  function fit() {
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    const pad = 24;
    const wide = sideOpen ? 380 : 0;
    z = Math.min((window.innerWidth - pad - wide) / iw,
                 (window.innerHeight - pad) / ih, 1);
    x = -wide / 2;
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
    const was = z ?? 1;
    const next = Math.max(MIN_Z, Math.min(MAX_Z, was * factor));
    if (next === was) return;
    const r = canvas.getBoundingClientRect();
    const ox = cx - r.left - r.width / 2;
    const oy = cy - r.top - r.height / 2;
    x = ox - (ox - x) * (next / was);
    y = oy - (oy - y) * (next / was);
    z = next;
    apply();
  }

  // ── текст на своєму місці ──────────────────────────────────────────────────
  /**
   * Рамки рядків у координатах САМОГО аркуша.
   *
   * SVG розтягнутий по знімку й має його `viewBox`, тож при зумі не треба
   * нічого перераховувати: масштаб бере на себе браузер, а рамка лишається
   * рівно там, де рядок.
   *
   * ⚠ `null` серед фігур — законне значення: рядок без обведення рамки не має,
   * і раннер пише в масив саме `null`, зберігаючи довжину. Індекс — це номер
   * рядка в тексті, тож пропускати елементи не можна.
   */
  function drawOverlay() {
    ov.innerHTML = '';
    const size = cur.size;
    const shapes = cur.shapes || [];
    if (!size || !shapes.length) {
      ov.setAttribute('viewBox', '0 0 1 1');
      return;
    }
    ov.setAttribute('viewBox', `0 0 ${size[0]} ${size[1]}`);
    shapes.forEach((sh, k) => {
      if (!Array.isArray(sh) || !sh.length) return;
      const el = document.createElementNS(NS,
        Array.isArray(sh[0]) ? 'polygon' : 'rect');
      if (Array.isArray(sh[0])) {
        el.setAttribute('points', sh.map((p) => p.join(',')).join(' '));
      } else {
        el.setAttribute('x', sh[0]);
        el.setAttribute('y', sh[1]);
        el.setAttribute('width', sh[2] - sh[0]);
        el.setAttribute('height', sh[3] - sh[1]);
      }
      el.setAttribute('class', 'lb-shape');
      el.dataset.i = String(k);
      ov.appendChild(el);
    });
  }

  function lineText(k) {
    const t = (cur.lines || [])[k];
    return typeof t === 'string' ? t : (t || {}).text || '';
  }

  /**
   * Підказка над рамкою.
   *
   * ⚠ Якщо місця вгорі немає — стає під рамкою. Інакше на верхніх рядках
   * аркуша підказка вилазить за край екрана, тобто зникає рівно там, де
   * читають найчастіше: у заголовку формуляра.
   */
  function showTip(k, el) {
    const text = lineText(k);
    if (!text) return;
    tip.textContent = text;
    tip.hidden = false;
    const b = el.getBoundingClientRect();
    tip.style.left = `${b.left + b.width / 2}px`;
    const above = b.top - 10;
    const below = above < 60;
    tip.classList.toggle('is-below', below);
    tip.style.top = `${below ? b.bottom + 10 : above}px`;
  }

  function hideTip() { tip.hidden = true; }

  function pin(k) {
    pinned = k;
    ov.querySelectorAll('.lb-shape.on').forEach((s) => s.classList.remove('on'));
    const sh = ov.querySelector(`.lb-shape[data-i="${k}"]`);
    if (sh) sh.classList.add('on');
    if (sideOpen) drawSide();
  }

  /**
   * Бічна панель: увесь аркуш підряд, із закріпленим рядком у фокусі.
   *
   * 🔴 Другий голос стоїть ПІД своїм рядком, а не окремим стовпцем. Збіг
   * голосів означає надійне читання, розбіжність — що ознака в пікселях і
   * судити має око; порівнювати їх можна лише поруч.
   */
  function drawSide() {
    const lines = cur.lines || [];
    if (!lines.length) {
      sideBody.innerHTML = `<p class="lb-none">${esc(L.notext)}</p>`;
      return;
    }
    const alt = cur.alt || [];
    sideBody.innerHTML = lines.map((_, k) => {
      const other = alt[k];
      const differs = other && other !== lineText(k);
      return `<div class="lb-line${k === pinned ? ' on' : ''}" data-i="${k}">
        <span class="no">${k + 1}</span><span class="tx">${esc(lineText(k))}</span>
        ${differs ? `<span class="alt" title="${esc(L.alt)}">${esc(other)}</span>` : ''}
      </div>`;
    }).join('');
    const node = sideBody.querySelector('.lb-line.on');
    if (node) node.scrollIntoView({ block: 'center' });
  }

  function toggleSide(on) {
    sideOpen = on === undefined ? !sideOpen : !!on;
    side.hidden = !sideOpen;
    root.classList.toggle('with-side', sideOpen);
    if (sideOpen) drawSide();
  }

  // ── гортання ───────────────────────────────────────────────────────────────
  async function showFrame(k) {
    const my = ++seq;
    i = Math.max(0, Math.min(n - 1, k));
    posEl.textContent = `${i + 1} / ${n}`;
    labEl.textContent = L.loading;
    root.classList.add('busy');
    hideTip();
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
      cur = {};
      drawOverlay();
      if (sideOpen) drawSide();
      return;
    }
    cur = got;
    pinned = null;
    labEl.textContent = got.label || '';
    img.src = got.image;
    drawOverlay();
    if (sideOpen) drawSide();
    root.querySelector('.lb-prev').disabled = i === 0;
    root.querySelector('.lb-next').disabled = i >= n - 1;
    root.classList.toggle('has-text', !!(got.lines || []).length);
    if (typeof onIndex === 'function') onIndex(i);
  }

  img.addEventListener('load', () => {
    // Вписуємо ЛИШЕ перший аркуш: далі масштаб належить читачеві.
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

  canvas.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    drag = { px: ev.clientX, py: ev.clientY, x, y };
    // 🔴 Де натискання ПОЧАЛОСЬ, а не де скінчилось. Жест, що стартував на
    // самому аркуші й доїхав до тла, — це перетягування, а не клік повз.
    press = { moved: false, backdrop: ev.target === canvas || ev.target === root };
    canvas.setPointerCapture(ev.pointerId);
    root.classList.add('grabbing');
  });

  canvas.addEventListener('pointermove', (ev) => {
    wake();
    if (!drag) {
      // Наведення на рамку — підказка з текстом рядка на його місці.
      const sh = SHOW_BOXES && ev.target && ev.target.closest
        ? ev.target.closest('.lb-shape') : null;
      if (sh) showTip(Number(sh.dataset.i), sh);
      else hideTip();
      return;
    }
    const dx = ev.clientX - drag.px;
    const dy = ev.clientY - drag.py;
    if (Math.abs(dx) > DRAG_SLOP || Math.abs(dy) > DRAG_SLOP) press.moved = true;
    if (press.moved) hideTip();
    x = drag.x + dx;
    y = drag.y + dy;
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
  // 🔴 Слухач на `window` із перехопленням: доки читалка відкрита, клавіші
  // належать ЇЙ. Інакше ← → доходили б і до екрана під нею, і сторінка
  // гортала б у двох місцях одночасно.
  function onKey(ev) {
    const map = {
      ArrowRight: () => showFrame(i + 1), PageDown: () => showFrame(i + 1),
      ' ': () => showFrame(i + 1),
      ArrowLeft: () => showFrame(i - 1), PageUp: () => showFrame(i - 1),
      Home: () => showFrame(0), End: () => showFrame(n - 1),
      '+': () => zoomAt(innerWidth / 2, innerHeight / 2, 1.25),
      '=': () => zoomAt(innerWidth / 2, innerHeight / 2, 1.25),
      '-': () => zoomAt(innerWidth / 2, innerHeight / 2, 1 / 1.25),
      0: fit, f: fit, F: fit,
      t: () => toggleSide(), T: () => toggleSide(), е: () => toggleSide(),
      b: () => toggleBoxes(), B: () => toggleBoxes(), и: () => toggleBoxes(),
      Escape: close,
    };
    const fn = map[ev.key];
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
  root.querySelector('.lb-boxes').addEventListener('click', () => toggleBoxes());
  root.querySelector('.lb-text').addEventListener('click', () => toggleSide());
  root.querySelector('.lb-close').addEventListener('click', close);

  // Клік по рядку в панелі — підсвітити його на скані.
  sideBody.addEventListener('click', (ev) => {
    const row = ev.target.closest ? ev.target.closest('.lb-line') : null;
    if (row) pin(Number(row.dataset.i));
  });

  /**
   * Клік повз аркуш закриває — але лише справжній клік.
   *
   * Три умови разом, і кожна закриває свою дірку: натискання почалось на тлі
   * (а не на аркуші), відпустилось теж на тлі, і між ними рука не рухалась.
   * Забравши будь-яку з них, ми повертаємо закриття посеред перетягування.
   */
  root.addEventListener('click', (ev) => {
    const sh = SHOW_BOXES && ev.target && ev.target.closest
      ? ev.target.closest('.lb-shape') : null;
    if (sh && !press.moved) { pin(Number(sh.dataset.i)); return; }
    if (press.moved || !press.backdrop) return;
    if (ev.target === root || ev.target === canvas) close();
  });

  function close() {
    seq += 1;                                // недокачане не домалює себе
    clearTimeout(idle);
    window.removeEventListener('keydown', onKey, true);
    document.body.style.overflow = scrollWas;
    root.remove();
  }

  applyBoxes();
  showFrame(i);
  return { ok: true, close, show: showFrame, side: toggleSide, boxes: toggleBoxes };
}
