# Împărtășiți textul citit (Supriaha)

Aceeași carte de arhivă o recunoaște astăzi fiecare separat. O citire nu
costă mult, dar costă **de fiecare dată**: un dosar de trei mii de file
înseamnă ore de lucru al calculatorului, iar pentru ele plătește oricine a
ajuns la el. Textul este însă același, iar la cineva el se află deja gata.

Supriaha (`nyshporka.online`) este banca comună de dosare citite. Pleacă
tocmai textul, nu imaginile: un dosar de 3772 de file ocupă în pachet
**3–4 megaocteți**.

!!! note "Imaginile nu intră niciodată în pachet"
    Pachetul poartă textul citit automat și pașaportul felului în care a fost
    obținut. Scanările înseși rămân la cel care le-a descărcat, iar pachetul
    doar numește sursa — ca destinatarul să le poată lua din același loc și
    în aceleași condiții.

## Calea cea mai scurtă

```sh
nysh share login                                  # один раз: браузер, одна кнопка
nysh share setup --as "ваше імʼя"                 # один раз: профіль
nysh share pack "ДАХмО 315-1-1234"                # спакувати справу
nysh share publish data/share/outbox/DAHMO_315-1-1234.nyshtext
```

De partea cealaltă:

```sh
nysh share pull "ДАХмО 315-1-1234" --take         # знайти в пулі й прийняти
nysh share pull --repo RGIA --fond 592 --opys 25 --take   # уся серія одним викликом
```

Citirile primite ajung în același loc cu textul citit propriu și intră imediat
în depozitul de text, așa că `nysh text find`, `grep` și `ctx` le văd fără un
`text index` separat. Se poate căuta într-o serie la fel ca într-un dosar:
`nysh text find <прізвище> --case "RGIA 592-25"`; pentru mai multe dosare —
repetați `--case`.

!!! tip "Dacă împărtășiți prin agent"
    Skill-ul `share-case` îl duce pe agent pe aceeași cale și păzește locurile
    care se strică pe tăcute: cota o verifică în dry-run înainte de încărcare,
    anii din catalogul FamilySearch nu îi ia, iar fișa setată cu `share card`
    o duce până în banca comună printr-o nouă încărcare. Se instalează
    împreună cu celelalte skill-uri: `nysh skills install`.

## Conectare

`nysh share login` deschide pagina nyshporka.online: vă conectați prin e-mail
sau Google ori anonim. Cheia ajunge singură în Nyshporka și se pune în
depozitul de chei al sistemului — nu trebuie copiat nimic. Ca să ștergeți
cheia de pe calculator: `nysh share logout`. Pe un server fără browser, cheia
se pune în variabila `NYSHPORKA_SUPRIAHA_TOKEN`, iar ea se emite în Contul meu.

Căutarea, preluarea și oferirea pachetelor banca comună le permite doar cu
cheie. Dacă încă nu o aveți, `pull`, `sync` și `publish` vă vor propune singure
să vă conectați.

## Profilul

`nysh share setup` fără opțiuni întreabă pe rând; cu orice opțiune — doar
salvează ce s-a numit și nu întreabă nimic (pentru scripturi și programul de
instalare).

| câmp | opțiune | implicit |
|---|---|---|
| pseudonim în catalog | `--as` | fără nume |
| contact (public) | `--contact`, ștergere — `--contact -` | nu există |
| licența textului | `--license` | `CC0-1.0` |
| când se oferă | `--consent nikoly \| pytaty \| zavzhdy` | `pytaty` — ține lista și amintește |
| întreabă banca comună înaintea citirii | `--lookup / --no-lookup` | **nu** |
| contururile rândurilor | `--geometry / --no-geometry` | da |

!!! warning "Contactul este o dată publică"
    El pleacă în fiecare pachet al dumneavoastră și este vizibil pentru toți
    cei care îl vor primi. Nu se completează niciodată singur (nici din
    `git config`, nici din numele utilizatorului sistemului) — doar din
    profilul pe care l-ați completat sau din `--contact`. Pentru un singur
    pachet fără contact — `--contact -`.

