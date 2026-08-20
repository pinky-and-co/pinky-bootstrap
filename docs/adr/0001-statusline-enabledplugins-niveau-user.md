---
title: "0001"
---
# ADR-0001 — `statusLine`/`subagentStatusLine` niveau user ; `enabledPlugins` scope git-repo-root
*Update date : 2026-08-21 00:00*

Status: accepted
Date: 2026-08-21

## Context

Une décision précédente (17/08) plaçait `statusLine`, `subagentStatusLine` ET `enabledPlugins` au
niveau user (`~/.claude/settings.json`), au motif qu'un `.claude/settings.json` de projet ne
s'applique que si le cwd de la session est EXACTEMENT le répertoire qui le porte. Prémisse fausse,
vérifiée contre la doc officielle le 2026-08-21 :

> Claude Code reads and writes this file at the root of the git repository, resolved through
> worktrees to the main checkout, so one file covers sessions started in any subdirectory or
> worktree of the repository.
> — `code.claude.com/docs/en/configuration.md`, section "Settings files"

Résolution par **racine du repo git** (via worktrees), pas par cwd exact — un `.claude/settings.json`
posé à la racine d'UN repo s'applique à toute session lancée dans n'importe quel sous-dossier ou
worktree de CE repo. Ce mécanisme était déjà un prérequis testé au démarrage de la migration
plugins, avant même l'ajout du niveau "groupe" à la hiérarchie AGENTS.md — la décision du 17/08 le
contredisait sans avoir recroisé ce fait déjà établi.

## Decision

- **`enabledPlugins` (et `extraKnownMarketplaces`) se scope par repo git**, pas systématiquement au
  niveau user. Un plugin spécifique à PLUTO s'active dans le `.claude/settings.json` de chaque repo
  `pluto-*`, un plugin Snowflake dans celui des repos `pinky-lib/*` — pas une liste unique et globale
  côté `~/.claude/settings.json`.
- **`statusLine`/`subagentStatusLine` restent niveau user.** Raison différente, toujours valide : ce
  sont des préférences d'exécution cross-session (l'apparence de la statusline ne dépend pas du repo
  ouvert), pas une question de résolution technique — le scope user est un choix délibéré ici, pas
  une contrainte de mécanisme.
- **Niveau "groupe" (`pluto/`, `pinky-lib/`, `bootstrap/`, ...) : un seul `.claude/settings.json`
  au niveau du groupe suffit** — testé empiriquement (prérequis validé au démarrage de la migration
  plugins, avant l'ajout du niveau groupe à la hiérarchie AGENTS.md). Pas de fan-out vers chaque
  repo nested : `pinky-lib/.claude/settings.json` s'applique aux sessions dans `pinky-lib/pinky-core/`
  etc. La doc officielle ne documente pas explicitement ce cas (silence, pas contradiction). Testé
  empiriquement par ailleurs (hors de ce repo) : une `.claude/rules/` path-scoped posée dans un
  dossier NON-git se déclenche bien sur un fichier à l'intérieur d'un repo git nested dedans, malgré
  la frontière `.git` propre à ce repo — la frontière `.git` ne bloque que la **remontée** (le repo
  comme point de départ de session), pas la **descente** (session ouverte plus haut, qui descend
  naturellement). Même principe retenu ici pour `.claude/settings.json`.

## Consequences

- L'installeur state-file (`pinky install`) peut scoper `enabledPlugins`/marketplaces par repo OU
  par groupe, avec un flux : (1) user ou projet ? (2) si projet, quelle profondeur (racine
  workspace / niveau groupe / repo) ? (3) proposer les cibles éligibles trouvées à ce niveau —
  chaque cible reçoit UN `.claude/settings.json`, jamais de fan-out.
- `cli-setup-repo-lot1.md` entrée 4 décision transverse #1 doit être recorrigée sur ce point (elle
  pointait vers l'ancienne version de cet ADR).
- `permissions.allow`/`permissions.deny` restent hors du périmètre de cet ADR (entrée 6 de la même
  card — source déclarée par les skills/agents installés, pas ce sujet).
