# Instalați și conectați asistentul

Calea principală — fără nicio comandă: trei programe în ordinea potrivită și
o cerere gata făcută. Durează 30–40 de minute, cea mai mare parte a timpului
este descărcarea.

!!! note "De ce nu chatul de pe site"

    În chatul de pe claude.ai sau chatgpt.com Nyshporka nu funcționează:
    chatul răspunde cu text și nu are acces la discul dumneavoastră. Este
    nevoie de un **program-asistent**, care vorbește la fel ca un chat, dar
    execută singur acțiuni pe calculator și cere permisiunea înaintea
    fiecăreia.

!!! tip "Același lucru pe video"

    Lecțiile 3–5 din [seria video](https://nyshporka.online/ro/uroky) arată
    instalarea pe Windows pas cu pas. Asistentul din video este Codex (vedeți
    „Alți asistenți” mai jos); cu Claude Desktop ordinea este aceeași: Git,
    Nyshporka, asistentul, dosarul de lucru, cererea gata scrisă. Lecțiile
    sunt în ucraineană, cu subtitrări în română.

## Ce este necesar

* Windows 10 sau 11, macOS ori Linux.
* Aproximativ 5 GB de spațiu liber: modelele de citire și tot ce le trebuie —
  2.5 GB.
* Un abonament **Claude Pro sau Max** — pentru Claude Desktop
  ([planuri](https://claude.com/pricing)). Sau un abonament ChatGPT — pentru
  Codex. Nyshporka însăși este gratuită: plătiți doar pentru asistent.

## Pasul 1. Git for Windows

Descărcați [Git for Windows](https://git-scm.com/downloads/win) și instalați-l,
apăsând peste tot „Next”. Fără el, în Claude Desktop nu se deschide fila
Code, iar Nyshporka are nevoie de el ca să instaleze modelele de citire. Pe
macOS, Git există de obicei deja.

## Pasul 2. Instalați Nyshporka

Nyshporka se instalează **după Git**: fără el nu se instalează programul de
citire a manuscriselor. Asistentul — ultimul (de ce — la pasul 3).

=== "Windows"

    1. [:material-download: Descărcați programul de instalare](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       și porniți-l.
    2. Dacă Windows afișează **„Windows v-a protejat PC-ul”** — „Mai multe
       informații” → „Executare oricum”. Așa întâmpină Windows orice program
       pe care încă puțini l-au descărcat. Dacă însă antivirusul numește
       programul de instalare troian și șterge fișierul, vedeți [„Antivirusul a numit programul de instalare troian”](#defender).
    3. Pe pagina «Де жити Нишпорці» (Unde va locui Nyshporka) alegeți un director
       pe un disc cu mult spațiu (sunt necesari circa 10 GB), de exemplu
       `D:\Genealogy\Nyshporka`. În acest singur director va sta tot: programul,
       motoarele de citire și cercetarea dumneavoastră.
    4. La întrebarea «Що ставимо» (Ce instalăm) lăsați **«Усе (рекомендовано)»**
       (Tot, recomandat). Setul ușor înseamnă doar cataloagele arhivelor, fără
       citirea manuscriselor și fără căutarea neamului.
    5. La final lăsați bifate ambele căsuțe: «Запустити Нишпорку» (Porniți
       Nyshporka) deschide aplicația în browser (este calculatorul
       dumneavoastră, nu un site: funcționează și fără internet), iar a doua
       deschide acest ghid la pasul următor.

=== "macOS și Linux"

    Deschideți „Terminal”, lipiți un singur rând și apăsați Enter:

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    Când scriptul se termină, închideți fereastra terminalului.

## Pasul 3. Claude Desktop { #pomichnyk }

1. Descărcați aplicația:
   [Windows](https://claude.ai/api/desktop/win32/x64/setup/latest/redirect),
   [macOS](https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect).
2. Porniți-o și conectați-vă la contul dumneavoastră.
3. Apăsați fila **Code** din partea de sus, la mijloc.

!!! warning "Dacă Claude era deja instalat pe calculator"

    Închideți-l **complet** — clic dreapta pe pictograma de lângă ceas →
    «Вийти» (Quit) — și deschideți-l din nou. Programul își amintește unde
    să caute comenzile în momentul pornirii, așa că nu știe de Nyshporka
    abia instalată. Simptom: asistentul scrie că comanda `nysh` nu a fost
    găsită.

## Pasul 4. Deschideți directorul de lucru

În fila Code, înainte de a scrie ceva:

1. Alegeți **Local** — asistentul va lucra pe calculatorul dumneavoastră.
2. **Select folder** → directorul ales în programul de instalare, pe pagina
   «Де жити Нишпорці» (Unde va locui Nyshporka), implicit `Документи\Нишпорка`
   (Documente\Nyshporka). Acolo vor sta scanările, textul citit și notițele.
   Dacă ați uitat unde este, calea este scrisă în partea de jos a paginii
   principale a aplicației.
3. Modul de permisiuni — **Manual**: asistentul va întreba înaintea fiecărei
   acțiuni, iar dumneavoastră vedeți ce face exact.

## Pasul 5. Lipiți cererea gata făcută

Copiați textul integral în câmpul de introducere și apăsați Enter:

```text
Citește https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
Mai întâi spune-mi pe scurt ce este Nyshporka și ce vom face acum.
Apoi fă după instrucțiune tot ce trebuie ca Nyshporka să fie gata pe acest calculator: verifică
calculatorul, la nevoie instalează motoarele de citire și modelele și pune skill-urile pentru toate
proiectele. Explică-mi fiecare pas în cuvinte simple.
Când totul e verde — întreabă-mă ce nume de familie caut și în ce grafii.
```

Asistentul va citi instrucțiunea scrisă pentru el și, cerând de fiecare dată
permisiunea:

* va verifica calculatorul (`nysh doctor`);
* va instala modelele de citire (`nysh htr install`, `nysh models get`) —
  acesta este cel mai lung pas, aproximativ 2.5 GB;
* va pune skill-urile — proceduri de lucru gata făcute
  (`nysh skills install --user`);
* va întreba ce nume de familie căutăm.

Este gata când asistentul spune că verificarea nu are rânduri roșii și vă
întreabă numele de familie. Mai departe — [„Cum se lucrează”](start.md).

## Alți asistenți

**Codex** (OpenAI, abonament ChatGPT):
[aplicația](https://learn.chatgpt.com/docs/quickstart) sau
[versiunea pentru terminal](https://learn.chatgpt.com/docs/cli). Pașii 1 și 2
sunt aceiași; la pasul 4 deschideți directorul `Документи\Нишпорка`; în cerere,
în loc de „pune skill-urile pentru toate proiectele”, scrieți „pune
skill-urile în directorul `~/.agents/skills`”.

**Claude Code în terminal** — ajung un singur rând și pornirea:

```powershell
nysh skills install --user   # скіли для всіх проєктів
claude
```

**Alții** — orice asistent care citește skill-uri în formatul `SKILL.md`
(Agent Skills), inclusiv OpenClaw. Ca să le puneți în directorul lui:
`nysh skills install --target <тека>`.

## Dacă ceva nu merge { #yakshcho-shchos-ne-tak }

| ce vedeți | ce să faceți |
|---|---|
| asistentul: „comanda `nysh` nu a fost găsită” | Închideți complet Claude (pictograma de lângă ceas → Quit) și deschideți-l din nou. În terminal — deschideți o fereastră nouă; dacă nu ajută — reporniți calculatorul |
| fila Code propune actualizarea planului | Este nevoie de un abonament Claude Pro sau Max |
| asistentul: „mediul motoarelor nu este pregătit” | Spuneți-i: „instalează motoarele de citire și modelele” |
| asistentul: „torch nu se încarcă”, „lipsește Visual C++” | Spuneți-i: „instalează motoarele de citire”. Nyshporka va instala componenta Microsoft Visual C++ — Windows va cere permisiunea de administrator, acceptați |
| asistentul nu vede directorul cu scanări | Directorul se află în afara directorului de lucru; asistentul trebuie să ceară permisiunea de a-l lua în evidență (`nysh roots add`). Fișierele nu se mută nicăieri |
| programul de instalare s-a încheiat cu „cod 1” | Uitați-vă la ultimele rânduri ale ieșirii. Cel mai des — o descărcare întreruptă, lipsă de spațiu sau un antivirus |
| altceva | [Scrieți autorului](https://github.com/SERGIUSH-UA/nyshporka/issues), adăugând cuvânt cu cuvânt ce a scris asistentul |

### Antivirusul a numit programul de instalare troian { #defender }

Microsoft Defender marchează uneori `nyshporka-setup.exe` drept troian, cel mai
des cu un nume de felul `Trojan:Win32/Bearfoos.B!ml`. Terminația `!ml`
înseamnă că programul a fost suspectat de un model automat după trăsături
generale, nu că s-a găsit în el un virus cunoscut. Așa se întâmplă cu
programele fără semnătură digitală, pe care încă puțini le-au descărcat.

Înainte de a permite fișierul, verificați că este autentic:

1. Programul de instalare trebuie descărcat cu butonul de pe această pagină sau
   de pe [pagina versiunilor](https://github.com/SERGIUSH-UA/nyshporka/releases) de pe GitHub. Un fișier primit pe altă
   cale (mesagerie, site de partajare, site străin) ștergeți-l și descărcați-l
   din nou.
2. Restaurați fișierul din carantină: „Securitate Windows” → „Protecție
   împotriva virușilor și amenințărilor” → „Istoric protecție” → intrarea
   despre fișier → „Acțiuni” → „Restaurare”. Deocamdată nu-l rulați.
3. Deschideți PowerShell (Start → tastați `PowerShell`) și lipiți trei rânduri.
   Dacă fișierul nu este în „Descărcări”, schimbați calea din primul rând:

    ```powershell
    $f = "$env:USERPROFILE\Downloads\nyshporka-setup.exe"
    $r = Invoke-RestMethod https://api.github.com/repos/SERGIUSH-UA/nyshporka/releases/latest
    ($r.assets | Where-Object name -eq 'nyshporka-setup.exe').digest -eq ('sha256:' + (Get-FileHash $f).Hash.ToLower())
    ```

- **`True`**: fișierul coincide cu ultima versiune de pe GitHub, detectarea
  este falsă. Rulați programul de instalare. Dacă Defender îl șterge din nou,
  în „Istoric protecție” alegeți „Se permite pe dispozitiv”.
- **`False`**: fișierul nu este cel corect sau între timp a apărut o versiune
  nouă. Nu-l rulați: ștergeți-l și descărcați-l din nou cu butonul de la
  pasul 2. Dacă și noul fișier dă `False`, [scrieți autorului](https://github.com/SERGIUSH-UA/nyshporka/issues).

## Fără asistent sau cu Python

Dacă Python sau `uv` există deja, pachetul se instalează din PyPI:

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install "nyshporka[app,archives,htr]"
nysh init                      # створити робочу теку
nysh doctor                    # перевірити машину
nysh serve                     # відкрити застосунок у браузері
nysh htr install               # середовище для моделей читання, разово
nysh models get                # моделі читання, ~225 МБ, разово
```

Programul de instalare într-un singur rând pentru Windows fără Python — în
PowerShell:

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```

??? note "Pentru avansați: seturi, parametrii programului de instalare, unde se află cercetarea"

    **Seturi.** `nysh init` întreabă ce veți folosi; se poate schimba oricând
    — `nysh sections`, fără reinstalare.

    | set | ce conține |
    |---|---|
    | `catalog` | cataloage, dicționar geografic, inventare ale fondurilor — fără modele de citire, economisește ~2.5 GB |
    | `amateur` | + citirea manuscrisului și răsfoitorul |
    | `researcher` (implicit) | + căutare în textul citit, evidență, export |
    | `lab` | + marcarea rândurilor și antrenarea suplimentară a modelelor (`nysh train`) |

    **Parametri.** La fel pentru scripturi și `.exe`:

    | ce setăm | `windows.ps1` | `unix.sh` | `.exe` |
    |---|---|---|---|
    | setul | `-Preset catalog` | `NYSH_PRESET=catalog` | `/PRESET=catalog` |
    | componența pachetului în întregime | `-Source 'nyshporka[app,archives]'` | `NYSH_SOURCE=…` | — |
    | o versiune anume | `-Version X.Y.Z` | prin `NYSH_SOURCE` | inclusă în fișier |
    | un singur director pentru tot | `-Workspace D:\Genealogy\Nyshporka -Home_ D:\Genealogy\Nyshporka\.program` | — | `/WORKSPACE=D:\Genealogy\Nyshporka` |
    | mutarea unei instalări existente | `nysh relocate D:\Genealogy\Nyshporka` | la fel | la fel |
    | fără întrebări | — | — | `/VERYSILENT` |
    | fără pachetul de ghiduri | `-NoCatalog` | `NYSH_NO_CATALOG=1` | — |
    | jurnal | — | — | `/LOG=setup.log` |
    | unde stă cercetarea | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` |

    ⚠ `irm … | iex` nu funcționează pentru scriptul Windows (fișierul are
    UTF-8 BOM) — întâi `-OutFile`, apoi `-File`.

    **Calculatorul dezvoltatorului.** Programul de instalare nu reinstalează
    nimic: `uv` și propriul Python 3.12 se pun în directorul aplicației,
    `pyenv`, `conda` și versiunile pentru CUDA rămân cum erau. În afara
    directoarelor proprii — doar o completare în PATH.
    `sh -s -- --dry-run` arată modificările și nu face nimic,
    `NYSH_NO_MODIFY_PATH=1` nu atinge PATH. Lista modificărilor se scrie în
    `install-trace.txt`.

    **Unde se află cercetarea.** Directorul de lucru (în comenzi — spațiul):

    ```bash
    nysh init D:/Дослідження                      # обрати місце при створенні
    export NYSHPORKA_WORKSPACE=D:/Дослідження     # закріпити для всіх команд
    nysh --workspace D:/Дослідження doctor        # разово
    ```

    Fără variabilă, comenzile caută `nyshporka.toml` în sus de la directorul
    curent. Unde se uită aplicația acum — `nysh doctor`, rândul «Робочий
    простір» (Spațiul de lucru).

    **Mac cu procesor Intel.** Se instalează ca peste tot; `nysh htr install`
    ia Python și torch din conda-forge, pentru că PyPI nu are pentru el
    pachete wheel torch mai noi de 2.2.2.

    **Placa video nu este necesară.** Fără ea o pagină se citește în
    ~20 s – 1 min (în funcție de procesor și de câte rânduri are pagina), cu
    placă — în ~10–15 s. Accelerarea cu placa video — un pas separat, îl va
    sugera `nysh doctor`.
