# Udostępnij odczytany tekst (Supriaha)

Tę samą księgę archiwalną dziś każdy rozpoznaje osobno. Przebieg odczytu
kosztuje niewiele, ale kosztuje **za każdym razem**: jednostka z trzema
tysiącami kart to godziny pracy maszyny, a płaci za nie każdy, kto do niej
dotarł. Tekst przy tym jest taki sam i u kogoś leży już gotowy.

Supriaha (`nyshporka.online`) to wspólny bank odczytanych jednostek. Przesyłany
jest sam tekst, nie obrazy: jednostka z 3772 kartami waży w pakiecie
**3–4 megabajty**.

!!! note "Obrazy nigdy nie wchodzą do pakietu"
    Pakiet niesie tekst z maszyny i paszport tego, jak go uzyskano. Same skany
    zostają u tego, kto je pobrał, a pakiet tylko wskazuje źródło —
    żeby odbiorca mógł wziąć je tam samo i na tych samych warunkach.

## Najkrótsza droga

```sh
nysh share login                                  # один раз: браузер, одна кнопка
nysh share setup --as "ваше імʼя"                 # один раз: профіль
nysh share pack "ДАХмО 315-1-1234"                # спакувати справу
nysh share publish data/share/outbox/DAHMO_315-1-1234.nyshtext
```

Po drugiej stronie:

```sh
nysh share pull "ДАХмО 315-1-1234" --take         # знайти в пулі й прийняти
nysh share pull --repo RGIA --fond 592 --opys 25 --take   # уся серія одним викликом
```

Przyjęte przebiegi trafiają tam, gdzie Twój własny odczytany tekst, i od razu
idą do magazynu tekstów, więc `nysh text find`, `grep` i `ctx` widzą je bez
osobnego `text index`. Szukać można w serii tak samo jak w jednostce:
`nysh text find <прізвище> --case "RGIA 592-25"`; kilka jednostek — powtórz
`--case`.

!!! tip "Jeśli udostępniasz przez agenta"
    Skill `share-case` prowadzi agenta tą samą drogą i pilnuje miejsc, które
    psują się po cichu: sygnaturę sprawdza w dry-run przed przesłaniem, lat z
    katalogu FamilySearch nie bierze, a kartę ustawioną przez `share card`
    doprowadza do puli ponownym przesłaniem. Instaluje się razem z pozostałymi
    skillami: `nysh skills install`.

## Logowanie

`nysh share login` otwiera stronę nyshporka.online: zalogować się e-mailem,
przez Google albo anonimowo. Klucz sam trafia do Nyshporki i do systemowego
magazynu kluczy — niczego nie trzeba kopiować. Usunąć klucz z komputera:
`nysh share logout`. Na serwerze bez przeglądarki klucz umieszcza się w
zmiennej `NYSHPORKA_SUPRIAHA_TOKEN`, a wydaje się go w zakładce „Moje konto”.

Szukać, pobierać i przekazywać pakiety pula pozwala tylko z kluczem. Jeśli go
jeszcze nie ma, `pull`, `sync` i `publish` same zaproponują podłączenie.

## Profil

`nysh share setup` bez flag pyta po kolei; z dowolną flagą — tylko zapisuje
podane i o nic nie pyta (dla skryptów i instalatora).

| pole | flaga | domyślnie |
|---|---|---|
| pseudonim w katalogu | `--as` | bez imienia |
| kontakt (publiczny) | `--contact`, usunąć — `--contact -` | brak |
| licencja tekstu | `--license` | `CC0-1.0` |
| kiedy przekazywać | `--consent nikoly \| pytaty \| zavzhdy` | `pytaty` — prowadzić listę i przypominać |
| pytać pulę przed odczytem | `--lookup / --no-lookup` | **nie** |
| geometria wierszy | `--geometry / --no-geometry` | tak |

