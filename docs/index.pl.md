# Nyshporka

<p align="center">
  <img alt="Nyshporka z lupą" src="assets/maskot-lupa.webp" width="200" height="231">
</p>

<p align="center"><em>Czyta rękopis. Przynosi to, co znalazła.</em></p>

**Nyshporka pomaga szukać przodków w dokumentach archiwalnych** — księgach
metrykalnych, spisach spowiadających się, rewizjach z XVIII–XIX wieku. Ale
nie działa tak jak zwykły program.

## Pracę wykonuje asystent, decydujesz Ty

<p align="center">
  <img alt="Genealożka ogląda kartę, którą przyniósł jej asystent Nyshporka" src="assets/scena-pomichnyk.webp" width="420" height="382">
</p>

Asystentowi takiemu jak Claude czy ChatGPT można pozwolić pracować na Twoim
komputerze: otwierać foldery, uruchamiać programy, zapisywać wynik — i za
każdym razem pytać o Twoją zgodę. Takiego asystenta nazywa się **agentem**.

Nyshporka powstała właśnie dla niego. Piszesz zwykłymi słowami:
*„oto folder ze skanami ksiąg metrykalnych z Czeczelnika — znajdź wszystkich Kowalskich”*.
Asystent czyta rękopiśmienne karty, szuka nazwiska i przynosi znalezione
wiersze wprost na skanie, z numerem karty.

**Czy to Twój ród — decydujesz Ty.** Tak samo Ty decydujesz, co zamówić w
archiwum i czy dzielić się odczytanym tekstem. Asystent pokazuje, a nie
wyciąga wniosków za Ciebie.

!!! tip "Zobacz na żywo"

    Nyshporkę pokazano w działaniu podczas transmisji
    [„ШІ-агенти в генеалогії: дослідження майбутнього”](https://www.youtube.com/live/VsvenHgbVZY)
    („Agenci AI w genealogii: badanie przyszłości”, „В гостях у Качки” nr 11) —
    [demonstracja mniej więcej od 42.
    minuty](https://www.youtube.com/live/VsvenHgbVZY?t=2550).

## Co Nyshporka daje asystentowi

Sam z siebie asystent nie zna archiwów i nie odczyta starego rękopisu.
Nyshporka daje mu:

* **wiedzę, co gdzie leży** — informatory archiwów, inwentarze zespołów, wykaz
  wsi i parafii;
* **umiejętność czytania rękopisów** — trzy modele odczytu, wytrenowane na
  archiwach ukraińskich, mołdawskich i polskich: **Pysar** i **Diak** czytają
  cyrylicę, **Skryba** — alfabet łaciński;
* **pamięć** — co już przejrzano i znaleziono, żeby nie kartkować tych samych
  kart drugi raz;
* **zasady uczciwej pracy** — „nie znalazłem” zawsze z wyjaśnieniem, ile kart
  przejrzano.

## Dlaczego to inne podejście

Zwykły program potrafi dokładnie to, co w nim zaprogramowano: ile przycisków —
tyle możliwości. Nyshporka natomiast daje asystentowi osobne umiejętności —
znaleźć jednostkę, odczytać kartę, znaleźć nazwisko, zapisać znalezisko — a on
składa z nich to, czego potrzeba akurat dla Twojego pytania: *„zrób tabelę
wszystkich ślubów w tej wsi z lat 20. XIX wieku”*, choć osobnego przycisku do
tego nikt nie zrobił. A im mądrzejsi stają się asystenci, tym więcej potrafi
Nyshporka — nawet bez aktualizacji.

## Czego potrzeba

* Komputer z systemem Windows, macOS lub Linux i około 5 GB wolnego miejsca.
* Sama Nyshporka — bezpłatna, z otwartym kodem.
* Asystent, który potrafi pracować na komputerze: **Claude Desktop**
  (subskrypcja Claude Pro lub Max), **Claude Code** albo **Codex** (subskrypcja
  ChatGPT).

Wszystko to instaluje się w pół godziny, bez żadnego polecenia —
[**„Instalacja i podłączenie asystenta”**](install.md). Modele odczytu
asystent zainstaluje sam: to dwa jednorazowe kroki, `nysh htr install` i
`nysh models get`.

**Skany nigdzie nie trafiają** — wszystko działa na Twoim komputerze. Nie ma
telemetrii ani kont.

!!! warning "Stan: wczesna wersja"

    Katalogi, odczyt rękopisu, wyszukiwanie nazwiska, ewidencja i aplikacja w
    przeglądarce działają. Czego jeszcze nie ma — w [częstych
    pytaniach](faq.md#chogo-shche-nemaie), bez przemilczeń.

## Słowa, które tu się pojawiają { #slovnyk }

| słowo | co to jest |
|---|---|
| **asystent (agent)** | asystent AI — Claude Desktop, Claude Code lub Codex — któremu pozwolono pracować na Twoim komputerze |
| **modele odczytu** | Pysar, Diak i Skryba — zamieniają rękopiśmienną kartę w tekst |
| **odczytany tekst** | to, co model odczytał z karty. Zawiera błędy: szuka się w nim, a znalezisko ogląda na skanie |
| **jednostka** | archiwalna jednostka przechowywania z sygnaturą, np. `ДАХмО 315-1-8433`; w Nyshporce — jeden folder ze skanami |
| **karta · skan** | strona jednostki · jeden obraz (skan) |
| **zestaw skanów** | komplet skanów jednej jednostki — własny, kupiony lub ze strony archiwum |
| **folder roboczy** | folder Nyshporki, domyślnie `Документи\Нишпорка` (Dokumenty\Nyshporka): tam leżą Twoje badania. W poleceniach nazywa się „przestrzenią roboczą” (workspace) |
| **aplikacja** | okno Nyshporki w przeglądarce — by widzieć znaleziska, przeglądać skany i odczytany tekst |
| **skille** | gotowe schematy pracy dla asystenta: jak odczytać jednostkę, jak szukać nazwiska, gdzie kopać dalej |
| **Supriaha** | wspólny bank odczytanych jednostek na [nyshporka.online/supriaha](https://nyshporka.online/supriaha): tego, co odczytał jeden, nie trzeba czytać drugi raz |

## Dokąd dalej

* [Instalacja i podłączenie asystenta](install.md)
* [Jak pracować](start.md) — o co prosić, jak sprawdzać znaleziska
* [Częste pytania](faq.md)
* Dla asystenta i programisty — [przewodniki](agents/index.md)
