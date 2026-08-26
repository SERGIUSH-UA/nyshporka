/**
 * 🎯 Рід — чиє прізвище шукаємо і в яких написаннях.
 *
 * 🔴 Найпропущеніший крок першої сесії, і доти єдиний, до якого з вікна не було
 * дверей узагалі: попередження про відсутній профіль показувалось, а завести
 * його можна було лише командою в терміналі. Людині, яка запустила застосунок
 * подвійним кліком, це читалось як «щось не так, і вдіяти нічого не можна».
 *
 * 🔴 Форма питає рівно три речі, і саме ті, які може знати ЛИШЕ людина:
 * прізвище, як воно відмінюється, і як його писали в різних орфографіях.
 * Вгадувати їх заборонено: основа, виведена правилом, мовчки викидає половину
 * написань із пошуку, а нуль після цього виглядає як відповідь.
 *
 * ⚠ Решта конфігу (конфузери, зниження рангу, рецепт синтетики) калібрується
 * замірами на власному матеріалі, а не набором у полі. Вона лишається текстом
 * під «весь файл», і екран каже це прямо, а не вдає, ніби її можна вибрати.
 */

import { t, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show } from '../core/nav.js';
import { ic } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';

/** Останній зріз — щоб форма правки не ходила по нього вдруге. */
let PS = null;

/** Скільки написань показувати, доки не попросили всі. */
const SHOWN = 24;
let ALL = false;


SCREENS.profile = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('profile.show', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  PS = env.data;
  setView(`<h2>${ic('target', 'ic-sm')} ${t('prof.title')}</h2>
    <p class="muted">${t('prof.why')}</p>
    ${renderWarnings(env)}
    <div id="prof-card">${card(PS)}</div>
    <div id="prof-form">${form(PS)}</div>
    ${sourceBlock(PS)}`);
};


/**
 * Картка наявного профілю.
 *
 * 🔴 Три стани, і плутати їх дорого: «профілю немає» лікується заведенням,
 * «файл побитий» — правкою тексту, і показати друге як перше означає послати
 * людину заводити те, що вже є, поверх того, що зламалось.
 */
function card(d) {
  if (d.broken) {
    return `<div class="warn err">${t('prof.broken')}<br>
      <span class="mono">${esc(d.broken)}</span></div>`;
  }
  if (!d.present) return `<p class="muted">${t('prof.none')}</p>`;
  const sp = d.spellings || [];
  const shown = ALL ? sp : sp.slice(0, SHOWN);
  return `<div class="dash-box">
    <div class="dash-nums">
      <span><b>${esc(d.display || d.name)}</b></span>
      <span>${t('prof.paradigm')}: <b>${esc(paradigmLabel(d, d.paradigm))}</b></span>
      <span>${t('prof.roots')}: <b>${esc((d.roots || []).join(', ') || '—')}</b></span>
      <span>${t('prof.spellings')}: <b>${sp.length}</b></span>
    </div>
    <p class="muted">${t('prof.spellings.why')}</p>
    <div class="prof-forms">${shown.map((x) =>
      `<span class="chip">${esc(x)}</span>`).join('')}
      ${sp.length > SHOWN && !ALL
        ? `<button class="ctl-sm" data-act="prof.all">+${sp.length - SHOWN}</button>`
        : ''}</div>
    ${stemGaps(d)}
  </div>`;
}

/**
 * Порожні орфографії — назвати вголос.
 *
 * 🔴 Без основи на дореформену орфографію метрики XIX ст. просто не
 * шукаються, і мовчання тут коштує найдорожче: пошук працює, нуль виглядає як
 * відповідь, а половину написань ніхто й не питав.
 */
function stemGaps(d) {
  const have = d.stems || {};
  const miss = (d.orthographies || []).filter((o) => !have[o]);
  if (!miss.length) return '';
  return `<p class="muted">⚠ ${t('prof.gaps')}: <span class="mono">${
    miss.map(esc).join(' · ')}</span></p>`;
}

function paradigmLabel(d, id) {
  const p = (d.paradigms || []).find((x) => x.id === id);
  return p ? p.label : (id || '');
}


