# Nyshporka

<p align="center" markdown>
![Nyshporka mit einer Lupe](assets/maskot-lupa.webp){ width="200" height="231" }
</p>

<p align="center"><em>Liest die Handschrift. Bringt das Gefundene.</em></p>

**Nyshporka ist ein KI-Assistent für Genealogen und alle, die die
Vergangenheit anhand alter Handschriften erforschen.** Sie sagen, wen und wo
Sie suchen, und der Assistent findet die passenden Archivbücher, liest die alte
Handschrift und zeigt das Gefundene direkt auf dem Scan.

## Die Arbeit macht der Assistent, entscheiden tun Sie

<p align="center" markdown>
![Eine Genealogin sieht sich ein Blatt an, das ihr der Assistent Nyshporka gebracht hat](assets/scena-pomichnyk.webp){ width="420" height="382" }
</p>

Einem Assistenten wie Claude oder ChatGPT kann man erlauben, auf Ihrem
Computer zu arbeiten: Ordner öffnen, Programme starten, Ergebnisse speichern
und dabei jedes Mal um Ihre Erlaubnis bitten. Einen solchen Assistenten nennt
man **Agenten**.

Nyshporka ist genau für ihn gemacht. Sie schreiben in ganz normalen Worten:
*„Hier ist ein Ordner mit Scans der Kirchenbücher von Chechelnyk — finde alle
Kowalskis“*. Der Agent findet selbst heraus, in welchen Büchern Einträge zum
Dorf stehen können, besorgt die Scans, liest die Handschrift und zeigt die
Zeilen mit dem Nachnamen auf der Seite, mit der Blattnummer.

Sie sehen sich diese Zeilen an und entscheiden selbst, ob es Ihre Vorfahren
sind. Ebenso entscheiden Sie, was Sie im Archiv bestellen und ob Sie Gelesenes
teilen. Der Assistent zeigt, was er gefunden hat, die Schlüsse ziehen Sie.

