/**
 * 🏠 Домівка — два різні екрани під одним іменем, і це навмисно.
 *
 * 🔴 Порожній простір бачить три двері («у мене є скани», «не знаю, де
 * шукати», «перевірити машину»). Це онбординг, і він працює: людині, яка щойно
 * поставила застосунок подвійним кліком, треба показати три входи, а не
 * дванадцять нулів.
 *
 * 🔴 Наповнений простір бачить дашборд. Ті самі три картки там — порожній
 * екран: людина, у якої вже є справи, прогони й канон, заходить на головну не
 * питати «з чого почнемо», а дивитись, де вона стоїть. Двері лишаються, але
 * згорнуті в ряд швидких дій унизу.
 *
 * Межа проходить по реєстру, а не по теці data: «реєстру ще не збирали» — теж
 * порожній стан, і показувати замість дашборда прочерки означало б відповісти
 * нулем там, де питання не ставили.
 */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, screenOfOp } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav, screenOn,
  refreshJobs } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';
import { spark, bars as rawBars, meter, steps, histogram, num } from '/ui/chart.js';


/**
 * Смуги розрізу з підписом хвоста цією мовою.
 *
 * Модуль діаграм лежить на спільному шарі й словника не бачить — у кожної
 * морди він свій, — тож слово «ще» мусить приїхати звідси. Обгортка одна на
 * весь екран: шість викликів із однаковим `restLabel` розійшлися б при першій
 * же правці.
 */
const bars = (items, opts = {}) => rawBars(items, { restLabel: t('dash.rest'), ...opts });

/** Зріз, на якому намальовано екран — щоб перемикач метрики не ходив на сервер. */
let PULSE = null;
/** Обрана метрика графіка часу. Живе між перемальовками одного екрана. */
let METRIC = 'htr_pages';


/**
 * 📖 Що сказати про зразкову справу — три різні стани, і плутати їх дорого.
 *
 * «Зразка немає в цій збірці» — межа версії, лагодити нічого. «Є, але не
 * розгорнутий» — одна кнопка. «Розгорнутий» — запрошення в гортач. Спільне
 * формулювання на всі три посилало б людину лагодити те, що справне, або
 * ховало б дію, яка є.
 */
function sampleBlock(d) {
  if (!d.sample_available) return `<p class="muted">${t('check.nosample')}</p>`;
  if (d.sample_case) return `<p class="muted">✅ ${t('check.sample.ready')}</p>`;
  return `<p class="muted">${t('check.sample.hint')}</p>
    <p><button data-act="sample.install">${t('check.sample.do')}</button></p>`;
}

/** Три двері першого запуску. Розмітка одна на обидва стани екрана. */
function doors() {
  return `<div class="cards">
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
  </div>`;
}

SCREENS.home = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('home.pulse', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  PULSE = env.data;
  const ws = PULSE.workspace || {};
  const reg = PULSE.registry || {};

  // Порожній простір: реєстру немає або в ньому нічого, крім, можливо, тек без
  // шифри. Саме ці двоє й означають «людина ще нічого не поклала».
  const empty = !reg.built || (!reg.cases && !reg.unfiled);
  if (empty) {
    setView(`<h2>${t('home.title')}</h2>
      ${renderWarnings(env)}
      ${doors()}
      ${onboarding(PULSE)}
      <p class="muted mono">${esc(ws.root || '')}</p>`);
    return;
  }
  setView(dashboard(env, PULSE));
};


/**
 * Чекліст першої сесії.
 *
 * 🔴 Три двері були входами, а не станом: людина натискала «перевірити машину»,
 * діставала таблицю — і на цьому шлях уривався. Питання «а що далі» не мало
 * відповіді ніде, і найпропущеніший крок першої сесії (чий рід шукаємо) не мав
 * у вікні дверей узагалі.
 *
 * 🔴 Смуга ЗНИКАЄ, коли все зелене, і вертається, щойно щось перестало ним
 * бути. Вічний чекліст на дашборді досвідченого дослідника — це шум, а
 * прихований назавжди після першого разу — це мовчання про поламане.
 *
 * ⚠ Крок, чия секція вимкнена, не показується. Червоний крок «щось прочитано»
 * у просторі, де читання вимкнено, вимагав би роботи, якої тут не роблять.
 */
