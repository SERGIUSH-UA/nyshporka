/** Мови застосунку і поточна мова.
 *
 *  Словник кожної мови — окремий файл у `strings/`: сім мов в одному файлі
 *  давали б понад сім тисяч рядків, у яких забутий ключ ніхто не помітить.
 *  Забуте ловить приймач (`test_translations_cover_every_key_in_every_language`):
 *  набір ключів кожної мови мусить збігатися з українським.
 *
 *  Перелік мов — той самий, що на порталі (`nyshporka-online/app/i18n.py`,
 *  `KATALOHY`); `DISABLED` — дзеркало тамтешнього `VYMKNENI`. Вимкнена мова
 *  перекладена й перевіряється, але її немає в перемикачі й вона не
 *  вибирається сама за мовою браузера.
 */
import uk from './strings/uk.js';

// ── i18n ─────────────────────────────────────────────────────────────────────
// 🔴 Вантажиться лише українська (запасна для кожного ключа) і ПОТОЧНА мова,
// а не всі сім: словники важать 80–110 КБ кожен, і сім разом — понад
// 650 КБ на кожне відкриття консолі, з телефона по Wi-Fi теж (замір 23.10.2026).
// Поточна мова довантажується верхньорівневим `await` нижче: модулі, що
// імпортують `t`, чекають на неї самі, тож перший рядок інтерфейсу вже
// перекладений, а не мигає українською.
const STRINGS = { uk };

/** Код і власна назва мови — у порядку перемикача. */
const LANGS = [
  ['uk', 'Українська'],
  ['en', 'English'],
  ['pl', 'Polski'],
  ['ro', 'Română'],
  ['fr', 'Français'],
  ['de', 'Deutsch'],
  ['ru', 'Русский'],
];
const DISABLED = ['ru'];
const ENABLED = LANGS.map(([c]) => c).filter((c) => !DISABLED.includes(c));

// Сховище може кинути виняток (приватне вікно, заблоковані дані сайту) —
// тоді мова просто не запам'ятовується, а застосунок працює.
function stored() {
  try { return localStorage.getItem('nysh.lang'); } catch (_e) { return null; }
}

/** Мова, коли людина ще не вибирала: перша з мов браузера, яку ми маємо. */
function fromBrowser() {
  const prefs = (typeof navigator !== 'undefined'
    && (navigator.languages || [navigator.language])) || [];
  for (const p of prefs) {
    const code = String(p || '').toLowerCase().split('-')[0];
    if (ENABLED.includes(code)) return code;
  }
  return 'uk';
}

const saved = stored();
const LANG = saved && ENABLED.includes(saved) ? saved : fromBrowser();
if (LANG !== 'uk') {
  try { STRINGS[LANG] = (await import(`./strings/${LANG}.js`)).default; } catch (_e) { /* лишається українська */ }
}
const t = (key) => (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.uk[key] || key;

/** Переклад, якщо він є саме в поточній мові, інакше — те, що дав сервер.
 *  Для назв, які сервер віддає лише українською й англійською (секції). */
const tOr = (key, fallback) => (STRINGS[LANG] && STRINGS[LANG][key]) || fallback;

if (typeof document !== 'undefined') document.documentElement.lang = LANG;

/** Число з відмінком: «1 особа · 3 особи · 393 осіб» замість «393 осіб» на все.
 *  Ключ має форми `.one/.few/.many/.other` у кожній мові (приймач вимагає
 *  однакового набору); категорію дає `Intl.PluralRules` мови, відсутню — `.other`. */
const PLURAL = new Intl.PluralRules(LANG);
const tn = (key, n) => {
  const form = t(`${key}.${PLURAL.select(n)}`);
  return (form.startsWith(key) ? t(`${key}.other`) : form).replace('{n}', n);
};

export { STRINGS, LANG, LANGS, DISABLED, ENABLED, t, tOr, tn };

/** Перемкнути мову. Пише лише сховище: сама змінна не переживає
 *  перезавантаження, а воно тут і відбувається. */
export function setLang(next) {
  try { localStorage.setItem('nysh.lang', next); } catch (_e) { /* див. stored() */ }
}

/**
 * Фраза сервера мовою вікна.
 *
 * Сервер пише застереження, назви перевірок і рядки історії українською — їх
 * читають агент і термінал. Ключ `srv.*` в `uk.js` тримає точний текст сервера,
 * `{x}` у ньому — змінну частину; збіг дає переклад того самого ключа, а змінні
 * частини перекладаються так само (назва шару в «каталог справ змінено …»).
 * Незнайома фраза лишається як є: краще українською, ніж зникнути.
 */
let SRV = null;
function srvPatterns() {
  if (SRV) return SRV;
  SRV = Object.entries(STRINGS.uk).filter(([k]) => k.startsWith('srv.')).map(([k, v]) => {
    const names = [];
    const src = String(v).split(/(\{\w+\})/).map((bit) => {
      const m = /^\{(\w+)\}$/.exec(bit);
      if (m) { names.push(m[1]); return '(.+?)'; }
      return bit.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('');
    return { key: k, re: new RegExp(`^${src}$`), names };
  });
  return SRV;
}

export function srv(text) {
  const s = String(text ?? '');
  if (LANG === 'uk' || !s) return s;
  for (const p of srvPatterns()) {
    const m = p.re.exec(s);
    if (!m) continue;
    let out = t(p.key);
    p.names.forEach((n, i) => { out = out.split(`{${n}}`).join(srv(m[i + 1])); });
    return out;
  }
  return s;
}
