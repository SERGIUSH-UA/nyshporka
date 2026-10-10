# Install and connect an assistant

The main route needs no commands at all: three programs in the right order and
one ready-made request. It takes 30–40 minutes, most of it downloading.

!!! note "Why not a chat on a website"

    Nyshporka does not work in the chat on claude.ai or chatgpt.com: the chat
    answers with text and has no access to your disk. You need an **assistant
    program** that talks just like the chat but carries out actions on the
    computer itself and asks permission before each one.

## What you need

* Windows 10 or 11, macOS or Linux.
* About 5 GB of free space: the reading models and everything they need take 2.5 GB.
* A **Claude Pro or Max** subscription — for Claude Desktop
  ([plans](https://claude.com/pricing)). Or a ChatGPT subscription — for Codex.
  Nyshporka itself is free: you pay only for the assistant.

## Step 1. Install Nyshporka

Nyshporka goes in **first**, the assistant last (step 3 explains why).

=== "Windows"

    1. [:material-download: Download the installer](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       and run it.
    2. If Windows says **“Windows protected your PC”** — “More info” →
       “Run anyway”. This is how Windows greets every program that few people
       have downloaded yet.
    3. When asked what to install («Що ставимо»), choose **«Каталоги + читання
       рукопису й пошук у прочитаному»** (catalogues + manuscript reading and
       search in the read text).
    4. At the end, leave the «Запустити Нишпорку» (Launch Nyshporka) box ticked —
       the app will open in your browser. This is your computer, not a website:
       it works without the internet too.

=== "macOS and Linux"

    Open “Terminal”, paste one line and press Enter:

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    When the script has finished, close the terminal window.

## Step 2. Git for Windows

Download [Git for Windows](https://git-scm.com/downloads/win) and install it,
clicking “Next” all the way through. Without it, the Code tab in Claude Desktop
will not open, and Nyshporka needs it to install the reading models. On macOS
Git is usually already there.

## Step 3. Claude Desktop

1. Download the app:
   [Windows](https://claude.ai/api/desktop/win32/x64/setup/latest/redirect),
   [macOS](https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect).
2. Run it and sign in to your account.
3. Click the **Code** tab at the top centre.

!!! warning "If Claude was already installed on the computer"

    Close it **completely** — right-click the icon next to the clock →
    “Quit” — and open it again. The program remembers where to look for
    commands at the moment it starts, so it does not know about the Nyshporka
    you have just installed. Symptom: the assistant writes that the `nysh`
    command was not found.

## Step 4. Open the working folder

In the Code tab, before writing anything:

1. Choose **Local** — the assistant will work on your computer.
2. **Select folder** → the `Документи\Нишпорка` folder (Documents\Nyshporka).
   The installer created it; your scans, read text and notes will live there.
   If there is no such folder, your “Documents” are synced with OneDrive, and
   Nyshporka has put the folder next to it. The app will show exactly where:
   **🐾 Огляд** (Overview) → «Перевірити цю машину» (Check this machine).
3. Permission mode — **Manual**: the assistant will ask before every action,
   and you see exactly what it is doing.

## Step 5. Paste the ready-made request

Copy the whole text into the input box and press Enter:

```text
Read https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
and follow it to do everything needed so that Nyshporka is ready on this computer: check
the machine, install the reading engines and models if needed, and put the skills in place for all
projects. Explain every step to me in plain words.
When everything is green, ask me which surname I am looking for and in which spellings.
```

The assistant will read the instructions written for it and, asking permission
each time, will:

* check the machine (`nysh doctor`);
* install the reading models (`nysh htr install`, `nysh models get`) — this is
  the longest step, about 2.5 GB;
* put in place the skills — ready-made working routines (`nysh skills install --user`);
* ask which surname we are looking for.

You are done when the assistant says the check shows no red lines and asks for
the surname. Next — [“How to work”](start.md).

## Other assistants

**Codex** (OpenAI, a ChatGPT subscription):
[the app](https://learn.chatgpt.com/docs/quickstart) or
[the terminal version](https://learn.chatgpt.com/docs/cli). Steps 1 and 2 are
the same; in step 4 open the `Документи\Нишпорка` folder; in the request,
instead of “put the skills in place for all projects”, write “put the skills in
the `~/.agents/skills` folder”.

**Claude Code in the terminal** — one line and a launch are enough:

```powershell
nysh skills install --user   # скіли для всіх проєктів
claude
```

**Others** — any assistant that reads skills in the `SKILL.md` format
(Agent Skills), OpenClaw among them. To put them in its folder:
`nysh skills install --target <тека>`.

## If something is wrong { #yakshcho-shchos-ne-tak }

| what you see | what to do |
|---|---|
| the assistant: “the `nysh` command was not found” | Close Claude completely (icon next to the clock → Quit) and open it again. In the terminal, open a new window; if that does not help, restart the computer |
| the Code tab offers to upgrade your plan | You need a Claude Pro or Max subscription |
| the assistant: “the reading engine environment is not ready” | Tell it: “install the reading engines and models” |
| the assistant cannot see the folder with the scans | The folder is outside the working folder; the assistant should ask permission to take it into its records (`nysh roots add`). No files are moved anywhere |
| the installer finished with “code 1” | Look at the last lines of the output. Most often it is an interrupted download, lack of space or an antivirus |
| something else | [Write to the author](https://github.com/SERGIUSH-UA/nyshporka/issues), adding word for word what the assistant wrote |

## Without an assistant, or with Python

If you already have Python or `uv`, the package installs from PyPI:

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install "nyshporka[app,archives,htr]"
nysh init                      # створити робочу теку
nysh doctor                    # перевірити машину
nysh serve                     # відкрити застосунок у браузері
nysh htr install               # середовище для моделей читання, разово
nysh models get                # моделі читання, ~225 МБ, разово
```

A one-line installer for Windows without Python — in PowerShell:

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```

??? note "For experienced users: presets, installer switches, where your research lives"

    **Presets.** `nysh init` asks what you will be using; you can change it at any
    time with `nysh sections`, without reinstalling.

    | preset | what it includes |
    |---|---|
    | `catalog` | catalogues, gazetteer, fond inventories — no reading models, saves ~2.5 GB |
    | `amateur` | + manuscript reading and the page viewer |
    | `researcher` (default) | + search in the read text, record-keeping, export |
    | `lab` | + line labelling and fine-tuning the models (`nysh train`) |

    **Switches.** The same for the scripts and the `.exe`:

    | what we set | `windows.ps1` | `unix.sh` | `.exe` |
    |---|---|---|---|
    | preset | `-Preset catalog` | `NYSH_PRESET=catalog` | `/PRESET=catalog` |
    | the whole package contents | `-Source 'nyshporka[app,archives]'` | `NYSH_SOURCE=…` | — |
    | a specific version | `-Version X.Y.Z` | via `NYSH_SOURCE` | built into the file |
    | installation folder | `-Home_ D:\Nysh` | — | `/DIR=D:\Nysh` |
    | no questions | — | — | `/VERYSILENT` |
    | without the reference pack | `-NoCatalog` | `NYSH_NO_CATALOG=1` | — |
    | log | — | — | `/LOG=setup.log` |
    | where your research lives | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` |

    ⚠ `irm … | iex` does not work for the Windows script (the file has a UTF-8 BOM) —
    first `-OutFile`, then `-File`.

    **A developer's machine.** The installer does not reinstall anything: `uv` and its own
    Python 3.12 go into the app's folder; `pyenv`, `conda` and CUDA builds
    stay as they were. Outside its own folders it only adds to PATH.
    `sh -s -- --dry-run` shows the changes and does nothing;
    `NYSH_NO_MODIFY_PATH=1` leaves PATH alone. The list of changes goes into
    `install-trace.txt`.

    **Where your research lives.** The working folder (in commands — the workspace):

    ```bash
    nysh init D:/Дослідження                      # обрати місце при створенні
    export NYSHPORKA_WORKSPACE=D:/Дослідження     # закріпити для всіх команд
    nysh --workspace D:/Дослідження doctor        # разово
    ```

    Without the variable, commands look for `nyshporka.toml` upwards from the current folder.
    Where the app is looking right now — `nysh doctor`, the «Робочий простір» (workspace) line.

    **A Mac with an Intel processor.** It installs as everywhere else; `nysh htr install` takes
    Python and torch from conda-forge, because PyPI has no torch wheels for it newer
    than 2.2.2.

    **You don't need a graphics card.** Without one, a page is read in ~20 s – 1 min
    (depending on the processor and how many lines the page has); with a card —
    in ~10–15 s. Speeding up with a card is a separate step; `nysh doctor`
    will suggest it.
