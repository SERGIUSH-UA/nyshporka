/** 🔎 Пошук у прочитаному. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ, FINAL_STATES } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive, maskot } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav,
  refreshJobs, onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';




SCREENS.search = async () => {
  // Справа з бібліотеки: пошук у її межах — інше питання, ніж пошук по всьому
  // прочитаному, і знаменник у відповіді буде інший.
  const only = (ST.search || {}).case || '';
  // Прийшли з «Робіт» по завершений пошук — показати саме його.
  const fromJob = (ST.search || {}).job || '';
  ST.search = null;
  setView(`
    <h2>${t('nav.search')}</h2>
    ${only ? `<p class="muted">${t('search.only')}
      <span class="mono">${esc(only)}</span></p>` : ''}
    <form class="row" data-act="search.run">
      <input name="case" type="hidden" value="${esc(only)}">
      <input name="q" placeholder="${t('search.q')}" autofocus>
      <select name="where">
        <option value="decode">${t('search.where.decode')}</option>
        <option value="pages">${t('search.where.pages')}</option>
        <option value="records">${t('search.where.records')}</option>
      </select>
      <button type="submit">${t('search.run')}</button>
    </form>
    <div id="prof-hint"></div>
    <div id="hits"><div class="search-idle">${maskot('lupa', 130)}</div></div>
    <div id="search-index"></div>`);
  // Спершу — свій пошук, що йде чи щойно скінчився: його запит у полі важливіший
  // за прізвище з профілю, яке підставляє `profileHint` у порожнє поле.
  if (fromJob) await ACTIONS['search.last'](null, { dataset: { job: fromJob } });
  else if (!only) await resumeSweep();
  await profileHint();
  if (!only) await searchIndexState();
};

/**
 * 🔁 Повернувся на «Пошук» — бачиш свій пошук.
 *
 * 🔴 Пошук по всьому прочитаному — фонова робота, і доти вона жила лише в
 * циклі опитування на цьому екрані: варто було піти й повернутись, як рядок
 * поступу зникав, у полі знову стояло прізвище з профілю, а результат лишався
 * в роботі, якої «Роботи» не показують (холодний прохід 07.10.2026: «готово»
 * через 24 хв, результату ніде). Тепер екран знаходить останній пошук сам:
 * той, що йде, — показує його поступ і чекає; завершений за півдоби — дає
 * показати.
 */
async function resumeSweep() {
  const job = await lastSweep();
  if (!job) return;
  const q = (job.cfg || {}).q || '';
  const input = el('view').querySelector('input[name="q"]');
  if (input) input.value = q;
  if (!FINAL_STATES.includes(job.state)) {
    const env = await pollSweep(job.id);
    if (env && env.ok) renderHits(env, q, 'decode');
    else if (env) boxError('hits', env);
    return;
  }
  const box = el('hits');
  if (!box || job.state !== 'done') return;
  const n = ((job.result || {}).hits || []).length;
  box.innerHTML = `<p class="muted">${esc(t('search.last')
    .replace('{q}', q).replace('{t}', hhmmOf(job.updated)).replace('{n}', n))}
    <button class="ctl-sm" data-act="search.last" data-job="${esc(job.id)}">${
  t('search.last.show')}</button></p>`;
}

/** Останній пошук по всьому прочитаному за півдоби — або нічого. */
async function lastSweep() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return null;
    const now = Date.now() / 1000;
    return ((await res.json()).jobs || [])
      .filter((j) => j.kind === 'search.sweep' && now - (j.updated || 0) < 43200)
      .sort((a, b) => (b.updated || 0) - (a.updated || 0))[0] || null;
  } catch { return null; }
}

const hhmmOf = (sec) => (sec ? new Date(sec * 1000).toTimeString().slice(0, 5) : '');

