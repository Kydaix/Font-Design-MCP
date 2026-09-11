# Qualité du dessin et preuves de livraison

Le MCP distingue désormais le fichier techniquement valide, les contrôles de dessin et la revue visuelle.
Un export d'épreuve permet d'itérer ; le statut de livraison demande des preuves explicites. Une réussite
du contrat reste une revue d'agent, jamais une certification esthétique ou une approbation humaine.

## Contrôles par défaut

`font_analyze` vérifie l'encre visible après décomposition des composants, avec le remplissage non nul.
Une lettre, un chiffre, un symbole ou une marque combinante sans encre produit `empty_visible_glyph`.
Les espaces, contrôles, sélecteurs de variante et caractères invisibles attendus restent autorisés.
Les composants écrasés et les contours de directions opposées qui s'annulent sont pris en compte.

Les contours dégénérés, croisements internes et dessins équivalents entre caractères distincts apparaissent
dans `review_candidates`, avec un `finding_id` stable par master. Les doublons sont recherchés sur des
contours échantillonnés, en neutralisant translation, départ et direction globale, mais en conservant le
remplissage relatif des contreformes. Les alias Unicode canoniquement équivalents sont exclus. Cette
détection signale notamment K=H ; elle ne reconnaît pas arbitrairement l'identité des caractères.

Les contrôles géométriques utilisent une approximation à `min(0.25, UPM/4000)` unités : maximum 20 000 points
par glyphe, un million par police et deux millions d'opérations de comparaison/scan. Une limite atteinte
échoue explicitement. Les croisements tangents, segments colinéaires, interactions entre contours et
fidélité esthétique ne sont pas certifiés. Les choix intentionnels restent examinables plutôt que rejetés
en bloc. Seuls les 16 premiers croisements d'un glyphe sont détaillés ; un candidat supplémentaire signale
la limite. Les listes globales restent bornées à 2 000 entrées avec compteurs exacts.

`outline_integrity_passed` concerne les contrôles bloquants d'encre et leurs budgets. Il ne veut pas dire
que tous les candidats ont été résolus. `checks_passed` inclut également le contrat déclaré.
`design_coverage` énumère les glyphes mesurés et ceux qui nécessitent encore un contrôle structurel.
Le serveur repère automatiquement les lettres présentes parmi `HOnosaASUKMNVRWXYkmy0123456789` et les ajoute
aux références déclarées : oublier K/M/Y dans la liste manuelle ne les retire pas du contrôle de livraison.

## Mesurer les diagonales et les contreformes

Ajouter `stroke_profiles` au `design_spec` complet, en conservant ses autres champs :

```json
{
  "id": "K-jambe",
  "glyph_id": "K",
  "master_id": "semibold",
  "start": [606, 80],
  "end": [500, 200],
  "samples": 5,
  "region": "ink",
  "minimum": 120,
  "maximum": 142,
  "max_ratio": 1.10
}
```

Ces valeurs illustrent un contrôle ; adapter les coordonnées et tolérances au dessin souhaité. `start`
et `end` définissent un axe au milieu du trait. Chaque coupe lui est perpendiculaire et sélectionne la
zone contenant son centre. Les bornes sont inclusives ; `max_ratio` limite le rapport plus grande/petite
épaisseur sur le profil. Les échantillons, de 2 à 17, incluent les extrémités : choisir une région éloignée
des jonctions et terminaisons. Un centre dans le blanc pour `region="ink"` est non mesurable et échoue.

`region="counter"` mesure un blanc borné par de l'encre de part et d'autre ; le blanc extérieur ne compte
pas comme contreforme. Un profil convient à une région localement droite. Il ne suit pas automatiquement
la courbure d'un squelette complexe. La précision d'aplatissement n'est pas une garantie de précision
de largeur près d'une tangence.

