<#
    Нишпорка — установлення на Windows без адміністратора й без Python.

    🔴 Python СИСТЕМНИЙ не використовується взагалі. Не з педантизму: на
    робочих машинах його або немає, або він 3.9 з магазину, або він уже
    зайнятий чужим проєктом і має несумісні пакети. Кожен із цих випадків дає
    поломку, яку генеалог зі сканами діагностувати не може. Тому інсталятор
    приносить `uv`, а `uv` приносить власний інтерпретатор.

    🔴 Усе кладеться в профіль користувача (%LOCALAPPDATA%). Права
    адміністратора не потрібні й не просяться: застосунок працює з файлами
    однієї людини і нічого системного не чіпає.

    Запуск із клону репозиторію:
        powershell -ExecutionPolicy Bypass -File install\windows.ps1

    Запуск без клону — завантажити файл і запустити (саме це дають агентові):
        irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
        powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1" -Preset catalog
    Пак довідників за замовчуванням береться з останнього релізу catalog-*
    (звірений sha256); не ставити його зовсім — `-NoCatalog`.

    🔴 Через конвеєр (`irm … | iex`) цей файл НЕ запускається, і відмова
    виглядає як десяток помилок розбору в шапці. Причина — BOM: він тут
    обов'язковий (див. коментар про UTF-8 нижче), `Invoke-RestMethod` віддає
    його як перший символ рядка, і ні `iex`, ні `[scriptblock]::Create` після
    цього вміст не розбирають. Перевірено на 5.1: без BOM той самий текст
    розбирається, з BOM — ні, незалежно від того, що стоїть у першому рядку.
#>
[CmdletBinding()]
param(
    [string]$Home_ = "$env:LOCALAPPDATA\Nyshporka",
    [string]$Source = "",
    # Які частини застосунку ставимо (`nysh sections`).
    # 🔴 Від цього залежить НЕ лише вигляд шапки, а й вага встановлення:
    # читання рукопису тягне torch (~2.5 ГБ), і той, хто прийшов подивитись
    # каталог справ, платити за нього гігабайтами не повинен. Змінити набір
    # можна будь-коли — але доставити рушії тоді доведеться окремим кроком.
    [ValidateSet('catalog', 'amateur', 'researcher', 'lab')]
    [string]$Preset = 'researcher',
    # Пін версії пакета. Порожньо — остання з PyPI (так зручніше тому, хто
    # запускає скрипт руками й хоче свіже).
    # 🔴 Майстер `.exe` передає сюди СВОЮ версію, і це не педантизм: файл
    # називається `nyshporka-0.6.2-setup.exe`, показує 0.6.2 у «Програмах і
    # засобах» — і мусить поставити 0.6.2, а не те, що лежить на PyPI сьогодні.
    # Та сама вада, проти якої в релізі вже стоїть приймач «версія колеса ==
    # тег»: реліз, усередині якого інша версія, читається як зламаний pip.
    [string]$Version = "",
    [switch]$NoLauncher,
    # Показати, що буде зроблено, і вийти. Симетрія з `--dry-run` в
    # `install/unix.sh`: людина має право подивитись, що чіпатимуть на її
    # машині, ДО того, як щось завантажилось.
    [switch]$DryRun,
    # Не брати пак довідників з останнього релізу `catalog-*`, коли його немає
    # поруч (офлайн-машина; свій пак поставлять окремо `nysh catalog install
    # --from`). Те саме робить змінна `NYSH_NO_CATALOG=1`, як в `unix.sh`.
    [switch]$NoCatalog,
    # Не доставляти рушії читання й моделі письма (`nysh htr install`,
    # `nysh models get`) — для того, хто поставить їх пізніше сам. Набір
    # `catalog` їх не ставить і без цього прапорця.
    [switch]$NoEngines,
    # Куди uv ставить керовані інтерпретатори. Порожньо — `<Home_>\python`.
    # 🔴 Не типовий `%APPDATA%\uv\python`: там uv робить junction на мінорну
    # версію, і Windows з перенаправленим AppData / OneDrive відмовляється його
    # проходити — os error 448 (14.10.2026, astral-sh/uv#19622, #19616). Якщо
    # 448 і в теці профілю — вказати теку поза ним: `-PythonDir D:\Nyshporka\python`.
    [string]$PythonDir = "",
    # Запуск із майстра `.exe`: консоль зникає разом зі скриптом, тож помилку
    # треба показати вікном, яке переживе консоль.
    [switch]$Wizard,
    # Мова виводу: uk | en | pl | ro | fr | de | ru. Порожньо — мова Windows.
    [string]$Lang = ''
)

# ── мова виводу ──────────────────────────────────────────────────────────────
# 🌐 Ті самі мови, що на порталі й у консолі. Майстер `.exe` передає свою
# (`-Lang`); запуск руками бере мову інтерфейсу Windows. Вимкнена мова
# (`$LangsOff`, дзеркало `VYMKNENI` порталу) сама не вибирається, лише явно.
# Мова, якої тут немає, — українська: так само, як у консолі.
# ⚠ Тексти — для `-f`: підстановки `{0}`, `{1}`; інших фігурних дужок у них
# бути не може (ловить `test_windows_ps1_messages_complete`).
$Langs = @('uk', 'en', 'pl', 'ro', 'fr', 'de', 'ru')
$LangsOff = @('ru')
if (-not $Lang) {
    try { $Lang = (Get-UICulture).TwoLetterISOLanguageName } catch { $Lang = 'uk' }
    if ($LangsOff -contains $Lang) { $Lang = 'uk' }
}
$Lang = "$Lang".ToLowerInvariant()
if ($Langs -notcontains $Lang) { $Lang = 'uk' }

