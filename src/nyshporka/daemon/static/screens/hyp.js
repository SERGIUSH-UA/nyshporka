/**
 * ❓ Гіпотези роду: що не доведено, на чому тримається і що це розв'яже.
 *
 * Гіпотези — картки канону (`H…`, open / awaiting / closed, до 5 кандидатів).
 * Досі їх було видно лише в `canon next` у терміналі. Порядок той самий, що в
 * «що вирішити» (`canon/next.rank`), закриті — у кінці.
 *
 * 🔴 Вердикт на кандидата виносить людина. Звідси кандидат іде в Розбір («На
 * звірку»), а не закривається тут: екран гіпотез нічого не вирішує сам.
 */

import { t } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, busy, failure, boxError, curGen, alive } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { show } from '../core/nav.js';
import { openModal } from '../core/modal.js';
import { ST } from '../core/state.js';
import { kv, pill } from '../core/bits.js';

const TONE = { open: 'warn', awaiting: 'info', closed: 'ok' };

/** Відкрита гіпотеза: хіти з прогоном, який дав `text.crop`. */
let OPEN = null;

SCREENS.hyp = async () => {
  const gen = curGen();
  busy(5);
  const env = await callOp('canon.hyps', {});
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const c = d.counts || {};
  const tile = (k) => `<div class="dash-box"><span class="muted">${t(`hyp.st.${k}`)}</span>
    <b class="num big">${esc(c[k] || 0)}</b></div>`;
  const rows = (d.rows || []).map((h) => `<div class="lrow">
      <div><b>${esc(h.claim)}</b>
        <small class="muted"><span class="mono">${esc(h.id)}</span>${
  h.decides ? ` · ${esc(t('hyp.decides'))}: ${esc(h.decides)}` : ''}</small>
        <span>${pill(TONE[h.status] || 'neutral', t(`hyp.st.${h.status}`))}${
  h.hits ? ` ${pill(h.strong ? 'warn' : 'neutral', t('hyp.hits').replace('{n}', h.hits))}` : ''}</span></div>
      <button data-act="hyp.open" data-arg="${esc(h.id)}">${t('canon.open')}</button></div>`).join('');
  setView(`<h2>${t('hyp.title')}</h2>
    <p class="muted">${t('hyp.why')}</p>
    <div class="dash-two">${tile('open')}${tile('awaiting')}${tile('closed')}</div>
    <div class="dash-box">${rows || `<p class="muted">${t('hyp.none')}</p>`}</div>`);
  const seed = ST.hyp;
  ST.hyp = null;
  if (seed && seed.id) await openHyp(seed.id);
};

/** Гіпотеза у вікні: підстава, спірні факти, кандидати з кропами. */
async function openHyp(id) {
  openModal({ title: id, body: `<p class="muted">${t('common.loading')}</p>` });
  const env = await callOp('canon.hyp', { id });
  if (!el('dlg-body')) return;
  if (!env.ok) { boxError('dlg-body', env); return; }
  const d = env.data || {};
  const card = d.card || {};
  OPEN = { id, hits: (d.hits || []).map((h) => ({ ...h })) };
  const hits = OPEN.hits.map((h, i) => `<div class="lrow">
      <div><div id="hyp-crop-${i}" class="hyp-crop"></div>
        <span class="mono">${esc(h.reading)}</span>
        <small class="muted mono">${esc(h.case)} · ${esc(h.scan)}${h.line ? ` · ${esc(t('ev.line'))} ${esc(h.line)}` : ''}
          · ${esc(t(`hyp.str.${h.strength}`))} · ${esc(h.eye ? t('hyp.eye.yes') : t('hyp.eye.no'))}</small></div>
    </div>`).join('');
  const canSift = OPEN.hits.some((h) => h.line);
  el('dlg-body').innerHTML = `<p><b>${esc(card.claim || id)}</b>
      ${pill(TONE[card.status] || 'neutral', t(`hyp.st.${card.status}`))}</p>
    ${kv([[t('hyp.basis'), esc(card.basis || '')], [t('hyp.decides'), esc(card.decides || '')],
    [t('hyp.facts'), esc((d.facts || []).join(', '))], [t('hyp.versus'), esc((d.versus || []).join(', '))],
    [t('hyp.about'), esc((card.about || []).join(', '))]])}
    <h4>${t('hyp.cands')}</h4>
    ${hits || `<p class="muted">${t('hyp.cands.none')}</p>`}
    <div class="row dlg-acts">
      ${canSift ? `<button class="primary" data-act="hyp.sift">${t('hyp.sift')}</button>` : ''}
      <button data-act="nav" data-arg="search">${t('hyp.more')}</button>
      <button class="ghost" data-act="modal.close">${t('modal.close')}</button>
    </div>`;
  await hitCrops(id);
}

/**
 * Кропи кандидатів: `text.crop` знаходить прогін і рядок за ключем справи,
 * `page.view` віддає картинку. Двома кроками, бо хіт гіпотези знає справу,
 * а не прогін.
 */
async function hitCrops(id) {
  for (let i = 0; i < OPEN.hits.length; i += 1) {
    const h = OPEN.hits[i];
    if (!h.line || !OPEN || OPEN.id !== id) continue;
    const crop = await callOp('text.crop', { case: h.case, page: h.scan, line: h.line });
    if (!OPEN || OPEN.id !== id) return;
    const box = el(`hyp-crop-${i}`);
    if (!crop.ok) { if (box) box.innerHTML = `<small class="muted">${esc(crop.error || '')}</small>`; continue; }
    h.run = (crop.data || {}).run;
    h.page = (crop.data || {}).page;
    const view = await callOp('page.view', { run: h.run, page: h.page, line: h.line - 1, region: 'line' });
    const b2 = el(`hyp-crop-${i}`);
    if (b2 && view.ok && (view.data || {}).image) {
      b2.innerHTML = `<img class="hit-crop" src="${esc(view.data.image)}" alt="${esc(h.reading)}">`;
    }
  }
}

/** Хіти гіпотези у форматі Розбору: прогін, сторінка, рядок з нуля. */
export function siftHits(hits) {
  return hits.filter((h) => h.line && h.run).map((h) => ({
    name: h.run, page: h.page || h.scan, line_index: h.line - 1, line: h.reading,
    matched: '', case_key: h.case, score: h.strength,
  }));
}

Object.assign(ACTIONS, {
  'hyp.open': (_ev, elm) => openHyp(elm.dataset.arg),
  'hyp.sift': () => {
    const hits = siftHits((OPEN || {}).hits || []);
    if (!hits.length) return null;
    ST.sift = { hits, i: 0, q: (OPEN || {}).id || '', crop: null, ctx: null };
    return show('sift');
  },
});
