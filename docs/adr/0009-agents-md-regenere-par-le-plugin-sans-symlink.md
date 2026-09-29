---
title: "0009"
---
# ADR-0009 — `AGENTS.md` du workspace et des groupes régénéré par le plugin, sans symlink `CLAUDE.md`
Status: accepted
Date: 2026-09-29
Supersedes: [ADR-0005](0005-agents-md-symlink-par-niveau.md)

## Context

Le workspace et ses groupes de repos ne sont pas des repos git. Le tableau des packages de leur
`AGENTS.md` dérive de `[project].description` de chaque repo ; aucun hook pre-commit n'y tourne et le
générateur ne se lançait que par un flag manuel de `pinky repo distribute`. Mesuré : un des cinq
`AGENTS.md` de groupe était périmé. Ces fichiers ne sont dans aucun repo : leur lecteur est une
session Claude qui les charge en ancêtre du repo ouvert, personne ne les lit sur GitHub.

Claude Code lit désormais `AGENTS.md` directement (≥ 2.1.277, réglage « Project instructions »),
là où ADR-0005 imposait un symlink `CLAUDE.md → AGENTS.md` ou un import.

## Decision

- Le rendu vit dans le plugin `pc-autodiscovery` (stdlib, sans appel au CLI `pinky`) : un hook
  `SessionStart` réécrit sur disque l'`AGENTS.md` du workspace et de chaque groupe, seulement si le
  contenu change, et signale l'écart à l'utilisateur et au modèle.
- Aucun symlink n'est créé ; ceux qui existent ne sont pas touchés.
- Niveau repo : un skill crée l'`AGENTS.md` absent, à la demande, jamais d'écriture automatique dans un
  repo versionné.
- `pinky-bootstrap` n'a plus de générateur : `setup/agents_md.py`, `--agents-md`, `--standalone`, les
  gabarits `agentic-harness/agents-md/` et `pinky claude-config-preset` (doublon de `pc-customize`)
  disparaissent. `agentic-harness/` ne garde que `rules/`.
- Les gotchas viennent de `settings.pinky.json["gotchas"]`, comme `behavior`.

## Alternatives écartées

- **Garder le symlink** : n'apporte plus rien dès que Claude Code lit `AGENTS.md` ; risque Windows
  documenté par ADR-0005 supprimé avec lui.
- **Hook pre-commit par repo** : le workspace et les groupes n'ont pas de repo, aucun déclencheur.
- **Sous-commande `pinky agents-md` appelée par le hook** : couple un plugin public au CLI d'un autre
  repo, et échoue silencieusement si le CLI est absent du `PATH`.
- **Déléguer l'amorçage repo à `claude-md-management`** (Anthropic) : ce plugin audite des `CLAUDE.md`
  existants, il ne crée aucun fichier et ne connaît pas `AGENTS.md`.
- **Gabarits `.tpl` portés dans le plugin** : aucun code ne les lisait et ils étaient déjà en retard
  sur le rendu.

## Consequences

- Un `AGENTS.md` de workspace sans `CLAUDE.md` voisin ne se charge que si le réglage « Project
  instructions » est actif ; son défaut n'a pas été mesuré.
- Le hook ne fait rien sur un `python3` inférieur à 3.11 (pas de `tomllib`).
- Une section écrite à la main hors des blocs générés est remplacée à la réécriture ; le message du
  hook le dit quand cela se produit.
