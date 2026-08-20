---
title: "0005"
---
# ADR-0005 — `CLAUDE.md`/`AGENTS.md` : import ou symlink selon le niveau, comme prévu au sketch §4.1
Status: accepted
Date: 2026-08-20

## Context

`03-mini-plugin-sketch.md` §4.1-4.2 pose déjà la règle et sa table par niveau : import par défaut,
symlink seulement quand le contenu du niveau est vérifié neutre — jamais l'inverse. Le niveau repo y
est classé candidat symlink (branche, glossaire — déjà largement neutre, illustré en §5) ; le niveau
workspace reste import (contenu vérifié Claude-spécifique : table de commandes, model routing).

§4.3 documente un blocage non résolu : le symlink n'est testé que localement sur macOS/iCloud. Sur
Windows (mode développeur ou privilège admin + `git config core.symlinks` requis côté client), un
symlink mal posé se checkoute comme un fichier texte contenant le chemin cible au lieu d'un vrai
lien — non vérifiable depuis cette machine pour les repos PLUTO partagés (mount Windows du frère).

Une première version de cet ADR proposait d'abandonner le symlink partout (import partout par
défaut) pour éviter ce risque. Écarté : le symlink est la convention standard pour ce cas d'usage
(citée par la doc Claude Code elle-même), et le risque ne concerne qu'une machine précise sur un
sous-ensemble de repos — pas une raison de renoncer à la simplicité du symlink pour tout le parc.

## Decision

**On garde la table du sketch §4.1-4.2 telle quelle** : workspace = import (`@AGENTS.md` + section
Claude-only), repo = symlink, org = à trancher une fois du contenu réel écrit à ce niveau.

Le risque Windows/PLUTO reste une **limite documentée**, pas un changement de design : à vérifier
concrètement sur la machine du frère avant d'onboarder un repo PLUTO partagé au générateur, pas avant.

## Consequences

- Le générateur écrit `CLAUDE.md` = `@AGENTS.md` au niveau workspace, et un symlink
  `CLAUDE.md → AGENTS.md` au niveau repo — conforme à la table du sketch, aucune branche
  supplémentaire à inventer.
- Un repo PLUTO partagé onboardé avant vérification Windows peut checkouter un `CLAUDE.md` cassé sur
  cette machine spécifique — risque accepté, à vérifier avant d'onboarder ces repos précisément, pas
  bloquant pour le reste du parc.
- Le générateur n'écrase jamais un `CLAUDE.md` existant qui n'est ni un symlink ni un import généré
  par lui (contenu hand-authored détecté, laissé intact).
