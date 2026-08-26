/** 📂 Мої справи й заведення нової. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav, goto,
  refreshJobs, onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';
import { pathField } from '../core/paths.js';
import { pager, step } from '/ui/pager.js';




/**
 * Опис, підвантажений у форму «Завести справу» для правки.
 *
 * 🔴 Порожня форма над уже описаною текою — пастка: людина бачить порожні
 * поля, вважає, що опису немає, і друкує його заново — часто інакше, ніж
 * попереднього разу. Тому правка починається з показу записаного.
 */
let EDIT = null;

/** Сторінка приймальні. Переживає вихід з екрана — як фільтр бібліотеки. */
let PAGE = 0;
/** Скільки їх усього. Тримається тут, щоб «далі» не везла за край. */
let PAGES = 1;

/**
 * 📥 Приймальня — матеріал на диску, який ще нічим не є.
 *
 * 🔴 Екран показує рівно те, чого немає в бібліотеці: теки без шифри
 * (`unfiled`) і збірки, всередині яких лежить багато справ (`bundle`). Доти він
 * віддавав ті самі рядки, що й бібліотека, лише без фільтрів і без сторінок —
 * тобто виглядав її гіршою копією, і питання «а чим вони відрізняються» не мало
 * відповіді, яку видно очима.
 *
 * Межа проста й вона про ключ: у бібліотеки одиниця обліку — справа з шифрою
 * (`repo/fond/spr`), і саме на цьому ключі тримаються всі її знаменники. Тека
 * без шифри ключа не має, тож у бібліотеці її не було й не буде — але вона є на
 * диску, і поки її не описали, вона невидима для всього іншого.
 */
SCREENS.cases = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('cases.list',
    { kind: 'unfiled,bundle', page: PAGE, page_size: 50 });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data;
  const rows = d.cases || [];
  const c = d.counts || {};
  PAGES = d.pages || 1;
  setView(`
    <h2>${t('nav.cases')} <button data-act="cases.build"
      title="${t('cases.build.why')}">🔄 ${t('cases.build')}</button></h2>
    <p class="muted">${t('intake.why')}</p>
    ${renderWarnings(env)}
    ${intakeCount(d, c)}
    ${rows.length ? `<table><thead><tr>
      <th></th><th>тека</th><th class="num">${t('common.frames')}</th><th></th>
      </tr></thead><tbody>
    ${rows.map((r) => `<tr>
      <td title="${esc(t(`intake.kind.${r.kind}`))}">${r.kind === 'bundle' ? '🗃' : '📄'}</td>
      <td class="mono">${esc(r.path || r.key)}</td>
      <td class="num">${esc(r.frames || 0)}</td>
      <td>${r.path
        ? `<button data-act="intake.frames" data-arg="${esc(r.path)}"
             title="${t('lib.act.frames')}">🖼</button>
           <button data-act="case.edit" data-arg="${esc(r.path)}"
             title="${t('intake.describe')}">✏</button>`
        : `<span class="muted" title="${t('cases.nodir')}">—</span>`}</td>
    </tr>`).join('')}
    </tbody></table>
    ${pager(d)}`
      : `<p><b>${t('intake.empty')}</b></p>`}`);
};

/**
 * 🔴 Знаменник обома боками межі.
 *
 * Приймальня без числа бібліотеки виглядає як увесь простір, і навпаки. Саме
 * тому тут стоїть і те, і те: «стільки неописаного, стільки описаного» — і
 * друге число водночас є кнопкою туди.
 */
function intakeCount(d, c) {
  const described = Number(c.case || 0);
  const bits = [];
  if (d.total !== null && d.total !== undefined) {
    bits.push(`<b>${esc(d.total)}</b> ${t('intake.undescribed')}`);
  }
  if (Number(c.bundle || 0)) bits.push(`${esc(c.bundle)} ${t('intake.bundles')}`);
  const lib = described
    ? ` · <button data-act="nav" data-arg="library">${esc(described)}
        ${t('intake.described')} →</button>` : '';
  return `<p class="muted">${bits.join(' · ')}${lib}</p>`;
}

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
      <div class="row">${pathField({ name: 'case_dir', mode: 'dir',
        purpose: 'case.dir', value: EDIT ? EDIT.case_dir : '',
        ph: t('case.dir'), autofocus: !EDIT })}</div>
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

PAGERS.cases = (delta) => {
  PAGE = step(PAGE, delta, PAGES);
  return show('cases');
};

Object.assign(ACTIONS, {
  /** 🖼 Подивитись, ЩО це, перш ніж описувати: без кадрів опис — вгадування. */
  'intake.frames': (_ev, elm) => goto('frames', { case: elm.dataset.arg }),

  'cases.build': async () => {
    const env = await callOp('cases.build', { rescan: true });
    if (!env.ok) return failure(env);
    // 🔴 Кнопка, після якої нічого видимо не сталось, натискається вдруге —
    // тому стан обов'язково видно. Але показувати його треба тут: людина
    // натиснула «перезібрати», дивлячись на цей перелік, і саме він зміниться
    // по завершенні. Перекидання на чергу забирало в неї місце й фільтр.
    const box = el('view');
    const id = (env.data || {}).job_id;
    if (!box || !id) return show('cases');
    box.insertAdjacentHTML('afterbegin',
      `<p id="cases-job" class="muted">${jobChip({ state: 'queued', progress: {} })}</p>`);
    const chip = el('cases-job');
    onJob(id, (j) => {
      if (chip) chip.innerHTML = jobChip(j);
      if (j.state === 'done') show('cases');
    });
    return undefined;
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
