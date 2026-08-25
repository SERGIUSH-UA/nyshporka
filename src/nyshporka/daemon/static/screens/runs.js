/**
 * 📜 Прогони — що ця машина вже прочитала.
 *
 * Питання, на яке не відповідає ні черга робіт, ні бібліотека: черга знає, що
 * йде ЗАРАЗ, бібліотека — що є на диску, а «чим і наскільки прочитана ця
 * книга» не знає ніхто. Доти дізнатись це можна було лише набравши ім'я
 * прогону в гортачі — тобто вже знаючи відповідь.
 *
 * 🔴 Групування ЗА СПРАВОЮ, а не за датою. Єдине питання, заради якого цей
 * екран існує, — «чи покрите письмо цієї книги», і воно пер-справа. Плоский
 * перелік за часом розкидав би два прогони однієї книги на рядки 4 і 31, і
 * саме та відповідь, по яку прийшли, лишилась би невидимою.
 *
 * 🔴 Відсоток покриття малюється ЛИШЕ там, де є знаменник. Покриття, чий
 * знаменник дорівнює чисельнику, — це та сама вада, від якої існує правило
 * «нуль зі знаменником», просто в новому вбранні: воно завжди показує 100%.
 */
import { t, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, renderWarnings,
  curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';

/** Фільтр переліку. Живе між входами на екран, як і в бібліотеці. */
let RUNS = { q: '', engine: '', state: '' };

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
 * Та сама межа, що в бібліотеці: фільтр міняє ТІЛЬКИ видачу, бо повна
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
  const known = groups.filter((g) => g.key);
  const body = known.map(runsGroupHtml).join('')
    + orphans.map((g) => runsOrphanHtml(g)).join('');

  if (!full) {
    const box = el('runs-body');
    if (box) swapHtml(box, body || runsEmptyHtml(env, runs.length));
    return;
  }

  const engines = [...new Set(runs.map((r) => r.engine_id).filter(Boolean))];
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

function runsMatch(r) {
  if (RUNS.engine && (r.engine_id || '') !== RUNS.engine) return false;
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
  const badge = r.engine_id ? eng(r.engine_id, false, LANG) : '';
  const mark = r.done ? '✅' : '▶';
  // 🔴 Відсоток лише зі справжнім знаменником. Немає кадрів справи — друкуємо
  // самі сторінки: покриття, порахане від себе самого, завжди дорівнює 100%
  // і читається як «прочитано все».
  const n = Number(r.frames || 0);
  const cov = n ? `<td class="num">${Math.round(100 * (r.pages_done || 0) / n)}%</td>`
                : `<td class="num muted" title="${esc(t('runs.nodenom'))}">—</td>`;
  const fail = r.failed
    ? `<span class="warn-inline" title="${esc(t('runs.failed'))}">✗${r.failed}</span>`
    : '';
  return `<tr>
    <td>${mark} ${badge}</td>
    <td class="mono">${esc(r.model || '')}</td>
    <td class="num">${esc(r.pages_done || 0)}${n ? ` / ${esc(n)}` : ''}</td>
    ${cov}
    <td>${fail}</td>
    <td class="mono dim">${esc((r.updated || '').slice(0, 16))}</td>
    <td><button class="ctl-sm" data-act="runs.open" data-arg="${esc(r.name)}"
      title="${esc(t('runs.open'))}">${ic('page', 'ic-o ic-sm')}</button></td>
  </tr>`;
}

function runsGroupHtml(g) {
  const n = g.frames || 0;
  const gapline = runsGap(g);
  return `<section class="run-group" data-case="${esc(g.key)}">
    <h3 class="mono">${esc(g.shifra || g.key)}
      <span class="dim">${esc((g.title || '').slice(0, 70))}</span>
      ${n ? `<span class="dim">· ${esc(n)} ${t('common.frames')}</span>` : ''}</h3>
    <table><tbody>${g.runs.map(runsRow).join('')}</tbody></table>
    ${gapline}
  </section>`;
}

/**
 * 🔴 «Прогін є» мовчки читається як «справу прочитано».
 *
 * Саме так половина книги з двома письмами лишається непрочитаною: перший
 * прогін закриває своє письмо, у переліку з'являється галочка, і питання
 * знімається. Тому тут три РІЗНІ речення, а не спільне «щось не так».
 */
function runsGap(g) {
  const ids = new Set(g.runs.map((r) => r.engine_id).filter(Boolean));
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
function runsOrphanHtml(g) {
  return `<section class="run-group orphan">
    <h3>⚠ ${t('runs.orphan.title')}</h3>
    <p class="warn">${t('runs.orphan.why')}</p>
    <table><tbody>${g.runs.map((r) => `<tr>
      <td class="mono">${esc(r.name)}</td>
      <td class="num">${esc(r.pages_done || 0)}</td>
      <td class="mono dim">${esc(r.case_dir || '')}</td>
      <td><button class="ctl-sm" data-act="runs.open" data-arg="${esc(r.name)}"
        title="${esc(t('runs.open'))}">${ic('page', 'ic-o ic-sm')}</button></td>
    </tr>`).join('')}</tbody></table>
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
    };
    return runsLoad(false);
  },

  'runs.open': (_ev, elm) => {
    // Гортач сам відкриє першу сторінку прогону: імені сторінки тут ще ніхто
    // не знає, і вимагати його означало б повернути ту саму вимогу «набери
    // руками», заради зняття якої екран і зроблено.
    ST.view = { run: elm.dataset.arg, page: '', line: null };
    return show('view');
  },
});