$Msg = @{
    uk = @{
        'brand.tag' = 'Читає рукопис. Приносить знайдене.'
        'hdr.dir' = '  тека: {0}'
        'dry.uv.have' = 'uv                 уже є: {0}'
        'dry.uv.get' = 'uv                 буде завантажено в {0}'
        'dry.python' = 'Python 3.12        керований, у {0}; ні в PATH, ні в реєстрі його не буде'
        'dry.app' = 'Нишпорка           {0}'
        'dry.preset' = 'набір {0}'
        'dry.app2' = '                   в ізольованому середовищі інструмента uv'
        'dry.cmd' = 'команда nysh       {0}'
        'dry.trace' = 'слід інсталятора   {0}'
        'dry.space' = 'простір досліджень тека, яку назве «nysh init»'
        'dry.eng1' = 'рушії читання      nysh htr install — torch під відеокарту NVIDIA, якщо драйвер її'
        'dry.eng2' = '                   показує, інакше під процесор (~2.5–4 ГБ, у теці простору)'
        'dry.models' = 'моделі письма      nysh models get (~215 МБ, sha256 звіряється)'
        'dry.why.own' = 'свої, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'рушії читання      не ставляться ({0})'
        'dry.cat.no' = 'довідники          не ставляться (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'довідники          з останнього релізу catalog-* (звірка sha256), якщо немає поруч'
        'dry.path.no' = 'PATH користувача   не чіпається (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'PATH користувача   один допис «{0}», якщо теки там ще немає'
        'dry.done' = 'Нічого не зроблено — це -DryRun.'
        'admin.1' = '  ⚠ Запуск із правами адміністратора. Усе стане в профіль користувача'
        'admin.3' = '    Якщо працювати буде інший користувач — йому команда nysh і ярлики'
        'admin.4' = '    не дістануться; встановлюйте з-під його облікового запису.'
        'preflight' = 'Передперевірка: програми з профілю користувача ({0}) на цій машині НЕ ЗАПУСКАЮТЬСЯ — схоже на політику AppLocker/SRP або правило ASR. Нишпорка ставиться в профіль без прав адміністратора, тож тут вона не працюватиме. Варіанти: запустити інсталятор правою кнопкою миші → «Запустити від імені адміністратора» (тоді все стане в профіль адміністратора), або попросити ІТ дозволити запуск із {0} і {1}.'
        'uv.have' = '✓ uv уже є: {0}'
        'err.uv' = 'uv не встановився у {0}'
        'err.python' = 'не вдалося встановити Python 3.12 (uv повернув {0})'
        'app.get' = '⬇ Нишпорка ({0})…'
        'err.app' = 'не вдалося встановити {0} (uv повернув {1})'
        'app.ok' = '✓ Нишпорка'
        'nocmd.1' = '✗ пакет установлено, але команди немає: {0}'
        'nocmd.2' = '  надішліть, будь ласка, вивід `uv tool list` — це вада інсталятора,'
        'nocmd.3' = '  а не вашої машини'
        'err.nocmd' = 'nysh не знайдено після встановлення'
        'info.fail' = '⚠ не вдалося записати {0} — ярлики доведеться створити вручну'
        'err.init' = 'не вдалося створити робочий простір (nysh повернув {0})'
        'eng.get' = '⬇ рушії читання (torch під вашу карту, ~2.5–4 ГБ — кілька хвилин)…'
        'eng.fail' = '⚠ рушії читання не зібрались (nysh повернув {0}) — повторити: nysh htr install'
        'models.get' = '⬇ моделі письма…'
        'models.fail' = '⚠ моделі письма не завантажились (nysh повернув {0}) — повторити: nysh models get'
        'eng.err' = '⚠ рушії читання не доставлено: {0}'
        'eng.retry' = '  повторити: nysh htr install, потім nysh models get'
        'eng.foreign' = 'ℹ рушії читання вказано змінною NYSHPORKA_HTR_VENV — не чіпаю: {0}'
        'eng.ok' = '✓ рушії читання й моделі письма'
        'cat.list' = '⚠ не вдалось прочитати перелік релізів GitHub — мережа чи ліміт API'
        'cat.none' = '⚠ жодного релізу catalog-* не знайдено'
        'cat.nosum' = '⚠ реліз {0}: асет без контрольної суми sha256 — качати без звірки не можна'
        'cat.nourl' = '⚠ реліз {0}: не знайдено посилання на завантаження'
        'cat.dl' = '⚠ не вдалось завантажити пак довідників ({0})'
        'cat.sum' = '⚠ контрольна сума пака довідників ({0}) не збіглася — не встановлюю'
        'cat.ok' = '✓ пак довідників {0}: встановлено (sha256 звірено)'
        'cat.refused' = '⚠ «nysh catalog install» відмовив на паку {0}'
        'cat.err' = '⚠ пак довідників з релізу не поставлено: {0}'
        'cat.skip' = 'ℹ довідники не ставляться (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ довідників поруч немає — пошук по каталогах архівів буде недоступний'
        'cat.take' = '  взяти: {0}'
        'cat.next' = '  далі:  nysh catalog install --from <завантажений zip>'
        'desk.ok' = '✓ ярлик на робочому столі'
        'trace.fail' = '⚠ не вдалося записати {0} — «nysh uninstall» питатиме шляхи'
        'sum.title' = 'Змінено на цій машині:'
        'sum.dir' = '  тека        {0}'
        'sum.bin' = '  команда     {0}'
        'sum.file' = '  файл        {0}'
        'sum.path' = '  PATH        допис «{0}» у змінні середовища користувача'
        'sum.space' = '  простір досліджень — тека, яку щойно назвав «nysh init»'
        'sum.undo' = '  зняти все це: nysh uninstall'
        'done' = 'Готово.'
        'reopen.1' = '  ⚠ Закрийте це вікно й відкрийте нове — команди нижче працюють там.'
        'reopen.2' = '    У вікнах, відкритих до встановлення, «nysh» не знайдеться.'
        'reopen.3' = '    Якщо й у новому не знайдеться — перезапустіть комп''ютер.'
        'next' = 'Далі:'
        'next.serve' = '  nysh serve            відкрити застосунок у браузері'
        'next.look' = '  nysh look <тека>      подивитись, що за скани'
        'next.htr' = '  nysh htr install      зібрати рушії читання (torch під вашу карту)'
        'next.models' = '  nysh models get       завантажити моделі письма'
        'next.doctor' = '  nysh doctor           перевірити те, що ламається тихо'
        'trap.error' = 'Помилка: {0}'
        'trap.line' = '   (рядок {0} інсталятора)'
        'trap.tail' = 'Останні рядки виводу:'
        'trap.log' = 'Повний журнал: {0}'
        'trap.title' = 'Нишпорка: установлення не завершилось'
        'brand.name' = 'Нишпорка'
        'lnk.desc' = 'Читання рукописних архівних справ'
        'err.448' = 'Windows не довіряє теці, куди uv ставить Python (os error 448: перенаправлений AppData чи OneDrive). Поставте Нишпорку наново з текою інтерпретаторів поза профілем: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    en = @{
        'brand.tag' = 'Reads handwriting. Brings back what it finds.'
        'hdr.dir' = '  folder: {0}'
        'dry.uv.have' = 'uv                 already installed: {0}'
        'dry.uv.get' = 'uv                 will be downloaded to {0}'
        'dry.python' = 'Python 3.12        managed, in {0}; it will not be in PATH or the registry'
        'dry.app' = 'Nyshporka          {0}'
        'dry.preset' = 'preset {0}'
        'dry.app2' = '                   in uv''s isolated tool environment'
        'dry.cmd' = 'nysh command       {0}'
        'dry.trace' = 'installer trace    {0}'
        'dry.space' = 'research space     folder named by “nysh init”'
        'dry.eng1' = 'reading engines    nysh htr install — torch for an NVIDIA graphics card if the driver'
        'dry.eng2' = '                   shows one, otherwise for the CPU (~2.5–4 GB, in the space folder)'
        'dry.models' = 'handwriting models nysh models get (~215 MB, sha256 verified)'
        'dry.why.own' = 'own, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'reading engines    not installed ({0})'
        'dry.cat.no' = 'catalogs           not installed (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'catalogs           from the latest catalog-* release (sha256 verified), if none nearby'
        'dry.path.no' = 'user PATH          left untouched (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'user PATH          one entry “{0}”, if the folder is not there yet'
        'dry.done' = 'Nothing was done — this is -DryRun.'
        'admin.1' = '  ⚠ Running as administrator. Everything will go into the user profile'
        'admin.3' = '    If another user will work here, they will not get the nysh command or the'
        'admin.4' = '    shortcuts; install from their own account.'
        'preflight' = 'Pre-check: programs from the user profile ({0}) CANNOT RUN on this machine — it looks like an AppLocker/SRP policy or an ASR rule. Nyshporka installs into the profile without administrator rights, so it will not work here. Options: start the installer with a right click → “Run as administrator” (everything then goes into the administrator''s profile), or ask IT to allow running from {0} and {1}.'
        'uv.have' = '✓ uv already installed: {0}'
        'err.uv' = 'uv did not install into {0}'
        'err.python' = 'could not install Python 3.12 (uv returned {0})'
        'app.get' = '⬇ Nyshporka ({0})…'
        'err.app' = 'could not install {0} (uv returned {1})'
        'app.ok' = '✓ Nyshporka'
        'nocmd.1' = '✗ the package is installed, but the command is missing: {0}'
        'nocmd.2' = '  please send the output of `uv tool list` — this is an installer bug,'
        'nocmd.3' = '  not a problem with your machine'
        'err.nocmd' = 'nysh not found after installation'
        'info.fail' = '⚠ could not write {0} — shortcuts will have to be created by hand'
        'err.init' = 'could not create the workspace (nysh returned {0})'
        'eng.get' = '⬇ reading engines (torch for your card, ~2.5–4 GB — a few minutes)…'
        'eng.fail' = '⚠ reading engines were not built (nysh returned {0}) — retry: nysh htr install'
        'models.get' = '⬇ handwriting models…'
        'models.fail' = '⚠ handwriting models were not downloaded (nysh returned {0}) — retry: nysh models get'
        'eng.err' = '⚠ reading engines were not installed: {0}'
        'eng.retry' = '  retry: nysh htr install, then nysh models get'
        'eng.foreign' = 'ℹ reading engines are set by NYSHPORKA_HTR_VENV — leaving them alone: {0}'
        'eng.ok' = '✓ reading engines and handwriting models'
        'cat.list' = '⚠ could not read the GitHub release list — network or API limit'
        'cat.none' = '⚠ no catalog-* release found'
        'cat.nosum' = '⚠ release {0}: asset has no sha256 checksum — will not download unverified'
        'cat.nourl' = '⚠ release {0}: download link not found'
        'cat.dl' = '⚠ could not download the catalog pack ({0})'
        'cat.sum' = '⚠ checksum of the catalog pack ({0}) does not match — not installing'
        'cat.ok' = '✓ catalog pack {0}: installed (sha256 verified)'
        'cat.refused' = '⚠ “nysh catalog install” rejected pack {0}'
        'cat.err' = '⚠ catalog pack from the release was not installed: {0}'
        'cat.skip' = 'ℹ catalogs are not installed (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ no catalogs nearby — searching the archive catalogs will be unavailable'
        'cat.take' = '  get it: {0}'
        'cat.next' = '  then:   nysh catalog install --from <downloaded zip>'
        'desk.ok' = '✓ desktop shortcut'
        'trace.fail' = '⚠ could not write {0} — “nysh uninstall” will ask for the paths'
        'sum.title' = 'Changed on this machine:'
        'sum.dir' = '  folder      {0}'
        'sum.bin' = '  command     {0}'
        'sum.file' = '  file        {0}'
        'sum.path' = '  PATH        entry “{0}” in the user''s environment variables'
        'sum.space' = '  research space — the folder “nysh init” just named'
        'sum.undo' = '  to undo all of this: nysh uninstall'
        'done' = 'Done.'
        'reopen.1' = '  ⚠ Close this window and open a new one — the commands below work there.'
        'reopen.2' = '    In windows opened before the installation, “nysh” will not be found.'
        'reopen.3' = '    If it is not found in the new one either, restart the computer.'
        'next' = 'Next:'
        'next.serve' = '  nysh serve            open the app in the browser'
        'next.look' = '  nysh look <folder>    see what the scans are'
        'next.htr' = '  nysh htr install      build the reading engines (torch for your card)'
        'next.models' = '  nysh models get       download the handwriting models'
        'next.doctor' = '  nysh doctor           check what breaks silently'
        'trap.error' = 'Error: {0}'
        'trap.line' = '   (installer line {0})'
        'trap.tail' = 'Last lines of output:'
        'trap.log' = 'Full log: {0}'
        'trap.title' = 'Nyshporka: installation did not finish'
        'brand.name' = 'Nyshporka'
        'lnk.desc' = 'Reading handwritten archival records'
        'err.448' = 'Windows does not trust the folder where uv puts Python (os error 448: redirected AppData or OneDrive). Reinstall Nyshporka with the interpreter folder outside the profile: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    pl = @{
        'brand.tag' = 'Czyta rękopisy. Przynosi to, co znajdzie.'
        'hdr.dir' = '  folder: {0}'
        'dry.uv.have' = 'uv                 już jest: {0}'
        'dry.uv.get' = 'uv                 zostanie pobrany do {0}'
        'dry.python' = 'Python 3.12        zarządzany, w {0}; nie trafi do PATH ani do rejestru'
        'dry.app' = 'Nyshporka          {0}'
        'dry.preset' = 'zestaw {0}'
        'dry.app2' = '                   w izolowanym środowisku narzędzia uv'
        'dry.cmd' = 'polecenie nysh     {0}'
        'dry.trace' = 'ślad instalatora   {0}'
        'dry.space' = 'przestrzeń badań   folder wskazany przez „nysh init”'
        'dry.eng1' = 'silniki odczytu    nysh htr install — torch pod kartę NVIDIA, jeśli sterownik'
        'dry.eng2' = '                   ją widzi, w przeciwnym razie pod procesor (~2,5–4 GB, w folderze przestrzeni)'
        'dry.models' = 'modele pisma       nysh models get (~215 MB, sha256 sprawdzany)'
        'dry.why.own' = 'własne, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'silniki odczytu    nie są instalowane ({0})'
        'dry.cat.no' = 'katalogi           nie są instalowane (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'katalogi           z najnowszego wydania catalog-* (sha256 sprawdzany), jeśli nie ma obok'
        'dry.path.no' = 'PATH użytkownika   bez zmian (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'PATH użytkownika   jeden wpis „{0}”, jeśli folderu jeszcze tam nie ma'
        'dry.done' = 'Nic nie zrobiono — to jest -DryRun.'
        'admin.1' = '  ⚠ Uruchomiono jako administrator. Wszystko trafi do profilu użytkownika'
        'admin.3' = '    Jeśli będzie tu pracować inny użytkownik, nie dostanie polecenia nysh ani'
        'admin.4' = '    skrótów; zainstaluj z jego konta.'
        'preflight' = 'Kontrola wstępna: programy z profilu użytkownika ({0}) NIE URUCHAMIAJĄ SIĘ na tym komputerze — wygląda to na zasadę AppLocker/SRP lub regułę ASR. Nyshporka instaluje się w profilu bez uprawnień administratora, więc tu nie zadziała. Do wyboru: uruchom instalator prawym przyciskiem myszy → „Uruchom jako administrator” (wtedy wszystko trafi do profilu administratora) albo poproś dział IT o zezwolenie na uruchamianie z {0} i {1}.'
        'uv.have' = '✓ uv już jest: {0}'
        'err.uv' = 'uv nie zainstalował się w {0}'
        'err.python' = 'nie udało się zainstalować Python 3.12 (uv zwrócił {0})'
        'app.get' = '⬇ Nyshporka ({0})…'
        'err.app' = 'nie udało się zainstalować {0} (uv zwrócił {1})'
        'app.ok' = '✓ Nyshporka'
        'nocmd.1' = '✗ pakiet zainstalowany, ale brak polecenia: {0}'
        'nocmd.2' = '  prześlij proszę wynik `uv tool list` — to błąd instalatora,'
        'nocmd.3' = '  a nie Twojego komputera'
        'err.nocmd' = 'nie znaleziono nysh po instalacji'
        'info.fail' = '⚠ nie udało się zapisać {0} — skróty trzeba będzie utworzyć ręcznie'
        'err.init' = 'nie udało się utworzyć przestrzeni roboczej (nysh zwrócił {0})'
        'eng.get' = '⬇ silniki odczytu (torch pod Twoją kartę, ~2,5–4 GB — kilka minut)…'
        'eng.fail' = '⚠ silniki odczytu nie zostały zbudowane (nysh zwrócił {0}) — ponów: nysh htr install'
        'models.get' = '⬇ modele pisma…'
        'models.fail' = '⚠ modele pisma nie zostały pobrane (nysh zwrócił {0}) — ponów: nysh models get'
        'eng.err' = '⚠ silniki odczytu nie zostały dostarczone: {0}'
        'eng.retry' = '  ponów: nysh htr install, potem nysh models get'
        'eng.foreign' = 'ℹ silniki odczytu wskazuje zmienna NYSHPORKA_HTR_VENV — nie ruszam: {0}'
        'eng.ok' = '✓ silniki odczytu i modele pisma'
        'cat.list' = '⚠ nie udało się odczytać listy wydań GitHub — sieć lub limit API'
        'cat.none' = '⚠ nie znaleziono żadnego wydania catalog-*'
        'cat.nosum' = '⚠ wydanie {0}: zasób bez sumy kontrolnej sha256 — nie wolno pobierać bez weryfikacji'
        'cat.nourl' = '⚠ wydanie {0}: nie znaleziono linku do pobrania'
        'cat.dl' = '⚠ nie udało się pobrać paczki katalogów ({0})'
        'cat.sum' = '⚠ suma kontrolna paczki katalogów ({0}) się nie zgadza — nie instaluję'
        'cat.ok' = '✓ paczka katalogów {0}: zainstalowana (sha256 sprawdzony)'
        'cat.refused' = '⚠ „nysh catalog install” odrzucił paczkę {0}'
        'cat.err' = '⚠ paczka katalogów z wydania nie została zainstalowana: {0}'
        'cat.skip' = 'ℹ katalogi nie są instalowane (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ brak katalogów obok — wyszukiwanie w katalogach archiwów będzie niedostępne'
        'cat.take' = '  pobierz: {0}'
        'cat.next' = '  potem:  nysh catalog install --from <pobrany zip>'
        'desk.ok' = '✓ skrót na pulpicie'
        'trace.fail' = '⚠ nie udało się zapisać {0} — „nysh uninstall” zapyta o ścieżki'
        'sum.title' = 'Zmieniono na tym komputerze:'
        'sum.dir' = '  folder      {0}'
        'sum.bin' = '  polecenie   {0}'
        'sum.file' = '  plik        {0}'
        'sum.path' = '  PATH        wpis „{0}” w zmiennych środowiskowych użytkownika'
        'sum.space' = '  przestrzeń badań — folder, który przed chwilą wskazał „nysh init”'
        'sum.undo' = '  cofnąć to wszystko: nysh uninstall'
        'done' = 'Gotowe.'
        'reopen.1' = '  ⚠ Zamknij to okno i otwórz nowe — polecenia poniżej działają tam.'
        'reopen.2' = '    W oknach otwartych przed instalacją „nysh” nie zostanie znalezione.'
        'reopen.3' = '    Jeśli w nowym też nie, uruchom komputer ponownie.'
        'next' = 'Dalej:'
        'next.serve' = '  nysh serve            otwórz aplikację w przeglądarce'
        'next.look' = '  nysh look <folder>    zobacz, co to za skany'
        'next.htr' = '  nysh htr install      zbuduj silniki odczytu (torch pod Twoją kartę)'
        'next.models' = '  nysh models get       pobierz modele pisma'
        'next.doctor' = '  nysh doctor           sprawdź to, co psuje się po cichu'
        'trap.error' = 'Błąd: {0}'
        'trap.line' = '   (wiersz {0} instalatora)'
        'trap.tail' = 'Ostatnie wiersze wyniku:'
        'trap.log' = 'Pełny dziennik: {0}'
        'trap.title' = 'Nyshporka: instalacja nie została ukończona'
        'brand.name' = 'Nyshporka'
        'lnk.desc' = 'Odczyt rękopiśmiennych dokumentów archiwalnych'
        'err.448' = 'Windows nie ufa folderowi, w którym uv instaluje Pythona (os error 448: przekierowany AppData lub OneDrive). Zainstaluj Nyshporkę ponownie z folderem interpreterów poza profilem: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    ro = @{
        'brand.tag' = 'Citește manuscrise. Aduce ce găsește.'
        'hdr.dir' = '  dosar: {0}'
        'dry.uv.have' = 'uv                 există deja: {0}'
        'dry.uv.get' = 'uv                 va fi descărcat în {0}'
        'dry.python' = 'Python 3.12        gestionat, în {0}; nu va fi nici în PATH, nici în registru'
        'dry.app' = 'Nyshporka          {0}'
        'dry.preset' = 'setul {0}'
        'dry.app2' = '                   în mediul izolat al instrumentului uv'
        'dry.cmd' = 'comanda nysh       {0}'
        'dry.trace' = 'urma instalării    {0}'
        'dry.space' = 'spațiu cercetare   folderul indicat de „nysh init”'
        'dry.eng1' = 'motoare de citire  nysh htr install — torch pentru placa NVIDIA, dacă driverul'
        'dry.eng2' = '                   o vede, altfel pentru procesor (~2,5–4 GB, în folderul spațiului)'
        'dry.models' = 'modele de scris    nysh models get (~215 MB, sha256 verificat)'
        'dry.why.own' = 'proprii, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'motoare de citire  nu se instalează ({0})'
        'dry.cat.no' = 'cataloage          nu se instalează (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'cataloage          din ultima versiune catalog-* (sha256 verificat), dacă nu există alături'
        'dry.path.no' = 'PATH utilizator    nu se modifică (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'PATH utilizator    o singură intrare „{0}”, dacă folderul nu e încă acolo'
        'dry.done' = 'Nu s-a făcut nimic — este -DryRun.'
        'admin.1' = '  ⚠ Rulare ca administrator. Totul va merge în profilul utilizatorului'
        'admin.3' = '    Dacă va lucra alt utilizator, nu va primi comanda nysh și scurtăturile;'
        'admin.4' = '    instalați din contul lui.'
        'preflight' = 'Verificare preliminară: programele din profilul utilizatorului ({0}) NU POT RULA pe acest calculator — pare o politică AppLocker/SRP sau o regulă ASR. Nyshporka se instalează în profil fără drepturi de administrator, deci aici nu va funcționa. Variante: porniți programul de instalare cu clic dreapta → „Executare ca administrator” (atunci totul va merge în profilul administratorului) sau cereți departamentului IT să permită rularea din {0} și {1}.'
        'uv.have' = '✓ uv există deja: {0}'
        'err.uv' = 'uv nu s-a instalat în {0}'
        'err.python' = 'nu s-a putut instala Python 3.12 (uv a returnat {0})'
        'app.get' = '⬇ Nyshporka ({0})…'
        'err.app' = 'nu s-a putut instala {0} (uv a returnat {1})'
        'app.ok' = '✓ Nyshporka'
        'nocmd.1' = '✗ pachetul este instalat, dar comanda lipsește: {0}'
        'nocmd.2' = '  trimiteți, vă rugăm, rezultatul comenzii `uv tool list` — este o defecțiune a'
        'nocmd.3' = '  programului de instalare, nu a calculatorului dumneavoastră'
        'err.nocmd' = 'nysh nu a fost găsit după instalare'
        'info.fail' = '⚠ nu s-a putut scrie {0} — scurtăturile trebuie create manual'
        'err.init' = 'nu s-a putut crea spațiul de lucru (nysh a returnat {0})'
        'eng.get' = '⬇ motoare de citire (torch pentru placa dumneavoastră, ~2,5–4 GB — câteva minute)…'
        'eng.fail' = '⚠ motoarele de citire nu s-au construit (nysh a returnat {0}) — reîncercați: nysh htr install'
        'models.get' = '⬇ modele de scris…'
        'models.fail' = '⚠ modelele de scris nu s-au descărcat (nysh a returnat {0}) — reîncercați: nysh models get'
        'eng.err' = '⚠ motoarele de citire nu au fost livrate: {0}'
        'eng.retry' = '  reîncercați: nysh htr install, apoi nysh models get'
        'eng.foreign' = 'ℹ motoarele de citire sunt indicate de variabila NYSHPORKA_HTR_VENV — nu le ating: {0}'
        'eng.ok' = '✓ motoare de citire și modele de scris'
        'cat.list' = '⚠ nu s-a putut citi lista versiunilor GitHub — rețea sau limită API'
        'cat.none' = '⚠ nu s-a găsit nicio versiune catalog-*'
        'cat.nosum' = '⚠ versiunea {0}: fișier fără sumă de control sha256 — nu se poate descărca fără verificare'
        'cat.nourl' = '⚠ versiunea {0}: nu s-a găsit linkul de descărcare'
        'cat.dl' = '⚠ nu s-a putut descărca pachetul de cataloage ({0})'
        'cat.sum' = '⚠ suma de control a pachetului de cataloage ({0}) nu corespunde — nu instalez'
        'cat.ok' = '✓ pachet de cataloage {0}: instalat (sha256 verificat)'
        'cat.refused' = '⚠ „nysh catalog install” a refuzat pachetul {0}'
        'cat.err' = '⚠ pachetul de cataloage din versiune nu a fost instalat: {0}'
        'cat.skip' = 'ℹ cataloagele nu se instalează (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ nu există cataloage alături — căutarea în cataloagele arhivelor nu va fi disponibilă'
        'cat.take' = '  luați: {0}'
        'cat.next' = '  apoi:  nysh catalog install --from <zip descărcat>'
        'desk.ok' = '✓ scurtătură pe desktop'
        'trace.fail' = '⚠ nu s-a putut scrie {0} — „nysh uninstall” va cere căile'
        'sum.title' = 'Modificat pe acest calculator:'
        'sum.dir' = '  folder      {0}'
        'sum.bin' = '  comandă     {0}'
        'sum.file' = '  fișier      {0}'
        'sum.path' = '  PATH        intrarea „{0}” în variabilele de mediu ale utilizatorului'
        'sum.space' = '  spațiu de cercetare — folderul indicat adineauri de „nysh init”'
        'sum.undo' = '  anulați toate acestea: nysh uninstall'
        'done' = 'Gata.'
        'reopen.1' = '  ⚠ Închideți această fereastră și deschideți una nouă — comenzile de mai jos funcționează acolo.'
        'reopen.2' = '    În ferestrele deschise înainte de instalare, „nysh” nu va fi găsit.'
        'reopen.3' = '    Dacă nici în cea nouă nu e găsit, reporniți calculatorul.'
        'next' = 'Mai departe:'
        'next.serve' = '  nysh serve            deschide aplicația în browser'
        'next.look' = '  nysh look <folder>    vezi ce scanări sunt'
        'next.htr' = '  nysh htr install      construiește motoarele de citire (torch pentru placa dvs.)'
        'next.models' = '  nysh models get       descarcă modelele de scris'
        'next.doctor' = '  nysh doctor           verifică ce se strică pe tăcute'
        'trap.error' = 'Eroare: {0}'
        'trap.line' = '   (linia {0} a programului de instalare)'
        'trap.tail' = 'Ultimele linii ale rezultatului:'
        'trap.log' = 'Jurnal complet: {0}'
        'trap.title' = 'Nyshporka: instalarea nu s-a încheiat'
        'brand.name' = 'Nyshporka'
        'lnk.desc' = 'Citirea dosarelor de arhivă scrise de mână'
        'err.448' = 'Windows nu are încredere în folderul în care uv instalează Python (os error 448: AppData sau OneDrive redirecționat). Reinstalați Nyshporka cu folderul interpretoarelor în afara profilului: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    fr = @{
        'brand.tag' = 'Lit les manuscrits. Rapporte ce qu''elle trouve.'
        'hdr.dir' = '  dossier : {0}'
        'dry.uv.have' = 'uv                 déjà présent : {0}'
        'dry.uv.get' = 'uv                 sera téléchargé dans {0}'
        'dry.python' = 'Python 3.12        géré, dans {0} ; absent du PATH et du registre'
        'dry.app' = 'Nyshporka          {0}'
        'dry.preset' = 'profil {0}'
        'dry.app2' = '                   dans l''environnement isolé de l''outil uv'
        'dry.cmd' = 'commande nysh      {0}'
        'dry.trace' = 'trace installeur   {0}'
        'dry.space' = 'espace recherche   dossier indiqué par « nysh init »'
        'dry.eng1' = 'moteurs de lecture nysh htr install — torch pour carte NVIDIA si le pilote'
        'dry.eng2' = '                   en signale une, sinon pour le processeur (~2,5–4 Go, dans l''espace)'
        'dry.models' = 'modèles d''écriture nysh models get (~215 Mo, sha256 vérifié)'
        'dry.why.own' = 'les vôtres, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'moteurs de lecture non installés ({0})'
        'dry.cat.no' = 'catalogues         non installés (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'catalogues         depuis la dernière version catalog-* (sha256 vérifié), si absents'
        'dry.path.no' = 'PATH utilisateur   inchangé (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'PATH utilisateur   une seule entrée « {0} », si le dossier n''y est pas encore'
        'dry.done' = 'Rien n''a été fait — c''est -DryRun.'
        'admin.1' = '  ⚠ Exécution en administrateur. Tout ira dans le profil de l''utilisateur'
        'admin.3' = '    Si un autre utilisateur travaille ici, il n''aura ni la commande nysh ni'
        'admin.4' = '    les raccourcis ; installez depuis son propre compte.'
        'preflight' = 'Contrôle préalable : les programmes du profil utilisateur ({0}) NE S''EXÉCUTENT PAS sur cette machine — on dirait une stratégie AppLocker/SRP ou une règle ASR. Nyshporka s''installe dans le profil sans droits d''administrateur, elle ne fonctionnera donc pas ici. Options : lancer l''installeur par clic droit → « Exécuter en tant qu''administrateur » (tout ira alors dans le profil de l''administrateur), ou demander au service informatique d''autoriser l''exécution depuis {0} et {1}.'
        'uv.have' = '✓ uv déjà présent : {0}'
        'err.uv' = 'uv ne s''est pas installé dans {0}'
        'err.python' = 'impossible d''installer Python 3.12 (uv a renvoyé {0})'
        'app.get' = '⬇ Nyshporka ({0})…'
        'err.app' = 'impossible d''installer {0} (uv a renvoyé {1})'
        'app.ok' = '✓ Nyshporka'
        'nocmd.1' = '✗ le paquet est installé, mais la commande est introuvable : {0}'
        'nocmd.2' = '  envoyez-nous, s''il vous plaît, la sortie de `uv tool list` — c''est un défaut'
        'nocmd.3' = '  de l''installeur, pas de votre machine'
        'err.nocmd' = 'nysh introuvable après l''installation'
        'info.fail' = '⚠ impossible d''écrire {0} — il faudra créer les raccourcis à la main'
        'err.init' = 'impossible de créer l''espace de travail (nysh a renvoyé {0})'
        'eng.get' = '⬇ moteurs de lecture (torch pour votre carte, ~2,5–4 Go — quelques minutes)…'
        'eng.fail' = '⚠ les moteurs de lecture n''ont pas été construits (nysh a renvoyé {0}) — relancer : nysh htr install'
        'models.get' = '⬇ modèles d''écriture…'
        'models.fail' = '⚠ les modèles d''écriture n''ont pas été téléchargés (nysh a renvoyé {0}) — relancer : nysh models get'
        'eng.err' = '⚠ les moteurs de lecture n''ont pas été livrés : {0}'
        'eng.retry' = '  relancer : nysh htr install, puis nysh models get'
        'eng.foreign' = 'ℹ les moteurs de lecture sont indiqués par NYSHPORKA_HTR_VENV — je n''y touche pas : {0}'
        'eng.ok' = '✓ moteurs de lecture et modèles d''écriture'
        'cat.list' = '⚠ impossible de lire la liste des versions GitHub — réseau ou limite d''API'
        'cat.none' = '⚠ aucune version catalog-* trouvée'
        'cat.nosum' = '⚠ version {0} : fichier sans somme de contrôle sha256 — téléchargement sans vérification impossible'
        'cat.nourl' = '⚠ version {0} : lien de téléchargement introuvable'
        'cat.dl' = '⚠ impossible de télécharger le pack de catalogues ({0})'
        'cat.sum' = '⚠ la somme de contrôle du pack de catalogues ({0}) ne correspond pas — pas d''installation'
        'cat.ok' = '✓ pack de catalogues {0} : installé (sha256 vérifié)'
        'cat.refused' = '⚠ « nysh catalog install » a refusé le pack {0}'
        'cat.err' = '⚠ le pack de catalogues de la version n''a pas été installé : {0}'
        'cat.skip' = 'ℹ catalogues non installés (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ pas de catalogues à proximité — la recherche dans les catalogues d''archives sera indisponible'
        'cat.take' = '  à prendre : {0}'
        'cat.next' = '  ensuite :  nysh catalog install --from <zip téléchargé>'
        'desk.ok' = '✓ raccourci sur le bureau'
        'trace.fail' = '⚠ impossible d''écrire {0} — « nysh uninstall » demandera les chemins'
        'sum.title' = 'Modifié sur cette machine :'
        'sum.dir' = '  dossier     {0}'
        'sum.bin' = '  commande    {0}'
        'sum.file' = '  fichier     {0}'
        'sum.path' = '  PATH        entrée « {0} » dans les variables d''environnement de l''utilisateur'
        'sum.space' = '  espace de recherche — le dossier que « nysh init » vient d''indiquer'
        'sum.undo' = '  tout annuler : nysh uninstall'
        'done' = 'Terminé.'
        'reopen.1' = '  ⚠ Fermez cette fenêtre et ouvrez-en une nouvelle — les commandes ci-dessous y fonctionnent.'
        'reopen.2' = '    Dans les fenêtres ouvertes avant l''installation, « nysh » restera introuvable.'
        'reopen.3' = '    Si c''est encore le cas dans la nouvelle, redémarrez l''ordinateur.'
        'next' = 'Ensuite :'
        'next.serve' = '  nysh serve            ouvrir l''application dans le navigateur'
        'next.look' = '  nysh look <dossier>   voir de quels scans il s''agit'
        'next.htr' = '  nysh htr install      construire les moteurs de lecture (torch pour votre carte)'
        'next.models' = '  nysh models get       télécharger les modèles d''écriture'
        'next.doctor' = '  nysh doctor           vérifier ce qui casse en silence'
        'trap.error' = 'Erreur : {0}'
        'trap.line' = '   (ligne {0} de l''installeur)'
        'trap.tail' = 'Dernières lignes de la sortie :'
        'trap.log' = 'Journal complet : {0}'
        'trap.title' = 'Nyshporka : l''installation ne s''est pas terminée'
        'brand.name' = 'Nyshporka'
        'lnk.desc' = 'Lecture de dossiers d''archives manuscrits'
        'err.448' = 'Windows ne fait pas confiance au dossier où uv installe Python (os error 448 : AppData ou OneDrive redirigé). Réinstallez Nyshporka avec le dossier des interpréteurs hors du profil : windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    de = @{
        'brand.tag' = 'Liest Handschriften. Bringt mit, was sie findet.'
        'hdr.dir' = '  Ordner: {0}'
        'dry.uv.have' = 'uv                 schon vorhanden: {0}'
        'dry.uv.get' = 'uv                 wird nach {0} heruntergeladen'
        'dry.python' = 'Python 3.12        verwaltet, in {0}; weder in PATH noch in der Registrierung'
        'dry.app' = 'Nyshporka          {0}'
        'dry.preset' = 'Set {0}'
        'dry.app2' = '                   in der isolierten Umgebung des Tools uv'
        'dry.cmd' = 'Befehl nysh        {0}'
        'dry.trace' = 'Installer-Spur     {0}'
        'dry.space' = 'Forschungsraum     Ordner, den „nysh init“ nennt'
        'dry.eng1' = 'Leseengines        nysh htr install — torch für NVIDIA-Grafikkarte, wenn der Treiber'
        'dry.eng2' = '                   eine meldet, sonst für den Prozessor (~2,5–4 GB, im Raum-Ordner)'
        'dry.models' = 'Schriftmodelle     nysh models get (~215 MB, sha256 wird geprüft)'
        'dry.why.own' = 'eigene, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'Leseengines        werden nicht installiert ({0})'
        'dry.cat.no' = 'Kataloge           werden nicht installiert (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'Kataloge           aus dem letzten Release catalog-* (sha256 geprüft), falls nicht vorhanden'
        'dry.path.no' = 'Benutzer-PATH      bleibt unberührt (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'Benutzer-PATH      ein Eintrag „{0}“, falls der Ordner dort noch fehlt'
        'dry.done' = 'Es wurde nichts getan — das ist -DryRun.'
        'admin.1' = '  ⚠ Start mit Administratorrechten. Alles landet im Benutzerprofil'
        'admin.3' = '    Wenn jemand anderes hier arbeitet, bekommt er weder den Befehl nysh noch'
        'admin.4' = '    die Verknüpfungen; installieren Sie unter seinem Konto.'
        'preflight' = 'Vorabprüfung: Programme aus dem Benutzerprofil ({0}) LASSEN SICH auf diesem Rechner NICHT STARTEN — vermutlich eine AppLocker/SRP-Richtlinie oder eine ASR-Regel. Nyshporka wird ohne Administratorrechte ins Profil installiert und würde hier nicht laufen. Möglichkeiten: den Installer per Rechtsklick → „Als Administrator ausführen“ starten (dann landet alles im Profil des Administrators) oder die IT bitten, das Ausführen aus {0} und {1} zu erlauben.'
        'uv.have' = '✓ uv schon vorhanden: {0}'
        'err.uv' = 'uv wurde nicht nach {0} installiert'
        'err.python' = 'Python 3.12 konnte nicht installiert werden (uv gab {0} zurück)'
        'app.get' = '⬇ Nyshporka ({0})…'
        'err.app' = '{0} konnte nicht installiert werden (uv gab {1} zurück)'
        'app.ok' = '✓ Nyshporka'
        'nocmd.1' = '✗ Paket installiert, aber der Befehl fehlt: {0}'
        'nocmd.2' = '  bitte senden Sie die Ausgabe von `uv tool list` — das ist ein Fehler des Installers,'
        'nocmd.3' = '  nicht Ihres Rechners'
        'err.nocmd' = 'nysh nach der Installation nicht gefunden'
        'info.fail' = '⚠ {0} konnte nicht geschrieben werden — Verknüpfungen müssen von Hand angelegt werden'
        'err.init' = 'Arbeitsbereich konnte nicht angelegt werden (nysh gab {0} zurück)'
        'eng.get' = '⬇ Leseengines (torch für Ihre Karte, ~2,5–4 GB — einige Minuten)…'
        'eng.fail' = '⚠ Leseengines wurden nicht gebaut (nysh gab {0} zurück) — erneut: nysh htr install'
        'models.get' = '⬇ Schriftmodelle…'
        'models.fail' = '⚠ Schriftmodelle wurden nicht geladen (nysh gab {0} zurück) — erneut: nysh models get'
        'eng.err' = '⚠ Leseengines wurden nicht bereitgestellt: {0}'
        'eng.retry' = '  erneut: nysh htr install, danach nysh models get'
        'eng.foreign' = 'ℹ Leseengines sind per NYSHPORKA_HTR_VENV festgelegt — ich fasse sie nicht an: {0}'
        'eng.ok' = '✓ Leseengines und Schriftmodelle'
        'cat.list' = '⚠ GitHub-Release-Liste konnte nicht gelesen werden — Netzwerk oder API-Limit'
        'cat.none' = '⚠ kein Release catalog-* gefunden'
        'cat.nosum' = '⚠ Release {0}: Datei ohne sha256-Prüfsumme — Download ohne Prüfung nicht erlaubt'
        'cat.nourl' = '⚠ Release {0}: Download-Link nicht gefunden'
        'cat.dl' = '⚠ Katalogpaket konnte nicht heruntergeladen werden ({0})'
        'cat.sum' = '⚠ Prüfsumme des Katalogpakets ({0}) stimmt nicht — keine Installation'
        'cat.ok' = '✓ Katalogpaket {0}: installiert (sha256 geprüft)'
        'cat.refused' = '⚠ „nysh catalog install“ hat das Paket {0} abgelehnt'
        'cat.err' = '⚠ Katalogpaket aus dem Release wurde nicht installiert: {0}'
        'cat.skip' = 'ℹ Kataloge werden nicht installiert (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ keine Kataloge in der Nähe — die Suche in den Archivkatalogen ist nicht verfügbar'
        'cat.take' = '  holen: {0}'
        'cat.next' = '  danach:  nysh catalog install --from <heruntergeladene zip>'
        'desk.ok' = '✓ Desktop-Verknüpfung'
        'trace.fail' = '⚠ {0} konnte nicht geschrieben werden — „nysh uninstall“ fragt dann nach den Pfaden'
        'sum.title' = 'Auf diesem Rechner geändert:'
        'sum.dir' = '  Ordner      {0}'
        'sum.bin' = '  Befehl      {0}'
        'sum.file' = '  Datei       {0}'
        'sum.path' = '  PATH        Eintrag „{0}“ in den Umgebungsvariablen des Benutzers'
        'sum.space' = '  Forschungsraum — der Ordner, den „nysh init“ eben genannt hat'
        'sum.undo' = '  alles rückgängig machen: nysh uninstall'
        'done' = 'Fertig.'
        'reopen.1' = '  ⚠ Schließen Sie dieses Fenster und öffnen Sie ein neues — die Befehle unten funktionieren dort.'
        'reopen.2' = '    In Fenstern, die vor der Installation geöffnet wurden, wird „nysh“ nicht gefunden.'
        'reopen.3' = '    Wird es auch im neuen nicht gefunden, starten Sie den Computer neu.'
        'next' = 'Weiter:'
        'next.serve' = '  nysh serve            die App im Browser öffnen'
        'next.look' = '  nysh look <Ordner>    ansehen, was das für Scans sind'
        'next.htr' = '  nysh htr install      Leseengines bauen (torch für Ihre Karte)'
        'next.models' = '  nysh models get       Schriftmodelle herunterladen'
        'next.doctor' = '  nysh doctor           prüfen, was still kaputtgeht'
        'trap.error' = 'Fehler: {0}'
        'trap.line' = '   (Zeile {0} des Installers)'
        'trap.tail' = 'Letzte Ausgabezeilen:'
        'trap.log' = 'Vollständiges Protokoll: {0}'
        'trap.title' = 'Nyshporka: Installation nicht abgeschlossen'
        'brand.name' = 'Nyshporka'
        'lnk.desc' = 'Lesen handschriftlicher Archivakten'
        'err.448' = 'Windows vertraut dem Ordner nicht, in den uv Python installiert (os error 448: umgeleitetes AppData oder OneDrive). Installieren Sie Nyshporka neu, mit dem Interpreter-Ordner außerhalb des Profils: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
    ru = @{
        'brand.tag' = 'Читает рукописи. Приносит найденное.'
        'hdr.dir' = '  папка: {0}'
        'dry.uv.have' = 'uv                 уже есть: {0}'
        'dry.uv.get' = 'uv                 будет скачан в {0}'
        'dry.python' = 'Python 3.12        управляемый, в {0}; ни в PATH, ни в реестре его не будет'
        'dry.app' = 'Нышпорка           {0}'
        'dry.preset' = 'набор {0}'
        'dry.app2' = '                   в изолированной среде инструмента uv'
        'dry.cmd' = 'команда nysh       {0}'
        'dry.trace' = 'след установщика   {0}'
        'dry.space' = 'папка исследований папка, которую назовёт «nysh init»'
        'dry.eng1' = 'движки чтения      nysh htr install — torch под видеокарту NVIDIA, если драйвер её'
        'dry.eng2' = '                   показывает, иначе под процессор (~2.5–4 ГБ, в папке пространства)'
        'dry.models' = 'модели письма      nysh models get (~215 МБ, sha256 сверяется)'
        'dry.why.own' = 'свои, NYSHPORKA_HTR_VENV={0}'
        'dry.eng.no' = 'движки чтения      не ставятся ({0})'
        'dry.cat.no' = 'справочники        не ставятся (-NoCatalog / NYSH_NO_CATALOG=1)'
        'dry.cat' = 'справочники        из последнего релиза catalog-* (сверка sha256), если рядом нет'
        'dry.path.no' = 'PATH пользователя  не трогается (NYSH_NO_MODIFY_PATH=1)'
        'dry.path' = 'PATH пользователя  одна запись «{0}», если папки там ещё нет'
        'dry.done' = 'Ничего не сделано — это -DryRun.'
        'admin.1' = '  ⚠ Запуск с правами администратора. Всё встанет в профиль пользователя'
        'admin.3' = '    Если работать будет другой пользователь, ему команда nysh и ярлыки'
        'admin.4' = '    не достанутся; устанавливайте из-под его учётной записи.'
        'preflight' = 'Предпроверка: программы из профиля пользователя ({0}) на этом компьютере НЕ ЗАПУСКАЮТСЯ — похоже на политику AppLocker/SRP или правило ASR. Нышпорка ставится в профиль без прав администратора, поэтому здесь она работать не будет. Варианты: запустить установщик правой кнопкой мыши → «Запуск от имени администратора» (тогда всё встанет в профиль администратора) или попросить ИТ разрешить запуск из {0} и {1}.'
        'uv.have' = '✓ uv уже есть: {0}'
        'err.uv' = 'uv не установился в {0}'
        'err.python' = 'не удалось установить Python 3.12 (uv вернул {0})'
        'app.get' = '⬇ Нышпорка ({0})…'
        'err.app' = 'не удалось установить {0} (uv вернул {1})'
        'app.ok' = '✓ Нышпорка'
        'nocmd.1' = '✗ пакет установлен, но команды нет: {0}'
        'nocmd.2' = '  пришлите, пожалуйста, вывод `uv tool list` — это ошибка установщика,'
        'nocmd.3' = '  а не вашего компьютера'
        'err.nocmd' = 'nysh не найден после установки'
        'info.fail' = '⚠ не удалось записать {0} — ярлыки придётся создать вручную'
        'err.init' = 'не удалось создать рабочее пространство (nysh вернул {0})'
        'eng.get' = '⬇ движки чтения (torch под вашу карту, ~2.5–4 ГБ — несколько минут)…'
        'eng.fail' = '⚠ движки чтения не собрались (nysh вернул {0}) — повторить: nysh htr install'
        'models.get' = '⬇ модели письма…'
        'models.fail' = '⚠ модели письма не загрузились (nysh вернул {0}) — повторить: nysh models get'
        'eng.err' = '⚠ движки чтения не доставлены: {0}'
        'eng.retry' = '  повторить: nysh htr install, затем nysh models get'
        'eng.foreign' = 'ℹ движки чтения заданы переменной NYSHPORKA_HTR_VENV — не трогаю: {0}'
        'eng.ok' = '✓ движки чтения и модели письма'
        'cat.list' = '⚠ не удалось прочитать список релизов GitHub — сеть или лимит API'
        'cat.none' = '⚠ ни одного релиза catalog-* не найдено'
        'cat.nosum' = '⚠ релиз {0}: файл без контрольной суммы sha256 — скачивать без сверки нельзя'
        'cat.nourl' = '⚠ релиз {0}: не найдена ссылка для скачивания'
        'cat.dl' = '⚠ не удалось скачать пакет справочников ({0})'
        'cat.sum' = '⚠ контрольная сумма пакета справочников ({0}) не совпала — не устанавливаю'
        'cat.ok' = '✓ пакет справочников {0}: установлен (sha256 сверен)'
        'cat.refused' = '⚠ «nysh catalog install» отклонил пакет {0}'
        'cat.err' = '⚠ пакет справочников из релиза не установлен: {0}'
        'cat.skip' = 'ℹ справочники не ставятся (-NoCatalog / NYSH_NO_CATALOG=1)'
        'cat.missing' = '⚠ справочников рядом нет — поиск по каталогам архивов будет недоступен'
        'cat.take' = '  взять: {0}'
        'cat.next' = '  далее:  nysh catalog install --from <скачанный zip>'
        'desk.ok' = '✓ ярлык на рабочем столе'
        'trace.fail' = '⚠ не удалось записать {0} — «nysh uninstall» будет спрашивать пути'
        'sum.title' = 'Изменено на этом компьютере:'
        'sum.dir' = '  папка       {0}'
        'sum.bin' = '  команда     {0}'
        'sum.file' = '  файл        {0}'
        'sum.path' = '  PATH        запись «{0}» в переменных среды пользователя'
        'sum.space' = '  папка исследований — папка, которую только что назвал «nysh init»'
        'sum.undo' = '  отменить всё это: nysh uninstall'
        'done' = 'Готово.'
        'reopen.1' = '  ⚠ Закройте это окно и откройте новое — команды ниже работают там.'
        'reopen.2' = '    В окнах, открытых до установки, «nysh» не найдётся.'
        'reopen.3' = '    Если и в новом не найдётся — перезагрузите компьютер.'
        'next' = 'Дальше:'
        'next.serve' = '  nysh serve            открыть приложение в браузере'
        'next.look' = '  nysh look <папка>     посмотреть, что за сканы'
        'next.htr' = '  nysh htr install      собрать движки чтения (torch под вашу карту)'
        'next.models' = '  nysh models get       скачать модели письма'
        'next.doctor' = '  nysh doctor           проверить то, что ломается тихо'
        'trap.error' = 'Ошибка: {0}'
        'trap.line' = '   (строка {0} установщика)'
        'trap.tail' = 'Последние строки вывода:'
        'trap.log' = 'Полный журнал: {0}'
        'trap.title' = 'Нышпорка: установка не завершилась'
        'brand.name' = 'Нышпорка'
        'lnk.desc' = 'Чтение рукописных архивных дел'
        'err.448' = 'Windows не доверяет папке, куда uv ставит Python (os error 448: перенаправленный AppData или OneDrive). Установите Нышпорку заново с папкой интерпретаторов вне профиля: windows.ps1 -PythonDir D:\Nyshporka\python'
    }
}

# Повідомлення поточною мовою; якщо ключа бракує — українською.
function M {
    param([Parameter(Mandatory)][string] $Key,
          [Parameter(ValueFromRemainingArguments)] [object[]] $Rest)
    $text = $Msg[$Lang][$Key]
    if (-not $text) { $text = $Msg['uk'][$Key] }
    if ($Rest) { $text -f $Rest } else { $text }
}

# Звідки брати пак довідників, якщо його немає поруч. Та сама адреса, що її
# друкує `nysh catalog list` на порожньому каталозі (`catalog.store.RELEASES_URL`).
$CatalogUrl = 'https://github.com/SERGIUSH-UA/nyshporka/releases'
# Той самий пак, але звідки його бере САМ інсталятор: перелік релізів API.
# `per_page=100` — розмір СТОРІНКИ, не стеля пошуку: `catalog-*` виходить
# рідко, звичайні релізи — щотижня, тож він з часом зсувається за першу сотню.
$CatalogApi = 'https://api.github.com/repos/SERGIUSH-UA/nyshporka/releases?per_page=100'
if ($env:NYSH_NO_CATALOG -eq '1') { $NoCatalog = [switch]$true }
if (-not $PythonDir) { $PythonDir = Join-Path $Home_ 'python' }
# Дослівно той самий текст, що `UNTRUSTED_MOUNT_HINT` у `setup/update.py`:
# інсталятор і `nysh htr install` при 448 радять одне.
$Untrusted448 = 'Windows не довіряє теці, куди uv ставить Python (os error 448: перенаправлений AppData чи OneDrive). Поставте Нишпорку наново з текою інтерпретаторів поза профілем: windows.ps1 -PythonDir D:\Nyshporka\python'
if ($Lang -ne 'uk') { $Untrusted448 = M 'err.448' }

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── слід відмови ─────────────────────────────────────────────────────────────
# 🔴 Текст помилки мусить пережити консоль. Майстер `.exe` запускає цей скрипт
# у власному вікні PowerShell, і те вікно закривається разом зі скриптом — а
# майстер показував лише «код 1» і радив читати вікно, якого вже немає (звіт
# користувача 06.09.2026). Тому будь-яка відмова: (1) лягає у `install.log`
# разом з усім виводом, (2) коротко — в `install-error.txt`, який майстер
# вставляє у своє повідомлення, (3) під майстром ще й показується вікном.
$LogFile   = Join-Path $Home_ 'install.log'
$ErrorFile = Join-Path $Home_ 'install-error.txt'
Remove-Item -LiteralPath $ErrorFile -Force -ErrorAction SilentlyContinue

trap {
    $failure = $_
    $lines = @((M 'trap.error' $failure.Exception.Message))
    if ($failure.InvocationInfo -and $failure.InvocationInfo.ScriptLineNumber) {
        $lines += (M 'trap.line' $failure.InvocationInfo.ScriptLineNumber)
    }
    try { Stop-Transcript | Out-Null } catch {}
    # Справжня причина — те, що написав uv або nysh перед «не вдалося». Береться
    # з буфера `Invoke-Logged`; транскрипт тут не годиться — він не бачить
    # виводу exe в консоль, а його заголовок з'їв би весь хвіст.
    $tail = @($script:NativeTail | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 15)
    if ($tail.Count) { $lines += ''; $lines += (M 'trap.tail'); $lines += $tail }
    if ($script:PreflightNote) { $lines += ''; $lines += $script:PreflightNote }
    $lines += ''
    $lines += (M 'trap.log' $LogFile)
    $text = $lines -join [Environment]::NewLine
    Write-Host ''
    Write-Host $text -ForegroundColor Red
    # ⚠ Кодування ANSI навмисно: майстер читає файл як AnsiString і переводить у
    # Unicode системною кодовою сторінкою — саме тією, якою .NET тут пише.
    try { [IO.File]::WriteAllText($ErrorFile, $text, [Text.Encoding]::Default) } catch {}
    if ($Wizard) {
        try {
            (New-Object -ComObject WScript.Shell).Popup(
                $text, 0, (M 'trap.title'), 16) | Out-Null
        } catch {}
    }
    exit 1
}

# Extras під обраний набір. Явно заданий -Source перебиває: хто вписав склад
# руками, знає, чого хоче.
# ⚠ Перелік дублює `core.sections.EXTRAS` — інакше інсталятор мусив би спершу
# поставити пакет, щоб спитати в нього, що ставити. Розбіжність ловить
# `test_installer_extras_match_the_sections`.
$ExtrasByPreset = @{ catalog = 'nyshporka[app,archives]'
                     lab     = 'nyshporka[app,archives,htr,train]' }
if (-not $Source) {
    $Source = if ($ExtrasByPreset[$Preset]) { $ExtrasByPreset[$Preset] }
              else { 'nyshporka[app,archives,htr]' }
    # ⚠ Пін чіпляється ЛИШЕ до обчисленого складу. Хто задав `-Source` руками,
    # уже сказав, що саме ставить — дописати туди `==` означало б зіпсувати
    # його специфікацію, а то й видати `nyshporka[app]==1.0==0.6.2`.
    if ($Version) { $Source = "$Source==$Version" }
}

function Say($text, $colour = 'White') { Write-Host $text -ForegroundColor $colour }

# Рушії читання потрібні кожному набору з розділом «Читання» (`core.sections`:
# усі, крім `catalog`).
$WantEngines = (-not $NoEngines) -and ($Preset -ne 'catalog')
# 🔴 Середовище рушіїв, вказане змінною, — чуже: людина зібрала його сама й
# могла тримати там свій torch. `nysh htr install` доставив би туди бракуюче й
# переставив би CPU-torch на CUDA, тож інсталятор його не чіпає взагалі.
$EnginesForeign = [bool]$env:NYSHPORKA_HTR_VENV
if ($EnginesForeign) { $WantEngines = $false }

# Слід, який лишається на машині. Накопичується ПО ХОДУ, а не вгадується
# потім: тека інструментів налаштовується (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`),
# і здогад про типове місце збігається лише з типовим випадком. З цього
# переліку `nysh uninstall` знімає РІВНО поставлене.
$Trace = New-Object System.Collections.ArrayList
function Trace($kind, $path) { $null = $Trace.Add("$kind $path") }

# 🔴 Рідну команду НЕ можна глушити через `2>&1` чи `2>$null`.
# Windows PowerShell 5.1 обгортає КОЖЕН рядок, який exe написав у stderr, у
# ErrorRecord `NativeCommandError` — байдуже, що там звичайне інформаційне
# повідомлення, — а `$ErrorActionPreference = 'Stop'` вище робить той
# ErrorRecord ТЕРМІНАЛЬНИМ. Інсталятор помирав рівно на цьому:
# `uv tool update-shell` друкує «Updated PATH to include executable
# directory …» у stderr, і повідомлення про УСПІХ обривало установлення перед
# `nysh init`, `doctor` і ярликом (звіт користувача 28.08.2026 — червона стіна
# там, де насправді все завантажилось).
# ⚠ `2>$null` не рятує: гасне ВИВІД, а не ErrorRecord. Рятує лише тимчасово
# послаблена преференція — тому перенаправлення живе тільки тут.
function Invoke-Muted {
    param([Parameter(Mandatory)][string] $Exe,
          [Parameter(ValueFromRemainingArguments)] [object[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try     { & $Exe @Arguments 2>&1 | Out-Null }
    finally { $ErrorActionPreference = $prev }
}

# 🔴 Рідна команда, чий вивід мусить ДІЙТИ до повідомлення про помилку.
# Транскрипт PowerShell не бачить того, що exe пише прямо в консоль (перевірено
# на 5.1: у `install.log` після «⬇ Нишпорка…» ішов одразу кінець транскрипту,
# а причина від uv лишалась у вікні, яке зникло). Тому обидва потоки йдуть
# через `Write-Host` — його транскрипт бачить — і в буфер, з якого trap бере
# останні рядки. Код виходу повертається значенням: `$LASTEXITCODE` читається
# тут же, у тій самій області, де його виставила команда.
$script:NativeTail = New-Object System.Collections.Generic.List[string]
function Invoke-Logged {
    param([Parameter(Mandatory)][string] $Exe,
          [Parameter(ValueFromRemainingArguments)] [object[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            Write-Host $line
            $script:NativeTail.Add($line)
        }
        return $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
}

# 🔴 `uv python install` падає на ОСТАННЬОМУ кроці — junction мінорної версії
# (`cpython-3.12-…` → `cpython-3.12.15-…`), коли інтерпретатор уже розпакований.
# 15.10.2026: os error 448 повторилась і в `{app}\python`, тобто тека тут ні до
# чого — Windows не дає робити junction узагалі. Junction потрібен uv лише для
# тихих патч-оновлень, тож беремо `python.exe` точної версії напряму, якщо він
# є й запускається. `$null` — це справжня відмова (завантаження тощо).
# Те саме робить пакет (`setup/update.py: ensure_python`) для venv рушіїв.
function Resolve-ExtractedPython([string] $Tail, [string] $Dir, [string] $Version) {
    if ($Tail -notmatch 'Failed to create Python minor version link directory|Missing expected target directory for Python minor version link') { return $null }
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { return $null }
    $pat = '^cpython-' + [regex]::Escape($Version) + '\.(\d+)-windows-[^-]+-none$'
    $best = Get-ChildItem -LiteralPath $Dir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match $pat -and (Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe')) } |
        Sort-Object { [int]([regex]::Match($_.Name, $pat).Groups[1].Value) } -Descending |
        Select-Object -First 1
    if (-not $best) { return $null }
    $exe = Join-Path $best.FullName 'python.exe'
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $got = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { $got = $null }
    finally { $ErrorActionPreference = $prev }
    if ("$got".Trim() -ne $Version) { return $null }
    # Недоробок junction — лише сам junction чи порожня тека: Directory.Delete
    # без рекурсії не йде за junction і не знімає теку з вмістом.
    Get-ChildItem -LiteralPath $Dir -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match ('^cpython-' + [regex]::Escape($Version) + '-windows-[^-]+-none$') } |
        ForEach-Object { try { [IO.Directory]::Delete($_.FullName, $false) } catch {} }
    return $exe
}

# Останній рядок stdout рідної команди; stderr і будь-яка відмова — у тишу.
# Для запитань на кшталт «а куди ти кладеш команди»: відповідь або є, або
# лишається порожньою, і викликач бере запасний варіант.
function Get-NativeLine {
    param([Parameter(Mandatory)][string] $Exe,
          [Parameter(ValueFromRemainingArguments)] [object[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try     { $out = & $Exe @Arguments 2>$null } catch { $out = $null }
    finally { $ErrorActionPreference = $prev }
    if ($out) { ($out | Select-Object -Last 1).ToString().Trim() } else { '' }
}

# 🔴 Вивід у UTF-8. Без цього кирилиця в консолі перетворюється на кракозябри:
# Windows PowerShell 5.1 бере кодування консолі з системної кодової сторінки, а
# саме на цій поверхні людина читає перше, що каже їй застосунок.
# ⚠ Сам ФАЙЛ мусить лежати з BOM — інакше 5.1 читає його як ANSI, і мова
# ламається ще до першого рядка виводу. Приймач — `test_installer_is_utf8_bom`.
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch {}
# 🔴 І те саме кодування — з того боку пайпа. `Invoke-Logged` читає вивід
# `nysh` як UTF-8 (рядок вище), а Python під пайпом пише в ANSI-сторінці
# системи: кирилиця приходила кракозябрами, а `✅` у cp1251 немає зовсім —
# `nysh init` падав `UnicodeEncodeError` на повідомленні про успіх (звіт
# користувача 20.09.2026). Змінна живе лише в цьому процесі й дочірніх.
$env:PYTHONIOENCODING = 'utf-8'

# 🐾 Знак ТОЙ САМИЙ, що друкує `nysh info` і старт застосунку — побайтово,
# і це звіряє тест. Інсталятор — найперша поверхня, яку бачить людина, і
# власна лапка тут означала б, що бренд розходиться з першого ж екрана.
Say "  ● ● ● ●" DarkYellow
Say ("  ╭─ ◍ ─╮   " + (M 'brand.name')) DarkYellow
Say ("  ╰─────╯   " + (M 'brand.tag')) DarkGray
Say ""
Say (M 'hdr.dir' $Home_) DarkGray

if ($DryRun) {
    $uvNow = (Get-Command uv -ErrorAction SilentlyContinue).Source
    $binGuess = if ($uvNow) { Get-NativeLine $uvNow tool dir --bin } else { $null }
    if (-not $binGuess) { $binGuess = Join-Path $env:USERPROFILE '.local\bin' }
    Say ""
    if ($uvNow) { Say (M 'dry.uv.have' $uvNow) }
    else         { Say (M 'dry.uv.get' (Join-Path $Home_ 'uv')) }
    Say (M 'dry.python' $PythonDir)
    Say (M 'dry.app' $(if ($Source) { $Source } else { M 'dry.preset' $Preset }))
    Say (M 'dry.app2')
    Say (M 'dry.cmd' (Join-Path $binGuess 'nysh.exe'))
    Say (M 'dry.trace' (Join-Path $Home_ 'install-info.ini'))
    Say "                   $(Join-Path $Home_ 'install-trace.txt')"
    Say (M 'dry.space')
    if ($WantEngines) {
        Say (M 'dry.eng1')
        Say (M 'dry.eng2')
        Say (M 'dry.models')
    } else {
        $why = if ($EnginesForeign) { M 'dry.why.own' $env:NYSHPORKA_HTR_VENV }
               elseif ($NoEngines) { '-NoEngines' } else { M 'dry.preset' $Preset }
        Say (M 'dry.eng.no' $why)
    }
    if ($NoCatalog) {
        Say (M 'dry.cat.no')
    } else {
        Say (M 'dry.cat')
    }
    if ($env:NYSH_NO_MODIFY_PATH -eq '1') {
        Say (M 'dry.path.no')
    } else {
        Say (M 'dry.path' $binGuess)
    }
    Say ""
    Say (M 'dry.done') Cyan
    exit 0
}

New-Item -ItemType Directory -Force -Path $Home_ | Out-Null
# Журнал усього виводу — і для хвоста в повідомленні про помилку, і для того,
# щоб людині було що надіслати в issue. Без транскрипту цей вивід живе рівно
# стільки, скільки вікно консолі.
try { Start-Transcript -LiteralPath $LogFile -Force | Out-Null } catch {}

# ── 0. передперевірка ────────────────────────────────────────────────────────
# 🔴 Звіт 06.09.2026: установлення падало з кодом 1 у звичайного користувача і
# проходило «від імені адміністратора». Жоден крок нижче прав не потребує —
# усе лягає в профіль, — тож різниця була або в ПОЛІТИЦІ ВИКОНАННЯ (AppLocker,
# SRP, правила ASR: адміністраторам усе, решті лише Program Files і Windows —
# і uv.exe з профілю просто не запускається), або в ІНШОМУ ПРОФІЛІ (інший
# обліковий запис = інші %LOCALAPPDATA%, %TEMP%, домівка). Обидва випадки
# дешево впізнати за секунду, до того як качати гігабайти, і назвати прямо.
$script:PreflightNote = ''

# Підвищення: усе ляже в профіль ЦЬОГО облікового запису. Якщо майстер
# запустили від імені іншого, адміністраторського, — команди `nysh`, PATH і
# ярлики дістануться йому, а не тому, хто працюватиме.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($elevated) {
    Say ""
    Say (M 'admin.1') Yellow
    Say "    $($identity.Name) ($env:USERPROFILE)." Yellow
    Say (M 'admin.3') DarkGray
    Say (M 'admin.4') DarkGray
}

# Чи запускаються програми з профілю взагалі. Проба — підписаний системний exe,
# скопійований у теку встановлення: правила за шляхом (типові для AppLocker і
# SRP) заблокують саме копію, а не оригінал. Відмова проби НЕ зупиняє
# встановлення (хибне спрацювання коштувало б людині всієї установки), а
# лишає пояснення, яке trap додасть до першої ж справжньої відмови.
# ⚠ Саме `cmd /c echo`, а не `where /?`: той пише довідку в stderr, і проба
# спрацьовувала хибно на цілком здоровій машині (перевірено 06.09.2026).
$probeSrc = Join-Path $env:SystemRoot 'System32\cmd.exe'
$probe = Join-Path $Home_ '_probe.exe'
if (Test-Path -LiteralPath $probeSrc) {
    try {
        Copy-Item -LiteralPath $probeSrc -Destination $probe -Force
        $seen = Get-NativeLine $probe /c echo nysh-probe-ok
        if ($seen -ne 'nysh-probe-ok') {
            $script:PreflightNote = M 'preflight' $Home_ "$env:LOCALAPPDATA\uv"
            Say ""
            Say "  ⚠ $($script:PreflightNote)" Yellow
        }
    } catch {
        # проба не вдалась сама по собі (антивірус, права на копіювання) — це
        # не вирок машині, мовчки йдемо далі
    } finally {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    }
}

$uvDir = Join-Path $Home_ 'uv'
$uv    = Join-Path $uvDir 'uv.exe'

# ── 1. uv ────────────────────────────────────────────────────────────────────
# Спершу дивимось, чи він уже є в системі: тягнути другий екземпляр заради
# 15 МБ немає сенсу, а два різні uv у PATH — джерело плутанини.
if (-not (Test-Path $uv)) {
    $existing = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if ($existing) {
        Say (M 'uv.have' $existing) Green
        $uv = $existing
    } else {
        Say "⬇ uv…" DarkGray
        New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
        $env:UV_INSTALL_DIR = $uvDir
        # 🔴 PATH користувача інсталятор uv не чіпає. Тека `$uvDir` наша, ми
        # кличемо uv повним шляхом, і запис у `HKCU\Environment` тут не дає
        # нічого, крім зайвої зміни в чужому середовищі. Та сама причина,
        # що й у `install/unix.sh`, де без цієї змінної інсталятор uv правив
        # шість файлів профілю одразу (скарга розробника 07.09.2026).
        $env:UV_NO_MODIFY_PATH = '1'
        # Офіційний інсталятор uv; ставить у вказану теку, без адміністратора.
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        # 🔴 І одразу прибираємо. Ця змінна слухається не лише інсталятором uv,
        # а й `uv tool update-shell` нижче — тобто, лишена в середовищі
        # процесу, вона мовчки скасовує ЄДИНИЙ допис у PATH, який нам потрібен.
        # Знайдено прогоном `install/unix.sh` у контейнері: установлення
        # проходило «успішно», а в новій оболонці команда не знаходилась.
        Remove-Item Env:UV_NO_MODIFY_PATH -ErrorAction SilentlyContinue
        if (-not (Test-Path $uv)) { throw (M 'err.uv' $uvDir) }
        Trace 'dir' $uvDir
        Say "✓ uv" Green
    }
}

# ── 2. інтерпретатор ─────────────────────────────────────────────────────────
Say "⬇ Python 3.12…" DarkGray
# 🔴 Дві змінні, і обидві — щоб керований інтерпретатор лишався деталлю
# Нишпорки, а не ставав системним Python 3.12 цієї машини.
# `UV_PYTHON_INSTALL_BIN=0` не кладе виконуваний `python3.12` у теку команд:
# на Unix такий файл ставав першим `python3.12` у PATH раніше за pyenv і
# conda, і за ним їхало все, що зібране під конкретний інтерпретатор
# (скарга розробника 07.09.2026). `UV_PYTHON_INSTALL_REGISTRY=0` не пише
# його в реєстр Windows (PEP 514) — інакше він з'являється в `py`-лаунчері
# та в списках інтерпретаторів чужих IDE, і людина обирає його не знаючи.
# ⚠ Змінними, а не прапорцями: гілка вище могла взяти ЧУЖИЙ uv, старіший за
# 0.8, і невідомий прапорець завалив би встановлення на другому кроці.
$env:UV_PYTHON_INSTALL_BIN = '0'
$env:UV_PYTHON_INSTALL_REGISTRY = '0'
# 🔴 Тека інтерпретаторів — наша, неромінгова (див. `-PythonDir`). Змінна
# процесу, а не постійна змінна користувача: постійна перенаправила б усі
# `uv python install` людини в теку Нишпорки, а `nysh uninstall` зносив би
# чужі інтерпретатори. Подальші виклики uv цього скрипта (`uv tool install`,
# `nysh htr install`) успадковують її звідси, а сама Нишпорка після
# встановлення бере теку з `python_dir=` в `install-info.ini`.
# ⚠ Гілка «uv уже є» могла взяти чужий uv будь-якої версії; змінна старша за
# junction мінорної версії, який і дає 448, тож uv, що його робить, її знає.
$env:UV_PYTHON_INSTALL_DIR = $PythonDir
$script:NativeTail.Clear()
$rc = Invoke-Logged $uv python install 3.12
# Що передавати в `--python` далі: версію, або — після збою junction — шлях.
$PythonArg = '3.12'
if ($rc -ne 0) {
    $tail = $script:NativeTail -join "`n"
    $exe = Resolve-ExtractedPython $tail $PythonDir '3.12'
    if ($exe) {
        Say "  python.exe → $exe" DarkGray
        $PythonArg = $exe
    } elseif ($tail -match 'os error 448') { throw $Untrusted448 }
    else { throw (M 'err.python' $rc) }
}
Say "✓ Python" Green

# ── 3. застосунок ────────────────────────────────────────────────────────────
# `uv tool install` кладе застосунок у власне ізольоване середовище й дає
# консольну команду. Це саме те, що треба: жодних конфліктів із чужими пакетами.
Say (M 'app.get' $Source) DarkGray
$script:NativeTail.Clear()
$rc = Invoke-Logged $uv tool install --python $PythonArg --force $Source
if ($rc -ne 0) {
    if (($script:NativeTail -join "`n") -match 'os error 448') { throw $Untrusted448 }
    throw (M 'err.app' $Source $rc)
}
Say (M 'app.ok') Green

# ── 3½. де команда й чи можна її набрати ─────────────────────────────────────
# 🔴 PATH тут лагодиться ДВІЧІ, і це дві РІЗНІ речі.
# `uv tool install` кладе `nysh.exe` у власну теку, і на чистій машині її в
# PATH немає. `uv tool update-shell` дописує теку в PATH КОРИСТУВАЧА — тобто
# у вікна, які відкриють ПІСЛЯ; поточне вікно про це не дізнається ніколи. А
# читає «Готово. Далі: nysh serve» і одразу це набирає людина саме в
# ПОТОЧНОМУ вікні — і отримує «nysh не розпізнано як імʼя командлета».
# Тому: теку питаємо в самого uv, дописуємо в PATH ПРОЦЕСУ (щоб працювало
# зараз) і кличемо `update-shell` (щоб працювало в наступних вікнах).
# ⚠ Теку саме питаємо, а не вгадуємо: вона налаштовується (`UV_TOOL_BIN_DIR`,
# `XDG_BIN_HOME`), і здогад `%USERPROFILE%\.local\bin` збігається лише з
# типовим випадком.
$binDir = Get-NativeLine $uv tool dir --bin
if (-not $binDir -or -not (Test-Path $binDir)) {
    $binDir = Join-Path $env:USERPROFILE '.local\bin'   # старий uv без `--bin`
}
$pathWasMissing = -not (($env:PATH -split ';' | Where-Object { $_ } |
                         ForEach-Object { $_.TrimEnd('\') }) -contains $binDir.TrimEnd('\'))
# 🔴 Запис у PATH КОРИСТУВАЧА — єдина зміна в чужому середовищі за все
# встановлення, тож у неї є вимикач і вона потрапляє у звіт. Хто веде PATH
# сам, ставить `NYSH_NO_MODIFY_PATH=1` і отримує рядок для вставки руками.
$keepPath = ($env:NYSH_NO_MODIFY_PATH -eq '1')
if ($pathWasMissing) {
    $env:PATH = "$binDir;$env:PATH"
    if (-not $keepPath) {
        # Знімок ДО й ПІСЛЯ — щоб звіт назвав зміну, якої справді не було
        # раніше: `update-shell` на вже дописаному PATH нічого не робить.
        $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
        Invoke-Muted $uv tool update-shell
        if ([Environment]::GetEnvironmentVariable('PATH', 'User') -ne $userPath) {
            Trace 'path' $binDir
        }
    }
}

$nysh = (Get-Command nysh -ErrorAction SilentlyContinue).Source
if (-not $nysh) { $nysh = Join-Path $binDir 'nysh.exe' }
# 🔴 Перевіряємо ПЕРЕД першим викликом. Інакше далі йде `& $nysh init` з
# вигаданим шляхом, і людина читає помилку про конвеєр замість того, що
# застосунок не знайшовся там, де мав лежати.
if (-not (Test-Path $nysh)) {
    Say ''
    Say (M 'nocmd.1' $nysh) Red
    Say (M 'nocmd.2') DarkGray
    Say (M 'nocmd.3') DarkGray
    throw (M 'err.nocmd')
}
Trace 'bin' $nysh

# ── 3¾. слід для майстра ─────────────────────────────────────────────────────
# 🪟 `.exe`-майстер (`install\nyshporka.iss`) кладе ярлики, а при деінсталяції
# знімає застосунок — і для обох дій мусить знати, КУДИ uv поклав команди. Сам
# він цього не з'ясує: `uv` у нього в PATH немає, а тека налаштовується
# (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`). Тому шлях лишає той, хто його щойно
# вирахував, — тут.
# ⚠ Кодування UTF-16LE навмисно: майстер читає файл через `GetPrivateProfileString`,
# а той розуміє Unicode лише за BOM UTF-16. Якщо в імені профілю є кирилиця,
# однобайтове кодування дало б шлях, якого не існує, — і ярлик мовчки вказував
# би в нікуди.
# ⚠ Файл службовий: без нього ламаються ярлики, а не сама Нишпорка. Тому
# помилка запису не валить встановлення.
$info = Join-Path $Home_ 'install-info.ini'
try {
    @('[nyshporka]', "nysh=$nysh", "uv=$uv", "preset=$Preset", "python_dir=$PythonDir") |
        Set-Content -LiteralPath $info -Encoding Unicode
} catch {
    Say (M 'info.fail' $info) Yellow
}
Trace 'file' $info

# ── 4. робочий простір ───────────────────────────────────────────────────────
# 🔴 Мовчки не створюємо: тека, що з'явилась сама, — це дослідження, яке потім
# не можуть знайти. `--yes` виправданий тим, що майстер бере шлях із
# драбини джерел (змінна · маркер · типове місце) і ДРУКУЄ, звідки він
# узявся, — тобто мовчазного вибору тут немає.
# ⚠ Не плутати з `$Home_` вище: то тека ВСТАНОВЛЕННЯ, а не простір.
Say ""
$rc = Invoke-Logged $nysh init --yes --preset $Preset
# 🔴 Простір мусить постати. Без нього застосунок не має де жити, і мовчазний
# провал тут дав би «встановлено» на порожньому місці.
if ($rc -ne 0) { throw (M 'err.init' $rc) }

# ── 4½. рушії читання й моделі письма ────────────────────────────────────────
# 🔴 Доти інсталятор лишав їх людині рядком «Далі: nysh models get», а torch під
# карту — команді `nysh htr install`, про яку треба було знати. Звіт у чаті
# 02.10.2026: людина з GTX 1050 Ti пішла в Docker, бо не знала, що нативна
# установка сама підбирає колесо під карту, — і вечір пішов на образ у 12 ГБ і
# сумісність Docker Desktop з драйвером. Тепер карту питає `nvidia-smi` тут же.
# 🔴 Жоден збій тут не валить установлення: застосунок уже стоїть, каталоги
# працюють, а рушії можна доставити пізніше тією самою командою. Тому все під
# try, відповідь — $true/$false, і функція не пише в конвеєр нічого іншого.
function Install-Engines {
    param([Parameter(Mandatory)][string] $Nysh)
    $ok = $true
    try {
        Say ""
        Say (M 'eng.get') DarkGray
        $rc = Invoke-Logged $Nysh htr install
        if ($rc -ne 0) {
            Say (M 'eng.fail' $rc) Yellow
            $ok = $false
        }
        # Ваги — незалежно від рушіїв: вони спільні на машину й знадобляться,
        # щойно рушії доставлять.
        Say (M 'models.get') DarkGray
        $rc = Invoke-Logged $Nysh models get
        if ($rc -ne 0) {
            Say (M 'models.fail' $rc) Yellow
            $ok = $false
        }
    } catch {
        Say (M 'eng.err' $_.Exception.Message) Yellow
        Say (M 'eng.retry') DarkGray
        $ok = $false
    }
    return $ok
}

$EnginesOk = $false
if ($EnginesForeign) {
    Say ""
    Say (M 'eng.foreign' $env:NYSHPORKA_HTR_VENV) DarkGray
}
if ($WantEngines) {
    $EnginesOk = Install-Engines -Nysh $nysh
    if ($EnginesOk) { Say (M 'eng.ok') Green }
}

# ⚠ А ось код виходу `doctor` навмисно НЕ перевіряється — рівно як `|| true` в
# `unix.sh`. Він віддає 1 на будь-якому `fail`, а `fail` — це, зокрема, «менше
# 5 ГБ вільного місця» (`setup/doctor.py`). Тобто на ноутбуці з повним диском
# цілком успішне встановлення виглядало б як провал — і саме в тієї аудиторії,
# що возить скани на зовнішніх дисках. Doctor тут світить лампочки, а не судить
# установлення.
$null = Invoke-Logged $nysh doctor

# ── 5. довідники ─────────────────────────────────────────────────────────────
# 🗂 Газетир і реєстри описів їдуть В КОМПЛЕКТІ — саме тому, що без них перше
# питання («де метрики мого села») лишається без відповіді, а людина не знає, що
# саме треба доставити. У КОЛЕСІ їх немає навмисно: каталог оновлюється, коли
# архів виклав новий опис, а код — коли полагодили ваду; це різні годинники, і
# `pip install --upgrade` заміщає дерево разом із тим, що користувач наклав.
# ⚠ `$PSScriptRoot` порожній, коли скрипт запустили віддалено (`irm | iex`):
# у пам'яті немає теки, «поруч» із якою можна щось шукати. Порожній `-Path`
# зараз мовчки не дає нічого, і поведінка виходить правильна — але випадково.
# Умова робить її навмисною й переживе будь-яку зміну в PowerShell.
#
# 🔴🔴 Пака поруч немає — беремо його з останнього релізу `catalog-РРРР-ММ-ДД`.
# Майстер `.exe` везе пак із собою, а запуск без клону (`irm … -OutFile`, як
# велить шапка) — ні, і `nysh find` по каталогах архівів мовчав би завжди.
# Той самий порядок, що в `unix.sh`: найновіший недрафтовий `catalog-*` з
# асетом `nyshporka-catalog-*.zip` → sha256 проти поля `digest`, яке рахує
# сам GitHub → `nysh catalog install --from`. Суми немає чи не збіглась — НЕ
# ставимо: обірваний файл виглядає як пак і навіть розпаковується, а вада
# вилазить аж нулем у пошуку, який ніхто не відрізнить від чесного.
# 🔴 Жоден збій тут не сміє звалити встановлення: каталог необов'язковий, а
# `$ErrorActionPreference = 'Stop'` зробив би будь-яку мережеву відмову
# термінальною — і trap показав би «установлення не завершилось» людині, в
# якої застосунок уже стоїть. Тому все під try, відповідь — $true/$false.
# ⚠ Функція не сміє нічого писати в конвеєр, крім відповіді: зайвий об'єкт
# перетворить `$false` на масив, а непорожній масив для `if` — істина.
function Install-CatalogFromRelease {
    param([Parameter(Mandatory)][string] $Nysh)
    # `GetTempPath()`, а не `$env:TEMP`: на Windows це та сама тека, а
    # приймач проганяє функцію й під pwsh на Linux, де `$env:TEMP` немає.
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('nysh-catalog-' + [guid]::NewGuid().ToString('N'))
    try {
        $releases = @()
        for ($page = 1; $page -le 10; $page++) {
            try {
                # ⚠ 5.1 віддає JSON-масив ОДНИМ об'єктом, а не елементами;
                # `ForEach-Object` розгортає його. 7.x розгортає сам — результат
                # той самий.
                $batch = @(Invoke-RestMethod -Uri "$CatalogApi&page=$page" `
                               -TimeoutSec 20 -UseBasicParsing | ForEach-Object { $_ })
            } catch {
                # Мережа впала не на першій сторінці — уже прочитане чесніше
                # за повну відмову: найновіший `catalog-*` може бути серед нього.
                if ($page -gt 1) { break }
                Say (M 'cat.list') Yellow
                return $false
            }
            if ($batch.Count -eq 0) { break }     # порожня сторінка — кінець списку
            $releases += $batch
        }
        # Дати ISO сортуються рядком правильно — порівняння рядків навмисне.
        $best = $releases |
            Where-Object { -not $_.draft -and "$($_.tag_name)" -match '^catalog-\d{4}-\d{2}-\d{2}$' } |
            ForEach-Object {
                $asset = @($_.assets) |
                    Where-Object { "$($_.name)" -like 'nyshporka-catalog-*.zip' } |
                    Select-Object -First 1
                if ($asset) { [pscustomobject]@{ Tag = "$($_.tag_name)"; Asset = $asset } }
            } |
            Sort-Object Tag -Descending | Select-Object -First 1
        if (-not $best) {
            Say (M 'cat.none') Yellow
            return $false
        }
        $tag = $best.Tag
        # `digest` — це `sha256:<64 hex>`; форма звіряється ДО завантаження,
        # щоб не тягнути мегабайти заради асета, який однаково не звірити.
        if (-not ("$($best.Asset.digest)" -match '^sha256:([0-9a-fA-F]{64})$')) {
            Say (M 'cat.nosum' $tag) Yellow
            return $false
        }
        $want = $Matches[1]
        $url = "$($best.Asset.browser_download_url)"
        if (-not $url) {
            Say (M 'cat.nourl' $tag) Yellow
            return $false
        }

        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        $zip = Join-Path $tmp 'pack.zip'
        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 120 -UseBasicParsing
        } catch {
            Say (M 'cat.dl' $tag) Yellow
            return $false
        }
        # ⚠ .NET, а не `Get-FileHash`: 5.1, запущений із вікна PowerShell 7,
        # успадковує його `PSModulePath`, бере чужий `Microsoft.PowerShell.Utility`
        # і `Get-FileHash` просто не знаходить (відтворено 18.09.2026).
        $sha = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($zip)
        try     { $got = [BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '' }
        finally { $stream.Dispose(); $sha.Dispose() }
        # `-ne` у PowerShell байдужий до регістру: .NET дає ВЕЛИКІ літери,
        # GitHub — малі.
        if ($got -ne $want) {
            Say (M 'cat.sum' $tag) Yellow
            return $false
        }
        $pack = Join-Path $tmp 'pack'
        Expand-Archive -LiteralPath $zip -DestinationPath $pack -Force
        $rc = Invoke-Logged $Nysh catalog install --from $pack
        if ($rc -eq 0) {
            Say (M 'cat.ok' $tag) Green
            return $true
        }
        Say (M 'cat.refused' $tag) Yellow
        return $false
    } catch {
        Say (M 'cat.err' $_.Exception.Message) Yellow
        return $false
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$seed = if ($PSScriptRoot) {
    Get-ChildItem -Path $PSScriptRoot -Filter 'nyshporka-catalog-*.zip' `
        -ErrorAction SilentlyContinue | Select-Object -First 1
} else { $null }
if ($seed) {
    $tmp = Join-Path $env:TEMP ('nysh-catalog-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -Path $seed.FullName -DestinationPath $tmp -Force
    $null = Invoke-Logged $nysh catalog install --from $tmp
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
} elseif ($NoCatalog) {
    Say (M 'cat.skip') DarkGray
} elseif (Install-CatalogFromRelease -Nysh $nysh) {
    # встановлено — рядок «✓» уже надрукувала сама функція
} else {
    # 🔴 Порада мусить казати, ЗВІДКИ взяти. Пак довідників лежить окремим
    # релізом (він оновлюється, коли архів виклав новий опис, а не коли
    # полагодили ваду), тож поруч із інсталятором його не буває НІКОЛИ, якщо
    # людина не зібрала комплект сама. Без адреси цей рядок читався як «щось
    # загубилось при встановленні», а `nysh find` мовчки лишався без каталогів.
    Say (M 'cat.missing') Yellow
    Say (M 'cat.take' $CatalogUrl) DarkGray
    Say (M 'cat.next')
}

# ── 6. ярлик ─────────────────────────────────────────────────────────────────
if (-not $NoLauncher) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Нишпорка.lnk'
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $nysh
    $s.Arguments = 'serve'
    $s.WorkingDirectory = $Home_
    $s.Description = M 'lnk.desc'
    $s.Save()
    Trace 'file' $lnk
    Say (M 'desk.ok') Green
}

# ── 7. що змінилось на цій машині ────────────────────────────────────────────
# 🔴 Перелік і друкується, і лягає на диск. Друкується — бо людина має право
# знати, що з нею зробили, не читаючи скрипта; лягає на диск — бо саме з
# нього `nysh uninstall` знімає РІВНО поставлене, а не те, що здається
# типовим. Скарга розробника 07.09.2026 була про обидві половини: змінили
# мовчки і зняти не було чим.
$traceFile = Join-Path $Home_ 'install-trace.txt'
Trace 'file' $traceFile
try {
    # 🔴 ДОПИСУЄМО до сліду попередніх запусків, а не затираємо його. Повторний
    # запуск — це й оновлення новим `.exe` поверх старого — бачить uv у теці
    # застосунку й теку команд уже в PATH, тож сам не записує ні `dir`, ні
    # `path`. Перезапис лишав у файлі лише `bin` і `file`, і допис у PATH,
    # зроблений ПЕРШИМ запуском, `nysh uninstall` більше не знімав. Друкуємо
    # нижче лише зміни цього запуску — на диск лягає їхнє об'єднання.
    $kept = @()
    if (Test-Path -LiteralPath $traceFile) {
        $kept = @(Get-Content -LiteralPath $traceFile -Encoding UTF8 |
                  Where-Object { $_ -and $_.Trim() -and -not $Trace.Contains($_) })
    }
    (@($kept) + @($Trace)) | Set-Content -LiteralPath $traceFile -Encoding UTF8
} catch {
    Say (M 'trace.fail' $traceFile) Yellow
}

Say ""
Say (M 'sum.title') Cyan
foreach ($line in $Trace) {
    $kind, $path = $line -split ' ', 2
    switch ($kind) {
        'dir'  { Say (M 'sum.dir' $path) DarkGray }
        'bin'  { Say (M 'sum.bin' $path) DarkGray }
        'file' { Say (M 'sum.file' $path) DarkGray }
        'path' { Say (M 'sum.path' $path) DarkGray }
        default { Say "  $kind $path" DarkGray }
    }
}
Say (M 'sum.space') DarkGray
Say (M 'sum.undo') DarkGray

Say ""
Say (M 'done') Cyan

# 🔴 Підказка стоїть ПЕРЕД переліком команд і сказана однією фразою, без слова
# «PATH». Відгук користувача 28.08.2026: «Побачив єдине знайоме слово
# "перезапустити" і надіслав комп'ютер перезапускатися. Ніби допомогло». Тобто
# пояснення механіки тут не читається взагалі — читається дія. Перезапуск вікна
# дешевший за перезапуск машини, тому названий першим; машина — як запасний
# варіант, а не як порада за замовчуванням.
if ($pathWasMissing) {
    Say ""
    Say (M 'reopen.1') Yellow
    Say (M 'reopen.2') DarkGray
    Say (M 'reopen.3') DarkGray
}

Say ""
Say (M 'next') Cyan
Say (M 'next.serve')
Say (M 'next.look')
if ($Preset -ne 'catalog' -and -not $EnginesOk -and -not $EnginesForeign) {
    Say (M 'next.htr')
    Say (M 'next.models')
}
Say (M 'next.doctor')

# 🔴 Успіх кажемо ЯВНО. `powershell -File` коду виходу останньої рідної команди
# назовні не віддає (перевірено на 5.1), тож нуль тут виходив би випадково — а
# на випадковість спирається `.exe`-майстер: саме за цим кодом він вирішує,
# показати «готово» чи сторінку помилки. Заразом це означає, що кожна рідна
# команда, дописана нижче, мусить перевірятись явно — тихо просочитись назовні
# її відмова більше не зможе.
try { Stop-Transcript | Out-Null } catch {}
exit 0
