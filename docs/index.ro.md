# Nyshporka

<p align="center">
  <img alt="Nyshporka cu lupa" src="assets/maskot-lupa.webp" width="200" height="231">
</p>

<p align="center"><em>Citește manuscrisul. Aduce ce a găsit.</em></p>

**Nyshporka vă ajută să căutați strămoșii în documentele de arhivă** —
registre metrice, liste de spovedanie, revizii din secolele XVIII–XIX. Dar nu
funcționează ca un program obișnuit.

## Munca o face asistentul, decideți dumneavoastră

<p align="center">
  <img alt="O genealogistă examinează o filă adusă de asistentul Nyshporka" src="assets/scena-pomichnyk.webp" width="420" height="382">
</p>

Unui asistent precum Claude sau ChatGPT i se poate permite să lucreze pe
calculatorul dumneavoastră: să deschidă dosare, să pornească programe, să
salveze rezultatul — și de fiecare dată să vă ceară permisiunea. Un astfel de
asistent se numește **agent**.

Nyshporka este făcută tocmai pentru el. Îi scrieți cu cuvinte obișnuite:
*„iată dosarul cu scanările registrelor metrice din Chechelnyk — găsește-i pe
toți Kovalski”*. Asistentul citește filele scrise de mână, caută numele de
familie și vă aduce rândurile găsite direct pe scanare, cu numărul filei.

**Dacă este neamul dumneavoastră — decideți dumneavoastră.** La fel decideți
ce să comandați la arhivă și dacă să împărtășiți ce s-a citit. Asistentul
arată, nu trage concluzii în locul dumneavoastră.

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
* **priceperea de a citi manuscrisul** — trei modele de citire, antrenate pe
  arhive ucrainene, moldovenești și poloneze: **Pysar** și **Diak** citesc
  chirilica, **Skryba** — alfabetul latin;
* **memorie** — ce s-a consultat și ce s-a găsit deja, ca să nu răsfoiască
  aceleași file a doua oară;
* **reguli de lucru cinstit** — „nu am găsit” vine mereu cu explicația câte
  file au fost consultate.

## De ce este o altă abordare

Un program obișnuit știe exact ce i s-a pus în el: câte butoane, atâtea
posibilități. Nyshporka îi dă asistentului priceperi separate — să găsească un
dosar, să citească o filă, să găsească un nume de familie, să noteze o
descoperire — iar el le combină exact pentru întrebarea dumneavoastră:
*„fă un tabel cu toate căsătoriile din acest sat din anii 1820”*, deși nimeni
nu a făcut un buton separat pentru asta. Și cu cât asistenții devin mai
inteligenți, cu atât Nyshporka știe mai multe — chiar și fără actualizare.

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

* [Instalați și conectați asistentul](install.md)
* [Cum se lucrează](start.md) — ce să cereți, cum să verificați ce s-a găsit
* [Întrebări frecvente](faq.md)
* Pentru asistent și dezvoltator — [ghidurile de referință](agents/index.md)
