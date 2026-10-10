# Nyshporka

<p align="center">
  <img alt="Nyshporka avec une loupe" src="assets/maskot-lupa.webp" width="200" height="231">
</p>

<p align="center"><em>Lit le manuscrit. Rapporte ce qu'elle a trouvé.</em></p>

**Nyshporka aide à rechercher des ancêtres dans les documents d'archives** —
registres paroissiaux, listes de confession, révisions des XVIIIe–XIXe siècles.
Mais elle ne fonctionne pas comme un programme ordinaire.

## L'assistant fait le travail, vous décidez

<p align="center">
  <img alt="Une généalogiste examine un feuillet que lui a apporté son assistant Nyshporka" src="assets/scena-pomichnyk.webp" width="420" height="382">
</p>

Un assistant comme Claude ou ChatGPT peut être autorisé à travailler sur votre
ordinateur : ouvrir des répertoires, lancer des programmes, enregistrer le
résultat — en vous demandant chaque fois votre permission. Un tel assistant
s'appelle un **agent**.

Nyshporka est faite précisément pour lui. Vous écrivez avec des mots ordinaires :
*« voici un répertoire avec les scans des registres paroissiaux de Chechelnyk — trouve tous les Kovalskyi »*.
L'assistant lit les feuillets manuscrits, cherche le nom de famille et rapporte
les lignes trouvées directement sur le scan, avec le numéro du feuillet.

**S'il s'agit de votre famille, c'est vous qui le décidez.** De même, c'est vous
qui décidez quoi commander aux archives et s'il faut partager ce qui a été lu.
L'assistant montre ; il ne tire pas de conclusions à votre place.

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
* **la capacité de lire un manuscrit** — trois modèles de lecture, entraînés sur
  des archives ukrainiennes, moldaves et polonaises : **Pysar** et **Diak**
  lisent le cyrillique, **Skryba** l'écriture latine ;
* **la mémoire** — ce qui a déjà été examiné et trouvé, pour ne pas feuilleter
  deux fois les mêmes feuillets ;
* **des règles de travail honnête** — un « rien trouvé » est toujours accompagné
  du nombre de feuillets examinés.

## Pourquoi c'est une autre approche

Un programme ordinaire sait faire exactement ce qu'on y a mis : autant de
boutons, autant de possibilités. Nyshporka donne à l'assistant des savoir-faire
séparés — trouver un dossier, lire un feuillet, trouver un nom, noter une
trouvaille —, et il les combine selon votre question précise : *« fais un
tableau de tous les mariages de ce village dans les années 1820 »*, même si
personne n'a créé de bouton pour cela. Et plus les assistants deviennent
intelligents, plus Nyshporka en sait faire — même sans mise à jour.

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

* [Installer et connecter l'assistant](install.md)
* [Comment travailler](start.md) — que demander, comment vérifier ce qui a été trouvé
* [Questions fréquentes](faq.md)
* Pour l'assistant et les développeurs — [références](agents/index.md)
