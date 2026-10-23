/**
 * 🧳 Перенести рід у проєкт — без помічника, кнопкою консолі.
 *
 * Обов'язковий крок переходу на 0.37 для тих, у кого рід лежить у корені
 * простору. Краще його робить помічник: після переносу він розкладає свою
 * пам'ять та інструкції, а консоль цього не вміє. Тому екран починається з
 * поради доручити це помічникові, а кроки відкриваються лише позначкою
 * «переношу сам».
 *
 * 🔴 Консоль сама тримає Майстерню, і переносити теки з-під живого сервера не
 * можна. Тож «Перенести» робить те саме, що «Оновити зараз»: помічник-процес
 * чекає, доки консоль закриється, переносить і відкриває її знову
 * (`project.adopt_restart`). Перешкоди плану видно ДО закриття.
 */

import { t } from '../core/strings.js';
import { callOp, pulse } from '../core/net.js';
import { esc, el, setView, failure, fld, maskot, mini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { confirmAct } from '../core/modal.js';
import { toast, copyText } from '../core/bits.js';
import { SECTIONS } from '../core/nav.js';
import { slugOf } from './project.js';

/** Фраза для помічника — та сама, що в покроковій інструкції порталу. */
const ASK = 'перенеси мій рід у проєкт';

let STATE = null;

SCREENS.adopt = async () => {
  const env = await callOp('project.adopt_state', {});
  if (!env.ok) return failure(env);
  STATE = env.data || {};
  paint();
  return undefined;
};

/** Посилання на інструкцію порталу — завжди назовні, у новій вкладці. */
function guide(label) {
  const url = (STATE && STATE.guide) || '';
  return /^https:\/\//.test(url)
    ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} →</a>` : '';
}

function paint() {
  const d = STATE || {};
  const last = d.last || {};
  // Рід уже в проєкті — підсумок переносу (що далі, як повернути), а не майстер.
  if (!d.legacy && last.state === 'done') {
    setView(result(d));
    return;
  }
  if (!d.legacy) {
    setView(`<div class="card up-hero">${maskot('onovleno', 120, 'up-maskot')}<div class="up-hero-t">
      <h3>${esc(t('adopt.none'))}</h3><p class="muted">${esc(t('adopt.none.why'))}</p></div></div>`);
    return;
  }
  const title = d.surname || '';
  setView(`${helperBanner(d)}
    <div class="card adopt-warn">${maskot('kliuch', 110, 'up-maskot')}<div>
      <h3>${esc(t('adopt.warn.h'))}</h3>
      <p>${esc(t('adopt.warn.why'))}</p>
      <ul><li>${esc(t('adopt.warn.memory'))}</li><li>${esc(t('adopt.warn.blocks'))}</li></ul>
      <p>${esc(t('adopt.warn.ask'))}</p>
      <p class="adopt-ask"><code class="mono">${esc(ASK)}</code>
        <button type="button" data-act="adopt.copy">${esc(t('adopt.copy'))}</button></p>
      <p>${guide(t('adopt.guide'))}</p>
      <label class="chk"><input type="checkbox" id="adopt-self" data-act="adopt.self">
        <span><b>${esc(t('adopt.self'))}</b><small class="muted">${esc(t('adopt.self.why'))}</small></span></label>
    </div></div>
    <div id="adopt-steps" hidden>
      ${d.refusal ? `<div class="warn">${esc(d.refusal)}</div>` : ''}
      <h3 class="rd-step"><span class="rd-n">1</span>${esc(t('adopt.step.name'))}</h3>
      <form id="adopt-form" onsubmit="return false">
        <div class="row">${fld(t('np.title'), `<input name="title" value="${esc(title)}" placeholder="${esc(t('np.title.ph'))}">`)}</div>
        <div class="row">${fld(t('np.name'), `<input name="name" value="${esc(slugOf(title))}" pattern="[a-z0-9][a-z0-9\\-]*" required>`)}</div>
        <p class="muted fld-hint">${esc(t('np.name.hint'))}</p>
        <div class="row">${fld(t('adopt.archive'), `<input name="archive" value="${esc(d.archive || '')}">`)}</div>
        <p class="muted fld-hint">${esc(t('adopt.archive.hint'))}</p>
      </form>
      <h3 class="rd-step"><span class="rd-n">2</span>${esc(t('adopt.step.plan'))}</h3>
      <p class="muted">${esc(t('adopt.plan.why'))}</p>
      <p><button type="button" data-act="adopt.plan">${esc(t('adopt.plan'))}</button></p>
      <div id="adopt-plan"></div>
      <h3 class="rd-step"><span class="rd-n">3</span>${esc(t('adopt.step.go'))}</h3>
      <p class="muted">${esc(t('adopt.go.why'))}</p>
      <p><button type="button" class="primary" data-act="adopt.go" id="adopt-go" disabled>${esc(t('adopt.go'))}</button></p>
    </div>`);
  const form = el('adopt-form');
  if (form && form.addEventListener) {
    let own = false;
    form.addEventListener('input', (ev) => {
      const q = (n) => form.querySelector(`[name="${n}"]`);
      if (ev.target && ev.target.name === 'name') own = true;
      if (ev.target && ev.target.name === 'title' && !own) q('name').value = slugOf(q('title').value);
      // Змінене ім'я чи тека — старий план уже не про них.
      const go = el('adopt-go');
      if (go) go.disabled = true;
    });
  }
}

/**
 * Чим скінчилась попередня спроба, якщо рід досі в корені: перенос повернуто,
 * перенос упав (і повернувся сам) або помічник не дійшов до переносу.
 */
function helperBanner(d) {
  const last = d.last || {};
  const h = d.helper || {};
  const log = h.tail ? `<pre class="mono up-log">${esc(h.tail)}</pre>` : '';
  if (last.state === 'rolled_back') return `<div class="card ok-line">${esc(t('adopt.undone'))}</div>`;
  if (last.state === 'failed') {
    return `<div class="warn"><b>${esc(t('adopt.failed'))}</b><p>${esc(last.failed || '')}</p>
      <p>${esc(t('adopt.failed.what'))}</p>${log}</div>`;
  }
  if (h.finished && !h.ok) return `<div class="warn">${esc(t('adopt.helper.failed'))}${log}</div>`;
  return '';
}

function form() {
  const f = el('adopt-form');
  const v = (n) => String(((f && f.querySelector(`[name="${n}"]`)) || {}).value || '').trim();
  return { name: v('name'), title: v('title'), archive: v('archive') };
}

/** Перешкода плану людською мовою — і що з нею зробити тут же. */
function problem(code, text) {
  const act = {
    dirty: `<button type="button" data-act="adopt.save">${esc(t('adopt.p.dirty.act'))}</button>`,
    cloud: `<button type="button" data-act="nav" data-arg="cloud">${esc(t('adopt.p.cloud.act'))}</button>`,
  }[code] || '';
  const how = t(`adopt.p.${code}`);
  return `<li class="adopt-p"><b>${esc(how === `adopt.p.${code}` ? t('adopt.p.other') : how)}</b>
    <small class="muted">${esc(text)}</small>${act ? ` ${act}` : ''}</li>`;
}

function planBox(p) {
  const mb = (n) => `${(Number(n || 0) / 1048576).toFixed(1)} ${t('up.mb')}`;
  const rows = (p.moves || []).map((m) => `<tr><td class="mono">${esc(m.path)}</td>
      <td class="num">${esc(m.files)}</td><td class="num">${esc(mb(m.size))}</td></tr>`).join('');
  const free = `${(Number(p.archive_free || 0) / 2 ** 30).toFixed(1)} ${t('adopt.gb')}`;
  const probs = (p.problems || []).map((x, i) => problem((p.codes || [])[i] || '', x)).join('');
  return `<div class="card">
      <p>${esc(t('adopt.plan.sum').replace('{f}', p.files || 0).replace('{s}', mb(p.size)))}</p>
      <table class="tbl"><thead><tr><th>${esc(t('adopt.col.path'))}</th><th>${esc(t('adopt.col.files'))}</th>
        <th>${esc(t('adopt.col.size'))}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted">${esc(t('adopt.plan.archive').replace('{a}', p.archive || '').replace('{f}', free))}</p>
    </div>
    ${probs ? `<div class="warn"><p>${esc(t('adopt.plan.blocked'))}</p><ul>${probs}</ul></div>`
    : `<div class="card ok-line">${esc(t('adopt.plan.ok'))}</div>`}`;
}

/** Підсумок переносу: що далі зробити і як повернути все, як було. */
function result(d) {
  const last = d.last || {};
  const name = last.pid || '';
  const inHub = !!SECTIONS.hub_only;
  return `<div class="card up-hero">${maskot('onovleno', 140, 'up-maskot')}<div class="up-hero-t">
      <h3>${esc(t('adopt.done').replace('{p}', last.title || name))}</h3>
      <p class="muted">${esc(t('adopt.done.archive').replace('{a}', (last.archive && last.archive.zip) || ''))}</p></div>
      <div class="up-acts">${inHub ? `<button class="primary" data-act="project.go" data-arg="${esc(name)}">${esc(t('adopt.open'))}</button>` : ''}</div></div>
    <h3 class="sub-h">${esc(t('adopt.after'))}</h3>
    <ol class="adopt-after">
      <li>${esc(t('adopt.after.check'))}</li>
      <li>${esc(t('adopt.after.site'))}</li>
      <li><b>${esc(t('adopt.after.agent'))}</b> <code class="mono">${esc(t('adopt.after.agent.ask'))}</code></li>
      <li>${esc(t('adopt.after.archive'))}</li>
    </ol>
    <p>${guide(t('adopt.guide'))}</p>
    <h3 class="sub-h">${esc(t('adopt.undo.h'))}</h3>
    <p class="muted">${esc(t('adopt.undo.why'))}</p>
    <p><button type="button" class="danger" data-act="adopt.undo" data-arg="${esc(name)}">${esc(t('adopt.undo'))}</button></p>`;
}

/**
 * Поки помічник переносить: консоль закрита, тож питаємо `/api/health`, доки
 * сервер не зникне й не повернеться. Тоді — на екран результату в проєкті.
 */
function moving(target, { every = 2000, give_up_ms = 5 * 60 * 1000 } = {}) {
  const draw = (slow) => setView(`<div class="card up-hero up-going">${maskot('onovliuie', 140, 'up-maskot')}
    <div class="up-hero-t"><h3>${esc(t('adopt.going'))}</h3>
      <p class="muted">${esc(slow ? t('adopt.slow') : t('up.keep'))}</p></div></div>`);
  draw(false);
  const t0 = Date.now();
  let sawDown = false;
  let pid0 = null;
  // Номер процесу консолі до перезапуску: нова консоль — інший номер, навіть
  // якщо сторінка не встигла застати її закритою (повернення — секунди).
  pulse().then((r) => (r && r.ok ? r.json() : null))
    .then((h) => { if (h && pid0 === null) pid0 = h.pid || 0; }).catch(() => { sawDown = true; });
  const tick = async () => {
    try {
      const res = await pulse();
      const h = res && res.ok ? await res.json() : null;
      if (!h) sawDown = true;
      if (h && (sawDown || (pid0 && h.pid && h.pid !== pid0))) {
        const q = new URLSearchParams(location.search);
        if (target) q.set('p', target); else q.delete('p');
        location.href = `${location.pathname}?${q.toString()}#adopt`;
        return;
      }
    } catch { sawDown = true; /* консоль закрита — так і має бути */ }
    if (Date.now() - t0 > give_up_ms) { draw(true); return; }
    setTimeout(tick, every);
  };
  setTimeout(tick, every);
}