`master_id` et `location` sont exclusifs. Sans portée, le profil s'applique à tous les masters ; `location`
mesure une instance du binaire variable compilé. Jusqu'à 512 profils peuvent être conservés. Utiliser les
`variation_probes` existantes pour imposer une progression de graisse entre plusieurs positions.

`render_glyph(measurements=true)` affiche les coupes actives du master et leurs valeurs : bleu quand le
profil passe, rouge quand il échoue. Les valeurs et extrémités sont conservées dans le rapport de l'image.
Les profils d'instances compilées sont disponibles dans l'analyse variable, pas superposés au master UFO.
Les outils mesurent et expliquent ; ils ne déplacent pas automatiquement les points pour satisfaire une règle.

## Passer de l'épreuve à la livraison

1. Définir les langues, caractères, usages, contrastes et références. Stabiliser les glyphes structurants,
   notamment diagonales, jonctions et chiffres, avant de composer les accents et étendre le répertoire.
2. Exécuter `font_analyze(detail="full")` sur les masters. Réparer les problèmes bloquants et examiner les
   candidats. Mesurer chaque glyphe structurel avec au moins une sonde ou un profil adapté.
3. Produire des `render_proof` par lots de 32 glyphes, sur chaque master. Examiner également les glyphes
   auxiliaires visibles. Utiliser `render_glyph(reference_id=...)` pour les références importées du master
   par défaut. L'absence d'un glyphe ne doit pas être masquée par un substitut.
4. Produire et regarder `render_text(sizes=[24,72], kern=true)` puis `kern=false`, pour chaque master
   (avec sa `location` pour une police variable). Ajouter des rendus à des positions intermédiaires des axes.
5. Enregistrer les observations après examen des images, avec `proof_review` :

```json
{
  "project_id": "<projet>",
  "revision": "<révision exacte>",
  "proof_uris": ["<report_uri d'une planche ou d'un rendu>"],
  "verdict": "accept",
  "observation": "Décrire les contours, les raccords, les contreformes et les espaces réellement examinés.",
  "resolutions": [
    {"finding_id": "<identifiant du candidat>", "reason": "Expliquer précisément pourquoi ce choix est intentionnel."}
  ]
}
```

Omettre `resolutions` s'il n'y a aucun candidat intentionnel. Un candidat ne peut être accepté que si les
glyphes qu'il concerne figurent dans les preuves de cette revue. Les problèmes bloquants ne se lèvent pas
par justification. Utiliser `verdict="revise"` pour demander des corrections, y compris sur une preuve
incomplète ; une telle revue ne satisfait pas le contrat de livraison.

6. Appeler `font_release_check(project_id=..., review_uris=[...])` avec les `report_uri` des revues. Le
   résultat indique chaque exigence manquante, les glyphes non examinés, les références sans comparaison,
   les candidats sans résolution et les mesures absentes.
7. Lorsque le résultat est satisfaisant, appeler `font_build(purpose="release", review_uris=[...])`.
   Le rapport de livraison associe les empreintes exactes TTF/WOFF2, l'analyse et les revues.

| Appel | Portée |
|---|---|
| `font_build()` | Épreuve, `release_status="not_reviewed"`, diagnostics disponibles. |
| `font_build(require_design_checks=true)` | Bloque les erreurs des contrôles par défaut et des règles déclarées ; ne vaut pas revue visuelle. |
| `font_build(purpose="release", review_uris=[...])` | Vérifie en plus toutes les exigences de revue ; échoue avec `release_not_ready` si elles restent incomplètes. |

Chaque master doit avoir une revue de ses glyphes visibles et de texte à au moins une taille ≤32 pixels
et une taille ≥48 pixels, avec et sans crénage. Chaque axe variable demande une revue de texte à une valeur
strictement intérieure à sa plage. Cela ne certifie pas l'intégralité continue de l'espace de variation.
Les références importées demandent une superposition examinée sur le master par défaut.

