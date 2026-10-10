# Gelesenes teilen (Supriaha)

Ein und dasselbe Archivbuch lässt heute jeder für sich erkennen. Ein
Lesedurchgang kostet nicht viel, aber er kostet **jedes Mal**: Eine Akte mit
dreitausend Blättern bedeutet Stunden Rechenzeit, und dafür zahlt jeder, der
bei ihr angekommen ist. Der Text ist dabei derselbe, und bei jemandem liegt
er schon fertig da.

Supriaha (`nyshporka.online`) ist eine gemeinsame Sammlung gelesener Akten.
Geteilt wird der Text, nicht die Bilder: Eine Akte mit 3772 Blättern wiegt
im Paket **3–4 Megabyte**.

!!! note "Bilder kommen niemals ins Paket"
    Das Paket enthält den Text der Lese-Engine und einen Pass darüber, wie er
    entstanden ist. Die Scans selbst bleiben bei dem, der sie heruntergeladen
    hat, und das Paket nennt nur die Quelle — damit der Empfänger sie dort
    und zu denselben Bedingungen beziehen kann.

## Der kürzeste Weg

```sh
nysh share login                                  # один раз: браузер, одна кнопка
nysh share setup --as "ваше імʼя"                 # один раз: профіль
nysh share pack "ДАХмО 315-1-1234"                # спакувати справу
nysh share publish data/share/outbox/DAHMO_315-1-1234.nyshtext
```

Auf der anderen Seite:

```sh
nysh share pull "ДАХмО 315-1-1234" --take         # знайти в пулі й прийняти
nysh share pull --repo RGIA --fond 592 --opys 25 --take   # уся серія одним викликом
```

Übernommene Lesedurchgänge landen dort, wo auch Ihr eigenes Gelesenes liegt,
und gehen sofort in den Textspeicher, sodass `nysh text find`, `grep` und
`ctx` sie ohne gesonderten `text index` sehen. Suchen kann man in einer Serie
genauso wie in einer Akte: `nysh text find <прізвище> --case "RGIA 592-25"`;
für mehrere Akten `--case` wiederholen.

!!! tip "Wenn Sie über den Agenten teilen"
    Der Skill `share-case` führt den Agenten genau diesen Weg und bewacht die
    Stellen, die still kaputtgehen: Die Signatur prüft er vor dem Hochladen
    im Dry-Run, Jahre aus dem Katalog von FamilySearch übernimmt er nicht,
    und eine mit `share card` festgelegte Karteikarte bringt er durch
    erneutes Hochladen in den Pool. Installiert wird er mit den übrigen
    Skills: `nysh skills install`.

## Anmeldung

`nysh share login` öffnet die Seite nyshporka.online: Anmeldung per E-Mail
oder Google oder anonym. Der Schlüssel kommt von selbst in Nyshporka an und
landet im Schlüsselspeicher des Systems — kopieren müssen Sie nichts. Den
Schlüssel vom Rechner entfernen: `nysh share logout`. Auf einem Server ohne
Browser kommt der Schlüssel in die Variable `NYSHPORKA_SUPRIAHA_TOKEN`,
ausgegeben wird er unter „Mein Konto“.

Suchen, Übernehmen und Teilen von Paketen erlaubt der Pool nur mit
Schlüssel. Gibt es noch keinen, schlagen `pull`, `sync` und `publish` von
selbst vor, sich zu verbinden.

## Profil

`nysh share setup` ohne Optionen fragt der Reihe nach; mit einer beliebigen
Option schreibt es nur das Genannte und fragt nichts (für Skripte und das
Installationsprogramm).

| Feld | Option | Standard |
|---|---|---|
| Pseudonym im Katalog | `--as` | ohne Namen |
| Kontakt (öffentlich) | `--contact`, entfernen — `--contact -` | keiner |
| Lizenz des Textes | `--license` | `CC0-1.0` |
| wann teilen | `--consent nikoly \| pytaty \| zavzhdy` | `pytaty` — Liste führen und erinnern |
| vor dem Lesen im Pool nachfragen | `--lookup / --no-lookup` | **nein** |
| Zeilenpositionen | `--geometry / --no-geometry` | ja |

!!! warning "Der Kontakt ist öffentlich"
    Er geht in jedes Ihrer Pakete mit und ist für alle sichtbar, die es
    übernehmen. Er wird nie von selbst eingesetzt (weder aus `git config`
    noch aus dem Benutzernamen des Systems) — nur aus dem Profil, das Sie
    ausgefüllt haben, oder aus `--contact`. Für ein einzelnes Paket ohne
    Kontakt — `--contact -`.

