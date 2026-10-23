/**
 * Дрібні будівельні блоки екранів роду (хвиля 7в): пари «підпис → значення»,
 * плашка стану, безпечний перегляд markdown.
 *
 * Тут лише чисті функції над рядками: ні запитів, ні реєстру. Так їх бачить і
 * тест у Node, і кожен екран, без циклу імпортів.
 */
import { ic } from '/ui/icons.js';
import { esc } from './view.js';
import { t, tOr, tn } from './strings.js';

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
  // 🔴 Посилання — ОДНИМ проходом. Доти `[[I9036]]` спершу ставав
  // `<span title="I9036">…</span>`, а наступна заміна голих id знаходила
  // `I9036` уже в атрибуті й вкладала туди другий тег — і в назвах гіпотез
  // проступав сирий HTML (`…"&gt;Никита…`, 65 разів на екрані, QA 23.10.2026).
  return esc(String(text ?? ''))
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]|\b(?:I|F|PL|H)\d{2,}\b|\bS_[A-Za-z0-9_]+\b/g,
      (m, _rid, label, wiki) => {
        if (label !== undefined) return label;
        if (wiki !== undefined) return name(wiki);
        return refs && refs[m] ? name(m) : m;
      })
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
}

/**
 * Тон мітки стану гіпотези — однаковий на кожному екрані: чекає вердикту —
 * дія людини (warn), відкрита — у роботі (info), закрита — ok.
 */
export const HYP_TONE = { open: 'info', awaiting: 'warn', closed: 'ok' };

/**
 * Рядок «що вирішити» (`canon.next`): номер гіпотези й що її розв'яже — дрібно
 * над твердженням, клікається весь рядок. Один на Канон і Огляд.
 *
 * 🔴 Твердження звичайною вагою: три абзаци суцільного жирного поруч із
 * трьома кнопками «Відкрити» читались важче за саму суть (прохід канону
 * 22.10.2026, варіант C). Дія — `canon.hyp` з екрана Канону: екрани
 * вантажаться всі, тож друга, однакова дія Огляду була б дублем.
 */
export function decRow(x, refs = {}) {
  return `<button class="dec" data-act="canon.hyp" data-arg="${esc(x.id)}">
    <span class="dec-meta"><span class="tag ${HYP_TONE[x.status] || ''}">${esc(x.id)}</span>
      <span class="dec-why">${named(x.decides || '', refs)}</span>
      <span class="dec-go">${esc(t('canon.open'))} →</span></span>
    <span class="dec-claim">${named(x.claim || '', refs)}</span></button>`;
}

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
    // Невідома модель — назва файлу без підкреслень («logofet ro · v9»), а не
    // сире ім'я з розширенням.
    if (!names[eng]) return base.replace(/_v(\d+)$/i, ' · v$1').replace(/_/g, ' ');
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
 * Короткий відгук після дії («Збережено», «Додано в чергу»). Дія без видимого
 * результату читається як кнопка, що не працює.
 *
 * `opts` — число (мс, як було) або `{ tone, ms }`: `ok` — зелена галочка,
 * `err` — червоний хрестик і довше на екрані, без тону — нейтральний. Тости
 * стають стосом у `#toasts` (не налазять один на одного, коли дві дії
 * завершились поруч), видимих — не більше трьох. Помилку, яку треба
 * прочитати й виправити, показують на екрані, а не тостом: тост зникає.
 */
const TOAST_ICON = { ok: 'check-circle', err: 'x-circle', info: 'info' };
export function toast(text, opts = {}) {
  const o = typeof opts === 'number' ? { ms: opts } : opts;
  const tone = o.tone || '';
  const ms = o.ms || (tone === 'err' ? 5000 : 2600);
  let box = document.getElementById('toasts');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toasts';
    box.className = 'toasts';
    box.setAttribute('aria-live', 'polite');
    document.body.appendChild(box);
  }
  [...box.children].slice(0, Math.max(0, box.children.length - 2)).forEach((c) => c.remove());
  const n = document.createElement('div');
  n.className = 'toast' + (tone ? ' toast-' + tone : '');
  n.setAttribute('role', tone === 'err' ? 'alert' : 'status');
  n.textContent = String(text || '');
  if (TOAST_ICON[tone] && n.insertAdjacentHTML) n.insertAdjacentHTML('afterbegin', ic(TOAST_ICON[tone], 'ic-sm'));
  box.appendChild(n);
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

/**
 * Справа з бібліотеки як підказка вибору: людина бачить шифру й назву, роки й
 * кадри — дрібно, а в дію йде шлях теки (`combobox.cbValue`).
 */
export function caseItem(c) {
  const title = String(c.title || '');
  const short = title.length > 70 ? `${title.slice(0, 68)}…` : title;
  const years = c.year_from ? (c.year_to && c.year_to !== c.year_from ? `${c.year_from}–${c.year_to}` : `${c.year_from}`) : '';
  const head = c.shifra || c.key || c.path;
  return { value: c.path, label: short ? `${head} · ${short}` : head,
    hint: [years, c.frames ? tn('unit.frames', c.frames) : ''].filter(Boolean).join(' · ') };
}

/**
 * Назва без емодзі: заголовки звітів і змін пишуть люди й агенти, і «🔎»,
 * «🦔» на початку рядка серед значків пером виглядають наліпками з чужого
 * набору. Дані не міняються — лише показ.
 */
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}\u{200D}\u{20E3}]/gu;
export function noEmoji(text) {
  return String(text || '').replace(EMOJI, '').replace(/\s{2,}/g, ' ').trim();
}

/**
 * Тонка смужка «скільки з скількох» під числом: неповне видно оком, не
 * вчитуючись у «104 / 994». Повне — медом, неповне — приглушено.
 */
export function ratioBar(n, total) {
  const a = Number(n) || 0;
  const b = Number(total) || 0;
  if (!b) return '';
  const pct = Math.max(0, Math.min(100, Math.round((a / b) * 100)));
  return `<span class="ratio-bar${pct >= 100 ? ' full' : ''}" role="img" aria-label="${pct}%"><i style="width:${pct}%"></i></span>`;
}

/** Кінець шляху — дві останні теки: «…/f211_films/211-3-32», повний — у підказці. */
export function pathTail(p, n = 2) {
  const parts = String(p || '').split(/[\/]+/).filter(Boolean);
  return parts.length > n ? `…/${parts.slice(-n).join('/')}` : parts.join('/');
}
