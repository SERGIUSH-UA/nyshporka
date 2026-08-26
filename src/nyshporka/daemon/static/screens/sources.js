/** 🔎 Каталоги: де взагалі є документи — поза цим комп'ютером. */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show, onJob, jobChip } from '../core/nav.js';
import { ic } from '/ui/icons.js';

/**
 * 🔎 Каталоги — зовнішні довідники: сайти архівів, покажчики плівок, Commons.
 *
 * 🔴 Не плутати з «Описами фондів»: там наш власний зібраний реєстр, і «немає»
 * означає «в архіві не існує». Тут — чужі каталоги, і «немає» означає лише
 * «немає в тих, куди ми змогли зазирнути». Два різні «немає», і на другому
 * напрям не закривають.
 *
 * 🔴 Перелік джерел зі станом кожного показується ДО пошуку, а не після.
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

/** 🔴 Знаменник екрана: скільки джерел уміють шукати й скільки мають на чому. */
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
  // 🔴 Живий запит — четвертий стан, а не зріз із порожньою датою. Нуль у
  // ньому означає «немає в покажчику зараз», а не «не було на дату зняття».
  const what = { workspace: t('sources.own'), live: t('sources.live') }[c.kind]
    || t('sources.bundled');
  const bits = [what];
  if (c.taken) bits.push(`${t('sources.taken')} ${esc(c.taken)}`);
  if (c.rows) bits.push(`${esc(c.rows)} ${t('sources.rows')}`);
  if (c.scope) bits.push(esc(c.scope));
  return `<span class="muted">${bits.join(' · ')}</span>`;
}

/**
 * Що можна зробити зі знахідкою.
 *
 * 🔴 Джерело, яке не віддає файлів, теж мусить кудись вести. Зведений покажчик
 * знає про справу все, крім самої справи, — і без адреси його знахідка була б
 * рядком, з яким нічого не зробиш, а виглядало б це як тупик самого пошуку.
 * Кнопка «Завантажити» там, де за нею немає файлу, гірша за її відсутність.
 */
function hitAction(h) {
  if (h.acquirable) {
    return `<button data-act="sources.get" data-source="${esc(h.source)}"
      data-ref="${esc(h.ref)}">${t('sources.get')}</button>`;
  }
  return h.url
    ? `<a href="${esc(h.url)}" target="_blank" rel="noopener">${t('sources.open')}</a>`
    : '';
}

/**
 * 🏛 Фонди, у яких знайшлось, — над списком справ, а не замість нього.
 *
 * 🔴 Пошук по каталогах не самоціль: за ним іде рішення «чи збирати реєстр
 * цього фонду», а воно про ФОНД, не про окрему справу. Плаский список трьох
 * томів одного фонду й трьох випадкових збігів із трьох архівів виглядає
 * однаково, і звідки прийшла знахідка, доводилось вичитувати з шифри очима.
 *
 * Джерела, які фондів не знають (дзеркало адресує плівки), сюди не потрапляють
 * — і саме тому сума по фондах буває меншою за видачу.
 */
function fondsBlock(fonds) {
  if (!fonds.length) return '';
  return `<h3>${t('sources.fonds')}</h3>
    <table><tbody>${fonds.map((f) => `<tr>
      <td><b>${esc(f.label || '?')} ф.${esc(f.fond)}</b><br>
        <span class="muted">${esc(f.sample || '')}</span></td>
      <td class="num">${esc(f.hits)} ${t('sources.fond.hits')}</td>
      <td class="mono">${f.year_from ? `${esc(f.year_from)}–${esc(f.year_to)}` : ''}</td>
      <td class="mono muted">${esc((f.sources || []).join(', '))}</td>
      <td><button data-act="sources.fond" data-repo="${esc(f.repo || f.archive || '')}"
        data-fond="${esc(f.fond)}"
        title="${esc(t('sources.fond.why'))}">${t('sources.fond')}</button></td>
    </tr>`).join('')}</tbody></table>`;
}

