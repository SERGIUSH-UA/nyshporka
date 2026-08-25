/** 🖋 Читання справи рушієм. */

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




/** Остання тека, для якої рахували план читання. */
let LAST_READ = null;

SCREENS.read = async () => {
  setView(`
    <h2>${t('nav.read')}</h2>
    <form class="row" data-act="read.plan">
      <input name="case_dir" placeholder="${t('read.dir')}" autofocus>
      <select name="script">
        <option value="">${t('read.script')}: авто</option>
        <option value="cyrillic">кирилиця</option>
        <option value="latin">латинка</option>
      </select>
      <button type="submit">${t('read.plan')}</button>
    </form>
    <div id="hits"></div>`);
};

Object.assign(ACTIONS, {
  'read.plan': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    LAST_READ = { case_dir: fd.get('case_dir'), script: fd.get('script') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('read.plan', LAST_READ);
    if (!env.ok) return boxError('hits', env);
    const p = env.data.plan || {};
    el('hits').innerHTML = `
      <table><tbody>
        <tr><td>${t('read.frames')}</td><td class="num">${esc(p.frames)}</td></tr>
        <tr><td>${t('read.script')}</td><td>${esc(p.script)}</td></tr>
        <tr><td>${t('read.model')}</td><td class="mono">${esc(p.model)}</td></tr>
        ${p.voice ? `<tr><td>${t('read.voice')}</td><td class="mono">${esc(p.voice)}</td></tr>` : ''}
        <tr><td>→</td><td class="mono">${esc(p.out_dir)}</td></tr>
      </tbody></table>
      <button data-act="read.go">${t('read.go')}</button>`;
  },

  'read.go': async () => {
    if (!LAST_READ) return;
    const env = await callOp('read.start', LAST_READ);
    if (!env.ok) return alert(env.error);
    show('jobs');
  },
});
