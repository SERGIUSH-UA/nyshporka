# Cum se lucrează

<p align="center">
  <img alt="Nyshporka citește un manuscris cu lupa" src="../assets/maskot-pratsiuie.webp" width="220" height="206">
</p>

Nyshporka este instalată, asistentul este conectat ([dacă nu](install.md)).
Mai departe vorbiți cu asistentul în limbaj obișnuit, iar ce s-a găsit
verificați singuri.

## Ce puteți cere

Câteva exemple — formulați cum doriți:

* „Ce există despre satul Lypovenke? Unde sunt registrele lui metrice și ce
  merită comandat la arhivă?”
* „Iată directorul `D:\скани\ДАКО 13-1-1`, înregistrează-l ca dosar. Este un
  registru metric, 1850–1855.”
* „Citește acest dosar.” (O carte de 300 de file fără placă video înseamnă o
  noapte; calculatorul nu trebuie să intre în repaus.)
* „Găsește aici familia Kovalski și arată-mi rândurile pe scanare.”
* „Notează că am consultat filele 12–40: ai noștri nu sunt acolo.”
* „Fă un tabel cu toate căsătoriile din această carte din anii 1820.”
* „Nu s-a găsit nimic — unde să săpăm mai departe?”

Asistentul știe singur ordinea lucrului: pentru asta are skill-uri —
proceduri gata făcute despre cum se citește un dosar, cum se caută un nume de
familie, unde să se sape, cum se notează ce s-a consultat.

## Scanările le aduceți dumneavoastră

Nyshporka nu descarcă dosare de pe FamilySearch sau din conturile de pe
site-urile arhivelor, unde trebuie să intrați cu propriul cont. Salvați
paginile din vizualizatorul arhivei pe disc, cum ați face și fără ea.
Cerințele pentru director sunt simple și stricte:

| regulă | de ce |
|---|---|
| un director = un dosar | cota, evidența și descoperirile se leagă de director |
| imaginile stau direct în director | citirea nu intră în subdirectoare |
| `jpg`, `png`, `tif`, `webp` | alte formate nu se socotesc imagini |
| PDF-ul se poate pune așa cum este | paginile se desfac singure în imagini înainte de citire |

Directorul poate sta oriunde — pe un disc extern, pe desktop, în rețea.
Fișierele nu se mută nicăieri; asistentul va cere permisiunea de a lua
directorul în evidență. În aplicație acest lucru se face în fereastra
**📥 Нові теки** (Directoare noi) → «Описати» (Descrieți): pentru un director
din afara cercetării va apărea acolo bifa «Показувати цю теку в переліках там,
де вона лежить» (Afișați acest director în liste acolo unde se află).

## Cum verificați ce s-a găsit

Asistentul arată candidații, iar decizia vă aparține. Pentru asta există
**aplicația din browser** — scurtătura „Нишпорка” de pe desktop sau
`nysh serve`, adresa `127.0.0.1:8788`.

* **📄 Гортач** (Răsfoitorul) — scanarea și textul citit alăturate. Faceți
  clic pe un rând — veți vedea decupajul din filă din care a fost citit.
* **🔎 Пошук** (Căutare) — toți candidații care se potrivesc, fiecare cu
  decupajul lui. Caută aceeași comandă ca la asistent, iar sub rezultate scrie
  unde și cu ce s-a căutat.
* **👁 Облік** (Evidența) — ce s-a consultat deja cu ochiul, chiar și filele
  goale.

Dacă asistentul spune „găsit” — cereți decupajul. Dacă spune „nu există” —
întrebați câte file au fost verificate.

## Trei reguli

* **„Nu există” fără un număr nu este un răspuns.** Corect sună așa: „au fost
  căutate 180 de file din 300, în textul citit nu există potriviri”. Un „nu
  există” greșit închide direcția căutării pentru totdeauna.
