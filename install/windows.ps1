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

    Запуск:
        powershell -ExecutionPolicy Bypass -File install\windows.ps1
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

Say "Нишпорка — установлення" Cyan
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

$nysh = (Get-Command nysh -ErrorAction SilentlyContinue).Source
if (-not $nysh) {
    & $uv tool update-shell 2>&1 | Out-Null
    $nysh = Join-Path $env:USERPROFILE '.local\bin\nysh.exe'
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
$seed = Get-ChildItem -Path $PSScriptRoot -Filter 'nyshporka-catalog-*.zip' `
    -ErrorAction SilentlyContinue | Select-Object -First 1
if ($seed) {
    $tmp = Join-Path $env:TEMP ('nysh-catalog-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -Path $seed.FullName -DestinationPath $tmp -Force
    & $nysh catalog install --from $tmp
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
} else {
    Say "⚠ довідників поруч немає — пошук по каталогах архівів буде недоступний" Yellow
    Say "  поставити пізніше: nysh catalog install --from <тека|zip>"
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
Say "Готово. Далі:" Cyan
Say "  nysh serve            відкрити застосунок у браузері"
Say "  nysh look <тека>      подивитись, що за скани"
Say "  nysh models get       завантажити моделі письма"
Say "  nysh doctor           перевірити те, що ламається тихо"
