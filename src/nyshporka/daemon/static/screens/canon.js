/**
 * 📚 Канон роду: перевірка, «що вирішити», картки й докази.
 *
 * 🔴 Консоль канон показує й перевіряє, але не править: картки веде агент або
 * людина у файлі (рішення дослідника, хвиля 6). Тож тут немає жодної кнопки
 * «змінити поле». Картку тут не пише ніщо: доказ іде в стор (`evidence.js`) і
 * закінчується дорученням агентові. Два записи все ж є, і обидва — в історію,
 * не в картку: зелена перевірка сама зберігає стан (автозбереження з 5г), а
 * «Повернути» на екрані «Історія» відновлює файл попередньою версією.
 */

import { t, tOr, tn, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, boxError, renderWarnings, curGen, alive, emptyMini } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto } from '../core/nav.js';
import { openModal, modalSeq, modalTitle } from '../core/modal.js';
import { kv, pill, toast, unwiki, fieldLabel, fieldValue, named, fmtDay, HYP_TONE, decRow } from '../core/bits.js';
import { openEvidence } from './evidence.js';

const KINDS = ['persons', 'families', 'places', 'sources', 'hypotheses'];

/** Пошук і кошик живуть між перемальовками екрана. */
const CN = { q: '', kind: '' };

SCREENS.canon = async () => {
  const gen = curGen();
  // Перевірка канону й «що вирішити» — секунда-півтори (обхід карток і
  // доказів), а пошук і перелік карток від них не залежать: каркас одразу,
  // ці два блоки — скелетоном і домальовуються (замір 23.10.2026).
  const chkP = callOp('canon.check', {});
  const nxtP = callOp('canon.next', { limit: 3 });
  const skel = '<div class="skel skel-card"></div>';
  setView(`
    <p class="muted">${t('canon.why')}</p>
    <div class="dash-two">
      <div class="dash-box" id="cn-check">${skel}</div>
      <div class="dash-box" id="cn-next">${skel}</div>
    </div>
    <div class="dash-box">
      <div class="row">
        <label class="fld"><span class="fld-l">${t('canon.find')}</span>
          <input id="cn-q" data-act="canon.find" data-live="1" value="${esc(CN.q)}"
            placeholder="${esc(t('canon.find.ph'))}"></label>
        <label class="fld"><span class="fld-l">${t('canon.kind')}</span>
          <select id="cn-kind" data-act="canon.find">
            <option value="">${t('canon.kind.all')}</option>
            ${KINDS.map((k) => `<option value="${k}"${CN.kind === k ? ' selected' : ''}>${
    esc(t(`canon.kind.${k}`))}</option>`).join('')}
          </select></label>
      </div>
      <div id="cn-list"><p class="muted">${t('load.cards')}</p></div>
    </div>`);
  // Прийшли з позначки «уже в каноні» іншого проєкту (`?card=`): одразу
  // картка. Параметр знімається — інакше вона відкривалась би на кожному вході.
  const q = new URLSearchParams(location.search);
  const card = q.get('card');
  if (card) {
    q.delete('card');
    history.replaceState(null, '', `${location.pathname}?${q.toString()}${location.hash}`);
    openCard(card);
  }
  const boxes = Promise.all([chkP, nxtP]).then(([chk, nxt]) => {
    if (!alive(gen)) return;
    const c = el('cn-check');
    const n = el('cn-next');
    if (c) { if (chk.ok) c.innerHTML = checkBox(chk); else boxError('cn-check', chk); }
    if (n) n.innerHTML = nextBox(nxt);
  });
  await Promise.all([cardsList(), boxes]);
};

/** Вид знахідки перевірки → мітка ліворуч від неї. Невідомий код — «інше». */
const ISSUE_KIND = {
  both_levels: 'family', one_sided: 'link', missing_ref: 'link', orphan: 'link',
  chronology: 'dates', conflict: 'dup', duplicate_fact: 'dup', duplicate_id: 'dup',
  maybe_living: 'living', uncited: 'proof', weak_confirmed: 'proof', evidence_missing: 'proof',
  not_a_path: 'proof', manifest: 'proof', manifest_missing: 'proof', manifest_hash: 'proof',
  hypothetical_unlinked: 'hyp', disputed_unlinked: 'hyp', wikilink: 'ref', sex: 'sex',
  schema: 'file', unreadable: 'file', file_name: 'file', regions: 'file',
};
const issueKind = (code) => ISSUE_KIND[code] || (String(code).startsWith('hyp_') ? 'hyp' : 'other');

/** Перші знахідки, які показує картка; решта — числом «і ще N». */
const SHOW_ISSUES = 5;

