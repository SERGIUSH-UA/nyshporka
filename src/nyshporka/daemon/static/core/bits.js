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
 * кілька правил — заголовки, списки, цитати, `код`, **жирне**, таблиці як
 * моноширинний текст.
 */
export function mdLite(src) {
  const out = [];
  let list = '';
  let para = [];
  let pre = null;
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  const flush = () => {
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
    if (line.startsWith('|')) { flush(); out.push(`<pre class="md-tbl">${esc(line)}</pre>`); continue; }
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

/** Підпис поля картки канону людською мовою; невідоме — як є. */
export const fieldLabel = (k) => tOr(`canon.f.${k}`, k);

/**
 * Значення поля картки як текст: стать, так/ні, дата-об'єкт, перелік,
 * вкладені записи (факти, цитати) — коротко, без JSON.
 */
export function fieldValue(k, v) {
  if (v === null || v === undefined || v === '') return '—';
  if (k === 'sex') return tOr(`canon.sex.${v}`, String(v));
  if (typeof v === 'boolean') return v ? t('canon.yes') : t('canon.no');
  if (Array.isArray(v)) {
    if (!v.length) return '—';
    if (v.every((x) => x && typeof x === 'object')) return t('canon.items').replace('{n}', v.length);
    return v.map((x) => fieldValue('', x)).join(', ');
  }
  if (typeof v === 'object') {
    for (const key of ['raw', 'text', 'form', 'value', 'name']) if (v[key]) return String(v[key]);
    return t('canon.items').replace('{n}', Object.keys(v).length);
  }
  return String(v);
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
