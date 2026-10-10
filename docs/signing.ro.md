# Licențe, semnarea codului și confidențialitate

## Politica de semnare a codului

Se semnează **un singur artefact** — programul de instalare pentru Windows
`nyshporka-<versiune>-setup.exe` de pe [pagina versiunilor][rel]. Pachetul
wheel și `sdist` de pe PyPI nu se semnează cu Authenticode: acolo integritatea
o garantează indexul însuși și [Trusted Publishing][tp] prin OIDC, fără
tokenuri de lungă durată.

**Ce se semnează și de către cine.** Fișierul se construiește exclusiv în
GitHub Actions (`.github/workflows/release.yml`, job `windows-setup`), din
tagul `v*`, după verificările de calitate și verificarea datelor private. În
lanț nu există nicio construire manuală pe mașina cuiva. Proiectul este condus
de o singură persoană, așa că rolurile Author, Reviewer și Approver coincid;
fiecare semnătură se confirmă separat, manual.

**Verificarea pentru dumneavoastră:**

```powershell
(Get-AuthenticodeSignature .\nyshporka-setup.exe).Status   # Valid
```

Lângă programul de instalare, în versiune se află `.sha256` — cu el puteți
verifica fișierul descărcat independent de semnătură.

> Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org)

⚠ **Deocamdată cererea a fost depusă, iar versiunile nu sunt încă semnate.**
Până atunci Windows afișează „Windows v-a protejat PC-ul” — este de așteptat
pentru un program pe care încă puțini l-au descărcat. Semnătura va elimina
mențiunea „Editor necunoscut”, dar avertismentul însuși va dispărea abia când
se va aduna reputația: Microsoft a renunțat la încrederea imediată în
certificate, inclusiv în cele EV.

[rel]: https://github.com/SERGIUSH-UA/nyshporka/releases
[tp]: https://docs.pypi.org/trusted-publishers/

## Confidențialitate

Nyshporka este o aplicație locală: nu există telemetrie, nu există conturi,
cercetarea nu se încarcă nicăieri, iar aplicația iese în rețea doar atunci
când i se cere acest lucru printr-o comandă. Lista completă a locurilor unde
și de ce — [`PRIVACY.md`](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

## Licență

[AGPL-3.0-or-later](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE).

Copyleft-ul aici nu este o alegere de moment, ci o cerință a arborelui de
dependențe: `Unidecode` — dependență de bază (normalizarea numelor,
`utils/text.py`) — este sub **GPL-2.0-or-later**. AGPL-3.0 este compatibilă cu
ea și mai strictă, iar aplicația funcționează prin browser, adică exact cazul
pe care îl acoperă AGPL.

⚠ Pachetul `strhub` conține submodulul `models/abinet` sub licența
non-comercială USTC. Nyshporka folosește din el **doar PARSeq** (Apache-2.0).

**Ponderile modelelor — separat, sub [CC BY-SA 4.0](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE-MODELS.md).** Ele
nu se află în pachet, vin într-o versiune separată, iar AGPL nu are pentru
ponderile binare un „cod sursă corespunzător” definit — adică nu ar proteja
nimic, în schimb i-ar descuraja pe cei care vor să le folosească cinstit.
Condițiile sunt aceleași în spirit: liber, inclusiv comercial, cu atribuire,
iar ponderile antrenate suplimentar rămân deschise.
