/** 🖋 Читання справи рушієм. */

import { t } from '../core/strings.js';
import { callOp, FINAL_STATES, TOKEN } from '../core/net.js';
import { esc, el, setView, boxError, busyForm,
  renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show, goto, onJob, jobProgress } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { attachCombobox } from '/ui/combobox.js';
import { pathField } from '../core/paths.js';

/** Тека, для якої показана картка. Живе між входами: справа не міняється. */
let RD = { case_dir: '', script: '', card: null };
/** Відписки від живих читань картки — знімаються при кожному перемальовуванні. */
let NOW_UNSUB = [];

/**
 * 🖋 Читання — єдиний екран, де людина віддає машині ніч.
 *
 * 🔴 Тому все, що можна дізнатись ДО запуску, показується до нього: скільки
 * кадрів, яким письмом і звідки це відомо, чим уже читали й чого бракує.
 * Дізнатись «модель не та» через годину означає втратити ніч.
 *
 * 🔴 Два режими, і межа між ними не в складності, а в ціні помилки. Простий
 * несе те, без чого запускати не можна. «Для досвідчених» — важелі, у яких є
 * зміряне правило користування; ручка без такого правила сюди не потрапляє
 * взагалі.
 */
SCREENS.read = async () => {
  const gen = curGen();
  // 🔴 Тека приходить із бібліотеки, а не з пам'яті людини. Набирати шлях
  // руками — найдешевший спосіб прочитати не ту теку й дізнатись про це через
  // годину.
  const seed = (ST.read || {}).case_dir || '';
  if (seed) RD = { case_dir: seed, script: '', card: null };
  ST.read = null;
  setView(`
    <h2>${t('nav.read')}</h2>
    <p class="muted">${t('read.why')}</p>
    <form class="row" data-act="read.pick">
      ${pathField({ name: 'case_dir', mode: 'dir', purpose: 'read.case_dir',
        value: RD.case_dir, ph: t('read.dir'), autofocus: !RD.case_dir })}
      <button type="submit">${t('read.show')}</button>
    </form>
    <div id="card"></div>
    <div id="hits"></div>`);
  await readCases();
  if (!alive(gen)) return;
  if (RD.case_dir) await readCard();
};

/**
 * Підказка тек: справи бібліотеки, які лежать на диску.
 *
 * 🔴 Дошук на сервері, а не перші двісті рядків у пам'яті. На просторі з
 * півтори тисячі справ фіксована пачка мовчки ховала більшість: людина
 * набирала назву й бачила «нічого», бо її справа не потрапила в перші двісті.
 *
 * ⚠ Вільний текст лишається: тека поза бібліотекою — законний перший випадок,
 * і вимагати опису до першого ж читання означало б замкнути двері перед тим,
 * хто щойно завантажив скани.
 */
async function readCases() {
  const input = el('view').querySelector('input[name="case_dir"]');
  if (!input) return;
  const load = async (q) => {
    const env = await callOp('library.list',
      { q, on_disk: true, page_size: 30 });
    return env.ok
      ? ((env.data || {}).cases || []).map((c) => c.path).filter(Boolean)
      : [];
  };
  const box = attachCombobox(input, { items: await load(''),
    empty: t('read.nocases') });
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const items = await load(input.value || '');
      if (box && box.setItems) box.setItems(items);
    }, 250);
  });
}

