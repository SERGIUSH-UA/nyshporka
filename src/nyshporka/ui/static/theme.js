// Нишпорка — тризначна тема: авто / світла / темна.
//
// «Авто» — не синонім «темної за замовчуванням», а ЖИВЕ стеження за системою:
// консоль тримають відкритою добами, і коли ОС перемикає нічний режим о 20:00,
// вкладка мусить піти за нею без перезавантаження (слухач `mql` унизу).
//
// 🔴 Дубль стартової логіки живе інлайном у <head> `console.html`. Там він
// потрібен ДО першого кадру: цей модуль вантажиться після парсингу <head>,
// тобто вже після того, як браузер намалював сторінку. Ключ (THEME_KEY) і
// порядок рішень в обох місцях мусять збігатися — інакше перший кадр буде
// однієї теми, а другий іншої.

export const THEME_KEY = 'nyshporka.theme';

const MODES = ['auto', 'light', 'dark'];
const mql = matchMedia('(prefers-color-scheme: light)');

/** Що ВИБРАВ користувач: 'auto' | 'light' | 'dark'. */
export function themeMode() {
  let v = null;
  // localStorage кидає в приватному режимі й за жорсткої політики куків —
  // консоль від цього падати не мусить, просто працює як «авто».
  try { v = localStorage.getItem(THEME_KEY); } catch (e) { /* нема — то й нема */ }
  return (v === 'light' || v === 'dark') ? v : 'auto';
}

/** Що РЕАЛЬНО намальовано: 'light' | 'dark'. */
export function themeEffective() {
  const m = themeMode();
  return m === 'auto' ? (mql.matches ? 'light' : 'dark') : m;
}

const ICO   = { auto: 'contrast', light: 'sun',  dark: 'moon' };
const TITLE = { auto: 'тема: за системою', light: 'тема: світла', dark: 'тема: темна' };

function paintButton() {
  const b = document.getElementById('theme-btn');
  if (!b) return;
  const m = themeMode();
  // Значок показує ПОТОЧНИЙ режим, а не наступний: інакше стан «авто»
  // нічим показати, і кнопка перестає бути індикатором.
  b.innerHTML = `<svg class="ic ic-o" aria-hidden="true"><use href="#i-${ICO[m]}"/></svg>`;
  b.title = TITLE[m] + ' · клік — наступна';
  b.setAttribute('aria-label', TITLE[m]);
}

function apply() {
  const eff = themeEffective();
  const root = document.documentElement;
  root.dataset.theme = eff;
  // Рідні елементи (попап <select>, спінери, календар, дефолтний скролбар)
  // інакше лишаються темними всередині світлої сторінки.
  const cs = document.querySelector('meta[name="color-scheme"]');
  if (cs) cs.setAttribute('content', eff);
  // Смуга браузера на телефоні (консоль відкривають через Cloudflare-тунель)
  // стоїть впритул до <header>, тож мусить збігатися з --s-0. Читаємо саме
  // з токена, щоб значення не могло розійтися з кольором шапки.
  const tc = document.querySelector('meta[name="theme-color"]');
  if (tc) {
    tc.setAttribute('content',
      getComputedStyle(root).getPropertyValue('--s-0').trim() || '#111');
  }
  paintButton();
}

/** Клік по кнопці: авто → світла → темна → авто. */
export function cycleTheme() {
  const next = MODES[(MODES.indexOf(themeMode()) + 1) % MODES.length];
  try {
    // «авто» — це ВІДСУТНІСТЬ запису, а не значення 'auto': інакше вкладка,
    // відкрита до появи перемикача, і вкладка після скидання поводились би
    // по-різному.
    if (next === 'auto') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, next);
  } catch (e) { /* приватний режим — тема доживе до перезавантаження */ }
  apply();
}

export function initTheme() {
  apply();
  // Зміна системної теми діє ЛИШЕ поки вибір «авто» — інакше явний вибір
  // користувача мовчки скасовувався б заходом сонця.
  mql.addEventListener('change', () => { if (themeMode() === 'auto') apply(); });
}

/** Значення токена рядком — для canvas і решти місць, де `var()` не працює. */
export const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
