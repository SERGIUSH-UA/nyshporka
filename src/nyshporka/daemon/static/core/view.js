/** Розмітка екрана: підміна вмісту, застереження, покриття, покоління. */
import { t } from './strings.js';
import { swapHtml, skelRows } from '/ui/dom.js';

let SCREEN_GEN = 0;

/**
 * 🔴 Покоління екрана рухає лише навігація, а читають його ВСІ екрани.
 * Доступ функціями, бо імпортована змінна для того, хто її імпортував,
 * доступна тільки на читання: пряме `SCREEN_GEN += 1` з іншого модуля
 * мовчки не спрацювало б, і жоден екран більше не скасовував би свій
 * застарілий запит.
 */
export const curGen = () => SCREEN_GEN;
export const bumpGen = () => { SCREEN_GEN += 1; };

const alive = (my) => my === SCREEN_GEN;

// ── розмітка ─────────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const el = (id) => document.getElementById(id);

/** Попередження конверта — на екран ЗАВЖДИ. Саме тут живе «нуль зі знаменником». */
function renderWarnings(env) {
  const bits = [];
  if (env.stale && env.stale.is) {
    // 🔴 Виправлення поруч із застереженням, а не в підказці «наберіть у
    // терміналі». Той, хто працює формами, інакше лишається із застереженням
    // і без способу його зняти — тобто змушений вірити застарілому зрізу.
    bits.push(`<div class="warn stale">⚠ ${esc(env.stale.reasons.join('; '))}
      <button data-act="cases.build">${t('cases.build')}</button></div>`);
  }
  for (const w of env.warnings || []) {
    bits.push(`<div class="warn">⚠ ${esc(w.text)}</div>`);
  }
  return bits.join('');
}

/**
 * Покриття конверта — ДЕ САМЕ шукали і якого воно зрізу.
 *
 * 🔴 Друга половина правила «нуль мусить щось означати». Перша — відмова
 * джерела, яке шукати не може; ця — про джерела, які змогли: порожня видача без
 * переліку переглянутого не відрізняється на екрані від «ніде не шукали», а
 * коштує ця плутанина напряму пошуку, закритого назавжди.
 */
function renderCoverage(env) {
  const cov = env.coverage || [];
  if (!cov.length) return '';
  const bits = cov.map((c) => {
    const taken = c.taken ? `, зріз ${esc(c.taken)}` : '';
    const scope = c.scope ? ` — ${esc(c.scope)}` : '';
    return `${esc(c.source)}${taken}${scope}`;
  });
  return `<p class="muted cov">🔎 ${t('cov.searched')}: ${bits.join('; ')}</p>`;
}

/**
 * Замінити вміст екрана.
 *
 * ⚠ Через `swapHtml`, а не присвоєнням `innerHTML`: голе присвоєння схлопує
 * контейнер у нульову висоту на один кадр, і сторінка під ним підстрибує —
 * найпомітніше на довгих таблицях, де око вже стоїть на потрібному рядку.
 * `keepScroll: false` тут навмисно: зміна екрана мусить починатись згори.
 */
function setView(html) { swapHtml(el('view'), html, { keepScroll: false }); }

/**
 * Стан завантаження.
 *
 * 🔴 Скелетон, а не рядок «завантаження…»: текстова заглушка має іншу висоту за
 * дані, тож у момент їх приходу вміст стрибає. Скелетон тримає приблизно ту
 * саму висоту, і сторінка лишається на місці.
 */
function busy(rows = 8) {
  setView(`<table><tbody>${skelRows(rows, 4)}</tbody></table>`);
}

function failure(env) {
  setView(`<div class="warn err">${t('common.error')}: ${esc(env.error || '?')}</div>`);
}

/**
 * Помилка В МЕЖАХ екрана — у власну коробку, а не через `setView`.
 *
 * 🔴 `failure()` замінює весь `main#view`, тобто зносить форму разом із
 * набраним текстом. А половина відмов тут — рівня описки («немає прогону
 * «X»», «не розпізнана шифра», «по справі ще нічого не занесено»): саме після
 * них форма й потрібна, а замість неї лишався один рядок помилки й похід у
 * вкладку заново. Зразок правильної поведінки в файлі вже був — `case.save`.
 */
function boxError(id, env) {
  const box = el(id);
  if (!box) return failure(env);   // немає куди покласти — краще екраном
  box.innerHTML = `<div class="warn err">${esc(env.error || '?')}</div>`;
  return undefined;
}

/** Заблокувати кнопки форми на час запиту; повертає, як розблокувати. */
function busyForm(form) {
  const btns = form && form.tagName === 'FORM'
    ? [...form.querySelectorAll('button')].filter((b) => !b.disabled) : [];
  btns.forEach((b) => { b.disabled = true; });
  return () => btns.forEach((b) => { b.disabled = false; });
}

export { esc, el, renderWarnings, renderCoverage, setView, busy,
  failure, boxError, busyForm, alive };
