<p align="center">
  <img alt="Нишпорка"
       src="https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/src/nyshporka/brand/data/assets/mark.png"
       width="132" height="132">
</p>

<h1 align="center">Нишпорка</h1>

<p align="center"><em>Читає рукопис. Приносить знайдене.</em></p>

<p align="center">
  <a href="https://pypi.org/project/nyshporka/"><img alt="PyPI"
     src="https://img.shields.io/pypi/v/nyshporka"></a>
  <a href="https://github.com/SERGIUSH-UA/nyshporka/actions/workflows/ci.yml"><img alt="CI"
     src="https://github.com/SERGIUSH-UA/nyshporka/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python" src="https://img.shields.io/pypi/pyversions/nyshporka">
  <img alt="Ліцензія" src="https://img.shields.io/badge/license-AGPL--3.0-informational">
</p>

Ви берете теку сканів із архіву — і отримуєте текст, у якому можна шукати
прізвище. Нишпорка читає рукописний скоропис XVIII–XIX ст. українських,
молдовських і польських архівів: те, чого не беруть комерційні OCR, а платні
платформи не мають моделей під цей матеріал.

Усе працює на вашому комп'ютері: ні облікових записів, ні передплати, ні
вивантаження ваших сканів кудись назовні.

<p align="center">
  <a href="https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe"><b>⬇ Завантажити для Windows</b></a>
  &nbsp;·&nbsp;
  <a href="https://sergiush-ua.github.io/nyshporka/install/">інші системи</a>
  &nbsp;·&nbsp;
  <a href="https://sergiush-ua.github.io/nyshporka/start/">поставив — що далі</a>
</p>

## Як це виглядає

**Видно, звідки взявся текст.** Машина подає прочитане, рішення лишається за
оком: клацнувши рядок, ви бачите його вирізку з аркуша — у тому вигляді, у
якому його бачив рушій.

<img alt="Гортач: скан із рамками рядків, машинний текст і вирізка обраного рядка"
     src="https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/docs/assets/screens/gortach.jpg">

**Де взагалі метрики мого села.** Газетир і покажчик плівок їдуть разом із
програмою й відповідають одразу після встановлення — без сканів, без
відеокарти, без обходу чужих сайтів.

<img alt="Газетир: пошук села по всіх фондах і конфесіях одразу"
     src="https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/docs/assets/screens/gazetyr.png">

**Пошук прізвища в прочитаному — зі знаменником.** Рушій калічить саме середину
слова, тож пошук нечіткий; і кожна відповідь каже, скільки прогонів і сторінок
за нею стоїть, щоб «немає» означало щось певне.

<img alt="Пошук: нечіткі збіги з оцінкою, шифром справи й покриттям пошуку"
     src="https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/docs/assets/screens/poshuk.png">

## Що вміє

* **Знайти, де лежать документи вашого села** — газетир ЦДІАК (4566 поселень,
  348 408 справ), поаркушевий покажчик плівок, каталог ДАХмО, церкви ~1772.
* **Прочитати рукопис** трьома рушіями: `[П]` **Писар** (кирилиця, головний
  голос), `[Д]` **Дяк** (кирилиця, другий голос — тримається пікселів там, де
  перший додумує), `[С]` **Скриба** (латинка: нотаріат і костельні книги).
* **Показати, звідки взявся текст** — вирізка рядка з рамкою, сторінка, два
  голоси поруч.
* **Шукати прізвище** в прочитаному, у виписаних іменах і в учасниках записів.
* **Вести облік** переглянутого оком, щоб наступна сесія не гортала ті самі
  аркуші вдруге.
* **Віддати таблицею** — розібрані акти в Ексель: фільтрувати роками, селом,
  станом і прізвищем.

