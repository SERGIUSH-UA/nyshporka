/** 🔎 Пошук у прочитаному. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav,
  refreshJobs } from '../core/nav.js';
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
    <div id="hits"></div>
    <div id="search-index"></div>`);
  if (!only) await searchIndexState();
};

/**
 * Стан індексу прочитаного — ДО пошуку, а не після.
 *
 * 🔴 Це знаменник цього екрана. Пошук чеше лише зібране, і «не знайшлось»
 * означає зовсім різне при повному й частковому індексі. Доти людина цього не
 * бачила взагалі: відповідь приходила однакова, а покривала різне.
 *
 * ⚠ Питається лише при пошуку по ВСЬОМУ прочитаному: у межах однієї справи
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

Object.assign(ACTIONS, {
  /**
   * Зібрати індекс прочитаного.
   *
   * 🔴 Робота довга (чверть години на великому корпусі) і йде в чергу — туди ж
   * і ведемо. Кнопка, після якої нічого видимо не сталось, натискається вдруге.
   */
  'search.index': async () => {
    const env = await callOp('search.index', {});
    if (!env.ok) return alert(env.error);
    return show('jobs');
  },

  'search.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const seq = ++SEQ.search;
    const unlock = busyForm(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    // 🔴 `context: 1` проситься ТУТ, а не добирається потім окремим запитом:
    // рядок сам по собі не розрізняє прізвищ зі спільним коренем, бо ім'я
    // стоїть вище, а роль нижче. Разом із вікном приходить читання того самого
    // рядка другим рушієм — те, чого другим запитом не дістати взагалі.
    const env = await callOp('search.run',
      { q: fd.get('q'), where: fd.get('where'), limit: 100, context: 1,
        case: String(fd.get('case') || '') });
    unlock();
    if (seq !== SEQ.search) return;
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
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.shifra || h.case || h.key || h.name || '')}</td>
        <td class="mono">${esc(h.page || h.scan || '')}</td>
        <td>${esc(String(h.matched || h.line || h.text || h.surname || '').slice(0, 120))}</td>
        <td class="num">${esc(h.score ?? '')}</td>
        <td>${/* 🔴 Виявити ≠ перевірити: машина подає кандидата, вирішує око.
                 Доти хіт був рядком таблиці — щоб глянути на нього, треба було
                 переписати прогін і сторінку в гортач руками, а це та сама
                 дія, заради якої пошук і робився. */''}
          ${h.name && h.page
            ? `<button data-act="hit.eye" data-run="${esc(h.name)}"
                 data-page="${esc(h.page)}"
                 data-line="${esc(h.line_index ?? '')}"
                 title="${t('hit.eye')}">👁</button>` : ''}
          ${(h.key || h.shifra) && (h.scan || h.page)
            ? `<button data-act="hit.note" data-case="${esc(h.key || h.shifra)}"
                 data-scan="${esc(h.scan || h.page)}"
                 title="${t('hit.note')}">✎</button>` : ''}
        </td>
      </tr>`).join('')}</tbody></table>
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