function onboarding(d) {
  const reg = d.registry || {};
  const rd = d.reading || {};
  const se = d.search || {};
  const m = d.machine || {};
  const all = [
    { on: true, ok: m.ok ? m.ready : null, k: 'step.machine',
      act: 'home.demo', note: (m.bad || []).join(' · ') },
    { on: true, ok: (d.profile || {}).present, k: 'step.profile',
      nav: 'profile', note: (d.profile || {}).display || '' },
    { on: true, ok: !!(reg.cases || reg.unfiled), k: 'step.material',
      nav: 'newcase', note: reg.built ? `${num(reg.cases || 0)}` : '' },
    { on: screenOn('read'), ok: !!rd.pages, k: 'step.read',
      nav: 'read', note: rd.pages ? num(rd.pages) : '' },
    { on: screenOn('search') && se.ok, ok: se.runs ? se.indexed >= se.runs : null,
      k: 'step.index', nav: 'search',
      note: se.runs ? `${num(se.indexed)} / ${num(se.runs)}` : '' },
  ].filter((x) => x.on && x.ok !== null);
  if (!all.length || all.every((x) => x.ok)) return '';
  const done = all.filter((x) => x.ok).length;
  return `<div class="dash-sec steps">
    <h3>${ic('check-circle', 'ic-sm')} ${t('step.title')}
      <span class="aside">${done} ${t('dash.of')} ${all.length}</span></h3>
    <div class="dash-box">${all.map((x) => `<div class="step${x.ok ? ' on' : ''}">
      <span class="step-m">${x.ok ? '✅' : '⚠'}</span>
      <span class="step-t">${t(x.k)}<br>
        <span class="muted">${t(x.k + '.why')}</span></span>
      <span class="step-n muted">${esc(x.note)}</span>
      <span>${x.ok ? '' : `<button data-act="${x.nav ? 'nav' : esc(x.act)}"${
        x.nav ? ` data-arg="${esc(x.nav)}"` : ''}>${t('step.go')}</button>`}</span>
    </div>`).join('')}</div>
  </div>`;
}


// ── дашборд ──────────────────────────────────────────────────────────────────
function dashboard(env, d) {
  const ws = d.workspace || {};
  return `<h2>${t('dash.title')}</h2>
    ${headline(d, ws)}
    ${renderWarnings(env)}
    ${onboarding(d)}
    ${tiles(d)}
    ${progressSection(d)}
    ${canonSection(d)}
    ${readingSection(d)}
    ${materialSection(d)}
    ${searchSection(d)}
    ${timeSection(d)}
    ${spaceSection(d)}
    <div class="dash-sec">
      <h3>${t('dash.doors')}</h3>
      ${doors()}
    </div>`;
}

/**
 * Шапка: де я, наскільки свіжий зріз і хто востаннє щось міняв.
 *
 * 🔴 Пульс тут не прикраса. Простір відкривають із двох вікон і з агентської
 * сесії, тож питання «це число моє чи чуже» стоїть щодня; рядок «востаннє
 * змінювали: 14:44, `registry.collect`» відповідає на нього одразу, а не після
 * походу в журнал робіт.
 */
function headline(d, ws) {
  const p = d.pulse || {};
  const reg = d.registry || {};
  // ⚠ Кожен шматок — власний вузол. Проміжок між ними дає `gap` флексу, а той
  // рахує елементи: голий текстовий вузол сусіда не відсуває, і рядок злипався
  // в «реєстр зібрано: 26.08 12:23востаннє змінювали: …».
  const bits = [`<span class="ws">${esc(ws.name || '')}</span>`];
  if (reg.at) bits.push(`<span>${t('dash.built')}: ${esc(when(reg.at))}</span>`);
  bits.push(p.at
    ? `<span>${t('dash.pulse')}: ${esc(when(p.at))}${p.by ? ` · ${esc(p.by)}` : ''}</span>`
    : `<span>${t('dash.never')}</span>`);
  bits.push(`<span class="mono">${esc(ws.root || '')}</span>`);
  return `<div class="dash-head">${bits.join('')}</div>`;
}