/** Картка справи: що це, яким письмом і що з нею вже робили. */
async function readCard() {
  const box = el('card');
  if (!box) return;
  box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  const env = await callOp('htr.case_info',
    { case_dir: RD.case_dir, script: RD.script });
  if (!env.ok) return boxError('card', env);
  const c = env.data || {};
  RD.card = c;
  box.innerHTML = `
    <table><tbody>
      <tr><td>${t('read.case')}</td><td>${c.shifra
        ? `<b class="mono">${esc(c.shifra)}</b> ${esc(c.title || '')}`
        : `<span class="warn-inline">${t('read.undescribed')}</span>`}</td></tr>
      <tr><td>${t('read.frames')}</td><td class="num">${esc(c.frames || 0)}
        ${c.frames ? `<button class="ctl-sm" data-act="read.frames"
          title="${esc(t('lib.act.frames'))}">${ic('image', 'ic-o ic-sm')}</button>` : ''}
        </td></tr>
      <tr><td>${t('read.script')}</td><td>${scriptCell(c)}</td></tr>
      <tr><td>${t('read.done')}</td><td>${coverCell(c)}</td></tr>
    </tbody></table>
    ${renderWarnings(env)}
    <div id="read-now"></div>
    <div id="read-form">${readForm(c)}</div>`;
  await readNow();
  return undefined;
}