!!! warning "Kontakt to dane publiczne"
    Trafia do każdego Twojego pakietu i widzi go każdy, kto pakiet przyjmie.
    Nigdy nie wstawia się sam (ani z `git config`, ani z nazwy użytkownika
    systemu) — tylko z wypełnionego przez Ciebie profilu albo z `--contact`. Dla
    jednego pakietu bez kontaktu — `--contact -`.

**Pytać pulę przed odczytem** (`--lookup`) oznacza: przed każdym `nysh read`
Nyshporka wysyła na serwer sygnaturę jednostki i liczbę skanów i, jeśli tekst
już jest, drukuje jeden wiersz. Serwer widzi przy tym, którą jednostkę
zamierzasz czytać — dlatego domyślnie jest to wyłączone.

## Karta jednostki: tytuł, lata, miejscowości, rodzaj

Pakowacz składa kartę sam — z paszportu folderu, rejestru inwentarza zespołu i
biblioteki jednostek. Robocze oznaczenia paszportu (data sprawdzenia w
nawiasach, „FS-тег: …”, „⚠ …”, oznaczenia priorytetu) do karty nie trafiają.
Gdy to za mało — jednostka bez tytułu, robocza nazwa zamiast prawdziwej — kartę
ustawia ten, kto przesyła:

```sh
nysh share card "ДАХмО 315-1-1234" --title "Сповідні розписи парафії …" \
  --years 1795-1797 --place "Слобідка" --place "Вербівка" --genre confession
```

To samo bezpośrednio przy pakowaniu: `nysh share pack … --title … --years …`.
Ustawione **jest zapamiętywane** (`data/share/cards.json`) i działa przy każdym
kolejnym pakowaniu tej jednostki — `pack`, `suggest --all`, automatyczne
przekazywanie. Obejrzeć — `nysh share card <шифра>`, skasować pole —
`--title ""`, całą kartę — `--clear`.

Rodzaje: `birth`, `marriage`, `death`, `confession`, `revision`, `clergy_list`,
`gazette`, `finding_aid`, `other` (można też opisem: «сповідні»).

**Gdzie są skany.** Gdy jednostkę odczytano z prywatnego zestawu skanów —
kolekcji badacza, kupionej lub zamówionej — w FamilySearch i Commons odbiorca
jej nie znajdzie. Karta wskazuje, kto ma skany:

```sh
nysh share card "ДАХмО 230-1-1234" --scans "Колекція дослідника=https://…"
```

Odnośnik idzie pierwszy wśród odnośników pakietu, z oznaczeniem `role: scans`,
i w puli stoi obok tekstu: po obrazy człowiek pójdzie właśnie tam. Jak reszta
karty jest zapamiętywany; skasować — `--scans ""`.

## Co odczytano, ale jeszcze nie przekazano

```sh
nysh share suggest                   # перелік зі статусами
nysh share suggest --all --ready     # спакувати все готове
nysh share suggest --skip "ДАХмО 315-1-1234" --why "платна зйомка"
```

Statusy: **gotowa**, **w puli bez ramek**, **niepełna** (odczytano mniej niż
80 % skanów — przekazuje się tylko z `--partial`), **bez skanów**. Co już jest
w puli, rozstrzyga przekrój puli (`nysh share sync`); jednostki, których
przekrój nie obejmuje, — dziennik pakowań. Odmowa jest zapamiętywana dla każdej
jednostki osobno: o jednostkę, której nie chcesz przekazywać, już się nie
pyta.

## Co jest w pakiecie

```
manifest.json    шифра, картка, джерело сканів, знаменник, ваші поля
frames.jsonl     перелік кадрів справи
runs/<прогін>/   NNNN.txt — сторінка, рядок у рядок; плюс паспорт прогону
README.md        пояснення для того, хто відкриє пакет без Нишпорки
```

Geometria wierszy (`*.lines.json`) idzie **osobnym** plikiem
`….geom.nyshtext`: waży ×10 więcej niż tekst i jest potrzebna tylko temu, kto
ma te same skany.

### Które przebiegi jadą

Głosy pakietu to odczyty jednostki, a nie wszystko, co leży obok. Zostają w
domu, a `pack` wymienia każdy z przyczyną:

