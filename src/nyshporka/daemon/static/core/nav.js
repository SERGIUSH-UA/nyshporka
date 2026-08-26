/** Секції, шапка, перехід між екранами й черга робіт. */
import { t, LANG } from './strings.js';
import { callOp, FINAL_STATES } from './net.js';
import { esc, el, setView, curGen, bumpGen, alive } from './view.js';
import { SCREENS, OP_SCREEN } from './registry.js';
import { ST } from './state.js';
import { ic } from '/ui/icons.js';

/** Скільки робіт зараз іде — щоб значок у шапці не залежав від розділу. */
let RUNNING_JOBS = 0;

// ── секції ───────────────────────────────────────────────────────────────────
/**
 * Що ввімкнено в цьому просторі. Приходить із `/api/sections`, тобто з того
 * самого `core.sections`, який фільтрує операції на сервері.
 *
 * 🔴 Другого переліку екранів тут немає навмисно. Мапа «екран → секція» їде
 * полем `screens` тієї ж відповіді: копія в браузері розходилась би з сервером
 * тихо, і виглядало б це як кнопка, що веде в порожнечу.
 */
let SECTIONS = { sections: [], screens: {}, op_screen: {}, presets: {},
  preset: null, glyphs: {} };

/** Порядок кнопок у шапці. Екрани, яких тут немає, кнопки не отримують. */
const NAV_ORDER = ['home', 'profile', 'sources', 'geog', 'fonds', 'library', 'frames', 'cases', 'newcase',
  'read', 'runs', 'view', 'eye', 'search', 'sift', 'export', 'jobs'];

/** Ключ i18n для кнопки екрана. Підпис «Завести справу» вже є в словнику. */
const NAV_LABEL = {
  home: 'nav.home', profile: 'nav.profile', sources: 'nav.sources', geog: 'nav.geog', fonds: 'nav.fonds',
  library: 'nav.library', frames: 'nav.frames', cases: 'nav.cases', newcase: 'nav.newcase', read: 'nav.read', runs: 'nav.runs', view: 'nav.view',
  eye: 'nav.eye', search: 'nav.search', sift: 'nav.sift', export: 'nav.export', jobs: 'nav.jobs',
};

/** Чи ввімкнена секція цього екрана. Невідомий екран не блокуємо. */
function screenOn(screen) {
  const sid = SECTIONS.screens[screen];
  if (!sid) return true;
  const sec = SECTIONS.sections.find((s) => s.id === sid);
  return !sec || (sec.active && sec.visible);
}

async function loadSections() {
  try {
    const res = await fetch('/api/sections');
    const env = await res.json();
    // 🔴 доповнюємо дефолт, а не заміщаємо його. Пряме присвоєння вірить, що
    // відповідь має рівно ту форму, якої ми чекаємо, — і коли в ній бракує
    // `screens`, наступний же `SECTIONS.screens[s]` кидає TypeError посеред
    // побудови шапки. Це падіння на старті: `boot` не доходить до першого
    // екрана, і застосунок лишається порожньою сторінкою без жодного слова.
    // Обірвана відповідь довідки не має права гасити весь застосунок.
    if (env.ok) SECTIONS = { ...SECTIONS, ...(env.data || {}) };
    // Мапа «операція → екран» кладеться в реєстр, а не лишається тут: її
    // читає `view.renderNext`, а той не сміє імпортувати цей модуль — вийшов
    // би цикл, який ламається не там, де його завели.
    Object.assign(OP_SCREEN, SECTIONS.op_screen || {});
  } catch {
    // Мережі немає — лишаємо порожній стан: тоді `screenOn` пропускає все, і
    // застосунок працює як раніше. Замикати UI через збій довідки не можна.
  }
  renderNav();
}

/**
 * Розділ, чиї екрани показані нижнім ярусом.
 *
 * Виводиться з поточного екрана, а не зберігається окремим станом: два джерела
 * правди про «де я» розходяться при першому ж переході за посиланням, і
 * виглядає це як підсвічений розділ, у якому відкритого екрана немає.
 */
let GROUP = null;

/** Розділи, у яких є хоч один доступний екран, у порядку сервера. */
function navGroups() {
  return (SECTIONS.sections || []).filter(
    (s) => s.visible && s.active && (s.screens || []).some((x) => NAV_ORDER.includes(x)));
}

