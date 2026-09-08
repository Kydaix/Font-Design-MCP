# Audit technique — Font Design MCP

**Périmètre :** performances, consommation de tokens et installation.  
**Date de l’analyse :** 8 septembre 2026.  
**Source :** archive `Font-Design-MCP-main.zip` fournie par l’utilisateur, confrontée au dépôt GitHub.  
**Commit de référence :** `4e1548b1a5d1386180ad1cdf3b35287821fa0d49` (7 septembre 2026, 23:09:40 UTC).  
**Version du projet :** `0.1.0`.

## Conclusion

Le projet n’a pas besoin d’une réécriture pour progresser nettement. Les interventions les plus prometteuses sont de **réutiliser les compilations d’une même révision**, **amortir les transactions sur plusieurs glyphes**, **éviter de reconstruire plusieurs fois le même UFO** et **réserver les résultats détaillés aux demandes explicites**.

Pour l’installation, le point d’entrée Python existe déjà. Le changement principal consiste à passer d’un parcours de développeur — clonage, environnement virtuel, chemins absolus vers cet environnement — à une distribution : paquet publié, lancement `uvx`, extension MCPB pour les hôtes compatibles et tests du paquet réellement distribué.

Les garanties d’intégrité sont un atout à préserver : historique immuable, contrôle de révision, limites de taille, défense contre les liens, compilation isolée et publication atomique. Accélérer ne doit pas signifier les désactiver.

## 1. Méthode, preuves et limites

Lecture des neuf modules de production, des schémas exportés, de la documentation, des tests, du packaging, de la CI et des exemples, notamment Miette. Les numéros de ligne ci-dessous correspondent au commit indiqué ; les chemins abrégés de modules sont relatifs à `src/font_design_mcp/`.

Les 25 fichiers Python présents dans `src`, `tests`, `scripts` et `examples` ont passé une analyse syntaxique AST. Les neuf modules de production comptent 1 705 lignes. Une vérification séparée a régénéré les 13 schémas d’entrée et le schéma de sortie avec Pydantic 2.13.4 disponible dans l’environnement : ils correspondent exactement à l’export archivé. Le projet fixe Pydantic 2.13.5 ; cette vérification n’équivaut donc pas à l’exécution dans l’environnement verrouillé.

L’installation `uv sync --frozen --python /opt/pyvenv/bin/python` a été tentée et a échoué sur la résolution DNS du serveur de téléchargement des dépendances. **Les tests fonctionnels, les temps de compilation, le démarrage et les parcours MCP n’ont pas été exécutés ici.** Cet échec d’accès réseau ne démontre pas un défaut du projet. Les résultats de tests annoncés dans sa documentation ne sont pas présentés comme des résultats personnellement reproduits.

Les mesures de volume proviennent de fichiers existants et de transformations JSON reproductibles. Ce sont des **octets UTF-8**, pas des tokens de modèle, ni une estimation de facturation. Le script `measure_static.py` et les valeurs `mesures.json` accompagnent cet audit. Aucune modification n’a été publiée dans le dépôt.

### Mesures reproductibles

| Objet | Mesure | Interprétation |
|---|---:|---|
| Catalogue des 13 outils, JSON compact | 30 235 octets | L’export indenté fait 66 230 octets ; ne pas confondre les deux. |
| Catalogue sans les annotations `title` | 25 253 octets | −16,48 % sur cet export compact, sans suppression de contraintes de validation. |
| Somme des schémas d’entrée | 17 286 octets | `glyph_edit` représente à lui seul 6 588 octets. |
| Somme des schémas de sortie | 9 100 octets | Le schéma `Result`, de 700 octets, est répété pour chaque outil. |
| Métadonnées d’un rendu de texte archivé | 2 240 octets | Image, enveloppe MCP et champ documentaire `capture` exclus. |
| Mêmes métadonnées sans `positions` ni `build` | 636 octets | −71,61 % de ces seules métadonnées. |
| Validation archivée de Miette | 10 955 octets | Résultat de données de validation, pas l’enveloppe complète. |
| Tableau des 121 observations de Miette | 10 294 octets | 93,97 % du résultat ; ces observations ne sont pas 121 erreurs. |

