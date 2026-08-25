/**
 * Нишпорка — браузерне обличчя.
 *
 * 🔴 РЕЄСТР ДІЙ, а не глобали й інлайн-onclick. У попередньому конвеєрі 26
 * файлів клали функції у `window` і вішали `onclick="doThing()"` прямо в
 * розмітці. Колізія імен між двома файлами не видна ні в дифі, ні в консолі:
 * пізніший просто перекриває раніший, і кнопка починає робити чуже. Тут кнопка
 * несе `data-act="ім'я"`, а обробники живуть у `ACTIONS`; невідома дія —
 * гучна помилка, а не тиша.
 *
 * 🔴 БЕЗ ЗБИРАЧА, і це рішення, а не лінощі. Збирач у застосунку, який ставлять
 * подвійним кліком, означає Node у складі релізу або зібраний бандл у git.
 * Три речі, заради яких він був потрібен, вирішені інакше: хеші імен — версією
 * у запиті (її дає сам сервер), переклад — словником нижче, типи форм — тим,
 * що фронт бере СХЕМИ операцій із `/api/ops`, а не переписує поля руками.
 * Останнє сильніше за згенеровані типи: переписане може протухнути, взяте з
 * сервера — ні.
 *
 * Компоненти, спільні з консоллю приватного конвеєра, приходять із `/ui/**` —
 * теки, яку сервер монтує з пакета. Це не «бібліотека для гарного вигляду»:
 * доти обидві морди мали власні значки, власний перемикач теми й власні
 * контролі, і розходились вони тихо.
 */
import { initTheme, cycleTheme } from '/ui/theme.js';
import { LANG, setLang, t } from './core/strings.js';
import { esc, el, setView, curGen, alive } from './core/view.js';
import { ACTIONS, KEYS, SCREENS } from './core/registry.js';
import { SECTIONS, loadSections, renderNav, groupScreens, show,
  refreshJobs, watchJobs, setGroup } from './core/nav.js';

// 🔴 Екрани імпортуються заради РЕЄСТРАЦІЇ: кожен модуль дописує себе в
// `SCREENS`/`ACTIONS`. Без цього рядка екран існує у файлі й не існує в
// застосунку — рівно та тиша, проти якої зроблено реєстр.
import './screens/home.js';
import './screens/sources.js';
import './screens/cases.js';
import './screens/library.js';
import './screens/frames.js';
import './screens/geog.js';
import './screens/fonds.js';
import './screens/search.js';
import './screens/sift.js';
import './screens/eye.js';
import './screens/view.js';
import './screens/read.js';
import './screens/runs.js';
import './screens/export.js';
import './screens/jobs.js';
import './screens/settings.js';

Object.assign(ACTIONS, {
  nav: (_ev, elm) => show(elm.dataset.arg),

  /** Клік по розділу веде на його ПЕРШИЙ екран, а не просто перемальовує
      смугу: розділ без відкритого екрана виглядав би як кнопка, що нічого не
      робить. */
  group: (_ev, elm) => {
    setGroup(elm.dataset.arg);
    const first = groupScreens(elm.dataset.arg)[0];
    return first ? show(first) : renderNav();
  },

  /** Тема: авто → світла → темна → авто. Значок показує ПОТОЧНИЙ режим. */
  'theme.cycle': () => cycleTheme(),

  'lang.toggle': () => {
    setLang(LANG === 'uk' ? 'en' : 'uk');
    location.reload();
  },
});

