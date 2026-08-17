---
title: "0001"
---
# ADR-0001 — `statusLine`/`subagentStatusLine`/`enabledPlugins` se rendent au niveau USER, jamais workspace
*Update date : 2026-08-17 11:27*

Status: accepted
Date: 2026-08-17

## Contexte

La hiérarchie de settings de Claude Code (user → project → local → managed) ne remonte ni ne
descend les répertoires parents — contrairement à `CLAUDE.md`, qui accumule sur toute la hiérarchie,
un `.claude/settings.json` ne s'applique que tant que le contexte de travail de la session est
exactement le répertoire qui le porte (déjà vérifié en concevant le flux d'install du CLI setup,
`_KANBAN/CHANTIER0023-migration-pinky-workspace/0-ideas/cli-setup-repo-lot1.md` entrée 4 décisions
transverses #1).

Une première version de cette même décision (14/08) plaçait `statusLine`, `subagentStatusLine` et
`enabledPlugins` au niveau **workspace** — au motif que rien ne devait rester caché dans
`~/.claude`. Ce motif confondait deux choses distinctes : du contenu propre à UN repo/workspace
(secrets, politique de projet — légitimement hors de `~/.claude`) et une préférence d'exécution
cross-session (le statusLine ne doit pas dépendre du repo dans lequel on se trouve).

**Vérifié empiriquement le 17/08** en lisant l'état réel de la machine : `~/.claude/settings.json`
porte `enabledPlugins`, `statusLine` et `subagentStatusLine` avec des chemins de script absolus ;
le `.claude/settings.json` du workspace pinky n'en porte aucun. C'est aussi ce que le port de
`pinky-bootstrap` avait déjà implémenté (`harness-hooks/` → `status-lines/`, « câblage réel de
`statusLine`/`subagentStatusLine` en chemin absolu », commits `827edaf`/`3c79927`) — la décision
workspace de `cli-setup-repo-lot1.md` n'a en réalité jamais été construite ainsi, et les deux
sources se sont contredites sans être recroisées jusqu'à cet ADR.

Rapporté à l'usage : ancré au niveau workspace/repo, le statusLine peut disparaître en cours de
session selon l'opération réalisée — tout contexte dont le répertoire résolu n'est pas exactement
celui qui porte le `.claude/settings.json` (un worktree, un sous-agent dont le contexte de travail
diffère) perd le réglage, faute de remontée dans la hiérarchie.

## Décision

`statusLine`, `subagentStatusLine` et `enabledPlugins` se rendent toujours dans le
`~/.claude/settings.json` **niveau user**, jamais dans un `.claude/settings.json` de workspace ou
de repo — quel que soit le mode du CLI qui rend (`--provider`, `--into`, un futur `pinky install`).

Le principe « rien de caché dans `~/.claude` » survit, restreint : il gouverne le contenu propre à
UN repo ou workspace (secrets, politique de projet, `.claude/policies.json`). Il ne s'applique pas à
une préférence dont la raison d'être est justement de rester stable, quel que soit le projet ouvert.

## Conséquences

- Le futur installeur state-file de `pinky-bootstrap` (`cli-setup-repo-lot1.md` entrée 4) doit cibler
  `~/.claude/settings.json` pour ces trois clés précisément, en fusion et jamais en écrasement — même
  discipline que l'ancien `_write_settings_json` appliquait déjà à `permissions.*`.
- `cli-setup-repo-lot1.md` entrée 4 décisions transverses #1 est corrigée sur place (17/08) pour
  pointer vers cet ADR plutôt que porter l'affirmation workspace périmée.
- `permissions.allow`/`permissions.deny` sont une question séparée (source = besoins déclarés par
  les skills/agents installés, pas un profil central — entrée 6 de la même card) et ne sont PAS
  tranchés par cet ADR ; seules les trois clés ci-dessus sont dans son périmètre.
