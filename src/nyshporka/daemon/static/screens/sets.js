/**
 * 🗃 Набори — те, з чого робляться мітки для трену.
 *
 * Екран відповідає на питання «що в мене є для розмітки і в якому стані», і
 * числа тут беруться з диска: скільки кропів лежить, скільки міток у
 * `lines.jsonl`, скільки рядків зведено арбітрами. Набір, який тут не показує
 * злиття, у корпус не потрапить — хоч би скільки рядків для нього звели.
 *
 * Довгі дії (нарізка, голоси, завдання) ідуть роботами в черзі демона, і їхній
 * поступ малюється тут, поруч із формою, а не лише на екрані «Роботи».
 */
import { modelName, dayOf, pill } from '../core/bits.js';
import { listView } from '../core/listview.js';
import { skelRows } from '/ui/dom.js';
import { t, tn, LANG } from '../core/strings.js';
import { callOp, staleThenFresh } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, renderWarnings,
  curGen, alive, emptyMini, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto, onJob, jobChip, jobNotes } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';
import { cbValue } from '/ui/combobox.js';
import { loadRuns, attachRunPicker } from '../core/runpick.js';

/** Набори, як їх віддав останній `train.sets` — для селектів у формах. */
let SETS = [];
let _runCb = null;
let _env = null;

SCREENS.sets = async () => {
  const gen = curGen();
  setView(`
    <p class="muted">${t('sets.why')}</p>
    <div id="sets-recent" class="sets-recent"></div>
    <div class="sets-sortbar"><label>${t('sets.sort')}
      <select data-act="sets.sort" id="sets-sort">${SORTS.map((k) =>
    `<option value="${k}"${k === sortMode() ? ' selected' : ''}>${t(`sets.sort.${k}`)}</option>`).join('')}</select></label></div>
    <div id="sets-list"><table><tbody>${skelRows(5, 4)}</tbody></table></div>
    <div id="sets-warn"></div>
    <div class="dash-two">
      <div class="dash-box">
        <h3>${t('sets.cut.title')}</h3>
        <p class="muted">${t('sets.cut.why')}</p>
        <form data-act="sets.cut">
          <div class="row">
            ${fld(t('sets.cut.run'), `<input name="run" required>`)}
            ${fld(t('sets.cut.name'), `<input name="name" required>`)}
          </div>
          <div class="row">
            ${fld(t('sets.cut.pages'), `<input name="pages">`)}
            ${fld(t('sets.cut.pick'), `<input name="pick" type="number" min="0" value="6">`)}
          </div>
          <div class="row">
            ${fld(t('sets.cut.domain'), `<input name="domain">`)}
            <button type="submit">${t('sets.cut.go')}</button>
          </div>
          <div id="sets-cut-job"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.voices.title')}</h3>
        <p class="muted">${t('sets.voices.why')}</p>
        <form data-act="sets.voices">
          <div class="row"><select name="name" id="sets-v-name"></select></div>
          <div class="row">
            ${fld(t('sets.voices.from_run'), `<input name="from_run">`)}
            ${fld(t('sets.voices.models'), `<input name="models">`)}
            <button type="submit">${t('sets.voices.go')}</button>
          </div>
          <div id="sets-voices-job"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.gloss.title')}</h3>
        <p class="muted">${t('sets.gloss.why')}</p>
        <form data-act="sets.gloss">
          <div class="row"><select name="name" id="sets-g-name"></select></div>
          <div class="row">
            ${fld(t('sets.gloss.add'), `<input name="add" required>`)}
            ${fld(t('sets.gloss.src'), `<input name="why">`)}
            <button type="submit">${t('sets.gloss.go')}</button>
          </div>
          <div id="sets-gloss"></div>
        </form>
      </div>
      <div class="dash-box">
        <h3>${t('sets.arb.title')}</h3>
        <p class="muted">${t('sets.arb.why')}</p>
        <form data-act="sets.export">
          <div class="row">
            <select name="name" id="sets-a-name"></select>
            <button type="submit">${t('sets.export.go')}</button>
            <button type="button" data-act="sets.import">${t('sets.import.go')}</button>
          </div>
          <div id="sets-arb-job"></div>
        </form>
      </div>
    </div>`);
  await setsList();
  if (!alive(gen)) return;
  await setsRunHints();
};

/** Таблиця наборів зі знаменниками — і селекти форм із тих самих імен. */
async function setsList() {
  // Набори рахуються з тисяч кропів (~1 с): спершу минула відповідь, потім свіжа.
  await staleThenFresh('train.sets', { all: true }, (env) => paintSets(env));
}

