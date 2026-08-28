; Нишпорка — майстер установлення для Windows.
;
; 🔴 Цей файл НЕ дублює логіку встановлення. Усе, що справді ставить Нишпорку,
; живе в `windows.ps1`, і майстер лише дає йому обличчя: вибір набору, ярлики,
; деінсталяцію, запуск. Причина проста — та логіка вже оплачена трьома скаргами
; й накрита приймачами в `tests/test_sections.py`; друга її копія на Pascal
; розійшлася б із першою на найближчому ж виправленні.
;
; Навіщо взагалі `.exe`, коли є однорядкова команда: скарги 28.08.2026 звелись
; до того, що людина не має відкривати термінал. Дослівно — «користувач має
; скачати файл, натиснути встановити і отримати застосунок».
;
; ⚠ Потрібен Inno Setup ≥ 6.5:
;   6.3 — читає `.iss` у UTF-8 БЕЗ BOM (цей файл саме такий);
;   6.5 — несе `Ukrainian.isl` у комплекті.
; На старішому кирилиця тихо перетвориться на кракозябри — зламається не
; збірка, а мова, і помітить це вже користувач. Це та сама пастка, що коштувала
; випуску 0.5.2, тож версія вимагається явно нижче.
;
; Збірка:  iscc install\nyshporka.iss /DAppVersion=0.5.3

#if VER < EncodeVer(6,5,0)
  #error Потрiбен Inno Setup 6.5 або новiший: UTF-8 без BOM i українська мова
#endif

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Нишпорка"
#define AppPublisher "Serhii Dalishchynskyi"
#define AppUrl "https://github.com/SERGIUSH-UA/nyshporka"

; 🗂 Пак довідників, якщо його поклали поруч. Ім'я з'ясовуємо ТУТ, на етапі
; збірки: воно несе дату зрізу (`nyshporka-catalog-2026-08-17.zip`), а
; `ExtractTemporaryFile` масок не розуміє й вимагає точного імені.
; ⚠ `#define` усередині `#sub` лягає в ЛОКАЛЬНУ область, і зовнішнє значення
; лишається порожнім — пак тоді мовчки не потрапляє в збірку, а `.exe`
; виходить нормальним на вигляд. Тому пряма форма, без підпрограми.
#define CatalogZip ""
#define FindHandle
#expr FindHandle = FindFirst(AddBackslash(SourcePath) + "nyshporka-catalog-*.zip", 0)
#if FindHandle
  #define CatalogZip FindGetFileName(FindHandle)
  #expr FindClose(FindHandle)
#endif
#if CatalogZip == ""
  #pragma message "⚠ пак довiдникiв не знайдено — .exe збереться без нього"
#else
  #pragma message "пак довiдникiв: " + CatalogZip
#endif

