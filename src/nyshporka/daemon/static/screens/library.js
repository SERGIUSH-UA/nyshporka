/**
 * 📚 Бібліотека справ — що взагалі є на руках і що з цим уже зроблено.
 *
 * Відповідає на питання, якого не закриває «Мої справи»: там ідеться про взяте
 * під облік у цьому просторі, тут — про весь матеріал разом із шарами роботи
 * над ним і рішеннями ока.
 *
 * 🔴 Порожня бібліотека і незібрана бібліотека показуються по-різному. «0
 * справ» читається як факт («шукати нема де»), і людина закриває напрям,
 * якого ніхто не відкривав; тому незібране каже про себе прямо й дає кнопку.
 *
 * 🔴🔴 Те саме правило вдруге, на шар глибше: колонка «обробка» показує «?»,
 * коли реєстру немає, і «—» лише тоді, коли перевірили й нічого немає.
 * Сплутати їх означає видати «зрізу не збирали» за «жодну справу не читали».
 */
import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, renderWarnings,
  curGen, alive, hasAlerts } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';
import { loadProjects, currentPid, projectInfo, projectChips, projectsNow } from '../core/projects.js';

/** Діючий фільтр. Живе між входами на екран: повернувшись, людина бачить своє. */
let LIB = {
  q: '', key: '', repo: '', record_type: '', uezd: '', htr: '', fuzzy: '',
  status: '', verdict: '', curated: false, on_disk: null, page: 0,
  // «Прошукано для роду цього проєкту»: '' · 'here' · 'todo' (прочитані, ще не).
  searched: '',
};

/**
 * Лічильник запитів бібліотеки.
 *
 * ⚠ Захист від обігнаної відповіді: фільтр набирають швидко, запити летять
 * підряд, і повільніший ранній може прийти після свіжого — на екрані лишиться
 * видача, що не відповідає полю. Не падає, не помиляється видимо, і саме тому
 * дорого: людина вирішує по тому, що бачить.
 */
let _libSeq = 0;

/** Фасети малюються раз на вхід: їхні числа не залежать від фільтра. */
let _libFacets = false;

/** Рядки поточної сторінки за ключем — з них розгортаються деталі (`lib.more`). */
let LIB_ROWS = new Map();

/** Скільки сторінок під поточним фільтром — щоб «далі» не везла за край. */
let LIB_PAGES = 1;

SCREENS.library = async () => {
  _libFacets = false;
  // 🔴 Засів із реєстру опису чи газетира — точним ключем, а не пошуком за
  // шифрою. Приблизний пошук відкривав би сусідні справи того самого фонду з
  // тим самим виглядом правильної відповіді.
  const seed = ST.library;
  if (seed) {
    LIB = { ...LIB, key: seed.key || '', q: '', page: 0 };
    ST.library = null;                  // засів одноразовий
  }
  busy();
  await libLoad(true);
};

/**
 * @param {boolean} full  перемалювати весь екран (вхід) чи лише видачу (фільтр).
 *
 * 🔴 Фільтр оновлює тільки таблицю. Перемальовуючи весь екран, ми щоразу
 * знищували б поле пошуку разом із фокусом і кареткою — і символи, набрані
 * після паузи в 250 мс, ішли б у нікуди. Виглядає це як «клавіатура
 * загубилась», а не як помилка.
 */