/**
 * Плитки-показники.
 *
 * 🔴 Кожна плитка — кнопка на профільний екран. Число, з якого нікуди не
 * піти, змушує шукати той самий зріз удруге руками; а «7029 кандидатів чекає
 * ока» без входу в розбір це просто докір.
 *
 * 🔴 Плитка вимкненої секції не малюється зовсім (`screenOn`). Нуль
 * прочитаних сторінок там, де читання вимкнено, — не «нічого не прочитано», а
 * «питання не стояло», і одне не має права виглядати як інше.
 */
function tiles(d) {
  const reg = d.registry || {};
  const canon = d.canon || {};
  const rd = d.reading || {};
  const eye = d.eye || {};
  const out = [];

  out.push(tile('cases', 'drawers', t('dash.tile.cases'), reg.cases,
    'cases', { hist: 'cases' }));
  out.push(tile('frames', 'image', t('dash.tile.frames'), reg.frames,
    'library', { hist: 'frames' }));
  if (screenOn('runs') && rd.ok) {
    out.push(tile('read', 'quill', t('dash.tile.read'), rd.pages,
      'runs', { hist: 'htr_pages', of: reg.frames }));
  }
  if (canon.present) {
    out.push(tile('canon', 'books', t('dash.tile.canon'), canon.persons,
      '', { hist: 'canon_persons',
        note: `${num(canon.facts)} ${t('dash.facts')}` }));
  }
  if (screenOn('sift') && reg.built) {
    out.push(tile('hits', 'crop-check', t('dash.tile.hits'), reg.fuzzy_hits_open,
      'sift', { hist: 'hits_open' }));
  }
  if (screenOn('eye') && eye.built) {
    out.push(tile('eye', 'eye', t('dash.tile.eye'), eye.pages,
      'eye', { hist: 'pages_noted',
        note: `${num(eye.pages_full)} ${t('dash.eye.full')}` }));
  }
  return `<div class="tiles">${out.join('')}</div>`;
}

function tile(id, icon, label, value, screen, opts = {}) {
  const series = opts.hist ? seriesOf(opts.hist) : [];
  const trend = series.length > 1
    ? spark(series.map((p) => p.v), { title: `${label}: ${num(series[0].v)} → ${num(value)}` })
    : '';
  const under = opts.of
    ? `<span class="tile-of">${t('dash.of')} ${num(opts.of)}</span>`
    : (opts.note ? `<span class="tile-of">${esc(opts.note)}</span>` : '');
  const body = `<span class="tile-k">${ic(icon, 'ic-sm')} ${esc(label)}</span>
    <span class="tile-n">${num(value)}</span>
    ${under}
    <span class="tile-foot">${trend}${delta(series, value)}</span>`;
  // ⚠ Плитка без екрана — це `div`, а не `disabled`-кнопка. Вимкнена кнопка
  // блякне й читається як щось поламане чи недоступне саме тут і зараз, тоді
  // як насправді екрана для канону в застосунку немає взагалі. Число мусить
  // виглядати як число, а не як відмова.
  return screen
    ? `<button class="tile" data-act="nav" data-arg="${esc(screen)}">${body}</button>`
    : `<div class="tile flat">${body}</div>`;
}

/**
 * Приріст за вікно.
 *
 * 🔴 Показуємо, лише коли в журналі Є точка старша за вікно. Інакше «+3371 за
 * тиждень» на щойно заведеному журналі означало б «стільки з'явилось за
 * тиждень», хоча насправді це «стільки було, коли ми вперше подивились».
 */
function delta(series, value) {
  if (!series.length || value === null || value === undefined) return '';
  const now = Date.now();
  for (const [days, key] of [[7, 'dash.week'], [30, 'dash.month']]) {
    const edge = now - days * 86400e3;
    const older = series.filter((p) => Date.parse(p.at) <= edge);
    if (!older.length) continue;
    const diff = Number(value) - Number(older[older.length - 1].v);
    if (!diff) return '';
    return `<span class="tile-d">${diff > 0 ? '+' : '−'}${num(Math.abs(diff))}
      ${t(key)}</span>`;
  }
  return '';
}


