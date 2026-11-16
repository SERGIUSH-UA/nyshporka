# Nyshporka

<p align="center" markdown>
![Nyshporka z lupą](assets/maskot-lupa.webp){ width="200" height="231" }
</p>

<p align="center"><em>Czyta rękopis. Przynosi to, co znalazła.</em></p>

**Nyshporka to asystent AI dla genealogów i wszystkich, którzy badają
przeszłość na podstawie starych rękopisów.** Mówisz, kogo i gdzie szukasz, a
asystent znajduje potrzebne księgi archiwalne, czyta stary rękopis i pokazuje
znalezione wprost na skanie.

## Pracę wykonuje asystent, decydujesz Ty

<p align="center" markdown>
![Genealożka ogląda kartę, którą przyniósł jej asystent Nyshporka](assets/scena-pomichnyk.webp){ width="420" height="382" }
</p>

Asystentowi takiemu jak Claude czy ChatGPT można pozwolić pracować na Twoim
komputerze: otwierać foldery, uruchamiać programy, zapisywać wynik, za każdym
razem pytając o Twoją zgodę. Takiego asystenta nazywa się **agentem**.

Nyshporka powstała właśnie dla niego. Piszesz zwykłymi słowami:
*„oto folder ze skanami ksiąg metrykalnych z Czeczelnika — znajdź wszystkich Kowalskich”*.
Agent sam ustala, w jakich księgach mogą być wpisy o wsi, pobiera skany,
czyta rękopis i pokazuje wiersze z nazwiskiem na stronie, z numerem karty.

Patrzysz na te wiersze i sam decydujesz, czy to Twoi przodkowie. Tak samo
decydujesz, co zamówić w archiwum i czy dzielić się odczytanym tekstem.
Asystent pokazuje znalezione, a wnioski wyciągasz Ty.

!!! tip "Lekcje wideo"

    [Seria krótkich lekcji wideo](https://nyshporka.online/pl/uroky) — od
    instalacji do pierwszego odkrycia i drzewa z dowodami, po 5–9 minut. Seria
    wciąż rośnie. Lekcje są po ukraińsku, z napisami, które YouTube
    przetłumaczy na Twój język.

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
* **umiejętność czytania rękopisów** — własne modele odczytu, wytrenowane na
  archiwach ukraińskich, mołdawskich i polskich: **Pysar** i **Diak** czytają
  cyrylicę, **Skryba** — alfabet łaciński;
* **pamięć** — co już przejrzano i znaleziono, żeby nie kartkować tych samych
  kart drugi raz;
* **zasady uczciwej pracy** — każde znalezisko widać na skanie, a „nie
  znalazłem” zawsze z wyjaśnieniem, ile kart przejrzano.

## Gotowych przycisków tu nie ma

Zwykły program potrafi dokładnie to, co w nim zaprogramowano: ile przycisków,
tyle możliwości. Nyshporka daje asystentowi osobne umiejętności: znaleźć
jednostkę, odczytać kartę, znaleźć nazwisko, zapisać znalezisko. Z nich składa
on to, czego potrzeba dla Twojego pytania, choć osobnego polecenia do tego nikt
nie zrobił: *„zrób tabelę wszystkich ślubów w tej wsi z lat 20. XIX wieku”*.
Tak przechodzi się całą drogę: od „gdzie szukać” do rodowodu, w którym przy
każdym fakcie jest wycinek skanu, i dalej do strony rodu z drzewem i mapą. A im
mądrzejsi stają się asystenci, tym więcej potrafi Nyshporka, nawet bez
aktualizacji.

## Nie tylko przodkowie

Szukać można nie tylko nazwiska, ale też nazwy wsi, słowa czy wydarzenia.
Dlatego w tych samych księgach bada się historię wsi i parafii, kościoła czy
klasztoru, miejscowych zwyczajów, biografię znanej osoby. Na przykład historię
własnej wsi można wyczytać z XVII-wiecznych ksiąg grodzkich: Nyshporka znajdzie
wśród tysięcy stron każdą wzmiankę o wsi, ludziach i wydarzeniach i pokaże
każdą na skanie. Więcej: [nie tylko genealogia](how-it-works.md#ne-lyshe-rodovid).

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

* [Jak to działa](how-it-works.md) — cały cykl od „gdzie szukać” do strony
  rodu i jak odnajduje się nazwisko w rękopisie (po ukraińsku)
* [Instalacja i podłączenie asystenta](install.md)
* [Jak pracować](start.md) — o co prosić, jak sprawdzać znaleziska
* [Częste pytania](faq.md)
* Dla asystenta i programisty — [przewodniki](agents/index.md)
