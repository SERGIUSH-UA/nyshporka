/**
 * 📜 Прогони — що ця машина вже прочитала.
 *
 * Питання, на яке не відповідає ні черга робіт, ні бібліотека: черга знає, що
 * йде зараз, бібліотека — що є на диску, а «чим і наскільки прочитана ця
 * книга» не знає ніхто. Доти дізнатись це можна було лише набравши ім'я
 * прогону в гортачі — тобто вже знаючи відповідь.
 *
 * 🔴 Групування ЗА справою, а не за датою. Єдине питання, заради якого цей
 * екран існує, — «чи покрите письмо цієї книги», і воно пер-справа. Плоский
 * перелік за часом розкидав би два прогони однієї книги на рядки 4 і 31, і
 * саме та відповідь, по яку прийшли, лишилась би невидимою.
 *
 * 🔴 Відсоток покриття малюється лише там, де є знаменник. Покриття, чий
 * знаменник дорівнює чисельнику, — це та сама вада, від якої існує правило
 * «нуль зі знаменником», просто в новому вбранні: воно завжди показує 100%.
 */
import { t, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto, onJob } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';

/** Фільтр переліку. Живе між входами на екран, як і в бібліотеці. */
let RUNS = { q: '', engine: '', state: '', page: 0 };

/**
 * Скільки справ показувати на сторінці.
 *
 * 🔴 Сторінка міряється справами, а не прогонами: екран групує прогони за
 * справою, і різати по рядках означало б розірвати групу навпіл — половина
 * прогонів книги лишилась би на наступній сторінці під чужим заголовком.
 */
const RUNS_PAGE = 25;
let RUNS_PAGES = 1;

let _runsSeq = 0;

SCREENS.runs = async () => {
  const gen = curGen();
  busy();
  await runsLoad(true);
  if (!alive(gen)) return;
};

/**
 * @param {boolean} full  перемалювати весь екран чи лише перелік.
 *
 * Та сама межа, що в бібліотеці: фільтр міняє тільки видачу, бо повна
 * перемальовка знищує поле пошуку разом із фокусом, і набране після паузи
 * йде в нікуди.
 */
