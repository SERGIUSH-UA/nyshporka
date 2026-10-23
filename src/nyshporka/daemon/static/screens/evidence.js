/**
 * 📎 Доказ у канон: кроп рядка → постійний стор → доручення агентові.
 *
 * Відкривається вікном з Розбору («Наш → у канон») і з картки канону
 * («Додати доказ»).
 *
 * 🔴 Консоль картку не править (рішення дослідника 21.10.2026): канон веде
 * агент файлами. Вікно робить лише те, що безпечно механічне, — ріже кроп
 * (`text.crop`) і кладе його сірим JPEG у стор доказів (`evidence.add`), бо
 * цитата на тимчасовий файл провисає, щойно кеш почистять. Факт у картку
 * вносить агент за готовим дорученням нижче.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, boxError, busyForm, fld, renderWarnings } from '../core/view.js';
import { ACTIONS } from '../core/registry.js';
import { openModal } from '../core/modal.js';
import { copyText } from '../core/bits.js';
import { currentName } from '../core/projects.js';

/** Що вікно знає про рядок: справа, скан, рядок (з одиниці), прочитання. */
let EV = {};

/** Архів із ключа справи («DAHMO/230/1/13» → «dahmo»); прогін — порожньо. */
export function provenanceOf(caseKey) {
  const head = String(caseKey || '').split('/')[0];
  return /^[A-Za-z][A-Za-z0-9_-]*$/.test(head) && String(caseKey).includes('/') ? head.toLowerCase() : '';
}

/**
 * Відкрити вікно доказу. `seed`: `{case, page, line, text, card}` — що відомо.
 * З картки відомо лише `card`, з Розбору — усе, крім картки.
 */
export function openEvidence(seed = {}) {
  EV = { ...seed };
  const v = (k) => esc(EV[k] === undefined || EV[k] === null ? '' : String(EV[k]));
  openModal({
    title: t('ev.title'),
    body: `<p class="muted">${t('ev.why')}</p>
      ${currentName() ? `<p class="consequence">${esc(t('ev.lands').replace('{p}', currentName()))}</p>` : ''}
      ${EV.text ? `<blockquote class="mono">${v('text')}</blockquote>` : ''}
      <form data-act="ev.secure" id="ev-form">
        <div class="row">
          ${fld(t('ev.case'), `<input name="case" value="${v('case')}" required>`)}
          ${fld(t('ev.page'), `<input name="page" value="${v('page')}" size="8" required>`)}
          ${fld(t('ev.line'), `<input name="line" type="number" min="1" value="${v('line')}" size="4" required>`)}
        </div>
        <div class="row">
          ${fld(t('ev.card'), `<input name="card" value="${v('card')}" placeholder="${esc(t('ev.card.ph'))}">`)}
          ${fld(t('ev.prov'), `<input name="provenance" value="${esc(provenanceOf(EV.case))}"
            pattern="[a-z][a-z0-9_\\-]*" required>`)}
        </div>
        <div class="row">${fld(t('ev.what'), `<input name="what" placeholder="${esc(t('ev.what.ph'))}" required>`)}</div>
        <div class="row dlg-acts"><button type="submit" class="primary">${t('ev.secure')}</button>
          <button type="button" class="ghost" data-act="modal.close">${t('modal.no')}</button></div>
        <div id="ev-box"></div>
      </form>`,
  });
}

/** Доручення агентові — тим самим текстом, що побачить людина. */
export function agentTask({ card, what, path, case: c, page, line, quote }) {
  // 🔴 Картка необов'язкова: у порожньому каноні її ще нема як назвати, а поле
  // було обов'язковим — і перший доказ не клався зовсім (прохід новачка
  // 23.10.2026). Без картки доручення просить завести нову.
  return t(card ? 'ev.task' : 'ev.task.new')
    .replace('{card}', card).replace('{what}', what).replace('{path}', path)
    .replace('{case}', c).replace('{page}', page).replace('{line}', line)
    .replace('{quote}', quote || '');
}

/** Ім'я доказу в сторі: справа, скан і рядок — латиницею й цифрами. */
export function evidenceName(caseKey, page, line) {
  const stem = String(page || '').replace(/\.[a-z0-9]+$/i, '');
  return `${caseKey}_${stem}_l${line}`.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
}

Object.assign(ACTIONS, {
  'ev.secure': async (ev) => {
    ev.preventDefault();
    const form = new FormData(ev.target);
    const f = (k) => String(form.get(k) || '').trim();
    const done = busyForm(ev.target);
    const line = Number(f('line') || 0);
    const crop = await callOp('text.crop', { case: f('case'), page: f('page'), line });
    if (!crop.ok) { done(); boxError('ev-box', crop); return; }
    const c = crop.data || {};
    // 🔴 Кадр узято не з прогону, а з теки справи за реєстром: збіг імені файла
    // ще не збіг аркуша. Доказ іде в постійний стор, тож спершу око — галочка.
    const risky = (crop.warnings || []).filter((w) => w.code === 'frame_by_registry');
    if (risky.length && !form.get('seen')) {
      done();
      const box = el('ev-box');
      if (box) {
        box.innerHTML = `${renderWarnings({ warnings: risky })}
          <label class="chk"><input type="checkbox" name="seen" value="1"> ${t('ev.seen')}</label>`;
      }
      return;
    }
    // Ім'я — з ключа справи, скану й рядка: «0005_l4» з кропу однакове для
    // будь-якої справи, і другий такий доказ упирався б у «вже є».
    // Походження — справа, скан і рядок, з яких вирізано кроп: по ньому Пошук
    // позначатиме цей рядок як «уже в каноні».
    const got = await callOp('evidence.add', { file: c.out, provenance: f('provenance'),
      name: evidenceName(f('case'), c.page || f('page'), line),
      origin_case: f('case'), origin_page: c.page || f('page'), origin_line: line });
    done();
    if (!got.ok) { boxError('ev-box', got); return; }
    const path = (got.data || {}).path || '';
    const task = agentTask({ card: f('card'), what: f('what'), path, case: f('case'),
      page: c.page || f('page'), line, quote: EV.text || c.text || '' });
    EV.task = task;
    const box = el('ev-box');
    if (!box) return;
    box.innerHTML = `<p class="ok-line">${t('ev.done')}</p>
      <p class="mono">${esc(path)}</p>
      <p class="muted">${t('ev.task.why')}</p>
      <textarea id="ev-task" rows="5" readonly>${esc(task)}</textarea>
      <p><button type="button" data-act="ev.copy">${t('ev.copy')}</button>
        <span id="ev-copied" class="muted"></span></p>`;
  },
  'ev.copy': async () => {
    const okCopy = await copyText(EV.task || '');
    const mark = el('ev-copied');
    if (mark) mark.textContent = okCopy ? t('ev.copied') : t('ev.copy.fail');
  },
});