/** Екрани розділу — у порядку `NAV_ORDER`, а не в порядку відповіді. */
function groupScreens(sid) {
  return NAV_ORDER.filter((s) => SECTIONS.screens[s] === sid && screenOn(s));
}

/**
 * Дві смуги: розділи зверху, екрани активного розділу під ними.
 *
 * 🔴 Одним рядом кнопок було дванадцять, і на вузькому екрані ряд ставав стіною
 * без ієрархії. Групування береться з секцій — тих самих, якими вмикають
 * частини застосунку, — а не з окремого переліку: другий список розходився б
 * із дозволеним тихо.
 *
 * Знак приходить із сервера (`brand.yaml`), а не з переліку тут. Значка немає —
 * кнопка лишається підписом, а не ламається.
 */
function renderNav() {
  const tabs = el('nav');
  const subs = el('subnav');
  if (!tabs) return;
  const groups = navGroups();
  if (!GROUP || !groups.some((g) => g.id === GROUP)) GROUP = (groups[0] || {}).id || null;

  const sicons = (SECTIONS.icons && SECTIONS.icons.sections) || {};
  tabs.innerHTML = groups.map((g) => {
    const label = esc(LANG === 'en' ? g.label_en || g.label : g.label);
    return `<button data-act="group" data-arg="${esc(g.id)}"`
      + `${g.id === GROUP ? ' class="on"' : ''}>${icon(sicons[g.id])}${label}</button>`;
  }).join('');

  if (!subs) return;
  const icons = (SECTIONS.icons && SECTIONS.icons.screens) || {};
  const here = (location.hash || '').slice(1);
  subs.innerHTML = groupScreens(GROUP).map((s) => {
    // 🔴 Значок малюється одразу з відомим числом. Він живе лише в підсмузі
    // розділу «core», тож при поверненні з іншого розділу з'являвся порожнім
    // і наповнювався аж наступною ітерацією `watchJobs` — а та блокується на
    // сервері до 25 с. Виглядало як «лічильник зник».
    const tail = s === 'jobs'
      ? `<sup id="jobcount">${RUNNING_JOBS || ''}</sup>` : '';
    return `<button data-act="nav" data-arg="${s}"${s === here ? ' class="on"' : ''}>`
      + `${icon(icons[s])}${esc(t(NAV_LABEL[s] || s))}</button>${tail}`;
  }).join('');
}

/** Значок спрайта або порожньо — підпис кнопки читається й без нього. */
function icon(name) {
  return name ? ic(name, 'ic-sm') + ' ' : '';
}

// ── навігація ────────────────────────────────────────────────────────────────
/** Екран, який показано зараз. Потрібен слухачеві історії: без нього
 *  «Назад» не відрізнити від власного запису `show()` у хеш, і кожен
 *  перехід замикався б у нескінченну пару викликів. */
/** Екрани, чий вміст не вміщається у вузьку колонку.
 *
 * ⚠ `home` тут не через таблицю, а через розкладку: дашборд стоїть на сітках,
 * які самі вирішують, скільки колонок брати (`auto-fit`). У 62rem вони
 * схлопуються до двох, тож плитки переносяться по одній у хвості, а розрізи
 * «за архівами» й «за повітами» стають одне під одним — тобто обмеження,
 * поставлене заради довжини рядка, з'їдає екран, на якому тексту майже немає.
 */
const WIDE_SCREENS = ['home', 'fonds', 'library', 'runs'];

let CURRENT = '';
export const currentScreen = () => CURRENT;