/**
 * Написання з профілю — під полем пошуку.
 *
 * 🔴 Це та ланка, заради якої профіль узагалі просять заповнити. Доти він був
 * формою, що нікуди не веде: жодна операція пошуку його не читала, `q`
 * лишалось обов'язковим, і людина щоразу пригадувала написання сама — саме
 * там, де рушій калічить середину слова й де пригадати їх найважче.
 *
 * ⚠ Поле лише ЗАПОВНЮЄТЬСЯ, а не замикається на профілі. Шукають і сусідів, і
 * конфузерів, і геть чуже прізвище; підставити прізвище роду назавжди означало
 * б забрати екран у половини його роботи.
 */
async function profileHint() {
  const box = el('prof-hint');
  if (!box) return;
  const env = await callOp('profile.show', {});
  if (!env.ok) return;
  const d = env.data || {};
  const input = el('view').querySelector('input[name="q"]');
  if (!d.present) {
    box.innerHTML = `<p class="muted">${t('search.noprofile')}
      <button class="ctl-sm" data-act="nav" data-arg="profile">${
      t('step.go')}</button></p>`;
    return;
  }
  if (input && !input.value) input.value = d.display || '';
  const sp = d.spellings || [];
  if (!sp.length) return;
  // Згорнуто: стіна з десятків написань стояла між полем запиту й видачею.
  // Число в заголовку — усі написання, і розкриття показує всі, а не перші 40.
  box.innerHTML = `<details class="notes"><summary>${t('search.forms')} (${sp.length})</summary>
    <div class="prof-forms">${sp.map((x) =>
      `<button class="chip" data-act="search.form" data-arg="${esc(x)}"
        >${esc(x)}</button>`).join('')}</div></details>`;
}

/**
 * Стан індексу прочитаного — ДО пошуку, а не після.
 *
 * 🔴 Це знаменник цього екрана. Пошук чеше лише зібране, і «не знайшлось»
 * означає зовсім різне при повному й частковому індексі. Доти людина цього не
 * бачила взагалі: відповідь приходила однакова, а покривала різне.
 *
 * ⚠ Питається лише при пошуку по всьому прочитаному: у межах однієї справи
 * індекс збирається на місці за секунди, і питання «скільки лишилось» там не
 * стоїть.
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

/**
 * Прочесати все прочитане — роботою в черзі, з видимим поступом.
 *
 * 🔴 Поступ тут не оздоблення. Робота триває хвилини, і без числа вона нічим
 * не відрізняється від зависання — а спинити те, чого не видно, неможливо.
 *
 * Повертає конверт із результатом роботи, тобто рівно те саме, що віддав би
 * синхронний пошук: екран далі не знає, яким шляхом прийшла відповідь.
 */
async function sweepJob(q) {
  const started = await callOp('search.sweep', { q, limit: 100, context: 1 });
  if (!started.ok) return started;
  return pollSweep((started.data || {}).job_id || '');
}

/**
 * Чекати пошук, показуючи, ЩО саме він робить.
 *
 * 🔴 Фаза — частина поступу. «Прогін 0 із 0» висіло, поки пошук індексував
 * нові прогони чи прочісував блоки корпусу, — і виглядало як зависання. Тепер
 * рядок каже фазу словами від сервера («індекс нових прогонів 3 із 8», «блоки
 * корпусу 12 із 40»), а до першого числа — «готуємо пошук».
 */
async function pollSweep(id) {
  for (;;) {
    const res = await fetch('/api/jobs');
    const data = await res.json().catch(() => ({}));
    const job = (data.jobs || []).find((x) => x.id === id);
    if (!job) return { ok: false, error: t('search.sweep.lost') };
    // Людина пішла з екрана — опитувати далі нема для кого; повернувшись, вона
    // приєднається знову (`resumeSweep`).
    const box = el('hits');
    if (!box) return null;
    const p = job.progress || {};
    const what = p.n
      ? t('search.sweep.going').replace('{what}', p.basis || '')
        .replace('{i}', p.i || 0).replace('{n}', p.n)
      : t('search.sweep.prep');
    box.innerHTML = `<div class="warn next">
      <button data-act="jobs.cancel" data-job="${esc(id)}">${t('jobs.cancel')}</button>
      <span>${esc(what)}</span></div>`;
    if (FINAL_STATES.includes(job.state)) {
      if (job.state === 'cancelled') {
        // Спинили — це не збій і не відповідь: обрізаний свіп нічого не
        // доводить, тож і показувати з нього нічого.
        return { ok: false, error: t('search.stopped') };
      }
      if (job.state !== 'done') {
        return { ok: false, error: job.error || t('job.failed') };
      }
      // 🔴 Застереження роботи не губляться: саме в них живе знаменник —
      // скільки прогонів прочесано й скільки лишилось поза індексом.
      return { ok: true, data: job.result || {}, warnings: job.warnings || [] };
    }
    await new Promise((r) => setTimeout(r, 900));
  }
}

