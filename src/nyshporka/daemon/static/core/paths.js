/** 📂 Вибір шляху: міст до сервера, дія кнопки й розмітка поля.
 *
 * Спільний віджет (`/ui/pathpick.js`) навмисно не знає ні про операції, ні про
 * маршрути — ту саму теку `/ui/` монтує друга морда, у якої інший бекенд. Отже
 * все, що стосується цього застосунку, живе тут: як спитати сервер, як дочекатись
 * системного вікна, як виглядає поле шляху й якими словами воно підписане.
 */

import { t } from './strings.js';
import { callOp, FINAL_STATES } from './net.js';
import { el, esc } from './view.js';
import { ACTIONS } from './registry.js';
import { ic } from '/ui/icons.js';
import { setPathBridge, pickPath, closePathPick } from '/ui/pathpick.js';

/**
 * Підписи для віджета.
 *
 * 🔴 Пари ключів виписані явно, а не зібрані шаблоном `t('pick.' + mode)`.
 * Приймач перекладу шукає в коді літеральні `t('…')` — шаблонний рядок він не
 * бачить, тобто забутий переклад пройшов би повз ворота й вилізав би вже в
 * англійському інтерфейсі порожнім ключем.
 */
function pickLabels() {
  return {
    title: { dir: t('pick.title.dir'), file: t('pick.title.file'),
             files: t('pick.title.files'), save: t('pick.title.save') },
    ok: { dir: t('pick.ok.dir'), file: t('pick.ok.file'),
          files: t('pick.ok.files'), save: t('pick.ok.save') },
    up: t('pick.up'), close: t('pick.close'), go: t('pick.go'),
    path: t('pick.path'), filter: t('pick.filter'), name: t('pick.name'),
    drives: t('pick.drives'), places: t('pick.places'),
    empty: t('pick.empty'), denied: t('pick.denied'),
    loading: t('common.loading'), more: t('pick.more'), selected: t('pick.selected'),
    shown: t('pick.shown'),
    frames: t('pick.frames'), pdfs: t('pick.pdfs'), dirs: t('pick.dirs'),
    mk: t('pick.mk'), mkName: t('pick.mk.name'), cancel: t('pick.cancel'),
    native: t('pick.native'), nativeOff: t('pick.native.off'),
    wait: t('pick.wait'), waitHint: t('pick.wait.hint'), waitHere: t('pick.wait.here'),
    outside: t('pick.outside'), outsideWhy: t('pick.outside.why'),
    keys: t('pick.keys'),
  };
}

/**
 * Дочекатись системного вікна.
 *
 * 🔴 Це довга робота, і не для зручності: синхронна операція виконується на
 * циклі подій демона, а системне вікно чекає людину — доки вона не відповість,
 * не працює ні черга, ні інші вкладки, ні статика. Тому та сама схема, що в
 * прочісуванні корпусу: старт → опитування черги → конверт.
 */
