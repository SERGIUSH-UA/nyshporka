# Frequently asked questions

## Scans and disk space

### Do I need to download all the scans to my computer?

Yes. To read a folio, the model cuts it into lines and goes through each one — that is
dozens of accesses to the file for a single page; nobody reads like that “on the fly” from an
archive's website.

### If I delete the scans afterwards, will the information be wiped?

Not all of it. **What stays:** the read text, the record of what has been looked through, findings and
notes: they live in Nyshporka's working folder, not in the folder with the scans, and searching the
text keeps working. **What goes:** the crops, and the ability to look at a candidate
by eye or to re-read the file with another model.

So before freeing up space, finish the file. A cheaper option is to
move the folder to an external drive and tell the assistant
(`nysh roots add "E:\скани"`): the file will not disappear from the lists.

### How much space do I need?

The application with the reading models takes about 3 GB. Scans take as much as they take (a folio
of a parish register weighs 2–8 MB). The read text is a few MB per file.

### The archive gave me a PDF, not separate pages

Reading currently accepts only images: `jpg`, `png`, `tif`, `webp`. A PDF first
has to be split into pages with an external tool. The exception is a printed book with
a text layer (for example, from Chtyvo): it does not need the model, the text is already there.

## Archives

### Can I work with scans from any archive?

Yes, straight away: the codes of all regional and central archives of Ukraine are already in the reference list,
so the reference code `ДАКО 13-1-1` is accepted without any setup. The only difference is whether
Nyshporka can browse the archive's catalogue by itself: ready-made catalogues exist for ДАХмО and
ЦДІАК, and the ARCHIUM viewers of other archives can be added with a few lines of
settings — ask the assistant.

### Does Nyshporka download files from FamilySearch?

No, and it will not: that needs a live browser session, and bulk downloading
breaks the service's rules. Instead there is a **film index**: which village is on which
frames of which film. It answers “where are my village's parish registers” without downloading anything, but
for now it covers only Moldova.

If the film frames are already on your disk, you can take them into your records as a
file: `nysh case <тека> --shifra "<архів фонд-опис-справа>" --dgs <номер
групи зображень>`. The number goes into the file's passport as the source of the scans.

## Reading

### Do I need a graphics card?

No. Reading is limited by the processor: about **2 minutes per page** on
an ordinary laptop versus ~20 seconds with a graphics card. A large file can be
read on a [rented machine](cloud.md).

### How do I read several files in a row without sitting next to the computer?

Put them in a queue: `nysh queue add <справи>`, then `nysh queue run`.
The queue takes the files one after another; if one cannot go further (the reference code is missing,
the source will not give the frames), it waits for your decision while the queue moves on to the next.
`nysh queue` shows what is at which stage and how much is left. To stop after
the current file — `nysh queue stop`; after a stop or a switched-off computer
`nysh queue run` carries on from the same place.

### The text comes out full of mistakes — is something broken?

No, that is the ceiling of the technology on this kind of material. On 18th–19th-century cursive the machine
mixes up a quarter to a third of the letters: “Franciszka Lubkowskiego” turns into
“Francisrha Lubhoustrio90”. The text is there so you can **search** it — the search is
fuzzy and finds a mangled surname — and what is found is then checked on the scan.

### Why two models for Cyrillic?

Diak reads the same lines as Pysar, but makes **different** mistakes: it sticks closer
to the strokes themselves where Pysar substitutes a plausible word. Together
they find more than either one alone.

### Does Nyshporka read Polish books, Latin, the 20th century?

The models are trained on 18th–19th-century cursive from Ukrainian, Moldovan and Polish
archives. Latin script (notarial records, Catholic church books) is read by Skryba. On handwriting the
model has never seen there are more mistakes — Skryba gets every fifth letter wrong in unfamiliar hands.
For finding a surname that is mostly enough, for a word-for-word quotation it is not, so
it is worth checking your first file of new material by eye. You [can](train.md) fine-tune the model
on your own handwriting.

## The assistant

### Can I do without the assistant?

Simple things — yes: in the application in the browser you can look at the reference lists,
what has been read and what has been found. But from “where to look” to “here is your ancestor” Nyshporka
is designed to go together with the assistant: it takes dozens of steps that would
take days by hand.

### What does the assistant do, and what does Nyshporka do?

