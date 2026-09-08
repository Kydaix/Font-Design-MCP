# Architecture et garanties — 0.2.0

Un processus Python, aucune architecture de plugins ni service web requis.

```text
Client MCP (décisions créatives)
  -> SDK officiel STDIO / server.py (schémas, limites transport, images, erreurs)
  -> service.py (cas d'usage, explicitation des révisions)
       -> models.py + domain.py + drawing.py (Pydantic, UFO, primitives numériques, validation)
       -> storage.py (verrou OS, snapshots UFO, chaîne de hashes, HEAD atomique)
       -> build.py (cache vérifié, fontmake isolé, fontTools TTF/WOFF2)
       -> render.py (HarfBuzz sur le TTF ; FreeType/Pillow PNG)
```

Le domaine n'importe pas MCP. Les modèles publics ne sont pas une seconde base de données : ils valident
les opérations et sérialisent une lecture. Le fichier UFO est la source typographique d'autorité, avec
Unicode, contours, composants, ancres, groupes/paires et métadonnées standard. Le manifeste JSON version 1
stocke uniquement brief, journal, provenance, révision et contrôle d'intégrité.

## Transaction

1. Valider les paramètres et IDs. Deux travailleurs ordinaires et un travailleur de calcul par processus.
2. Obtenir le verrou OS du projet, attente maximale 5 secondes.
3. Vérifier HEAD, la chaîne des manifestes, le hash UFO et les fichiers internes avant lecture.
4. Charger un objet UFO complet en mémoire ; vérifier `expected_revision`.
5. Appliquer tout le lot en mémoire, puis valider le **projet entier**, y compris les glyphes dépendants.
6. Écrire `revisions/.stage-<uuid>/source.ufo` et un manifeste, puis synchroniser les fichiers.
7. Recontrôler l'état source, renommer l'étape en révision définitive.
8. Écrire un HEAD temporaire, puis le remplacer atomiquement. C'est le point de commit.

Chaque restauration suit ce protocole et crée un nouvel UUID de révision. Aucun ancien snapshot n'est
réécrit. Une opération topologique renvoie `removed_ids`, `added_ids` et `touched_ids` avec `detail="full"`. Une modification
de point ou de poignée conserve l'ID. Les remplacements complets sont explicites : `replace_glyph`,
`duplicate` ou `compose_accent` ; les primitives peuvent remplacer les contours avec `replace=true`.

Une interruption avant HEAD laisse l'ancien état actif. Une interruption après HEAD laisse le nouveau
snapshot complet. Les étapes temporaires et révisions orphelines sont ignorées parce que l'historique suit
uniquement les parents de HEAD. Les tests interrompent réellement un processus pendant l'écriture d'un
UFO et injectent aussi des erreurs aux deux renommages. Il n'y a pas de déverrouillage manuel dangereux
des locks : filelock utilise les primitives OS, libérées à la mort du processus.

Pas de purge automatique des révisions ou exports : l'utilisateur peut archiver le projet entier. Après arrêt de tous les processus
et sauvegarde, les dossiers `.stage-*` peuvent être retirés manuellement s'ils ne contiennent aucun résultat
à diagnostiquer. Les révisions historiques ne doivent pas être effacées individuellement car cela romprait
la chaîne des parents. Une politique de compaction sera un ajout explicite, avec migration du format.

Les hashes détectent des changements accidentels externes, pas une falsification par un attaquant capable
de réécrire tout le workspace et HEAD. Les contrôles de chemins refusent les liens/jonctions lors des accès,
mais ne remplacent pas une isolation OS contre les courses de remplacement par un processus hostile.
Les garanties ciblent un workspace local privé et des interruptions de processus ; ni réseau partagé,
ni modifications simultanées hors serveur, ni coupure électrique ne sont déclarés testés.

## Compilation

Le service capture la révision sous verrou projet puis libère ce verrou avant compilation/rendu.
Un cache par projet conserve TTF et WOFF2 sous une clé SHA-256 comprenant source, révision, date,
politique du compilateur, versions installées, Python et plateforme. Le premier accès compile le TTF
et convertit WOFF2 ; les deux formats sont validés et publiés ensemble par renommage atomique.
Le cache est plafonné à 128 Mo par projet, avec réserve de 32 Mo pour une construction ; les anciennes
entrées et étapes abandonnées sont supprimables. Les exports demandés via `font_build` sont copiés dans
`artifacts/` et conservés indépendamment de cette purge. Les snapshots ne partagent pas de hard links.

Un verrou de cache déduplique les demandes entre processus. Un verrou de compilation au niveau workspace
limite les compilateurs actifs à un. Attente maximale 150 secondes, contrôlée toutes les 50 ms pour
l'annulation ; l'ordre FIFO est assuré par le limiteur AnyIO à l'intérieur d'un serveur, pas garanti par
les verrous OS entre serveurs. Une annulation interrompt et récolte le sous-processus avant de libérer
le verrou. Les écritures restent protégées jusqu'à leur commit et ne sont pas abandonnées en cours de publication.

