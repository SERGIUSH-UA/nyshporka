/**
 * Нишпорка — браузерне обличчя.
 *
 * 🔴 РЕЄСТР ДІЙ, а не глобали й інлайн-onclick. У попередньому конвеєрі 26
 * файлів клали функції у `window` і вішали `onclick="doThing()"` прямо в
 * розмітці. Колізія імен між двома файлами не видна ні в дифі, ні в консолі:
 * пізніший просто перекриває раніший, і кнопка починає робити чуже. Тут кнопка
 * несе `data-act="ім'я"`, а обробники живуть у `ACTIONS`; невідома дія —
 * гучна помилка, а не тиша.
 *
 * 🔴 БЕЗ ЗБИРАЧА, і це рішення, а не лінощі. Збирач у застосунку, який ставлять
 * подвійним кліком, означає Node у складі релізу або зібраний бандл у git.
 * Три речі, заради яких він був потрібен, вирішені інакше: хеші імен — версією
 * у запиті (її дає сам сервер), переклад — словником нижче, типи форм — тим,
 * що фронт бере СХЕМИ операцій із `/api/ops`, а не переписує поля руками.
 * Останнє сильніше за згенеровані типи: переписане може протухнути, взяте з
 * сервера — ні.
 */

// ── i18n ─────────────────────────────────────────────────────────────────────
const STRINGS = {
  uk: {
    'nav.home': 'Дослідження', 'nav.sources': 'Джерела', 'nav.cases': 'Мої справи',
    'nav.search': 'Пошук', 'nav.jobs': 'Роботи',
    'home.title': 'З чого почнемо',
    'home.have_scans': 'У мене є скани',
    'home.have_scans.hint': 'тека з фотографіями або PDF зі справою',
    'home.where': 'Не знаю, де шукати',
    'home.where.hint': 'пошук по каталогах архівів і покажчиках плівок',
    'home.demo': 'Показати на прикладі',
    'home.demo.hint': 'демо-справа: перевірити, що читання працює на цій машині',
    'sources.q': 'Село, прізвище або слово із заголовка справи',
    'sources.find': 'Шукати',
    'sources.searched': 'шукали в',
    'sources.nothing': 'Нічого не знайшлось',
    'sources.zero_warning':
      'Порожній результат означає «немає в оглянутих каталогах», а не «не існує».',
    'sources.get': 'Завантажити',
    'sources.manifest': 'Що принесе',
    'cases.title': 'Справи в роботі',
    'cases.frames': 'кадрів', 'cases.read': 'прочитано', 'cases.none': 'не читано',
    'cases.nodir': 'теки на цій машині немає — правити нічого',
    'cases.build': 'перезібрати реєстр',
    'cases.build.why': "Реєстр — зріз п'яти сховищ: після прогону, завантаження чи занесення в облік він старіє за хвилини.",
    'search.q': 'Прізвище', 'search.where': 'Де шукати',
    'search.where.decode': 'у прочитаному машиною',
    'search.where.pages': 'у виписаних прізвищах',
    'search.where.records': 'в учасниках записів',
    'search.run': 'Знайти',
    'search.coverage': 'шукали по',
    'nav.eye': 'Око',
    'eye.case': 'Справа', 'eye.check': 'Що вже дивились',
    'eye.disk': 'на диску', 'eye.noted': 'занесено', 'eye.left': 'ще не дивились',
    'eye.note': 'Занести сторінку', 'eye.scan': 'Скан', 'eye.type': 'Тип',
    'eye.surnames': 'Прізвища ЯК У ДЖЕРЕЛІ (через кому)',
    'eye.status': 'Повнота', 'eye.comment': 'Коментар', 'eye.save': 'Занести',
    'eye.rule': 'Заносьте КОЖЕН відкритий скан — навіть порожній. Інакше наступного разу ви відкриєте його знову.',
    'case.title': 'Завести або виправити справу',
    'case.dir': 'Тека зі сканами', 'case.shifra': 'Шифра',
    'case.name': 'Назва справи', 'case.type': 'Тип документа',
    'case.years': 'Роки', 'case.place': 'Місце', 'case.save': 'Зберегти',
    'case.note': 'Примітка: звідки взято, що незрозуміло',
    'case.edit': 'Змінити опис справи', 'case.fresh': 'Завести іншу',
    'case.editing': 'Правимо опис теки',
    'case.keep': 'Порожнє поле лишає попереднє значення — стерти опис можна лише правкою файлу _source.json у теці.',
    'case.why': 'Без шифри тека лишається купою файлів: немає ні обліку прочитаного, ні можливості послатись на знахідку.',
    'nav.view': 'Гортач',
    'view.run': 'Прогін', 'view.open': 'Відкрити',
    'view.pages': 'сторінок', 'view.lines': 'рядків',
    'view.eye': 'Око вирішує, машина лише подає — дивіться на рядок, а не на текст.',
    'nav.read': 'Читання',
    'read.dir': 'Тека зі сканами (пласка)', 'read.plan': 'Що робитимемо',
    'read.go': 'Читати', 'read.frames': 'кадрів', 'read.script': 'письмо',
    'read.model': 'модель', 'read.voice': 'другий голос',
    'read.started': 'Поставлено в чергу',
    'nav.export': 'Експорт',
    'export.case': 'Справа', 'export.what': 'Що вивантажити',
    'export.records': 'розібрані записи', 'export.pages': 'прізвища зі сторінок',
    'export.run': 'Показати', 'export.csv': 'Зберегти CSV',
    'jobs.title': 'Що зараз робиться',
    'jobs.none': 'Наразі нічого не виконується',
    'jobs.cancel': 'Спинити',
    'common.loading': 'Хвилинку…',
    'common.error': 'Не вийшло',
    'common.frames': 'кадрів',
    'common.pages': 'сторінок',
  },
  en: {
    'nav.home': 'Research', 'nav.sources': 'Sources', 'nav.cases': 'My cases',
    'nav.search': 'Search', 'nav.jobs': 'Jobs',
    'home.title': 'Where do we start',
    'home.have_scans': 'I have scans',
    'home.have_scans.hint': 'a folder of photographs, or a PDF of a case',
    'home.where': "I don't know where to look",
    'home.where.hint': 'search archive catalogues and film sheet indexes',
    'home.demo': 'Show me an example',
    'home.demo.hint': 'demo case: check that reading works on this machine',
    'sources.q': 'Village, surname, or a word from the case title',
    'sources.find': 'Search',
    'sources.searched': 'searched in',
    'sources.nothing': 'Nothing found',
    'sources.zero_warning':
      'An empty result means "not in the catalogues we looked at", not "does not exist".',
    'sources.get': 'Download',
    'sources.manifest': 'What it brings',
    'cases.title': 'Cases in progress',
    'cases.frames': 'frames', 'cases.read': 'read', 'cases.none': 'not read',
    'cases.nodir': 'folder not present on this machine — nothing to edit',
    'cases.build': 'rebuild registry',
    'cases.build.why': 'The registry is a snapshot of five stores: after a run, a download or a note it goes stale within minutes.',
    'search.q': 'Surname', 'search.where': 'Where to look',
    'search.where.decode': 'in machine-read text',
    'search.where.pages': 'in noted surnames',
    'search.where.records': 'in record participants',
    'search.run': 'Search',
    'search.coverage': 'searched across',
    'nav.eye': 'Eye',
    'eye.case': 'Case', 'eye.check': 'Already looked at',
    'eye.disk': 'on disk', 'eye.noted': 'noted', 'eye.left': 'not looked at yet',
    'eye.note': 'Note a page', 'eye.scan': 'Scan', 'eye.type': 'Type',
    'eye.surnames': 'Surnames AS WRITTEN (comma separated)',
    'eye.status': 'Completeness', 'eye.comment': 'Comment', 'eye.save': 'Save',
    'eye.rule': 'Note EVERY scan you opened — even an empty one. Otherwise you will open it again next time.',
    'case.title': 'Register or correct a case',
    'case.dir': 'Folder with scans', 'case.shifra': 'Reference',
    'case.name': 'Case title', 'case.type': 'Document type',
    'case.years': 'Years', 'case.place': 'Place', 'case.save': 'Save',
    'case.note': 'Note: where it came from, what is unclear',
    'case.edit': 'Edit case description', 'case.fresh': 'Register another',
    'case.editing': 'Editing the description of',
    'case.keep': 'An empty field keeps the previous value — to erase a field, edit _source.json in the folder.',
    'case.why': 'Without a reference the folder stays a pile of files: no record of what was read, no way to cite a finding.',
    'nav.view': 'Viewer',
    'view.run': 'Run', 'view.open': 'Open',
    'view.pages': 'pages', 'view.lines': 'lines',
    'view.eye': 'The eye decides, the machine only proposes — look at the line, not the text.',
    'nav.read': 'Reading',
    'read.dir': 'Folder with scans (flat)', 'read.plan': 'What we will do',
    'read.go': 'Read', 'read.frames': 'frames', 'read.script': 'script',
    'read.model': 'model', 'read.voice': 'second voice',
    'read.started': 'Queued',
    'nav.export': 'Export',
    'export.case': 'Case', 'export.what': 'What to export',
    'export.records': 'parsed records', 'export.pages': 'surnames from pages',
    'export.run': 'Show', 'export.csv': 'Save CSV',
    'jobs.title': 'What is running',
    'jobs.none': 'Nothing is running right now',
    'jobs.cancel': 'Stop',
    'common.loading': 'One moment…',
    'common.error': 'Did not work',
    'common.frames': 'frames',
    'common.pages': 'pages',
  },
};