const normPath = (s) => String(s || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();

/**
 * ▶ Що зараз читається з цієї справи — тут же, де запуск.
 *
 * 🔴 Поступ і «Спинити» живуть на картці справи, а не на окремому екрані.
 * Доти після «Читати» лишався лише напис «триває 12%» без кнопки, і зникав,
 * щойно людина виходила з картки: повернувшись, вона бачила форму запуску
 * знову й ставила друге читання тієї самої справи в чергу за першим
 * (тестувальник 06.10.2026: кирилиця й латинка, обидві «чекали на карту»).
 * Тому, поки справа читається, форма схована — щоб читати інакше, спершу
 * спинити.
 */
async function readNow() {
  NOW_UNSUB.forEach((f) => f());
  NOW_UNSUB = [];
  const box = el('read-now');
  if (!box) return;
  let jobs = [];
  try {
    const res = await fetch('/api/jobs');
    if (res.ok) jobs = (await res.json()).jobs || [];
  } catch { /* без переліку робіт картка лишається як була */ }
  const mine = new Set([normPath(RD.case_dir), normPath((RD.card || {}).case_dir)]);
  const now = jobs.filter((j) => j.kind === 'read' && !FINAL_STATES.includes(j.state)
    && mine.has(normPath((j.cfg || {}).case_dir)));
  const form = el('read-form');
  if (form) form.hidden = now.length > 0;
  if (!now.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<h3>${t('read.now')}</h3>
    ${now.map((j) => `<div class="job" id="now-${esc(j.id)}">${nowItem(j)}</div>`).join('')}
    <p class="muted">${t('read.now.busy')}</p>`;
  for (const j of now) {
    NOW_UNSUB.push(onJob(j.id, (fresh) => {
      if (FINAL_STATES.includes(fresh.state)) { readCard(); return; }
      const item = el(`now-${fresh.id}`);
      if (item) item.innerHTML = nowItem(fresh);
    }));
  }
}

/** Рядок живого читання: чим, що з ним зараз і кнопка «Спинити». */
function nowItem(j) {
  // Заголовок роботи — «тека: N кадрів, модель … · чекає на карту: хто»;
  // тека вже стоїть у картці, тож лишаємо решту.
  const what = String(j.title || '').split(': ').slice(1).join(': ') || j.title || '';
  return `<b>${esc(what)}</b>
    ${jobProgress(j)}
    ${j.error ? `<div class="warn err">${esc(j.error)}</div>` : ''}
    <button data-act="jobs.cancel" data-job="${esc(j.id)}">${t('jobs.cancel')}</button>
    <button data-act="read.change" data-job="${esc(j.id)}">${t('read.change')}</button>`;
}

/** Модель → рушій за префіксом імені ваг, як у маніфесті. */
const engineOf = (model) => (/^pysar/.test(model) ? 'pysar'
  : /^diak/.test(model) ? 'diak' : /^skryba/.test(model) ? 'skryba' : '');

/**
 * Розкласти голоси запуску: що йде спільним проходом, а що — окремим прогоном.
 *
 * Справу цим письмом уже почали (основний рушій має сторінки) — тоді кожен
 * голос, якого бракує, іде окремим прогоном своєю моделлю: так він дістанеться
 * ВСІМ сторінкам, а не лише недочитаним (див. `addVoiceButtons`).
 */
function splitVoices(c, args) {
  const models = c.models || {};
  const done = c.covered || {};
  const mainEng = (args.script || c.script) === 'latin' ? 'skryba' : 'pysar';
  const started = Number((done[mainEng] || {}).pages_done || 0) > 0;
  const extra = [];
  if (!started) return { args, extra };
  const out = { ...args };
  if (out.second_voice && models.diak) {
    out.second_voice = false;
    extra.push(models.diak);
  }
  if ((out.also || []).includes('latin') && models.skryba) {
    out.also = [];
    extra.push(models.skryba);
  }
  return { args: out, extra };
}

/**
 * Письмо — трьома різними станами, ніколи одним.
 *
 * 🔴 Здогад із назви теки й запис у паспорті справи розрізняються надійністю
 * на порядок, а на екрані виглядали б однаково. Помилка тут не дає збою: вона
 * дає осмислене на вигляд сміття через годину роботи, і помічають її через
 * місяць — коли по декоду шукають прізвище й не знаходять.
 */
function scriptCell(c) {
  const label = t(`read.script.${c.script}`) || c.script || '?';
  const cls = { fixed: '', genre: 'muted', epoch: 'muted',
    folder: 'warn-inline', unknown: 'warn-inline' }[c.script_trust] || 'muted';
  return `<b>${esc(label)}</b>
    <span class="${cls}"> — ${esc(c.script_why || '')}</span>
    <label class="lbl-mini">${t('read.script.set')}
      <select data-act="read.script">
        <option value="">${t('read.script.auto')}</option>
        <option value="cyrillic"${c.script_trust === 'fixed' && c.script === 'cyrillic' ? ' selected' : ''}>${t('read.script.cyrillic')}</option>
        <option value="latin"${c.script_trust === 'fixed' && c.script === 'latin' ? ' selected' : ''}>${t('read.script.latin')}</option>
      </select></label>`;
}

/**
 * Чим справу вже прочитали — і чого бракує.
 *
 * 🔴 «Прогін є» мовчки читається як «справу прочитано». Для книги з двома
 * письмами це неправда: один рушій закриває лише своє, і половина сторінок
 * лишається непрочитаною при зеленому вигляді переліку.
 */
function coverCell(c) {
  const done = c.covered || {};
  const ids = Object.keys(done);
  if (!ids.length) return `<span class="muted">${t('read.never')}</span>`;
  return ids.map((id) => `${eng(id)} <span class="mono">${esc(done[id].model || '')}</span>
    <span class="dim">${esc(done[id].pages_done || 0)} ${t('common.pages')}</span>`)
    .join(' · ') + addVoiceButtons(c);
}

/**
 * ➕ «Додати голос» — рушій, якого цій справі бракує, окремим прогоном.
 *
 * 🔴 Окремим, а не перезапуском із галочкою: рушій при відновленні пропускає
 * сторінки, які вже є, тож доданий перезапуском голос дістався б лише решті, і
 * про це ніщо не сказало б. Окремий прогін моделлю голосу лягає в ту саму
 * теку голосу й доповнює рівно те, чого бракує (`pick.engine_models`).
 */
function addVoiceButtons(c) {
  const models = c.models || {};
  const names = Object.fromEntries((c.engines || []).map((e) => [e.id, e.label]));
  const missing = (c.gaps || []).filter((g) => g.kind === 'missing' && models[g.engine]);
  if (!missing.length) return '';
  return `<div class="row-actions">${missing.map((g) => `<button class="ctl-sm"
    data-act="read.addvoice" data-arg="${esc(models[g.engine])}">${ic('plus', 'ic-sm')}
    ${t('read.addvoice')}: ${esc(names[g.engine] || g.engine)}</button>`).join(' ')}</div>`;
}

/** Форма запуску: просте зверху, важелі під розкриттям. */
function readForm(c) {
  const engines = (c.engines || []).map((e) => e.label).filter(Boolean);
  // «Змінити» живе читання: галочки — як у нього, а не за замовчуванням.
  const prev = RD.prev || null;
  const second = prev ? prev.second : true;
  const alsoLatin = prev ? prev.latin : c.script === 'mixed';
  return `<form data-act="read.plan">
    ${prev ? `<p class="muted">${t('read.change.why')}</p>` : ''}
    <div class="row">
      <label><input type="checkbox" name="second_voice" value="1"${second ? ' checked' : ''}>
        ${t('read.voice.on')}</label>
      <span class="muted">${t('read.voice.why')}</span>
    </div>
    ${c.script === 'latin' ? '' : `<div class="row">
      <label><input type="checkbox" name="also_latin" value="1"
        ${alsoLatin ? 'checked' : ''}> ${t('read.also.latin')}</label>
      <span class="muted">${t('read.also.why')}</span>
    </div>`}
    <details><summary>${t('read.expert')}</summary>
      <div class="row">
        <label class="lbl-mini">${t('read.limit')}
          <input name="limit" size="6" placeholder="0"></label>
        <label class="lbl-mini">${t('read.pages')}
          <input name="pages" size="10" placeholder="1-50,60"></label>
        <label class="lbl-mini">${t('read.workers')}
          <input name="workers" size="3" value="1"></label>
        <label class="lbl-mini">${t('read.device')}
          <input name="device" size="7" placeholder="cuda:0"></label>
        <label class="lbl-mini">${t('read.seg')}
          <input name="seg_height" size="5" placeholder="0"></label>
      </div>
      <div class="row">
        <label class="lbl-mini" for="pf-out_dir">${t('read.outdir')}</label>
        ${pathField({ name: 'out_dir', mode: 'dir', purpose: 'read.out_dir',
          ph: t('read.outdir.why') })}
      </div>
      <div class="row">
        <label class="lbl-mini" for="pf-model">${t('read.modelfile')}</label>
        ${pathField({ name: 'model', mode: 'file', purpose: 'read.model',
          ph: t('read.modelfile.why') })}
      </div>
      <p class="muted">${t('read.expert.why')}</p>
      ${engines.length
        ? `<p class="muted">${t('read.engines')}: ${esc(engines.join(', '))}</p>`
        : ''}
    </details>
    <div class="row"><button type="submit">${t('read.plan')}</button></div>
  </form>`;
}

Object.assign(ACTIONS, {
  'read.pick': (ev) => {
    ev.preventDefault();
    RD = { case_dir: String(new FormData(ev.target).get('case_dir') || ''),
      script: '', card: null };
    return readCard();
  },

  'read.script': (_ev, elm) => {
    RD = { ...RD, script: elm.value || '' };
    return readCard();
  },

  'read.plan': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    const num = (k) => Number(fd.get(k) || 0) || 0;
    RD = { ...RD,
      args: {
        case_dir: RD.case_dir,
        script: (RD.card || {}).script_trust === 'fixed' ? RD.script : '',
        second_voice: fd.get('second_voice') === '1',
        // ➕ латинка третім голосом того самого проходу: мішане письмо
        // закривається одним прогоном, сегментація рахується раз
        also: fd.get('also_latin') === '1' ? ['latin'] : [],
        limit: num('limit'),
        pages: String(fd.get('pages') || ''),
        workers: Math.max(1, num('workers') || 1),
        seg_height: num('seg_height'),
        device: String(fd.get('device') || ''),
        // 🔴 Обидва поля мусять доїхати в аргументи. Показане на екрані й не
        // надіслане — гірше за відсутнє: людина вказала, куди класти текст,
        // побачила, що вказала, і не отримала цього.
        out_dir: String(fd.get('out_dir') || ''),
        model: String(fd.get('model') || ''),
      } };
    const split = splitVoices(RD.card || {}, RD.args);
    RD.args = split.args;
    RD.extra = split.extra;
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('read.plan', RD.args);
    unlock();
    if (!env.ok) return boxError('hits', env);
    const p = env.data.plan || {};
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <table><tbody>
        <tr><td>${t('read.frames')}</td><td class="num">${esc(p.frames)}</td></tr>
        <tr><td>${t('read.script')}</td><td>${esc(p.script)}</td></tr>
        <tr><td>${t('read.model')}</td><td class="mono">${esc(p.model)}</td></tr>
        ${(p.voices || []).length
    ? `<tr><td>${t('read.voice')}</td><td class="mono">${esc(p.voices.join(' + '))}</td></tr>`
    : ''}
        <tr><td>→</td><td class="mono">${esc(p.out_dir)}</td></tr>
        ${(RD.extra || []).length ? `<tr><td>${t('read.voice')}</td><td>
          <span class="mono">${esc(RD.extra.join(' + '))}</span>
          <span class="muted">— ${t('read.extra.why')}</span></td></tr>` : ''}
      </tbody></table>
      <button data-act="read.go">${t('read.go')}</button>`;
    return undefined;
  },

  /**
   * Запуск.
   *
   * 🔴 Єдине місце в застосунку, де модальне питання доречне: розбіжність
   * письма й моделі коштує годин карти заради правдоподібного сміття, а банер
   * на екрані ігнорується — саме тому, що виглядає як решта банерів.
   */
  'read.go': async () => {
    const c = RD.card || {};
    // Мішане письмо з латинкою третім голосом уже закрите одним проходом —
    // питати тут означало б лякати тим, від чого галочка й рятує.
    const bothScripts = ((RD.args || {}).also || []).length > 0;
    if (c.script === 'unknown' || (c.script === 'mixed' && !bothScripts)) {
      const why = c.script === 'mixed' ? t('read.confirm.mixed')
        : t('read.confirm.unknown');
      // eslint-disable-next-line no-alert
      if (!confirm(why)) return undefined;
    }
    const env = await callOp('read.start', RD.args || { case_dir: RD.case_dir });
    if (!env.ok) {
      const box = el('hits') || el('view');
      if (box) box.insertAdjacentHTML('afterbegin',
        `<div class="warn err">${esc(env.error)}</div>`);
      return undefined;
    }
    // 🔴 Прогін триває годинами — і саме тому людину не можна викидати з
    // картки, яку вона щойно налаштувала. Поступ і «Спинити» стають на картці
    // (`readNow`), а план запуску прибирається: він уже виконується.
    for (const model of RD.extra || []) {
      // eslint-disable-next-line no-await-in-loop
      await callOp('read.start', { case_dir: RD.case_dir, model, second_voice: false });
    }
    RD.extra = [];
    RD.prev = null;
    el('hits').innerHTML = '';
    return readCard();
  },

  /** ➕ Голос, якого бракує, — окремим прогоном своєю моделлю. */
  'read.addvoice': async (_ev, elm) => {
    const env = await callOp('read.start',
      { case_dir: RD.case_dir, model: elm.dataset.arg, second_voice: false });
    if (!env.ok) {
      el('card').insertAdjacentHTML('afterbegin', `<div class="warn err">${esc(env.error)}</div>`);
      return undefined;
    }
    return readCard();
  },

  /**
   * ✎ «Змінити» живе читання: спинити й відкрити ту саму форму з його
   * налаштуваннями — письмо, другий рушій, латинка третім голосом.
   */
  'read.change': async (_ev, elm) => {
    const res = await fetch('/api/jobs');
    const job = res.ok
      ? ((await res.json()).jobs || []).find((j) => j.id === elm.dataset.job) : null;
    const cfg = (job || {}).cfg || {};
    const voices = (cfg.voices || []).map(engineOf);
    await fetch(`/api/jobs/${encodeURIComponent(elm.dataset.job)}/cancel`,
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    RD = { ...RD, script: cfg.script || RD.script,
      prev: { second: voices.includes('diak'),
        latin: cfg.script !== 'latin' && voices.includes('skryba') } };
    return readCard();
  },

  /** 🖼 Подивитись аркуші перед тим, як віддавати ніч. */
  'read.frames': () => goto('frames', { case: RD.case_dir }),
});