[Setup]
; 🔴 AppId не міняти НІКОЛИ. За ним Windows упізнає вже встановлену Нишпорку:
; інший ідентифікатор дасть другий запис у «Програмах», два деінсталятори й
; два комплекти ярликів на одну програму.
AppId={{6E7C4B21-9A3D-4F5E-8C10-2D9B7A4E5F33}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Читає рукопис. Приносить знайдене.

; 🔴 Прав адміністратора не просимо й не потребуємо — рівно як `windows.ps1`.
; Застосунок працює з файлами однієї людини і нічого системного не чіпає, а
; запит UAC на такому інсталяторі читається як «щось тут не так».
PrivilegesRequired=lowest
; 🔴🔴 НЕ `{localappdata}\Nyshporka`, попри те, що саме такий типовий `-Home_`
; у `windows.ps1`. Ця тека вже зайнята: `platformdirs.user_data_dir` віддає її
; під ДАНІ застосунку — там лежать довідники (49 МБ) і ваги моделей (130 МБ, у
; `Cache\model`). Зробити її ще й текою встановлення означає покласти міну під
; деінсталятор: перший, хто допише туди рекурсивне видалення `{app}`, змиє
; завантажене користувачем — тихо й без відновлення.
; `{autopf}` під `lowest` = `%LOCALAPPDATA%\Programs\Nyshporka`.
DefaultDirName={autopf}\Nyshporka
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; ⚠ Сторінки вибору теки немає навмисно, і це не спрощення заради спрощення:
; вага встановлення лягає НЕ в `{app}`, а у власні теки uv (інтерпретатор і
; середовище застосунку). Тобто сторінка обіцяла б керування місцем, якого
; насправді не дає, — і людина, що перенесла б теку на інший диск, усе одно
; отримала б 2.5 ГБ у профілі.
DisableDirPage=yes

OutputDir=..\dist
OutputBaseFilename=nyshporka-{#AppVersion}-setup
SetupIconFile=..\src\nyshporka\brand\data\assets\nyshporka.ico
UninstallDisplayIcon={app}\nyshporka.ico
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
Compression=lzma2/max
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Files]
; 🔴 `windows.ps1` кладеться ПОБАЙТОВО, разом із BOM. Без BOM Windows
; PowerShell 5.1 читає файл як ANSI, і кирилиця ламається ще до першого рядка
; виводу; приймач самого файла — `test_windows_installer_is_utf8_with_bom`.
; `dontcopy` — це інструмент установлення, а не частина застосунку: у `{app}`
; йому потім немає чого робити.
Source: "windows.ps1"; Flags: dontcopy
#if CatalogZip != ""
; 🗂 Пак довідників їде В КОМПЛЕКТІ. Без нього перше питання людини («де
; метрики мого села») лишається без відповіді, хоч README обіцяє, що
; `nysh find` працює одразу після встановлення. Досі при встановленні без
; клону репозиторію пак не ставився НІКОЛИ: скрипт шукає його поруч із собою,
; а `$PSScriptRoot` у такому запуску порожній. `ExtractTemporaryFile` кладе
; обидва файли в ту саму теку — і наявна логіка спрацьовує без правок.
Source: "{#CatalogZip}"; Flags: dontcopy
#endif
Source: "..\src\nyshporka\brand\data\assets\nyshporka.ico"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Створити ярлик на робочому столі"; GroupDescription: "Додатково:"

[Icons]
; ⚠ Ціль обчислюється на льоту: `nysh.exe` кладе uv, і тека налаштовується
; (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`), тож на етапі збірки шляху не знає ніхто.
; Його лишає `windows.ps1` у `install-info.ini` — див. `GetNyshExe` нижче.
Name: "{group}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; IconFilename: "{app}\nyshporka.ico"; Comment: "Читання рукописних архівних справ"
Name: "{group}\Видалити {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; IconFilename: "{app}\nyshporka.ico"; Tasks: desktopicon

[Run]
; 🔴 `nowait` обов'язковий: `nysh serve` піднімає сервер і БЛОКУЄ потік до
; кінця життя процесу. Без цього прапорця майстер завис би на останньому кроці
; назавжди, і виглядало б це як зависле встановлення.
; Браузер відкриває сам застосунок — `serve` робить це через секунду після
; старту, тож глушити його `--no-browser` не треба.
Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; Description: "Запустити {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\install-info.ini"

[Code]
var
  PresetPage: TInputOptionWizardPage;
  ResolvedNysh: String;

const
  PRESET_CATALOG = 0;
  PRESET_RESEARCHER = 1;

procedure InitializeWizard();
begin
  // 🔴 Набір питаємо, а не вирішуємо за людину: різниця між гілками — 2.5 ГБ і
  // кілька хвилин чекання. Типово легкий, бо найперший відвідувач приходить із
  // питанням «де метрики мого села», а не зі сканами й відеокартою.
  PresetPage := CreateInputOptionPage(wpSelectTasks,
    'Що ставимо', 'Нишпорку ставлять дуже різні люди.',
    'Змінити відповідь можна будь-коли командою «nysh sections» — ' +
    'перевстановлювати нічого не доведеться.',
    True, False);
  PresetPage.Add('Каталоги архівів: де шукати метрики свого села.' + #13#10 +
    'Легкий набір, без рушіїв читання.');
  PresetPage.Add('Каталоги + читання рукопису й пошук у прочитаному.' + #13#10 +
    'Тягне torch: близько 2.5 ГБ і кілька хвилин.');
  PresetPage.SelectedValueIndex := PRESET_CATALOG;
end;

function SelectedPreset(): String;
var
  Quiet: String;
begin
  Result := 'catalog';
  if WizardSilent then
  begin
    // Тихий режим (агенти, димовий прогін у CI) сторінок не показує, тож набір
    // приходить параметром: `nyshporka-setup.exe /VERYSILENT /PRESET=researcher`.
    Quiet := Lowercase(ExpandConstant('{param:preset|catalog}'));
    // 🔴 Звіряємо ТУТ. Невідоме ім'я інакше доїхало б до `nysh init` і впало на
    // останньому кроці — коли інтерпретатор і пакети вже завантажено, тобто
    // через хвилини чекання й уже без права на другу спробу задарма.
    if (Quiet <> 'catalog') and (Quiet <> 'amateur')
       and (Quiet <> 'researcher') and (Quiet <> 'lab') then
      RaiseException('Невідомий набір «' + Quiet + '».' + #13#10 +
        'Можна: catalog | amateur | researcher | lab');
    Result := Quiet;
  end
  else if PresetPage.SelectedValueIndex = PRESET_RESEARCHER then
    Result := 'researcher';
end;

function InfoFile(): String;
begin
  Result := ExpandConstant('{app}\install-info.ini');
end;

// Шлях до `nysh.exe`, який щойно вирахував `windows.ps1`.
function GetNyshExe(Param: String): String;
begin
  if ResolvedNysh = '' then
    ResolvedNysh := GetIniString('nyshporka', 'nysh', '', InfoFile());
  Result := ResolvedNysh;
end;

procedure RunInstallScript();
var
  Script, Params: String;
  Code: Integer;
begin
  // Обидва файли лягають у ту саму тимчасову теку, тож `$PSScriptRoot` у
  // скрипті знаходить пак довідників «поруч із собою».
  ExtractTemporaryFile('windows.ps1');
#if CatalogZip != ""
  ExtractTemporaryFile('{#CatalogZip}');
#endif

  Script := ExpandConstant('{tmp}\windows.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '"' +
            ' -Preset ' + SelectedPreset() +
            ' -Version {#AppVersion}' +
            ' -Home_ "' + ExpandConstant('{app}') + '"' +
            ' -NoLauncher';

  // 🪟 Консоль показуємо (`SW_SHOW`) навмисно. Установлення качає інтерпретатор
  // і пакети — це хвилини, і смуга Inno без жодного тексту читається як
  // зависання. Власний прогрес довелося б вигадувати й синхронізувати з чужим
  // виводом; замість цього людина бачить справжній хід роботи.
  WizardForm.StatusLabel.Caption := 'Ставимо Нишпорку — це може зайняти кілька хвилин…';
  if not Exec('powershell.exe', Params, '', SW_SHOW, ewWaitUntilTerminated, Code) then
    RaiseException('Не вдалося запустити PowerShell. Установлення перервано.');

  // 🔴 Ненульовий код виходу мусить валити встановлення ГОЛОСНО. Мовчазний
  // провал дав би ярлики, які нікуди не ведуть, — а людина вважала б, що
  // застосунок стоїть.
  if Code <> 0 then
    RaiseException('Установлення не завершилось (код ' + IntToStr(Code) + ').' + #13#10 +
      'Текст помилки лишився у вікні PowerShell.');

  if GetNyshExe('') = '' then
    RaiseException('Нишпорка встановилась, але не сказала, де опинилась команда.' + #13#10 +
      'Напишіть, будь ласка, на {#AppUrl}/issues');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // ⚠ Саме `ssInstall`, а не `ssPostInstall`: ярлики Inno створює МІЖ ними, а
  // їхня ціль відома лише після того, як скрипт відпрацював.
  if CurStep = ssInstall then
    RunInstallScript();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Uv: String;
  Res: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  // 🔴🔴 Робочий простір НЕ чіпаємо — ніде й ніколи. Там скани, прочитане й
  // роками зібране дослідження людини; тека створювалась окремо (`nysh init`)
  // і живе поза `{app}`. Знімаємо рівно те, що поставили: сам пакет, ярлики й
  // теку встановлення.
  Uv := GetIniString('nyshporka', 'uv', '', InfoFile());
  if (Uv <> '') and FileExists(Uv) then
    Exec(Uv, 'tool uninstall nyshporka', '', SW_HIDE, ewWaitUntilTerminated, Res);
end;
