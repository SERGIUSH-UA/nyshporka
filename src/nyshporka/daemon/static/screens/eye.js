/** 👁 Облік переглянутого оком. */

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
 * Типи сторінок — рівно ті, що приймає сховище.
 *
 * 🔴 Порядок не абетковий, а за частотою в роботі: метричні рубрики першими,
 * службові аркуші наприкінці. Заносити доводиться сотні сторінок поспіль, і
 * зайвий рух до потрібного рядка множиться на цю сотню.
 */
const PAGE_TYPES = ['birth', 'marriage', 'death', 'confession', 'revision',
  'census', 'index', 'title', 'cover', 'flyleaf', 'blank', 'illegible',
  'mixed', 'other'];

SCREENS.eye = async () => {
  const e = ST.eye || {};
  setView(`
    <h2>${t('nav.eye')}</h2>
    <p class="muted">${t('eye.rule')}</p>
    <form class="row" data-act="eye.check">
      <input name="case" placeholder="${t('eye.case')}: DAHMO/315/8433"
        value="${esc(e.case || '')}" ${e.case ? '' : 'autofocus'}>
      <button type="submit">${t('eye.check')}</button>
    </form>
    <div id="hits"></div>`);
  if (!e.case) return;
  await ACTIONS['eye.check']({
    preventDefault() {}, target: el('view').querySelector('form') });
  // Скан, на якому спрацював пошук, підставляється у форму занесення: людина
  // прийшла сюди саме з нього, і набирати його ще раз — зайвий шанс на описку.
  const note = el('view').querySelector('form[data-act="eye.note"]');
  if (note && e.scan) note.querySelector('input[name="scan"]').value = e.scan;
};

Object.assign(ACTIONS, {
  // 🔴 Спершу ПЛАН, і лише окремою кнопкою — старт. Справа читається годинами;
  // дізнатись «модель не та» або «кадрів не 20, а 3000» після запуску означає
  // втратити ніч.
  'eye.check': async (ev) => {
    ev.preventDefault();
    ST.eye = { case: new FormData(ev.target).get('case') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('pages.status', ST.eye);
    if (!env.ok) return boxError('hits', env);
    const d = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p><b>${esc(d.shifra)}</b> ${esc(d.title || '')}</p>
      <p class="muted">${t('eye.disk')}: ${d.total_disk ?? 0} ·
         ${t('eye.noted')}: ${d.noted} ·
         ${t('eye.left')}: ${d.unnoted_count ?? '?'}</p>
      <h3>${t('eye.note')}</h3>
      <form data-act="eye.note">
        <div class="row">
          <input name="scan" placeholder="${t('eye.scan')}: 0030.JPG">
          <select name="page_type">${PAGE_TYPES.map((k) =>
            `<option value="${k}">${t(`ptype.${k}`)}</option>`).join('')}</select>
          <select name="status">
            <option value="full">full — виписано ВСІ прізвища</option>
            <option value="partial">partial — не всі</option>
            <option value="skipped">skipped — не читав</option>
            <option value="unreadable">unreadable — не читається</option>
          </select>
        </div>
        <div class="row"><input name="surnames" placeholder="${t('eye.surnames')}"></div>
        <div class="row">
          <input name="comment" placeholder="${t('eye.comment')}">
          <button type="submit">${t('eye.save')}</button>
        </div>
      </form>
      <div id="noted"></div>`;
  },

  'eye.note': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('pages.note', { ...ST.eye, ...fd });
    const box = el('noted');
    if (!env.ok) { box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    box.innerHTML = `<div class="warn">✅ ${esc(fd.scan)} занесено</div>`
      + renderWarnings(env);
    ev.target.reset();
  },
});