Les deux captures textuelles archivées donnent les mêmes tailles. Ces exemples ne suffisent pas à généraliser un pourcentage d’économie à une session IA entière. Pour le catalogue, l’injection effective dans le contexte dépend de l’hôte.

## 2. Fondations à préserver

`models.py` propose des contrats typés et des opérations discriminées plutôt qu’un exécuteur de code arbitraire. `glyph_edit` sait déjà appliquer plusieurs opérations atomiquement à un glyphe ; `spacing_edit` sait déjà travailler par lots. La séparation entre `server.py`, `service.py`, `domain.py` et les moteurs spécialisés est exploitable sans bouleversement.

`storage.py` assure des instantanés immuables, un verrou interprocessus et une publication de HEAD par remplacement atomique. `expected_revision` évite les écritures concurrentes silencieuses. Les vérifications SHA-256, XML, chemins et tailles visent des risques concrets.

`build.py` compile une copie privée, sans shell, avec une limite de temps et de journal. `server.py` émet déjà les images sous forme de `ImageContent` : le problème n’est pas une image base64 collée dans un bloc de texte. Les tests couvrent notamment les conflits de révision, l’intégrité, les chemins malveillants et des scénarios de panne ; il faut conserver ces scénarios lors des optimisations.

## 3. Performance : interventions prioritaires

### P1 — Un cache de compilation partagé par rendu, validation et export

**Constat :** `compile_font()` dans `build.py:49–126` crée un nouvel artefact, sauvegarde un UFO privé et lance `fontmake` à chaque appel. Il n’existe pas de recherche d’un résultat antérieur. La fonction est appelée par `font_validate`, `font_build` et `render_text` (`service.py:225–282`).

Le parcours Miette appelle successivement `render_text`, `font_validate` et `font_build` sur la même révision (`examples/miette/build.py:76–83`). Le chemin de code déclenche donc **trois compilations TTF**. Une compilation réutilisée permettrait d’en demander **une seule** pour cette séquence. C’est un comptage de travail évitable, pas la mesure d’une réduction de 66 % du temps total ; le rendu, les contrôles et la conversion WOFF2 restent nécessaires.

**Proposition :** conserver un TTF compilé et validé par clé de construction. Produire ensuite WOFF2 à partir de ce TTF et mettre aussi cette conversion en cache. Conserver l’isolation du compilateur.

Clé conceptuelle :

```text
build_key = hash(
  source_sha256,
  paramètres de compilation,
  identité/version de la chaîne de compilation,
  politique de timestamp,
  éléments de plateforme pertinents
)
```

Une première version plus simple peut inclure le projet et la révision. Attention : `run_compiler()` reçoit actuellement un `SOURCE_DATE_EPOCH` dérivé de `manifest.created_at` (`build.py:75`). Deux sources identiques dans deux révisions différentes ne garantissent donc pas des binaires identiques selon la politique actuelle. Une clé fondée uniquement sur le dessin serait insuffisante.

Le cache doit vérifier les artefacts réutilisés, invalider un résultat corrompu, conserver les contrôles d’intégrité de la source et empêcher deux processus de construire simultanément la même clé. Une construction ratée ne doit jamais devenir une entrée réussie. La publication du cache doit être atomique. Une politique de quota doit distinguer caches supprimables et exports conservés par l’utilisateur.

**Validation attendue :** zéro nouveau lancement de `fontmake` pour une même clé déjà validée ; une seule construction lors de deux demandes identiques concurrentes ; corruption détectée ; changement de source, d’options ou de politique de timestamp invalidant correctement la clé.

### P1 — Charger une fois plutôt que reconstruire trois fois la même source

**Constat :** une mutation ordinaire d’un projet existant, par exemple `glyph_edit`, suit ce parcours :

```text
Service.execute
  Store.load -> validate_font
  appliquer les opérations
  Store.commit
    validate_font sur le nouvel état
    Store.load sur l’ancien état -> validate_font
    sauvegarder et synchroniser l’instantané
    Store.load sur l’ancien état -> validate_font
    publier la nouvelle révision
```

