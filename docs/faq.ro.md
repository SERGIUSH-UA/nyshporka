# Întrebări frecvente

## Scanări și spațiu pe disc

### Trebuie să descarc toate scanările pe calculator?

Da. Ca să citească o filă, modelul o taie în rânduri și trece prin fiecare —
sunt zeci de accesări ale fișierului pentru o singură pagină; „din zbor” de pe
site-ul arhivei nu se poate citi așa.

### Dacă șterg apoi scanările — se pierd informațiile?

Nu toate. **Rămân** textul citit, evidența celor consultate, descoperirile și
notițele: ele sunt în directorul de lucru Nyshporka, nu în directorul cu
scanări, iar căutarea în text funcționează în continuare. **Dispar**
decupajele și posibilitatea de a verifica un candidat cu ochiul sau de a
reciti dosarul cu alt model.

Așa că, înainte de a elibera spațiu, duceți dosarul până la capăt. Mai ieftin
— mutați directorul pe un disc extern și spuneți-i asistentului
(`nysh roots add "E:\скани"`): dosarul nu va dispărea din liste.

### Cât spațiu este necesar?

Aplicația cu modelele de citire — aproximativ 3 GB. Scanările — câte sunt (o
filă de registru metric are 2–8 MB). Textul citit — câțiva MB pe dosar.

### Arhiva a dat un PDF, nu pagini separate

Deocamdată citirea ia doar imagini: `jpg`, `png`, `tif`, `webp`. PDF-ul trebuie
mai întâi desfăcut în pagini cu un instrument extern. Excepție — o carte
tipărită cu strat de text (de exemplu, din Чтиво): modelul nu îi trebuie,
textul există deja.

## Arhive

### Se poate lucra cu scanările oricărei arhive?

Da, imediat: codurile tuturor arhivelor regionale și centrale ale Ucrainei
sunt deja în ghid, așa că cota `ДАКО 13-1-1` este acceptată fără setări.
Diferența este doar dacă Nyshporka știe să parcurgă singură catalogul arhivei:
cataloage gata făcute există pentru ДАХмО și ЦДІАК, iar vizualizatoarele
ARCHIUM ale altor arhive se adaugă cu câteva rânduri de setări — cereți-i
asistentului.

### Descarcă Nyshporka dosare de pe FamilySearch?

Nu, și nu va descărca: asta cere o sesiune activă în browser, iar descărcarea
în masă contravine regulilor serviciului. În schimb există **indexul
microfilmelor**: ce sat pe ce imagini ale cărui microfilm se află. El răspunde
la „unde sunt registrele metrice ale satului meu” fără descărcare, dar
deocamdată acoperă doar Moldova.

Dacă imaginile microfilmului sunt deja pe discul dumneavoastră, ele pot fi
luate în evidență ca dosar: `nysh case <тека> --shifra "<архів фонд-опис-справа>" --dgs <номер
групи зображень>`. Numărul va intra în pașaport ca sursă a scanărilor.

## Citire

### Este nevoie de placă video?

Nu. Citirea depinde de procesor: aproximativ **2 minute pe pagină** pe un
laptop obișnuit, față de ~20 de secunde cu placă video. Un dosar mare poate fi
citit pe un [calculator închiriat](cloud.md).

### Cum citesc mai multe dosare la rând fără să stau lângă calculator?

Puneți-le la coadă: `nysh queue add <справи>`, apoi `nysh queue run`. Coada
duce dosarele unul după altul; dacă vreunul nu poate merge mai departe
(lipsește cota, sursa nu dă imaginile), el așteaptă decizia dumneavoastră, iar
coada îl ia pe următorul. `nysh queue` arată ce se află în ce etapă și cât a
mai rămas. Oprire după dosarul curent — `nysh queue stop`; după oprire sau
după ce calculatorul a fost închis, `nysh queue run` continuă din același loc.

### Textul iese cu greșeli — este o defecțiune?

Nu, este plafonul tehnologiei pe un asemenea material. În cursiva din
secolele XVIII–XIX, calculatorul încurcă între un sfert și o treime din
litere: «Franciszka Lubkowskiego» devine «Francisrha Lubhoustrio90». Textul
este necesar ca să **căutați** în el — căutarea este aproximativă și găsește
și numele de familie stâlcit — iar ce s-a găsit se verifică pe scanare.

