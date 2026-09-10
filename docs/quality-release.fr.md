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
mesure une instance du binaire variable compilé. Jusqu'à 64 profils peuvent être conservés. Utiliser les
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

Les projets des schémas 1, 2 et 3 restent lisibles. L'emploi des profils fait passer le contrat en version 2
et le manifeste au schéma 4 ; les anciens serveurs le refusent explicitement. Un contrat sans profils
n'ajoute pas ce champ vide aux anciens formats. Sauvegarder les sources, manifestes et artefacts de revue.

`pytest tests/test_quality.py` contient notamment le M vide, K=H, le K d'UniSlaw, une contreforme, des profils
tournés, des preuves périmées/modifiées et une livraison complète. Les tests MCP lancent un serveur STDIO
séparé ; les tests de revue utilisent des attestations de fixture identifiées comme telles.
