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
 * 🗺 Газетир — від села до справ по всіх фондах архіву.
 *
 * 🔑 Найчастіший перший крок дослідника: він знає село, а не фонд. Реєстр опису
 * на це відповісти не може — він знає один фонд і мовчить про сусідні.
 *
 * 🕍 Конфесія тут фільтр, а не три окремі довідники: метрики православної
 * громади, костелу й рабинату одного містечка лежать у різних фондах, тож
 * дефолт «усі» — не зручність, а захист від систематичного недобору.
 */

SCREENS.geog = async () => {
  const gen = curGen();
  busy();
  // 🔴 Стан довідників показуємо одразу, поруч із полем пошуку, а не ховаємо в
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
    <h3>⛪ ${t('church.title')}</h3>
    <p class="muted">${t('church.why')}</p>
    <form class="row" data-act="church.find">
      <input name="q" placeholder="${t('church.q')}">
      <button type="submit">${t('church.find')}</button>
    </form>
    <div id="churchhits"></div>
    <h3>${t('catalog.title')}</h3>
    <table><tbody>${ok.map((x) => `<tr>
      <td class="mono">${esc(x.pack_id)}</td>
      <td>${x.taken ? `зріз ${esc(x.taken)}` : ''}</td>
      <td class="muted">${esc(x.note || '')}</td>
    </tr>`).join('')}</tbody></table>
    ${renderWarnings(packs)}`);
};

/** 🗺 Поселення газетира, зшиті з церквою: назва, повіт, справ, оцінка. */
function renderPlaces(places) {
  return `<table><tbody>${(places || []).map((p) => `<tr>
    <td class="num">${esc(p.score)}</td>
    <td><b>${esc(p.village_uk)}</b>${p.region === 'mismatch' ? ` <span class="warn">⚠ ${t('church.mismatch')}</span>` : ''}${p.region === 'far' ? ` <span class="warn">⚠ ${esc(p.km)} ${t('church.km')}</span>` : ''}${p.km != null && p.region !== 'far' ? ` <span class="muted">${esc(p.km)} ${t('church.km')}</span>` : ''}</td>
    <td class="muted">${esc(p.uezd_gub || '')}</td>
    <td class="num">${p.n_cases || 0}</td>
    <td><button data-act="geog.card" data-arg="${esc(p.card)}">${t('view.open')}</button></td>
  </tr>`).join('')}</tbody></table>`;
}

/** ⛪ Перелік церков (пошук або коло) — кожна з зшитими поселеннями під нею. */
function renderChurches(env, rows, withKm) {
  return `
    ${renderWarnings(env)}
    ${rows.length ? '' : `<p><b>${t('church.nothing')}</b></p>`}
    <table><tbody>${rows.map((c) => `<tr>
      ${withKm ? `<td class="num">${esc(c.km)} ${t('church.km')}</td>` : `<td class="num">${esc(c.score)}</td>`}
      <td><b>${esc(c.name)}</b>${c.name_v ? `<br><span class="muted">${esc(c.name_v)}</span>` : ''}
          ${c.via === 'variant' ? ` <span class="muted">(${t('church.variant')})</span>` : ''}</td>
      <td>${esc(c.voivodeship_uk || c.voivodeship || '')}<br><span class="muted">${esc(c.deanery || '')}</span></td>
      <td>${esc(c.title_uk || c.title || '')}</td>
      <td>${(c.places || []).map((p) => `<button class="ctl-sm" data-act="geog.card" data-arg="${esc(p.card)}"
          title="${esc(p.uezd_gub || '')}">${p.region === 'mismatch' ? '⚠ ' : ''}${esc(p.village_uk)} · ${p.n_cases || 0}</button>`).join(' ')}</td>
      <td class="acts">
        <button class="ctl-sm" data-act="church.card" data-arg="${esc(c.ob_id)}">${t('view.open')}</button>
        <button class="ctl-sm" data-act="church.near" data-arg="${esc(c.ob_id)}">${t('church.near')}</button>
      </td>
    </tr>`).join('')}</tbody></table>
    ${renderCoverage(env)}`;
}

Object.assign(ACTIONS, {
  /**
   * 📚 Ця сама справа в бібліотеці.
   *
   * 🔴 Доти картка села була тупиком: вона знає шлях справи на диску (поле
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
    // 🔴 Відмова каталогу — це не «нічого не знайдено»: довідника просто немає,
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

  /**
   * ⛪ Церкви ~1772 за назвою села — гібрид: кожна церква приходить уже
   * зшитою з поселенням газетира, тож поруч видно, де тепер її книги.
   *
   * 🪤 Однойменне село в іншому воєводстві зшивається теж (Kapitanka
   * Балтського деканату ↔ Капітанівка Чигиринського повіту), і різниця
   * помітна лише позначкою `region=mismatch` — тому вона малюється, а не
   * ховається в даних.
   */
  'church.find': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    el('churchhits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('church.find', { q: f.get('q'), limit: 20 });
    unlock();
    if (!env.ok) { el('churchhits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    el('churchhits').innerHTML = renderChurches(env, env.data.churches || [], false);
  },

  /** 🗺 Коло по газетиру: сусідні села, у яких книги вціліли й відомо де. */
  'geog.near': async (_ev, elm) => {
    busy();
    const env = await callOp('geog.near', { at: String(elm.dataset.arg), km: 15, limit: 100 });
    if (!env.ok) return failure(env);
    const c = env.data.center || {};
    const rows = env.data.places || [];
    setView(`
      <h2>🗺 ${t('geog.near.title')}</h2>
      <p class="muted">📍 ${esc(c.how || '')} · ${c.km} ${t('church.km')} · ${rows.length} · ${t('geog.cases')}: <b>${env.data.n_cases || 0}</b></p>
      ${renderWarnings(env)}
      <table><tbody>${rows.map((p) => `<tr>
        <td class="num">${esc(p.km)} ${t('church.km')}${p.how === 'ambiguous' ? ' ?' : ''}</td>
        <td><b>${esc(p.village_uk)}</b><br><span class="muted">${esc(p.institution || '')}</span></td>
        <td class="muted">${esc(p.uezd_gub || '')}</td>
        <td class="num">${p.n_cases || 0}</td>
        <td><button data-act="geog.card" data-arg="${esc(p.card)}">${t('view.open')}</button></td>
      </tr>`).join('')}</tbody></table>
      ${renderCoverage(env)}`);
  },

  'church.near': async (_ev, elm) => {
    el('churchhits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('church.near', { at: String(elm.dataset.arg), km: 15, limit: 60 });
    if (!env.ok) { el('churchhits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    const c = env.data.center || {};
    el('churchhits').innerHTML = `
      <p>📍 ${esc(c.how || '')} · ${c.km} ${t('church.km')}</p>
      ${renderChurches(env, env.data.churches || [], true)}`;
  },

  'church.card': async (_ev, elm) => {
    busy();
    const env = await callOp('church.card', { ob_id: Number(elm.dataset.arg), km: 10 });
    if (!env.ok) return failure(env);
    const c = env.data.church;
    if (!c) return setView(`<h2>⛪ ${t('church.title')}</h2>${renderWarnings(env)}${renderCoverage(env)}`);
    setView(`
      <h2>⛪ ${esc(c.name)} <span class="muted">${c.name_v ? `(${esc(c.name_v)})` : ''}</span></h2>
      <p class="muted">
        ${t('church.title_of')}: <b>${esc(c.title_uk || c.title || '—')}</b> ·
        ${t('church.deanery')}: ${esc(c.deanery || '—')} · ${esc(c.voivodeship_uk || c.voivodeship || '')} ·
        ${t('church.patron')}: ${esc(c.patronage_uk || c.patronage || '—')}
        ${c.material_uk ? ` · ${esc(c.material_uk)}` : ''}
        ${c.monastery ? ` · ${esc(c.monastery)}` : ''}<br>
        ${t('church.source')}: ${esc(c.source || '—')}
        ${c.lat != null ? ` · ${Number(c.lat).toFixed(4)}, ${Number(c.lng).toFixed(4)}` : ''}
      </p>
      ${renderWarnings(env)}
      ${(c.places || []).length ? `<h3>🗺 ${t('church.places')}</h3>${renderPlaces(c.places)}` : ''}
      ${(c.nearby || []).length ? `<h3>⛪ ${t('church.nearby')}</h3>
        <table><tbody>${c.nearby.map((x) => `<tr>
          <td class="num">${esc(x.km)} ${t('church.km')}</td>
          <td><b>${esc(x.name)}</b></td>
          <td class="muted">${esc(x.deanery || '')}</td>
          <td>${esc(x.title_uk || x.title || '')}</td>
          <td><button data-act="church.card" data-arg="${esc(x.ob_id)}">${t('view.open')}</button></td>
        </tr>`).join('')}</tbody></table>` : ''}
      ${renderCoverage(env)}`);
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
      ${pl.location && pl.location.lat != null ? `<p class="muted">📍 ${Number(pl.location.lat).toFixed(4)}, ${Number(pl.location.lng).toFixed(4)}
        <span class="mono">${esc(pl.location.qid)}</span>${pl.location.how === 'ambiguous' ? ` ⚠ ${t('geog.loc.ambiguous')}` : ''}
        <button class="ctl-sm" data-act="geog.near" data-arg="${esc(pl.card)}">${t('geog.near')}</button>
        <button class="ctl-sm" data-act="church.near" data-arg="${esc(`${pl.location.lat},${pl.location.lng}`)}">${t('geog.near.churches')}</button></p>` : ''}
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
