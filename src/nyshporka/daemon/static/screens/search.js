/** 🔎 Пошук у прочитаному. */

import { t } from '../core/strings.js';
import { callOp, SEQ, FINAL_STATES } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, fld,
  renderWarnings, maskot } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show, onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { attachCombobox } from '/ui/combobox.js';

/**
 * 🔎 Пошук — ТА САМА команда, що в агента (`text.find`), але з поправкою на
 * людину.
 *
 * 🔴 Доти консоль шукала «чимось своїм» (дослідник 07.10.2026): тим самим
 * двигуном, але без каналів роду, без журналу знаменника, без самоперевірки
 * й з іншим порогом. Агент на той самий запит діставав повнішу відповідь,
 * ніж людина. Тепер обидва питають `text.find`, а консоль шле її роботою в
 * черзі (`search.find`) — з поступом і «Спинити».
 *
 * 🔴 Параметри команди людина не набирає. Рід береться з профілю сам; канали
 * (якорі імен, запис) вмикаються самі, коли межа — справа, а запит — рід;
 * поріг схований під «Точніше». Набирати лишається два поля, і обидва з
 * підказками: «Що» — написання роду й недавні запити, «Де» — лише фонди,
 * описи й справи, у яких є прочитане.
 *
 * Шукане — не лише прізвище: назва села в книзі чи фонді шукається тим
 * самим полем, лише без каналів роду (вони про людей).
 */

/** Підпис підказки «Де» → значення межі для `text.find`. */
const SCOPE_VALUE = new Map();
/** Недавні запити — зручність одного браузера, тож `localStorage`. */
const RECENT_KEY = 'nysh.search.recent';
/** Поріг за замовчуванням — той самий, що в `text.find`. */
const THRESH = 78;

function recent() {
  try {
    const got = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    return Array.isArray(got) ? got.filter((x) => typeof x === 'string') : [];
  } catch { return []; }
}

function remember(q) {
  try {
    localStorage.setItem(RECENT_KEY,
      JSON.stringify([q, ...recent().filter((x) => x !== q)].slice(0, 12)));
  } catch { /* приватне вікно — без недавніх, і це не поламка */ }
}

/** Набране в «Де» → межа: підпис підказки, «уся бібліотека» або вільний текст. */
function scopeValue(raw) {
  const v = String(raw || '').trim();
  if (!v || v === t('search.scope.all')) return '';
  return SCOPE_VALUE.has(v) ? SCOPE_VALUE.get(v) : v;
}

SCREENS.search = async () => {
  // Справа з бібліотеки («Шукати рід»): межа вже названа.
  const only = (ST.search || {}).case || '';
  // Прийшли з «Робіт» по завершений пошук — показати саме його.
  const fromJob = (ST.search || {}).job || '';
  ST.search = null;
  setView(`
    <h2>${t('nav.search')}</h2>
    <p class="muted">${t('search.why')}</p>
    <form data-act="search.run" id="search-form">
      <div class="row">
        ${fld(t('search.what'), `<input name="q" placeholder="${t('search.q')}"
          autocomplete="off" autofocus>`)}
        ${fld(t('search.scope'), `<input name="case" placeholder="${t('search.scope.all')}"
          value="${esc(only)}" autocomplete="off">`)}
        ${fld(t('search.in'), `<select name="where">
          <option value="decode">${t('search.where.decode')}</option>
          <option value="pages">${t('search.where.pages')}</option>
          <option value="records">${t('search.where.records')}</option>
        </select>`)}
      </div>
      <div class="row">
        <button type="submit">${t('search.run')}</button>
        <details class="more-filters"><summary>${t('search.more')}</summary>
          <label class="lbl-mini">${t('search.thresh')}
            <input name="thresh" type="number" min="50" max="100" value="${THRESH}" size="4"></label>
          <span class="muted">${t('search.thresh.why')}</span>
        </details>
      </div>
    </form>
    <div id="prof-hint"></div>
    <div id="hits"><div class="search-idle">${maskot('lupa', 130)}</div></div>
    <div id="search-index"></div>`);
  scopeHints();
  // Спершу — свій пошук, що йде чи щойно скінчився: його запит у полі важливіший
  // за прізвище з профілю, яке підставляє `profileHint` у порожнє поле.
  if (fromJob) await ACTIONS['search.last'](null, { dataset: { job: fromJob } });
  else if (!only) await resumeSweep();
  await profileHint();
  if (!only) await searchIndexState();
};

