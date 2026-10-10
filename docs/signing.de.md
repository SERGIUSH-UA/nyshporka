# Lizenzen, Signierung und Datenschutz

## Richtlinie zur Codesignierung

Signiert wird **ein Artefakt** — das Installationsprogramm für Windows
`nyshporka-<версія>-setup.exe` von der [Release-Seite][rel]. Das Wheel und
`sdist` auf PyPI werden nicht mit Authenticode signiert: Dort garantiert der
Index selbst die Unversehrtheit, zusammen mit [Trusted Publishing][tp] über
OIDC, ohne langlebige Tokens.

**Was signiert wird und von wem.** Die Datei wird ausschließlich in GitHub
Actions gebaut (`.github/workflows/release.yml`, Job `windows-setup`), aus
einem Tag `v*`, nach den Qualitätsprüfungen und der Prüfung auf private
Daten. Einen manuellen Build auf irgendjemandes Rechner gibt es in der Kette
nicht. Das Projekt führt eine einzige Person, daher fallen die Rollen Author,
Reviewer und Approver zusammen; jede Signatur wird einzeln und von Hand
bestätigt.

**Prüfung für Sie:**

```powershell
(Get-AuthenticodeSignature .\nyshporka-setup.exe).Status   # Valid
```

Neben dem Installationsprogramm liegt im Release eine `.sha256` — damit lässt
sich der Download unabhängig von der Signatur abgleichen.

> Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org)

⚠ **Derzeit ist der Antrag gestellt, und die Releases sind noch nicht
signiert.** Bis dahin zeigt Windows „Der Computer wurde durch Windows
geschützt“ — das ist bei einem Programm, das bisher nur wenige
heruntergeladen haben, zu erwarten. Die Signatur entfernt den Hinweis
„Unbekannter Herausgeber“, die Warnung selbst verschwindet aber erst, wenn
sich Reputation angesammelt hat: Microsoft hat das sofortige Vertrauen in
Zertifikate abgeschafft, auch in EV-Zertifikate.

[rel]: https://github.com/SERGIUSH-UA/nyshporka/releases
[tp]: https://docs.pypi.org/trusted-publishers/

## Datenschutz

Nyshporka ist eine lokale Anwendung: Es gibt keine Telemetrie und keine
Benutzerkonten, die Forschung wird nirgendwohin hochgeladen, und ins Netz geht
die Anwendung nur, wenn man sie per Befehl darum gebeten hat. Die
vollständige Liste, wohin und wozu —
[`PRIVACY.md`](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

## Lizenz

[AGPL-3.0-or-later](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE).

Copyleft ist hier keine Frage der Laune, sondern eine Anforderung des
Abhängigkeitsbaums: `Unidecode` — eine Kernabhängigkeit (Normalisierung von
Namen, `utils/text.py`) — steht unter **GPL-2.0-or-later**. AGPL-3.0 ist damit
kompatibel und strenger, und die Anwendung arbeitet über den Browser, also
genau der Fall, den die AGPL abdeckt.

⚠ Das Paket `strhub` enthält das Untermodul `models/abinet` unter einer
nicht-kommerziellen Lizenz der USTC. Nyshporka verwendet daraus **nur
PARSeq** (Apache-2.0).

**Die Gewichte der Modelle stehen gesondert unter [CC BY-SA 4.0](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE-MODELS.md).** Im Paket
sind sie nicht enthalten, sie kommen mit einem eigenen Release, und die AGPL
hat für binäre Gewichte keinen definierten „entsprechenden Quellcode“ — sie
würde also nichts schützen, aber diejenigen abschrecken, die sie redlich
nutzen wollen. Die Bedingungen sind dem Geist nach dieselben: frei, auch
kommerziell, mit Namensnennung, und nachtrainierte Gewichte bleiben offen.
