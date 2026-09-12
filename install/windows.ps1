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
    # Запуск із майстра `.exe`: консоль зникає разом зі скриптом, тож помилку
    # треба показати вікном, яке переживе консоль.
    [switch]$Wizard
)

# Звідки брати пак довідників, якщо його немає поруч. Та сама адреса, що її
# друкує `nysh catalog list` на порожньому каталозі (`catalog.store.RELEASES_URL`).
$CatalogUrl = 'https://github.com/SERGIUSH-UA/nyshporka/releases'

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
    $lines = @('Помилка: ' + $failure.Exception.Message)
    if ($failure.InvocationInfo -and $failure.InvocationInfo.ScriptLineNumber) {
        $lines += ('   (рядок ' + $failure.InvocationInfo.ScriptLineNumber + ' інсталятора)')
    }
    try { Stop-Transcript | Out-Null } catch {}
    # Справжня причина — те, що написав uv або nysh перед «не вдалося». Береться
    # з буфера `Invoke-Logged`; транскрипт тут не годиться — він не бачить
    # виводу exe в консоль, а його заголовок з'їв би весь хвіст.
    $tail = @($script:NativeTail | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 15)
    if ($tail.Count) { $lines += ''; $lines += 'Останні рядки виводу:'; $lines += $tail }
    if ($script:PreflightNote) { $lines += ''; $lines += $script:PreflightNote }
    $lines += ''
    $lines += ('Повний журнал: ' + $LogFile)
    $text = $lines -join [Environment]::NewLine
    Write-Host ''
    Write-Host $text -ForegroundColor Red
    # ⚠ Кодування ANSI навмисно: майстер читає файл як AnsiString і переводить у
    # Unicode системною кодовою сторінкою — саме тією, якою .NET тут пише.
    try { [IO.File]::WriteAllText($ErrorFile, $text, [Text.Encoding]::Default) } catch {}
    if ($Wizard) {
        try {
            (New-Object -ComObject WScript.Shell).Popup(
                $text, 0, 'Нишпорка: установлення не завершилось', 16) | Out-Null
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

# 🐾 Знак ТОЙ САМИЙ, що друкує `nysh info` і старт застосунку — побайтово,
# і це звіряє тест. Інсталятор — найперша поверхня, яку бачить людина, і
# власна лапка тут означала б, що бренд розходиться з першого ж екрана.
Say "  ● ● ● ●" DarkYellow
Say "  ╭─ ◍ ─╮   Нишпорка" DarkYellow
Say "  ╰─────╯   Читає рукопис. Приносить знайдене." DarkGray
Say ""
Say "  тека: $Home_" DarkGray

if ($DryRun) {
    $uvNow = (Get-Command uv -ErrorAction SilentlyContinue).Source
    $binGuess = if ($uvNow) { Get-NativeLine $uvNow tool dir --bin } else { $null }
    if (-not $binGuess) { $binGuess = Join-Path $env:USERPROFILE '.local\bin' }
    Say ""
    if ($uvNow) { Say "uv                 уже є: $uvNow" }
    else         { Say "uv                 буде завантажено в $(Join-Path $Home_ 'uv')" }
    Say "Python 3.12        керований, у теці uv; ні в PATH, ні в реєстрі його не буде"
    Say "Нишпорка           $(if ($Source) { $Source } else { "набір $Preset" })"
    Say "                   в ізольованому середовищі інструмента uv"
    Say "команда nysh       $(Join-Path $binGuess 'nysh.exe')"
    Say "слід інсталятора   $(Join-Path $Home_ 'install-info.ini')"
    Say "                   $(Join-Path $Home_ 'install-trace.txt')"
    Say "простір досліджень тека, яку назве «nysh init»"
    if ($env:NYSH_NO_MODIFY_PATH -eq '1') {
        Say "PATH користувача   не чіпається (NYSH_NO_MODIFY_PATH=1)"
    } else {
        Say "PATH користувача   один допис «$binGuess», якщо теки там ще немає"
    }
    Say ""
    Say "Нічого не зроблено — це -DryRun." Cyan
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
    Say "  ⚠ Запуск із правами адміністратора. Усе стане в профіль користувача" Yellow
    Say "    $($identity.Name) ($env:USERPROFILE)." Yellow
    Say "    Якщо працювати буде інший користувач — йому команда nysh і ярлики" DarkGray
    Say "    не дістануться; встановлюйте з-під його облікового запису." DarkGray
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
            $script:PreflightNote = (
                "Передперевірка: програми з профілю користувача ($Home_) на цій машині " +
                "НЕ ЗАПУСКАЮТЬСЯ — схоже на політику AppLocker/SRP або правило ASR. " +
                "Нишпорка ставиться в профіль без прав адміністратора, тож тут вона " +
                "не працюватиме. Варіанти: запустити інсталятор правою кнопкою миші " +
                "→ «Запустити від імені адміністратора» (тоді все стане в профіль " +
                "адміністратора), або попросити ІТ дозволити запуск із $Home_ і " +
                "$env:LOCALAPPDATA\uv.")
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
        Say "✓ uv уже є: $existing" Green
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
        if (-not (Test-Path $uv)) { throw "uv не встановився у $uvDir" }
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
$rc = Invoke-Logged $uv python install 3.12
if ($rc -ne 0) { throw "не вдалося встановити Python 3.12 (uv повернув $rc)" }
Say "✓ Python" Green

# ── 3. застосунок ────────────────────────────────────────────────────────────
# `uv tool install` кладе застосунок у власне ізольоване середовище й дає
# консольну команду. Це саме те, що треба: жодних конфліктів із чужими пакетами.
Say "⬇ Нишпорка ($Source)…" DarkGray
$rc = Invoke-Logged $uv tool install --python 3.12 --force $Source
if ($rc -ne 0) { throw "не вдалося встановити $Source (uv повернув $rc)" }
Say "✓ Нишпорка" Green

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
    Say "✗ пакет установлено, але команди немає: $nysh" Red
    Say '  надішліть, будь ласка, вивід `uv tool list` — це вада інсталятора,' DarkGray
    Say '  а не вашої машини' DarkGray
    throw 'nysh не знайдено після встановлення'
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
    @('[nyshporka]', "nysh=$nysh", "uv=$uv", "preset=$Preset") |
        Set-Content -LiteralPath $info -Encoding Unicode
} catch {
    Say "⚠ не вдалося записати $info — ярлики доведеться створити вручну" Yellow
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
if ($rc -ne 0) { throw "не вдалося створити робочий простір (nysh повернув $rc)" }

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
$seed = if ($PSScriptRoot) {
    Get-ChildItem -Path $PSScriptRoot -Filter 'nyshporka-catalog-*.zip' `
        -ErrorAction SilentlyContinue | Select-Object -First 1
} else { $null }
if ($seed) {
    $tmp = Join-Path $env:TEMP ('nysh-catalog-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -Path $seed.FullName -DestinationPath $tmp -Force
    $null = Invoke-Logged $nysh catalog install --from $tmp
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
} else {
    # 🔴 Порада мусить казати, ЗВІДКИ взяти. Пак довідників лежить окремим
    # релізом (він оновлюється, коли архів виклав новий опис, а не коли
    # полагодили ваду), тож поруч із інсталятором його не буває НІКОЛИ, якщо
    # людина не зібрала комплект сама. Без адреси цей рядок читався як «щось
    # загубилось при встановленні», а `nysh find` мовчки лишався без каталогів.
    Say "⚠ довідників поруч немає — пошук по каталогах архівів буде недоступний" Yellow
    Say "  взяти: $CatalogUrl" DarkGray
    Say "  далі:  nysh catalog install --from <завантажений zip>"
}

# ── 6. ярлик ─────────────────────────────────────────────────────────────────
if (-not $NoLauncher) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Нишпорка.lnk'
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $nysh
    $s.Arguments = 'serve'
    $s.WorkingDirectory = $Home_
    $s.Description = 'Читання рукописних архівних справ'
    $s.Save()
    Trace 'file' $lnk
    Say "✓ ярлик на робочому столі" Green
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
    Say "⚠ не вдалося записати $traceFile — «nysh uninstall» питатиме шляхи" Yellow
}

Say ""
Say "Змінено на цій машині:" Cyan
foreach ($line in $Trace) {
    $kind, $path = $line -split ' ', 2
    switch ($kind) {
        'dir'  { Say "  тека        $path" DarkGray }
        'bin'  { Say "  команда     $path" DarkGray }
        'file' { Say "  файл        $path" DarkGray }
        'path' { Say "  PATH        допис «$path» у змінні середовища користувача" DarkGray }
        default { Say "  $kind $path" DarkGray }
    }
}
Say "  простір досліджень — тека, яку щойно назвав «nysh init»" DarkGray
Say "  зняти все це: nysh uninstall" DarkGray

Say ""
Say "Готово." Cyan

# 🔴 Підказка стоїть ПЕРЕД переліком команд і сказана однією фразою, без слова
# «PATH». Відгук користувача 28.08.2026: «Побачив єдине знайоме слово
# "перезапустити" і надіслав комп'ютер перезапускатися. Ніби допомогло». Тобто
# пояснення механіки тут не читається взагалі — читається дія. Перезапуск вікна
# дешевший за перезапуск машини, тому названий першим; машина — як запасний
# варіант, а не як порада за замовчуванням.
if ($pathWasMissing) {
    Say ""
    Say "  ⚠ Закрийте це вікно й відкрийте нове — команди нижче працюють там." Yellow
    Say "    У вікнах, відкритих до встановлення, «nysh» не знайдеться." DarkGray
    Say "    Якщо й у новому не знайдеться — перезапустіть комп'ютер." DarkGray
}

Say ""
Say "Далі:" Cyan
Say "  nysh serve            відкрити застосунок у браузері"
Say "  nysh look <тека>      подивитись, що за скани"
Say "  nysh models get       завантажити моделі письма"
Say "  nysh doctor           перевірити те, що ламається тихо"

# 🔴 Успіх кажемо ЯВНО. `powershell -File` коду виходу останньої рідної команди
# назовні не віддає (перевірено на 5.1), тож нуль тут виходив би випадково — а
# на випадковість спирається `.exe`-майстер: саме за цим кодом він вирішує,
# показати «готово» чи сторінку помилки. Заразом це означає, що кожна рідна
# команда, дописана нижче, мусить перевірятись явно — тихо просочитись назовні
# її відмова більше не зможе.
try { Stop-Transcript | Out-Null } catch {}
exit 0