/**
 * Підказки «Де»: фонди, описи й справи, у яких є прочитане.
 *
 * ⚠ Дошук на сервері, а не перша сотня в пам'яті: справ тисячі, і фіксована
 * пачка мовчки ховала б ту, яку людина набирає.
 */
function scopeHints() {
  const input = el('view').querySelector('input[name="case"]');
  if (!input || !input.addEventListener) return;
  const load = async (q) => {
    // Обраний пункт чи «уся бібліотека» — не запит: показати знову все.
    const want = (!q || q === t('search.scope.all') || SCOPE_VALUE.has(q)) ? '' : q;
    const env = await callOp('search.scopes', { q: want, limit: 40 });
    const items = (env.ok && (env.data || {}).items) || [];
    const labels = [t('search.scope.all')];
    for (const x of items) {
      const label = `${x.label}${x.kind === 'case' ? '' : ` · ${x.cases} ${t('search.scope.cases')}`}`;
      SCOPE_VALUE.set(label, x.value);
      labels.push(label);
    }
    return labels;
  };
  let box = null;
  let timer = null;
  load('').then((items) => { box = attachCombobox(input, { items, free: true }); });
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const items = await load(input.value || '');
      if (box && box.setItems) box.setItems(items);
    }, 250);
  });
}

/**
 * Написання з профілю — підказками поля «Що» і рядком під ним.
 *
 * 🔴 Це та ланка, заради якої профіль узагалі просять заповнити: людина не
 * мусить пригадувати написання сама — саме там, де рушій калічить середину
 * слова й де пригадати їх найважче.
 *
 * ⚠ Поле лише ЗАПОВНЮЄТЬСЯ, а не замикається на профілі. Шукають і сусідів, і
 * села, і геть чуже прізвище.
 */
async function profileHint() {
  const box = el('prof-hint');
  if (!box) return;
  const env = await callOp('profile.show', {});
  if (!env.ok) return;
  const d = env.data || {};
  const input = el('view').querySelector('input[name="q"]');
  const sp = d.present ? (d.spellings || []) : [];
  if (input && input.addEventListener) {
    const items = [...new Set([...recent(), d.display || '', ...sp].filter(Boolean))];
    if (items.length) attachCombobox(input, { items, free: true });
  }
  if (!d.present) {
    box.innerHTML = `<p class="muted">${t('search.noprofile')}
      <button class="ctl-sm" data-act="nav" data-arg="profile">${
      t('step.go')}</button></p>`;
    return;
  }
  if (input && !input.value) input.value = d.display || '';
  if (!sp.length) return;
  // Згорнуто: стіна з десятків написань стояла між полем запиту й видачею.
  box.innerHTML = `<details class="notes"><summary>${t('search.forms')} (${sp.length})</summary>
    <div class="prof-forms">${sp.map((x) =>
      `<button class="chip" data-act="search.form" data-arg="${esc(x)}"
        >${esc(x)}</button>`).join('')}</div></details>`;
}

/**
 * Стан індексу прочитаного — ДО пошуку, а не після.
 *
 * 🔴 Це знаменник цього екрана: пошук чеше лише зібране, і «не знайшлось»
 * означає різне при повному й частковому індексі.
 */
async function searchIndexState() {
  const box = el('search-index');
  if (!box) return;
  const env = await callOp('search.state', {});
  if (!env.ok) return;
  const d = env.data || {};
  if (!d.runs) return;                       // читати ще нема чого
  const mb = (d.bytes || 0) / (1024 * 1024);
  box.innerHTML = d.stale
    ? `<div class="warn">${esc(t('search.index.partial')
        .replace('{n}', d.stale).replace('{all}', d.runs))}
       <button data-act="search.index">${t('search.index.go')}</button></div>`
    : `<p class="muted">${esc(t('search.index.ready')
        .replace('{all}', d.runs).replace('{mb}', mb.toFixed(0)))}</p>`;
}