### De ce două modele pentru chirilică?

Diak citește aceleași rânduri ca Pysar, dar greșește **altfel**: se ține mai
aproape de trăsăturile scrisului acolo unde Pysar pune un cuvânt plauzibil.
Împreună găsesc mai mult decât fiecare separat.

### Citește Nyshporka cărți poloneze, latină, secolul XX?

Modelele sunt antrenate pe cursiva din secolele XVIII–XIX din arhive
ucrainene, moldovenești și poloneze. Alfabetul latin (acte notariale, registre
ale bisericilor catolice) îl citește Skryba. Pe un scris pe care modelul nu
l-a văzut, greșelile sunt mai multe — la Skryba, pe mâini străine, fiecare a
cincea literă. Pentru căutarea unui nume de familie de obicei este suficient,
pentru o citare cuvânt cu cuvânt — nu, așa că primul dosar dintr-un material
nou merită verificat cu ochiul. Antrenarea suplimentară a modelului pe
scrisul dumneavoastră — [este posibilă](train.md).

## Asistentul

### Se poate fără asistent?

Lucrurile simple — da: în aplicația din browser puteți consulta ghidurile,
textul citit și ce s-a găsit. Dar de la „unde să caut” la „iată strămoșul
dumneavoastră” Nyshporka este gândită să meargă împreună cu asistentul: el
face zeci de pași care manual ar dura zile.

### Ce face asistentul și ce face Nyshporka?

Citirea manuscrisului și căutarea le face Nyshporka pe calculatorul
dumneavoastră — nu costă nimic, doar timp. Asistentul decide ce urmează,
pornește pașii și explică rezultatul. Singurul lucru pe care îl „citește cu
ochii” el însuși este **analiza actelor pe câmpuri** (date, nume, roluri):
asta înseamnă aproximativ 84 de mii de tokenuri pe scanare, adică pentru o
carte de două sute de file — milioane de tokenuri, iar trecerile necesare
sunt două.

## Bani și confidențialitate

### Cât costă?

Nyshporka — nimic, este liberă (AGPL-3.0). Plătiți doar pentru asistent
(abonamentul lui) și, dacă doriți, pentru închirierea unui calculator pentru
citire — costul se vede **înainte** de închiriere.

### Scanările mele sunt trimise undeva?

