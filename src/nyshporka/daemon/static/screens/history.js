/**
 * 🕓 Історія проєкту: журнал змін, «що змінилось», повернення картки.
 *
 * Історія — локальний git, який Нишпорка заводить сама (хвиля 5г); зелена
 * перевірка канону зберігається сама. Там, де git веде сама людина, замість
 * перемикача стоїть «коміти ведете ви», а «Повернути» лишається.
 *
 * 🔴 «Що змінилось» у картці — полями «було → стало», а не сирим git diff:
 * людина звіряє дату народження, а не рядки YAML.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { openModal, confirmAct, modalSeq } from '../core/modal.js';
import { ST } from '../core/state.js';
import { pill, toast, fieldLabel, fieldValue } from '../core/bits.js';

/** Файл, журнал якого показано (з картки канону), — або весь проєкт. */
let PATH = '';
/** Рядки журналу з останньої відповіді: «Що змінилось» бере файли звідси. */
let ROWS = [];

SCREENS.history = async () => {
  const gen = curGen();
  const seed = ST.history;
  ST.history = null;
  // Вкладка без посіву — увесь проєкт: фільтр картки не переживає виходу.
  PATH = seed && seed.path ? seed.path : '';
  busy(5);
  const auto = await callOp('history.auto', {});
  if (!alive(gen)) return;
  if (!auto.ok) return failure(auto);
  setView(`
    <p class="muted">${t('hist.why')}</p>
    <div class="dash-box" id="hist-auto">${autoBox(auto.data || {})}</div>
    <div class="dash-box">
      <div class="row"><h3>${PATH ? esc(PATH) : t('hist.all')}</h3>
        ${PATH ? `<button class="ctl-sm" data-act="hist.all">${t('hist.showall')}</button>` : ''}
        <button data-act="hist.save">${t('hist.save')}</button></div>
      <div id="hist-log"><p class="muted">${t('load.history')}</p></div>
    </div>`);
  await drawLog();
};

function autoBox(d) {
  if (!d.git) return `<p class="warn">${t('hist.nogit')}</p>`;
  if (!d.repo) return `<p class="warn">${t('hist.norepo')}</p><p class="mono">nysh history setup</p>`;
  if (d.own) return `<p>${pill('neutral', t('hist.own'))} ${t('hist.own.why')}</p>`;
  return `<label class="chk"><input type="checkbox" data-act="hist.auto"${d.auto ? ' checked' : ''}>
    <b>${t('hist.auto')}</b></label><p class="muted">${t('hist.auto.why')}</p>`;
}

async function drawLog() {
  const env = await callOp('history.log', { path: PATH, limit: 30 });
  const box = el('hist-log');
  if (!box) return;
  if (!env.ok) { boxError('hist-log', env); return; }
  ROWS = (env.data || {}).rows || [];
  box.innerHTML = ROWS.length ? ROWS.map((r, i) => {
    const files = r.files || (PATH ? [PATH] : []);
    const tail = r.more ? ` ${esc(t('hist.more').replace('{n}', r.more))}` : '';
    return `<div class="lrow">
      <div><b>${esc(r.subject)}</b>
        <small class="muted"><span class="mono">${esc(r.rev)}</span> · ${esc(r.date)}</small>
        ${files.length ? `<small class="muted mono">${esc(files.join(', '))}${tail}</small>` : ''}</div>
      ${files.length ? `<button data-act="hist.diff" data-arg="${i}">${t('hist.diff')}</button>` : ''}</div>`;
  }).join('') : `<p class="muted">${t('hist.empty')}</p>`;
}

