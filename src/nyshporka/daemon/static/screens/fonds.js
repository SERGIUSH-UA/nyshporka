/** 🏛 Реєстр опису фонду. */

import { t } from '../core/strings.js';
import { callOp, SEQ } from '../core/net.js';
import { esc, el, setView, busy, failure, busyForm,
  renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS, PAGERS } from '../core/registry.js';
import { show, goto, onJob, jobChip } from '../core/nav.js';
import { ST } from '../core/state.js';
import { ic } from '/ui/icons.js';
import { swapHtml, skelRows } from '/ui/dom.js';
import { pager, step } from '/ui/pager.js';
import { attachCombobox } from '/ui/combobox.js';

/**
 * Що зараз відкрито в описі. Живе між входами: повернувшись, людина бачить той
 * самий фонд, той самий фільтр і ту саму сторінку, а не порожню форму.
 */
let FD = { fond: '', opys: '', q: '', surname: '', year: '', uezd: '',
  state: '', flag: '', spr: '', page: 0, pages: 1 };

/**
 * 🏛 Фонди — реєстр опису: «що взагалі існує в архіві».
 *
 * 🔴 Це окреме сховище поруч із бібліотекою («що ми маємо») і приймальнею («що
 * лежить на диску нічим»). Плутати їх дорого: «справи немає» тут означає «в
 * архіві не існує», а в бібліотеці — «ще не завантажено». Два різні «немає»,
 * і на другому закривають напрям, якого ніхто не перевіряв.
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
  if (!FD.fond && fonds.length) FD.fond = fonds[0].id;

  // 🔴 Порожній стан — це пропозиція, а не діагноз. Тут стояли поспіль три
  // смуги: попередження операції «жодного реєстру опису немає», те саме
  // словами екрана, і згорнута форма під ними. Людина, яка щойно відкрила
  // застосунок, діставала два застереження про одне й те саме й жодної дії —
  // а єдине, що їй треба, це зібрати свій перший опис.
  const empty = !fonds.length;
  const notes = empty
    ? { ...env, warnings: (env.warnings || []).filter((w) => w.code !== 'no_registries') }
    : env;
  setView(`
    <h2>${t('nav.fonds')}</h2>
    ${empty ? `<p class="muted">${t('fonds.why')}</p>` : ''}
    ${renderWarnings(notes)}
    ${empty ? fondNone() : fondHead(fonds)}
    ${collectBlock(empty)}
    <div id="fondrows"></div>`);
  if (FD.fond && fonds.some((f) => f.id === FD.fond)) {
    attachFondPicker(fonds);
    await fondLoad(true);
  }
  // Збирачі тягнуться окремо й після: їхня відсутність (не поставлено extras)
  // не має права затримати показ самого реєстру.
  const col = await callOp('registry.collectors', {});
  if (!alive(gen)) return;
  const box = el('fd-collector');
  if (!box) return;
  const items = (col.ok && (col.data || {}).collectors) || [];
  // Довідка, а не вибір: збирання йде всіма готовими джерелами одразу, тож тут
  // лишається сказати, які вони, — щоб порожній результат можна було пояснити.
  box.textContent = items.length
    ? `${t('fonds.collect.have')}: ${items.map((c) => c.label).join(' · ')}`
    : t('fonds.collect.none');
};

/** Шапка екрана: пікер фонду, зведення, кнопка зведення джерел. */
function fondHead(fonds) {
  const cur = fonds.find((f) => f.id === FD.fond) || fonds[0] || {};
  return `<div class="row fond-head">
      <input id="fd-pick" size="30" value="${esc(fondLabel(cur))}"
        placeholder="${t('fonds.pick')}" autocomplete="off">
      <button data-act="fond.merge" title="${t('fonds.merge.why')}">
        ${t('fonds.merge')}</button>
    </div>
    <p id="fd-sum" class="muted">${fondSummary(cur.summary || {})}</p>
    <div id="fd-cov"></div>`;
}

/** Підпис фонду в пікері: назва плюс обсяг, бо вибирають саме за ним. */
function fondLabel(f) {
  return f && f.label ? `${f.label} — ${f.rows} ${t('fonds.cases')}` : '';
}

/**
 * Пікер фонду поверх звичайного поля.
 *
 * 🔴 Комбобокс надбудовується над `<input>`, а не замінює його: вибір диспатчить
 * справжні події, тож решта коду читає значення як зі звичайного поля. Саме
 * тому один віджет обслуговує і десять фондів, і тисячу.
 */
