/** Секції, шапка, перехід між екранами й черга робіт. */
import { t, tOr } from './strings.js';
import { callOp, FINAL_STATES, apiFetch } from './net.js';
import { esc, el, setView, setViewTarget, curGen, bumpGen, alive, maskot, busy, paints,
  splitWarnings, notesBlock, seedAttr, emptyMini } from './view.js';
import { openModal, closeModal, modalOpen, modalTitle } from './modal.js';
import { SCREENS, OP_SCREEN } from './registry.js';
import { ST } from './state.js';
import { projectChip, loadProjects, projectsNow, projectInfo, currentPid } from './projects.js';
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
  preset: null, glyphs: {}, nav: [], blocks: [], layers: {}, project_screens: [],
  screen_action: {}, hub_only: false };

/** Порядок кнопок у шапці. Екрани, яких тут немає, кнопки не отримують. */
// 🔴 «Пошук» — одразу після «Огляду»: заради нього застосунок і ставлять. І
// «Розбір» перед «Оком»: «Дослідження» відкривалось на «Оці», тобто на обліку
// переглянутого, а не на роботі з кандидатами (холодний прохід 07.10.2026).
const NAV_ORDER = ['home', 'search', 'canon', 'hyp', 'research', 'profile', 'sources', 'geog', 'fonds',
  'library', 'frames', 'cases', 'read', 'queue', 'runs', 'cloud', 'view', 'sift', 'eye', 'export', 'site',
  'history', 'give', 'pull', 'cards', 'sets', 'label', 'jobs', 'projects', 'status', 'settings'];

/**
 * Екрани-кроки без власної вкладки → вкладка, яку підсвічувати.
 *
 * 🔴 «Опис справи» стояв окремою вкладкою поруч із «Приймальнею», і дві
 * вкладки про одне («тека без шифри → дати їй шифру») читались як дві різні
 * дії. Тепер опис відкривається з «Нових тек» («Описати»), з бібліотеки й з
 * «Огляду», а вкладка лишилась одна.
 */
const STEP_OF = { newcase: 'cases', newproject: 'home', sprofile: 'give' };

/**
 * Екрани, що відкриваються вікном поверх поточного, а не сторінкою.
 *
 * Правило макета хвилі 6: сторінка — для довгої роботи, вікно — для однієї
 * дії. Модуль екрана той самий; його `setView` малює в тіло вікна
 * (`view.setViewTarget`), а екран під вікном лишається, де був.
 */
const MODAL_SCREENS = ['newcase', 'newproject', 'settings', 'sprofile'];