/**
 * Поступ — стекові смуги, а не відсотки текстом.
 *
 * ⚠ Смуга сходиться до цілого за побудовою: частки складаються в те, що є на
 * диску, а не в окремо задане «скільки мало б бути». Хвіст, що не сходиться,
 * читався б як утрачені кадри.
 */
function progressSection(d) {
  const reg = d.registry || {};
  if (!reg.built) return '';
  const rd = d.reading || {};
  const blocks = [];

  const readPages = rd.ok ? Number(rd.pages || 0) : null;
  const left = Number(reg.htr_frames_left || 0);
  if (readPages !== null && (readPages || left)) {
    blocks.push(`<div><h4>${t('dash.progress.frames')}</h4>${meter([
      { label: t('dash.done.read'), n: readPages, tone: 'done' },
      { label: t('dash.done.left'), n: left, tone: 'todo' },
      { label: t('dash.done.ordered'), n: Number(reg.ordered || 0), tone: 'mut' },
    ])}</div>`);
  }
  if (screenOn('search') && reg.fuzzy_none !== undefined) {
    const all = Number(reg.cases || 0);
    const none = Number(reg.fuzzy_none || 0);
    blocks.push(`<div><h4>${t('dash.progress.cases')}</h4>${meter([
      { label: t('dash.done.sought'), n: Math.max(all - none, 0), tone: 'done' },
      { label: t('dash.done.unsought'), n: none, tone: 'todo' },
    ])}</div>`);
  }
  if (!blocks.length) return '';
  return sec('gauge', t('dash.progress'),
    `<div class="dash-two">${blocks.join('')}</div>`);
}


/**
 * Канон.
 *
 * 🔴 «Канону немає» — окремий стан із поясненням, а не зведення з нулями.
 * Нуль осіб читається як перевірений результат («я дивився, там порожньо»),
 * тоді як бази просто не збирали, і лікується це однією командою.
 */
function canonSection(d) {
  const c = d.canon || {};
  if (!c.present) {
    // ⚠ Сире `why` сервера тут не друкується: для звичайної відсутності канону
    // воно каже те саме, що рядок вище, лише службовими словами — і секція
    // виходила подвійним поясненням однієї речі.
    return sec('books', t('dash.canon'),
      `<p class="muted">${t('dash.canon.none')}</p>`);
  }
  const cov = c.coverage || {};
  const nums = [
    n(t('dash.canon.persons'), c.persons), n(t('dash.canon.families'), c.families),
    n(t('dash.canon.sources'), c.sources), n(t('dash.canon.places'), c.places),
    n(t('dash.canon.facts'), c.facts), n(t('dash.canon.cites'), c.citations),
    // 🔴 Ці два — з класом `flag`. Недоведений факт у дереві виглядає так
    // само, як доведений, тож єдине місце, де він узагалі помітний, — тут.
    n(t('dash.canon.uncited'), c.facts_uncited, c.facts_uncited > 0),
    n(t('dash.canon.nodates'), c.persons_no_dates, c.persons_no_dates > 0),
  ].join('');
  const years = (cov.year_min && cov.year_max)
    ? `<span class="aside">${t('dash.canon.years')} ${cov.year_min}—${cov.year_max}</span>`
    : '';
  const two = [];
  if ((c.facts_by_type || []).length) {
    two.push(`<div><h4>${t('dash.canon.types')}</h4>
      ${bars(c.facts_by_type.map(factLabel), { of: c.facts })}</div>`);
  }
  if ((c.top_surnames || []).length) {
    two.push(`<div><h4>${t('dash.canon.surnames')}</h4>
      ${bars(c.top_surnames, { of: c.persons })}</div>`);
  }
  if ((cov.by_record_type || []).length) {
    two.push(`<div><h4>${t('dash.canon.rt')}</h4>${bars(cov.by_record_type)}</div>`);
  }
  if ((cov.by_status || []).length) {
    two.push(`<div><h4>${t('dash.canon.status')}</h4>${bars(cov.by_status)}</div>`);
  }
  const dec = (c.facts_by_decade || []).length
    ? `<div><h4>${t('dash.canon.decades')}</h4>${histogram(c.facts_by_decade)}</div>`
    : '';
  return sec('books', t('dash.canon'),
    `<div class="dash-nums">${nums}</div>
     ${dec}
     ${two.length ? `<div class="dash-two">${two.join('')}</div>` : ''}`, years);
}