async function show(screen) {
  // 🔴 Екран вимкненої секції не мовчить і не показує порожнечу. Сюди
  // потрапляють через закладку чи посилання з часів, коли секція була
  // ввімкнена, — і «нічого не сталось» тут читається як поламаний застосунок.
  if (!screenOn(screen)) {
    // Покоління зростає і тут: інакше запит, що летить із попереднього екрана,
    // домальовує свою таблицю поверх банера про вимкнену секцію.
    bumpGen();
    CURRENT = screen;
    const sid = SECTIONS.screens[screen];
    const sec = SECTIONS.sections.find((s) => s.id === sid) || {};
    const label = LANG === 'en' ? sec.label_en : sec.label;
    location.hash = screen;
    document.querySelectorAll('nav button').forEach((b) => b.classList.remove('on'));
    setView(`<div class="warn">${t('sect.off.msg')}: <b>${esc(label || sid)}</b>
      <p class="muted">${esc(LANG === 'en' ? sec.why_en || '' : sec.why || '')}</p>
      <button data-act="sections.toggle" data-arg="${esc(sid)}"
        data-back="${esc(screen)}">${t('sect.on')}</button>
      <button data-act="nav" data-arg="settings">⚙ ${t('sect.title')}</button></div>`);
    return;
  }
  const fn = SCREENS[screen] || SCREENS.home;
  // Усе, що малювалось досі, стає неактуальним рівно тут.
  bumpGen();
  CURRENT = screen;
  location.hash = screen;
  // Розділ іде за екраном: перехід за посиланням чи закладкою мусить
  // підсвітити ту саму пару, що й клік по кнопці.
  const sid = SECTIONS.screens[screen];
  if (sid && sid !== GROUP) GROUP = sid;
  // Ширина йде за екраном: таблиці на десять колонок у 62rem злипаються, а
  // текстові екрани в повну ширину монітора читати важче. Перелік тут, а не
  // в кожному екрані, бо це властивість розкладки, а не змісту.
  const main = document.querySelector('main');
  if (main) main.classList.toggle('wide', WIDE_SCREENS.includes(screen));
  renderNav();
  await fn();
}

// ── черга ────────────────────────────────────────────────────────────────────
let cursor = 0;

/**
 * Хто чекає на конкретну роботу: `job_id` → колбек зі свіжим записом.
 *
 * 🔴 Кнопка, після якої людину викидає на іншу вкладку, — це втрата місця. Вона
 * запустила завантаження, дивлячись на рядок справи, а опинялась у переліку
 * робіт, де той рядок ніяк не названо: щоб зрозуміти, котра з робіт її, треба
 * читати заголовки. Повернутись назад теж нічим — фільтр і сторінка втрачені.
 *
 * Тому прогрес малюється там, звідки його запустили, а перекидання лишається
 * лише тим, хто справді пішов дивитись чергу.
 */
const JOB_WATCH = new Map();

/**
 * Стежити за роботою. Повертає функцію відписки.
 *
 * ⚠ Підписник живе доти, доки робота не стала фінальною, або доки його не
 * зняли: екран міг перемалюватись, і вузол, у який він писав, уже не в DOM.
 */
export function onJob(jobId, cb) {
  if (!jobId) return () => {};
  const list = JOB_WATCH.get(jobId) || [];
  list.push(cb);
  JOB_WATCH.set(jobId, list);
  return () => {
    const cur = (JOB_WATCH.get(jobId) || []).filter((f) => f !== cb);
    if (cur.length) JOB_WATCH.set(jobId, cur);
    else JOB_WATCH.delete(jobId);
  };
}

/** Компактний стан роботи — рядком, для місця, звідки її запустили. */
export function jobChip(j) {
  if (!j) return '';
  const p = j.progress || {};
  const pct = p.n ? ` ${Math.round((p.i / p.n) * 100)}%` : '';
  const num = p.n ? ` ${p.i}/${p.n}` : '';
  if (j.state === 'error') {
    return `<span class="warn-inline" title="${esc(j.error || '')}">${t('job.failed')}</span>`;
  }
  if (j.state === 'done') return `<span class="ok-line">${t('job.done')}</span>`;
  if (j.state === 'cancelled') return `<span class="muted">${t('job.cancelled')}</span>`;
  return `<span class="muted mono">${t('job.going')}${pct || num}</span>`;
}

/**
 * Смуга поступу — тільки коли є чим міряти.
 *
 * 🔴 «0/0 робота» під порожньою смугою читається як «нічого не зроблено», хоча
 * означає протилежне: робота не рахується кроками (обхід сайту не знає
 * заздалегідь, скільки їх буде). Порожній знаменник тут — те саме, що нуль без
 * знаменника в пошуку: число, яке виглядає як відповідь і нею не є.
 */
function jobProgress(j) {
  const p = j.progress || {};
  if (!p.n) return '';
  return `<progress value="${p.i}" max="${p.n}"></progress>
    <span class="mono">${p.i}/${p.n} ${esc(p.basis || '')}</span>`;
}