* **Calculatorul găsește, decideți dumneavoastră.** Textul citit are greșeli
  — în cursiva din secolele XVIII–XIX, fiecare a treia-a patra literă. În el
  se caută, iar ce s-a găsit se verifică pe scanare. Nu respingeți un
  candidat pentru că rădăcina cuvântului nu seamănă: modelul strică tocmai
  mijlocul numelui de familie.
* **Cifrele verificați-le pe scanare.** Anii, vârsta, numerele actelor
  calculatorul le încurcă mai des decât cuvintele, iar asta arată la fel de
  sigur.

## Ferestrele aplicației { #vikna-zastosunku }

Fiecare fereastră răspunde la o singură întrebare, iar „nu există” înseamnă
în fiecare altceva.

| fereastră | întrebare |
|---|---|
| 🐾 Огляд (Prezentare) | unde mă aflu: ce am deja, ce s-a citit, ce nu s-a terminat de citit, verificarea calculatorului |
| 🔎 Пошук (Căutare) | unde apare în textul citit numele meu de familie, satul sau orice cuvânt — în toată biblioteca, în fond sau în dosar |
| 🎯 Рід (Neamul) | al cui nume de familie îl căutăm și în ce grafii — singurul lucru pe care îl indicați dumneavoastră |
| 📥 Нові теки (Directoare noi) | ce de pe disc nu a devenit încă dosar: descrieți-l cu cotă sau puneți-l deoparte ca „nu e dosar” |
| 🗺 Газетир (Dicționar geografic) | unde sunt documentele satului meu |
| 🔎 Каталоги (Cataloage) | ce există în ghidurile arhivelor și pe site-urile arhivelor; catalogul unui site se construiește cu un buton |
| 🏛 Описи фондів (Inventarele fondurilor) | ce există în general în arhivă, chiar și nedigitizat |
| 📚 Бібліотека (Biblioteca) | ce am pe disc |
| 🖋 Читання · 📜 Прогони (Citire · Rulări) | citiți un dosar · cu ce și cât s-a citit, ce a rămas de citit |
| 📄 Гортач · 🔍 Розбір · 👁 Облік (Răsfoitorul · Analiza · Evidența) | textul citit alături de scanare · candidați cu decupaje · ce am văzut deja cu ochiul |

Ghidul detaliat al ferestrelor — [„Harta ecranelor”](agents/screens.md).

## Încercați fără scanări proprii

În aplicație: **🐾 Огляд** (Prezentare) → «Перевірити цю машину» (Verificați
acest calculator) → «Розгорнути зразок» (Desfaceți exemplul) (sau
`nysh sample`). Sunt trei file deja citite din dosarul **ДАХмО 315-1-159**
(1821–1822): pe ele se văd răsfoitorul, decupajele și căutarea încă înainte să
aduceți propriile scanări.

## Ce mai știe Nyshporka

* **Dicționarul geografic și ghidurile** imediat după instalare: catalogul
  consolidat al ЦДІАК (4566 de localități), catalogul ДАХмО, indexul
  microfilmelor FamilySearch pentru Moldova, bisericile din jurul anului 1772.
* **Cataloagele site-urilor arhivelor** — ARCHIUM, «Бабин Яр», Wikimedia
  Commons, Duck Inspector, ridni.org, Чтиво, Internet Archive.
* **Analiza actelor într-un tabel** — date, nume, roluri, stare civilă, vârstă
  — și exportul în Excel. Analiza o face asistentul însuși, adică pe seama
  abonamentului dumneavoastră.
* **Antrenarea suplimentară a modelului** pe scrisul dumneavoastră —
  [detalii](train.md).
* **Citirea unui dosar mare pe un calculator închiriat** într-o oră în loc de
  o săptămână — [detalii](cloud.md).

Lista tehnică completă cu comenzi — [ghidul posibilităților](agents/features.md).

## Actualizări

Nyshporka nu iese singură în rețea și nu amintește de versiunile noi. Din când
în când cereți asistentului să verifice sau rulați `nysh update --check`.
