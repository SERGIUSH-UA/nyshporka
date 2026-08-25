/** 📚 Бібліотека справ. */

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
 * 📚 Бібліотека справ — що взагалі є на руках.
 *
 * Відповідає на питання, якого не закриває «Мої справи»: там ідеться про взяте
 * під облік у цьому просторі, тут — про весь матеріал разом із рішеннями ока.
 *
 * 🔴 Порожня бібліотека і НЕЗІБРАНА бібліотека показуються по-різному. «0 справ»
 * читається як факт («шукати нема де»), і людина закриває напрям, якого ніхто
 * не відкривав; тому незібране каже про себе прямо й дає кнопку.
 */
let LIB = { q: '', repo: '', verdict: '', on_disk: null };
/**
 * Лічильник запитів бібліотеки.
 *
 * ⚠ Захист від ОБІГНАНОЇ відповіді: фільтр набирають швидко, запити летять
 * підряд, і повільніший ранній може прийти ПІСЛЯ свіжого — на екрані лишиться
 * видача, що не відповідає полю. Не падає, не помиляється видимо, і саме тому
 * дорого: людина вирішує по тому, що бачить.
 */
let _libSeq = 0;

SCREENS.library = async () => {
  busy();
  await libLoad(true);
};

/**
 * @param {boolean} full  перемалювати весь екран (вхід) чи лише видачу (фільтр).
 *
 * 🔴 Фільтр оновлює ТІЛЬКИ таблицю. Перемальовуючи весь екран, ми щоразу
 * знищували б поле пошуку разом із фокусом і кареткою — і символи, набрані
 * після паузи в 250 мс, ішли б у нікуди. Виглядає це як «клавіатура загубилась»,
 * а не як помилка.
 */
