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
import { t, LANG, tn } from '../core/strings.js';
import { callOp, staleThenFresh } from '../core/net.js';
import { esc, el, setView, busy, failure, renderWarnings,
  curGen, alive, mini } from '../core/view.js';
import { modelName, fmtDay, pathTail, ratioBar } from '../core/bits.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto, onJob } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';
import { loadProjects, projectCount, projectChip } from '../core/projects.js';

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
  // Прогони спільні: з кількома проєктами — чип того, хто замовив.
  await loadProjects();
  if (!alive(gen)) return;
  await runsLoad(true);
};

/** Що питати в сервера: сторінку груп за справою під поточним фільтром. */
function runsArgs() {
  return { grouped: true, page: RUNS.page, page_size: RUNS_PAGE,
    q: RUNS.q, engine: RUNS.engine, state: RUNS.state };
}

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
  const live = () => seq === _runsSeq && alive(gen);
  // 🔴 Групи й сторінки рахує сервер (`runs.list --grouped`): доти екран тягнув
  // усі прогони (~16 тис., ~10 МБ) і групував у браузері, а нічиї блоки
  // малював усі — 3 с на відкриття (замір 23.10.2026). Вхід — з минулої
  // відповіді одразу (`staleThenFresh`); фільтр і сторінки — легкі запити.
  if (full) {
    await staleThenFresh('runs.list', runsArgs(), (env) => (live() ? runsPaint(env, true, live) : undefined));
    return;
  }
  const env = await callOp('runs.list', runsArgs());
  if (live()) await runsPaint(env, false, live);
}

