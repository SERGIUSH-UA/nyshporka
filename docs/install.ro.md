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

## Ce este necesar

* Windows 10 sau 11, macOS ori Linux.
* Aproximativ 5 GB de spațiu liber: modelele de citire și tot ce le trebuie —
  2.5 GB.
* Un abonament **Claude Pro sau Max** — pentru Claude Desktop
  ([planuri](https://claude.com/pricing)). Sau un abonament ChatGPT — pentru
  Codex. Nyshporka însăși este gratuită: plătiți doar pentru asistent.

## Pasul 1. Instalați Nyshporka

Nyshporka se instalează **prima**, asistentul — ultimul (de ce — la pasul 3).

=== "Windows"

    1. [:material-download: Descărcați programul de instalare](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       și porniți-l.
    2. Dacă Windows afișează **„Windows v-a protejat PC-ul”** — „Mai multe
       informații” → „Executare oricum”. Așa întâmpină Windows orice program
       pe care încă puțini l-au descărcat.
    3. La întrebarea «Що ставимо» (Ce instalăm) alegeți **«Каталоги + читання
       рукопису й пошук у прочитаному»** (Cataloage + citirea manuscrisului și
       căutarea în textul citit).
    4. La final lăsați bifa «Запустити Нишпорку» (Porniți Nyshporka) — în
       browser se va deschide aplicația. Este calculatorul dumneavoastră, nu
       un site: funcționează și fără internet.

=== "macOS și Linux"

    Deschideți „Terminal”, lipiți un singur rând și apăsați Enter:

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    Când scriptul se termină, închideți fereastra terminalului.

## Pasul 2. Git for Windows

Descărcați [Git for Windows](https://git-scm.com/downloads/win) și instalați-l,
apăsând peste tot „Next”. Fără el, în Claude Desktop nu se deschide fila
Code, iar Nyshporka are nevoie de el ca să instaleze modelele de citire. Pe
macOS, Git există de obicei deja.

## Pasul 3. Claude Desktop

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
2. **Select folder** → directorul `Документи\Нишпорка` (Documente\Nyshporka).
   L-a creat programul de instalare; acolo vor sta scanările, textul citit și
   notițele. Dacă un asemenea director nu există, „Documentele”
   dumneavoastră se sincronizează cu OneDrive, iar Nyshporka a pus directorul
   alături. Unde anume — vă arată aplicația: **🐾 Огляд** (Prezentare) →
   «Перевірити цю машину» (Verificați acest calculator).
3. Modul de permisiuni — **Manual**: asistentul va întreba înaintea fiecărei
   acțiuni, iar dumneavoastră vedeți ce face exact.

## Pasul 5. Lipiți cererea gata făcută

Copiați textul integral în câmpul de introducere și apăsați Enter:

```text
Citește https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
și fă după el tot ce trebuie ca Nyshporka să fie gata pe acest calculator: verifică
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
| asistentul nu vede directorul cu scanări | Directorul se află în afara directorului de lucru; asistentul trebuie să ceară permisiunea de a-l lua în evidență (`nysh roots add`). Fișierele nu se mută nicăieri |
| programul de instalare s-a încheiat cu „cod 1” | Uitați-vă la ultimele rânduri ale ieșirii. Cel mai des — o descărcare întreruptă, lipsă de spațiu sau un antivirus |
| altceva | [Scrieți autorului](https://github.com/SERGIUSH-UA/nyshporka/issues), adăugând cuvânt cu cuvânt ce a scris asistentul |

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
    | directorul de instalare | `-Home_ D:\Nysh` | — | `/DIR=D:\Nysh` |
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
