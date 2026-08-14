
  worker-bundle:
    # Repos déployés comme Worker Python (détectés par un binding D1 dans wrangler.jsonc). Ce job
    # ne déploie RIEN : il prouve que la chaîne d'assemblage tient et que le schéma s'applique.
    # Deux choses qu'aucun linter ne voit et qui cassent en silence sinon.
    runs-on: ubuntu-latest
    permissions:
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node 22
        # ⚠ Version ÉPINGLÉE, et surtout pas « latest ». `pywrangler` construit son environnement
        # Pyodide en lançant node avec `--experimental-wasm-stack-switching` ; V8 a renommé puis
        # stabilisé ce drapeau en JSPI, et Node 26 le refuse sèchement (`node: bad option`).
        # Constaté le 2026-07-31 : sur Node 26, aucune commande pywrangler ne démarre.
        uses: actions/setup-node@v4
        with:
          node-version: "22"

      - name: Set up Python __PYTHON_VERSION__
        uses: actions/setup-python@v5
        with:
          python-version: "__PYTHON_VERSION__"

      - name: Install uv
        uses: astral-sh/setup-uv@v6

      - name: Apply the D1 migrations to a throwaway local database
        # `--local` : une base SQLite jetable dans .wrangler/, jamais la base distante. On ne
        # vérifie pas l'état de la production, on vérifie que les fichiers de migration
        # s'appliquent — un .sql invalide ne se voit qu'en l'exécutant.
        run: npx --yes wrangler@latest d1 migrations apply __D1_DATABASE__ --local

      - name: Build the Worker bundle and check its compressed size
        # `--dry-run` n'exige aucun identifiant Cloudflare (vérifié) et ne déploie rien : il assemble
        # les dépendances Python et imprime le poids gzip, le seul chiffre qui décide si le Worker
        # tient sur le plan gratuit — plafond 3 MB APRÈS compression, pas avant.
        run: uv run pywrangler deploy --outdir bundle/ --dry-run

  worker-deploy:
    # Le déploiement de la sandbox : le SCHÉMA puis le CODE, sur la base réelle.
    #
    # Job SÉPARÉ de `worker-bundle`, et ce n'est pas de la coquetterie : celui-ci porte un jeton
    # Cloudflare. Fusionner les deux exposerait ce secret à chaque pull request, y compris celle d'un
    # contributeur extérieur. `worker-bundle` reste sans identifiants et tourne partout ;
    # `worker-deploy` ne tourne que sur un push de la branche d'intégration.
    #
    # `develop` et pas `main` : c'est la branche que l'infrastructure déclare comme étant la sandbox
    # (voir `pluto-infra/terraform/cloudflare-pilot.tf`). La production de chaque client vivra sur son
    # propre compte, avec ses propres variables — ce n'est pas ce que ce job déploie.
    if: github.event_name == 'push' && github.ref == 'refs/heads/develop'
    needs: worker-bundle
    runs-on: ubuntu-latest
    permissions:
      contents: read
    env:
      # Au niveau du REPO, pas de l'organisation — contrainte du plan gratuit GitHub, mesurée le
      # 2026-08-01 : une valeur d'org ne descend pas dans un dépôt privé. Le détail du test et les
      # trois faux signaux qui font croire l'inverse : card kanban `deployer-pilot-depuis-la-ci`.
      # Conséquence assumée : le jeton est recopié dans chaque repo qui déploie.
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node 22
        uses: actions/setup-node@v4
        with:
          node-version: "22"

      - name: Set up Python __PYTHON_VERSION__
        uses: actions/setup-python@v5
        with:
          python-version: "__PYTHON_VERSION__"

      - name: Install uv
        uses: astral-sh/setup-uv@v6

      - name: Apply the D1 migrations to the real database
        # ⚠ AVANT le déploiement du code, et l'ordre n'est pas négociable. Déployer du code qui
        # attend une colonne absente casse l'application pour de vrai ; migrer sans déployer ne casse
        # rien — le code déjà en place ignore simplement la nouveauté. En cas d'échec ici, le job
        # s'arrête et l'ancien Worker continue de servir : c'est le comportement voulu.
        #
        # Rejouable sans risque : le registre `d1_migrations` de la base note ce qui est déjà passé,
        # donc un push sans nouvelle migration ne fait rien.
        run: npx --yes wrangler@latest d1 migrations apply __D1_DATABASE__ --remote

      - name: Deploy the Worker
        run: uv run pywrangler deploy
