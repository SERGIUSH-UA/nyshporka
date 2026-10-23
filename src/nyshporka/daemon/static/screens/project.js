/** 📁 Проєкти Майстерні: новий проєкт (вікно), перехід у проєкт, картки на Огляді. */

import { ic } from '/ui/icons.js';
import { t, srv } from '../core/strings.js';
import { PROJECT, callOp } from '../core/net.js';
import { esc, el, setView, boxError, busyForm, fld, humanError, mini, emptyMini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto, jobDone, jobChip, currentScreen, SECTIONS, screenOn } from '../core/nav.js';
import { openModal, closeModal } from '../core/modal.js';
import { decRow, noEmoji, fmtDay } from '../core/bits.js';
import { projectBadge as badge, projectColor, projectsNow, currentPid, iconPicker, iconSrc, scenePicker, sceneSrc,
  sceneThumb } from '../core/projects.js';

/**
 * Перейти в проєкт: нова адреса вкладки (`?p=`), а не стан сторінки — інакше
 * вже завантажені екрани лишились би з даними попереднього проєкту.
 * `back` — екран, на який людина йшла, коли її спитали «який проєкт».
 */
export function openProject(id, back = '', extra = {}) {
  if (id === PROJECT && !back) return;
  const q = new URLSearchParams(location.search);
  if (id) q.set('p', id); else q.delete('p');
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  location.href = `${location.pathname}?${q.toString()}${back ? `#${back}` : ''}`;
}

/**
 * Екран, на якому лишитись після зміни контексту: «Бібліотека» в роді X →
 * «Бібліотека» в роді Y. Екран роду при переході в саму Майстерню веде на її
 * Огляд — роду там немає, а вибір проєкту замість Майстерні був би не тим,
 * чого людина просила.
 */
function keepScreen(toHub) {
  const here = currentScreen();
  if (!here) return '';
  if (toHub && (SECTIONS.project_screens || []).includes(here)) return 'home';
  return here;
}

