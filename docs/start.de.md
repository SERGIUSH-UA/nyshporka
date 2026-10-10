# So arbeiten Sie

<p align="center">
  <img alt="Nyshporka liest mit einer Lupe eine Handschrift" src="../assets/maskot-pratsiuie.webp" width="220" height="206">
</p>

Nyshporka ist installiert, der Assistent verbunden ([falls nicht](install.md)).
Ab jetzt sprechen Sie mit dem Assistenten in ganz normaler Sprache, und das
Gefundene sehen Sie sich selbst an.

## Worum Sie bitten können

Ein paar Beispiele — formulieren Sie, wie Sie möchten:

* „Was gibt es über das Dorf Lypovenke? Wo sind seine Kirchenbücher, und was
  lohnt sich im Archiv zu bestellen?“
* „Hier ist der Ordner `D:\скани\ДАКО 13-1-1`, lege ihn als Akte an. Es ist
  ein Kirchenbuch, 1850–1855.“
* „Lies diese Akte.“ (Ein Buch mit 300 Blättern ohne Grafikkarte — das ist
  eine Nacht; der Computer darf nicht einschlafen.)
* „Finde hier die Kowalskis und zeig mir die Zeilen auf dem Scan.“
* „Halte fest, dass ich die Blätter 12–40 durchgesehen habe: Unserer ist dort
  nicht.“
* „Mach eine Tabelle aller Trauungen in diesem Buch in den 1820er Jahren.“
* „Nichts gefunden — wo soll ich weitergraben?“

Der Assistent kennt den Arbeitsablauf selbst: Dafür hat er Skills — fertige
Abläufe, wie man eine Akte liest, wie man einen Nachnamen sucht, wo man
weitergräbt, wie man Durchgesehenes festhält.

## Die Scans bringen Sie selbst mit

Nyshporka lädt keine Akten von FamilySearch oder aus Archivportalen herunter,
bei denen man sich mit dem eigenen Konto anmelden muss. Sie speichern die
Seiten aus dem Archivbetrachter auf der Festplatte, wie Sie es auch ohne sie
tun würden. Die Anforderungen an den Ordner sind einfach und streng:

| Regel | Warum |
|---|---|
| ein Ordner = eine Akte | Signatur, Buchführung und Funde hängen am Ordner |
| die Bilder liegen direkt im Ordner | in Unterordner geht das Lesen nicht hinein |
| `jpg`, `png`, `tif`, `webp` | andere Formate zählen nicht als Aufnahmen |
| PDF kann man so ablegen, wie es ist | die Seiten werden vor dem Lesen von selbst in Aufnahmen zerlegt |

Der Ordner kann liegen, wo Sie möchten — externe Festplatte, Desktop,
Netzwerk. Dateien werden nirgendwohin verschoben; der Assistent bittet um
Erlaubnis, den Ordner in die Buchführung aufzunehmen. In der Anwendung
geschieht das im Fenster **📥 Нові теки** (Neue Ordner) → «Описати»
(Beschreiben): Für einen Ordner außerhalb der Forschung erscheint dort das
Häkchen «Показувати цю теку в переліках там, де вона лежить» (Diesen Ordner
in den Listen dort zeigen, wo er liegt).

## Wie Sie Gefundenes prüfen

Der Assistent zeigt Kandidaten, und Sie entscheiden. Dafür gibt es die
**Anwendung im Browser** — die Verknüpfung „Нишпорка“ auf dem Desktop oder
`nysh serve`, Adresse `127.0.0.1:8788`.

* **📄 Гортач** (Betrachter) — Scan und gelesener Text nebeneinander. Klicken
  Sie auf eine Zeile — Sie sehen den Ausschnitt des Blattes, aus dem sie
  gelesen wurde.
* **🔎 Пошук** (Suche) — alle Kandidaten mit Treffer, jeder mit seinem
  Ausschnitt. Es sucht derselbe Befehl wie beim Assistenten, und unter den
  Ergebnissen steht, wo und womit gesucht wurde.
* **👁 Облік** (Buchführung) — was schon mit eigenen Augen durchgesehen ist,
  sogar leere Blätter.

Sagt der Assistent „gefunden“ — bitten Sie um den Ausschnitt. Sagt er „gibt es
nicht“ — fragen Sie, wie viele Blätter geprüft wurden.

## Drei Regeln

* **„Gibt es nicht“ ohne Zahl ist keine Antwort.** Richtig klingt es so: „180
  von 300 Blättern durchsucht, im Gelesenen keine Treffer“. Ein falsches „gibt
  es nicht“ schließt eine Suchrichtung für immer.
