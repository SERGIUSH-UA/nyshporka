# Jak pracować

<p align="center">
  <img alt="Nyshporka czyta rękopis z lupą" src="../assets/maskot-pratsiuie.webp" width="220" height="206">
</p>

Nyshporka jest zainstalowana, asystent podłączony ([jeśli nie](install.md)).
Dalej rozmawiasz z asystentem zwykłym językiem, a znaleziska oglądasz samodzielnie.

## O co można poprosić

Kilka przykładów — formułuj, jak chcesz:

* „Co jest o wsi Lypovenke? Gdzie są jej metryki i co warto zamówić w archiwum?”
* „Oto folder `D:\скани\ДАКО 13-1-1`, załóż go jako jednostkę. To księga
  metrykalna, 1850–1855.”
* „Odczytaj tę jednostkę.” (Księga z 300 kartami bez karty graficznej to noc;
  komputer nie może zasnąć.)
* „Znajdź tu Kowalskich i pokaż wiersze na skanie.”
* „Zapisz, że przejrzałem karty 12–40: naszego tam nie ma.”
* „Zrób tabelę wszystkich ślubów w tej księdze z lat 20. XIX wieku.”
* „Nic się nie znalazło — gdzie kopać dalej?”

Asystent sam zna kolejność pracy: ma do tego skille — gotowe schematy, jak
odczytać jednostkę, jak szukać nazwiska, gdzie kopać, jak zapisać przejrzane.

## Skany przynosisz samodzielnie

Nyshporka nie pobiera jednostek z FamilySearch ani z archiwalnych serwisów, do
których trzeba logować się własnym kontem. Zapisujesz strony z przeglądarki
archiwum na dysk, tak samo jak bez niej. Wymagania wobec folderu są
proste i ścisłe:

| zasada | dlaczego |
|---|---|
| jeden folder = jedna jednostka | sygnatura, ewidencja i znaleziska są przypisane do folderu |
| obrazy leżą bezpośrednio w folderze | odczyt nie wchodzi do podfolderów |
| `jpg`, `png`, `tif`, `webp` | inne formaty nie liczą się jako skany |
| PDF można wrzucić jak jest | strony same rozłożą się na skany przed odczytem |

Folder może leżeć gdziekolwiek — dysk zewnętrzny, pulpit, sieć. Pliki nigdzie
nie są przenoszone; asystent zapyta o zgodę na wzięcie folderu do ewidencji. W
aplikacji robi się to w oknie **📥 Нові теки** (Nowe foldery) → «Описати»
(Opisz): dla folderu spoza badań pojawi się tam pole «Показувати цю теку в
переліках там, де вона лежить» (Pokazuj ten folder na listach tam, gdzie leży).

## Jak sprawdzić znalezisko

Asystent pokazuje kandydatów, a decydujesz Ty. Służy do tego **aplikacja w
przeglądarce** — skrót „Nyshporka” na pulpicie lub `nysh serve`, adres
`127.0.0.1:8788`.

* **📄 Гортач** (Przeglądarka skanów) — skan i odczytany tekst obok siebie.
  Kliknij wiersz — zobaczysz wycinek z karty, z którego go odczytano.
* **🔎 Пошук** (Wyszukiwanie) — wszyscy kandydaci z trafieniem, z wycinkiem
  każdego. Szuka to samo polecenie, którego używa asystent, a pod wynikami
  napisano, gdzie i czym szukano.
* **👁 Облік** (Ewidencja) — co już przejrzano wzrokiem, nawet puste karty.

Jeśli asystent mówi „znaleziono” — proś o wycinek. Jeśli „nie ma” — pytaj, ile
kart sprawdzono.

## Trzy zasady

* **„Nie ma” bez liczby to nie odpowiedź.** Poprawnie brzmi to tak:
  „przeszukano 180 kart z 300, w odczytanym tekście brak trafień”. Fałszywe
  „nie ma” zamyka kierunek poszukiwań na zawsze.