function attachFondPicker(fonds) {
  const input = el('fd-pick');
  if (!input) return;
  const byLabel = new Map(fonds.map((f) => [fondLabel(f), f.id]));
  attachCombobox(input, {
    items: [...byLabel.keys()],
    onPick: (v) => {
      const id = byLabel.get(v);
      if (!id || id === FD.fond) return;
      // Фільтри скидаються разом із фондом: описи й повіти в кожного свої, і
      // перенесений фільтр звузив би новий фонд до порожнечі без пояснення.
      FD = { ...FD, fond: id, opys: '', uezd: '', spr: '', page: 0 };
      show('fonds');
    },
  });
}

/**
 * Рядок метаданих фонду — сім чисел, кожне з яких є рішенням.
 *
 * 🔴 `summarize()` рахує вісімнадцять показників в одному проході, а наверх
 * ішли чотири. Через це екран не міг сказати ні скільки справ обрізає дзеркало,
 * ні скільки номерів відновлено між якорями, ні скільки справ узагалі має
 * прізвища — тобто мовчав саме про те, чим вирішують, куди дивитись далі.
 */
function fondSummary(s) {
  const bits = [
    [s.rows, t('fonds.sum.rows'), ''],
    [(s.commons || 0) + (s.mirror_only || 0), t('fonds.sum.scans'), t('fonds.sum.scans.why')],
    [s.on_disk_live, t('fonds.sum.disk'), t('fonds.sum.disk.why')],
    [s.todo, t('fonds.sum.todo'), t('fonds.sum.todo.why')],
    [s.truncated, t('fonds.sum.cut'), t('fonds.sum.cut.why')],
    [s.interp, t('fonds.sum.interp'), t('fonds.sum.interp.why')],
    [s.with_surnames, t('fonds.sum.surnames'), t('fonds.sum.surnames.why')],
  ];
  // Нуль не друкується: рядок і так довгий, а «0 обрізаних» — не новина.
  // Виняток — саме число справ: воно є завжди, бо це знаменник усього решти.
  return bits
    .filter(([n], i) => i === 0 || n)
    .map(([n, label, why]) => `<span title="${esc(why)}"><b>${esc(n || 0)}</b> ${label}</span>`)
    .join(' · ');
}

/**
 * Порожній реєстр описів — і що з цим робити.
 *
 * 🔴 Доти тут друкувався текст про паки довідників, яких `fond.list` не читає
 * взагалі: відповідь була не на те питання, і порада вела не туди.
 */
function fondNone() {
  return `<div class="warn"><b>${t('fonds.none')}</b>
    <p class="muted">${t('fonds.none.why')}</p></div>`;
}

/** Форма збирання розгорнута, коли збирати ще нічого не збирали. */
function collectOpen(empty) {
  return empty ? ' open' : '';
}

/**
 * 🧾 Зібрати опис фонду.
 *
 * 🔴 Чотири операції збирання існували від початку й не мали жодного входу з
 * екрана: зібрати опис можна було тільки командним рядком. Тобто екран, який
 * без реєстру порожній, не показував способу цей реєстр завести.
 */
function collectBlock(empty) {
  return `<details class="collect"${collectOpen(empty)}><summary>🧾 ${t('fonds.collect')}</summary>
    <p class="muted">${t('fonds.collect.why')}</p>
    <form class="row" data-act="fond.collect">
      <input name="repo" id="fd-repo" placeholder="${t('fonds.collect.repo')}" size="8">
      <input name="fond" id="fd-fond" placeholder="${t('fonds.collect.fond')}" size="6">
      <input name="opys" placeholder="${t('fonds.collect.opys')}" size="6">
      <input name="fond_id" placeholder="${t('fonds.collect.fondid')}" size="10"
        title="${t('fonds.collect.fondid.why')}">
      <button type="submit">${t('fonds.collect.plan')}</button>
    </form>
    <p class="muted" id="fd-collector"></p>
    <div id="fd-collect"></div></details>`;
}

/**
 * Покриття фонду по описах — межа знання про фонд.
 *
 * 🔴 Числами, а не відсотком. Відсоток ховає те, ЩО саме невідомо: «98%»
 * читається як «майже все», тоді як 144 непокритих одиниці зберігання — це
 * конкретні книги, яких ми не бачимо. Δ до путівника архіву і є тією межею.
 *
 * ⚠ Немає файла покриття — кажемо «не рахувалось», а не показуємо нулі: нуль
 * тут читався б як «фонд не покрито», чого ніхто не міряв.
 */
