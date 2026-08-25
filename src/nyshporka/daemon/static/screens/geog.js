/** 🗺 Газетир. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav, goto,
  refreshJobs } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';




/**
 * 🗺 Газетир — від СЕЛА до справ по ВСІХ фондах архіву.
 *
 * 🔑 Найчастіший перший крок дослідника: він знає село, а не фонд. Реєстр опису
 * на це відповісти не може — він знає один фонд і мовчить про сусідні.
 *
 * 🕍 Конфесія тут ФІЛЬТР, а не три окремі довідники: метрики православної
 * громади, костелу й рабинату одного містечка лежать у РІЗНИХ фондах, тож
 * дефолт «усі» — не зручність, а захист від систематичного недобору.
 */

SCREENS.geog = async () => {
  const gen = curGen();
  busy();
  // 🔴 Стан довідників показуємо ОДРАЗУ, поруч із полем пошуку, а не ховаємо в
  // діагностику. Це і є знаменник: без нього «нічого не знайдено» не
  // відрізнити від «нема де шукати», і людина закриє напрям, якого не
  // перевіряла. Особливо на щойно встановленому застосунку.
  const packs = await callOp('catalog.packs', {});
  if (!alive(gen)) return;
  const ok = ((packs.data || {}).packs || []).filter((x) => x.state === 'ok');
  setView(`
    <h2>${t('geog.title')}</h2>
    <p class="muted">${t('geog.why')}</p>
    ${ok.length ? '' : `<div class="warn">${t('catalog.none')}</div>`}
    <form class="row" data-act="geog.find">
      <input name="q" placeholder="${t('geog.q')}" autofocus>
      <select name="section">
        <option value="">${t('geog.section.all')}</option>
        <option value="church">${t('geog.section.church')}</option>
        <option value="decanats">${t('geog.section.decanats')}</option>
        <option value="rabbinate">${t('geog.section.rabbinate')}</option>
      </select>
      <button type="submit">${t('geog.find')}</button>
    </form>
    <div id="geoghits"></div>
    <h3>${t('catalog.title')}</h3>
    <table><tbody>${ok.map((x) => `<tr>
      <td class="mono">${esc(x.pack_id)}</td>
      <td>${x.taken ? `зріз ${esc(x.taken)}` : ''}</td>
      <td class="muted">${esc(x.note || '')}</td>
    </tr>`).join('')}</tbody></table>
    ${renderWarnings(packs)}`);
};

Object.assign(ACTIONS, {
  /**
   * 📚 Ця сама справа в бібліотеці.
   *
   * 🔴 Доти картка села була тупиком: вона ЗНАЄ шлях справи на диску (поле
   * `on_disk`) і показувала лише позначку «✓». Тобто найдешевший перехід у
   * всьому застосунку — від села до вже завантаженої книги — доводилось
   * робити руками через пошук за шифрою.
   */
  'geog.lib': (_ev, elm) => goto('library', { key: elm.dataset.arg }),

  /** 🏛 Ця сама справа в реєстрі опису — «а що ще є в цьому фонді». */
  'geog.opys': (_ev, elm) => {
    const [repo, fond, spr] = String(elm.dataset.arg).split('/');
    return goto('fonds', { repo, fond, spr });
  },

  'geog.find': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const seq = ++SEQ.geog;
    const unlock = busyForm(ev.target);
    el('geoghits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('geog.find',
      { q: f.get('q'), section: f.get('section') || '', limit: 40 });
    unlock();
    if (seq !== SEQ.geog) return;          // нас уже обігнав свіжіший запит
    // 🔴 Відмова каталогу — це НЕ «нічого не знайдено»: довідника просто немає,
    // і нуль тут не означав би нічого. Показуємо причину, а не порожню таблицю.
    if (!env.ok) { el('geoghits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    const places = env.data.places || [];
    el('geoghits').innerHTML = `
      ${renderWarnings(env)}
      ${places.length ? '' : `<p><b>${t('geog.nothing')}</b></p>`}
      <table><tbody>${places.map((pl) => `<tr>
        <td>${esc(pl.institution || '')}</td>
        <td><b>${esc(pl.village_uk)}</b><br>
            <span class="muted">${esc(pl.village_ru || '')}</span></td>
        <td>${esc(pl.uezd_gub || '')}</td>
        <td class="num">${pl.n_cases || 0}</td>
        <td><button data-act="geog.card" data-arg="${esc(pl.card)}">${t('view.open')}</button></td>
      </tr>`).join('')}</tbody></table>
      ${renderCoverage(env)}`;
  },

  'geog.card': async (_ev, elm) => {
    busy();
    const env = await callOp('geog.card', { card: elm.dataset.arg });
    if (!env.ok) return failure(env);
    const pl = env.data.place;
    if (!pl) return setView(`<h2>${t('geog.title')}</h2>${renderWarnings(env)}${renderCoverage(env)}`);
    const cases = pl.cases || [];
    setView(`
      <h2>🗺 ${esc(pl.village_uk)} <span class="muted">(${esc(pl.village_ru || '')})</span></h2>
      <p class="muted">
        ${t('geog.hist')}: ${esc(pl.hist_place || '—')} ·
        ${t('geog.after')}: ${esc(pl.uezd_gub || '—')} ·
        ${t('geog.modern')}: ${esc(pl.modern_place || '—')}
        ${pl.church ? ` · ${t('geog.church')}: ${esc(pl.church)}` : ''}
      </p>
      ${renderWarnings(env)}
      <p><b>${cases.length}</b> ${t('geog.cases')}, ${t('geog.ondisk')} <b>${pl.n_on_disk || 0}</b></p>
      <table><tbody>${cases.map((c) => `<tr>
        <td>${c.on_disk ? '✓' : '·'}</td>
        <td class="mono">${esc(c.shifra)}</td>
        <td>${c.year_from ? `${esc(c.year_from)}–${esc(c.year_to)}` : ''}</td>
        <td>${esc(c.doc_type || '')}</td>
        <td class="muted">${esc(c.parish || '')}</td>
        <td class="acts">
          ${c.on_disk ? `<button class="ctl-sm" data-act="geog.lib"
            data-arg="${esc(c.key || '')}"
            title="${esc(t('geog.act.lib'))}">${ic('books', 'ic-o ic-sm')}</button>` : ''}
          ${c.key ? `<button class="ctl-sm" data-act="geog.opys"
            data-arg="${esc(c.key)}"
            title="${esc(t('geog.act.opys'))}">${ic('archive-box', 'ic-o ic-sm')}</button>` : ''}
        </td>
      </tr>`).join('')}</tbody></table>
      ${(pl.siblings || []).length ? `<h3>🕍 ${t('geog.siblings')}</h3>
        <table><tbody>${pl.siblings.map((x) => `<tr>
          <td>${esc(x.institution || '')}</td><td>${esc(x.village_uk)}</td>
          <td class="num">${x.n_cases || 0}</td>
          <td><button data-act="geog.card" data-arg="${esc(x.card)}">${t('view.open')}</button></td>
        </tr>`).join('')}</tbody></table>` : ''}
      ${(pl.confusers || []).length ? `<h3>⚠ ${t('geog.confusers')}</h3>
        <table><tbody>${pl.confusers.map((x) => `<tr>
          <td class="num">${esc(x.score)}</td><td>${esc(x.village_uk)}</td>
          <td class="muted">${esc(x.uezd_gub || '')}</td>
        </tr>`).join('')}</tbody></table>` : ''}
      ${renderCoverage(env)}`);
  },
});
