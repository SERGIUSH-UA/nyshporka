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
import { ic, eng } from '/ui/icons.js';
import { initTheme, cycleTheme } from '/ui/theme.js';
import { swapHtml, skelRows, skelCards } from '/ui/dom.js';
import { attachCombobox } from '/ui/combobox.js';

// ── i18n ─────────────────────────────────────────────────────────────────────
const STRINGS = {
  uk: {
    'nav.home': 'Дослідження', 'nav.sources': 'Джерела', 'nav.cases': 'Мої справи',
    'nav.search': 'Пошук', 'nav.jobs': 'Роботи',
    'nav.geog': 'Газетир', 'nav.fonds': 'Фонди',
    'nav.newcase': 'Завести справу',
    'sect.title': 'Частини застосунку',
    'sect.why': 'Нишпорку ставлять дуже різні люди: одному потрібен лише каталог справ, другий читає рукопис відеокартою. Вимкнена частина зникає з шапки, а її дії не виконуються ні тут, ні в командному рядку, ні агентом.',
    'sect.preset': 'Готовий набір',
    'sect.custom': 'власний набір',
    'sect.always': 'завжди',
    'sect.empty': 'поки порожня',
    'sect.on': 'Увімкнути',
    'sect.off': 'Вимкнути',
    'sect.off.msg': 'Ця частина застосунку вимкнена',
    'preset.catalog': 'Каталог',
    'preset.amateur': 'Аматор',
    'preset.researcher': 'Дослідник',
    'preset.lab': 'Лабораторія',
    'cov.searched': 'шукали в',
    'geog.title': 'Де метрики цього села',
    'geog.why': 'Зворотний напрям до опису: ви знаєте СЕЛО, а не фонд. Каталог показує справи по всіх фондах архіву одразу — і по всіх конфесіях: метрики православної громади, костелу й рабинату одного містечка лежать окремо.',
    'geog.q': 'Назва села — українською, російською або латинкою',
    'geog.find': 'Знайти',
    'geog.section.all': 'усі конфесії',
    'geog.section.church': 'православні',
    'geog.section.decanats': 'костели',
    'geog.section.rabbinate': 'рабинати',
    'geog.nothing': 'У переглянутих довідниках такого поселення немає.',
    'geog.cases': 'справ у каталозі',
    'geog.ondisk': 'з них у нас',
    'geog.siblings': 'те саме поселення в інших конфесіях',
    'geog.confusers': 'схожі назви — фаззі-пошук плутає їх із цим селом',
    'geog.church': 'церква',
    'geog.hist': 'до 1793',
    'geog.after': 'після',
    'geog.modern': 'нині',
    'fonds.title': 'Що взагалі існує в архіві',
    'fonds.why': 'Реєстр опису — третє сховище поруч із «мої справи». «Справи немає» тут означає «в архіві не існує», а не «ще не завантажено».',
    'fonds.rows': 'справ в опису',
    'fonds.ondisk': 'у нас',
    'fonds.todo': 'скан є, не взято',
    'fonds.filter': 'Заголовок, село або слово',
    'fonds.surname': 'Прізвище з алфавітки',
    'fonds.uezd': 'Повіт',
    'fonds.state.any': 'будь-який стан',
    'fonds.state.disk': 'у нас на диску',
    'fonds.state.todo': 'скан є, не взято',
    'fonds.state.film': 'плівка FS, не взято',
    'fonds.state.order': 'замовляти в архіві',
    'fonds.matched': 'під фільтр',
    'fonds.of': 'із',
    'catalog.title': 'Довідники',
    'catalog.none': 'Довідників немає — пошук по каталогах архівів недоступний, і його нуль нічого не означатиме.',
    'home.title': 'З чого почнемо',
    'home.have_scans': 'У мене є скани',
    'home.have_scans.hint': 'тека з фотографіями або PDF зі справою',
    'home.where': 'Не знаю, де шукати',
    'home.where.hint': 'пошук по каталогах архівів і покажчиках плівок',
    'home.demo': 'Перевірити цю машину',
    'home.demo.hint': 'чи складеться читання рукопису тут — ДО того, як вкладати скани',
    'check.title': 'Чи готова ця машина читати рукопис',
    'check.why': 'Перевірка робиться до того, як ви вкладете тисячі сканів і чекатимете ніч.',
    'check.ready': 'Усе на місці — можна читати.',
    'check.notready': '⚠ Читання поки не запуститься. Нижче — чого бракує і чим це ставиться.',
    'check.nosample': 'Зразкової справи в цій збірці немає, тож перевірка показує стан машини, а не приклад читання.',
    'check.sample.title': 'Зразкова справа розгорнута',
    'check.sample.hint': 'У застосунок вкладено три аркуші справи ДАХмО 315-1-159 (1821-1822) з готовим машинним декодом. Прочитати їх заново нічим — ваги моделей ще не викладені; зате гортач, пошук у декоді й реєстр працюють на них одразу.',
    'check.sample.do': 'Розгорнути зразкову справу',
    'check.sample.ready': 'Зразкова справа вже в просторі — її видно в реєстрі й у гортачі.',
    'check.sample.next': 'Далі: відкрийте гортач і клацніть рядок — видно буде, ЗВІДКИ взявся текст.',
    'case.dirhint': 'Шлях до теки скопіюйте з адресного рядка провідника. Вибрати теку віконцем браузер не дозволяє — це його обмеження, не застосунку.',
    'sources.q': 'Село, прізвище або слово із заголовка справи',
    'sources.find': 'Шукати',
    'sources.searched': 'шукали в',
    'sources.nothing': 'Нічого не знайшлось',
    'sources.zero_warning':
      'Порожній результат означає «немає в оглянутих каталогах», а не «не існує».',
    'sources.get': 'Завантажити',
    'sources.manifest': 'Що принесе',
    'nav.library': 'Бібліотека',
    'lib.title': 'Бібліотека справ',
    'lib.why': 'Що взагалі є на руках — канон і диск разом, з рішеннями ока поверх.',
    'lib.q': 'Шифра, назва або місце',
    'lib.repo': 'Архів', 'lib.repo.any': 'усі архіви',
    'lib.verdict': 'Вердикт', 'lib.verdict.any': 'будь-який',
    'lib.verdict.none': 'без вердикту', 'lib.verdict.all': 'усі справи',
    'lib.ondisk': 'лише ті, що на диску',
    'lib.col.shifra': 'шифра', 'lib.col.title': 'назва', 'lib.col.years': 'роки',
    'lib.col.place': 'місце', 'lib.col.verdict': 'вердикт',
    'lib.disk': 'на диску', 'lib.nodisk': 'на диску немає',
    'lib.unbuilt': 'Зведення ще не збирали — це НЕ означає, що справ немає.',
    'lib.build': 'Зібрати зведення',
    'lib.count': 'показано {n} із {total}',
    'lib.verdict.set': 'позначити',
    'lib.verdict.clear': 'зняти вердикт',
    'lib.verdict.no_clan': 'роду немає',
    'lib.verdict.clan_found': 'рід знайдено',
    'lib.verdict.recheck': 'перевірити ще',
    'lib.pages': 'Скільки аркушів переглянуто',
    'lib.pages.why': 'Без цього числа «роду немає» наступного разу прочитають як доведений нуль.',
    'lib.note': 'Чим доведено',
    'lib.save': 'Зберегти рішення',
    'lib.cancel': 'Не зараз',
    'nav.sift': 'Розбір',
    'sift.title': 'Розбір знахідок',
    'sift.keys': 'Клавіші: ← → гортати · E — гортач · N — в облік',

    'sift.empty': 'Немає чого розбирати — спершу знайдіть щось у прочитаному.',
    'sift.togo': 'знахідка {i} з {n}',
    'sift.open': 'Розібрати знахідки',
    'sift.crop': 'вирізка рядка',
    'sift.crop.load': 'показати вирізку',
    'sift.crop.fail': 'вирізку взяти не вдалось',
    'sift.context': 'сусідні рядки',
    'sift.score': 'бал',
    'sift.prev': 'Назад', 'sift.next': 'Далі',
    'sift.note': 'Занести сторінку в облік',
    'sift.view': 'Відкрити в гортачі',
    'sift.rule': 'Вирішує ОКО. Машина подала кандидата — прочитайте вирізку самі: '
      + 'збіг у балах не є доказом, а розбіжність не є спростуванням.',
    'sift.stem': '⚠ Не відкидайте за коренем слова: рушій калічить саме середину, '
      + 'тож шукане прізвище виходить із нього невпізнанним.',
    'view.run.none': 'такого прогону немає',
    'view.run.empty': 'Жодної справи ще не прочитано — гортати нема чого.',
    'view.overlay': 'Клацніть по рядку на знімку, щоб побачити його текст.',
    'view.page': 'Сторінка цілком',
    'view.page.why': 'Дорого: ціла сторінка важить у десятки разів більше за вирізку рядка. Але саме на ній видно, ЧИЙ це запис і що стоїть поруч.',
    'view.zoom.fit': 'вписати', 'view.zoom.in': 'більше', 'view.zoom.out': 'менше',
    'view.close': 'Згорнути',
    'cases.title': 'Справи в роботі',
    'cases.frames': 'кадрів', 'cases.read': 'прочитано', 'cases.none': 'не читано',
    'cases.nodir': 'теки на цій машині немає — правити нічого',
    'cases.build': 'перезібрати реєстр',
    'cases.build.why': "Реєстр — зріз п'яти сховищ: після прогону, завантаження чи занесення в облік він старіє за хвилини.",
    'search.q': 'Прізвище', 'search.where': 'Де шукати',
    'search.where.decode': 'у прочитаному машиною',
    'search.where.pages': 'у виписаних прізвищах',
    'search.where.records': 'в учасниках записів',
    'search.run': 'Знайти',
    'hit.eye': 'подивитись на рядок оком',
    'hit.note': 'занести цю сторінку в облік',
    'search.coverage': 'шукали по', 'search.runs': 'прогонах',
    'search.cases': 'справах, занесених оком',
    'nav.eye': 'Око',
    'eye.case': 'Справа', 'eye.check': 'Що вже дивились',
    'eye.disk': 'на диску', 'eye.noted': 'занесено', 'eye.left': 'ще не дивились',
    'eye.note': 'Занести сторінку', 'eye.scan': 'Скан', 'eye.type': 'Тип',
    'eye.surnames': 'Прізвища ЯК У ДЖЕРЕЛІ (через кому)',
    'eye.status': 'Повнота', 'eye.comment': 'Коментар', 'eye.save': 'Занести',
    'ptype.birth': 'народження', 'ptype.marriage': 'шлюб',
    'ptype.death': 'смерть', 'ptype.confession': 'сповідний розпис',
    'ptype.revision': 'ревізька казка', 'ptype.census': 'перепис',
    'ptype.index': 'покажчик', 'ptype.title': 'титул',
    'ptype.cover': 'обкладинка', 'ptype.flyleaf': 'форзац',
    'ptype.blank': 'порожня', 'ptype.illegible': 'не читається',
    'ptype.mixed': 'мішана', 'ptype.other': 'інше',
    'eye.rule': 'Заносьте КОЖЕН відкритий скан — навіть порожній. Інакше наступного разу ви відкриєте його знову.',
    'case.title': 'Завести або виправити справу',
    'case.dir': 'Тека зі сканами', 'case.shifra': 'Шифра',
    'case.name': 'Назва справи', 'case.type': 'Тип документа',
    'case.years': 'Роки', 'case.place': 'Місце', 'case.save': 'Зберегти',
    'case.note': 'Примітка: звідки взято, що незрозуміло',
    'case.adopt': 'Узяти теку під облік там, де вона лежить',
    'case.adopt.why': "Потрібно лише для теки ПОЗА простором (зовнішній диск, робочий стіл): інакше справа не з'явиться в переліках. Файли не переносяться — теку буде оголошено в nyshporka.toml.",
    'case.edit': 'Змінити опис справи', 'case.fresh': 'Завести іншу',
    'case.editing': 'Правимо опис теки',
    'case.keep': 'Порожнє поле лишає попереднє значення — стерти опис можна лише правкою файлу _source.json у теці.',
    'case.why': 'Без шифри тека лишається купою файлів: немає ні обліку прочитаного, ні можливості послатись на знахідку.',
    'nav.view': 'Гортач',
    'view.run': 'Прогін', 'view.open': 'Відкрити',
    'view.pages': 'сторінок', 'view.lines': 'рядків',
    'view.eye': 'Око вирішує, машина лише подає — дивіться на рядок, а не на текст.',
    'nav.read': 'Читання',
    'read.dir': 'Тека зі сканами (пласка)', 'read.plan': 'Що робитимемо',
    'read.go': 'Читати', 'read.frames': 'кадрів', 'read.script': 'письмо',
    'read.model': 'модель', 'read.voice': 'другий голос',
    'read.started': 'Поставлено в чергу',
    'nav.export': 'Експорт',
    'export.case': 'Справа', 'export.what': 'Що вивантажити',
    'export.records': 'розібрані записи', 'export.pages': 'прізвища зі сторінок',
    'export.run': 'Показати', 'export.csv': 'Зберегти CSV',
    'jobs.title': 'Що зараз робиться',
    'jobs.none': 'Наразі нічого не виконується',
    'jobs.cancel': 'Спинити',
    'common.loading': 'Хвилинку…',
    'common.error': 'Не вийшло',
    'common.frames': 'кадрів',
    'common.pages': 'сторінок',
    'common.page': 'сторінка',
  },
  en: {
    'nav.home': 'Research', 'nav.sources': 'Sources', 'nav.cases': 'My cases',
    'nav.search': 'Search', 'nav.jobs': 'Jobs',
    'nav.geog': 'Gazetteer', 'nav.fonds': 'Fonds',
    'nav.newcase': 'New case',
    'sect.title': 'Parts of the app',
    'sect.why': 'Nyshporka is installed by very different people: one needs only the case catalogue, another reads handwriting on a GPU. A disabled part disappears from the header, and its actions do not run here, in the command line, or through the agent.',
    'sect.preset': 'Ready-made set',
    'sect.custom': 'custom set',
    'sect.always': 'always on',
    'sect.empty': 'empty for now',
    'sect.on': 'Enable',
    'sect.off': 'Disable',
    'sect.off.msg': 'This part of the app is disabled',
    'preset.catalog': 'Catalogue',
    'preset.amateur': 'Amateur',
    'preset.researcher': 'Researcher',
    'preset.lab': 'Lab',
    'cov.searched': 'searched in',
    'geog.title': 'Where the records of this village are',
    'geog.why': 'The reverse direction: you know the VILLAGE, not the fond. The catalogue lists cases across all fonds at once — and all confessions: Orthodox, Catholic and Jewish registers of one town are kept separately.',
    'geog.q': 'Village name — Ukrainian, Russian or Latin script',
    'geog.find': 'Search',
    'geog.section.all': 'all confessions',
    'geog.section.church': 'Orthodox',
    'geog.section.decanats': 'Catholic',
    'geog.section.rabbinate': 'Jewish',
    'geog.nothing': 'No such settlement in the reference sets searched.',
    'geog.cases': 'cases in catalogue',
    'geog.ondisk': 'of them here',
    'geog.siblings': 'same settlement in other confessions',
    'geog.confusers': 'similar names — fuzzy search confuses them with this one',
    'geog.church': 'church',
    'geog.hist': 'before 1793',
    'geog.after': 'after',
    'geog.modern': 'today',
    'fonds.title': 'What exists in the archive at all',
    'fonds.why': 'The finding aid is a third store next to “my cases”. “No such case” here means “does not exist in the archive”, not “not downloaded yet”.',
    'fonds.rows': 'cases in finding aid',
    'fonds.ondisk': 'here',
    'fonds.todo': 'scan exists, not taken',
    'fonds.filter': 'Title, village or word',
    'fonds.surname': 'Surname from the archive index',
    'fonds.uezd': 'Uyezd',
    'fonds.state.any': 'any state',
    'fonds.state.disk': 'on our disk',
    'fonds.state.todo': 'scan exists, not taken',
    'fonds.state.film': 'FS film, not taken',
    'fonds.state.order': 'order at the archive',
    'fonds.matched': 'matched',
    'fonds.of': 'of',
    'catalog.title': 'Reference sets',
    'catalog.none': 'No reference sets installed — catalogue search is unavailable, and its zero would mean nothing.',
    'home.title': 'Where do we start',
    'home.have_scans': 'I have scans',
    'home.have_scans.hint': 'a folder of photographs, or a PDF of a case',
    'home.where': "I don't know where to look",
    'home.where.hint': 'search archive catalogues and film sheet indexes',
    'home.demo': 'Check this machine',
    'home.demo.hint': 'will handwriting reading work here — BEFORE you commit scans',
    'check.title': 'Is this machine ready to read handwriting',
    'check.why': 'Run this before you commit thousands of scans and wait a night.',
    'check.ready': 'Everything is in place — you can read.',
    'check.notready': '⚠ Reading will not start yet. Below: what is missing and what installs it.',
    'check.nosample': 'This build ships no sample case, so the check shows the state of the machine, not an example of reading.',
    'check.sample.title': 'Sample case deployed',
    'check.sample.do': 'Deploy the sample case',
    'check.sample.hint': 'Three leaves of case DAHMO 315-1-159 (1821-1822) ship with the app, machine-decoded already. Reading them anew takes model weights, which are not published yet — but the viewer, decode search and the case registry work on them right away.',
    'check.sample.ready': 'The sample case is already in your workspace — it shows up in the registry and in the viewer.',
    'check.sample.next': 'Next: open the viewer and click a line — you will see WHERE the text came from.',
    'case.dirhint': 'Copy the folder path from your file manager address bar. Picking a folder with a dialog is not something the browser allows — its limitation, not the app’s.',
    'sources.q': 'Village, surname, or a word from the case title',
    'sources.find': 'Search',
    'sources.searched': 'searched in',
    'sources.nothing': 'Nothing found',
    'sources.zero_warning':
      'An empty result means "not in the catalogues we looked at", not "does not exist".',
    'sources.get': 'Download',
    'sources.manifest': 'What it brings',
    'nav.library': 'Library',
    'lib.title': 'Case library',
    'lib.why': 'What you actually hold — canon and disk together, with eye decisions on top.',
    'lib.q': 'Reference, title or place',
    'lib.repo': 'Archive', 'lib.repo.any': 'all archives',
    'lib.verdict': 'Verdict', 'lib.verdict.any': 'any',
    'lib.verdict.none': 'no verdict yet', 'lib.verdict.all': 'all cases',
    'lib.ondisk': 'only what is on disk',
    'lib.col.shifra': 'reference', 'lib.col.title': 'title', 'lib.col.years': 'years',
    'lib.col.place': 'place', 'lib.col.verdict': 'verdict',
    'lib.disk': 'on disk', 'lib.nodisk': 'not on disk',
    'lib.unbuilt': 'The summary has never been built — this does NOT mean there are no cases.',
    'lib.build': 'Build the summary',
    'lib.count': 'showing {n} of {total}',
    'lib.verdict.set': 'mark',
    'lib.verdict.clear': 'clear verdict',
    'lib.verdict.no_clan': 'clan not here',
    'lib.verdict.clan_found': 'clan found',
    'lib.verdict.recheck': 'check again',
    'lib.pages': 'How many leaves were looked at',
    'lib.pages.why': 'Without this number, "clan not here" will later be read as a proven zero.',
    'lib.note': 'What proves it',
    'lib.save': 'Save the decision',
    'lib.cancel': 'Not now',
    'nav.sift': 'Sift',
    'sift.title': 'Sifting the hits',
    'sift.keys': 'Keys: ← → to move · E — viewer · N — note it',

    'sift.empty': 'Nothing to sift yet — find something in the read text first.',
    'sift.togo': 'hit {i} of {n}',
    'sift.open': 'Sift these hits',
    'sift.crop': 'line crop',
    'sift.crop.load': 'show the crop',
    'sift.crop.fail': 'could not take the crop',
    'sift.context': 'neighbouring lines',
    'sift.score': 'score',
    'sift.prev': 'Back', 'sift.next': 'Next',
    'sift.note': 'Note this page',
    'sift.view': 'Open in the viewer',
    'sift.rule': 'THE EYE decides. The machine offered a candidate — read the crop '
      + 'yourself: a high score is not proof, and a mismatch is not a refutation.',
    'sift.stem': '⚠ Do not reject on the stem: the engine mangles the MIDDLE of a '
      + 'word, so the surname you want comes out of it unrecognisable.',
    'view.run.none': 'no such run',
    'view.run.empty': 'Nothing has been read yet — there is nothing to leaf through.',
    'view.overlay': 'Click a line on the scan to see its text.',
    'view.page': 'Whole page',
    'view.page.why': 'Expensive: a whole page weighs tens of times more than a line crop. But it is where you see WHOSE record this is and what stands next to it.',
    'view.zoom.fit': 'fit', 'view.zoom.in': 'larger', 'view.zoom.out': 'smaller',
    'view.close': 'Collapse',
    'cases.title': 'Cases in progress',
    'cases.frames': 'frames', 'cases.read': 'read', 'cases.none': 'not read',
    'cases.nodir': 'folder not present on this machine — nothing to edit',
    'cases.build': 'rebuild registry',
    'cases.build.why': 'The registry is a snapshot of five stores: after a run, a download or a note it goes stale within minutes.',
    'search.q': 'Surname', 'search.where': 'Where to look',
    'search.where.decode': 'in machine-read text',
    'search.where.pages': 'in noted surnames',
    'search.where.records': 'in record participants',
    'search.run': 'Search',
    'hit.eye': 'look at the line with your own eyes',
    'hit.note': 'note this page in the reading log',
    'search.coverage': 'searched across', 'search.runs': 'runs',
    'search.cases': 'cases noted by eye',
    'nav.eye': 'Eye',
    'eye.case': 'Case', 'eye.check': 'Already looked at',
    'eye.disk': 'on disk', 'eye.noted': 'noted', 'eye.left': 'not looked at yet',
    'eye.note': 'Note a page', 'eye.scan': 'Scan', 'eye.type': 'Type',
    'eye.surnames': 'Surnames AS WRITTEN (comma separated)',
    'eye.status': 'Completeness', 'eye.comment': 'Comment', 'eye.save': 'Save',
    'ptype.birth': 'birth', 'ptype.marriage': 'marriage',
    'ptype.death': 'death', 'ptype.confession': 'confession list',
    'ptype.revision': 'revision list', 'ptype.census': 'census',
    'ptype.index': 'index', 'ptype.title': 'title page',
    'ptype.cover': 'cover', 'ptype.flyleaf': 'flyleaf',
    'ptype.blank': 'blank', 'ptype.illegible': 'illegible',
    'ptype.mixed': 'mixed', 'ptype.other': 'other',
    'eye.rule': 'Note EVERY scan you opened — even an empty one. Otherwise you will open it again next time.',
    'case.title': 'Register or correct a case',
    'case.dir': 'Folder with scans', 'case.shifra': 'Reference',
    'case.name': 'Case title', 'case.type': 'Document type',
    'case.years': 'Years', 'case.place': 'Place', 'case.save': 'Save',
    'case.note': 'Note: where it came from, what is unclear',
    'case.adopt': 'Take this folder into the registry where it is',
    'case.adopt.why': 'Needed only for a folder OUTSIDE the workspace (external drive, desktop): otherwise the case will not appear in any listing. Nothing is moved — the folder is declared in nyshporka.toml.',
    'case.edit': 'Edit case description', 'case.fresh': 'Register another',
    'case.editing': 'Editing the description of',
    'case.keep': 'An empty field keeps the previous value — to erase a field, edit _source.json in the folder.',
    'case.why': 'Without a reference the folder stays a pile of files: no record of what was read, no way to cite a finding.',
    'nav.view': 'Viewer',
    'view.run': 'Run', 'view.open': 'Open',
    'view.pages': 'pages', 'view.lines': 'lines',
    'view.eye': 'The eye decides, the machine only proposes — look at the line, not the text.',
    'nav.read': 'Reading',
    'read.dir': 'Folder with scans (flat)', 'read.plan': 'What we will do',
    'read.go': 'Read', 'read.frames': 'frames', 'read.script': 'script',
    'read.model': 'model', 'read.voice': 'second voice',
    'read.started': 'Queued',
    'nav.export': 'Export',
    'export.case': 'Case', 'export.what': 'What to export',
    'export.records': 'parsed records', 'export.pages': 'surnames from pages',
    'export.run': 'Show', 'export.csv': 'Save CSV',
    'jobs.title': 'What is running',
    'jobs.none': 'Nothing is running right now',
    'jobs.cancel': 'Stop',
    'common.loading': 'One moment…',
    'common.error': 'Did not work',
    'common.frames': 'frames',
    'common.pages': 'pages',
    'common.page': 'page',
  },
};