async function libLoad(full = false) {
  const seq = ++_libSeq;
  const gen = curGen();
  await loadProjects();
  const env = await callOp('library.list', {
    q: LIB.q, key: LIB.key, repo: LIB.repo, record_type: LIB.record_type,
    uezd: LIB.uezd,
    htr: LIB.htr, fuzzy: LIB.fuzzy, status: LIB.status, verdict: LIB.verdict,
    curated: LIB.curated, page: LIB.page,
    ...(LIB.on_disk === null ? {} : { on_disk: LIB.on_disk }),
    ...libSearchedArgs(),
  });
  if (seq !== _libSeq) return;          // нас уже обігнав свіжіший запит
  if (!alive(gen)) return;              // з бібліотеки вже пішли
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const rows = d.cases || [];
  const layers = (d.summary || {}).has_layers;
  LIB_PAGES = d.pages || 1;
  LIB_ROWS = new Map(rows.map((r) => [r.key, r]));

  if (!full) {
    // Каркас на місці — міняється лише вміст. `swapHtml` тримає висоту
    // контейнера на час підміни, тож сторінка під таблицею не підстрибує.
    const body = el('lib-rows');
    if (body) swapHtml(body, rows.map((r) => libRow(r, layers)).join(''));
    const n = el('lib-count');
    if (n) n.innerHTML = libCount(d);
    const warn = el('lib-warn');
    if (warn) warn.innerHTML = libKeyChip() + renderWarnings(env);
    const scope = el('lib-scope');
    if (scope) scope.innerHTML = libScopeButtons();
    // Локальна змінна не зветься `pager`: під цим іменем уже стоїть спільна
    // смуга, і тінь мовчки перетворила б виклик на звертання до вузла DOM.
    const pg = el('lib-pager');
    if (pg) pg.innerHTML = pager(d);
    return;
  }

  const head = `
    <p class="muted">${t('lib.why')}</p>`;

  if (!d.built) {
    setView(`${head}${renderWarnings(env)}
      <div class="warn">${t('lib.unbuilt')}
        <button data-act="cases.build">${t('lib.build')}</button></div>`);
    return;
  }

  setView(`${head}
    ${libSummary(d.summary || {})}
    <div class="row">
      <input id="lib-q" type="search" placeholder="${esc(t('lib.q'))}"
             value="${esc(LIB.q)}" data-act="lib.filter" data-live="1"
             title="${esc(t('lib.q.why'))}">
      ${libFacetSelects(d)}
    </div>
    <details class="more-filters"${libMoreActive() ? ' open' : ''}>
      <summary>${t('lib.more')}</summary>
      <div class="row">
      ${libStageSelects(d)}
      <label class="lbl-mini"><input type="checkbox" id="lib-disk"
        data-act="lib.filter"${LIB.on_disk ? ' checked' : ''}> ${t('lib.ondisk')}</label>
      <label class="lbl-mini"><input type="checkbox" id="lib-curated"
        data-act="lib.filter"${LIB.curated ? ' checked' : ''}> ${t('lib.curated')}</label>
      </div>
    </details>
    ${currentPid() ? `<div class="dash-pick lib-scope" id="lib-scope" role="group">${libScopeButtons()}</div>` : ''}
    <div id="lib-warn">${libKeyChip()}${renderWarnings(env)}</div>
    <p class="muted" id="lib-count">${libCount(d)}</p>
    <div class="tbl-wide"><table class="lib-tbl"><thead><tr>
      <th>${t('lib.col.shifra')}</th><th>${t('lib.col.title')}</th>
      <th class="num">${t('lib.col.years')}</th><th>${t('lib.col.place')}</th>
      <th class="num">${t('common.frames')}</th>
      <th title="${esc(t('lib.col.work.why'))}">${t('lib.col.work')}</th>
      <th title="${esc(t('lib.col.srch.why'))}">${esc(libSearchedHead())}</th>
      ${isHub() ? '' : `<th>${t('lib.col.verdict')}</th>`}<th></th></tr></thead>
    <tbody id="lib-rows">${rows.map((r) => libRow(r, layers)).join('')
      || skelRows(6, cols())}</tbody></table></div>
    <div id="lib-pager">${pager(d)}</div>`);
  _libFacets = true;
}

/**
 * Чи вибрано щось у другому ряду фільтрів.
 *
 * Другий ряд (стани обробки, вердикт, «на диску», «відібрані») згорнуто: два
 * ряди з восьми полів стояли над таблицею постійно. Але вибраний фільтр не
 * ховається ніколи — інакше видача звужена, а чим, не видно.
 */
function libMoreActive() {
  return Boolean(LIB.htr || LIB.fuzzy || LIB.status || LIB.verdict
    || LIB.curated || LIB.on_disk);
}

/**
 * Смуга зведення: скільки чого й де робота.
 *
 * 🔴 Числа шарів показуються лише коли реєстр зібрано. «0 без декоду»
 * читається як досягнення, а означало б, що зрізу не збирали — і саме на цьому
 * рядку людина вирішує, що читати далі.
 */