let LANG = localStorage.getItem('nysh.lang') || 'uk';
const t = (key) => (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.uk[key] || key;

// ── транспорт ────────────────────────────────────────────────────────────────
const TOKEN = document.body.dataset.token || '';

async function callOp(name, args) {
  const res = await fetch(`/api/op/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Nysh-Token': TOKEN },
    body: JSON.stringify(args || {}),
  });
  const env = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  return env;
}

// ── розмітка ─────────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const el = (id) => document.getElementById(id);

/** Попередження конверта — на екран ЗАВЖДИ. Саме тут живе «нуль зі знаменником». */
function renderWarnings(env) {
  const bits = [];
  if (env.stale && env.stale.is) {
    // 🔴 Виправлення поруч із застереженням, а не в підказці «наберіть у
    // терміналі». Той, хто працює формами, інакше лишається із застереженням
    // і без способу його зняти — тобто змушений вірити застарілому зрізу.
    bits.push(`<div class="warn stale">⚠ ${esc(env.stale.reasons.join('; '))}
      <button data-act="cases.build">${t('cases.build')}</button></div>`);
  }
  for (const w of env.warnings || []) {
    bits.push(`<div class="warn">⚠ ${esc(w.text)}</div>`);
  }
  return bits.join('');
}

function setView(html) { el('view').innerHTML = html; }

function busy() { setView(`<p class="muted">${t('common.loading')}</p>`); }

function failure(env) {
  setView(`<div class="warn err">${t('common.error')}: ${esc(env.error || '?')}</div>`);
}

// ── екрани ───────────────────────────────────────────────────────────────────
const SCREENS = {};

/** Остання вивантажена таблиця — щоб CSV збирався без повторного запиту. */
let LAST_EXPORT = null;

/** Остання тека, для якої рахували план читання. */
let LAST_READ = null;

/** Прогін і сторінка, відкриті в гортачі. */
let VIEW = null;

/** Справа, відкрита в обліку прочитаного. */
let EYE = null;

/**
 * Опис, підвантажений у форму «Завести справу» для ПРАВКИ.
 *
 * 🔴 Порожня форма над уже описаною текою — пастка: людина бачить порожні
 * поля, вважає, що опису немає, і друкує його заново — часто інакше, ніж
 * попереднього разу. Тому правка починається з показу записаного.
 */
let EDIT = null;

SCREENS.home = async () => {
  const env = await callOp('workspace.info', {});
  const ws = env.ok ? env.data : {};
  setView(`
    <h2>${t('home.title')}</h2>
    ${renderWarnings(env)}
    <div class="cards">
      <button class="card" data-act="home.scans">
        <span class="card-title">📁 ${t('home.have_scans')}</span>
        <span class="card-hint">${t('home.have_scans.hint')}</span>
      </button>
      <button class="card" data-act="nav" data-arg="sources">
        <span class="card-title">🔎 ${t('home.where')}</span>
        <span class="card-hint">${t('home.where.hint')}</span>
      </button>
      <button class="card" data-act="home.demo">
        <span class="card-title">▶ ${t('home.demo')}</span>
        <span class="card-hint">${t('home.demo.hint')}</span>
      </button>
    </div>
    <p class="muted mono">${esc(ws.root || '')}</p>`);
};

SCREENS.sources = async () => {
  setView(`
    <h2>${t('nav.sources')}</h2>
    <form class="row" data-act="sources.find">
      <input name="q" placeholder="${t('sources.q')}" autofocus>
      <button type="submit">${t('sources.find')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.cases = async () => {
  busy();
  const env = await callOp('cases.list', { limit: 100 });
  if (!env.ok) return failure(env);
  const rows = env.data.cases || [];
  setView(`
    <h2>${t('cases.title')} <button data-act="cases.build"
      title="${t('cases.build.why')}">🔄 ${t('cases.build')}</button></h2>
    ${renderWarnings(env)}
    <table><thead><tr>
      <th>шифра</th><th>назва</th><th class="num">${t('common.frames')}</th>
      <th>читання</th><th></th></tr></thead><tbody>
    ${rows.map((r) => `<tr>
      <td class="mono">${esc(r.shifra || r.key)}</td>
      <td>${esc((r.title || '').slice(0, 90))}</td>
      <td class="num">${esc(r.frames || 0)}</td>
      <td>${r.htr_stage && r.htr_stage !== 'none'
        ? `${t('cases.read')} ${esc(r.htr_pages_max || '')}`
        : `<span class="muted">${t('cases.none')}</span>`}</td>
      <td>${r.path
        ? `<button data-act="case.edit" data-arg="${esc(r.path)}"
             title="${t('case.edit')}">✏</button>`
        : `<span class="muted" title="${t('cases.nodir')}">—</span>`}</td>
    </tr>`).join('')}
    </tbody></table>`);
};

SCREENS.search = async () => {
  setView(`
    <h2>${t('nav.search')}</h2>
    <form class="row" data-act="search.run">
      <input name="q" placeholder="${t('search.q')}" autofocus>
      <select name="where">
        <option value="decode">${t('search.where.decode')}</option>
        <option value="pages">${t('search.where.pages')}</option>
        <option value="records">${t('search.where.records')}</option>
      </select>
      <button type="submit">${t('search.run')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.eye = async () => {
  setView(`
    <h2>${t('nav.eye')}</h2>
    <p class="muted">${t('eye.rule')}</p>
    <form class="row" data-act="eye.check">
      <input name="case" placeholder="${t('eye.case')}: DAHMO/315/8433" autofocus>
      <button type="submit">${t('eye.check')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.newcase = async () => {
  const sc = (EDIT && EDIT.sidecar) || {};
  const v = (k) => esc(sc[k] === null || sc[k] === undefined ? '' : sc[k]);
  const dir = EDIT ? esc(EDIT.case_dir) : '';
  setView(`
    <h2>${EDIT ? t('case.edit') : t('case.title')}</h2>
    <p class="muted">${t('case.why')}</p>
    ${EDIT ? `<div class="warn">${t('case.editing')} <b class="mono">${dir}</b>
       · ${esc(EDIT.scans)} ${t('common.frames')}<br>
       <span class="muted">${t('case.keep')}</span></div>` : ''}
    <form data-act="case.save">
      <div class="row"><input name="case_dir" placeholder="${t('case.dir')}"
        value="${dir}" ${EDIT ? '' : 'autofocus'}></div>
      <div class="row">
        <input name="shifra" placeholder="${t('case.shifra')}: ДАХмО 315-1-8433"
          value="${v('shifra')}">
        <input name="doc_type" placeholder="${t('case.type')}: метрична"
          value="${v('doc_type')}">
      </div>
      <div class="row"><input name="title" placeholder="${t('case.name')}"
        value="${v('title')}" ${EDIT ? 'autofocus' : ''}></div>
      <div class="row">
        <input name="place" placeholder="${t('case.place')}" value="${v('place')}">
        <input name="year_from" placeholder="${t('case.years')}: 1858" size="6"
          value="${v('year_from')}">
        <input name="year_to" placeholder="1860" size="6" value="${v('year_to')}">
      </div>
      <div class="row"><input name="note" placeholder="${t('case.note')}"
        value="${v('note')}"></div>
      <div class="row"><button type="submit">${t('case.save')}</button>
        ${EDIT ? `<button type="button" data-act="case.fresh">${t('case.fresh')}</button>`
          : ''}</div>
    </form>
    <div id="hits"></div>`);
  EDIT = null;
};

SCREENS.view = async () => {
  setView(`
    <h2>${t('nav.view')}</h2>
    <p class="muted">${t('view.eye')}</p>
    <form class="row" data-act="view.open">
      <input name="run" placeholder="${t('view.run')}" autofocus>
      <input name="page" placeholder="00003.JPG">
      <button type="submit">${t('view.open')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.read = async () => {
  setView(`
    <h2>${t('nav.read')}</h2>
    <form class="row" data-act="read.plan">
      <input name="case_dir" placeholder="${t('read.dir')}" autofocus>
      <select name="script">
        <option value="">${t('read.script')}: авто</option>
        <option value="cyrillic">кирилиця</option>
        <option value="latin">латинка</option>
      </select>
      <button type="submit">${t('read.plan')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.export = async () => {
  setView(`
    <h2>${t('nav.export')}</h2>
    <form class="row" data-act="export.run">
      <input name="case" placeholder="${t('export.case')}: DAHMO/315/8433" autofocus>
      <select name="what">
        <option value="records">${t('export.records')}</option>
        <option value="pages">${t('export.pages')}</option>
      </select>
      <button type="submit">${t('export.run')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.jobs = async () => {
  setView(`<h2>${t('jobs.title')}</h2><div id="jobs"></div>`);
  await refreshJobs();
};

// ── дії ──────────────────────────────────────────────────────────────────────
const ACTIONS = {
  nav: (_ev, elm) => show(elm.dataset.arg),

  'home.scans': () => {
    // Нативного вибору теки з браузера немає й не буде — тому кажемо прямо, а
    // не показуємо кнопку, яка нічого не робить.
    setView(`<h2>📁 ${t('home.have_scans')}</h2>
      <p>Вкажіть теку зі сканами командою:</p>
      <pre>nysh look &lt;шлях до теки&gt;</pre>
      <p class="muted">Браузер не має права зазирати у файли на диску, тож цей
      крок робиться з командного рядка. Далі все знову тут.</p>`);
  },

  'home.demo': async () => {
    busy();
    const env = await callOp('htr.env', {});
    setView(`<h2>▶ ${t('home.demo')}</h2>${renderWarnings(env)}
      <pre>${esc(JSON.stringify(env.data, null, 1))}</pre>`);
  },

  'sources.find': async (ev) => {
    ev.preventDefault();
    const q = new FormData(ev.target).get('q');
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.search', { q, limit: 40 });
    if (!env.ok) return failure(env);
    const { hits = [], coverage = {} } = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.source)}</td>
        <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}</span></td>
        <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
        <td>${h.acquirable
          ? `<button data-act="sources.get" data-source="${esc(h.source)}" data-ref="${esc(h.ref)}">${t('sources.get')}</button>`
          : ''}</td>
      </tr>`).join('')}</tbody></table>
      <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
  },

  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    if (!env.ok) return alert(env.error);
    show('jobs');
  },

  'search.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('search.run',
      { q: fd.get('q'), where: fd.get('where'), limit: 100 });
    if (!env.ok) return failure(env);
    const hits = env.data.hits || [];
    const cov = env.data.coverage || {};
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.case || h.name || '')}</td>
        <td class="mono">${esc(h.page || h.scan || '')}</td>
        <td>${esc((h.line || h.text || h.surname || '').slice(0, 120))}</td>
        <td class="num">${esc(h.score ?? '')}</td>
      </tr>`).join('')}</tbody></table>
      ${cov.runs !== undefined
        ? `<p class="muted">${t('search.coverage')}: ${cov.runs} прогонів, ${cov.pages} ${t('common.pages')}</p>`
        : ''}`;
  },

  // 🔴 Спершу ПЛАН, і лише окремою кнопкою — старт. Справа читається годинами;
  // дізнатись «модель не та» або «кадрів не 20, а 3000» після запуску означає
  // втратити ніч.
  'eye.check': async (ev) => {
    ev.preventDefault();
    EYE = { case: new FormData(ev.target).get('case') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('pages.status', EYE);
    if (!env.ok) return failure(env);
    const d = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p><b>${esc(d.shifra)}</b> ${esc(d.title || '')}</p>
      <p class="muted">${t('eye.disk')}: ${d.total_disk ?? 0} ·
         ${t('eye.noted')}: ${d.noted} ·
         ${t('eye.left')}: ${d.unnoted_count ?? '?'}</p>
      <h3>${t('eye.note')}</h3>
      <form data-act="eye.note">
        <div class="row">
          <input name="scan" placeholder="${t('eye.scan')}: 0030.JPG">
          <input name="page_type" placeholder="${t('eye.type')}: confession">
          <select name="status">
            <option value="full">full — виписано ВСІ прізвища</option>
            <option value="partial">partial — не всі</option>
            <option value="skipped">skipped — не читав</option>
            <option value="unreadable">unreadable — не читається</option>
          </select>
        </div>
        <div class="row"><input name="surnames" placeholder="${t('eye.surnames')}"></div>
        <div class="row">
          <input name="comment" placeholder="${t('eye.comment')}">
          <button type="submit">${t('eye.save')}</button>
        </div>
      </form>
      <div id="noted"></div>`;
  },

  'eye.note': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('pages.note', { ...EYE, ...fd });
    const box = el('noted');
    if (!env.ok) { box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    box.innerHTML = `<div class="warn">✅ ${esc(fd.scan)} занесено</div>`
      + renderWarnings(env);
    ev.target.reset();
  },

  'cases.build': async () => {
    const env = await callOp('cases.build', { rescan: true });
    if (!env.ok) return failure(env);
    // Робота йде у черзі — туди ж і ведемо: інакше кнопка виглядає як така,
    // що нічого не зробила, і її натискають ще раз.
    await show('jobs');
  },

  'case.edit': async (_ev, elm) => {
    const env = await callOp('case.show', { case_dir: elm.dataset.arg });
    if (!env.ok) return failure(env);
    EDIT = env.data;
    await show('newcase');
    if (env.warnings && env.warnings.length) {
      el('hits').innerHTML = renderWarnings(env);
    }
  },

  'case.fresh': async () => {
    EDIT = null;
    await show('newcase');
  },

  'case.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    for (const k of ['year_from', 'year_to']) fd[k] = fd[k] ? Number(fd[k]) : null;
    const env = await callOp('case.register', fd);
    if (!env.ok) {
      el('hits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return;
    }
    const sc = env.data.sidecar;
    el('hits').innerHTML = `${renderWarnings(env)}
      <div class="warn">✅ <b>${esc(sc.shifra)}</b> — ${esc(sc.title || 'без назви')}</div>`;
  },

  'view.open': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    VIEW = { run: fd.get('run'), page: fd.get('page') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('page.text', VIEW);
    if (!env.ok) return failure(env);
    const lines = (env.data.text || '').split('\n');
    const geo = env.data.lines || {};
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p class="muted">${lines.length} ${t('view.lines')}${geo.has ? '' : ' · без рамок'}</p>
      <div id="shot"></div>
      <table><tbody>${lines.map((ln, i) => `<tr>
        <td class="num mono">${i}</td>
        <td><button data-act="view.line" data-line="${i}">👁</button></td>
        <td>${esc(ln)}</td></tr>`).join('')}</tbody></table>`;
  },

  // 🔴 Рядок, а не сторінка. Вирізка легша в десятки разів (виміряно: 15 КБ
  // проти 1.1 МБ), а звірок за сеанс бувають десятки.
  'view.line': async (_ev, elm) => {
    if (!VIEW) return;
    const env = await callOp('page.view',
      { ...VIEW, line: Number(elm.dataset.line), region: 'line' });
    if (!env.ok) return alert(env.error);
    const d = env.data;
    el('shot').innerHTML = `
      ${renderWarnings(env)}
      <img src="${d.image}" alt="рядок ${d.line}" style="max-width:100%">
      <p class="muted mono">${esc(d.text || '')}</p>`;
    el('shot').scrollIntoView({ block: 'nearest' });
  },

  'read.plan': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    LAST_READ = { case_dir: fd.get('case_dir'), script: fd.get('script') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('read.plan', LAST_READ);
    if (!env.ok) return failure(env);
    const p = env.data.plan || {};
    el('hits').innerHTML = `
      <table><tbody>
        <tr><td>${t('read.frames')}</td><td class="num">${esc(p.frames)}</td></tr>
        <tr><td>${t('read.script')}</td><td>${esc(p.script)}</td></tr>
        <tr><td>${t('read.model')}</td><td class="mono">${esc(p.model)}</td></tr>
        ${p.voice ? `<tr><td>${t('read.voice')}</td><td class="mono">${esc(p.voice)}</td></tr>` : ''}
        <tr><td>→</td><td class="mono">${esc(p.out_dir)}</td></tr>
      </tbody></table>
      <button data-act="read.go">${t('read.go')}</button>`;
  },

  'read.go': async () => {
    if (!LAST_READ) return;
    const env = await callOp('read.start', LAST_READ);
    if (!env.ok) return alert(env.error);
    show('jobs');
  },

  'export.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('export.case',
      { case: fd.get('case'), what: fd.get('what') });
    if (!env.ok) return failure(env);
    const { columns = [], rows = [] } = env.data;
    LAST_EXPORT = { columns, rows, name: env.data.shifra || env.data.case };
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${rows.length ? `<button data-act="export.csv">${t('export.csv')}</button>` : ''}
      <table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${rows.slice(0, 200).map((r) => `<tr>${columns.map(
        (c) => `<td>${esc(String(r[c] ?? '').slice(0, 80))}</td>`).join('')}</tr>`).join('')}
      </tbody></table>
      <p class="muted">${rows.length} рядків</p>`;
  },

  // 🔴 CSV збирається на клієнті й зберігається діалогом браузера. Писати файл
  // кудись «у простір» тут не можна: людина вивантажує, щоб віднести дані в
  // ЧУЖУ програму, і мусить сама сказати куди.
  'export.csv': () => {
    if (!LAST_EXPORT) return;
    const { columns, rows, name } = LAST_EXPORT;
    const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [columns.join(','), ...rows.map(
      (r) => columns.map((c) => cell(r[c])).join(','))].join('\r\n');
    // BOM — щоб Excel не з''їв кирилицю: без нього виписка відкривається
    // «крякозябрами», і виглядає це як зіпсовані дані, а не як кодування.
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${String(name).replace(/[^\w.-]+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  },

  'jobs.cancel': async (_ev, elm) => {
    await fetch(`/api/jobs/${encodeURIComponent(elm.dataset.job)}/cancel`,
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    await refreshJobs();
  },

  'lang.toggle': () => {
    LANG = LANG === 'uk' ? 'en' : 'uk';
    localStorage.setItem('nysh.lang', LANG);
    location.reload();
  },
};

// Одна точка входу на всі кліки й сабміти. `data-act` — єдиний спосіб повісити
// поведінку; інлайн-onclick у розмітці немає ніде.
function dispatch(ev) {
  const elm = ev.target.closest('[data-act]');
  if (!elm) return;
  const name = elm.dataset.act;
  const fn = ACTIONS[name];
  if (!fn) {
    // 🔴 Гучно. Мовчазний «нічого не сталось» — це та сама вада, що й колізія
    // глобалів: кнопка є, натискається, і не робить нічого.
    console.error(`невідома дія: ${name}`);
    alert(`невідома дія: ${name}`);
    return;
  }
  fn(ev, elm);
}
document.addEventListener('click', dispatch);
document.addEventListener('submit', dispatch);

// ── навігація ────────────────────────────────────────────────────────────────
async function show(screen) {
  const fn = SCREENS[screen] || SCREENS.home;
  document.querySelectorAll('nav button').forEach((b) => {
    b.classList.toggle('on', b.dataset.arg === screen);
  });
  location.hash = screen;
  await fn();
}

// ── черга ────────────────────────────────────────────────────────────────────
let cursor = 0;

async function refreshJobs() {
  const res = await fetch(`/api/jobs?since=${cursor}`);
  const data = await res.json();
  cursor = data.seq;
  const box = el('jobs');
  if (!box) return;
  const jobs = (data.jobs || []).filter((j) => j.state !== 'done' || Date.now() / 1000 - j.updated < 300);
  box.innerHTML = jobs.length ? jobs.map((j) => `
    <div class="job">
      <b>${esc(j.title || j.kind)}</b> <span class="muted">${esc(j.state)}</span>
      <progress value="${j.progress.i}" max="${j.progress.n || 1}"></progress>
      <span class="mono">${j.progress.i}/${j.progress.n} ${esc(j.progress.basis)}</span>
      ${j.error ? `<div class="warn err">${esc(j.error)}</div>` : ''}
      ${j.state === 'running' || j.state === 'queued'
        ? `<button data-act="jobs.cancel" data-job="${esc(j.id)}">${t('jobs.cancel')}</button>` : ''}
    </div>`).join('') : `<p class="muted">${t('jobs.none')}</p>`;
}

/** Довге очікування на СЕРВЕРІ: одне з'єднання замість опитувань щосекунди. */
async function watchJobs() {
  for (;;) {
    try {
      const res = await fetch(`/api/jobs/wait?since=${cursor}&timeout_s=25`);
      const data = await res.json();
      cursor = data.seq;
      if (el('jobs')) await refreshJobs();
      const running = (data.jobs || []).filter((j) => j.state === 'running' || j.state === 'queued');
      el('jobcount').textContent = running.length ? String(running.length) : '';
    } catch {
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

// ── старт ────────────────────────────────────────────────────────────────────
function boot() {
  document.querySelectorAll('[data-i18n]').forEach((n) => {
    n.textContent = t(n.dataset.i18n);
  });
  show((location.hash || '#home').slice(1));
  watchJobs();
}
boot();