function readingSection(d) {
  const r = d.reading;
  if (!r) return '';               // секція читання вимкнена — питання не стояло
  if (!r.ok) return sec('quill', t('dash.reading'),
    `<p class="muted mono">${esc(r.why || '')}</p>`);
  const nums = [
    n(t('dash.reading.runs'), r.runs),
    n(t('dash.reading.pages'), r.pages),
    r.sec_median ? n(t('dash.reading.speed'), r.sec_median) : '',
    r.orphans ? n(t('dash.reading.orphans'), r.orphans, true) : '',
  ].join('');
  const two = [];
  if ((r.by_engine || []).length) {
    two.push(`<div><h4>${t('dash.reading.engines')}</h4>
      ${(r.by_engine).map((e) => `<div class="ch-bar">
        <span class="ch-bar-l">${eng(e.code, true, LANG)}</span>
        <span class="ch-bar-t"><i style="width:${pct(e.n, r.runs)}%"></i></span>
        <span class="ch-bar-n">${num(e.n)}</span></div>`).join('')}</div>`);
  }
  if ((r.by_model || []).length) {
    two.push(`<div><h4>${t('dash.reading.models')}</h4>${bars(r.by_model)}</div>`);
  }
  const last = (r.last || []).length
    ? `<div><h4>${t('dash.reading.last')}</h4><table><tbody>${
      r.last.map((x) => `<tr>
        <td class="mono">${esc(x.shifra || x.name || '')}</td>
        <td>${num(x.pages)}</td>
        <td class="mono muted">${esc(x.model || '')}</td>
        <td class="muted">${esc(when(x.updated))}</td></tr>`).join('')
    }</tbody></table></div>`
    : '';
  return sec('quill', t('dash.reading'),
    `<div class="dash-nums">${nums}</div>
     ${two.length ? `<div class="dash-two">${two.join('')}</div>` : ''}
     ${last}
     <p><button data-act="home.demo">▶ ${t('dash.machine')}</button></p>`);
}


function materialSection(d) {
  const reg = d.registry || {};
  if (!reg.built) return '';
  const two = [];
  if ((reg.by_repo || []).length) {
    two.push(`<div><h4>${t('dash.material.repo')}</h4>${bars(
      reg.by_repo.map((r) => ({ label: r.repo, n: r.frames })),
      { unit: t('dash.tile.frames') })}</div>`);
  }
  if ((reg.by_uezd || []).length) {
    two.push(`<div><h4>${t('dash.material.uezd')}</h4>${bars(
      reg.by_uezd.map((r) => ({ label: r.uezd, n: r.n })),
      { unit: t('dash.tile.cases') })}</div>`);
  }
  if (!two.length) return '';
  return sec('archive-box', t('dash.material'),
    `<div class="dash-two">${two.join('')}</div>`);
}


function searchSection(d) {
  const s = d.search;
  const eye = d.eye;
  if (!s && !eye) return '';       // секція дослідження вимкнена
  const nums = [];
  if (s && s.ok) {
    nums.push(n(t('dash.search.indexed'), `${num(s.indexed)} / ${num(s.runs)}`));
    if (s.stale) nums.push(n(t('dash.search.stale'), s.stale, true));
  }
  if (eye && eye.built) {
    nums.push(n(t('dash.eye.pages'), eye.pages));
    nums.push(n(t('dash.eye.full'), eye.pages_full));
    nums.push(n(t('dash.eye.records'), eye.records));
    if (eye.cases !== undefined) nums.push(n(t('dash.eye.cases'), eye.cases));
  }
  if (!nums.length) return '';
  return sec('search', t('dash.search'),
    `<div class="dash-nums">${nums.join('')}</div>`);
}


/**
 * Графік часу.
 *
 * 🔴 Під ним завжди стоїть, з якого дня ведеться спостереження і що означає
 * пунктир. Крива без цього рядка виглядає як повна історія простору, тоді як
 * насправді вона починається там, де вперше подивились, а її ліва частина —
 * реконструкція з міток на диску.
 */
