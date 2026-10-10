# Share what you have read (Supriaha)

Today the same archival book gets recognised by everyone separately. A reading does not cost
much, but it costs **every time**: a file of three thousand folios means hours
of machine time, and everyone who gets to it pays for them. Yet the text is
the same, and someone already has it ready.

Supriaha (`nyshporka.online`) is a shared bank of files that have been read. What travels is the text,
not the images: a file of 3772 folios weighs **3–4 megabytes** in a package.

!!! note "Images never go into the package"
    The package carries the machine's text and a passport of how it was obtained. The scans
    themselves stay with whoever downloaded them, and the package only names the source —
    so the recipient can get them from the same place and on the same terms.

## The shortest way

```sh
nysh share login                                  # один раз: браузер, одна кнопка
nysh share setup --as "ваше імʼя"                 # один раз: профіль
nysh share pack "ДАХмО 315-1-1234"                # спакувати справу
nysh share publish data/share/outbox/DAHMO_315-1-1234.nyshtext
```

On the other end:

```sh
nysh share pull "ДАХмО 315-1-1234" --take         # знайти в пулі й прийняти
nysh share pull --repo RGIA --fond 592 --opys 25 --take   # уся серія одним викликом
```

Accepted readings go to the same place as your own, and go straight into
the text store, so `nysh text find`, `grep` and `ctx` see them without a separate
`text index`. You can search a series the same way as a file:
`nysh text find <прізвище> --case "RGIA 592-25"`; for several files, repeat
`--case`.

!!! tip "If you share through the assistant"
    The `share-case` skill takes the assistant along this same path and guards the places that
    break silently: it checks the reference code in a dry run before uploading, does not take the
    FamilySearch catalogue years, and carries the catalogue entry set with `share card` through to the pool
    by uploading again. It is installed together with the other skills: `nysh skills install`.

## Signing in

`nysh share login` opens the nyshporka.online page: sign in with email or
Google, or anonymously. The key comes to Nyshporka by itself and goes into the system's
key store — there is nothing to copy. To remove the key from the machine:
`nysh share logout`. On a server without a browser the key goes into the
`NYSHPORKA_SUPRIAHA_TOKEN` variable, and it is issued in My account.

The pool lets you search, take and share packages only with a key. If you do not have one
yet, `pull`, `sync` and `publish` will offer to connect by themselves.

## Profile

`nysh share setup` with no flags asks one question after another; with any flag it
only records what was given and asks nothing (for scripts and the installer).

| field | flag | default |
|---|---|---|
| pseudonym in the catalogue | `--as` | no name |
| contact (public) | `--contact`, to remove — `--contact -` | none |
| text licence | `--license` | `CC0-1.0` |
| when to share | `--consent nikoly \| pytaty \| zavzhdy` | `pytaty` — keep a list and remind |
| ask the pool before reading | `--lookup / --no-lookup` | **no** |
| line positions | `--geometry / --no-geometry` | yes |

!!! warning "Your contact is public data"
    It goes into every package of yours and is visible to everyone who accepts it. It is never
    filled in by itself (neither from `git config` nor from the system user name) —
    only from the profile you have filled in, or from `--contact`. For a single package
    without a contact — `--contact -`.

**Ask the pool before reading** (`--lookup`) means: before every `nysh read`
Nyshporka sends the file's reference code and the number of frames to the server and, if the text already exists,
prints one line. The server then sees which file you are about to read
— that is why it is off by default.

## The catalogue entry: title, years, places, genre

The packer puts the catalogue entry together itself — from the folder's passport, the fond inventory register and
the file library. The passport's working marks (a check date in brackets, “FS-тег: …”,
“⚠ …”, priority marks) do not go into the entry. When that is not enough — a file with no
name, a working title instead of the real one — the entry is set by whoever uploads:

```sh
nysh share card "ДАХмО 315-1-1234" --title "Сповідні розписи парафії …" \
  --years 1795-1797 --place "Слобідка" --place "Вербівка" --genre confession
```

The same can be done right when packing: `nysh share pack … --title … --years …`. What you set
**is remembered** (`data/share/cards.json`) and applies to every later
packing of this file — `pack`, `suggest --all`, automatic sharing. To look at it —
`nysh share card <шифра>`, to clear a field — `--title ""`, the whole entry — `--clear`.

Genres: `birth`, `marriage`, `death`, `confession`, `revision`, `clergy_list`,
`gazette`, `finding_aid`, `other` (you can also use a label: «сповідні»).

**Where the frames are.** When a file has been read from a private photography set — a researcher's collection,
bought or commissioned — the recipient will not find it on FamilySearch or Commons.
The catalogue entry names who holds the frames:

```sh
nysh share card "ДАХмО 230-1-1234" --scans "Колекція дослідника=https://…"
```

The link goes first among the package's links, marked `role: scans`, and in
the pool it sits next to the text: that is exactly where a person will go for the images. Like the rest of
the entry, it is remembered; to clear it — `--scans ""`.

## What has been read but not shared yet