- przebiegi pomiarowe (oznaczenie `control_run` w paszporcie przebiegu);
- próby: przebieg, którego wszystkie strony są w pełniejszym przebiegu **tego
  samego modelu** (części jednostki odczytane jednym modelem jadą obie);
- przebiegi innej jednostki o podobnej nazwie;
- cudze przyjęte przebiegi — przekazuje je autor, nie Ty;
- wskazane przez Ciebie: `--skip-run <прогін>`.

### Mianownik — najważniejsze pole

Manifest mówi, **ile skanów ma jednostka i ile z nich odczytano**, jakim
modelem i czy sprawdzano orientację. Bez tego cudzy odczyt hurtowo produkuje
fałszywe zera: ktoś przegrepuje trzy strony, wzięte za trzy tysiące, nie
znajdzie nazwiska — i uczciwie zamknie kierunek, robiąc wszystko poprawnie.

Dlatego pakiet z niepełnym odczytem albo bez nazwy modelu po prostu się nie
złoży. Odczytano fragment celowo — powiedz dlaczego:

```sh
nysh share pack "ДАХмО 315-1-1234" --partial "лише аркуші з нашим селом"
nysh share pack "ДАХмО 315-1-1234" --frames 408        # число кадрів справи, якщо пакувальник його не знайшов
```

## Twoje pola

```sh
nysh share pack "ДАХмО 315-1-1234" \
  --as "sergiy" --contact "t.me/…" \
  --note "читав Дяком, останні аркуші підмокли" \
  --link "звідки скани=https://…" \
  --extra "plivka=105208823"
```

- `--note` — dowolny tekst, dociera do czytelnika i trafia do README pakietu.
- `--link` — „podpis=adres” albo sam odnośnik; najprzydatniejszy jest ten, który
  prowadzi do skanów. Adres z `=` w środku (odnośnik FamilySearch) jest
  rozpoznawany w całości.
- `--extra` — pary „klucz=wartość”, które format przeniesie nietknięte. Para
  bez `=`, z pustym kluczem albo podana dwa razy — odmowa, a nie ciche
  pominięcie.

## Co nie trafia do pakietu

Pakowacz bierze **tylko** strony tekstu i paszport przebiegu — a z paszportu
tylko pola potrzebne odbiorcy: model, silnik, pismo, ile stron zrobiono. Nie
jadą ścieżki Twojego dysku, robocze notatki (`*_note`, objaśnienia pomiarów,
historia scalania), wycinki ratunkowe, dzienniki, kwarantanna, magazyn stron,
werdykty, kanon.

Zobaczyć, co dokładnie pojedzie, można przed złożeniem:

```sh
nysh share pack "ДАХмО 315-1-1234" --dry-run
```

## Notatnik jednostki

Oprócz tekstu o jednostce często wiadomo coś jeszcze, co przyda się każdemu,
kto ją otworzy: co naprawdę jest w księdze, gdzie inwentarz archiwum pomylił
się w tytule lub latach, gdzie leży kopia. Tu też należy wiersz, który maszyna
odczytała krzywo, a Ty sprawdzasz ze skanem. Wszystko to jest notatnikiem
jednostki. Leży obok przejrzanych kart i idzie do Supriahy **osobno od
tekstu**: dopisać go można także do księgi, którą przekazał ktoś inny.

```sh
nysh note add "ДАХмО 315-1-1234" --kind about --text "Метрична книга Покровської церкви, 1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind catalog-error --field years --archive-says 1834 --actually "1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind copy --other "ДАВіО 904-24-55" --text "копія в консисторії" --share
nysh note read "ДАХмО 315-1-1234" 0031 --line 153 --text "урожденная Прухницкая" --share

nysh note push "ДАХмО 315-1-1234" --dry-run   # що поїде
nysh note push "ДАХмО 315-1-1234"             # віддати
nysh note pull "ДАХмО 315-1-1234"             # що дописали інші
```