function timeSection(d) {
  return sec('curve', t('dash.time'),
    `<div id="dash-time">${timeBody(d.history || [])}</div>`);
}

function timeBody(rows) {
  const picks = [
    ['htr_pages', t('dash.tile.read')],
    ['cases', t('dash.tile.cases')],
    ['frames', t('dash.tile.frames')],
    ['canon_persons', t('dash.tile.canon')],
    ['pages_noted', t('dash.tile.eye')],
    ['hits_open', t('dash.tile.hits')],
  ].filter(([k]) => seriesOf(k, rows).length > 1);
  if (!picks.length) return `<p class="muted">${t('dash.time.none')}</p>`;
  if (!picks.some(([k]) => k === METRIC)) METRIC = picks[0][0];
  const series = seriesOf(METRIC, rows);
  const live = rows.filter((r) => r.src !== 'backfill');
  // ⚠ Пояснення пунктиру — лише коли пунктир справді намальовано, тобто в
  // цьому ряду не менше двох реконструйованих точок (з однієї відрізка немає).
  // Легенда до лінії, якої на екрані немає, змушує людину шукати неіснуюче й
  // сумніватись у тому, що вона бачить.
  const dashed = series.filter((p) => p.src === 'backfill').length >= 2;
  const foot = [
    live.length ? `${t('dash.time.since')} ${esc(live[0].at.slice(0, 10))}` : '',
    dashed ? t('dash.time.backfill') : '',
  ].filter(Boolean).join(' · ');
  // ⚠ Спільна «сегментована група» (`.seg` у base.css) тут не працює, і це не
  // випадковість: ця морда перебиває вигляд усіх кнопок правилом `#view button`
  // (`app.css`), а ідентифікатор сильніший за будь-який клас спільного шару.
  // Тому активний стан описано поруч із тим правилом, тим самим способом, що й
  // головна дія форми. `aria-pressed` лишається при класі: клас каже про
  // вигляд, а екранному диктору потрібен саме стан.
  return `<div class="dash-pick">${picks.map(([k, label]) =>
      `<button data-act="home.metric" data-arg="${esc(k)}"
        class="${k === METRIC ? 'on' : ''}"
        aria-pressed="${k === METRIC}">${esc(label)}</button>`).join('')}</div>
    ${steps(series)}
    <p class="muted">${foot}</p>`;
}


function spaceSection(d) {
  const s = d.sections || {};
  const p = d.profile || {};
  const jobs = d.jobs || {};
  const bits = [];
  const preset = s.preset
    ? `${t('dash.preset')}: ${t(`preset.${s.preset}`)}`
    : t('dash.custom');
  bits.push(`<span>${esc(preset)}</span>`);
  for (const id of s.active || []) {
    const sec_ = (SECTIONS.sections || []).find((x) => x.id === id);
    if (sec_) bits.push(`<span>${esc(LANG === 'en' ? sec_.label_en : sec_.label)}</span>`);
  }
  if (jobs.queue && jobs.running) {
    bits.push(`<span class="flag">${t('dash.jobs.running')}: <b>${num(jobs.running)}</b></span>`);
  }
  const prof = p.present
    ? `<div class="dash-nums">
        <span><b>${esc(p.display || p.name || '')}</b></span>
        ${n(t('dash.profile.roots'), (p.roots || []).length)}
        ${n(t('dash.profile.spellings'), p.spellings)}
       </div>`
    : `<p class="muted">${t('dash.profile.none')}</p>`;
  return sec('settings', t('dash.space'),
    `<div class="dash-nums">${bits.join('')}</div>${prof}`);
}


// ── дрібні помічники ─────────────────────────────────────────────────────────
function sec(icon, title, body, aside = '') {
  return `<div class="dash-sec">
    <h3>${ic(icon, 'ic-sm')} ${esc(title)}${aside}</h3>
    <div class="dash-box">${body}</div>
  </div>`;
}

function n(label, value, flag = false) {
  if (value === null || value === undefined || value === '') return '';
  const shown = typeof value === 'string' ? value : num(value);
  return `<span${flag ? ' class="flag"' : ''}>${esc(label)}: <b>${shown}</b></span>`;
}