**Vor dem Lesen im Pool nachfragen** (`--lookup`) bedeutet: Vor jedem
`nysh read` schickt Nyshporka die Signatur der Akte und die Zahl der
Aufnahmen an den Server und gibt, wenn der Text schon da ist, eine Zeile aus.
Der Server sieht dabei, welche Akte Sie lesen wollen — deshalb ist es
standardmäßig ausgeschaltet.

## Karteikarte der Akte: Titel, Jahre, Orte, Quellenart

Der Packer stellt die Karteikarte selbst zusammen — aus dem Pass des
Ordners, dem Register des Findbuchs und der Aktenbibliothek. Arbeitsvermerke
des Passes (Prüfdatum in Klammern, „FS-тег: …“, „⚠ …“, Prioritätsvermerke)
kommen nicht auf die Karteikarte. Reicht das nicht — eine namenlose Akte, ein
Arbeitstitel statt des echten —, legt die Karteikarte fest, wer hochlädt:

```sh
nysh share card "ДАХмО 315-1-1234" --title "Сповідні розписи парафії …" \
  --years 1795-1797 --place "Слобідка" --place "Вербівка" --genre confession
```

Dasselbe direkt beim Verpacken: `nysh share pack … --title … --years …`. Das
Festgelegte wird **gespeichert** (`data/share/cards.json`) und gilt für jedes
weitere Verpacken dieser Akte — `pack`, `suggest --all`, automatisches
Teilen. Ansehen — `nysh share card <шифра>`, ein Feld löschen —
`--title ""`, die ganze Karteikarte — `--clear`.

Quellenarten: `birth`, `marriage`, `death`, `confession`, `revision`,
`clergy_list`, `gazette`, `finding_aid`, `other` (auch als Bezeichnung
möglich: «сповідні»).

**Wo die Aufnahmen sind.** Wurde die Akte aus privaten Aufnahmen gelesen —
der Sammlung eines Forschers, gekauft oder bestellt —, findet der Empfänger
sie weder bei FamilySearch noch auf Commons. Die Karteikarte nennt, wer die
Aufnahmen hat:

```sh
nysh share card "ДАХмО 230-1-1234" --scans "Колекція дослідника=https://…"
```

Der Link steht unter den Links des Pakets an erster Stelle, mit dem Vermerk
`role: scans`, und im Pool steht er neben dem Text: Für die Bilder geht man
genau dorthin. Wie der Rest der Karteikarte wird er gespeichert; löschen —
`--scans ""`.

## Was gelesen, aber noch nicht geteilt ist

```sh
nysh share suggest                   # перелік зі статусами
nysh share suggest --all --ready     # спакувати все готове
nysh share suggest --skip "ДАХмО 315-1-1234" --why "платна зйомка"
```

Status: **bereit**, **im Pool ohne Rahmen**, **unvollständig** (weniger als
80 % der Aufnahmen gelesen — wird nur mit `--partial` geteilt), **ohne
Aufnahmen**. Was schon im Pool ist, entscheidet der Stand des Pools
(`nysh share sync`); Akten, die der Stand nicht abdeckt, nach dem Protokoll
der Verpackungen. Eine Ablehnung wird einzeln gespeichert: Zu einer Akte,
die Sie nicht teilen wollten, wird nicht mehr nachgefragt.

## Was im Paket steckt

```
manifest.json    шифра, картка, джерело сканів, знаменник, ваші поля
frames.jsonl     перелік кадрів справи
runs/<прогін>/   NNNN.txt — сторінка, рядок у рядок; плюс паспорт прогону
README.md        пояснення для того, хто відкриє пакет без Нишпорки
```

Die Zeilenpositionen (`*.lines.json`) gehen als **gesonderte** Datei
`….geom.nyshtext` mit: Sie wiegen das Zehnfache des Textes und werden nur
von dem gebraucht, der dieselben Aufnahmen hat.

### Welche Lesedurchgänge mitgehen

Die Stimmen des Pakets sind Lesungen der Akte, nicht alles, was daneben
liegt. Zu Hause bleiben, und `pack` nennt jeden mit Grund:

