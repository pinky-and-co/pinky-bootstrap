# pinky-bootstrap — index

## ADR

- [0001 — `statusLine`/`subagentStatusLine` niveau user ; `enabledPlugins` scope git-repo-root](adr/0001-statusline-enabledplugins-niveau-user.md)
- [0002 — Marketplace `directory` en dev local pour les repos plugin, `github` pour la consommation](adr/0002-directory-marketplace-source-dev-local-plugins.md)
- [0005 — `CLAUDE.md`/`AGENTS.md` : import ou symlink selon le niveau](adr/0005-agents-md-symlink-par-niveau.md)

## How-to

- [install-plugin.md](how-to/install-plugin.md) — installer un plugin puis l'activer au bon scope (user/groupe/repo)
- [setup-model-pool.md](how-to/setup-model-pool.md) — provisionner le pool multi-fournisseur (clés, schéma d'entrée) pour `adversarial`/délégation
- [setup-declarative-secrets.md](how-to/setup-declarative-secrets.md) — déclarer une clé chargée au `SessionStart` (`keys` de `settings.pinky.json`, trousseau classique)

## Explanation

- [rules-scope-and-precedence.md](explanation/rules-scope-and-precedence.md) — où une rule s'applique, qui gagne
- [claude-code-architecture-findings.md](explanation/claude-code-architecture-findings.md) — tests empiriques skills/plugins/forks/CLAUDE.md, référence avant de re-tester