/** Ключ i18n для кнопки екрана. Підпис «Завести справу» вже є в словнику. */
const NAV_LABEL = {
  home: 'nav.home', profile: 'nav.profile', sources: 'nav.sources', geog: 'nav.geog', fonds: 'nav.fonds',
  library: 'nav.library', frames: 'nav.frames', cases: 'nav.cases', newcase: 'nav.newcase', read: 'nav.read', runs: 'nav.runs', view: 'nav.view',
  eye: 'nav.eye', search: 'nav.search', sift: 'nav.sift', export: 'nav.export',
  sets: 'nav.sets', label: 'nav.label', jobs: 'nav.jobs', queue: 'nav.queue', site: 'nav.site',
  newproject: 'nav.newproject', canon: 'nav.canon', hyp: 'nav.hyp', research: 'nav.research',
  history: 'nav.history', cloud: 'nav.cloud', give: 'nav.give', pull: 'nav.pull', cards: 'nav.cards',
  sprofile: 'nav.sprofile', settings: 'nav.settings', projects: 'nav.projects', status: 'nav.status',
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
    const res = await apiFetch('/api/sections');
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
 * Група меню, у якій відкритий екран (вона розкрита).
 *
 * Виводиться з поточного екрана, а не зберігається окремим станом: два джерела
 * правди про «де я» розходяться при першому ж переході за посиланням, і
 * виглядає це як підсвічений розділ, у якому відкритого екрана немає.
 */
let GROUP = null;

/** Чи цей екран — про рід, а вкладка відкрита в Майстерні без проєкту. */
function needsProject(screen) {
  return !!SECTIONS.hub_only && (SECTIONS.project_screens || []).includes(screen);
}

/** Чи екран має вкладку тут і зараз: секція ввімкнена, проєкт є, де треба. */
function tabOn(screen) {
  return NAV_ORDER.includes(screen) && screenOn(screen) && !needsProject(screen);
}

/** Чи показувати блок меню тут: блок роду — у проєкті, блок Майстерні — без нього. */
function blockOn(block) {
  if (block === 'own') return !SECTIONS.hub_only;
  if (block === 'hub') return !!SECTIONS.hub_only;
  return true;
}

/**
 * Групи бічного меню з хоч одним доступним екраном, у порядку сервера.
 *
 * Групи приходять з `core.sections.NAV_GROUPS`. Без них (довідка не прийшла)
 * меню складається із секцій, як до хвилі 7: краще старе меню, ніж порожнє.
 */
function navGroups() {
  const nav = SECTIONS.nav && SECTIONS.nav.length ? SECTIONS.nav
    : (SECTIONS.sections || []).filter((s) => s.visible && s.active).map((s) => ({
      id: s.id, label: s.label, block: 'shared', fold: true,
      screens: NAV_ORDER.filter((x) => SECTIONS.screens[x] === s.id) }));
  return nav.filter((g) => blockOn(g.block || 'shared') && (g.screens || []).some(tabOn));
}

/** Екрани групи — у порядку групи. */
function groupScreens(gid) {
  const g = navGroups().find((x) => x.id === gid);
  return g ? g.screens.filter(tabOn) : [];
}

/** Група екрана: пункт меню, крок (`STEP_OF`) чи дія сторінки (`screen_action`). */
function groupOf(screen) {
  const tab = STEP_OF[screen] || screen;
  const g = navGroups().find((x) => (x.screens || []).includes(tab));
  if (g) return g.id;
  const act = Object.entries(SECTIONS.screen_action || {}).find(([, scr]) => scr === screen);
  return act ? groupOf(act[0]) : null;
}

/** Назва проєкту вкладки; `''` — Майстерня або перелік ще не прийшов. */
function projectName() {
  const p = projectInfo(currentPid());
  return p ? (p.name || p.id) : '';
}

/** Розкриті групи меню — пам'ять вкладки; без сховища розкрита лише активна. */
const OPEN_KEY = 'nysh.side.open';
function openGroups() {
  try { return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || '[]')); } catch { return new Set(); }
}
function toggleGroup(gid) {
  const set = openGroups();
  if (set.has(gid)) set.delete(gid); else set.add(gid);
  try { localStorage.setItem(OPEN_KEY, JSON.stringify([...set])); } catch { /* приватний режим */ }
  renderNav();
}

/** Підпис блоку меню: назва роду, «Майстерня», «Спільне Майстерні», «Сервіс». */
function blockLabel(block) {
  if (block === 'own') return projectName() || t('stage.project.label');
  if (block === 'hub') return t('stage.hub.label');
  if (block === 'shared') return t('side.shared');
  return t('stage.service.label');
}

/**
 * Бічне меню: блоки за тим, де живуть дані, у блоках — групи й пункти.
 *
 * 🔴 Один рівень навігації замість двох горизонтальних ярусів. Доти «Огляд»,
 * «Читання» й «Пошук» були водночас етапом і вкладкою, а екрани роду стояли
 * поруч зі спільними, і людина не бачила, що належить роду, а що Майстерні
 * (оцінка консолі 22.10.2026). Блок підписано словами: назва роду, «Спільне
 * Майстерні», «Сервіс».
 *
 * Знак приходить із сервера (`brand.yaml`), а не з переліку тут. Значка немає —
 * пункт лишається підписом, а не ламається.
 */
