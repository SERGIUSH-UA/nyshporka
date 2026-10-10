# Częste pytania

## Skany i miejsce na dysku

### Trzeba pobrać wszystkie skany na komputer?

Tak. Aby odczytać kartę, model tnie ją na wiersze i przechodzi przez każdy — to
dziesiątki odwołań do pliku na jedną stronę, „w locie” ze strony archiwum tak
się nie czyta.

### Jeśli potem usunę skany — informacje się skasują?

Nie wszystkie. **Zostają** odczytany tekst, ewidencja przejrzanego, znaleziska i
notatki: są w folderze roboczym Nyshporki, a nie w folderze ze skanami, i
wyszukiwanie w tekście działa dalej. **Znikają** wycinki i możliwość obejrzenia
kandydata na własne oczy czy ponownego odczytu jednostki innym modelem.

Dlatego zanim zwolnisz miejsce, doprowadź jednostkę do końca. Taniej —
przenieść folder na dysk zewnętrzny i powiedzieć o tym asystentowi
(`nysh roots add "E:\скани"`): jednostka nie zniknie z list.

### Ile miejsca potrzeba?

Aplikacja z modelami odczytu — około 3 GB. Skany — tyle, ile ich jest (karta
księgi metrykalnej waży 2–8 MB). Odczytany tekst — kilka MB na jednostkę.

### Archiwum dało PDF, a nie osobne strony

Odczyt na razie przyjmuje tylko obrazy: `jpg`, `png`, `tif`, `webp`. PDF trzeba
najpierw rozłożyć na strony zewnętrznym narzędziem. Wyjątek — drukowana książka
z warstwą tekstową (na przykład z „Chtyva”): model nie jest jej potrzebny, tekst
już jest.

## Archiwa

### Czy można pracować ze skanami z dowolnego archiwum?

Tak, od razu: kody wszystkich obwodowych i centralnych archiwów Ukrainy są już
w informatorze, więc sygnatura `ДАКО 13-1-1` jest przyjmowana bez ustawień.
Różnica polega tylko na tym, czy Nyshporka potrafi sama chodzić po katalogu
archiwum: gotowe katalogi są dla ДАХмО i ЦДІАК, a przeglądarki ARCHIUM innych
archiwów dodaje się kilkoma wierszami ustawień — poproś asystenta.

### Czy Nyshporka pobiera jednostki z FamilySearch?

Nie i nie będzie: wymaga to aktywnej sesji w przeglądarce, a masowe pobieranie
narusza zasady serwisu. Zamiast tego jest **indeks mikrofilmów**: która wieś na
których skanach którego mikrofilmu. Odpowiada on na pytanie „gdzie są metryki
mojej wsi” bez pobierania, ale na razie obejmuje tylko Mołdawię.

Jeśli skany mikrofilmu masz już na dysku, można je wziąć do ewidencji jako
jednostkę: `nysh case <тека> --shifra "<архів фонд-опис-справа>" --dgs <номер
групи зображень>`. Numer trafi do paszportu jako źródło skanów.

## Odczyt

### Czy potrzebna jest karta graficzna?

Nie. Odczyt opiera się na procesorze: około **2 minut na stronę** na zwykłym
laptopie wobec ~20 sekund z kartą graficzną. Dużą jednostkę można odczytać na
[wynajętym komputerze](cloud.md).

### Jak odczytać kilka jednostek po kolei i nie siedzieć obok?

Ustawić je w kolejce: `nysh queue add <справи>`, potem `nysh queue run`.
Kolejka prowadzi jednostki jedną po drugiej; jeśli któraś nie może iść dalej
(brakuje sygnatury, źródło nie oddaje skanów), czeka na Twoją decyzję, a
kolejka bierze następną. `nysh queue` pokazuje, co jest na jakim etapie i ile
zostało. Zatrzymać po bieżącej jednostce — `nysh queue stop`; po zatrzymaniu
lub wyłączeniu komputera `nysh queue run` kontynuuje od tego samego miejsca.

### Tekst wychodzi z błędami — to usterka?

