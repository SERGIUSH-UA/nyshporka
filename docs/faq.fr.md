# Questions fréquentes

## Scans et espace disque

### Faut-il télécharger tous les scans sur l'ordinateur ?

Oui. Pour lire un feuillet, le modèle le découpe en lignes et parcourt chacune
d'elles — ce sont des dizaines d'accès au fichier pour une seule page ; on ne lit
pas ainsi « à la volée » depuis le site d'une archive.

### Si je supprime ensuite les scans, les informations seront-elles effacées ?

Pas toutes. **Restent** le texte lu, le suivi de ce qui a été examiné, les
trouvailles et les notes : ils se trouvent dans le répertoire de travail de
Nyshporka, et non dans le répertoire des scans, et la recherche dans le texte
continue de fonctionner. **Disparaissent** les extraits et la possibilité de
regarder un candidat à l'œil ou de relire le dossier avec un autre modèle.

Avant de libérer de la place, menez donc le dossier à son terme. Moins coûteux :
déplacer le répertoire sur un disque externe et le signaler à l'assistant
(`nysh roots add "E:\скани"`) : le dossier ne disparaîtra pas des listes.

### Combien de place faut-il ?

L'application avec les modèles de lecture — environ 3 Go. Les scans — autant
qu'il y en a (un feuillet de registre paroissial pèse 2–8 Mo). Le texte lu —
quelques Mo par dossier.

### Les archives ont fourni un PDF, et non des pages séparées

Pour l'instant, la lecture ne prend que des images : `jpg`, `png`, `tif`,
`webp`. Il faut d'abord découper le PDF en pages avec un outil externe.
Exception : un livre imprimé avec une couche de texte (par exemple, depuis
Чтиво) — il n'a pas besoin de modèle, le texte est déjà là.

## Archives

### Peut-on travailler avec les scans de n'importe quelles archives ?

Oui, tout de suite : les codes de toutes les archives régionales et centrales
d'Ukraine figurent déjà dans le référentiel, si bien que la cote `ДАКО 13-1-1`
est acceptée sans réglage. La seule différence est de savoir si Nyshporka sait
parcourir elle-même le catalogue des archives : des catalogues tout prêts
existent pour le ДАХмО et le ЦДІАК, et les visionneuses ARCHIUM des autres
archives s'ajoutent en quelques lignes de configuration — demandez à
l'assistant.

### Nyshporka télécharge-t-elle des dossiers depuis FamilySearch ?

Non, et elle ne le fera pas : cela exige une session active dans le navigateur,
et le téléchargement en masse est contraire aux règles du service. À la place,
il existe un **index des microfilms** : quel village se trouve sur quelles
images de quel microfilm. Il répond à « où sont les registres paroissiaux de mon
village » sans téléchargement, mais pour l'instant il ne couvre que la Moldavie.

Si les images d'un microfilm se trouvent déjà sur votre disque, on peut les
prendre en compte comme un dossier :
`nysh case <тека> --shifra "<архів фонд-опис-справа>" --dgs <номер
групи зображень>`. Le numéro sera inscrit dans le passeport comme source des
scans.

## Lecture

### Faut-il une carte graphique ?

Non. La lecture dépend du processeur : environ **2 minutes par page** sur un
ordinateur portable ordinaire, contre ~20 secondes avec une carte graphique. Un
gros dossier peut être lu sur une [machine louée](cloud.md).

### Comment lire plusieurs dossiers d'affilée sans rester à côté ?

Les mettre en file d'attente : `nysh queue add <справи>`, puis `nysh queue run`.
La file traite les dossiers l'un après l'autre ; si l'un d'eux ne peut pas
avancer (cote manquante, source qui ne fournit pas les images), il attend votre
décision, et la file passe au suivant. `nysh queue` montre où en est chaque
dossier et combien il en reste. Pour arrêter après le dossier en cours :
`nysh queue stop` ; après un arrêt ou un ordinateur éteint, `nysh queue run`
reprend au même endroit.

### Le texte sort avec des erreurs — c'est une panne ?

