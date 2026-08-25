/** 🏠 Домівка: три двері в застосунок. */

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
 * 📖 Що сказати про зразкову справу — три РІЗНІ стани, і плутати їх дорого.
 *
 * «Зразка немає в цій збірці» — межа версії, лагодити нічого. «Є, але не
 * розгорнутий» — одна кнопка. «Розгорнутий» — запрошення в гортач. Спільне
 * формулювання на всі три посилало б людину лагодити те, що справне, або
 * ховало б дію, яка є.
 */
function sampleBlock(d) {
  if (!d.sample_available) return `<p class="muted">${t('check.nosample')}</p>`;
  if (d.sample_case) return `<p class="muted">✅ ${t('check.sample.ready')}</p>`;
  return `<p class="muted">${t('check.sample.hint')}</p>
    <p><button data-act="sample.install">${t('check.sample.do')}</button></p>`;
}

SCREENS.home = async () => {
  const gen = curGen();
  const env = await callOp('workspace.info', {});
  if (!alive(gen)) return;
  const ws = env.ok ? env.data : {};
  setView(`
    <h2>${t('home.title')}</h2>
    ${renderWarnings(env)}
    <div class="cards">
      <button class="card" data-act="home.scans">
        <span class="card-title">📁 ${t('home.have_scans')}</span>
        <span class="card-hint">${t('home.have_scans.hint')}</span>
      </button>
      <button class="card" data-act="nav" data-arg="sources">
        <span class="card-title">🔎 ${t('home.where')}</span>
        <span class="card-hint">${t('home.where.hint')}</span>
      </button>
      <button class="card" data-act="home.demo">
        <span class="card-title">▶ ${t('home.demo')}</span>
        <span class="card-hint">${t('home.demo.hint')}</span>
      </button>
    </div>
    <p class="muted mono">${esc(ws.root || '')}</p>`);
};

Object.assign(ACTIONS, {
  'home.scans': async () => {
    // 🔴 Раніше ця картка — перший клік того, заради кого все й робилось —
    // відсилала в командний рядок за `nysh look`. Вибору теки віконцем браузер
    // справді не дасть, але ШЛЯХ у форму вписати можна, і форма вже є. Відсилати
    // до терміналу того, хто щойно поставив застосунок подвійним кліком, значило
    // б обірвати шлях на першому ж кроці.
    await show('newcase');
  },

  'home.demo': async () => {
    // 🔴 Раніше тут вивалювався сирий JSON про середовище рушіїв — під написом
    // «перевірити, що читання працює на цій машині». Питання правильне, а
    // відповідь була не тими словами й не про те: людина, яка щойно поставила
    // застосунок, мусить прочитати, ЧОГО бракує і ЧИМ це ставиться.
    busy();
    const env = await callOp('setup.check', {});
    if (!env.ok) return failure(env);
    const rows = (env.data.checks || []).map((c) => {
      const mark = { ok: '✅', warn: '⚠', fail: '🔴' }[c.level] || '•';
      return `<tr><td>${mark}</td><td><b>${esc(c.name)}</b><br>
        <span class="muted">${esc(c.detail)}</span></td>
        <td>${c.fix ? `<code>${esc(c.fix)}</code>` : ''}</td></tr>`;
    }).join('');
    setView(`<h2>▶ ${t('check.title')}</h2>
      <p class="muted">${t('check.why')}</p>
      ${env.data.ready ? `<div class="warn">✅ ${t('check.ready')}</div>`
        : `<div class="warn">${t('check.notready')}</div>`}
      <table><tbody>${rows}</tbody></table>
      ${sampleBlock(env.data)}`);
  },

  // 📖 Зразок — єдина дія на цьому екрані, що щось МІНЯЄ. Вона стоїть саме
  // тут, бо питання «чи воно працює» і відповідь «ось перевірте на трьох
  // аркушах» — одне питання, і розводити їх по різних екранах означало б
  // сховати відповідь від того, хто щойно поставив застосунок.
  'sample.install': async () => {
    busy();
    const env = await callOp('sample.install', {});
    if (!env.ok) return failure(env);
    const d = env.data;
    setView(`<h2>📖 ${t('check.sample.title')}</h2>
      <p>${esc(d.shifra)} — ${d.frames.length}/${d.frames_total}</p>
      <p class="muted">${esc(d.case_dir)}</p>
      <p class="muted">${t('check.sample.next')}</p>
      <p><button data-act="nav" data-arg="view">${t('nav.view')}</button></p>`);
  },
});
