/**
 * 📋 Перелік із пошуком, плитками-фільтрами, групами й позначенням — один на
 * всі довгі переліки консолі.
 *
 * 🔴 Чому спільний. «Віддати» показувало 659 справ одним полотном, а 589
 * галочок стояли самі; канон і гіпотези — те саме без груп і фільтрів
 * (дослідник, 23.10.2026: «з пагінацією, фільтрами й групуванням проблема
 * всюди»). Латка на кожному екрані дала б шість різних способів зробити одне.
 *
 * Клієнтський: дані вже в браузері. Переліки на десятки тисяч рядків, які
 * сервер віддає сторінками (Бібліотека, Прогони), лишаються на `ui/pager.js`.
 *
 * Що вміє:
 * - пошук по тексту рядка (`cfg.text`);
 * - плитки-фільтри з числами (`cfg.chips`) — число рахується після пошуку й
 *   перемикачів, тож плитка каже, скільки буде, якщо її натиснути;
 * - перемикачі (`cfg.toggles`), напр. «лише те, чого ще немає в пулі»;
 * - групи (`cfg.group`): згорнуті, у заголовку — підсумок групи й галочка
 *   «позначити групу» (лише рядки, які `cfg.groupPick` дозволяє);
 * - показ частинами: `cfg.pageSize` рядків у групі, далі «ще N»;
 * - позначення й липка смуга дії внизу (`cfg.actions`).
 *
 * 🔴 Нічого не позначається саме. Пачку на сотні справ людина збирає сама —
 * групою чи плиткою, але свідомо.
 */
import { t } from './strings.js';
import { esc, el } from './view.js';
import { ACTIONS } from './registry.js';

/** Стан кожного переліку за його `id`: що набрано, що відкрито, що позначено. */
const LV = new Map();

/**
 * Намалювати перелік у `box` і повернути керування ним.
 *
 * @param {HTMLElement} box
 * @param {object} cfg  id, rows, key(r), text(r), chips[{id,label,test,tone}],
 *   toggles[{id,label,test}], group(r)→{id,label}, groupSummary(rows)→html,
 *   head (html <tr>), cells(r)→html (<td>…), pageSize, select, canPick(r),
 *   groupPick(r), actions(sel)→html, selSummary(sel)→text, placeholder, empty
 */
export function listView(box, cfg) {
  if (!box) return null;
  const prev = LV.get(cfg.id);
  const st = {
    cfg, box,
    q: prev ? prev.q : '',
    chip: prev ? prev.chip : (cfg.chip || 'all'),
    toggles: prev ? prev.toggles : new Set(),
    open: prev ? prev.open : new Set(),
    shown: new Map(),
    // Позначене переживає оновлення переліку, але лише для рядків, що лишились.
    sel: new Set(),
  };
  const keys = new Set(cfg.rows.map(cfg.key));
  if (prev) prev.sel.forEach((k) => { if (keys.has(k)) st.sel.add(k); });
  LV.set(cfg.id, st);
  box.dataset.lv = cfg.id;
  box.classList.add('lv');
  const toggles = (cfg.toggles || []).map((x) => `<label class="chk lv-tg"><input type="checkbox"
      data-act="lv.toggle" data-lv="${esc(cfg.id)}" data-arg="${esc(x.id)}"${st.toggles.has(x.id) ? ' checked' : ''}> ${esc(x.label)}</label>`).join('');
  const id = esc(cfg.id);
  box.innerHTML = `<div class="lv-chips" id="${id}-chips"></div>
    <div class="lv-tools"><input type="search" class="lv-q" data-act="lv.q" data-live="1" data-lv="${id}"
      value="${esc(st.q)}" placeholder="${esc(cfg.placeholder || t('lv.q.ph'))}" aria-label="${esc(cfg.placeholder || t('lv.q.ph'))}">${toggles}</div>
    <div class="lv-body" id="${id}-body"></div>${cfg.select ? `<div class="lv-bar" id="${id}-bar"></div>` : ''}`;
  paint(st);
  return {
    selected: () => selectedRows(st),
    clear: () => { st.sel.clear(); paint(st); },
    setBusy: (on) => box.classList.toggle('lv-busy', !!on),
    repaint: () => paint(st),
  };
}

/** Рядки після пошуку й перемикачів (без плитки) — з них рахуються плитки. */
function baseRows(st) {
  const q = st.q.trim().toLocaleLowerCase('uk');
  const tg = (st.cfg.toggles || []).filter((x) => st.toggles.has(x.id));
  return st.cfg.rows.filter((r) => (!q || String(st.cfg.text(r) || '').toLocaleLowerCase('uk').includes(q))
    && tg.every((x) => x.test(r)));
}

