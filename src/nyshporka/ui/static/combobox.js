// Нишпорка — комбобокс: <input> + власний випадний список підказок.
//
// Чому не нативний <datalist>: він не стилізується жодним CSS (малювався
// системною СВІТЛОЮ палітрою поверх темної консолі), не підсвічує збіг, не
// показує знаменника «скільки ще знайшлось» і німо обрізає довгі списки.
//
// 🔴 Віджет НАДБУДОВУЄТЬСЯ над існуючим <input>, а не замінює його. Наслідок,
// заради якого це й зроблено: код, що читає `getElementById(id).value`
// (fonds-tab.js збирає query саме так), лишається чинним без правок, а вибір
// опції диспатчить СПРАВЖНІЙ `input`-івент — тож інлайнові `oninput="…"`
// у розмітці спрацьовують самі, без жодного колбека.

const LIMIT   = 60;    // скільки рядків малюємо (решта — рядком «знайдено N…»)
const SCANCAP = 4000;  // скільки елементів переглядаємо, поки не набрали LIMIT
const MAXH    = 320;   // стеля висоти попапа, px

let _uid = 0;

// Згортання для порівняння: регістр + різні апострофи. Дореформені ѣ/ъ/і до
// сучасних НЕ зводимо — у прізвищах це різні написання, а не варіанти.
const fold = (s) => String(s ?? '').toLocaleLowerCase('uk').replace(/[’'ʼ`]/g, "'");

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/**
 * Начепити комбобокс на існуючий <input>.
 * @param {HTMLInputElement} input
 * @param {{items?: string[], limit?: number, openOnFocus?: boolean,
 *          commitOnTab?: boolean, empty?: string,
 *          onPick?: (v: string) => void}} [opts]
 * @returns {{setItems(a: string[]): void, open(): void, close(): void, destroy(): void}}
 */
export function attachCombobox(input, opts = {}) {
  const noop = { setItems() {}, open() {}, close() {}, destroy() {} };
  if (!input) return noop;
  if (input._cb) { if (opts.items) input._cb.setItems(opts.items); return input._cb; }

  const id      = 'cb-' + (++_uid);
  const limit   = opts.limit ?? LIMIT;
  const onFocus = opts.openOnFocus !== false;
  const onTab   = opts.commitOnTab === true;
  const emptyTx = opts.empty ?? 'нічого не знайшлось';

  let raw = [], low = [];   // елементи та їхня згорнута копія (згортаємо РАЗ)
  let rows = [];            // видимі індекси в raw
  let active = -1, open = false, rafId = 0;

  // Попап живе в <body>, а не поруч із полем: поле сидить у `.lib-tools`
  // всередині `main{overflow:auto}`, і абсолютний попап різався б будь-яким
  // overflow:hidden предком та розсовував розкладку тулбара.
  const pop = document.createElement('div');
  pop.className = 'cb-pop';
  pop.id = id;
  pop.setAttribute('role', 'listbox');
  pop.hidden = true;
  document.body.appendChild(pop);

  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-controls', id);
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('autocomplete', 'off');
  input.removeAttribute('list');   // щоб поруч не лишився нативний попап

  // Два проходи: спершу префікси (рід шукають саме з початку слова), потім
  // решта підрядків. Обидва обриваються на SCANCAP — кілька тисяч рядків
  // перебираються за ~1 мс, але на КОЖНЕ натискання клавіші це вже зайве.
  function filter(q) {
    if (!q) return { hit: raw.map((_, i) => i).slice(0, limit), total: raw.length };
    const f = fold(q);
    const pre = [], sub = [];
    for (let i = 0; i < low.length && i < SCANCAP; i++) {
      const at = low[i].indexOf(f);
      if (at === 0) pre.push(i);
      else if (at > 0) sub.push(i);
      if (pre.length >= limit) break;
    }
    const all = pre.concat(sub);
    return { hit: all.slice(0, limit), total: all.length };
  }

  function mark(s, q) {
    if (!q) return esc(s);
    const at = fold(s).indexOf(fold(q));
    if (at < 0) return esc(s);
    return esc(s.slice(0, at)) + '<mark>' + esc(s.slice(at, at + q.length))
      + '</mark>' + esc(s.slice(at + q.length));
  }

  function render() {
    const q = input.value.trim();
    const { hit, total } = filter(q);
    rows = hit;
    active = hit.length ? 0 : -1;
    pop.innerHTML = hit.length
      ? hit.map((ri, k) =>
          `<div class="cb-opt${k === 0 ? ' on' : ''}" role="option" id="${id}-o${k}"`
          + ` aria-selected="${k === 0}" data-k="${k}">${mark(raw[ri], q)}</div>`).join('')
        + (total > hit.length
            ? `<div class="cb-more" aria-live="polite">знайдено ${total} — показано `
              + `${hit.length}, уточніть запит</div>` : '')
      : `<div class="cb-empty">${esc(emptyTx)}</div>`;
    syncActive();
  }

  function syncActive() {
    for (const el of pop.querySelectorAll('.cb-opt')) {
      const on = Number(el.dataset.k) === active;
      el.classList.toggle('on', on);
      el.setAttribute('aria-selected', String(on));
    }
    if (active >= 0) {
      input.setAttribute('aria-activedescendant', `${id}-o${active}`);
      const el = pop.querySelector(`#${id}-o${active}`);
      if (el) el.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  }

  // position:fixed → координати від viewport. Плата: попап не їде за скролом
  // сам, тому ловимо scroll у ФАЗІ ЗАХОПЛЕННЯ (сплива він лише з document) і
  // перераховуємо; поле пішло за край екрана — закриваємось.
  function place() {
    const r = input.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { hide(); return; }
    pop.style.left = Math.max(4, Math.min(r.left, window.innerWidth - r.width - 4)) + 'px';
    pop.style.minWidth = r.width + 'px';
    pop.style.maxWidth = Math.max(r.width, 320) + 'px';
    const below = window.innerHeight - r.bottom, above = r.top;
    if (below < 160 && above > below) {          // місця під полем немає — вгору
      pop.style.top = 'auto';
      pop.style.bottom = (window.innerHeight - r.top + 4) + 'px';
      pop.style.maxHeight = Math.min(MAXH, above - 10) + 'px';
    } else {
      pop.style.bottom = 'auto';
      pop.style.top = (r.bottom + 4) + 'px';
      pop.style.maxHeight = Math.min(MAXH, below - 10) + 'px';
    }
  }
  const reflow = () => {
    if (rafId) return;
    rafId = requestAnimationFrame(() => { rafId = 0; if (open) place(); });
  };

  function show() {
    if (input.disabled || !raw.length) return;
    render();
    pop.hidden = false; open = true;
    input.setAttribute('aria-expanded', 'true');
    place();
    window.addEventListener('scroll', reflow, true);
    window.addEventListener('resize', reflow);
  }
  function hide() {
    if (!open) return;
    pop.hidden = true; open = false; active = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    window.removeEventListener('scroll', reflow, true);
    window.removeEventListener('resize', reflow);
  }

  // 🔴 Прапорець на час ВЛАСНОГО input-івента. Без нього вибір опції відкриває
  // попап назад: pick() ховає його, тут же диспатчить `input`, а обробник
  // `onInput` бачить закритий попап і показує його знову — тобто список ніколи
  // не закривається кліком.
  let firingOwn = false;

  function pick(k) {
    const ri = rows[k];
    if (ri == null) return;
    const v = raw[ri];
    input.value = v;
    hide();
    firingOwn = true;
    try {
      // справжній івент → інлайновий oninput="…" у розмітці спрацює сам
      input.dispatchEvent(new Event('input',  { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } finally { firingOwn = false; }
    if (opts.onPick) opts.onPick(v);
  }

  const onInput   = () => { if (firingOwn) return; if (open) render(); else show(); };
  const onFocusIn = () => { if (onFocus) show(); };

  const onKey = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { show(); return; }
      if (!rows.length) return;
      active = e.key === 'ArrowDown'
        ? (active + 1) % rows.length
        : (active - 1 + rows.length) % rows.length;
      syncActive(); return;
    }
    if (!open) return;
    if (e.key === 'Home')      { e.preventDefault(); active = 0; syncActive(); }
    else if (e.key === 'End')  { e.preventDefault(); active = rows.length - 1; syncActive(); }
    else if (e.key === 'Enter') {
      if (active >= 0) { e.preventDefault(); e.stopPropagation(); pick(active); }
      else hide();
    } else if (e.key === 'Escape') {
      // 🔴 stopPropagation обов'язковий: keys.js слухає keydown на document і
      // БЕЗУМОВНО закриває всі модалки консолі. Без цього рядка закриття
      // підказок заодно закривало б відкриту модалку.
      e.preventDefault(); e.stopPropagation(); hide();
    } else if (e.key === 'Tab') {
      if (onTab && active >= 0) pick(active); else hide();
    }
  };

  // mousedown, а не click: інакше інпут блюриться раніше, ніж клік дійде
  const onPopDown = (e) => {
    const el = e.target.closest('.cb-opt');
    if (!el) return;
    e.preventDefault();
    pick(Number(el.dataset.k));
  };
  const onDocDown = (e) => {
    if (!open) return;
    if (e.target === input || pop.contains(e.target)) return;
    hide();
  };

  input.addEventListener('input', onInput);
  input.addEventListener('focus', onFocusIn);
  input.addEventListener('keydown', onKey);
  pop.addEventListener('mousedown', onPopDown);
  document.addEventListener('pointerdown', onDocDown, true);

  const api = {
    setItems(a) {
      raw = Array.isArray(a) ? a : [];
      low = raw.map(fold);
      if (open) render();
    },
    open: show,
    close: hide,
    destroy() {
      hide();
      input.removeEventListener('input', onInput);
      input.removeEventListener('focus', onFocusIn);
      input.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDocDown, true);
      pop.remove();
      delete input._cb;
    },
  };
  api.setItems(opts.items || []);
  input._cb = api;
  return api;
}