**Întrebarea băncii comune înaintea citirii** (`--lookup`) înseamnă: înaintea
fiecărui `nysh read`, Nyshporka trimite la server cota dosarului și numărul de
imagini și, dacă textul există deja, afișează un rând. Serverul vede astfel ce
dosar urmează să citiți — de aceea implicit este dezactivat.

## Fișa dosarului: titlu, ani, locuri, gen

Programul de împachetare alcătuiește fișa singur — din pașaportul
directorului, din registrul inventarului fondului și din biblioteca de
dosare. Notațiile de lucru ale pașaportului (data verificării în paranteze,
„FS-тег: …”, „⚠ …”, notațiile de prioritate) nu intră în fișă. Când asta nu
ajunge — dosar fără nume, titlu de lucru în loc de cel adevărat — fișa o
stabilește cel care încarcă:

```sh
nysh share card "ДАХмО 315-1-1234" --title "Сповідні розписи парафії …" \
  --years 1795-1797 --place "Слобідка" --place "Вербівка" --genre confession
```

Același lucru direct la împachetare: `nysh share pack … --title … --years …`.
Ce s-a stabilit **se reține** (`data/share/cards.json`) și se aplică la
fiecare împachetare următoare a acestui dosar — `pack`, `suggest --all`,
oferirea automată. Ca să vedeți — `nysh share card <шифра>`, ca să ștergeți un
câmp — `--title ""`, toată fișa — `--clear`.

Genuri: `birth`, `marriage`, `death`, `confession`, `revision`, `clergy_list`,
`gazette`, `finding_aid`, `other` (se poate și cu denumirea: «сповідні»).

**Unde sunt imaginile.** Când dosarul a fost citit dintr-o fotografiere
privată — colecția cercetătorului, cumpărată sau comandată — destinatarul nu o
va găsi pe FamilySearch și Commons. Fișa numește cine deține imaginile:

```sh
nysh share card "ДАХмО 230-1-1234" --scans "Колекція дослідника=https://…"
```

Linkul pleacă primul dintre linkurile pachetului, cu marcajul `role: scans`,
și în banca comună stă lângă text: după imagini omul va merge tocmai acolo. La
fel ca restul fișei, el se reține; ștergere — `--scans ""`.

## Ce s-a citit, dar nu s-a oferit încă

```sh
nysh share suggest                   # перелік зі статусами
nysh share suggest --all --ready     # спакувати все готове
nysh share suggest --skip "ДАХмО 315-1-1234" --why "платна зйомка"
```

Stări: **gata**, **în banca comună fără chenare**, **incomplet** (s-a citit
mai puțin de 80 % din imagini — se oferă doar cu `--partial`), **fără
imagini**. Ce se află deja în banca comună hotărăște instantaneul băncii
comune (`nysh share sync`); dosarele pe care instantaneul nu le cuprinde —
după jurnalul împachetărilor. Refuzul se reține pentru fiecare dosar în
parte: despre un dosar pe care ați decis să nu-l oferiți nu vi se mai cere.

## Ce se află în pachet

```
manifest.json    шифра, картка, джерело сканів, знаменник, ваші поля
frames.jsonl     перелік кадрів справи
runs/<прогін>/   NNNN.txt — сторінка, рядок у рядок; плюс паспорт прогону
README.md        пояснення для того, хто відкриє пакет без Нишпорки
```

Contururile rândurilor (`*.lines.json`) pleacă într-un fișier **separat**
`….geom.nyshtext`: ele cântăresc de ×10 cât textul și sunt necesare doar
celui care are aceleași imagini.

### Ce citiri pleacă

Vocile pachetului sunt citirile dosarului, nu tot ce se află alături. Rămân
acasă, iar `pack` o numește pe fiecare, cu motivul:

