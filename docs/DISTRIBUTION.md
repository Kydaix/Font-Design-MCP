# Distribution — 0.2.0

Les commandes de publication sont préparées. Aucun paquet PyPI, tag, release GitHub ou enregistrement
au registre MCP n'est publié par la modification locale du code.

## Construire et vérifier

```sh
uv sync --frozen --python 3.13
uv run --frozen font-design-mcp doctor --build
uv run --frozen pytest -q
uv build
uv run --frozen python scripts/check_distribution.py
uv run --frozen python scripts/test_wheel.py
uv run --frozen python scripts/build_mcpb.py
uv run --frozen python scripts/test_mcpb.py
uv run --frozen python scripts/check_registry.py
npx --yes @anthropic-ai/mcpb@2.1.2 validate mcpb/manifest.json
```

`check_distribution.py` inspecte le wheel et le sdist de la version du `pyproject.toml`.
`test_wheel.py` crée un environnement dans un dossier temporaire extérieur au dépôt, installe le wheel
et vérifie les fichiers réellement importés, le point d'entrée, le diagnostic TTF/WOFF2 et une démonstration
STDIO complète. Ses chemins comprennent des espaces et un accent. La CI lance ces étapes sur Windows,
macOS et Linux, Python 3.11/3.13. Une matrice configurée n'est pas une preuve que ses jobs distants ont tourné.

Le wheel et le paquet PyPI fixent les dépendances directes, mais `uvx` ne consomme pas automatiquement le
`uv.lock` du dépôt. `requirements.lock` fournit les résolutions/hashes des dépendances sans installation
éditable du projet (`uv export --frozen --no-dev --no-emit-project`) ; les smoke tests de
wheel installent la résolution réellement obtenue hors dépôt. MCPB embarque `uv.lock` et se lance avec
`uv run --frozen --no-dev --no-editable`, sans environnement virtuel embarqué. Le mode non éditable évite
notamment les problèmes d'encodage des chemins `.pth` avec Python 3.11 sous Windows dans un dossier accentué.

## Clients anciens et nouveaux

Le serveur utilise `mcp==2.2.0` et les handlers `on_*`, avec champs Python snake_case et objets de résultat
explicites. Le format JSON du protocole reste géré par le SDK. Le test `test_new_protocol_client` impose
la version 2026-07-28. Les tests `ClientSession` couvrent le protocole historique.

Pour tester en plus un véritable SDK 1.30 dans un environnement isolé, remplacer l'interpréteur de serveur :

```sh
uv run --isolated --no-project --with mcp==1.30.0 python scripts/legacy_client.py /absolute/path/.venv/bin/python
```

Sous Windows : `.venv/Scripts/python.exe`. Le client ancien lit volontairement le JSON textuel, puis une
image et une ressource. La [migration officielle](https://py.sdk.modelcontextprotocol.io/migration/) décrit
les ruptures d'API ; elle a été accompagnée de tests, pas d'un simple remplacement de dépendance.

## PyPI et releases

Le workflow `release.yml` se déclenche sur les tags `v*`, vérifie l'égalité tag/version et attend la matrice
de tests. Il reconstruit/teste le wheel, publie wheel et sdist par OIDC, puis joint les distributions,
MCPB et `SHA256SUMS` à une release GitHub.

Avant le premier tag, le propriétaire doit configurer un Trusted Publisher PyPI pour
`Kydaix/Font-Design-MCP`, workflow `release.yml`, environnement `pypi`, et les protections souhaitées de
cet environnement GitHub. Aucun jeton permanent n'est nécessaire. Voir les
[instructions PyPI](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

Le manifeste `server.json` et le marqueur `mcp-name` du README concordent. Publier ce manifeste au registre
avec le compte GitHub propriétaire **après** disponibilité de la version PyPI, suivant les
[instructions du registre](https://modelcontextprotocol.io/registry/package-types).
Le registre n'héberge pas le wheel. Ajouter une distribution MCPB au manifeste exige l'URL de release et
son empreinte réelle, produite par `build_mcpb.py` ; aucune URL d'artefact inexistant n'est annoncée.

## MCPB

`build_mcpb.py` produit `dist/font-design-mcp-0.2.0.mcpb` avec une liste stricte : code de production,
manifeste, point d'entrée, icône, métadonnées de paquet, lock, README et licence. Aucun workspace, `.venv`,
historique utilisateur ou spécimen de Miette n'y entre. Les entrées ZIP ont des dates fixes.
Le manifeste suit l'[exemple UV officiel](https://github.com/modelcontextprotocol/mcpb/tree/main/examples/hello-world-uv)
et demande un dossier de workspace choisi par l'utilisateur.

Validation du schéma, installation UV et démarrage du bundle sont testables automatiquement. L'installation
graphique, le sélecteur de dossier, la mise à jour et la désinstallation doivent encore être vérifiés dans
chaque hôte/version annoncé compatible. Aucun hôte graphique spécifique n'est déclaré certifié.
La désinstallation de l'extension conserve le workspace choisi ; celui-ci n'est pas stocké dans le bundle.
Le premier téléchargement UV nécessite le réseau : ce paquet n'est pas un binaire autonome hors ligne.