Do Supriahy jedzie tylko to, co oznaczono `--share`, oraz lista przejrzanych
kart bez Twoich komentarzy. Sprawy rodzinne — „tu zapisany jest mój dziadek” —
zapisuj jako `--kind note`: taki wpis nie jedzie nigdy, a wpisu ze słowami
rodzinnymi pula nie przyjmie, nawet oznaczonego. Na stronie księgi notatnik
widać osobno od tekstu i nie wchodzi on do liczby odczytanych stron: sprawdzone
wzrokiem to wybrane wiersze, a nie odczytana jednostka.

Sprawdzony wiersz jedzie do Supriahy razem z wycinkiem tego wiersza ze skanu,
szarym JPEG, jeśli skan jednostki jest na Twoim komputerze (bez niego wiersz
jedzie tylko jako tekst). **Udostępniając sprawdzone wiersze, zgadzasz się, że
właściciel Nyshporki może je wykorzystać do trenowania modeli rozpoznawania.**
Innym użytkownikom wycinki nie są przekazywane i nie pokazuje się ich na stronie
księgi; tekst sprawdzenia widzą wszyscy. Wycofany wpis (`nysh note retract` i
`note push`) zabiera z puli także wycinek.

## Przyjęcie cudzego pakietu

!!! tip "Jeśli pobierasz przez agenta"
    Skill `pull-case` prowadzi agenta od `pull` do wyszukiwania w przyjętym
    tekście i odczytuje na głos etykietę dopasowania: co z cudzego tekstu
    nałoży się na Twoje skany, a co — tylko do wyszukiwania.

```sh
nysh share inspect <файл або адреса>     # подивитись, нічого не розкладаючи
nysh share import <файл або адреса>      # прийняти
nysh share geometry <….geom.nyshtext>    # докласти рамки рядків
```

Pakiet przychodzi od osoby, której nie znasz, i odbiornik nie wierzy mu na
słowo:

- **bramki mierzą zawartość, a nie deklarację**: strony, wiersze i hash tekstu
  liczy się z samego pakietu, a pakiet, który deklaruje więcej, niż w nim jest,
  nie przechodzi;
- **wada pakietu — odmowa przed zapisem**: ścieżka poza
  `runs/<прогін>/<файл>`, nazwa niedopuszczalna w Windows, dowiązanie, zbyt
  duży plik — i na dysk nie trafia nic;
- rozkładane są tylko przebiegi wymienione w manifeście i tylko tekst z
  paszportem; paszport czyści się tą samą białą listą;
- **Twój odczyt nigdy nie jest nadpisywany** — nawet z `--force`. Przebieg o
  tej samej nazwie (bez względu na wielkość liter) — odmowa. `--force`
  zastępuje tylko pakiet przyjęty wcześniej;
- pakiet spod adresu z katalogu jest sprawdzany z jego sha256
  (`share pull --take` robi to sam; dla `import` i `geometry` spod adresu — `--sha256`):
  plik podmieniony w magazynie już po tym, jak pula go przyjęła, nie jest
  przyjmowany.

## Na ile cudzy tekst nałoży się na Twoje skany

Klucz jednostki się do tego nie nadaje: składa się go z nazwy folderu i Twojego
informatora archiwów, więc u dwóch osób ta sama księga dostaje różne klucze.
Dlatego pakiet niesie listę skanów i odcisk zestawu skanów, a Nyshporka
**mierzy** zgodność i mówi na głos:

| etykieta | co oznacza | co działa |
|---|---|---|
| `exact` | zgodziły się wszystkie skany (hash lub identyfikator FamilySearch) albo odcisk zestawu skanów na co najmniej trzech skanach | wszystko, łącznie z wycinkami i cudzą geometrią |
| `by-name` | zgodziły się nazwy i liczba | wszystko oprócz cudzej geometrii |
| `by-position` | zgodziła się tylko liczba lub część skanów | strona tak, wycinek pod znakiem zapytania |
| `text-only` | skanów nie ma albo są inne | wyszukiwanie, strona, sygnatura |

