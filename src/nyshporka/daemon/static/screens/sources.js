/** 🔎 Каталоги: де взагалі є документи — поза цим комп'ютером. */

import { t } from '../core/strings.js';
import { callOp, FINAL_STATES } from '../core/net.js';
import { esc, safeHref, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';

/**
 * 🔎 Каталоги — зовнішні довідники: сайти архівів, покажчики плівок, Commons.
 *
 * 🔴 Не плутати з «Описами фондів»: там наш власний зібраний реєстр, і «немає»
 * означає «в архіві не існує». Тут — чужі каталоги, і «немає» означає лише
 * «немає в тих, куди ми змогли зазирнути». Два різні «немає», і на другому
 * напрям не закривають.
 *
 * 🔴 Перелік джерел зі станом кожного показується ДО пошуку, а не після.
 * Доти екран був одним полем вводу: людина набирала село, чекала одинадцять
 * секунд, діставала нуль — і не мала способу дізнатись, що шукали у зрізі
 * одного архіву дворічної давнини, а другий архів не переглядали взагалі.
 */
SCREENS.sources = async () => {
  const gen = curGen();
  // Прийшли з поради («пошукати, де взяти справи села») або з «Робіт» по
  // завершений пошук — запит уже відомий, і набирати його вдруге не треба.
  const seed = ST.sources || {};
  ST.sources = null;
  busy(4);
  const [env, jobs] = await Promise.all([callOp('sources.list', {}), recentJobs()]);
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data;
  setView(`
    <h2>${t('nav.sources')}</h2>
    <p class="muted">${t('sources.why')}</p>
    <form class="row" data-act="sources.find">
      <input name="q" placeholder="${t('sources.q')}" value="${esc(seed.q || '')}" autofocus>
      <button type="submit">${t('sources.find')}</button>
    </form>
    <div id="hits"></div>
    <h3>${t('sources.where')}</h3>
    ${renderWarnings(env)}
    <div id="src-table">${srcBlock(d)}</div>`);
  // Обходи, що йдуть, — у рядках своїх джерел: поступ там, звідки запускали.
  for (const j of jobs) {
    if (j.kind === 'catalog.crawl' && !FINAL_STATES.includes(j.state)) {
      watchCrawl(j.id, (j.cfg || {}).source || '');
    }
  }
  if (seed.q) return findNow();
  if (seed.job) return showSweep(await jobById(seed.job));
  return resumeSweep(jobs);
};

/** Роботи цього екрана: пошуки по каталогах і обходи — свіжі, за півдоби. */
async function recentJobs() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return [];
    const now = Date.now() / 1000;
    return ((await res.json()).jobs || [])
      .filter((j) => (j.kind === 'catalog.sweep' || j.kind === 'catalog.crawl')
        && now - (j.updated || 0) < 43200)
      .sort((a, b) => (b.updated || 0) - (a.updated || 0));
  } catch { return []; }
}

/** Робота за id — будь-якої давнини, бо з «Робіт» приходять і по старі. */
async function jobById(id) {
  try {
    const res = await fetch('/api/jobs');
    return res.ok ? ((await res.json()).jobs || []).find((j) => j.id === id) : null;
  } catch { return null; }
}

/** Запустити пошук із тим, що вже стоїть у полі. */
function findNow() {
  const form = el('view').querySelector('form[data-act="sources.find"]');
  if (!form) return undefined;
  return ACTIONS['sources.find']({ preventDefault() {}, target: form });
}

/**
 * 🔁 Повернувся на «Каталоги» — бачиш свій пошук.
 *
 * Той самий урок, що на «Пошуку»: пошук по каталогах — робота в черзі, і
 * доти, доки він жив лише в циклі опитування екрана, вихід з екрана губив і
 * поступ, і запит, і відповідь.
 */
async function resumeSweep(jobs) {
  const job = jobs.find((j) => j.kind === 'catalog.sweep');
  if (!job) return undefined;
  if (!FINAL_STATES.includes(job.state)) {
    setQuery((job.cfg || {}).q || '');
    const env = await pollFind(job.id);
    if (env) renderFind(env);
    return undefined;
  }
  if (job.state !== 'done') return undefined;
  setQuery((job.cfg || {}).q || '');
  const box = el('hits');
  if (!box) return undefined;
  const n = ((job.result || {}).hits || []).length;
  box.innerHTML = `<p class="muted">${esc(t('sources.last')
    .replace('{q}', (job.cfg || {}).q || '').replace('{t}', hhmmOf(job.updated))
    .replace('{n}', n))}
    <button class="ctl-sm" data-act="sources.last" data-job="${esc(job.id)}">${
  t('sources.last.show')}</button></p>`;
  return undefined;
}

const hhmmOf = (sec) => (sec ? new Date(sec * 1000).toTimeString().slice(0, 5) : '');

function setQuery(q) {
  const input = el('view') && el('view').querySelector('input[name="q"]');
  if (input) input.value = q;
}

/** Показати завершений пошук — з цього екрана чи з «Робіт». */
function showSweep(job) {
  if (!job || !job.result) return boxError('hits', { ok: false, error: t('sources.lost') });
  setQuery((job.cfg || {}).q || '');
  renderFind({ ok: true, data: job.result, warnings: job.warnings || [],
    next: job.next || [] });
  return undefined;
}

/**
 * Чекати пошук по каталогах, показуючи, КОГО ще чекаємо.
 *
 * 🔴 Пошук триває стільки, скільки найповільніше джерело, — Internet Archive
 * ходить чергою до archive.org і відповідає за пів хвилини й довше. Доти ці
 * секунди йшли під «Хвилинку…», і відрізнити повільне джерело від зависання
 * було нічим. Рядок від сервера каже поіменно, хто ще не відповів.
 */
async function pollFind(id) {
  let grace = 5;
  for (;;) {
    const res = await fetch('/api/jobs');
    const data = await res.json().catch(() => ({}));
    const job = (data.jobs || []).find((x) => x.id === id);
    if (!job) return { ok: false, error: t('sources.lost') };
    const box = el('hits');
    if (!box) return null;                // пішли з екрана — повернувшись, приєднаються
    const p = job.progress || {};
    const what = p.n
      ? t('sources.going').replace('{i}', p.i || 0).replace('{n}', p.n)
        .replace('{what}', p.basis || '')
      : t('sources.prep');
    box.innerHTML = `<div class="warn next">
      <button data-act="jobs.cancel" data-job="${esc(id)}">${t('jobs.cancel')}</button>
      <span>${esc(what)}</span></div>`;
    if (FINAL_STATES.includes(job.state)) {
      if (job.state === 'error') return { ok: false, error: job.error || t('job.failed') };
      // Спинений пошук теж має відповідь: ті джерела, що встигли, і чесне
      // «решту не опитано» в попередженнях. ⚠ Стан «спинено» стає одразу, а
      // відповідь доходить, коли пошук перестане чекати (до пів секунди), —
      // тож кілька опитувань її ще чекаємо.
      if (job.result) {
        return { ok: true, data: job.result, warnings: job.warnings || [],
          next: job.next || [] };
      }
      grace -= 1;
      if (grace <= 0) return { ok: false, error: t('sources.stopped') };
    }
    await new Promise((r) => setTimeout(r, 900));
  }
}

/** Знаменник і перелік джерел — одним шматком, щоб оновлювати їх разом. */
function srcBlock(d) {
  return `<p class="muted">${srcCount(d)}</p>${srcTable(d.sources || [])}`;
}

/**
 * Перемалювати лише перелік джерел — після обходу.
 *
 * ⚠ Не весь екран: людина в цей час може дивитись видачу пошуку, і обхід,
 * що скінчився, не має права її стерти.
 */