Nie, to granica możliwości technologii na takim materiale. W kursywie z
XVIII–XIX w. maszyna myli od jednej czwartej do jednej trzeciej liter:
„Franciszka Lubkowskiego” staje się „Francisrha Lubhoustrio90”. Tekst jest
potrzebny, żeby w nim **szukać** — wyszukiwanie jest przybliżone i znajduje
przekręcone nazwisko — a znaleziska ogląda się na skanie.

### Po co dwa modele do cyrylicy?

Diak czyta te same wiersze co Pysar, ale myli się **inaczej**: trzyma się
bliżej samych kresek tam, gdzie Pysar podstawia prawdopodobne słowo. Razem
znajdują więcej niż każdy z osobna.

### Czy Nyshporka czyta księgi polskie, łacinę, XX wiek?

Modele wytrenowano na kursywie z XVIII–XIX w. z archiwów ukraińskich,
mołdawskich i polskich. Alfabet łaciński (akta notarialne, księgi
rzymskokatolickie) czyta Skryba. W piśmie, którego model nie widział, błędów
jest więcej — u Skryby przy obcych charakterach pisma co piąta litera. Do
wyszukania nazwiska zwykle to wystarcza, do dosłownego cytatu — nie, więc
pierwszą jednostkę z nowego materiału warto sprawdzić wzrokiem. Douczyć model
na własnym piśmie — [można](train.md).

## Asystent

### Czy można bez asystenta?

Proste rzeczy — tak: w aplikacji w przeglądarce można przejrzeć informatory,
odczytany tekst i znaleziska. Ale drogę od „gdzie szukać” do „oto Twój
przodek” Nyshporka ma przechodzić razem z asystentem: wykonuje on dziesiątki
kroków, które ręcznie zajęłyby dni.

### Co robi asystent, a co Nyshporka?

Odczyt rękopisu i wyszukiwanie wykonuje Nyshporka na Twoim komputerze — to nic
nie kosztuje, poza czasem. Asystent decyduje, co robić dalej, uruchamia kroki i
objaśnia wynik. Jedyne, co „czyta oczami” sam, to **opracowanie aktów w pola**
(daty, imiona, role): to około 84 tysięcy tokenów na skan, czyli na księgę z
dwustu kart — miliony tokenów, a przejścia potrzebne są dwa.

## Pieniądze i prywatność

### Ile to kosztuje?

Nyshporka — nic, jest wolnym oprogramowaniem (AGPL-3.0). Płacisz tylko za
asystenta (jego subskrypcję) i, jeśli zechcesz, za wynajem komputera do
odczytu — koszt widać **przed** wynajmem.

### Czy moje skany są gdzieś wysyłane?

