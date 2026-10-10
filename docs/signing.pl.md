# Licencje, podpisywanie i prywatność

## Zasady podpisywania kodu

Podpisywany jest **jeden artefakt** — instalator dla Windows
`nyshporka-<версія>-setup.exe` ze [strony wydań][rel]. Koło i `sdist` na
PyPI nie są podpisywane Authenticode: tam integralność gwarantuje sam indeks i
[Trusted Publishing][tp] przez OIDC, bez długotrwałych tokenów.

**Co jest podpisywane i przez kogo.** Plik jest budowany wyłącznie w GitHub
Actions (`.github/workflows/release.yml`, job `windows-setup`), z tagu `v*`, po
bramkach jakości i sprawdzeniu pod kątem danych prywatnych. Ręcznego budowania
na czyimś komputerze w łańcuchu nie ma. Projekt prowadzi jedna osoba, więc role
Author, Reviewer i Approver się pokrywają; każdy podpis jest zatwierdzany
osobno, ręcznie.

**Sprawdzenie dla Ciebie:**

```powershell
(Get-AuthenticodeSignature .\nyshporka-setup.exe).Status   # Valid
```

Obok instalatora w wydaniu leży `.sha256` — można nim sprawdzić pobrany plik
niezależnie od podpisu.

> Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org)

⚠ **Na chwilę obecną wniosek został złożony, a wydania nie są jeszcze
podpisane.** Do tego czasu Windows pokazuje „System Windows ochronił ten
komputer” — to oczekiwane dla programu, który pobrało jeszcze niewiele osób.
Podpis usunie napis „Nieznany wydawca”, ale samo ostrzeżenie zniknie dopiero
wtedy, gdy zbierze się reputacja: Microsoft zniósł natychmiastowe zaufanie do
certyfikatów, w tym także EV.

[rel]: https://github.com/SERGIUSH-UA/nyshporka/releases
[tp]: https://docs.pypi.org/trusted-publishers/

## Prywatność

Nyshporka to aplikacja lokalna: nie ma telemetrii, nie ma kont, badania nigdzie
nie są wysyłane, a z siecią aplikacja łączy się tylko wtedy, gdy poproszono ją o
to poleceniem. Pełna lista tego, dokąd i po co, —
[`PRIVACY.md`](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

## Licencja

[AGPL-3.0-or-later](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE).

Copyleft nie jest tu kwestią nastroju, lecz wymogiem drzewa zależności:
`Unidecode` — zależność rdzenia (normalizacja imion, `utils/text.py`) — jest na
licencji **GPL-2.0-or-later**. AGPL-3.0 jest z nią zgodna i surowsza, a
aplikacja działa przez przeglądarkę, czyli to dokładnie ten przypadek, który
AGPL obejmuje.

⚠ Pakiet `strhub` zawiera podmoduł `models/abinet` na niekomercyjnej licencji
USTC. Nyshporka korzysta z niego **tylko z PARSeq** (Apache-2.0).

**Wagi modeli — osobno, na licencji [CC BY-SA 4.0](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE-MODELS.md).** W pakiecie ich
nie ma, przychodzą osobnym wydaniem, a AGPL dla binarnych wag nie ma
określonego „odpowiedniego kodu źródłowego” — czyli niczego by nie chroniła, za
to odstraszałaby tych, którzy chcą użyć ich uczciwie. Warunki są te same w
duchu: swobodnie, także komercyjnie, z podaniem autorstwa, a douczone wagi
pozostają otwarte.