Les revues sont des artefacts immuables, pas de nouvelles révisions de la police. Une modification des
sources, du contrat ou des métriques rend les anciennes preuves inapplicables à la nouvelle révision.
Elles restent utilisables pour exporter l'ancienne révision explicitement demandée. Un hash d'image
incorrect, une preuve étrangère au projet ou une révision différente est refusé.
Les preuves de texte sont aussi liées au hash du TTF compilé : une sortie différente après changement
du compilateur demande de nouveaux rendus, même si la révision des sources est identique.

Une revue d'agent décrit une observation déclarée : le protocole ne peut pas prouver que le client a
affiché l'image ni que le jugement est juste. Il ne faut pas automatiser des attestations positives sans
examiner les rendus. L'espacement optique, le style et la reconnaissance générale des caractères restent
des tâches de design et de critique visuelle.

## Compatibilité et vérification

Les projets des schémas 1 à 4 restent lisibles. L'emploi des profils fait passer le contrat en version 2
et le manifeste au schéma 4. Les nouveaux contrôles régionaux, profils variables, usages, origines,
recadrages et réseaux utilisent la version 3 et le schéma 5 ; les anciens serveurs les refusent. Un contrat sans profils
n'ajoute pas ce champ vide aux anciens formats. Sauvegarder les sources, manifestes et artefacts de revue.

`pytest tests/test_quality.py` contient notamment le M vide, K=H, le K d'UniSlaw, une contreforme, des profils
tournés, des preuves périmées/modifiées et une livraison complète. Les tests MCP lancent un serveur STDIO
séparé ; les tests de revue utilisent des attestations de fixture identifiées comme telles.

## Couverture spatiale et usages réels

`design_coverage.regions` détermine la couverture par la position des mesures réussies, indépendamment du
nom choisi pour une sonde. Les modèles conventionnels K/M/N/Y/V/W/X/R/v/w/x demandent par défaut deux
échantillons distincts par région. Répéter une sonde sur la tige ne mesure pas les branches. Déclarer les
autres constructions avec `regions=[{id,glyph_id,bounds:[u0,v0,u1,v1],role,minimum_samples,master_id?}]` :
les bornes sont normalisées dans la boîte visible, les rôles sont stem/branch/junction/counter/curve/terminal.
Ces modèles latins ne prétendent pas définir l'anatomie de toutes les écritures ou variantes stylistiques.

Le rapport complet propose un `evidence_plan` : boîtes et points de départ pour les régions non couvertes,
groupes de glyphes et mots disponibles. L'agent doit placer les coupes sur les traits après inspection et
définir les cibles selon l'intention du dessin ; les cibles proposées restent nulles. Ce plan n'enregistre
aucune mesure ni acceptation. Les résumés limitent chaque liste à 12 éléments et renvoient au rapport complet.
`review_groups` regroupe les candidats par type de diagnostic afin de corriger une cause commune.

Déclarer `usage_texts` : jusqu'à 64 séquences de 2 à 80 caractères. Les épreuves acceptées doivent contenir
des glyphes façonnés adjacents et de l'encre rasterisée à chaque taille demandée. Espaces, lettre unique et
lettres séparées par des espaces ne prouvent pas l'usage en mots. Les rapports conservent glyphes, points
Unicode, paires adjacentes et tailles contenant de l'encre. Chaque combinaison master/crénage/petite ou
grande taille doit couvrir les glyphes structurants et les séquences déclarées. `HH` ne prouve pas `KAYAK`.

`variation_profiles` ajoute aux profils normaux un axe `axis_tag`, 2 à 9 `values` croissantes, une `location`
pour les autres axes, `direction`, `tolerance` et `minimum_change`. Chaque coupe est comparée sur toute la
séquence compilée pour détecter les inversions locales. Vérifier que la ligne médiane fixe atteint toujours
la bonne branche aux différentes positions. Jusqu'à 128 profils variables peuvent être déclarés.

## Construction, référence et contexte

`stroke_network` conserve jusqu'à 16 tracés centraux liés à 16 paramètres d'épaisseur. Exemple de réseau :

