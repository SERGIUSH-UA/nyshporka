/** 🏛 Реєстр опису фонду. */

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




/**
 * 🏛 Фонди — реєстр ОПИСУ: «що взагалі існує в архіві».
 *
 * Третє сховище поруч із «мої справи». Плутати їх дорого: «справи немає» тут
 * означає «в архіві не існує», а в «моїх справах» — «ще не завантажено».
 */
SCREENS.fonds = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('fond.list', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const fonds = env.data.fonds || [];
  if (!fonds.length) {
    return setView(`<h2>${t('fonds.title')}</h2>${renderWarnings(env)}
      <p class="muted">${t('catalog.none')}</p>`);
  }
  setView(`
    <h2>${t('fonds.title')}</h2>
    <p class="muted">${t('fonds.why')}</p>
    ${renderWarnings(env)}
    <form class="row" data-act="fond.rows">
      <select name="fond">
        ${fonds.map((f) => `<option value="${esc(f.id)}">${esc(f.label)} —
          ${f.rows} ${t('fonds.rows')}, ${t('fonds.ondisk')} ${f.on_disk}, ${t('fonds.todo')} ${f.todo}</option>`).join('')}
      </select>
      <input name="q" placeholder="${t('fonds.filter')}">
      <input name="surname" placeholder="${t('fonds.surname')}" size="18">
      <input name="uezd" placeholder="${t('fonds.uezd')}" size="12">
      <select name="state">
        <option value="">${t('fonds.state.any')}</option>
        <option value="disk">${t('fonds.state.disk')}</option>
        <option value="todo">${t('fonds.state.todo')}</option>
        <option value="film">${t('fonds.state.film')}</option>
        <option value="order">${t('fonds.state.order')}</option>
      </select>
      <button type="submit">${t('geog.find')}</button>
    </form>
    <div id="fondrows"></div>`);
};

Object.assign(ACTIONS, {
  'fond.rows': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const seq = ++SEQ.fond;
    const unlock = busyForm(ev.target);
    el('fondrows').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('fond.rows', {
      fond: f.get('fond'), q: f.get('q') || '', surname: f.get('surname') || '',
      uezd: f.get('uezd') || '', state: f.get('state') || '', limit: 200,
    });
    unlock();
    if (seq !== SEQ.fond) return;
    if (!env.ok) { el('fondrows').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    const rows = env.data.rows || [];
    // 🔴 Знаменник поруч із числом: «5 справ» без «із 2944» читається як
    // «у фонді п'ять справ», тобто як зовсім інша відповідь.
    el('fondrows').innerHTML = `
      ${renderWarnings(env)}
      <p>${t('fonds.matched')} <b>${env.data.matched}</b> ${t('fonds.of')}
         <b>${env.data.summary.rows}</b></p>
      <table><thead><tr><th></th><th>шифра</th><th>назва</th><th>роки</th>
        <th>арк.</th><th>плівка</th></tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td title="${esc(r.state)}">${r.on_disk ? '✓' : (r.state === 'todo' ? '⬇' : '·')}</td>
        <td class="mono">${esc(r.shifra)}</td>
        <td>${esc((r.title || '').slice(0, 90))}</td>
        <td>${r.year_from ? `${esc(r.year_from)}–${esc(r.year_to)}` : ''}</td>
        <td class="num">${esc(r.folios || '')}</td>
        <td class="mono">${esc(r.fs_film || '')}</td>
      </tr>`).join('')}
      </tbody></table>`;
  },
});