function libSummary(s) {
  const bits = [
    // Справи, а не теки: одна справа буває кількома теками (фрагменти плівки).
    `${ic('books', 'ic-sm')} ${esc(s.all ?? 0)} ${t('lib.sum.all')}${
      s.folders > s.all ? ` <span class="dim">(${esc(s.folders)} ${t('lib.sum.folders')})</span>` : ''}`,
    s.on_disk != null ? `${ic('disk', 'ic-sm')} ${esc(s.on_disk)} ${t('lib.sum.disk')}` : '',
    s.offloaded ? `<span title="${esc(t('lib.noframes'))}">${esc(s.offloaded)} ${
      t('lib.sum.offloaded')}</span>` : '',
  ];
  if (s.has_layers) {
    bits.push(
      `${ic('quill', 'ic-sm')} ${esc(s.no_htr)} ${t('lib.sum.nohtr')}`,
      `${ic('search', 'ic-sm')} ${esc(s.no_fuzzy)} ${t('lib.sum.nofuzzy')}`,
      s.hits_open ? `${ic('eye', 'ic-sm')} ${esc(s.hits_open)} ${t('lib.sum.open')}` : '');
  } else {
    bits.push(`<span class="dim">${t('lib.sum.nolayers')}</span>`);
  }
  if (s.no_clan) bits.push(`${ic('x-circle', 'ic-sm')} ${esc(s.no_clan)} ${t('lib.sum.noclan')}`);
  return `<p class="lib-sum">${bits.filter(Boolean).join(' · ')}</p>`;
}

/**
 * Підпис типу запису. Словник типів сторінок уже є — беремо звідти; коду, для
 * якого перекладу немає, показуємо сам код, а не службовий ключ: людина
 * прочитає «revision» як тип, а `ptype.revision` — як поламаний застосунок.
 */
function _rtype(code) {
  const got = t(`ptype.${code}`);
  return got.startsWith('ptype.') ? code : got;
}