// ── перелік наборів: спільний `listView`, а не власна таблиця ──────────────
const SORTS = ['recent', 'name', 'crops'];

/** Вибір сортування й «щойно відкритий» живуть у сесії вкладки: після переходу в
 *  «Розмітку» й назад екран збирається заново, а людина — та сама. */
function store(key, val) {
  try {
    if (val === undefined) return sessionStorage.getItem(key) || '';
    sessionStorage.setItem(key, val);
  } catch { /* приватне вікно: працюємо без пам'яті */ }
  return '';
}
function sortMode() {
  const v = store('sets.sort');
  return SORTS.includes(v) ? v : 'recent';
}
function setSortMode(v) { store('sets.sort', SORTS.includes(v) ? v : 'recent'); }
function rememberLast(name) { store('sets.last', String(name || '')); }
const lastOpened = () => store('sets.last');

/** Коли чіпали: щойно відкритий із цього екрана вважається найсвіжішим. */
const touchedOf = (s) => (s.name === lastOpened() ? Infinity : Number(s.touched || 0));

/** Стан набору словами: що з ним далі. Лише з числових полів, без вгадування. */
const stNoMerge = (s) => !s.merge;
const stAwait = (s) => !!s.merge && !s.n_marked;
const stHand = (s) => s.n_marked > 0;

/** Голоси без повторів: «Логофет v9, Логофет v8, Логофет v9» → «Логофет v9, Логофет v8». */
export function voiceNames(s) {
  return [...new Set((s.voices || []).map(modelName).filter(Boolean))];
}

/** Сімейство набору — його жанр із set.json (`domain`): це поле є в кожного набору
 *  й задано людиною. Префікс імені (`x17-`, `ro-`) — угода про назви, не дані. */
const genreOf = (s) => String(s.domain || '').trim();

const byRecent = (a, b) => touchedOf(b) - touchedOf(a) || a.name.localeCompare(b.name, 'uk');
const SORT_CMP = {
  recent: byRecent,
  name: (a, b) => a.name.localeCompare(b.name, 'uk', { numeric: true }),
  crops: (a, b) => (b.n_crops || 0) - (a.n_crops || 0) || byRecent(a, b),
};
const sum = (rows, f) => rows.reduce((n, r) => n + (f(r) || 0), 0);

/** Порядок груп під обраним сортуванням: рядки в групі вже відсортовані. */
function groupOrder(mode) {
  if (mode === 'name') return (a, b) => String(a.label).localeCompare(String(b.label), 'uk');
  if (mode === 'crops') return (a, b) => sum(b.rows, (r) => r.n_crops) - sum(a.rows, (r) => r.n_crops);
  return (a, b) => touchedOf(b.rows[0]) - touchedOf(a.rows[0]);
}

function marksCell(s) {
  if (!s.n_marked) {
    const why = stAwait(s) ? pill('warn', t('sets.st.await')) : pill('neutral', t('sets.st.nomerge'));
    return `<span class="muted">${esc(t('sets.marks.none'))}</span><br>${why}`;
  }
  const ok = (s.by_status || {}).ok || 0;
  return `<b>${esc(t('sets.marks.ok').replace('{ok}', ok).replace('{n}', s.n_marked))}</b>`;
}

function mergeCell(s) {
  if (!s.merge) return '<span class="muted">—</span>';
  const m = s.merge;
  const tot = s.n_merged || 1;
  const pc = (k) => ((m[k] || 0) * 100 / tot).toFixed(1);
  const part = (k, cls) => `<span class="${cls}">${esc(t(`sets.conf.${k}`))} <b>${m[k] || 0}</b></span>`;
  return `<span class="sets-bar" aria-hidden="true"><i class="h" style="width:${pc('high')}%"></i><i class="m" style="width:${pc('med')}%"></i><i class="l" style="width:${pc('low')}%"></i></span>
    <div class="sets-conf">${part('high', 'ch')} ${part('med', 'cm')} ${part('low', 'cl')}</div>
    <small class="muted">${esc(t('sets.merge.total').replace('{n}', s.n_merged))}</small>`;
}

function nameCell(s) {
  // Без назви — запасний підпис із set.json: справа й жанр, а не порожній рядок.
  const sub = s.title || [s.case, s.domain].filter(Boolean).join(' · ');
  const tags = [s.hidden ? pill('neutral', t('sets.hidden')) : '',
    s.name === lastOpened() ? pill('info', t('sets.last')) : ''].filter(Boolean).join(' ');
  return `<b>${esc(s.name)}</b> ${tags}${sub ? `<div class="muted${s.title ? '' : ' sets-fallback'}">${esc(sub)}</div>` : ''}`;
}

