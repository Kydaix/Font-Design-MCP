# Du dessin à une police contrôlée

Ces ajouts facilitent la reconstruction et la mise au propre à partir de tes dessins. Ils ne constituent
pas une vectorisation automatique, une reconnaissance du style ou une garantie de qualité professionnelle.
Le modèle client doit réellement recevoir et examiner les images. Les particularités voulues du dessin
ne doivent pas être confondues avec des erreurs.

## Parcours conseillé

Définir d'abord quelques glyphes structurants, **dont des chiffres**, avec `project_create(design_spec=...)`
ou `project_update(design_spec=...)`. Ce champ remplace la spécification entière : la relire avec
`project_inspect(detail="full")` avant modification. Exemple de valeurs de travail, pas de normes universelles :

```json
{
  "required_characters": "HOnobdpq0123456789",
  "reference_glyphs": ["H", "O", "n", "o", "zero", "eight"],
  "notes": "Panses légèrement carrées, faible contraste. Vérifier à 16, 32 et 72 pixels.",
  "protected_features": "Préserver l'asymétrie du O et la forme particulière du 2.",
  "digit_spacing": "tabular",
  "stroke_probes": [
    {"id": "fut-H", "glyph_id": "H", "axis": "horizontal", "position": 200,
     "span_index": 0, "target": 80, "tolerance": 2}
  ]
}
```

Les champs descriptifs orientent l'agent : le serveur ne comprend pas automatiquement leur signification
visuelle. Les mesures doivent correspondre au dessin, avec les corrections optiques nécessaires.
`tabular` vérifie les **avances** des dix chiffres, pas leur largeur visible. `proportional` exige les
chiffres mais ne leur impose pas la même avance. Les chiffres sont identifiés par Unicode.

## Importer une référence

Déposer une image dans `inbox/` à l'intérieur du workspace configuré au lancement, puis appeler
`reference_import` avec l'ID du projet et sa révision courante :

```json
{
  "project_id": "<ID du projet>",
  "expected_revision": "<révision courante>",
  "reference_id": "O-papier",
  "glyph_id": "O",
  "source_path": "inbox/O.png",
  "image_to_font": [1, 0, 0, -1, 0, 700],
  "label": "O original, ligne de base à y=700 pixels"
}
```

La matrice transforme les pixels en unités de police :
`x_police = a*x_pixel + c*y_pixel + tx`, `y_police = b*x_pixel + d*y_pixel + ty`.
L'image a son origine en haut à gauche, Y vers le bas ; la police a sa ligne de base à Y=0, Y vers le haut.
Ici, le pixel `(10,700)` devient `(10,0)`. Utiliser des repères communs aux dessins plutôt qu'un
redimensionnement indépendant de chaque lettre. Le serveur ne corrige pas la perspective et ne segmente
pas une planche : fournir des recadrages calibrés explicitement.

L'import ne dessine pas le glyphe. Il retourne l'image au modèle, puis conserve une référence immuable.
Formats et limites : PNG non animé, 2 Mo, 2048×2048 pixels ; 64 références actives et 32 Mo cumulés
après normalisation. Liens symboliques, jonctions, liens physiques et chemins hors `inbox/` sont refusés.
Les transparences sont compositées sur blanc et les métadonnées sont supprimées. Le hash du fichier
original est conservé, mais pas ses octets complets : sauvegarder aussi les scans d'origine séparément.

`replace=true` remplace une association existante sans effacer les anciennes révisions.
`project_update(remove_reference_ids=["O-papier"])` détache une référence active sans effacer son historique.
Supprimer ensuite le fichier d'entrée ne modifie pas la référence importée.

## Reconstruire et corriger

Dessiner avec les opérations existantes, puis demander `render_glyph` avec `reference_id="O-papier"`
pour voir le contour superposé à l'original. Aucune adaptation automatique de la référence n'est appliquée.
Pour une comparaison de révisions, la même référence de la révision principale, le même cadre et la même
échelle sont utilisés des deux côtés. Il n'y a pas de score automatique de fidélité.

Lire les IDs avec `glyph_get(detail="full")`. Les nouvelles éditions évitent certains raccords cassés :

