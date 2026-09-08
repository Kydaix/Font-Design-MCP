# Mise en œuvre de l’audit — 0.2.0

Travail effectué sur le projet local à partir de [l’audit du 8 septembre 2026](audit.md).
Le remplacement préexistant de `docs/AUDIT.md` par `docs/audit.md` est conservé ; l’audit fourni n’est pas réécrit.

## Changements et preuves

| Sujet | Mise en œuvre | Vérification |
|---|---|---|
| Instrumentation | Durées par phase, compteurs de compilations/hits, I/O contrôlées, attentes de verrous, octets JSON et allocations Python | `scripts/benchmark.py`, trois profils et trois répétitions ; JSON des mesures conservé |
| Cache partagé | Clé source/révision/date/politique/versions/plateforme ; TTF et WOFF2 validés ; publication atomique | Une compilation pour rendu → validation → export ; zéro compilation supplémentaire sur hit |
| Intégrité et quota | Hashes des fichiers réutilisés, source revérifiée, reconstruction après corruption, 128 Mo de cache par projet | Corruptions TTF et WOFF2 testées ; source modifiée refusée ; exports conservés après purge |
| Chargement | Hash et inspection XML fusionnés ; GLIF parsé une fois par le contrôle ; vérification séparée de la matérialisation | Une seule matérialisation par transaction ; deux validations globales, état lu puis état final |
| Transactions | `font_edit`, jusqu’à 128 glyphes et 512 opérations, espacement final, références de composants dans le lot | Rollback intégral, révision obsolète, composant déclaré avant sa base, cycle et profondeur excessive |
| Verrous et annulation | Calcul hors verrou de modification ; un compilateur par workspace ; file d’attente de calcul séparée des lectures/écritures | Mise à jour pendant compilation ; deux processus dédupliqués ; enfant annulé et récolté |
| Historique | Pagination de manifestes sans objet UFO ; total exact explicite | Une page de deux entrées ne lit que trois manifestes ; aucune matérialisation |
| Réponses | Résumés par défaut, diagnostics bornés, détails explicites | JSON texte et sortie structurée concordants ; rapports complets lisibles |
| Ressources | URI de PNG, fontes et rapports, avec empreinte ; `resources/read` et ResourceLink | Lecture effective et refus d’une image modifiée ; mode inline préservé |
| Dessin | `stroke_path`, `filled_path`, rectangle/ellipse, duplication, accents par ancres ; extraction du moteur de Miette | Grammaire numérique/tailles bornées ; coordonnées et commandes interdites refusées ; Miette reconstruite |
| Optimisations locales | Index de points par lot, mémo de graphe limité à une validation, dessin de texte réutilisé entre tailles | Tests de géométrie, contreformes, cycles et profondeur maintenus |
| Contrats MCP | Catalogue préconstruit, suppression des annotations `title`, erreurs Pydantic limitées à cinq | Schémas exportés par un vrai `tools/list` ; contraintes conservées |
| Installation | `--version`, workspace utilisateur, priorité CLI/env/défaut, `config`, `doctor --build` | Diagnostic, compilation et chemins avec espaces/accents |
| Distribution | Wheel/sdist, smoke test hors dépôt, MCPB à liste de fichiers stricte, CI multiplateforme, release OIDC, `server.json` | Wheel et MCPB installés réellement hors dépôt ; manifeste MCPB et schéma officiel du registre validés |
| SDK | Migration vers MCP 2.2.0, handlers explicites et champs Python snake_case | Protocole 2026-07-28 et véritable client SDK 1.30 isolé testés |

Les historiques restent immuables, les mutations conservent `expected_revision`, les snapshots sont
synchronisés et HEAD reste publié par remplacement atomique. Les liens, hooks UFO et ressources XML
externes restent interdits. Aucun import de document SVG, fonte système ou code utilisateur n’a été ajouté.

## Résultats locaux

Sous Windows / CPython 3.11.16 : **36 tests réussis en 19,14 secondes** avec
`uv run --frozen pytest -q`. Ruff et la vérification du lock passent.

Le wheel installé dans un environnement temporaire extérieur au dépôt passe le diagnostic TTF/WOFF2
et la démonstration complète par STDIO. Le MCPB extrait dans un autre dossier temporaire passe son vrai
lancement UV, son diagnostic et une création/export via le protocole 2026-07-28. Le lancement MCPB utilise
`--no-editable`, car le test a détecté une incompatibilité des chemins `.pth` accentués sous Python 3.11/Windows.

Miette reconstruite dans `test-output/audit-miette` passe le vérificateur des binaires : **114 glyphes,
107 caractères encodés, 84 lettres**, crénage hérité des accents, contreformes et accord TTF/WOFF2.
Ses dessins sont transmis en un lot `font_edit`. Les binaires d’exemple déjà suivis dans Git restent les archives livrées.

### Mesures de volume

