/**
 * 📝 Дослідження: звіти й нотатки роду з `reports/` проєкту.
 *
 * Пишуть їх агент і людина, лежать вони в теці проєкту, і досі їх було видно
 * лише у файлах. Тут — перелік із пошуком і читання у вікні. Прочитане
 * рушіями (`reports/htr`) сюди не входить: це не звіти, а мільйон рядків.
 */

import { t, tOr, LANG } from '../core/strings.js';
import { callOp, staleThenFresh } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, curGen, alive, emptyMini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, modalSeq, modalTitle } from '../core/modal.js';
import { mdLite, dayOf, noEmoji } from '../core/bits.js';

/** Перелік з останньої відповіді — фільтр у браузері, без запиту на кожну літеру. */
let ROWS = [];
const RS = { q: '', kind: '' };

SCREENS.research = async () => {
  const gen = curGen();
  busy(6);
  // Перелік звітів — тисячі файлів; спершу минула відповідь, потім свіжа.
  await staleThenFresh('reports.list', {}, (env, _stale, again) => {
    if (!alive(gen)) return;
    paintResearch(env, again);
  });
};

function paintResearch(env, again = false) {
  if (!env.ok) return failure(env);
  ROWS = (env.data || {}).rows || [];
  // Найновіші зверху: «що ми робили останнім» — головне питання цього екрана.
  ROWS.sort((a, b) => Number(b.mtime || 0) - Number(a.mtime || 0));
  const count = {};
  ROWS.forEach((r) => { if (r.kind) count[r.kind] = (count[r.kind] || 0) + 1; });
  const kinds = Object.keys(count).sort((a, b) => count[b] - count[a]);
  setView(`
    <p class="muted">${t('rs.why')}</p>
    <div class="row">
      <label class="fld"><span class="fld-l">${t('rs.find')}</span>
        <input id="rs-q" data-act="rs.find" data-live="1" value="${esc(RS.q)}"
          placeholder="${esc(t('rs.find.ph'))}"></label>
      <label class="fld"><span class="fld-l">${t('rs.kind')}</span>
        <select id="rs-kind" data-act="rs.find"><option value="">${t('canon.kind.all')}</option>
          ${kinds.map((k) => `<option value="${esc(k)}"${RS.kind === k ? ' selected' : ''}>${esc(kindLabel(k))} · ${count[k]}</option>`).join('')}
        </select></label>
    </div>
    <div class="dash-box" id="rs-list"></div>`, again);
  drawList();
}

/** Вид звіту — перша тека в `reports/`; знайомі назви — словами, решта —
 *  ім'ям теки без підкреслень і з великої літери, а не `village_sweep`. */
const kindLabel = (k) => tOr(`rs.k.${k}`, '') || humanKind(k);
function humanKind(k) {
  const s = String(k || '').replace(/[_-]+/g, ' ').trim();
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/** Скільки рядків показано: тисячі звітів одним шматком гальмували екран. */
const PAGE = 60;

/** Рядки під поточний фільтр: назва, шлях і вид — без урахування регістру. */
export function filterReports(rows, q, kind) {
  const n = String(q || '').trim().toLowerCase();
  return rows.filter((r) => (!kind || r.kind === kind)
    && (!n || `${r.title} ${r.path}`.toLowerCase().includes(n)));
}

function drawList() {
  const box = el('rs-list');
  if (!box) return;
  const all = filterReports(ROWS, RS.q, RS.kind);
  const limit = RS.limit || PAGE;
  const rows = all.slice(0, limit);
  const more = all.length > rows.length
    ? `<p class="row"><button class="ghost" data-act="rs.more">${t('rs.more').replace('{n}', Math.min(PAGE, all.length - rows.length))}</button>
        <span class="muted">${t('rs.shown').replace('{n}', rows.length).replace('{all}', all.length)}</span></p>` : '';
  box.innerHTML = rows.length ? rows.map((r) => `<div class="lrow">
      <div><b>${esc(noEmoji(r.title))}</b>
        <small class="muted">${r.kind ? `<span class="tag">${esc(kindLabel(r.kind))}</span> ` : ''}${esc(dayOf(r.mtime, LANG))}</small></div>
      <button data-act="rs.read" data-arg="${esc(r.path)}">${t('rs.read')}</button></div>`).join('') + more
    : (ROWS.length ? `<p class="muted">${t('rs.nomatch')}</p>` : emptyMini('lupa', t('rs.none')));
}

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
  'rs.find': () => {
    RS.q = String((el('rs-q') || {}).value || '');
    RS.kind = String((el('rs-kind') || {}).value || '');
    RS.limit = PAGE;
    drawList();
  },
  'rs.more': () => {
    RS.limit = (RS.limit || PAGE) + PAGE;
    drawList();
  },
  'rs.read': (_ev, elm) => readReport(elm.dataset.arg),
});
