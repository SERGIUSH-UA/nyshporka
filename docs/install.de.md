# Installieren und den Assistenten verbinden

Der Hauptweg kommt ohne einen einzigen Befehl aus: drei Programme in der
richtigen Reihenfolge und eine fertige Anfrage. Das dauert 30–40 Minuten, den
größten Teil davon der Download.

!!! note "Warum nicht der Chat auf der Website"

    Im Chat auf claude.ai oder chatgpt.com funktioniert Nyshporka nicht: Der
    Chat antwortet mit Text und hat keinen Zugriff auf Ihre Festplatte. Nötig
    ist ein **Assistenzprogramm**, das sich genauso unterhält wie der Chat,
    aber selbst Aktionen auf dem Computer ausführt und vor jeder um Erlaubnis
    bittet.

## Was Sie brauchen

* Windows 10 oder 11, macOS oder Linux.
* Etwa 5 GB freien Platz: Die Lesemodelle und alles, was sie brauchen — 2.5 GB.
* Ein Abo **Claude Pro oder Max** — für Claude Desktop
  ([Tarife](https://claude.com/pricing)). Oder ein ChatGPT-Abo — für Codex.
  Nyshporka selbst ist kostenlos: Sie zahlen nur für den Assistenten.

## Schritt 1. Nyshporka installieren

Nyshporka wird **zuerst** installiert, der Assistent zuletzt (warum — in
Schritt 3).

=== "Windows"

    1. [:material-download: Installationsprogramm herunterladen](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       und starten.
    2. Wenn Windows meldet **„Der Computer wurde durch Windows geschützt“** —
       „Weitere Informationen“ → „Trotzdem ausführen“. So begrüßt Windows
       jedes Programm, das bisher nur wenige heruntergeladen haben.
    3. Bei der Frage «Що ставимо» (Was installieren wir) wählen Sie
       **«Каталоги + читання рукопису й пошук у прочитаному»** (Kataloge +
       Lesen von Handschrift und Suche im Gelesenen).
    4. Lassen Sie am Ende das Häkchen «Запустити Нишпорку» (Nyshporka starten)
       gesetzt — im Browser öffnet sich die Anwendung. Das ist Ihr Computer,
       keine Website: Sie funktioniert auch ohne Internet.

=== "macOS und Linux"

    Öffnen Sie das „Terminal“, fügen Sie eine Zeile ein und drücken Sie Enter:

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    Wenn das Skript fertig ist, schließen Sie das Terminalfenster.

## Schritt 2. Git for Windows

Laden Sie [Git for Windows](https://git-scm.com/downloads/win) herunter und
installieren Sie es, indem Sie überall auf „Next“ klicken. Ohne Git öffnet
sich in Claude Desktop der Reiter Code nicht, und Nyshporka braucht es, um die
Lesemodelle zu installieren. Unter macOS ist Git meist schon vorhanden.

## Schritt 3. Claude Desktop

1. Laden Sie die Anwendung herunter:
   [Windows](https://claude.ai/api/desktop/win32/x64/setup/latest/redirect),
   [macOS](https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect).
2. Starten Sie sie und melden Sie sich bei Ihrem Konto an.
3. Klicken Sie oben in der Mitte auf den Reiter **Code**.

!!! warning "Wenn Claude schon auf dem Computer installiert war"

    Schließen Sie es **vollständig** — Rechtsklick auf das Symbol neben der
    Uhr → «Beenden» (Quit) — und öffnen Sie es erneut. Das Programm merkt
    sich beim Start, wo es nach Befehlen suchen soll, und weiß daher nichts
    von der gerade installierten Nyshporka. Symptom: Der Assistent schreibt,
    dass der Befehl `nysh` nicht gefunden wurde.

## Schritt 4. Den Arbeitsordner öffnen

Im Reiter Code, bevor Sie etwas schreiben:

1. Wählen Sie **Local** — der Assistent arbeitet dann auf Ihrem Computer.
2. **Select folder** → der Ordner `Документи\Нишпорка` (der Ordner
   „Нишпорка“ unter „Dokumente“). Ihn hat das Installationsprogramm angelegt;
   dort werden Scans, Gelesenes und Notizen liegen. Gibt es diesen Ordner
   nicht, werden Ihre „Dokumente“ mit OneDrive synchronisiert, und Nyshporka
   hat den Ordner daneben angelegt. Wo genau, zeigt die Anwendung:
   **🐾 Огляд** (Übersicht) → «Перевірити цю машину» (Diesen Rechner prüfen).
3. Berechtigungsmodus — **Manual**: Der Assistent fragt vor jeder Aktion, und
   Sie sehen, was genau er tut.

## Schritt 5. Die fertige Anfrage einfügen

Kopieren Sie den Text vollständig in das Eingabefeld und drücken Sie Enter:

```text
Lies https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
und erledige danach alles, damit Nyshporka auf diesem Computer bereit ist: Prüfe
den Rechner, installiere bei Bedarf die Lese-Engines und Modelle und lege die Skills für alle
Projekte ab. Erkläre mir jeden Schritt in einfachen Worten.
Wenn alles grün ist, frag mich, welchen Nachnamen ich suche und in welchen Schreibweisen.
```

Der Assistent liest die für ihn geschriebene Anleitung und wird, jedes Mal mit
der Bitte um Erlaubnis:

* den Rechner prüfen (`nysh doctor`);
* die Lesemodelle installieren (`nysh htr install`, `nysh models get`) — das
  ist der längste Schritt, etwa 2.5 GB;
* die Skills ablegen — fertige Arbeitsabläufe (`nysh skills install --user`);
* fragen, welchen Nachnamen wir suchen.

Fertig ist es, wenn der Assistent sagt, dass die Prüfung keine roten Zeilen
hat, und nach dem Nachnamen fragt. Weiter geht es mit
[„So arbeiten Sie“](start.md).

## Andere Assistenten

**Codex** (OpenAI, ChatGPT-Abo):
[Anwendung](https://learn.chatgpt.com/docs/quickstart) oder
[Version für das Terminal](https://learn.chatgpt.com/docs/cli). Die Schritte 1
und 2 sind dieselben; öffnen Sie in Schritt 4 den Ordner `Документи\Нишпорка`;
schreiben Sie in der Anfrage statt „lege die Skills für alle Projekte ab“
„lege die Skills im Ordner `~/.agents/skills` ab“.

**Claude Code im Terminal** — eine Zeile und der Start genügen:

```powershell
nysh skills install --user   # скіли для всіх проєктів
claude
```

**Andere** — jeder Assistent, der Skills im Format `SKILL.md` liest (Agent
Skills), darunter OpenClaw. So legen Sie sie in seinen Ordner:
`nysh skills install --target <тека>`.

## Wenn etwas nicht stimmt { #yakshcho-shchos-ne-tak }

| Was Sie sehen | Was zu tun ist |
|---|---|
| Assistent: „Befehl `nysh` nicht gefunden“ | Claude vollständig schließen (Symbol neben der Uhr → Beenden) und erneut öffnen. Im Terminal ein neues Fenster öffnen; hilft das nicht, den Computer neu starten |
| Der Reiter Code bietet an, den Tarif zu wechseln | Nötig ist ein Abo Claude Pro oder Max |
| Assistent: „Umgebung der Lese-Engines nicht bereit“ | Sagen Sie ihm: „Installiere die Lese-Engines und Modelle“ |
| Der Assistent sieht den Ordner mit den Scans nicht | Der Ordner liegt außerhalb des Arbeitsordners; der Assistent muss um Erlaubnis bitten, ihn in die Buchführung aufzunehmen (`nysh roots add`). Dateien werden nirgendwohin verschoben |
| Das Installationsprogramm endete mit „Code 1“ | Sehen Sie sich die letzten Zeilen der Ausgabe an. Meist ist es ein abgebrochener Download, zu wenig Platz oder ein Virenschutz |
| Etwas anderes | [Dem Autor schreiben](https://github.com/SERGIUSH-UA/nyshporka/issues) und wörtlich anfügen, was der Assistent geschrieben hat |

## Ohne Assistenten oder mit Python

Wenn Python oder `uv` schon vorhanden ist, wird das Paket von PyPI installiert:

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install "nyshporka[app,archives,htr]"
nysh init                      # створити робочу теку
nysh doctor                    # перевірити машину
nysh serve                     # відкрити застосунок у браузері
nysh htr install               # середовище для моделей читання, разово
nysh models get                # моделі читання, ~225 МБ, разово
```

Ein einzeiliges Installationsprogramm für Windows ohne Python — in PowerShell:

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```

??? note "Für Fortgeschrittene: Pakete, Schalter des Installationsprogramms, wo die Forschung liegt"

    **Pakete.** `nysh init` fragt, was Sie nutzen werden; ändern lässt sich das
    jederzeit mit `nysh sections`, ohne Neuinstallation.

    | Paket | Was enthalten ist |
    |---|---|
    | `catalog` | Kataloge, Ortsverzeichnis, Findbücher der Bestände — ohne Lesemodelle, spart ~2.5 GB |
    | `amateur` | + Lesen von Handschrift und Betrachter |
    | `researcher` (Standard) | + Suche im Gelesenen, Buchführung, Export |
    | `lab` | + Zeilenauszeichnung und Nachtrainieren von Modellen (`nysh train`) |

    **Schalter.** Gleich für Skripte und `.exe`:

    | Was wir festlegen | `windows.ps1` | `unix.sh` | `.exe` |
    |---|---|---|---|
    | Paket | `-Preset catalog` | `NYSH_PRESET=catalog` | `/PRESET=catalog` |
    | Zusammensetzung des Pakets komplett | `-Source 'nyshporka[app,archives]'` | `NYSH_SOURCE=…` | — |
    | bestimmte Version | `-Version X.Y.Z` | über `NYSH_SOURCE` | in die Datei eingebaut |
    | Installationsordner | `-Home_ D:\Nysh` | — | `/DIR=D:\Nysh` |
    | ohne Rückfragen | — | — | `/VERYSILENT` |
    | ohne Paket der Nachschlagewerke | `-NoCatalog` | `NYSH_NO_CATALOG=1` | — |
    | Protokoll | — | — | `/LOG=setup.log` |
    | wo die Forschung liegt | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` |

    ⚠ `irm … | iex` funktioniert für das Windows-Skript nicht (die Datei hat
    ein UTF-8-BOM) — erst `-OutFile`, dann `-File`.

    **Entwicklerrechner.** Das Installationsprogramm installiert nichts um:
    `uv` und ein eigenes Python 3.12 kommen in den Ordner der Anwendung,
    `pyenv`, `conda` und CUDA-Builds bleiben, wie sie waren. Außerhalb der
    eigenen Ordner gibt es nur einen Eintrag in PATH.
    `sh -s -- --dry-run` zeigt die Änderungen und tut nichts,
    `NYSH_NO_MODIFY_PATH=1` lässt PATH unangetastet. Die Liste der Änderungen
    landet in `install-trace.txt`.

    **Wo die Forschung liegt.** Der Arbeitsordner (in Befehlen — Arbeitsbereich):

    ```bash
    nysh init D:/Дослідження                      # обрати місце при створенні
    export NYSHPORKA_WORKSPACE=D:/Дослідження     # закріпити для всіх команд
    nysh --workspace D:/Дослідження doctor        # разово
    ```

    Ohne die Variable suchen die Befehle `nyshporka.toml` vom aktuellen Ordner
    aus nach oben. Wohin die Anwendung gerade schaut — `nysh doctor`, Zeile
    «Робочий простір» (Arbeitsbereich).

    **Mac mit Intel-Prozessor.** Wird wie überall installiert;
    `nysh htr install` nimmt Python und torch aus conda-forge, weil PyPI dafür
    keine torch-Wheels neuer als 2.2.2 hat.

    **Eine Grafikkarte ist nicht nötig.** Ohne sie wird eine Seite in ~20 s –
    1 Min. gelesen (je nach Prozessor und danach, wie viele Zeilen die Seite
    hat), mit Karte in ~10–15 s. Die Beschleunigung per Karte ist ein eigener
    Schritt, den `nysh doctor` vorschlägt.