// Одна точка входу на всі кліки й сабміти. `data-act` — єдиний спосіб повісити
// поведінку; інлайн-onclick у розмітці немає ніде.
function dispatch(ev) {
  const elm = ev.target.closest('[data-act]');
  if (!elm) return;
  // 🔴 Форма реагує ТІЛЬКИ на `submit`. Без цієї межі будь-яка подія з поля
  // всередині `<form data-act="…">` спливала б до самої форми й кликала її
  // дію — а та бере `new FormData(ev.target)`, де `ev.target` уже поле, не
  // форма: `TypeError: parameter 1 is not of type 'HTMLFormElement'`.
  //
  // ⚠ Той самий шлях через `click` мав наслідок, гірший за виняток: клік по
  // чекбоксу «узяти теку під облік» діставав `ev.preventDefault()` від дії
  // форми, і браузер скасовував перемикання — галочку неможливо було
  // поставити взагалі, і виглядало це як мертвий чекбокс, а не як помилка.
  if (ev.type !== 'submit' && elm.tagName === 'FORM') return;
  // 🔴 Те саме для полів: їхня подія — `change` (або `input` із `data-live`),
  // а не `click`. Диспетчер висить на обох, тож клік по `<select>`/чекбоксу
  // давав ДВА проходи: один зі старим значенням (у момент кліку), другий зі
  // свіжим. Клік у текстове поле просто щоб поставити каретку теж запускав
  // повний прохід по бібліотеці. Видимої вади не було — її ховав `_libSeq`, —
  // зате кожна взаємодія коштувала вдвічі, а на 1200 справах це відчутно.
  if (ev.type === 'click'
      && ['INPUT', 'SELECT', 'TEXTAREA', 'OPTION'].includes(elm.tagName)) return;
  const name = elm.dataset.act;
  const fn = ACTIONS[name];
  if (!fn) {
    // 🔴 Гучно. Мовчазний «нічого не сталось» — це та сама вада, що й колізія
    // глобалів: кнопка є, натискається, і не робить нічого.
    console.error(`невідома дія: ${name}`);
    alert(`невідома дія: ${name}`);
    return;
  }
  fn(ev, elm);
}
document.addEventListener('click', dispatch);
document.addEventListener('submit', dispatch);
// Селекти й чекбокси клік не диспетчить: `change` — це їхня подія. Без цього
// фільтр із випадним списком виглядає робочим і мовчки нічого не міняє.
document.addEventListener('change', dispatch);

/**
 * Набір у полі — окремо, і ЗАВЖДИ з паузою.
 *
 * ⚠ Без дебаунса кожна натиснута клавіша — окремий запит: десять символів
 * прізвища дають десять проходів по бібліотеці, і останній не обов'язково
 * повертається останнім. Пауза прибирає більшість, порядок відповідей
 * стереже лічильник на боці екрана.
 *
 * Реагують лише поля з `data-live`: решта чекає на `change`, тобто на те, що
 * людина закінчила вводити.
 */
let _liveTimer = null;
document.addEventListener('input', (ev) => {
  const elm = ev.target.closest('[data-act][data-live]');
  if (!elm) return;
  clearTimeout(_liveTimer);
  const gen = curGen();
  _liveTimer = setTimeout(() => {
    // 🔴 За 250 мс людина могла піти з екрана. Тоді поле вже від'єднане, але
    // `data-act` на ньому лишився — дія викликалась і читала `(el('lib-q') ||
    // {}).value`, тобто ПОРОЖНЬО, і мовчки скидала збережений фільтр
    // бібліотеки. Наступний вхід у бібліотеку показував «нічого не набрано».
    if (!alive(gen) || !document.contains(elm)) return;
    dispatch(ev);
  }, 250);
});

// ── клавіші ──────────────────────────────────────────────────────────────────
/**
 * Гарячі клавіші розбору.
 *
 * 🔴 Свій роутер, а не спільний із консоллю: там він знає про лабораторні
 * вкладки (банк розмітки, синтетику) і тягне їх за собою імпортом. Спільним
 * шаром він стати не може, і копіювати його сюди означало б привезти
 * півсотні прив'язок до екранів, яких тут немає.
 *
 * ⚠ Клавіші діють лише там, де НЕ вводять текст. Інакше «н» у полі прізвища
 * гортало б знахідки замість того, щоб набиратись, — і виглядало б це як
 * поламане поле, а не як гаряча клавіша.
 */

document.addEventListener('keydown', (ev) => {
  const tag = (ev.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select'
      || ev.target.isContentEditable) return;
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const screen = (location.hash || '#home').slice(1);
  const fn = (KEYS[screen] || {})[ev.key];
  if (!fn) return;
  ev.preventDefault();
  fn();
});

// ── старт ────────────────────────────────────────────────────────────────────
async function boot() {
  document.querySelectorAll('[data-i18n]').forEach((n) => {
    n.textContent = t(n.dataset.i18n);
  });
  // Тема — ПЕРЕД мережею: вона малює кнопку в шапці й вішає слухач системної
  // налаштованості, і затримка тут дала б видимий стрибок вигляду вже після
  // того, як сторінка намальована.
  initTheme();
  // Спершу довідка про секції, і лише потім екран: інакше перший показ ішов би
  // з порожнім переліком, тобто пускав би на екран, якого в цьому просторі немає.
  await loadSections();
  await show((location.hash || '#home').slice(1));
  watchJobs();
}
boot();