- Messdurchgänge (Vermerk `control_run` im Pass des Durchgangs);
- Proben: ein Durchgang, dessen Seiten alle in einem vollständigeren
  Durchgang **desselben Modells** enthalten sind (Teile einer Akte, die mit
  einem Modell gelesen wurden, gehen beide mit);
- Durchgänge einer anderen Akte mit ähnlichem Namen;
- fremde übernommene Durchgänge — die teilt der Autor, nicht Sie;
- von Ihnen genannte: `--skip-run <прогін>`.

### Der Nenner — das wichtigste Feld

Das Manifest sagt, **wie viele Aufnahmen die Akte hat und wie viele davon
gelesen sind**, mit welchem Modell und ob die Ausrichtung geprüft wurde. Ohne
das erzeugt eine fremde Lesung massenhaft falsche Nullen: Jemand durchsucht
drei Seiten, die er für dreitausend hält, findet den Nachnamen nicht — und
schließt die Richtung ehrlich, obwohl er alles richtig gemacht hat.

Deshalb lässt sich ein Paket mit unvollständiger Lesung oder ohne
Modellnamen gar nicht erst zusammenstellen. Haben Sie absichtlich nur ein
Stück gelesen, sagen Sie, warum:

```sh
nysh share pack "ДАХмО 315-1-1234" --partial "лише аркуші з нашим селом"
nysh share pack "ДАХмО 315-1-1234" --frames 408        # число кадрів справи, якщо пакувальник його не знайшов
```

## Ihre Felder

```sh
nysh share pack "ДАХмО 315-1-1234" \
  --as "sergiy" --contact "t.me/…" \
  --note "читав Дяком, останні аркуші підмокли" \
  --link "звідки скани=https://…" \
  --extra "plivka=105208823"
```

- `--note` — freier Text, er kommt beim Leser an und landet in der README
  des Pakets.
- `--link` — „Bezeichnung=Adresse“ oder nur der Link; am nützlichsten ist,
  was zu den Scans führt. Eine Adresse mit `=` darin (FamilySearch-Links)
  wird als Ganzes erkannt.
- `--extra` — Paare „Schlüssel=Wert“, die das Format unangetastet
  mitnimmt. Ein Paar ohne `=`, mit leerem Schlüssel oder doppelt genannt —
  das ist eine Ablehnung, kein stilles Überspringen.

## Was nicht ins Paket kommt

Der Packer nimmt **nur** die Textseiten und den Pass des Durchgangs — und aus
dem Pass nur die Felder, die der Empfänger braucht: Modell, Engine, Schrift,
wie viele Seiten fertig sind. Nicht mit gehen Pfade Ihrer Festplatte,
Arbeitsnotizen (`*_note`, Erläuterungen zu Messungen, Verlauf von
Zusammenführungen), Rettungsausschnitte, Protokolle, Quarantäne,
Seitenspeicher, Urteile, Kanon.

Was genau mitgeht, kann man vor dem Zusammenstellen ansehen:

```sh
nysh share pack "ДАХмО 315-1-1234" --dry-run
```

## Notizbuch der Akte

Außer dem Text weiß man über eine Akte oft noch etwas, das jedem nützt, der
sie öffnet: was wirklich im Buch steht, wo das Findbuch des Archivs sich im
Titel oder bei den Jahren geirrt hat, wo eine Abschrift liegt. Hierher gehört
auch eine Zeile, die die Lese-Engine schief gelesen und Sie mit dem Scan
abgeglichen haben. All das ist das Notizbuch der Akte. Es liegt neben den
durchgesehenen Blättern und geht **getrennt vom Text** an Supriaha: Ergänzen
kann man es auch zu einem Buch, das jemand anderes geteilt hat.

```sh
nysh note add "ДАХмО 315-1-1234" --kind about --text "Метрична книга Покровської церкви, 1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind catalog-error --field years --archive-says 1834 --actually "1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind copy --other "ДАВіО 904-24-55" --text "копія в консисторії" --share
nysh note read "ДАХмО 315-1-1234" 0031 --line 153 --text "урожденная Прухницкая" --share

nysh note push "ДАХмО 315-1-1234" --dry-run   # що поїде
nysh note push "ДАХмО 315-1-1234"             # віддати
nysh note pull "ДАХмО 315-1-1234"             # що дописали інші
```