/**
 * 🔴 Мітка стану каже правду про обидва рівні. Була одна «без помилок» —
 * над п'ятьма попередженнями під нею (прохід канону 22.10.2026).
 * Знахідка — реченням для людини (`say`) про особу (`who`); `text` з назвами
 * полів лишається агентові й показується лише там, де речення ще немає.
 */
function checkBox(env) {
  const d = env.data || {};
  const refs = d.refs || {};
  const n = d.loaded || {};
  const all = (d.issues || []).filter((i) => i.severity !== 'INFO');
  const issues = all.slice(0, SHOW_ISSUES).map((i) => `<li>
      <span class="tag${i.severity === 'ERROR' ? ' err' : ''}">${esc(t(`canon.iss.${issueKind(i.code)}`))}</span>
      <span class="iss-who">${named(i.who || i.where, refs)}</span>
      <span class="iss-what">${named(i.say || i.text, refs)}</span></li>`).join('');
  const more = all.length - SHOW_ISSUES;
  const at = new Date().toLocaleTimeString(LANG, { hour: '2-digit', minute: '2-digit' });
  return `<div class="bx-head"><h3>${t('canon.check')}</h3>
      ${d.warnings ? pill('warn', tn('canon.n.warns', d.warnings)) : ''}
      ${pill(d.errors ? 'err' : 'ok', tn('canon.n.errs', d.errors || 0))}</div>
    <p class="muted">${esc([tn('canon.n.persons', n.persons || 0), tn('canon.n.families', n.families || 0),
    tn('canon.n.places', n.places || 0), tn('canon.n.sources', n.sources || 0)].join(' · '))}</p>
    ${issues ? `<ul class="iss">${issues}</ul>` : ''}
    ${more > 0 ? `<p class="muted">${esc(t('canon.iss.more').replace('{n}', more))}</p>` : ''}
    ${renderWarnings(env)}
    <div class="bx-foot"><button data-act="canon.recheck">${t('canon.recheck')}</button>
      <span class="muted">${esc(t('canon.checked.at').replace('{t}', at))}</span></div>`;
}

/** «Що вирішити» — три перші рішення; решта чекає, доки ці вирішено. */
function nextBox(env) {
  if (!env.ok) return `<h3>${t('canon.next')}</h3><p class="muted">${esc(env.error || '')}</p>`;
  const d = env.data || {};
  const next = d.next || [];
  const total = (d.open || 0) + (d.awaiting || 0);
  const of = total > next.length
    ? `<span class="aside">${esc(t('canon.next.of').replace('{n}', next.length).replace('{m}', total))}</span>` : '';
  return `<div class="bx-head"><h3>${t('canon.next')}</h3>${of}</div>
    ${next.map((x) => decRow(x, d.refs || {})).join('') || `<p class="muted">${t('canon.next.none')}</p>`}`;
}

let LIST_SEQ = 0;

async function cardsList() {
  const seq = ++LIST_SEQ;
  const env = await callOp('canon.cards', { kind: CN.kind, q: CN.q, limit: 200 });
  if (seq !== LIST_SEQ || !el('cn-list')) return;
  if (!env.ok) { boxError('cn-list', env); return; }
  const d = env.data || {};
  const rows = (d.rows || []).map((r) => `<div class="lrow">
      <div><b>${esc(unwiki(r.title))}</b>
        <small class="muted"><span class="mono">${esc(r.id)}</span> · ${esc(t(`canon.kind.${r.kind}`))}
        ${r.private ? ` · ${esc(t('canon.private'))}` : ''}</small></div>
      ${pill(r.citations ? 'ok' : 'neutral', t('canon.cites').replace('{n}', r.citations))}
      <button data-act="canon.card" data-arg="${esc(r.id)}">${t('canon.open')}</button></div>`).join('');
  const more = d.found > (d.rows || []).length
    ? `<p class="muted">${esc(t('canon.more').replace('{n}', d.found))}</p>` : '';
  el('cn-list').innerHTML = rows ? rows + more : emptyMini('pechatka', t('canon.none'));
}

/** Значення поля картки як текст: дата-об'єкт, перелік, рядок. */
function plain(v) {
  if (v === null || v === undefined) return '';
  if (Array.isArray(v)) return v.map(plain).filter(Boolean).join(', ');
  if (typeof v === 'object') {
    for (const k of ['raw', 'text', 'form', 'value', 'name']) if (v[k]) return String(v[k]);
    return JSON.stringify(v);
  }
  return String(v);
}

function citeRow(c, where = '', refs = {}) {
  return `<li>${where ? `<b>${esc(where)}</b> · ` : ''}${named(c.source_id || '', refs)}
    ${c.page ? ` · ${esc(c.page)}` : ''}${c.quote ? `<blockquote>${esc(c.quote)}</blockquote>` : ''}
    ${c.note ? `<small class="muted">${esc(c.note)}</small>` : ''}</li>`;
}

