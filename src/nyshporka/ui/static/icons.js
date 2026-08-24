// Нишпорка — значки для розмітки, яку збирає JS.
//
// Спільний шар: цей файл читають обидві морди — ком'юніті-застосунок і консоль
// дослідника. Сам спрайт інжектується в тіло сторінки замість `{{SPRITE}}`
// (`nyshporka.ui.with_sprite`), а не підключається файлом: `<use href>` до
// зовнішнього SVG ЗАБОРОНЯЄ успадкування currentColor у Chrome — значки стали б
// чорними на будь-якому тлі.
//
//   ic('refresh')            → значок у своєму тоні, з відступом під підпис
//   ic('trash', 'ic-o')      → значок без підпису (кнопка-іконка)
//   ic('download', 'ic-sm')  → дрібний, для щільних таблиць
//   ic('check', 'ic-plain')  → БЕЗ тону: значок бере колір кнопки (для кнопок,
//                              що вже пофарбовані — зелене «зберегти» тощо)
//
// ⚠ Назва мусить існувати у спрайті: помилка в назві дає ПОРОЖНЄ місце без
// жодної помилки в консолі — `<use>` на неіснуючий id мовчить. Що всі назви
// звідси є у спрайті, доводить приймач.

// ── Тон закріплений за ЗНАЧКОМ, а не за місцем ───────────────────────────────
// Кошик червоний і в банку, і в синтетиці, і в модалці; папка жовта скрізь.
// Саме сталість робить колір ДРУГОЮ ознакою впізнавання поряд із формою — око
// ловить «щось червоне праворуч» ще до того, як прочитає підпис. Тон,
// прив'язаний до місця (усі значки вкладки — одного кольору), цього не дає:
// всередині вкладки значки знову зливаються.
// Кольори — `--ic-*` у tokens.css, класи `.ic-t-*` — у base.css.
export const TONES = {
  // розділи й підвкладки
  search: 'gold', 'archive-box': 'sand', drawers: 'indigo', chip: 'teal',
  scan: 'lime', 'crop-check': 'sky', quill: 'violet', 'pencil-line': 'pink',
  books: 'amber', column: 'sand', eye: 'cyan', letters: 'gold',
  twins: 'blue', flask: 'mint', curve: 'orange', bars: 'sky',
  // ствердне / деструктивне — семантика, однакова скрізь
  plus: 'green', check: 'green', 'check-circle': 'green', play: 'green',
  x: 'red', 'x-circle': 'red', trash: 'red', broom: 'red', scissors: 'red',
  'slash-page': 'red', 'chart-down': 'red', stop: 'red',
  // робота з даними
  folder: 'amber', 'folder-open': 'amber', 'book-open': 'amber', note: 'amber',
  clock: 'amber', scale: 'amber', target: 'orange', refresh: 'sky', list: 'blue',
  download: 'blue', upload: 'blue', mail: 'blue', disk: 'teal', anchor: 'teal',
  link: 'cyan', focus: 'cyan', zone: 'cyan', swap: 'cyan', radar: 'cyan',
  // ручна праця й образи
  'pen-nib': 'violet', image: 'violet', film: 'violet', wand: 'violet',
  sparkles: 'violet', ab: 'violet', mic: 'pink', palette: 'pink', hook: 'pink',
  // відзнаки та стани
  info: 'sky', ruler: 'slate', gauge: 'orange',
  bolt: 'gold', medal: 'gold', alert: 'gold', pause: 'gold', skip: 'gold',
  paw: 'gold', tag: 'mint', flag: 'mint', new: 'mint',
  // службове — навмисно тихе, щоб не сперечалося зі змістовними значками
  printer: 'slate', hand: 'slate', grid4: 'slate', rect: 'slate', page: 'slate',
  scroll: 'slate', 'help-circle': 'slate', undo: 'slate', expand: 'slate',
  settings: 'slate', menu: 'slate', 'chevron-up': 'slate', 'arrow-up': 'slate',
  'arrow-left': 'slate',
};

export const tone = (name) => TONES[name] || 'slate';

export function ic(name, cls = '') {
  const plain = cls.includes('ic-plain');
  const t = plain ? '' : ' ic-t-' + tone(name);
  const extra = cls ? ' ' + cls : '';
  return `<svg class="ic${t}${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

// ── 🖋 Бейдж рушія читання ────────────────────────────────────────────────────
// Три ознаки, і кожна працює сама: КОЛІР, ФОРМА і ЛІТЕРА. Одного кольору мало —
// вивід потрапляє на скріншоти, у логи й до людей із дальтонізмом, а в самих
// даних Дяк і Скриба однаково позначені як `kraken`: без бейджа вони зливаються
// рівно там, де різниця вирішує (одне письмо латинське, інше кириличне, і
// невідповідність дає ТИХЕ сміття без падіння впевненості).
//
// 🔴 Літери, форми й ролі — з `brand.yaml`, того самого джерела, з якого їх бере
// `nysh models list` і згенерований `tokens.css`. Свій відтінок чи своя літера
// тут означали б, що Писар у вікні й Писар у командному рядку — різні рушії.
// Звіряє приймач; колір під `data-engine` ставить tokens.css, форму під
// `data-shape` — base.css.
//
// ⚠ Ім'я моделі НЕ перекладається: воно стоїть в іменах файлів (`pysar_cyr_v*.pt`),
// і перекладене воно перестало б збігатися з тим, що людина бачить на диску.
// Перекладається роль — і літера, бо в англійському рядку кирилична «П» серед
// латиниці читається як друкарська помилка.
export const ENGINES = {
  pysar: {
    letter: 'П', letter_en: 'P', shape: 'circle', name: 'Писар',
    role: 'кирилиця, головний голос', role_en: 'Cyrillic, main voice',
  },
  diak: {
    letter: 'Д', letter_en: 'D', shape: 'diamond', name: 'Дяк',
    role: 'кирилиця, другий голос', role_en: 'Cyrillic, second voice',
  },
  skryba: {
    letter: 'С', letter_en: 'S', shape: 'notched', name: 'Скриба',
    role: 'латинка', role_en: 'Latin script',
  },
};

//   eng('pysar')                  → бейдж
//   eng('diak', true)             → бейдж плюс ім'я
//   eng('skryba', true, 'en')     → те саме англійською
export function eng(id, withName = false, lang = 'uk') {
  const e = ENGINES[id];
  if (!e) return '';
  const letter = lang === 'en' ? e.letter_en : e.letter;
  const role = lang === 'en' ? e.role_en : e.role;
  const badge = `<span class="engine" data-engine="${id}" data-shape="${e.shape}"`
    + ` title="${e.name} — ${role}" aria-label="${e.name}"><span>${letter}</span></span>`;
  return withName ? `<span class="engine-row">${badge}<b>${e.name}</b></span>` : badge;
}