Cela représente **trois `Store.load()` et quatre `validate_font()` complets**, hors validations Pydantic locales. Références : `service.py:128–169`, `storage.py:213–289`.

Un chargement relit et hache l’arbre, inspecte les fichiers UFO/XML, ouvre entièrement la fonte avec `lazy=False`, puis valide tout le modèle. Les deux relectures dans `commit()` cherchent à détecter une modification externe avant et après la préparation du nouvel instantané ; cette intention est correcte, mais reconstruire une nouvelle fonte pour la jeter n’est pas indispensable à chaque vérification.

**Proposition :** séparer trois opérations internes : vérifier l’intégrité d’un instantané, matérialiser une fonte déjà vérifiée, valider le nouvel état. Garder les contrôles prépublication et postpréparation, sans refaire inutilement les mêmes conversions XML → UFO → modèles Pydantic. Fusionner lorsque possible lecture contrôlée, hash et inspection XML. `validate_ufo_files()` analyse aussi les GLIF deux fois (`storage.py:116–120`) : mutualiser ce parsing en conservant `defusedxml` et les limites.

Un cache mémoire peut être borné par le volume et indexé par empreinte vérifiée. Il ne faut ni partager un objet `Font` mutable entre écritures, ni considérer la seule révision ou le seul `mtime` comme une preuve d’intégrité. Réutiliser le calcul ne dispense pas de vérifier que le disque correspond encore à la source engagée.

**À éviter :** supprimer `fsync`, faire confiance au nom du dossier, désactiver les validations globales, ou substituer des liens physiques aux snapshots. Les hard links sont explicitement rejetés par les protections actuelles et peuvent compromettre l’indépendance des révisions.

### P1 — Une transaction multi-glyphes

**Constat :** `GlyphEdit` porte un `glyph_id` et jusqu’à 128 opérations (`models.py:210–213`). La construction de Miette boucle sur les glyphes et crée une révision par dessin (`examples/miette/build.py:62–67`). `commit()` sauvegarde l’ensemble de la fonte à chaque fois.

**Proposition :** ajouter une opération typée `font_edit` ou `glyphs_edit` pour modifier plusieurs glyphes, leurs composants et leur espacement au sein d’une transaction. Conserver les outils actuels pour les retouches simples.

Une transaction de vingt glyphes doit nécessiter un chargement, une validation finale cohérente et une publication, plutôt que vingt de chacun. Limiter le nombre d’opérations et le volume total, garder `expected_revision`, annuler le lot entier en cas d’échec et définir l’ordre d’application. Les références entre glyphes créés dans le même lot doivent être résolues avant la validation finale.

Un futur `operation_id` pourrait identifier une transaction et son contenu afin qu’une réponse perdue puisse être récupérée sans refaire l’écriture. Une même clé avec un contenu différent doit être rejetée. Cette idempotence applicative ne remplace pas le contrôle de révision.

Le gain est double : moins de lectures et écritures, mais aussi moins d’allers-retours IA ↔ serveur et moins de répétitions du projet, de la révision et des accusés de réception.

### P2 — Raccourcir les verrous, pas simplement ajouter des threads

**Constat :** presque tout `Service.execute` est sous un verrou projet (`service.py:128–283`), y compris compilation et rendu. Le verrou expire après cinq secondes d’attente (`storage.py:171`), tandis que le serveur limite à deux opérations déportées simultanément (`server.py:46`). Une compilation et une seconde opération qui attend son verrou peuvent occuper les deux places et retarder d’autres projets.

**Proposition :** capturer et vérifier la révision immuable sous verrou, faire le calcul coûteux hors du verrou de modification, puis publier l’artefact avec le minimum de coordination nécessaire. Un rendu demandé pour une révision doit continuer à représenter cette révision même si HEAD avance. Conserver une vérification finale compatible avec les garanties de détection des changements externes.

