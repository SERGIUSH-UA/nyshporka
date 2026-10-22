/**
 * Дрібні будівельні блоки екранів роду (хвиля 7в): пари «підпис → значення»,
 * плашка стану, безпечний перегляд markdown.
 *
 * Тут лише чисті функції над рядками: ні запитів, ні реєстру. Так їх бачить і
 * тест у Node, і кожен екран, без циклу імпортів.
 */
import { esc } from './view.js';
import { t, tOr } from './strings.js';

/** `<dl class="kv">` з пар; порожні значення випадають. */
export function kv(rows) {
  const body = rows.filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('');
  return body ? `<dl class="kv">${body}</dl>` : '';
}

/** Мітка родини `.tag`: `ok` · `warn` · `info` · `err` · `neutral`. */
export function pill(tone, text) {
  return `<span class="tag ${esc(tone)}">${esc(text)}</span>`;
}

/**
 * Markdown звіту для читання у вікні — мінімально й безпечно.
 *
 * 🔴 Спершу екранування, потім розмітка: звіт пишуть агент і людина, і сирий
 * HTML у ньому не має права стати HTML у консолі. Тому тут не бібліотека, а
 * кілька правил — заголовки, списки, цитати, `код`, **жирне**, таблиці,
 * `[[ID]]` → ім'я з `refs` (як у картках канону).
 */
export function mdLite(src, refs = {}) {
  const out = [];
  let list = '';
  let para = [];
  let pre = null;
  let tbl = [];
  const inline = (s) => named(s, refs);
  // Таблиця markdown — справжньою таблицею: перший рядок — заголовок, рядок
  // `|---|` — роздільник. Доти вона йшла моноширинним текстом із рисками.
  const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
  const flushTbl = () => {
    if (!tbl.length) return;
    const rows = tbl.filter((l) => !/^\|?\s*:?-{2,}/.test(l.trim()));
    const [head, ...body] = rows;
    out.push(`<div class="tbl-wide"><table class="md-table"><thead><tr>${cells(head).map((c) => `<th>${inline(c)}</th>`).join('')
    }</tr></thead><tbody>${body.map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')
    }</tbody></table></div>`);
    tbl = [];
  };
  const flush = () => {
    flushTbl();
    if (para.length) out.push(`<p>${para.map(inline).join(' ')}</p>`);
    para = [];
    if (list) { out.push(`</${list}>`); list = ''; }
  };
  for (const raw of String(src || '').split(/\r?\n/)) {
    if (pre !== null) {
      if (raw.trim().startsWith('```')) { out.push(`<pre>${esc(pre.join('\n'))}</pre>`); pre = null; }
      else pre.push(raw);
      continue;
    }
    const line = raw.trimEnd();
    if (line.trim().startsWith('```')) { flush(); pre = []; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flush(); const n = Math.min(h[1].length + 2, 6); out.push(`<h${n}>${inline(h[2])}</h${n}>`); continue; }
    const li = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.*)$/);
    if (li) {
      if (para.length) { out.push(`<p>${para.map(inline).join(' ')}</p>`); para = []; }
      const tag = /^\s*\d/.test(line) ? 'ol' : 'ul';
      if (list !== tag) { if (list) out.push(`</${list}>`); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${inline(li[1])}</li>`);
      continue;
    }
    if (line.trim().startsWith('|')) {
      if (!tbl.length) flush();
      tbl.push(line);
      continue;
    }
    flushTbl();
    if (line.startsWith('>')) { flush(); out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`); continue; }
    if (!line.trim()) { flush(); continue; }
    if (list) { out.push(`</${list}>`); list = ''; }
    para.push(line.trim());
  }
  if (pre !== null) out.push(`<pre>${esc(pre.join('\n'))}</pre>`);
  flush();
  return out.join('\n');
}

/**
 * Твердження без вікі-дужок: картки пишуть `[[I9001]]` як посилання для
 * сайту роду, а в консолі дужки — шум посеред речення.
 */
export function unwiki(text) {
  return String(text || '').replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, id, label) => label || id);
}

/**
 * Текст картки канону як HTML: ID → ім'я (з ID у підказці), `[[ID]]` і
 * `[[ID|підпис]]` → ім'я чи підпис, `**жирне**` і `код`. Спершу екранування.
 *
 * 🔴 Консоль показувала «Чоловік I9001 · Дружина I9002», «PL9001», «[[I9012]]»
 * там, де людина чекає імен (прохід консолі 22.10.2026). Назви ID кладе сервер
 * полем `refs` відповіді.
 */