!!! tip "Videokurs"

    [Eine Reihe kurzer Videolektionen](https://nyshporka.online/de/uroky) —
    von der Installation bis zum ersten Fund und einem Stammbaum mit Belegen,
    je 5–9 Minuten. Die Reihe wächst weiter. Die Lektionen sind auf
    Ukrainisch, mit Untertiteln, die YouTube in Ihre Sprache übersetzt.

!!! tip "Live ansehen"

    Nyshporka ist im Livestream
    [„ШІ-агенти в генеалогії: дослідження майбутнього“](https://www.youtube.com/live/VsvenHgbVZY)
    („В гостях у Качки“ Nr. 11) bei der Arbeit zu sehen — [Vorführung ab etwa
    Minute 42](https://www.youtube.com/live/VsvenHgbVZY?t=2550).

## Was Nyshporka dem Assistenten gibt

Von sich aus kennt der Assistent keine Archive und liest keine alte
Handschrift. Nyshporka gibt ihm:

* **Wissen, wo was liegt** — Archivverzeichnisse, Findbücher der Bestände,
  eine Liste der Dörfer und Pfarreien;
* **die Fähigkeit, Handschrift zu lesen** — eigene Lesemodelle, trainiert an
  ukrainischen, moldauischen und polnischen Archiven: **Pysar** und **Diak**
  lesen Kyrillisch, **Skryba** liest Lateinschrift;
* **ein Gedächtnis** — was schon durchgesehen und gefunden ist, damit
  dieselben Blätter nicht ein zweites Mal durchgeblättert werden;
* **Regeln ehrlicher Arbeit** — jeder Fund ist auf dem Scan zu sehen, und
  „nicht gefunden“ kommt immer mit der Erklärung, wie viele Blätter
  durchgesehen wurden.

## Fertige Schaltflächen gibt es hier nicht

Ein gewöhnliches Programm kann genau das, was man ihm eingebaut hat: so viele
Schaltflächen, so viele Möglichkeiten. Nyshporka gibt dem Assistenten
einzelne Fähigkeiten: eine Akte finden, ein Blatt lesen, einen Nachnamen
finden, einen Fund festhalten. Daraus setzt er zusammen, was Ihre Frage
verlangt, auch wenn dafür niemand einen eigenen Befehl gebaut hat: *„Mach eine
Tabelle aller Trauungen in diesem Dorf in den 1820er Jahren“*. So wird der
ganze Weg abgedeckt: von „wo suchen“ bis zum Stammbaum, in dem an jedem Fakt
ein Ausschnitt des Scans hängt, und weiter zur Familienwebsite mit Baum und
Karte. Und je klüger die Assistenten werden, desto mehr kann Nyshporka, sogar
ohne Update.

## Nicht nur Vorfahren

Gesucht werden kann nicht nur ein Nachname, sondern auch der Name eines Dorfes,
ein Wort oder ein Ereignis. Darum erforscht man anhand derselben Bücher auch
die Geschichte eines Dorfes oder einer Pfarrei, einer Kirche oder eines
Klosters, örtlicher Bräuche oder die Biografie einer bekannten Person. Die
Geschichte des eigenen Dorfes lässt sich zum Beispiel aus den Burggerichtsbüchern
des 17. Jahrhunderts herauslesen: Nyshporka findet in Tausenden Seiten jede
Erwähnung des Dorfes, seiner Menschen und Ereignisse und zeigt jede auf dem
Scan. Mehr unter [nicht nur Ahnenforschung](how-it-works.md#ne-lyshe-rodovid).

## Was Sie brauchen

* Einen Computer mit Windows, macOS oder Linux und etwa 5 GB freien Platz.
* Nyshporka selbst — kostenlos, mit offenem Quellcode.
* Einen Assistenten, der auf dem Computer arbeiten kann: **Claude Desktop**
  (Abo Claude Pro oder Max), **Claude Code** oder **Codex** (Abo ChatGPT).

All das ist in einer halben Stunde installiert, ohne einen einzigen Befehl —
[**„Installieren und den Assistenten verbinden“**](install.md). Die
Lesemodelle installiert der Assistent selbst: Das sind zwei einmalige
Schritte, `nysh htr install` und `nysh models get`.

**Die Scans gehen nirgendwohin** — alles läuft auf Ihrem Computer. Es gibt
weder Telemetrie noch Benutzerkonten.

!!! warning "Stand: frühe Version"

    Kataloge, das Lesen von Handschrift, die Nachnamensuche, die Buchführung
    und die Anwendung im Browser funktionieren. Was es noch nicht gibt — in den
    [häufigen Fragen](faq.md#chogo-shche-nemaie), ohne etwas zu verschweigen.

## Wörter, die hier vorkommen { #slovnyk }

| Wort | Was das ist |
|---|---|
| **Assistent (Agent)** | ein KI-Assistent — Claude Desktop, Claude Code oder Codex —, der auf Ihrem Computer arbeiten darf |
| **Lesemodelle** | Pysar, Diak und Skryba — sie machen aus einem handschriftlichen Blatt Text |
| **gelesener Text** | das, was das Modell vom Blatt gelesen hat. Er enthält Fehler: Man sucht darin, das Gefundene sieht man sich auf dem Scan an |
| **Akte** | eine archivische Verzeichnungseinheit mit Signatur, z. B. `ДАХмО 315-1-8433`; in Nyshporka ein Ordner mit Scans |
| **Blatt · Aufnahme** | eine Seite der Akte · ein Bild (Scan) |
| **Aufnahmeserie** | die Scans einer Akte — Ihre eigenen, gekauften oder von einer Archivwebsite |
| **Arbeitsordner** | der Ordner von Nyshporka, standardmäßig `Документи\Нишпорка` (der Ordner „Нишпорка“ unter „Dokumente“): Dort liegt Ihre Forschung. In Befehlen heißt er „Arbeitsbereich“ (space) |
| **Anwendung** | das Fenster von Nyshporka im Browser — um Gefundenes zu sehen, Scans und Gelesenes durchzublättern |
| **Skills** | fertige Arbeitsabläufe für den Assistenten: wie man eine Akte liest, wie man einen Nachnamen sucht, wo man weitergräbt |
| **Supriaha** | eine gemeinsame Sammlung gelesener Akten unter [nyshporka.online/supriaha](https://nyshporka.online/supriaha): Was einer gelesen hat, muss nicht noch einmal gelesen werden |

## Wie es weitergeht

* [Wie es funktioniert](how-it-works.md) — der ganze Ablauf von „wo suchen“ bis
  zur Familienseite und wie ein Name in der Handschrift gefunden wird (auf Ukrainisch)
* [Installieren und den Assistenten verbinden](install.md)
* [So arbeiten Sie](start.md) — worum Sie bitten, wie Sie Gefundenes prüfen
* [Häufige Fragen](faq.md)
* Für Assistenten und Entwickler — [Nachschlagewerke](agents/index.md)