Object.assign(ACTIONS, {
  'adopt.copy': async () => {
    const done = await copyText(ASK);
    toast(done === false ? t('common.error') : t('adopt.copied'), { tone: done === false ? 'err' : 'ok' });
  },
  'adopt.self': (_ev, elm) => {
    const box = el('adopt-steps');
    if (box) box.hidden = !elm.checked;
  },
  'adopt.plan': async () => {
    const f = form();
    const box = el('adopt-plan');
    const go = el('adopt-go');
    if (!f.name) { toast(t('adopt.need.name'), { tone: 'err' }); return; }
    const env = await callOp('project.adopt', { name: f.name, archive: f.archive });
    if (!env.ok) {
      if (box) box.innerHTML = `<div class="warn">${esc(env.error || t('common.error'))}</div>`;
      if (go) go.disabled = true;
      toast(env.error || t('common.error'), { tone: 'err' });
      return;
    }
    const p = env.data || {};
    if (box) box.innerHTML = planBox(p);
    if (go) go.disabled = !!(p.problems || []).length || !!(STATE && STATE.refusal);
    toast((p.problems || []).length ? t('adopt.plan.blocked') : t('adopt.plan.ok'),
      { tone: (p.problems || []).length ? 'warn' : 'ok' });
  },
  /** Незбережені правки — зберегти історією й одразу перевірити план знову. */
  'adopt.save': async () => {
    const env = await callOp('history.save', { message: 'Перед переносом роду в проєкт' });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    toast(t('adopt.saved'), { tone: 'ok' });
    await ACTIONS['adopt.plan']();
  },
  'adopt.go': async () => {
    const f = form();
    const yes = await confirmAct({ title: t('adopt.confirm'), text: t('adopt.confirm.why'),
      rows: [[t('np.title'), f.title || f.name], [t('np.name'), f.name], [t('adopt.archive'), f.archive]],
      okLabel: t('adopt.go') });
    if (!yes) return;
    const env = await callOp('project.adopt_restart', { name: f.name, title: f.title, archive: f.archive });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    moving(f.name);
  },
  'adopt.undo': async (_ev, elm) => {
    const name = elm.dataset.arg;
    const yes = await confirmAct({ title: t('adopt.undo'), text: t('adopt.undo.confirm'),
      okLabel: t('adopt.undo'), danger: true });
    if (!yes) return;
    const env = await callOp('project.adopt_restart', { name, rollback: true });
    if (!env.ok) { toast(env.error || t('common.error'), { tone: 'err' }); return; }
    moving('');
  },
});

/**
 * Плашка на Огляді старого кореня: перенос — обов'язковий крок 0.37.
 * Малюється в `#adopt-banner`, щойно відомо, що рід лежить у корені.
 */
export async function adoptBanner() {
  const box = el('adopt-banner');
  if (!box) return;
  const env = await callOp('project.adopt_state', {});
  if (!env.ok || !(env.data || {}).legacy) return;
  STATE = env.data;
  box.innerHTML = `<div class="card adopt-banner">${mini('derevo', 56)}<div>
      <b>${esc(t('adopt.banner'))}</b><small class="muted">${esc(t('adopt.banner.why'))}</small></div>
      <div class="up-acts"><button type="button" class="primary" data-act="nav" data-arg="adopt">${esc(t('adopt.banner.go'))}</button>
      ${guide(t('adopt.guide'))}</div></div>`;
}