async function refreshSources() {
  const env = await callOp('sources.list', {});
  const box = el('src-table');
  if (!box || !env.ok) return;
  box.innerHTML = srcBlock(env.data);
}

/** 🔴 Знаменник екрана: скільки джерел уміють шукати й скільки мають на чому. */
function srcCount(d) {
  return esc(t('sources.count')
    .replace('{ok}', d.with_catalog ?? 0)
    .replace('{n}', d.searchable ?? 0)
    .replace('{all}', d.shown ?? 0));
}

function srcTable(rows) {
  return `<table><tbody>${rows.map((s) => {
    const c = s.catalog || {};
    return `<tr>
      <td><b>${esc(s.label)}</b><br>
        <span class="muted mono">${esc(s.id)}</span></td>
      <td>${srcCaps(s.caps || [])}</td>
      <td>${srcBasis(c)}</td>
      <td class="acts">${(s.caps || []).includes('browse')
        ? `<button class="ctl-sm" data-act="sources.browse" data-arg="${esc(s.id)}"
             title="${esc(t('sources.browse.why'))}">${t('sources.browse')}</button>`
        : ''}${crawlCell(s)}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
}

/** Що джерело вміє — знаками, бо їх читають краєм ока. */
function srcCaps(caps) {
  const bits = [];
  // Значки з набору, в один рядок: емодзі стояли стовпчиком і малювались
  // кожна система по-своєму.
  const one = (cap, name) => (caps.includes(cap)
    ? `<span title="${esc(t(`sources.cap.${cap}`))}">${ic(name, 'ic-o ic-sm')}</span>` : '');
  bits.push(one('search', 'search'), one('browse', 'list'), one('fetch', 'download'));
  return `<span class="caps">${bits.join('')}</span>`;
}

/**
 * На чому це джерело шукає.
 *
 * 🔴 Три стани, і плутати їх дорого: власний обхід (найсвіжіший), вкладений у
 * пакет зріз (датований, вужчий) і «нема на чому» — останнє означає, що нуль
 * від цього джерела не є відповіддю взагалі.
 */
function srcBasis(c) {
  if (!c.searchable) return `<span class="dim">${t('sources.nosearch')}</span>`;
  if (c.kind === 'none') {
    // 🔴 Без каталогу — ще не «пошук недоступний». ARCHIUM без зібраного
    // каталогу питає сам сайт, і поруч зі знахідками з нього напис «пошук
    // недоступний» був неправдою (холодний прохід 07.10.2026). Команда
    // терміналу людині теж не показується: каталог збирає кнопка поруч.
    return c.live
      ? `<span class="muted">${t('sources.live.site')}</span>`
      : `<span class="warn-inline">${t('sources.blind')}</span>`;
  }
  // 🔴 Живий запит — четвертий стан, а не зріз із порожньою датою. Нуль у
  // ньому означає «немає в покажчику зараз», а не «не було на дату зняття».
  const what = { workspace: t('sources.own'), live: t('sources.live') }[c.kind]
    || t('sources.bundled');
  const bits = [what];
  if (c.taken) bits.push(`${t('sources.taken')} ${esc(c.taken)}`);
  // Обхід спинили чи він обірвався — сказати це в самому рядку джерела, поруч
  // із кнопкою, що докінчує обхід.
  if (c.partial) {
    return `<span class="muted">${bits.join(' · ')}</span>
      <br><span class="warn-inline">${t('sources.partial')}</span>`;
  }
  if (c.rows) bits.push(`${esc(c.rows)} ${t('sources.rows')}`);
  if (c.scope) bits.push(esc(c.scope));
  return `<span class="muted">${bits.join(' · ')}</span>`;
}