let LANG = localStorage.getItem('nysh.lang') || 'uk';
const t = (key) => (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.uk[key] || key;

// ── секції ───────────────────────────────────────────────────────────────────
/**
 * Що ввімкнено в цьому просторі. Приходить із `/api/sections`, тобто з того
 * самого `core.sections`, який фільтрує операції на сервері.
 *
 * 🔴 Другого переліку екранів тут НЕМАЄ навмисно. Мапа «екран → секція» їде
 * полем `screens` тієї ж відповіді: копія в браузері розходилась би з сервером
 * тихо, і виглядало б це як кнопка, що веде в порожнечу.
 */
let SECTIONS = { sections: [], screens: {}, presets: {}, preset: null, glyphs: {} };

/** Порядок кнопок у шапці. Екрани, яких тут немає, кнопки не отримують. */
const NAV_ORDER = ['home', 'sources', 'geog', 'fonds', 'library', 'cases', 'newcase',
  'read', 'view', 'eye', 'search', 'sift', 'export', 'jobs'];

/** Ключ i18n для кнопки екрана. Підпис «Завести справу» вже є в словнику. */
const NAV_LABEL = {
  home: 'nav.home', sources: 'nav.sources', geog: 'nav.geog', fonds: 'nav.fonds',
  library: 'nav.library', cases: 'nav.cases', newcase: 'nav.newcase', read: 'nav.read', view: 'nav.view',
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
    if (env.ok) SECTIONS = env.data;
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
    const tail = s === 'jobs' ? '<sup id="jobcount"></sup>' : '';
    return `<button data-act="nav" data-arg="${s}"${s === here ? ' class="on"' : ''}>`
      + `${icon(icons[s])}${esc(t(NAV_LABEL[s] || s))}</button>${tail}`;
  }).join('');
}

