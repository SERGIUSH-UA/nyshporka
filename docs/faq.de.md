# Häufige Fragen

## Scans und Speicherplatz

### Muss ich alle Scans auf den Computer herunterladen?

Ja. Um ein Blatt zu lesen, zerlegt das Modell es in Zeilen und geht jede
durch — das sind Dutzende Zugriffe auf die Datei pro Seite, „im Flug“ von
einer Archivwebsite liest man so nicht.

### Wenn ich die Scans später lösche — geht die Information verloren?

Nicht alle. **Erhalten bleiben** der gelesene Text, die Buchführung über das
Durchgesehene, Funde und Notizen: Sie liegen im Arbeitsordner von Nyshporka,
nicht im Ordner mit den Scans, und die Suche im Text funktioniert weiter.
**Verloren gehen** die Ausschnitte und die Möglichkeit, einen Kandidaten mit
eigenen Augen anzusehen oder die Akte mit einem anderen Modell neu zu lesen.

Bringen Sie die Akte also zu Ende, bevor Sie Platz freigeben. Günstiger ist
es, den Ordner auf eine externe Festplatte zu verschieben und das dem
Assistenten zu sagen (`nysh roots add "E:\скани"`): Die Akte verschwindet
nicht aus den Listen.

### Wie viel Platz wird gebraucht?

Die Anwendung mit den Lesemodellen — etwa 3 GB. Die Scans — so viel, wie sie
eben sind (ein Blatt eines Kirchenbuchs wiegt 2–8 MB). Der gelesene Text —
ein paar MB pro Akte.

### Das Archiv hat ein PDF geliefert, keine einzelnen Seiten

Das Lesen nimmt vorerst nur Bilder: `jpg`, `png`, `tif`, `webp`. Ein PDF muss
zuerst mit einem externen Werkzeug in Seiten zerlegt werden. Ausnahme ist ein
gedrucktes Buch mit Textebene (zum Beispiel aus Чтиво): Es braucht kein
Modell, der Text ist schon da.

## Archive

### Kann ich mit Scans aus jedem Archiv arbeiten?

Ja, sofort: Die Kürzel aller Gebiets- und Zentralarchive der Ukraine stehen
schon im Nachschlagewerk, sodass die Signatur `ДАКО 13-1-1` ohne Einrichtung
angenommen wird. Der Unterschied liegt nur darin, ob Nyshporka den Katalog
des Archivs selbst durchgehen kann: Fertige Kataloge gibt es für ДАХмО und
ЦДІАК, und ARCHIUM-Betrachter anderer Archive lassen sich mit ein paar Zeilen
Einstellungen hinzufügen — bitten Sie den Assistenten.

### Lädt Nyshporka Akten von FamilySearch herunter?

Nein, und das wird sie auch nicht: Das erfordert eine aktive Sitzung im
Browser, und massenhaftes Herunterladen widerspricht den Regeln des Dienstes.
Stattdessen gibt es ein **Filmregister**: welches Dorf auf welchen Aufnahmen
welches Films steht. Es beantwortet „wo sind die Kirchenbücher meines Dorfes“
ohne Download, deckt aber vorerst nur Moldau ab.

Liegen die Aufnahmen eines Films schon auf Ihrer Festplatte, kann man sie als
Akte in die Buchführung aufnehmen: `nysh case <тека> --shifra "<архів
фонд-опис-справа>" --dgs <номер групи зображень>`. Die Nummer wird als Quelle
der Scans in den Aktenpass eingetragen.

## Lesen

### Brauche ich eine Grafikkarte?

Nein. Das Lesen hängt am Prozessor: etwa **2 Minuten pro Seite** auf einem
gewöhnlichen Laptop gegenüber ~20 Sekunden mit Grafikkarte. Eine große Akte
kann man auf einem [gemieteten Rechner](cloud.md) lesen.

### Wie lese ich mehrere Akten nacheinander, ohne daneben zu sitzen?

Stellen Sie sie in die Warteschlange: `nysh queue add <справи>`, dann
`nysh queue run`. Die Warteschlange arbeitet die Akten nacheinander ab; kommt
eine nicht weiter (die Signatur fehlt, die Quelle liefert die Aufnahmen
nicht), wartet sie auf Ihre Entscheidung, und die Warteschlange nimmt die
nächste. `nysh queue` zeigt, was in welchem Schritt ist und wie viel noch
bleibt. Nach der aktuellen Akte anhalten — `nysh queue stop`; nach einem
Anhalten oder einem ausgeschalteten Computer setzt `nysh queue run` an
derselben Stelle fort.

### Der Text kommt mit Fehlern heraus — ist das ein Defekt?