```sh
nysh share suggest                   # перелік зі статусами
nysh share suggest --all --ready     # спакувати все готове
nysh share suggest --skip "ДАХмО 315-1-1234" --why "платна зйомка"
```

Statuses: **ready**, **in the pool without frames**, **incomplete** (less than 80 % of
the frames read — shared only with `--partial`), **no frames**. What is already in the pool
is decided by the pool snapshot (`nysh share sync`); files the snapshot does not cover — by
the packing log. A refusal is remembered file by file: you will not be asked again about a file you
decided not to share.

## What is inside a package

```
manifest.json    шифра, картка, джерело сканів, знаменник, ваші поля
frames.jsonl     перелік кадрів справи
runs/<прогін>/   NNNN.txt — сторінка, рядок у рядок; плюс паспорт прогону
README.md        пояснення для того, хто відкриє пакет без Нишпорки
```

Line positions (`*.lines.json`) travel in a **separate** file,
`….geom.nyshtext`: they weigh ×10 the text and are needed only by someone who has
the same frames.

### Which readings travel

The voices in a package are readings of the file, not everything that happens to lie nearby. These stay
at home, and `pack` names each one with the reason:

- measurement readings (the `control_run` mark in the reading's passport);
- trials: a reading all of whose pages are in a fuller reading by **the same
  model** (parts of a file read by one model both travel);
- readings of another file with a similar name;
- other people's accepted readings — their author shares them, not you;
- those you name: `--skip-run <прогін>`.

### The denominator is the key field

The manifest says **how many frames the file has and how many of them have been read**, by which
model, and whether the orientation was checked. Without this, someone else's decode produces false
zeros wholesale: a person greps three pages taken for three thousand, does not find
the surname — and honestly closes that line of enquiry, having done everything right.

That is why a package with an incomplete decode or without the model's name simply will not be built.
If you read a part on purpose, say why:

```sh
nysh share pack "ДАХмО 315-1-1234" --partial "лише аркуші з нашим селом"
nysh share pack "ДАХмО 315-1-1234" --frames 408        # число кадрів справи, якщо пакувальник його не знайшов
```

## Your fields

```sh
nysh share pack "ДАХмО 315-1-1234" \
  --as "sergiy" --contact "t.me/…" \
  --note "читав Дяком, останні аркуші підмокли" \
  --link "звідки скани=https://…" \
  --extra "plivka=105208823"
```

- `--note` — free text; it reaches the reader and goes into the package's README.
- `--link` — “label=address” or just the link; most useful is one that leads to
  the scans. An address with `=` inside it (a FamilySearch link) is parsed whole.
- `--extra` — “key=value” pairs that the format will carry untouched. A pair
  without `=`, with an empty key or given twice is refused, not silently
  skipped.

## What does not go into a package

The packer takes **only** the text pages and the reading's passport — and from the passport
only the fields the recipient needs: the model, the reading engine, the script, how many pages have been
done. What does not travel: paths on your disk, working notes (`*_note`, explanations of
measurements, merge history), rescue crops, logs, quarantine, the page store,
verdicts, the canon.

You can see exactly what will travel before building:

```sh
nysh share pack "ДАХмО 315-1-1234" --dry-run
```

## The file notebook

Besides the text, something else is often known about a file that is useful to anyone who
opens it: what the book really contains, where the archive's inventory got the title or the years wrong, where
a copy is kept. A line the machine read crookedly and you checked against the
scan also goes here. All of this is the file notebook. It sits next to the folios you have looked through
and goes to Supriaha **separately from the text**: you can add to it even for a book that
someone else shared.

```sh
nysh note add "ДАХмО 315-1-1234" --kind about --text "Метрична книга Покровської церкви, 1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind catalog-error --field years --archive-says 1834 --actually "1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind copy --other "ДАВіО 904-24-55" --text "копія в консисторії" --share
nysh note read "ДАХмО 315-1-1234" 0031 --line 153 --text "урожденная Прухницкая" --share

nysh note push "ДАХмО 315-1-1234" --dry-run   # що поїде
nysh note push "ДАХмО 315-1-1234"             # віддати
nysh note pull "ДАХмО 315-1-1234"             # що дописали інші
```

Only what is marked `--share` goes to Supriaha, plus the list of folios you looked through without
your comments. Family matters — “my grandfather is recorded here” — write as
`--kind note`: such an entry never travels, and an entry with family words the pool
will not accept even if it is marked. On the book's page the notebook is shown separately from the
text, and it does not count towards the number of pages read: what was checked by eye is
selected lines, not a file that has been read.

A checked line goes to Supriaha together with a crop — a cut-out of that line from the
scan, a grey JPEG, if the file's scan is on your computer (without it the line
travels as text only). **By sharing checked lines, you agree that the owner of
Nyshporka may use them to train recognition models.** Crops are not given to other
users and are not shown on the book's page; the text of the check is visible to everyone. A retracted entry (`nysh note retract` and `note push`)
removes the crop from the pool as well.

## Accept someone else's package

