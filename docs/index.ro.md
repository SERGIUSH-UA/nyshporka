# Nyshporka

<p align="center" markdown>
![Nyshporka cu lupa](assets/maskot-lupa.webp){ width="200" height="231" }
</p>

<p align="center"><em>Citește manuscrisul. Aduce ce a găsit.</em></p>

**Nyshporka este un asistent AI pentru genealogiști și pentru toți cei care
cercetează trecutul după manuscrise vechi.** Spuneți pe cine și unde căutați,
iar asistentul găsește registrele de arhivă potrivite, citește manuscrisul
vechi și arată ce a găsit direct pe scanare.

## Munca o face asistentul, decideți dumneavoastră

<p align="center" markdown>
![O genealogistă examinează o filă adusă de asistentul Nyshporka](assets/scena-pomichnyk.webp){ width="420" height="382" }
</p>

Unui asistent precum Claude sau ChatGPT i se poate permite să lucreze pe
calculatorul dumneavoastră: să deschidă dosare, să pornească programe, să
salveze rezultatul, cerându-vă de fiecare dată permisiunea. Un astfel de
asistent se numește **agent**.

Nyshporka este făcută tocmai pentru el. Îi scrieți cu cuvinte obișnuite:
*„iată dosarul cu scanările registrelor metrice din Chechelnyk — găsește-i pe
toți Kovalski”*. Agentul stabilește singur în ce registre pot fi înscrieri
despre sat, aduce scanările, citește manuscrisul și arată rândurile cu numele de
familie pe pagină, cu numărul filei.

Vă uitați la aceste rânduri și decideți singur dacă sunt strămoșii
dumneavoastră. La fel decideți ce să comandați la arhivă și dacă să
împărtășiți ce s-a citit. Asistentul arată ce a găsit, iar concluziile le
trageți dumneavoastră.

