/** 📤 Вивантаження. */

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




/** Остання вивантажена таблиця — щоб CSV збирався без повторного запиту. */
let LAST_EXPORT = null;

SCREENS.export = async () => {
  setView(`
    <h2>${t('nav.export')}</h2>
    <form class="row" data-act="export.run">
      <input name="case" placeholder="${t('export.case')}: ДАХмО 315-1-8433" autofocus>
      <select name="what">
        <option value="acts">${t('export.acts')}</option>
        <option value="records">${t('export.records')}</option>
        <option value="pages">${t('export.pages')}</option>
        <option value="tally">${t('export.tally')}</option>
      </select>
      <button type="submit">${t('export.run')}</button>
    </form>
    <div id="hits"></div>`);
};

Object.assign(ACTIONS, {
  'export.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('export.case',
      { case: fd.get('case'), what: fd.get('what') });
    if (!env.ok) return boxError('hits', env);
    const { columns = [], rows = [], labels = {} } = env.data;
    LAST_EXPORT = { columns, rows, labels,
      name: env.data.shifra || env.data.case };
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${rows.length ? `<button data-act="export.csv">${t('export.csv')}</button>` : ''}
      <table><thead><tr>${columns.map(
        (c) => `<th>${esc(labels[c] || c)}</th>`).join('')}</tr></thead>
      <tbody>${rows.slice(0, 200).map((r) => `<tr>${columns.map(
        (c) => `<td>${esc(String(r[c] ?? '').slice(0, 80))}</td>`).join('')}</tr>`).join('')}
      </tbody></table>
      <p class="muted">${rows.length} рядків</p>`;
  },

  // 🔴 CSV збирається на клієнті й зберігається діалогом браузера. Писати файл
  // кудись «у простір» тут не можна: людина вивантажує, щоб віднести дані в
  // чужу програму, і мусить сама сказати куди.
  'export.csv': () => {
    if (!LAST_EXPORT) return;
    const { columns, rows, labels = {}, name } = LAST_EXPORT;
    const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    // Шапка людськими словами — тими самими, що їх дає `export.write`. Мапа
    // приходить з відповіддю, а не складається тут: другий примірник назв
    // розійшовся б із першим мовчки.
    const head = columns.map((c) => cell(labels[c] || c)).join(',');
    const csv = [head, ...rows.map(
      (r) => columns.map((c) => cell(r[c])).join(','))].join('\r\n');
    // BOM — щоб Excel не з''їв кирилицю: без нього виписка відкривається
    // «крякозябрами», і виглядає це як зіпсовані дані, а не як кодування.
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${String(name).replace(/[^\w.-]+/g, '_')}.csv`;
    a.click();
    // ⚠ Не одразу: посилання не в документі, і Firefox історично рвав
    // завантаження, коли URL відкликали в тому ж такті, що й `click()`.
    const href = a.href;
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  },
});