async function runsLoad(full = false) {
  const seq = ++_runsSeq;
  const gen = curGen();
  const env = await callOp('runs.list', {});
  if (seq !== _runsSeq || !alive(gen)) return;
  if (!env.ok) return failure(env);

  const runs = (env.data || {}).runs || [];
  const groups = runsGroup(runs.filter(runsMatch));
  const orphans = groups.filter((g) => !g.key);
  // Справи для вибору тягнемо ЛИШЕ якщо нічиї є: на просторі, де все
  // прив'язане, цей запит нічого не дає й тільки сповільнює екран.
  if (orphans.length && BIND_CASES === null) {
    // 🔴 200 — це стеля СХЕМИ (`ops_library.LibraryArgs.page_size`, le=200).
    // З 300 операція відмовляла цілком, `BIND_CASES` ставав `[]`, і
    // `<datalist>` виходив порожній ЗАВЖДИ — тобто вибір справи, заради якого
    // цей блок і зроблено, не працював у жодного користувача, і мовчки: жодна
    // гілка не дивилась на `lib.ok`.
    const lib = await callOp('library.list', { page_size: 200 });
    if (seq !== _runsSeq || !alive(gen)) return;
    // ⚠ Невдачу НЕ кешуємо: `null` означає «не питали», і наступний показ
    // екрана спробує ще раз. Порожній масив у цій змінній назавжди пришив би
    // одну випадкову відмову до всієї сесії.
    if (lib.ok) BIND_CASES = (lib.data || {}).cases || [];
  }
  const known = groups.filter((g) => g.key);
  RUNS_PAGES = Math.max(1, Math.ceil(known.length / RUNS_PAGE));
  if (RUNS.page >= RUNS_PAGES) RUNS.page = 0;
  const from = RUNS.page * RUNS_PAGE;
  const shown = known.slice(from, from + RUNS_PAGE);
  const bar = pager({ page: RUNS.page, pages: RUNS_PAGES,
    page_size: RUNS_PAGE, total: known.length });
  // 🔴 Нічиї прогони — під сторінкою й без сторінок: їх мало, і саме з ними
  // треба щось зробити. Сховати їх на четвертій сторінці означало б лишити
  // невидимим текст, який і так невидимий з кожної картки справи.
  const body = bar + shown.map(runsGroupHtml).join('') + bar
    + orphans.map((g, gi) => runsOrphanHtml(g, gi)).join('');

  if (!full) {
    const box = el('runs-body');
    if (box) swapHtml(box, body || runsEmptyHtml(env, runs.length));
    return;
  }

  const engines = [...new Set(runs.flatMap((r) =>
    (r.engine_ids && r.engine_ids.length ? r.engine_ids
      : [r.engine_id])).filter(Boolean))];
  const opt = (v, label, cur) =>
    `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;

  setView(`<h2>${ic('list')} ${t('runs.title')}</h2>
    <p class="muted">${t('runs.why')}</p>
    <div class="row">
      <input id="runs-q" type="search" placeholder="${esc(t('runs.q'))}"
             value="${esc(RUNS.q)}" data-act="runs.filter" data-live="1">
      <select id="runs-engine" data-act="runs.filter">
        ${opt('', t('runs.engine.any'), RUNS.engine)}
        ${engines.map((e) => opt(e, e, RUNS.engine)).join('')}
      </select>
      <select id="runs-state" data-act="runs.filter">
        ${opt('', t('runs.state.any'), RUNS.state)}
        ${opt('done', t('runs.state.done'), RUNS.state)}
        ${opt('going', t('runs.state.going'), RUNS.state)}
        ${opt('orphan', t('runs.state.orphan'), RUNS.state)}
      </select>
    </div>
    ${renderWarnings(env)}
    <p class="muted" id="runs-count">${esc(t('runs.count')
      .replace('{n}', runs.length)
      .replace('{c}', new Set(runs.map((r) => r.case_key || r.case_dir)).size))}</p>
    <div id="runs-body">${body || runsEmptyHtml(env, runs.length)}</div>`);
  runsFocus();
}

PAGERS.runs = (delta) => {
  RUNS.page = step(RUNS.page, delta, RUNS_PAGES);
  return runsLoad(false);
};

function runsMatch(r) {
  const ids = r.engine_ids && r.engine_ids.length
    ? r.engine_ids : [r.engine_id].filter(Boolean);
  if (RUNS.engine && !ids.includes(RUNS.engine)) return false;
  if (RUNS.state === 'done' && !r.done) return false;
  if (RUNS.state === 'going' && r.done) return false;
  if (RUNS.state === 'orphan' && r.case_key) return false;
  if (RUNS.q) {
    const hay = [r.name, r.shifra, r.title, r.model, r.case_dir]
      .map((x) => String(x || '')).join(' ').toLowerCase();
    if (!hay.includes(RUNS.q.toLowerCase())) return false;
  }
  return true;
}

/** Прогони → групи за справою. Порядок груп — за свіжістю найновішого. */
function runsGroup(runs) {
  const by = new Map();
  for (const r of runs) {
    const key = r.case_key || '';
    const id = key || `dir:${r.case_dir || r.name}`;
    if (!by.has(id)) {
      by.set(id, { key, id, shifra: r.shifra || key, title: r.title || '',
                   case_dir: r.case_dir || '', frames: 0, runs: [],
                   updated: '' });
    }
    const g = by.get(id);
    g.runs.push(r);
    if ((r.updated || '') > g.updated) g.updated = r.updated || '';
    if (!g.shifra && r.shifra) g.shifra = r.shifra;
    if (!g.title && r.title) g.title = r.title;
    if (!g.frames && r.frames) g.frames = r.frames;
  }
  return [...by.values()].sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
}

function runsRow(r) {
  // 🔴 Бейджі всіх рушіїв прогону. Прогін двома голосами пише обидві моделі
  // одним полем через «+», і показавши лише перший, ми сказали б, що письмо
  // покрите наполовину — тобто порадили б прогнати те, що вже прогнали.
  const ids = r.engine_ids && r.engine_ids.length
    ? r.engine_ids : [r.engine_id].filter(Boolean);
  const badges = ids.map((x) => eng(x, false, LANG)).join('');
  const state = r.done
    ? `<span class="run-state">✅ ${t('runs.st.done')}</span>`
    : `<span class="run-state">▶ ${t('runs.st.going')}</span>`;
  // 🔴 Відсоток лише зі справжнім знаменником. Немає кадрів справи — друкуємо
  // самі сторінки: покриття, порахане від себе самого, завжди дорівнює 100%
  // і читається як «прочитано все».
  const n = Number(r.frames || 0);
  const cov = n
    ? `<td class="num">${Math.round(100 * (r.pages_done || 0) / n)}%</td>`
    : `<td class="num dim" title="${esc(t('runs.nodenom'))}">—</td>`;
  const fail = r.failed
    ? `<span class="warn-inline" title="${esc(t('runs.failed'))}">✗${r.failed}</span>`
    : '';
  return `<tr>
    <td>${state}</td>
    <td>${badges}</td>
    <td class="mono">${esc(r.model || '')}</td>
    <td class="num">${esc(r.pages_done || 0)}${n ? ` / ${esc(n)}` : ''} ${fail}</td>
    ${cov}
    <td class="mono dim">${esc((r.updated || '').slice(0, 10))}</td>
    <td><button class="ctl-sm" data-act="runs.open" data-arg="${esc(r.name)}"
      title="${esc(t('runs.open'))}">${ic('page', 'ic-o ic-sm')}</button></td>
  </tr>`;
}

function runsGroupHtml(g) {
  const n = g.frames || 0;
  return `<section class="run-group" data-case="${esc(g.key)}">
    <h3>
      <span class="shifra">${esc(g.shifra || g.key)}</span>
      <span class="name" title="${esc(g.title || '')}">${esc(g.title || '')}</span>
      ${n ? `<span class="frames dim">${esc(n)} ${t('common.frames')}</span>` : ''}
      ${g.key ? `<button class="ctl-sm" data-act="runs.lib" data-arg="${esc(g.key)}"
        title="${esc(t('runs.act.lib'))}">${ic('books', 'ic-o ic-sm')}</button>` : ''}
    </h3>
    <table><thead><tr>
      <th>${t('runs.col.state')}</th><th>${t('runs.col.engine')}</th>
      <th>${t('runs.col.model')}</th>
      <th class="num">${t('runs.col.pages')}</th>
      <th class="num">${t('runs.col.cov')}</th>
      <th>${t('runs.col.when')}</th><th></th>
    </tr></thead>
    <tbody>${g.runs.map(runsRow).join('')}</tbody></table>
    ${runsGap(g)}
  </section>`;
}

/**
 * 🔴 «Прогін є» мовчки читається як «справу прочитано».
 *
 * Саме так половина книги з двома письмами лишається непрочитаною: перший
 * прогін закриває своє письмо, у переліку з'являється галочка, і питання
 * знімається. Тому тут три різні речення, а не спільне «щось не так».
 */
function runsGap(g) {
  // 🔴 Рахуємо по всіх рушіях кожного прогону, а не по головному. Прогін
  // «Писар + Дяк» покриває два — і зведений до одного, він давав пораду
  // прогнати другий голос, який уже прогнали.
  const ids = new Set();
  for (const r of g.runs) {
    for (const x of (r.engine_ids && r.engine_ids.length
      ? r.engine_ids : [r.engine_id])) if (x) ids.add(x);
  }
  const scripts = new Set(g.runs.map((r) => r.script).filter(Boolean));
  if (ids.size >= 2) {
    return `<p class="dim">🤝 ${t('runs.gap.covered')}</p>`;
  }
  if (scripts.has('cyrillic') && ids.size === 1 && ids.has('pysar')) {
    return `<p class="dim">🤝 ${t('runs.gap.second')}</p>`;
  }
  return '';
}

/**
 * 🔴 Прогін без шифри — найдорожчий рядок цього екрана.
 *
 * Текст є, а до якої справи належить — невідомо, і зшивати це доводиться
 * правкою JSON руками. Тому нічиї стоять окремим блоком із кнопкою, а не
 * розчиняються серед решти.
 */
function runsOrphanHtml(g, gi = 0) {
  // 🔴 Саме тут стоїть кнопка, якої не було. Докстрінг вище обіцяв її з
  // першого дня, а в рядку жила лише «подивитись» — і вела вона рівно у
  // відмову гортача «теки справи цей прогін не називає», яка радила набрати
  // `nysh cases bind` у терміналі. Тобто єдиний вихід із екрана лежав поза
  // застосунком (звіт користувача 29.08.2026).
  // 🔴 Ідентифікатори НЕСУТЬ номер блока. Нічиї групуються за текою
  // (`runsGroup` → `dir:…`), тож блоків буває кілька, а `i` в кожному
  // починається з нуля. `getElementById` віддає ПЕРШИЙ збіг у документі —
  // тобто кнопка другого блока читала ключ із першого: або мовчазна відмова
  // «виберіть справу», або, гірше, чужий ключ, записаний у прив'язку. А
  // прив'язка — найсильніший канал резолвера, і помилка в ній тиха й довговічна.
  const uid = (name) => `bind-${gi}-${name}`;
  const list = `<datalist id="${uid('cases')}">${
    (BIND_CASES || []).map((c) => `<option value="${esc(c.key)}">${
      esc([c.shifra, c.title].filter(Boolean).join(' — '))}</option>`).join('')}</datalist>`;
  return `<section class="run-group orphan">
    <h3>⚠ ${t('runs.orphan.title')}</h3>
    <p class="warn">${t('runs.orphan.why')}</p>
    <p class="muted">${t('runs.bind.pick')}</p>
    ${list}
    <table><tbody>${g.runs.map((r, i) => `<tr>
      <td class="mono">${esc(r.name)}</td>
      <td class="num">${esc(r.pages_done || 0)}</td>
      <td class="mono dim">${esc(r.case_dir || '')}</td>
      <td><input id="${uid(`key-${i}`)}" list="${uid('cases')}" size="22"
        placeholder="${esc(t('runs.bind.ph'))}"></td>
      <td><input id="${uid(`why-${i}`)}" size="18"
        placeholder="${esc(t('runs.bind.why'))}"></td>
      <td><button class="ctl-sm" data-act="runs.bind" data-arg="${esc(r.name)}"
        data-row="${esc(uid(String(i)))}">${esc(t('runs.bind'))}</button>
        <button class="ctl-sm" data-act="runs.open" data-arg="${esc(r.name)}"
        title="${esc(t('runs.open'))}">${ic('page', 'ic-o ic-sm')}</button></td>
    </tr>`).join('')}</tbody></table>
    <div id="${uid('hits')}"></div>
  </section>`;
}

/**
 * 🔴 Порожньо й «нічого не прочитано» — різні відповіді.
 *
 * Нуль під фільтром означає «звузьте фільтр», нуль без нього — «читати ще не
 * починали», і друга відповідь мусить нести кнопку, а не лише число.
 */
function runsEmptyHtml(env, total) {
  if (total) {
    return `<div class="warn">${t('runs.empty.filter').replace('{n}', total)}</div>`;
  }
  return `<div class="warn">${t('runs.empty.none')}
    <button data-act="nav" data-arg="read">${t('nav.read')}</button></div>`;
}

/**
 * Справи для вибору при прив'язці. Тягнеться один раз: перелік міняється рідше,
 * ніж людина відкриває екран, а запит на кожен показ платився б за незмінне.
 */
let BIND_CASES = null;

/** Прокрутка до справи, з якої сюди прийшли. */
function runsFocus() {
  if (!ST.runsFocus) return;
  const node = document.querySelector(
    `.run-group[data-case="${CSS.escape(ST.runsFocus)}"]`);
  ST.runsFocus = '';
  if (node) node.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

Object.assign(ACTIONS, {
  'runs.filter': () => {
    RUNS = {
      q: (el('runs-q') || {}).value || '',
      engine: (el('runs-engine') || {}).value || '',
      state: (el('runs-state') || {}).value || '',
      // Зміна фільтра завжди повертає на першу сторінку: інакше людина звужує
      // вибірку до трьох справ і бачить порожньо, бо стоїть на сьомій.
      page: 0,
    };
    return runsLoad(false);
  },

  /** 📚 Ця сама справа в бібліотеці — з групи прогонів. */
  'runs.lib': (_ev, elm) => goto('library', { key: elm.dataset.arg }),

  /**
   * 🔗 Прив'язати нічийний прогін до справи — мишкою, а не командою.
   *
   * Після прив'язки реєстр перезбирається одразу: інакше людина натискає
   * кнопку, повертається в перелік і бачить прогін так само нічиїм — тобто
   * читає це як «не спрацювало».
   */
  'runs.bind': async (_ev, elm) => {
    // `data-row` несе повний ідентифікатор рядка разом із номером блока —
    // див. `uid()` у `runsOrphanHtml`.
    const row = elm.dataset.row;                       // «bind-<блок>-<рядок>»
    const at = row.lastIndexOf('-');
    const pre = row.slice(0, at);                      // «bind-<блок>»
    const i = row.slice(at + 1);
    const key = ((el(`${pre}-key-${i}`) || {}).value || '').trim();
    const hits = el(`${pre}-hits`);
    const say = (html) => { if (hits) hits.innerHTML = html; };
    if (!key) return say(`<div class="warn err">${t('runs.bind.pick')}</div>`);
    const env = await callOp('cases.bind', {
      run: elm.dataset.arg, key,
      why: ((el(`${pre}-why-${i}`) || {}).value || '').trim(),
    });
    if (!env.ok) return say(`<div class="warn err">${esc(env.error)}</div>`);
    say(`${renderWarnings(env)}<div class="warn">✅ ${esc(elm.dataset.arg)} → ${
      esc(key)} — ${t('runs.bind.done')}</div>`);
    // 🔴 Прив'язка змінює реєстр, і доки він не перезібраний, вона нікуди не
    // видна — сама операція каже про це полем `stale`. Робимо це за людину:
    // просити натиснути другу кнопку заради того, щоб побачила перша, означало
    // б лишити той самий глухий кут, лише на крок далі.
    //
    // ⚠ `cases.build` оголошена `long=True`: виклик повертає НОМЕР РОБОТИ, а
    // не зібраний реєстр. Перечитати перелік одразу означало б прочитати його
    // проти старого зрізу — і побачити прогін так само нічиїм, тобто рівно те
    // «не спрацювало», проти якого ця кнопка й стоїть.
    const built = await callOp('cases.build', { rescan: false });
    const jid = built.ok ? (built.data || {}).job_id : null;
    BIND_CASES = null;
    if (!jid) return runsLoad(false);
    onJob(jid, (j) => { if (j.state === 'done') runsLoad(false); });
    return undefined;
  },

  'runs.open': (_ev, elm) => {
    // Гортач сам відкриє першу сторінку прогону: імені сторінки тут ще ніхто
    // не знає, і вимагати його означало б повернути ту саму вимогу «набери
    // руками», заради зняття якої екран і зроблено.
    ST.view = { run: elm.dataset.arg, page: '', line: null };
    return show('view');
  },
});