Nu. Nu există telemetrie, nu este nevoie de cont pentru lucru. Scanările,
textul citit și notițele stau într-un director de pe discul dumneavoastră. În
rețea Nyshporka iese doar atunci când ați cerut: căutare în cataloage,
descărcarea unui dosar, instalarea modelelor, actualizare. Lista completă —
[politica de confidențialitate](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

Puteți împărtăși textul citit în [Supriaha](share.md) doar după conectare
(`nysh share login`) și doar cu acordul dumneavoastră: se oferă textul citit
automat și descrierea dosarului. Scanările și notițele nu ajung niciodată
acolo. Întrebarea băncii comune înaintea fiecărei citiri și oferirea automată
a textului citit — ambele moduri sunt dezactivate implicit, le activați
dumneavoastră (`nysh share setup`).

### Se poate muta cercetarea pe alt calculator?

Da: directorul de lucru este un director obișnuit, poate fi copiat în
întregime. Descrierea fiecărui dosar se află în directorul dosarului însuși,
așa că se mută împreună cu el, inclusiv la un coleg.

## Actualizare și dezinstalare

### Cum actualizez?

Cereți-i asistentului sau rulați `nysh update --check` — comanda vă spune dacă
există o versiune mai nouă și cu ce rând să actualizați exact pe calculatorul
dumneavoastră. Pe Windows cel mai simplu este să descărcați noul program de
instalare și să-l rulați peste cel vechi: cercetarea, modelele și ghidurile
rămân la locul lor. Nyshporka însăși nu amintește de versiunile noi: așa
promite politica de confidențialitate.

### Cum dezinstalez Nyshporka?

`nysh uninstall` arată ce va fi dezinstalat, `nysh uninstall --yes --all`
dezinstalează totul, împreună cu modelele. Pe Windows se poate și ca un
program obișnuit — „Programe și caracteristici”. **Directorul de lucru cu
cercetarea dumneavoastră nu se șterge niciodată.**

## Când căutarea nu a găsit nimic { #nichogo-ne-znaishlos }

Un rezultat gol este cel mai scump răspuns în genealogie, pentru că „nu
există” închide o direcție pentru mult timp. Înainte să-l credeți, întrebați-vă
(sau întrebați asistentul) patru lucruri:

1. **Este textul lizibil?** Consultați dosarul în răsfoitor. Zgomot continuu —
   zeroul privește calitatea citirii, nu prezența numelui de familie.
2. **Câte file au fost căutate de fapt?** „Nu s-a găsit în 180 de file din
   300” și „nu s-a găsit” sunt răspunsuri diferite.
3. **Găsește căutarea ceea ce sigur se află aici?** Căutați un nume de familie
   pe care l-ați văzut deja pe scanare cu ochii dumneavoastră. Nu s-a găsit —
   problema este la căutare.
4. **S-a căutat în sursele potrivite?** Cereți-i asistentului planul: ce surse
   au fost parcurse, cât a consultat fiecare și ce urmează.

Asistentul mai știe două căi ocolitoare: să caute neamul după **prenume și
patronimice**, pe care modelul le stâlcește mai puțin decât un nume de familie
lung, și **autoverificarea** — dacă vede căutarea filele unde numele de
familie l-ați notat deja dumneavoastră.

## Ce nu există încă { #chogo-shche-nemaie }

Cinstit, fără nimic ascuns:

* **Scanările le aduceți dumneavoastră** — un program de descărcare de pe
  FamilySearch nu există și nu va exista.
* **Analiza actelor pe câmpuri o face asistentul pe costul dumneavoastră.**
  Nyshporka pregătește fila și verifică dacă este completă, dar nu analizează
  ea însăși actele: un serviciu plătit încorporat v-ar cheltui banii fără
  acordul dumneavoastră.
* **Tipul paginii** (registru metric, copertă, index) îl stabilește omul sau
  asistentul — Nyshporka însăși nu îl recunoaște.
* **O filă decolorată s-ar putea să nu o salveze nimic** — nici mărirea, nici
  recitirea. O asemenea parte a dosarului se refotografiază sau se acceptă
  incompletă.
* **Modelele de citire sunt bune pe materialul pe care au învățat**; pe altul,
  un text prost arată la fel de sigur ca unul bun.
* **Inventare nu există pentru toate fondurile** — doar acolo unde inventarul
  este publicat pe site-uri pe care Nyshporka știe să le citească.
* **Indexul microfilmelor acoperă doar Moldova.**

Detaliile tehnice ale limitelor — în [ghidul posibilităților](agents/features.md#mezhi-chogo-shche-nemaie).

## Dacă ceva nu merge

| ce vedeți | ce să faceți |
|---|---|
| „comanda `nysh` nu a fost găsită” | Închideți și redeschideți asistentul (Claude — complet, prin pictograma de lângă ceas) sau fereastra terminalului |
| „Windows v-a protejat PC-ul” | „Mai multe informații” → „Executare oricum”. Verificați fișierul — după `.sha256` din [versiune](https://github.com/SERGIUSH-UA/nyshporka/releases/latest) |
| programul de instalare s-a încheiat cu „cod 1” | Uitați-vă la ultimele rânduri ale ieșirii: cel mai des — o descărcare întreruptă, lipsă de spațiu sau un antivirus. Detalii — [instalare](install.md#yakshcho-shchos-ne-tak) |
| fereastra aplicației este goală | O fereastră goală scrie mereu ce lipsește. Cel mai des dosarul nu a fost încă înregistrat sau catalogul nu a fost construit — întrebați asistentul |
| jumătate din ferestre lipsesc | Părți ale aplicației se pot dezactiva: ⚙ → «Частини застосунку» (Părțile aplicației). Setul `catalog` nu are citirea manuscrisului |