const pct = (part, whole) => whole ? ((Number(part) / Number(whole)) * 100).toFixed(1) : 0;

/**
 * Тип факту — словом, а не кодом.
 *
 * 🔴 Сервер віддає `occupation`, і поставити це в український стовпчик поруч
 * зі «Шлюбами» й «Сповідними» означає показати людині внутрішнє ім'я поля.
 * Переклад лишається в обличчі: словник знає обидві мови, схема — жодної.
 * Невідомий код лишається кодом, а не зникає: новий тип факту має бути видно.
 */
function factLabel(row) {
  if (!row.code) return row;                       // рядок хвоста «ще N»
  const key = `fact.${row.code}`;
  const label = t(key);
  return { ...row, label: label === key ? row.code : label };
}

/** Ряд журналу → точки графіка. Рядки без цього поля пропускаються, не нулюються. */
function seriesOf(key, rows) {
  return (rows || (PULSE && PULSE.history) || [])
    .filter((r) => r[key] !== null && r[key] !== undefined)
    .map((r) => ({ at: r.at, v: Number(r[key]), src: r.src }));
}

/** `2026-08-26T15:05:14` → `26.08 15:05`. Рік лишається, коли він не цьогорічний. */
function when(iso) {
  const s = String(iso || '');
  if (s.length < 10) return s;
  const y = s.slice(0, 4);
  const md = `${s.slice(8, 10)}.${s.slice(5, 7)}`;
  const hm = s.length >= 16 ? ` ${s.slice(11, 16)}` : '';
  const nowY = String(new Date().getFullYear());
  return y === nowY ? `${md}${hm}` : `${md}.${y}`;
}


