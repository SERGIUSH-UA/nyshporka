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
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';

/** Діючий фільтр. Живе між входами на екран: повернувшись, людина бачить своє. */
let LIB = {
  q: '', key: '', repo: '', record_type: '', uezd: '', htr: '', fuzzy: '',
  status: '', verdict: '', curated: false, on_disk: null, page: 0,
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
  const env = await callOp('library.list', {
    q: LIB.q, key: LIB.key, repo: LIB.repo, record_type: LIB.record_type,
    uezd: LIB.uezd,
    htr: LIB.htr, fuzzy: LIB.fuzzy, status: LIB.status, verdict: LIB.verdict,
    curated: LIB.curated, page: LIB.page,
    ...(LIB.on_disk === null ? {} : { on_disk: LIB.on_disk }),
  });
  if (seq !== _libSeq) return;          // нас уже обігнав свіжіший запит
  if (!alive(gen)) return;              // з бібліотеки вже пішли
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const rows = d.cases || [];
  const layers = (d.summary || {}).has_layers;
  LIB_PAGES = d.pages || 1;

  if (!full) {
    // Каркас на місці — міняється лише вміст. `swapHtml` тримає висоту
    // контейнера на час підміни, тож сторінка під таблицею не підстрибує.
    const body = el('lib-rows');
    if (body) swapHtml(body, rows.map((r) => libRow(r, layers)).join(''));
    const n = el('lib-count');
    if (n) n.innerHTML = libCount(d);
    const warn = el('lib-warn');
    if (warn) warn.innerHTML = libKeyChip() + renderWarnings(env);
    // Локальна змінна не зветься `pager`: під цим іменем уже стоїть спільна
    // смуга, і тінь мовчки перетворила б виклик на звертання до вузла DOM.
    const pg = el('lib-pager');
    if (pg) pg.innerHTML = pager(d);
    return;
  }

  const head = `<h2>${ic('books')} ${t('lib.title')}</h2>
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
    <div class="row">
      ${libStageSelects(d)}
      <label class="lbl-mini"><input type="checkbox" id="lib-disk"
        data-act="lib.filter"${LIB.on_disk ? ' checked' : ''}> ${t('lib.ondisk')}</label>
      <label class="lbl-mini"><input type="checkbox" id="lib-curated"
        data-act="lib.filter"${LIB.curated ? ' checked' : ''}> ${t('lib.curated')}</label>
    </div>
    <div id="lib-warn">${libKeyChip()}${renderWarnings(env)}</div>
    <p class="muted" id="lib-count">${libCount(d)}</p>
    <table><thead><tr>
      <th>${t('lib.col.shifra')}</th><th>${t('lib.col.title')}</th>
      <th class="num">${t('lib.col.years')}</th><th>${t('lib.col.place')}</th>
      <th class="num">${t('common.frames')}</th>
      <th title="${esc(t('lib.col.work.why'))}">${t('lib.col.work')}</th>
      <th>${t('lib.col.verdict')}</th><th></th></tr></thead>
    <tbody id="lib-rows">${rows.map((r) => libRow(r, layers)).join('')
      || skelRows(6, 8)}</tbody></table>
    <div id="lib-pager">${pager(d)}</div>`);
  _libFacets = true;
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
    `${ic('books', 'ic-sm')} ${esc(s.all ?? 0)} ${t('lib.sum.all')}`,
    s.on_disk != null ? `${ic('disk', 'ic-sm')} ${esc(s.on_disk)} ${t('lib.sum.disk')}` : '',
  ];
  if (s.has_layers) {
    bits.push(
      `${ic('quill', 'ic-sm')} ${esc(s.no_htr)} ${t('lib.sum.nohtr')}`,
      `${ic('search', 'ic-sm')} ${esc(s.no_fuzzy)} ${t('lib.sum.nofuzzy')}`,
      s.hits_open ? `${ic('eye', 'ic-sm')} ${esc(s.hits_open)} ${t('lib.sum.open')}` : '');
  } else {
    bits.push(`<span class="dim">${t('lib.sum.nolayers')}</span>`);
  }
  if (s.no_clan) bits.push(`🚫 ${esc(s.no_clan)} ${t('lib.sum.noclan')}`);
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
    </select>`;
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
      { scanned: '🔎', swept: '🔎', reviewed: '🏁' }[fz] || '🔎'}</span>${
      open ? `<b class="open">${open}</b>` : ''}`);
  }
  if (r.canon_facts) bits.push(`📖${esc(r.canon_facts)}`);
  if (r.pages_noted) bits.push(`🗒${esc(r.pages_noted)}`);
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
  return `<tr>
    <td class="mono">${disk} ${esc(r.shifra || r.key || '')}</td>
    <td>${esc((r.title || '').slice(0, 80))}</td>
    <td class="num">${esc(years)}</td>
    <td>${esc((r.place || '').slice(0, 30))}</td>
    <td class="num">${esc(r.frames || 0)}</td>
    <td class="work">${libWork(r, layers)}</td>
    <td>${v}</td>
    <td class="acts">
      ${r.path ? `<button class="ctl-sm" data-act="lib.frames" data-arg="${esc(r.path)}"
        title="${esc(t('lib.act.frames'))}">${ic('image', 'ic-o ic-sm')}</button>` : ''}
      ${r.path ? `<button class="ctl-sm" data-act="lib.read" data-arg="${esc(r.path)}"
        title="${esc(t('lib.act.read'))}">${ic('quill', 'ic-o ic-sm')}</button>` : ''}
      <button class="ctl-sm" data-act="lib.runs" data-arg="${esc(r.key)}"
        title="${esc(t('lib.act.runs'))}">${ic('list', 'ic-o ic-sm')}</button>
      <button class="ctl-sm" data-act="lib.find" data-arg="${esc(r.key)}"
        title="${esc(t('lib.act.find'))}">${ic('search', 'ic-o ic-sm')}</button>
      ${r.fond ? `<button class="ctl-sm" data-act="lib.opys"
        data-arg="${esc(`${r.repo}/${r.fond}/${r.spr}`)}"
        title="${esc(t('lib.act.opys'))}">${ic('archive-box', 'ic-o ic-sm')}</button>` : ''}
      <button class="ctl-sm" data-act="lib.verdict" data-arg="${esc(r.key)}"
        title="${esc(t('lib.verdict.set'))}">${ic('pencil-line', 'ic-o ic-sm')}</button>
    </td>
  </tr>`;
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
  setView(`<h2>${ic('pencil-line')} ${esc(key)}</h2>
    <div class="row"><select id="lv-kind">
      <option value="">${esc(t('lib.verdict.clear'))}</option>
      <option value="no_clan">${esc(t('lib.verdict.no_clan'))}</option>
      <option value="clan_found">${esc(t('lib.verdict.clan_found'))}</option>
      <option value="recheck">${esc(t('lib.verdict.recheck'))}</option>
    </select></div>
    <div class="row"><input id="lv-pages" type="number" min="0"
      placeholder="${esc(t('lib.pages'))}"></div>
    <p class="muted">${t('lib.pages.why')}</p>
    <div class="row"><input id="lv-note" placeholder="${esc(t('lib.note'))}"></div>
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
      // 🔴 Будь-яка зміна фільтра повертає на першу сторінку: лишившись на
      // сьомій, людина побачила б порожньо й вирішила, що нічого не знайшлось.
      page: 0,
    };
    return libLoad(false);
  },


  'lib.verdict': (_ev, elm) => libVerdictForm(elm.dataset.arg),

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
    if (box && (env.warnings || []).length) {
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
    const [repo, fond, spr] = String(elm.dataset.arg).split('/');
    return goto('fonds', { repo, fond, spr });
  },

  /** 🔎 Пошук у межах цієї справи. */
  'lib.find': (_ev, elm) => {
    ST.search = { case: elm.dataset.arg };
    return show('search');
  },
});