An Supriaha geht nur das mit `--share` Markierte und die Liste der
durchgesehenen Blätter ohne Ihre Kommentare. Familiäres — „hier ist mein
Großvater eingetragen“ — schreiben Sie als `--kind note`: Ein solcher Eintrag
geht niemals mit, und einen Eintrag mit familiären Wörtern nimmt der Pool
nicht an, selbst wenn er markiert ist. Auf der Seite des Buches ist das
Notizbuch getrennt vom Text zu sehen und zählt nicht zu den gelesenen Seiten:
Von Hand Geprüftes sind ausgewählte Zeilen, keine gelesene Akte.

Eine geprüfte Zeile geht zusammen mit einem Ausschnitt an Supriaha — einem
Ausschnitt dieser Zeile aus dem Scan als graues JPEG, wenn der Scan der Akte
auf Ihrem Computer liegt (ohne ihn geht die Zeile nur als Text). **Indem Sie
geprüfte Zeilen teilen, erklären Sie sich einverstanden, dass der Betreiber
von Nyshporka sie für das Training von Erkennungsmodellen verwenden kann.**
Anderen Nutzern werden die Ausschnitte nicht weitergegeben und auf der Seite
des Buches nicht gezeigt; der Text der Prüfung ist für alle sichtbar. Ein
zurückgezogener Eintrag (`nysh note retract` und `note push`) nimmt auch den
Ausschnitt aus dem Pool.

## Ein fremdes Paket übernehmen

!!! tip "Wenn Sie über den Agenten übernehmen"
    Der Skill `pull-case` führt den Agenten von `pull` bis zur Suche im
    Übernommenen und liest die Zuordnungsmarke laut vor: Was vom fremden Text
    auf Ihre Aufnahmen passt und was nur für die Suche taugt.

```sh
nysh share inspect <файл або адреса>     # подивитись, нічого не розкладаючи
nysh share import <файл або адреса>      # прийняти
nysh share geometry <….geom.nyshtext>    # докласти рамки рядків
```

Das Paket kommt von einem Menschen, den Sie nicht kennen, und der Empfänger
glaubt ihm nicht aufs Wort:

- **die Prüftore messen den Inhalt, nicht die Angabe**: Seiten, Zeilen und
  der Hash des Textes werden aus dem Paket selbst gezählt, und ein Paket, das
  mehr angibt, als es enthält, kommt nicht durch;
- **ein Fehler im Paket ist eine Ablehnung vor dem Schreiben**: ein Pfad
  außerhalb von `runs/<прогін>/<файл>`, ein unter Windows unzulässiger Name,
  ein Verweis, eine zu große Datei — und auf die Festplatte kommt nichts;
- entpackt werden nur die im Manifest genannten Durchgänge und nur Text mit
  Pass; der Pass wird mit derselben Positivliste bereinigt;
- **Ihre eigene Lesung wird niemals überschrieben** — auch nicht mit
  `--force`. Ein Durchgang mit demselben Namen (ohne Rücksicht auf Groß- und
  Kleinschreibung) — Ablehnung. `--force` ersetzt nur ein früher übernommenes
  Paket;
- ein Paket unter einer Adresse aus dem Katalog wird mit seiner sha256
  abgeglichen (`share pull --take` macht das selbst; für `import` und
  `geometry` per Adresse — `--sha256`): Eine Datei, die im Speicher
  ausgetauscht wurde, nachdem der Pool sie angenommen hatte, wird nicht
  übernommen.

## Wie gut ein fremder Text auf Ihre Aufnahmen passt

Der Schlüssel der Akte taugt dafür nicht: Er wird aus dem Ordnernamen und
Ihrem Archivverzeichnis gebildet, sodass dasselbe Buch bei zwei Menschen
verschiedene Schlüssel erhält. Deshalb trägt das Paket eine Liste der
Aufnahmen und einen Fingerabdruck der Aufnahmeserie, und Nyshporka **misst**
die Übereinstimmung und sagt sie laut:

| Marke | Was sie bedeutet | Was funktioniert |
|---|---|---|
| `exact` | alle Aufnahmen stimmen überein (Hash oder FamilySearch-Kennung) oder der Fingerabdruck der Aufnahmeserie auf mindestens drei Aufnahmen | alles, einschließlich Ausschnitten und fremder Zeilenpositionen |
| `by-name` | Namen und Anzahl stimmen überein | alles außer fremden Zeilenpositionen |
| `by-position` | nur die Anzahl oder ein Teil der Aufnahmen stimmt überein | Seite ja, Ausschnitt fraglich |
| `text-only` | keine Aufnahmen oder andere | Suche, Seite, Signatur |

