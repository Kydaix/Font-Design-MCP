# Contrat des outils

Schémas exacts : [tool-schemas.json](tool-schemas.json), issus d'un vrai `tools/list` STDIO.
Les objets refusent les champs inconnus. Les nombres non finis et Unicode surrogate sont refusés.
Les IDs de projet et de révision sont des UUID hexadécimaux de 32 caractères, fournis par le serveur.
Les éléments vectoriels portent des IDs stables fournis par le client, uniques dans un glyphe.

Chaque réponse structurée contient `ok`, `summary`, `project_id`, `revision`, `changed`, `warnings`, `data`
et `error`. Une version JSON lisible se trouve aussi dans un contenu texte MCP. Les rendus ajoutent un
ou deux contenus image PNG (révision demandée d'abord, puis `compare_revision`). Les codes métier sont
dans `error.code` avec `isError=true`. Une erreur JSON-RPC de méthode/enveloppe relève du SDK.

## Paramètres communs

- Lecture : `project_id`, `revision` facultatif (la tête courante si absent).
- Mutation : `project_id`, **`expected_revision`**, `summary` facultatif ≤500 caractères.
- Pagination : `offset` (défaut 0), `limit` (défaut 50, maximum 100), `next_offset` dans la réponse.
- Les schémas n'acceptent aucun chemin d'import/export, script, URL, nom de module ou réglage de réseau.
- `detail="summary"` par défaut pour inspection, lecture/édition de glyphe, lot, validation et rendus.
  `detail="full"` restitue les détails ; `render_text` accepte aussi `detail="positions"`.
- `history_list.include_total=true` demande le total exact (parcours complet) ; il est omis sinon.
- `image_mode="inline"` par défaut pour les rendus ; `"resource"` renvoie seulement les références et métadonnées.

## Projet et journal

`project_create` exige `metadata.family`. `metadata.style` vaut `Regular` par défaut.
`metadata.copyright` et `metadata.license_text` sont facultatifs et vides par défaut.

Les nouvelles créations utilisent `fsType=0` pour l'intégration installable des exports. Un ancien projet
dont `openTypeOS2Type` est absent reçoit ce défaut lors d'un `project_update` ; une valeur explicitement
stockée est conservée. Ce réglage évite le défaut « aperçu et impression » du compilateur et ne renseigne
pas le texte de licence de la police.
`metrics` : `units_per_em=1000`, `ascender=800`, `descender=-200`, `cap_height=700`, `x_height=500`.
La contrainte est `descender ≤ 0 < x_height ≤ cap_height ≤ ascender` et UPM entre 16 et 4096.
`brief` est facultatif, maximum 4000 caractères. Le serveur retourne un nouvel ID de projet et de révision.

`project_open` prend seulement `project_id`. Il rouvre un projet **créé par ce serveur** dans le workspace.
`project_inspect` renvoie famille, style, UPM, métriques et nombre de glyphes. Avec `detail="full"`,
il ajoute source UFO relative, inventaire paginé, groupes, paires, brief et décisions. Aucun projet actif n'est mémorisé.

`project_update` prend les paramètres de mutation et des objets facultatifs `metadata`, `metrics`, `brief`,
`decision`. Les objets metadata/metrics sont complets selon leur schéma et valeurs par défaut, pas des
patches champ par champ : reprendre les valeurs que l'on souhaite conserver. UPM doit rester identique.
Un changement de métriques verticales met aussi à jour les champs hhea/OS2 correspondants.

Une `decision` contient `hypothesis` obligatoire, `variant`, `observation`, `review` parmi `unreviewed`,
`automatic`, `agent`. 128 entrées maximum ; toutes sont versionnées. Aucun statut d'approbation humaine
ne peut être fourni par un agent. Les assertions en prose ne deviennent pas une preuve d'approbation.

## Lire et éditer un glyphe

`glyph_get` ajoute `glyph_id` aux paramètres de lecture. Le résumé contient identifiant, Unicode et métriques.
`detail="full"` ajoute `advance`, `contours`, `components` et `anchors`, avec tous les IDs.
Les bornes géométriques sont `null` pour un glyphe vide.

`glyph_edit` ajoute `glyph_id`, `create=false`, `operations` (1–128 objets à union discriminée par `op`).
Mettre `create=true` uniquement pour un nouveau glyphe. Un nouveau glyphe sans `replace_glyph` a une avance
initiale de zéro (valeur UFO) ; régler l'avance avec `spacing_edit` ou le remplacement explicite.

| `op` | Champs spécifiques | Effet |
|---|---|---|
| `put_contour` | `contour: {id, points}`, `replace=false` | Ajoute un contour ; `replace=true` exige cet ID existant |
| `move_point` | `point_id`, `x`, `y` | Position absolue d'un point sur courbe ou d'une poignée |
| `transform` | `matrix: [xx,xy,yx,yy,dx,dy]`, `contour_ids` facultatif | Affine sur tout le glyphe ou contours ciblés ; avance conservée |
| `put_component` | `component: {id,base,transform}`, `replace=false` | Composant avec affine (identité par défaut) |
| `put_anchor` | `anchor: {id,name,x,y}`, `replace=false` | Ancre nommée |
| `remove` | `kind: contour/component/anchor`, `id` | Supprime explicitement l'élément |
| `set_unicodes` | `unicodes: [entiers]` | Remplace les associations Unicode du glyphe |
| `replace_glyph` | `glyph: {advance,unicodes,contours,components,anchors}` | Remplacement global explicite ; l'ancien UFO est conservé |
| `stroke_path` | `paths`, `width`, `id="outline"`, `cap="round"`, `join="round"`, `replace=false`, `advance` facultative | Développe les lignes centrales en contours et fusionne les overlaps |
| `filled_path` | `paths`, `id="outline"`, `replace=false`, `advance` facultative | Contours remplis fermés, union nonzero |
| `primitive` | `shape: rectangle/ellipse`, `x,y,width,height`, `id`, `replace`, `advance` facultative | Primitive en unités de fonte ; ellipse cubique |
| `duplicate` | `source`, `matrix` facultative | Remplace le glyphe par une copie transformée ; Unicode remis à vide, avance conservée |
| `compose_accent` | `base`, `mark`, `base_anchor="top"`, `mark_anchor="_top"` | Remplace le dessin par deux composants alignés par ancres ; garde Unicode et prend l'avance de la base |

Les chemins acceptent seulement les commandes absolues explicites `M`, `L`, `Q`, `C`, `Z` et des nombres
finis dans ±16000. Pas de document SVG, arc, commande relative ou ressource externe. Les chemins remplis
doivent se fermer avec `Z`. Limites : 32 chemins, 16000 caractères par chemin, 256 segments par chemin,
512 segments et 8192 points générés par opération ; les limites globales de fonte restent applicables.
`width` du trait est >0 et ≤2000, `cap` accepte `round/butt/square`, `join` `round/bevel/miter`
(limite de miter fixée à 4). `replace=true` remplace **tous les contours**, en conservant composants,
ancres et Unicode. Sans remplacement, les IDs doivent être nouveaux.

Les IDs générés sont `{id}_c{index}` et `{id}_c{index}_p{index}`. Le préfixe est limité à 24 caractères.
Ils sont déterministes pour le même dessin et moteur, mais leur correspondance n'est pas garantie après
un changement topologique ou de moteur : relire `glyph_get(detail="full")` avant une correction de point.

Un point est `{id,x,y,type,smooth}` : type `line` par défaut, `offcurve` pour une poignée, `curve` pour
l'arrivée d'une cubique, `qcurve` pour celle d'une quadratique. `smooth=false` par défaut. Contours fermés,
types décrivant le segment entrant. Les coordonnées absolues sont en unités de police, Y vers le haut.
Les matrices doivent être non singulières ; coefficients linéaires ±16 et translations ±16000.
Pour ajouter/supprimer un point topologique, remplacer explicitement son contour tout en réutilisant
les IDs conservés. Un simple déplacement ne demande pas de réécrire le contour.

Exemple de création d'un triangle (remplacer les deux IDs de projet/révision) :

```json
{
  "project_id": "0123456789abcdef0123456789abcdef",
  "expected_revision": "fedcba9876543210fedcba9876543210",
  "glyph_id": "triangle",
  "create": true,
  "operations": [{
    "op": "replace_glyph",
    "glyph": {
      "advance": 600,
      "unicodes": [9651],
      "contours": [{"id": "outer", "points": [
        {"id": "left", "x": 50, "y": 0},
        {"id": "apex", "x": 300, "y": 700},
        {"id": "right", "x": 550, "y": 0}
      ]}]
    }
  }]
}
```

Puis `glyph_edit` avec la **nouvelle** révision, `create=false` et :

```json
{"op": "move_point", "point_id": "apex", "x": 320, "y": 710}
```

Le résumé donne `changed` et `data.operation_count`. Avec `detail="full"`, les résultats ajoutent
`data.touched_ids`, `added_ids`, `removed_ids`. Une erreur n'applique
aucune partie du lot au projet. Les cycles de composants, y compris indirects, sont bloquants.

## Transaction multi-glyphes

`font_edit` reçoit `project_id`, `expected_revision`, `glyphs` (1–128 objets `{glyph_id, create, operations}`)
et `spacing` facultatif (opérations de `spacing_edit`). Maximum 512 opérations au total, 128 par glyphe,
et 2 Mo sur l'enveloppe STDIO. Un glyphe ne peut figurer qu'une fois dans le tableau.
Les glyphes sont traités dans l'ordre du tableau, puis l'espacement. Les références de composants peuvent
viser un glyphe créé plus loin dans le lot ; `duplicate` et `compose_accent` utilisent des bases déjà créées.
Une validation finale et un seul commit publient le lot. Pour `bearings`, une validation supplémentaire
avant l'espacement protège le parcours du nouveau graphe de composants. Toute erreur annule le lot entier.
La démonstration Miette utilise cet outil. Les retouches unitaires gardent `glyph_edit`.

Les résumés limitent les diagnostics à dix éléments, avec comptes et indication de troncature.
Les rapports de ressources et `detail="full"` conservent les listes complètes.

## Espacement et crénage

`spacing_edit` prend les paramètres de mutation et `operations` :

| `op` | Champs | Effet |
|---|---|---|
| `advance` | `glyph_id`, `value` | Avance 0–16000 ; ne déplace pas les contours |
| `bearings` | `glyph_id`, `left`, `right` | Translate le glyphe pour atteindre l'approche gauche, recalcule l'avance |
| `kern_group` | `name`, `glyphs` | Groupe `public.kern1.nom` (gauche) ou `public.kern2.nom` (droite) |
| `kern_pair` | `left`, `right`, `value` | Paire de noms de glyphes ou groupes ; valeur négative rapproche |

`kern_group.glyphs=null` supprime un groupe ; `kern_pair.value=null` supprime une paire existante.
Les groupes d'un même côté ne peuvent partager un glyphe. Retirer une référence encore utilisée échoue,
sauf si les paires correspondantes sont aussi retirées dans ce même lot. Les paires de glyphes peuvent
constituer des exceptions aux classes ; l'implémentation OpenType est celle de fontmake/ufo2ft.

## Rendu

`render_glyph` : paramètres de lecture, `glyph_id`, `compare_revision` facultatif,
`width=640`, `height=640` (128–1024), `guides=true`, `points=true`.
Guides : limite rasterisée des contours, ligne de base, ascender/descender, cap/x-height, origine et avance.
Points : carrés sur courbe, cercles de poignées, segments de contrôle, croix/nom d'ancre.
Les chiffres exacts et IDs sont dans `glyph_get` ; les images ne remplacent pas les mesures.

`render_text` : paramètres de lecture, `text` (1–256 caractères), `sizes=[32,72]` (1–4 tailles, 8–160 px),
`kern=true`, `width=1000` (128–2048), `dark=false`, `compare_revision` facultatif.
Un TTF vérifié est réutilisé pour une même clé de compilation. HarfBuzz retourne les IDs/avances/décalages enregistrés dans les
métadonnées de rendu. Le serveur ne juxtapose pas des caractères en simulant les paires. Les codes absents
du cmap sont rapportés, sans police système. Les substitutions/normalisations propres à HarfBuzz restent
celles du moteur de shaping ; la prise en charge générale de marques combinantes n'est pas annoncée.

Avec `detail="full"`, `data.images` donne pour chaque image sa révision, ID d'artefact, chemin relatif, taille, SHA-256, paramètres,
moteur et détails. `render_glyph` donne aussi cadre, échelle et origine pixel, ce qui permet des assertions
sur le remplissage. `render_text` donne `positions`, `missing_codepoints`, `advance_units` et son build TTF.
Le résumé garde dimensions, révision, chemin, URI et avertissements utiles ; `positions` et `build` sont omis.
`detail="positions"` ajoute seulement les positions. Les images sont persistées et retournées comme contenus
image MCP, maximum 2 Mo chacune, sauf demande `image_mode="resource"`.

Les URI `font-design://...?...` retournées par les outils se lisent réellement via `resources/read`.
`uri` donne l'image ; `report_uri` donne son JSON complet. La révision engagée, les identifiants,
le type de fichier et l'empreinte SHA-256 de l'URI sont vérifiés. Une ressource modifiée est refusée.
Un hôte doit lire explicitement les ressources ; une URI seule ne fait pas voir une image au modèle.

## Validation et compilation

`font_validate` : paramètres de lecture, `corpus` facultatif ≤4000 caractères.
Le résumé contient validité, erreurs, couverture, comptes par sévérité, dix premières observations
actionnables et `report_uri` vers le rapport complet. Les contours d'aire nulle et dépassements verticaux
sont des avertissements à examiner. `detail="full"` retourne toutes les `observations` et le build de contrôle.
Les absences et l'absence de licence déclarée sont des avertissements.
Le rapport ne donne pas de note artistique. Les erreurs de lecture/structure empêchant la validation
sont des erreurs d'outil ; un compilateur en échec produit un rapport `valid=false`.

`font_build` : paramètres de lecture, `formats=["ttf","woff2"]`. Les seuls formats acceptés sont ces deux-là.
Retour : `artifact_id`, révision, versions de la chaîne, tables, `files.<format>.{path,sha256,bytes}`.
`cache_hit` indique la réutilisation d'une compilation et `build_key` son identité.
Le TTF intermédiaire existe aussi quand seul WOFF2 est demandé. Le moteur conserve les overlaps et utilise
les conversions officielles ; aucun autohinting. Les sources sont vérifiées inchangées après compilation.

## Historique

`history_list` : lecture avec pagination. Avec `revision`, commence l'histoire à cette révision.
Les entrées donnent révision, parent, date, résumé, restauration éventuelle et hash source, du plus récent
au plus ancien. Elles ne répètent pas le journal complet de chaque révision.
Cette lecture certifie la chaîne des manifestes visités, pas les fichiers UFO. La pagination s'arrête
après la page et une entrée de détection du curseur suivant, sauf demande explicite du total.
`history_restore` : mutation avec `target_revision`. Crée une nouvelle tête dont le contenu est copié de
la cible et dont le parent est la tête précédente. Renvoie la nouvelle révision ; jamais un recul destructif de HEAD.

## Erreurs identifiables

`stale_revision`, `invalid_input`, `invalid_geometry`, `component_cycle`, `missing_reference`,
`capability_unavailable`, `path_denied`, `external_modification`, `duplicate_id`, `glyph_exists`,
`invalid_unicode`, `invalid_kerning`, `project_busy`, `limit_exceeded`, `invalid_history`,
`build_failed`, `build_timeout`, `unknown_tool`, `operation_failed`.

Une erreur inattendue est journalisée sur stderr avec `operation_failed` ; elle n'est jamais traduite en
faux succès. Une coupure de transport pendant une mutation impose de relire la tête au redémarrage :
le commit peut avoir précédé la coupure, même si le client n'a pas reçu sa réponse.
