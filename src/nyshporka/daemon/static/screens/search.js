/** 🔎 Пошук у прочитаному. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ, FINAL_STATES } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
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
    <div id="hits"></div>
    <div id="search-index"></div>`);
  await profileHint();
  if (!only) await searchIndexState();
};

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
  box.innerHTML = `<p class="muted">${t('search.forms')} (${sp.length}):</p>
    <div class="prof-forms">${sp.slice(0, 40).map((x) =>
      `<button class="chip" data-act="search.form" data-arg="${esc(x)}"
        >${esc(x)}</button>`).join('')}</div>`;
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
  const id = (started.data || {}).job_id || '';
  const box = el('hits');
  for (;;) {
    const res = await fetch('/api/jobs');
    const data = await res.json().catch(() => ({}));
    const job = (data.jobs || []).find((x) => x.id === id);
    if (!job) return { ok: false, error: t('search.sweep.lost') };
    if (box) {
      const p = job.progress || {};
      box.innerHTML = `<div class="warn next">
        <button data-act="jobs.cancel" data-job="${esc(id)}">${t('jobs.cancel')}</button>
        <span>${esc(t('search.sweep.going')
          .replace('{i}', p.i || 0).replace('{n}', p.n || 0))}</span></div>`;
    }
    if (FINAL_STATES.includes(job.state)) {
      if (job.state !== 'done') {
        return { ok: false, error: job.error || job.state };
      }
      // 🔴 Застереження роботи не губляться: саме в них живе знаменник —
      // скільки прогонів прочесано й скільки лишилось поза індексом.
      return { ok: true, data: job.result || {}, warnings: job.warnings || [] };
    }
    await new Promise((r) => setTimeout(r, 900));
  }
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
    const hits = env.data.hits || [];
    const cov = env.data.coverage || {};
    // Хіти лишаються під рукою: розбір відкривається з них, а не переповторює
    // пошук — інакше два екрани показували б різні набори того самого запиту.
    ST.sift = { hits: hits.filter((h) => h.name && h.page), i: 0,
             q: String(fd.get('q') || ''), crop: null, ctx: null };
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${ST.sift.hits.length
        ? `<p><button data-act="sift.open">${ic('crop-check', 'ic-sm')}
             ${t('sift.open')}</button></p>` : ''}
      <table><tbody>${hits.map((h) => {
        // 🔴 records-хіт — інша форма, не підмножина decode/pages-хіта: там
        // немає `page`/`scan` (однина) взагалі, замість `matched`/`line`/
        // `text`/`surname` — `name`/`role`/`date`, а `scans` (множина) буває
        // або локальним файлом справи, або зовнішньою цитатою (посилання на
        // джерело запису, занесеного напряму через `records add` без скана).
        // Плутати два рендери під один шаблон означало для records-режиму
        // порожні колонки на кожному хіті без винятку — issue #4.
        const isRec = where === 'records';
        const where_col = isRec ? (h.role || '') : (h.page || h.scan || '');
        const ctx = isRec
          ? [h.name, h.date].filter(Boolean).join(' · ')
          : (h.matched || h.line || h.text || h.surname || '');
        // ✎ веде на «Око» голим іменем файлу (див. `PageNote.scan`); цитата
        // без скана — це URL чи інший шлях зі скісною, і показувати кнопку,
        // яка там гарантовано впаде валідацією, гірше за її відсутність.
        const scan0 = isRec ? ((h.scans && h.scans[0]) || '') : (h.scan || h.page || '');
        const scan0Local = scan0 && !/[\\/]/.test(scan0);
        return `<tr>
        <td class="mono">${esc(h.shifra || h.case_key || h.case || '')}</td>
        <td class="mono">${esc(where_col)}</td>
        <td>${esc(String(ctx).slice(0, 120))}</td>
        <td class="num">${esc(h.score ?? '')}</td>
        <td>${/* 🔴 Виявити ≠ перевірити: машина подає кандидата, вирішує око.
                 Доти хіт був рядком таблиці — щоб глянути на нього, треба було
                 переписати прогін і сторінку в гортач руками, а це та сама
                 дія, заради якої пошук і робився. */''}
          ${!isRec && h.name && h.page
            ? `<button data-act="hit.eye" data-run="${esc(h.name)}"
                 data-page="${esc(h.page)}"
                 data-line="${esc(h.line_index ?? '')}"
                 title="${t('hit.eye')}">👁</button>` : ''}
          ${(h.key || h.shifra) && scan0Local
            ? `<button data-act="hit.note" data-case="${esc(h.key || h.shifra)}"
                 data-scan="${esc(scan0)}"
                 title="${t('hit.note')}">✎</button>` : ''}
        </td>
      </tr>`;
      }).join('')}</tbody></table>
      ${cov.runs !== undefined
        ? `<p class="muted">${t('search.coverage')}: ${cov.runs} ${t('search.runs')}, ${cov.pages} ${t('common.pages')}</p>`
        : cov.cases !== undefined
          ? `<p class="muted">${t('search.coverage')}: ${cov.cases} ${t('search.cases')}</p>`
          : ''}`;
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