/** Вікно «Що змінилось»: файл коміту → поля «було → стало» чи рядки. */
async function openDiff(i, file = '') {
  const r = ROWS[i];
  if (!r) return;
  const files = r.files || (PATH ? [PATH] : []);
  const path = file || files[0];
  openModal({ title: `${r.rev} · ${r.date}`, body: `<p class="muted">${t('common.loading')}</p>` });
  const seq = modalSeq();
  const env = await callOp('history.diff', { path, rev: r.rev });
  if (seq !== modalSeq()) return;
  const pick = files.length > 1 ? `<label class="fld"><span class="fld-l">${t('hist.file')}</span>
      <select data-act="hist.pick" data-arg="${i}">${files.map((f) => `<option${f === path ? ' selected' : ''}>${
  esc(f)}</option>`).join('')}</select></label>` : `<p class="mono">${esc(path)}</p>`;
  const body = env.ok ? diffBody(env.data || {}) : `<p class="warn">${esc(env.error || '')}</p>`;
  el('dlg-body').innerHTML = `<p>${esc(r.subject)}</p>${pick}${body}
    <div class="row dlg-acts">
      <button class="danger" data-act="hist.restore" data-arg="${i}" data-file="${esc(path)}">${
  esc(t('hist.restore').replace('{rev}', r.rev))}</button>
      <button class="ghost" data-act="modal.close">${t('modal.close')}</button></div>`;
}

/** Тіло різниці: поля картки або рядки тексту з позначкою обрізки. */
export function diffBody(d) {
  if (d.kind === 'fields') {
    const rows = (d.fields || []).map((f) => `<tr><td>${esc(fieldLabel(f.field))}</td>
      <td class="diff-d">${esc(fieldValue(f.field, f.before))}</td><td class="diff-a">${
  esc(fieldValue(f.field, f.after))}</td></tr>`).join('');
    return `${rows ? `<table class="tbl-diff"><thead><tr><th>${t('hist.field')}</th><th>${t('hist.before')}</th>
      <th>${t('hist.after')}</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="muted">${t('hist.nofields')}</p>`}
      ${d.notes_changed ? `<p>${pill('info', t('hist.notes'))}</p>` : ''}`;
  }
  return `<pre class="diff">${(d.lines || []).map((l) => {
    const cls = l.startsWith('+') ? 'diff-a' : l.startsWith('-') ? 'diff-d' : '';
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join('\n')}</pre>${d.cut ? `<p class="muted">${t('hist.cut')}</p>` : ''}`;
}

Object.assign(ACTIONS, {
  'hist.all': () => { ST.history = null; return SCREENS.history(); },
  'hist.save': async () => {
    const env = await callOp('history.save', { message: t('hist.save.msg') });
    if (!env.ok) { boxError('hist-log', env); return; }
    toast((env.data || {}).saved ? t('hist.saved') : t('hist.nochange'));
    await drawLog();
  },
  'hist.auto': async (_ev, elm) => {
    const env = await callOp('history.auto', { on: !!elm.checked });
    const box = el('hist-auto');
    if (!box) return;
    if (env.ok) { box.innerHTML = autoBox(env.data || {}); toast(env.data.auto ? t('hist.auto.on') : t('hist.auto.off')); return; }
    // Відмова не забирає перемикач: людина бачить причину й може спробувати ще.
    elm.checked = !elm.checked;
    box.insertAdjacentHTML('beforeend', `<div class="warn err">${esc(env.error || '')}</div>`);
  },
  'hist.diff': (_ev, elm) => openDiff(Number(elm.dataset.arg)),
  'hist.pick': (_ev, elm) => openDiff(Number(elm.dataset.arg), elm.value),
  /**
   * 🔴 Повернення — лише після підтвердження, що називає наслідок: сьогоднішні
   * зміни картки зникнуть з канону (в історії лишаться).
   */
  'hist.restore': async (_ev, elm) => {
    const r = ROWS[Number(elm.dataset.arg)];
    const path = elm.dataset.file;
    if (!r || !path) return;
    const yes = await confirmAct({ title: t('hist.restore.title'), text: t('hist.restore.why'),
      rows: [[t('hist.file'), path], [t('hist.rev'), `${r.rev} · ${r.date}`]],
      okLabel: t('hist.restore.go'), danger: true });
    if (!yes) return;
    const env = await callOp('history.restore', { path, rev: r.rev });
    if (!env.ok) { boxError('hist-log', env); return; }
    // Без нового коміту файл уже був таким — сказати це, а не мовчати.
    toast((env.data || {}).rev ? t('hist.restored') : t('hist.same'));
    await drawLog();
  },
});