Mesures reproductibles de [measure_static.py](../scripts/measure_static.py), également consignées dans
[audit-output-sizes.json](audit-output-sizes.json). Les chiffres portent sur du JSON UTF-8 compact,
hors images et enveloppe MCP, **pas sur des tokens de modèle**.

| Objet identique, représentation différente | Détaillé / avec annotations | Compact |
|---|---:|---:|
| Catalogue actuel des 14 outils | 49 200 octets avec titres | 41 355 octets sans titres |
| Opération de dessin d’un A | 2 111 octets de points développés | 106 octets en `stroke_path` |
| Métadonnées de rendu de texte Miette | 4 177 octets | 735 octets |
| Données de validation Miette | 11 076 octets | 368 octets |

Le catalogue actuel est plus volumineux que les 30 235 octets de l’ancienne version : il expose désormais
le lot et les nouvelles opérations. Le retrait des titres réduit **ce nouveau catalogue**, mais ne suffit
pas à annuler cet ajout de fonctions. Aucune économie globale de contexte ou de facturation n’est revendiquée.

### Mesures de travail et de temps

[audit-measurements.json](audit-measurements.json) contient les échantillons, médianes/p95, empreinte du code
mesuré et horodatage pour une petite fonte, Miette et une fonte synthétique de **502 glyphes / 48 008 points**.
La première obtention du catalogue dans un nouveau processus est mesurée séparément des opérations métier.

| Profil | Rendu froid, médiane | Rendu chaud, médiane | Lot de plusieurs glyphes, médiane |
|---|---:|---:|---:|
| Petite fonte (8 glyphes) | 0,593 s | 0,166 s | 0,099 s |
| Miette (114 glyphes) | 1,706 s | 0,770 s | 0,977 s |
| Synthétique (502 glyphes) | 8,019 s | 4,053 s | 6,441 s |

Le lot porte sur cinq glyphes pour la petite fonte et vingt pour les deux autres profils.

Les assertions du banc imposent, pour chacun des trois profils et chacune des trois répétitions :

- une compilation pour la nouvelle clé utilisée par `render_text` ;
- aucune nouvelle compilation pour le rendu répété, la validation et l’export ;
- une seule matérialisation UFO pour le déplacement unitaire et pour le lot ;
- un relevé distinct des rendus froids et chauds, comparaisons et pages d’historique.

« Froid » signifie une clé de compilation absente, sans prétendre vider les caches de l’OS. Les temps
incluent le coût de `tracemalloc` ; le pic mémoire concerne les allocations Python, pas le RSS des moteurs
natifs ou de fontmake. Les durées de phases peuvent se recouvrir. Avec trois répétitions, le p95 de rang
le plus proche est le maximum observé. Ce banc n’est pas une comparaison chronométrée avec l’ancien commit.

## Migration pour les clients

La version passe à **0.2.0** car les valeurs de détail par défaut changent.
Pour conserver les anciennes données, demander `detail="full"` pour inspection, lecture/édition de glyphe,
rendu ou validation, et `include_total=true` pour l’historique. Les outils unitaires restent disponibles.
Les ressources ne sont pas lues automatiquement par tous les hôtes ; l’image inline reste le défaut.
Les IDs de points générés doivent être relus après modification topologique ou changement de moteur.

Voir [TOOLS.md](TOOLS.md) pour l’ordre du lot, les limites, la grammaire des chemins et la conservation
des éléments lors d’un remplacement ; [DISTRIBUTION.md](DISTRIBUTION.md) pour le lancement et la livraison.

## Étapes externes et pistes volontairement différées

- **Publication réelle** : configurer l’identité PyPI/GitHub, puis créer le tag de release et publier le
  manifeste au registre. Les fichiers et workflows sont préparés ; aucune publication ni aucun push n’a été effectué.
- **Hôtes graphiques et autres OS** : valider installation, choix de workspace, mise à jour et désinstallation
  dans les applications annoncées compatibles. La CI contient la matrice Windows/macOS/Linux ; seuls les résultats
  locaux Windows sont présentés comme exécutés ici.
- **Idempotence `operation_id`, stockage en deltas, binaire figé** : propositions futures de l’audit, non ajoutées.
  Les lots amortissent déjà les snapshots et `expected_revision` prévient les écritures perdues.
- **Caches de Font mutable, géométrie entre requêtes et graphe inverse persistant** : non introduits ; les gains
  locaux utilisent uniquement des objets privés à une opération et préservent la validation globale.
- **Équité stricte entre processus** : attentes bornées et annulation coopérative, mais les verrous OS ne
  garantissent pas un ordre FIFO global ; le limiteur AnyIO assure l’ordre au sein d’un serveur.
- **Tokens réels et RSS natif** : nécessitent une instrumentation de l’hôte/modèle et des moteurs. Les octets JSON
  et allocations Python mesurés ne les remplacent pas.