function cropsCell(s) {
  if (!s.crops_present) return `<span class="warn-inline">${t('sets.nocrops')}</span>`;
  return `<b>${s.n_crops}</b> <span class="muted">/ ${s.n_pages} ${t('common.pages')}</span>`;
}

function paintRecent(rows) {
  const box = el('sets-recent');
  if (!box) return;
  const top = rows.filter((s) => touchedOf(s) > 0).sort(byRecent).slice(0, 3);
  box.innerHTML = top.length
    ? `<span class="muted">${esc(t('sets.sort.recent'))}:</span> ${top.map((s) => `<button type="button" class="ghost ctl-sm"
        data-act="sets.open" data-arg="${esc(s.name)}" title="${esc(dayOf(s.touched, LANG))}">${esc(s.name)}</button>`).join(' ')}`
    : '';
}

function paintSets(env) {
  const box = el('sets-list');
  if (!box) return undefined;
  if (!env.ok) return boxError('sets-list', env);
  _env = env;
  SETS = env.data.sets || [];
  const opts = SETS.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
  for (const id of ['sets-v-name', 'sets-g-name', 'sets-a-name']) {
    const sel = el(id);
    if (!sel) continue;
    const was = sel.value;           // вибір у формі не губиться при оновленні
    sel.innerHTML = opts;
    if (was && SETS.some((x) => x.name === was)) sel.value = was;
  }
  const warn = el('sets-warn');
  if (warn) warn.innerHTML = renderWarnings(env);
  if (!SETS.length) {
    box.innerHTML = emptyMini('kolba', t('sets.none'));
    return undefined;
  }
  const mode = sortMode();
  const rows = [...SETS].sort(SORT_CMP[mode]);
  paintRecent(rows);
  listView(box, {
    id: 'sets',
    rows,
    key: (s) => s.name,
    text: (s) => [s.name, s.title, s.case, s.domain, s.source_run, ...(s.voices || []), ...voiceNames(s)].join(' '),
    placeholder: t('sets.search.ph'),
    pageSize: 30,
    chips: [
      { id: 'train', label: t('sets.role.train'), test: (s) => s.role !== 'holdout' },
      { id: 'holdout', label: t('sets.role.holdout'), test: (s) => s.role === 'holdout' },
      { id: 'nomerge', label: t('sets.f.nomerge'), test: stNoMerge },
      { id: 'await', label: t('sets.f.await'), test: stAwait, tone: 'warn' },
      { id: 'hand', label: t('sets.f.hand'), test: stHand, tone: 'ok' },
      ...['cyrillic', 'latin', 'mixed'].map((k) => ({ id: `sc-${k}`, label: t(`sets.script.${k}`),
        test: (s) => s.script === k })),
      { id: 'hidden', label: t('sets.f.hidden'), test: (s) => !!s.hidden },
    ],
    group: (s) => {
      const g = genreOf(s);
      return { id: `g:${g}`, label: g || t('sets.nogenre') };
    },
    groupSort: groupOrder(mode),
    groupSummary: (g) => esc(t('sets.gsum')
      .replace('{sets}', tn('lv.n.sets', g.length))
      .replace('{crops}', tn('lv.n.crops', sum(g, (r) => r.n_crops)))
      .replace('{ok}', sum(g, (r) => (r.by_status || {}).ok))
      .replace('{merged}', sum(g, (r) => r.n_merged))),
    head: `<th>${t('sets.h.name')}</th><th>${t('sets.col.role')}</th><th>${t('sets.h.crops')}</th>
      <th>${t('sets.h.marks')}</th><th>${t('sets.h.merge')}</th><th>${t('sets.h.voices')}</th>
      <th>${t('sets.h.when')}</th><th></th>`,
    cells: (s) => `<td>${nameCell(s)}</td>
      <td class="lv-nw">${s.role === 'holdout' ? ic('target', 'ic-sm') + ' ' + t('sets.role.holdout') : t('sets.role.train')}</td>
      <td class="num">${cropsCell(s)}</td>
      <td>${marksCell(s)}</td>
      <td>${mergeCell(s)}</td>
      <td>${esc(voiceNames(s).join(', ') || '—')}</td>
      <td class="lv-nw">${esc(s.touched ? dayOf(s.touched, LANG) : '—')}</td>
      <td class="lv-nw sets-acts">${s.merge ? `<button data-act="sets.open" data-arg="${esc(s.name)}" data-scen="merge">${t('sets.open.merge')}</button>` : ''}
        <button data-act="sets.open" data-arg="${esc(s.name)}" data-scen="new">${t('sets.open.new')}</button></td>`,
  });
  return undefined;
}