/** Стан роботи людською мовою: сирий `done`/`running` в українському
 *  інтерфейсі був єдиним місцем, де назовні лізли внутрішні коди. */
function jobState(state) {
  const key = `jobs.st.${state}`;
  const got = t(key);
  return got === key ? state : got;
}

/**
 * Попередження роботи.
 *
 * 🔴 Вони винесені з `result` навмисно (див. `core/jobs.py`): саме там їде
 * знаменник довгого пошуку. Не показавши їх, екран перетворює «прочесано 400 з
 * 1142» на просто «готово».
 */
function jobNotes(j) {
  const notes = (j.warnings || []).map(
    (w) => `<div class="warn">⚠ ${esc(w.text || '')}</div>`);
  // 🔴 І кнопка, а не лише текст. Довга робота часто не остання в ланцюжку
  // («зібране лягло окремим файлом; звести джерела в реєстр»), і поки поради
  // йшли самим текстом із командою терміналу, вони називали наступний крок
  // тому, хто працює з браузера й набирати команду нема куди. Попередження без
  // виходу перестає бути попередженням.
  for (const n of j.next || []) {
    const scr = OP_SCREEN[n.op];
    const label = scr ? t(NAV_LABEL[scr] || scr) : n.op;
    const btn = scr
      ? `<button data-act="nav" data-arg="${esc(scr)}">${esc(label)} →</button>`
      : `<span class="mono">${esc(n.op)}</span>`;
    notes.push(`<div class="warn next">${btn} <span>${esc(n.why || '')}</span></div>`);
  }
  return notes.join('');
}

/**
 * Що робота принесла.
 *
 * 🔴 `result` приїздив у відповіді черги від самого початку й не рендерився
 * ніде. Робота, яка завершилась, поки людина була на іншому екрані, віддавала
 * свій результат у нікуди — а за вікном ретенції зникала й сама.
 *
 * Показуються лише скалярні поля: усередині бувають цілі переліки хітів, і
 * вивалювати їх у смугу черги означало б зробити її нечитною.
 */
function jobResult(j) {
  const res = j.result;
  if (!res || typeof res !== 'object') return '';
  const bits = Object.entries(res)
    .filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
    // 🔴 Лише поля з людським підписом. Сире ім'я поля в смузі результату
    // читається не так, як означає: `kept` — це «рядки чужих описів, яких
    // запуск не чіпав», тобто на першому зборі він нульовий за визначенням,
    // а поруч із «рядків: 229» читався як «залишено 0 з 229», тобто як втрата
    // всієї роботи. Невідоме поле краще не показати, ніж показати сирим.
    .filter(([k, v]) => t(`jobs.res.${k}`) !== `jobs.res.${k}`
      && !(ZERO_IS_NOISE.includes(k) && Number(v) === 0))
    .map(([k, v]) => `${esc(t(`jobs.res.${k}`))}: ${esc(String(v))}`);
  if (!bits.length) return '';
  return `<div class="muted mono">${t('jobs.result')} — ${bits.join(' · ')}</div>`;
}

/** Поля, чий нуль не є новиною: він означає «нічого такого не траплялось». */
const ZERO_IS_NOISE = ['kept', 'skipped', 'errors', 'failed'];

async function refreshJobs() {
  const res = await fetch(`/api/jobs?since=${cursor}`);
  const data = await res.json();
  cursor = data.seq;
  const box = el('jobs');
  if (!box) return;
  // 🔴 Вікно ретенції — на всі фінальні стани, а не лише на «готово»:
  // журнал робіт лежить на диску й переживає рестарти, тож помилка
  // тижневої давнини висіла в списку «Що зараз робиться» вічно.
  //
  // 🔴 Але й п'ять хвилин — не вікно. Довгі роботи ставлять на ніч, і зранку
  // екран казав «наразі нічого не виконується»: ні що бігало, ні чи впало, ні
  // куди дивитись за результатом. Півдоби покривають нічний прогін, а старе
  // однаково відсіється.
  const jobs = (data.jobs || []).filter(
    (j) => !FINAL_STATES.includes(j.state) || Date.now() / 1000 - j.updated < 43200);
  box.innerHTML = jobs.length ? jobs.map((j) => `
    <div class="job">
      <b>${esc(j.title || j.kind)}</b> <span class="muted">${esc(jobState(j.state))}</span>
      ${jobProgress(j)}
      ${j.error ? `<div class="warn err">${esc(j.error)}</div>` : ''}
      ${jobNotes(j)}
      ${jobResult(j)}
      ${j.state === 'running' || j.state === 'queued'
        ? `<button data-act="jobs.cancel" data-job="${esc(j.id)}">${t('jobs.cancel')}</button>` : ''}
    </div>`).join('') : `<p class="muted">${t('jobs.none')}</p>`;
}

