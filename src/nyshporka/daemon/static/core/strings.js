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
import en from './strings/en.js';
import pl from './strings/pl.js';
import ro from './strings/ro.js';
import fr from './strings/fr.js';
import de from './strings/de.js';
import ru from './strings/ru.js';

// ── i18n ─────────────────────────────────────────────────────────────────────
const STRINGS = { uk, en, pl, ro, fr, de, ru };

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