SCREENS.newproject = async () => {
  // 🧭 Три кроки: що це → назва й прізвище → вигляд. Вид — картками з
  // мініатюрою, а не випадним списком внизу; тека виводиться з назви латинкою
  // сама (поправити — під «Тека проєкту»); знак видно одразу, яким він буде.
  // 🔴 Прізвище — у тій самій формі: без профілю пошук роду в новому проєкті
  // не знає, що шукати, і перший же «Шукати» відповідав би порожнечею.
  const kind = (v, pic, on) => `<label class="np-kind card">
      <input type="radio" name="kind" value="${v}"${on ? ' checked' : ''}>
      ${mini(pic, 56)}<span><b>${t(`np.kind.${v}`)}</b><small>${t(`np.kind.${v}.why`)}</small></span></label>`;
  const step = (n, key) => `<h3 class="rd-step"><span class="rd-n">${n}</span>${esc(t(key))}</h3>`;
  setView(`<div id="np-adopt"></div><p class="muted">${t('np.why')}</p>
    <form data-act="project.create" id="np-form">
      ${step(1, 'np.step.kind')}
      <div class="np-kinds">${kind('family', 'derevo', true)}${kind('order', 'pechatka', false)}</div>
      ${step(2, 'np.step.name')}
      <div class="row">${fld(t('np.title'), `<input name="title" placeholder="${t('np.title.ph')}" autofocus>`)}</div>
      <div class="row">${fld(t('np.surname'), `<input name="surname" placeholder="${t('np.surname.ph')}">`)}</div>
      <div class="row">${fld(t('np.variants'), `<input name="variants" placeholder="${t('np.variants.ph')}">`)}</div>
      <p class="muted fld-hint">${t('np.variants.hint')}</p>
      <details class="np-folder"><summary>${t('np.folder')}: <b class="mono" id="np-slug">—</b></summary>
        <div class="row">${fld(t('np.name'), `<input name="name" placeholder="bondar" pattern="[a-z0-9][a-z0-9\\-]*" required>`)}</div>
        <p class="muted fld-hint">${t('np.name.hint')}</p></details>
      ${step(3, 'np.step.look')}
      <div class="row np-look"><span class="pj-badge" id="np-prev">?</span>
        <label class="chk"><input type="checkbox" name="usecolor" value="1"> ${t('np.usecolor')}</label>
        ${fld(t('np.color'), `<input name="color" type="color" value="#4f6bd8">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3">`)}</div>
      ${iconPicker('')}
      <p class="muted fld-hint">${t('np.icon.hint')}</p>
      <div class="row dlg-acts"><button type="submit" class="primary">${t('np.create')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="np-box"></div>
    </form>`);
  npLive();
  npAdopt();
};

/**
 * Рід ще лежить у корені простору — спершу перенести його в проєкт (0.37),
 * а вже тоді заводити другий: інакше перший лишиться змішаним із Майстернею.
 */
async function npAdopt() {
  const env = await callOp('project.adopt_state', {});
  const box = el('np-adopt');
  if (!box || !env.ok || !(env.data || {}).legacy) return;
  box.innerHTML = `<div class="warn"><b>${esc(t('adopt.np'))}</b> ${esc(t('adopt.np.why'))}
    <p><button type="button" data-act="nav" data-arg="adopt">${esc(t('adopt.banner.go'))}</button></p></div>`;
}

/** Латинська тека з назви: «Рід Бондарів» → `rid-bondariv`. */
const LAT = { а: 'a', б: 'b', в: 'v', г: 'h', ґ: 'g', д: 'd', е: 'e', є: 'ie', ж: 'zh', з: 'z', и: 'y', і: 'i',
  ї: 'i', й: 'i', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f',
  х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch', ь: '', ю: 'iu', я: 'ia', ы: 'y', э: 'e', ъ: '', ё: 'io' };
export function slugOf(title) {
  return String(title || '').toLowerCase().split('').map((c) => (c in LAT ? LAT[c] : c)).join('')
    .replace(/[’'ʼ`]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
}

/** Тека й прев'ю знака стежать за полями, доки людина не взялась за теку сама. */
function npLive() {
  const form = el('np-form');
  if (!form || !form.querySelector || !form.addEventListener) return;
  const q = (n) => form.querySelector(`[name="${n}"]`);
  let own = false;
  const paint = () => {
    const name = q('name');
    const title = String((q('title') || {}).value || '');
    if (name && !own) name.value = slugOf(title);
    const slug = el('np-slug');
    if (slug) slug.textContent = (name && name.value) || '—';
    const prev = el('np-prev');
    if (prev) {
      const glyph = String((q('glyph') || {}).value || '').trim();
      const word = title.replace(/^(рід|род)\s+/i, '').trim();
      const use = q('usecolor');
      const color = use && use.checked ? String((q('color') || {}).value || '') : '';
      const icon = String((form.querySelector('[name="icon"]:checked') || {}).value || '');
      // Значок — замість літери, колір — його обідком; так само, як у перемикачі.
      if (icon) prev.innerHTML = `<img src="${iconSrc(icon)}" alt="">`;
      else prev.textContent = glyph || (word ? word[0].toUpperCase() : '?');
      prev.className = icon ? `pj-badge pj-ico${color ? ' pj-ring' : ''}` : 'pj-badge';
      if (prev.style) {
        prev.style.background = icon ? '' : color;
        if (prev.style.setProperty) prev.style.setProperty('--pj', color);
      }
    }
  };
  form.addEventListener('input', (ev) => {
    if (ev.target && ev.target.name === 'name') own = true;
    paint();
  });
  form.addEventListener('change', paint);
  paint();
}

/**
 * Картки проєктів для Огляду Майстерні.
 *
 * 🔴 Замість відмови «Оберіть проєкт»: у Майстерні без проєкту людина бачить, які
 * роди тут ведуться, і заходить у потрібний одним кліком. Картка — окремий,
 * виразний предмет (тло, тінь, смуга кольору проєкту): до 7в вона зливалась із
 * дашбордом під нею, і проєкти не читались як вхід.
 */
export async function projectCards({ limit = 0, all = false } = {}) {
  const env = await callOp('project.list', {});
  if (!env.ok) return '';
  const every = (env.data || {}).projects || [];
  const live = every.filter((p) => !p.archived);
  const shown = limit ? live.slice(0, limit) : live;
  const card = (p) => {
    const h = p.hypotheses || {};
    const open = (h.open || 0) + (h.awaiting || 0);
    const color = projectColor(p) ? ` style="--pj:${esc(p.color)}"` : '';
    return `<button class="pj-card" data-act="project.go" data-arg="${esc(p.id)}"${color}>
      <img class="pj-scene" src="${sceneThumb(p.scene)}" alt="" loading="lazy">
      <span class="pj-top">${badge(p)}<span><b>${esc(p.name || p.id)}</b>
        <small>${esc(t(`np.kind.${p.kind === 'order' ? 'order' : 'family'}`))}</small></span></span>
      <span class="pj-stats">
        <span><b class="num">${esc(p.persons ?? 0)}</b> ${esc(t('pj.persons'))}</span>
        <span${open ? ' class="pj-warn"' : ''}><b class="num">${esc(open)}</b> ${esc(t('pj.open'))}</span>
      </span>
      <span class="pj-go">${t('project.open')} →</span>
    </button>`;
  };
  const cards = shown.map(card).join('');
  // На Огляді — кілька проєктів і «Усі проєкти»; на екрані «Проєкти» — усі й архівні.
  const more = limit && live.length > limit
    ? `<p><button class="ghost" data-act="nav" data-arg="projects">${t('home.allprojects')} (${live.length}) →</button></p>` : '';
  const archived = all ? every.filter((p) => p.archived) : [];
  const arch = archived.length ? `<details class="pj-arch"><summary>${t('projects.archived')} (${archived.length})</summary>
    <div class="pj-cards">${archived.map(card).join('')}</div></details>` : '';
  return `<section class="hub-projects">${all ? '' : `<h2>${t('home.continue')}</h2>`}
    <div class="pj-cards">${cards}
      <button class="pj-card pj-new" data-act="nav" data-arg="newproject">
        <span class="pj-top"><span class="pj-badge">+</span><b>${t('stage.act.newproject')}</b></span>
        <small class="muted">${t('np.why')}</small></button>
    </div>${more}${arch}</section>`;
}

/** Проєкт, на верх якого дивимось: стиль змінюється саме йому. */
let HEAD = null;

/**
 * Мальовані речі карток Огляду (ілюстрації дослідника, 23.10.2026). Шляхи
 * повністю, без шаблону: тест пакета звіряє кожну названу картинку з файлом.
 */
const ART = {
  canon: '/ui/img/art-konverty.webp', hyp: '/ui/img/art-kompas.webp',
  mat: '/ui/img/art-shukhliada.webp', hist: '/ui/img/art-suvii.webp',
  decide: '/ui/img/art-selo.webp', news: '/ui/img/art-pero.webp',
};

/**
 * Картка-показник Огляду проєкту: значок у кружку, назва, число, мальована річ
 * у куті й стрілка переходу. Річ — оздоба під текстом: на вузькій картці вона
 * меншає, а текст лишається читабельним.
 */
function kpi(id, label, nav, icon, art) {
  return `<button class="ov-kpi" id="${id}" data-act="nav" data-arg="${nav}">
    <span class="ov-ic">${ic(icon, 'ic-plain')}</span>
    <span class="ov-kpi-t"><span class="ov-kpi-l">${esc(label)}</span>
      <span class="ov-kpi-v"><span class="muted ov-wait">${t('load.count')}</span></span>
      <span class="ov-kpi-s"></span></span>
    <img class="ov-art" src="${art}" alt="" loading="lazy" decoding="async">
    <span class="ov-go" aria-hidden="true"></span></button>`;
}

/** Розділ Огляду з шапкою-стрічкою: значок, назва, гравюра праворуч. */
function ovSection(icon, title, art, body) {
  return `<div class="dash-box ov-sec"><div class="ov-sec-h"><span class="ov-ic">${ic(icon, 'ic-plain')}</span>
      <h3>${esc(title)}</h3><img class="ov-sec-art" src="${art}" alt="" loading="lazy" decoding="async"></div>
    <div class="ov-sec-b">${body}</div></div>`;
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
    <div class="ov-hero ov-hero-rid"><div class="ov-title"><span id="ov-badge"></span>
      <span class="muted" id="ov-sub"></span>
      <button class="ghost ctl-sm ov-style" data-act="phead.style">${t('phead.style')}</button></div></div>
    <div class="ov-kpis">
      ${kpi('ov-k-canon', t('nav.canon'), 'canon', 'page', ART.canon)}
      ${kpi('ov-k-hyp', t('nav.hyp'), 'hyp', 'scale', ART.hyp)}
      ${kpi('ov-k-mat', t('phead.material'), 'search', 'drawers', ART.mat)}
      ${kpi('ov-k-hist', t('nav.history'), 'history', 'clock', ART.hist)}
    </div>
    <div class="dash-sec steps" id="ov-plan" hidden></div>
    <div class="ov-cols">
      ${ovSection('book-open', t('canon.next'), ART.decide, '<div id="ov-decide"><span class="skel-cell"></span></div>')}
      ${ovSection('ledger', t('ov.new'), ART.news, '<div id="ov-new"><span class="skel-cell"></span></div>')}
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
      // Картина Огляду — своя в кожного роду; без вибору лишається село.
      const hero = document.querySelector && document.querySelector('.ov-hero-rid');
      if (hero && hero.style && hero.style.setProperty && d.scene) hero.style.setProperty('--hero', `url("${sceneSrc(d.scene)}")`);
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
      box.innerHTML = (d.next || []).length ? (d.next || []).map((x) => decRow(x, d.refs || {})).join('')
        + (more > 0 ? `<p><button class="ghost ctl-sm" data-act="nav" data-arg="hyp">${
          esc(t('ov.more').replace('{n}', more))}</button></p>` : '')
        : emptyMini('pero', t('canon.next.none'));
    }),
    fillMaterial(stillHere),
    fillPlan(stillHere),
    Promise.all([callOp('history.log', { limit: 4 }), callOp('reports.list', {})]).then(([hl, rl]) => {
      const box = el('ov-new');
      if (!stillHere() || !box) return;
      const rows = (hl.ok && (hl.data || {}).rows) || [];
      const last = rows[0];
      setKpi('ov-k-hist', last ? `<b>${esc(fmtDay(last.date))}</b>` : '—',
        esc(last ? `${t('ov.hist.last')}: ${srv(last.subject)}` : (hl.ok ? t('hist.empty') : t('ov.hist.none'))));
      const reps = ((rl.ok && (rl.data || {}).rows) || []).slice(0, 3);
      const items = [
        ...rows.map((r) => `<div class="ov-feed"><span class="muted">${esc(fmtDay(r.date))}</span><span>${
          esc(srv(r.subject))}</span></div>`),
        ...reps.map((r) => `<button class="ov-feed ov-link" data-act="rs.read" data-arg="${esc(r.path)}">
          <span class="muted">${ic('note', 'ic-o ic-sm')}</span><span>${esc(noEmoji(r.title))}</span></button>`)];
      box.innerHTML = items.length ? items.join('') : emptyMini('hodynnyk', t('ov.new.none'));
    }),
  ];
  await Promise.all(jobs);
}