- `move_point(preserve_handles=true)` déplace le nœud et ses poignées adjacentes ensemble. Sans cette option,
  le déplacement reste brut, pour préserver la compatibilité.
- `move_handle(mode="aligned")` aligne la poignée opposée en conservant sa longueur ; `symmetric` impose
  aussi des longueurs égales. Les deux côtés doivent avoir des poignées cubiques non nulles. Les contrôles
  quadratiques ambigus et les jonctions droite/courbe nécessitent une édition explicite.
- `set_smooth` déclare l'intention d'un raccord, sans déplacer les points. Un angle volontaire doit être
  déclaré comme tel, mais ne pas désactiver ce drapeau simplement pour masquer un défaut.

`compose_accent(auto_align=true)` lie le placement de l'accent aux ancres et l'avance à celle de la base.
Les modifications ultérieures des ancres et des approches propagent les corrections dans la même
transaction. `detach_composition` permet une exception locale en conservant les composants actuels.
Le comportement historique reste le défaut (`auto_align=false`). Les ancres personnalisées ajoutées à
un composé ne sont pas automatiquement héritées ; ce mécanisme ne remplace pas le placement GPOS des
marques combinantes.

## Examiner l'ensemble avant export

`font_analyze` mesure sans compiler les tangentes des raccords déclarés lisses, la couverture, les glyphes
de référence, les cibles de métriques et les épaisseurs explicitement demandées. Les sondes horizontales
coupent à Y constant et numérotent les intervalles remplis de gauche à droite ; les verticales coupent à
X constant et les numérotent de bas en haut. Les contreformes respectent le remplissage non nul.

Choisir les sondes loin des jonctions et extrema : elles utilisent une approximation géométrique bornée,
pas une mesure optique universelle. Cette approximation ne change jamais les sources. Les limites de
calcul deviennent des diagnostics, jamais des réussites silencieuses. Le résumé montre dix observations ;
le rapport immuable contient les mesures et jusqu'à 2000 problèmes, avec le nombre exact et un indicateur
de troncature. Les rapports trop volumineux échouent explicitement.

`render_proof` compare jusqu'à 32 glyphes à **échelle commune**, y compris entre deux révisions. Les absents
sont identifiés, pas remplacés. Compléter par `render_text` sur des mots et nombres aux tailles visées,
avec et sans crénage. Stabiliser les approches avant d'accumuler les paires de crénage.

`font_validate` sépare désormais `technical_valid`, `coverage_complete` et `design.checks_passed`.
Le champ historique `valid` garde son sens technique. Le résumé de dessin porte sur le master par défaut ;
`font_analyze(master_id=...)` examine les autres. `font_build(require_design_checks=true)` exige une
couverture déclarée non vide et applique le contrat partagé à **tous les masters** avant export. Ne pas
utiliser une cible propre à une graisse comme invariant commun à toute la famille.

Une validation réussie ne certifie ni la beauté, ni la fidélité à l'image, ni toutes les interpolations.
Ne sont pas implémentés : vectorisation/reconstruction automatique des courbes, inférence du style,
recettes paramétriques persistantes, certification de continuité de courbure, espacement optique automatique
et contrôle exhaustif des axes variables. Le serveur ne revendique aucune approbation artistique ou humaine.

## Sauvegardes et versions

L'utilisation du contrat de dessin, des références ou des compositions liées produit un manifeste de
**schéma 3**. Les projets de schémas 1 et 2 restent lisibles et ne migrent pas lors d'une édition ordinaire.
Les anciens serveurs refusent le schéma 3 plutôt que de perdre silencieusement les nouvelles relations.
Une restauration remet aussi les références et le contrat de la révision choisie.

UFO reste la source des contours. Le manifeste et les images importées référencées constituent aussi des
entrées du projet : **sauvegarder tout le dossier, y compris les artefacts référencés**. Une image importée
est ancrée à la révision parente de son import, comme preuve originale, pas comme rendu de la police.
Les hashes sont vérifiés à la lecture et avant publication des superpositions. Aucune image ni instruction
UFO arbitraire n'est transmise au compilateur. Un import échoué peut laisser un artefact non référencé,
mais ne valide jamais une partie de la transaction.

Voir le [contrat technique détaillé](design-workflow.md) pour les conventions et limites complètes.