/**
 * 🧭 Зібрати каталог джерела — кнопкою, з поступом у рядку джерела.
 *
 * 🔴 Доти тут стояла команда `nysh crawl …`: людині з браузера набирати її
 * нема куди, тож джерело без каталогу лишалось сліпим назавжди. Кнопка є лише
 * там, де обхід можливий, а каталог ще не свій; зібраний обхід оновлюється
 * тією самою кнопкою — він продовжується, а не починається наново.
 */
function crawlCell(s) {
  const c = s.catalog || {};
  if (!c.crawlable || !c.searchable) return '';
  const own = c.kind === 'workspace';
  return ` <span class="crawl-here" id="crawl-${esc(s.id)}">
    <button class="ctl-sm" data-act="sources.crawl" data-arg="${esc(s.id)}"
      title="${esc(t(own ? 'sources.crawl.again.why' : 'sources.crawl.why'))}">${
  t(own ? 'sources.crawl.again' : 'sources.crawl')}</button></span>`;
}

/** Поступ обходу в рядку його джерела — і «Спинити» там само. */
function watchCrawl(id, source) {
  const box = el(`crawl-${source}`);
  if (!box || !id) return;
  const paint = (j) => {
    const p = j.progress || {};
    if (FINAL_STATES.includes(j.state)) {
      // Каталог змінився — перелік джерел показує вже його обсяг і дату.
      if (j.state === 'done') { refreshSources(); return; }
      box.innerHTML = `${jobChip(j)}${(j.warnings || []).map((w) => `
        <span class="warn-inline">${esc(w.text || '')}</span>`).join('')}`;
      return;
    }
    box.innerHTML = `<span class="muted mono">${esc(p.n
      ? `${p.i}/${p.n} ${p.basis || ''}` : t('sources.crawl.prep'))}</span>
      <button class="ctl-sm" data-act="jobs.cancel" data-job="${esc(id)}">${
  t('jobs.cancel')}</button>`;
  };
  paint({ state: 'queued', progress: {} });
  onJob(id, paint);
}

/**
 * Що можна зробити зі знахідкою.
 *
 * 🔴 Джерело, яке не віддає файлів, теж мусить кудись вести. Зведений покажчик
 * знає про справу все, крім самої справи, — і без адреси його знахідка була б
 * рядком, з яким нічого не зробиш, а виглядало б це як тупик самого пошуку.
 * Кнопка «Завантажити» там, де за нею немає файлу, гірша за її відсутність.
 */
function hitAction(h) {
  if (h.acquirable) {
    return `<button data-act="sources.get" data-source="${esc(h.source)}"
      data-ref="${esc(h.ref)}">${t('sources.get')}</button>`;
  }
  return safeHref(h.url)
    ? `<a href="${safeHref(h.url)}" target="_blank" rel="noopener">${t('sources.open')}</a>`
    : '';
}

/**
 * Вирізка навколо слова — для джерел, що шукають у тексті сканів.
 *
 * 🔴 Без неї знахідка в тексті — лише обіцянка: чи це прізвище, чи OCR-калік
 * сусіднього слова, видно тільки на зображенні, а до нього інакше треба
 * завантажити цілу справу.
 */
function hitCrop(h) {
  const src = safeHref(h.crop_url);
  if (!src) return '';
  const href = safeHref(h.url) || src;
  return `<br><a href="${href}" target="_blank" rel="noopener"><img class="hit-crop"
    loading="lazy" src="${src}" alt=""></a>`;
}

/**
 * 🏛 Фонди, у яких знайшлось, — над списком справ, а не замість нього.
 *
 * 🔴 Пошук по каталогах не самоціль: за ним іде рішення «чи збирати реєстр
 * цього фонду», а воно про ФОНД, не про окрему справу. Плаский список трьох
 * томів одного фонду й трьох випадкових збігів із трьох архівів виглядає
 * однаково, і звідки прийшла знахідка, доводилось вичитувати з шифри очима.
 *
 * Джерела, які фондів не знають (дзеркало адресує плівки), сюди не потрапляють
 * — і саме тому сума по фондах буває меншою за видачу.
 */