```json
{"parameters":{"diagonale":140},"strokes":[{"id":"branche","path":"M 100 100 L 500 600","width_parameter":"diagonale"}],"advance":800}
```

`update_stroke_network` modifie les paramètres connus, `horizontal_scale` ou `advance`. L'élargissement
déplace les lignes médianes avant de redessiner leurs contours ; l'épaisseur normale reste liée au paramètre.
Les contours des traits restent distincts avec leurs recouvrements intentionnels. Pour déplacer librement
les points ou les approches, utiliser `detach_stroke_network`. Ancres et codes Unicode restent modifiables.
Ce mécanisme ne calcule pas automatiquement les corrections optiques. Seule sa clé typée est autorisée
dans le lib du glyphe ; les entrées arbitraires ou exécutables restent interdites.

`reference_import(crop=[gauche,haut,droite,bas])` reçoit la calibration de la page entière, conserve sa PNG
normalisée et calcule celle du recadrage. La page réutilisée est dédupliquée. Les hashes de la page et du crop
sont vérifiés au chargement ; leur poids cumulé reste limité à 32 Mo par projet.
`render_glyph(reference_id=..., comparison_mode="difference")` montre les encres distinctes et leur
recouvrement. L'intersection-sur-union après seuillage est une comparaison raster, pas une note esthétique.
`glyph_origins=[{glyph_id,status,reference_ids,observation}]` distingue observed/extrapolated/original.
Une forme observée doit citer une référence importée ; la livraison d'un projet fondé sur des références
demande ce statut pour les glyphes structurants. Une petite lettre illisible ne devient pas un tracé exact.

`project_inspect(detail="full", sections=["design"], glyph_ids=["K"])` permet de cibler le contexte.
Sections : metadata/design/glyphs/spacing/compositions/history. Crénage, groupes, décisions, références et
liens de composition ont leur propre pagination. Le ciblage garde les relations d'espacement et de
composition pertinentes et liste les voisins directs. Lire le contrat complet avant de le remplacer.

## Interpolation et compatibilité

`font_analyze(interpolation=true)` combine le diagnostic de correspondance fontTools et une grille compilée
min/milieu/max de toutes les combinaisons d'axes, plus les masters. Les exports contrôlés de polices
variables l'exécutent aussi. Les incompatibilités structurelles, mauvais départs/ordres et instances vides
bloquent ces exports. Les autres observations de fontTools restent des candidats. Le processus est limité
à 45 secondes avec des budgets de travail ; une limite atteinte ne produit aucune réussite. Cette grille
finie ne certifie pas l'espace continu. [Documentation fontTools](https://fonttools.readthedocs.io/en/latest/varLib/interpolatable.html).

Le corpus `tests/test_quality.py` et `tests/test_quality_workflow.py` couvre les défauts observés et injectés.
La CI prévoit Windows/Linux/macOS ; une exécution locale Windows ne valide pas les autres plateformes.
`scripts/check_font_binary.py` conserve l'hôte, les versions, tables, façonnage et aller-retour TTF/WOFF2.
L'option `--fontbakery` exécute le profil universel s'il est installé et conserve son rapport ; son absence
est déclarée. [Utilisation officielle de FontBakery](https://fontbakery.readthedocs.io/en/latest/user/USAGE.html).

L'export variable renseigne également les valeurs STAT des masters et classe les instances par graisse,
puis par autres axes. Les coordonnées standard de graisse/largeur utilisent leurs libellés conventionnels ;
les autres valeurs reprennent le nom et la coordonnée de l'axe. Les contours et coordonnées des sources
restent identiques. Ce changement du compilateur invalide le cache et demande de nouvelles preuves de texte.
`scripts/render_browser_proof.py` produit aussi un spécimen UniSlaw avec un navigateur Chromium installé
et conserve la réussite du chargement ainsi que la version du navigateur.