/** Пошуки цього екрана: нова команда й ще не забрані старі. */
const SEARCH_JOBS = ['search.find', 'search.sweep'];

/** Останній пошук по прочитаному за півдоби — або нічого. */
async function lastSweep() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return null;
    const now = Date.now() / 1000;
    return ((await res.json()).jobs || [])
      .filter((j) => SEARCH_JOBS.includes(j.kind) && now - (j.updated || 0) < 43200)
      .sort((a, b) => (b.updated || 0) - (a.updated || 0))[0] || null;
  } catch { return null; }
}

const hhmmOf = (sec) => (sec ? new Date(sec * 1000).toTimeString().slice(0, 5) : '');

function setField(name, value) {
  const input = el('view') && el('view').querySelector(`[name="${name}"]`);
  if (input) input.value = value ?? '';
}

/**
 * 🔁 Повернувся на «Пошук» — бачиш свій пошук: той, що йде, — з поступом,
 * завершений за півдоби — кнопкою «Показати».
 */
async function resumeSweep() {
  const job = await lastSweep();
  if (!job) return;
  const cfg = job.cfg || {};
  setField('q', cfg.q || '');
  if (cfg.case) setField('case', cfg.case);
  if (!FINAL_STATES.includes(job.state)) {
    const env = await pollSweep(job.id);
    if (env) showFound(env, cfg.q || '', job.kind);
    return;
  }
  const box = el('hits');
  if (!box || !job.result) return;
  const n = (job.result.hits || []).length;
  box.innerHTML = `<p class="muted">${esc(t('search.last')
    .replace('{q}', cfg.q || '').replace('{t}', hhmmOf(job.updated)).replace('{n}', n))}
    <button class="ctl-sm" data-act="search.last" data-job="${esc(job.id)}">${
  t('search.last.show')}</button></p>`;
}

/** Відповідь роботи — тим шляхом, яким її малює її команда. */
function showFound(env, q, kind) {
  if (!env.ok) return boxError('hits', env);
  return kind === 'search.sweep' ? renderHits(env, q, 'decode') : renderFind(env, q);
}

/**
 * Чекати пошук, показуючи, ЩО саме він робить, — і з «Спинити».
 *
 * 🔴 Спинений пошук теж має відповідь: прочесане до зупинки з тривогою
 * «прочесано не все». Стан «спинено» стає одразу, а відповідь доходить, коли
 * пошук перестане (до секунди), — тож кілька опитувань її ще чекаємо.
 */
async function pollSweep(id) {
  let grace = 5;
  for (;;) {
    const res = await fetch('/api/jobs');
    const data = await res.json().catch(() => ({}));
    const job = (data.jobs || []).find((x) => x.id === id);
    if (!job) return { ok: false, error: t('search.sweep.lost') };
    const box = el('hits');
    if (!box) return null;                 // пішли з екрана — повернувшись, приєднаються
    const p = job.progress || {};
    const what = p.n
      ? t('search.sweep.going').replace('{what}', p.basis || '')
        .replace('{i}', p.i || 0).replace('{n}', p.n)
      : t('search.sweep.prep');
    box.innerHTML = `<div class="warn next">
      <button data-act="jobs.cancel" data-job="${esc(id)}">${t('jobs.cancel')}</button>
      <span>${esc(what)}</span></div>`;
    if (FINAL_STATES.includes(job.state)) {
      if (job.state === 'error') return { ok: false, error: job.error || t('job.failed') };
      if (job.result) {
        return { ok: true, data: job.result, warnings: job.warnings || [],
          next: job.next || [] };
      }
      grace -= 1;
      if (grace <= 0) return { ok: false, error: t('search.stopped') };
    }
    await new Promise((r) => setTimeout(r, 900));
  }
}

/**
 * Із чого складається «знайдено» — за видом збігу.
 *
 * 🔴 296 тис. на «Ярошинський» читались як «прізвище майже всюди», а
 * чотири п'ятих із них — шукане всередині довших слів. Число без розкладу —
 * не відповідь.
 */
