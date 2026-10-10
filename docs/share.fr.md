# Partager ce qui a été lu (Supriaha)

Aujourd'hui, chacun fait reconnaître séparément le même registre d'archives. Une
lecture ne coûte pas cher, mais elle coûte **à chaque fois** : un dossier de trois
mille feuillets, ce sont des heures de calcul, et chacun de ceux qui y arrivent les
paie. Pourtant le texte est le même, et quelqu'un l'a déjà tout prêt.

Supriaha (`nyshporka.online`) est la banque commune des dossiers lus. C'est le
texte qui voyage, pas les images : un dossier de 3772 feuillets pèse
**3–4 mégaoctets** dans un paquet.

!!! note "Les images n'entrent jamais dans le paquet"
    Le paquet contient le texte de la machine et le passeport de la façon dont il a
    été obtenu. Les scans eux-mêmes restent chez celui qui les a téléchargés, et le
    paquet ne fait que nommer la source — pour que le destinataire puisse les
    obtenir au même endroit et aux mêmes conditions.

## Le chemin le plus court

```sh
nysh share login                                  # один раз: браузер, одна кнопка
nysh share setup --as "ваше імʼя"                 # один раз: профіль
nysh share pack "ДАХмО 315-1-1234"                # спакувати справу
nysh share publish data/share/outbox/DAHMO_315-1-1234.nyshtext
```

De l'autre côté :

```sh
nysh share pull "ДАХмО 315-1-1234" --take         # знайти в пулі й прийняти
nysh share pull --repo RGIA --fond 592 --opys 25 --take   # уся серія одним викликом
```

Les lectures reçues se rangent au même endroit que vos propres textes lus et
entrent aussitôt dans le stockage de texte : `nysh text find`, `grep` et `ctx` les
voient sans `text index` séparé. On peut chercher dans une série comme dans un
dossier : `nysh text find <прізвище> --case "RGIA 592-25"` ; pour plusieurs
dossiers, répétez `--case`.

!!! tip "Si vous partagez par l'intermédiaire d'un agent"
    La skill `share-case` conduit l'agent par ce même chemin et surveille les
    endroits qui cassent sans bruit : elle vérifie la cote en dry-run avant le
    versement, n'utilise pas les années du catalogue FamilySearch, et fait
    parvenir à la banque la fiche définie par `share card` en versant à nouveau.
    Elle s'installe avec les autres skills : `nysh skills install`.

## Connexion

`nysh share login` ouvre une page de nyshporka.online : se connecter par e-mail,
avec Google ou anonymement. La clé arrive d'elle-même dans Nyshporka et se range
dans le trousseau de clés du système — il n'y a rien à copier. Pour retirer la
clé de la machine : `nysh share logout`. Sur un serveur sans navigateur, la clé se
place dans la variable `NYSHPORKA_SUPRIAHA_TOKEN` ; elle est délivrée dans Mon
compte.

La banque ne permet de chercher, de prendre et de verser des paquets qu'avec une
clé. Si vous n'en avez pas encore, `pull`, `sync` et `publish` proposeront
d'eux-mêmes de vous connecter.

## Profil

