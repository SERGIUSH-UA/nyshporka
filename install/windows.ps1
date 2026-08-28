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

    Запуск без клону — однією командою (саме її дають агентові):
        irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 | iex

    Те саме з набором (`param()` вимагає форми зі scriptblock — конвеєр
    аргументів не передає):
        & ([scriptblock]::Create((irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1))) -Preset catalog
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
    [switch]$NoLauncher
)

# Звідки брати пак довідників, якщо його немає поруч. Та сама адреса, що її
# друкує `nysh catalog list` на порожньому каталозі (`catalog.store.RELEASES_URL`).
$CatalogUrl = 'https://github.com/SERGIUSH-UA/nyshporka/releases'

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Extras під обраний набір. Явно заданий -Source перебиває: хто вписав склад
# руками, знає, чого хоче.
# ⚠ Перелік дублює `core.sections.EXTRAS` — інакше інсталятор мусив би спершу
# поставити пакет, щоб спитати в нього, що ставити. Розбіжність ловить
# `test_installer_extras_match_the_sections`.
if (-not $Source) {
    $Source = if ($Preset -eq 'catalog') { 'nyshporka[app,archives]' }
              else { 'nyshporka[app,archives,htr]' }
}

function Say($text, $colour = 'White') { Write-Host $text -ForegroundColor $colour }

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

New-Item -ItemType Directory -Force -Path $Home_ | Out-Null
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
        # Офіційний інсталятор uv; ставить у вказану теку, без адміністратора.
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        if (-not (Test-Path $uv)) { throw "uv не встановився у $uvDir" }
        Say "✓ uv" Green
    }
}

# ── 2. інтерпретатор ─────────────────────────────────────────────────────────
Say "⬇ Python 3.12…" DarkGray
& $uv python install 3.12 | Out-Null
Say "✓ Python" Green

# ── 3. застосунок ────────────────────────────────────────────────────────────
# `uv tool install` кладе застосунок у власне ізольоване середовище й дає
# консольну команду. Це саме те, що треба: жодних конфліктів із чужими пакетами.
Say "⬇ Нишпорка ($Source)…" DarkGray
& $uv tool install --python 3.12 --force $Source
if ($LASTEXITCODE -ne 0) { throw "не вдалося встановити $Source" }
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
if ($pathWasMissing) {
    $env:PATH = "$binDir;$env:PATH"
    Invoke-Muted $uv tool update-shell
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

# ── 4. робочий простір ───────────────────────────────────────────────────────
# 🔴 Мовчки не створюємо: тека, що з'явилась сама, — це дослідження, яке потім
# не можуть знайти. `--yes` виправданий тим, що майстер бере шлях із
# драбини джерел (змінна · маркер · типове місце) і ДРУКУЄ, звідки він
# узявся, — тобто мовчазного вибору тут немає.
# ⚠ Не плутати з `$Home_` вище: то тека ВСТАНОВЛЕННЯ, а не простір.
Say ""
& $nysh init --yes --preset $Preset
& $nysh doctor

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
    & $nysh catalog install --from $tmp
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
    Say "✓ ярлик на робочому столі" Green
}

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
