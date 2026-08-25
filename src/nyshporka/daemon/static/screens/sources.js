/** 🔎 Каталоги: де взагалі є документи — поза цим комп'ютером. */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show } from '../core/nav.js';
import { ic } from '/ui/icons.js';

/**
 * 🔎 Каталоги — ЗОВНІШНІ довідники: сайти архівів, покажчики плівок, Commons.
 *
 * 🔴 Не плутати з «Описами фондів»: там наш власний зібраний реєстр, і «немає»
 * означає «в архіві не існує». Тут — чужі каталоги, і «немає» означає лише
 * «немає в тих, куди ми змогли зазирнути». Два різні «немає», і на другому
 * напрям не закривають.
 *
 * 🔴 Перелік джерел зі СТАНОМ кожного показується ДО пошуку, а не після.
 * Доти екран був одним полем вводу: людина набирала село, чекала одинадцять
 * секунд, діставала нуль — і не мала способу дізнатись, що шукали у зрізі
 * одного архіву дворічної давнини, а другий архів не переглядали взагалі.
 */
SCREENS.sources = async () => {
  const gen = curGen();
  busy(4);
  const env = await callOp('sources.list', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data;
  setView(`
    <h2>${t('nav.sources')}</h2>
    <p class="muted">${t('sources.why')}</p>
    <form class="row" data-act="sources.find">
      <input name="q" placeholder="${t('sources.q')}" autofocus>
      <button type="submit">${t('sources.find')}</button>
    </form>
    <div id="hits"></div>
    <h3>${t('sources.where')}</h3>
    ${renderWarnings(env)}
    <p class="muted">${srcCount(d)}</p>
    ${srcTable(d.sources || [])}`);
};

/** 🔴 Знаменник екрана: скільки джерел УМІЮТЬ шукати й скільки мають на чому. */
function srcCount(d) {
  return esc(t('sources.count')
    .replace('{ok}', d.with_catalog ?? 0)
    .replace('{n}', d.searchable ?? 0)
    .replace('{all}', d.shown ?? 0));
}

function srcTable(rows) {
  return `<table><tbody>${rows.map((s) => {
    const c = s.catalog || {};
    return `<tr>
      <td><b>${esc(s.label)}</b><br>
        <span class="muted mono">${esc(s.id)}</span></td>
      <td>${srcCaps(s.caps || [])}</td>
      <td>${srcBasis(c)}</td>
      <td>${(s.caps || []).includes('browse')
        ? `<button data-act="sources.browse" data-arg="${esc(s.id)}"
             title="${esc(t('sources.browse.why'))}">${t('sources.browse')}</button>`
        : ''}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
}

/** Що джерело вміє — знаками, бо їх читають краєм ока. */
function srcCaps(caps) {
  const bits = [];
  if (caps.includes('search')) bits.push(`<span title="${esc(t('sources.cap.search'))}">🔎</span>`);
  if (caps.includes('browse')) bits.push(`<span title="${esc(t('sources.cap.browse'))}">🌳</span>`);
  if (caps.includes('fetch')) bits.push(`<span title="${esc(t('sources.cap.fetch'))}">⬇</span>`);
  return bits.join(' ');
}

/**
 * На чому це джерело шукає.
 *
 * 🔴 Три стани, і плутати їх дорого: власний обхід (найсвіжіший), вкладений у
 * пакет зріз (датований, вужчий) і «нема на чому» — останнє означає, що нуль
 * від цього джерела не є відповіддю взагалі.
 */
function srcBasis(c) {
  if (!c.searchable) return `<span class="dim">${t('sources.nosearch')}</span>`;
  if (c.kind === 'none') {
    return `<span class="warn-inline">${t('sources.blind')}</span>
      ${c.fix ? `<br><code class="mono">${esc(c.fix)}</code>` : ''}`;
  }
  const what = c.kind === 'workspace' ? t('sources.own') : t('sources.bundled');
  const bits = [what];
  if (c.taken) bits.push(`${t('sources.taken')} ${esc(c.taken)}`);
  if (c.rows) bits.push(`${esc(c.rows)} ${t('sources.rows')}`);
  if (c.scope) bits.push(esc(c.scope));
  return `<span class="muted">${bits.join(' · ')}</span>`;
}

Object.assign(ACTIONS, {
  'sources.find': async (ev) => {
    ev.preventDefault();
    const q = new FormData(ev.target).get('q');
    const unlock = busyForm(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const limit = 40;
    const env = await callOp('catalog.search', { q, limit });
    unlock();
    if (!env.ok) return boxError('hits', env);
    const { hits = [], coverage = {} } = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.source)}</td>
        <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}</span></td>
        <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
        <td>${h.acquirable
          ? `<button data-act="sources.get" data-source="${esc(h.source)}" data-ref="${esc(h.ref)}">${t('sources.get')}</button>`
          : ''}</td>
      </tr>`).join('')}</tbody></table>
      ${hits.length >= limit
        ? `<p class="warn-inline">${esc(t('sources.ceiling').replace('{n}', limit))}</p>`
        : ''}
      <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
    return undefined;
  },

  /** 🌳 Що взагалі лежить у цьому джерелі — до всякого запиту. */
  'sources.browse': async (_ev, elm) => {
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.browse', { source: elm.dataset.arg });
    if (!env.ok) return boxError('hits', env);
    const nodes = env.data.nodes || [];
    el('hits').innerHTML = `${renderWarnings(env)}
      ${nodes.length ? `<table><tbody>${nodes.map((n) => `<tr>
        <td class="mono">${esc(n.ref || '')}</td>
        <td>${esc(n.label || '')}</td>
        <td class="num">${n.frames ? `${n.frames} ${t('common.frames')}` : ''}</td>
      </tr>`).join('')}</tbody></table>`
        : `<p class="muted">${t('sources.nonodes')}</p>`}
      ${renderCoverage(env)}`;
    return undefined;
  },

  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    if (!env.ok) return alert(env.error);
    return show('jobs');
  },
});