`nysh share setup` sans options pose les questions une à une ; avec n'importe
quelle option, il enregistre seulement ce qui est indiqué et ne demande rien
(pour les scripts et l'installateur).

| champ | option | par défaut |
|---|---|---|
| pseudonyme au catalogue | `--as` | sans nom |
| contact (public) | `--contact`, pour le retirer — `--contact -` | aucun |
| licence du texte | `--license` | `CC0-1.0` |
| quand verser | `--consent nikoly \| pytaty \| zavzhdy` | `pytaty` — tenir une liste et le rappeler |
| consulter la banque avant une lecture | `--lookup / --no-lookup` | **non** |
| géométrie des lignes | `--geometry / --no-geometry` | oui |

!!! warning "Le contact est une donnée publique"
    Il part dans chacun de vos paquets et est visible par tous ceux qui le
    reçoivent. Il n'est jamais rempli automatiquement (ni depuis `git config`, ni
    depuis le nom d'utilisateur du système) — seulement depuis le profil que vous
    avez rempli, ou depuis `--contact`. Pour un seul paquet sans contact —
    `--contact -`.

**Consulter la banque avant une lecture** (`--lookup`) signifie : avant chaque
`nysh read`, Nyshporka envoie au serveur la cote du dossier et le nombre d'images
et, si le texte existe déjà, affiche une ligne. Le serveur voit alors quel dossier
vous vous apprêtez à lire — c'est pourquoi c'est désactivé par défaut.

## Fiche du dossier : titre, années, lieux, genre

L'empaqueteur compose la fiche lui-même — à partir du passeport du répertoire, du
relevé de l'inventaire du fonds et de la bibliothèque des dossiers. Les mentions
de travail du passeport (date de vérification entre parenthèses, « FS-тег: … »,
« ⚠ … », marques de priorité) n'entrent pas dans la fiche. Quand c'est
insuffisant — dossier sans nom, titre de travail au lieu du vrai —, c'est celui
qui verse qui définit la fiche :

```sh
nysh share card "ДАХмО 315-1-1234" --title "Сповідні розписи парафії …" \
  --years 1795-1797 --place "Слобідка" --place "Вербівка" --genre confession
```

La même chose directement à l'empaquetage : `nysh share pack … --title … --years …`.
Ce qui est défini est **mémorisé** (`data/share/cards.json`) et s'applique à chaque
empaquetage suivant de ce dossier — `pack`, `suggest --all`, le versement
automatique. Pour consulter — `nysh share card <шифра>`, pour effacer un champ —
`--title ""`, toute la fiche — `--clear`.

Genres : `birth`, `marriage`, `death`, `confession`, `revision`, `clergy_list`,
`gazette`, `finding_aid`, `other` (on peut aussi les donner par leur libellé :
« сповідні »).

**Où sont les images.** Quand un dossier a été lu à partir d'une prise de vue
privée — collection d'un chercheur, achetée ou commandée —, le destinataire ne la
trouvera ni sur FamilySearch ni sur Commons. La fiche indique qui détient les
images :

```sh
nysh share card "ДАХмО 230-1-1234" --scans "Колекція дослідника=https://…"
```

Le lien part en premier parmi les liens du paquet, avec la marque `role: scans`,
et dans la banque il figure à côté du texte : c'est là que la personne ira
chercher les images. Comme le reste de la fiche, il est mémorisé ; pour l'effacer —
`--scans ""`.

## Ce qui est lu mais pas encore versé

```sh
nysh share suggest                   # перелік зі статусами
nysh share suggest --all --ready     # спакувати все готове
nysh share suggest --skip "ДАХмО 315-1-1234" --why "платна зйомка"
```

Statuts : **prêt**, **dans la banque sans position des lignes**, **incomplet**
(moins de 80 % des images lues — versé seulement avec `--partial`), **sans
images**. Ce qui est déjà dans la banque est déterminé par l'instantané de la
banque (`nysh share sync`) ; pour les dossiers que l'instantané ne couvre pas —
par le journal des empaquetages. Un refus est mémorisé dossier par dossier : on ne
vous redemandera plus rien sur un dossier que vous avez décidé de ne pas verser.

## Ce qu'il y a dans un paquet

```
manifest.json    шифра, картка, джерело сканів, знаменник, ваші поля
frames.jsonl     перелік кадрів справи
runs/<прогін>/   NNNN.txt — сторінка, рядок у рядок; плюс паспорт прогону
README.md        пояснення для того, хто відкриє пакет без Нишпорки
```

La géométrie des lignes (`*.lines.json`) part dans un fichier **séparé**,
`….geom.nyshtext` : elle pèse ×10 le texte et n'est utile qu'à celui qui a les
mêmes images.

### Quelles lectures partent

Les voix d'un paquet sont des lectures du dossier, et non tout ce qui se trouve à
côté. Restent à la maison, et `pack` nomme chacune avec la raison :

- les lectures de mesure (marque `control_run` dans le passeport de la lecture) ;
- les essais : une lecture dont toutes les pages figurent dans une lecture plus
  complète **du même modèle** (des parties d'un dossier lues par un même modèle
  partent toutes les deux) ;
- les lectures d'un autre dossier au nom semblable ;
- les lectures reçues d'autrui — c'est leur auteur qui les verse, pas vous ;
- celles que vous nommez : `--skip-run <прогін>`.

### Le dénominateur — le champ principal

Le manifeste indique **combien d'images compte le dossier et combien ont été
lues**, avec quel modèle, et si l'orientation a été vérifiée. Sans cela, le
décodage d'autrui produit de faux zéros en masse : quelqu'un fait un grep sur trois
pages prises pour trois mille, ne trouve pas le nom — et ferme honnêtement la
piste, en ayant tout fait correctement.

C'est pourquoi un paquet avec un décodage incomplet ou sans nom de modèle ne se
construit tout simplement pas. Si vous avez lu une partie exprès, dites pourquoi :

```sh
nysh share pack "ДАХмО 315-1-1234" --partial "лише аркуші з нашим селом"
nysh share pack "ДАХмО 315-1-1234" --frames 408        # число кадрів справи, якщо пакувальник його не знайшов
```

## Vos champs

```sh
nysh share pack "ДАХмО 315-1-1234" \
  --as "sergiy" --contact "t.me/…" \
  --note "читав Дяком, останні аркуші підмокли" \
  --link "звідки скани=https://…" \
  --extra "plivka=105208823"
```

- `--note` — texte libre ; il parvient au lecteur et figure dans le README du
  paquet.
- `--link` — « libellé=adresse » ou simplement le lien ; le plus utile est celui
  qui mène aux scans. Une adresse contenant `=` (lien FamilySearch) est prise en
  entier.
- `--extra` — des paires « clé=valeur » que le format transportera intactes. Une
  paire sans `=`, avec une clé vide ou nommée deux fois — c'est un refus, et non
  une omission silencieuse.

## Ce qui n'entre pas dans le paquet

L'empaqueteur prend **seulement** les pages de texte et le passeport de la lecture
— et, du passeport, seulement les champs utiles au destinataire : modèle, moteur,
écriture, nombre de pages traitées. Ne partent pas : les chemins de votre disque,
les notes de travail (`*_note`, explications des mesures, historique des
fusions), les extraits de sauvetage, les journaux, la quarantaine, le stockage des
pages, les verdicts, le canon.

On peut voir exactement ce qui partira avant la construction :

```sh
nysh share pack "ДАХмО 315-1-1234" --dry-run
```

## Carnet du dossier

Outre le texte, on sait souvent sur un dossier autre chose, utile à quiconque
l'ouvrira : ce que contient vraiment le registre, où l'inventaire des archives
s'est trompé dans le titre ou les années, où se trouve une copie. S'y ajoute aussi
une ligne que la machine a lue de travers et que vous avez vérifiée sur le scan.
Tout cela, c'est le carnet du dossier. Il se trouve à côté des feuillets examinés
et part dans Supriaha **séparément du texte** : on peut aussi l'ajouter à un
registre versé par quelqu'un d'autre.

```sh
nysh note add "ДАХмО 315-1-1234" --kind about --text "Метрична книга Покровської церкви, 1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind catalog-error --field years --archive-says 1834 --actually "1834–1836" --share
nysh note add "ДАХмО 315-1-1234" --kind copy --other "ДАВіО 904-24-55" --text "копія в консисторії" --share
nysh note read "ДАХмО 315-1-1234" 0031 --line 153 --text "урожденная Прухницкая" --share

nysh note push "ДАХмО 315-1-1234" --dry-run   # що поїде
nysh note push "ДАХмО 315-1-1234"             # віддати
nysh note pull "ДАХмО 315-1-1234"             # що дописали інші
```

Dans Supriaha ne part que ce qui est marqué `--share`, ainsi que la liste des
feuillets examinés, sans vos commentaires. Le familial — « mon grand-père est
inscrit ici » — écrivez-le en `--kind note` : une telle entrée ne part jamais, et
la banque n'acceptera pas une entrée contenant des mots familiaux, même marquée.
Sur la page du registre, le carnet est affiché séparément du texte et n'entre pas
dans le nombre de pages lues : ce qui est vérifié à l'œil, ce sont des lignes
choisies, et non un dossier lu.

Une ligne vérifiée part dans Supriaha avec son extrait — la découpe de cette ligne
dans le scan, en JPEG gris, si le scan du dossier se trouve sur votre ordinateur
(sans lui, la ligne part seulement en texte). **En partageant des lignes
vérifiées, vous acceptez que le propriétaire de Nyshporka les utilise pour
entraîner les modèles de reconnaissance.** Les extraits ne sont pas transmis aux
autres utilisateurs et ne sont pas affichés sur la page du registre ; le texte de
la vérification est visible par tous. Une entrée retirée (`nysh note retract` puis
`note push`) retire aussi l'extrait de la banque.

## Recevoir le paquet de quelqu'un d'autre

!!! tip "Si vous passez par un agent"
    La skill `pull-case` conduit l'agent de `pull` jusqu'à la recherche dans ce
    qui a été reçu et énonce à voix haute le niveau de correspondance : ce qui,
    dans le texte d'autrui, se placera sur vos images, et ce qui ne servira qu'à
    la recherche.

```sh
nysh share inspect <файл або адреса>     # подивитись, нічого не розкладаючи
nysh share import <файл або адреса>      # прийняти
nysh share geometry <….geom.nyshtext>    # докласти рамки рядків
```

Le paquet vient d'une personne que vous ne connaissez pas, et le récepteur ne le
croit pas sur parole :

- **les contrôles mesurent le contenu, et non la déclaration** : pages, lignes et
  empreinte du texte sont calculées à partir du paquet lui-même, et un paquet qui
  déclare plus qu'il ne contient ne passe pas ;
- **un défaut du paquet entraîne un refus avant toute écriture** : un chemin hors
  de `runs/<прогін>/<файл>`, un nom interdit sous Windows, un lien, un fichier trop
  gros — et rien n'est écrit sur le disque ;
- seules les lectures nommées dans le manifeste sont déployées, et seulement le
  texte avec son passeport ; le passeport est nettoyé selon la même liste
  blanche ;
- **votre propre lecture n'est jamais écrasée** — même avec `--force`. Une lecture
  portant le même nom (sans tenir compte de la casse) — c'est un refus. `--force`
  ne remplace qu'un paquet reçu auparavant ;
- un paquet récupéré à une adresse du catalogue est vérifié avec son sha256
  (`share pull --take` le fait lui-même ; pour `import` et `geometry` par adresse —
  `--sha256`) : un fichier substitué dans le stockage après que la banque l'a
  accepté n'est pas reçu.

## Dans quelle mesure le texte d'autrui se place sur vos images

La clé du dossier ne convient pas pour cela : elle est formée à partir du nom du
répertoire et de votre référentiel d'archives, si bien que chez deux personnes le
même registre obtient des clés différentes. C'est pourquoi le paquet contient la
liste des images et l'empreinte de la prise de vue, et Nyshporka **mesure** la
correspondance et l'annonce clairement :

| niveau | ce que cela signifie | ce qui fonctionne |
|---|---|---|
| `exact` | toutes les images concordent (empreinte ou identifiant FamilySearch), ou l'empreinte de la prise de vue sur au moins trois images | tout, y compris les extraits et la géométrie d'autrui |
| `by-name` | les noms et le nombre concordent | tout, sauf la géométrie d'autrui |
| `by-position` | seul le nombre, ou une partie des images, concorde | la page oui, l'extrait est douteux |
| `text-only` | pas d'images, ou des images différentes | recherche, page, cote |

La géométrie d'autrui ne se place que sur le texte de **la même contribution** et
seulement avec `exact` ; sinon — refus avec explication (`--force`, si vous êtes
sûr de vous).

`text-only` n'est pas un échec, mais le cas d'usage le plus fréquent : vous trouvez
le nom dans le texte d'autrui, vous voyez le dossier et le numéro du feuillet — et
vous allez regarder le scan lui-même à la source.

!!! danger "Un même nom de fichier ne signifie pas la même image"
    Un staging à plat renumérote les pages : deux prises de vue d'un même registre
    donnent facilement les mêmes noms pour un contenu différent. C'est justement
    pourquoi le niveau n'est jamais relevé sur une supposition.

## Votre zéro et le zéro d'autrui sont deux réponses différentes

Les lectures reçues sont marquées, et la recherche le dit :

```
знаменник: кадрів 3772 · прочитано 3770 · у сторі прогонів 2 із 2 …
з них чужий декод: прогонів 2 із 2 · сторінок 3770 · від oksana
```

Le texte d'autrui a été lu par un autre modèle, personne ici ne répond de son
exhaustivité, et on ne peut le faire relire qu'en le demandant à celui qui l'a
donné. Un zéro obtenu sur ce texte pèse moins qu'un zéro sur le vôtre — et cela
doit se voir.

## La banque

```sh
nysh share pull                     # огляд пулу: архів · фонд · опис, справ і сторінок
nysh share pull "Слобідка"          # що є в каталозі
nysh share pull "ДАХмО 315-1-1234" --take
nysh share pull --repo RGIA --fond 592           # серія: що в ній є
nysh share pull --repo RGIA --fond 592 --take    # і прийняти всю
nysh share stats --catalog          # хто скільки вніс
nysh share sync --repo DAHMO --fond 315   # зріз для колонки «пул» у `cases fond`
```

Le catalogue est l'API `https://api.nyshporka.online/v1`. Un miroir à vous ou un
serveur de test se définit par la variable `NYSHPORKA_TOLOKA` ou l'option
`--base` ; la clé de Supriaha **ne part pas** vers une telle adresse — ni depuis le
trousseau, ni depuis `NYSHPORKA_SUPRIAHA_TOKEN`. Votre propre serveur doit être
nommé explicitement : `NYSHPORKA_SUPRIAHA_TRUST=https://хост[:порт]` — HTTPS
uniquement et correspondance exacte de l'adresse ; la clé de Supriaha part alors
vers lui. La boucle locale de cette machine (`127.0.0.1`, `localhost`) est de
toute façon considérée comme sûre.

`sync` avec `--repo`/`--fond` ajoute l'instantané d'un seul fonds à celui qui
existe ; pour les fonds que l'instantané ne couvre pas, la colonne « пул »
(banque) indique « on ne sait pas », et non « absent ».

Un refus de la banque (contrôles, quota journalier), Nyshporka l'affiche avec les
mots du serveur. Quand le même texte est déjà dans la banque, `publish` indique
s'il a été accepté, refusé autrefois ou s'il n'est pas encore terminé — « déjà
dans Supriaha » ne signifie que le premier cas.

## La trace des échanges

`data/share/journal.jsonl` garde la mémoire de ce qui est arrivé d'où et de ce qui
est parti où, et les paquets reçus restent dans `data/share/inbox`. Ce n'est pas
du suivi pour le suivi : un fait tiré du décodage d'autrui et inscrit dans le canon
doit s'appuyer sur un fichier permanent — sinon la citation reste en l'air dès que
vous supprimez le téléchargement.

```sh
nysh share list          # журнал
nysh share stats         # скільки віддано, скільки прийнято, від кого
```

## Licence

Le paquet indique à quelles conditions le texte est versé (`--license`, par défaut
`CC0-1.0`) et, à part, les conditions de la source des scans (`--source-terms`),
s'il y en a. Sans licence, le paquet ne se construit pas : le destinataire doit
savoir ce qu'il peut en faire.