async function runsPaint(env, full, live) {
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const groups = d.groups || [];
  const extra = d.orphan_groups || [];
  // Справи для вибору тягнемо ЛИШЕ якщо нічиї на екрані є: на просторі, де все
  // прив'язане, цей запит нічого не дає й тільки сповільнює екран. І не
  // чекаємо його: перелік справ — секунда, а екран малюється одразу, вибір
  // справи дозаповнюється (`bindCasesLater`).
  const needCases = (extra.length || groups.some((g) => !g.key)) && BIND_CASES === null;
  RUNS_PAGES = Math.max(1, d.pages || 1);
  RUNS.page = d.page || 0;
  const bar = pager({ page: RUNS.page, pages: RUNS_PAGES,
    page_size: RUNS_PAGE, total: d.groups_total || 0 });
  // Нічиї блоки нумеруються наскрізно: ідентифікатори полів прив'язки несуть
  // номер блока, і два блоки з тим самим номером читали б одне поле.
  let ob = 0;
  const one = (g) => (g.key ? runsGroupHtml(g) : runsOrphanHtml(g, ob++));
  // 🔴 Нічиї прогони — під сторінкою: саме з ними треба щось зробити. Їх
  // буває сотні груп, тож тут перші кілька й кнопка «усі без справи», яка
  // гортає їх сторінками, а не 249 блоків з вибором справи в кожному.
  const more = (d.orphan_groups_total || 0) > extra.length && RUNS.state !== 'orphan'
    ? `<p><button class="ghost" data-act="runs.orphans">${esc(t('runs.orphan.all')
      .replace('{n}', d.orphan_groups_total))}</button></p>` : '';
  const body = groups.length || extra.length
    ? bar + groups.map(one).join('') + bar + extra.map(one).join('') + more : '';

  if (!full) {
    const box = el('runs-body');
    if (box) swapHtml(box, body || runsEmptyHtml(env, d.everything || 0));
    if (needCases) bindCasesLater(live);
    return undefined;
  }

  const engines = d.engines || [];
  const opt = (v, label, cur) =>
    `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;

  setView(`
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
      .replace('{n}', d.everything || 0)
      .replace('{c}', d.all_cases || 0))}</p>
    <div id="runs-body">${body || runsEmptyHtml(env, d.everything || 0)}</div>`);
  runsFocus();
  if (needCases) bindCasesLater(live);
  return undefined;
}

/** Варіанти вибору справи для прив'язки нічийного прогону. */
function bindOptions() {
  return (BIND_CASES || []).map((c) => `<option value="${esc(c.key)}">${
    esc([c.shifra, c.title].filter(Boolean).join(' — '))}</option>`).join('');
}

/** Запит переліку справ, що вже летить: два малювання не питають двічі. */
let BIND_P = null;

async function bindCasesLater(live) {
  if (BIND_P) return BIND_P;
  BIND_P = bindCasesFetch(live).finally(() => { BIND_P = null; });
  return BIND_P;
}

async function bindCasesFetch(live) {
  // 🔴 200 — це стеля СХЕМИ (`ops_library.LibraryArgs.page_size`, le=200).
  // З 300 операція відмовляла цілком, `BIND_CASES` ставав `[]`, і
  // `<datalist>` виходив порожній ЗАВЖДИ — тобто вибір справи, заради якого
  // цей блок і зроблено, не працював у жодного користувача, і мовчки: жодна
  // гілка не дивилась на `lib.ok`.
  const lib = await callOp('library.list', { page_size: 200 });
  // ⚠ Невдачу НЕ кешуємо: `null` означає «не питали», і наступний показ
  // екрана спробує ще раз. Порожній масив у цій змінній назавжди пришив би
  // одну випадкову відмову до всієї сесії.
  if (!lib.ok) return;
  BIND_CASES = (lib.data || {}).cases || [];
  if (!live()) return;
  const html = bindOptions();
  document.querySelectorAll('datalist[id^="bind-"]').forEach((dl) => { dl.innerHTML = html; });
}

PAGERS.runs = (delta) => {
  RUNS.page = step(RUNS.page, delta, RUNS_PAGES);
  return runsLoad(false);
};

/**
 * Прогін дочитано — за ДИСКОМ: текст є для всіх кадрів справи.
 *
 * 🔴 Позначка `done` у меті прогону буває хибною: прогін із 1764 сторінками з
 * 1764 стояв «не дочитано», бо раннер не дописав фінал. Приймач повноти — диск,
 * а не самозвіт (так само рахує `htr.run.completeness`).
 */
/**
 * Стан прогону словом: готово · читається зараз · не дочитано.
 *
 * 🔴 Стан рахує сервер (`htr_store.mark_run_states`): «читається» — лише
 * коли прогін є в реєстрі живих читань. Доти недочитаний прогін скрізь стояв
 * під «◐», значком поступу, — і спинений годину тому виглядав як той, що йде.
 */
export function runState(r) {
  if (runDone(r)) return `<span class="run-state">${ic('check-circle', 'ic-sm')} ${t('runs.st.done')}</span>`;
  if (r.state === 'reading') return `<span class="run-state">▶ ${t('runs.st.reading')}</span>`;
  return `<span class="run-state" title="${esc(t('runs.st.going.why'))}">${ic('pause', 'ic-sm')} ${t('runs.st.going')}</span>`;
}

function runDone(r) {
  // Стан ставить сервер (`mark_run_states`) — з прапорцем `done` мети, якого
  // «Огляд» не отримує; без цього прогін, позначений дочитаним при неповних
  // кадрах, на «Огляді» був «не дочитано», а в «Прогонах» — «готово».
  if (r.state) return r.state === 'done';
  const n = Number(r.frames || 0);
  return Boolean(r.done || (n && Number(r.pages_done || 0) >= n));
}

function runsRow(r) {
  // 🔴 Бейджі всіх рушіїв прогону. Прогін двома голосами пише обидві моделі
  // одним полем через «+», і показавши лише перший, ми сказали б, що письмо
  // покрите наполовину — тобто порадили б прогнати те, що вже прогнали.
  const ids = r.engine_ids && r.engine_ids.length
    ? r.engine_ids : [r.engine_id].filter(Boolean);
  const badges = ids.map((x) => eng(x, false, LANG, t(`engine.${x}.role`))).join('');
  const state = runState(r);
  // 🔴 Відсоток лише зі справжнім знаменником. Немає кадрів справи — друкуємо
  // самі сторінки: покриття, порахане від себе самого, завжди дорівнює 100%
  // і читається як «прочитано все».
  // Кадрів менше, ніж прочитаних сторінок (справа одним PDF, тека кадрів не та) —
  // знаменник ненадійний: «315 / 1 · 31500%» нічого не означало (22.10.2026).
  const n = Number(r.frames || 0) >= Number(r.pages_done || 0) ? Number(r.frames || 0) : 0;
  const cov = n
    ? `<td class="num cov-cell">${ratioBar(r.pages_done || 0, n)} ${Math.round(100 * (r.pages_done || 0) / n)}%</td>`
    : `<td class="num dim" title="${esc(t('runs.nodenom'))}">—</td>`;
  const fail = r.failed
    ? `<span class="warn-inline" title="${esc(t('runs.failed'))}">✗${r.failed}</span>`
    : '';
  return `<tr>
    <td>${state}${projectCount() > 1
    ? ` ${projectChip(r.project || '', { hubLabel: t('pj.hub') })}` : ''}</td>
    <td>${badges}</td>
    <td title="${esc(r.model || '')}">${esc(modelName(r.model))}</td>
    <td class="num">${esc(r.pages_done || 0)}${n ? ` / ${esc(n)}` : ''} ${fail}</td>
    ${cov}
    <td class="dim">${esc(fmtDay((r.updated || '').slice(0, 10)))}</td>
    <td class="acts">${!runDone(r) && r.state !== 'reading' && r.case_dir ? `<button class="ctl-sm" data-act="runs.resume"
      data-arg="${esc(r.case_dir)}" title="${esc(t('runs.resume.why'))}">${ic('quill', 'ic-o ic-sm')}
      ${t('runs.resume')}</button>` : ''}<button class="ctl-sm" data-act="runs.open" data-arg="${esc(r.name)}"
      title="${esc(t('runs.open'))}">${ic('page', 'ic-o ic-sm')}</button></td>
  </tr>`;
}

function runsGroupHtml(g) {
  const n = g.frames || 0;
  return `<section class="run-group" data-case="${esc(g.key)}">
    <h3>
      <span class="shifra" title="${esc(g.case_dir || g.key || '')}">${esc(g.shifra
        || (String(g.key || '').startsWith('dir:') ? pathTail(g.case_dir || g.key.slice(4)) : g.key))}</span>
      <span class="name" title="${esc(g.title || '')}">${esc(g.title || '')}</span>
      ${n ? `<span class="frames dim">${esc(tn('unit.frames', Number(n)))}</span>` : ''}
      ${g.key ? `<button class="ctl-sm" data-act="runs.lib" data-arg="${esc(g.key)}"
        title="${esc(t('runs.act.lib'))}">${ic('books', 'ic-o ic-sm')}</button>` : ''}
    </h3>
    <table class="tbl-cards"><thead><tr>
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
    return `<p class="dim">${ic('stitch', 'ic-sm')} ${t('runs.gap.covered')}</p>`;
  }
  if (scripts.has('cyrillic') && ids.size === 1 && ids.has('pysar')) {
    return `<p class="dim">${ic('stitch', 'ic-sm')} ${t('runs.gap.second')}</p>`;
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
  const list = `<datalist id="${uid('cases')}">${bindOptions()}</datalist>`;
  return `<section class="run-group orphan">
    <h3>${t('runs.orphan.title')}</h3>
    <p class="warn">${t('runs.orphan.why')}</p>
    <p class="muted">${t('runs.bind.pick')}</p>
    ${list}
    <table><tbody>${g.runs.map((r, i) => `<tr>
      <td class="mono">${esc(r.name)}</td>
      <td class="num">${esc(r.pages_done || 0)}</td>
      <td class="mono dim" title="${esc(r.case_dir || '')}">${esc(pathTail(r.case_dir))}</td>
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
  return `<div class="warn empty-mini">${mini('knyha', 72)}<div>${t('runs.empty.none')}
    <button data-act="nav" data-arg="read">${t('nav.read')}</button></div></div>`;
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
  // Усі нічиї групи — сторінками: той самий фільтр «без справи».
  'runs.orphans': () => {
    RUNS = { ...RUNS, state: 'orphan', page: 0 };
    return runsLoad(true);
  },

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
  /** Дочитати — там, де читання запускають і де видно його хід. */
  'runs.resume': (_ev, elm) => goto('read', { case_dir: elm.dataset.arg }),

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
    say(`${renderWarnings(env)}<div class="warn">${ic('check-circle', 'ic-sm')} ${esc(elm.dataset.arg)} → ${
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
