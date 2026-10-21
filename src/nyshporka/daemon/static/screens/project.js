/** 📁 Проєкти Майстерні: новий проєкт (вікно), перехід у проєкт, картки на Огляді. */

import { t } from '../core/strings.js';
import { PROJECT, callOp } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';

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

Object.assign(ACTIONS, {
  'project.go': (_ev, elm) => openProject(elm.dataset.arg, elm.dataset.back || ''),

  'project.create': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const done = busyForm(ev.target);
    const env = await callOp('project.new', {
      name: String(fd.name || '').trim(),
      title: String(fd.title || '').trim(),
      surname: String(fd.surname || '').trim(),
      kind: fd.kind === 'order' ? 'order' : 'family',
    });
    done();
    if (!env.ok) { boxError('np-box', env); return; }
    openProject(String(fd.name || '').trim());
  },
});

// Вузол форми потрібен лише щоб тест міг перевірити, що вікно намалювалось.
export const npForm = () => el('np-form');
