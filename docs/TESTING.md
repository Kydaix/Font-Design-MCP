# Vérification de livraison — 8 septembre 2026

## Exécuté réellement sur Windows 11 x64 / CPython 3.11.16

| Vérification | Résultat |
|---|---|
| `uv run --frozen pytest -q` | **20 tests réussis, 11,24 s** |
| `uv run --frozen ruff check src tests scripts examples` | Tous les contrôles passent |
| `uv lock --check` | Verrou cohérent, 59 packages résolus (projet/dev compris) |
| `font-design-mcp doctor` | FreeType 2.13.2, génération PNG réussie |
| `python tests/test_acceptance.py` | Scénario STDIO autonome réussi, captures/transcription conservées |
| `uv build` + contrôle des archives | Wheel/sdist construits, aucun cache, environnement ou workspace inclus |
| Wheel installé dans `.venv-wheel` | Commande d'entrée et démonstration MCP complètes réussies, hors installation éditable |
| `python examples/demo.py --workspace ./workspace` | Projet UFO, PNG avant/après, TTF, WOFF2 et page de spécimens créés |

Les tests MCP lancent le vrai serveur dans un processus distinct, initialisent le protocole avec le SDK
officiel, découvrent les 13 outils et appellent leur véritable implémentation. Un proxy de test enregistre
stdout octet pour octet et le transmet sans modifier les messages. Toutes les lignes enregistrées sont
des objets JSON-RPC ; stderr reste vide dans le scénario d'acceptation (pannes injectées comprises).
Le test de transport trop volumineux attend, séparément, une fermeture avec diagnostic stderr.

## Couverture des assertions

- Création des glyphes originaux A, V, O, Q, acute et Á ; `.notdef` et espace techniques.
- Contreforme, orientations opposées, Bézier cubiques et quadratiques ; trou de O vérifié en pixels
  sur le rendu UFO **et sur les contours du TTF réellement compilé après cu2qu**.
- Ancres et transformations affines de composants ; approche gauche/droite et avance distinguées.
- Déplacement d'un point visible dans UFO, TTF et PNG ; V reste identique dans les trois lectures pertinentes.
- Réception réelle de blocs image MCP, décodage PNG et comparaison exacte aux fichiers/hashes persistés.
- Comparaison des révisions à cadrage/tailles identiques ; spécimens multi-tailles, crénage activé/désactivé.
- Paire OV et classes A/Á–V : écarts HarfBuzz mesurés dans le TTF de **35** et **80** unités.
- WOFF2 réouvert par fontTools ; cmap/tables conservés. Deux builds d'une même révision ont les mêmes hashes.
- Absence de `?` et de U+200D : signalement et présence effective du glyphe zéro ; aucun fallback système.
- Révision obsolète ; lot partiellement valide abandonné atomiquement ; IDs topologiques explicités.
- Redémarrage du processus, réouverture, pagination, restauration comme nouvelle révision.
- Deux serveurs sur le même workspace : une seule mutation concurrente gagne ; l'autre reçoit `stale_revision`.
- Cycle indirect de composants, référence manquante, Unicode surrogate, NaN/±Inf/coordonnée excessive,
  courbe mal formée, ID dupliqué et cible ambiguë rejetés.
- Modification externe de l'UFO et d'un manifeste historique détectée.
- Sortie de répertoire via ID refusée ; jonction Windows refusée par MCP ; liens physiques et références
  internes UFO sortantes refusés par les tests unitaires ; entités XML et hooks exécutables de lib refusés.
- Échec réel de fontmake sur une entrée absente : `build_failed`, aucun succès factice.
- Enfant compilateur bloqué ou trop bavard : délai/limite de log effectivement interrompus.
- Arrêt brutal du processus pendant une écriture UFO partielle : l'ancienne tête se rouvre, et une nouvelle
  édition réussit. Erreurs injectées avant le renommage du snapshot et avant HEAD : ancien état conservé.
- Requête STDIO >2 Mo refusée avant parsing JSON.
- Tentatives `review: "human"`, format OTF et changement UPM refusées.

Les pannes sont injectées uniquement par `tests/fault_server.py`, jamais par un outil MCP ou une option
de lancement du produit. Les opérations d'acceptation passent toutes par MCP ; les accès directs UFO/TTF
du client ne servent qu'aux assertions. Les tests unitaires n'ont pas vocation à remplacer ce parcours réel.

## Artefacts conservés

- Démonstration : `workspace/751e2debe6a74dd69d7d080d6a052cbd/specimen.html`.
- Révision dessinée : `596c9d64548d49479ae6efba5326e1ef`.
- Sources : `workspace/751e2debe6a74dd69d7d080d6a052cbd/revisions/596c9d64548d49479ae6efba5326e1ef/source.ufo`.
- TTF : `workspace/751e2debe6a74dd69d7d080d6a052cbd/artifacts/0d68f92d83324b35a2b527093f3f6938/font.ttf` (1 312 octets).
- WOFF2 : même dossier, `font.woff2` (648 octets).
- Acceptation autonome : `test-output/acceptance-b979640b/report.json`, `protocol.jsonl`, `server.stderr.log`
  et le projet `3d0a3ff604e2411390de6526ba9c4a39` dans ce même dossier.
- Vérification du package : `test-output/wheel-smoke-report.json` avec le chemin du module effectivement installé.
- Six captures : [captures/](captures/) ; [provenance JSON](captures/provenance.json).

Les captures de documentation sont des copies intactes des PNG MCP, avec leur révision et hash d'origine.
Les images et fontes de test sont une fixture technique originale, pas une direction artistique approuvée.

| Capture | Ce qu'elle démontre |
|---|---|
| [glyph-before.png](captures/glyph-before.png) / [glyph-edited.png](captures/glyph-edited.png) | Apex déplacé et cadrage partagé |
| [curves-guides.png](captures/curves-guides.png) | Contreforme de O, cubiques, points et poignées |
| [accent-components.png](captures/accent-components.png) | Á construit par composants transformés |
| [text-before.png](captures/text-before.png) / [text-edited.png](captures/text-edited.png) | HarfBuzz sur TTF, tailles 24/64/120, `.notdef` |

## Revue visuelle et limites non testées

Les PNG ont été inspectés : remplissage/contreforme, poignées, repères, accent et marqueur manquant sont
visibles ; le déplacement de l'apex est observable dans les comparaisons. C'est une revue de fonctionnement
effectuée par l'agent, **pas une approbation humaine du dessin**. L'accent dépasse les métriques verticales
par défaut et apparaît comme observation technique ; aucune correction esthétique n'a été appliquée.

À faire avant diffusion d'une véritable police : revue humaine des proportions/espacements, longs corpus,
grilles de petites tailles, usages réels et rendu natif sur les plateformes destinataires. Le MVP n'est
pas hinté, n'a pas de couverture générale et ne démontre pas le positionnement `mark/mkmk` des séquences
combinantes. OTF, variable et écritures complexes ne sont pas annoncés opérationnels.

CI préparée pour Windows/macOS/Linux et Python 3.11/3.13 ; **aucun job distant n'a tourné pendant la mission**.
Aucune intégration Codex/Claude Desktop/etc. active n'a été prétendue testée : la documentation Codex et
l'aide locale ont été vérifiées, le client SDK est testé. Pas de test de panne électrique, de système de
fichiers réseau, d'ARM, de Python 3.14, ni de reproductibilité binaire entre différents OS.