Cudza geometria nakłada się tylko na tekst **tego samego wkładu** i tylko przy
`exact`; w innym razie — odmowa z wyjaśnieniem (`--force`, jeśli masz pewność).

`text-only` to nie porażka, lecz najczęstszy scenariusz pożytku: znajdujesz
nazwisko w cudzym tekście, widzisz jednostkę i numer karty — i idziesz obejrzeć
sam skan w źródle.

!!! danger "Zgodność nazwy pliku nie oznacza tego samego skanu"
    Płaski staging przenumerowuje strony, więc dwa zestawy skanów jednej księgi
    łatwo dają jednakowe nazwy przy różnej zawartości. Właśnie dlatego etykieta
    nigdy nie jest podwyższana na podstawie domysłu.

## Własne zero i cudze zero to różne odpowiedzi

Przyjęte przebiegi są oznaczone, a wyszukiwanie to nazywa:

```
знаменник: кадрів 3772 · прочитано 3770 · у сторі прогонів 2 із 2 …
з них чужий декод: прогонів 2 із 2 · сторінок 3770 · від oksana
```

Cudzy tekst czytał inny model, za jego kompletność nikt tu nie odpowiada, a
odczytać go ponownie można tylko, prosząc tego, kto go dał. Zero na nim waży
mniej niż zero na własnym — i musi to być widać.

## Pula

```sh
nysh share pull                     # огляд пулу: архів · фонд · опис, справ і сторінок
nysh share pull "Слобідка"          # що є в каталозі
nysh share pull "ДАХмО 315-1-1234" --take
nysh share pull --repo RGIA --fond 592           # серія: що в ній є
nysh share pull --repo RGIA --fond 592 --take    # і прийняти всю
nysh share stats --catalog          # хто скільки вніс
nysh share sync --repo DAHMO --fond 315   # зріз для колонки «пул» у `cases fond`
```

Katalog — API `https://api.nyshporka.online/v1`. Własne lustro lub serwer
testowy ustawia się zmienną `NYSHPORKA_TOLOKA` albo flagą `--base`; klucz
Supriahy na taki adres **nie jedzie** — ani z magazynu kluczy, ani z
`NYSHPORKA_SUPRIAHA_TOKEN`. Własny serwer trzeba wskazać wprost:
`NYSHPORKA_SUPRIAHA_TRUST=https://хост[:порт]` — tylko HTTPS i tylko dokładna
zgodność adresu; wtedy jedzie na niego klucz Supriahy.
Pętla zwrotna tego komputera (`127.0.0.1`, `localhost`) i tak jest zaufana.

`sync` z `--repo`/`--fond` dopisuje przekrój jednego zespołu do istniejącego; o
zespołach, których przekrój nie obejmuje, kolumna «пул» (pula) mówi «не знаємо»
(nie wiemy), a nie «немає» (brak).

Odmowę puli (bramki, dzienny limit) Nyshporka drukuje słowami serwera. Gdy ten
sam tekst już jest w puli, `publish` mówi, czy został przyjęty, kiedyś
odrzucony, czy jeszcze nie zakończony — «уже в Супрязі» (już w serwisie
Supriaha) oznacza tylko pierwsze.

## Ślad wymiany

`data/share/journal.jsonl` pamięta, co skąd przyszło i co dokąd poszło, a
przyjęte pakiety zostają w `data/share/inbox`. To nie ewidencja dla samej
ewidencji: fakt wzięty z cudzego odczytu i wpisany do kanonu musi opierać się
na stałym pliku — inaczej cytat zawiśnie w próżni, gdy tylko usuniesz
pobrane.

```sh
nysh share list          # журнал
nysh share stats         # скільки віддано, скільки прийнято, від кого
```

## Licencja

Pakiet mówi, na jakich warunkach przekazywany jest tekst (`--license`,
domyślnie `CC0-1.0`), i osobno — warunki źródła skanów (`--source-terms`),
jeśli istnieją. Bez licencji pakiet się nie złoży: odbiorca musi wiedzieć, co
wolno z tym robić.
