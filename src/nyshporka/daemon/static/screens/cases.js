/** 📂 Мої справи й заведення нової. */

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
 * Опис, підвантажений у форму «Завести справу» для ПРАВКИ.
 *
 * 🔴 Порожня форма над уже описаною текою — пастка: людина бачить порожні
 * поля, вважає, що опису немає, і друкує його заново — часто інакше, ніж
 * попереднього разу. Тому правка починається з показу записаного.
 */
let EDIT = null;

SCREENS.cases = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('cases.list', { limit: 100 });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const rows = env.data.cases || [];
  setView(`
    <h2>${t('cases.title')} <button data-act="cases.build"
      title="${t('cases.build.why')}">🔄 ${t('cases.build')}</button></h2>
    ${renderWarnings(env)}
    <table><thead><tr>
      <th>шифра</th><th>назва</th><th class="num">${t('common.frames')}</th>
      <th>читання</th><th></th></tr></thead><tbody>
    ${rows.map((r) => `<tr>
      <td class="mono">${esc(r.shifra || r.key)}</td>
      <td>${esc((r.title || '').slice(0, 90))}</td>
      <td class="num">${esc(r.frames || 0)}</td>
      <td>${r.htr_stage && r.htr_stage !== 'none'
        ? `${t('cases.read')} ${esc(r.htr_pages_max || '')}`
        : `<span class="muted">${t('cases.none')}</span>`}</td>
      <td>${r.path
        ? `<button data-act="case.edit" data-arg="${esc(r.path)}"
             title="${t('case.edit')}">✏</button>`
        : `<span class="muted" title="${t('cases.nodir')}">—</span>`}</td>
    </tr>`).join('')}
    </tbody></table>`);
};

SCREENS.newcase = async () => {
  const sc = (EDIT && EDIT.sidecar) || {};
  const v = (k) => esc(sc[k] === null || sc[k] === undefined ? '' : sc[k]);
  const dir = EDIT ? esc(EDIT.case_dir) : '';
  setView(`
    <h2>${EDIT ? t('case.edit') : t('case.title')}</h2>
    <p class="muted">${t('case.why')}</p>
    ${EDIT ? `<div class="warn">${t('case.editing')} <b class="mono">${dir}</b>
       · ${esc(EDIT.scans)} ${t('common.frames')}<br>
       <span class="muted">${t('case.keep')}</span></div>` : ''}
    <form data-act="case.save">
      <div class="row"><input name="case_dir" placeholder="${t('case.dir')}"
        value="${dir}" ${EDIT ? '' : 'autofocus'}></div>
      ${EDIT ? '' : `<p class="muted">${t('case.dirhint')}</p>`}
      <div class="row">
        <input name="shifra" placeholder="${t('case.shifra')}: ДАХмО 315-1-8433"
          value="${v('shifra')}">
        <input name="doc_type" placeholder="${t('case.type')}: метрична"
          value="${v('doc_type')}">
      </div>
      <div class="row"><input name="title" placeholder="${t('case.name')}"
        value="${v('title')}" ${EDIT ? 'autofocus' : ''}></div>
      <div class="row">
        <input name="place" placeholder="${t('case.place')}" value="${v('place')}">
        <input name="year_from" placeholder="${t('case.years')}: 1858" size="6"
          value="${v('year_from')}">
        <input name="year_to" placeholder="1860" size="6" value="${v('year_to')}">
      </div>
      <div class="row"><input name="note" placeholder="${t('case.note')}"
        value="${v('note')}"></div>
      <div class="row"><label><input type="checkbox" name="adopt" value="1">
        ${t('case.adopt')}</label></div>
      <p class="muted">${t('case.adopt.why')}</p>
      <div class="row"><button type="submit">${t('case.save')}</button>
        ${EDIT ? `<button type="button" data-act="case.fresh">${t('case.fresh')}</button>`
          : ''}</div>
    </form>
    <div id="hits"></div>`);
  EDIT = null;
};

Object.assign(ACTIONS, {
  'cases.build': async () => {
    const env = await callOp('cases.build', { rescan: true });
    if (!env.ok) return failure(env);
    // Робота йде у черзі — туди ж і ведемо: інакше кнопка виглядає як така,
    // що нічого не зробила, і її натискають ще раз.
    await show('jobs');
  },

  'case.edit': async (_ev, elm) => {
    const env = await callOp('case.show', { case_dir: elm.dataset.arg });
    if (!env.ok) return failure(env);
    EDIT = env.data;
    await show('newcase');
    if (env.warnings && env.warnings.length) {
      el('hits').innerHTML = renderWarnings(env);
    }
  },

  'case.fresh': async () => {
    EDIT = null;
    await show('newcase');
  },

  'case.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    for (const k of ['year_from', 'year_to']) fd[k] = fd[k] ? Number(fd[k]) : null;
    // Незнята позначка у FormData просто відсутня — схема чекає булеве поле.
    fd.adopt = fd.adopt === '1';
    const env = await callOp('case.register', fd);
    if (!env.ok) {
      el('hits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return;
    }
    const sc = env.data.sidecar;
    el('hits').innerHTML = `${renderWarnings(env)}
      <div class="warn">✅ <b>${esc(sc.shifra)}</b> — ${esc(sc.title || 'без назви')}</div>`;
  },
});
