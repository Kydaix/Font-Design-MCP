<div align="center">

# Font Design MCP

**Dessiner, inspecter, affiner et compiler des polices via MCP.**

Un serveur MCP local pour créer des polices avec un agent IA, du dessin vectoriel aux exports TTF et WOFF2.

[![CI](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml)
[![Python : 3.11–3.13](https://img.shields.io/badge/Python-3.11–3.13-3776AB)](pyproject.toml)
[![Licence : MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) · **Français**

[Démarrer](#démarrer) · [Connecter un client](#connecter-un-client) · [Documentation](#documentation) · [Signaler un problème](https://github.com/Kydaix/font-design-mcp/issues)

</div>

---

## Démarrer

La version **0.2.0** ajoute les transactions multi-glyphes, le cache TTF/WOFF2, les réponses compactes,
les primitives de dessin et les ressources MCP immuables. Voir le [suivi de l’audit](docs/AUDIT-IMPLEMENTATION.md).

Pour utiliser un wheel construit sans cloner le dépôt, remplacez le chemin ci-dessous par celui du fichier téléchargé :

```sh
uvx --python 3.13 --from /chemin/absolu/font_design_mcp-0.2.0-py3-none-any.whl font-design-mcp doctor --build
uvx --python 3.13 --from /chemin/absolu/font_design_mcp-0.2.0-py3-none-any.whl font-design-mcp config --from /chemin/absolu/font_design_mcp-0.2.0-py3-none-any.whl
```

Après publication de 0.2.0 sur PyPI : `uvx --python 3.13 font-design-mcp@0.2.0 doctor --build`.
La publication est préparée ; sa disponibilité n’est pas affirmée ici.
`config --from /chemin/absolu/paquet.whl` imprime la configuration client utilisant ce wheel ;
`config` seul cible le paquet PyPI versionné. Aucun fichier client n’est modifié.
Lancez le diagnostic avant de connecter un hôte : le premier appel UV doit télécharger les dépendances.

Priorité du workspace : `--workspace`, puis `FONT_DESIGN_MCP_WORKSPACE`, puis le dossier de données utilisateur :
`%LOCALAPPDATA%/font-design-mcp/workspace` sous Windows, `~/Library/Application Support/font-design-mcp/workspace`
sous macOS, `$XDG_DATA_HOME/font-design-mcp/workspace` (ou `~/.local/share/...`) sous Linux.
Ce dossier reste indépendant du cache UV et survit aux mises à jour et à la suppression de l’extension.

L’[extension MCPB](mcpb/manifest.json) vise les hôtes prenant en charge le runtime UV du manifeste 0.4.
Voir la [distribution et publication](docs/DISTRIBUTION.md) pour la construction et les limites des tests d’hôtes.

### Développement depuis les sources

1. Clonez le dépôt et installez les dépendances avec les commandes ci-dessous.
2. Lancez le diagnostic et la démonstration pour générer votre premier spécimen.
3. [Connectez votre client MCP](#connecter-un-client) pour commencer à créer avec un agent.

**Prérequis :** Python 3.11–3.13, uv et un compte GitHub disposant de l'accès à ce dépôt.
Les commandes fonctionnent dans PowerShell et les shells POSIX. L'installation se fait depuis les sources ;
cette version n'est pas publiée sur PyPI.

```sh
git clone https://github.com/Kydaix/font-design-mcp.git
cd font-design-mcp
uv sync --frozen --python 3.11
uv run --frozen font-design-mcp doctor
uv run --frozen python examples/demo.py --workspace ./workspace
```

`doctor` vérifie les dépendances et rasterise un PNG ; `doctor --build` compile aussi TTF et WOFF2. Les opérations typographiques sont locales
après installation ; le serveur ne nécessite ni clé API de modèle ni éditeur propriétaire.
L'agent client peut utiliser un modèle distant.

La démonstration lance un vrai serveur STDIO avec le SDK Python MCP officiel. Elle dessine **A, V, O, Q, acute
et Á**, règle le crénage AV à −80 unités, déplace l'apex de A, compare les révisions, valide et compile les deux
formats d'export. Chaque exécution crée un nouveau projet et affiche le chemin de **`specimen.html`**.
Ouvrez ce fichier directement dans un navigateur.

| Sortie de la démonstration | Contenu |
|---|---|
| `specimen.html` | Aperçus en lecture seule et liens vers les polices générées ; aucun serveur web requis |
| `demo-calls.json` | Appels MCP et résultats structurés |
| `demo-report.json` | Références du projet, de la révision, des sources, des exports et de la validation |
| `revisions/` et `artifacts/` | Instantanés UFO, PNG, TTF/WOFF2, paramètres et hashes |

Les espaces de travail générés restent locaux et sont ignorés par Git.

## Miette : une police ronde en exemple

**Miette Regular** est une police originale, douce et arrondie, avec **84 lettres** : majuscules,
minuscules, accents français et æ/œ/Æ/Œ. La ponctuation et les espaces portent le total à 107 caractères
encodés. Ses dessins, composants accentués, réglages de crénage et recette de création MCP sont fournis.

[![Miette, une police ronde originale créée avec Font Design MCP](examples/miette/preview.png)](examples/miette/README.md)

[Télécharger la TTF](examples/miette/Miette-Regular.ttf) · [Télécharger la WOFF2](examples/miette/Miette-Regular.woff2) · [Spécimen et reproduction](examples/miette/README.md)

Ouvrez `examples/miette/specimen.html` localement pour saisir votre texte, régler sa taille et comparer
le crénage. Cette première graisse Regular se concentre sur les lettres françaises ; les chiffres et
les autres styles ne sont pas inclus.

## Connecter un client

Le client MCP lance le processus serveur. Indiquez un **chemin absolu vers l'interpréteur** et un **chemin
absolu vers l'espace de travail** dans sa configuration :

```json
{
  "mcpServers": {
    "font-design": {
      "command": "/absolute/path/font-design-mcp/.venv/bin/python",
      "args": ["-m", "font_design_mcp", "serve", "--workspace", "/absolute/path/font-workspace"]
    }
  }
}
```

Sous Windows, utilisez `C:/path/font-design-mcp/.venv/Scripts/python.exe` pour `command` et un chemin absolu
Windows pour l'espace de travail. L'utilisateur fixe ce dossier au lancement ; aucun appel d'outil ne peut l'élargir.

<details>
<summary>Configuration Codex CLI</summary>

Ajoutez un bloc de ce type à votre configuration Codex, en adaptant les deux chemins :

```toml
[mcp_servers.font_design]
command = "/absolute/path/font-design-mcp/.venv/bin/python"
args = ["-m", "font_design_mcp", "serve", "--workspace", "/absolute/path/font-workspace"]
startup_timeout_sec = 20
tool_timeout_sec = 180
```

Ce format suit la [documentation MCP officielle de Codex](https://developers.openai.com/codex/mcp/).
Les chemins propres à l'installation de l'[exemple Windows](examples/codex.toml) doivent être adaptés.
Le client SDK est testé de bout en bout. Miette a aussi permis de vérifier une connexion MCP depuis Codex
sous Windows : création de projet, inspection, réception des aperçus et exports de police.

</details>

<details>
<summary>Lancer directement le serveur</summary>

Windows / PowerShell :

```powershell
.\.venv\Scripts\font-design-mcp.exe serve --workspace "$PWD\workspace"
```

macOS / Linux :

```sh
.venv/bin/font-design-mcp serve --workspace "$PWD/workspace"
```

Le processus attend les messages MCP sur stdin. Stdout est réservé à JSON-RPC : aucune bannière de démarrage
n'est affichée. Les logs vont vers stderr ou les journaux capturés du compilateur. L'exécutable installé évite
la résolution des dépendances au démarrage. En usage normal, laissez le client lancer le processus.

</details>

**L'accès aux images dépend du client.** Les outils de rendu retournent de véritables blocs image MCP, ainsi
que les chemins persistants, dimensions, hashes et révisions. Le client doit transmettre ces images à un
modèle capable de les exploiter.

## Créer une police

L'agent client prend les décisions créatives ; le serveur applique des opérations validées et conserve un historique des révisions.

| Étape | Ce que vous pouvez faire |
| --- | --- |
| **Dessiner** | Partir d'un brief et de quelques glyphes structurants. Créer segments, courbes cubiques et quadratiques, contreformes, composants et ancres. |
| **Prévisualiser et affiner** | Inspecter les PNG avec repères et poignées. Déplacer les points par identifiant stable et comparer les révisions aux mêmes tailles. |
| **Espacer et créner** | Stabiliser les proportions, régler les approches, puis le crénage. Tester des mots avec et sans crénage avant d'étendre l'alphabet. |
| **Valider et exporter** | Vérifier géométrie, couverture et compilation. Produire les TTF et WOFF2 depuis une révision figée. |

Conservez les hypothèses et corrections observées dans le journal de décisions du projet.

<details>
<summary>Exemple : déplacer un point et comparer les révisions</summary>

Chaque appel identifie son projet. Les éditions de sources exigent `expected_revision` ; les requêtes
périmées échouent au lieu d'écraser une autre modification. Les points et poignées ont des identifiants
stables : une correction peut donc se limiter à cette opération :

```json
{
  "op": "move_point",
  "point_id": "Aouter_1",
  "x": 340,
  "y": 720
}
```

Placez cette opération dans `glyph_edit.operations`, avec l'ID du projet, celui du glyphe et la révision
attendue courante. Une édition réussie renvoie la nouvelle révision et les IDs modifiés. `compare_revision`
sur l'un des outils de rendu affiche deux révisions dans les mêmes conditions d'observation.

</details>

La validation technique et l'appréciation de l'agent sont distinctes d'une approbation humaine. Le serveur
n'attribue pas de note artistique et n'accepte pas qu'un agent déclare une approbation humaine authentifiée.

## Outils disponibles

Le SDK MCP officiel expose les schémas d'entrée et de sortie via `tools/list`. Les réponses contiennent des
données structurées, des résumés lisibles, les révisions, les avertissements et des erreurs identifiables.

| Outil | Fonction |
|---|---|
| `project_create` | Créer un projet avec métadonnées, métriques et brief facultatif |
| `project_open` | Rouvrir un projet créé par le serveur et vérifier son intégrité |
| `project_inspect` | Lire métadonnées, métriques, crénage et inventaire paginé des glyphes |
| `project_update` | Modifier le brief, les métadonnées prises en charge, les métriques verticales ou le journal |
| `glyph_get` | Inspecter contours, IDs, composants, ancres, avance, boîte et approches |
| `glyph_edit` | Appliquer un lot vectoriel typé et atomique à un glyphe |
| `font_edit` | Modifier jusqu'à 128 glyphes et leur espacement atomiquement dans une révision |
| `spacing_edit` | Régler avances, approches, paires et groupes de crénage |
| `render_glyph` | Rendre un glyphe avec repères, poignées et comparaison de révisions facultatifs |
| `render_text` | Compiler, composer et rendre un texte à plusieurs tailles |
| `font_validate` | Vérifier géométrie, couverture Unicode, compilation et tables OpenType |
| `font_build` | Exporter en TTF et/ou WOFF2 depuis une révision figée |
| `history_list` | Consulter les révisions commises et résumés de changements |
| `history_restore` | Restaurer un état antérieur dans une nouvelle révision |

[Schémas JSON exacts](docs/tool-schemas.json) · [Référence détaillée des outils](docs/TOOLS.md)

En 0.2.0, l'inspection, la lecture/édition de glyphes, les lots, la validation et les rendus utilisent
`detail="summary"` par défaut. Demandez `detail="full"` pour les données complètes, notamment les IDs
des points avant de les modifier ; `render_text` accepte aussi `detail="positions"`. Les images restent
incluses par défaut ; `image_mode="resource"` renvoie des références à récupérer via les ressources MCP.

## Sauvegarder et restaurer votre travail

UFO 3 est la source typographique d'autorité. Les binaires et les images sont des artefacts dérivés liés à une révision :

```text
workspace/<project_id>/
├── HEAD.json
├── revisions/<revision>/
│   ├── source.ufo/
│   └── manifest.json
└── artifacts/<artifact_id>/
    ├── font.ttf / font.woff2 / image.png
    └── artifact.json
```

Les éditions valident le projet entier, écrivent un nouvel instantané UFO complet, puis mettent à jour
atomiquement le pointeur de révision sous un verrou OS. Un lot invalide préserve l'état commis. Les hashes
détectent les changements externes ; une restauration conserve l'historique. Sauvegardez le dossier du
projet entier, de préférence serveur arrêté.

Utilisez un espace de travail local privé et modifiez les instantanés avec les outils. Le serveur contrôle
les chemins et références UFO, refuse les liens symboliques/jonctions et le XML dangereux, et n'expose aucun
outil de code arbitraire, terminal, téléchargement ou installation de paquet. Entrées, images, géométrie,
durée de compilation et logs sont bornés. Ces contrôles ne sont pas un sandbox OS contre un processus
hostile ayant les mêmes droits utilisateur, et les instantanés ne remplacent pas une sauvegarde externe.
Il n'y a ni quota disque global automatique ni purge de l'historique.

Les coordonnées sont en unités de police, ligne de base `y=0`, axe Y vers le haut. Avance, largeur visible
et approches sont des mesures différentes. UPM est fixé à la création. Les contours fermés utilisent le
remplissage non-zero ; les contreformes nécessitent une orientation opposée. Les détails sont dans les
[notes d'architecture et de récupération](docs/ARCHITECTURE.md).

## Formats pris en charge et limites

**Périmètre actuel :** polices statiques à un master, contours fermés libres, composants, ancres et crénage.
Le texte est composé par HarfBuzz depuis un TTF compilé et rasterisé avec FreeType/Pillow, sans substitution
par une police système.

**Non pris en charge dans cette version :** OTF, polices variables, plusieurs masters, import UFO/SVG
arbitraire, traçage d'image, adaptateurs d'éditeurs, collaboration réseau et éditeur graphique complet.
Ni hinting ni code de fonctions OpenType arbitraire ne sont exposés. Les aperçus de texte sont des spécimens
sur une ligne, sans mise en page de paragraphes.

**Á précomposé avec des composants est testé.** Le positionnement général des marques combinantes
(`mark`/`mkmk`) et la couverture des écritures complexes ne sont pas annoncés. La conversion de courbes peut
faire légèrement différer les aperçus de sources des contours compilés ; le rendu FreeType non hinté
ne garantit pas une identité avec le rendu natif du système.

## Compiler depuis les sources

Après les étapes de [démarrage](#démarrer), générez l'archive source et le wheel :

```sh
uv build
```

Sortie : `dist/`. Les versions des dépendances sont fixées dans `pyproject.toml` et `uv.lock` ;
`requirements.lock` fournit les dépendances avec hashes pour pip :
`pip install --require-hashes -r requirements.lock`, puis `pip install --no-deps /chemin/vers/paquet.whl`.

### Vérifications

```sh
uv run --frozen pytest -q
uv run --frozen ruff check src tests scripts examples
uv run --frozen python tests/test_acceptance.py
```

Le client d'acceptation autonome conserve ses captures et sa transcription JSON-RPC dans
`test-output/acceptance-*`. Il vérifie le crénage compilé, l'isolation des éditions, les conflits de révision,
les lots invalides atomiques, les chemins dangereux, l'échec du compilateur, le redémarrage et les écritures
interrompues.

| Vérification | Résultat |
| --- | --- |
| **Windows 11 x64, Python 3.11** | 36 tests locaux réussis, dont appels STDIO réels, éditions multi-glyphes atomiques, cache de compilation, rendu et récupération |
| **Runners Windows, macOS et Linux** | [Résultats CI](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml), avec Python 3.11 et 3.13 |
| **Wheel installé** | Commande d'entrée et démonstration MCP complète testées dans un environnement séparé |
| **Extension MCPB** | Installée hors dépôt ; diagnostic, appels STDIO et exports TTF/WOFF2 testés |

Le résultat CI couvre les environnements de ses runners, pas toutes les versions d'OS ou architectures CPU.
Le [rapport de livraison initial](docs/TESTING.md) conserve les résultats locaux antérieurs à la première CI.

## Documentation

L'anglais est la langue par défaut du [README principal](README.md). Cette version française reprend le même
parcours. Les guides détaillés restent actuellement en français, sauf l'inventaire des dépendances et les
schémas lisibles par les clients.

| Référence | Contenu |
|---|---|
| [Référence des outils](docs/TOOLS.md) | Conventions d'entrée, opérations vectorielles, espacement, résultats et erreurs |
| [Schémas JSON](docs/tool-schemas.json) | Schémas exportés depuis un appel réel à `tools/list` |
| [Architecture](docs/ARCHITECTURE.md) | Domaine, persistance, rendu, compilation, limites et récupération |
| [Rapport de tests](docs/TESTING.md) | Preuves d'acceptation initiales, captures et revue visuelle restante |
| [Licences des dépendances](docs/DEPENDENCIES.md) | Dépendances verrouillées et mentions des bibliothèques natives |
| [Audit technique](docs/audit.md) | Performances, volume des réponses et installation |
| [Mise en œuvre de l’audit](docs/AUDIT-IMPLEMENTATION.md) | Changements, mesures et vérifications de publication/hôtes restantes |

## Crédits et licence

Construit avec le SDK Python MCP officiel, les sources UFO, HarfBuzz et FreeType/Pillow.
Les mentions des bibliothèques tierces figurent dans les [licences des dépendances](docs/DEPENDENCIES.md).

Le code du serveur et les exemples originaux sont sous [licence MIT](LICENSE). **Cette licence ne s'applique
pas automatiquement aux polices que vous créez avec le serveur.** Les métadonnées de licence des polices
sont vides par défaut et restent sous le contrôle du créateur. Aucun contour ni fichier de police tiers n'est inclus.