Fremde Zeilenpositionen passen nur zum Text **desselben Beitrags** und nur
bei `exact`; sonst — Ablehnung mit Erklärung (`--force`, wenn Sie sicher
sind).

`text-only` ist keine Niederlage, sondern der häufigste nützliche Fall: Sie
finden den Nachnamen im fremden Text, sehen Akte und Blattnummer — und gehen
den Scan selbst in der Quelle ansehen.

!!! danger "Ein gleicher Dateiname bedeutet nicht dieselbe Aufnahme"
    Flaches Staging nummeriert die Seiten neu, sodass zwei Aufnahmeserien
    desselben Buches leicht gleiche Namen bei verschiedenem Inhalt ergeben.
    Genau deshalb wird die Marke niemals durch Vermutung heraufgesetzt.

## Die eigene Null und eine fremde Null sind verschiedene Antworten

Übernommene Durchgänge sind markiert, und die Suche nennt das:

```
знаменник: кадрів 3772 · прочитано 3770 · у сторі прогонів 2 із 2 …
з них чужий декод: прогонів 2 із 2 · сторінок 3770 · від oksana
```

Den fremden Text hat ein anderes Modell gelesen, für seine Vollständigkeit
steht hier niemand ein, und neu lesen lässt er sich nur, wenn man den bittet,
der ihn gegeben hat. Eine Null darauf wiegt weniger als eine Null auf dem
eigenen — und das muss sichtbar sein.

## Pool

```sh
nysh share pull                     # огляд пулу: архів · фонд · опис, справ і сторінок
nysh share pull "Слобідка"          # що є в каталозі
nysh share pull "ДАХмО 315-1-1234" --take
nysh share pull --repo RGIA --fond 592           # серія: що в ній є
nysh share pull --repo RGIA --fond 592 --take    # і прийняти всю
nysh share stats --catalog          # хто скільки вніс
nysh share sync --repo DAHMO --fond 315   # зріз для колонки «пул» у `cases fond`
```

Der Katalog ist die API `https://api.nyshporka.online/v1`. Ein eigener
Spiegel oder ein Testserver wird mit der Variablen `NYSHPORKA_TOLOKA` oder der
Option `--base` festgelegt; der Schlüssel von Supriaha geht an eine solche
Adresse **nicht** mit — weder aus dem Schlüsselspeicher noch aus
`NYSHPORKA_SUPRIAHA_TOKEN`. Einen eigenen Server muss man ausdrücklich
nennen: `NYSHPORKA_SUPRIAHA_TRUST=https://хост[:порт]` — nur HTTPS und nur
bei exakter Übereinstimmung der Adresse; dann geht der Schlüssel von Supriaha
an ihn. Die Loopback-Adresse dieses Rechners (`127.0.0.1`, `localhost`) ist
ohnehin vertrauenswürdig.

`sync` mit `--repo`/`--fond` ergänzt den vorhandenen Stand um den Stand eines
Bestands; zu Beständen, die der Stand nicht abdeckt, sagt die Spalte „Pool“
„unbekannt“, nicht „gibt es nicht“.

Eine Ablehnung durch den Pool (Prüftore, Tageskontingent) gibt Nyshporka mit
den Worten des Servers aus. Liegt derselbe Text schon im Pool, sagt
`publish`, ob er angenommen, irgendwann abgelehnt oder noch nicht
abgeschlossen ist — „schon in Supriaha“ bedeutet nur das Erste.

## Spur des Austauschs

`data/share/journal.jsonl` merkt sich, was woher gekommen und was wohin
gegangen ist, und übernommene Pakete bleiben in `data/share/inbox`. Das ist
keine Buchführung um der Buchführung willen: Eine Tatsache, die aus einer
fremden Lesung stammt und in den Kanon eingetragen wurde, muss sich auf eine
dauerhafte Datei stützen — sonst hängt das Zitat in der Luft, sobald Sie den
Download entfernen.

```sh
nysh share list          # журнал
nysh share stats         # скільки віддано, скільки прийнято, від кого
```

## Lizenz

Das Paket nennt, zu welchen Bedingungen der Text geteilt wird (`--license`,
standardmäßig `CC0-1.0`), und gesondert die Bedingungen der Scanquelle
(`--source-terms`), falls es welche gibt. Ohne Lizenz lässt sich das Paket
nicht zusammenstellen: Der Empfänger muss wissen, was er damit tun darf.
