# Comment travailler

<p align="center">
  <img alt="Nyshporka lit un manuscrit avec une loupe" src="../assets/maskot-pratsiuie.webp" width="220" height="206">
</p>

Nyshporka est installée, l'assistant est connecté ([sinon](install.md)). Ensuite,
vous parlez à l'assistant en langage courant, et ce qui a été trouvé, vous le
regardez vous-même.

## Ce qu'on peut demander

Quelques exemples — formulez comme vous voulez :

* « Que trouve-t-on sur le village de Lypovenke ? Où sont ses registres paroissiaux et que vaut-il la peine de commander aux archives ? »
* « Voici le répertoire `D:\скани\ДАКО 13-1-1`, enregistre-le comme dossier. C'est un
  registre paroissial, 1850–1855. »
* « Lis ce dossier. » (Un registre de 300 feuillets sans carte graphique, c'est une nuit ;
  l'ordinateur ne doit pas se mettre en veille.)
* « Trouve ici les Kovalskyi et montre les lignes sur le scan. »
* « Note que j'ai examiné les feuillets 12–40 : notre famille n'y est pas. »
* « Fais un tableau de tous les mariages de ce registre dans les années 1820. »
* « Rien trouvé — où creuser ensuite ? »

L'assistant connaît lui-même la marche à suivre : il dispose pour cela de skills —
des méthodes toutes prêtes pour lire un dossier, chercher un nom, savoir où
creuser, noter ce qui a été examiné.

## Les scans, c'est vous qui les apportez

Nyshporka ne télécharge pas de dossiers depuis FamilySearch ni depuis les espaces
en ligne des archives où il faut se connecter avec son propre compte. Vous
enregistrez les pages de la visionneuse de l'archive sur votre disque, comme vous
le feriez sans elle. Les exigences pour le répertoire sont simples et strictes :

| règle | pourquoi |
|---|---|
| un répertoire = un dossier | la cote, le suivi et les trouvailles sont rattachés au répertoire |
| les images sont directement dans le répertoire | la lecture n'entre pas dans les sous-répertoires |
| `jpg`, `png`, `tif`, `webp` | les autres formats ne comptent pas comme des images |
| un PDF peut être déposé tel quel | ses pages seront d'elles-mêmes converties en images avant la lecture |

Le répertoire peut se trouver n'importe où — disque externe, bureau, réseau. Les
fichiers ne sont déplacés nulle part ; l'assistant demandera la permission de
prendre le répertoire en compte. Dans l'application, cela se fait dans la
fenêtre **📥 Нові теки** (Nouveaux répertoires) → « Описати » (Décrire) : pour un
répertoire situé hors de la recherche, une case « Показувати цю теку в переліках
там, де вона лежить » (Afficher ce répertoire dans les listes là où il se trouve)
y apparaîtra.

## Comment vérifier ce qui a été trouvé

L'assistant montre des candidats, et c'est vous qui décidez. Pour cela, il y a
l'**application dans le navigateur** — le raccourci « Нишпорка » sur le bureau ou
`nysh serve`, adresse `127.0.0.1:8788`.

* **📄 Гортач** (Visionneuse) — le scan et le texte lu côte à côte. Cliquez sur
  une ligne : vous verrez l'extrait du feuillet à partir duquel elle a été lue.
* **🔎 Пошук** (Recherche) — tous les candidats qui correspondent, chacun avec
  son extrait. La recherche utilise la même commande que l'assistant, et sous les
  résultats il est indiqué où et comment on a cherché.
* **👁 Облік** (Suivi) — ce qui a déjà été examiné à l'œil, même les feuillets
  vides.

Si l'assistant dit « trouvé », demandez l'extrait. S'il dit « rien », demandez
combien de feuillets ont été vérifiés.

## Trois règles

* **Un « rien » sans chiffre n'est pas une réponse.** La bonne formulation est :
  « 180 feuillets sur 300 examinés, aucune correspondance dans le texte lu ». Un
  faux « rien » ferme une piste de recherche pour toujours.
* **La machine trouve, vous décidez.** Le texte lu contient des erreurs — sur la
  cursive des XVIIIe–XIXe siècles, une lettre sur trois ou quatre. On cherche
  dedans, et l'on regarde ce qu'on a trouvé sur le scan. N'écartez pas un
  candidat parce que la racine du mot ne ressemble pas : le modèle estropie
  justement le milieu des noms.
* **Vérifiez les chiffres sur le scan.** La machine confond les années, les âges
  et les numéros d'actes plus souvent que les mots, et cela paraît tout aussi
  assuré.

## Les fenêtres de l'application { #vikna-zastosunku }

Chaque fenêtre répond à une seule question, et « rien » a un sens différent dans
chacune.

| fenêtre | question |
|---|---|
| 🐾 Огляд (Aperçu) | où j'en suis : ce que j'ai déjà, ce qui est lu, ce qui n'est pas terminé, la vérification de la machine |
| 🔎 Пошук (Recherche) | où, dans le texte lu, figurent mon nom, mon village ou n'importe quel mot — dans toute la bibliothèque, un fonds ou un dossier |
| 🎯 Рід (Famille) | quel nom on cherche et sous quelles graphies — c'est la seule chose que vous indiquez |
| 📥 Нові теки (Nouveaux répertoires) | ce qui, sur le disque, n'est pas encore devenu un dossier : le décrire par une cote ou le mettre de côté comme « pas un dossier » |
| 🗺 Газетир (Index géographique) | où sont les documents de mon village |
| 🔎 Каталоги (Catalogues) | ce qu'il y a dans les guides d'archives et sur les sites des archives ; le catalogue d'un site se collecte avec un bouton |
| 🏛 Описи фондів (Inventaires des fonds) | ce qui existe aux archives, même non numérisé |
| 📚 Бібліотека (Bibliothèque) | ce que j'ai sur mon disque |
| 🖋 Читання · 📜 Прогони (Lecture · Passages) | lire un dossier · avec quoi et dans quelle mesure il a été lu, ce qui reste à terminer |
| 📄 Гортач · 🔍 Розбір · 👁 Облік (Visionneuse · Examen · Suivi) | le texte lu à côté du scan · les candidats avec extraits · ce que j'ai déjà vu à l'œil |

Le guide détaillé des fenêtres — [« Carte des écrans »](agents/screens.md).

## Essayer sans vos propres scans

Dans l'application : **🐾 Огляд** (Aperçu) → « Перевірити цю машину » (Vérifier
cette machine) → « Розгорнути зразок » (Déployer l'exemple) (ou `nysh sample`).
Ce sont trois feuillets déjà lus du dossier **ДАХмО 315-1-159** (1821–1822) : on y
voit la visionneuse, les extraits et la recherche avant même que vous apportiez
vos propres scans.

## Ce que Nyshporka sait faire d'autre

* **Index géographique et ouvrages de référence** dès l'installation : le
  catalogue récapitulatif du ЦДІАК (4566 localités), le catalogue du ДАХмО,
  l'index des microfilms FamilySearch pour la Moldavie, les églises vers 1772.
* **Catalogues des sites d'archives** — ARCHIUM, « Бабин Яр », Wikimedia Commons,
  Duck Inspector, ridni.org, Чтиво, Internet Archive.
* **Dépouillement des actes en tableau** — dates, noms, rôles, condition, âge — et
  export vers Excel. C'est l'assistant lui-même qui dépouille, donc aux frais de
  votre abonnement.
* **Affiner le modèle** sur votre écriture — [en savoir plus](train.md).
* **Lire un gros dossier sur une machine louée** en une heure au lieu d'une
  semaine — [en savoir plus](cloud.md).

La liste technique complète, avec les commandes — [référence des fonctionnalités](agents/features.md).

## Mises à jour

Nyshporka ne va pas d'elle-même sur le réseau et ne signale pas les nouvelles
versions. De temps en temps, demandez à l'assistant de vérifier ou lancez
`nysh update --check`.
