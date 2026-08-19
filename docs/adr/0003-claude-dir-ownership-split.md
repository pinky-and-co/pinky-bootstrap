---
title: "0003"
---
# ADR-0003 — `.claude/` : propriété plugin à 90 %, CLI setup à 10 % ; `CLAUDE.md`/`AGENTS.md` : template CLI + édition manuelle
*Update date : 2026-08-19 23:29*

Status: accepted
Date: 2026-08-19

## Contexte

Le rendu `.claude/` d'un repo consommateur (ce workspace inclus) mélange deux origines : ce que les
plugins installés apportent nativement (skills, hooks, agents, `enabledPlugins`) et ce qui n'a pas
d'équivalent plugin natif — les `rules/` distribuées par `pinky-bootstrap --rules`
(`feature/distribute-rules-core`, pas encore mergée), les output styles, les thèmes. Sans partage
explicite, la question « qui a le droit d'écrire quoi sous `.claude/` » revient à chaque carte
(`cli-setup-repo-lot1.md`, la migration des rules, `reinstaller-plugin-pc-core.md`) sans réponse
stable.

## Décision

**`.claude/` se partage 90 % / 10 % :**

- **90 % plugin-managed** — tout ce qu'un plugin installé (`enabledPlugins`) rend nativement :
  skills, hooks, agents, cache plugin. Le CLI setup n'y touche jamais.
- **10 % CLI-custom-managed** — ce qui n'a pas de mécanisme plugin natif : `rules/`, output styles,
  thèmes. Reste porté par `pinky-bootstrap` (`setup/rules.py` et équivalents), pas par un plugin.

**`CLAUDE.md`/`AGENTS.md` suivent une troisième règle, différente des deux ci-dessus** : générés en
template par le CLI setup, puis **édités à la main** dans le repo consommateur — ni 100 % généré
(un fichier qu'on ne peut jamais amender perd son utilité), ni 100 % manuel (on perd la
mécanisation de ce qui est commun à tous les repos).

## Conséquences

- `cli-setup-repo-lot1.md` Entrée 0 (génération `AGENTS.md`/`CLAUDE.md`) implémente la troisième
  règle — template + main éditable, pas un rendu figé façon `render_claude_md` (déjà supprimé,
  ADR-0001 `pinky-bootstrap`).
- La migration des rules (`migration-des-24-rules-verdict-par-fichier.md`) est le chantier qui
  peuple le 10 % CLI-managed — elle ne cherche pas à faire porter les rules par un plugin.
- Un futur mécanisme plugin natif pour les rules (si Claude Code en introduit un) ferait glisser ce
  10 % vers le 90 % — à rouvrir seulement si ça arrive, pas anticipé ici.
