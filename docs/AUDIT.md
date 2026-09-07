# Audit initial — 7 septembre 2026

Le répertoire de travail était `C:/Users/Administrator/IdeaProjects`, sans dépôt Git à sa racine.
L'inventaire de premier niveau montrait un projet `custom-vinyl-records` et des dossiers de configuration.
Aucun code/configuration/changement Git de ce projet voisin n'a été modifié. `font-design-mcp` a été créé
comme nouveau dossier autonome ; aucun `git init`, dépôt imbriqué, commit, publication ou installation de
police système. Aucun parcours des polices ni des documents personnels.

Instructions lues : celles fournies par l'utilisateur, LEAN-CTX.md et skills lean-ctx, ponytail, OpenAI Docs.
Le contrôle de premier niveau n'a trouvé aucun AGENTS.md additionnel à appliquer dans ce nouveau dossier.
Les accès d'exploration ont utilisé lean-ctx ; les lectures des skills hors de sa racine ont nécessité
le mécanisme local de lecture. Aucun paramètre global de sécurité ou de client n'a été changé.

| Élément | Observation réelle |
|---|---|
| OS | Windows 11 Enterprise 64 bits, noyau 10.0.26300 |
| Architecture | x64, confirmée par OS et binaire uv x86_64 |
| Python système | 3.14.7 |
| Python retenu | CPython 3.11.16 déjà disponible via uv |
| uv | 0.12.10 |
| Git, Node | Exécutables disponibles ; aucun dépôt créé |
| Client MCP identifié | Codex CLI 0.153.4 disponible ; configuration globale non lue/modifiée |
| Client réellement testé | SDK MCP Python 1.30.0, initialisation/découverte/appels STDIO réels |
| Rasterisation | freetype-py 2.5.1, FreeType natif 2.13.2, Pillow 12.3.0 ; PNG réellement créé |

La valeur `platform.platform()` rapporte le noyau sous « Windows-10 » et `platform.machine()` est vide dans
cet environnement réduit. Cela ne remplace pas l'identification OS faite avec Win32_OperatingSystem.

## Choix techniques et vérifications

Les API du SDK installé ont été inspectées : `Server.list_tools`, `Server.call_tool(validate_input=False)`,
`stdio_server`, `ClientSession` et `CallToolResult(structuredContent=..., content=..., isError=...)`.
La validation Pydantic est appliquée explicitement avant l'appel métier, afin d'avoir des codes d'erreur
structurés. Les schémas d'entrée et de sortie sont publiés dans `tools/list` et consommés par le client SDK.

ufoLib2 a été retenu pour les objets UFO 3 ; fontmake 3.12.1 est réellement appelé avec `--keep-overlaps`,
`--no-autohint`, `--no-production-names` et `--validate-ufo`. L'aide du binaire installé a été vérifiée.
FreeTypePen a été testé sur un contour original avant d'être choisi ; ses PNG sont fournis par Pillow.
HarfBuzz compose les binaires créés, sans substitution de polices système. Skia a été examiné mais n'est
pas une dépendance : ses prérequis Linux additionnels n'apportaient rien de nécessaire à ce MVP.

Installation isolée dans `.venv` ; cache de téléchargement local au projet `.uv-cache` pendant le travail.
Les versions installées, y compris transitives, figurent dans `uv.lock`. Aucun package installé à l'exécution
d'un outil MCP. FontForge et les adaptateurs d'éditeurs sont absents de la chaîne requise.

## Documentation officielle consultée

- [SDK MCP Python, branche 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) et source **installée** 1.30.0.
- [ufoLib2 : modèle UFO 3](https://ufolib2.readthedocs.io/en/latest/) et signatures installées 0.18.1.
- [fontmake](https://github.com/googlefonts/fontmake), aide CLI installée 3.12.1.
- [fontTools FreeTypePen](https://fonttools.readthedocs.io/en/latest/pens/freetypePen.html) : rendu non-zero, transformations, dimensions.
- [freetype-py](https://github.com/rougier/freetype-py) : bibliothèque native incluse dans les wheels supportées.
- [uharfbuzz](https://github.com/harfbuzz/uharfbuzz) : shaping local et positions.
- [Pydantic, unions discriminées](https://docs.pydantic.dev/latest/concepts/unions/).
- [Configuration MCP Codex officielle](https://developers.openai.com/codex/mcp/), redirigée par OpenAI vers sa documentation actuelle ; `codex mcp add --help` local.
- [actions/checkout](https://github.com/actions/checkout), [actions/setup-python](https://github.com/actions/setup-python), [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) pour la CI configurée.

Les documentations ont guidé les choix ; les tests locaux valident la combinaison effectivement installée.
La présence de wheels annoncées pour d'autres plateformes n'est pas assimilée à une exécution réussie ici.