Nie. Nie ma telemetrii, konto do pracy nie jest potrzebne. Skany, odczytany
tekst i notatki leżą w folderze na Twoim dysku. Z siecią Nyshporka łączy się
tylko wtedy, gdy o to poprosisz: wyszukiwanie w katalogach, pobieranie
jednostki, instalacja modeli, aktualizacja. Pełna lista —
[polityka prywatności](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

Podzielić się odczytanym tekstem w serwisie [Supriaha](share.md) można tylko po
zalogowaniu (`nysh share login`) i tylko za Twoją zgodą: przekazywany jest
tekst odczytany przez maszynę i opis jednostki. Skany i notatki nigdy tam nie
trafiają. Pytanie puli przed każdym odczytem i automatyczne przekazywanie
odczytanego tekstu — oba tryby są domyślnie wyłączone, włączasz je Ty
(`nysh share setup`).

### Czy można przenieść badania na inny komputer?

Tak: folder roboczy to zwykły folder, można go skopiować w całości. Opis każdej
jednostki leży w samym folderze jednostki, więc przenosi się razem z nim — także
do kolegi.

## Aktualizacja i usuwanie

### Jak zaktualizować?

Poproś asystenta albo wykonaj `nysh update --check` — polecenie powie, czy jest
nowsza wersja i jakim wierszem zaktualizować akurat na Twoim komputerze. Na
Windows najprościej pobrać nowy instalator i uruchomić go na istniejącej
instalacji: badania, modele i informatory zostają na miejscu. Sama Nyshporka o
nowych wersjach nie przypomina: tak obiecuje polityka prywatności.

### Jak odinstalować Nyshporkę?

`nysh uninstall` pokazuje, co zostanie usunięte, `nysh uninstall --yes --all`
usuwa wszystko razem z modelami. Na Windows można też jak zwykły program —
„Programy i funkcje”. **Folder roboczy z Twoimi badaniami nigdy nie jest
usuwany.**

## Gdy wyszukiwanie nic nie znalazło { #nichogo-ne-znaishlos }

Pusty wynik to najdroższa odpowiedź w genealogii, bo „nie ma” zamyka kierunek
na długo. Zanim w to uwierzysz, zadaj sobie (albo asystentowi) cztery pytania:

1. **Czy tekst jest czytelny?** Obejrzyj jednostkę w przeglądarce skanów. Jeśli
   to jednolity szum — zero dotyczy jakości odczytu, a nie obecności nazwiska.
2. **Ile kart naprawdę przeszukano?** „Nie znalazło się w 180 kartach z 300” i
   „nie znalazło się” to różne odpowiedzi.
3. **Czy wyszukiwanie znajduje to, co tu na pewno jest?** Poszukaj nazwiska,
   które na skanie widać już na własne oczy. Nie znalazło się — problem
   jest w wyszukiwaniu.
4. **Czy szukano we właściwych źródłach?** Poproś asystenta o plan: które
   źródła przeszukano, ile każde przejrzało i co jest następne.

Asystent zna jeszcze dwie drogi obejścia: szukać rodu po **imionach i
patronimikach**, które model przekręca mniej niż długie nazwisko, oraz
**samosprawdzenie** — czy wyszukiwanie widzi te karty, na których nazwisko
zostało już wypisane przez Ciebie.

## Czego jeszcze nie ma { #chogo-shche-nemaie }

Uczciwie, bez przemilczeń:

* **Skany przynosisz samodzielnie** — narzędzia do pobierania z FamilySearch
  nie ma i nie będzie.
* **Opracowanie aktów w pola wykonuje asystent na Twój koszt.** Nyshporka
  przygotowuje kartę i sprawdza kompletność, ale sama aktów nie opracowuje:
  wbudowana płatna usługa wydawałaby Twoje pieniądze bez Twojej zgody.
* **Typ strony** (metryka, okładka, indeks) określa człowiek albo asystent —
  sama Nyshporka tego nie rozpoznaje.
* **Wyblakłej karty może nie uratować nic** — ani powiększenie, ani ponowny
  odczyt. Taką część jednostki skanuje się ponownie albo przyjmuje jako
  niekompletną.
* **Modele odczytu są dobre na materiale, na którym się uczyły**; na innym zły
  tekst wygląda równie pewnie jak dobry.
* **Inwentarze są nie dla wszystkich zespołów** — tylko tam, gdzie inwentarz
  zamieszczono na stronach, które Nyshporka potrafi czytać.
* **Indeks mikrofilmów obejmuje tylko Mołdawię.**

Techniczne szczegóły ograniczeń — w [przewodniku po możliwościach](agents/features.md#mezhi-chogo-shche-nemaie).

## Jeśli coś jest nie tak

| co widzisz | co robić |
|---|---|
| „polecenia `nysh` nie znaleziono” | Zamknij i ponownie otwórz asystenta (Claude — całkowicie, przez ikonę przy zegarze) lub okno terminala |
| „System Windows ochronił ten komputer” | „Więcej informacji” → „Uruchom mimo to”. Sprawdzić plik można według `.sha256` w [wydaniu](https://github.com/SERGIUSH-UA/nyshporka/releases/latest) |
| instalator zakończył się „kod 1” | Zobacz ostatnie wiersze wyniku: najczęściej przerwane pobieranie, brak miejsca albo antywirus. Więcej — [instalacja](install.md#yakshcho-shchos-ne-tak) |
| okno aplikacji jest puste | Puste okno zawsze pisze, czego brakuje. Najczęściej jednostki jeszcze nie założono albo katalogu nie zebrano — zapytaj asystenta |
| brakuje połowy okien | Części aplikacji można wyłączać: ⚙ → «Частини застосунку» (Części aplikacji). Zestaw `catalog` nie ma odczytu rękopisu |