Object.assign(ACTIONS, {
  'home.scans': async () => {
    // 🔴 Раніше ця картка — перший клік того, заради кого все й робилось —
    // відсилала в командний рядок за `nysh look`. Відсилати до терміналу того,
    // хто щойно поставив застосунок подвійним кліком, означало обірвати шлях на
    // першому ж кроці.
    //
    // ⚠ Тут довго стояло «вибору теки віконцем браузер не дасть». Це було
    // правдою про браузер і неправдою про застосунок: діалог відкриває сервер,
    // який стоїть на тій самій машині, — і тепер у формі є і він, і гортач тек.
    await show('newcase');
  },

  // 🔴 Перемикач метрики не ходить на сервер: зріз уже в `PULSE`, і ще один
  // запит на кожен клік дав би півсекунди очікування там, де дані лежать у
  // пам'яті. Заразом це знімає ризик, що дві криві на одному екрані виявляться
  // з різних зрізів.
  // 🔴 Перемальовується тільки коробка графіка, а не весь екран. Через
  // `setView` пішли б і застереження конверта — а серед них «зріз застарів» із
  // кнопкою перезбірки. Клік по підпису кривої не має права гасити попередження
  // про те, що всі числа поруч старі.
  //
  // 🔴 І не запит на сервер: зріз уже лежить у `PULSE`, тож ще одне ходіння
  // коштувало б секунди на клік — і дало б криву з іншого зрізу, ніж плитки.
  'home.metric': (_ev, elm) => {
    METRIC = elm.dataset.arg;
    const box = el('dash-time');
    if (box && PULSE) swapHtml(box, timeBody(PULSE.history || []));
  },

  'home.demo': async () => {
    // 🔴 Раніше тут вивалювався сирий JSON про середовище рушіїв — під написом
    // «перевірити, що читання працює на цій машині». Питання правильне, а
    // відповідь була не тими словами й не про те: людина, яка щойно поставила
    // застосунок, мусить прочитати, чого бракує і чим це ставиться.
    busy();
    const env = await callOp('setup.check', {});
    if (!env.ok) return failure(env);
    const rows = (env.data.checks || []).map((c) => {
      const mark = { ok: '✅', warn: '⚠', fail: '🔴' }[c.level] || '•';
      // 🔴 Колонка «чим це ставиться» була суцільним терміналом: дев'ять
      // рядків `<code>` і жодної кнопки — під написом, який обіцяв протилежне.
      // Людина, що ставила застосунок майстром, командного рядка не має в полі
      // зору взагалі, тож ця порада виконувалась рівно ніким. Тепер кнопка
      // з'являється там, де операція справді є (поле `op` заповнює сервер), а
      // команда лишається для решти — чесно, як команда.
      const act = c.op
        ? `<button class="ctl-sm" data-act="check.fix" data-arg="${esc(c.op)}"
             >${esc(t('check.fix'))}</button>`
        : (c.fix ? `<code>${esc(c.fix)}</code>` : '');
      return `<tr><td>${mark}</td><td><b>${esc(c.name)}</b><br>
        <span class="muted">${esc(c.detail)}</span></td>
        <td>${act}</td></tr>`;
    }).join('');
    setView(`<h2>▶ ${t('check.title')}</h2>
      <p class="muted">${t('check.why')}</p>
      ${env.data.ready ? `<div class="warn">✅ ${t('check.ready')}</div>`
        : `<div class="warn">${t('check.notready')}</div>`}
      ${renderWarnings(env)}
      <table><tbody>${rows}</tbody></table>
      ${sampleBlock(env.data)}`);
  },

  /**
   * 🔧 Полагодити рядок перевірки — тим, чим він і лагодиться.
   *
   * Дві поведінки, і різниця в тому, чи операція щось міняє. Читальну
   * (`update.check`) виконуємо тут-таки й показуємо відповідь: людина питала
   * саме про це. Ту, що міняє (`profile.set`), виконати без її слів не можна —
   * ведемо на екран, де ці слова питають.
   */
  'check.fix': async (_ev, elm) => {
    const name = elm.dataset.arg;
    if (name === 'update.check') {
      const env = await callOp(name, {});
      // 🔴 Три стани, і всі три різні: відмова операції, «до pypi.org не
      // дійшли» і відповідь. Доти всі вони йшли однією гілкою по `d.known`,
      // тож справжня поламка виглядала як порожня червона рамка без тексту.
      const d = env.data || {};
      const line = !env.ok
        ? `<div class="warn err">${esc(env.error || '?')}</div>`
        : (!d.known
          ? `<div class="warn">${esc(d.installed)}${renderWarnings(env)}</div>`
          : `<div class="warn">${d.newer ? '⬆' : '✅'} ${esc(d.installed)} → ${
              esc(d.latest)}${renderWarnings(env)}${
              d.newer ? `<br><code>${esc(d.how)}</code>` : ''}</div>`);
      // ⚠ Заміна, а не дописування: `insertAdjacentHTML` лишав по банеру на
      // кожне натискання, і таблиця перевірок з'їжджала вниз.
      let box = el('check-upd');
      if (!box) {
        const view = el('view');
        if (!view) return undefined;
        view.insertAdjacentHTML('afterbegin', '<div id="check-upd"></div>');
        box = el('check-upd');
      }
      box.innerHTML = line;
      return undefined;
    }
    const scr = screenOfOp(name);
    return scr ? show(scr) : undefined;
  },

  // 📖 Зразок — єдина дія на цьому екрані, що щось міняє. Вона стоїть саме
  // тут, бо питання «чи воно працює» і відповідь «ось перевірте на трьох
  // аркушах» — одне питання, і розводити їх по різних екранах означало б
  // сховати відповідь від того, хто щойно поставив застосунок.
  'sample.install': async () => {
    busy();
    const env = await callOp('sample.install', {});
    if (!env.ok) return failure(env);
    const d = env.data;
    // 🔴 Разом із застереженнями. Тут їх рівно два — «декоду до кадрів немає» і
    // «реєстр не перезібрався», — і обидва описують той стан, у якому людина
    // за хвилину опиниться: піде в «Мої справи», побачить нуль при розгорнутій
    // справі й вирішить, що зразок не розгорнувся. Викидати попередження саме
    // тут означало дати справдитись рівно тому, про що попереджали.
    setView(`<h2>📖 ${t('check.sample.title')}</h2>
      <p>${esc(d.shifra)} — ${d.frames.length}/${d.frames_total}</p>
      <p class="muted">${esc(d.case_dir)}</p>
      ${renderWarnings(env)}
      <p class="muted">${t('check.sample.next')}</p>
      <p><button data-act="nav" data-arg="view">${t('nav.view')}</button></p>`);
  },
});
