/** ⚙ Налаштування секцій. */

import { toast } from '../core/bits.js';
import { t, tOr, LANG } from '../core/strings.js';
import { netBox } from './update.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive, leadMini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { NAV_LABEL, show, renderNav, refreshJobs, setSections } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';
import { pathField, pickPath } from '../core/paths.js';




/**
 * ⚙ Налаштування: які частини застосунку ввімкнено.
 *
 * Пресет — те, з чого починають («я тут щоб прочитати свої скани»), окремі
 * перемикачі — для того, хто вже знає, чого хоче. Порожня секція показується
 * сірою й непереставною: вона оголошена, але вмикати в ній ще нічого, а
 * кнопка, що нічого не додає до шапки, читається як поламана.
 */
SCREENS.settings = async () => {
  const gen = curGen();
  busy();
  const env = await callOp('sections.show', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  setSections(env.data);
  const presets = Object.keys(env.data.presets || {});
  const rows = (env.data.sections || []).map((s) => {
    const label = tOr(`section.${s.id}.label`, s.label);
    const why = tOr(`section.${s.id}.why`, s.why);
    const screens = (s.screens || []).map((x) => esc(t(NAV_LABEL[x] || x))).join(' · ');
    // Знак секції — той самий, що в переліку `nysh sections`: два обличчя одного
    // застосунку не мають виглядати як два різні продукти.
    const g = ((env.data.icons || {}).sections || {})[s.id] || '';
    let control;
    if (s.required) {
      control = `<span class="muted">${t('sect.always')}</span>`;
    } else if (!s.visible) {
      control = `<span class="muted">${t('sect.empty')}</span>`;
    } else {
      control = `<button data-act="sections.toggle" data-arg="${esc(s.id)}"
        data-on="${s.active ? '1' : ''}">${s.active ? t('sect.off') : t('sect.on')}</button>`;
    }
    return `<tr>
      <td>${s.active ? ic('check-circle', 'ic-sm') : ''}</td>
      <td><b>${g ? ic(g, 'ic-sm') + ' ' : ''}${esc(label)}</b><br><span class="muted">${esc(why)}</span>
          ${screens ? `<br><span class="muted mono">${screens}</span>` : ''}</td>
      <td class="num">${s.ops}</td>
      <td>${control}</td>
    </tr>`;
  }).join('');
  setView(`<h2>${t('sect.title')}</h2>
    ${leadMini('kliuch', t('sect.why'))}
    ${renderWarnings(env)}
    <p>${t('sect.preset')}:
      ${presets.map((p) => `<button data-act="sections.preset" data-arg="${esc(p)}"
        ${p === env.data.preset ? 'class="on" aria-pressed="true" disabled' : ''}>${esc(t('preset.' + p))}</button>`).join(' ')}
      <span class="muted">${env.data.preset ? '' : t('sect.custom')}</span></p>
    <table><tbody>${rows}</tbody></table>
    <div id="roots"></div>
    <div id="ver"></div>`);
  await renderRoots();
  renderVersion();
};

/**
 * 🌐 Мережа: фонова перевірка оновлень і сповіщення Супряги.
 *
 * 🔴 Обидва вимикачі типово вимкнені: `PRIVACY.md` обіцяє «фонової активності в
 * мережі немає», і консоль іде в мережу сама лише тоді, коли людина це
 * ввімкнула тут (рішення дослідника 23.10.2026). Що йде і куди — під кожним.
 * Сама версія, «що нового» й кнопка оновлення — на екрані «Оновлення».
 */
function renderVersion() {
  const box = el('ver');
  if (!box) return;
  box.innerHTML = `<h3>${t('up.net')}</h3>
    <p class="muted">${t('net.why')}</p>
    <div id="net-box"></div>
    <p><button data-act="nav" data-arg="update">${ic('bell', 'ic-sm')} ${t('nav.update')}</button></p>`;
  callOp('notices.state', { lang: LANG }).then((env) => {
    const nb = el('net-box');
    if (nb && env.ok) nb.innerHTML = netBox((env.data || {}).settings || {}, (env.data || {}).logged_in);
  });
}

/**
 * 🌳 Корені справ: де застосунок шукає скани.
 *
 * 🔴 Керувати ними з браузера доти було нічим. Оголосити корінь можна було лише
 * разом із заведенням однієї справи (позначкою у формі), а зняти — лише руками
 * в маркері простору. Тобто помилковий корінь — не та тека, флешка колеги —
 * лишався назавжди, і виправити його пропонувалось редагуванням файлу, якого
 * людина не заводила.
 */
async function renderRoots() {
  const box = el('roots');
  if (!box) return;
  const env = await callOp('roots.list', {});
  if (!env.ok) return boxError('roots', env);
  const rows = (env.data.roots || []).map((r) => `<tr>
    <td>${r.kind === 'space' ? ic('house', 'ic-o ic-sm') : ic('anchor', 'ic-o ic-sm')}</td>
    <td class="mono">${esc(r.path)}${r.gone
      ? ` <span class="warn-inline">${t('roots.gone')}</span>` : ''}</td>
    <td>${r.kind === 'space'
      ? `<span class="muted">${t('roots.always')}</span>`
      : `<button data-act="roots.forget" data-arg="${esc(r.path)}"
           >${t('roots.forget')}</button>`}</td>
  </tr>`).join('');
  box.innerHTML = `<h3>${t('roots.title')}</h3>
    <p class="muted">${t('roots.why')}</p>
    ${renderWarnings(env)}
    <table><tbody>${rows}</tbody></table>
    <p><button data-act="roots.pick">${ic('folder-open', 'ic-sm')} ${t('roots.add')}</button>
      <span class="muted">${t('roots.keep')}</span></p>
    <div id="roots-hits"></div>`;
}

Object.assign(ACTIONS, {

  /** 📂 Оголосити нову теку коренем — вибором, а не набором шляху. */
  'roots.pick': async () => {
    const got = await pickPath({ mode: 'dir', purpose: 'roots.add' });
    if (!got.ok) return;
    const env = await callOp('roots.add', { path: got.path });
    // 🔴 Відмова — у ВЛАСНУ коробку під переліком, а не в `#roots`.
    //
    // `#roots` — це весь розділ разом із кнопками «Оголосити корінь» і
    // «Забути». Писати помилку туди означало стерти саме той засіб, яким її
    // виправляють: людина вибирає теку, якої вже немає, читає «такої теки
    // немає» — і бачить, що розділ «Корені справ» зник цілком. Це рівно те
    // «шукати дорогу назад», проти чого й писалась ця правка.
    if (!env.ok) return boxError('roots-hits', env);
    toast(t('toast.root.added'), { tone: 'ok' });
    await renderRoots();
  },

  'roots.forget': async (_ev, elm) => {
    const env = await callOp('roots.remove', { path: elm.dataset.arg });
    if (!env.ok) return boxError('roots-hits', env);
    toast(t('toast.root.removed'), { tone: 'ok' });
    await renderRoots();
  },

  'sections.preset': async (_ev, elm) => {
    const env = await callOp('sections.set', { preset: elm.dataset.arg });
    if (!env.ok) return failure(env);
    toast(t('toast.sections'), { tone: 'ok' });
    setSections(env.data);
    renderNav();
    await show('settings');
  },

  'sections.toggle': async (_ev, elm) => {
    const id = elm.dataset.arg;
    const on = !!elm.dataset.on;
    const env = await callOp('sections.set',
      on ? { disable: [id] } : { enable: [id] });
    if (!env.ok) return failure(env);
    toast(t('toast.sections'), { tone: 'ok' });
    setSections(env.data);
    renderNav();
    // 🔴 Повертаємось туди, заради чого вмикали. Кнопка стоїть не лише в
    // налаштуваннях, а й на банері вимкненої секції — тобто людина йшла на
    // конкретний екран, і висадити її в налаштуваннях означає змусити шукати
    // дорогу назад до того, що вона щойно відкрила.
    await show(elm.dataset.back || 'settings');
  },
});
