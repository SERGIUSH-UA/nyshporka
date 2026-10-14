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
; під ДАНІ застосунку — там лежать довідники (49 МБ) і ваги моделей (~215 МБ, у
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
; Мова майстра — за мовою інтерфейсу Windows; вікно вибору лише тоді, коли
; такої мови тут немає.
ShowLanguageDialog=auto
; Картинки — з растру бренду, без тексту (майстер семимовний); збирає
; `tools/installer_images.py`. Кілька розмірів — Inno бере свій під масштаб екрана.
WizardImageFile=img\wizard-164x314.png,img\wizard-192x386.png,img\wizard-246x459.png,img\wizard-273x556.png,img\wizard-328x604.png,img\wizard-355x700.png,img\wizard-410x797.png
WizardSmallImageFile=img\small-55x55.png,img\small-64x68.png,img\small-83x80.png,img\small-92x97.png,img\small-110x106.png,img\small-119x123.png,img\small-138x140.png

[Languages]
; 🌐 Ті самі мови, що на порталі й у консолі (`nyshporka-online/app/i18n.py`,
; `KATALOHY`). Румунської серед офіційних перекладів Inno немає — файл узято
; з неофіційних (jrsoftware/issrc, Files/Languages/Unofficial) і покладено поруч.
; Російська перекладена, але вимкнена, як на порталі (`VYMKNENI`):
;   iscc install\nyshporka.iss /DWITH_RU
;
; 🔴 Мова першою — типова, коли мову Windows не впізнано.
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "romanian"; MessagesFile: "lang\Romanian.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
#ifdef WITH_RU
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
#endif

[CustomMessages]
; Власні написи майстра. Ярлики, завдання й «Запустити» беруть готові
; повідомлення самих мовних файлів Inno ({cm:CreateDesktopIcon} тощо).
; `%n` — новий рядок, `%1` — підстановка FmtMessage.
ukrainian.AppComment=Читання рукописних архівних справ
ukrainian.PresetTitle=Що ставимо
ukrainian.PresetSub=Нишпорку ставлять дуже різні люди.
ukrainian.PresetDesc=Змінити відповідь можна будь-коли командою «nysh sections» — перевстановлювати нічого не доведеться.
ukrainian.PresetCatalog=Каталоги архівів: де шукати метрики свого села.%nЛегкий набір, без рушіїв читання.
ukrainian.PresetResearcher=Каталоги + читання рукопису й пошук у прочитаному.%nРушії читання під вашу відеокарту: 2.5–4 ГБ і кілька хвилин.
ukrainian.UnknownPreset=Невідомий набір «%1».%nМожна: catalog | amateur | researcher | lab
ukrainian.Installing=Ставимо Нишпорку — це може зайняти кілька хвилин…
ukrainian.NoPowerShell=Не вдалося запустити PowerShell. Установлення перервано.
ukrainian.NoErrorText=Текст помилки не зберігся. Журнал: %1
ukrainian.AdminHint=Якщо причина вище не названа — спробуйте запустити інсталятор правою кнопкою миші → «Запустити від імені адміністратора». Тоді все стане в профіль того облікового запису, від імені якого запущено.
ukrainian.InstallFailed=Установлення не завершилось (код %1).
ukrainian.NoCommand=Нишпорка встановилась, але не сказала, де опинилась команда.%nНапишіть, будь ласка, на %1
ukrainian.PyDirTitle=Тека для Python
ukrainian.PyDirSub=Куди Нишпорка покладе свій інтерпретатор Python.
ukrainian.PyDirDesc=Зазвичай нічого міняти не треба. Якщо встановлення вже падало з «os error 448» (тека профілю в OneDrive чи перенаправлена), вкажіть теку поза профілем, наприклад D:\Nyshporka\python.
english.AppComment=Reading handwritten archival records
english.PresetTitle=What to install
english.PresetSub=Very different people install Nyshporka.
english.PresetDesc=You can change the answer at any time with the “nysh sections” command — nothing needs to be reinstalled.
english.PresetCatalog=Archive catalogs: where to look for your village's registers.%nLight set, no reading engines.
english.PresetResearcher=Catalogs + reading handwriting and searching what was read.%nReading engines for your graphics card: 2.5–4 GB and a few minutes.
english.UnknownPreset=Unknown preset “%1”.%nAllowed: catalog | amateur | researcher | lab
english.Installing=Installing Nyshporka — this may take a few minutes…
english.NoPowerShell=Could not start PowerShell. Installation aborted.
english.NoErrorText=The error text was not saved. Log: %1
english.AdminHint=If the cause is not named above, try starting the installer with a right click → “Run as administrator”. Everything will then go into the profile of the account it was started as.
english.InstallFailed=Installation did not finish (code %1).
english.NoCommand=Nyshporka was installed, but did not say where the command ended up.%nPlease write to %1
english.PyDirTitle=Folder for Python
english.PyDirSub=Where Nyshporka will put its Python interpreter.
english.PyDirDesc=Usually nothing needs changing. If installation has already failed with “os error 448” (profile folder in OneDrive or redirected), choose a folder outside the profile, for example D:\Nyshporka\python.
polish.AppComment=Odczyt rękopiśmiennych dokumentów archiwalnych
polish.PresetTitle=Co instalujemy
polish.PresetSub=Nyshporkę instalują bardzo różni ludzie.
polish.PresetDesc=Odpowiedź można zmienić w każdej chwili poleceniem „nysh sections” — nic nie trzeba instalować od nowa.
polish.PresetCatalog=Katalogi archiwów: gdzie szukać ksiąg metrykalnych swojej wsi.%nLekki zestaw, bez silników odczytu.
polish.PresetResearcher=Katalogi + odczyt rękopisów i wyszukiwanie w odczytanym.%nSilniki odczytu pod Twoją kartę graficzną: 2,5–4 GB i kilka minut.
polish.UnknownPreset=Nieznany zestaw „%1”.%nDostępne: catalog | amateur | researcher | lab
polish.Installing=Instalujemy Nyshporkę — to może potrwać kilka minut…
polish.NoPowerShell=Nie udało się uruchomić PowerShell. Instalacja przerwana.
polish.NoErrorText=Tekst błędu nie został zapisany. Dziennik: %1
polish.AdminHint=Jeśli przyczyna nie jest wymieniona powyżej, uruchom instalator prawym przyciskiem myszy → „Uruchom jako administrator”. Wszystko trafi wtedy do profilu konta, z którego go uruchomiono.
polish.InstallFailed=Instalacja nie została ukończona (kod %1).
polish.NoCommand=Nyshporka została zainstalowana, ale nie podała, gdzie jest polecenie.%nNapisz proszę na %1
polish.PyDirTitle=Folder na Pythona
polish.PyDirSub=Gdzie Nyshporka umieści swój interpreter Pythona.
polish.PyDirDesc=Zwykle nic nie trzeba zmieniać. Jeśli instalacja już kończyła się błędem „os error 448” (folder profilu w OneDrive lub przekierowany), wskaż folder poza profilem, na przykład D:\Nyshporka\python.
romanian.AppComment=Citirea dosarelor de arhivă scrise de mână
romanian.PresetTitle=Ce instalăm
romanian.PresetSub=Nyshporka este instalată de oameni foarte diferiți.
romanian.PresetDesc=Răspunsul poate fi schimbat oricând cu comanda „nysh sections” — nu trebuie reinstalat nimic.
romanian.PresetCatalog=Cataloagele arhivelor: unde să căutați registrele satului dumneavoastră.%nSet ușor, fără motoare de citire.
romanian.PresetResearcher=Cataloage + citirea manuscriselor și căutare în ce a fost citit.%nMotoare de citire pentru placa video: 2,5–4 GB și câteva minute.
romanian.UnknownPreset=Set necunoscut „%1”.%nPosibile: catalog | amateur | researcher | lab
romanian.Installing=Se instalează Nyshporka — poate dura câteva minute…
romanian.NoPowerShell=Nu s-a putut porni PowerShell. Instalarea a fost întreruptă.
romanian.NoErrorText=Textul erorii nu s-a păstrat. Jurnal: %1
romanian.AdminHint=Dacă cauza nu este numită mai sus, încercați să porniți programul de instalare cu clic dreapta → „Executare ca administrator”. Atunci totul va merge în profilul contului cu care a fost pornit.
romanian.InstallFailed=Instalarea nu s-a încheiat (cod %1).
romanian.NoCommand=Nyshporka a fost instalată, dar nu a spus unde se află comanda.%nScrieți, vă rugăm, la %1
romanian.PyDirTitle=Dosar pentru Python
romanian.PyDirSub=Unde își va pune Nyshporka interpretorul Python.
romanian.PyDirDesc=De obicei nu trebuie schimbat nimic. Dacă instalarea a eșuat deja cu „os error 448” (dosarul profilului în OneDrive sau redirecționat), alegeți un dosar din afara profilului, de exemplu D:\Nyshporka\python.
french.AppComment=Lecture de dossiers d'archives manuscrits
french.PresetTitle=Que faut-il installer
french.PresetSub=Nyshporka est installée par des personnes très différentes.
french.PresetDesc=Vous pouvez changer cette réponse à tout moment avec la commande « nysh sections » — rien à réinstaller.
french.PresetCatalog=Catalogues d'archives : où chercher les registres de votre village.%nVersion légère, sans moteurs de lecture.
french.PresetResearcher=Catalogues + lecture des manuscrits et recherche dans ce qui a été lu.%nMoteurs de lecture pour votre carte graphique : 2,5–4 Go et quelques minutes.
french.UnknownPreset=Profil inconnu « %1 ».%nPossibles : catalog | amateur | researcher | lab
french.Installing=Installation de Nyshporka — cela peut prendre quelques minutes…
french.NoPowerShell=Impossible de lancer PowerShell. Installation interrompue.
french.NoErrorText=Le texte de l'erreur n'a pas été conservé. Journal : %1
french.AdminHint=Si la cause n'est pas indiquée plus haut, essayez de lancer l'installeur par clic droit → « Exécuter en tant qu'administrateur ». Tout ira alors dans le profil du compte avec lequel il a été lancé.
french.InstallFailed=L'installation ne s'est pas terminée (code %1).
french.NoCommand=Nyshporka est installée, mais n'a pas indiqué où se trouve la commande.%nÉcrivez-nous, s'il vous plaît, à %1
french.PyDirTitle=Dossier pour Python
french.PyDirSub=Où Nyshporka placera son interpréteur Python.
french.PyDirDesc=En général, rien à changer. Si l'installation a déjà échoué avec « os error 448 » (dossier de profil dans OneDrive ou redirigé), choisissez un dossier hors du profil, par exemple D:\Nyshporka\python.
german.AppComment=Lesen handschriftlicher Archivakten
german.PresetTitle=Was wird installiert
german.PresetSub=Nyshporka wird von sehr unterschiedlichen Menschen installiert.
german.PresetDesc=Die Antwort lässt sich jederzeit mit dem Befehl „nysh sections“ ändern — neu installieren müssen Sie nichts.
german.PresetCatalog=Archivkataloge: wo Sie die Kirchenbücher Ihres Dorfes finden.%nLeichtes Set, ohne Leseengines.
german.PresetResearcher=Kataloge + Handschriften lesen und im Gelesenen suchen.%nLeseengines für Ihre Grafikkarte: 2,5–4 GB und einige Minuten.
german.UnknownPreset=Unbekanntes Set „%1“.%nMöglich: catalog | amateur | researcher | lab
german.Installing=Nyshporka wird installiert — das kann einige Minuten dauern…
german.NoPowerShell=PowerShell konnte nicht gestartet werden. Installation abgebrochen.
german.NoErrorText=Der Fehlertext wurde nicht gespeichert. Protokoll: %1
german.AdminHint=Wenn die Ursache oben nicht genannt ist, starten Sie den Installer per Rechtsklick → „Als Administrator ausführen“. Dann landet alles im Profil des Kontos, unter dem er gestartet wurde.
german.InstallFailed=Die Installation wurde nicht abgeschlossen (Code %1).
german.NoCommand=Nyshporka wurde installiert, hat aber nicht gemeldet, wo der Befehl liegt.%nBitte schreiben Sie an %1
german.PyDirTitle=Ordner für Python
german.PyDirSub=Wohin Nyshporka ihren Python-Interpreter legt.
german.PyDirDesc=Normalerweise muss nichts geändert werden. Ist die Installation bereits mit „os error 448“ gescheitert (Profilordner in OneDrive oder umgeleitet), wählen Sie einen Ordner außerhalb des Profils, z. B. D:\Nyshporka\python.
#ifdef WITH_RU
russian.AppComment=Чтение рукописных архивных дел
russian.PresetTitle=Что ставим
russian.PresetSub=Нышпорку ставят очень разные люди.
russian.PresetDesc=Изменить ответ можно в любой момент командой «nysh sections» — переустанавливать ничего не придётся.
russian.PresetCatalog=Каталоги архивов: где искать метрики своего села.%nЛёгкий набор, без движков чтения.
russian.PresetResearcher=Каталоги + чтение рукописей и поиск по прочитанному.%nДвижки чтения под вашу видеокарту: 2.5–4 ГБ и несколько минут.
russian.UnknownPreset=Неизвестный набор «%1».%nМожно: catalog | amateur | researcher | lab
russian.Installing=Ставим Нышпорку — это может занять несколько минут…
russian.NoPowerShell=Не удалось запустить PowerShell. Установка прервана.
russian.NoErrorText=Текст ошибки не сохранился. Журнал: %1
russian.AdminHint=Если причина выше не названа — попробуйте запустить установщик правой кнопкой мыши → «Запуск от имени администратора». Тогда всё встанет в профиль той учётной записи, от имени которой он запущен.
russian.InstallFailed=Установка не завершилась (код %1).
russian.NoCommand=Нышпорка установилась, но не сказала, где оказалась команда.%nНапишите, пожалуйста, на %1
russian.PyDirTitle=Папка для Python
russian.PyDirSub=Куда Нышпорка положит свой интерпретатор Python.
russian.PyDirDesc=Обычно ничего менять не нужно. Если установка уже падала с «os error 448» (папка профиля в OneDrive или перенаправлена), укажите папку вне профиля, например D:\Nyshporka\python.
#endif

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
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Icons]
; ⚠ Ціль обчислюється на льоту: `nysh.exe` кладе uv, і тека налаштовується
; (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`), тож на етапі збірки шляху не знає ніхто.
; Його лишає `windows.ps1` у `install-info.ini` — див. `GetNyshExe` нижче.
Name: "{group}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; IconFilename: "{app}\nyshporka.ico"; Comment: "{cm:AppComment}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; IconFilename: "{app}\nyshporka.ico"; Tasks: desktopicon

[Run]
; 🔴 `nowait` обов'язковий: `nysh serve` піднімає сервер і БЛОКУЄ потік до
; кінця життя процесу. Без цього прапорця майстер завис би на останньому кроці
; назавжди, і виглядало б це як зависле встановлення.
; Браузер відкриває сам застосунок — `serve` робить це через секунду після
; старту, тож глушити його `--no-browser` не треба.
Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 🔴 Перелік — дзеркало `HOME_OWNED` у `setup/uninstall.py`: усе, що
; `windows.ps1` кладе в `{app}`. Доти тут не було `install-trace.txt` і власного
; uv, тож після деінсталяції в «Programs» лишалась тека з uv.exe і слідом, а
; `{app}` через них не спорожнювався. Приймач — `test_iss_uninstall_takes_what_the_script_put`.
; ⚠ uv знімається ПОФАЙЛОВО, а не `filesandordirs`: теку встановлення можна
; перенести `/DIR=`, і рекурсивне видалення `{app}\uv` на чужому диску зачепило
; б теку з тим самим ім'ям, яку клав не майстер.
Type: files; Name: "{app}\install-info.ini"
Type: files; Name: "{app}\install-error.txt"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{app}\install-trace.txt"
Type: files; Name: "{app}\uv\uv.exe"
Type: files; Name: "{app}\uv\uvx.exe"
Type: files; Name: "{app}\uv\uvw.exe"
Type: dirifempty; Name: "{app}\uv"

[Code]
var
  PresetPage: TInputOptionWizardPage;
  PyDirPage: TInputDirWizardPage;
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
    CustomMessage('PresetTitle'), CustomMessage('PresetSub'),
    CustomMessage('PresetDesc'), True, False);
  PresetPage.Add(CustomMessage('PresetCatalog'));
  // Рушії читання й моделі цей варіант доставляє сам (`windows.ps1`, крок 4½),
  // а torch підбирає під відеокарту NVIDIA, якщо драйвер її показує.
  PresetPage.Add(CustomMessage('PresetResearcher'));
  PresetPage.SelectedValueIndex := PRESET_CATALOG;

  // 🔴 Тека для Python — окремим полем (рішення дослідника 14.10.2026). Типова
  // `{app}\python`; міняють її лише ті, у кого встановлення падало з os error
  // 448: uv не може пройти junction у профілі, перенаправленому в OneDrive.
  // Без поля такій людині лишалось запускати windows.ps1 руками.
  PyDirPage := CreateInputDirPage(PresetPage.ID,
    CustomMessage('PyDirTitle'), CustomMessage('PyDirSub'),
    CustomMessage('PyDirDesc'), False, '');
  PyDirPage.Add('');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // `{app}` відомий лише після сторінки вибору теки, тож типове значення
  // ставимо тут, і лише якщо людина ще нічого не вписала.
  if (CurPageID = PyDirPage.ID) and (PyDirPage.Values[0] = '') then
    PyDirPage.Values[0] := ExpandConstant('{app}\python');
end;

// Тека для `windows.ps1 -PythonDir`; порожньо — типова скрипта (`{app}\python`).
// Тихий режим: `/PYTHONDIR=D:\Nyshporka\python`.
function PythonDirFlag(): String;
var
  Dir: String;
begin
  if WizardSilent then
    Dir := ExpandConstant('{param:pythondir|}')
  else
    Dir := Trim(PyDirPage.Values[0]);
  Result := '';
  if Dir <> '' then
    Result := ' -PythonDir "' + Dir + '"';
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
      RaiseException(FmtMessage(CustomMessage('UnknownPreset'), [Quiet]));
    Result := Quiet;
  end
  else if PresetPage.SelectedValueIndex = PRESET_RESEARCHER then
    Result := 'researcher';
end;

// Тихий режим без рушіїв: `/ENGINES=no` (димовий прогін, офлайн-машина).
function EnginesFlag(): String;
begin
  Result := '';
  if WizardSilent and (Lowercase(ExpandConstant('{param:engines|yes}')) = 'no') then
    Result := ' -NoEngines';
end;

// Код мови для `windows.ps1 -Lang` — той самий, що в консолі й на порталі.
function LangCode(): String;
begin
  Result := 'uk';
  if ActiveLanguage = 'english' then Result := 'en';
  if ActiveLanguage = 'polish' then Result := 'pl';
  if ActiveLanguage = 'romanian' then Result := 'ro';
  if ActiveLanguage = 'french' then Result := 'fr';
  if ActiveLanguage = 'german' then Result := 'de';
  if ActiveLanguage = 'russian' then Result := 'ru';
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
  Script, Params, Detail: String;
  Raw: AnsiString;
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
            ' -NoLauncher' +
            EnginesFlag() +
            PythonDirFlag() +
            ' -Lang ' + LangCode() +
            ' -Wizard';
  // Слід ПОПЕРЕДНЬОЇ відмови не має видаватись за теперішню.
  DeleteFile(ExpandConstant('{app}\install-error.txt'));

  // 🪟 Консоль показуємо (`SW_SHOW`) навмисно. Установлення качає інтерпретатор
  // і пакети — це хвилини, і смуга Inno без жодного тексту читається як
  // зависання. Власний прогрес довелося б вигадувати й синхронізувати з чужим
  // виводом; замість цього людина бачить справжній хід роботи.
  WizardForm.StatusLabel.Caption := CustomMessage('Installing');
  if not Exec('powershell.exe', Params, '', SW_SHOW, ewWaitUntilTerminated, Code) then
    RaiseException(CustomMessage('NoPowerShell'));

  // 🔴 Ненульовий код виходу мусить валити встановлення ГОЛОСНО. Мовчазний
  // провал дав би ярлики, які нікуди не ведуть, — а людина вважала б, що
  // застосунок стоїть.
  // 🔴 І з ТЕКСТОМ, а не з відсиланням до вікна PowerShell: те вікно
  // закривається разом зі скриптом, і людина бачила лише «код 1». Скрипт
  // лишає причину в `install-error.txt` (кодування ANSI — саме так її читає
  // `LoadStringFromFile`), а повний вивід — у `install.log`.
  if Code <> 0 then
  begin
    Detail := '';
    if LoadStringFromFile(ExpandConstant('{app}\install-error.txt'), Raw) then
      Detail := Raw;
    if Trim(Detail) = '' then
      Detail := FmtMessage(CustomMessage('NoErrorText'), [ExpandConstant('{app}\install.log')]);
    // Спостережене 06.09.2026: у звичайного користувача відмова, від імені
    // адміністратора — успіх (політика виконання на машині). Порада стоїть
    // останньою і лише без підвищення: із підвищенням вона вже не допоможе.
    if not IsAdmin then
      Detail := Detail + #13#10#13#10 + CustomMessage('AdminHint');
    // ⚠ `#13#10` не на початку рядка: препроцесор Inno читає такий рядок як
    // свою директиву («Unknown preprocessor directive»).
    // ⚠ І не `[` на початку рядка — це вже заголовок секції.
    Detail := FmtMessage(CustomMessage('InstallFailed'), [IntToStr(Code)]) + #13#10#13#10 + Detail;
    RaiseException(Detail);
  end;

  if GetNyshExe('') = '' then
    RaiseException(FmtMessage(CustomMessage('NoCommand'), ['{#AppUrl}/issues']));
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