Prévoir une limite propre aux compilations, une attente bornée et équitable, et une déduplication des demandes identiques. En cas d’annulation prise en charge, transmettre un signal coopératif au worker et arrêter proprement le sous-processus. Augmenter arbitrairement `CapacityLimiter(2)` pourrait surtout augmenter la consommation mémoire.

### P2 — Historique et accès ciblés

`history_list` charge actuellement un UFO complet avant de construire toute la liste d’historique et de la découper (`service.py:128–130, 202–224`). Lister des métadonnées ne devrait pas nécessiter de reconstruire tous les glyphes. Créer un chemin de lecture des manifestes et une pagination qui s’arrête à la page demandée. Un total exact peut être optionnel ou indexé. Définir explicitement si ce résultat certifie seulement les manifestes ou aussi l’intégrité de tous les fichiers sources.

Précision importante : `Store.load()` ne parcourt pas systématiquement tout l’historique pour HEAD. Son `any()` s’arrête au premier manifeste correspondant. Le parcours complet concerne notamment `history_list`, et les révisions anciennes nécessitent de remonter jusqu’à leur position.

### P3 — Optimisations locales après instrumentation

Dans `edit_glyph`, chaque `move_point` reconstruit une liste des points et la parcourt (`domain.py:171`). Un index local `point_id → point`, actualisé après les changements de topologie, remplace des recherches répétées par des accès directs.

`validate_font()` reconstruit des modèles et calcule notamment aires, composants et limites pour l’ensemble des glyphes. Un graphe de dépendances inverses aide à invalider les composites affectés par une modification d’une base. Les caches de graphes doivent préserver la détection des cycles et limites de profondeur. Les contrôles globaux Unicode, groupes et crénage restent nécessaires.

`text_view()` réalise déjà le shaping une seule fois avant la boucle des tailles (`render.py:132–154`). En revanche, le dessin vectoriel est repris pour chaque taille. Enregistrer puis rejouer la géométrie et réutiliser les données de fontes chargées est une piste secondaire. Ne pas partager des objets natifs mutables sans vérifier leur comportement concurrent.

Enfin, construire les schémas une seule fois au démarrage plutôt qu’à chaque `tools/list` (`server.py:48–61`) est simple. Ce n’est toutefois pas un coût payé à chaque appel de dessin.

## 4. Tokens : réduire le travail demandé au modèle

### 4.1 Mettre les commandes typographiques de haut niveau au premier plan

Le meilleur candidat n’est pas de renommer `project_id` en `p`. C’est de ne plus demander au modèle d’expliciter tous les points d’une construction prévisible.

Le projet possède déjà une démonstration de cette approche : `examples/miette/drawings.py:26–97` transforme des chemins de centre de trait en contours avec `fontTools.svgLib.path.parse_path`, `FreeType.Stroker` et une union géométrique. Les chaînes de dessin sont compactes ; l’exemple Python développe ensuite leurs nombreux points avant d’appeler le MCP. **Ce mécanisme n’est pas encore une primitive de l’API MCP.**

Extraire les fonctions génériques vers `src`, puis exposer des opérations typées : tracé avec épaisseur, contour rempli, primitive, duplication transformée et composition d’accents par ancres. Conserver les outils de points pour les corrections optiques fines. Déclarer directement les dépendances utilisées par le cœur plutôt que compter sur une dépendance transitive de `fontmake`.

Exemple de contrat proposé, inexistant dans la version auditée :

```json
{
  "op": "stroke_path",
  "glyph_id": "A",
  "advance": 660,
  "paths": ["M 90 44 L 330 666 L 570 44", "M 172 255 L 488 255"],
  "width": 88,
  "cap": "round",
  "join": "round"
}
```

Limiter strictement la grammaire, les segments, coordonnées et points résultants. Accepter des chemins numériques n’implique pas d’accepter des documents SVG arbitraires, des ressources externes ou du Python exécuté. Générer des identifiants déterministes et fournir leur correspondance à la demande. La stabilité après changement de topologie doit être définie, pas supposée.

### 4.2 Résumé par défaut, détails consultables

Proposer des modes explicites, par exemple `detail="summary|metrics|full"` pour l’inspection et `detail="summary|positions|full"` pour le rendu. Leur ajout doit rester proportionné afin de ne pas grossir inutilement tous les schémas.

| Outil | Réponse par défaut recommandée | Données à demander explicitement |
|---|---|---|
| `project_inspect` | Révision, famille, métriques utiles, compte des glyphes | Brief complet, décisions, inventaire, groupes, crénage |
| `glyph_get` | Mesures et géométrie ciblée selon le besoin | Tous les points, ancres et composants |
| `glyph_edit` | Révision, glyphes touchés, compte des changements | Tous les identifiants ajoutés, retirés et touchés |
| `render_text` | Image ou référence, révision, dimensions, avertissements utiles | Positions HarfBuzz, provenance et rapport complet de build |
| `font_validate` | Validité, compte par sévérité, premiers problèmes actionnables | Toutes les observations et preuves de compilation |
| `history_list` | Page et curseur suivant | Total exact et audit exhaustif |

`project_inspect` ne pagine aujourd’hui que les noms des glyphes, pas les groupes ou le crénage. Il répète aussi le brief et toutes les décisions sur chaque page (`service.py:172–194`). Ce coût peut devenir important sans être visible dans la petite démonstration.

Pour `render_text`, retirer seulement les positions et le build des métadonnées archivées passe de 2 240 à 636 octets. Pour Miette, presque tout le résultat de validation est un tableau de 121 observations, dont de nombreuses informations d’aire et d’orientation des contours. Une synthèse ne doit toutefois pas masquer un problème géométrique réel : séparer erreurs, avertissements et informations, avec un rapport détaillé accessible.

### 4.3 Ressources MCP et images : ne pas confondre transport et contexte

Enregistrer les preuves complètes sur le serveur et exposer des ressources immuables, par exemple une URI associant projet, révision et artefact. Implémenter réellement la résolution par `resources/read`, les types MIME et le contrôle des identifiants. Un chemin local brut n’est pas une ressource lisible par tous les clients.

Les ressources et liens de ressources sont prévus par MCP [E2, E9]. Ils ne font économiser des tokens que lorsque le client ne réinjecte pas systématiquement tout leur contenu dans le contexte. Garder une option d’image inline pour les hôtes qui en ont besoin ; une URI seule ne permet pas au modèle de voir un rendu.

La compression PNG réduit des octets, pas automatiquement les tokens visuels. Réduire la taille ou choisir une planche de glyphes peut être utile, à condition de préserver la lisibilité des courbes, contreformes et espacements. Prévoir un zoom ciblé. Mesurer le comportement avec les modèles réellement utilisés plutôt que promettre un facteur universel.

### 4.4 Conserver des contrats précis, alléger leur présentation

L’export compact du catalogue fait environ 30 ko pour 13 outils : ce n’est pas une explosion du nombre d’outils. Supprimer les annotations `title` redondantes donne −16,48 % sur cet export. Conserver les types, descriptions nécessaires, limites et unions discriminées. La fonction de mesure confirme qu’aucune propriété métier nommée `title` n’existe dans cet export ; une suppression générique aveugle serait à réexaminer sur de futurs schémas.

Le même schéma de sortie est répété treize fois. Le rendre plus compact est possible ; utiliser une référence globale partagée entre outils n’est pas une optimisation portable garantie. Garder un catalogue stable, préconstruit, et tester la sélection correcte des outils après chaque allègement. La spécification actuelle demande une liste cohérente, non modifiée comme effet secondaire des appels [E2]. Un profil choisi au démarrage est plus prévisible qu’un masquage dynamique.

`server.py:95–101` renvoie le résultat à la fois en `structuredContent` et en JSON textuel. Cette duplication est réelle sur le protocole, mais MCP recommande encore le texte pour la rétrocompatibilité [E2]. Elle ne prouve pas un doublement des tokens, puisque l’hôte décide ce qu’il transmet au modèle. Réduire d’abord le résultat logique commun aux deux formes. Un mode sans duplication ne doit être activé que pour des clients testés.

