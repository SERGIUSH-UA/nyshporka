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
 * 🔴 Другого переліку екранів тут НЕМАЄ навмисно. Мапа «екран → секція» їде
 * полем `screens` тієї ж відповіді: копія в браузері розходилась би з сервером
 * тихо, і виглядало б це як кнопка, що веде в порожнечу.
 */
let SECTIONS = { sections: [], screens: {}, op_screen: {}, presets: {},
  preset: null, glyphs: {} };

/** Порядок кнопок у шапці. Екрани, яких тут немає, кнопки не отримують. */
const NAV_ORDER = ['home', 'sources', 'geog', 'fonds', 'library', 'frames', 'cases', 'newcase',
  'read', 'runs', 'view', 'eye', 'search', 'sift', 'export', 'jobs'];

/** Ключ i18n для кнопки екрана. Підпис «Завести справу» вже є в словнику. */
const NAV_LABEL = {
  home: 'nav.home', sources: 'nav.sources', geog: 'nav.geog', fonds: 'nav.fonds',
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
    // 🔴 ДОПОВНЮЄМО дефолт, а не заміщаємо його. Пряме присвоєння вірить, що
    // відповідь має рівно ту форму, якої ми чекаємо, — і коли в ній бракує
    // `screens`, наступний же `SECTIONS.screens[s]` кидає TypeError ПОСЕРЕД
    // побудови шапки. Це падіння на СТАРТІ: `boot` не доходить до першого
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
 * без ієрархії. Групування береться з СЕКЦІЙ — тих самих, якими вмикають
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
    // 🔴 Значок малюється ОДРАЗУ з відомим числом. Він живе лише в підсмузі
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
async function show(screen) {
  // 🔴 Екран вимкненої секції не мовчить і не показує порожнечу. Сюди
  // потрапляють через закладку чи посилання з часів, коли секція була
  // ввімкнена, — і «нічого не сталось» тут читається як поламаний застосунок.
  if (!screenOn(screen)) {
    // Покоління зростає і тут: інакше запит, що летить із попереднього екрана,
    // домальовує свою таблицю поверх банера про вимкнену секцію.
    bumpGen();
    const sid = SECTIONS.screens[screen];
    const sec = SECTIONS.sections.find((s) => s.id === sid) || {};
    const label = LANG === 'en' ? sec.label_en : sec.label;
    location.hash = screen;
    document.querySelectorAll('nav button').forEach((b) => b.classList.remove('on'));
    setView(`<div class="warn">${t('sect.off.msg')}: <b>${esc(label || sid)}</b>
      <p class="muted">${esc(LANG === 'en' ? sec.why_en || '' : sec.why || '')}</p>
      <button data-act="sections.toggle" data-arg="${esc(sid)}">${t('sect.on')}</button>
      <button data-act="nav" data-arg="settings">⚙ ${t('sect.title')}</button></div>`);
    return;
  }
  const fn = SCREENS[screen] || SCREENS.home;
  // Усе, що малювалось досі, стає неактуальним рівно тут.
  bumpGen();
  location.hash = screen;
  // Розділ іде за екраном: перехід за посиланням чи закладкою мусить
  // підсвітити ту саму пару, що й клік по кнопці.
  const sid = SECTIONS.screens[screen];
  if (sid && sid !== GROUP) GROUP = sid;
  renderNav();
  await fn();
}

// ── черга ────────────────────────────────────────────────────────────────────
let cursor = 0;

async function refreshJobs() {
  const res = await fetch(`/api/jobs?since=${cursor}`);
  const data = await res.json();
  cursor = data.seq;
  const box = el('jobs');
  if (!box) return;
  // 🔴 Вікно ретенції — на ВСІ фінальні стани, а не лише на «готово»:
  // журнал робіт лежить на диску й переживає рестарти, тож помилка
  // тижневої давнини висіла в списку «Що зараз робиться» вічно.
  const jobs = (data.jobs || []).filter(
    (j) => !FINAL_STATES.includes(j.state) || Date.now() / 1000 - j.updated < 300);
  box.innerHTML = jobs.length ? jobs.map((j) => `
    <div class="job">
      <b>${esc(j.title || j.kind)}</b> <span class="muted">${esc(j.state)}</span>
      <progress value="${j.progress.i}" max="${j.progress.n || 1}"></progress>
      <span class="mono">${j.progress.i}/${j.progress.n} ${esc(j.progress.basis)}</span>
      ${j.error ? `<div class="warn err">${esc(j.error)}</div>` : ''}
      ${j.state === 'running' || j.state === 'queued'
        ? `<button data-act="jobs.cancel" data-job="${esc(j.id)}">${t('jobs.cancel')}</button>` : ''}
    </div>`).join('') : `<p class="muted">${t('jobs.none')}</p>`;
}

/** Довге очікування на СЕРВЕРІ: одне з'єднання замість опитувань щосекунди. */
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
      RUNNING_JOBS = running.length;
      const badge = el('jobcount');
      if (badge) badge.textContent = running.length ? String(running.length) : '';
      // 🐾 Знак у шапці показує, що робота йде. Саме ПРОЦЕС: результату він не
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
 * Перейти на екран, ЗАСІЯВШИ його тим, з чого прийшли.
 *
 * 🔴 Одна функція на всі переходи, а не поле в `ST` на кожну пару екранів.
 * Пар багато — опис ↔ бібліотека ↔ прогони ↔ газетир ↔ приймальня, — і кожен
 * новий механізм передачі це ще одне місце, де посів мовчки не доїде.
 *
 * Посів кладеться в `ST[екран]`, і читає його САМ цільовий екран: він один
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