- citirile de măsurare (marcajul `control_run` în pașaportul citirii);
- probele: o citire ale cărei pagini se află toate într-o citire mai completă
  **a aceluiași model** (părțile dosarului citite de un singur model pleacă
  amândouă);
- citirile altui dosar cu nume asemănător;
- citirile străine primite — le oferă autorul, nu dumneavoastră;
- cele numite de dumneavoastră: `--skip-run <прогін>`.

### Numitorul — câmpul principal

Manifestul spune **câte imagini are dosarul și câte dintre ele au fost
citite**, cu ce model și dacă s-a verificat orientarea. Fără asta, o citire
străină produce zerouri false în masă: omul caută în trei pagini luate drept
trei mii, nu găsește numele de familie — și închide cinstit direcția, după ce
a făcut totul corect.

De aceea un pachet cu citire incompletă sau fără numele modelului pur și
simplu nu se va asambla. Ați citit o bucată intenționat — spuneți de ce:

```sh
nysh share pack "ДАХмО 315-1-1234" --partial "лише аркуші з нашим селом"
nysh share pack "ДАХмО 315-1-1234" --frames 408        # число кадрів справи, якщо пакувальник його не знайшов
```

## Câmpurile dumneavoastră

```sh
nysh share pack "ДАХмО 315-1-1234" \
  --as "sergiy" --contact "t.me/…" \
  --note "читав Дяком, останні аркуші підмокли" \
  --link "звідки скани=https://…" \
  --extra "plivka=105208823"
```

- `--note` — text liber; ajunge la cititor și intră în README-ul pachetului.
- `--link` — „denumire=adresă” sau doar linkul; cel mai util este cel care
  duce la scanări. O adresă cu `=` înăuntru (linkurile FamilySearch) este
  tratată întreagă.
- `--extra` — perechi „cheie=valoare”, pe care formatul le va purta
  neatinse. O pereche fără `=`, cu cheie goală sau numită de două ori —
  refuz, nu omitere tăcută.

## Ce nu intră în pachet

Programul de împachetare ia **doar** paginile de text și pașaportul citirii
— iar din pașaport doar câmpurile necesare destinatarului: modelul, motorul,
scrierea, câte pagini s-au făcut. Nu pleacă căile de pe discul
dumneavoastră, notițele de lucru (`*_note`, explicațiile măsurătorilor,
istoricul unificării), decupajele de salvare, jurnalele, carantina, depozitul
de pagini, verdictele, canonul.

Puteți vedea ce anume va pleca înainte de asamblare:

```sh
nysh share pack "ДАХмО 315-1-1234" --dry-run
```

## Carnetul dosarului

Pe lângă text, despre un dosar se știe adesea și altceva, util oricui îl va
deschide: ce conține de fapt cartea, unde inventarul arhivei a greșit titlul
sau anii, unde se află o copie. Tot aici — un rând pe care calculatorul l-a
citit strâmb, iar dumneavoastră l-ați verificat pe scanare. Toate acestea
formează carnetul dosarului. El stă lângă filele consultate și pleacă în
Supriaha **separat de text**: îl puteți completa și pentru o carte oferită de
altcineva.

```sh
nysh note add "ДАХмО 315-1-1234" --kind about --text "Метрична книга Покровської церкви, 1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind catalog-error --field years --archive-says 1834 --actually "1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind copy --other "ДАВіО 904-24-55" --text "копія в консисторії" --share
nysh note read "ДАХмО 315-1-1234" 0031 --line 153 --text "урожденная Прухницкая" --share

nysh note push "ДАХмО 315-1-1234" --dry-run   # що поїде
nysh note push "ДАХмО 315-1-1234"             # віддати
nysh note pull "ДАХмО 315-1-1234"             # що дописали інші
```