Limiter aussi les listes d’erreurs d’entrée : quelques erreurs précises, un total et une indication de troncature suffisent souvent. Ne pas retirer le chemin du champ fautif. Supprimer les champs vides facultatifs sans violer `outputSchema` est un complément, pas le chantier principal.

## 5. Installation : publier une application plutôt qu’un environnement de développement

### 5.1 Parcours cible : PyPI et `uvx`

`pyproject.toml` définit déjà un point d’entrée `font-design-mcp`. Le README de cette version indique une installation depuis les sources et l’absence de publication PyPI. Le paquet distribué et sa configuration devraient devenir le parcours principal ; le clonage restera destiné au développement.

Après publication d’une version correspondante, le contrat de lancement proposé est :

```json
{
  "mcpServers": {
    "font-design": {
      "command": "uvx",
      "args": [
        "--python", "3.13",
        "font-design-mcp@0.1.0",
        "serve",
        "--workspace", "/chemin/absolu/font-workspace"
      ]
    }
  }
}
```

Ce bloc est une **configuration cible après publication**, pas l’affirmation que ce paquet est disponible aujourd’hui. Le client doit trouver `uvx` dans son environnement. Adapter le chemin du workspace à la plateforme et au dossier choisi par l’utilisateur.

`uvx` exécute les outils dans un environnement isolé et permet de fixer paquet et Python [E1]. Le premier téléchargement doit être anticipé : proposer un `doctor` d’installation avant le lancement par l’hôte. Le démarrage en cache et l’installation initiale sont deux expériences à tester séparément.

Attention à la reproductibilité : lancer un paquet PyPI par `uvx` n’applique pas automatiquement le `uv.lock` du dépôt. Ce verrou reste utile pour les tests et les versions applicatives ; les dépendances transitives du paquet doivent être prises en compte dans la stratégie de livraison.

### 5.2 Transition sans clonage manuel

Le point d’entrée existant autorise déjà un lancement UV depuis un commit Git, sous réserve de pouvoir installer ses dépendances :

```sh
uvx --python 3.13 --from "git+https://github.com/Kydaix/Font-Design-MCP@4e1548b1a5d1386180ad1cdf3b35287821fa0d49" font-design-mcp doctor
```

Cette commande n’a pas été validée de bout en bout dans cet environnement sans accès au téléchargement. Elle requiert UV, Git et le réseau lors de la préparation. La documentation UV décrit ce mode `--from` et les révisions Git [E1]. Il s’agit d’une transition, pas du parcours final idéal.

### 5.3 Workspace et diagnostic

Ajouter un dossier de données utilisateur dédié par défaut, avec priorité explicite entre option CLI, variable d’environnement et valeur par défaut. Ne pas choisir silencieusement le répertoire courant, le dépôt ou le cache UV. Le workspace demeure la frontière d’autorisation ; sa modification ne doit pas être accordée à une simple requête du modèle.

Ajouter `--version`, un `doctor` qui diagnostique les dépendances manquantes proprement, et un mode de test réel TTF/WOFF2. Le `doctor` actuel rasterise un triangle et indique les versions, mais ne teste pas la compilation complète (`__main__.py:25–59`). Une commande d’aide à la configuration peut imprimer le bloc JSON ; modifier automatiquement les fichiers des clients devrait être une action explicite avec sauvegarde.

Conserver les journaux sur stderr en mode serveur. Les messages de bienvenue, de téléchargement ou de diagnostic ne doivent pas polluer stdout, réservé au protocole STDIO [E7].

### 5.4 Extension MCPB pour les hôtes compatibles

Distribuer une extension MCPB avec manifeste, version, icône, description et sélection du workspace rendrait l’installation graphique plus accessible. La spécification actuelle du manifeste prend en charge `server.type="uv"` à partir de la version 0.4, avec `pyproject.toml` et gestion du runtime Python/dépendances par l’hôte compatible [E3].

Inclure le code et les métadonnées nécessaires, pas `.venv`, les workspaces ou tous les artefacts d’exemple. Tester explicitement les versions et plateformes des hôtes supportés : le support MCPB/UV n’est pas une garantie universelle. Le téléchargement initial distingue ce mode d’un paquet entièrement hors ligne.

Un binaire autonome multi-plateforme peut être une offre complémentaire, mais pas un simple archivage de l’environnement virtuel. Point spécifique au code : `sys.executable -m fontmake` suppose un interpréteur Python disponible ; dans un exécutable figé, il faut un point d’entrée de compilation interne ou un worker correctement empaqueté.

### 5.5 Registre et chaîne de publication

Ajouter `server.json` et publier les métadonnées dans le registre MCP officiel, pour un paquet PyPI et/ou MCPB. Pour PyPI, aligner le marqueur `mcp-name` du README avec le manifeste ; pour MCPB, fournir les informations de distribution et d’intégrité requises [E4]. Le registre référence les serveurs : il ne remplace pas l’hébergement des paquets et ne garantit pas leur sécurité [E5].

Automatiser les releases à partir de tags, utiliser une publication PyPI par identité de confiance/OIDC plutôt qu’un jeton permanent lorsque possible [E8], conserver les empreintes des artefacts et tester ce qui est réellement distribué.

La CI actuelle construit le paquet, mais n’appelle pas les scripts existants `check_distribution.py` et `wheel_smoke.py`. Les intégrer à un test d’installation du wheel hors du dépôt, sur les systèmes et architectures annoncés, avec démarrage STDIO, diagnostic et parcours minimal de création/export. La matrice OS/Python existante constitue un bon début ; elle ne prouve pas à elle seule la compatibilité de tous les binaires natifs ou de tous les clients.

### 5.6 Moderniser MCP séparément des gains métier

Le projet fixe `mcp==1.30.0`. La documentation officielle décrit désormais la migration SDK v1 → v2, notamment les changements de noms de champs et du serveur bas niveau ; v1 reste maintenue pour les correctifs critiques et de sécurité [E6]. Ne pas remplacer simplement la version dans le lockfile.

Prévoir une migration testée des handlers, types, sorties et connexions anciennes/nouvelles. STDIO reste pertinent pour ce serveur local [E7] ; un service HTTP distant ajouterait des contraintes sans supprimer les recompilations ni la verbosité des réponses. Les mécanismes de découverte/cache du protocole actuel doivent être traités comme un chantier de compatibilité distinct du cache de compilation interne.

## 6. Architecture cible, sans réécriture générale

```text
Client MCP
   │ commandes métier typées, lots, niveau de détail
   ▼
Transport / validation des requêtes
   ▼
Service de transactions ─── Présentation des résultats compacts
   │                         └── Rapports et ressources détaillés
   ├── Stockage : vérification, chargement, commit atomique
   ├── Domaine : opérations et invariants typographiques
   ├── Cache de compilation : TTF puis WOFF2
   └── Rendu : cache lié à la source et aux paramètres
```

Commencer par des interfaces internes autour des modules existants. Un changement de langage, un passage à une autre surcouche MCP ou une migration de tout le stockage n’est pas un préalable.

Les clés de rendu doivent inclure les deux révisions en cas de comparaison, le texte, le shaping, les tailles, le cadre partagé, les couleurs et la version des moteurs pertinents. Un cache seulement indexé par le nom du glyphe serait incorrect.

Le stockage complet par révision reste coûteux pour de nombreuses modifications, mais les lots doivent être essayés avant une migration vers des deltas ou un stockage adressé par contenu. Une telle migration demande un format, un mécanisme de reprise et des tests d’intégrité ; elle n’est pas un correctif rapide.

## 7. Plan de réalisation et critères d’acceptation