!!! tip "Lecții video"

    [O serie de lecții video scurte](https://nyshporka.online/ro/uroky) — de
    la instalare la prima descoperire și un arbore cu dovezi, câte 5–9 minute.
    Seria continuă. Lecțiile sunt în ucraineană, cu subtitrări în română.

!!! tip "Vedeți în direct"

    Nyshporka este arătată la lucru în transmisiunea
    [«ШІ-агенти в генеалогії: дослідження майбутнього»](https://www.youtube.com/live/VsvenHgbVZY)
    („Agenți IA în genealogie: cercetarea viitorului”, «В гостях у Качки»
    nr. 11) — [demonstrația începe pe la minutul
    42](https://www.youtube.com/live/VsvenHgbVZY?t=2550).

## Ce îi dă Nyshporka asistentului

Singur, asistentul nu cunoaște arhivele și nu poate citi un manuscris vechi.
Nyshporka îi dă:

* **știința unde se află fiecare lucru** — ghiduri ale arhivelor, inventare
  ale fondurilor, liste de sate și parohii;
* **priceperea de a citi manuscrisul** — modele proprii de citire, antrenate pe
  arhive ucrainene, moldovenești și poloneze: **Pysar** și **Diak** citesc
  chirilica, **Skryba** — alfabetul latin;
* **memorie** — ce s-a consultat și ce s-a găsit deja, ca să nu răsfoiască
  aceleași file a doua oară;
* **reguli de lucru cinstit** — fiecare descoperire se vede pe scanare, iar „nu
  am găsit” vine mereu cu explicația câte file au fost consultate.

## Butoane gata făcute nu există aici

Un program obișnuit știe exact ce i s-a pus în el: câte butoane, atâtea
posibilități. Nyshporka îi dă asistentului priceperi separate: să găsească un
dosar, să citească o filă, să găsească un nume de familie, să noteze o
descoperire. Din ele el alcătuiește ce are nevoie întrebarea dumneavoastră,
chiar dacă nimeni nu a făcut o comandă separată pentru asta: *„fă un tabel cu
toate căsătoriile din acest sat din anii 1820”*. Așa se parcurge tot drumul: de
la „unde să caut” până la arborele genealogic în care fiecare fapt are atașat
un decupaj din scanare, și mai departe la site-ul neamului, cu arbore și hartă.
Și cu cât asistenții devin mai inteligenți, cu atât Nyshporka știe mai multe,
chiar și fără actualizare.

## Nu doar strămoși

Se poate căuta nu doar un nume de familie, ci și numele unui sat, un cuvânt sau
un eveniment. De aceea, în aceleași registre se cercetează istoria unui sat sau
a unei parohii, a unei biserici sau a unei mănăstiri, obiceiurile locale,
biografia unei persoane cunoscute. De exemplu, istoria propriului sat poate fi
citită din registrele tribunalelor de cetate din secolul al XVII-lea: Nyshporka
găsește printre mii de pagini fiecare mențiune despre sat, oameni și
evenimente și o arată pe scanare. Mai multe: [nu doar genealogie](how-it-works.md#ne-lyshe-rodovid).

## Ce este necesar

* Un calculator cu Windows, macOS sau Linux și aproximativ 5 GB de spațiu
  liber.
* Nyshporka însăși — gratuită, cu cod deschis.
* Un asistent care știe să lucreze pe calculator: **Claude Desktop**
  (abonament Claude Pro sau Max), **Claude Code** sau **Codex** (abonament
  ChatGPT).

Totul se instalează în jumătate de oră, fără nicio comandă —
[**„Instalați și conectați asistentul”**](install.md). Modelele de citire le
va instala asistentul singur: sunt doi pași unici, `nysh htr install` și
`nysh models get`.

**Scanările nu pleacă nicăieri** — totul funcționează pe calculatorul
dumneavoastră. Nu există telemetrie și nici conturi.

!!! warning "Stadiu: versiune timpurie"

    Cataloagele, citirea manuscrisului, căutarea numelui de familie, evidența
    și aplicația din browser funcționează. Ce nu există încă — în
    [întrebările frecvente](faq.md#chogo-shche-nemaie), fără nimic ascuns.

## Cuvinte pe care le veți întâlni aici { #slovnyk }

| cuvânt | ce înseamnă |
|---|---|
| **asistent (agent)** | asistentul IA — Claude Desktop, Claude Code sau Codex — căruia i se permite să lucreze pe calculatorul dumneavoastră |
| **modele de citire** | Pysar, Diak și Skryba — ele transformă fila scrisă de mână în text |
| **text citit** | ceea ce modelul a citit de pe filă. Are greșeli: în el se caută, iar ce s-a găsit se verifică pe scanare |
| **dosar** | unitate arhivistică de păstrare cu cotă, de ex. `ДАХмО 315-1-8433`; în Nyshporka — un director cu scanări |
| **filă · imagine** | pagina dosarului · o imagine (scanare) |
| **fotografiere** | setul de scanări ale unui dosar — propriu, cumpărat sau de pe site-ul arhivei |
| **director de lucru** | directorul Nyshporka, implicit `Documente\Нишпорка`: acolo se află cercetarea dumneavoastră. În comenzi se numește „spațiu” |
| **aplicație** | fereastra Nyshporka din browser — ca să vedeți ce s-a găsit, să răsfoiți scanările și textul citit |
| **skill-uri** | proceduri de lucru gata făcute pentru asistent: cum se citește un dosar, cum se caută un nume de familie, unde să săpați mai departe |
| **Supriaha** | banca comună de dosare citite pe [nyshporka.online/supriaha](https://nyshporka.online/supriaha): ce a citit unul nu mai trebuie citit a doua oară |

## Mai departe

* [Cum funcționează](how-it-works.md) — întregul ciclu, de la „unde să caut”
  la site-ul familiei, și cum se găsește un nume în manuscris (în ucraineană)
* [Instalați și conectați asistentul](install.md)
* [Cum se lucrează](start.md) — ce să cereți, cum să verificați ce s-a găsit
* [Întrebări frecvente](faq.md)
* Pentru asistent și dezvoltator — [ghidurile de referință](agents/index.md)