function visibleRows(st) {
  const chip = (st.cfg.chips || []).find((c) => c.id === st.chip);
  const base = baseRows(st);
  return chip ? base.filter(chip.test) : base;
}

function selectedRows(st) {
  return st.cfg.rows.filter((r) => st.sel.has(st.cfg.key(r)));
}

function groupsOf(st, rows) {
  const g = st.cfg.group;
  if (!g) return [{ id: '', label: '', rows }];
  const by = new Map();
  for (const r of rows) {
    const { id, label } = g(r);
    if (!by.has(id)) by.set(id, { id, label, rows: [] });
    by.get(id).rows.push(r);
  }
  // Більші групи вище: там, де справ найбільше, людина й починає.
  return [...by.values()].sort((a, b) => b.rows.length - a.rows.length || String(a.label).localeCompare(String(b.label), 'uk'));
}

function paint(st) {
  const { cfg, box } = st;
  const base = baseRows(st);
  const lv = esc(cfg.id);
  const chips = el(`${cfg.id}-chips`);
  if (chips) {
    const allCls = st.chip === 'all' ? 'lv-chip on' : 'lv-chip';
    const all = `<button type="button" class="${allCls}" data-act="lv.chip" data-lv="${lv}" data-arg="all"
      aria-pressed="${st.chip === 'all'}"><b class="num">${base.length}</b><span>${esc(t('lv.all'))}</span></button>`;
    chips.innerHTML = cfg.chips && cfg.chips.length ? all + cfg.chips.map((c) => {
      const n = base.filter(c.test).length;
      const cls = ['lv-chip', st.chip === c.id ? 'on' : '', c.tone ? `lv-${c.tone}` : ''].filter(Boolean).join(' ');
      return `<button type="button" class="${cls}"
        data-act="lv.chip" data-lv="${lv}" data-arg="${esc(c.id)}" aria-pressed="${st.chip === c.id}"${n ? '' : ' disabled'}>
        <b class="num">${n}</b><span>${esc(c.label)}</span></button>`;
    }).join('') : '';
  }
  const rows = visibleRows(st);
  const groups = groupsOf(st, rows);
  // Групу видно розгорнутою, коли їх мало або людина щось шукає: тоді згорнуте
  // ховало б саме те, що вона щойно знайшла.
  const autoOpen = groups.length <= 2 || !!st.q.trim();
  const size = cfg.pageSize || 50;
  const body = el(`${cfg.id}-body`);
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<p class="muted lv-none">${esc(cfg.rows.length ? t('lv.none') : (cfg.empty || t('lv.none')))}</p>`;
  } else {
    body.innerHTML = groups.map((g) => {
      const open = autoOpen || st.open.has(g.id) || !cfg.group;
      const shown = st.shown.get(g.id) || size;
      const pickable = g.rows.filter(cfg.groupPick || cfg.canPick || (() => true));
      const nSel = pickable.filter((r) => st.sel.has(cfg.key(r))).length;
      const head = cfg.group ? `<header class="lv-gh">
          <button type="button" class="lv-fold" data-act="lv.fold" data-lv="${lv}" data-arg="${esc(g.id)}" aria-expanded="${open}"
            aria-label="${esc(g.label)}"><span class="chev-s"></span></button>
          ${cfg.select && pickable.length ? `<input type="checkbox" class="lv-gck" data-act="lv.pickg" data-lv="${lv}" data-arg="${esc(g.id)}"
            title="${esc(t('lv.group.pick'))}" aria-label="${esc(t('lv.group.pick'))}: ${esc(g.label)}"${nSel && nSel === pickable.length ? ' checked' : ''}
            data-part="${nSel && nSel < pickable.length ? '1' : ''}">` : ''}
          <b class="lv-gl">${esc(g.label)}</b>
          <span class="muted lv-gs">${cfg.groupSummary ? cfg.groupSummary(g.rows) : esc(String(g.rows.length))}</span>
        </header>` : '';
      if (!open) return `<section class="lv-g" data-g="${esc(g.id)}">${head}</section>`;
      const list = g.rows.slice(0, shown).map((r) => {
        const k = cfg.key(r);
        const can = !cfg.canPick || cfg.canPick(r);
        const ck = cfg.select ? `<td class="lv-ck">${can ? `<input type="checkbox" data-act="lv.pick" data-lv="${lv}" data-arg="${esc(k)}"
          aria-label="${esc(k)}"${st.sel.has(k) ? ' checked' : ''}>` : ''}</td>` : '';
        return `<tr data-k="${esc(k)}"${st.sel.has(k) ? ' class="lv-on"' : ''}>${ck}${cfg.cells(r)}</tr>`;
      }).join('');
      const more = g.rows.length > shown ? `<p class="lv-more"><button type="button" class="ghost" data-act="lv.more" data-lv="${lv}"
          data-arg="${esc(g.id)}">${esc(t('lv.more').replace('{n}', g.rows.length - shown))}</button>
          <span class="muted">${esc(t('lv.shown').replace('{a}', shown).replace('{b}', g.rows.length))}</span></p>` : '';
      return `<section class="lv-g open" data-g="${esc(g.id)}">${head}
        <table class="lv-t">${cfg.head ? `<thead>${cfg.select ? '<tr><th class="lv-ck"></th>' : '<tr>'}${cfg.head}</tr></thead>` : ''}
        <tbody>${list}</tbody></table>${more}</section>`;
    }).join('');
    // `indeterminate` — лише властивістю, атрибута в HTML немає.
    (body.querySelectorAll ? [...body.querySelectorAll('.lv-gck[data-part="1"]')] : [])
      .forEach((x) => { x.indeterminate = true; });
  }
  paintBar(st);
}

function paintBar(st) {
  const bar = el(`${st.cfg.id}-bar`);
  if (!bar) return;
  const sel = selectedRows(st);
  const sum = sel.length && st.cfg.selSummary ? ` · ${esc(st.cfg.selSummary(sel))}` : '';
  bar.innerHTML = `<span class="lv-sel">${sel.length
    ? `<b>${esc(t('lv.sel').replace('{n}', sel.length))}</b>${sum}
       <button type="button" class="ghost ctl-sm" data-act="lv.clear" data-lv="${esc(st.cfg.id)}">${esc(t('lv.clear'))}</button>`
    : `<span class="muted">${esc(st.cfg.selHint || t('lv.sel.none'))}</span>`}</span>
    <span class="lv-acts">${st.cfg.actions ? st.cfg.actions(sel) : ''}</span>`;
  if (bar.classList) bar.classList.toggle('on', sel.length > 0);
}

/** Стан переліку, якому належить елемент: `data-lv` стоїть на кожному з них. */
function stateOf(elm) {
  const id = elm && elm.dataset && elm.dataset.lv;
  return id ? LV.get(id) : null;
}

Object.assign(ACTIONS, {
  'lv.q': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    st.q = String(elm.value || '');
    st.shown.clear();
    paint(st);
  },
  'lv.chip': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    st.chip = elm.dataset.arg || 'all';
    st.shown.clear();
    paint(st);
  },
  'lv.toggle': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    if (elm.checked) st.toggles.add(elm.dataset.arg); else st.toggles.delete(elm.dataset.arg);
    paint(st);
  },
  'lv.fold': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    const id = elm.dataset.arg;
    if (st.open.has(id)) st.open.delete(id); else st.open.add(id);
    paint(st);
  },
  'lv.more': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    const id = elm.dataset.arg;
    st.shown.set(id, (st.shown.get(id) || st.cfg.pageSize || 50) + (st.cfg.pageSize || 50));
    paint(st);
  },
  'lv.pick': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    const k = elm.dataset.arg;
    if (elm.checked) st.sel.add(k); else st.sel.delete(k);
    const tr = elm.closest && elm.closest('tr');
    if (tr) tr.classList.toggle('lv-on', elm.checked);
    // Заголовок групи й смуга — без перемальовування всього: галочка, яку
    // щойно поставили, не мусить губити фокус.
    const sec = elm.closest && elm.closest('.lv-g');
    const g = sec && sec.dataset.g;
    const gck = sec && sec.querySelector('.lv-gck');
    if (gck && st.cfg.group) {
      const rows = visibleRows(st).filter((r) => st.cfg.group(r).id === g)
        .filter(st.cfg.groupPick || st.cfg.canPick || (() => true));
      const n = rows.filter((r) => st.sel.has(st.cfg.key(r))).length;
      gck.checked = !!n && n === rows.length;
      gck.indeterminate = !!n && n < rows.length;
    }
    paintBar(st);
  },
  'lv.pickg': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    const g = elm.dataset.arg;
    const rows = visibleRows(st).filter((r) => st.cfg.group(r).id === g)
      .filter(st.cfg.groupPick || st.cfg.canPick || (() => true));
    rows.forEach((r) => { if (elm.checked) st.sel.add(st.cfg.key(r)); else st.sel.delete(st.cfg.key(r)); });
    paint(st);
  },
  'lv.clear': (_ev, elm) => {
    const st = stateOf(elm);
    if (!st) return;
    st.sel.clear();
    paint(st);
  },
});