function fondsBlock(fonds) {
  if (!fonds.length) return '';
  return `<h3>${t('sources.fonds')}</h3>
    <table><tbody>${fonds.map((f) => `<tr>
      <td><b>${esc(f.label || '?')} ф.${esc(f.fond)}</b><br>
        <span class="muted">${esc(f.sample || '')}</span></td>
      <td class="num">${esc(f.hits)} ${t('sources.fond.hits')}</td>
      <td class="mono">${f.year_from ? `${esc(f.year_from)}–${esc(f.year_to)}` : ''}</td>
      <td class="mono muted">${esc((f.sources || []).join(', '))}</td>
      <td><button data-act="sources.fond" data-repo="${esc(f.repo || f.archive || '')}"
        data-fond="${esc(f.fond)}"
        title="${esc(t('sources.fond.why'))}">${t('sources.fond')}</button></td>
    </tr>`).join('')}</tbody></table>`;
}

/**
 * Картка фонду: чужий покажчик і наш власний стан поруч.
 *
 * 🔴 Обидві половини разом, і це не оформлення. Фонд, який виглядає цікавим,
 * регулярно виявляється вже зібраним — а поки «що це за фонд» і «чи є він у
 * нас» жили на різних екранах, дізнавались про це після збирання.
 */
function fondCard(d) {
  const c = d.card || {};
  const o = d.ours || {};
  const opys = (c.opys || []).map((i) => `<tr>
      <td class="mono">${t('sources.fond.opys')} ${esc(i.opys)}</td>
      <td class="mono">${esc(i.years || '')}</td>
      <td>${esc(i.title || '')}</td>
    </tr>`).join('');
  const ours = o.has_registry
    ? `<b>${esc(o.rows)}</b> ${t('sources.fond.rows')} ·
       ${esc(o.on_disk)} ${t('sources.fond.ondisk')}`
    : `<span class="warn-inline">${t('sources.fond.noregistry')}</span>`;
  return `<div class="box">
    <h3>${esc(d.repo || '')} ф.${esc(d.fond)}</h3>
    <p>${esc(c.title || '')} ${c.years ? `<span class="mono">${esc(c.years)}</span>` : ''}</p>
    <p class="muted">${t('sources.fond.ours')}: ${ours}</p>
    ${opys ? `<table><tbody>${opys}</tbody></table>` : ''}
    ${safeHref(c.url) ? `<p><a href="${safeHref(c.url)}" target="_blank" rel="noopener">${t('sources.open')}</a></p>` : ''}
  </div>`;
}

/** Скільки знахідок просимо: стеля видачі, про яку екран попереджає. */
const FIND_LIMIT = 40;