/** Картка у вікні: поля, факти з доказами, зауваження перевірки, гіпотези. */
async function openCard(id) {
  const box = openModal({ title: id, body: `<p class="muted">${t('load.open')}</p>` });
  const seq = modalSeq();
  const env = await callOp('canon.card', { id });
  if (!box || seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  const c = d.card || {};
  const refs = d.refs || {};
  modalTitle(`${unwiki(d.title || id)} · ${id}`);
  // Службове (шлях сирого файла, ID OpenStreetMap) людині ні до чого: шлях до
  // картки — у «Історії картки», а не текстом під нею.
  const skip = new Set(['id', 'facts', 'citations', 'names', 'media', 'notes', 'hits', 'raw_path', 'osm_id']);
  const fields = Object.entries(c).filter(([k, v]) => !skip.has(k) && (typeof v === 'boolean' || plain(v)))
    .map(([k, v]) => [fieldLabel(k), named(fieldValue(k, v), refs)]);
  const facts = (c.facts || []).map((f) => `<li><b>${esc(tOr(`canon.ft.${f.type}`, f.type))}</b>
      ${f.date ? ` · ${esc(fmtDay(plain(f.date)))}` : ''}${f.place_id ? ` · ${named(f.place_id, refs)}` : ''}
      ${f.value ? ` · ${named(f.value, refs)}` : ''} ${pill(f.status === 'confirmed' ? 'ok' : f.status === 'disputed' ? 'warn' : 'neutral',
    tOr(`canon.fs.${f.status}`, f.status || ''))}
      ${f.hypothesis ? ` ${named(f.hypothesis, refs)}` : ''}</li>`).join('');
  const cites = [...(c.citations || []).map((x) => citeRow(x, '', refs)),
    ...(c.facts || []).flatMap((f) => (f.citations || []).map((x) => citeRow(x, tOr(`canon.ft.${f.type}`, f.type), refs)))].join('');
  const issues = (d.issues || []).map((i) => `<li>${pill(i.severity === 'ERROR' ? 'err' : i.severity === 'WARN' ? 'warn' : 'neutral',
    tOr(`canon.sev.${i.severity}`, i.severity))}
      ${named(i.text, refs)}</li>`).join('');
  const hyps = (d.hypotheses || []).map((h) => `<li><button class="ctl-sm" data-act="canon.hyp"
      data-arg="${esc(h.id)}">${esc(h.id)}</button> ${named(h.claim, refs)} ${pill(HYP_TONE[h.status] || 'neutral', tOr(`hyp.st.${h.status}`, h.status))}</li>`).join('');
  el('dlg-body').innerHTML = `<p><b>${esc(d.title || id)}</b>
      <small class="muted"> · ${esc(t(`canon.kind.${d.kind}`))}${d.private ? ` · ${esc(t('canon.private'))}` : ''}</small></p>
    ${kv(fields)}
    ${facts ? `<h4>${t('canon.facts')}</h4><ul>${facts}</ul>` : ''}
    <h4>${t('canon.evidence')}</h4>${cites ? `<ul>${cites}</ul>` : `<p class="muted">${t('canon.evidence.none')}</p>`}
    ${issues ? `<h4>${t('canon.issues')}</h4><ul>${issues}</ul>` : ''}
    ${hyps ? `<h4>${t('nav.hyp')}</h4><ul>${hyps}</ul>` : ''}
    <div class="row dlg-acts">
      <button class="primary" data-act="canon.evidence" data-arg="${esc(id)}">${t('ev.add')}</button>
      <button data-act="canon.history" data-arg="${esc(d.file || '')}">${t('canon.history')}</button>
      <button class="ghost" data-act="modal.close">${t('modal.close')}</button>
    </div>`;
}

Object.assign(ACTIONS, {
  'canon.find': () => {
    CN.q = String((el('cn-q') || {}).value || '').trim();
    CN.kind = String((el('cn-kind') || {}).value || '');
    return cardsList();
  },
  'canon.recheck': async () => {
    const box = el('cn-check');
    if (box) box.innerHTML = `<p class="muted">${t('load.open')}</p>`;
    const env = await callOp('canon.check', {});
    if (!el('cn-check')) return;
    if (!env.ok) { boxError('cn-check', env); return; }
    el('cn-check').innerHTML = checkBox(env);
    const n = (env.data || {}).errors || 0;
    toast(n ? t('canon.check.errors').replace('{n}', n) : t('canon.checked'));
  },
  'canon.card': (_ev, elm) => openCard(elm.dataset.arg),
  'canon.hyp': (_ev, elm) => goto('hyp', { id: elm.dataset.arg }),
  'canon.evidence': (_ev, elm) => openEvidence({ card: elm.dataset.arg }),
  'canon.history': (_ev, elm) => goto('history', { path: elm.dataset.arg }),
});