/**
 * 🧭 План нового роду: рід → справи → читання → пошук.
 *
 * Новий проєкт доти відкривався чотирма нулями й порожнім «що вирішити», і
 * людина не знала, з чого почати (дослідник, 23.10.2026). План стоїть, доки
 * хоч один крок не зроблено, і зникає, коли зроблено всі. Перший незроблений —
 * головною кнопкою: решта не забороняється, але порядок видно.
 * Рід, у каноні якого вже є особи, план не бачить: це давній проєкт, і «з чого
 * почати» над сотнями карток — шум.
 */
async function fillPlan(stillHere = () => true) {
  const [st, pr, any, read, here] = await Promise.all([
    callOp('project.status', {}),
    callOp('profile.show', {}),
    callOp('cases.list', { limit: 1 }),
    callOp('cases.list', { htr: 'read', limit: 1 }),
    callOp('cases.list', { searched: 'here', limit: 1 })]);
  const box = el('ov-plan');
  if (!stillHere() || !box) return;
  if (st.ok && Number((st.data || {}).persons || 0) > 0) { box.hidden = true; return; }
  const total = (e) => (e.ok ? Number((e.data || {}).total || 0) : 0);
  const p = pr.ok ? (pr.data || {}) : {};
  const all = [
    { k: 'ov.plan.family', ok: !!p.present && !!(p.places || []).length, nav: 'profile' },
    { k: 'ov.plan.cases', ok: total(any) > 0, nav: 'newcase' },
    { k: 'ov.plan.read', ok: total(read) > 0, nav: 'read' },
    { k: 'ov.plan.search', ok: total(here) > 0, nav: 'search' },
  ].filter((x) => screenOn(x.nav));
  if (!all.length || all.every((x) => x.ok)) { box.hidden = true; return; }
  const first = all.find((x) => !x.ok);
  box.hidden = false;
  box.innerHTML = `<h3>${ic('check-circle', 'ic-sm')} ${esc(t('ov.plan'))}
      <span class="aside">${all.filter((x) => x.ok).length} ${esc(t('dash.of'))} ${all.length}</span></h3>
    <div class="dash-box">${all.map((x, i) => `<div class="step${x.ok ? ' on' : ''}">
      <span class="step-m">${x.ok ? ic('check-circle', 'ic-o ic-sm') : `<b class="num">${i + 1}</b>`}</span>
      <span class="step-t">${esc(t(x.k))}<br><span class="muted">${esc(t(`${x.k}.why`))}</span></span>
      <span class="step-n"></span>
      <span>${x.ok ? '' : `<button${x === first ? ' class="primary"' : ''} data-act="nav" data-arg="${x.nav}">${
        esc(t('step.go'))}</button>`}</span></div>`).join('')}</div>`;
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
      ${fld(t('np.title'), `<input name="title" required value="${esc(d.name || '')}"
        placeholder="${esc(t('np.title.ph'))}">`)}
      <div class="row">${fld(t('np.color'), `<input name="color" type="color" data-act="phead.touch"
        value="${esc(/^#[0-9a-fA-F]{6}$/.test(d.color || '') ? d.color : '#4f6bd8')}">`)}
        ${fld(t('np.glyph'), `<input name="glyph" maxlength="2" size="3" value="${esc(d.glyph || '')}">`)}</div>
      ${d.color ? `<label class="chk"><input type="checkbox" name="nocolor" value="1"> ${t('ov.nocolor')}</label>` : ''}
      ${iconPicker(d.icon || '')}
      <p class="muted fld-hint">${t('np.icon.hint')}</p>
      ${scenePicker(d.scene || '')}
      <p class="muted fld-hint">${t('np.scene.hint')}</p>
      <div class="row dlg-acts"><button type="submit" class="primary">${t('sp.save')}</button>
        <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
      <div id="ps-box"></div></form>` });
}

Object.assign(ACTIONS, {
  'phead.style': () => styleForm(),
  'phead.save': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const was = HEAD || {};
    // Колір іде лише тоді, коли його змінили або зняли: міняючи знак, людина
    // не мала б мовчки дістати колір, що стояв у полі за замовчуванням.
    const color = fd.get('nocolor') ? '' : String(fd.get('color') || '');
    const args = { name: was.project || PROJECT, glyph: String(fd.get('glyph') || '').trim(),
      title: String(fd.get('title') || '').trim(), icon: String(fd.get('icon') || ''),
      scene: String(fd.get('scene') || '') };
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
    if (!env.ok) {
      elm.disabled = false;     // відмова — кнопка знову натискається, а не мертва
      if (box) box.innerHTML = `<div class="warn err">${humanError(env.error)}</div>`;
      return;
    }
    const job = await jobDone((env.data || {}).job_id, (j) => { const b = el('ov-mat-note'); if (b) b.innerHTML = jobChip(j); });
    // Перемальовуємо весь Огляд: застарілий рядок «Стану Майстерні» теж зникає.
    if (job.state === 'done') goto('home');
    else elm.disabled = false;
  },
  'project.go': (_ev, elm) => {
    const id = elm.dataset.arg;
    const hub = (projectsNow() || {}).hub_id || '_hub';
    // Той самий контекст — нікуди не йдемо: перезавантаження стерло б набране.
    if ((id === hub && !currentPid()) || (id && id === currentPid())) return undefined;
    return openProject(id, elm.dataset.back || keepScreen(id === hub));
  },
  // Картка іншого проєкту (з позначки «уже в каноні» в Пошуку).
  'project.card': (_ev, elm) => openProject(elm.dataset.arg, 'canon',
    { card: elm.dataset.card || '' }),

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
      icon: String(fd.icon || ''),
      kind: fd.kind === 'order' ? 'order' : 'family',
    });
    done();
    if (!env.ok) { boxError('np-box', env); return; }
    openProject(String(fd.name || '').trim());
  },
});

// Вузол форми потрібен лише щоб тест міг перевірити, що вікно намалювалось.
export const npForm = () => el('np-form');
