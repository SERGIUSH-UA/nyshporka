/** 📂 Мої справи й заведення нової. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm, fld,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav, goto,
  refreshJobs, onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';
import { pathField } from '../core/paths.js';




/**
 * Опис, підвантажений у форму «Завести справу» для правки.
 *
 * 🔴 Порожня форма над уже описаною текою — пастка: людина бачить порожні
 * поля, вважає, що опису немає, і друкує його заново — часто інакше, ніж
 * попереднього разу. Тому правка починається з показу записаного.
 */
let EDIT = null;

/**
 * 📥 Нові теки — матеріал на диску, якого Нишпорка ще не знає як справу.
 *
 * 🔴 Екран звався «Приймальня», і навіщо він, не розумів навіть дослідник,
 * що працює із застосунком від початку (07.10.2026). У даних було три
 * причини: поруч із неописаними теками стояли збірки — уже описані групування
 * з прогонами, з якими тут нема чого робити (звідси «дві однакові» теки й
 * рядок «— —»); випуски однієї газети йшли сотнею рядків; а книгу чи корпус,
 * яким шифри не буде ніколи, не було як прибрати.
 *
 * Тепер тут рівно одне питання — «що на диску ще не стало справою» — і три
 * відповіді на нього: «Аркуші» (подивитись), «Описати» (дати шифру, і тека
 * стає справою в бібліотеці), «Не справа» (книга, газета, опис фонду —
 * відкласти, щоб не заважало; повертається одним натисканням).
 *
 * Групи — за першою текою під коренем справ, тобто за тим, звідки матеріал:
 * «bov» — це 67 випусків однієї газети, а не 67 різних питань.
 */
SCREENS.cases = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('intake.list', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data;
  const c = d.counts || {};
  const waiting = d.waiting || [];
  setView(`
    <h2>${t('nav.cases')}</h2>
    <p class="muted">${t('intake.why')}</p>
    <div class="row">
      <button type="button" data-act="intake.other">${ic('pencil-line', 'ic-sm')} ${t('intake.other')}</button>
      <button type="button" class="ctl-sm" data-act="cases.build"
        title="${t('cases.build.why')}">${ic('refresh', 'ic-sm')} ${t('cases.build')}</button>
    </div>
    ${renderWarnings(env)}
    ${intakeCount(d, c)}
    ${waiting.length
    ? `<div class="intake">${waiting.map((g, i) => intakeGroup(g, `w${i}`)).join('')}</div>`
    : `<p><b>${t('intake.empty')}</b></p>`}
    ${asideBlock(d.aside || [])}`);
};

/** Знаменник обома боками: стільки чекає опису, стільки вже справ. */
function intakeCount(d, c) {
  if (!d.registry) return '';
  const bits = [`<b>${esc(c.waiting || 0)}</b> ${t('intake.undescribed')}`];
  if (c.waiting_frames) bits.push(`${esc(c.waiting_frames)} ${t('common.frames')}`);
  const lib = Number(c.described || 0)
    ? ` · <button data-act="nav" data-arg="library">${esc(c.described)}
        ${t('intake.described')} →</button>` : '';
  return `<p class="muted">${bits.join(' · ')}${lib}</p>`;
}

/**
 * Група: рядок «звідки» з числами й діями, під ним — теки (згорнуто, якщо
 * їх більше однієї). Група з однієї теки — це сама тека.
 */