function matchSplit(m) {
  if (!m) return '';
  const bits = ['exact', 'variant', 'ending', 'inside']
    .filter((k) => Number(m[k] || 0))
    .map((k) => `${t(`search.match.${k}.n`)} ${Number(m[k]).toLocaleString('uk')}`);
  return bits.length ? `: ${esc(bits.join(' · '))}` : '';
}

function countLine(total, shown, matches) {
  return `<p class="muted search-count">${esc((total > shown ? t('search.count.cut') : t('search.count'))
    .replace('{n}', shown).replace('{all}', total))}${matchSplit(matches)}</p>`;
}

/**
 * Таблиця знахідок — одна на всі області й канали.
 *
 * 🔴 records-хіт — інша форма, не підмножина decode/pages-хіта: там немає
 * `page`/`scan`, замість `matched`/`line` — `name`/`role`/`date`, а `scans`
 * буває й зовнішньою цитатою. Плутати два рендери під один шаблон означало
 * порожні колонки на кожному хіті — issue #4.
 */
function hitTable(hits, where) {
  if (!hits.length) return '';
  const isRec = where === 'records';
  const head = isRec ? t('search.col.role') : t('search.col.page');
  return `<table><thead><tr><th>${t('search.col.case')}</th><th>${head}</th>
      <th>${t('search.col.text')}</th><th class="num">${t('search.col.score')}</th><th></th>
    </tr></thead><tbody>${hits.map((h) => {
    const whereCol = isRec ? (h.role || '') : (h.page || h.scan || '');
    // 🔴 Місце йде в контекст нарівні з іменем: однофамільця від односельця
    // відрізняє саме воно.
    const ctx = isRec
      ? [h.name, h.date, h.place].filter(Boolean).join(' · ')
      : (h.matched || h.line || h.text || h.surname || '');
    // ✎ веде на «Око» голим іменем файлу (див. `PageNote.scan`); перевірка
    // повторює валідатор ЦІЛКОМ — кнопка, що падає після кліку, гірша за її
    // відсутність.
    const scan0 = isRec ? ((h.scans && h.scans[0]) || '') : (h.scan || h.page || '');
    const scan0Local = scan0 && !/^\.|[\\/]/.test(scan0);
    return `<tr>
      <td class="mono">${esc(h.shifra || h.case_key || h.case || '')}</td>
      <td class="mono">${esc(whereCol)}</td>
      <td>${esc(String(ctx).slice(0, 120))}${h.note
    ? `<br><span class="muted">${esc(h.note)}</span>` : ''}</td>
      <td class="num">${esc(h.score ?? '')}${h.match
    ? `<br><span class="tag" title="${esc(t(`search.match.${h.match}.why`))}">${
      esc(t(`search.match.${h.match}`))}</span>` : ''}</td>
      <td class="acts">${/* 🔴 Виявити ≠ перевірити: машина подає кандидата, вирішує око. */''}
        ${!isRec && h.name && h.page
    ? `<button class="ctl-sm" data-act="hit.eye" data-run="${esc(h.name)}"
               data-page="${esc(h.page)}"
               data-line="${esc(h.line_index ?? '')}"
               title="${t('hit.eye')}">${ic('eye', 'ic-o ic-sm')}</button>` : ''}
        ${(h.key || h.shifra) && scan0Local
    ? `<button class="ctl-sm" data-act="hit.note" data-case="${esc(h.key || h.shifra)}"
               data-scan="${esc(scan0)}"
               title="${t('hit.note')}">${ic('pencil-line', 'ic-o ic-sm')}</button>` : ''}
      </td>
    </tr>`;
  }).join('')}</tbody></table>`;
}

/** Хіти лишаються під рукою: розбір відкривається з них, а не переповторює пошук. */
function keepForSift(hits, q) {
  ST.sift = { hits: hits.filter((h) => h.name && h.page), i: 0, q, crop: null, ctx: null };
  return ST.sift.hits.length
    ? `<p><button data-act="sift.open">${ic('crop-check', 'ic-sm')} ${t('sift.open')}</button></p>`
    : '';
}