/** Форма заведення або правки. Поля ті самі — різниця лише в підписі кнопки. */
function form(d) {
  const s = d.stems || {};
  const v = (k) => esc(s[k] || '');
  const par = (d.paradigms || []).map((p) => `<option value="${esc(p.id)}"
      ${p.id === (d.paradigm || 'adj_skyi') ? 'selected' : ''}>${esc(p.label)}${
    p.verified ? '' : ' — ' + t('prof.unverified')}</option>`).join('');
  return `<h3>${d.present ? t('prof.edit') : t('prof.new')}</h3>
    <form data-act="prof.save">
      <div class="row">
        <input name="display" placeholder="${t('prof.surname')}: Сікорський"
          value="${esc(d.display || '')}" autofocus>
        <select name="paradigm">${par}</select>
      </div>
      <p class="muted">${t('prof.paradigm.why')}</p>
      <h4>${t('prof.stems')}</h4>
      <p class="muted">🔴 ${t('prof.stems.why')}</p>
      <div class="row">
        ${(d.orthographies || []).map((o) => `<label class="lbl-mini">${
          t('orth.' + o)}<input class="inp-mini" name="stem_${esc(o)}"
          value="${v(o)}" size="12"></label>`).join('')}
      </div>
      <div class="row">
        <label class="lbl-mini">${t('prof.rootlist')}
          <input name="roots" value="${esc((d.roots || []).join(', '))}"
            placeholder="лищинськ, ищинс"></label>
        <label class="lbl-mini">${t('prof.subs')}
          <input name="substrings" value="${esc((d.substrings || []).join(', '))}"
            placeholder="ищинс, szczyn"></label>
      </div>
      <p class="muted">${t('prof.rootlist.why')}</p>
      <div class="row"><button type="submit">${
        d.present ? t('prof.save') : t('prof.create')}</button></div>
    </form>
    <div id="prof-hits"></div>`;
}


/**
 * Сирий файл.
 *
 * ⚠ Під `<details>` навмисно: тому, хто заводить рід уперше, він не потрібен і
 * лише лякає; тому, хто дописує конфузери за замірами, — єдине потрібне місце.
 */
function sourceBlock(d) {
  return `<details class="dash-sec"><summary>▸ ${t('prof.source')}</summary>
    <p class="muted">${t('prof.source.why')}</p>
    <p class="muted mono">${esc(d.path || '')}</p>
    <form data-act="prof.source">
      <textarea name="text" rows="18" spellcheck="false"
        class="mono">${esc(d.source || '')}</textarea>
      <div class="row"><button type="submit">${t('prof.source.save')}</button>
        <span class="muted">${t('prof.source.bak')}</span></div>
    </form>
    <div id="prof-src"></div>
  </details>`;
}


Object.assign(ACTIONS, {
  /** Показати решту написань. Перемальовується лише картка. */
  'prof.all': () => {
    ALL = true;
    const box = el('prof-card');
    if (box && PS) swapHtml(box, card(PS));
  },

  /**
   * Зберегти поля форми.
   *
   * ⚠ Читається через `fd.get(...)`, а не `Object.fromEntries(fd.entries())`:
   * приймач, який виконує фронт на Node, підміняє `FormData` заглушкою з одним
   * `get()`. Форма, написана на `entries()`, там падає — і падає саме там, де
   * перевіряють, що екран узагалі малюється.
   */
  'prof.save': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    const list = (k) => String(fd.get(k) || '').split(/[,\n]/)
      .map((x) => x.trim()).filter(Boolean);
    const stems = {};
    for (const o of (PS && PS.orthographies) || []) {
      const val = String(fd.get('stem_' + o) || '').trim();
      if (val) stems[o] = val;
    }
    // ⚠ Коментарів усередині літерала бути не може: приймач
    // `test_screens_send_only_fields_the_schema_accepts` тягне з нього ключі
    // регексом і бере за поле будь-яке слово перед двокрапкою — навіть у прозі.
    //
    // `orth` — це орфографія, якою подано САМЕ поле «прізвище», а не перелік
    // тих, що заповнені: основи на решту приходять окремими полями.
    const env = await callOp('profile.set', {
      display: String(fd.get('display') || '').trim(),
      name: (PS && PS.name) || '',
      paradigm: String(fd.get('paradigm') || 'adj_skyi'),
      orth: 'uk',
      stems, roots: list('roots'), substrings: list('substrings'),
    });
    unlock();
    if (!env.ok) return boxError('prof-hits', env);
    return show('profile');
  },

  /** Записати сирий файл. Відмова лишається в коробці — текст не втрачається. */
  'prof.source': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    const env = await callOp('profile.source',
      { text: String(fd.get('text') || '') });
    unlock();
    if (!env.ok) return boxError('prof-src', env);
    return show('profile');
  },
});
