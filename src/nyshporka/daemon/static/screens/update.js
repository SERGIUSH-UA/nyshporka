/**
 * ⬆️ Оновлення: що стоїть, що вийшло, що в ньому нового — і кнопка.
 *
 * «Що нового» — примітки випусків з порталу (заголовок і одне речення, а
 * «Детальніше» веде на сторінку порталу), а не рядки git. Моделі, яких на
 * машині ще немає, — тут же: нова модель приходить разом з оновленням
 * застосунку, і без цього блоку люди сиділи на старих вагах роками.
 *
 * 🔴 Без мережі за замовчуванням: екран показує збережене, «Перевірити зараз» —
 * дія людини. Фонову перевірку вмикають тут же або в Налаштуваннях.
 */

import { t, LANG } from '../core/strings.js';
import { callOp, staleThenFresh } from '../core/net.js';
import { esc, el, setView, failure, curGen, alive, mini, emptyMini, maskot } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal } from '../core/modal.js';
import { onJob, jobChip } from '../core/nav.js';
import { toast, fmtDay, pill } from '../core/bits.js';
import { bellLoad } from '../core/bell.js';
import { skelCards } from '/ui/dom.js';

SCREENS.update = async () => {
  const gen = curGen();
  setView(`<div class="read-picks">${skelCards(3)}</div>`);
  await staleThenFresh('notices.state', { lang: LANG }, (env) => {
    if (alive(gen)) paintUpdate(env);
  });
};

/** Розмір пака словами: «312 МБ». */
function mb(bytes) {
  const n = Number(bytes || 0);
  return n ? `${Math.round(n / (1024 * 1024))} ${t('up.mb')}` : '';
}

export function paintUpdate(env) {
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const s = d.settings || {};
  bellLoad(env);
  const head = d.newer
    ? `<h3>${esc(t('up.new').replace('{v}', d.latest))}</h3>
       <p class="up-vers">${pill('neutral', d.installed)} <span aria-hidden="true">→</span> ${pill('ok', d.latest)}</p>`
    : `<h3>${esc(d.latest ? t('up.fresh') : t('up.unknown'))}</h3>
       <p class="up-vers">${pill('neutral', d.installed)}</p>`;
  const checked = d.checked_at ? t('up.checked').replace('{d}', fmtDay(new Date(d.checked_at * 1000).toISOString().slice(0, 10))) : t('up.never');
  const rels = (d.releases || []).map((r) => `<article class="card up-rel">
      <small class="muted">${esc(fmtDay(r.date))} · ${esc(r.version)}</small>
      <b>${esc(r.title)}</b><p>${esc(r.summary)}</p>
      ${/^https:\/\//.test(r.url || '') ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(t('up.more'))} →</a>` : ''}
    </article>`).join('');
  const models = (d.models || []).map((m) => `<li><b>${esc(m.label)}</b> <small class="muted">${esc(mb(m.size))}${
    m.reason === 'update' ? ` · ${esc(t('up.model.newer'))}` : ''}</small></li>`).join('');
  setView(`
    <div class="card up-hero">${maskot(d.newer ? 'vyishlo' : d.latest ? 'onovleno' : 'chekaie', 150, 'up-maskot')}<div class="up-hero-t">${head}
      <p class="muted">${esc(checked)}</p></div>
      <div class="up-acts">${d.newer ? `<button class="primary" data-act="up.apply">${esc(t('up.apply'))}</button>` : ''}
        <button data-act="up.check">${esc(t('bell.check'))}</button></div></div>
    <h3 class="sub-h">${esc(t('up.whatsnew'))}</h3>
    ${rels ? `<div class="up-rels">${rels}</div>` : emptyMini('lihtar', esc(d.newer ? t('up.nonotes') : t('up.nonews')))}
    <h3 class="sub-h">${esc(t('up.models'))}</h3>
    ${models ? `<div class="card up-models">${mini('kolba', 56)}<div><ul>${models}</ul>
        <button data-act="up.models">${esc(t('up.models.get'))}</button><span id="up-models-job"></span></div></div>`
    : `<p class="muted">${esc(t('up.models.ok'))}</p>`}
    <h3 class="sub-h">${esc(t('up.net'))}</h3>
    ${netBox(s, d.logged_in)}`);
  return undefined;
}

/** Вимикачі мережі — ті самі, що в Налаштуваннях: що йде і куди. */
export function netBox(s, loggedIn) {
  return `<div class="card net-box">
    <label class="chk"><input type="checkbox" data-act="net.set" data-arg="updates"${s.updates ? ' checked' : ''}>
      <span><b>${esc(t('net.updates'))}</b><small class="muted">${esc(t('net.updates.why'))}</small></span></label>
    <label class="chk"><input type="checkbox" data-act="net.set" data-arg="supriaha"${s.supriaha ? ' checked' : ''}${loggedIn ? '' : ' disabled'}>
      <span><b>${esc(t('net.sup'))}</b><small class="muted">${esc(loggedIn ? t('net.sup.why') : t('net.sup.login'))}</small></span></label>
  </div>`;
}

Object.assign(ACTIONS, {
  'up.check': async () => {
    const env = await callOp('notices.check', { lang: LANG });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    paintUpdate(env);
    toast(env.data.newer ? t('bell.new').replace('{v}', env.data.latest) : t('bell.checked'),
      { tone: env.data.newer ? 'info' : 'ok' });
  },
  /** Вимикач мережі: записати й одразу показати, що змінилось. */
  'net.set': async (_ev, elm) => {
    const key = elm.dataset.arg;
    const env = await callOp('settings.net', { [key]: !!elm.checked });
    if (!env.ok) { elm.checked = !elm.checked; toast(env.error || t('common.error'), { tone: 'err' }); return; }
    toast(elm.checked ? t('net.on') : t('net.off'), { tone: 'ok' });
    await bellLoad();
  },
  'up.models': async () => {
    const env = await callOp('models.get', {});
    const box = el('up-models-job');
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    const jid = (env.data || {}).job_id;
    if (box && jid) box.innerHTML = jobChip({ state: 'queued', progress: {} });
    if (jid) {
      onJob(jid, async (j) => {
        if (box && document.contains(box)) box.innerHTML = jobChip(j);
        if (j.state === 'done') { toast(t('up.models.done'), { tone: 'ok' }); await bellLoad(); }
      });
    }
  },
  /** Оновлення: поки — команда для термінала з поясненням (одним натиском — далі). */
  'up.apply': async () => {
    const env = await callOp('update.check', {});
    const how = (env.ok && env.data && env.data.how) || '';
    openModal({ title: t('up.apply'), body: `<p>${esc(t('ver.how'))}</p>
      ${how ? `<pre class="mono">${esc(how)}</pre>` : ''}
      <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${esc(t('modal.close'))}</button></div>` });
  },
});
