# How to work

<p align="center">
  <img alt="Nyshporka reading a manuscript with a magnifying glass" src="../assets/maskot-pratsiuie.webp" width="220" height="206">
</p>

Nyshporka is installed and the assistant is connected ([if not](install.md)). From
here on you talk to the assistant in ordinary language, and look at what has been
found yourself.

## What you can ask for

A few examples — phrase them however you like:

* “What is there about the village of Lypovenke? Where are its parish registers, and what is worth ordering from the archive?”
* “Here is the folder `D:\скани\ДАКО 13-1-1`, set it up as a file. It is a parish register,
  1850–1855.”
* “Read this file.” (A book of 300 folios without a graphics card takes a night;
  the computer must not go to sleep.)
* “Find the Kovalskyis here and show me the lines on the scan.”
* “Record that I have looked through folios 12–40: our man is not there.”
* “Make a table of all the marriages in this book in the 1820s.”
* “Nothing found — where should I dig next?”

The assistant knows the order of work by itself: for this it has skills — ready-made
routines for how to read a file, how to search for a surname, where to dig, how to record
what has been looked through.

## You bring the scans yourself

Nyshporka does not download files from FamilySearch or from archive accounts that you have to
sign in to with your own login. You save the pages from the archive's
viewer to your disk, as you would without it. The requirements for the folder are simple and strict:

| rule | why |
|---|---|
| one folder = one file | the reference code, the records and the discoveries are attached to the folder |
| images sit directly in the folder | reading does not go into subfolders |
| `jpg`, `png`, `tif`, `webp` | other formats do not count as frames |
| a PDF can go in as it is | its pages will be unfolded into frames by themselves before reading |

The folder can be anywhere — an external drive, the desktop, a network. No files
are moved anywhere; the assistant will ask permission to take the folder into its records. In the
app this is done in the **📥 Нові теки** (New folders) window → «Описати» (Describe): for a folder outside
your research, a tick box «Показувати цю теку в переліках там, де
вона лежить» (Show this folder in the lists where it lies) will appear there.

## How to check what has been found

The assistant shows candidates, and you decide. For this there is the **app in the
browser** — the “Nyshporka” shortcut on the desktop or `nysh serve`, address
`127.0.0.1:8788`.

* **📄 Гортач** (Page viewer) — the scan and the read text side by side. Click a line and you will see
  the clipping of the folio it was read from.
* **🔎 Пошук** (Search) — all candidates with a match, each with its clipping. It searches with the same
  command as the assistant, and under the results it says where and with what the search was made.
* **👁 Облік** (Records) — what has already been looked through by eye, even blank folios.

If the assistant says “found”, ask for the clipping. If it says “not there”, ask
how many folios were checked.

## Three rules

* **“Not there” without a number is not an answer.** The right way to put it is: “180
  folios out of 300 searched, no matches in the read text”. A false “not there” closes a line of
  search for good.
* **The machine finds, you decide.** The read text contains mistakes — in
  18th–19th-century cursive, every third or fourth letter. You search in it, and
  look at what you find on the scan. Do not reject a candidate because the root of the
  word does not look similar: the model mangles precisely the middle of a surname.
* **Check numbers against the scan.** The machine confuses years, ages and entry numbers more often
  than words, and it looks just as confident.

## The app's windows { #vikna-zastosunku }

Each window answers one question, and “not there” means something different in each.

| window | question |
|---|---|
| 🐾 Огляд (Overview) | where I stand: what I already have, what has been read, what is not finished, the machine check |
| 🔎 Пошук (Search) | where in the read text my surname, village or any word appears — in the whole library, a fond or a file |
| 🎯 Рід (Family) | whose surname we are looking for and in which spellings — the only thing you specify |
| 📥 Нові теки (New folders) | what on the disk has not yet become a file: describe it with a reference code or set it aside as “not a file” |
| 🗺 Газетир (Gazetteer) | where my village's documents are |
| 🔎 Каталоги (Catalogues) | what is in the archive guides and on the archives' websites; a website's catalogue is gathered with a button |
| 🏛 Описи фондів (Fond inventories) | what exists in the archive at all, even if not digitised |
| 📚 Бібліотека (Library) | what I have on my disk |
| 🖋 Читання · 📜 Прогони (Reading · Reading runs) | read a file · with what and how well it was read, what is left to finish |
| 📄 Гортач · 🔍 Розбір · 👁 Облік (Page viewer · Review · Records) | the read text next to the scan · candidates with clippings · what I have already seen by eye |

A detailed guide to the windows — [“Screen map”](agents/screens.md).

## Try it without your own scans

In the app: **🐾 Огляд** (Overview) → «Перевірити цю машину» (Check this machine) → «Розгорнути
зразок» (Unpack the sample) (or `nysh sample`). These are three already read folios of the file
**ДАХмО 315-1-159** (1821–1822): on them you can see the page viewer, the clippings and search even before
you bring your own scans.

## What else Nyshporka can do

* **A gazetteer and reference guides** straight after installation: the consolidated catalogue of the ЦДІАК
  (Central State Historical Archive of Ukraine in Kyiv; 4566 settlements), the catalogue of the ДАХмО, the index of FamilySearch films for Moldova,
  churches around 1772.
* **Catalogues of archive websites** — ARCHIUM, «Бабин Яр» (Babyn Yar), Wikimedia Commons,
  Duck Inspector, ridni.org, Чтиво (Chtyvo), Internet Archive.
* **Parsing entries into a table** — dates, names, roles, status, age — and exporting to
  Excel. The assistant does the parsing itself, that is, at the cost of your subscription.
* **Fine-tune the model** on your own handwriting — [more](train.md).
* **Read a large file on a rented machine** in an hour instead of
  a week — [more](cloud.md).

The full technical list with commands — [feature reference](agents/features.md).

## Updates

Nyshporka does not go online by itself and does not remind you about new versions. Every so
often, ask the assistant to check, or run `nysh update --check`.
