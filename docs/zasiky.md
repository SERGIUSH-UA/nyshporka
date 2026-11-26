# Засіки: як агент читає опис фонду

Посібник спостерігача.

Опис фонду — це перелік справ архіву з назвами, роками й номерами. Засіки — розділ Супряги,
де такі описи можна шукати: за назвою справи, селом чи прізвищем знаходиться номер справи
і сторінка опису з посиланням на скан.

Читає опис агент (помічник, що працює з Нишпоркою). Ця сторінка — для людини, яка команд сама не
виконує: вона стежить за ходом роботи й втручається там, де без неї не обійтись. Тут описано, що
відбувається на кожному етапі, скільки це триває, що видно на екрані й коли варто зупинити агента.

!!! note "Доступ зараз"
    Засіки в бета-тесті. Віддавати описи й шукати по них можуть учасники Супряги, які вже залили
    в неї справи (Нишпорка під'єднана: `nysh share login`). Іншим сервер відмовить і скаже чому.
    Пошук — до 30 запитів на хвилину й 300 на добу на людину.

## 1. Хто що робить

| | Агент | Людина |
|---|---|---|
| Команди | виконує всі | не виконує жодної |
| Розгляд сторінок | дивиться 2–3 сторінки й записує, який це опис | може перевірити записане оком |
| Хмара | ставить захід, повторює команду, забирає результат | дозволяє захід, що коштує понад стелю автозапуску ($2): `--confirm` ставить лише людина |
| Назви справ | нормалізує пачки | дає власний ключ API для нормалізації й визначає бюджет |
| Заливка | готує й виконує `nysh opys push` | погоджується: заливка йде від імені людини |

Ключ API агент не бачить і не вводить: налаштування (`nysh opys api nalashtuvaty`) людина робить у
власному терміналі, а агентові ця команда відмовляє навмисно. Бюджет теж піднімає лише людина.

## 2. Шлях цілком

Команда `nysh opys read` проходить етапи сама. Якщо щось перервалось, достатньо повторити ту саму
команду: вона продовжить з місця, а зроблене не повторюватиме.

<div><svg viewBox="0 0 540 676" width="100%" role="img" aria-label="Етапи читання опису за ролями: людина, агент, машина або хмара" style="display:block;max-width:540px;margin:0 auto;font-family:inherit"><defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" fill-opacity=".8"/></marker></defs><rect x="88" y="2" width="144" height="30" rx="6" fill="#e0a030" fill-opacity=".25"/><text x="160.0" y="22" text-anchor="middle" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="160.0" dy="0">Людина</tspan></text><rect x="236" y="2" width="144" height="30" rx="6" fill="#3b82f6" fill-opacity=".25"/><text x="308.0" y="22" text-anchor="middle" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="308.0" dy="0">Агент</tspan></text><rect x="384" y="2" width="144" height="30" rx="6" fill="#10b981" fill-opacity=".25"/><text x="456.0" y="22" text-anchor="middle" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="456.0" dy="0">Машина/хмара</tspan></text><rect x="0" y="37" width="540" height="70" fill="currentColor" fill-opacity=".04"/><text x="4" y="71" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">1. Джерело</tspan></text><rect x="236" y="43" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="61.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">бере файл,</tspan><tspan x="306.0" dy="15">питає сервер,</tspan><tspan x="306.0" dy="15">чи приймає фонд</tspan></text><text x="4" y="141" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">2. Сторінки</tspan></text><rect x="384" y="113" width="140" height="58" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="454.0" y="146.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="454.0" dy="0">секунди–хвилини</tspan></text><rect x="0" y="177" width="540" height="70" fill="currentColor" fill-opacity=".04"/><text x="4" y="211" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">3. Метадані</tspan></text><rect x="88" y="183" width="140" height="58" rx="8" fill="#e0a030" fill-opacity=".2" stroke="#e0a030" stroke-width="1.5" stroke-dasharray="5 3"/><text x="158.0" y="201.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="158.0" dy="0">можна звірити:</tspan><tspan x="158.0" dy="15">число справ,</tspan><tspan x="158.0" dy="15">сторінки таблиці</tspan></text><rect x="236" y="183" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="201.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">дивиться 2–3</tspan><tspan x="306.0" dy="15">сторінки, пише</tspan><tspan x="306.0" dy="15">метадані</tspan></text><text x="4" y="281" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">4. Читання</tspan></text><rect x="88" y="253" width="140" height="58" rx="8" fill="#e0a030" fill-opacity=".2" stroke="#e0a030" stroke-width="1.5"/><text x="158.0" y="279.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="158.0" dy="0">дозвіл на хмару</tspan><tspan x="158.0" dy="15">понад $2</tspan></text><circle cx="224" cy="257" r="9" fill="#e5484d"/><text x="224" y="261.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">!</text><rect x="236" y="253" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="279.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">запускає читання,</tspan><tspan x="306.0" dy="15">повторює команду</tspan></text><rect x="384" y="253" width="140" height="58" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="454.0" y="286.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="454.0" dy="0">тут або в хмарі</tspan></text><rect x="0" y="317" width="540" height="70" fill="currentColor" fill-opacity=".04"/><text x="4" y="351" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">5. Дочит №</tspan></text><rect x="384" y="323" width="140" height="58" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="454.0" y="349.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="454.0" dy="0">колонка № цілим</tspan><tspan x="454.0" dy="15">рядком</tspan></text><text x="4" y="421" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">6. Таблиця</tspan></text><rect x="236" y="393" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="411.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">дивиться повноту,</tspan><tspan x="306.0" dy="15">вирішує, чи</tspan><tspan x="306.0" dy="15">віддавати</tspan></text><rect x="384" y="393" width="140" height="58" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="454.0" y="426.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="454.0" dy="0">таблиця справ</tspan></text><rect x="0" y="457" width="540" height="70" fill="currentColor" fill-opacity=".04"/><text x="4" y="491" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">7. Назви</tspan></text><rect x="88" y="463" width="140" height="58" rx="8" fill="#e0a030" fill-opacity=".2" stroke="#e0a030" stroke-width="1.5"/><text x="158.0" y="489.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="158.0" dy="0">свій ключ API —</tspan><tspan x="158.0" dy="15">лише людина</tspan></text><circle cx="224" cy="467" r="9" fill="#e5484d"/><text x="224" y="471.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">!</text><rect x="236" y="463" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="489.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">нормалізує пачки</tspan><tspan x="306.0" dy="15">по 20 назв</tspan></text><text x="4" y="561" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="4" dy="0">8. Заливка</tspan></text><rect x="88" y="533" width="140" height="58" rx="8" fill="#e0a030" fill-opacity=".2" stroke="#e0a030" stroke-width="1.5"/><text x="158.0" y="566.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="158.0" dy="0">згода на заливку</tspan></text><circle cx="224" cy="537" r="9" fill="#e5484d"/><text x="224" y="541.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">!</text><rect x="236" y="533" width="140" height="58" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="306.0" y="559.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="306.0" dy="0">заливає, перевіряє</tspan><tspan x="306.0" dy="15">пошуком</tspan></text><rect x="384" y="533" width="140" height="58" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="454.0" y="566.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="454.0" dy="0">ворота й заливка</tspan></text><circle cx="14" cy="614" r="9" fill="#e5484d"/><text x="14" y="618.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">!</text><text x="30" y="618.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="30" dy="0">людина вирішує</tspan></text><rect x="200" y="605" width="26" height="18" rx="3" fill="none" stroke="currentColor" stroke-opacity=".6" stroke-dasharray="4 2"/><text x="234" y="618.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="234" dy="0">людина може глянути</tspan></text><text x="4" y="646" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Зупинка — етап 3: читання не стартує без метаданих.</tspan></text><text x="4" y="664" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Перерване — та сама команда продовжує з місця.</tspan></text></svg></div>

| Етап | Що відбувається | Скільки триває | Що видно |
|---|---|---|---|
| 1. Джерело | Агент бере PDF (чи тека кадрів, чи DjVu з PDF-перетворенням) і адресу, де опис опубліковано. Сервер каже, чи приймає Супряга описи цього фонду | миттєво | «нова тека опису», рядок «паспорт» серед зроблених кроків; відмова, якщо описи фонду не приймаються |
| 2. Сторінки | PDF розкладається на сторінки-зображення | секунди, хвилини | рядок «сторінки» |
| 3. Метадані | Зупинка: агент розглядає названі сторінки й записує вигляд опису, колонки, число справ | залежить від агента; читання без цього не стартує | відповідь `meta_potribni`, перелік сторінок для перегляду |
| 4. Читання | Сторінки читаються тут чи в хмарі | тут, на відеокарті: хвилини; на процесорі: години; у хмарі: хвилини | прогрес читання або «захід поставлено в хмару» |
| 5. Дочит колонки № | Номери справ читаються окремо, цілим рядком | тут: близько секунди на номер; у хмарі: ще один короткий захід | «кропи колонки №» |
| 6. Таблиця справ | З прочитаного складається таблиця справ | секунди | число справ, повнота, попередження |
| 7. Нормалізація назв | Назви справ осучаснюються пачками по 20 | залежить від шляху (розділ 4) | кількість пачок, що чекають відповіді |
| 8. Заливка | Ворота перевіряють пакет, далі заливка в Супрягу | не виміряно | або «залито», або перелік усіх причин відмови разом |
| 9. Перевірка | Пошук відомого з опису села знаходить справу | не виміряно | справа з номером і сторінкою |

Орієнтир за часом: опис на 16 сторінок читається на відеокарті GTX 1650 близько 3,5 хвилини
разом із дочитом номерів. Опис на сотню сторінок на процесорі — година лише на номери. Затримка тут
не означає, що процес завис. У хмарі той самий опис читається за хвилини й коштує центи: 29 сторінок —
близько $0.01, машинопис на 53 сторінки — близько $0.07.

## 3. Етапи докладніше

### 3.1. Джерело

Агентові потрібні файл опису й адреса, де людина сама відкриє той самий файл: посилання кожної
справи в Супрязі веде саме туди. Якщо архів публікує опис кадрами, джерелом є тека кадрів, а адресою —
адреса цієї теки. Коли за адресою лежить DjVu, а читається PDF-перетворення, агент указує обидва
файли. Фонд, описи якого Супряга не приймає, відмовляє відразу й підказує, куди звернутися.

Якщо PDF збережено давно і точної адреси ви не пам'ятаєте, опис читається й без неї. Перед
віддачею в Супрягу знайдіть цей файл на сайті архіву й переконайтеся, що там той самий опис. Тоді
агент запише адресу (`nysh opys dzherelo`). Без адреси опис не віддається, а вигадувати її агент
не має.

Коли опису в мережі немає зовсім, залийте скан на Wikimedia Commons: тоді кожну справу можна звірити
зі сторінкою скану. Не маєте змоги — погодьтеся передати скан власникові Нишпорки командою
`nysh opys skan <тека>` у своєму терміналі. Тоді опис піде в Засіки разом зі сканом; власник
заллє скан на Commons, і посилання справ з'являться самі. В обох випадках скан стає публічним для
всіх і назавжди, тож вирішуєте ви, а не агент.

Віддаючи опис, ви приймаєте [умови Засік](https://nyshporka.online/zasiky/umovy): текст відкритий
іншим лише для некомерційного вжитку, а власник Нишпорки може використовувати внесок і матеріал для
навчання (розмітку рядків, вирізки колонки номерів) з будь-якою метою. Приймаєте умови ви самі, один
раз, на сайті.

### 3.2. Зупинка «метадані»

Це єдине місце, де перша команда навмисно зупиняється й чекає на розсуд агента. `read` називає 2–3
сторінки: першу сторінку таблиці, середню й останню. Агент розглядає їх і записує (`nysh opys meta`):

- **вигляд опису:** друкований бланк, розграфлено від руки чи машинопис;
- **ролі колонок** зліва направо: номер, початок, назва, кінець, аркуші, відмітка;
- **скільки справ в описі й звідки це число:** засвідчувальний напис на останній сторінці чи останній
  номер таблиці;
- **сторінки таблиці:** перша й остання. Титул і засвідчувальний напис лишаються поза нею.

Що людина може звірити оком: число справ і першу та останню сторінки таблиці. Від цього числа далі
рахується повнота таблиці, тож помилка тут не видна до етапу 6.

### 3.3. Читання

Де читати, вирішується розвилкою нижче. Рукописний опис у хмарі читається двома короткими заходами:
спершу сторінки, потім кропи колонки №. Машинопис читає окремий рушій друку, і лише в хмарі.

<div><svg viewBox="0 0 540 575" width="100%" role="img" aria-label="Розвилка: де читається опис — тут чи в хмарі, і коли потрібен дозвіл людини" style="display:block;max-width:540px;margin:0 auto;font-family:inherit"><defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" fill-opacity=".8"/></marker></defs><rect x="120" y="8" width="160" height="36" rx="8" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="200.0" y="30.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="200.0" dy="0">nysh opys read</tspan></text><path d="M200,44 L200,74" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><polygon points="200,74 290,110 200,146 110,110" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="200" y="114.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="200" dy="0">машинопис?</tspan></text><path d="M290,110 L375,110" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="322" y="102" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="322" dy="0">так</tspan></text><rect x="375" y="87" width="155" height="46" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="452.5" y="107.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="452.5" dy="0">лише хмара</tspan><tspan x="452.5" dy="15">(рушій друку)</tspan></text><path d="M452,133 L452,192" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><path d="M200,146 L200,177" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="210" y="166" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="210" dy="0">ні</tspan></text><polygon points="200,177 310,215 200,253 90,215" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="200" y="212.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="200" dy="0">є плагін оренди?</tspan><tspan x="200" dy="15">(--de auto)</tspan></text><path d="M310,215 L375,215" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="334" y="207" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="334" dy="0">так</tspan></text><rect x="375" y="192" width="155" height="46" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="452.5" y="212.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="452.5" dy="0">читання</tspan><tspan x="452.5" dy="15">в хмарі</tspan></text><path d="M200,253 L200,282" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="210" y="273" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="210" dy="0">ні</tspan></text><rect x="100" y="282" width="200" height="56" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="200.0" y="299.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="200.0" dy="0">читання тут: карта —</tspan><tspan x="200.0" dy="15">хвилини, процесор —</tspan><tspan x="200.0" dy="15">години</tspan></text><path d="M452,238 L452,314" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><polygon points="452,314 530,350 452,386 374,350" fill="#3b82f6" fill-opacity=".2" stroke="#3b82f6" stroke-width="1.5"/><text x="452" y="347.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="452" dy="0">кошторис</tspan><tspan x="452" dy="15">понад $2?</tspan></text><path d="M452,386 L452,430" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="462" y="412" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="462" dy="0">ні</tspan></text><rect x="375" y="430" width="155" height="46" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="452.5" y="450.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="452.5" dy="0">захід іде сам,</tspan><tspan x="452.5" dy="15">без людини</tspan></text><path d="M374,350 L335,350 L335,453 L312,453" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="343" y="342" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="343" dy="0">так</tspan></text><rect x="60" y="430" width="252" height="46" rx="8" fill="#e0a030" fill-opacity=".2" stroke="#e0a030" stroke-width="1.5"/><text x="186.0" y="450.0" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="186.0" dy="0">людина дає дозвіл</tspan><tspan x="186.0" dy="15">(--confirm); агент не ставить</tspan></text><circle cx="304" cy="438" r="9" fill="#e5484d"/><text x="304" y="442.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">!</text><text x="4" y="508" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Хмара відмовила в режимі auto (немає ключа чи</tspan><tspan x="4" dy="15">балансу) — читається тут, причину названо.</tspan><tspan x="4" dy="15">Машинопис тут не читається: якщо хмара не взяла</tspan><tspan x="4" dy="15">захід, агент повідомляє причину.</tspan></text></svg></div>

Поки читання йде на цій машині, на екрані прогрес, і довга пауза між рядками нормальна. Ставити
довге читання на ніч — звичайна практика.

### 3.4. Хмарний захід

Хмарний захід відчеплений від команди: `read` ставить його й одразу виходить. Щоб забрати результат,
агент повторює ту саму команду. Доки хмара читає, відповідь каже, скільки вже прочитано.

<div><svg viewBox="0 0 540 540" width="100%" role="img" aria-label="Хмарний захід у часі: агент повторює ту саму команду, поки хмара читає" style="display:block;max-width:540px;margin:0 auto;font-family:inherit"><defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" fill-opacity=".8"/></marker></defs><text x="30" y="22" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="30" dy="0">Агент</tspan></text><text x="425" y="22" text-anchor="middle" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="425" dy="0">Хмара</tspan></text><line x1="30" y1="60" x2="30" y2="380" stroke="currentColor" stroke-opacity=".35" stroke-width="1.5"/><circle cx="30" cy="60" r="6" fill="#3b82f6"/><text x="50" y="64.5" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="50" dy="0">read</tspan></text><text x="50" y="79.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="50" dy="0">«захід поставлено в хмару»</tspan><tspan x="50" dy="15">команда виходить</tspan></text><line x1="300" y1="60" x2="326" y2="60" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/><circle cx="30" cy="140" r="6" fill="#3b82f6"/><text x="50" y="144.5" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="50" dy="0">read (повтор)</tspan></text><text x="50" y="159.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="50" dy="0">«хмара ще читає — N з M»</tspan></text><line x1="300" y1="140" x2="326" y2="140" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/><circle cx="30" cy="220" r="6" fill="#3b82f6"/><text x="50" y="224.5" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="50" dy="0">read (повтор)</tspan></text><text x="50" y="239.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="50" dy="0">забрано сторінки; ставить</tspan><tspan x="50" dy="15">захід для кропів №</tspan></text><line x1="300" y1="220" x2="326" y2="220" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/><circle cx="30" cy="300" r="6" fill="#3b82f6"/><text x="50" y="304.5" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="50" dy="0">read (повтор)</tspan></text><text x="50" y="319.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="50" dy="0">«хмара ще читає — N з M»</tspan></text><line x1="300" y1="300" x2="326" y2="300" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/><circle cx="30" cy="380" r="6" fill="#3b82f6"/><text x="50" y="384.5" text-anchor="start" font-size="12.5" fill="currentColor" font-weight="600"><tspan x="50" dy="0">read (повтор)</tspan></text><text x="50" y="399.5" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="50" dy="0">забрано кропи №; таблиця</tspan><tspan x="50" dy="15">й пачки назв</tspan></text><line x1="300" y1="380" x2="326" y2="380" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/><rect x="326" y="60" width="200" height="157" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="426.0" y="135.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="426.0" dy="0">захід 1:</tspan><tspan x="426.0" dy="15">сторінки опису</tspan></text><rect x="326" y="223" width="200" height="157" rx="8" fill="#10b981" fill-opacity=".2" stroke="#10b981" stroke-width="1.5"/><text x="426.0" y="298.5" text-anchor="middle" font-size="12.5" fill="currentColor"><tspan x="426.0" dy="0">захід 2:</tspan><tspan x="426.0" dy="15">кропи колонки №</tspan></text><path d="M10,70 L10,400" fill="none" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" marker-end="url(#ar)"/><text x="4" y="462" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Час — згори вниз, хвилини.</tspan></text><text x="4" y="486" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Між командами від вас нічого не потрібно:</tspan></text><text x="4" y="502" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">хмара читає, агент чекає й повторює команду.</tspan></text><text x="4" y="526" text-anchor="start" font-size="12.5" fill="currentColor"><tspan x="4" dy="0">Стан заходу: nysh cloud state &lt;run_id&gt;</tspan></text></svg></div>

Повідомлення, які можна побачити в роботі агента:

| Що написано | Що це означає |
|---|---|
| «захід поставлено в хмару» | захід щойно стартував; команда вийшла, так і задумано |
| «хмара ще читає — N з M» | захід іде, потрібно просто повторити команду пізніше |
| «стан — `nysh cloud state <run_id>`» | де агент може глянути стан заходу окремо |

Стежить за заходом процес на комп'ютері, звідки його запущено, тому під час заходу комп'ютер не
вимикають і не присипляють: так само, як і в [читанні на орендованій машині](cloud.md). Ціна
хмарного читання опису — центи. Заходи, що коштували б понад стелю автозапуску ($2), стартують лише
з дозволом людини.

Якщо захід завершився з нестачею (обрив, пошкоджена сторінка), береться те, що прочитано, а решту для
рукопису дочитує ця машина. Для машинопису відповідь містить попередження, що рушій друку скінчив з
нестачею й таблиця неповна.

### 3.5. Дочит колонки №

Номери справ читаються окремо від решти таблиці: вирізки колонки № (кропи) читаються цілим рядком,
а номери зводяться ланцюжком: номер, якому рушій загубив першу цифру («313» там, де 1313),
добудовується з сусідів. Номер, якого не вдалось підтвердити, в Супрязі має позначку «звірити». Це
нормальний наслідок, а не збій.

### 3.6. Таблиця справ і повнота

Після читання `read` складає таблицю справ і порівнює їх число з тим, що агент записав у метаданих.
Це повнота:

- **90 % і вище** — таблиця може йти далі;
- **нижче 90 %** — попередження, що справи злиплись. Такий опис віддавати не можна: агент має спершу
  звірити метадані (сторінки таблиці, ролі колонок) з двома-трьома сторінками й сказати, на яких
  сторінках справ бракує.

Межі справ пакет вибирає сам: ні людина, ні агент їх не задають.

## 4. Нормалізація назв

Назви справ спершу лишаються такими, як їх прочитала машина, і їх нормалізують (осучаснюють),
щоб за ними можна було шукати. Назви нарізаються пачками по 20, і є три шляхи.

| Шлях | Хто нормалізує | Що видно людині |
|---|---|---|
| Агент | підагенти агента, пачками | кількість пачок і відповідь на кожну |
| Ключ API людини | сам `nysh` через пакетний режим (Claude чи OpenAI): дешевше, у межах бюджету, який людина задала | `nysh opys api stan` показує модель, бюджет, витрачене й залишок; задача пакетного режиму чекає до 30 хвилин, повтор команди забирає готове |
| Обмін (`--na-obmin`) | інші учасники Супряги | опис іде з сирими назвами, нормалізація відбудеться пізніше |

Правила, на які можна покластись:

- **Прізвища й назви місць нормалізатор не виправляє.** Він переписує їх буквально, а зіпсоване
  позначає ⟨?…⟩.
- **Ворота не пускають опис**, де нормалізовано менше ніж 95 % рядків, або де нормалізація вигадує
  власні назви.
- Пачка з відповіддю не тієї довжини не приймається. Відповідь, що не розбирається як масив (`norm_bad`),
  теж: агент переробляє таку пачку сам.
- Поки назви не осучаснено, опис у Супрязі видно з сирими назвами, як їх прочитала машина.

## 5. Заливка й перевірка

`nysh opys push` збирає відповіді нормалізації, пакет, проводить його через ворота й заливає. Ворота
відмовляють усіма причинами разом, тож агентові не доведеться вгадувати їх по одній. Заливка йде
від імені людини, тому її згода потрібна. Повторна заливка того самого опису тим самим автором
заступає попередню.

Перевірку робить агент, а людина може стежити:

- **до заливки** — число справ і номери на двох-трьох сторінках таблиці збігаються з тим, що видно
  на скані;
- **після заливки** — пошук відомого з опису села (`nysh opys search "<село>"` чи на сторінці Засік)
  знаходить справу з номером і посиланням на сторінку.

## 6. Коли втручатись, а коли ні

| | Ситуація | Чому |
|---|---|---|
| 🔴 Втрутитись | Повнота таблиці нижче 90 % | справи злиплись, опис не можна віддавати |
| 🔴 Втрутитись | Номери на звірених сторінках не збігаються зі сканом | таблиця читається хибно, і пошук дасть чужі справи |
| 🔴 Втрутитись | Агент просить дозволу на хмарний захід понад стелю ($2) | це рішення людини про гроші |
| 🔴 Втрутитись | «Хмара ще читає» понад годину без руху | захід, схоже, завис: потрібен стан (`nysh cloud state`) |
| 🔴 Втрутитись | Агент пропонує вписати ключ API за людину | ключ вводить лише людина, і лише у своєму терміналі |
| 🔴 Втрутитись | Ворота відмовили, а агент «обходить» відмову переписуванням назв | ворота стережуть якість, їх не обходять |
| 🟢 Не втручатись | Довге читання, де є прогрес | так працює процесор; на відеокарті й у хмарі швидше |
| 🟢 Не втручатись | Агент знову й знову запускає ту саму команду | так задумано: повтор забирає результат і продовжує з місця |
| 🟢 Не втручатись | Частина номерів має позначку «звірити» | так позначається непідтверджений номер |
| 🟢 Не втручатись | Агент сам переробляє пачку, яку не прийняли (`norm_bad`) | звичайна поправка відповіді нормалізатора |

## 7. Що людина має за собою

- Вона не набирає команд і не читає журналів: агент розповідає, що відбувається.
- Вона вирішує те, що належить лише їй: гроші за хмару понад стелю, власний ключ API й бюджет,
  згоду на заливку.
- Вона може перевірити результат без технічних знань: відкрити сторінку Засік, знайти відоме село
  й побачити, що справа з номером і сторінкою опису там є.

Технічні команди й опис кроків для агента — у його скілі `read-opys`.