Nein, das ist die Grenze der Technik bei solchem Material. Bei Kursivschrift
des 18.–19. Jh. verwechselt die Maschine ein Viertel bis ein Drittel der
Buchstaben: „Franciszka Lubkowskiego“ wird zu „Francisrha Lubhoustrio90“. Der
Text ist dazu da, darin zu **suchen** — die Suche ist unscharf und findet
auch einen verstümmelten Nachnamen —, und das Gefundene sieht man sich auf dem
Scan an.

### Wozu zwei Modelle für Kyrillisch?

Diak liest dieselben Zeilen wie Pysar, irrt sich aber **anders**: Er hält sich
näher an die Striche selbst, wo Pysar ein plausibles Wort einsetzt. Zusammen
finden sie mehr als jedes für sich.

### Liest Nyshporka polnische Bücher, Latein, das 20. Jahrhundert?

Die Modelle sind an Kursivschrift des 18.–19. Jh. aus ukrainischen,
moldauischen und polnischen Archiven trainiert. Lateinschrift (Notariat,
katholische Kirchenbücher) liest Skryba. Bei einer Schrift, die das Modell
nicht gesehen hat, gibt es mehr Fehler — bei Skryba auf fremden Handschriften
jeder fünfte Buchstabe. Für die Nachnamensuche reicht das meist, für ein
wörtliches Zitat nicht, daher lohnt es sich, die erste Akte aus neuem
Material mit eigenen Augen abzugleichen. Ein Modell auf der eigenen
Handschrift nachtrainieren — [ist möglich](train.md).

## Assistent

### Geht es auch ohne Assistenten?

Einfache Dinge — ja: In der Anwendung im Browser kann man Nachschlagewerke,
Gelesenes und Gefundenes ansehen. Aber den Weg von „wo suchen“ bis „hier ist
Ihr Vorfahr“ ist Nyshporka darauf ausgelegt, zusammen mit dem Assistenten zu
gehen: Er macht Dutzende Schritte, die von Hand Tage dauern würden.

### Was macht der Assistent und was Nyshporka?

Das Lesen der Handschrift und die Suche erledigt Nyshporka auf Ihrem Computer
— das kostet nichts außer Zeit. Der Assistent entscheidet, was als Nächstes
zu tun ist, startet die Schritte und erklärt das Ergebnis. Das Einzige, was
er selbst „mit den Augen liest“, ist die **Auswertung von Akten in Felder**
(Daten, Namen, Rollen): Das sind etwa 84 Tausend Tokens pro Scan, also bei
einem Buch mit zweihundert Blättern Millionen Tokens, und es braucht zwei
Durchgänge.

## Geld und Privatsphäre

### Was kostet das?

Nyshporka — nichts, sie ist frei (AGPL-3.0). Sie zahlen nur für den
Assistenten (sein Abo) und, wenn Sie möchten, für die Miete eines Rechners
zum Lesen — die Kosten sieht man **vor** der Miete.

### Werden meine Scans irgendwohin geschickt?