function _opt(v, label, cur) {
  return `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
}

/**
 * 🔴 Фасети беруться з усієї бібліотеки, а не з видачі. Зібрані з
 * відфільтрованого, вони схлопуються до одного пункту після першого ж вибору:
 * решта архівів зникає зі списку, і повернутись до них нема чим — екран
 * починає брехати про діючий фільтр.
 */
function libFacetSelects(d) {
  const f = d.facets || {};
  const n = (x) => (x.n ? ` (${x.n})` : '');
  return `
    <select id="lib-repo" data-act="lib.filter">
      ${_opt('', t('lib.repo.any'), LIB.repo)}
      ${(f.repos || []).map((x) => _opt(x.code, x.code + n(x), LIB.repo)).join('')}
    </select>
    <select id="lib-rtype" data-act="lib.filter">
      ${_opt('', t('lib.rtype.any'), LIB.record_type)}
      ${(f.record_types || []).map((x) =>
        _opt(x.code, _rtype(x.code) + n(x), LIB.record_type)).join('')}
    </select>
    <select id="lib-uezd" data-act="lib.filter">
      ${_opt('', t('lib.uezd.any'), LIB.uezd)}
      ${(f.uezds || []).slice(0, 40).map((x) =>
        _opt(x.code, x.code + n(x), LIB.uezd)).join('')}
    </select>`;
}

function libStageSelects(d) {
  const kinds = d.kinds || {};
  return `
    <select id="lib-htr" data-act="lib.filter" title="${esc(t('lib.htr.why'))}">
      ${_opt('', t('lib.htr.all'), LIB.htr)}
      ${_opt('none', t('lib.htr.none'), LIB.htr)}
      ${_opt('any', t('lib.htr.any'), LIB.htr)}
      ${_opt('partial', t('lib.htr.partial'), LIB.htr)}
      ${_opt('both', t('lib.htr.both'), LIB.htr)}
    </select>
    <select id="lib-fuzzy" data-act="lib.filter">
      ${_opt('', t('lib.fuzzy.all'), LIB.fuzzy)}
      ${_opt('none', t('lib.fuzzy.none'), LIB.fuzzy)}
      ${_opt('any', t('lib.fuzzy.any'), LIB.fuzzy)}
      ${_opt('reviewed', t('lib.fuzzy.reviewed'), LIB.fuzzy)}
    </select>
    <select id="lib-status" data-act="lib.filter" title="${esc(t('lib.status.why'))}">
      ${_opt('', t('lib.status.all'), LIB.status)}
      ${_opt('todo', t('lib.status.todo'), LIB.status)}
      ${_opt('unread', t('lib.status.unread'), LIB.status)}
      ${_opt('read', t('lib.status.read'), LIB.status)}
      ${_opt('missing', t('lib.status.missing'), LIB.status)}
    </select>
    <select id="lib-verdict" data-act="lib.filter">
      ${_opt('', t('lib.verdict.all'), LIB.verdict)}
      ${_opt('any', t('lib.verdict.any'), LIB.verdict)}
      ${_opt('none', t('lib.verdict.none'), LIB.verdict)}
      ${Object.keys(kinds).map((k) =>
        _opt(k, t(`lib.verdict.${k}`), LIB.verdict)).join('')}
    </select>
`;
}

/** Ім'я проєкту вкладки для підписів «для «X»». */
function _pname() {
  const p = projectInfo(currentPid());
  return p ? (p.name || p.id) : currentPid();
}

/**
 * Зріз роду — перемикачем над таблицею, лише в проєкті: у Майстерні роду немає,
 * і сервер на нього відмовляє (`library.list searched`).
 *
 * 🔴 За замовчуванням — усі справи: вони спільні, а робота дослідника — знайти
 * ще не прошукане; звуження за замовчуванням сховало б саме такі (рішення
 * перекрою консолі 22.10.2026).
 */
function libScopeButtons() {
  const p = _pname();
  const b = (v, label) => `<button type="button" class="${LIB.searched === v ? 'on' : ''}" data-act="lib.scope"`
    + ` data-arg="${v}" aria-pressed="${LIB.searched === v}">${esc(label)}</button>`;
  return b('', t('lib.scope.all')) + b('todo', t('lib.srch.todo').replace('{p}', p))
    + b('here', t('lib.srch.here').replace('{p}', p));
}

/** Сама Майстерня без проєкту: вердиктів (вони проєктні) тут немає. */
function isHub() {
  const d = projectsNow();
  return !!(d && d.hub_only && !currentPid());
}

/** Скільки колонок у таблиці — для розгорнутого рядка й скелета. */
const cols = () => (isHub() ? 8 : 9);

/**
 * «Прочитані, не прошукані» — це два фільтри: прошукане й хоч якийсь декод.
 * Без другого в «непрошукане» потрапляло б і те, у чому шукати ще нічого.
 */
function libSearchedArgs() {
  if (!LIB.searched || !currentPid()) return {};
  if (LIB.searched === 'here') return { searched: 'here' };
  return { searched: 'not_here', ...(LIB.htr ? {} : { htr: 'any' }) };
}

function libSearchedHead() {
  return currentPid() ? t('lib.col.srch.here').replace('{p}', _pname()) : t('lib.col.srch.all');
}

/**
 * Колонка «прошукано»: у проєкті — чи шукав цей рід (і хто ще), у Майстерні —
 * які проєкти шукали.
 *
 * 🔴 «Ні» — лише для прочитаної справи. У непрочитаній шукати нема в чому, і
 * жовте «ні» там читалось би як недогляд, а не як «спершу прочитати».
 */
function libSearched(r) {
  const by = r.searched_by || {};
  const mine = currentPid();
  const others = Object.keys(by).filter((p) => p !== mine);
  const chips = projectChips(others);
  if (!mine) return chips || '<span class="dim">—</span>';
  const read = (r.htr_stage || 'none') !== 'none';
  const day = String(by[mine] || '').slice(0, 10);
  const here = by[mine]
    ? `<span class="pill ok" title="${esc(day)}">${esc(t('lib.srch.yes'))}</span>`
    : (read ? `<span class="pill warn">${esc(t('lib.srch.no'))}</span>` : '<span class="dim">—</span>');
  return chips ? `${here} <span class="dim">${esc(t('lib.srch.also'))}</span> ${chips}` : here;
}

/** 🔴 Знаменник поруч із видачею: скільки показано, з чого й із чого всього. */
function libKeyChip() {
  if (!LIB.key) return '';
  // 🔴 Звуження до однієї справи мусить бути видним. Мовчазний точковий фільтр
  // читається як «у бібліотеці одна справа» — тобто як відповідь про весь
  // простір, а не про один рядок опису.
  return `<div class="warn next">
    <button data-act="lib.all">${t('lib.key.all')}</button>
    <span>${t('lib.key.one')} <b class="mono">${esc(LIB.key)}</b></span></div>`;
}

function libCount(d) {
  return esc(t('lib.count').replace('{n}', d.shown ?? 0)
    .replace('{total}', d.total ?? 0)) +
    (d.library_total && d.library_total !== d.total
      ? ` <span class="dim">${esc(t('lib.of').replace('{all}', d.library_total))}</span>`
      : '');
}



/**
 * Колонка «обробка» — три шари в одній клітинці.
 *
 * 🔴 `?` і `—` означають різне. `?` — реєстру немає, сказати нічого;
 * `—` — перевірили, нічого немає. Сплутати їх означає видати «зрізу не
 * збирали» за «жодну справу не читали», і саме на цьому числі вирішують, що
 * гнати наступним.
 */
function libWork(r, layers) {
  if (!layers) {
    return `<span class="dim" title="${esc(t('lib.work.noindex'))}">?</span>`;
  }
  const bits = [];
  const stage = r.htr_stage || 'none';
  if (stage === 'none') {
    bits.push('<span class="dim">—</span>');
  } else {
    // Бейдж рушія, а не літера власного винаходу: колір, форма й літера — три
    // ознаки, і кожна працює сама (скріншот, чорно-білий друк, дальтонізм).
    const ids = { pysar: ['pysar'], diak: ['diak'], skryba: ['skryba'],
                  both: ['pysar', 'diak'] }[stage] || [];
    bits.push(ids.length ? ids.map((x) => eng(x)).join('') : '◐');
    if (r.htr_coverage != null && r.htr_coverage < 1) {
      bits.push(`<span class="dim">${Math.round(r.htr_coverage * 100)}%</span>`);
    }
  }
  const fz = r.fuzzy_stage || 'none';
  if (fz !== 'none') {
    const open = Math.max((r.fuzzy_hits || 0) - (r.fuzzy_reviewed || 0), 0);
    bits.push(`<span title="${esc(t(`lib.fuzzy.${fz}`))}">${
      ic(fz === 'reviewed' ? 'flag' : 'search', 'ic-sm')}</span>${
      open ? `<b class="open">${open}</b>` : ''}`);
  }
  if (r.canon_facts) {
    bits.push(`<span title="${esc(t('lib.work.canon'))}">${ic('book-open', 'ic-sm')}${
      esc(r.canon_facts)}</span>`);
  }
  if (r.pages_noted) {
    bits.push(`<span title="${esc(t('lib.work.noted'))}">${ic('note', 'ic-sm')}${
      esc(r.pages_noted)}</span>`);
  }
  return bits.join(' ');
}

function libRow(r, layers) {
  const years = [r.year_from, r.year_to].filter(Boolean).join('–');
  const disk = r.on_disk
    ? `<span title="${esc(t('lib.disk'))}">${ic('disk', 'ic-sm')}</span>`
    : `<span class="muted" title="${esc(t('lib.nodisk'))}">—</span>`;
  const v = r.verdict
    ? `<span class="badge ${r.verdict === 'clan_found' ? 'known' : ''}"
         title="${esc(r.verdict_note || '')}">${esc(t(`lib.verdict.${r.verdict}`))}</span>`
    : '';
  return `<tr class="lib-row" data-act="lib.more" data-arg="${esc(r.key)}">
    <td class="mono">${disk} ${esc(r.shifra || r.key || '')}</td>
    <td class="lib-title">${esc((r.title || '').slice(0, 80))}</td>
    <td class="num" data-l="${esc(t('lib.col.years'))}">${esc(years)}</td>
    <td data-l="${esc(t('lib.col.place'))}">${esc((r.place || '').slice(0, 30))}</td>
    <td class="num" data-l="${esc(t('common.frames'))}">${r.frames ? esc(r.frames)
    : `<span class="dim" title="${esc(t('lib.noframes'))}">${
      r.state === 'archived' ? t('lib.offloaded') : '—'}</span>`}</td>
    <td class="work" data-l="${esc(t('lib.col.work'))}">${libWork(r, layers)}</td>
    <td data-l="${esc(t('lib.col.srch.short'))}">${libSearched(r)}</td>
    ${isHub() ? '' : `<td>${v}</td>`}
    <td class="acts">${libPrimary(r)}<button class="ctl-sm lib-dots" data-act="lib.more"
      data-arg="${esc(r.key)}" title="${esc(t('lib.acts'))}" aria-label="${esc(t('lib.acts'))}">⋯</button></td>
  </tr>`;
}

/**
 * Головна дія рядка — одна, підписана, за станом справи: непрочитану читати,
 * прочитану й не прошукану для роду — шукати, решту — дивитись аркуші. Решта
 * дій — у «⋯» (розгорнутий рядок, з підписами).
 *
 * 🔴 Доти в рядку стояли шість дрібних значків, чий зміст видно лише в
 * підказці — тобто ніде на телефоні (оцінка консолі 22.10.2026).
 */
function libPrimary(r) {
  const read = (r.htr_stage || 'none') !== 'none';
  const mine = currentPid();
  const btn = (act, arg, icon, label) => `<button class="ctl-sm" ${act} data-arg="${
    esc(arg)}">${ic(icon, 'ic-sm')} ${esc(label)}</button>`;
  if (r.path && !read) return btn('data-act="lib.read"', r.path, 'quill', t('lib.btn.read'));
  if (read && !(mine && (r.searched_by || {})[mine])) return btn('data-act="lib.find"', r.key, 'search', t('lib.btn.find'));
  if (r.path) return btn('data-act="lib.frames"', r.path, 'image', t('lib.btn.frames'));
  return '';
}

