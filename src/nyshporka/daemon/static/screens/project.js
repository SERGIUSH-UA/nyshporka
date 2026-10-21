/** 📁 Проєкти Майстерні: новий проєкт (вікно), перехід у проєкт, картки на Огляді. */

import { t } from '../core/strings.js';
import { PROJECT, callOp } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, fld, humanError } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto, jobDone, jobChip } from '../core/nav.js';
import { openModal, closeModal } from '../core/modal.js';
import { unwiki } from '../core/bits.js';

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
      <div class="row">${fld(t('np.name'), `<input name="name" placeholder="bondar" pattern="[a-z0-9][a-z0-9\\-]*" required>`)}</div>
      <p class="muted fld-hint">${t('np.name.hint')}</p>
      <div class="row">${fld(t('np.surname'), `<input name="surname" placeholder="${t('np.surname.ph')}">`)}</div>
      <div class="row">${fld(t('np.variants'), `<input name="variants" placeholder="${t('np.variants.ph')}">`)}</div>
      <p class="muted fld-hint">${t('np.variants.hint')}</p>
      <div class="row"><label class="chk"><input type="checkbox" name="usecolor" value="1"> ${t('np.usecolor')}</label>
        ${fld(t('np.color'), `<input name="color" type="color" value="#4f6bd8">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3">`)}</div>
      <div class="row">${fld(t('np.kind'), `<select name="kind">
        <option value="family">${t('np.kind.family')}</option>
        <option value="order">${t('np.kind.order')}</option></select>`)}</div>
      <div class="row dlg-acts"><button type="submit" class="primary">${t('np.create')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="np-box"></div>
    </form>`);
};

/** Кружок проєкту: знак (або перша літера) на кольорі проєкту. */
function badge(p) {
  const color = /^#[0-9a-fA-F]{6}$/.test(p.color || '') ? p.color : '';
  const mark = p.glyph || String(p.name || p.id || '?').trim().charAt(0).toUpperCase();
  return `<span class="pj-badge"${color ? ` style="--pj:${esc(color)}"` : ''}>${esc(mark)}</span>`;
}

/**
 * Картки проєктів для Огляду Майстерні.
 *
 * 🔴 Замість відмови «Оберіть проєкт»: у Майстерні без проєкту людина бачить, які
 * роди тут ведуться, і заходить у потрібний одним кліком. Картка — окремий,
 * виразний предмет (тло, тінь, смуга кольору проєкту): до 7в вона зливалась із
 * дашбордом під нею, і проєкти не читались як вхід.
 */
export async function projectCards() {
  const env = await callOp('project.list', {});
  if (!env.ok) return '';
  const list = ((env.data || {}).projects || []).filter((p) => !p.archived);
  const cards = list.map((p) => {
    const h = p.hypotheses || {};
    const open = (h.open || 0) + (h.awaiting || 0);
    const color = /^#[0-9a-fA-F]{6}$/.test(p.color || '') ? ` style="--pj:${esc(p.color)}"` : '';
    return `<button class="pj-card" data-act="project.go" data-arg="${esc(p.id)}"${color}>
      <span class="pj-top">${badge(p)}<span><b>${esc(p.name || p.id)}</b>
        <small>${esc(t(`np.kind.${p.kind === 'order' ? 'order' : 'family'}`))}</small></span></span>
      <span class="pj-stats">
        <span><b class="num">${esc(p.persons ?? 0)}</b> ${esc(t('pj.persons'))}</span>
        <span${open ? ' class="pj-warn"' : ''}><b class="num">${esc(open)}</b> ${esc(t('pj.open'))}</span>
      </span>
      <span class="pj-go">${t('project.open')} →</span>
    </button>`;
  }).join('');
  return `<section class="hub-projects"><h2>${t('project.cards')}</h2>
    <div class="pj-cards">${cards}
      <button class="pj-card pj-new" data-act="nav" data-arg="newproject">
        <span class="pj-top"><span class="pj-badge">+</span><b>${t('stage.act.newproject')}</b></span>
        <small class="muted">${t('np.why')}</small></button>
    </div></section>`;
}

/** Проєкт, на верх якого дивимось: стиль змінюється саме йому. */
let HEAD = null;

/** Картка-показник Огляду проєкту: число, підпис, перехід на закладку. */
function kpi(id, label, nav) {
  return `<button class="ov-kpi" id="${id}" data-act="nav" data-arg="${nav}">
    <span class="ov-kpi-l">${esc(label)}</span>
    <span class="ov-kpi-v"><span class="muted ov-wait">${t('common.loading')}</span></span>
    <span class="ov-kpi-s"></span></button>`;
}

function setKpi(id, value, sub, tone = '') {
  const n = el(id);
  if (!n) return;
  n.className = `ov-kpi${tone ? ` ov-${tone}` : ''}`;
  const v = n.querySelector('.ov-kpi-v');
  const s2 = n.querySelector('.ov-kpi-s');
  if (v) v.innerHTML = value;
  if (s2) s2.innerHTML = sub;
}

/**
 * Каркас Огляду проєкту — одразу, без жодного запиту.
 *
 * 🔴 Показники доїжджають кожен своїм запитом (`fillProject`). На великому
 * просторі реєстр відповідає за секунди, а перевірка машини — за десятки:
 * чекати найповільнішого, щоб показати назву роду й «що вирішити», означало
 * дивитись на сірі смуги пів хвилини (замір на живому просторі 22.10.2026).
 */
export function projectShell() {
  return `<section class="ov" id="ov-head">
    <div class="ov-title"><span id="ov-badge"></span>
      <div><h2 id="ov-name">${esc(PROJECT || '')}</h2><span class="muted" id="ov-sub"></span></div>
      <button class="ghost ctl-sm ov-style" data-act="phead.style">${t('phead.style')}</button></div>
    <div class="ov-kpis">
      ${kpi('ov-k-canon', t('nav.canon'), 'canon')}
      ${kpi('ov-k-hyp', t('nav.hyp'), 'hyp')}
      ${kpi('ov-k-mat', t('phead.material'), 'search')}
      ${kpi('ov-k-hist', t('nav.history'), 'history')}
    </div>
    <div class="ov-cols">
      <div class="dash-box"><h3>${t('canon.next')}</h3><div id="ov-decide"><span class="skel-cell"></span></div></div>
      <div class="dash-box"><h3>${t('ov.new')}</h3><div id="ov-new"><span class="skel-cell"></span></div></div>
    </div>
    <div class="dash-box" id="ov-mat" hidden></div>
  </section>`;
}

/**
 * Наповнити каркас. `stillHere()` — чи екран ще той самий: запізніла відповідь не
 * домальовує чужий Огляд.
 *
 * 🔴 Нуль без знаменника не буває зеленим: «0 непрошуканих» при нулі
 * прочитаних — це «ще нічого не прочитано», а не «усе прошукано».
 */
export async function fillProject(stillHere = () => true) {
  const jobs = [
    callOp('project.status', {}).then((st) => {
      if (!stillHere() || !st.ok || !(st.data || {}).project) return;
      const d = st.data;
      HEAD = d;
      const n = el('ov-name');
      if (n) n.textContent = d.name || d.project;
      const sub = el('ov-sub');
      if (sub) {
        sub.textContent = `${t(`np.kind.${d.kind === 'order' ? 'order' : 'family'}`)}${
          d.surname ? ` · ${d.surname}` : ''}`;
      }
      const b = el('ov-badge');
      if (b) b.innerHTML = badge({ ...d, id: d.project });
      setKpi('ov-k-canon', `<b class="num">${esc(d.persons || 0)}</b>`, esc(t('pj.persons')),
        d.persons ? 'ok' : '');
      const h = d.hypotheses || {};
      setKpi('ov-k-hyp', `<b class="num">${esc(h.open || 0)}</b> / <b class="num">${esc(h.awaiting || 0)}</b>`,
        esc(t('ov.hyp.sub')), h.awaiting ? 'warn' : (h.open ? 'info' : ''));
    }),
    callOp('canon.next', { limit: 3 }).then((nx) => {
      const box = el('ov-decide');
      if (!stillHere() || !box) return;
      if (!nx.ok) { box.innerHTML = `<p class="muted">${humanError(nx.error)}</p>`; return; }
      const d = nx.data || {};
      const more = (d.open || 0) + (d.awaiting || 0) - (d.next || []).length;
      box.innerHTML = (d.next || []).length ? (d.next || []).map((x) => `<button class="ov-row" data-act="phead.hyp"
          data-arg="${esc(x.id)}"><span class="pill ${x.status === 'awaiting' ? 'warn' : 'info'}">${esc(x.id)}</span>
          <span><b>${esc(unwiki(x.claim))}</b>${x.decides ? `<small class="muted">${esc(t('hyp.decides'))}: ${
  esc(unwiki(x.decides))}</small>` : ''}</span></button>`).join('')
        + (more > 0 ? `<p><button class="ghost ctl-sm" data-act="nav" data-arg="hyp">${
          esc(t('ov.more').replace('{n}', more))}</button></p>` : '')
        : `<p class="muted">${t('canon.next.none')}</p>`;
    }),
    fillMaterial(stillHere),
    Promise.all([callOp('history.log', { limit: 4 }), callOp('reports.list', {})]).then(([hl, rl]) => {
      const box = el('ov-new');
      if (!stillHere() || !box) return;
      const rows = (hl.ok && (hl.data || {}).rows) || [];
      const last = rows[0];
      setKpi('ov-k-hist', last ? `<b>${esc(last.date)}</b>` : '—',
        esc(last ? `${t('ov.hist.last')}: ${last.subject}` : (hl.ok ? t('hist.empty') : t('ov.hist.none'))));
      const reps = ((rl.ok && (rl.data || {}).rows) || []).slice(0, 3);
      const items = [
        ...rows.map((r) => `<div class="ov-feed"><span class="muted mono">${esc(r.date)}</span><span>${
          esc(r.subject)}</span></div>`),
        ...reps.map((r) => `<button class="ov-feed ov-link" data-act="rs.read" data-arg="${esc(r.path)}">
          <span class="muted">📝</span><span>${esc(r.title)}</span></button>`)];
      box.innerHTML = items.length ? items.join('') : `<p class="muted">${t('ov.new.none')}</p>`;
    }),
  ];
  await Promise.all(jobs);
}

/** Матеріал Майстерні зрізом проєкту: скільки прочитаного він ще не шукав. */
async function fillMaterial(stillHere = () => true) {
  const [all, left] = await Promise.all([
    callOp('cases.list', { htr: 'read', limit: 1 }),
    callOp('cases.list', { htr: 'read', searched: 'not_here', limit: 1 })]);
  if (!stillHere()) return;
  const read = all.ok ? (all.data || {}).total : null;
  const todo = left.ok ? (left.data || {}).total : null;
  const mat = el('ov-mat');
  if (read === null || read === undefined) {
    // Реєстру немає — це «ще не зібрано», а не нуль справ.
    setKpi('ov-k-mat', '—', esc(t('ov.mat.noreg')));
    // Без реєстру людині треба в Бібліотеку (там «перезібрати»), а не в Пошук.
    const card = el('ov-k-mat');
    if (card) card.dataset.arg = 'library';
    if (mat && all.ok) {
      mat.hidden = false;
      mat.innerHTML = `<p>${t('lib.unbuilt')}</p><p><button data-act="phead.build">${t('cases.build')}</button>
        <span id="ov-mat-note" class="muted"></span></p>`;
    }
    return;
  }
  if (mat) mat.hidden = true;
  if (!read) {
    setKpi('ov-k-mat', '<b class="num">0</b>', esc(t('ov.mat.noread')));
    return;
  }
  setKpi('ov-k-mat', `<b class="num">${esc(todo ?? '—')}</b>`,
    esc(t('ov.mat.sub').replace('{n}', read)), todo ? 'warn' : 'ok');
}

function styleForm() {
  const d = HEAD || {};
  openModal({ title: t('phead.style'), narrow: true, body: `<form data-act="phead.save">
      <input type="hidden" name="touched" value="">
      <div class="row">${fld(t('np.color'), `<input name="color" type="color" data-act="phead.touch"
        value="${esc(/^#[0-9a-fA-F]{6}$/.test(d.color || '') ? d.color : '#4f6bd8')}">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3" value="${esc(d.glyph || '')}">`)}</div>
      ${d.color ? `<label class="chk"><input type="checkbox" name="nocolor" value="1"> ${t('ov.nocolor')}</label>` : ''}
      <div class="row dlg-acts"><button type="submit" class="primary">${t('sp.save')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="ps-box"></div></form>` });
}

Object.assign(ACTIONS, {
  'phead.hyp': (_ev, elm) => goto('hyp', { id: elm.dataset.arg }),
  'phead.style': () => styleForm(),
  'phead.save': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const was = HEAD || {};
    // Колір іде лише тоді, коли його змінили або зняли: міняючи знак, людина
    // не мала б мовчки дістати колір, що стояв у полі за замовчуванням.
    const color = fd.get('nocolor') ? '' : String(fd.get('color') || '');
    const args = { name: was.project || PROJECT, glyph: String(fd.get('glyph') || '').trim() };
    if (color !== (was.color || '') && (was.color || fd.get('touched') || fd.get('nocolor'))) args.color = color;
    const env = await callOp('project.style', args);
    if (!env.ok) { boxError('ps-box', env); return; }
    closeModal(true);
    location.reload();
  },
  'phead.touch': (_ev, elm) => { const f = elm.form; if (f && f.touched) f.touched.value = '1'; },
  'phead.build': async (_ev, elm) => {
    elm.disabled = true;
    const env = await callOp('cases.build', {});
    const box = el('ov-mat');
    if (!env.ok) { if (box) box.innerHTML = `<div class="warn err">${humanError(env.error)}</div>`; return; }
    const job = await jobDone((env.data || {}).job_id, (j) => { const b = el('ov-mat-note'); if (b) b.innerHTML = jobChip(j); });
    // Перемальовуємо весь Огляд: застарілий рядок «Стану Майстерні» теж зникає.
    if (job.state === 'done') goto('home');
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
      // Колір — лише коли людина його вибрала, бо поле кольору завжди має
      // значення, і без галочки кожен проєкт мовчки діставав би той самий.
      color: fd.usecolor ? String(fd.color || '') : '',
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
