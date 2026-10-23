/**
 * ▶ Зараз читається — одна панель на всіх екранах Читання.
 *
 * 🔴 Доти «Прогони» показували «читається зараз» без кнопки, «Хмара» —
 * «нічого не крутиться», коли справа читалась на цій машині, а «Черга» не
 * бачила прогону з термінала чи від помічника (дослідник, 23.10.2026). Тепер
 * кожне живе читання видно звідусіль: де йде, хто запустив, скільки прочитано —
 * і чим його спинити.
 *
 * Панель оновлюється сама, поки щось читається і екран той самий.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, alive, boxError } from '../core/view.js';
import { ACTIONS } from '../core/registry.js';
import { goto } from '../core/nav.js';
import { ratioBar, toast } from '../core/bits.js';

/** Як часто перепитувати, поки щось читається. */
const EVERY_MS = 8000;

export const nowBox = () => '<div id="rn-box" class="rn" hidden></div>';

function row(it) {
  const name = it.shifra || it.case_key || it.case || it.run;
  const where = it.where === 'cloud'
    ? `${t('rn.cloud')}${it.phase ? ` · ${esc(it.phase)}` : ''}`
    : t('rn.local');
  const who = it.where === 'cloud' ? '' : ` · ${t(`rn.via.${it.via}`)}`;
  const shards = it.shards > 1 ? ` · ${t('rn.shards').replace('{n}', it.shards)}` : '';
  const mins = it.minutes ? ` · ${t('rn.min').replace('{n}', it.minutes)}` : '';
  const count = it.total ? `${it.done} / ${it.total}` : String(it.done || 0);
  let acts = '';
  if (it.where === 'cloud') {
    acts = `<button class="ctl-sm" data-act="rn.stop" data-kind="cloud" data-arg="${esc(it.run)}">${t('rn.stop')}</button>
      <button class="ctl-sm ghost" data-act="nav" data-arg="cloud">${t('rn.go.cloud')}</button>`;
  } else if (it.via === 'queue') {
    acts = `<button class="ctl-sm" data-act="rn.stop" data-kind="queue" data-arg="${esc(it.case)}">${t('rn.stop.queue')}</button>
      <button class="ctl-sm ghost" data-act="nav" data-arg="queue">${t('rn.go.queue')}</button>`;
  } else {
    acts = `<button class="ctl-sm" data-act="rn.stop" data-kind="local" data-arg="${esc(it.case)}">${t('rn.stop')}</button>`;
  }
  return `<div class="rn-row">
      <span class="rn-mark" aria-hidden="true">▶</span>
      <span class="rn-what"><b class="mono">${esc(name)}</b>${it.title ? ` <span class="muted">${esc(it.title)}</span>` : ''}
        <small class="muted">${where}${who}${shards}${mins}</small></span>
      <span class="rn-prog">${ratioBar(it.done, it.total)} <span class="num">${esc(count)}</span></span>
      <span class="rn-acts">${acts}</span>
    </div>`;
}

let TIMER = null;

/** Намалювати й, поки щось читається, перепитувати. `gen` — покоління екрана. */
export async function fillNow(gen) {
  if (TIMER) { clearTimeout(TIMER); TIMER = null; }
  const box = el('rn-box');
  if (!box) return;
  const env = await callOp('reading.now', {});
  if (!alive(gen) || !el('rn-box')) return;
  const items = (env.ok && (env.data || {}).items) || [];
  box.hidden = !items.length;
  box.innerHTML = items.length
    ? `<h3>${t('rn.title')}</h3>${items.map(row).join('')}<div id="rn-msg"></div>`
    : '';
  if (items.length) TIMER = setTimeout(() => fillNow(gen), EVERY_MS);
}

Object.assign(ACTIONS, {
  /**
   * Спинити — з другого натискання: перше лише питає. Прочитане лишається,
   * справу дочитують на Прогонах.
   */
  'rn.stop': async (_ev, elm) => {
    if (elm.dataset.sure !== '1') {
      elm.dataset.sure = '1';
      elm.textContent = t('rn.stop.sure');
      return undefined;
    }
    const kind = elm.dataset.kind;
    const arg = elm.dataset.arg;
    const env = kind === 'cloud' ? await callOp('cloud.stop', { run_id: arg })
      : kind === 'queue' ? await callOp('queue.stop', { now: true })
        : await callOp('read.stop', { case: arg });
    if (!env.ok) { boxError('rn-msg', env); return undefined; }
    toast(t('rn.stopped'), { tone: 'ok' });
    const box = el('rn-box');
    if (box) box.hidden = true;
    return goto(location.hash.slice(1) || 'runs');
  },
});
