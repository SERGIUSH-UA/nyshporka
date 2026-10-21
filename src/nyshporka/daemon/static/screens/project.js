/** 📁 Проєкти Майстерні: новий проєкт (вікно), перехід у проєкт, картки на Огляді. */

import { t } from '../core/strings.js';
import { PROJECT, callOp } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto } from '../core/nav.js';
import { openModal, closeModal } from '../core/modal.js';
import { pill } from '../core/bits.js';

/**
 * Перейти в проєкт: нова адреса вкладки (`?p=`), а не стан сторінки — інакше
 * вже завантажені екрани лишились би з даними попереднього проєкту.
 * `back` — екран, на який людина йшла, коли її спитали «який проєкт».
 */
export function openProject(id, back = '') {
  if (id === PROJECT && !back) return;
  const q = new URLSearchParams(location.search);
  if (id) q.set('p', id); else q.delete('p');
  location.href = `${location.pathname}?${q.toString()}${back ? `#${back}` : ''}`;
}

SCREENS.newproject = async () => {
  // 🔴 Прізвище — у тій самій формі: без профілю пошук роду в новому проєкті
  // не знає, що шукати, і перший же «Шукати» відповідав би порожнечею.
  setView(`<p class="muted">${t('np.why')}</p>
    <form data-act="project.create" id="np-form">
      <div class="row">${fld(t('np.title'), `<input name="title" placeholder="${t('np.title.ph')}" autofocus>`)}</div>
      <div class="row">${fld(t('np.name'), `<input name="name" placeholder="bondar" pattern="[a-z0-9][a-z0-9-]*" required>`)}</div>
      <p class="muted fld-hint">${t('np.name.hint')}</p>
      <div class="row">${fld(t('np.surname'), `<input name="surname" placeholder="${t('np.surname.ph')}">`)}</div>
      <div class="row">${fld(t('np.variants'), `<input name="variants" placeholder="${t('np.variants.ph')}">`)}</div>
      <p class="muted fld-hint">${t('np.variants.hint')}</p>
      <div class="row">${fld(t('np.color'), `<input name="color" type="color" value="#4f6bd8">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3">`)}</div>
      <div class="row">${fld(t('np.kind'), `<select name="kind">
        <option value="family">${t('np.kind.family')}</option>
        <option value="order">${t('np.kind.order')}</option></select>`)}</div>
      <div class="row dlg-acts"><button type="submit" class="primary">${t('np.create')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="np-box"></div>
    </form>`);
};

/**
 * Картки проєктів для Огляду Майстерні.
 *
 * 🔴 Замість відмови «Оберіть проєкт»: у Майстерні без проєкту людина бачить, які
 * роди тут ведуться, і заходить у потрібний одним кліком.
 */
export async function projectCards() {
  const env = await callOp('project.list', {});
  if (!env.ok) return '';
  const list = ((env.data || {}).projects || []).filter((p) => !p.archived);
  const cards = list.map((p) => `<div class="pcard">
      <div class="pcard-t"><b>${esc(p.name || p.id)}</b>
        <span class="muted">${esc(t(`np.kind.${p.kind === 'order' ? 'order' : 'family'}`))}</span></div>
      ${p.persons !== undefined ? `<span class="muted">${esc(t('project.persons').replace('{n}', p.persons))}</span>` : ''}
      <button data-act="project.go" data-arg="${esc(p.id)}">${t('project.open')}</button>
    </div>`).join('');
  return `<section class="hub-projects"><h3>${t('project.cards')}</h3>
    <div class="pcards">${cards}
      <div class="pcard pcard-new"><b>${t('stage.act.newproject')}</b>
        <span class="muted">${t('np.why')}</span>
        <button class="primary" data-act="nav" data-arg="newproject">${t('np.create')}</button></div>
    </div></section>`;
}

/** Проєкт, на верх якого дивимось: стиль змінюється саме йому. */
let HEAD = null;

/**
 * Верх Огляду проєкту: рід, кроки, «що вирішити», непрошукане за родом.
 *
 * 🔴 «Що вирішити» — з `canon.next`, тобто з карток гіпотез, а не з нотаток:
 * той самий перелік бачить агент. Порожньо — карток гіпотез немає, і це
 * сказано словами, а не нулем.
 */
export async function projectHead() {
  const st = await callOp('project.status', {});
  if (!st.ok || !(st.data || {}).project) return '';
  const d = st.data;
  HEAD = d;
  const [nxt, todo] = await Promise.all([
    callOp('canon.next', { limit: 5 }),
    callOp('cases.list', { htr: 'read', searched: 'not_here', limit: 1 })]);
  const h = d.hypotheses || {};
  const step = (on, label, value) => `<div class="step ${on ? 't-done' : 't-todo'}"><span class="step-t">${
    esc(label)}</span><b>${esc(value)}</b></div>`;
  const decisions = ((nxt.ok && nxt.data && nxt.data.next) || []).map((x) => `<div class="lrow">
      <div><b>${esc(x.claim)}</b><small class="muted">${esc(x.id)}${x.decides ? ` · ${esc(x.decides)}` : ''}${
  (x.hits || []).length ? ` · ${esc(t('hyp.hits').replace('{n}', x.hits.length))}` : ''}</small></div>
      <button data-act="phead.hyp" data-arg="${esc(x.id)}">${t('canon.open')}</button></div>`).join('');
  const left = todo.ok ? (todo.data || {}).total : null;
  return `<section class="proj-head">
    <div class="row"><h2>${esc(`${d.glyph || ''} ${d.name || d.project}`.trim())}</h2>
      <span class="muted">${esc(t(`np.kind.${d.kind === 'order' ? 'order' : 'family'}`))}${
  d.surname ? ` · ${esc(d.surname)}` : ''}</span>
      <button class="ctl-sm" data-act="phead.style">${t('phead.style')}</button></div>
    <div class="steps">
      ${step(!!d.surname, t('phead.step.profile'), d.surname || t('phead.none'))}
      ${step(left !== null && left === 0, t('phead.step.search'),
    left === null ? '—' : t('phead.left').replace('{n}', left))}
      ${step(!!d.persons, t('phead.step.canon'), t('project.persons').replace('{n}', d.persons || 0))}
      ${step(!(h.open || h.awaiting), t('phead.step.hyp'),
    `${h.open || 0} / ${h.awaiting || 0} / ${h.closed || 0}`)}
    </div>
    <div class="dash-two">
      <div class="dash-box"><div class="row"><h3>${t('canon.next')}</h3>${
  pill((h.open || h.awaiting) ? 'warn' : 'ok', String((h.open || 0) + (h.awaiting || 0)))}</div>
        ${decisions || `<p class="muted">${esc(nxt.ok ? t('canon.next.none') : (nxt.error || ''))}</p>`}
        <p class="row"><button data-act="nav" data-arg="canon">${t('nav.canon')}</button>
          <button class="ghost" data-act="nav" data-arg="history">${t('nav.history')}</button></p></div>
      <div class="dash-box"><h3>${t('phead.material')}</h3>
        <p>${left !== null ? esc(t('phead.material.left').replace('{n}', left))
    : todo.ok ? `${t('lib.unbuilt')} <span class="mono">nysh cases build</span>` : esc(todo.error || '')}</p>
        <p class="row"><button data-act="nav" data-arg="search">${t('nav.search')}</button>
          <button class="ghost" data-act="nav" data-arg="library">${t('nav.library')}</button></p></div>
    </div></section>`;
}

function styleForm() {
  const d = HEAD || {};
  openModal({ title: t('phead.style'), narrow: true, body: `<form data-act="phead.save">
      <div class="row">${fld(t('np.color'), `<input name="color" type="color" value="${esc(d.color || '#4f6bd8')}">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3" value="${esc(d.glyph || '')}">`)}</div>
      <div class="row dlg-acts"><button type="submit" class="primary">${t('sp.save')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="ps-box"></div></form>` });
}

Object.assign(ACTIONS, {
  'phead.hyp': (_ev, elm) => goto('hyp', { id: elm.dataset.arg }),
  'phead.style': () => styleForm(),
  'phead.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('project.style', { name: (HEAD || {}).project || PROJECT,
      color: String(fd.color || ''), glyph: String(fd.glyph || '').trim() });
    if (!env.ok) { boxError('ps-box', env); return; }
    closeModal(true);
    location.reload();
  },
  'project.go': (_ev, elm) => openProject(elm.dataset.arg, elm.dataset.back || ''),

  'project.create': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const done = busyForm(ev.target);
    const env = await callOp('project.new', {
      name: String(fd.name || '').trim(),
      title: String(fd.title || '').trim(),
      surname: String(fd.surname || '').trim(),
      variants: String(fd.variants || '').split(',').map((v) => v.trim()).filter(Boolean),
      color: String(fd.color || ''),
      glyph: String(fd.glyph || '').trim(),
      kind: fd.kind === 'order' ? 'order' : 'family',
    });
    done();
    if (!env.ok) { boxError('np-box', env); return; }
    openProject(String(fd.name || '').trim());
  },
});

// Вузол форми потрібен лише щоб тест міг перевірити, що вікно намалювалось.
export const npForm = () => el('np-form');
