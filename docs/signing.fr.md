# Licences, signature et confidentialité

## Politique de signature du code

**Un seul artefact** est signé — l'installateur pour Windows
`nyshporka-<версія>-setup.exe` de la [page des versions publiées][rel]. La wheel et
le `sdist` sur PyPI ne sont pas signés avec Authenticode : leur intégrité est
garantie par l'index lui-même et par [Trusted Publishing][tp] via OIDC, sans jetons
de longue durée.

**Ce qui est signé et par qui.** Le fichier est construit exclusivement dans GitHub
Actions (`.github/workflows/release.yml`, job `windows-setup`), à partir d'un tag
`v*`, après les contrôles de qualité et la vérification des données privées. La
chaîne ne comporte aucune construction manuelle sur la machine de qui que ce soit.
Le projet est mené par une seule personne, si bien que les rôles d'Author, de
Reviewer et d'Approver se confondent ; chaque signature est confirmée séparément,
à la main.

**Comment vérifier vous-même :**

```powershell
(Get-AuthenticodeSignature .\nyshporka-setup.exe).Status   # Valid
```

À côté de l'installateur, la version publiée contient un `.sha256` — il permet de
vérifier le fichier téléchargé indépendamment de la signature.

> Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org)

⚠ **À ce jour, la demande a été déposée, et les versions ne sont pas encore
signées.** D'ici là, Windows affiche « Windows a protégé votre ordinateur » — c'est
attendu pour un programme encore peu téléchargé. La signature fera disparaître la
mention « Éditeur inconnu », mais l'avertissement lui-même ne disparaîtra que
lorsque la réputation se sera constituée : Microsoft a supprimé la confiance
immédiate accordée aux certificats, y compris EV.

[rel]: https://github.com/SERGIUSH-UA/nyshporka/releases
[tp]: https://docs.pypi.org/trusted-publishers/

## Confidentialité

Nyshporka est une application locale : pas de télémétrie, pas de comptes, la
recherche n'est envoyée nulle part, et l'application ne va sur le réseau que
lorsqu'on le lui demande par une commande. La liste complète des destinations et
des raisons —
[`PRIVACY.md`](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

## Licence

[AGPL-3.0-or-later](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE).

Le copyleft n'est pas ici une affaire d'humeur, mais une exigence de l'arbre des
dépendances : `Unidecode` — dépendance centrale (normalisation des noms,
`utils/text.py`) — est sous **GPL-2.0-or-later**. L'AGPL-3.0 est compatible avec
elle et plus stricte, et l'application fonctionne via le navigateur, c'est-à-dire
précisément le cas que couvre l'AGPL.

⚠ Le paquet `strhub` contient le sous-module `models/abinet` sous une licence non
commerciale de l'USTC. Nyshporka n'en utilise **que PARSeq** (Apache-2.0).

**Les poids des modèles — à part, sous [CC BY-SA 4.0](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE-MODELS.md).** Ils ne
sont pas dans le paquet, ils arrivent par une version publiée séparée, et l'AGPL ne
définit pas de « code source correspondant » pour des poids binaires — elle ne
protégerait donc rien, mais rebuterait ceux qui veulent les utiliser honnêtement.
Les conditions sont les mêmes dans l'esprit : libre, y compris commercialement,
avec attribution, et les poids affinés restent ouverts.