/**
 * Деталі справи під її рядком: повна назва, тека й ті самі дії — з підписами.
 *
 * 🔴 Доти клік по рядку не робив нічого, а дії стояли шістьма значками, чий
 * зміст видно лише в підказці при наведенні — тобто ніде на телефоні
 * (холодний прохід 07.10.2026: «прочитати» знайшлось лише в підказці). Значки
 * в рядку лишаються для тих, хто їх знає; тут — те саме словами.
 */
function libMore(r) {
  const btn = (act, arg, label) => `<button class="ctl-sm" ${act}
    data-arg="${esc(arg)}">${label}</button>`;
  const years = [r.year_from, r.year_to].filter(Boolean).join('–');
  return `<tr class="lib-more"><td colspan="${cols()}">
    <p><b>${esc(r.title || r.shifra || r.key || '')}</b>
      ${years ? `<span class="muted"> · ${esc(years)}</span>` : ''}
      ${r.place ? `<span class="muted"> · ${esc(r.place)}</span>` : ''}</p>
    <p class="muted mono">${esc(r.key || '')}${r.path ? ` · ${esc(r.path)}` : ''}</p>
    ${r.verdict_note ? `<p class="muted">${esc(r.verdict_note)}</p>` : ''}
    <p class="row-actions">
      ${r.path ? btn('data-act="lib.frames"', r.path, `${ic('image', 'ic-sm')} ${t('lib.btn.frames')}`) : ''}
      ${r.path ? btn('data-act="lib.read"', r.path, `${ic('quill', 'ic-sm')} ${t('lib.btn.read')}`) : ''}
      ${btn('data-act="lib.runs"', r.key, `${ic('list', 'ic-sm')} ${t('lib.btn.runs')}`)}
      ${btn('data-act="lib.find"', r.key, `${ic('search', 'ic-sm')} ${t('lib.btn.find')}`)}
      ${r.fond ? btn('data-act="lib.opys"', r.key, `${ic('archive-box', 'ic-sm')} ${t('lib.btn.opys')}`) : ''}
      ${isHub() ? '' : btn('data-act="lib.verdict"', r.key, `${ic('pencil-line', 'ic-sm')} ${t('lib.btn.verdict')}`)}
      ${r.path ? btn('data-act="case.edit"', r.path, `${ic('page', 'ic-sm')} ${t('lib.btn.describe')}`) : ''}
    </p></td></tr>`;
}