Non, c'est la limite de la technologie sur ce type de matériau. Sur la cursive
des XVIIIe–XIXe siècles, la machine confond un quart à un tiers des lettres :
« Franciszka Lubkowskiego » devient « Francisrha Lubhoustrio90 ». Le texte sert à
**chercher** — la recherche est approximative et trouve un nom estropié —, et ce
qu'on a trouvé, on le regarde sur le scan.

### Pourquoi deux modèles pour le cyrillique ?

Diak lit les mêmes lignes que Pysar, mais se trompe **autrement** : il s'en tient
davantage aux traits eux-mêmes là où Pysar substitue un mot vraisemblable.
Ensemble, ils trouvent plus que chacun séparément.

### Nyshporka lit-elle les registres polonais, le latin, le XXe siècle ?

Les modèles sont entraînés sur la cursive des XVIIIe–XIXe siècles d'archives
ukrainiennes, moldaves et polonaises. L'écriture latine (notariat, registres
catholiques) est lue par Skryba. Sur une écriture que le modèle n'a pas vue, les
erreurs sont plus nombreuses — chez Skryba, sur des mains inconnues, une lettre
sur cinq. Pour chercher un nom de famille, cela suffit le plus souvent ; pour
une citation littérale, non : il vaut donc la peine de vérifier à l'œil le
premier dossier d'un nouveau type de matériau. Affiner le modèle sur votre
écriture — [c'est possible](train.md).

## Assistant

### Peut-on se passer d'assistant ?

Pour les choses simples, oui : dans l'application du navigateur, on peut
consulter les ouvrages de référence, le texte lu et ce qui a été trouvé. Mais
pour aller de « où chercher » à « voici votre ancêtre », Nyshporka est conçue
pour travailler avec un assistant : il fait des dizaines d'étapes qui, à la
main, prendraient des jours.

### Que fait l'assistant, et que fait Nyshporka ?

La lecture du manuscrit et la recherche, c'est Nyshporka qui les fait sur votre
ordinateur — cela ne coûte rien, seulement du temps. L'assistant décide de la
suite, lance les étapes et explique le résultat. La seule chose qu'il « lit des
yeux » lui-même, c'est le **dépouillement des actes en champs** (dates, noms,
rôles) : environ 84 mille tokens par scan, soit, pour un registre de deux cents
feuillets, des millions de tokens — et il faut deux passages.

## Argent et confidentialité

### Combien ça coûte ?

Nyshporka — rien, elle est libre (AGPL-3.0). Vous ne payez que l'assistant (son
abonnement) et, si vous le souhaitez, la location d'une machine pour la lecture
— le coût est affiché **avant** la location.

### Mes scans sont-ils envoyés quelque part ?