function coverageBlock(cov) {
  if (!cov) return `<p class="muted">${t('fonds.cov.none')}</p>`;
  const tot = cov._total || {};
  const rows = Object.keys(cov)
    .filter((k) => k !== '_total')
    .sort((a, b) => Number(a) - Number(b))
    .map((k) => {
      const c = cov[k] || {};
      const pct = c.last_number
        ? Math.round((c.present || 0) * 100 / c.last_number) : null;
      return `<tr><td class="mono">${t('fonds.cov.opys')} ${esc(k)}</td>
        <td class="num">${esc(c.last_number ?? '')}</td>
        <td class="num">${esc(c.present ?? '')}</td>
        <td class="num">${esc(c.letter_families ?? 0)} / ${esc(c.letter_rows ?? 0)}</td>
        <td class="num">${esc(c.absent ?? '')}</td>
        <td class="num">${pct === null ? '—' : `${pct}%`}</td></tr>`;
    }).join('');
  const delta = (tot.guide_total || 0) - (tot.computed_units || 0);
  return `<table class="cov"><thead><tr>
      <th>${t('fonds.cov.opys')}</th><th class="num">${t('fonds.cov.last')}</th>
      <th class="num">${t('fonds.cov.present')}</th>
      <th class="num">${t('fonds.cov.letters')}</th>
      <th class="num">${t('fonds.cov.absent')}</th><th class="num">%</th>
    </tr></thead><tbody>${rows}</tbody></table>
    <p class="mono muted">Σ ${esc(tot.sum_last_number ?? 0)}
      − ${esc(tot.absent ?? 0)} + ${esc(tot.letter_rows ?? 0)}
      = <b>${esc(tot.computed_units ?? 0)}</b></p>
    ${tot.guide_total ? `<p class="mono">${t('fonds.cov.guide')}
      ${esc(tot.guide_total)} → <b class="warn-inline">Δ ${esc(delta)}</b>
      ${t('fonds.cov.delta')}</p>` : ''}`;
}

/**
 * Рядки опису обраного фонду.
 *
 * `full=false` — міняються лише самі рядки, лічильник і пейджер. Повне
 * перемальовування вбиває фокус у полі фільтра, а фільтрують саме набором.
 */
async function fondLoad(full = false) {
  const seq = ++SEQ.fond;
  const box = el('fondrows');
  if (!box) return;
  if (full) swapHtml(box, skelRows(8, 9));
  const env = await callOp('fond.rows', {
    fond: FD.fond, opys: FD.opys, q: FD.q, surname: FD.surname, year: FD.year,
    uezd: FD.uezd, state: FD.state, spr: FD.spr, page: FD.page, page_size: 50,
  });
  if (seq !== SEQ.fond) return;
  if (!env.ok) {
    box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
    return;
  }
  const d = env.data;
  FD.pages = d.pages || 1;
  const bySurname = !!FD.surname;
  const body = `${renderWarnings(env)}
    <p class="muted">${sprChip()}${t('fonds.matched')} <b>${esc(d.matched)}</b>
      ${t('fonds.of')} <b>${esc((d.summary || {}).rows)}</b></p>
    ${(d.rows || []).length ? `<div class="tbl-wide"><table><thead><tr>
      <th>${t('fonds.col.shifra')}</th><th>${t('fonds.col.title')}</th>
      <th>${t('fonds.col.years')}</th><th class="num">${t('fonds.col.folios')}</th>
      <th class="num">${t('fonds.col.dv')}</th><th>${t('fonds.col.scan')}</th>
      <th>${t('fonds.col.disk')}</th>
      <th class="num" title="${t('fonds.col.conf.why')}">${t('fonds.col.conf')}</th>
      <th></th></tr></thead><tbody>
    ${d.rows.map((r) => fondRow(r, bySurname)).join('')}
    </tbody></table></div>${pager(d)}` : ''}`;

  if (full) {
    swapHtml(box, `${fondForm(d)}<div id="fd-body">${body}</div>`);
    attachSurnames(d);
    const cov = el('fd-cov');
    if (cov) {
      cov.innerHTML = `<details><summary>${t('fonds.cov.title')}</summary>
        ${coverageBlock(d.coverage)}</details>`;
    }
    const sum = el('fd-sum');
    if (sum) sum.innerHTML = fondSummary(d.summary || {});
  } else {
    swapHtml(el('fd-body'), body);
  }
}