* **Die Maschine findet, Sie entscheiden.** Der gelesene Text hat Fehler — bei
  Kursivschrift des 18.–19. Jh. jeder dritte bis vierte Buchstabe. Man sucht
  darin, das Gefundene sieht man sich auf dem Scan an. Verwerfen Sie keinen
  Kandidaten, nur weil der Wortstamm nicht ähnlich aussieht: Das Modell
  verstümmelt gerade die Mitte des Nachnamens.
* **Zahlen gleichen Sie mit dem Scan ab.** Jahre, Alter, Aktennummern
  verwechselt die Maschine häufiger als Wörter, und es sieht genauso
  selbstsicher aus.

## Fenster der Anwendung { #vikna-zastosunku }

Jedes Fenster beantwortet eine Frage, und „gibt es nicht“ bedeutet in jedem
etwas anderes.

| Fenster | Frage |
|---|---|
| 🐾 Огляд (Übersicht) | wo stehe ich: was schon da ist, was gelesen ist, was nicht zu Ende gelesen ist, Prüfung des Rechners |
| 🔎 Пошук (Suche) | wo im Gelesenen mein Nachname, mein Dorf oder ein beliebiges Wort steht — in der ganzen Bibliothek, in einem Bestand oder einer Akte |
| 🎯 Рід (Familie) | wessen Nachnamen wir suchen und in welchen Schreibweisen — das Einzige, was Sie angeben |
| 📥 Нові теки (Neue Ordner) | was auf der Festplatte noch keine Akte geworden ist: mit einer Signatur beschreiben oder als „keine Akte“ beiseitelegen |
| 🗺 Газетир (Ortsverzeichnis) | wo die Dokumente meines Dorfes liegen |
| 🔎 Каталоги (Kataloge) | was in Archivführern und auf Archivwebsites steht; der Katalog einer Website wird per Schaltfläche gesammelt |
| 🏛 Описи фондів (Findbücher) | was im Archiv überhaupt existiert, auch Nicht-Digitalisiertes |
| 📚 Бібліотека (Bibliothek) | was ich auf der Festplatte habe |
| 🖋 Читання · 📜 Прогони (Lesen · Durchgänge) | eine Akte lesen · womit und wie weit gelesen wurde, was noch zu Ende zu lesen ist |
| 📄 Гортач · 🔍 Розбір · 👁 Облік (Betrachter · Auswertung · Buchführung) | Gelesenes neben dem Scan · Kandidaten mit Ausschnitten · was ich schon mit eigenen Augen gesehen habe |

Ein ausführliches Nachschlagewerk zu den Fenstern — [„Bildschirmkarte“](agents/screens.md).

## Ausprobieren ohne eigene Scans

In der Anwendung: **🐾 Огляд** (Übersicht) → «Перевірити цю машину» (Diesen
Rechner prüfen) → «Розгорнути зразок» (Beispiel entpacken) (oder
`nysh sample`). Das sind drei bereits gelesene Blätter der Akte
**ДАХмО 315-1-159** (1821–1822): An ihnen sieht man Betrachter, Ausschnitte
und Suche, noch bevor Sie eigene Scans mitbringen.

## Was Nyshporka sonst noch kann

* **Ortsverzeichnis und Nachschlagewerke** gleich nach der Installation: der
  Sammelkatalog des ЦДІАК (4566 Orte), der Katalog des ДАХмО, das Register der
  FamilySearch-Filme zu Moldau, Kirchen um 1772.
* **Kataloge von Archivwebsites** — ARCHIUM, „Бабин Яр“, Wikimedia Commons,
  Duck Inspector, ridni.org, Чтиво, Internet Archive.
* **Akten in eine Tabelle auswerten** — Daten, Namen, Rollen, Stand, Alter —
  und nach Excel exportieren. Die Auswertung macht der Assistent selbst, also
  auf Kosten Ihres Abos.
* **Ein Modell nachtrainieren** auf Ihrer Handschrift — [mehr dazu](train.md).
* **Eine große Akte auf einem gemieteten Rechner lesen** in einer Stunde statt
  einer Woche — [mehr dazu](cloud.md).

Die vollständige technische Liste mit Befehlen — [Nachschlagewerk der Funktionen](agents/features.md).

## Updates

Nyshporka geht nicht von selbst ins Netz und erinnert nicht an neue Versionen.
Bitten Sie den Assistenten ab und zu, nachzusehen, oder führen Sie
`nysh update --check` aus.
