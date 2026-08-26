/** ⏳ Черга робіт. */

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




SCREENS.jobs = async () => {
  // 🔴 Кнопка «прибрати завершені» стоїть тут, а не в налаштуваннях: журнал
  // переживає перезапуски, і без неї перелік «Що зараз робиться» ставав
  // історією всього, що колись запускали. Свою щойно запущену роботу
  // доводилось шукати серед десятка однакових рядків — тобто екран, який має
  // відповідати «що зі мною зараз», відповідав «що тут колись бувало».
  setView(`<h2>${t('jobs.title')}</h2>
    <p><button data-act="jobs.forget">${t('jobs.forget')}</button></p>
    <div id="jobs"></div>`);
  await refreshJobs();
};

Object.assign(ACTIONS, {
  'jobs.forget': async () => {
    const res = await fetch('/api/jobs/forget',
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    if (!res.ok) {
      const box = el('jobs');
      const why = res.status === 403 ? t('err.token') : `HTTP ${res.status}`;
      if (box) box.insertAdjacentHTML('afterbegin', `<div class="warn err">${esc(why)}</div>`);
      return;
    }
    await refreshJobs();
  },

  'jobs.cancel': async (_ev, elm) => {
    // 🔴 Відповідь перевіряється. Сервер віддає 403 на протухлому токені й 404
    // на невідомій роботі; доти обидві відмови були нечутні: список
    // перемальовувався, робота лишалась «running», кнопка на місці — і людина
    // тиснула її знову й знову, поки прогін тримав карту.
    const res = await fetch(`/api/jobs/${encodeURIComponent(elm.dataset.job)}/cancel`,
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    if (!res.ok) {
      const env = await res.json().catch(() => ({}));
      const why = res.status === 403 ? t('err.token') : (env.detail || `HTTP ${res.status}`);
      const box = el('jobs');
      if (box) box.insertAdjacentHTML('afterbegin',
        `<div class="warn err">${esc(why)}</div>`);
      return;
    }
    await refreshJobs();
  },
});