Докладно, з межами кожного джерела — [**що вже
працює**](https://sergiush-ua.github.io/nyshporka/features/).

## Поставити

🤖 **Ставить агент?** Дайте йому одне посилання — [`AGENTS.md`](https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md).
Там і встановлення, і перші кроки, і межі, за якими вирішує людина.

**Windows.** [⬇ Завантажити інсталятор][setup] — запустити, відповісти на два
питання, натиснути «Встановити». Наприкінці галочка «Запустити Нишпорку»
відкриє застосунок у браузері. Python, прав адміністратора й термінала не
треба.

⚠ «Windows захистив ваш ПК» — «Докладніше» → «Виконати в будь-якому разі». Так
Windows зустрічає кожну програму, яку ще мало хто завантажував.

**Термінал, будь-яка система.** На чистій машині, без Python і без прав
адміністратора:

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```
```sh
curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
```

🔴 Коли скрипт завершить роботу — закрийте вікно термінала й **відкрийте нове**:
доти команда `nysh` у ньому не знайдеться. Якщо й у новому вікні не знаходиться —
**перезапустіть комп'ютер**. (Тим, хто ставив інсталятором, це не потрібно:
ярлики працюють одразу.)

**Якщо Python або `uv` уже є:**

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install …
nysh init                      # створити робочий простір
nysh doctor                    # перевірити те, що ламається тихо
nysh serve                     # відкрити застосунок у браузері
```

🔴 **Щоб читати рукопис — ще два разові кроки.** Рушії живуть в окремому
інтерпретаторі, а ваги приходять окремим релізом: у пакеті їх немає навмисно,
інакше кожен, хто прийшов подивитись каталог справ, платив би за них
гігабайтами.

```bash
nysh htr install    # середовище рушіїв: kraken і PARSeq
nysh models get     # ваги трьох моделей, ~130 МБ
```

Каталогам, газетиру й пошуку по описах вони не потрібні — ті працюють одразу.

На робочій машині розробника інсталятор нічого не переставляє; `--dry-run`
показує, що буде зроблено, а `NYSH_NO_MODIFY_PATH=1` не чіпає PATH зовсім.
Важелі, набори частин, деінсталяція й те, де живе дослідження, —
[**встановлення докладно**](https://sergiush-ua.github.io/nyshporka/install/).

## 🔴 Нуль мусить щось означати

«Немає» — найдорожча відповідь у генеалогії: вона закриває напрям назавжди.
Тому джерело, яке **не може** шукати, не додає нуль до суми: воно відмовляється
відповідати й каже, чого бракує. Кожна відповідь несе покриття — де саме
шукали, скільки сторінок пройдено й чи бачить пошук відомий позитив.

Це правило вбудоване в код, а не в інструкцію.

## Стан: alpha

Каталоги, завантаження, читання рукопису, гортач, сховище прочитаного, пошук,
браузерне обличчя й установлення працюють. Скани ви приносите самі, розбір
актів у поля робить ваш агент і вашим коштом, а ваги міряні на тому матеріалі,
на якому вчились. Повний перелік того, чого ще немає, без замовчувань —
[**межі**](https://sergiush-ua.github.io/nyshporka/limits/).

## Далі

| | |
|---|---|
| поставив — що робити першим | [Поставив. Що далі?](https://sergiush-ua.github.io/nyshporka/start/) |
| питання першого тижня | [Часті питання](https://sergiush-ua.github.io/nyshporka/faq/) |
| працювати через Claude Desktop чи Codex | [Підключити агента](https://sergiush-ua.github.io/nyshporka/agent/) |
| який екран на яке питання відповідає | [Карта екранів](https://sergiush-ua.github.io/nyshporka/screens/) |
| навчити Писаря своєму почерку | [Трен](https://sergiush-ua.github.io/nyshporka/train/) |
| прочитати справу на орендованій машині | [Хмара](https://sergiush-ua.github.io/nyshporka/cloud/) |
| що змінилось у версіях | [Що нового](https://sergiush-ua.github.io/nyshporka/whats-new/) |

Агентові окремий MCP не потрібен: `nysh op <ім'я> --describe` віддає схему
операції, `nysh op <ім'я>` виконує. Порядок роботи й межі, за якими вирішує
людина, — [`AGENTS.md`](AGENTS.md).

## Приватність, ліцензія, участь

Телеметрії немає, облікових записів немає, дослідження нікуди не
вивантажується, а в мережу застосунок ходить лише тоді, коли його про це
попросили командою — [`PRIVACY.md`](PRIVACY.md).

Код — [AGPL-3.0-or-later](LICENSE), ваги моделей — окремо, під
[CC BY-SA 4.0](LICENSE-MODELS.md). Чому саме так, як підписується інсталятор і
що звіряти при завантаженні —
[підписування й ліцензії](https://sergiush-ua.github.io/nyshporka/signing/).

Знайшли ваду або хочете допомогти — [`CONTRIBUTING.md`](CONTRIBUTING.md) і
[Issues](https://github.com/SERGIUSH-UA/nyshporka/issues).

[setup]: https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe
