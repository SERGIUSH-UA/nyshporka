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
; 🔴 Стандартної сторінки теки немає, бо питаємо не теку ПРОГРАМИ, а теку, де
; житиме ВСЕ (розкладка «одна тека», з 0.32): власна сторінка «Де жити
; Нишпорці» нижче, у коді майстра. Людина обирає `X`, простір дослідження стає `X`,
; а `{app}` = `X\.program` — туди ж кладуться Python, середовище застосунку,
; кеш uv, довідники й ваги (`windows.ps1 -Workspace`). Доти `{app}` був у
; LOCALAPPDATA, а вага встановлення — у власних теках uv у профілі, тож людина,
; яка хотіла D:, отримувала 2.5–4 ГБ на C: і простір у «Документах»
; (відеоурок, 16.10.2026).
; ⚠ Оновлення поверх установки бере попередній `{app}` (UsePreviousAppDir) і
; сторінки не показує: стару розкладку переносить `nysh relocate`, не майстер.
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
ukrainian.SiteName=Сайт родини
ukrainian.SiteComment=Сайт роду з канону Нишпорки
ukrainian.PresetTitle=Що ставимо
ukrainian.PresetSub=Нишпорку ставлять дуже різні люди.
ukrainian.PresetDesc=Змінити відповідь можна будь-коли командою «nysh sections» — перевстановлювати нічого не доведеться.
ukrainian.PresetCatalog=Лише каталоги архівів — дізнатися, де лежать метрики села.%nБез читання рукописів і без пошуку роду в прочитаному.
ukrainian.PresetResearcher=Усе (рекомендовано): каталоги, читання рукописів і пошук роду в прочитаному.%nРушії читання під вашу відеокарту: 2.5–4 ГБ і кілька хвилин.
ukrainian.UnknownPreset=Невідомий набір «%1».%nМожна: catalog | amateur | researcher | lab
ukrainian.Installing=Ставимо Нишпорку — це може зайняти кілька хвилин…
ukrainian.NoPowerShell=Не вдалося запустити PowerShell. Установлення перервано.
ukrainian.NoErrorText=Текст помилки не зберігся. Журнал: %1
ukrainian.AdminHint=Якщо причина вище не названа — спробуйте запустити інсталятор правою кнопкою миші → «Запустити від імені адміністратора». Тоді все стане в профіль того облікового запису, від імені якого запущено.
ukrainian.InstallFailed=Установлення не завершилось (код %1).
ukrainian.NoCommand=Нишпорка встановилась, але не сказала, де опинилась команда.%nНапишіть, будь ласка, на %1
ukrainian.SpaceTitle=Де жити Нишпорці
ukrainian.SpaceSub=Одна тека на все: програма, рушії читання й ваші справи.
ukrainian.SpaceDesc=Тут будуть програма, рушії читання (до 4 ГБ) і все дослідження: скани, прочитане, нотатки. Оберіть диск, де вдосталь місця, — наприклад D:. Пізніше перенести можна командою «nysh relocate».
ukrainian.SpaceRoot=Потрібна окрема тека щонайменше на два рівні від кореня диска, наприклад D:\Genealogy\Нишпорка.
ukrainian.SpaceSystem=Це системна або надто широка тека. Створіть у ній окрему, наприклад %1\Нишпорка.
ukrainian.SpaceCloud=Тека синхронізується з хмарою (OneDrive, Dropbox тощо). Читання тисяч сторінок з такої теки виглядає як зависання. Оберіть теку поза хмарою.
ukrainian.SpaceLow=На цьому диску вільно лише %1 ГБ, а потрібно близько 10 ГБ. Усе одно ставити сюди?
ukrainian.AgentDoc=Відкрити інструкцію: як підключити помічника (Claude чи Codex)
ukrainian.FinishAgent=Далі — підключіть помічника: Claude або Codex. Він веде дослідження, а вікно Нишпорки показує, що зроблено.
english.AppComment=Reading handwritten archival records
english.SiteName=Family site
english.SiteComment=The family site built from the Nyshporka canon
english.PresetTitle=What to install
english.PresetSub=Very different people install Nyshporka.
english.PresetDesc=You can change the answer at any time with the “nysh sections” command — nothing needs to be reinstalled.
english.PresetCatalog=Archive catalogs only — find out where your village's registers are.%nNo reading of handwriting and no family search in what was read.
english.PresetResearcher=Everything (recommended): catalogs, reading handwriting and searching for the family in what was read.%nReading engines for your graphics card: 2.5–4 GB and a few minutes.
english.UnknownPreset=Unknown preset “%1”.%nAllowed: catalog | amateur | researcher | lab
english.Installing=Installing Nyshporka — this may take a few minutes…
english.NoPowerShell=Could not start PowerShell. Installation aborted.
english.NoErrorText=The error text was not saved. Log: %1
english.AdminHint=If the cause is not named above, try starting the installer with a right click → “Run as administrator”. Everything will then go into the profile of the account it was started as.
english.InstallFailed=Installation did not finish (code %1).
english.NoCommand=Nyshporka was installed, but did not say where the command ended up.%nPlease write to %1
english.SpaceTitle=Where Nyshporka will live
english.SpaceSub=One folder for everything: the program, the reading engines and your records.
english.SpaceDesc=This folder will hold the program, the reading engines (up to 4 GB) and all your research: scans, readings, notes. Choose a drive with plenty of space, for example D:. You can move it later with “nysh relocate”.
english.SpaceRoot=Choose a separate folder at least two levels below the drive root, for example D:\Genealogy\Nyshporka.
english.SpaceSystem=This is a system folder or too broad. Create a separate folder inside it, for example %1\Nyshporka.
english.SpaceCloud=This folder is synced to the cloud (OneDrive, Dropbox etc.). Reading thousands of pages from it looks like a hang. Choose a folder outside the cloud.
english.SpaceLow=Only %1 GB is free on this drive, and about 10 GB is needed. Install here anyway?
english.AgentDoc=Open the guide: how to connect an assistant (Claude or Codex)
english.FinishAgent=Next, connect an assistant: Claude or Codex. It does the research, and the Nyshporka window shows what has been done.
polish.AppComment=Odczyt rękopiśmiennych dokumentów archiwalnych
polish.SiteName=Strona rodziny
polish.SiteComment=Strona rodu z kanonu Nyszporki
polish.PresetTitle=Co instalujemy
polish.PresetSub=Nyshporkę instalują bardzo różni ludzie.
polish.PresetDesc=Odpowiedź można zmienić w każdej chwili poleceniem „nysh sections” — nic nie trzeba instalować od nowa.
polish.PresetCatalog=Tylko katalogi archiwów — dowiedzieć się, gdzie są metryki wsi.%nBez odczytu rękopisów i bez szukania rodu w odczytanym.
polish.PresetResearcher=Wszystko (zalecane): katalogi, odczyt rękopisów i szukanie rodu w odczytanym.%nSilniki odczytu pod Twoją kartę graficzną: 2,5–4 GB i kilka minut.
polish.UnknownPreset=Nieznany zestaw „%1”.%nDostępne: catalog | amateur | researcher | lab
polish.Installing=Instalujemy Nyshporkę — to może potrwać kilka minut…
polish.NoPowerShell=Nie udało się uruchomić PowerShell. Instalacja przerwana.
polish.NoErrorText=Tekst błędu nie został zapisany. Dziennik: %1
polish.AdminHint=Jeśli przyczyna nie jest wymieniona powyżej, uruchom instalator prawym przyciskiem myszy → „Uruchom jako administrator”. Wszystko trafi wtedy do profilu konta, z którego go uruchomiono.
polish.InstallFailed=Instalacja nie została ukończona (kod %1).
polish.NoCommand=Nyshporka została zainstalowana, ale nie podała, gdzie jest polecenie.%nNapisz proszę na %1
polish.SpaceTitle=Gdzie zamieszka Nyshporka
polish.SpaceSub=Jeden folder na wszystko: program, silniki odczytu i Twoje sprawy.
polish.SpaceDesc=Tu będą program, silniki odczytu (do 4 GB) i całe badanie: skany, odczytane teksty, notatki. Wybierz dysk z dużą ilością miejsca, np. D:. Później można przenieść poleceniem „nysh relocate”.
polish.SpaceRoot=Potrzebny osobny folder co najmniej dwa poziomy od katalogu głównego dysku, np. D:\Genealogy\Nyshporka.
polish.SpaceSystem=To folder systemowy lub zbyt ogólny. Utwórz w nim osobny, np. %1\Nyshporka.
polish.SpaceCloud=Folder jest synchronizowany z chmurą (OneDrive, Dropbox itp.). Czytanie tysięcy stron z takiego folderu wygląda jak zawieszenie. Wybierz folder poza chmurą.
polish.SpaceLow=Na tym dysku wolne jest tylko %1 GB, a potrzeba około 10 GB. Instalować tu mimo to?
polish.AgentDoc=Otwórz instrukcję: jak podłączyć asystenta (Claude lub Codex)
polish.FinishAgent=Dalej podłącz asystenta: Claude lub Codex. To on prowadzi badanie, a okno Nyshporki pokazuje, co zrobiono.
romanian.AppComment=Citirea dosarelor de arhivă scrise de mână
romanian.SiteName=Site-ul familiei
romanian.SiteComment=Site-ul neamului din canonul Nyshporka
romanian.PresetTitle=Ce instalăm
romanian.PresetSub=Nyshporka este instalată de oameni foarte diferiți.
romanian.PresetDesc=Răspunsul poate fi schimbat oricând cu comanda „nysh sections” — nu trebuie reinstalat nimic.
romanian.PresetCatalog=Doar cataloagele arhivelor — aflați unde sunt registrele satului.%nFără citirea manuscriselor și fără căutarea familiei în textul citit.
romanian.PresetResearcher=Totul (recomandat): cataloage, citirea manuscriselor și căutarea familiei în textul citit.%nMotoare de citire pentru placa video: 2,5–4 GB și câteva minute.
romanian.UnknownPreset=Set necunoscut „%1”.%nPosibile: catalog | amateur | researcher | lab
romanian.Installing=Se instalează Nyshporka — poate dura câteva minute…
romanian.NoPowerShell=Nu s-a putut porni PowerShell. Instalarea a fost întreruptă.
romanian.NoErrorText=Textul erorii nu s-a păstrat. Jurnal: %1
romanian.AdminHint=Dacă cauza nu este numită mai sus, încercați să porniți programul de instalare cu clic dreapta → „Executare ca administrator”. Atunci totul va merge în profilul contului cu care a fost pornit.
romanian.InstallFailed=Instalarea nu s-a încheiat (cod %1).
romanian.NoCommand=Nyshporka a fost instalată, dar nu a spus unde se află comanda.%nScrieți, vă rugăm, la %1
romanian.SpaceTitle=Unde va locui Nyshporka
romanian.SpaceSub=Un singur dosar pentru tot: programul, motoarele de citire și dosarele dvs.
romanian.SpaceDesc=Aici vor fi programul, motoarele de citire (până la 4 GB) și toată cercetarea: scanări, texte citite, note. Alegeți un disc cu mult spațiu, de exemplu D:. Mai târziu îl puteți muta cu „nysh relocate”.
romanian.SpaceRoot=Alegeți un dosar separat, la cel puțin două niveluri de rădăcina discului, de exemplu D:\Genealogy\Nyshporka.
romanian.SpaceSystem=Acesta este un dosar de sistem sau prea larg. Creați în el un dosar separat, de exemplu %1\Nyshporka.
romanian.SpaceCloud=Dosarul este sincronizat cu cloudul (OneDrive, Dropbox etc.). Citirea a mii de pagini de acolo arată ca o blocare. Alegeți un dosar în afara cloudului.
romanian.SpaceLow=Pe acest disc sunt libere doar %1 GB, iar sunt necesari circa 10 GB. Instalați aici totuși?
romanian.AgentDoc=Deschideți ghidul: cum se conectează asistentul (Claude sau Codex)
romanian.FinishAgent=Apoi conectați un asistent: Claude sau Codex. El face cercetarea, iar fereastra Nyshporka arată ce s-a făcut.
french.AppComment=Lecture de dossiers d'archives manuscrits
french.SiteName=Site de famille
french.SiteComment=Le site de famille tiré du canon Nyshporka
french.PresetTitle=Que faut-il installer
french.PresetSub=Nyshporka est installée par des personnes très différentes.
french.PresetDesc=Vous pouvez changer cette réponse à tout moment avec la commande « nysh sections » — rien à réinstaller.
french.PresetCatalog=Catalogues d'archives seulement — savoir où sont les registres du village.%nSans lecture des manuscrits ni recherche de la famille dans le texte lu.
french.PresetResearcher=Tout (recommandé) : catalogues, lecture des manuscrits et recherche de la famille dans le texte lu.%nMoteurs de lecture adaptés à votre carte graphique : 2,5–4 Go et quelques minutes.
french.UnknownPreset=Profil inconnu « %1 ».%nPossibles : catalog | amateur | researcher | lab
french.Installing=Installation de Nyshporka — cela peut prendre quelques minutes…
french.NoPowerShell=Impossible de lancer PowerShell. Installation interrompue.
french.NoErrorText=Le texte de l'erreur n'a pas été conservé. Journal : %1
french.AdminHint=Si la cause n'est pas indiquée plus haut, essayez de lancer l'installeur par clic droit → « Exécuter en tant qu'administrateur ». Tout ira alors dans le profil du compte avec lequel il a été lancé.
french.InstallFailed=L'installation ne s'est pas terminée (code %1).
french.NoCommand=Nyshporka est installée, mais n'a pas indiqué où se trouve la commande.%nÉcrivez-nous, s'il vous plaît, à %1
french.SpaceTitle=Où Nyshporka va vivre
french.SpaceSub=Un seul dossier pour tout : le programme, les moteurs de lecture et vos dossiers.
french.SpaceDesc=Ce dossier contiendra le programme, les moteurs de lecture (jusqu'à 4 Go) et toute la recherche : scans, lectures, notes. Choisissez un disque avec beaucoup de place, par exemple D:. Vous pourrez le déplacer plus tard avec « nysh relocate ».
french.SpaceRoot=Choisissez un dossier séparé, au moins deux niveaux sous la racine du disque, par exemple D:\Genealogy\Nyshporka.
french.SpaceSystem=C'est un dossier système ou trop large. Créez-y un dossier séparé, par exemple %1\Nyshporka.
french.SpaceCloud=Ce dossier est synchronisé avec le cloud (OneDrive, Dropbox, etc.). Lire des milliers de pages depuis ce dossier ressemble à un blocage. Choisissez un dossier hors du cloud.
french.SpaceLow=Seuls %1 Go sont libres sur ce disque, il en faut environ 10. Installer ici quand même ?
french.AgentDoc=Ouvrir le guide : comment connecter un assistant (Claude ou Codex)
french.FinishAgent=Ensuite, connectez un assistant : Claude ou Codex. Il mène la recherche, et la fenêtre de Nyshporka montre ce qui a été fait.
german.AppComment=Lesen handschriftlicher Archivakten
german.SiteName=Familienseite
german.SiteComment=Die Familienseite aus dem Nyshporka-Kanon
german.PresetTitle=Was wird installiert
german.PresetSub=Nyshporka wird von sehr unterschiedlichen Menschen installiert.
german.PresetDesc=Die Antwort lässt sich jederzeit mit dem Befehl „nysh sections“ ändern — neu installieren müssen Sie nichts.
german.PresetCatalog=Nur Archivkataloge — herausfinden, wo die Kirchenbücher des Dorfes liegen.%nOhne Handschriftenlesen und ohne Familiensuche im Gelesenen.
german.PresetResearcher=Alles (empfohlen): Kataloge, Handschriften lesen und die Familie im Gelesenen suchen.%nLese-Engines für Ihre Grafikkarte: 2,5–4 GB und einige Minuten.
german.UnknownPreset=Unbekanntes Set „%1“.%nMöglich: catalog | amateur | researcher | lab
german.Installing=Nyshporka wird installiert — das kann einige Minuten dauern…
german.NoPowerShell=PowerShell konnte nicht gestartet werden. Installation abgebrochen.
german.NoErrorText=Der Fehlertext wurde nicht gespeichert. Protokoll: %1
german.AdminHint=Wenn die Ursache oben nicht genannt ist, starten Sie den Installer per Rechtsklick → „Als Administrator ausführen“. Dann landet alles im Profil des Kontos, unter dem er gestartet wurde.
german.InstallFailed=Die Installation wurde nicht abgeschlossen (Code %1).
german.NoCommand=Nyshporka wurde installiert, hat aber nicht gemeldet, wo der Befehl liegt.%nBitte schreiben Sie an %1
german.SpaceTitle=Wo Nyshporka wohnen wird
german.SpaceSub=Ein Ordner für alles: das Programm, die Lese-Engines und Ihre Akten.
german.SpaceDesc=Hier liegen das Programm, die Lese-Engines (bis 4 GB) und Ihre gesamte Forschung: Scans, Gelesenes, Notizen. Wählen Sie ein Laufwerk mit viel Platz, z. B. D:. Später lässt es sich mit „nysh relocate“ verschieben.
german.SpaceRoot=Wählen Sie einen eigenen Ordner mindestens zwei Ebenen unter dem Laufwerksstamm, z. B. D:\Genealogy\Nyshporka.
german.SpaceSystem=Das ist ein Systemordner oder zu allgemein. Legen Sie darin einen eigenen an, z. B. %1\Nyshporka.
german.SpaceCloud=Der Ordner wird mit der Cloud synchronisiert (OneDrive, Dropbox usw.). Tausende Seiten von dort zu lesen sieht aus wie ein Hänger. Wählen Sie einen Ordner außerhalb der Cloud.
german.SpaceLow=Auf diesem Laufwerk sind nur %1 GB frei, benötigt werden etwa 10 GB. Trotzdem hier installieren?
german.AgentDoc=Anleitung öffnen: einen Assistenten verbinden (Claude oder Codex)
german.FinishAgent=Als Nächstes verbinden Sie einen Assistenten: Claude oder Codex. Er führt die Forschung, und das Nyshporka-Fenster zeigt, was erledigt ist.
#ifdef WITH_RU
russian.AppComment=Чтение рукописных архивных дел
russian.SiteName=Сайт семьи
russian.SiteComment=Сайт рода из канона Нышпорки
russian.PresetTitle=Что ставим
russian.PresetSub=Нышпорку ставят очень разные люди.
russian.PresetDesc=Изменить ответ можно в любой момент командой «nysh sections» — переустанавливать ничего не придётся.
russian.PresetCatalog=Только каталоги архивов — узнать, где лежат метрики села.%nБез чтения рукописей и без поиска рода в прочитанном.
russian.PresetResearcher=Всё (рекомендуется): каталоги, чтение рукописей и поиск рода в прочитанном.%nДвижки чтения под вашу видеокарту: 2.5–4 ГБ и несколько минут.
russian.UnknownPreset=Неизвестный набор «%1».%nМожно: catalog | amateur | researcher | lab
russian.Installing=Ставим Нышпорку — это может занять несколько минут…
russian.NoPowerShell=Не удалось запустить PowerShell. Установка прервана.
russian.NoErrorText=Текст ошибки не сохранился. Журнал: %1
russian.AdminHint=Если причина выше не названа — попробуйте запустить установщик правой кнопкой мыши → «Запуск от имени администратора». Тогда всё встанет в профиль той учётной записи, от имени которой он запущен.
russian.InstallFailed=Установка не завершилась (код %1).
russian.NoCommand=Нышпорка установилась, но не сказала, где оказалась команда.%nНапишите, пожалуйста, на %1
russian.SpaceTitle=Где будет жить Нышпорка
russian.SpaceSub=Одна папка для всего: программа, движки чтения и ваши дела.
russian.SpaceDesc=Здесь будут программа, движки чтения (до 4 ГБ) и всё исследование: сканы, прочитанное, заметки. Выберите диск, где много места, например D:. Позже перенести можно командой «nysh relocate».
russian.SpaceRoot=Нужна отдельная папка не меньше чем на два уровня от корня диска, например D:\Genealogy\Nyshporka.
russian.SpaceSystem=Это системная или слишком общая папка. Создайте в ней отдельную, например %1\Nyshporka.
russian.SpaceCloud=Папка синхронизируется с облаком (OneDrive, Dropbox и т. п.). Чтение тысяч страниц из такой папки выглядит как зависание. Выберите папку вне облака.
russian.SpaceLow=На этом диске свободно лишь %1 ГБ, а нужно около 10 ГБ. Всё равно ставить сюда?
russian.AgentDoc=Открыть инструкцию: как подключить помощника (Claude или Codex)
russian.FinishAgent=Дальше — подключите помощника: Claude или Codex. Он ведёт исследование, а окно Нышпорки показывает, что сделано.
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
Name: "{group}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{code:GetWorkDir}"; IconFilename: "{app}\nyshporka.ico"; Comment: "{cm:AppComment}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{code:GetWorkDir}"; IconFilename: "{app}\nyshporka.ico"; Tasks: desktopicon
; Сайт роду — той самий застосунок, вкладка одразу на /site/ (`serve --page site`).
Name: "{group}\{cm:SiteName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve --page site"; WorkingDir: "{code:GetWorkDir}"; IconFilename: "{app}\nyshporka.ico"; Comment: "{cm:SiteComment}"
Name: "{autodesktop}\{cm:SiteName}"; Filename: "{code:GetNyshExe}"; Parameters: "serve --page site"; WorkingDir: "{code:GetWorkDir}"; IconFilename: "{app}\nyshporka.ico"; Comment: "{cm:SiteComment}"; Tasks: desktopicon

[Run]
; 🔴 `nowait` обов'язковий: `nysh serve` піднімає сервер і БЛОКУЄ потік до
; кінця життя процесу. Без цього прапорця майстер завис би на останньому кроці
; назавжди, і виглядало б це як зависле встановлення.
; Браузер відкриває сам застосунок — `serve` робить це через секунду після
; старту, тож глушити його `--no-browser` не треба.
Filename: "{code:GetNyshExe}"; Parameters: "serve"; WorkingDir: "{code:GetWorkDir}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; 🤝 Основний режим роботи — з помічником (Claude, Codex). Галочка відкриває
; інструкцію, як його підключити, мовою майстра.
Filename: "{code:AgentDocUrl}"; Description: "{cm:AgentDoc}"; Flags: shellexec nowait postinstall skipifsilent

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
  SpacePage: TInputDirWizardPage;
  // Тека, де житиме все (простір дослідження). Порожньо — оновлення поверх
  // старої установки: простір уже є, і `windows.ps1` знайде його сам.
  SpaceDir: String;
  // Набір попередньої установки. При оновленні НЕ перепитуємо: сторінка з
  // типовим «Усе» перевела б людину з легким набором на 2.5–4 ГБ рушіїв, а з
  // `lab` (у майстрі лише два пункти) — мовчки зняла б тренування. Змінити
  // набір — `nysh sections`.
  PrevPreset: String;
  ResolvedNysh: String;

const
  PRESET_RESEARCHER = 0;
  PRESET_CATALOG = 1;
  // Скільки потрібно вільного місця: рушії 2.5–4 ГБ, кеш uv, моделі й перші
  // справи. Менше — питаємо, а не мовчимо.
  MIN_FREE_MB = 10240;
  DRIVE_FIXED = 3;

function GetDriveType(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function IsUpgrade(): Boolean;
begin
  Result := WizardForm.PrevAppDir <> '';
end;

function FreeMB(Dir: String): Int64;
var
  Free, Total: Int64;
begin
  Result := -1;
  if GetSpaceOnDisk64(AddBackslash(ExtractFileDrive(Dir)), Free, Total) then
    Result := Free div (1024 * 1024);
end;

function IsSynced(Dir: String): Boolean;
var
  L: String;
begin
  L := Lowercase(Dir);
  Result := (Pos('onedrive', L) > 0) or (Pos('dropbox', L) > 0) or
            (Pos('google drive', L) > 0) or (Pos('icloud', L) > 0) or
            (Pos('yandex', L) > 0);
end;

// 🔴 Типова тека — «Документи\Нишпорка», як і досі в `nysh init`. Але якщо
// на диску профілю мало місця, а є інший внутрішній диск, де його більше,
// пропонуємо його: саме так людина з відео впиралась у повний C:.
function DefaultSpace(): String;
var
  Docs, Cand: String;
  Best: Int64;
  Got: Int64;
  C: Integer;
  Root: String;
begin
  Docs := ExpandConstant('{userdocs}');
  if IsSynced(Docs) then
    Docs := ExpandConstant('{%USERPROFILE}');
  Result := AddBackslash(Docs) + '{#AppName}';
  Best := FreeMB(Result);
  if (Best < 0) or (Best >= 3 * MIN_FREE_MB) then
    Exit;
  for C := Ord('D') to Ord('Z') do
  begin
    Root := Chr(C) + ':\';
    if GetDriveType(Root) <> DRIVE_FIXED then
      Continue;
    Got := FreeMB(Root);
    if Got > Best then
    begin
      Best := Got;
      Cand := Root + 'Genealogy\{#AppName}';
    end;
  end;
  if Cand <> '' then
    Result := Cand;
end;

// Ті самі межі, що `core.workspace.validate_root`: інакше майстер прийняв би
// теку, яку `nysh init` потім відкине, — уже після хвилин завантаження.
function CheckSpace(Dir: String): Boolean;
var
  Depth, I: Integer;
  Low: Int64;
begin
  Result := False;
  Depth := 0;
  for I := 1 to Length(Dir) do
    if Dir[I] = '\' then
      Depth := Depth + 1;
  if (Length(Dir) < 3) or (Dir[2] <> ':') or (Depth < 2) then
  begin
    MsgBox(CustomMessage('SpaceRoot'), mbError, MB_OK);
    Exit;
  end;
  if (CompareText(Dir, ExpandConstant('{%USERPROFILE}')) = 0) or
     (CompareText(Dir, ExpandConstant('{userdocs}')) = 0) or
     (CompareText(Dir, ExpandConstant('{userdesktop}')) = 0) or
     (CompareText(Dir, ExpandConstant('{%USERPROFILE}\Downloads')) = 0) or
     (CompareText(Dir, ExpandConstant('{win}')) = 0) or
     (CompareText(Dir, ExpandConstant('{commonpf}')) = 0) then
  begin
    MsgBox(FmtMessage(CustomMessage('SpaceSystem'), [Dir]), mbError, MB_OK);
    Exit;
  end;
  if IsSynced(Dir) then
  begin
    MsgBox(CustomMessage('SpaceCloud'), mbError, MB_OK);
    Exit;
  end;
  Low := FreeMB(Dir);
  if (Low >= 0) and (Low < MIN_FREE_MB) then
    if MsgBox(FmtMessage(CustomMessage('SpaceLow'), [IntToStr(Low div 1024)]),
              mbConfirmation, MB_YESNO) = IDNO then
      Exit;
  Result := True;
end;

// `{app}` = `<простір>\.program`. Ставиться щоразу, коли змінився простір, —
// і до першої сторінки (тихий режим сторінок не бачить).
procedure UseSpace(Dir: String);
begin
  SpaceDir := RemoveBackslashUnlessRoot(Trim(Dir));
  WizardForm.DirEdit.Text := AddBackslash(SpaceDir) + '.program';
end;

procedure InitializeWizard();
var
  Quiet, Prev, Moved: String;
begin
  // 🗂 Де жити Нишпорці — одразу після ліцензії: від цієї відповіді залежить
  // усе інше, і людина має бачити її першою, а не дізнатись про C: з помилки.
  SpacePage := CreateInputDirPage(wpLicense,
    CustomMessage('SpaceTitle'), CustomMessage('SpaceSub'),
    CustomMessage('SpaceDesc'), False, '');
  SpacePage.Add('');

  // 🔴 Набір питаємо, а не вирішуємо за людину: різниця між гілками — 2.5 ГБ і
  // кілька хвилин чекання. Типово ПОВНИЙ (рішення дослідника 16.10.2026):
  // основний режим — читання й пошук роду з помічником, а легкий набір лише
  // для того, хто свідомо прийшов тільки по каталог.
  PresetPage := CreateInputOptionPage(wpSelectTasks,
    CustomMessage('PresetTitle'), CustomMessage('PresetSub'),
    CustomMessage('PresetDesc'), True, False);
  // Рушії читання й моделі цей варіант доставляє сам (`windows.ps1`, крок 4½),
  // а torch підбирає під відеокарту NVIDIA, якщо драйвер її показує.
  PresetPage.Add(CustomMessage('PresetResearcher'));
  PresetPage.Add(CustomMessage('PresetCatalog'));
  PresetPage.SelectedValueIndex := PRESET_RESEARCHER;

  if IsUpgrade() then
  begin
    // 🔴 Оновлення установки «одна тека» мусить знову передати `-Workspace`,
    // інакше `windows.ps1` поставить нову версію в типові теки uv на C:.
    // Програма, перенесена `nysh relocate`, лишає в старому сліді
    // `relocated_to` — тоді ставимо туди, а не в стару теку.
    Prev := AddBackslash(WizardForm.PrevAppDir) + 'install-info.ini';
    PrevPreset := Lowercase(GetIniString('nyshporka', 'preset', '', Prev));
    if (PrevPreset <> 'catalog') and (PrevPreset <> 'amateur')
       and (PrevPreset <> 'researcher') and (PrevPreset <> 'lab') then
      PrevPreset := '';
    Moved := GetIniString('nyshporka', 'relocated_to', '', Prev);
    if Moved <> '' then
      Prev := AddBackslash(Moved) + 'install-info.ini';
    Quiet := GetIniString('nyshporka', 'workspace', '', Prev);
    if Quiet <> '' then
      UseSpace(Quiet);
    Exit;
  end;
  // Тихий режим: `/WORKSPACE=D:\Genealogy\Нишпорка`. Без нього — типова, але
  // хто передав лише старий `/DIR=`, той отримує стару розкладку.
  Quiet := ExpandConstant('{param:workspace|}');
  if Quiet <> '' then
    UseSpace(Quiet)
  else if not (WizardSilent and (ExpandConstant('{param:dir|}') <> '')) then
    UseSpace(DefaultSpace());
  SpacePage.Values[0] := SpaceDir;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = SpacePage.ID) and IsUpgrade()) or
            ((PageID = PresetPage.ID) and (PrevPreset <> ''));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = SpacePage.ID then
  begin
    Result := CheckSpace(RemoveBackslashUnlessRoot(Trim(SpacePage.Values[0])));
    if Result then
      UseSpace(SpacePage.Values[0]);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + CustomMessage('FinishAgent');
end;

// Тека для `windows.ps1 -PythonDir`; порожньо — типова скрипта (`{app}\python`,
// тобто в розкладці «одна тека» — під простором). Окремої сторінки більше
// немає: теку обирають одну на все. Тихий режим: `/PYTHONDIR=D:\Nyshporka\python`.
function PythonDirFlag(): String;
var
  Dir: String;
begin
  Dir := ExpandConstant('{param:pythondir|}');
  Result := '';
  if Dir <> '' then
    Result := ' -PythonDir "' + Dir + '"';
end;

// Простір для `windows.ps1 -Workspace`. Порожньо — оновлення: не чіпаємо.
function WorkspaceFlag(): String;
begin
  Result := '';
  if SpaceDir <> '' then
    Result := ' -Workspace "' + SpaceDir + '"';
end;

function SelectedPreset(): String;
var
  Quiet: String;
begin
  Result := 'researcher';
  if PrevPreset <> '' then
    Result := PrevPreset;
  if WizardSilent then
  begin
    // Тихий режим (агенти, димовий прогін у CI) сторінок не показує, тож набір
    // приходить параметром: `nyshporka-setup.exe /VERYSILENT /PRESET=catalog`.
    // Без параметра — набір попередньої установки, а на свіжій — повний.
    Quiet := Lowercase(ExpandConstant('{param:preset|' + Result + '}'));
    // 🔴 Звіряємо ТУТ. Невідоме ім'я інакше доїхало б до `nysh init` і впало на
    // останньому кроці — коли інтерпретатор і пакети вже завантажено, тобто
    // через хвилини чекання й уже без права на другу спробу задарма.
    if (Quiet <> 'catalog') and (Quiet <> 'amateur')
       and (Quiet <> 'researcher') and (Quiet <> 'lab') then
      RaiseException(FmtMessage(CustomMessage('UnknownPreset'), [Quiet]));
    Result := Quiet;
  end
  else if (PrevPreset = '') and (PresetPage.SelectedValueIndex = PRESET_CATALOG) then
    Result := 'catalog';
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

// Робоча тека ярликів і запуску: простір, щоб `nysh serve` знаходив його за
// маркером, а не вгадував. Стара розкладка простору в сліді не має — `{app}`.
function GetWorkDir(Param: String): String;
begin
  Result := GetIniString('nyshporka', 'workspace', '', InfoFile());
  if (Result = '') or not DirExists(Result) then
    Result := ExpandConstant('{app}');
end;

// Інструкція «як підключити помічника» мовою майстра (якір є в кожному перекладі).
function AgentDocUrl(Param: String): String;
begin
  Result := 'https://nyshporka.online/docs/';
  if LangCode() <> 'uk' then
    Result := Result + LangCode() + '/';
  Result := Result + 'install/#pomichnyk';
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
            WorkspaceFlag() +
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