În Supriaha pleacă doar ce este marcat cu `--share` și lista filelor
consultate, fără comentariile dumneavoastră. Ce ține de familie — „aici este
înregistrat bunicul meu” — scrieți ca `--kind note`: o asemenea însemnare nu
pleacă niciodată, iar o însemnare cu cuvinte de familie banca comună nu o va
primi, nici dacă este marcată. Pe pagina cărții carnetul se vede separat de
text și nu intră în numărul paginilor citite: verificat cu ochiul înseamnă
rânduri alese, nu un dosar citit.

Rândul verificat pleacă în Supriaha împreună cu decupajul — fragmentul acestui
rând din scanare, un JPEG gri, dacă scanarea dosarului se află pe calculatorul
dumneavoastră (fără ea rândul pleacă doar ca text). **Împărtășind rândurile
verificate, sunteți de acord ca proprietarul Nyshporka să le poată folosi
pentru antrenarea modelelor de recunoaștere.** Altor utilizatori decupajele
nu li se dau și nu se afișează pe pagina cărții; textul verificării îl văd
toți. O însemnare retrasă (`nysh note retract` și `note push`) ia din banca
comună și decupajul.

## Primiți pachetul altcuiva

!!! tip "Dacă îl luați prin agent"
    Skill-ul `pull-case` îl duce pe agent de la `pull` până la căutarea în
    textul primit și citește cu voce tare marcajul de corespondență: ce din
    textul străin se va așeza pe imaginile dumneavoastră și ce — doar pentru
    căutare.

```sh
nysh share inspect <файл або адреса>     # подивитись, нічого не розкладаючи
nysh share import <файл або адреса>      # прийняти
nysh share geometry <….geom.nyshtext>    # докласти рамки рядків
```

Pachetul vine de la un om pe care nu îl cunoașteți, iar receptorul nu îl
crede pe cuvânt:

- **verificările măsoară conținutul, nu declarația**: paginile, rândurile și
  hash-ul textului se numără din pachetul însuși, iar un pachet care declară
  mai mult decât conține nu trece;
- **un defect al pachetului înseamnă refuz înainte de scriere**: o cale în
  afara `runs/<прогін>/<файл>`, un nume nepermis pe Windows, o legătură
  simbolică, un fișier prea mare — și pe disc nu se scrie nimic;
- se desfac doar citirile numite în manifest și doar textul cu pașaportul;
  pașaportul se curăță cu aceeași listă albă;
- **citirea dumneavoastră nu se suprascrie niciodată** — nici cu `--force`. O
  citire cu același nume (indiferent de majuscule) — refuz. `--force`
  înlocuiește doar un pachet primit anterior;
- pachetul de la o adresă din catalog se verifică după sha256-ul lui
  (`share pull --take` face asta singur; pentru `import` și `geometry` după
  adresă — `--sha256`): un fișier înlocuit în depozit după ce banca comună l-a
  primit nu este acceptat.

## Cât de bine se va așeza textul străin pe imaginile dumneavoastră

Cheia dosarului nu este potrivită pentru asta: ea se alcătuiește din numele
directorului și din ghidul dumneavoastră al arhivelor, așa că la doi oameni
aceeași carte primește chei diferite. De aceea pachetul poartă lista
imaginilor și amprenta fotografierii, iar Nyshporka **măsoară** potrivirea și
o spune cu voce tare:

| marcaj | ce înseamnă | ce funcționează |
|---|---|---|
| `exact` | s-au potrivit toate imaginile (hash sau identificator FamilySearch) sau amprenta fotografierii pe cel puțin trei imagini | totul, inclusiv decupajele și contururile străine |
| `by-name` | s-au potrivit numele și numărul | totul, în afară de contururile străine |
| `by-position` | s-a potrivit doar numărul sau o parte din imagini | pagina da, decupajul este îndoielnic |
| `text-only` | imaginile lipsesc sau sunt altele | căutarea, pagina, cota |