/** Видача виписаного й розібраного (`search.run`) — їх `text.find` не покриває. */
function renderHits(env, q, where) {
  const d = env.data || {};
  const hits = d.hits || [];
  const cov = d.coverage || {};
  const box = el('hits');
  if (!box) return;
  box.innerHTML = `
    ${renderWarnings(env)}
    ${countLine(Number(d.total ?? hits.length), hits.length, d.matches)}
    ${keepForSift(hits, q)}
    ${hitTable(hits, where)}
    ${cov.runs !== undefined
    ? `<p class="muted">${t('search.coverage')}: ${cov.runs} ${t('search.runs')}, ${cov.pages} ${t('common.pages')}</p>`
    : cov.cases !== undefined
      ? `<p class="muted">${t('search.coverage')}: ${cov.cases} ${t('search.cases')}</p>`
      : ''}`;
}

/**
 * Відповідь `text.find`: знахідки, окремі канали роду й журнал — де й чим шукали.
 *
 * 🔴 Журнал — частина відповіді, а не довідка. «Не знайшлось» без нього не
 * відрізнити від «не шукали»: скільки прогонів, якими голосами, які канали
 * ганяли, а які ні й чому.
 */
function renderFind(env, q) {
  const d = env.data || {};
  const box = el('hits');
  if (!box) return;
  const hits = d.hits || [];
  const anchor = d.anchor || {};
  const record = d.record || {};
  // Запис — ознаки родини в одному записі: рядок таблиці — перелік ознак.
  const recHits = (record.hits || []).map((h) => ({
    ...h, shifra: h.shifra || '',
    matched: (h.marks || []).map((m) => m.term).join(' · '),
    note: ((h.marks || [])[0] || {}).line || '' }));
  box.innerHTML = `
    ${renderWarnings(env)}
    ${familyLine(d)}
    ${countLine(Number(d.total ?? hits.length), hits.length, d.matches)}
    ${keepForSift([...hits, ...(anchor.hits || []), ...recHits], q)}
    ${hitTable(hits, 'decode')}
    ${(anchor.hits || []).length ? `<h3>${t('search.ch.anchor')}</h3>
      <p class="muted">${esc(t('search.anchor.why'))}</p>${hitTable(anchor.hits, 'decode')}` : ''}
    ${recHits.length ? `<h3>${t('search.ch.record')}</h3>
      <p class="muted">${esc(t('search.record.why'))}</p>${hitTable(recHits, 'decode')}` : ''}
    ${ledgerBlock(d)}`;
}

/** Чий рід і скількома написаннями шукали — одним рядком над видачею. */
function familyLine(d) {
  const fam = d.family;
  const n = (d.stems || []).length;
  if (!fam) return '';
  return `<p class="muted">${esc(t('search.family')
    .replace('{who}', fam.display || fam.name || '').replace('{n}', n))}</p>`;
}

/** Голоси прогонів — значками рушіїв з іменами. */
function voices(ids) {
  return (ids || []).map((v) => eng(String(v).split(/[_.+]/)[0], true) || esc(v)).join(' ');
}

/**
 * Де й чим шукали: межа, прогони, голоси й канали — кожен із числом або з
 * причиною, чому його не ганяли.
 */
function ledgerBlock(d) {
  const led = d.ledger || {};
  const chans = (led.channels || []).map((ch) => {
    const name = t(`search.ch.${ch.id}`) === `search.ch.${ch.id}` ? ch.label : t(`search.ch.${ch.id}`);
    if (!ch.ran) {
      return `<li class="muted">— ${esc(name)}${ch.why ? `: ${esc(ch.why)}` : ''}</li>`;
    }
    const n = ch.hits !== undefined && ch.hits !== null ? ` — ${esc(Number(ch.hits).toLocaleString('uk'))}` : '';
    return `<li>✓ ${esc(name)}${n}</li>`;
  }).join('');
  const where = d.shifra || d.case_key || t('search.scope.all');
  return `<details class="notes search-ledger"><summary>${t('search.ledger')}</summary>
    <p>${esc(t('search.ledger.line')
    .replace('{where}', where).replace('{runs}', led.runs ?? '—')
    .replace('{pages}', led.pages_scoped ?? '—'))}
      ${led.voices && led.voices.length ? `<br>${t('search.ledger.voices')}: ${voices(led.voices)}` : ''}</p>
    ${chans ? `<ul class="search-channels">${chans}</ul>` : ''}
  </details>`;
}