/** Значок спрайта або порожньо — підпис кнопки читається й без нього. */
function icon(name) {
  return name ? ic(name, 'ic-sm') + ' ' : '';
}

/**
 * Покоління показу.
 *
 * 🔴 Кожен екран малює себе ПІСЛЯ `await`, і за цей час людина могла піти на
 * інший. Тоді повільніша відповідь домальовує свою таблицю поверх чужого
 * екрана — при тому, що підсвітка в шапці показує новий. Виглядає це як
 * «застосунок показує не те, що я відкрив», і ніяк не як помилка.
 *
 * `_libSeq` захищає лише від обігнаної відповіді В МЕЖАХ одного екрана; це —
 * спільний лічильник на перехід між ними.
 */
let SCREEN_GEN = 0;
const alive = (my) => my === SCREEN_GEN;

// ── транспорт ────────────────────────────────────────────────────────────────
const TOKEN = document.body.dataset.token || '';

async function callOp(name, args) {
  const res = await fetch(`/api/op/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Nysh-Token': TOKEN },
    body: JSON.stringify(args || {}),
  });
  const env = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  return env;
}

// ── розмітка ─────────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const el = (id) => document.getElementById(id);

/** Попередження конверта — на екран ЗАВЖДИ. Саме тут живе «нуль зі знаменником». */
function renderWarnings(env) {
  const bits = [];
  if (env.stale && env.stale.is) {
    // 🔴 Виправлення поруч із застереженням, а не в підказці «наберіть у
    // терміналі». Той, хто працює формами, інакше лишається із застереженням
    // і без способу його зняти — тобто змушений вірити застарілому зрізу.
    bits.push(`<div class="warn stale">⚠ ${esc(env.stale.reasons.join('; '))}
      <button data-act="cases.build">${t('cases.build')}</button></div>`);
  }
  for (const w of env.warnings || []) {
    bits.push(`<div class="warn">⚠ ${esc(w.text)}</div>`);
  }
  return bits.join('');
}

/**
 * Покриття конверта — ДЕ САМЕ шукали і якого воно зрізу.
 *
 * 🔴 Друга половина правила «нуль мусить щось означати». Перша — відмова
 * джерела, яке шукати не може; ця — про джерела, які змогли: порожня видача без
 * переліку переглянутого не відрізняється на екрані від «ніде не шукали», а
 * коштує ця плутанина напряму пошуку, закритого назавжди.
 */
function renderCoverage(env) {
  const cov = env.coverage || [];
  if (!cov.length) return '';
  const bits = cov.map((c) => {
    const taken = c.taken ? `, зріз ${esc(c.taken)}` : '';
    const scope = c.scope ? ` — ${esc(c.scope)}` : '';
    return `${esc(c.source)}${taken}${scope}`;
  });
  return `<p class="muted cov">🔎 ${t('cov.searched')}: ${bits.join('; ')}</p>`;
}

/**
 * Замінити вміст екрана.
 *
 * ⚠ Через `swapHtml`, а не присвоєнням `innerHTML`: голе присвоєння схлопує
 * контейнер у нульову висоту на один кадр, і сторінка під ним підстрибує —
 * найпомітніше на довгих таблицях, де око вже стоїть на потрібному рядку.
 * `keepScroll: false` тут навмисно: зміна екрана мусить починатись згори.
 */
function setView(html) { swapHtml(el('view'), html, { keepScroll: false }); }

/**
 * Стан завантаження.
 *
 * 🔴 Скелетон, а не рядок «завантаження…»: текстова заглушка має іншу висоту за
 * дані, тож у момент їх приходу вміст стрибає. Скелетон тримає приблизно ту
 * саму висоту, і сторінка лишається на місці.
 */
function busy(rows = 8) {
  setView(`<table><tbody>${skelRows(rows, 4)}</tbody></table>`);
}

function failure(env) {
  setView(`<div class="warn err">${t('common.error')}: ${esc(env.error || '?')}</div>`);
}

/**
 * 📖 Що сказати про зразкову справу — три РІЗНІ стани, і плутати їх дорого.
 *
 * «Зразка немає в цій збірці» — межа версії, лагодити нічого. «Є, але не
 * розгорнутий» — одна кнопка. «Розгорнутий» — запрошення в гортач. Спільне
 * формулювання на всі три посилало б людину лагодити те, що справне, або
 * ховало б дію, яка є.
 */
function sampleBlock(d) {
  if (!d.sample_available) return `<p class="muted">${t('check.nosample')}</p>`;
  if (d.sample_case) return `<p class="muted">✅ ${t('check.sample.ready')}</p>`;
  return `<p class="muted">${t('check.sample.hint')}</p>
    <p><button data-act="sample.install">${t('check.sample.do')}</button></p>`;
}

// ── екрани ───────────────────────────────────────────────────────────────────
/**
 * Типи сторінок — рівно ті, що приймає сховище.
 *
 * 🔴 Порядок не абетковий, а за частотою в роботі: метричні рубрики першими,
 * службові аркуші наприкінці. Заносити доводиться сотні сторінок поспіль, і
 * зайвий рух до потрібного рядка множиться на цю сотню.
 */
const PAGE_TYPES = ['birth', 'marriage', 'death', 'confession', 'revision',
  'census', 'index', 'title', 'cover', 'flyleaf', 'blank', 'illegible',
  'mixed', 'other'];

const SCREENS = {};

/** Остання вивантажена таблиця — щоб CSV збирався без повторного запиту. */
let LAST_EXPORT = null;

/** Остання тека, для якої рахували план читання. */
let LAST_READ = null;

/** Прогін і сторінка, відкриті в гортачі. */
let VIEW = null;

/** Справа, відкрита в обліку прочитаного. */
let EYE = null;

/**
 * Опис, підвантажений у форму «Завести справу» для ПРАВКИ.
 *
 * 🔴 Порожня форма над уже описаною текою — пастка: людина бачить порожні
 * поля, вважає, що опису немає, і друкує його заново — часто інакше, ніж
 * попереднього разу. Тому правка починається з показу записаного.
 */
let EDIT = null;

SCREENS.home = async () => {
  const env = await callOp('workspace.info', {});
  const ws = env.ok ? env.data : {};
  setView(`
    <h2>${t('home.title')}</h2>
    ${renderWarnings(env)}
    <div class="cards">
      <button class="card" data-act="home.scans">
        <span class="card-title">📁 ${t('home.have_scans')}</span>
        <span class="card-hint">${t('home.have_scans.hint')}</span>
      </button>
      <button class="card" data-act="nav" data-arg="sources">
        <span class="card-title">🔎 ${t('home.where')}</span>
        <span class="card-hint">${t('home.where.hint')}</span>
      </button>
      <button class="card" data-act="home.demo">
        <span class="card-title">▶ ${t('home.demo')}</span>
        <span class="card-hint">${t('home.demo.hint')}</span>
      </button>
    </div>
    <p class="muted mono">${esc(ws.root || '')}</p>`);
};

SCREENS.sources = async () => {
  setView(`
    <h2>${t('nav.sources')}</h2>
    <form class="row" data-act="sources.find">
      <input name="q" placeholder="${t('sources.q')}" autofocus>
      <button type="submit">${t('sources.find')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.cases = async () => {
  const gen = SCREEN_GEN;
  busy();
  const env = await callOp('cases.list', { limit: 100 });
  if (!alive(gen)) return;
  if (!env.ok) return failure(env);
  const rows = env.data.cases || [];
  setView(`
    <h2>${t('cases.title')} <button data-act="cases.build"
      title="${t('cases.build.why')}">🔄 ${t('cases.build')}</button></h2>
    ${renderWarnings(env)}
    <table><thead><tr>
      <th>шифра</th><th>назва</th><th class="num">${t('common.frames')}</th>
      <th>читання</th><th></th></tr></thead><tbody>
    ${rows.map((r) => `<tr>
      <td class="mono">${esc(r.shifra || r.key)}</td>
      <td>${esc((r.title || '').slice(0, 90))}</td>
      <td class="num">${esc(r.frames || 0)}</td>
      <td>${r.htr_stage && r.htr_stage !== 'none'
        ? `${t('cases.read')} ${esc(r.htr_pages_max || '')}`
        : `<span class="muted">${t('cases.none')}</span>`}</td>
      <td>${r.path
        ? `<button data-act="case.edit" data-arg="${esc(r.path)}"
             title="${t('case.edit')}">✏</button>`
        : `<span class="muted" title="${t('cases.nodir')}">—</span>`}</td>
    </tr>`).join('')}
    </tbody></table>`);
};

/**
 * 🗺 Газетир — від СЕЛА до справ по ВСІХ фондах архіву.
 *
 * 🔑 Найчастіший перший крок дослідника: він знає село, а не фонд. Реєстр опису
 * на це відповісти не може — він знає один фонд і мовчить про сусідні.
 *
 * 🕍 Конфесія тут ФІЛЬТР, а не три окремі довідники: метрики православної
 * громади, костелу й рабинату одного містечка лежать у РІЗНИХ фондах, тож
 * дефолт «усі» — не зручність, а захист від систематичного недобору.
 */
/**
 * 📚 Бібліотека справ — що взагалі є на руках.
 *
 * Відповідає на питання, якого не закриває «Мої справи»: там ідеться про взяте
 * під облік у цьому просторі, тут — про весь матеріал разом із рішеннями ока.
 *
 * 🔴 Порожня бібліотека і НЕЗІБРАНА бібліотека показуються по-різному. «0 справ»
 * читається як факт («шукати нема де»), і людина закриває напрям, якого ніхто
 * не відкривав; тому незібране каже про себе прямо й дає кнопку.
 */
let LIB = { q: '', repo: '', verdict: '', on_disk: null };
/**
 * Лічильник запитів бібліотеки.
 *
 * ⚠ Захист від ОБІГНАНОЇ відповіді: фільтр набирають швидко, запити летять
 * підряд, і повільніший ранній може прийти ПІСЛЯ свіжого — на екрані лишиться
 * видача, що не відповідає полю. Не падає, не помиляється видимо, і саме тому
 * дорого: людина вирішує по тому, що бачить.
 */
let _libSeq = 0;

SCREENS.library = async () => {
  busy();
  await libLoad(true);
};

/**
 * @param {boolean} full  перемалювати весь екран (вхід) чи лише видачу (фільтр).
 *
 * 🔴 Фільтр оновлює ТІЛЬКИ таблицю. Перемальовуючи весь екран, ми щоразу
 * знищували б поле пошуку разом із фокусом і кареткою — і символи, набрані
 * після паузи в 250 мс, ішли б у нікуди. Виглядає це як «клавіатура загубилась»,
 * а не як помилка.
 */
async function libLoad(full = false) {
  const seq = ++_libSeq;
  const gen = SCREEN_GEN;
  const env = await callOp('library.list', {
    q: LIB.q, repo: LIB.repo, verdict: LIB.verdict,
    ...(LIB.on_disk === null ? {} : { on_disk: LIB.on_disk }),
  });
  if (seq !== _libSeq) return;          // нас уже обігнав свіжіший запит
  if (!alive(gen)) return;              // з бібліотеки вже пішли
  if (!env.ok) return failure(env);
  const d = env.data || {};
  const rows = d.cases || [];
  const count = esc(t('lib.count')
    .replace('{n}', d.shown ?? 0).replace('{total}', d.total ?? 0));

  if (!full) {
    // Каркас на місці — міняється лише вміст. `swapHtml` тримає висоту
    // контейнера на час підміни, тож сторінка під таблицею не підстрибує.
    const body = el('lib-rows');
    if (body) swapHtml(body, rows.map(libRow).join(''));
    const n = el('lib-count');
    if (n) n.textContent = count;
    const warn = el('lib-warn');
    if (warn) warn.innerHTML = renderWarnings(env);
    return;
  }

  const head = `<h2>${ic('books')} ${t('lib.title')}</h2>
    <p class="muted">${t('lib.why')}</p>`;

  if (!d.built) {
    setView(`${head}${renderWarnings(env)}
      <div class="warn">${t('lib.unbuilt')}
        <button data-act="cases.build">${t('lib.build')}</button></div>`);
    return;
  }

  const opt = (v, label, cur) =>
    `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
  // Перелік архівів дає СЕРВЕР — по всій бібліотеці. Зібраний із видачі, він
  // схлопувався б до одного пункту після першого ж вибору.
  const repos = d.repos || [];
  const kinds = d.kinds || {};

  setView(`${head}
    <div class="row">
      <input id="lib-q" type="search" placeholder="${esc(t('lib.q'))}"
             value="${esc(LIB.q)}" data-act="lib.filter" data-live="1">
      <select id="lib-repo" data-act="lib.filter">
        ${opt('', t('lib.repo.any'), LIB.repo)}
        ${repos.map((r) => opt(r, r, LIB.repo)).join('')}
      </select>
      <select id="lib-verdict" data-act="lib.filter">
        ${opt('', t('lib.verdict.all'), LIB.verdict)}
        ${opt('any', t('lib.verdict.any'), LIB.verdict)}
        ${opt('none', t('lib.verdict.none'), LIB.verdict)}
        ${Object.keys(kinds).map((k) =>
          opt(k, t(`lib.verdict.${k}`), LIB.verdict)).join('')}
      </select>
      <label class="lbl-mini"><input type="checkbox" id="lib-disk"
        data-act="lib.filter"${LIB.on_disk ? ' checked' : ''}> ${t('lib.ondisk')}</label>
    </div>
    <div id="lib-warn">${renderWarnings(env)}</div>
    <p class="muted" id="lib-count">${count}</p>
    <table><thead><tr>
      <th>${t('lib.col.shifra')}</th><th>${t('lib.col.title')}</th>
      <th class="num">${t('lib.col.years')}</th><th>${t('lib.col.place')}</th>
      <th>${t('lib.col.verdict')}</th></tr></thead>
    <tbody id="lib-rows">${rows.map(libRow).join('')}</tbody></table>`);
}

function libRow(r) {
  const years = [r.year_from, r.year_to].filter(Boolean).join('–');
  const disk = r.on_disk
    ? `<span title="${esc(t('lib.disk'))}">${ic('disk', 'ic-sm')}</span>`
    : `<span class="muted" title="${esc(t('lib.nodisk'))}">—</span>`;
  const v = r.verdict
    ? `<span class="badge ${r.verdict === 'clan_found' ? 'known' : ''}"
         title="${esc(r.verdict_note || '')}">${esc(t(`lib.verdict.${r.verdict}`))}</span>`
    : '';
  return `<tr>
    <td class="mono">${disk} ${esc(r.shifra || r.key || '')}</td>
    <td>${esc((r.title || '').slice(0, 90))}</td>
    <td class="num">${esc(years)}</td>
    <td>${esc(r.place || '')}</td>
    <td>${v} <button class="ctl-sm" data-act="lib.verdict" data-arg="${esc(r.key)}"
      title="${esc(t('lib.verdict.set'))}">${ic('pencil-line', 'ic-o ic-sm')}</button></td>
  </tr>`;
}

/**
 * Форма рішення по справі.
 *
 * 🔴 Поле «скільки аркушів переглянуто» стоїть ПОРУЧ із «роду немає», а не в
 * примітці: нуль без знаменника не результат, і саме цей вердикт наступного
 * разу закриє напрям. Порожнім лишити можна — вердикт виносить людина, і
 * машина не має права не пустити її рішення, — але мовчки це не проходить.
 */
function libVerdictForm(key) {
  setView(`<h2>${ic('pencil-line')} ${esc(key)}</h2>
    <div class="row"><select id="lv-kind">
      <option value="">${esc(t('lib.verdict.clear'))}</option>
      <option value="no_clan">${esc(t('lib.verdict.no_clan'))}</option>
      <option value="clan_found">${esc(t('lib.verdict.clan_found'))}</option>
      <option value="recheck">${esc(t('lib.verdict.recheck'))}</option>
    </select></div>
    <div class="row"><input id="lv-pages" type="number" min="0"
      placeholder="${esc(t('lib.pages'))}"></div>
    <p class="muted">${t('lib.pages.why')}</p>
    <div class="row"><input id="lv-note" placeholder="${esc(t('lib.note'))}"></div>
    <button data-act="lib.verdict.save" data-arg="${esc(key)}">${t('lib.save')}</button>
    <button data-act="nav" data-arg="library">${t('lib.cancel')}</button>`);
}

SCREENS.geog = async () => {
  busy();
  // 🔴 Стан довідників показуємо ОДРАЗУ, поруч із полем пошуку, а не ховаємо в
  // діагностику. Це і є знаменник: без нього «нічого не знайдено» не
  // відрізнити від «нема де шукати», і людина закриє напрям, якого не
  // перевіряла. Особливо на щойно встановленому застосунку.
  const packs = await callOp('catalog.packs', {});
  const ok = ((packs.data || {}).packs || []).filter((x) => x.state === 'ok');
  setView(`
    <h2>${t('geog.title')}</h2>
    <p class="muted">${t('geog.why')}</p>
    ${ok.length ? '' : `<div class="warn">${t('catalog.none')}</div>`}
    <form class="row" data-act="geog.find">
      <input name="q" placeholder="${t('geog.q')}" autofocus>
      <select name="section">
        <option value="">${t('geog.section.all')}</option>
        <option value="church">${t('geog.section.church')}</option>
        <option value="decanats">${t('geog.section.decanats')}</option>
        <option value="rabbinate">${t('geog.section.rabbinate')}</option>
      </select>
      <button type="submit">${t('geog.find')}</button>
    </form>
    <div id="geoghits"></div>
    <h3>${t('catalog.title')}</h3>
    <table><tbody>${ok.map((x) => `<tr>
      <td class="mono">${esc(x.pack_id)}</td>
      <td>${x.taken ? `зріз ${esc(x.taken)}` : ''}</td>
      <td class="muted">${esc(x.note || '')}</td>
    </tr>`).join('')}</tbody></table>
    ${renderWarnings(packs)}`);
};

/**
 * 🏛 Фонди — реєстр ОПИСУ: «що взагалі існує в архіві».
 *
 * Третє сховище поруч із «мої справи». Плутати їх дорого: «справи немає» тут
 * означає «в архіві не існує», а в «моїх справах» — «ще не завантажено».
 */
SCREENS.fonds = async () => {
  busy();
  const env = await callOp('fond.list', {});
  if (!env.ok) return failure(env);
  const fonds = env.data.fonds || [];
  if (!fonds.length) {
    return setView(`<h2>${t('fonds.title')}</h2>${renderWarnings(env)}
      <p class="muted">${t('catalog.none')}</p>`);
  }
  setView(`
    <h2>${t('fonds.title')}</h2>
    <p class="muted">${t('fonds.why')}</p>
    ${renderWarnings(env)}
    <form class="row" data-act="fond.rows">
      <select name="fond">
        ${fonds.map((f) => `<option value="${esc(f.id)}">${esc(f.label)} —
          ${f.rows} ${t('fonds.rows')}, ${t('fonds.ondisk')} ${f.on_disk}, ${t('fonds.todo')} ${f.todo}</option>`).join('')}
      </select>
      <input name="q" placeholder="${t('fonds.filter')}">
      <input name="surname" placeholder="${t('fonds.surname')}" size="18">
      <input name="uezd" placeholder="${t('fonds.uezd')}" size="12">
      <select name="state">
        <option value="">${t('fonds.state.any')}</option>
        <option value="disk">${t('fonds.state.disk')}</option>
        <option value="todo">${t('fonds.state.todo')}</option>
        <option value="film">${t('fonds.state.film')}</option>
        <option value="order">${t('fonds.state.order')}</option>
      </select>
      <button type="submit">${t('geog.find')}</button>
    </form>
    <div id="fondrows"></div>`);
};

SCREENS.search = async () => {
  setView(`
    <h2>${t('nav.search')}</h2>
    <form class="row" data-act="search.run">
      <input name="q" placeholder="${t('search.q')}" autofocus>
      <select name="where">
        <option value="decode">${t('search.where.decode')}</option>
        <option value="pages">${t('search.where.pages')}</option>
        <option value="records">${t('search.where.records')}</option>
      </select>
      <button type="submit">${t('search.run')}</button>
    </form>
    <div id="hits"></div>`);
};

/**
 * 🔬 Розбір знахідок — те місце, де машина віддає рішення людині.
 *
 * Пошук подає рядки, схожі на запит; чи це справді шукане прізвище, видно лише
 * на самому знімку. Тому картка несе ВИРІЗКУ, а не самий декод: рушій калічить
 * середину слова, і текст, у якому «не той корінь», може бути рівно тим
 * прізвищем, по яке пошук і кликали.
 *
 * 🔴 Два правила стоять НА ЕКРАНІ, а не в документації, бо порушують їх саме
 * тут: вирішує око, і відсівати за коренем не можна.
 */
let SIFT = { hits: [], i: 0, q: '', crop: null, ctx: null };

SCREENS.sift = async () => {
  const gen = SCREEN_GEN;
  if (!SIFT.hits.length) {
    setView(`<h2>${ic('crop-check')} ${t('sift.title')}</h2>
      <div class="warn">${t('sift.empty')}
        <button data-act="nav" data-arg="search">${t('nav.search')}</button></div>`);
    return;
  }
  siftDraw();
  if (!alive(gen)) return;
  await siftLoadCrop();
};

function siftDraw() {
  const h = SIFT.hits[SIFT.i] || {};
  const badge = h.engine ? eng(h.engine, true, LANG) : '';
  const pos = t('sift.togo').replace('{i}', SIFT.i + 1).replace('{n}', SIFT.hits.length);
  // Збіг підсвічується в рядку, але НЕ вирізається з нього: сусідні слова —
  // це роль і відмінок, тобто половина того, за чим упізнають запис.
  const line = esc(h.line || '');
  const lit = h.matched
    ? line.replace(esc(h.matched), `<mark>${esc(h.matched)}</mark>`)
    : line;
  setView(`<h2>${ic('crop-check')} ${t('sift.title')}</h2>
    <div class="row">
      <button data-act="sift.step" data-arg="-1"${SIFT.i ? '' : ' disabled'}>
        ${ic('arrow-left', 'ic-sm')} ${t('sift.prev')}</button>
      <span class="muted">${esc(pos)}</span>
      <button data-act="sift.step" data-arg="1"${
        SIFT.i + 1 < SIFT.hits.length ? '' : ' disabled'}>${t('sift.next')}</button>
    </div>
    <div class="warn">${t('sift.rule')}</div>
    <p class="mono">${esc(h.name || '')} · ${t('common.page')} ${esc(h.page || '')}
       · ${badge} · ${t('sift.score')} ${esc(h.score || '')}</p>
    <div id="sift-crop"><p class="muted">${t('sift.crop.load')}…</p></div>
    <p class="mono">${lit}</p>
    <div id="sift-ctx"></div>
    <p class="muted">${t('sift.stem')}</p>
    <div class="row">
      <button data-act="sift.view">${ic('eye', 'ic-sm')} ${t('sift.view')}</button>
      <button data-act="sift.note">${ic('pencil-line', 'ic-sm')} ${t('sift.note')}</button>
    </div>
    <p class="dim">${t('sift.keys')}</p>`);
}

/** Вирізка поточного рядка. Окремим кроком: сторінка коштує ~1.1 МБ, рядок 15 КБ. */
async function siftLoadCrop() {
  const h = SIFT.hits[SIFT.i] || {};
  const box = el('sift-crop');
  if (!box || !h.name) return;
  const env = await callOp('page.view', {
    run: h.name, page: h.page, line: h.line_index, region: 'line',
  });
  if (!env.ok || !(env.data || {}).image) {
    box.innerHTML = `<p class="muted">${t('sift.crop.fail')}</p>`;
    return;
  }
  box.innerHTML = `<img src="${esc(env.data.image)}" alt="${esc(t('sift.crop'))}"
    style="max-width:100%;background:var(--paper);border:1px solid var(--paper-edge);
           border-radius:var(--r-m)">`;
  // Сусідні рядки — той самий «контекст двох голосів»: роль і відмінок стоять
  // поряд, а не в самому слові.
  const ctx = await callOp('page.text', { run: h.name, page: h.page });
  const cbox = el('sift-ctx');
  if (!cbox || !ctx.ok) return;
  const lines = (ctx.data || {}).lines || [];
  const near = lines.slice(Math.max(0, (h.line_index || 0) - 1), (h.line_index || 0) + 2);
  cbox.innerHTML = near.length
    ? `<p class="muted">${t('sift.context')}</p><pre>${near
        .map((l) => esc(typeof l === 'string' ? l : l.text || '')).join('\n')}</pre>`
    : '';
}

SCREENS.eye = async () => {
  const e = EYE || {};
  setView(`
    <h2>${t('nav.eye')}</h2>
    <p class="muted">${t('eye.rule')}</p>
    <form class="row" data-act="eye.check">
      <input name="case" placeholder="${t('eye.case')}: DAHMO/315/8433"
        value="${esc(e.case || '')}" ${e.case ? '' : 'autofocus'}>
      <button type="submit">${t('eye.check')}</button>
    </form>
    <div id="hits"></div>`);
  if (!e.case) return;
  await ACTIONS['eye.check']({
    preventDefault() {}, target: el('view').querySelector('form') });
  // Скан, на якому спрацював пошук, підставляється у форму занесення: людина
  // прийшла сюди саме з нього, і набирати його ще раз — зайвий шанс на описку.
  const note = el('view').querySelector('form[data-act="eye.note"]');
  if (note && e.scan) note.querySelector('input[name="scan"]').value = e.scan;
};

SCREENS.newcase = async () => {
  const sc = (EDIT && EDIT.sidecar) || {};
  const v = (k) => esc(sc[k] === null || sc[k] === undefined ? '' : sc[k]);
  const dir = EDIT ? esc(EDIT.case_dir) : '';
  setView(`
    <h2>${EDIT ? t('case.edit') : t('case.title')}</h2>
    <p class="muted">${t('case.why')}</p>
    ${EDIT ? `<div class="warn">${t('case.editing')} <b class="mono">${dir}</b>
       · ${esc(EDIT.scans)} ${t('common.frames')}<br>
       <span class="muted">${t('case.keep')}</span></div>` : ''}
    <form data-act="case.save">
      <div class="row"><input name="case_dir" placeholder="${t('case.dir')}"
        value="${dir}" ${EDIT ? '' : 'autofocus'}></div>
      ${EDIT ? '' : `<p class="muted">${t('case.dirhint')}</p>`}
      <div class="row">
        <input name="shifra" placeholder="${t('case.shifra')}: ДАХмО 315-1-8433"
          value="${v('shifra')}">
        <input name="doc_type" placeholder="${t('case.type')}: метрична"
          value="${v('doc_type')}">
      </div>
      <div class="row"><input name="title" placeholder="${t('case.name')}"
        value="${v('title')}" ${EDIT ? 'autofocus' : ''}></div>
      <div class="row">
        <input name="place" placeholder="${t('case.place')}" value="${v('place')}">
        <input name="year_from" placeholder="${t('case.years')}: 1858" size="6"
          value="${v('year_from')}">
        <input name="year_to" placeholder="1860" size="6" value="${v('year_to')}">
      </div>
      <div class="row"><input name="note" placeholder="${t('case.note')}"
        value="${v('note')}"></div>
      <div class="row"><label><input type="checkbox" name="adopt" value="1">
        ${t('case.adopt')}</label></div>
      <p class="muted">${t('case.adopt.why')}</p>
      <div class="row"><button type="submit">${t('case.save')}</button>
        ${EDIT ? `<button type="button" data-act="case.fresh">${t('case.fresh')}</button>`
          : ''}</div>
    </form>
    <div id="hits"></div>`);
  EDIT = null;
};

SCREENS.view = async () => {
  // Значення підставляє САМ екран, а не той, хто на нього переходить: інакше
  // перехід із пошуку мусив би підробляти подію форми, і будь-яка зміна
  // розмітки тихо ламала б саме цей шлях.
  const v = VIEW || {};
  setView(`
    <h2>${t('nav.view')}</h2>
    <p class="muted">${t('view.eye')}</p>
    <form class="row" data-act="view.open">
      <input name="run" placeholder="${t('view.run')}" value="${esc(v.run || '')}"
        ${v.run ? '' : 'autofocus'}>
      <input name="page" placeholder="00003.JPG" value="${esc(v.page || '')}">
      <button type="submit">${t('view.open')}</button>
      <button type="button" data-act="view.page" title="${esc(t('view.page.why'))}">
        ${ic('image', 'ic-sm')} ${t('view.page')}</button>
    </form>
    <div id="stage"></div>
    <div id="hits"></div>`);
  // 🔴 Підказка, а не вільний рядок. Імена прогонів довгі й схожі між собою
  // (одна справа читається двічі — латинка й кирилиця), тож набраний руками
  // рядок помиляється саме тоді, коли шукають конкретну сторінку: гортач
  // відповідає «немає такого прогону», і це читається як «сторінки немає».
  // Список береться з сервера; не приїхав — поле лишається звичайним.
  await viewRunHints();
  if (v.run && v.page) {
    await ACTIONS['view.open']({
      preventDefault() {}, target: el('view').querySelector('form') });
    if (v.line !== null && v.line !== undefined) {
      await ACTIONS['view.line']({}, { dataset: { line: String(v.line) } });
    }
  }
};

/**
 * 🖼 Сторінка цілком.
 *
 * 🔴 Окремою дією, а не одразу: вирізка рядка важить 15 КБ, ціла сторінка —
 * близько мегабайта, і при розборі десятків знахідок різниця вирішує. Але
 * рядок сам по собі не каже, ЧИЙ це запис: роль, відмінок і сусідні імена
 * стоять поруч, а не в самому слові.
 *
 * Зум — шириною зображення, без канви: канва потрібна там, де по знімку
 * МАЛЮЮТЬ, а тут на нього дивляться.
 */
let ZOOM = 100;

/** Живий комбобокс гортача — щоб було що прибрати перед наступним. */
let _runCb = null;

/**
 * Підказки для поля прогону: перелік прочитаного з сервера.
 *
 * ⚠ Перед новим чіпляємо — старий прибираємо. `setView` щоразу створює НОВЕ
 * поле, тож внутрішній гард `input._cb` не спрацьовує, і без `destroy()` у
 * `<body>` накопичувались би попапи, а на `document` — слухачі, що тримають
 * посилання на давно викинуті поля.
 */
async function viewRunHints() {
  if (_runCb) { _runCb.destroy(); _runCb = null; }
  const input = el('view').querySelector('input[name="run"]');
  if (!input) return;
  const env = await callOp('runs.list', {});
  if (!env.ok) return;
  const runs = (env.data || {}).runs || [];
  _runCb = attachCombobox(input, {
    items: runs.map((r) => r.name).filter(Boolean),
    empty: t('view.run.none'),
  });
  // Знаменник поруч: «нічого не знайшлось» у гортачі означає різне при
  // нулі прочитаних справ і при трьохстах.
  const box = el('stage');
  if (box && !runs.length) {
    box.innerHTML = `<div class="warn">${t('view.run.empty')}</div>`;
  }
}

async function viewWholePage() {
  const box = el('stage');
  const form = el('view').querySelector('form');
  if (!box || !form) return;
  const run = form.run.value.trim();
  const page = form.page.value.trim();
  if (!run || !page) return;
  box.innerHTML = `<p class="muted">${t('common.loading')}</p>`;
  const env = await callOp('page.view', { run, page, region: 'page' });
  if (!env.ok || !(env.data || {}).image) {
    box.innerHTML = `<div class="warn err">${esc(env.error || t('sift.crop.fail'))}</div>`;
    return;
  }
  ZOOM = 100;
  // Рамки рядків — окремим запитом: вони є не в кожного прогону, і сторінка
  // мусить показатись навіть тоді, коли їх немає.
  const geo = await callOp('page.lines', { run, page });
  const g = (geo.ok && geo.data) || {};
  box.innerHTML = `
    <div class="row">
      <button data-act="view.zoom" data-arg="-25">${t('view.zoom.out')}</button>
      <button data-act="view.zoom" data-arg="fit">${t('view.zoom.fit')}</button>
      <button data-act="view.zoom" data-arg="25">${t('view.zoom.in')}</button>
      <button data-act="view.stage.close">${t('view.close')}</button>
    </div>
    ${g.has ? `<p class="dim">${t('view.overlay')}</p>`
            : renderWarnings(geo)}
    <div class="stage"><div class="stage-wrap" style="width:${ZOOM}%">
      <img id="stage-img" src="${esc(env.data.image)}" alt="${esc(page)}">
      ${stageOverlay(g)}
    </div></div>
    <div id="stage-line"></div>`;
}

/**
 * 🖼 Рамки рядків поверх знімка.
 *
 * SVG у тих самих координатах, що й зображення (`viewBox` = розмір сторінки),
 * тож масштаб бере на себе браузер — при зумі нічого перераховувати не треба.
 *
 * ⚠ `pointer-events: fill` навмисно: фігура намальована без заливки, і без
 * цього клік ловився б лише самою лінією обведення — тобто попадати треба було
 * б у два пікселі. Правило живе в base.css поруч із рештою примітивів.
 */
function stageOverlay(g) {
  if (!g.has || !g.size) return '';
  const [w, h] = g.size;
  const shapes = (g.polys || g.boxes || []).map((sh, i) => {
    // 🔴 `null` тут — законне значення, а не поламані дані: рядок без обведення
    // й без базової лінії рамки не має, і раннер пише в масив саме `null`,
    // зберігаючи довжину. Без цієї перевірки `sh[0]` кидає TypeError ПОСЕРЕД
    // обчислення шаблона, тобто `innerHTML` не присвоюється зовсім — і
    // «сторінка цілком» назавжди лишається на «Хвилинку…», без картинки й без
    // кнопки «Згорнути».
    //
    // ⚠ Індекс береться з `map`, а не з лічильника вцілілих: він же номер
    // рядка в тексті, і зсунувши його, клік показував би чужий рядок.
    if (!Array.isArray(sh) || !sh.length) return '';
    const attrs = `class="ln" data-act="view.line.pick" data-arg="${i}"`;
    return Array.isArray(sh[0])
      ? `<polygon ${attrs} points="${sh.map((pt) => pt.join(',')).join(' ')}"/>`
      : `<rect ${attrs} x="${sh[0]}" y="${sh[1]}"
           width="${sh[2] - sh[0]}" height="${sh[3] - sh[1]}"/>`;
  });
  return `<svg class="stage-ov" viewBox="0 0 ${w} ${h}"
    preserveAspectRatio="none" aria-hidden="true">${shapes.join('')}</svg>`;
}

SCREENS.read = async () => {
  setView(`
    <h2>${t('nav.read')}</h2>
    <form class="row" data-act="read.plan">
      <input name="case_dir" placeholder="${t('read.dir')}" autofocus>
      <select name="script">
        <option value="">${t('read.script')}: авто</option>
        <option value="cyrillic">кирилиця</option>
        <option value="latin">латинка</option>
      </select>
      <button type="submit">${t('read.plan')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.export = async () => {
  setView(`
    <h2>${t('nav.export')}</h2>
    <form class="row" data-act="export.run">
      <input name="case" placeholder="${t('export.case')}: DAHMO/315/8433" autofocus>
      <select name="what">
        <option value="records">${t('export.records')}</option>
        <option value="pages">${t('export.pages')}</option>
      </select>
      <button type="submit">${t('export.run')}</button>
    </form>
    <div id="hits"></div>`);
};

SCREENS.jobs = async () => {
  setView(`<h2>${t('jobs.title')}</h2><div id="jobs"></div>`);
  await refreshJobs();
};

/**
 * ⚙ Налаштування: які частини застосунку ввімкнено.
 *
 * Пресет — те, з чого починають («я тут щоб прочитати свої скани»), окремі
 * перемикачі — для того, хто вже знає, чого хоче. Порожня секція показується
 * сірою й непереставною: вона оголошена, але вмикати в ній ще нічого, а
 * кнопка, що нічого не додає до шапки, читається як поламана.
 */
SCREENS.settings = async () => {
  busy();
  const env = await callOp('sections.show', {});
  if (!env.ok) return failure(env);
  SECTIONS = env.data;
  const presets = Object.keys(env.data.presets || {});
  const rows = (env.data.sections || []).map((s) => {
    const label = LANG === 'en' ? s.label_en : s.label;
    const why = LANG === 'en' ? s.why_en : s.why;
    const screens = (s.screens || []).map((x) => esc(t(NAV_LABEL[x] || x))).join(' · ');
    // Знак секції — той самий, що в переліку `nysh sections`: два обличчя одного
    // застосунку не мають виглядати як два різні продукти.
    const g = ((env.data.glyphs || {}).sections || {})[s.id] || '';
    let control;
    if (s.required) {
      control = `<span class="muted">${t('sect.always')}</span>`;
    } else if (!s.visible) {
      control = `<span class="muted">${t('sect.empty')}</span>`;
    } else {
      control = `<button data-act="sections.toggle" data-arg="${esc(s.id)}"
        data-on="${s.active ? '1' : ''}">${s.active ? t('sect.off') : t('sect.on')}</button>`;
    }
    return `<tr>
      <td>${s.active ? '✅' : (s.visible ? '⬜' : '▫️')}</td>
      <td><b>${g ? esc(g) + ' ' : ''}${esc(label)}</b><br><span class="muted">${esc(why)}</span>
          ${screens ? `<br><span class="muted mono">${screens}</span>` : ''}</td>
      <td class="num">${s.ops}</td>
      <td>${control}</td>
    </tr>`;
  }).join('');
  setView(`<h2>⚙ ${t('sect.title')}</h2>
    <p class="muted">${t('sect.why')}</p>
    ${renderWarnings(env)}
    <p>${t('sect.preset')}:
      ${presets.map((p) => `<button data-act="sections.preset" data-arg="${esc(p)}"
        ${p === env.data.preset ? 'disabled' : ''}>${esc(t('preset.' + p))}</button>`).join(' ')}
      <span class="muted">${env.data.preset ? '' : t('sect.custom')}</span></p>
    <table><tbody>${rows}</tbody></table>`);
};

// ── дії ──────────────────────────────────────────────────────────────────────
const ACTIONS = {
  nav: (_ev, elm) => show(elm.dataset.arg),

  /** Клік по розділу веде на його ПЕРШИЙ екран, а не просто перемальовує
      смугу: розділ без відкритого екрана виглядав би як кнопка, що нічого не
      робить. */
  group: (_ev, elm) => {
    GROUP = elm.dataset.arg;
    const first = groupScreens(GROUP)[0];
    return first ? show(first) : renderNav();
  },

  /** Тема: авто → світла → темна → авто. Значок показує ПОТОЧНИЙ режим. */
  'theme.cycle': () => cycleTheme(),
  /** Фільтр бібліотеки. Читає ВСІ поля одразу: інакше зміна одного скидала б
      інші до дефолтів, і видача не відповідала б тому, що видно на екрані. */
  'lib.filter': () => {
    LIB = {
      q: (el('lib-q') || {}).value || '',
      repo: (el('lib-repo') || {}).value || '',
      verdict: (el('lib-verdict') || {}).value || '',
      on_disk: (el('lib-disk') || {}).checked ? true : null,
    };
    return libLoad();
  },

  'lib.verdict': (_ev, elm) => libVerdictForm(elm.dataset.arg),
  /** Вхід у розбір із видачі пошуку. */
  'sift.open': () => show('sift'),
  'view.page': () => viewWholePage(),

  'view.zoom': (_ev, elm) => {
    // 🔴 Зум міняє ОБГОРТКУ, а не картинку. Оверлей рамок розтягнутий по
    // обгортці (`.stage-ov { inset: 0 }`), тож зміна ширини самого `<img>`
    // роз'їжджає рамки з рядками — і клік по рамці віддає текст іншого рядка.
    // Помітно це лише після першого «+», а «вписати» випадково лікує, тобто
    // вада виглядає плаваючою.
    const wrap = document.querySelector('.stage-wrap');
    if (!wrap) return;
    // «Вписати» — не 100%, а ширина контейнера: сторінка з архіву буває
    // 4000 px завширшки, і сотня відсотків від неї не влазить нікуди.
    ZOOM = elm.dataset.arg === 'fit'
      ? 100
      : Math.max(25, Math.min(600, ZOOM + Number(elm.dataset.arg)));
    wrap.style.width = `${ZOOM}%`;
  },

  /** Клік по рамці на знімку — показати текст саме цього рядка. */
  'view.line.pick': async (_ev, elm) => {
    const i = Number(elm.dataset.arg);
    const form = el('view').querySelector('form');
    const box = el('stage-line');
    if (!form || !box) return;
    document.querySelectorAll('.stage-ov .ln.on').forEach(
      (n) => n.classList.remove('on'));
    elm.classList.add('on');
    const env = await callOp('page.text',
      { run: form.run.value.trim(), page: form.page.value.trim() });
    if (!env.ok) return;
    const lines = (env.data || {}).lines || [];
    const one = lines[i];
    box.innerHTML = `<p class="mono">${esc(
      typeof one === 'string' ? one : (one || {}).text || '')}</p>`;
  },

  'view.stage.close': () => { const b = el('stage'); if (b) b.innerHTML = ''; },


  'sift.step': async (_ev, elm) => {
    const next = SIFT.i + Number(elm.dataset.arg || 0);
    if (next < 0 || next >= SIFT.hits.length) return;
    SIFT.i = next;
    siftDraw();
    await siftLoadCrop();
  },

  /** У гортач — на ту саму сторінку й той самий рядок. */
  'sift.view': () => {
    const h = SIFT.hits[SIFT.i] || {};
    VIEW = { run: h.name, page: h.page, line: h.line_index };
    return show('view');
  },

  /** В облік — зі справою й сканом уже підставленими. */
  'sift.note': () => {
    const h = SIFT.hits[SIFT.i] || {};
    EYE = { ...(EYE || {}), case: h.key || h.shifra || h.name, scan: h.page };
    return show('eye');
  },


  'lib.verdict.save': async (_ev, elm) => {
    const pages = ((el('lv-pages') || {}).value || '').trim();
    const env = await callOp('library.verdict', {
      key: elm.dataset.arg,
      verdict: (el('lv-kind') || {}).value || '',
      note: (el('lv-note') || {}).value || '',
      ...(pages ? { pages: Number(pages) } : {}),
    });
    if (!env.ok) return failure(env);
    // Застереження про нуль без знаменника не ковтається: воно доїжджає
    // конвертом і малюється над поверненою таблицею.
    await show('library');
    const box = el('view');
    if (box && env.warnings && env.warnings.length) {
      box.insertAdjacentHTML('afterbegin', renderWarnings(env));
    }
  },


  'sections.preset': async (_ev, elm) => {
    const env = await callOp('sections.set', { preset: elm.dataset.arg });
    if (!env.ok) return failure(env);
    SECTIONS = env.data;
    renderNav();
    await show('settings');
  },

  'sections.toggle': async (_ev, elm) => {
    const id = elm.dataset.arg;
    const on = !!elm.dataset.on;
    const env = await callOp('sections.set',
      on ? { disable: [id] } : { enable: [id] });
    if (!env.ok) return failure(env);
    SECTIONS = env.data;
    renderNav();
    await show('settings');
  },

  'home.scans': async () => {
    // 🔴 Раніше ця картка — перший клік того, заради кого все й робилось —
    // відсилала в командний рядок за `nysh look`. Вибору теки віконцем браузер
    // справді не дасть, але ШЛЯХ у форму вписати можна, і форма вже є. Відсилати
    // до терміналу того, хто щойно поставив застосунок подвійним кліком, значило
    // б обірвати шлях на першому ж кроці.
    await show('newcase');
  },

  'home.demo': async () => {
    // 🔴 Раніше тут вивалювався сирий JSON про середовище рушіїв — під написом
    // «перевірити, що читання працює на цій машині». Питання правильне, а
    // відповідь була не тими словами й не про те: людина, яка щойно поставила
    // застосунок, мусить прочитати, ЧОГО бракує і ЧИМ це ставиться.
    busy();
    const env = await callOp('setup.check', {});
    if (!env.ok) return failure(env);
    const rows = (env.data.checks || []).map((c) => {
      const mark = { ok: '✅', warn: '⚠', fail: '🔴' }[c.level] || '•';
      return `<tr><td>${mark}</td><td><b>${esc(c.name)}</b><br>
        <span class="muted">${esc(c.detail)}</span></td>
        <td>${c.fix ? `<code>${esc(c.fix)}</code>` : ''}</td></tr>`;
    }).join('');
    setView(`<h2>▶ ${t('check.title')}</h2>
      <p class="muted">${t('check.why')}</p>
      ${env.data.ready ? `<div class="warn">✅ ${t('check.ready')}</div>`
        : `<div class="warn">${t('check.notready')}</div>`}
      <table><tbody>${rows}</tbody></table>
      ${sampleBlock(env.data)}`);
  },

  // 📖 Зразок — єдина дія на цьому екрані, що щось МІНЯЄ. Вона стоїть саме
  // тут, бо питання «чи воно працює» і відповідь «ось перевірте на трьох
  // аркушах» — одне питання, і розводити їх по різних екранах означало б
  // сховати відповідь від того, хто щойно поставив застосунок.
  'sample.install': async () => {
    busy();
    const env = await callOp('sample.install', {});
    if (!env.ok) return failure(env);
    const d = env.data;
    setView(`<h2>📖 ${t('check.sample.title')}</h2>
      <p>${esc(d.shifra)} — ${d.frames.length}/${d.frames_total}</p>
      <p class="muted">${esc(d.case_dir)}</p>
      <p class="muted">${t('check.sample.next')}</p>
      <p><button data-act="nav" data-arg="view">${t('nav.view')}</button></p>`);
  },

  'geog.find': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    el('geoghits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('geog.find',
      { q: f.get('q'), section: f.get('section') || '', limit: 40 });
    // 🔴 Відмова каталогу — це НЕ «нічого не знайдено»: довідника просто немає,
    // і нуль тут не означав би нічого. Показуємо причину, а не порожню таблицю.
    if (!env.ok) { el('geoghits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    const places = env.data.places || [];
    el('geoghits').innerHTML = `
      ${renderWarnings(env)}
      ${places.length ? '' : `<p><b>${t('geog.nothing')}</b></p>`}
      <table><tbody>${places.map((pl) => `<tr>
        <td>${esc(pl.institution || '')}</td>
        <td><b>${esc(pl.village_uk)}</b><br>
            <span class="muted">${esc(pl.village_ru || '')}</span></td>
        <td>${esc(pl.uezd_gub || '')}</td>
        <td class="num">${pl.n_cases || 0}</td>
        <td><button data-act="geog.card" data-arg="${esc(pl.card)}">${t('view.open')}</button></td>
      </tr>`).join('')}</tbody></table>
      ${renderCoverage(env)}`;
  },

  'geog.card': async (_ev, elm) => {
    busy();
    const env = await callOp('geog.card', { card: elm.dataset.arg });
    if (!env.ok) return failure(env);
    const pl = env.data.place;
    if (!pl) return setView(`<h2>${t('geog.title')}</h2>${renderWarnings(env)}${renderCoverage(env)}`);
    const cases = pl.cases || [];
    setView(`
      <h2>🗺 ${esc(pl.village_uk)} <span class="muted">(${esc(pl.village_ru || '')})</span></h2>
      <p class="muted">
        ${t('geog.hist')}: ${esc(pl.hist_place || '—')} ·
        ${t('geog.after')}: ${esc(pl.uezd_gub || '—')} ·
        ${t('geog.modern')}: ${esc(pl.modern_place || '—')}
        ${pl.church ? ` · ${t('geog.church')}: ${esc(pl.church)}` : ''}
      </p>
      ${renderWarnings(env)}
      <p><b>${cases.length}</b> ${t('geog.cases')}, ${t('geog.ondisk')} <b>${pl.n_on_disk || 0}</b></p>
      <table><tbody>${cases.map((c) => `<tr>
        <td>${c.on_disk ? '✓' : '·'}</td>
        <td class="mono">${esc(c.shifra)}</td>
        <td>${c.year_from ? `${esc(c.year_from)}–${esc(c.year_to)}` : ''}</td>
        <td>${esc(c.doc_type || '')}</td>
        <td class="muted">${esc(c.parish || '')}</td>
      </tr>`).join('')}</tbody></table>
      ${(pl.siblings || []).length ? `<h3>🕍 ${t('geog.siblings')}</h3>
        <table><tbody>${pl.siblings.map((x) => `<tr>
          <td>${esc(x.institution || '')}</td><td>${esc(x.village_uk)}</td>
          <td class="num">${x.n_cases || 0}</td>
          <td><button data-act="geog.card" data-arg="${esc(x.card)}">${t('view.open')}</button></td>
        </tr>`).join('')}</tbody></table>` : ''}
      ${(pl.confusers || []).length ? `<h3>⚠ ${t('geog.confusers')}</h3>
        <table><tbody>${pl.confusers.map((x) => `<tr>
          <td class="num">${esc(x.score)}</td><td>${esc(x.village_uk)}</td>
          <td class="muted">${esc(x.uezd_gub || '')}</td>
        </tr>`).join('')}</tbody></table>` : ''}
      ${renderCoverage(env)}`);
  },

  'fond.rows': async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    el('fondrows').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('fond.rows', {
      fond: f.get('fond'), q: f.get('q') || '', surname: f.get('surname') || '',
      uezd: f.get('uezd') || '', state: f.get('state') || '', limit: 200,
    });
    if (!env.ok) { el('fondrows').innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    const rows = env.data.rows || [];
    // 🔴 Знаменник поруч із числом: «5 справ» без «із 2944» читається як
    // «у фонді п'ять справ», тобто як зовсім інша відповідь.
    el('fondrows').innerHTML = `
      ${renderWarnings(env)}
      <p>${t('fonds.matched')} <b>${env.data.matched}</b> ${t('fonds.of')}
         <b>${env.data.summary.rows}</b></p>
      <table><thead><tr><th></th><th>шифра</th><th>назва</th><th>роки</th>
        <th>арк.</th><th>плівка</th></tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td title="${esc(r.state)}">${r.on_disk ? '✓' : (r.state === 'todo' ? '⬇' : '·')}</td>
        <td class="mono">${esc(r.shifra)}</td>
        <td>${esc((r.title || '').slice(0, 90))}</td>
        <td>${r.year_from ? `${esc(r.year_from)}–${esc(r.year_to)}` : ''}</td>
        <td class="num">${esc(r.folios || '')}</td>
        <td class="mono">${esc(r.fs_film || '')}</td>
      </tr>`).join('')}
      </tbody></table>`;
  },

  'sources.find': async (ev) => {
    ev.preventDefault();
    const q = new FormData(ev.target).get('q');
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('catalog.search', { q, limit: 40 });
    if (!env.ok) return failure(env);
    const { hits = [], coverage = {} } = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${hits.length ? '' : `<p><b>${t('sources.nothing')}.</b> ${t('sources.zero_warning')}</p>`}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.source)}</td>
        <td>${esc(h.title)}<br><span class="muted">${esc(h.shifra || '')} ${esc(h.years || '')}</span></td>
        <td class="num">${h.frames ? `${h.frames} ${t('common.frames')}` : ''}</td>
        <td>${h.acquirable
          ? `<button data-act="sources.get" data-source="${esc(h.source)}" data-ref="${esc(h.ref)}">${t('sources.get')}</button>`
          : ''}</td>
      </tr>`).join('')}</tbody></table>
      <p class="muted">${t('sources.searched')}: ${esc((coverage.searched || []).join(', ') || '—')}</p>`;
  },

  'sources.get': async (_ev, elm) => {
    const env = await callOp('acquire.start',
      { source: elm.dataset.source, ref: elm.dataset.ref });
    if (!env.ok) return alert(env.error);
    show('jobs');
  },

  'search.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('search.run',
      { q: fd.get('q'), where: fd.get('where'), limit: 100 });
    if (!env.ok) return failure(env);
    const hits = env.data.hits || [];
    const cov = env.data.coverage || {};
    // Хіти лишаються під рукою: розбір відкривається з них, а не переповторює
    // пошук — інакше два екрани показували б різні набори того самого запиту.
    SIFT = { hits: hits.filter((h) => h.name && h.page), i: 0,
             q: String(fd.get('q') || ''), crop: null, ctx: null };
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${SIFT.hits.length
        ? `<p><button data-act="sift.open">${ic('crop-check', 'ic-sm')}
             ${t('sift.open')}</button></p>` : ''}
      <table><tbody>${hits.map((h) => `<tr>
        <td class="mono">${esc(h.shifra || h.case || h.key || h.name || '')}</td>
        <td class="mono">${esc(h.page || h.scan || '')}</td>
        <td>${esc(String(h.matched || h.line || h.text || h.surname || '').slice(0, 120))}</td>
        <td class="num">${esc(h.score ?? '')}</td>
        <td>${/* 🔴 Виявити ≠ перевірити: машина подає кандидата, вирішує око.
                 Доти хіт був рядком таблиці — щоб глянути на нього, треба було
                 переписати прогін і сторінку в гортач руками, а це та сама
                 дія, заради якої пошук і робився. */''}
          ${h.name && h.page
            ? `<button data-act="hit.eye" data-run="${esc(h.name)}"
                 data-page="${esc(h.page)}"
                 data-line="${esc(h.line_index ?? '')}"
                 title="${t('hit.eye')}">👁</button>` : ''}
          ${(h.key || h.shifra) && (h.scan || h.page)
            ? `<button data-act="hit.note" data-case="${esc(h.key || h.shifra)}"
                 data-scan="${esc(h.scan || h.page)}"
                 title="${t('hit.note')}">✎</button>` : ''}
        </td>
      </tr>`).join('')}</tbody></table>
      ${cov.runs !== undefined
        ? `<p class="muted">${t('search.coverage')}: ${cov.runs} ${t('search.runs')}, ${cov.pages} ${t('common.pages')}</p>`
        : cov.cases !== undefined
          ? `<p class="muted">${t('search.coverage')}: ${cov.cases} ${t('search.cases')}</p>`
          : ''}`;
  },

  // 🔴 Спершу ПЛАН, і лише окремою кнопкою — старт. Справа читається годинами;
  // дізнатись «модель не та» або «кадрів не 20, а 3000» після запуску означає
  // втратити ніч.
  'eye.check': async (ev) => {
    ev.preventDefault();
    EYE = { case: new FormData(ev.target).get('case') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('pages.status', EYE);
    if (!env.ok) return failure(env);
    const d = env.data;
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p><b>${esc(d.shifra)}</b> ${esc(d.title || '')}</p>
      <p class="muted">${t('eye.disk')}: ${d.total_disk ?? 0} ·
         ${t('eye.noted')}: ${d.noted} ·
         ${t('eye.left')}: ${d.unnoted_count ?? '?'}</p>
      <h3>${t('eye.note')}</h3>
      <form data-act="eye.note">
        <div class="row">
          <input name="scan" placeholder="${t('eye.scan')}: 0030.JPG">
          <select name="page_type">${PAGE_TYPES.map((k) =>
            `<option value="${k}">${t(`ptype.${k}`)}</option>`).join('')}</select>
          <select name="status">
            <option value="full">full — виписано ВСІ прізвища</option>
            <option value="partial">partial — не всі</option>
            <option value="skipped">skipped — не читав</option>
            <option value="unreadable">unreadable — не читається</option>
          </select>
        </div>
        <div class="row"><input name="surnames" placeholder="${t('eye.surnames')}"></div>
        <div class="row">
          <input name="comment" placeholder="${t('eye.comment')}">
          <button type="submit">${t('eye.save')}</button>
        </div>
      </form>
      <div id="noted"></div>`;
  },

  'eye.note': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    const env = await callOp('pages.note', { ...EYE, ...fd });
    const box = el('noted');
    if (!env.ok) { box.innerHTML = `<div class="warn err">${esc(env.error)}</div>`; return; }
    box.innerHTML = `<div class="warn">✅ ${esc(fd.scan)} занесено</div>`
      + renderWarnings(env);
    ev.target.reset();
  },

  'cases.build': async () => {
    const env = await callOp('cases.build', { rescan: true });
    if (!env.ok) return failure(env);
    // Робота йде у черзі — туди ж і ведемо: інакше кнопка виглядає як така,
    // що нічого не зробила, і її натискають ще раз.
    await show('jobs');
  },

  'case.edit': async (_ev, elm) => {
    const env = await callOp('case.show', { case_dir: elm.dataset.arg });
    if (!env.ok) return failure(env);
    EDIT = env.data;
    await show('newcase');
    if (env.warnings && env.warnings.length) {
      el('hits').innerHTML = renderWarnings(env);
    }
  },

  'case.fresh': async () => {
    EDIT = null;
    await show('newcase');
  },

  'case.save': async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target).entries());
    for (const k of ['year_from', 'year_to']) fd[k] = fd[k] ? Number(fd[k]) : null;
    // Незнята позначка у FormData просто відсутня — схема чекає булеве поле.
    fd.adopt = fd.adopt === '1';
    const env = await callOp('case.register', fd);
    if (!env.ok) {
      el('hits').innerHTML = `<div class="warn err">${esc(env.error)}</div>`;
      return;
    }
    const sc = env.data.sidecar;
    el('hits').innerHTML = `${renderWarnings(env)}
      <div class="warn">✅ <b>${esc(sc.shifra)}</b> — ${esc(sc.title || 'без назви')}</div>`;
  },

  // 🔴 Хіт — це кандидат, а не висновок: дивиться око. Доти, щоб глянути на
  // знайдений рядок, треба було переписати ім'я прогону й номер сторінки в
  // гортач руками — тобто зробити ту саму роботу, заради якої пошук і є.
  'hit.eye': async (_ev, elm) => {
    VIEW = { run: elm.dataset.run, page: elm.dataset.page,
             line: elm.dataset.line === '' ? null : Number(elm.dataset.line) };
    await show('view');
  },

  'hit.note': async (_ev, elm) => {
    EYE = { case: elm.dataset.case, scan: elm.dataset.scan };
    await show('eye');
  },

  'view.open': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    VIEW = { run: fd.get('run'), page: fd.get('page') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('page.text', VIEW);
    if (!env.ok) return failure(env);
    const lines = env.data.lines || [];
    const geo = env.data.geometry || {};
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      <p class="muted">${lines.length} ${t('view.lines')}${geo.has ? '' : ' · без рамок'}</p>
      <div id="shot"></div>
      <table><tbody>${lines.map((ln, i) => `<tr>
        <td class="num mono">${i}</td>
        <td><button data-act="view.line" data-line="${i}">👁</button></td>
        <td>${esc(ln)}</td></tr>`).join('')}</tbody></table>`;
  },

  // 🔴 Рядок, а не сторінка. Вирізка легша в десятки разів (виміряно: 15 КБ
  // проти 1.1 МБ), а звірок за сеанс бувають десятки.
  'view.line': async (_ev, elm) => {
    if (!VIEW) return;
    const env = await callOp('page.view',
      { ...VIEW, line: Number(elm.dataset.line), region: 'line' });
    if (!env.ok) return alert(env.error);
    const d = env.data;
    el('shot').innerHTML = `
      ${renderWarnings(env)}
      <img src="${d.image}" alt="рядок ${d.line}" style="max-width:100%">
      <p class="muted mono">${esc(d.text || '')}</p>`;
    el('shot').scrollIntoView({ block: 'nearest' });
  },

  'read.plan': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    LAST_READ = { case_dir: fd.get('case_dir'), script: fd.get('script') };
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('read.plan', LAST_READ);
    if (!env.ok) return failure(env);
    const p = env.data.plan || {};
    el('hits').innerHTML = `
      <table><tbody>
        <tr><td>${t('read.frames')}</td><td class="num">${esc(p.frames)}</td></tr>
        <tr><td>${t('read.script')}</td><td>${esc(p.script)}</td></tr>
        <tr><td>${t('read.model')}</td><td class="mono">${esc(p.model)}</td></tr>
        ${p.voice ? `<tr><td>${t('read.voice')}</td><td class="mono">${esc(p.voice)}</td></tr>` : ''}
        <tr><td>→</td><td class="mono">${esc(p.out_dir)}</td></tr>
      </tbody></table>
      <button data-act="read.go">${t('read.go')}</button>`;
  },

  'read.go': async () => {
    if (!LAST_READ) return;
    const env = await callOp('read.start', LAST_READ);
    if (!env.ok) return alert(env.error);
    show('jobs');
  },

  'export.run': async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    el('hits').innerHTML = `<p class="muted">${t('common.loading')}</p>`;
    const env = await callOp('export.case',
      { case: fd.get('case'), what: fd.get('what') });
    if (!env.ok) return failure(env);
    const { columns = [], rows = [] } = env.data;
    LAST_EXPORT = { columns, rows, name: env.data.shifra || env.data.case };
    el('hits').innerHTML = `
      ${renderWarnings(env)}
      ${rows.length ? `<button data-act="export.csv">${t('export.csv')}</button>` : ''}
      <table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${rows.slice(0, 200).map((r) => `<tr>${columns.map(
        (c) => `<td>${esc(String(r[c] ?? '').slice(0, 80))}</td>`).join('')}</tr>`).join('')}
      </tbody></table>
      <p class="muted">${rows.length} рядків</p>`;
  },

  // 🔴 CSV збирається на клієнті й зберігається діалогом браузера. Писати файл
  // кудись «у простір» тут не можна: людина вивантажує, щоб віднести дані в
  // ЧУЖУ програму, і мусить сама сказати куди.
  'export.csv': () => {
    if (!LAST_EXPORT) return;
    const { columns, rows, name } = LAST_EXPORT;
    const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [columns.join(','), ...rows.map(
      (r) => columns.map((c) => cell(r[c])).join(','))].join('\r\n');
    // BOM — щоб Excel не з''їв кирилицю: без нього виписка відкривається
    // «крякозябрами», і виглядає це як зіпсовані дані, а не як кодування.
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${String(name).replace(/[^\w.-]+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  },

  'jobs.cancel': async (_ev, elm) => {
    await fetch(`/api/jobs/${encodeURIComponent(elm.dataset.job)}/cancel`,
      { method: 'POST', headers: { 'X-Nysh-Token': TOKEN } });
    await refreshJobs();
  },

  'lang.toggle': () => {
    LANG = LANG === 'uk' ? 'en' : 'uk';
    localStorage.setItem('nysh.lang', LANG);
    location.reload();
  },
};

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
  _liveTimer = setTimeout(() => dispatch(ev), 250);
});

// ── навігація ────────────────────────────────────────────────────────────────
async function show(screen) {
  // 🔴 Екран вимкненої секції не мовчить і не показує порожнечу. Сюди
  // потрапляють через закладку чи посилання з часів, коли секція була
  // ввімкнена, — і «нічого не сталось» тут читається як поламаний застосунок.
  if (!screenOn(screen)) {
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
  SCREEN_GEN += 1;
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
  const jobs = (data.jobs || []).filter((j) => j.state !== 'done' || Date.now() / 1000 - j.updated < 300);
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
const KEYS = {
  sift: {
    ArrowRight: () => ACTIONS['sift.step'](null, { dataset: { arg: '1' } }),
    ArrowLeft: () => ACTIONS['sift.step'](null, { dataset: { arg: '-1' } }),
    ' ': () => ACTIONS['sift.step'](null, { dataset: { arg: '1' } }),
    e: () => ACTIONS['sift.view'](),
    n: () => ACTIONS['sift.note'](),
  },
  view: {
    '+': () => ACTIONS['view.zoom'](null, { dataset: { arg: '25' } }),
    '-': () => ACTIONS['view.zoom'](null, { dataset: { arg: '-25' } }),
    '0': () => ACTIONS['view.zoom'](null, { dataset: { arg: 'fit' } }),
  },
};

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