/** Видача пошуку по каталогах — з роботи чи з минулого пошуку однаково. */
function renderFind(env) {
  if (!env.ok) return boxError('hits', env);
  const { hits = [], fonds = [], coverage = {} } = env.data || {};
  el('hits').innerHTML = `
    ${renderWarnings(env)}
    ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
    ${fondsBlock(fonds)}
    <div id="fondcard"></div>
    <table><tbody>${hits.map((h) => `<tr>
      <td class="mono">${esc(h.source)}</td>
      <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}
        ${esc(h.note || '')}</span>${hitCrop(h)}</td>
      <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
      <td>${hitAction(h)}</td>
    </tr>`).join('')}</tbody></table>
    ${hits.length >= FIND_LIMIT
    ? `<p class="warn-inline">${esc(t('sources.ceiling').replace('{n}', FIND_LIMIT))}</p>`
    : ''}
    <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
  return undefined;
}

Object.assign(ACTIONS, {
  /**
   * 🔎 Пошук по каталогах — роботою в черзі, з поступом по джерелах.
   *
   * ⚠ Агент і термінал питають той самий пошук синхронно (`catalog.search`);
   * тут — `catalog.sweep`, бо пів хвилини синхронного запиту в браузері
   * виглядають як зависання і не спиняються.
   */
  'sources.find': async (ev) => {
    ev.preventDefault();
    const q = String(new FormData(ev.target).get('q') || '').trim();
    if (!q) return undefined;
    const unlock = busyForm(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('sources.prep')}</p>`;
    const started = await callOp('catalog.sweep', { q, limit: FIND_LIMIT });
    const env = started.ok ? await pollFind((started.data || {}).job_id || '') : started;
    unlock();
    if (env) renderFind(env);
    return undefined;
  },

  /** Показати завершений пошук по каталогах. */
  'sources.last': async (_ev, elm) => showSweep(await jobById(elm.dataset.job)),

  /** 🧭 Зібрати каталог джерела. Поступ — у рядку джерела, не в «Роботах». */
  'sources.crawl': async (_ev, elm) => {
    const source = elm.dataset.arg;
    const env = await callOp('catalog.crawl', { source });
    if (!env.ok) {
      const box = el(`crawl-${source}`);
      if (box) box.innerHTML = `<span class="warn-inline">${esc(env.error)}</span>`;
      return undefined;
    }
    watchCrawl((env.data || {}).job_id || '', source);
    return undefined;
  },

  /** 🏛 Оцінити фонд перед тим, як збирати його реєстр опису. */
  'sources.fond': async (_ev, elm) => {
    const box = el('fondcard');
    box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.fond',
      { repo: elm.dataset.repo, fond: elm.dataset.fond });
    if (!env.ok) return boxError('fondcard', env);
    box.innerHTML = `${renderWarnings(env)}${fondCard(env.data)}`;
    return undefined;
  },

  /** 🌳 Що взагалі лежить у цьому джерелі — до всякого запиту. */
  'sources.browse': async (_ev, elm) => {
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.browse', { source: elm.dataset.arg });
    if (!env.ok) return boxError('hits', env);
    const nodes = env.data.nodes || [];
    el('hits').innerHTML = `${renderWarnings(env)}
      ${nodes.length ? `<table><tbody>${nodes.map((n) => `<tr>
        <td class="mono">${esc(n.ref || '')}</td>
        <td>${esc(n.label || '')}</td>
        <td class="num">${n.frames ? `${n.frames} ${t('common.frames')}` : ''}</td>
      </tr>`).join('')}</tbody></table>`
        : `<p class="muted">${t('sources.nonodes')}</p>`}
      ${renderCoverage(env)}`;
    return undefined;
  },

  /**
   * ⬇ Забрати знахідку з джерела — і показати це рядком знахідки.
   *
   * 🔴 Завантаження триває довго, а людина в цей час дивиться на видачу
   * пошуку: який саме результат вона взяла, видно лише тут. У переліку робіт
   * цього не видно взагалі, тож перекидання туди міняло зрозумілий стан на
   * незрозумілий.
   */
  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    const near = elm.parentElement;
    if (!env.ok) {
      if (near) near.insertAdjacentHTML('beforeend',
        `<span class="warn-inline">${esc(env.error)}</span>`);
      return undefined;
    }
    elm.disabled = true;                  // друге натискання = друга закачка
    const id = (env.data || {}).job_id;
    if (near && id) {
      // ⚠ Вузол створюється й тримається ПОСИЛАННЯМ. `:last-of-type` рахує
      // останній елемент СВОГО ТИПУ, а не останній із цим класом, — у рядку з
      // кількома `<span>` він знайшов би чужий, і прогрес одного завантаження
      // писався б у сусідній результат пошуку.
      const chip = document.createElement('span');
      chip.className = 'job-here';
      chip.innerHTML = jobChip({ state: 'queued', progress: {} });
      near.appendChild(chip);
      onJob(id, (j) => { chip.innerHTML = jobChip(j); });
    }
    return undefined;
  },
});