/**
 * Видача пошуку — один шлях для нового пошуку, відновленого й показаного з
 * «Робіт». Два шляхи малювання того самого розходились би: колонки в одному,
 * знаменник в іншому.
 */
function renderHits(env, q, where) {
  const hits = env.data.hits || [];
  const cov = env.data.coverage || {};
  // Хіти лишаються під рукою: розбір відкривається з них, а не переповторює
  // пошук — інакше два екрани показували б різні набори того самого запиту.
  ST.sift = { hits: hits.filter((h) => h.name && h.page), i: 0,
           q, crop: null, ctx: null };
  const total = Number(env.data.total ?? hits.length);
  const head = where === 'records' ? t('search.col.role') : t('search.col.page');
  const box = el('hits');
  if (!box) return;
  box.innerHTML = `
    ${renderWarnings(env)}
    <p class="muted search-count">${esc((total > hits.length ? t('search.count.cut') : t('search.count'))
  .replace('{n}', hits.length).replace('{all}', total))}</p>
    ${ST.sift.hits.length
      ? `<p><button data-act="sift.open">${ic('crop-check', 'ic-sm')}
           ${t('sift.open')}</button></p>` : ''}
    ${hits.length ? `<table><thead><tr><th>${t('search.col.case')}</th><th>${head}</th>
      <th>${t('search.col.text')}</th><th class="num">${t('search.col.score')}</th><th></th>
    </tr></thead><tbody>${hits.map((h) => {
      // 🔴 records-хіт — інша форма, не підмножина decode/pages-хіта: там
      // немає `page`/`scan` (однина) взагалі, замість `matched`/`line`/
      // `text`/`surname` — `name`/`role`/`date`, а `scans` (множина) буває
      // або локальним файлом справи, або зовнішньою цитатою (посилання на
      // джерело запису, занесеного напряму через `records add` без скана).
      // Плутати два рендери під один шаблон означало для records-режиму
      // порожні колонки на кожному хіті без винятку — issue #4.
      const isRec = where === 'records';
      const where_col = isRec ? (h.role || '') : (h.page || h.scan || '');
      // 🔴 Місце йде в контекст нарівні з іменем. Однофамільця від
      // односельця відрізняє саме воно: прізвище в парафії повторюється
      // частіше, ніж здається, і рядок без місця лишає хіт нерозрізненим —
      // тобто повертає рівно ту роботу, заради якої пошук і кликали.
      const ctx = isRec
        ? [h.name, h.date, h.place].filter(Boolean).join(' · ')
        : (h.matched || h.line || h.text || h.surname || '');
      // ✎ веде на «Око» голим іменем файлу (див. `PageNote.scan`); цитата
      // без скана — це URL чи інший шлях зі скісною, і показувати кнопку,
      // яка там гарантовано впаде валідацією, гірше за її відсутність.
      const scan0 = isRec ? ((h.scans && h.scans[0]) || '') : (h.scan || h.page || '');
      // ⚠ Перевірка повторює валідатор `PageNote.scan` ЦІЛКОМ, а не
      // наполовину: він відкидає і шлях, і провідну крапку. Неповна копія
      // тут гірша за її відсутність — кнопка малюється, а падає вже після
      // кліку, тобто помилку видно там, де її причини не видно.
      const scan0Local = scan0 && !/^\.|[\\/]/.test(scan0);
      return `<tr>
      <td class="mono">${esc(h.shifra || h.case_key || h.case || '')}</td>
      <td class="mono">${esc(where_col)}</td>
      <td>${esc(String(ctx).slice(0, 120))}</td>
      <td class="num">${esc(h.score ?? '')}</td>
      <td class="acts">${/* 🔴 Виявити ≠ перевірити: машина подає кандидата, вирішує око.
               Доти хіт був рядком таблиці — щоб глянути на нього, треба було
               переписати прогін і сторінку в гортач руками, а це та сама
               дія, заради якої пошук і робився. */''}
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
    }).join('')}</tbody></table>` : ''}
    ${cov.runs !== undefined
      ? `<p class="muted">${t('search.coverage')}: ${cov.runs} ${t('search.runs')}, ${cov.pages} ${t('common.pages')}</p>`
      : cov.cases !== undefined
        ? `<p class="muted">${t('search.coverage')}: ${cov.cases} ${t('search.cases')}</p>`
        : ''}`;
}

Object.assign(ACTIONS, {
  /**
   * Клік по написанню — підставити його в поле й шукати одразу.
   *
   * ⚠ Саме шукати, а не лише підставити: написань буває тридцять, і перебирати
   * їх мишею до поля й назад означає тридцять зайвих кліків там, де вся суть у
   * швидкому переборі.
   */
  'search.form': (_ev, elm) => {
    const input = el('view').querySelector('input[name="q"]');
    if (!input) return undefined;
    input.value = elm.dataset.arg;
    const form = input.closest('form');
    return form ? ACTIONS['search.run']({ preventDefault() {}, target: form })
                : undefined;
  },

  /**
   * Зібрати індекс прочитаного.
   *
   * 🔴 Робота довга (чверть години на великому корпусі) і йде в чергу — туди ж
   * і ведемо. Кнопка, після якої нічого видимо не сталось, натискається вдруге.
   */
  'search.index': async () => {
    const env = await callOp('search.index', {});
    const box = el('hits');
    if (!env.ok) {
      if (box) box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return undefined;
    }
    // Індекс збирається хвилинами; людина в цей час дивиться на свій запит, а
    // не на чергу. Готовий індекс міняє саме те, що вона бачить, — тож після
    // завершення видача перечитується сама.
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

  'search.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const seq = ++SEQ.search;
    const unlock = busyForm(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    // 🔴 `context: 1` проситься тут, а не добирається потім окремим запитом:
    // рядок сам по собі не розрізняє прізвищ зі спільним коренем, бо ім'я
    // стоїть вище, а роль нижче. Разом із вікном приходить читання того самого
    // рядка другим рушієм — те, чого другим запитом не дістати взагалі.
    const only = String(fd.get('case') || '');
    const where = String(fd.get('where') || 'decode');
    // 🔴 Той самий пошук, але двома шляхами, і межа не в тому, ЩО робиться, а
    // скільки це триває. У межах справи — частка секунди, тож синхронно. По
    // всьому прочитаному — хвилини, і синхронний запит виглядав би в браузері
    // рівно як зависання: сторінка не відповідає й не каже, чому.
    const env = (!only && where === 'decode')
      ? await sweepJob(String(fd.get('q') || ''))
      : await callOp('search.run',
        { q: fd.get('q'), where, limit: 100, context: 1, case: only });
    unlock();
    if (seq !== SEQ.search) return;
    if (!env) return undefined;                // роботу спинили
    if (!env.ok) return boxError('hits', env);
    renderHits(env, String(fd.get('q') || ''), where);
    return undefined;
  },

  /** Показати завершений пошук — з «Пошуку» чи з «Робіт». */
  'search.last': async (_ev, elm) => {
    const res = await fetch('/api/jobs');
    const job = res.ok
      ? ((await res.json()).jobs || []).find((j) => j.id === elm.dataset.job) : null;
    if (!job || !job.result) return boxError('hits', { ok: false, error: t('search.sweep.lost') });
    const input = el('view').querySelector('input[name="q"]');
    if (input) input.value = (job.cfg || {}).q || '';
    renderHits({ ok: true, data: job.result, warnings: job.warnings || [] },
      (job.cfg || {}).q || '', 'decode');
    return undefined;
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