/** Підказка прогонів у полі нарізки: імена довгі й схожі, набирати їх руками — описка. */
async function setsRunHints() {
  if (_runCb) { _runCb.destroy(); _runCb = null; }
  const input = el('view').querySelector('input[name="run"]');
  if (!input) return;
  // Пошуком на сервері, порцією, а не всі прогони (`core/runpick.js`).
  const runs = await loadRuns('');
  if (runs === null || !document.contains(input)) return;
  _runCb = attachRunPicker(input, runs);
}

/**
 * Довга робота — поруч із формою. Після завершення перелік наборів
 * перечитується: кропів чи голосів побільшало, і таблиця мусить це показати.
 */
function watchHere(box, jobId) {
  if (!box) return;
  box.innerHTML = jobChip({ state: 'queued', progress: {} });
  onJob(jobId, async (j) => {
    if (!document.contains(box)) return;
    box.innerHTML = jobChip(j) + (j.state === 'done' || j.state === 'error' ? jobNotes(j) : '');
    if (j.state === 'done') await setsList();
  });
}

Object.assign(ACTIONS, {
  'sets.cut': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    // У полі видно шифру й модель; у дію — ім'я прогону (`cbValue`).
    const runIn = ev.target.querySelector ? ev.target.querySelector('input[name="run"]') : null;
    if (runIn) fd.run = cbValue(runIn) || fd.run;
    const free = busyForm(ev.target);
    const env = await callOp('train.cut', { run: fd.run, name: fd.name, pages: fd.pages,
      pick: Number(fd.pick || 0), domain: fd.domain });
    free();
    if (!env.ok) return boxError('sets-cut-job', env);
    watchHere(el('sets-cut-job'), (env.data || {}).job_id);
    return undefined;
  },

  'sets.voices': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const free = busyForm(ev.target);
    const env = await callOp('train.voices', { name: fd.name, from_run: fd.from_run,
      models: fd.models });
    free();
    if (!env.ok) return boxError('sets-voices-job', env);
    watchHere(el('sets-voices-job'), (env.data || {}).job_id);
    return undefined;
  },

  'sets.gloss': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('train.glossary', { name: fd.name, add: fd.add, why: fd.why });
    const box = el('sets-gloss');
    if (!env.ok) return boxError('sets-gloss', env);
    const items = Object.entries(env.data.glossary || {});
    box.innerHTML = (items.length
      ? `<p>${items.map(([k, v]) => `<b>${esc(k)}</b>${v ? ` <span class="muted">${esc(v)}</span>` : ''}`).join(' · ')}</p>`
      : `<p class="muted">${t('sets.gloss.empty')}</p>`) + renderWarnings(env);
    const add = ev.target.elements.add;
    if (add) add.value = '';
    return undefined;
  },

  'sets.export': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const free = busyForm(ev.target);
    const env = await callOp('train.export', { name: fd.name });
    free();
    if (!env.ok) return boxError('sets-arb-job', env);
    watchHere(el('sets-arb-job'), (env.data || {}).job_id);
    return undefined;
  },

  /** Імпорт — коротка дія: відповідь приходить одразу, з воротами в `warnings`. */
  'sets.import': async (_ev, elm) => {
    const form = elm.closest('form');
    const name = form ? form.elements.name.value : '';
    const box = el('sets-arb-job');
    box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('train.import', { name });
    if (!env.ok) return boxError('sets-arb-job', env);
    const c = env.data.conf || {};
    box.innerHTML = `<p>${t('sets.import.done')}: <b>${env.data.rows}</b>
      <span class="muted">(high ${c.high || 0} · med ${c.med || 0} · low ${c.low || 0})</span></p>`
      + renderWarnings(env);
    await setsList();
    return undefined;
  },

  'sets.open': (_ev, elm) => {
    rememberLast(elm.dataset.arg);
    return goto('label', { set: elm.dataset.arg, scen: elm.dataset.scen || 'new' });
  },

  'sets.sort': (_ev, elm) => {
    setSortMode(elm.value);
    if (_env) paintSets(_env);
  },
});

/** Тримаємо `ST` в імпортах: посів екрана читає `goto`, а не цей модуль. */
void ST;
