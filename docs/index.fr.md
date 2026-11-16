# Nyshporka

<p align="center" markdown>
![Nyshporka avec une loupe](assets/maskot-lupa.webp){ width="200" height="231" }
</p>

<p align="center"><em>Lit le manuscrit. Rapporte ce qu'elle a trouvé.</em></p>

**Nyshporka est un assistant IA pour les généalogistes et pour tous ceux qui
étudient le passé à travers de vieux manuscrits.** Vous dites qui vous cherchez
et où, et l'assistant trouve les bons registres d'archives, lit le vieux
manuscrit et montre ce qu'il a trouvé directement sur le scan.

## L'assistant fait le travail, vous décidez

<p align="center" markdown>
![Une généalogiste examine un feuillet que lui a apporté son assistant Nyshporka](assets/scena-pomichnyk.webp){ width="420" height="382" }
</p>

Un assistant comme Claude ou ChatGPT peut être autorisé à travailler sur votre
ordinateur : ouvrir des répertoires, lancer des programmes, enregistrer le
résultat, en vous demandant chaque fois votre permission. Un tel assistant
s'appelle un **agent**.

Nyshporka est faite précisément pour lui. Vous écrivez avec des mots ordinaires :
*« voici un répertoire avec les scans des registres paroissiaux de Chechelnyk — trouve tous les Kovalskyi »*.
L'agent détermine lui-même dans quels registres le village peut apparaître,
récupère les scans, lit le manuscrit et montre les lignes avec le nom de
famille sur la page, avec le numéro du feuillet.

Vous regardez ces lignes et décidez vous-même s'il s'agit de vos ancêtres. De
même, c'est vous qui décidez quoi commander aux archives et s'il faut partager
ce qui a été lu. L'assistant montre ce qu'il a trouvé, les conclusions sont les
vôtres.

