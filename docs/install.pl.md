# Instalacja i podłączenie asystenta

Główna droga — bez żadnego polecenia: trzy programy we właściwej kolejności i
jedno gotowe zapytanie. Zajmuje 30–40 minut, większość czasu to pobieranie.

!!! note "Dlaczego nie czat na stronie"

    Na czacie na claude.ai czy chatgpt.com Nyshporka nie działa: czat odpowiada
    tekstem i nie ma dostępu do Twojego dysku. Potrzebny jest **program-asystent**,
    który rozmawia tak samo jak czat, ale sam wykonuje działania na komputerze i
    pyta o zgodę przed każdym z nich.

## Czego potrzeba

* Windows 10 lub 11, macOS albo Linux.
* Około 5 GB wolnego miejsca: modele odczytu i wszystko, czego potrzebują — 2.5 GB.
* Subskrypcja **Claude Pro lub Max** — dla Claude Desktop
  ([plany](https://claude.com/pricing)). Albo subskrypcja ChatGPT — dla Codex.
  Sama Nyshporka jest bezpłatna: płacisz tylko za asystenta.

## Krok 1. Zainstaluj Nyshporkę

Nyshporkę instaluje się **najpierw**, asystenta — na końcu (dlaczego — w kroku 3).

=== "Windows"

    1. [:material-download: Pobierz instalator](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       i uruchom go.
    2. Jeśli Windows pisze **„System Windows ochronił ten komputer”** —
       „Więcej informacji” → „Uruchom mimo to”. Tak Windows wita każdy program,
       który pobrało jeszcze niewiele osób.
    3. Na pytanie «Що ставимо» (Co instalujemy) wybierz **«Каталоги + читання
       рукопису й пошук у прочитаному»** (katalogi + odczyt rękopisu i
       wyszukiwanie w odczytanym tekście).
    4. Na końcu zostaw zaznaczone «Запустити Нишпорку» (Uruchom Nyshporkę) — w
       przeglądarce otworzy się aplikacja. To Twój komputer, a nie strona
       internetowa: działa też bez internetu.

=== "macOS i Linux"

    Otwórz „Terminal”, wklej jeden wiersz i naciśnij Enter:

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    Gdy skrypt skończy, zamknij okno terminala.

## Krok 2. Git for Windows

Pobierz [Git for Windows](https://git-scm.com/downloads/win) i zainstaluj,
wszędzie klikając „Next”. Bez niego w Claude Desktop nie otwiera się zakładka
Code, a Nyshporce jest potrzebny do zainstalowania modeli odczytu. Na macOS Git
zwykle już jest.

## Krok 3. Claude Desktop

1. Pobierz aplikację:
   [Windows](https://claude.ai/api/desktop/win32/x64/setup/latest/redirect),
   [macOS](https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect).
2. Uruchom ją i zaloguj się na swoje konto.
3. Kliknij zakładkę **Code** u góry pośrodku.

!!! warning "Jeśli Claude był już zainstalowany na komputerze"

    Zamknij go **całkowicie** — prawym przyciskiem na ikonie przy zegarze →
    „Zakończ” (Quit) — i otwórz ponownie. Program zapamiętuje, gdzie szukać
    poleceń, w chwili uruchomienia, więc o świeżo zainstalowanej Nyshporce nie
    wie. Objaw: asystent pisze, że polecenia `nysh` nie znaleziono.

## Krok 4. Otwórz folder roboczy

W zakładce Code, zanim cokolwiek napiszesz:

1. Wybierz **Local** — asystent będzie pracował na Twoim komputerze.
2. **Select folder** → folder `Документи\Нишпорка` (Dokumenty\Nyshporka). Utworzył
   go instalator; tam będą skany, odczytany tekst i notatki. Jeśli takiego
   folderu nie ma, Twoje „Dokumenty” synchronizują się z OneDrive, a Nyshporka
   położyła folder obok. Gdzie dokładnie — pokaże aplikacja: **🐾 Огляд**
   (Przegląd) → «Перевірити цю машину» (Sprawdź ten komputer).
3. Tryb uprawnień — **Manual**: asystent będzie pytał przed każdym działaniem,
   a Ty widzisz, co dokładnie robi.

## Krok 5. Wklej gotowe zapytanie

Skopiuj cały tekst do pola wpisywania i naciśnij Enter:

```text
Przeczytaj https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
i zrób według niego wszystko, żeby Nyshporka była gotowa na tym komputerze: sprawdź
komputer, w razie potrzeby zainstaluj silniki odczytu i modele i umieść skille dla wszystkich
projektów. Każdy krok tłumacz mi prostymi słowami.
Gdy wszystko będzie zielone — zapytaj, jakiego nazwiska szukam i w jakich zapisach.
```

Asystent przeczyta instrukcję napisaną dla niego i, za każdym razem pytając o zgodę:

* sprawdzi komputer (`nysh doctor`);
* zainstaluje modele odczytu (`nysh htr install`, `nysh models get`) — to
  najdłuższy krok, około 2.5 GB;
* umieści skille — gotowe schematy pracy (`nysh skills install --user`);
* zapyta, jakiego nazwiska szukamy.

Gotowe, gdy asystent mówi, że sprawdzenie przeszło bez czerwonych wierszy, i
pyta o nazwisko. Dalej — [„Jak pracować”](start.md).

## Inni asystenci

**Codex** (OpenAI, subskrypcja ChatGPT):
[aplikacja](https://learn.chatgpt.com/docs/quickstart) lub
[wersja dla terminala](https://learn.chatgpt.com/docs/cli). Kroki 1 i 2 są te
same; w kroku 4 otwórz folder `Документи\Нишпорка`; w zapytaniu zamiast
„umieść skille dla wszystkich projektów” napisz „umieść skille w folderze
`~/.agents/skills`”.

**Claude Code w terminalu** — wystarczy jeden wiersz i uruchomienie:

```powershell
nysh skills install --user   # скіли для всіх проєктів
claude
```

**Inni** — każdy asystent, który czyta skille w formacie `SKILL.md`
(Agent Skills), między innymi OpenClaw. Umieść je w jego folderze:
`nysh skills install --target <тека>`.

## Jeśli coś jest nie tak { #yakshcho-shchos-ne-tak }

| co widzisz | co robić |
|---|---|
| asystent: „polecenia `nysh` nie znaleziono” | Całkowicie zamknij Claude (ikona przy zegarze → Zakończ) i otwórz ponownie. W terminalu — otwórz nowe okno; nie pomogło — uruchom ponownie komputer |
| zakładka Code proponuje zmianę planu | Potrzebna jest subskrypcja Claude Pro lub Max |
| asystent: „środowisko silników nie jest gotowe” | Powiedz mu: „zainstaluj silniki odczytu i modele” |
| asystent nie widzi folderu ze skanami | Folder leży poza folderem roboczym; asystent powinien zapytać o zgodę na wzięcie go do ewidencji (`nysh roots add`). Pliki nigdzie nie są przenoszone |
| instalator zakończył się „kod 1” | Zobacz ostatnie wiersze wyniku. Najczęściej — przerwane pobieranie, brak miejsca albo antywirus |
| coś innego | [Napisz do autora](https://github.com/SERGIUSH-UA/nyshporka/issues), dodając dosłownie, co napisał asystent |

## Bez asystenta lub z Pythonem

Jeśli Python lub `uv` już jest, pakiet instaluje się z PyPI:

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install "nyshporka[app,archives,htr]"
nysh init                      # створити робочу теку
nysh doctor                    # перевірити машину
nysh serve                     # відкрити застосунок у браузері
nysh htr install               # середовище для моделей читання, разово
nysh models get                # моделі читання, ~225 МБ, разово
```

Jednowierszowy instalator dla Windows bez Pythona — w PowerShell:

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```

??? note "Dla zaawansowanych: zestawy, przełączniki instalatora, gdzie leżą badania"

    **Zestawy.** `nysh init` pyta, z czego będziesz korzystać; zmienić można w
    każdej chwili — `nysh sections`, bez ponownej instalacji.

    | zestaw | co zawiera |
    |---|---|
    | `catalog` | katalogi, gazetteer, inwentarze zespołów — bez modeli odczytu, oszczędza ~2.5 GB |
    | `amateur` | + odczyt rękopisu i przeglądarka skanów |
    | `researcher` (domyślnie) | + wyszukiwanie w odczytanym tekście, ewidencja, eksport |
    | `lab` | + oznaczanie wierszy i douczanie modeli (`nysh train`) |

    **Przełączniki.** Tak samo dla skryptów i `.exe`:

    | co ustawiamy | `windows.ps1` | `unix.sh` | `.exe` |
    |---|---|---|---|
    | zestaw | `-Preset catalog` | `NYSH_PRESET=catalog` | `/PRESET=catalog` |
    | cały skład pakietu | `-Source 'nyshporka[app,archives]'` | `NYSH_SOURCE=…` | — |
    | konkretna wersja | `-Version X.Y.Z` | przez `NYSH_SOURCE` | wbudowana w plik |
    | folder instalacji | `-Home_ D:\Nysh` | — | `/DIR=D:\Nysh` |
    | bez pytań | — | — | `/VERYSILENT` |
    | bez pakietu informatorów | `-NoCatalog` | `NYSH_NO_CATALOG=1` | — |
    | dziennik | — | — | `/LOG=setup.log` |
    | gdzie mają leżeć badania | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` |

    ⚠ `irm … | iex` dla skryptu Windows nie działa (plik ma UTF-8 BOM) —
    najpierw `-OutFile`, potem `-File`.

    **Komputer programisty.** Instalator niczego nie przestawia: `uv` i własny
    Python 3.12 trafiają do folderu aplikacji, `pyenv`, `conda` i kompilacje pod
    CUDA zostają, jak były. Poza swoimi folderami — tylko dopisek w PATH.
    `sh -s -- --dry-run` pokazuje zmiany i niczego nie robi,
    `NYSH_NO_MODIFY_PATH=1` nie rusza PATH. Lista zmian trafia do
    `install-trace.txt`.

    **Gdzie leżą badania.** Folder roboczy (w poleceniach — przestrzeń robocza):

    ```bash
    nysh init D:/Дослідження                      # обрати місце при створенні
    export NYSHPORKA_WORKSPACE=D:/Дослідження     # закріпити для всіх команд
    nysh --workspace D:/Дослідження doctor        # разово
    ```

    Bez zmiennej polecenia szukają `nyshporka.toml` w górę od bieżącego folderu.
    Gdzie aplikacja patrzy teraz — `nysh doctor`, wiersz «Робочий простір»
    (przestrzeń robocza).

    **Mac z procesorem Intel.** Instaluje się jak wszędzie; `nysh htr install`
    bierze Pythona i torch z conda-forge, bo PyPI nie ma dla niego kół torch
    nowszych niż 2.2.2.

    **Karta graficzna nie jest potrzebna.** Bez niej strona jest odczytywana w
    ~20 s – 1 min (zależnie od procesora i liczby wierszy na stronie), z kartą —
    w ~10–15 s. Przyspieszenie kartą to osobny krok, podpowie go `nysh doctor`.
