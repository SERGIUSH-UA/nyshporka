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

import { t, tOr } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, renderWarnings, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { goto } from '../core/nav.js';
import { openModal, modalSeq } from '../core/modal.js';
import { kv, pill, toast, unwiki } from '../core/bits.js';
import { openEvidence } from './evidence.js';

const KINDS = ['persons', 'families', 'places', 'sources', 'hypotheses'];

/** Пошук і кошик живуть між перемальовками екрана. */
const CN = { q: '', kind: '' };

SCREENS.canon = async () => {
  const gen = curGen();
  busy(6);
  const [chk, nxt] = await Promise.all([
    callOp('canon.check', {}), callOp('canon.next', { limit: 3 })]);
  if (!alive(gen)) return;
  if (!chk.ok) return failure(chk);
  setView(`<h2>${t('canon.title')}</h2>
    <p class="muted">${t('canon.why')}</p>
    <div class="dash-two">
      <div class="dash-box" id="cn-check">${checkBox(chk)}</div>
      <div class="dash-box" id="cn-next">${nextBox(nxt)}</div>
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
      <div id="cn-list"><p class="muted">${t('common.loading')}</p></div>
    </div>`);
  await cardsList();
};

function checkBox(env) {
  const d = env.data || {};
  const n = d.loaded || {};
  const tone = d.errors ? 'err' : d.warnings ? 'warn' : 'ok';
  const head = d.errors
    ? t('canon.check.errors').replace('{n}', d.errors)
    : t('canon.check.clean');
  const issues = (d.issues || []).filter((i) => i.severity !== 'INFO').slice(0, 5)
    .map((i) => `<li><span class="mono">${esc(i.where)}</span> ${esc(i.text)}</li>`).join('');
  return `<div class="row"><h3>${t('canon.check')}</h3>${pill(tone, head)}</div>
    <p class="muted num">${esc(t('canon.counts')
    .replace('{p}', n.persons || 0).replace('{f}', n.families || 0)
    .replace('{pl}', n.places || 0).replace('{s}', n.sources || 0))}</p>
    ${issues ? `<ul>${issues}</ul>` : ''}
    ${renderWarnings(env)}
    <p><button data-act="canon.recheck">${t('canon.recheck')}</button></p>`;
}

/** «Що вирішити» — три перші рішення; решта чекає, доки ці вирішено. */
function nextBox(env) {
  if (!env.ok) return `<h3>${t('canon.next')}</h3><p class="muted">${esc(env.error || '')}</p>`;
  const rows = ((env.data || {}).next || []).map((d) => `<div class="lrow">
      <div><b>${esc(unwiki(d.claim))}</b><small class="muted">${esc(d.id)} · ${esc(unwiki(d.decides || ''))}</small></div>
      <button data-act="canon.hyp" data-arg="${esc(d.id)}">${t('canon.open')}</button></div>`).join('');
  return `<h3>${t('canon.next')}</h3>${rows || `<p class="muted">${t('canon.next.none')}</p>`}`;
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
  el('cn-list').innerHTML = rows ? rows + more : `<p class="muted">${t('canon.none')}</p>`;
}

/** Значення поля картки людською мовою: стать, так/ні, дата-об'єкт, перелік. */
function value(k, v) {
  if (k === 'sex') return tOr(`canon.sex.${v}`, String(v));
  if (typeof v === 'boolean') return v ? t('canon.yes') : t('canon.no');
  return plain(v);
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

function citeRow(c, where = '') {
  return `<li>${where ? `<b>${esc(where)}</b> · ` : ''}<span class="mono">${esc(c.source_id || '')}</span>
    ${c.page ? ` · ${esc(c.page)}` : ''}${c.quote ? `<blockquote>${esc(c.quote)}</blockquote>` : ''}
    ${c.note ? `<small class="muted">${esc(c.note)}</small>` : ''}</li>`;
}

/** Картка у вікні: поля, факти з доказами, зауваження перевірки, гіпотези. */
async function openCard(id) {
  const box = openModal({ title: id, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('canon.card', { id });
  if (!box || seq !== modalSeq()) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  const c = d.card || {};
  const skip = new Set(['id', 'facts', 'citations', 'names', 'media', 'notes', 'hits']);
  const fields = Object.entries(c).filter(([k, v]) => !skip.has(k) && (typeof v === 'boolean' || plain(v)))
    .map(([k, v]) => [tOr(`canon.f.${k}`, k), esc(value(k, v))]);
  const facts = (c.facts || []).map((f) => `<li><b>${esc(tOr(`canon.ft.${f.type}`, f.type))}</b>
      ${f.date ? ` · ${esc(plain(f.date))}` : ''}${f.place_id ? ` · ${esc(f.place_id)}` : ''}
      ${f.value ? ` · ${esc(f.value)}` : ''} ${pill(f.status === 'confirmed' ? 'ok' : f.status === 'disputed' ? 'warn' : 'neutral',
    tOr(`canon.fs.${f.status}`, f.status || ''))}
      ${f.hypothesis ? ` <span class="mono">${esc(f.hypothesis)}</span>` : ''}</li>`).join('');
  const cites = [...(c.citations || []).map((x) => citeRow(x)),
    ...(c.facts || []).flatMap((f) => (f.citations || []).map((x) => citeRow(x, tOr(`canon.ft.${f.type}`, f.type))))].join('');
  const issues = (d.issues || []).map((i) => `<li>${pill(i.severity === 'ERROR' ? 'err' : i.severity === 'WARN' ? 'warn' : 'neutral',
    tOr(`canon.sev.${i.severity}`, i.severity))}
      ${esc(i.text)}</li>`).join('');
  const hyps = (d.hypotheses || []).map((h) => `<li><button class="ctl-sm" data-act="canon.hyp"
      data-arg="${esc(h.id)}">${esc(h.id)}</button> ${esc(unwiki(h.claim))} ${pill('info', tOr(`hyp.st.${h.status}`, h.status))}</li>`).join('');
  el('dlg-body').innerHTML = `<p><b>${esc(d.title || id)}</b>
      <small class="muted"> · ${esc(t(`canon.kind.${d.kind}`))}${d.private ? ` · ${esc(t('canon.private'))}` : ''}</small></p>
    ${kv(fields)}
    ${facts ? `<h4>${t('canon.facts')}</h4><ul>${facts}</ul>` : ''}
    <h4>${t('canon.evidence')}</h4>${cites ? `<ul>${cites}</ul>` : `<p class="muted">${t('canon.evidence.none')}</p>`}
    ${issues ? `<h4>${t('canon.issues')}</h4><ul>${issues}</ul>` : ''}
    ${hyps ? `<h4>${t('nav.hyp')}</h4><ul>${hyps}</ul>` : ''}
    <p class="muted mono">${esc(d.file || '')}</p>
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
    if (box) box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
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
