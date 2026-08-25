/** ⚙ Налаштування секцій. */

import { t, LANG } from '../core/strings.js';
import { TOKEN, callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, busyForm,
  renderWarnings, renderCoverage, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { SECTIONS, NAV_LABEL, show, renderNav,
  refreshJobs } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic, eng } from '/ui/icons.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';




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
  SECTIONS = env.data;
  const presets = Object.keys(env.data.presets || {});
  const rows = (env.data.sections || []).map((s) => {
    const label = LANG === 'en' ? s.label_en : s.label;
    const why = LANG === 'en' ? s.why_en : s.why;
    const screens = (s.screens || []).map((x) => esc(t(NAV_LABEL[x] || x))).join(' · ');
    // Знак секції — той самий, що в переліку `nysh sections`: два обличчя одного
    // застосунку не мають виглядати як два різні продукти.
    const g = ((env.data.glyphs || {}).sections || {})[s.id] || '';
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
      <td>${s.active ? '✅' : (s.visible ? '⬜' : '▫️')}</td>
      <td><b>${g ? esc(g) + ' ' : ''}${esc(label)}</b><br><span class="muted">${esc(why)}</span>
          ${screens ? `<br><span class="muted mono">${screens}</span>` : ''}</td>
      <td class="num">${s.ops}</td>
      <td>${control}</td>
    </tr>`;
  }).join('');
  setView(`<h2>⚙ ${t('sect.title')}</h2>
    <p class="muted">${t('sect.why')}</p>
    ${renderWarnings(env)}
    <p>${t('sect.preset')}:
      ${presets.map((p) => `<button data-act="sections.preset" data-arg="${esc(p)}"
        ${p === env.data.preset ? 'disabled' : ''}>${esc(t('preset.' + p))}</button>`).join(' ')}
      <span class="muted">${env.data.preset ? '' : t('sect.custom')}</span></p>
    <table><tbody>${rows}</tbody></table>`);
};

Object.assign(ACTIONS, {
  'sections.preset': async (_ev, elm) => {
    const env = await callOp('sections.set', { preset: elm.dataset.arg });
    if (!env.ok) return failure(env);
    SECTIONS = env.data;
    renderNav();
    await show('settings');
  },

  'sections.toggle': async (_ev, elm) => {
    const id = elm.dataset.arg;
    const on = !!elm.dataset.on;
    const env = await callOp('sections.set',
      on ? { disable: [id] } : { enable: [id] });
    if (!env.ok) return failure(env);
    SECTIONS = env.data;
    renderNav();
    await show('settings');
  },
});