/**
 * Форма рішення по справі.
 *
 * 🔴 Поле «скільки аркушів переглянуто» стоїть поруч із «роду немає», а не в
 * примітці: нуль без знаменника не результат, і саме цей вердикт наступного
 * разу закриє напрям. Порожнім лишити можна — вердикт виносить людина, і
 * машина не має права не пустити її рішення, — але мовчки це не проходить.
 */
function libVerdictForm(key) {
  // Форма відкривається з наявним рішенням: порожня форма й «Зберегти» мовчки
  // знімали вердикт, який людина ставила раніше (прохід консолі 22.10.2026).
  const r = LIB_ROWS.get(key) || {};
  const opt = (v, label) => `<option value="${v}"${(r.verdict || '') === v ? ' selected' : ''}>${esc(label)}</option>`;
  setView(`<h2>${esc(key)}</h2>
    <div class="row"><select id="lv-kind">
      ${opt('', t(r.verdict ? 'lib.verdict.clear' : 'lib.verdict.pick'))}
      ${opt('no_clan', t('lib.verdict.no_clan'))}
      ${opt('clan_found', t('lib.verdict.clan_found'))}
      ${opt('recheck', t('lib.verdict.recheck'))}
    </select></div>
    <div class="row"><label class="fld"><span class="fld-l">${esc(t('lib.pages'))}</span>
      <input id="lv-pages" type="number" min="0"
      value="${r.verdict_pages ? esc(String(r.verdict_pages)) : ''}"
      placeholder="0"></label></div>
    <p class="muted">${t('lib.pages.why')}</p>
    <p class="consequence">${esc(t('lib.verdict.lands').replace('{p}', _pname()))}</p>
    <div class="row"><label class="fld"><span class="fld-l">${esc(t('lib.note'))}</span>
      <input id="lv-note" value="${esc(r.verdict_note || '')}"></label></div>
    <button data-act="lib.verdict.save" data-arg="${esc(key)}">${t('lib.save')}</button>
    <button data-act="nav" data-arg="library">${t('lib.cancel')}</button>`);
}

