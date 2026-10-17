/** 🌐 Сайт родини: зібрати з канону, перезібрати й відкрити — не виходячи з консолі. */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, boxError, renderWarnings } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show, onJob, jobChip } from '../core/nav.js';
import { ic } from '/ui/icons.js';

/**
 * 🔴 Сайт віддає сама консоль (`/site/`, `/site-public/`), тож кнопка
 * «Відкрити» веде туди, де людина вже є, а не на окремий сервер, який треба
 * тримати запущеним у другому вікні.
 *
 * Дві версії поруч, бо це два різні рішення: приватна — для себе й родини
 * (живі з датами до десятиліття), відкрита — для інтернету, і її збірку
 * перевіряє сторож: витік — відмова з переліком, а HTML не лишається.
 */

const when = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined,
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

function card(kind, info, canon, can = true) {
  const pub = kind === 'public';
  const c = info.counts || {};
  const stale = info.built && canon && c.persons !== undefined && !pub && c.persons !== canon;
  return `<div class="card site-card" id="site-${kind}">
    <h3>${ic(pub ? 'upload' : 'disk', 'ic-sm')} ${t(pub ? 'site.public' : 'site.private')}</h3>
    <p class="muted">${t(pub ? 'site.public.why' : 'site.private.why')}</p>
    <p>${info.built
    ? `${esc(t('site.built').replace('{t}', when(info.built_at)))}${c.persons !== undefined
      ? ` · ${esc(t('site.counts').replace('{p}', c.persons).replace('{f}', c.families ?? 0)
        .replace('{h}', c.hypotheses ?? 0))}` : ''}`
    : `<span class="muted">${t('site.none')}</span>`}</p>
    ${stale ? `<p class="warn">${esc(t('site.stale').replace('{n}', canon).replace('{s}', c.persons))}</p>` : ''}
    <div class="row">
      ${info.built ? `<a class="btn-solid" href="${esc(info.url)}" target="_blank" rel="noopener">${
    ic('link', 'ic-sm')} ${t('site.open')}</a>` : ''}
      <button type="button" data-act="site.rebuild" ${can ? '' : 'disabled'}
        data-arg="${pub ? '1' : ''}">${ic('refresh', 'ic-sm')} ${t(info.built ? 'site.rebuild' : 'site.build')}</button>
    </div>
    ${pub && info.built ? `<p class="muted">${t('site.folder')}: <span class="mono">${esc(info.path)}</span></p>` : ''}
    <div class="site-job"></div>
  </div>`;
}

SCREENS.site = async () => {
  setView(`<h2>${t('nav.site')}</h2>
    <p class="muted">${t('site.why')}</p>
    <div id="site-cards"><p class="muted">${t('common.loading')}</p></div>`);
  const env = await callOp('site.status', {});
  if (!env.ok) return boxError('site-cards', env);
  const d = env.data || {};
  const box = el('site-cards');
  if (!box) return undefined;
  box.innerHTML = `
    ${d.mkdocs === false ? `<div class="warn">${t('site.nomkdocs')}
      <span class="mono">pip install "nyshporka[site]"</span></div>` : ''}
    ${d.canon_persons ? '' : `<div class="warn">${t('site.nocanon')}</div>`}
    <div class="site-cards">${card('private', d.private || {}, d.canon_persons, d.mkdocs !== false)}${
  card('public', d.public || {}, d.canon_persons, d.mkdocs !== false)}</div>`;
  return undefined;
};

Object.assign(ACTIONS, {
  /**
   * Перезібрати — роботою в черзі: MkDocs на кількасот сторінок іде хвилини, і
   * вкладка не мусить висіти. Поступ — тут, де натиснули, і в «Роботах».
   */
  'site.rebuild': async (_ev, elm) => {
    const pub = elm.dataset.arg === '1';
    const slot = el(`site-${pub ? 'public' : 'private'}`);
    const out = slot && slot.querySelector('.site-job');
    elm.disabled = true;
    const env = await callOp('site.rebuild', { public: pub });
    if (!env.ok) {
      elm.disabled = false;
      if (out) out.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return undefined;
    }
    const id = (env.data || {}).job_id;
    if (out) out.innerHTML = `<p class="muted">${jobChip({ state: 'queued', progress: {} })} ${t('site.going')}</p>`;
    onJob(id, (j) => {
      if (!out) return;
      if (j.state === 'done') { show('site'); return; }
      if (j.state === 'error') {
        elm.disabled = false;
        out.innerHTML = `<div class="warn err">${esc(j.error || t('job.failed'))}</div>
          ${renderWarnings({ warnings: j.warnings || [] })}`;
        return;
      }
      out.innerHTML = `<p class="muted">${jobChip(j)} ${t('site.going')}</p>`;
    });
    return undefined;
  },
});