Non. Il n'y a pas de télémétrie, et aucun compte n'est nécessaire pour
travailler. Les scans, le texte lu et les notes se trouvent dans un répertoire
sur votre disque. Nyshporka ne va sur le réseau que quand vous le lui demandez :
recherche dans les catalogues, téléchargement d'un dossier, installation des
modèles, mise à jour. La liste complète —
[politique de confidentialité](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

On ne peut partager ce qui a été lu dans [Supriaha](share.md) qu'après s'être
connecté (`nysh share login`) et uniquement avec votre accord : ce qui part,
c'est le texte lu par la machine et la description du dossier. Les scans et les
notes n'y vont jamais. Consulter la banque avant chaque lecture et verser
automatiquement ce qui a été lu — ces deux modes sont désactivés par défaut,
c'est vous qui les activez (`nysh share setup`).

### Peut-on transférer une recherche sur un autre ordinateur ?

Oui : le répertoire de travail est un répertoire ordinaire, on peut le copier en
entier. La description de chaque dossier se trouve dans le répertoire du dossier
lui-même : elle voyage avec lui, y compris chez un collègue.

## Mise à jour et suppression

### Comment mettre à jour ?

Demandez à l'assistant ou lancez `nysh update --check` — la commande dira s'il
existe une version plus récente et avec quelle ligne mettre à jour sur votre
machine précisément. Sous Windows, le plus simple est de télécharger le nouvel
installateur et de le lancer par-dessus : la recherche, les modèles et les
ouvrages de référence restent en place. Nyshporka ne signale pas d'elle-même
les nouvelles versions : c'est ce que promet la politique de confidentialité.

### Comment désinstaller Nyshporka ?

`nysh uninstall` montre ce qui sera supprimé, `nysh uninstall --yes --all`
supprime tout, modèles compris. Sous Windows, on peut aussi la désinstaller
comme un programme ordinaire — « Programmes et fonctionnalités ». **Le
répertoire de travail avec votre recherche n'est jamais supprimé.**

## Quand la recherche n'a rien trouvé { #nichogo-ne-znaishlos }

Un résultat vide est la réponse la plus lourde de conséquences en généalogie,
car « rien » ferme une piste pour longtemps. Avant d'y croire, posez-vous (ou
posez à l'assistant) quatre questions :

1. **Le texte est-il lisible ?** Regardez le dossier dans la visionneuse. Si ce
   n'est que du bruit, le zéro concerne la qualité de la lecture, et non la
   présence du nom.
2. **Combien de feuillets ont réellement été examinés ?** « Rien trouvé dans 180
   feuillets sur 300 » et « rien trouvé » sont deux réponses différentes.
3. **La recherche trouve-t-elle ce qui est sûrement là ?** Cherchez un nom que
   vous avez déjà vu de vos yeux sur le scan. S'il n'est pas trouvé, le problème
   vient de la recherche.
4. **A-t-on cherché dans les bonnes sources ?** Demandez à l'assistant le plan :
   quelles sources ont été passées en revue, combien chacune a examiné et
   laquelle vient ensuite.

L'assistant connaît encore deux contournements : chercher la famille par les
**prénoms et patronymes**, que le modèle estropie moins qu'un long nom de
famille, et l'**auto-vérification** — la recherche voit-elle les feuillets où
vous avez déjà relevé le nom vous-même.

## Ce qui manque encore { #chogo-shche-nemaie }

Honnêtement, sans rien passer sous silence :

* **Les scans, c'est vous qui les apportez** — il n'y a pas et il n'y aura pas
  de téléchargeur depuis FamilySearch.
* **Le dépouillement des actes en champs est fait par l'assistant, à vos
  frais.** Nyshporka prépare le feuillet et vérifie l'exhaustivité, mais ne
  dépouille pas elle-même les actes : un service payant intégré dépenserait
  votre argent sans votre accord.
* **Le type de page** (acte paroissial, couverture, index) est déterminé par une
  personne ou par l'assistant — Nyshporka ne le reconnaît pas elle-même.
* **Rien ne peut parfois sauver un feuillet délavé** — ni le zoom, ni une
  nouvelle lecture. Cette partie du dossier est alors rephotographiée ou
  acceptée incomplète.
* **Les modèles de lecture sont bons sur le matériau sur lequel ils ont
  appris** ; sur un autre, un mauvais texte a l'air aussi sûr de lui qu'un bon.
* **Il n'y a pas d'inventaires pour tous les fonds** — seulement là où
  l'inventaire est publié sur des sites que Nyshporka sait lire.
* **L'index des microfilms ne couvre que la Moldavie.**

Les détails techniques des limites — dans la [référence des fonctionnalités](agents/features.md#mezhi-chogo-shche-nemaie).

## Si quelque chose ne va pas

| ce que vous voyez | que faire |
|---|---|
| « commande `nysh` introuvable » | Fermer et rouvrir l'assistant (Claude — complètement, par l'icône près de l'horloge) ou la fenêtre du terminal |
| « Windows a protégé votre ordinateur » | « Informations complémentaires » → « Exécuter quand même ». Pour vérifier le fichier — avec le `.sha256` de la [version publiée](https://github.com/SERGIUSH-UA/nyshporka/releases/latest) |
| l'installateur s'est terminé avec « code 1 » | Regardez les dernières lignes de la sortie : le plus souvent un téléchargement interrompu, un manque de place ou un antivirus. En détail — [installation](install.md#yakshcho-shchos-ne-tak) |
| la fenêtre de l'application est vide | Une fenêtre vide indique toujours ce qui manque. Le plus souvent, le dossier n'est pas encore enregistré ou le catalogue n'est pas collecté — demandez à l'assistant |
| la moitié des fenêtres manque | Des parties de l'application se désactivent : ⚙ → « Частини застосунку » (Parties de l'application). L'ensemble `catalog` n'a pas la lecture des manuscrits |
