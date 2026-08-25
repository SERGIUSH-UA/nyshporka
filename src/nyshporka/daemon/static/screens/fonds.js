/** 🏛 Реєстр опису фонду. */

import { t } from '../core/strings.js';
import { callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, busyForm,
  renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';
import { swapHtml } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';

/**
 * Що зараз відкрито в описі. Живе між входами: повернувшись, людина бачить той
 * самий фонд і ту саму сторінку, а не порожню форму.
 */
let FD = { fond: '', q: '', surname: '', uezd: '', state: '', spr: '',
  page: 0, pages: 1 };

/**
 * 🏛 Фонди — реєстр ОПИСУ: «що взагалі існує в архіві».
 *
 * 🔴 Це окреме сховище поруч із бібліотекою («що ми маємо») і приймальнею («що
 * лежить на диску нічим»). Плутати їх дорого: «справи немає» ТУТ означає «в
 * архіві не існує», а в бібліотеці — «ще не завантажено». Два різні «немає»,
 * і на другому закривають напрям, якого ніхто не перевіряв.
 *
 * 🔴 Перелік фондів малюється ОДРАЗУ таблицею. Доти він був захований у
 * випадному списку всередині форми, тобто щоб побачити, що реєстр не порожній,
 * треба було спершу натиснути «Знайти» — і людина, яка цього не зробила,
 * чесно вважала, що описів у неї немає.
 */
SCREENS.fonds = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('fond.list', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const fonds = env.data.fonds || [];
  // Засів із бібліотеки чи газетира: там уже знають фонд і номер справи.
  const seed = ST.fonds;
  if (seed) {
    const hit = fonds.find((f) => f.repo === seed.repo && f.fond === seed.fond);
    FD = { ...FD, fond: (hit || {}).id || FD.fond, spr: seed.spr || '', page: 0 };
    ST.fonds = null;      // засів одноразовий: інакше він держав би екран
  }
  setView(`
    <h2>${t('nav.fonds')}</h2>
    <p class="muted">${t('fonds.why')}</p>
    ${renderWarnings(env)}
    ${fonds.length ? fondTable(fonds) : fondNone()}
    ${collectBlock()}
    <div id="fondrows"></div>`);
  if (FD.fond && fonds.some((f) => f.id === FD.fond)) await fondLoad();
  // Збирачі тягнуться ОКРЕМО й після: їхня відсутність (не поставлено extras)
  // не має права затримати показ самого реєстру.
  const col = await callOp('registry.collectors', {});
  if (!alive(gen)) return;
  const box = el('fd-collector');
  if (!box) return;
  const items = (col.ok && (col.data || {}).collectors) || [];
  box.innerHTML = items.length
    ? items.map((c) => `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join('')
    : `<option value="">${esc(t('fonds.collect.none'))}</option>`;
};

/**
 * Таблиця фондів: скільки справ в описі, скільки з них уже в нас.
 *
 * 🔴 Три числа в рядку — це три різні стани того самого фонду, і саме на них
 * вирішують, чи є сенс замовляти документ в архіві.
 */
function fondTable(fonds) {
  return `<table><thead><tr>
      <th>фонд</th>
      <th class="num">${t('fonds.rows')}</th>
      <th class="num">${t('fonds.ondisk')}</th>
      <th class="num">${t('fonds.todo')}</th>
      <th></th></tr></thead><tbody>
    ${fonds.map((f) => `<tr${f.id === FD.fond ? ' class="on"' : ''}>
      <td><b>${esc(f.label)}</b></td>
      <td class="num">${esc(f.rows)}</td>
      <td class="num">${esc(f.on_disk)}</td>
      <td class="num">${esc(f.todo)}</td>
      <td><button data-act="fond.open" data-arg="${esc(f.id)}">
        ${t('fonds.open')}</button></td>
    </tr>`).join('')}
    </tbody></table>`;
}

/**
 * Порожній реєстр описів — і що з цим робити.
 *
 * 🔴 Доти тут друкувався текст про ПАКИ ДОВІДНИКІВ, яких `fond.list` не читає
 * взагалі: відповідь була не на те питання, і порада вела не туди.
 */
function fondNone() {
  return `<div class="warn"><b>${t('fonds.none')}</b>
    <p class="muted">${t('fonds.none.why')}</p></div>`;
}

/**
 * 🧾 Зібрати опис фонду.
 *
 * 🔴 Чотири операції збирання існували від початку й не мали ЖОДНОГО входу з
 * екрана: зібрати опис можна було тільки командним рядком. Тобто екран, який
 * без реєстру порожній, не показував способу цей реєстр завести.
 */
function collectBlock() {
  return `<details class="collect"><summary>🧾 ${t('fonds.collect')}</summary>
    <p class="muted">${t('fonds.collect.why')}</p>
    <form class="row" data-act="fond.collect">
      <select name="collector" id="fd-collector"></select>
      <input name="repo" id="fd-repo" placeholder="${t('fonds.collect.repo')}" size="8">
      <input name="fond" id="fd-fond" placeholder="${t('fonds.collect.fond')}" size="6">
      <input name="opys" placeholder="${t('fonds.collect.opys')}" size="6">
      <button type="submit" data-plan="1">${t('fonds.collect.plan')}</button>
      <button type="button" data-act="fond.merge">${t('fonds.merge')}</button>
    </form>
    <div id="fd-collect"></div></details>`;
}

/** Рядки опису обраного фонду. */
async function fondLoad() {
  const seq = ++SEQ.fond;
  const box = el('fondrows');
  if (!box) return;
  box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  const env = await callOp('fond.rows', {
    fond: FD.fond, q: FD.q, surname: FD.surname, uezd: FD.uezd,
    state: FD.state, spr: FD.spr, page: FD.page, page_size: 50,
  });
  if (seq !== SEQ.fond) return;
  if (!env.ok) {
    box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
    return;
  }
  const d = env.data;
  FD.pages = d.pages || 1;
  const rows = d.rows || [];
  swapHtml(box, `
    <h3>${esc(d.fond)}</h3>
    ${fondForm()}
    ${renderWarnings(env)}
    <p class="muted">${t('fonds.matched')} <b>${esc(d.matched)}</b>
      ${t('fonds.of')} <b>${esc((d.summary || {}).rows)}</b></p>
    ${rows.length ? `<table><thead><tr>
      <th></th><th>шифра</th><th>назва</th><th>роки</th>
      <th class="num">арк.</th><th>плівка</th><th></th>
      </tr></thead><tbody>
    ${rows.map(fondRow).join('')}
    </tbody></table>${pager(d)}` : ''}`);
}

/** Фільтри рядків опису. Стоять НАД видачею, бо звужують саме її. */
function fondForm() {
  const opt = (v, label) =>
    `<option value="${esc(v)}"${FD.state === v ? ' selected' : ''}>${label}</option>`;
  return `<form class="row" data-act="fond.filter">
      <input name="q" placeholder="${t('fonds.filter')}" value="${esc(FD.q)}">
      <input name="surname" placeholder="${t('fonds.surname')}" size="18"
        value="${esc(FD.surname)}">
      <input name="uezd" placeholder="${t('fonds.uezd')}" size="12"
        value="${esc(FD.uezd)}">
      <input name="spr" placeholder="${t('fonds.spr')}" size="7"
        value="${esc(FD.spr)}">
      <select name="state">
        ${opt('', t('fonds.state.any'))}
        ${opt('disk', t('fonds.state.disk'))}
        ${opt('todo', t('fonds.state.todo'))}
        ${opt('film', t('fonds.state.film'))}
        ${opt('order', t('fonds.state.order'))}
      </select>
      <button type="submit">${t('geog.find')}</button>
    </form>`;
}

/**
 * Один рядок опису — і що з ним можна зробити.
 *
 * 🔴 Доти рядок був тупиком: жодної кнопки. Людина бачила «скан є, не взято» —
 * і не мала чим узяти; бачила «у нас на диску» — і не мала чим відкрити.
 */
function fondRow(r) {
  const mark = r.on_disk ? '✓' : (r.state === 'todo' ? '⬇' : '·');
  const acts = [];
  if (r.on_disk) {
    acts.push(`<button data-act="fond.lib" data-arg="${esc(r.key)}"
      title="${t('fonds.act.lib')}">${ic('books', 'ic-o ic-sm')}</button>`);
  } else if (r.takeable) {
    acts.push(`<button data-act="fond.take" data-arg="${esc(r.key)}"
      title="${t('fonds.act.take')}">${ic('download', 'ic-o ic-sm')}</button>`);
  }
  return `<tr>
    <td title="${esc(r.state || '')}">${mark}</td>
    <td class="mono">${esc(r.shifra)}</td>
    <td>${esc((r.title || '').slice(0, 90))}</td>
    <td>${r.year_from ? `${esc(r.year_from)}–${esc(r.year_to)}` : ''}</td>
    <td class="num">${esc(r.folios || '')}</td>
    <td class="mono">${esc(r.fs_film || '')}</td>
    <td>${acts.join(' ')}</td>
  </tr>`;
}

PAGERS.fonds = (delta) => {
  FD.page = step(FD.page, delta, FD.pages);
  return fondLoad();
};

Object.assign(ACTIONS, {
  'fond.open': (_ev, elm) => {
    FD = { ...FD, fond: elm.dataset.arg, page: 0 };
    return show('fonds');
  },

  'fond.filter': (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    FD = { ...FD, q: f.get('q') || '', surname: f.get('surname') || '',
      uezd: f.get('uezd') || '', spr: f.get('spr') || '',
      state: f.get('state') || '', page: 0 };
    return fondLoad();
  },

  /** 📚 Ця сама справа в бібліотеці — за спільним ключем, а не пошуком. */
  'fond.lib': (_ev, elm) => goto('library', { key: elm.dataset.arg }),

  /**
   * ⬇ Узяти справу в роботу.
   *
   * 🔴 Робота довга й іде в чергу — туди ж і ведемо. Кнопка, після якої нічого
   * видимо не сталось, натискається вдруге, а вдруге тут означає другу
   * закачку тієї самої справи.
   */
  'fond.take': async (_ev, elm) => {
    const env = await callOp('fond.take', { key: elm.dataset.arg });
    if (!env.ok) return alert(env.error);
    return show('jobs');
  },

  'fond.collect': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    const args = {
      collector: f.get('collector') || '', repo: f.get('repo') || '',
      fond: f.get('fond') || '', opys: f.get('opys') || '',
    };
    // 🔴 Спершу ПЛАН, і тільки потім збирання. План не робить жодної мережевої
    // дії й коштує нуль секунд, а дізнатись «збирати нема з чого» після
    // півгодини обходу — найдорожчий спосіб це з'ясувати.
    const plan = await callOp('registry.plan', args);
    unlock();
    const box = el('fd-collect');
    if (!box) return undefined;
    if (!plan.ok) {
      box.innerHTML = `<div class="warn err">${esc(plan.error)}</div>`;
      return undefined;
    }
    box.innerHTML = `${renderWarnings(plan)}
      <pre class="mono">${esc(JSON.stringify(plan.data, null, 1))}</pre>
      <button data-act="fond.collect.go"
        data-arg="${esc(JSON.stringify(args))}">${t('fonds.collect.go')}</button>`;
    return undefined;
  },

  'fond.collect.go': async (_ev, elm) => {
    const env = await callOp('registry.collect', JSON.parse(elm.dataset.arg));
    if (!env.ok) return alert(env.error);
    return show('jobs');
  },

  /**
   * 🔴 Злиття — ОКРЕМИЙ крок, і саме тому окрема кнопка. Збирання кладе
   * `registry/<збирач>.tsv` і реєстру ще не міняє; доки не злито, екран
   * лишається порожнім, і виглядає це так, ніби обхід нічого не привіз.
   */
  'fond.merge': async () => {
    // Поля читаються за id, а не через `FormData`: ця кнопка не подає форму
    // (вона `type="button"`), тож події `submit` тут немає й бути не може.
    const val = (id) => (el(id) || {}).value || '';
    const env = await callOp('registry.merge', {
      repo: val('fd-repo'), fond: val('fd-fond'),
    });
    if (!env.ok) return alert(env.error);
    return show('jobs');
  },
});
