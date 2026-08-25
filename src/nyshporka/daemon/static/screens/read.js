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
  // 🔴 Тека приходить із бібліотеки, а не з пам'яті людини. Набирати шлях
  // руками — найдешевший спосіб прочитати не ту теку й дізнатись про це через
  // годину.
  const seed = (ST.read || {}).case_dir || '';
  setView(`
    <h2>${t('nav.read')}</h2>
    <form class="row" data-act="read.plan">
      <input name="case_dir" placeholder="${t('read.dir')}"
        value="${esc(seed)}"${seed ? '' : ' autofocus'}>
      <select name="script">
        <option value="">${t('read.script')}: авто</option>
        <option value="cyrillic">кирилиця</option>
        <option value="latin">латинка</option>
      </select>
      <button type="submit">${t('read.plan')}</button>
    </form>
    <div id="hits"></div>`);
  // Засів одноразовий: лишившись, він підставляв би стару теку на кожному
  // наступному вході — а людина в цей момент уже думає про іншу справу.
  ST.read = null;
  await readCases();
};

/**
 * Підказка тек: справи бібліотеки, які лежать на диску.
 *
 * ⚠ Вільний текст лишається: тека поза бібліотекою — законний перший випадок,
 * і вимагати опису до першого ж читання означало б замкнути двері перед тим,
 * хто щойно завантажив скани.
 */
async function readCases() {
  const input = el('view').querySelector('input[name="case_dir"]');
  if (!input) return;
  const env = await callOp('library.list', { on_disk: true, page_size: 200 });
  if (!env.ok) return;
  const items = ((env.data || {}).cases || [])
    .filter((c) => c.path)
    .map((c) => c.path);
  if (items.length) attachCombobox(input, { items, empty: t('lib.count') });
}

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
