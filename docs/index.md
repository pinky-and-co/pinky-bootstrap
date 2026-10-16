# pinky-bootstrap — index

## ADR

- [0001 — `statusLine`/`subagentStatusLine` niveau user ; `enabledPlugins` scope git-repo-root](adr/0001-statusline-enabledplugins-niveau-user.md)
- [0002 — Marketplace `directory` en dev local pour les repos plugin, `github` pour la consommation](adr/0002-directory-marketplace-source-dev-local-plugins.md)
- [0005 — `CLAUDE.md`/`AGENTS.md` : import ou symlink selon le niveau](adr/0005-agents-md-symlink-par-niveau.md)
- [0009 — `AGENTS.md` du workspace et des groupes régénéré par le plugin, sans symlink `CLAUDE.md`](adr/0009-agents-md-regenere-par-le-plugin-sans-symlink.md)
- [0006 — Council : advisors sur modèles distincts du pool, pas sur personas d'un seul modèle](adr/0006-council-advisors-cross-modele.md)
- [0010 — Rules paresseuses : stub présenté, contenu lu à la demande, lecture autorisée par `permissions.allow`](adr/0010-rules-paresseuses-stub-contenu-permission.md)
- [0011 — `freeze` ne juge plus `Bash` : le garde d'écriture Bash est supprimé](adr/0011-freeze-ne-juge-plus-bash.md)
- [0012 — Un `/goal` ne verrouille jamais les outils ; amender = prouver l'impossibilité](adr/0012-goal-ne-verrouille-jamais-les-outils.md)

## How-to

- [install-plugin.md](how-to/install-plugin.md) — installer un plugin puis l'activer au bon scope (user/groupe/repo)
- [setup-model-pool.md](how-to/setup-model-pool.md) — provisionner le pool multi-fournisseur (clés, schéma d'entrée) pour `adversarial`/délégation
- [setup-declarative-secrets.md](how-to/setup-declarative-secrets.md) — déclarer une clé résolue à la demande (`keys` de `settings.pinky.json`, trousseau classique)
- [pinky-doctor.md](how-to/pinky-doctor.md) — vérifier les prérequis des plugins installés (binaires, Ollama, clés API) ; `--fix` propose les `brew install`
- [distribute-to-plugin-repos.md](how-to/distribute-to-plugin-repos.md) — `pinky repo distribute` : plan + `[y/N]`, ce que reçoit chaque repo (hooks, CI, fichiers partagés, vendored), `--commit`, drift

## Explanation

- [rules-scope-and-precedence.md](explanation/rules-scope-and-precedence.md) — où une rule s'applique, qui gagne
- [claude-code-architecture-findings.md](explanation/claude-code-architecture-findings.md) — tests empiriques skills/plugins/forks/CLAUDE.md, référence avant de re-tester
