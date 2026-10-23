/**
 * 📝 Дослідження: звіти й нотатки роду з `reports/` проєкту.
 *
 * Пишуть їх агент і людина, лежать вони в теці проєкту, і досі їх було видно
 * лише у файлах. Тут — перелік із пошуком і читання у вікні. Прочитане
 * рушіями (`reports/htr`) сюди не входить: це не звіти, а мільйон рядків.
 *
 * Звітів буває кілька тисяч (у великому дослідженні — 4720), тож перелік спільний (`listView`):
 * групи за текою, найсвіжіша тека вгорі, плитки «за тиждень / за місяць».
 * Доти це був один стовпчик по 60 і випадний перелік видів.
 */

import { t, tOr, tn, LANG } from '../core/strings.js';
import { callOp, staleThenFresh } from '../core/net.js';
import { listView } from '../core/listview.js';
import { esc, el, setView, busy, failure, boxError, curGen, alive, emptyMini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, modalSeq, modalTitle } from '../core/modal.js';
import { mdLite, dayOf, noEmoji } from '../core/bits.js';

SCREENS.research = async () => {
  const gen = curGen();
  busy(6);
  // Перелік звітів — тисячі файлів; спершу минула відповідь, потім свіжа.
  await staleThenFresh('reports.list', {}, (env, _stale, again) => {
    if (!alive(gen)) return;
    paintResearch(env, again);
  });
};

const DAY = 86400;

/** «Свіже» — за останні `days` днів від `now` (секунди, як `mtime`). */
const freshWithin =(days, now = Date.now() / 1000) => (r) => now - Number(r.mtime || 0) <= days * DAY;

function paintResearch(env, again = false) {
  if (!env.ok) return failure(env);
  const rows = [...((env.data || {}).rows || [])];
  // Найновіші зверху: «що ми робили останнім» — головне питання цього екрана.
  rows.sort((a, b) => Number(b.mtime || 0) - Number(a.mtime || 0));
  setView(`<p class="muted">${t('rs.why')}</p>
    ${rows.length ? '<div id="rs-list"></div>' : `<div class="dash-box">${emptyMini('sviy', t('rs.none'))}</div>`}`, again);
  if (!rows.length) return;
  listView(el('rs-list'), {
    id: 'research',
    rows,
    key: (r) => r.path,
    text: (r) => `${r.title} ${r.path}`,
    placeholder: t('rs.find.ph'),
    chips: [
      { id: 'week', label: t('rs.lv.week'), test: freshWithin(7), tone: 'ok' },
      { id: 'month', label: t('rs.lv.month'), test: freshWithin(30) },
    ],
    // Теки одного архіву (`davo`, `davio`) — однією групою під його скороченням.
    group: (r) => (r.archive ? { id: `a:${r.archive}`, label: r.archive }
      : { id: r.kind || '', label: r.kind ? capFirst(kindLabel(r.kind)) : t('rs.lv.loose') }),
    // Тека зі свіжішим звітом — вище: рядки вже йдуть від нових, тож перший
    // рядок групи і є її найсвіжіший.
    groupSort: (a, b) => Number(b.rows[0].mtime || 0) - Number(a.rows[0].mtime || 0),
    groupSummary: (g) => esc(t('rs.lv.gsum').replace('{cnt}', tn('lv.n.reports', g.length))
      .replace('{d}', dayOf(g[0].mtime, LANG))),
    head: `<th>${t('rs.lv.report')}</th><th>${t('rs.lv.when')}</th><th></th>`,
    cells: (r) => `<td><b>${esc(noEmoji(r.title || r.path))}</b><br><small class="muted mono">${esc(r.path)}</small></td>
      <td class="lv-nw">${esc(dayOf(r.mtime, LANG))}</td>
      <td class="lv-nw"><button data-act="rs.read" data-arg="${esc(r.path)}">${t('rs.read')}</button></td>`,
  });
}

/** Вид звіту — перша тека в `reports/`; знайомі назви — словами, решта —
 *  ім'ям теки без підкреслень і з великої літери, а не `village_sweep`. */
const kindLabel = (k) => tOr(`rs.k.${k}`, '') || humanKind(k);
const capFirst = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const humanKind = (k) => capFirst(String(k || '').replace(/[_-]+/g, ' ').trim());

async function readReport(path) {
  openModal({ title: path, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('reports.read', { path });
  if (seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  // Назва звіту, а не шлях до файла: шлях людині нічого не каже.
  if (d.title) modalTitle(d.title);
  el('dlg-body').innerHTML = `<div class="md">${mdLite(d.text, d.refs || {})}</div>
    <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

Object.assign(ACTIONS, {
  'rs.read': (_ev, elm) => readReport(elm.dataset.arg),
});