Nein. Es gibt keine Telemetrie, für die Arbeit braucht man kein Konto. Scans,
Gelesenes und Notizen liegen in einem Ordner auf Ihrer Festplatte. Ins Netz
geht Nyshporka nur, wenn Sie darum gebeten haben: Suche in Katalogen,
Herunterladen einer Akte, Installation von Modellen, Updates. Die
vollständige Liste —
[Datenschutzerklärung](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

Gelesenes mit [Supriaha](share.md) teilen kann man nur nach der Anmeldung
(`nysh share login`) und nur mit Ihrer Zustimmung: Weitergegeben werden der
Text, den die Maschine gelesen hat, und die Beschreibung der Akte. Scans und
Notizen gehen dort niemals hin. Vor jedem Lesedurchgang in der Sammlung
nachfragen und Gelesenes automatisch teilen — beide Modi sind standardmäßig
ausgeschaltet, Sie schalten sie ein (`nysh share setup`).

### Kann ich die Forschung auf einen anderen Computer übertragen?

Ja: Der Arbeitsordner ist ein gewöhnlicher Ordner, man kann ihn vollständig
kopieren. Die Beschreibung jeder Akte liegt im Ordner der Akte selbst, sie
zieht also mit ihr um, auch zu einer Kollegin oder einem Kollegen.

## Updates und Deinstallation

### Wie aktualisiere ich?

Bitten Sie den Assistenten oder führen Sie `nysh update --check` aus — der
Befehl sagt, ob es eine neuere Version gibt und mit welcher Zeile Sie gerade
auf Ihrem Rechner aktualisieren. Unter Windows ist es am einfachsten, das
neue Installationsprogramm herunterzuladen und darüber zu installieren:
Forschung, Modelle und Nachschlagewerke bleiben an ihrem Platz. Nyshporka
selbst erinnert nicht an neue Versionen: Das verspricht die
Datenschutzerklärung.

### Wie deinstalliere ich Nyshporka?

`nysh uninstall` zeigt, was entfernt wird, `nysh uninstall --yes --all`
entfernt alles samt den Modellen. Unter Windows geht es auch wie bei einem
gewöhnlichen Programm — „Programme und Features“. **Der Arbeitsordner mit
Ihrer Forschung wird niemals entfernt.**

## Wenn die Suche nichts gefunden hat { #nichogo-ne-znaishlos }

Ein leeres Ergebnis ist die teuerste Antwort in der Genealogie, weil „gibt es
nicht“ eine Richtung für lange Zeit schließt. Bevor Sie es glauben, fragen
Sie sich (oder den Assistenten) vier Dinge:

1. **Ist der Text lesbar?** Sehen Sie sich die Akte im Betrachter an. Ist
   alles nur Rauschen, betrifft die Null die Qualität des Lesens, nicht das
   Vorkommen des Nachnamens.
2. **Wie viele Blätter wurden tatsächlich durchsucht?** „In 180 von 300
   Blättern nicht gefunden“ und „nicht gefunden“ sind verschiedene Antworten.
3. **Findet die Suche, was hier sicher steht?** Suchen Sie einen Nachnamen,
   den Sie schon mit eigenen Augen auf dem Scan gesehen haben. Nicht gefunden
   — dann liegt es an der Suche.
4. **Wurde in den richtigen Quellen gesucht?** Bitten Sie den Assistenten um
   einen Plan: welche Quellen durchgegangen wurden, wie viel jede
   durchgesehen hat und was als Nächstes kommt.

Der Assistent kennt noch zwei Umwege: die Familie über **Vornamen und
Vatersnamen** suchen, die das Modell weniger verstümmelt als einen langen
Nachnamen, und die **Selbstprüfung** — ob die Suche die Blätter sieht, auf
denen Sie den Nachnamen schon herausgeschrieben haben.

## Was es noch nicht gibt { #chogo-shche-nemaie }

Ehrlich, ohne etwas zu verschweigen:

* **Die Scans bringen Sie selbst mit** — einen Downloader für FamilySearch
  gibt es nicht und wird es nicht geben.
* **Die Auswertung von Akten in Felder macht der Assistent auf Ihre Kosten.**
  Nyshporka bereitet das Blatt vor und prüft die Vollständigkeit, wertet die
  Akten aber nicht selbst aus: Ein eingebauter kostenpflichtiger Dienst würde
  Ihr Geld ohne Ihr Wort ausgeben.
* **Die Art der Seite** (Kirchenbuch, Einband, Register) bestimmt ein Mensch
  oder der Assistent — Nyshporka selbst erkennt das nicht.
* **Ein verblasstes Blatt kann nichts retten** — weder Zoom noch erneutes
  Lesen. Einen solchen Teil der Akte nimmt man neu auf oder akzeptiert ihn
  unvollständig.
* **Die Lesemodelle sind gut bei dem Material, an dem sie gelernt haben**;
  bei anderem sieht schlechter Text genauso selbstsicher aus wie guter.
* **Findbücher gibt es nicht für alle Bestände** — nur dort, wo das Findbuch
  auf Websites veröffentlicht ist, die Nyshporka lesen kann.
* **Das Filmregister deckt nur Moldau ab.**

Technische Einzelheiten der Grenzen — im [Nachschlagewerk der Funktionen](agents/features.md#mezhi-chogo-shche-nemaie).

## Wenn etwas nicht stimmt

| Was Sie sehen | Was zu tun ist |
|---|---|
| „Befehl `nysh` nicht gefunden“ | Den Assistenten (Claude vollständig, über das Symbol neben der Uhr) oder das Terminalfenster schließen und erneut öffnen |
| „Der Computer wurde durch Windows geschützt“ | „Weitere Informationen“ → „Trotzdem ausführen“. Die Datei prüfen — anhand der `.sha256` im [Release](https://github.com/SERGIUSH-UA/nyshporka/releases/latest) |
| Das Installationsprogramm endete mit „Code 1“ | Sehen Sie sich die letzten Zeilen der Ausgabe an: meist ein abgebrochener Download, zu wenig Platz oder ein Virenschutz. Mehr dazu — [Installation](install.md#yakshcho-shchos-ne-tak) |
| Das Fenster der Anwendung ist leer | Ein leeres Fenster schreibt immer, was fehlt. Meist ist die Akte noch nicht angelegt oder der Katalog nicht gesammelt — fragen Sie den Assistenten |
| Die Hälfte der Fenster fehlt | Teile der Anwendung lassen sich ausschalten: ⚙ → «Частини застосунку» (Teile der Anwendung). Das Paket `catalog` enthält kein Lesen von Handschrift |
