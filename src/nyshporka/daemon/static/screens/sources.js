/** 🔎 Джерела: де взагалі є документи. */

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




SCREENS.sources = async () => {
  setView(`
    <h2>${t('nav.sources')}</h2>
    <form class="row" data-act="sources.find">
      <input name="q" placeholder="${t('sources.q')}" autofocus>
      <button type="submit">${t('sources.find')}</button>
    </form>
    <div id="hits"></div>`);
};

Object.assign(ACTIONS, {
  'sources.find': async (ev) => {
    ev.preventDefault();
    const q = new FormData(ev.target).get('q');
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.search', { q, limit: 40 });
    if (!env.ok) return boxError('hits', env);
    const { hits = [], coverage = {} } = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.source)}</td>
        <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}</span></td>
        <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
        <td>${h.acquirable
          ? `<button data-act="sources.get" data-source="${esc(h.source)}" data-ref="${esc(h.ref)}">${t('sources.get')}</button>`
          : ''}</td>
      </tr>`).join('')}</tbody></table>
      <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
  },

  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    if (!env.ok) return alert(env.error);
    show('jobs');
  },
});
