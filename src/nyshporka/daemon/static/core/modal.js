/**
 * 🪟 Вікно поверх поточного екрана.
 *
 * Правило консолі (макет хвилі 6, апрув дослідника 21.10.2026): окрема сторінка —
 * лише там, де людина працює довго (список, перегляд, розбір). Форма на одну
 * дію, підтвердження й деталь запису відкриваються вікном: людина не губить,
 * звідки прийшла, а екран під вікном живе далі.
 *
 * 🔴 Вузол вікна стоїть у розмітці ПЕРЕД `<main id=view>` (`index.html`). Екрани
 * шукають свої вузли за `id` (`el('hits')`), а екран у вікні й екран під ним
 * можуть мати однакові: першим у документі тоді знаходиться той, що у вікні,
 * тобто той, з яким людина зараз працює.
 *
 * ⚠ `<dialog>.showModal` є не скрізь (Node-заглушка тестів, старі вбудовані
 * переглядачі), тож без нього вікно відкривається атрибутом `open`: модальності
 * немає, але вміст і закриття працюють.
 */
import { t } from './strings.js';
import { esc, el } from './view.js';

/** Хто чекає на закриття поточного вікна (повертає вибір підтвердження). */
let ON_CLOSE = null;

/**
 * Номер відкриття вікна. Вікно, що чекає відповіді (картка, «що змінилось»),
 * запам'ятовує його й малює лише якщо воно досі те саме: інакше запізніла
 * відповідь лягла б у вікно, відкрите після, — і могла б затерти кнопки
 * підтвердження. Вузол `dlg-body` у розмітці постійний, тож перевірка
 * «вузол ще є» тут нічого не ловить.
 */
let SEQ = 0;
export const modalSeq = () => SEQ;

function dlg() { return el('dlg'); }

/** Відкрити вікно з готовою розміткою. Повертає вузол тіла. */
export function openModal({ title = '', body = '', narrow = false, onClose = null } = {}) {
  const d = dlg();
  if (!d) return null;
  settle(undefined);
  SEQ += 1;
  const head = el('dlg-title');
  if (head) head.textContent = title;
  const box = el('dlg-body');
  if (box) box.innerHTML = body;
  d.classList.toggle('narrow', !!narrow);
  ON_CLOSE = onClose;
  // ⚠ Esc і клік повз закривають `<dialog>` самі, оминаючи `closeModal`. Без
  // цього слухача той, хто чекав (екран у вікні повертає `setView` на екран,
  // підтвердження — відповідь), лишився б чекати назавжди.
  if (!d.dataset.wired && d.addEventListener) {
    d.dataset.wired = '1';
    d.addEventListener('close', () => settle(false));
  }
  if (!d.open) {
    if (typeof d.showModal === 'function') {
      try { d.showModal(); } catch { d.setAttribute('open', ''); }
    } else d.setAttribute('open', '');
  }
  return box;
}

/** Заголовок відкритого вікна — коли вміст малює екран, а не той, хто відкрив. */
export function modalTitle(title) {
  const head = el('dlg-title');
  if (head) head.textContent = title;
}

export function modalOpen() {
  const d = dlg();
  if (!d) return false;
  const a = d.getAttribute ? d.getAttribute('open') : null;
  return !!d.open || (a !== null && a !== undefined);
}

/** Закрити вікно; `value` дістане той, хто чекав (`confirmAct`). */
export function closeModal(value) {
  const d = dlg();
  if (d) {
    if (typeof d.close === 'function' && d.open) {
      try { d.close(); } catch { d.removeAttribute('open'); }
    } else if (d.removeAttribute) d.removeAttribute('open');
    const box = el('dlg-body');
    if (box) box.innerHTML = '';
  }
  settle(value);
}

function settle(value) {
  const cb = ON_CLOSE;
  ON_CLOSE = null;
  if (cb) {
    try { cb(value); } catch { /* закриття не має права падати через слухача */ }
  }
}

/**
 * Підтвердження дії, що щось змінює (`mutates`).
 *
 * 🔴 Підтвердження називає наслідок, а не питає «Ви впевнені?»: людина має
 * бачити, ЩО станеться (скільки списано, що зникне з канону), інакше кнопку
 * натискають не читаючи. `rows` — пари «підпис → значення».
 *
 * Повертає Promise<boolean>: `true` — погодились, `false` — ні або закрили.
 */
export function confirmAct({ title, text = '', rows = [], okLabel, danger = false }) {
  return new Promise((resolve) => {
    const kv = rows.length ? `<dl class="kv">${rows.map(([k, v]) =>
      `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>` : '';
    openModal({
      title,
      narrow: true,
      body: `${text ? `<p>${esc(text)}</p>` : ''}${kv}
        <div class="row dlg-acts">
          <button type="button" class="${danger ? 'danger' : 'primary'}" data-act="modal.ok">${
  esc(okLabel || t('modal.ok'))}</button>
          <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button>
        </div>`,
      onClose: (v) => resolve(v === true),
    });
  });
}