Reading the manuscript and searching are done by Nyshporka on your computer — that costs
nothing but time. The assistant decides what to do next, runs the steps and
explains the result. The only thing it “reads with its own eyes” is **breaking records down into fields**
(dates, names, roles): that is about 84 thousand tokens per scan, so for a book of
two hundred folios it is millions of tokens, and two passes are needed.

## Money and privacy

### How much does it cost?

Nyshporka costs nothing, it is free software (AGPL-3.0). You only pay for the assistant (its
subscription) and, if you wish, for renting a machine for reading — the cost is shown
**before** you rent.

### Are my scans sent anywhere?

No. There is no telemetry, and you do not need an account to work. Scans,
what has been read and your notes stay in a folder on your disk. Nyshporka goes online
only when you have asked it to: searching catalogues, downloading a file,
installing models, updating. The full list is in the
[privacy policy](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

You can share what you have read in [Supriaha](share.md) only after signing in
(`nysh share login`) and only with your consent: what is shared is the text the
machine has read and the file's description. Scans and notes never go there. Asking the pool before
each reading and sharing what has been read automatically — both modes are off by default,
you switch them on (`nysh share setup`).

### Can I move my research to another computer?

Yes: the working folder is an ordinary folder, you can copy it whole. The description of each
file lives in that file's own folder, so it moves along with it, including to a
colleague.

## Updating and uninstalling

### How do I update?

Ask the assistant or run `nysh update --check` — the command will tell you whether there is
a newer version and which line to run to update on your particular machine. On Windows
the simplest way is to download the new installer and run it over the old one: your research,
models and reference lists stay in place. Nyshporka itself does not remind you about new versions:
that is what the privacy policy promises.

### How do I uninstall Nyshporka?

`nysh uninstall` shows what will be removed, `nysh uninstall --yes --all` removes
everything, models included. On Windows you can also do it like any other program — “Programs and
Features”. **The working folder with your research is never removed.**

## When the search found nothing { #nichogo-ne-znaishlos }

An empty result is the most expensive answer in genealogy, because “not there” closes a
line of enquiry for a long time. Before you believe it, ask yourself (or the assistant) four things:

1. **Is the text readable?** Look at the file in the viewer. If it is solid noise,
   the zero is about the quality of the reading, not about whether the surname is there.
2. **How many folios were actually searched?** “Not found in 180 folios out of
   300” and “not found” are different answers.
3. **Does the search find what is definitely there?** Search for a surname you have already
   seen on a scan with your own eyes. If it is not found, the problem is the search.
4. **Were the right sources searched?** Ask the assistant for a plan: which sources
   have been read, how much each one covered and what comes next.

The assistant knows two more workarounds: searching for a family by **first names and patronymics**,
which the model mangles less than a long surname, and a **self-check** — whether
the search sees the folios where you have already written out the surname yourself.

## What is not there yet { #chogo-shche-nemaie }

Honestly, with nothing left out:

* **You bring the scans yourself** — there is no FamilySearch downloader and there will not be one.
* **Breaking records down into fields is done by the assistant at your expense.** Nyshporka prepares the folio and
  checks completeness, but does not break records down itself: a built-in paid service
  would spend your money without your say.
* **The page type** (register entry, cover, index) is determined by a person or
  the assistant — Nyshporka does not recognise it by itself.
* **Nothing may save a faded folio** — neither zoom nor a second reading.
  That part of the file is either re-photographed or accepted as incomplete.
* **The reading models are good on the material they learned from**; on other material
  bad text looks just as confident as good text.
* **Inventories are not available for all fonds** — only where the inventory is published on websites
  Nyshporka can read.
* **The film index covers only Moldova.**

Technical details of the limits are in the [features reference](agents/features.md#mezhi-chogo-shche-nemaie).

## If something goes wrong

| what you see | what to do |
|---|---|
| “`nysh` command not found” | Close and reopen the assistant (Claude — fully, via the icon next to the clock) or the terminal window |
| “Windows protected your PC” | “More info” → “Run anyway”. To verify the file, use the `.sha256` in the [release](https://github.com/SERGIUSH-UA/nyshporka/releases/latest) |
| the installer finished with “code 1” | Look at the last lines of the output: most often an interrupted download, lack of space or an antivirus. More detail — [installation](install.md#yakshcho-shchos-ne-tak) |
| the application window is empty | An empty window always says what is missing. Most often the file has not been set up yet or the catalogue has not been built — ask the assistant |
| half the windows are missing | Parts of the application can be switched off: ⚙ → “Parts of the application”. The `catalog` set has no manuscript reading |