function intakeGroup(g, id) {
  const folders = g.folders || [];
  const one = folders.length === 1 ? folders[0] : null;
  const title = (one && one.title) || (folders.find((f) => f.title) || {}).title || '';
  const head = `<div class="intake-h">
    <span class="intake-n"><b>${esc(g.label || g.parent)}</b>
      ${title ? `<span class="muted"> — ${esc(title)}</span>` : ''}
      ${one && one.note ? `<span class="tag">${esc(one.note)}</span>` : ''}</span>
    <span class="muted mono">${one ? '' : `${esc(folders.length)} ${t('intake.subdirs')} · `}${
  esc(g.frames)} ${t('common.frames')}</span>
    <span class="acts" id="ia-${id}">
      ${one ? folderActs(one) : `<button class="ctl-sm" data-act="intake.toggle" data-arg="${id}">${
        t('intake.show')}</button>`}
      ${g.aside_key ? `<button class="ctl-sm" data-act="intake.aside.ask" data-arg="${id}"
        data-path="${esc(g.aside_key)}" title="${esc(t('intake.aside.why'))}">${t('intake.aside')}</button>` : ''}
    </span>
  </div>`;
  if (one) return `<div class="intake-g">${head}</div>`;
  return `<div class="intake-g">${head}
    <table id="ig-${id}" hidden><tbody>${folders.map((f) => `<tr>
      <td class="mono">${esc(f.path.slice((g.parent || '').length + 1) || f.name)}</td>
      <td>${esc(f.title || '')}${f.note ? ` <span class="tag">${esc(f.note)}</span>` : ''}</td>
      <td class="num">${esc(f.frames)}</td>
      <td class="acts">${folderActs(f)}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

/** Дві дії над текою — підписані, а не самими значками. */
function folderActs(f) {
  return `<button class="ctl-sm" data-act="intake.frames" data-arg="${esc(f.path)}">${
    ic('image', 'ic-o ic-sm')} ${t('intake.frames')}</button>
    <button class="ctl-sm" data-act="case.edit" data-arg="${esc(f.path)}"
      title="${esc(t('intake.describe.why'))}">${ic('pencil-line', 'ic-o ic-sm')} ${t('intake.describe')}</button>`;
}

/** Відкладене — згорнуто, з причиною й «Повернути». */
function asideBlock(groups) {
  if (!groups.length) return '';
  const n = groups.reduce((s, g) => s + (g.folders || []).length, 0);
  return `<details class="intake-aside"><summary>${t('intake.aside.title')} (${esc(n)})</summary>
    <table><tbody>${groups.map((g) => `<tr>
      <td><b>${esc(g.label || g.parent)}</b>${g.why ? ` <span class="muted">— ${esc(g.why)}</span>` : ''}</td>
      <td class="num">${esc((g.folders || []).length)} ${t('intake.subdirs')}</td>
      <td class="acts"><button class="ctl-sm" data-act="intake.unaside"
        data-path="${esc(g.aside_key || g.parent)}">${t('intake.unaside')}</button></td>
    </tr>`).join('')}</tbody></table></details>`;
}

/** Що це за матеріал — варіанти причини «не справа». */
const ASIDE_WHY = ['book', 'press', 'opys', 'train', 'other'];

/**
 * Перелік архівів, які застосунок знає. Тримається між показами екрана: він
 * міняється лише тоді, коли людина сама додала архів, і перепитувати його на
 * кожен показ означало б платити запитом за незмінне.
 */
let REPOS = null;

/** Селект архівів. Порожній вибір — «архів у самій шифрі», і він за замовчуванням. */
function repoOptions(picked) {
  const rows = (REPOS && REPOS.archives) || [];
  const opt = (val, label) =>
    `<option value="${esc(val)}"${val === (picked || '') ? ' selected' : ''}>${esc(label)}</option>`;
  return [opt('', t('case.repo.any')),
          ...rows.map((r) => opt(r.code, r.name ? `${r.label} — ${r.name}` : r.label))].join('');
}

let CHECK_TIMER = null;

/**
 * Слухати форму: шифра, архів і тека перевіряються, поки їх набирають.
 *
 * ⚠ З затримкою: запит на кожну літеру — це десяток відповідей, що приходять
 * не по черзі, і остання показана могла б бути не від останнього набраного.
 */
function watchForm() {
  const form = el('case-form');
  if (!form || !form.addEventListener) return;
  const later = () => {
    clearTimeout(CHECK_TIMER);
    CHECK_TIMER = setTimeout(checkForm, 350);
  };
  form.addEventListener('input', later);
  form.addEventListener('change', later);
  checkForm();
}

/**
 * 🔎 Як прочиталась шифра і чи тека в просторі — до «Зберегти».
 *
 * 🔴 Шифра показується РОЗІБРАНОЮ: архів повною назвою, фонд, опис, справа.
 * Набране «ANRM 2-1-1741» і «2-1-1741» з архівом у селекті виглядали однаково
 * правильно, і чи впізнано архів, людина дізнавалась із відмови після
 * збереження.
 */
async function checkForm() {
  const form = el('case-form');
  if (!form || !form.querySelector) return;
  const val = (name) => {
    const x = form.querySelector(`[name="${name}"]`);
    return x ? String(x.value || '') : '';
  };
  const seq = ++SEQ.casecheck;
  const env = await callOp('case.check',
    { case_dir: val('case_dir'), shifra: val('shifra'), repo: val('repo') });
  if (seq !== SEQ.casecheck || !env.ok) return;
  const d = env.data || {};
  const read = el('shifra-read');
  if (read) {
    const s = d.shifra;
    read.innerHTML = s
      ? `✓ <b>${esc(s.label)}</b>${s.name ? ` — ${esc(s.name)}` : ''} · ${t('case.fond')} <b>${
        esc(s.fond)}</b> · ${t('case.opys')} <b>${esc(s.opys)}</b> · ${t('case.spr')} <b>${esc(s.spr)}</b>`
      : (d.shifra_error ? `<span class="warn-inline">${esc(d.shifra_error)}</span>` : '');
  }
  // Позначка «показувати там, де лежить» — лише для теки поза простором.
  const box = el('adopt-box');
  if (box) box.hidden = !(d.dir && d.dir.outside);
}

SCREENS.newcase = async () => {
  const sc = (EDIT && EDIT.sidecar) || {};
  const v = (k) => esc(sc[k] === null || sc[k] === undefined ? '' : sc[k]);
  const dir = EDIT ? esc(EDIT.case_dir) : '';
  // 🔴 Валідатор шифри вимагає назву архіву зі свого переліку, а показати цей
  // перелік не було де: людина читала «архів невідомий» і не мала як довідатись,
  // що взагалі приймається, ані чим це поповнити (звіт 29.08.2026).
  const gen = curGen();
  if (REPOS === null) {
    const env = await callOp('archives.list', {});
    // ⚠ Екран малюється лише якщо людина ще тут: `show()` піднімає покоління на
    // кожній навігації, а до цієї правки форма була синхронною й такої ями не
    // мала. Без перевірки заведення справи намалювалось би поверх екрана, який
    // людина відкрила замість нього.
    if (!alive(gen)) return;
    // ⚠ Невдачу НЕ запам'ятовуємо: `null` означає «не питали». Порожній перелік
    // у цій змінній пришив би одну випадкову відмову (секція щойно вимкнена,
    // демон перезапустився) до всієї сесії — і селект назавжди лишився б із
    // самим «з шифри», тобто рівно тим станом, проти якого він і зроблений.
    if (env.ok) REPOS = env.data;
  }
  // 🔴 Кожне поле — з підписом над ним. Доти підписом була сама підказка в
  // полі, і вона зникала, щойно поле заповнене: у формі, відкритій на правку,
  // стояли «ANRM 2-1-1741», «газета», «1854», «1854» — і котре з двох «1854»
  // «від», а котре «до», не казало ніщо (холодний прохід 07.10.2026).
  setView(`
    <h2>${t('case.title')}</h2>
    ${EDIT ? `<div class="warn">${t('case.editing')} <b class="mono">${dir}</b>
       · ${esc(EDIT.scans)} ${t('common.frames')}<br>
       <span class="muted">${t('case.keep')}</span></div>`
    : `<p class="muted">${t('case.why')}</p>`}
    <form data-act="case.save" id="case-form">
      <div class="row">${fld(t('case.dir'), pathField({ name: 'case_dir', mode: 'dir',
        purpose: 'case.dir', value: EDIT ? EDIT.case_dir : '',
        ph: t('case.dir.ph'), autofocus: !EDIT }))}</div>
      ${EDIT ? '' : `<p class="muted fld-hint">${t('case.dirhint')}</p>`}
      <div class="row">
        ${fld(t('case.shifra'), `<input name="shifra" placeholder="ДАХмО 315-1-8433"
          value="${v('shifra')}">`)}
        ${fld(t('case.repo'), `<select name="repo">${repoOptions(sc.repo)}</select>`)}
        <button type="button" class="fld-btn" data-act="case.repo.toggle">${t('case.repo.add')}</button>
      </div>
      <p id="shifra-read" class="muted fld-hint"></p>
      <div id="repo-add" hidden>
        <p class="muted">${t('case.repo.add.why')}</p>
        <div class="row">
          <input id="repo-code" placeholder="${t('case.repo.code')}" size="8">
          <input id="repo-label" placeholder="${t('case.repo.label')}" size="10">
          <input id="repo-name" placeholder="${t('case.repo.name')}">
          <button type="button" data-act="case.repo.add">${t('case.repo.save')}</button>
        </div>
        <div id="repo-hits"></div>
      </div>
      <div class="row">${fld(t('case.name'), `<input name="title"
        placeholder="${t('case.name.ph')}" value="${v('title')}" ${EDIT ? 'autofocus' : ''}>`)}</div>
      <div class="row">
        ${fld(t('case.type'), `<input name="doc_type" placeholder="${t('case.type.ph')}"
          value="${v('doc_type')}">`)}
        ${fld(t('case.place'), `<input name="place" placeholder="${t('case.place.ph')}"
          value="${v('place')}">`)}
      </div>
      <div class="row">
        ${fld(t('case.year_from'), `<input name="year_from" placeholder="1858" inputmode="numeric"
          value="${v('year_from')}">`, 'narrow')}
        ${fld(t('case.year_to'), `<input name="year_to" placeholder="1860" inputmode="numeric"
          value="${v('year_to')}">`, 'narrow')}
      </div>
      <div class="row">${fld(t('case.note'), `<input name="note"
        placeholder="${t('case.note.ph')}" value="${v('note')}">`)}</div>
      <div id="adopt-box" hidden>
        <div class="warn"><label><input type="checkbox" name="adopt" value="1">
          ${t('case.adopt')}</label><br>
          <span class="muted">${t('case.adopt.why')}</span></div>
      </div>
      <div class="row"><button type="submit">${t('case.save')}</button>
        ${EDIT ? `<button type="button" data-act="case.fresh">${t('case.fresh')}</button>`
    : ''}</div>
    </form>
    <div id="hits"></div>`);
  watchForm();
  EDIT = null;
};

Object.assign(ACTIONS, {
  /** 🖼 Подивитись, ЩО це, перш ніж описувати: без кадрів опис — вгадування. */
  'intake.frames': (_ev, elm) => goto('frames', { case: elm.dataset.arg }),

  /** Розгорнути теки групи. */
  'intake.toggle': (_ev, elm) => {
    const tb = el(`ig-${elm.dataset.arg}`);
    if (!tb) return;
    tb.hidden = !tb.hidden;
    elm.textContent = t(tb.hidden ? 'intake.show' : 'intake.hide');
  },

  /** Описати теку, якої в переліку немає (поза простором, щойно скопійовану). */
  'intake.other': async () => {
    EDIT = null;
    await show('newcase');
  },

  /**
   * «Не справа» — спершу спитати, що це, і лише тоді відкласти.
   *
   * Причина не прикраса: через пів року «відкладено» без «що це» не відрізнити
   * від «відкладено помилково», і повертати доведеться наосліп.
   */
  'intake.aside.ask': (_ev, elm) => {
    const box = el(`ia-${elm.dataset.arg}`);
    if (!box) return;
    box.innerHTML = `<select id="iw-${esc(elm.dataset.arg)}">${ASIDE_WHY.map((k) =>
      `<option value="${esc(t(`intake.why.${k}`))}">${esc(t(`intake.why.${k}`))}</option>`).join('')}</select>
      <button class="ctl-sm" data-act="intake.aside.do" data-arg="${esc(elm.dataset.arg)}"
        data-path="${esc(elm.dataset.path)}">${t('intake.aside.do')}</button>
      <button class="ctl-sm" data-act="intake.aside.cancel">${t('intake.cancel')}</button>`;
  },

  'intake.aside.cancel': () => show('cases'),

  'intake.aside.do': async (_ev, elm) => {
    const sel = el(`iw-${elm.dataset.arg}`);
    const env = await callOp('intake.aside',
      { paths: [elm.dataset.path], why: sel ? sel.value : '' });
    if (!env.ok) return failure(env);
    return show('cases');
  },

  'intake.unaside': async (_ev, elm) => {
    const env = await callOp('intake.aside', { paths: [elm.dataset.path], undo: true });
    if (!env.ok) return failure(env);
    return show('cases');
  },

  'cases.build': async () => {
    const env = await callOp('cases.build', { rescan: true });
    if (!env.ok) return failure(env);
    // 🔴 Кнопка, після якої нічого видимо не сталось, натискається вдруге —
    // тому стан обов'язково видно. Але показувати його треба тут: людина
    // натиснула «перезібрати», дивлячись на цей перелік, і саме він зміниться
    // по завершенні. Перекидання на чергу забирало в неї місце й фільтр.
    const box = el('view');
    const id = (env.data || {}).job_id;
    if (!box || !id) return show('cases');
    box.insertAdjacentHTML('afterbegin',
      `<p id="cases-job" class="muted">${jobChip({ state: 'queued', progress: {} })}</p>`);
    const chip = el('cases-job');
    onJob(id, (j) => {
      if (chip) chip.innerHTML = jobChip(j);
      if (j.state === 'done') show('cases');
    });
    return undefined;
  },

  'case.edit': async (_ev, elm) => {
    const env = await callOp('case.show', { case_dir: elm.dataset.arg });
    if (!env.ok) return failure(env);
    EDIT = env.data;
    await show('newcase');
    if (env.warnings && env.warnings.length) {
      el('hits').innerHTML = renderWarnings(env);
    }
  },

  'case.fresh': async () => {
    EDIT = null;
    await show('newcase');
  },

  'case.repo.toggle': () => {
    const box = el('repo-add');
    if (box) box.hidden = !box.hidden;
  },

  /**
   * ➕ Додати архів, якого пак не знає.
   *
   * 🔴 Досі це вміла лише правка YAML руками, і застосунок не казав про неї
   * ніде — дослідник із польським чи білоруським архівом не заводив справу
   * через інтерфейс узагалі. Форма лишається на екрані: людина щойно набирала
   * опис справи, і викинути його заради додавання архіву означало б змусити
   * набрати все вдруге.
   */
  'case.repo.add': async () => {
    const env = await callOp('archive.add', {
      code: (el('repo-code') || {}).value || '',
      label: (el('repo-label') || {}).value || '',
      name: (el('repo-name') || {}).value || '',
    });
    const hits = el('repo-hits');
    if (!env.ok) {
      if (hits) hits.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return;
    }
    // Перелік перепитуємо, а не дописуємо руками: пак міг звести написання
    // інакше, ніж очікує форма, і розбіжність тут була б невидима.
    const fresh = await callOp('archives.list', {});
    if (fresh.ok) REPOS = fresh.data;
    const sel = document.querySelector('select[name="repo"]');
    if (sel) sel.innerHTML = repoOptions(env.data.code);
    if (hits) {
      hits.innerHTML = `${renderWarnings(env)}
        <div class="warn">✅ ${esc(env.data.label)} — ${t('case.repo.added')}</div>`;
    }
  },

  'case.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    // ⚠ Тире доїжджає ТИРЕ, а не `NaN`. `Number('-')` дає `NaN`, JSON робить із
    // нього `null`, а `null` для схеми означає «не чіпай» — тобто обіцянка
    // «тире стирає поле» для років була мовчазним холостим ходом.
    for (const k of ['year_from', 'year_to']) {
      const raw = String(fd[k] || '').trim();
      fd[k] = raw ? (['-', '—', '–'].includes(raw) ? raw : Number(raw)) : null;
    }
    // Незнята позначка у FormData просто відсутня — схема чекає булеве поле.
    fd.adopt = fd.adopt === '1';
    const env = await callOp('case.register', fd);
    if (!env.ok) {
      el('hits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return;
    }
    const sc = env.data.sidecar;
    el('hits').innerHTML = `${renderWarnings(env)}
      <div class="warn">✅ <b>${esc(sc.shifra)}</b> — ${esc(sc.title || 'без назви')}</div>`;
  },
});