PAGERS.library = (delta) => {
  LIB = { ...LIB, page: step(LIB.page, delta, LIB_PAGES) };
  return libLoad(false);
};

Object.assign(ACTIONS, {
  /** Зняти точковий засів і показати бібліотеку цілком. */
  'lib.all': () => {
    LIB = { ...LIB, key: '', page: 0 };
    return libLoad(true);
  },

  /** Фільтр бібліотеки. Читає всі поля одразу: інакше зміна одного скидала б
      інші до дефолтів, і видача не відповідала б тому, що видно на екрані. */
  'lib.filter': () => {
    const val = (id) => (el(id) || {}).value || '';
    LIB = {
      ...LIB,
      // 🔴 Будь-яка правка фільтра знімає точковий засів. Інакше людина
      // крутить фільтри над однією справою й бачить порожньо — тобто
      // бібліотека виглядає порожньою, будучи повною.
      key: '',
      q: val('lib-q'),
      repo: val('lib-repo'),
      record_type: val('lib-rtype'),
      uezd: val('lib-uezd'),
      htr: val('lib-htr'),
      fuzzy: val('lib-fuzzy'),
      status: val('lib-status'),
      verdict: val('lib-verdict'),
      curated: !!(el('lib-curated') || {}).checked,
      on_disk: (el('lib-disk') || {}).checked ? true : null,
      // Зріз роду — перемикач над таблицею, не поле форми: лишається, яким був.
      searched: LIB.searched,
      // 🔴 Будь-яка зміна фільтра повертає на першу сторінку: лишившись на
      // сьомій, людина побачила б порожньо й вирішила, що нічого не знайшлось.
      page: 0,
    };
    return libLoad(false);
  },


  'lib.verdict': (_ev, elm) => libVerdictForm(elm.dataset.arg),

  /** Розгорнути чи згорнути деталі справи під її рядком. */
  /** Зріз роду: усі · прочитані й не прошукані · прошукані. */
  'lib.scope': (_ev, elm) => {
    LIB = { ...LIB, searched: elm.dataset.arg || '', key: '', page: 0 };
    return libLoad(false);
  },

  'lib.more': (_ev, btn) => {
    // Клік по рядку чи по «⋯» у ньому — деталі під цим самим рядком.
    const elm = (btn.closest && btn.closest('tr')) || btn;
    const next = elm.nextElementSibling;
    if (next && next.classList && next.classList.contains('lib-more')) {
      next.remove();
      return undefined;
    }
    const r = LIB_ROWS.get(btn.dataset.arg);
    if (r) elm.insertAdjacentHTML('afterend', libMore(r));
    return undefined;
  },

  'lib.verdict.save': async (_ev, elm) => {
    const kind = (el('lv-kind') || {}).value || '';
    const pages = Number((el('lv-pages') || {}).value || 0) || null;
    const env = await callOp('library.verdict', {
      key: elm.dataset.arg, verdict: kind,
      note: (el('lv-note') || {}).value || '',
      ...(pages ? { pages } : {}),
    });
    // 🔴 Відмова лишається В ФОРМІ, а не замінює екран. `failure()` робить
    // `setView`, тобто зносить `main#view` разом із набраним «Чим доведено» й
    // числом переглянутих аркушів — а половина відмов тут рівня описки, тобто
    // саме після них форма й потрібна. Правило описане в `core/view.js`, і
    // порушувалось воно у файлі, який на нього посилається.
    if (!env.ok) return boxError('lv-hits', env);
    // Застереження про нуль без знаменника мусить дійти до людини, а не
    // зникнути разом з екраном форми.
    // ⚠ Не `alert()`: модалка браузера зникає з першим натисканням і не
    // лишає слідів, а тут їде знаменник — «прочесано 400 з 1142». Його
    // перечитують, а не проклацують.
    // 🔴 Успіх лишається успіхом, навіть коли має що сказати. Доти гілка з
    // застереженням показувала САМІ застереження — без ✅ і без повернення в
    // перелік, — тож форма стояла озброєна, і друге натискання надсилало
    // вердикт удруге. А без `lv-hits` поведінка ще й розходилась залежно від
    // стану DOM.
    const box = el('lv-hits');
    // Панель підтвердження — лише на тривогу: примітка не варта того, щоб
    // зупиняти людину посеред переліку.
    if (box && hasAlerts(env)) {
      box.innerHTML = `<div class="warn">✅ ${esc(elm.dataset.arg)}</div>`
        + renderWarnings(env)
        + `<p><button data-act="nav" data-arg="library">${t('lib.cancel')}</button></p>`;
      return undefined;
    }
    return show('library');
  },

  /**
   * 🖼 Просто подивитись на аркуші — без прогону й без декоду.
   *
   * 🔴 Найчастіша дія над справою, і найдовше її не було: щоб глянути на
   * завантажене, доводилось спершу прочитати справу рушієм. Тому кнопка стоїть
   * першою в рядку — перед читанням, а не після нього.
   */
  'lib.frames': (_ev, elm) => {
    ST.frames = { case: elm.dataset.arg };
    return show('frames');
  },

  /** 🖋 Читати цю справу: тека підставляється, набирати шлях не треба. */
  'lib.read': (_ev, elm) => {
    ST.read = { case_dir: elm.dataset.arg };
    return show('read');
  },

  /** 📜 Прогони цієї справи. */
  'lib.runs': (_ev, elm) => {
    ST.runsFocus = elm.dataset.arg;
    return show('runs');
  },

  /**
   * 🏛 Ця сама справа в реєстрі опису.
   *
   * 🔴 Зворотний бік межі: бібліотека каже «в мене є», опис — «в архіві існує».
   * Без цього переходу друге питання доводилось ставити руками, набираючи
   * фонд і номер у формі, — а саме там і губиться зв'язок між двома
   * реєстрами, які тримаються на одному ключі.
   */
  'lib.opys': (_ev, elm) => {
    // Ключ справи — `REPO/фонд/опис/справа`; опис `_` — не встановлено.
    const parts = String(elm.dataset.arg).split('/');
    if (parts.length !== 4) return undefined;
    const [repo, fond, opys, spr] = parts;
    return goto('fonds', { repo, fond, opys: opys === '_' ? '' : opys, spr });
  },

  /** 🔎 Пошук у межах цієї справи. */
  'lib.find': (_ev, elm) => {
    ST.search = { case: elm.dataset.arg };
    return show('search');
  },
});
