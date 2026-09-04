---
title: "0007"
---
# ADR-0007 — `pyright@claude-code-lsps` (fork communautaire) au lieu de `pyright-lsp@claude-plugins-official`
*Update date : 2026-09-04 00:00*

Status: accepted
Date: 2026-09-04

## Contexte

`pyright-lsp@claude-plugins-official` était activé sur 3 repos (`bootstrap`, `pinky-lib`, `pluto`).
Le marketplace officiel déclare bien `lspServers: ["pyright"]` pour ce plugin
(`plugin-catalog-cache.json`), mais au moment de l'install, Claude Code ne propage jamais cette
config vers le cache du plugin installé — vérifié en local le 2026-09-04 :
`~/.claude/plugins/cache/claude-plugins-official/pyright-lsp/1.0.0/` ne contient que `LICENSE` et
`README.md`, aucun fichier de config LSP. Le plugin est `enabled` mais zéro serveur LSP n'est
réellement enregistré. Bug amont, même root cause sur les 11 plugins `*-lsp` du marketplace officiel
(issues anthropics/claude-code#14803, #15560, #16219, #23298,
anthropics/claude-plugins-official#379 — toutes ouvertes au 2026-09-04).

Un LSP fonctionnel a une justification mesurée, pas supposée : `serena` (MCP de navigation de code,
présent sur cette machine via l'essai Headroom en cours,
`_KANBAN/CHANTIER0024-pinky-bootstrap/3-in-progress/adopter-headroom-essai-1-semaine.md`) échoue sur
un cas de résolution cross-package réel — `find_declaration` sur l'import
`pinky_ai/quota.py:22 → pinky_core.security.validate_identifier` ne résout rien ; `find_symbol`
retrouve la bonne définition mais noyée dans 3 faux positifs homonymes de fichiers legacy. `serena`
et un LSP ne sont pas mutuellement exclusifs (registres différents : MCP vs plugin LSP) — mais
`headroom wrap claude --code-memory none` est déjà l'intention retenue côté Headroom
(alias `hw`), ce qui laisse la navigation de code reposer sur le LSP, pas sur serena.

Le fork `Piebald-AI/claude-code-lsps` a été vérifié avant adoption (pas pris sur parole) : son
plugin `pyright` embarque la config du serveur dans un fichier `.lsp.json` versionné dans le repo
du plugin lui-même (`{"python": {"command": "pyright-langserver", "args": ["--stdio"], ...}}`),
distinct du `marketplace.json` — donc indépendant du mécanisme de propagation cassé côté officiel.

## Décision

Remplacer `pyright-lsp@claude-plugins-official` par `pyright@claude-code-lsps` sur les 3 repos où il
était actif, et outiller la détection/le câblage dans `pinky-bootstrap` plutôt que de l'éditer à la
main — un `pinky install --plugin` ou `pinky plugins reconcile --apply` refait sur ce plugin (ou un
futur autre `*-lsp`) doit reproduire le même résultat, pas dépendre d'une édition JSON une fois
oubliée :

- `plugin_install.ships_lsp_server(install_path)` détecte un `*.lsp.json` dans les fichiers
  installés — signal indépendant de la marketplace source (couvre aussi bien le fork qu'un futur
  fix upstream de l'officiel, si son mécanisme de propagation venait à livrer le même genre de
  fichier).
- `plugin_install.ensure_lsp_tool_enabled(target)` pose `env.ENABLE_LSP_TOOL=1` au même scope que le
  plugin — `ENABLE_LSP_TOOL` n'a pas de slot dans le manifeste de plugin, même trou que `statusLine`
  déjà comblé par `set_status_lines`.
- Câblé dans `plugin_scope.run_marketplace_wizard`, le seul point qui active un plugin à un scope,
  pour les deux appelants (`pinky install --plugin` et `pinky plugins reconcile --apply`).

## Conséquences

- Les 3 repos (`bootstrap`, `pinky-lib`, `pluto`) ont `pyright@claude-code-lsps: true` +
  `env.ENABLE_LSP_TOOL: "1"` dans leur `.claude/settings.json`, posés par le wizard, pas à la main.
- `pyright-lsp@claude-plugins-official` désactivé aux 3 scopes projet + décision `uninstall`
  enregistrée dans le ledger (`~/.claude/pinky-install-state.json`,
  `reconcile:pyright-lsp@claude-plugins-official`) — un futur `reconcile --apply` ne le réactivera
  pas. Reliquat inoffensif : son entrée de registre `scope: local` (fichiers en cache, jamais dans
  un `enabledPlugins`) a refusé la désinstallation CLI (`claude plugin uninstall --scope local` →
  "not installed in local scope") ; sans impact puisque rien ne l'active plus nulle part.
- Dépendance à un marketplace tiers non-Anthropic (`Piebald-AI/claude-code-lsps`) — code exécuté au
  build/à l'install du plugin, accepté en connaissance de cause plutôt qu'ignoré.
- Les 10 autres plugins `*-lsp@claude-plugins-official` du marketplace officiel partagent le même
  bug de propagation ; aucun n'est installé sur cette machine aujourd'hui — signalé, pas traité ici.
- **Critère de retour à l'officiel** : les issues amont citées ci-dessus ferment, et
  `~/.claude/plugins/cache/claude-plugins-official/<plugin>-lsp/<version>/` contient autre chose que
  `LICENSE`/`README.md` après un install propre (même vérification qu'en Contexte) — pas une
  annonce de fix, une réplique de la mesure.