Object.assign(ACTIONS, {
  /**
   * Клік по написанню — підставити його в поле й шукати одразу: написань
   * буває тридцять, і перебирати їх мишею до поля й назад — тридцять зайвих
   * кліків там, де вся суть у швидкому переборі.
   */
  'search.form': (_ev, elm) => {
    setField('q', elm.dataset.arg);
    const form = el('search-form');
    return form ? ACTIONS['search.run']({ preventDefault() {}, target: form }) : undefined;
  },

  /**
   * Зібрати індекс прочитаного — робота довга, тож чіп поступу ставимо тут, де
   * дивиться людина; готовий індекс перемальовує екран сам.
   */
  'search.index': async () => {
    const env = await callOp('search.index', {});
    const box = el('hits');
    if (!env.ok) {
      if (box) box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return undefined;
    }
    const id = (env.data || {}).job_id;
    if (box) {
      box.innerHTML = jobChip({ state: 'queued', progress: {} });
      onJob(id, (j) => {
        box.innerHTML = jobChip(j);
        if (j.state === 'done') show('search');
      });
    }
    return undefined;
  },

  /**
   * Шукати. Прочитане машиною — `text.find` роботою в черзі (`search.find`);
   * виписане й записи — `search.run`, синхронно: там лічені секунди.
   */
  'search.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const q = String(fd.get('q') || '').trim();
    if (!q) return undefined;
    const where = String(fd.get('where') || 'decode');
    const scope = scopeValue(fd.get('case'));
    const raw = Number(fd.get('thresh'));
    const thresh = Number.isFinite(raw) && raw >= 50 && raw <= 100 ? raw : THRESH;
    const seq = ++SEQ.search;
    const unlock = busyForm(ev.target);
    remember(q);
    el('hits').innerHTML = `<p class="muted">${t('search.sweep.prep')}</p>`;
    let env;
    if (where === 'decode') {
      const started = await callOp('search.find',
        { q, case: scope, thresh, limit: 100, context: 1 });
      env = started.ok ? await pollSweep((started.data || {}).job_id || '') : started;
    } else {
      env = await callOp('search.run', { q, where, limit: 100, context: 1, case: scope, thresh });
    }
    unlock();
    if (seq !== SEQ.search || !env) return undefined;
    if (!env.ok) return boxError('hits', env);
    if (where === 'decode') renderFind(env, q);
    else renderHits(env, q, where);
    return undefined;
  },

  /** Показати завершений пошук — з «Пошуку» чи з «Робіт». */
  'search.last': async (_ev, elm) => {
    const res = await fetch('/api/jobs');
    const job = res.ok
      ? ((await res.json()).jobs || []).find((j) => j.id === elm.dataset.job) : null;
    if (!job || !job.result) return boxError('hits', { ok: false, error: t('search.sweep.lost') });
    const cfg = job.cfg || {};
    setField('q', cfg.q || '');
    if (cfg.case) setField('case', cfg.case);
    return showFound({ ok: true, data: job.result, warnings: job.warnings || [] },
      cfg.q || '', job.kind);
  },

  // 🔴 Хіт — це кандидат, а не висновок: дивиться око. Доти, щоб глянути на
  // знайдений рядок, треба було переписати ім'я прогону й номер сторінки в
  // гортач руками — тобто зробити ту саму роботу, заради якої пошук і є.
  'hit.eye': async (_ev, elm) => {
    ST.view = { run: elm.dataset.run, page: elm.dataset.page,
      line: elm.dataset.line === '' ? null : Number(elm.dataset.line) };
    await show('view');
  },

  'hit.note': async (_ev, elm) => {
    ST.eye = { case: elm.dataset.case, scan: elm.dataset.scan };
    await show('eye');
  },
});