/**
 * Фільтри рядків опису. Стоять над видачею, бо звужують саме її.
 *
 * 🔴 Описи й повіти приходять фасетами з лічильниками, а не вписуються руками:
 * перелік і є мапою фонду, а число за кожним пунктом — відповіддю на «чи варто
 * туди дивитись».
 */
function fondForm(d) {
  const sel = (id, cur, opts, extra = '') =>
    `<select id="${id}"${extra}>${opts.map(([v, label]) =>
      `<option value="${esc(v)}"${cur === v ? ' selected' : ''}>${esc(label)}</option>`)
      .join('')}</select>`;
  const facets = d.facets || {};
  const opysOpts = [['', t('fonds.f.opys.any')]].concat(
    (facets.opys || []).map((o) => [o.code, `${t('fonds.cov.opys')} ${o.code} (${o.n})`]));
  const uezdOpts = [['', t('fonds.f.uezd.any')]].concat(
    (facets.uezd || []).map((o) => [o.code, `${o.code} (${o.n})`]));
  // Стара схема реєстру не знає ні станів, ні позначок — вимикаємо з
  // поясненням замість того, щоб пропонувати фільтр, який нічого не звузить.
  const old = d.schema && d.schema !== 'merged_v2';
  const off = old ? ` disabled title="${esc(t('fonds.f.old'))}"` : '';
  return `<form class="row" data-act="fond.filter">
      ${sel('fd-opys', FD.opys, opysOpts)}
      <input type="search" id="fd-q" data-act="fond.filter" data-live="1"
        placeholder="${t('fonds.filter')}" value="${esc(FD.q)}">
      <input id="fd-surname" size="16" autocomplete="off"
        placeholder="${t('fonds.surname')}" value="${esc(FD.surname)}">
      <input id="fd-year" size="10" placeholder="${t('fonds.f.year')}"
        value="${esc(FD.year)}">
      ${sel('fd-uezd', FD.uezd, uezdOpts)}
      ${sel('fd-state', FD.state, [
    ['', t('fonds.state.any')], ['disk', t('fonds.state.disk')],
    ['todo', t('fonds.state.todo')], ['film', t('fonds.state.film')],
    ['order', t('fonds.state.order')]], off)}
      ${sel('fd-flag', FD.flag, [
    ['', t('fonds.f.flag.any')], ['partial', t('fonds.f.flag.partial')],
    ['interp', t('fonds.f.flag.interp')], ['truncated', t('fonds.f.flag.truncated')],
    ['lo', t('fonds.f.flag.lo')], ['title_conflict', t('fonds.f.flag.conflict')],
    ['no_title', t('fonds.f.flag.notitle')]], off)}
      <button type="submit">${t('geog.find')}</button>
    </form>`;
}

/** Підказки прізвищ з алфавітки архіву — або чесне «її немає». */
function attachSurnames(d) {
  const input = el('fd-surname');
  if (!input) return;
  const items = d.surnames || [];
  if (!items.length) {
    // 🔴 Вимикаємо З поясненням. Поле, яке приймає введення й завжди віддає
    // нуль, читається як «такого прізвища у фонді немає» — тобто як відповідь
    // про рід, тоді як це відповідь про наявність алфавітки.
    input.disabled = true;
    input.title = t('fonds.surname.none');
    return;
  }
  attachCombobox(input, { items, limit: 60, empty: t('fonds.surname.miss') });
}

/**
 * Картка справи: поле — значення, і звідки воно взялось.
 *
 * ⚠ Порожні поля не друкуються. У реєстрі п'ятдесят дві колонки, і більшість
 * із них для конкретної справи порожні; надрукувати всі означає сховати ті
 * шість, які щось означають.
 */