!!! tip "Leçons vidéo"

    [Une série de courtes leçons vidéo](https://nyshporka.online/fr/uroky) —
    de l'installation à la première trouvaille et à un arbre avec preuves, 5 à
    9 minutes chacune. La série continue. Les leçons sont en ukrainien, avec
    des sous-titres que YouTube traduit dans votre langue.

!!! tip "Voir en direct"

    Nyshporka est montrée au travail dans le stream
    [« ШІ-агенти в генеалогії: дослідження майбутнього »](https://www.youtube.com/live/VsvenHgbVZY)
    (« Agents IA en généalogie : la recherche de l'avenir », « В гостях у Качки » n° 11) —
    [la démonstration commence vers la 42e
    minute](https://www.youtube.com/live/VsvenHgbVZY?t=2550).

## Ce que Nyshporka apporte à l'assistant

À lui seul, l'assistant ne connaît pas les archives et ne sait pas lire un
manuscrit ancien. Nyshporka lui donne :

* **le savoir où se trouve quoi** — guides des archives, inventaires des fonds,
  liste des villages et des paroisses ;
* **la capacité de lire un manuscrit** — des modèles de lecture propres, entraînés sur
  des archives ukrainiennes, moldaves et polonaises : **Pysar** et **Diak**
  lisent le cyrillique, **Skryba** l'écriture latine ;
* **la mémoire** — ce qui a déjà été examiné et trouvé, pour ne pas feuilleter
  deux fois les mêmes feuillets ;
* **des règles de travail honnête** — chaque trouvaille se voit sur le scan, et
  un « rien trouvé » est toujours accompagné du nombre de feuillets examinés.

## Il n'y a pas ici de boutons tout faits

Un programme ordinaire sait faire exactement ce qu'on y a mis : autant de
boutons, autant de possibilités. Nyshporka donne à l'assistant des savoir-faire
séparés : trouver un dossier, lire un feuillet, trouver un nom, noter une
trouvaille. Il les combine selon votre question, même si personne n'a créé de
commande pour cela : *« fais un tableau de tous les mariages de ce village dans
les années 1820 »*. C'est ainsi que l'on parcourt tout le chemin : de « où
chercher » à la généalogie où chaque fait est accompagné d'un extrait du scan,
puis au site de la famille avec arbre et carte. Et plus les assistants
deviennent intelligents, plus Nyshporka en sait faire, même sans mise à jour.

## Pas seulement les ancêtres

On peut chercher non seulement un nom de famille, mais aussi le nom d'un
village, un mot ou un événement. Les mêmes registres servent donc à étudier
l'histoire d'un village ou d'une paroisse, d'une église ou d'un monastère, des
coutumes locales, la biographie d'une personne connue. Par exemple, l'histoire
de son propre village peut se lire dans les registres des tribunaux de château
du XVIIe siècle : Nyshporka retrouve dans des milliers de pages chaque mention
du village, de ses habitants et des événements, et montre chacune sur le scan.
Plus de détails : [pas seulement la généalogie](how-it-works.md#ne-lyshe-rodovid).

## Ce qu'il faut

* Un ordinateur sous Windows, macOS ou Linux et environ 5 Go d'espace libre.
* Nyshporka elle-même — gratuite, à code source ouvert.
* Un assistant capable de travailler sur l'ordinateur : **Claude Desktop**
  (abonnement Claude Pro ou Max), **Claude Code** ou **Codex** (abonnement
  ChatGPT).

Tout cela s'installe en une demi-heure, sans la moindre commande —
[**« Installer et connecter l'assistant »**](install.md). Les modèles de lecture,
l'assistant les installera lui-même : ce sont deux étapes uniques,
`nysh htr install` et `nysh models get`.

**Les scans ne partent nulle part** — tout fonctionne sur votre ordinateur. Il
n'y a ni télémétrie ni compte utilisateur.

!!! warning "État : version précoce"

    Les catalogues, la lecture des manuscrits, la recherche de noms, le suivi et
    l'application dans le navigateur fonctionnent. Ce qui manque encore est
    indiqué dans les [questions fréquentes](faq.md#chogo-shche-nemaie), sans
    rien passer sous silence.

## Les mots que vous rencontrerez ici { #slovnyk }

| mot | ce que c'est |
|---|---|
| **assistant (agent)** | un assistant IA — Claude Desktop, Claude Code ou Codex — autorisé à travailler sur votre ordinateur |
| **modèles de lecture** | Pysar, Diak et Skryba — ils transforment un feuillet manuscrit en texte |
| **texte lu** | ce que le modèle a lu sur le feuillet. Il contient des erreurs : on cherche dedans, et l'on regarde ce qu'on a trouvé sur le scan |
| **dossier** | une unité de conservation d'archives avec sa cote, p. ex. `ДАХмО 315-1-8433` ; dans Nyshporka, un répertoire de scans |
| **feuillet · image** | une page du dossier · une image (un scan) |
| **prise de vue** | l'ensemble des scans d'un dossier — les vôtres, achetés ou tirés du site d'une archive |
| **répertoire de travail** | le répertoire de Nyshporka, par défaut `Документи\Нишпорка` (Documents\Nyshporka) : c'est là que se trouve votre recherche. Dans les commandes, il s'appelle « espace de travail » |
| **application** | la fenêtre de Nyshporka dans le navigateur — pour voir ce qui a été trouvé, feuilleter les scans et le texte lu |
| **skills** | des méthodes de travail toutes prêtes pour l'assistant : comment lire un dossier, comment chercher un nom, où creuser ensuite |
| **Supriaha** | la banque commune des dossiers lus, sur [nyshporka.online/supriaha](https://nyshporka.online/supriaha) : ce qu'une personne a lu n'a pas besoin d'être relu |

## Pour aller plus loin

* [Comment ça marche](how-it-works.md) — tout le cycle, de « où chercher » au
  site de la famille, et comment un nom se retrouve dans un manuscrit (en ukrainien)
* [Installer et connecter l'assistant](install.md)
* [Comment travailler](start.md) — que demander, comment vérifier ce qui a été trouvé
* [Questions fréquentes](faq.md)
* Pour l'assistant et les développeurs — [références](agents/index.md)