/** Довге очікування на сервері: одне з'єднання замість опитувань щосекунди. */
async function watchJobs() {
  for (;;) {
    try {
      const res = await fetch(`/api/jobs/wait?since=${cursor}&timeout_s=25`);
      const data = await res.json();
      cursor = data.seq;
      if (el('jobs')) await refreshJobs();
      const running = (data.jobs || []).filter((j) => j.state === 'running' || j.state === 'queued');
      // Лічильник живе в кнопці «Роботи», яку ставить `renderNav` — до першої
      // побудови шапки його ще немає.
      // Число тримається в модулі: шапка перемальовується при кожній зміні
      // розділу, а робота триває незалежно від того, куди пішла людина.
      // Кожна робота, на яку хтось чекає, будить своїх підписників — і саме
      // так прогрес доїжджає до рядка таблиці чи до форми, а не лише до
      // переліку робіт.
      for (const j of data.jobs || []) {
        for (const cb of JOB_WATCH.get(j.id) || []) {
          try { cb(j); } catch { /* підписник не має права спиняти чергу */ }
        }
        if (FINAL_STATES.includes(j.state)) JOB_WATCH.delete(j.id);
      }
      RUNNING_JOBS = running.length;
      const badge = el('jobcount');
      if (badge) badge.textContent = running.length ? String(running.length) : '';
      // 🐾 Знак у шапці показує, що робота йде. Саме процес: результату він не
      // повідомляє — це справа тексту, який несе знаменник.
      const paw = document.querySelector('.mark');
      if (paw) paw.classList.toggle('busy', running.length > 0);
    } catch {
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

/** Розділ, відкритий у шапці. Ставиться сетером: пряме присвоєння з
 *  іншого модуля мовчки не спрацювало б, і смуга екранів лишалась би на
 *  попередньому розділі. */
export const setGroup = (v) => { GROUP = v; };

/**
 * Оновити довідку секцій із відповіді `sections.show` / `sections.set`.
 *
 * 🔴 Сетер, а не присвоєння ззовні. `SECTIONS` — імпортоване зв'язування, і
 * `SECTIONS = env.data` в іншому модулі не «мовчки не спрацьовує», а кидає
 * `TypeError: Assignment to constant variable` посеред малювання. Екран
 * налаштувань саме на цьому й спинявся: спінер лишався назавжди, а кнопка
 * «Увімкнути секцію» робила серверну зміну успішно й падала до `renderNav()` —
 * тобто виглядала мертвою, хоча секція вже була ввімкнена.
 *
 * 🔴 доповнюємо дефолт, а не заміщаємо — з тієї ж причини, що й у
 * `loadSections`: без `screens` наступний `SECTIONS.screens[s]` валить шапку.
 */
export const setSections = (data) => {
  SECTIONS = { ...SECTIONS, ...(data || {}) };
  Object.assign(OP_SCREEN, SECTIONS.op_screen || {});
};

/**
 * Перейти на екран, засіявши його тим, з чого прийшли.
 *
 * 🔴 Одна функція на всі переходи, а не поле в `ST` на кожну пару екранів.
 * Пар багато — опис ↔ бібліотека ↔ прогони ↔ газетир ↔ приймальня, — і кожен
 * новий механізм передачі це ще одне місце, де посів мовчки не доїде.
 *
 * Посів кладеться в `ST[екран]`, і читає його сам цільовий екран: він один
 * знає, що з ним робити. Вихідний екран нічого не підробляє — ні події форми,
 * ні значень полів.
 */
export async function goto(screen, seed) {
  ST[screen] = seed === undefined ? null : seed;
  await show(screen);
}

export { SECTIONS, NAV_ORDER, NAV_LABEL, GROUP, screenOn, loadSections,
  navGroups, groupScreens, renderNav, icon, show, refreshJobs, watchJobs,
  RUNNING_JOBS };