Contururile străine se așază doar pe textul **aceleiași contribuții** și doar
la `exact`; altfel — refuz cu explicație (`--force`, dacă sunteți sigur).

`text-only` nu este o înfrângere, ci scenariul cel mai frecvent de folos:
găsiți numele de familie în textul altcuiva, vedeți dosarul și numărul filei —
și mergeți să vedeți scanarea însăși la sursă.

!!! danger "Potrivirea numelui de fișier nu înseamnă aceeași imagine"
    Așezarea plată renumerotează paginile, așa că două fotografieri ale
    aceleiași cărți dau ușor nume identice la conținut diferit. Tocmai de
    aceea marcajul nu se ridică niciodată prin presupunere.

## Zeroul propriu și zeroul străin sunt răspunsuri diferite

Citirile primite sunt marcate, iar căutarea o spune:

```
знаменник: кадрів 3772 · прочитано 3770 · у сторі прогонів 2 із 2 …
з них чужий декод: прогонів 2 із 2 · сторінок 3770 · від oksana
```

Textul străin a fost citit de alt model, pentru completitudinea lui nimeni
de aici nu răspunde, iar recitit poate fi doar cerându-l celui care l-a dat.
Un zero pe el cântărește mai puțin decât un zero pe al dumneavoastră — și
acest lucru trebuie să se vadă.

## Banca comună

```sh
nysh share pull                     # огляд пулу: архів · фонд · опис, справ і сторінок
nysh share pull "Слобідка"          # що є в каталозі
nysh share pull "ДАХмО 315-1-1234" --take
nysh share pull --repo RGIA --fond 592           # серія: що в ній є
nysh share pull --repo RGIA --fond 592 --take    # і прийняти всю
nysh share stats --catalog          # хто скільки вніс
nysh share sync --repo DAHMO --fond 315   # зріз для колонки «пул» у `cases fond`
```

Catalogul — API `https://api.nyshporka.online/v1`. O oglindă proprie sau un
server de test se setează cu variabila `NYSHPORKA_TOLOKA` sau cu opțiunea
`--base`; cheia Supriaha **nu pleacă** la o asemenea adresă — nici din
depozitul de chei, nici din `NYSHPORKA_SUPRIAHA_TOKEN`. Serverul propriu
trebuie numit explicit: `NYSHPORKA_SUPRIAHA_TRUST=https://хост[:порт]` —
doar HTTPS și doar potrivire exactă a adresei; atunci cheia Supriaha pleacă
spre el. Bucla acestui calculator (`127.0.0.1`, `localhost`) este oricum de
încredere.

`sync` cu `--repo`/`--fond` adaugă instantaneul unui singur fond la cel
existent; despre fondurile pe care instantaneul nu le cuprinde, coloana
«пул» (banca comună) spune „nu știm”, nu „nu există”.

Refuzul băncii comune (verificări, norma zilnică) Nyshporka îl afișează cu
cuvintele serverului. Când același text se află deja în banca comună,
`publish` spune dacă a fost acceptat, respins cândva sau încă neterminat —
„deja în Supriaha” înseamnă doar primul caz.

## Urma schimbului

`data/share/journal.jsonl` ține minte ce a venit de unde și ce a plecat unde,
iar pachetele primite rămân în `data/share/inbox`. Aceasta nu este evidență de
dragul evidenței: un fapt luat dintr-o citire străină și trecut în canon
trebuie să se sprijine pe un fișier permanent — altfel citarea va rămâne în
aer de îndată ce veți șterge descărcarea.

```sh
nysh share list          # журнал
nysh share stats         # скільки віддано, скільки прийнято, від кого
```

## Licență

Pachetul numește condițiile în care se oferă textul (`--license`, implicit
`CC0-1.0`) și, separat, condițiile sursei scanărilor (`--source-terms`), dacă
există. Fără licență pachetul nu se va asambla: destinatarul trebuie să știe
ce poate face cu el.