| Ordre | Changement | Preuve d’acceptation |
|---|---|---|
| 0 | Instrumentation par phase, compteurs de compilation, tailles des sorties | Mesures reproductibles sur petits et grands projets ; pas de mélange froid/chaud. |
| 1 | Cache TTF/WOFF2 et résultats compacts | Une compilation au plus pour la séquence Miette sur une même clé ; même couverture et rendu. |
| 2 | Séparation vérification/chargement et transactions multi-glyphes | Un chargement matérialisé par transaction ordinaire ; rollback complet du lot fautif. |
| 3 | Publication PyPI, configuration UV et smoke tests du wheel | Installation propre hors dépôt, lancement STDIO et export sur les plateformes annoncées. |
| 4 | Primitives de dessin et ressources à la demande | Moins d’appels et de tokens mesurés sur un même objectif, sans perte de correction. |
| 5 | Verrous raccourcis, caches de géométrie et migration SDK | Concurrence saine, annulation propre, compatibilité des clients et tests d’intégrité conservés. |
| 6 | MCPB et publication au registre | Installation graphique vérifiée, workspace autorisé, désinstallation et mises à jour testées. |

La séquence peut être parallélisée entre packaging et cœur métier. Aucun gain de temps ou de tokens ne doit être annoncé sur la seule base d’une diminution d’octets.

### Banc de mesure recommandé

Comparer un petit projet de démonstration, Miette et un jeu synthétique approchant les limites actuelles. Pour chacun : démarrage froid/chaud, modification d’un point, lot multi-glyphes, rendu répété d’une révision, comparaison avant/après, validation puis export, pagination d’un long historique et deux projets actifs simultanément.

Mesurer temps total et temps par phase, médiane et p95 sur plusieurs répétitions, nombre de fichiers lus/écrits, octets, mémoire maximale, constructions lancées, taux de cache et attente de verrous. Pour l’IA, enregistrer avec consentement les appels, les tokens réels du modèle/hôte, les nouvelles tentatives, le taux de succès et la qualité visuelle. Les octets de JSON restent une métrique auxiliaire.

Tests de non-régression indispensables : source modifiée derrière un cache chaud ; artefact corrompu ; `expected_revision` obsolète ; crash avant publication ; lot partiellement invalide ; composants dépendants ; lecture d’une révision pendant une autre écriture ; compilation annulée ; chemins avec espaces et accents ; stdout exclusivement protocolaire ; ancien client n’utilisant pas `structuredContent` ; hôte ne lisant pas automatiquement les ressources.

## 8. Sources externes vérifiées

Les constats sur le projet viennent du code fourni, aux lignes indiquées, et des captures présentes dans l’archive. Les références suivantes appuient les points concernant l’écosystème actuel. Les commandes et contrats présentés comme propositions ne sont pas des fonctionnalités déjà implémentées dans Font Design MCP.

**E1 — Astral, Using tools :** isolation UV, versions, `--from`, Python, installation d’outils.
```text
https://docs.astral.sh/uv/guides/tools/
```

**E2 — MCP, Tools, spécification 2026-07-28 :** outils, sortie structurée, compatibilité textuelle, liens et stabilité du catalogue.
```text
https://modelcontextprotocol.io/specification/2026-07-28/server/tools
```

**E3 — MCPB, Manifest :** mode UV, versions du manifeste, configuration utilisateur et autres modes de distribution.
```text
https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
```

**E4 — MCP Registry, Package types :** publication PyPI/MCPB et métadonnées d’identification.
```text
https://modelcontextprotocol.io/registry/package-types
```

**E5 — MCP Registry, About :** rôle et limites du registre.
```text
https://modelcontextprotocol.io/registry/about
```

**E6 — MCP Python SDK, Migration Guide v1 to v2 :** changements incompatibles et maintenance de v1.
```text
https://py.sdk.modelcontextprotocol.io/migration/
```

**E7 — MCP, STDIO, spécification 2026-07-28 :** transport local et séparation stdout/stderr.
```text
https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
```

**E8 — PyPI, Trusted Publishers :** publication par identité de confiance.
```text
https://docs.pypi.org/trusted-publishers/
```

**E9 — MCP, Resources, spécification 2026-07-28 :** ressources et lecture de leur contenu.
```text
https://modelcontextprotocol.io/specification/2026-07-28/server/resources
```

**Dépôt et commit audités :**
```text
https://github.com/Kydaix/Font-Design-MCP
https://github.com/Kydaix/Font-Design-MCP/commit/4e1548b1a5d1386180ad1cdf3b35287821fa0d49
```