function renderNav() {
  const side = el('side');
  if (!side) return;
  // Назва роду — з переліку проєктів; поки він їде, блок підписано «Рід».
  if (!projectsNow() && !SECTIONS.hub_only) {
    loadProjects().then((d) => {
      if (!d) return;
      renderNav();
      if (CURRENT && !MODAL_SCREENS.includes(CURRENT)) renderHead(CURRENT);
    });
  }
  const groups = navGroups();
  // Екран — з `show()`, а не з адреси: вікно (`newcase`) адреси не міняє.
  const raw = CURRENT || (location.hash || '').replace(/^#/, '').split('?')[0];
  const here = STEP_OF[raw] || raw;
  if (!GROUP || !groups.some((g) => g.id === GROUP)) GROUP = groupOf(here) || (groups[0] || {}).id || null;
  const open = openGroups();
  const icons = (SECTIONS.icons && SECTIONS.icons.screens) || {};
  const item = (s) => {
    // 🔴 Значок малюється одразу з відомим числом: інакше після перемальовки
    // меню лічильник з'являвся порожнім аж до наступної відповіді черги.
    const tail = s === 'jobs' ? `<sup id="jobcount">${RUNNING_JOBS || ''}</sup>` : '';
    return `<button data-act="nav" data-arg="${s}"${s === here ? ' class="on" aria-current="page"' : ''}>`
      + `${icon(icons[s])}<span>${esc(screenLabel(s))}</span>${tail}</button>`;
  };
  const blocks = (SECTIONS.blocks && SECTIONS.blocks.length ? SECTIONS.blocks
    : ['own', 'hub', 'shared', 'service']);
  side.innerHTML = blocks.map((b) => {
    const mine = groups.filter((g) => (g.block || 'shared') === b);
    if (!mine.length) return '';
    const body = mine.map((g) => {
      const items = g.screens.filter(tabOn).map(item).join('');
      if (g.fold === false) return items;
      const on = g.id === GROUP || open.has(g.id);
      const label = esc(tOr(`stage.${g.id}.label`, tOr(`section.${g.id}.label`, g.label)));
      // Підпис групи веде на її перший екран (група розкривається як поточна),
      // стрілка поруч — лише розкрити й подивитись, не переходячи.
      const first = g.screens.filter(tabOn)[0];
      return `<div class="sg${g.id === GROUP ? ' cur' : ''}"><div class="sg-h">`
        + `<button data-act="nav" data-arg="${esc(first)}">${label}</button>`
        + `<button class="sg-fold" data-act="side.fold" data-arg="${esc(g.id)}" aria-expanded="${on}"`
        + ` aria-label="${label}"><span class="caret">▾</span></button></div>`
        + `<div class="sg-i"${on ? '' : ' hidden'}>${items}</div></div>`;
    }).join('');
    return `<section class="sb sb-${b}"><h4>${esc(blockLabel(b))}</h4>${body}</section>`;
  }).join('');
}

/** Назва екрана — та сама в меню, крихтах і заголовку («одна назва на екран»). */
function screenLabel(s) {
  if (s === 'home') return t(SECTIONS.hub_only ? 'nav.home.hub' : 'nav.home.project');
  return t(NAV_LABEL[s] || s);
}

/**
 * Мітка шару: чиї це дані. Відповідь на «де я» — словами, а не кольором.
 *
 * `mixed` у проєкті — спільний матеріал зі зрізом роду, у Майстерні — просто
 * спільне. Огляд (`context`) мітки не має: його заголовок і є назвою контексту.
 */
function layerTag(screen) {
  const raw = (SECTIONS.layers || {})[screen];
  // Екран роду в Майстерні без проєкту — вибір проєкту: роду, якому «належить»,
  // ще немає, і мітка «належить «Рід»» вводила б в оману.
  if (!raw || raw === 'context' || needsProject(screen)) return '';
  const inProject = !SECTIONS.hub_only;
  const layer = raw === 'mixed' && !inProject ? 'shared' : raw;
  const name = projectName() || t('stage.project.label');
  return `<span class="tag layer-${layer}" title="${esc(t(`layer.${layer}.why`))}">${
    esc(t(`layer.${layer}`).replace('{p}', name))}</span>`;
}

/**
 * Заголовок сторінки: крихти, назва, шар і дія сторінки.
 *
 * 🔴 Спільний для всіх екранів і малюється тут, а не кожним екраном: доти
 * кожен ставив свій `<h2>`, і він часто не збігався з назвою вкладки
 * («Бібліотека» → «Бібліотека справ»), а сказати, де людина й чиї дані
 * бачить, не було кому.
 */
function renderHead(screen) {
  const box = el('phead');
  if (!box) return;
  const inProject = !SECTIONS.hub_only;
  const ctx = inProject ? (projectName() || t('stage.project.label')) : t('stage.hub.label');
  const gid = groupOf(screen);
  const g = navGroups().find((x) => x.id === gid);
  const crumbs = [`<button data-act="nav" data-arg="home">${esc(ctx)}</button>`];
  if (g && g.fold !== false) crumbs.push(`<span>${esc(tOr(`stage.${g.id}.label`, g.label))}</span>`);
  const title = screen === 'home' && inProject ? ctx : screenLabel(screen);
  if (screen !== 'home') crumbs.push(`<span>${esc(screenLabel(screen))}</span>`);
  const act = (SECTIONS.screen_action || {})[screen];
  const actOn = act && screenOn(act) && (act !== 'newproject' || SECTIONS.hub_only);
  box.innerHTML = `<nav class="crumbs" aria-label="${esc(t('side.crumbs'))}">${crumbs.join('<i>›</i>')}</nav>
    <div class="ph-row"><h1>${esc(title)}</h1>${layerTag(screen)}${actOn
    ? `<span class="ph-acts"><button class="primary" data-act="nav" data-arg="${esc(act)}">${
      esc(t(`stage.act.${act}`))}</button></span>` : ''}</div>`;
}

/** ☰ каже читалці екрана, чи меню висунуте. */
export function sideBtnState() {
  const b = document.querySelector('.side-btn');
  if (b && b.setAttribute) b.setAttribute('aria-expanded', String(document.body.classList.contains('side-open')));
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
const WIDE_SCREENS = ['home', 'fonds', 'library', 'runs', 'queue', 'cases', 'sets'];

let CURRENT = '';
export const currentScreen = () => CURRENT;

async function show(screen) {
  // Невідомий екран (стара закладка, описка в адресі) — Огляд, а не заголовок
  // із сирим хешем і порожнім екраном (прохід консолі 22.10.2026).
  if (!SCREENS[screen] && !MODAL_SCREENS.includes(screen)) screen = 'home';
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
    const label = tOr(`section.${sid}.label`, sec.label);
    location.hash = screen;
    renderNav();
    renderHead(screen);
    setView(`<div class="warn">${t('sect.off.msg')}: <b>${esc(label || sid)}</b>
      <p class="muted">${esc(tOr(`section.${sid}.why`, sec.why || ''))}</p>
      <button data-act="sections.toggle" data-arg="${esc(sid)}"
        data-back="${esc(screen)}">${t('sect.on')}</button>
      <button data-act="nav" data-arg="settings">${ic('settings', 'ic-sm')} ${t('sect.title')}</button></div>`);
    return;
  }
  // Вікно — поверх поточного екрана: ні покоління, ні адреса, ні шапка не
  // міняються, інакше екран під вікном вважав би себе покинутим. Без екрана
  // під ним (вхід за посиланням) вікну нема над чим стояти — тоді сторінкою.
  if (MODAL_SCREENS.includes(screen) && SCREENS[screen] && CURRENT) {
    await showInModal(screen);
    return;
  }
  if (modalOpen()) closeModal();
  setViewTarget('view');
  // Випадні списки підказок живуть у `<body>`: поле, до якого вони належали,
  // зникає разом з екраном, а список висів над наступним (прохід 22.10.2026).
  document.querySelectorAll('.cb-pop').forEach((n) => n.remove());
  // 🔴 Екран роду в Майстерні без проєкту — вибір проєкту, а не відмова
  // операції: людина прийшла за родом, і «Оберіть проєкт» червоним без
  // переліку проєктів лишало її без виходу.
  if (needsProject(screen)) {
    bumpGen();
    CURRENT = screen;
    location.hash = screen;
    GROUP = groupOf(screen);
    renderNav();
    renderHead(screen);
    await chooseProject(screen);
    return;
  }
  const fn = SCREENS[screen] || SCREENS.home;
  // Усе, що малювалось досі, стає неактуальним рівно тут.
  bumpGen();
  CURRENT = screen;
  location.hash = screen;
  // Етап іде за екраном: перехід за посиланням чи закладкою мусить
  // підсвітити ту саму пару, що й клік по кнопці.
  const gid = groupOf(screen);
  if (gid && gid !== GROUP) GROUP = gid;
  // Ширина йде за екраном: таблиці на десять колонок у 62rem злипаються, а
  // текстові екрани в повну ширину монітора читати важче. Перелік тут, а не
  // в кожному екрані, бо це властивість розкладки, а не змісту.
  const main = document.querySelector('main');
  if (main) main.classList.toggle('wide', WIDE_SCREENS.includes(screen));
  // На телефоні меню — висувне: перехід його закриває.
  document.body.classList.remove('side-open');
  sideBtnState();
  renderNav();
  renderHead(screen);
  // 🦴 Скелетон, якщо екран мовчить довше за мить. Доти перехід лишав на місці
  // ПОПЕРЕДНІЙ екран, поки новий чекав сервера (Набори — 2 с, «Віддати» — 6 с),
  // і здавалось, що клік не спрацював. 140 мс — щоб швидкі екрани не моргали.
  const p0 = paints();
  const g0 = curGen();
  const skel = setTimeout(() => { if (paints() === p0 && curGen() === g0) busy(6); }, 140);
  try { await fn(); } finally { clearTimeout(skel); }
}

/** Екран у вікні: той самий модуль, лише `setView` малює в тіло вікна. */
async function showInModal(screen) {
  openModal({ title: screenLabel(screen), onClose: () => setViewTarget('view') });
  modalTitle(screenLabel(screen));
  setViewTarget('dlg-body');
  try {
    await SCREENS[screen]();
  } finally {
    // Екран у вікні міг перейти деінде (`show` закрив вікно): ціль малювання
    // повертається на екран, щойно вікно не відкрите.
    if (!modalOpen()) setViewTarget('view');
  }
}

/** Майстерня без проєкту, а екран — про рід: перелік проєктів з переходом. */
async function chooseProject(screen) {
  const gen = curGen();
  let got = null;
  try {
    const res = await apiFetch('/api/projects');
    if (res.ok) got = await res.json();
  } catch { /* перелік не прийшов — лишається підказка без карток */ }
  if (!alive(gen)) return;
  const list = (got && Array.isArray(got.projects) ? got.projects : []).filter((p) => !p.archived);
  const cards = list.map((p) => `<div class="pcard">
      <b>${esc(p.name || p.id)}</b>
      <button data-act="project.go" data-arg="${esc(p.id)}" data-back="${esc(screen)}">${t('project.open')}</button>
    </div>`).join('');
  setView(`<p><b>${t('project.need.title')}</b></p>
    <p class="muted">${t('project.need.why')}</p>
    <div class="pcards">${cards || emptyMini('derevo', t('project.none'))}</div>
    <p><button data-act="nav" data-arg="newproject">${t('stage.act.newproject')}</button></p>`);
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

/**
 * Дочекатись кінця роботи: Promise з останнім записом (`done`, `error`,
 * `cancelled`). Для вікон, де наступний крок залежить від результату
 * довгої операції (кошторис хмари перед орендою).
 */
export function jobDone(jobId, onTick = null) {
  // Без номера роботи чекати нема на що: інакше Promise висів би вічно.
  if (!jobId) return Promise.resolve({ state: 'error', error: t('job.failed') });
  return new Promise((resolve) => {
    let done = false;
    const finish = (j) => {
      if (done) return;
      if (onTick) { try { onTick(j); } catch { /* показ стану не спиняє очікування */ } }
      if (FINAL_STATES.includes(j.state)) { done = true; off(); resolve(j); }
    };
    const off = onJob(jobId, finish);
    // 🔴 Швидка робота (сухий кошторис хмари) може скінчитись раніше, ніж
    // підписались: довге очікування черги віддає лише зміни після курсора,
    // і запису вдруге не буде. Тож один раз питаємо перелік робіт самі.
    apiFetch('/api/jobs').then((r) => (r.ok ? r.json() : null)).then((got) => {
      const j = ((got && got.jobs) || []).find((x) => x.id === jobId);
      if (j) finish(j);
    }).catch(() => { /* перелік не прийшов — чекаємо на спостерігача черги */ });
  });
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
export function jobProgress(j) {
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
  // Тривоги — плашкою, решта — згорнутими примітками (`view.splitWarnings`).
  const { alerts, notes: quiet } = splitWarnings(j.warnings);
  const notes = alerts.map((a) => `<div class="warn">${ic('alert', 'ic-sm')} ${esc(a)}</div>`);
  // 🔴 І кнопка, а не лише текст. Довга робота часто не остання в ланцюжку
  // («зібране лягло окремим файлом; звести джерела в реєстр»), і поки поради
  // йшли самим текстом із командою терміналу, вони називали наступний крок
  // тому, хто працює з браузера й набирати команду нема куди. Попередження без
  // виходу перестає бути попередженням.
  const extra = quiet.map(esc);
  for (const n of j.next || []) {
    if ((n.level || 'note') === 'agent') continue;
    const scr = OP_SCREEN[n.op];
    // Порада без екрана — команда терміналу: у примітки, не окремою смугою.
    if (!scr) {
      extra.push(`<span class="mono">${esc(n.op)}</span> — ${esc(n.why || '')}`);
      continue;
    }
    const label = screenLabel(scr);
    // Та сама дія, що в поради конверта (`next`), — щоб і тут кнопка несла
    // запит на екран, а не відкривала його порожнім.
    notes.push(`<div class="warn next"><button data-act="next" data-arg="${esc(n.op)}"${seedAttr(n)}>`
      + `${esc(label)} →</button> <span>${esc(n.why || '')}</span></div>`);
  }
  return notes.join('') + notesBlock(extra);
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
const ZERO_IS_NOISE = ['kept', 'skipped', 'errors', 'failed', 'short'];

async function refreshJobs() {
  const res = await apiFetch(`/api/jobs?since=${cursor}`);
  // Відмова (допуск протух) — не журнал: без перевірки в курсор лягав `undefined`.
  if (!res.ok) return;
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
  // Маскот «працює» — лише поки щось справді виконується або чекає: це стан
  // ПРОЦЕСУ. Над готовими й упалими роботами його немає — там говорить текст.
  const live = jobs.filter((j) => j.state === 'running' || j.state === 'queued').length;
  const head = live ? `<div class="jobs-busy">${maskot('pratsiuie', 110)}
    <p>${esc(t('jobs.busy').replace('{n}', live))}</p></div>` : '';
  // 🔴 Живе — повними картками з поступом і «Спинити»; завершене — рядками в
  // одному згорнутому блоці. Доти все стояло суцільним списком карток за
  // півдоби, і своє живе читання доводилось шукати серед проб письма й
  // пошуків, кожен зі своїми примітками.
  const isLive = (j) => j.state === 'running' || j.state === 'queued';
  const liveJobs = jobs.filter(isLive);
  const done = jobs.filter((j) => !isLive(j))
    .sort((a, b) => (b.updated || 0) - (a.updated || 0));
  // Черга одна на Майстерню: коли в ній роботи кількох проєктів, кожна
  // підписана своїм, інакше чуже читання виглядає як своє.
  const many = new Set(jobs.map((j) => j.project ?? '.')).size > 1;
  const whose = (j) => (many ? ` ${projectChip(j.project || '', { hubLabel: t('pj.hub') })}` : '');
  const cards = liveJobs.map((j) => `
    <div class="job">
      <b>${esc(j.title || j.kind)}</b>${whose(j)} <span class="muted">${esc(jobState(j.state))}</span>
      ${jobProgress(j)}
      ${j.error ? `<div class="warn err">${esc(j.error)}</div>` : ''}
      ${jobNotes(j)}
      <button data-act="jobs.cancel" data-job="${esc(j.id)}">${t('jobs.cancel')}</button>
      ${caseLink(j)}
    </div>`).join('');
  box.innerHTML = head + (cards || emptyMini('hodynnyk', t('jobs.none')))
    + doneBlock(done);
}

/**
 * Читання веде на картку своєї справи — там «Змінити», «Додати голос» і хід.
 *
 * 🔴 Доти в рядку читання на «Роботах» була лише «Спинити», і перемкнути письмо
 * звідси було нікуди (холодний прохід 07.10.2026: глухий кут).
 */
function caseLink(j) {
  const dir = j.kind === 'read' ? (j.cfg || {}).case_dir : '';
  return dir ? `<button class="ctl-sm" data-act="jobs.case" data-arg="${esc(dir)}">${
    t('jobs.case')}</button>` : '';
}

/**
 * Коли робота завершилась: «19:38» сьогодні, «06.10 22:20» — раніше.
 *
 * 🔴 Сама година змішувала вчорашнє з сьогоднішнім: півдоби завершених робіт
 * перетинає північ (холодний прохід 07.10.2026).
 */
function hhmm(sec) {
  if (!sec) return '';
  const d = new Date(sec * 1000);
  const time = d.toTimeString().slice(0, 5);
  if (d.toDateString() === new Date().toDateString()) return time;
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm} ${time}`;
}

/**
 * «Показати результат» — для пошуків, чия відповідь живе на їхньому екрані.
 *
 * Спинений пошук по каталогах теж має відповідь (ті джерела, що встигли),
 * тож кнопка є і в нього; спинений пошук по прочитаному не доводить нічого.
 */
function showResult(j) {
  const label = t('jobs.search.show');
  if ((j.kind === 'search.sweep' || j.kind === 'search.find') && j.result) {
    return `<button class="ctl-sm" data-act="jobs.search" data-job="${esc(j.id)}">${label}</button>`;
  }
  if (j.kind === 'catalog.sweep' && j.result) {
    return `<button class="ctl-sm" data-act="jobs.sources" data-job="${esc(j.id)}">${label}</button>`;
  }
  return '';
}

/**
 * Завершене — рядками під одним розкриттям, збої названо в заголовку.
 *
 * Збій не ховається: число стоїть у самому заголовку, а рядок збою червоний.
 * Результат і примітки — під рядком, як і були, але вже не займають екран.
 */
function doneBlock(done) {
  if (!done.length) return '';
  const failed = done.filter((j) => j.state === 'error').length;
  const rows = done.map((j) => `
    <div class="job-row${j.state === 'error' ? ' failed' : ''}">
      <span class="mono dim">${esc(hhmm(j.updated))}</span>
      <b>${esc(j.title || j.kind)}</b>
      <span class="muted">${esc(jobState(j.state))}</span>
      ${j.error ? `<div class="err-line">${esc(j.error)}</div>` : ''}
      ${jobResult(j)}
      ${caseLink(j)}
      ${showResult(j)}
      ${jobNotes(j)}
    </div>`).join('');
  return `<details class="jobs-done"${failed ? ' open' : ''}>
    <summary>${t('jobs.done.title')} (${done.length}${failed
    ? ` · ${t('jobs.done.failed')} ${failed}` : ''})</summary>
    ${rows}
    <p><button class="ctl-sm" data-act="jobs.forget">${t('jobs.forget')}</button></p>
  </details>`;
}

/** Довге очікування на сервері: одне з'єднання замість опитувань щосекунди. */
async function watchJobs() {
  for (;;) {
    try {
      const res = await apiFetch(`/api/jobs/wait?since=${cursor}&timeout_s=25`);
      // 🔴 Відмова з JSON-тілом виняток не кидає, а пауза стоїть лише в `catch`:
      // без цього рядка пристрій без допуску молотив сервер запитами без упину.
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
      LIVE_JOBS = running;
      const badge = el('jobcount');
      if (badge) badge.textContent = running.length ? String(running.length) : '';
      // Кнопка «Працює N» у шапці: ховається, коли нічого не йде.
      const chip = el('jobs-chip');
      if (chip) {
        chip.hidden = running.length === 0;
        const n = el('jobs-n');
        if (n) n.textContent = String(running.length);
      }
      // 🐾 Знак у шапці показує, що робота йде. Саме процес: результату він не
      // повідомляє — це справа тексту, який несе знаменник.
      const paw = document.querySelector('.logo-img');
      if (paw) paw.classList.toggle('busy', running.length > 0);
    } catch {
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

/** Розкрити чи згорнути групу бічного меню (`side.fold`). */
export const foldGroup = (gid) => toggleGroup(gid);

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

/** Живі роботи з останньої відповіді черги — для меню «Працює» в шапці. */
let LIVE_JOBS = [];
const liveJobs = () => LIVE_JOBS;

export { SECTIONS, NAV_ORDER, NAV_LABEL, GROUP, screenOn, loadSections,
  navGroups, groupScreens, groupOf, renderNav, renderHead, screenLabel, icon, show,
  refreshJobs, watchJobs, jobNotes, RUNNING_JOBS, MODAL_SCREENS, needsProject, liveJobs };
