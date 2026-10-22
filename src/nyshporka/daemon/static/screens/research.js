/**
 * 📝 Дослідження: звіти й нотатки роду з `reports/` проєкту.
 *
 * Пишуть їх агент і людина, лежать вони в теці проєкту, і досі їх було видно
 * лише у файлах. Тут — перелік із пошуком і читання у вікні. Прочитане
 * рушіями (`reports/htr`) сюди не входить: це не звіти, а мільйон рядків.
 */

import { t, tOr, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, modalSeq } from '../core/modal.js';
import { mdLite, dayOf } from '../core/bits.js';

/** Перелік з останньої відповіді — фільтр у браузері, без запиту на кожну літеру. */
let ROWS = [];
const RS = { q: '', kind: '' };

SCREENS.research = async () => {
  const gen = curGen();
  busy(6);
  const env = await callOp('reports.list', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  ROWS = (env.data || {}).rows || [];
  const kinds = [...new Set(ROWS.map((r) => r.kind).filter(Boolean))].sort();
  setView(`
    <p class="muted">${t('rs.why')}</p>
    <div class="row">
      <label class="fld"><span class="fld-l">${t('rs.find')}</span>
        <input id="rs-q" data-act="rs.find" data-live="1" value="${esc(RS.q)}"
          placeholder="${esc(t('rs.find.ph'))}"></label>
      <label class="fld"><span class="fld-l">${t('rs.kind')}</span>
        <select id="rs-kind" data-act="rs.find"><option value="">${t('canon.kind.all')}</option>
          ${kinds.map((k) => `<option value="${esc(k)}"${RS.kind === k ? ' selected' : ''}>${esc(kindLabel(k))}</option>`).join('')}
        </select></label>
    </div>
    <div class="dash-box" id="rs-list"></div>`);
  drawList();
};

/** Вид звіту — перша тека в `reports/`; знайомі назви — словами, решта як є. */
const kindLabel = (k) => tOr(`rs.k.${k}`, k);

/** Рядки під поточний фільтр: назва, шлях і вид — без урахування регістру. */
export function filterReports(rows, q, kind) {
  const n = String(q || '').trim().toLowerCase();
  return rows.filter((r) => (!kind || r.kind === kind)
    && (!n || `${r.title} ${r.path}`.toLowerCase().includes(n)));
}

function drawList() {
  const box = el('rs-list');
  if (!box) return;
  const rows = filterReports(ROWS, RS.q, RS.kind);
  box.innerHTML = rows.length ? rows.map((r) => `<div class="lrow">
      <div><b>${esc(r.title)}</b>
        <small class="muted mono">${esc(r.path)}</small>
        <small class="muted">${r.kind ? `<span class="tag">${esc(kindLabel(r.kind))}</span> ` : ''}${esc(dayOf(r.mtime, LANG))}</small></div>
      <button data-act="rs.read" data-arg="${esc(r.path)}">${t('rs.read')}</button></div>`).join('')
    : `<p class="muted">${ROWS.length ? t('rs.nomatch') : t('rs.none')}</p>`;
}

async function readReport(path) {
  openModal({ title: path, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('reports.read', { path });
  if (seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  el('dlg-body').innerHTML = `<div class="md">${mdLite(d.text)}</div>
    <p class="muted mono">reports/${esc(d.path || path)}</p>
    <div class="row dlg-acts"><button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

Object.assign(ACTIONS, {
  'rs.find': () => {
    RS.q = String((el('rs-q') || {}).value || '');
    RS.kind = String((el('rs-kind') || {}).value || '');
    drawList();
  },
  'rs.read': (_ev, elm) => readReport(elm.dataset.arg),
});