!!! tip "If you take it through the assistant"
    The `pull-case` skill takes the assistant from `pull` to searching what was accepted and reads
    the match label out loud: what of the other person's text will fit your frames, and what is only
    for searching.

```sh
nysh share inspect <файл або адреса>     # подивитись, нічого не розкладаючи
nysh share import <файл або адреса>      # прийняти
nysh share geometry <….geom.nyshtext>    # докласти рамки рядків
```

A package comes from a person you do not know, and the receiver does not take its
word for anything:

- **the gates measure the content, not the claim**: pages, lines and the text hash
  are counted from the package itself, and a package that claims more than it contains does not
  get through;
- **a fault in the package means refusal before anything is written**: a path outside `runs/<прогін>/<файл>`,
  a name not allowed on Windows, a link, an oversized file — and nothing goes onto the
  disk;
- only the readings named in the manifest are unpacked, and only the text with its passport;
  the passport is cleaned with the same allow list;
- **your own reading is never overwritten** — not even with `--force`. A reading
  with the same name (regardless of case) is refused. `--force` replaces
  only a package accepted earlier;
- a package from an address in the catalogue is checked against its sha256 (`share pull --take`
  does this by itself; for `import` and `geometry` from an address — `--sha256`): a file
  swapped in the storage after the pool accepted it is not accepted.

## How well someone else's text fits your frames

The file key will not do for this: it is built from the folder name and your
archive reference list, so the same book gets different keys for two people. That is why
the package carries a list of frames and a fingerprint of the photography, and Nyshporka **measures** the match and
says it out loud:

| label | what it means | what works |
|---|---|---|
| `exact` | all frames match (hash or FamilySearch identifier) or the photography fingerprint matches on at least three frames | everything, including crops and the other person's line positions |
| `by-name` | names and count match | everything except the other person's line positions |
| `by-position` | only the count or some of the frames match | the page yes, the crop is doubtful |
| `text-only` | there are no frames or they are different | search, page, reference code |

Someone else's line positions are applied only to the text of **the same
contribution** and only with `exact`; otherwise you get a refusal with an explanation (`--force`, if you are sure).

`text-only` is not a defeat but the most common way it helps: you find
a surname in someone else's text, you see the file and the folio number — and you go to look at the
scan itself at the source.

!!! danger "Matching file names do not mean the same frame"
    Flat staging renumbers the pages, so two photography sets of one book
    easily end up with the same names and different content. That is exactly why the label is never
    raised by guesswork.

## Your zero and someone else's zero are different answers

Accepted readings are marked, and the search says so:

```
знаменник: кадрів 3772 · прочитано 3770 · у сторі прогонів 2 із 2 …
з них чужий декод: прогонів 2 із 2 · сторінок 3770 · від oksana
```

Someone else's text was read by another model, nobody here answers for its completeness, and
it can only be re-read by asking whoever gave it. A zero on it weighs
less than a zero on your own — and that has to be visible.

## The pool

```sh
nysh share pull                     # огляд пулу: архів · фонд · опис, справ і сторінок
nysh share pull "Слобідка"          # що є в каталозі
nysh share pull "ДАХмО 315-1-1234" --take
nysh share pull --repo RGIA --fond 592           # серія: що в ній є
nysh share pull --repo RGIA --fond 592 --take    # і прийняти всю
nysh share stats --catalog          # хто скільки вніс
nysh share sync --repo DAHMO --fond 315   # зріз для колонки «пул» у `cases fond`
```

The catalogue is the API at `https://api.nyshporka.online/v1`. Your own mirror or a test
server is set with the `NYSHPORKA_TOLOKA` variable or the `--base` flag; the Supriaha
key **does not go** to such an address — neither from the key store nor from
`NYSHPORKA_SUPRIAHA_TOKEN`. Your own server has to be named explicitly:
`NYSHPORKA_SUPRIAHA_TRUST=https://хост[:порт]` — HTTPS only and only an exact
address match; then the Supriaha key goes to it.
This machine's loopback (`127.0.0.1`, `localhost`) is trusted anyway.

`sync` with `--repo`/`--fond` adds a snapshot of one fond to the existing one; for fonds
the snapshot does not cover, the “pool” column says “don't know”, not “none”.

Nyshporka prints a refusal from the pool (gates, daily limit) in the server's own words. When the same
text is already in the pool, `publish` says whether it was accepted, rejected at some point,
or not finished yet — “already in Supriaha” means only the first.

## The exchange trail

`data/share/journal.jsonl` remembers what came from where and what went where, and
accepted packages stay in `data/share/inbox`. This is not record-keeping for its own sake:
a fact taken from someone else's decode and entered into the canon has to rest on a
permanent file — otherwise the citation will hang in the air as soon as you clear away the download.

```sh
nysh share list          # журнал
nysh share stats         # скільки віддано, скільки прийнято, від кого
```

## Licence

The package states on what terms the text is shared (`--license`, `CC0-1.0` by default),
and separately the terms of the scan source (`--source-terms`), if there are any. Without a licence
the package will not be built: the recipient has to know what they may do with it.