* **Maszyna znajduje, decydujesz Ty.** Odczytany tekst ma błędy — w kursywie
  z XVIII–XIX w. co trzecia–czwarta litera. Szuka się w nim, a znaleziska
  ogląda na skanie. Nie odrzucaj kandydata dlatego, że rdzeń słowa nie jest
  podobny: model przekręca właśnie środek nazwiska.
* **Liczby porównuj ze skanem.** Lata, wiek, numery aktów maszyna myli częściej
  niż słowa, a wygląda to równie pewnie.

## Okna aplikacji { #vikna-zastosunku }

Każde okno odpowiada na jedno pytanie, a „nie ma” w każdym oznacza coś innego.

| okno | pytanie |
|---|---|
| 🐾 Огляд (Przegląd) | gdzie jestem: co już mam, co odczytano, czego nie doczytano, sprawdzenie komputera |
| 🔎 Пошук (Wyszukiwanie) | gdzie w odczytanym tekście jest moje nazwisko, wieś czy dowolne słowo — w całej bibliotece, zespole czy jednostce |
| 🎯 Рід (Ród) | czyjego nazwiska szukamy i w jakich zapisach — to jedyne, co wskazujesz Ty |
| 📥 Нові теки (Nowe foldery) | co na dysku nie stało się jeszcze jednostką: opisać sygnaturą albo odłożyć jako „nie jednostkę” |
| 🗺 Газетир (Gazetteer) | gdzie są dokumenty mojej wsi |
| 🔎 Каталоги (Katalogi) | co jest w archiwalnych informatorach i na stronach archiwów; katalog strony zbiera się przyciskiem |
| 🏛 Описи фондів (Inwentarze zespołów) | co w ogóle istnieje w archiwum, nawet niezdigitalizowane |
| 📚 Бібліотека (Biblioteka) | co mam na dysku |
| 🖋 Читання · 📜 Прогони (Odczyt · Przebiegi) | odczytać jednostkę · czym i w jakim stopniu odczytano, co zostało do doczytania |
| 📄 Гортач · 🔍 Розбір · 👁 Облік (Przeglądarka · Analiza · Ewidencja) | odczytany tekst obok skanu · kandydaci z wycinkami · co już widziałem na własne oczy |

Szczegółowy przewodnik po oknach — [„Mapa ekranów”](agents/screens.md).

## Spróbuj bez własnych skanów

W aplikacji: **🐾 Огляд** (Przegląd) → «Перевірити цю машину» (Sprawdź ten
komputer) → «Розгорнути зразок» (Rozpakuj próbkę) (albo `nysh sample`). To
trzy już odczytane karty jednostki **ДАХмО 315-1-159** (1821–1822): widać na
nich przeglądarkę skanów, wycinki i wyszukiwanie, zanim przyniesiesz własne
skany.

## Co jeszcze potrafi Nyshporka

* **Gazetteer i informatory** od razu po instalacji: zbiorczy katalog ЦДІАК
  (4566 miejscowości), katalog ДАХмО, indeks mikrofilmów FamilySearch dla
  Mołdawii, cerkwie z około 1772 roku.
* **Katalogi stron archiwalnych** — ARCHIUM, „Babi Jar”, Wikimedia Commons,
  Duck Inspector, ridni.org, „Chtyvo”, Internet Archive.
* **Opracowanie aktów w tabeli** — daty, imiona, role, stan, wiek — i eksport do
  Excela. Opracowuje sam asystent, czyli w ramach Twojej subskrypcji.
* **Douczanie modelu** na własnym piśmie — [więcej](train.md).
* **Odczyt dużej jednostki na wynajętym komputerze** w godzinę zamiast
  tygodnia — [więcej](cloud.md).

Pełny techniczny wykaz z poleceniami — [przewodnik po możliwościach](agents/features.md).

## Aktualizacje

Nyshporka sama nie łączy się z siecią i nie przypomina o nowych wersjach. Co
jakiś czas poproś asystenta o sprawdzenie albo wykonaj `nysh update --check`.