async function libLoad(full = false) {
  const seq = ++_libSeq;
  const gen = curGen();
  const env = await callOp('library.list', {
    q: LIB.q, repo: LIB.repo, verdict: LIB.verdict,
    ...(LIB.on_disk === null ? {} : { on_disk: LIB.on_disk }),
  });
  if (seq !== _libSeq) return;          // нас уже обігнав свіжіший запит
  if (!alive(gen)) return;              // з бібліотеки вже пішли
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const rows = d.cases || [];
  const count = esc(t('lib.count')
    .replace('{n}', d.shown ?? 0).replace('{total}', d.total ?? 0));

  if (!full) {
    // Каркас на місці — міняється лише вміст. `swapHtml` тримає висоту
    // контейнера на час підміни, тож сторінка під таблицею не підстрибує.
    const body = el('lib-rows');
    if (body) swapHtml(body, rows.map(libRow).join(''));
    const n = el('lib-count');
    if (n) n.textContent = count;
    const warn = el('lib-warn');
    if (warn) warn.innerHTML = renderWarnings(env);
    return;
  }

  const head = `<h2>${ic('books')} ${t('lib.title')}</h2>
    <p class="muted">${t('lib.why')}</p>`;

  if (!d.built) {
    setView(`${head}${renderWarnings(env)}
      <div class="warn">${t('lib.unbuilt')}
        <button data-act="cases.build">${t('lib.build')}</button></div>`);
    return;
  }

  const opt = (v, label, cur) =>
    `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
  // Перелік архівів дає СЕРВЕР — по всій бібліотеці. Зібраний із видачі, він
  // схлопувався б до одного пункту після першого ж вибору.
  const repos = d.repos || [];
  const kinds = d.kinds || {};

  setView(`${head}
    <div class="row">
      <input id="lib-q" type="search" placeholder="${esc(t('lib.q'))}"
             value="${esc(LIB.q)}" data-act="lib.filter" data-live="1">
      <select id="lib-repo" data-act="lib.filter">
        ${opt('', t('lib.repo.any'), LIB.repo)}
        ${repos.map((r) => opt(r, r, LIB.repo)).join('')}
      </select>
      <select id="lib-verdict" data-act="lib.filter">
        ${opt('', t('lib.verdict.all'), LIB.verdict)}
        ${opt('any', t('lib.verdict.any'), LIB.verdict)}
        ${opt('none', t('lib.verdict.none'), LIB.verdict)}
        ${Object.keys(kinds).map((k) =>
          opt(k, t(`lib.verdict.${k}`), LIB.verdict)).join('')}
      </select>
      <label class="lbl-mini"><input type="checkbox" id="lib-disk"
        data-act="lib.filter"${LIB.on_disk ? ' checked' : ''}> ${t('lib.ondisk')}</label>
    </div>
    <div id="lib-warn">${renderWarnings(env)}</div>
    <p class="muted" id="lib-count">${count}</p>
    <table><thead><tr>
      <th>${t('lib.col.shifra')}</th><th>${t('lib.col.title')}</th>
      <th class="num">${t('lib.col.years')}</th><th>${t('lib.col.place')}</th>
      <th>${t('lib.col.verdict')}</th></tr></thead>
    <tbody id="lib-rows">${rows.map(libRow).join('')}</tbody></table>`);
}

function libRow(r) {
  const years = [r.year_from, r.year_to].filter(Boolean).join('–');
  const disk = r.on_disk
    ? `<span title="${esc(t('lib.disk'))}">${ic('disk', 'ic-sm')}</span>`
    : `<span class="muted" title="${esc(t('lib.nodisk'))}">—</span>`;
  const v = r.verdict
    ? `<span class="badge ${r.verdict === 'clan_found' ? 'known' : ''}"
         title="${esc(r.verdict_note || '')}">${esc(t(`lib.verdict.${r.verdict}`))}</span>`
    : '';
  return `<tr>
    <td class="mono">${disk} ${esc(r.shifra || r.key || '')}</td>
    <td>${esc((r.title || '').slice(0, 90))}</td>
    <td class="num">${esc(years)}</td>
    <td>${esc(r.place || '')}</td>
    <td>${v} <button class="ctl-sm" data-act="lib.verdict" data-arg="${esc(r.key)}"
      title="${esc(t('lib.verdict.set'))}">${ic('pencil-line', 'ic-o ic-sm')}</button></td>
  </tr>`;
}

/**
 * Форма рішення по справі.
 *
 * 🔴 Поле «скільки аркушів переглянуто» стоїть ПОРУЧ із «роду немає», а не в
 * примітці: нуль без знаменника не результат, і саме цей вердикт наступного
 * разу закриє напрям. Порожнім лишити можна — вердикт виносить людина, і
 * машина не має права не пустити її рішення, — але мовчки це не проходить.
 */
function libVerdictForm(key) {
  setView(`<h2>${ic('pencil-line')} ${esc(key)}</h2>
    <div class="row"><select id="lv-kind">
      <option value="">${esc(t('lib.verdict.clear'))}</option>
      <option value="no_clan">${esc(t('lib.verdict.no_clan'))}</option>
      <option value="clan_found">${esc(t('lib.verdict.clan_found'))}</option>
      <option value="recheck">${esc(t('lib.verdict.recheck'))}</option>
    </select></div>
    <div class="row"><input id="lv-pages" type="number" min="0"
      placeholder="${esc(t('lib.pages'))}"></div>
    <p class="muted">${t('lib.pages.why')}</p>
    <div class="row"><input id="lv-note" placeholder="${esc(t('lib.note'))}"></div>
    <button data-act="lib.verdict.save" data-arg="${esc(key)}">${t('lib.save')}</button>
    <button data-act="nav" data-arg="library">${t('lib.cancel')}</button>`);
}

Object.assign(ACTIONS, {
  /** Фільтр бібліотеки. Читає ВСІ поля одразу: інакше зміна одного скидала б
      інші до дефолтів, і видача не відповідала б тому, що видно на екрані. */
  'lib.filter': () => {
    LIB = {
      q: (el('lib-q') || {}).value || '',
      repo: (el('lib-repo') || {}).value || '',
      verdict: (el('lib-verdict') || {}).value || '',
      on_disk: (el('lib-disk') || {}).checked ? true : null,
    };
    return libLoad();
  },

  'lib.verdict': (_ev, elm) => libVerdictForm(elm.dataset.arg),

  'lib.verdict.save': async (_ev, elm) => {
    const pages = ((el('lv-pages') || {}).value || '').trim();
    const env = await callOp('library.verdict', {
      key: elm.dataset.arg,
      verdict: (el('lv-kind') || {}).value || '',
      note: (el('lv-note') || {}).value || '',
      ...(pages ? { pages: Number(pages) } : {}),
    });
    if (!env.ok) return failure(env);
    // Застереження про нуль без знаменника не ковтається: воно доїжджає
    // конвертом і малюється над поверненою таблицею.
    await show('library');
    const box = el('view');
    if (box && env.warnings && env.warnings.length) {
      box.insertAdjacentHTML('afterbegin', renderWarnings(env));
    }
  },
});