function cardHtml(env) {
  const d = env.data || {};
  const r = d.row || {};
  const st = d.status || {};
  const rows = [
    [t('fonds.card.title'), r.title, r.title_src],
    [t('fonds.card.alt'), r.title_alt, ''],
    [t('fonds.card.commons_title'), r.commons_title, ''],
    [t('fonds.card.years'), r.year_from ? `${r.year_from}–${r.year_to}` : '', r.years_src],
    [t('fonds.card.folios'), r.folios, r.folios_src],
    [t('fonds.card.dv'), r.dv_no, ''],
    [t('fonds.card.surnames'), r.surnames, ''],
    [t('fonds.card.place'), r.cat_place || r.cover_place, ''],
    [t('fonds.card.uezd'), r.cat_uezd, ''],
    [t('fonds.card.types'), r.record_types, ''],
    [t('fonds.card.commons'), r.commons_url, ''],
    [t('fonds.card.archium'), r.archium_url, ''],
    [t('fonds.card.mirror'), r.mirror_url, ''],
    [t('fonds.card.film'), r.fs_film || r.fs_dgs,
      [r.fs_frames ? `${r.fs_frames} ${t('fonds.scan.frames')}` : '',
        r.fs_place, r.fs_record_type].filter(Boolean).join(' · ')],
    [t('fonds.card.film.url'), r.fs_url, ''],
    [t('fonds.card.disk'), st.on_disk_live, ''],
    [t('fonds.card.frames'), st.frames_disk && d.expected_frames
      ? `${st.frames_disk} / ${d.expected_frames}` : '', ''],
    [t('fonds.card.num'), r.num_src === 'interp' ? t('fonds.card.num.interp') : '',
      r.src_page ? `${t('fonds.num.page')} ${r.src_page}` : ''],
    [t('fonds.card.sources'), r.sources, ''],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');
  const flags = (st.flags || []).length
    ? `<p class="muted">${t('fonds.card.flags')}: ${(st.flags || []).join(' · ')}</p>` : '';
  return `<div class="case-card">
    ${renderWarnings(env)}
    <table class="kv">${rows.map(([k, v, src]) => `<tr>
      <th>${esc(k)}</th><td>${esc(String(v))}
      ${src ? `<span class="muted">(${esc(String(src))})</span>` : ''}</td>
    </tr>`).join('')}</table>
    ${flags}
    <p class="muted mono">${t('fonds.card.registry')}: ${esc(d.registry || '')}</p>
  </div>`;
}

/**
 * Чип точкового засіву: коли екран звужено до однієї справи.
 *
 * 🔴 Перехід із бібліотеки ставить номер справи у фільтр — і показує один
 * рядок. Без видимої позначки це читається як «у фонді одна справа».
 */
function sprChip() {
  if (!FD.spr) return '';
  return `<button class="ctl-sm" data-act="fond.allspr">
    ${t('fonds.spr')} ${esc(FD.spr)} ✕</button> `;
}

/** Розмір людськими одиницями: ГБ від гігабайта, інакше цілі МБ. */
function size(bytes) {
  const n = Number(bytes || 0);
  if (!n) return '';
  const mb = n / 1048576;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} ГБ` : `${Math.round(mb)} МБ`;
}

/**
 * Звідки брати скан і чого це коштуватиме.
 *
 * 🔴 Розмір тут не прикраса: 25 МБ проти 771 МБ на тій самій справі означає, що
 * дзеркало її ріже, і ніч завантаження піде намарно. Тому ✂ фарбується й несе
 * пояснення в підказці.
 */
function scanCell(r) {
  const bits = [];
  if (r.archium_url) bits.push(`<b title="${t('fonds.scan.archium')}">A</b>`);
  if (r.commons_url) {
    const parts = [size(r.commons_size), r.commons_pages
      ? `${esc(r.commons_pages)} ${t('fonds.scan.pages')}` : ''].filter(Boolean);
    bits.push(`C${parts.length ? ` ${parts.join(' · ')}` : ''}`);
    if (Number(r.commons_files || 0) > 1) {
      bits.push(`<b title="${t('fonds.scan.files')}">${esc(r.commons_files)} т.</b>`);
    }
  } else if (r.mirror_size) {
    bits.push(`${t('fonds.scan.mirror')} ${size(r.mirror_size)}`);
  }
  if (r.truncated_mirror) {
    bits.push(`<span class="cut" title="${t('fonds.scan.cut')}">${ic('scissors', 'ic-o ic-sm')}</span>`);
  }
  // 🔴 Плівка FamilySearch — третій канал, і для частини справ єдиний: на
  // Commons їх немає, у переглядачі архіву теж, а плівка оцифрована й лежить.
  // Доти наверх ішов самий номер, тобто його можна було прочитати й не можна
  // було ним скористатись.
  if (r.fs_film || r.fs_dgs) {
    const label = `FS ${esc(r.fs_film || r.fs_dgs)}`;
    const frames = r.fs_frames ? ` · ${esc(r.fs_frames)} ${t('fonds.scan.frames')}` : '';
    const why = [r.fs_place, r.fs_record_type].filter(Boolean).join(' · ');
    bits.push(r.fs_url
      ? `<a href="${esc(r.fs_url)}" target="_blank" rel="noopener"
           title="${esc(why || t('fonds.scan.film'))}">${label}</a>${frames}`
      : `<span title="${esc(why || t('fonds.scan.film.nourl'))}">${label}</span>${frames}`);
  }
  // ⚠ `null` у розмірах означає «схема цього фонду про скани не знає» — це не
  // те саме, що «сканів немає», і прочерк тут із поясненням.
  if (!bits.length) {
    const unknown = r.commons_size === null && r.mirror_size === null;
    return `<span class="muted"${unknown ? ` title="${t('fonds.scan.unknown')}"` : ''}>—</span>`;
  }
  return bits.join(' ');
}

/** Стан на диску — і чи можна вірити реєстру про нього. */
function diskCell(r) {
  // ⚠ Значки зі спрайта, не емодзі: емодзі малюються шрифтом системи, тобто
  // різного розміру й кольору на кожній машині, і в колонці на 24 пікселі це
  // виглядає плямою. Спрайт бере `currentColor` і той самий кегль, що текст.
  const marks = { disk: 'check', todo: 'target', order: 'archive-box' };
  const name = r.on_disk ? 'check' : marks[r.state];
  const mark = name ? ic(name, 'ic-o ic-sm') : '<span class="muted">—</span>';
  const frames = r.frames_disk && r.frames_expected
    ? ` <span class="muted mono">${esc(r.frames_disk)}/${esc(r.frames_expected)}</span>` : '';
  // 🔴 Розходження порядково: число у зведенні каже «17 справ», але не каже,
  // котрим саме не вірити.
  const bad = r.disk_mismatch
    ? ` <span class="mism" title="${t('fonds.disk.mismatch')}">⚠</span>` : '';
  return `<span title="${esc(r.on_disk || r.state || '')}">${mark}</span>${frames}${bad}`;
}

/**
 * Назва справи — і чому саме ця.
 *
 * 🔴 Коли фільтрують за прізвищем, показуються прізвища, а не заголовок:
 * алфавітка архіву надійніша за OCR опису, а в багатьох справах заголовка
 * немає взагалі.
 */
function titleCell(r, bySurname) {
  const head = (bySurname && r.surnames) || r.title || r.surnames || '';
  const extra = [];
  if (r.title_alt) extra.push(`${t('fonds.title.alt')}: ${esc(r.title_alt)}`);
  if (r.commons_title && r.commons_title !== r.title) {
    extra.push(`Commons: ${esc(r.commons_title)}`);
  }
  const main = esc(String(head).slice(0, 120))
    || `<span class="muted">${t('fonds.title.none')}</span>`;
  return `${main}${extra.length ? `<div class="muted">${extra.join(' · ')}</div>` : ''}`;
}

/** Шифра з позначками надійності самого номера. */
function shifraCell(r) {
  const bits = [`<span class="mono">${esc(r.shifra)}</span>`];
  if (r.num_src === 'interp') {
    const page = r.src_page ? ` ${t('fonds.num.page')} ${esc(r.src_page)}` : '';
    bits.push(`<span title="${t('fonds.num.interp')}${page}">🔴</span>`);
  }
  if (r.page_quality === 'lo') {
    bits.push(`<span title="${t('fonds.num.lo')}">⚠</span>`);
  }
  return bits.join(' ');
}

/**
 * Один рядок опису — і що з ним можна зробити.
 *
 * 🔴 Доти рядок був тупиком: жодної кнопки. Людина бачила «скан є, не взято» —
 * і не мала чим узяти; бачила «у нас на диску» — і не мала чим відкрити.
 */
function fondRow(r, bySurname) {
  // 🔴 Картка є завжди, решта — за станом справи. Рядок показує сім полів із
  // п'ятдесяти двох, тож без картки він є твердженням без доказу: звідки взято
  // заголовок, чому номер вважається відновленим, із чого складається скан —
  // усе це видно лише в ній.
  // ⚠ Номер і літера йдуть окремо: реєстр шукає рядок за парою, а склеєне
  // «40е» не збігається ні з «40», ні з чим іншим — картка просто не
  // відкривалась, і то саме на літерних томах, тобто на цілих серіях.
  const acts = [`<button class="ctl-sm" data-act="fond.card"
    data-arg="${esc(`${r.opys}|${r.spr_int || r.spr}|${r.spr_letter || ''}`)}"
    title="${t('fonds.act.card')}">${ic('note', 'ic-o ic-sm')}</button>`];
  if (!r.on_disk && r.takeable) {
    acts.push(`<button class="ctl-sm" data-act="fond.take" data-arg="${esc(r.key)}"
      title="${t('fonds.act.take')}">${ic('download', 'ic-o ic-sm')}</button>`);
  }
  if (r.on_disk) {
    acts.push(`<button class="ctl-sm" data-act="fond.view" data-arg="${esc(r.key)}"
      title="${t('fonds.act.view')}">${ic('eye', 'ic-o ic-sm')}</button>`);
    acts.push(`<button class="ctl-sm" data-act="fond.lib" data-arg="${esc(r.key)}"
      title="${t('fonds.act.lib')}">${ic('books', 'ic-o ic-sm')}</button>`);
  }
  const url = r.archium_url || r.commons_url;
  if (url) {
    acts.push(`<a class="ctl-sm" href="${esc(url)}" target="_blank" rel="noopener"
      title="${t('fonds.act.ext')}">${ic('link', 'ic-o ic-sm')}</a>`);
  }
  const dv = (r.dv_no === null || r.dv_no === undefined || r.dv_no === '')
    ? `<span class="muted">—</span>` : esc(r.dv_no);
  return `<tr>
    <td>${shifraCell(r)}</td>
    <td>${titleCell(r, bySurname)}</td>
    <td class="mono">${r.year_from ? `${esc(r.year_from)}–${esc(r.year_to)}` : ''}</td>
    <td class="num">${esc(r.folios || '')}</td>
    <td class="num">${dv}</td>
    <td>${scanCell(r)}</td>
    <td class="disk-cell">${diskCell(r)}</td>
    <td class="num">${r.conflicts ? esc(r.conflicts) : ''}</td>
    <td class="acts">${acts.join(' ')}</td>
  </tr>`;
}

/**
 * Показати стан роботи в заданому вузлі.
 *
 * ⚠ Після успіху екран перечитується сам: збирання й зведення міняють те, на
 * що людина дивиться (числа фонду, покриття, самі рядки), і лишити старий
 * знімок означає показувати застаріле як поточне.
 */
function watchHere(box, jobId, done) {
  if (!box) return;
  if (!jobId) {                       // операція виявилась миттєвою
    if (done) done();
    return;
  }
  box.innerHTML = jobChip({ state: 'queued', progress: {} });
  onJob(jobId, (j) => {
    box.innerHTML = jobChip(j);
    if (j.state === 'done' && done) done();
  });
}

PAGERS.fonds = (delta) => {
  FD.page = step(FD.page, delta, FD.pages);
  return fondLoad();
};

Object.assign(ACTIONS, {
  /**
   * Фільтр читає поля ЗА ID, а не з `FormData`.
   *
   * 🔴 Дію кличуть з двох боків: `submit` форми і живе поле пошуку (`data-live`).
   * У другому випадку `ev.target` — саме поле, і зібраний із нього `FormData`
   * мовчки віддав би порожнечу, тобто фільтр скидався б замість звуження.
   * Той самий патерн у бібліотеці (`lib.filter`), і не випадково.
   */
  'fond.filter': (ev) => {
    if (ev && ev.preventDefault) ev.preventDefault();
    const val = (id) => (el(id) || {}).value || '';
    FD = { ...FD, opys: val('fd-opys'), q: val('fd-q'),
      surname: val('fd-surname'), year: val('fd-year'),
      uezd: val('fd-uezd'), state: val('fd-state'),
      flag: val('fd-flag'), page: 0 };
    return fondLoad();
  },

  /** Зняти точковий засів — показати весь фонд. */
  'fond.allspr': () => {
    FD = { ...FD, spr: '', page: 0 };
    return fondLoad();
  },

  /** 📚 Ця сама справа в бібліотеці — за спільним ключем, а не пошуком. */
  'fond.lib': (_ev, elm) => goto('library', { key: elm.dataset.arg }),

  /**
   * 👁 Погортати аркуші справи.
   *
   * Кнопка стоїть лише в тих рядках, де справа вже на диску: гортати те, чого
   * не завантажено, нема чим, і кнопка, яка відкриває порожнечу, гірша за
   * відсутню.
   */
  'fond.view': (_ev, elm) => goto('frames', { case: elm.dataset.arg }),

  /**
   * ℹ Картка справи — усе, що про неї знає реєстр.
   *
   * 🔴 Розгортається під рядком, а не в діалозі: діалог ховає таблицю, а
   * картку читають, звіряючи з сусідніми рядками — саме так помічають, що
   * номер відновлено не в одній справі, а в цілому шматку опису.
   */
  'fond.card': async (_ev, elm) => {
    const [opys, spr, letter] = (elm.dataset.arg || '').split('|');
    const tr = elm.closest('tr');
    if (!tr) return undefined;
    const open = tr.nextElementSibling;
    if (open && open.classList.contains('card-row')) {
      open.remove();                       // повторний клік згортає
      return undefined;
    }
    const env = await callOp('fond.case',
      { fond: FD.fond, opys, spr, letter: letter || '' });
    const html = env.ok ? cardHtml(env) : `<div class="warn err">${esc(env.error)}</div>`;
    tr.insertAdjacentHTML('afterend',
      `<tr class="card-row"><td colspan="9">${html}</td></tr>`);
    return undefined;
  },

  /**
   * ⬇ Узяти справу в роботу.
   *
   * 🔴 Робота довга й іде в чергу — туди ж і ведемо. Кнопка, після якої нічого
   * видимо не сталось, натискається вдруге, а вдруге тут означає другу
   * закачку тієї самої справи.
   */
  /**
   * ⬇ Узяти справу в роботу — і показати це В рядку.
   *
   * 🔴 Доти кнопка викидала на вкладку «Роботи». Людина натискала її, дивлячись
   * на конкретний рядок опису, і опинялась у переліку, де той рядок ніяк не
   * названо; повернутись до свого фільтра теж було нічим. Тепер стан пише
   * сама клітинка «диск», а перелік робіт лишається тим, хто справді пішов
   * дивитись чергу.
   */
  'fond.take': async (_ev, elm) => {
    const cell = elm.closest('tr') && elm.closest('tr').querySelector('.disk-cell');
    const env = await callOp('fond.take', { key: elm.dataset.arg });
    if (!env.ok) {
      if (cell) cell.innerHTML = `<span class="warn-inline">${esc(env.error)}</span>`;
      return undefined;
    }
    elm.disabled = true;                    // друге натискання = друга закачка
    const id = (env.data || {}).job_id;
    if (cell) cell.innerHTML = jobChip({ state: 'queued', progress: {} });
    onJob(id, (j) => {
      if (cell) cell.innerHTML = jobChip(j);
      // Робота скінчилась успіхом — рядок більше не той, що був: справа тепер
      // на диску. Перечитуємо саме рядки, не весь екран.
      if (j.state === 'done') fondLoad();
    });
    return undefined;
  },

  'fond.collect': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const unlock = busyForm(ev.target);
    // ⚠ `fond_id` потрібен рівно одному збирачеві: сайт архіву адресує
    // фонд власним внутрішнім номером, не пов'язаним з архівним
    // (ф.224 значиться там фондом 198). Без нього ARCHIUM пропускається
    // з поясненням, решта джерел збирається як звичайно.
    // 🔴 Збирача не питаємо. Який саме сайт віддав рядок — наша механіка, а не
    // рішення дослідника: відповідь «котрий із них знає цей фонд» знає план, і
    // питати про неї треба не людину. `registry.build` обходить усі готові
    // джерела, неготові пропускає з поясненням і зводить реєстр один раз.
    const env = await callOp('registry.build', {
      repo: f.get('repo') || '', fond: f.get('fond') || '',
      opys: f.get('opys') || '', fond_id: f.get('fond_id') || '',
    });
    unlock();
    const box = el('fd-collect');
    if (!env.ok) {
      if (box) box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return undefined;
    }
    watchHere(box, (env.data || {}).job_id, () => show('fonds'));
    return undefined;
  },

  /**
   * 🔄 Звести джерела в реєстр.
   *
   * Потрібне окремо від збирання: файли джерел могли лягти раніше (іншою
   * машиною, руками), і гнати заради них повний обхід сайтів — марна ніч.
   */
  'fond.merge': async () => {
    const [repo, fond] = (FD.fond || '').split('_');
    const env = await callOp('registry.merge',
      { repo: repo || '', fond: fond || '' });
    const box = el('fd-cov');
    if (!env.ok) {
      if (box) box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return undefined;
    }
    watchHere(box, (env.data || {}).job_id, () => show('fonds'));
    return undefined;
  },
});