Sur un hit, empreintes et fontes binaires sont revérifiées, ainsi que les sources engagées. Une corruption
du cache entraîne une reconstruction, jamais celle des sources. Des octets privés de TTF sont retournés
au rendu avant libération du verrou de cache : une éviction ne peut supprimer son entrée en cours de lecture.
Les images et rapports utilisent des URI immuables à empreinte vérifiée, résolues par `resources/read`.

Une copie privée d'UFO est construite depuis l'objet validé de la révision. Le compilateur ne reçoit ni
argument de shell ni chemin fourni par le client. Les hooks de lib UFO, features brutes et ressources
externes sont refusés avant chargement/compilation. Le sous-processus est fermé à stdin ; stdout et stderr
sont capturés dans un log de l'étape. Un échec/time-out ne publie aucun artefact réussi.

`SOURCE_DATE_EPOCH` est fixé à la date de la révision et `PYTHONHASHSEED=0` dans le sous-processus, sans
modifier l'environnement global du serveur. Le WOFF2 conserve les horodatages du TTF. Deux builds identiques
sont comparés dans les tests ; la reproductibilité binaire entre plateformes différentes n'est pas revendiquée.
Le manifeste d'artefact indique les versions fontmake/fontTools/ufo2ft/ufoLib2, formats, tables, hashes et révision.

Le budget du compilateur est 60 secondes et 1 Mo de log. La taille des entrées est contrôlée ; un flux de
logs excessif est arrêté lors du prochain contrôle (50 ms), donc la limite est un seuil de terminaison,
pas une réservation disque imposée par le noyau. Il n'y a pas de sous-processus de commande utilisateur.

## Rendu et validation

`Store.verify` vérifie manifestes et empreinte sans construire d'objet UFO ; `Store.load` matérialise une
fonte une seule fois. Lecture contrôlée, hash et inspection XML sont fusionnés au chargement ; les GLIF
ne sont parsés qu'une fois par le contrôle XML. Les deux contrôles de source entourant la préparation du
commit restent actifs, ainsi que `fsync`, validation globale et remplacement atomique de HEAD.

`font_edit` applique les glyphes dans l'ordre puis l'espacement, avec une seule publication. Les validations
de graphe utilisent un mémo local à la validation ; aucun objet Font mutable ni résultat de validation ne
traverse les transactions. Les déplacements de points réutilisent un index local, invalidé après les
changements topologiques. Le dessin FreeType d'un texte est réutilisé pour toutes ses tailles.

Le catalogue des outils est construit au démarrage et ses annotations `title` redondantes sont retirées,
en préservant les propriétés métier et toutes les contraintes. Les réponses résumées n'incluent pas les
positions ni le build détaillé ; les preuves complètes restent disponibles. La duplication JSON texte/
`structuredContent` est conservée pour les clients anciens. Le serveur utilise MCP SDK 2.2.0.

`FONT_DESIGN_MCP_PROFILE=1` active sur stderr les compteurs et durées par phase, sans texte ni géométrie
de requête. Le [banc de mesure](../scripts/benchmark.py) consigne médianes, p95, compilations, octets JSON,
lectures contrôlées, écritures de snapshots et pic d'allocations Python. Il ne mesure ni RSS natif ni tokens
du modèle. Les mesures froides/chaudes désignent l'état du cache de compilation, pas celui des caches OS.

`render_glyph` rasterise les contours UFO avec FreeTypePen. Les deux révisions d'une comparaison partagent
le même cadrage calculé sur leur union de bornes et métriques. Les ancres et poignées directes sont montrées.
Les points de composants appartiennent au glyphe de base et s'inspectent séparément.

`render_text` compile chaque révision, charge le TTF avec HarfBuzz, respecte IDs, avances X/Y et décalages,
puis dessine les glyphes **du binaire** avec FreeType. Les deux variantes partagent largeur, tailles, couleurs,
options de crénage et cadre vertical. Pas de mise en page de paragraphes. Tous les paramètres et moteurs
sont enregistrés avec le PNG. Les sources et binaires peuvent différer légèrement du fait de cu2qu/arrondi.

`font_validate` vérifie le domaine, les orientations/aires, les associations Unicode et la couverture,
puis compile réellement et vérifie les tables du TTF. Une erreur de lecture/intégrité renvoie une erreur
d'outil ; une erreur de compilation dans le rapport donne `valid=false` avec `errors`. Les glyphes hors
métriques sont des observations à examiner, pas des fautes esthétiques à corriger automatiquement.

## Extensions ultérieures

Les fichiers de domaine, stockage, rendu et compilation séparent déjà les responsabilités nécessaires.
L'ajout de multi-master/variable nécessitera un format de projet et une validation de compatibilité
explicites ; un import devra sécuriser/adopter les sources avec une nouvelle révision ; les adaptateurs
d'éditeurs pourront traduire vers les modèles. Aucun registre de plugins spéculatif n'est nécessaire aujourd'hui.
