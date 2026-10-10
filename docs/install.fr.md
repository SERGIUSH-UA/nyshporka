# Installer et connecter l'assistant

La voie principale se passe de toute commande : trois programmes dans le bon
ordre et une demande toute prête. Comptez 30–40 minutes, surtout du
téléchargement.

!!! note "Pourquoi pas le chat sur le site"

    Dans le chat de claude.ai ou de chatgpt.com, Nyshporka ne fonctionne pas : le
    chat répond par du texte et n'a pas accès à votre disque. Il faut un
    **programme-assistant**, qui converse comme le chat, mais exécute lui-même
    les actions sur l'ordinateur et demande la permission avant chacune.

## Ce qu'il faut

* Windows 10 ou 11, macOS ou Linux.
* Environ 5 Go d'espace libre : les modèles de lecture et tout ce qu'il leur faut — 2.5 Go.
* Un abonnement **Claude Pro ou Max** — pour Claude Desktop
  ([offres](https://claude.com/pricing)). Ou un abonnement ChatGPT — pour Codex.
  Nyshporka elle-même est gratuite : vous ne payez que l'assistant.

## Étape 1. Installer Nyshporka

Nyshporka s'installe **en premier**, l'assistant en dernier (pourquoi — à
l'étape 3).

=== "Windows"

    1. [:material-download: Téléchargez l'installateur](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe){ .md-button .md-button--primary }
       et lancez-le.
    2. Si Windows affiche **« Windows a protégé votre ordinateur »** —
       « Informations complémentaires » → « Exécuter quand même ». C'est ainsi
       que Windows accueille tout programme encore peu téléchargé.
    3. À la question « Що ставимо » (Que faut-il installer), choisissez
       **« Каталоги + читання рукопису й пошук у прочитаному »** (catalogues +
       lecture des manuscrits et recherche dans le texte lu).
    4. À la fin, laissez cochée la case « Запустити Нишпорку » (Lancer
       Nyshporka) — l'application s'ouvrira dans le navigateur. C'est votre
       ordinateur, pas un site : elle fonctionne aussi sans internet.

=== "macOS et Linux"

    Ouvrez le « Terminal », collez une ligne et appuyez sur Entrée :

    ```sh
    curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
    ```

    Quand le script a terminé, fermez la fenêtre du terminal.

## Étape 2. Git for Windows

Téléchargez [Git for Windows](https://git-scm.com/downloads/win) et installez-le
en cliquant partout sur « Next ». Sans lui, l'onglet Code de Claude Desktop ne
s'ouvre pas, et Nyshporka en a besoin pour installer les modèles de lecture. Sur
macOS, Git est généralement déjà présent.

## Étape 3. Claude Desktop

1. Téléchargez l'application :
   [Windows](https://claude.ai/api/desktop/win32/x64/setup/latest/redirect),
   [macOS](https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect).
2. Lancez-la et connectez-vous à votre compte.
3. Cliquez sur l'onglet **Code**, en haut au centre.

!!! warning "Si Claude était déjà installé sur l'ordinateur"

    Fermez-le **complètement** — clic droit sur l'icône près de l'horloge →
    « Quitter » (Quit) — puis rouvrez-le. Le programme mémorise où chercher les
    commandes au moment de son lancement : il ignore donc la Nyshporka que vous
    venez d'installer. Symptôme : l'assistant écrit que la commande `nysh` est
    introuvable.

## Étape 4. Ouvrir le répertoire de travail

Dans l'onglet Code, avant d'écrire quoi que ce soit :

1. Choisissez **Local** — l'assistant travaillera sur votre ordinateur.
2. **Select folder** → le répertoire `Документи\Нишпорка` (Documents\Nyshporka).
   L'installateur l'a créé ; c'est là que vivront les scans, le texte lu et les
   notes. Si ce répertoire n'existe pas, vos « Documents » sont synchronisés
   avec OneDrive, et Nyshporka a placé le répertoire à côté. L'application
   indiquera où exactement : **🐾 Огляд** (Aperçu) → « Перевірити цю машину »
   (Vérifier cette machine).
3. Mode d'autorisation — **Manual** : l'assistant demandera avant chaque action,
   et vous voyez exactement ce qu'il fait.

## Étape 5. Coller la demande toute prête

Copiez le texte en entier dans le champ de saisie et appuyez sur Entrée :

```text
Lis https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/AGENTS.md
et fais tout ce qu'il indique pour que Nyshporka soit prête sur cet ordinateur : vérifie
la machine, installe si besoin les moteurs de lecture et les modèles, et installe les skills pour tous
les projets. Explique-moi chaque étape avec des mots simples.
Quand tout est vert, demande-moi quel nom de famille je cherche et sous quelles graphies.
```

L'assistant lira les instructions écrites pour lui et, en demandant chaque fois
la permission :

* vérifiera la machine (`nysh doctor`) ;
* installera les modèles de lecture (`nysh htr install`, `nysh models get`) —
  c'est l'étape la plus longue, environ 2.5 Go ;
* installera les skills — des méthodes de travail toutes prêtes
  (`nysh skills install --user`) ;
* demandera quel nom de famille on cherche.

C'est prêt quand l'assistant dit que la vérification ne montre aucune ligne
rouge et demande le nom de famille. Ensuite — [« Comment travailler »](start.md).

## Autres assistants

**Codex** (OpenAI, abonnement ChatGPT) :
[l'application](https://learn.chatgpt.com/docs/quickstart) ou
[la version pour terminal](https://learn.chatgpt.com/docs/cli). Les étapes 1 et
2 sont les mêmes ; à l'étape 4, ouvrez le répertoire `Документи\Нишпорка` ; dans
la demande, au lieu de « installe les skills pour tous les projets », écrivez
« installe les skills dans le répertoire `~/.agents/skills` ».

**Claude Code dans le terminal** — une ligne et un lancement suffisent :

```powershell
nysh skills install --user   # скіли для всіх проєктів
claude
```

**Les autres** — tout assistant qui lit les skills au format `SKILL.md`
(Agent Skills), notamment OpenClaw. Pour les placer dans son répertoire :
`nysh skills install --target <тека>`.

## Si quelque chose ne va pas { #yakshcho-shchos-ne-tak }

| ce que vous voyez | que faire |
|---|---|
| l'assistant : « commande `nysh` introuvable » | Fermer complètement Claude (icône près de l'horloge → Quitter) et le rouvrir. Dans le terminal — ouvrir une nouvelle fenêtre ; si cela ne suffit pas — redémarrer l'ordinateur |
| l'onglet Code propose de changer d'offre | Il faut un abonnement Claude Pro ou Max |
| l'assistant : « l'environnement des moteurs n'est pas prêt » | Dites-lui : « installe les moteurs de lecture et les modèles » |
| l'assistant ne voit pas le répertoire des scans | Le répertoire se trouve hors du répertoire de travail ; l'assistant doit demander la permission de le prendre en compte (`nysh roots add`). Les fichiers ne sont déplacés nulle part |
| l'installateur s'est terminé avec « code 1 » | Regardez les dernières lignes de la sortie. Le plus souvent : un téléchargement interrompu, un manque de place ou un antivirus |
| autre chose | [Écrire à l'auteur](https://github.com/SERGIUSH-UA/nyshporka/issues), en ajoutant mot pour mot ce qu'a écrit l'assistant |

## Sans assistant ou avec Python

Si Python ou `uv` est déjà installé, le paquet s'installe depuis PyPI :

```bash
uv tool install "nyshporka[app,archives,htr]"   # або: pip install "nyshporka[app,archives,htr]"
nysh init                      # створити робочу теку
nysh doctor                    # перевірити машину
nysh serve                     # відкрити застосунок у браузері
nysh htr install               # середовище для моделей читання, разово
nysh models get                # моделі читання, ~225 МБ, разово
```

L'installateur en une ligne pour Windows sans Python — dans PowerShell :

```powershell
irm https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/windows.ps1 -OutFile "$env:TEMP\nysh-install.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\nysh-install.ps1"
```

??? note "Pour les utilisateurs avancés : ensembles, options de l'installateur, emplacement de la recherche"

    **Ensembles.** `nysh init` demande ce que vous allez utiliser ; on peut le
    changer à tout moment avec `nysh sections`, sans réinstaller.

    | ensemble | ce qu'il contient |
    |---|---|
    | `catalog` | catalogues, index géographique, inventaires des fonds — sans modèles de lecture, économise ~2.5 Go |
    | `amateur` | + lecture des manuscrits et visionneuse |
    | `researcher` (par défaut) | + recherche dans le texte lu, suivi, export |
    | `lab` | + annotation des lignes et affinage des modèles (`nysh train`) |

    **Options.** Les mêmes pour les scripts et le `.exe` :

    | ce qu'on règle | `windows.ps1` | `unix.sh` | `.exe` |
    |---|---|---|---|
    | ensemble | `-Preset catalog` | `NYSH_PRESET=catalog` | `/PRESET=catalog` |
    | composition complète du paquet | `-Source 'nyshporka[app,archives]'` | `NYSH_SOURCE=…` | — |
    | version précise | `-Version X.Y.Z` | via `NYSH_SOURCE` | intégrée au fichier |
    | répertoire d'installation | `-Home_ D:\Nysh` | — | `/DIR=D:\Nysh` |
    | sans questions | — | — | `/VERYSILENT` |
    | sans le paquet de références | `-NoCatalog` | `NYSH_NO_CATALOG=1` | — |
    | journal | — | — | `/LOG=setup.log` |
    | emplacement de la recherche | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` | `NYSHPORKA_WORKSPACE` |

    ⚠ `irm … | iex` ne fonctionne pas pour le script Windows (le fichier a un BOM
    UTF-8) — d'abord `-OutFile`, puis `-File`.

    **Machine de développeur.** L'installateur ne réinstalle rien : `uv` et son
    propre Python 3.12 vont dans le répertoire de l'application ; `pyenv`,
    `conda` et les builds pour CUDA restent tels quels. En dehors de ses propres
    répertoires, il ne fait qu'un ajout au PATH. `sh -s -- --dry-run` montre les
    changements sans rien faire, `NYSH_NO_MODIFY_PATH=1` ne touche pas au PATH.
    La liste des changements est enregistrée dans `install-trace.txt`.

    **Où se trouve la recherche.** Le répertoire de travail (dans les commandes —
    l'espace de travail) :

    ```bash
    nysh init D:/Дослідження                      # обрати місце при створенні
    export NYSHPORKA_WORKSPACE=D:/Дослідження     # закріпити для всіх команд
    nysh --workspace D:/Дослідження doctor        # разово
    ```

    Sans la variable, les commandes cherchent `nyshporka.toml` en remontant depuis
    le répertoire courant. Où l'application regarde en ce moment — `nysh doctor`,
    ligne « Робочий простір » (espace de travail).

    **Mac à processeur Intel.** L'installation est la même qu'ailleurs ;
    `nysh htr install` prend Python et torch sur conda-forge, car PyPI n'a pas
    pour lui de wheels torch plus récentes que la 2.2.2.

    **Pas besoin de carte graphique.** Sans elle, une page se lit en ~20 s – 1 min
    (selon le processeur et le nombre de lignes sur la page), avec une carte — en
    ~10–15 s. L'accélération par carte graphique est une étape à part ;
    `nysh doctor` la suggérera.