/**
 * Картка фонду: чужий покажчик і наш власний стан поруч.
 *
 * 🔴 Обидві половини разом, і це не оформлення. Фонд, який виглядає цікавим,
 * регулярно виявляється вже зібраним — а поки «що це за фонд» і «чи є він у
 * нас» жили на різних екранах, дізнавались про це після збирання.
 */
function fondCard(d) {
  const c = d.card || {};
  const o = d.ours || {};
  const opys = (c.opys || []).map((i) => `<tr>
      <td class="mono">${t('sources.fond.opys')} ${esc(i.opys)}</td>
      <td class="mono">${esc(i.years || '')}</td>
      <td>${esc(i.title || '')}</td>
    </tr>`).join('');
  const ours = o.has_registry
    ? `<b>${esc(o.rows)}</b> ${t('sources.fond.rows')} ·
       ${esc(o.on_disk)} ${t('sources.fond.ondisk')}`
    : `<span class="warn-inline">${t('sources.fond.noregistry')}</span>`;
  return `<div class="box">
    <h3>${esc(d.repo || '')} ф.${esc(d.fond)}</h3>
    <p>${esc(c.title || '')} ${c.years ? `<span class="mono">${esc(c.years)}</span>` : ''}</p>
    <p class="muted">${t('sources.fond.ours')}: ${ours}</p>
    ${opys ? `<table><tbody>${opys}</tbody></table>` : ''}
    ${c.url ? `<p><a href="${esc(c.url)}" target="_blank" rel="noopener">${t('sources.open')}</a></p>` : ''}
  </div>`;
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
    const { hits = [], fonds = [], coverage = {} } = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
      ${fondsBlock(fonds)}
      <div id="fondcard"></div>
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.source)}</td>
        <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}
          ${esc(h.note || '')}</span></td>
        <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
        <td>${hitAction(h)}</td>
      </tr>`).join('')}</tbody></table>
      ${hits.length >= limit
        ? `<p class="warn-inline">${esc(t('sources.ceiling').replace('{n}', limit))}</p>`
        : ''}
      <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
    return undefined;
  },

  /** 🏛 Оцінити фонд перед тим, як збирати його реєстр опису. */
  'sources.fond': async (_ev, elm) => {
    const box = el('fondcard');
    box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.fond',
      { repo: elm.dataset.repo, fond: elm.dataset.fond });
    if (!env.ok) return boxError('fondcard', env);
    box.innerHTML = `${renderWarnings(env)}${fondCard(env.data)}`;
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

  /**
   * ⬇ Забрати знахідку з джерела — і показати це рядком знахідки.
   *
   * 🔴 Завантаження триває довго, а людина в цей час дивиться на видачу
   * пошуку: який саме результат вона взяла, видно лише тут. У переліку робіт
   * цього не видно взагалі, тож перекидання туди міняло зрозумілий стан на
   * незрозумілий.
   */
  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    const near = elm.parentElement;
    if (!env.ok) {
      if (near) near.insertAdjacentHTML('beforeend',
        `<span class="warn-inline">${esc(env.error)}</span>`);
      return undefined;
    }
    elm.disabled = true;                  // друге натискання = друга закачка
    const id = (env.data || {}).job_id;
    if (near && id) {
      // ⚠ Вузол створюється й тримається ПОСИЛАННЯМ. `:last-of-type` рахує
      // останній елемент СВОГО ТИПУ, а не останній із цим класом, — у рядку з
      // кількома `<span>` він знайшов би чужий, і прогрес одного завантаження
      // писався б у сусідній результат пошуку.
      const chip = document.createElement('span');
      chip.className = 'job-here';
      chip.innerHTML = jobChip({ state: 'queued', progress: {} });
      near.appendChild(chip);
      onJob(id, (j) => { chip.innerHTML = jobChip(j); });
    }
    return undefined;
  },
});