export function named(text, refs = {}) {
  const name = (rid) => (refs && refs[rid] ? `<span class="ref" title="${esc(rid)}">${esc(refs[rid])}</span>` : esc(rid));
  return esc(String(text ?? ''))
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, (_m, _rid, label) => label)
    .replace(/\[\[([^\]]+)\]\]/g, (_m, rid) => name(rid))
    .replace(/\b(?:I|F|PL|H)\d{2,}\b|\bS_[A-Za-z0-9_]+\b/g, (rid) => (refs && refs[rid] ? name(rid) : rid))
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
}

/**
 * Тон мітки стану гіпотези — однаковий на кожному екрані: чекає вердикту —
 * дія людини (warn), відкрита — у роботі (info), закрита — ok.
 */
export const HYP_TONE = { open: 'info', awaiting: 'warn', closed: 'ok' };

/**
 * Модель словами: «pysar_cyr_v28.pt+diak_v10» → «Писар v28 + Дяк v10».
 *
 * Рушії мають імена (Писар, Дяк, Скриба), і в консолі ними вже названо блок
 * «Рушії»; файл ваг поруч із ними на тому самому екрані змішував мови. Файл
 * невідомого рушія лишається іменем без розширення.
 */
export function modelName(file) {
  const names = { pysar: 'read.engine.pysar', diak: 'read.engine.diak', skryba: 'read.engine.skryba' };
  return String(file || '').split('+').map((part) => {
    const base = part.trim().split(/[\\/]/).pop().replace(/\.(pt|mlmodel|safetensors|ckpt)$/i, '');
    const eng = base.split('_')[0].toLowerCase();
    const ver = (base.match(/_v(\d+)$/i) || [])[1];
    if (!names[eng]) return base;
    const who = tOr(names[eng], eng);
    return ver ? `${who} v${ver}` : who;
  }).filter(Boolean).join(' + ');
}

/** Дата з рядка ISO («2026-07-23T00:00:00Z», «1993-08-28») → «23.07.2026»; інше — як є. */
export function fmtDay(v) {
  const m = String(v ?? '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(v ?? '');
}

/** Підпис поля картки канону людською мовою; невідоме — як є. */
export const fieldLabel = (k) => tOr(`canon.f.${k}`, k);

/**
 * Значення поля картки як текст: стать, так/ні, дата-об'єкт, перелік,
 * вкладені записи (факти, цитати) — коротко, без JSON.
 */
export function fieldValue(k, v) {
  if (v === null || v === undefined || v === '') return '—';
  if (k === 'sex') return tOr(`canon.sex.${v}`, String(v));
  if (k === 'status') return tOr(`hyp.st.${v}`, tOr(`canon.fs.${v}`, String(v)));
  if (k === 'type' || k === 'kind') return tOr(`canon.type.${v}`, String(v));
  if (typeof v === 'boolean') return v ? t('canon.yes') : t('canon.no');
  if (Array.isArray(v)) {
    if (!v.length) return '—';
    // Варіанти назв, імена: самі написання, а не «записів: 4».
    const forms = v.map((x) => (x && typeof x === 'object'
      ? ['form', 'name', 'value', 'text', 'raw'].map((key) => x[key]).find(Boolean) : x)).filter(Boolean);
    if (forms.length === v.length) return forms.map((x) => fmtDay(x)).join(', ');
    return t('canon.items').replace('{n}', v.length);
  }
  if (typeof v === 'object') {
    for (const key of ['raw', 'text', 'form', 'value', 'name']) if (v[key]) return String(v[key]);
    // Словник «мова → назва»: самі назви через кому.
    const vals = Object.values(v).filter((x) => typeof x === 'string' && x);
    if (vals.length) return vals.join(', ');
    return t('canon.items').replace('{n}', Object.keys(v).length);
  }
  return fmtDay(v);
}

/** Дата з секунд епохи — коротко, мовою вікна. */
export function dayOf(sec, lang = 'uk') {
  if (!sec) return '';
  try {
    return new Date(Number(sec) * 1000).toLocaleDateString(lang, { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return '';
  }
}

/**
 * Короткий відгук після дії («Збережено», «Нічого не змінилось»). Дія без
 * видимого результату читається як кнопка, що не працює.
 */
export function toast(text, ms = 2600) {
  const n = document.createElement('div');
  n.className = 'toast';
  n.setAttribute('role', 'status');
  n.textContent = String(text || '');
  document.body.appendChild(n);
  setTimeout(() => n.classList.add('hide'), ms);
  setTimeout(() => n.remove(), ms + 600);
  return n;
}

/** Скопіювати текст у буфер; `false` — браузер не дав (стара вкладка, http). */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(String(text || ''));
    return true;
  } catch {
    return false;
  }
}