async function waitDialog(args) {
  const started = await callOp('pick.ask', args);
  if (!started.ok) return { state: 'error', error: started.error };
  const id = (started.data || {}).job_id || '';
  for (;;) {
    const res = await fetch('/api/jobs');
    const data = await res.json().catch(() => ({}));
    const job = (data.jobs || []).find((x) => x.id === id);
    if (!job) return { state: 'error', error: t('pick.lost') };
    if (FINAL_STATES.includes(job.state)) {
      if (job.state !== 'done') return { state: 'error', error: job.error || job.state };
      return job.result || {};
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

let PROBED = null;

setPathBridge({
  async list(req) {
    const env = await callOp('pick.browse', {
      path: req.path || '', want: req.want || 'all', patterns: req.patterns || [],
      q: req.q || '', limit: req.limit || 200, offset: req.offset || 0,
      show_hidden: !!req.show_hidden,
    });
    if (!env.ok) throw new Error(env.error || 'не вийшло');
    const d = env.data || {};
    // Спроможність системного вікна їде разом із першим лістингом, а не окремим
    // запитом: одна відповідь — одна правда, і кнопки, якої не буде де
    // натиснути, людина не побачить узагалі.
    if (PROBED === null) {
      const can = await callOp('pick.can', {});
      PROBED = can.ok ? can.data : { can: false, why: '' };
    }
    d.native = !!PROBED.can;
    d.nativeWhy = PROBED.why || '';
    return d;
  },

  async dialog(req) {
    const got = await waitDialog({
      mode: req.mode || 'dir', purpose: req.purpose || '', title: req.title || '',
      start: req.start || '', name: req.name || '', patterns: req.patterns || [],
    });
    return { state: got.state || 'error', paths: got.paths || [],
             why: got.why || got.error || '' };
  },

  async mkdir(req) {
    const env = await callOp('pick.mkdir', { path: req.path, name: req.name });
    if (!env.ok) return { error: env.error };
    return { path: (env.data || {}).path || '' };
  },
});

/**
 * Розмітка поля шляху: `<input>` плюс кнопка вибору.
 *
 * 🔴 Поле адресується за `id`, а не через форму: кнопка передає його в
 * `data-arg`, а дія бере `getElementById`. Так ланка «кнопка → поле» лишається
 * простою й перевірюваною — пошук по формі в тестовому середовищі не працює.
 *
 * 🔴 `type="button"` обов'язковий: поля шляху стоять усередині форм, і кнопка
 * без типу — це кнопка надсилання, тобто клік по ній відправляв би форму
 * замість того, щоб відкрити вибір.
 */
export function pathField(o) {
  const name = o.name;
  const id = o.id || ('pf-' + name);
  const mode = o.mode || 'dir';
  return `<span class="pf">
    <input id="${esc(id)}" name="${esc(name)}" value="${esc(o.value || '')}"
      placeholder="${esc(o.ph || '')}"${o.autofocus ? ' autofocus' : ''}>
    <button type="button" class="ctl-sm" data-act="path.pick" data-arg="${esc(id)}"
      data-mode="${esc(mode)}" data-purpose="${esc(o.purpose || name)}"
      title="${esc(o.title || t('pick.open'))}">${ic('folder-open', 'ic-o ic-sm')}</button>
  </span>`;
}

/**
 * Тека поза простором — поставити позначку «взяти під облік» самим.
 *
 * 🔴 Один рух замість двох, і зроблений там, де людина вже дивиться. Інакше
 * послідовність така: обрав теку на зовнішньому диску, зберіг справу, побачив
 * ✅ — і не знайшов її в жодному переліку. Причина при цьому написана в формі,
 * але написана нижче поля, дрібним, і читати її немає приводу: доти, доки не
 * стало пізно, ця позначка виглядає як налаштування для когось іншого.
 *
 * ⚠ Позначку ставимо, але не знімаємо: людина могла ввімкнути її свідомо, і
 * забрати чуже рішення гірше, ніж не додати свого.
 */
function markOutside(elm, got) {
  if (!got.outside || !got.outside.is) return;
  const form = elm.closest ? elm.closest('form') : null;
  const box = form ? form.querySelector('input[name="adopt"]') : null;
  if (!box || box.checked) return;
  box.checked = true;
  box.dispatchEvent(new Event('change', { bubbles: true }));
}

Object.assign(ACTIONS, {
  /** 📂 Вибрати шлях і покласти його в поле. */
  'path.pick': async (_ev, elm) => {
    const input = el(elm.dataset.arg);
    if (!input) return;
    const mode = elm.dataset.mode || 'dir';
    const got = await pickPath({
      mode,
      start: input.value || '',
      purpose: elm.dataset.purpose || elm.dataset.arg,
      patterns: elm.dataset.patterns ? elm.dataset.patterns.split(',') : [],
      labels: pickLabels(),
    });
    if (!got.ok) return;
    input.value = got.path;
    // 🔴 Порядок цих чотирьох рядків має значення. Події потрібні, щоб
    // спрацювали слухачі поля (підказки бібліотеки, живі фільтри), але саме
    // вони — і повернутий фокус — знову відкривають попап комбобокса. Тому
    // закриття стоїть останнім: інакше вибір теки щоразу закінчувався б
    // випадним списком, який людина не викликала.
    if (input.focus) input.focus();
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    if (input._cb && input._cb.close) input._cb.close();
    markOutside(elm, got);
  },
});

// Гортач переживає перемальовку екрана, тож при переході його закриває морда:
// модалка, що лишилась висіти над іншим екраном, — це вікно, яке нікуди не веде.
window.addEventListener('hashchange', () => { closePathPick('gone'); });

export { pickPath, closePathPick };
