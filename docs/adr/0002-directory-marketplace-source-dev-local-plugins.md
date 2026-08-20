---
title: "0002"
---
# ADR-0002 — Marketplace `directory` en dev local pour les repos plugin, `github` pour la consommation
*Update date : 2026-08-21 00:48*

Status: proposé — mécanisme de bascule pas encore vérifié, voir § Conséquences
Date: 2026-08-18

## Contexte

Le plugin installé (`pc-commit@pinky-agentic-plugins`) résout depuis une marketplace source
`github` (`pinky-and-co/pinky-agentic-plugins`), synchronisée dans `~/.claude/plugins/cache/` et
`~/.claude/plugins/marketplaces/`. `claude plugin update` gate strictement sur `plugin.json.version`,
pas sur le SHA git — un fix mergé (PR #3, 17/08) est resté injoignable depuis `main` pendant un jour
entier faute de bump (vérifié empiriquement le 18/08 : `update` répond « already at the latest »
malgré le merge). Trois tentatives de contournement, dans l'ordre, toutes documentées ici pour ne
pas être retentées :

1. **Éditer le mirror `~/.claude/plugins/marketplaces/`** — faux : c'est une copie synchronisée par
   le mécanisme `claude plugin`, pas un working tree, même si elle a un remote git réel (source de
   confusion, elle se comporte comme un vrai clone jusqu'à ce qu'on essaie de la faire évoluer).
2. **`claude plugin uninstall`/`install` en CLI** — échec de scope (le plugin est activé via
   `.claude/settings.json` **projet**, pas juste « installé » — le CLI refuse de désinstaller sans
   changer ce fichier projet).
3. **Suppression manuelle du dossier cache** — pire que rien : `claude plugin update` a fait
   réapparaître un ancien snapshot local (`0.1.0`, encore avec le bug), pas un refetch GitHub. Cache
   réparé en resynchronisant directement depuis le vrai clone plutôt qu'en continuant à batailler
   avec le CLI.

Chasser ce contournement à la main, à chaque fix, produit exactement le double-écrit
cache-vs-repo que ce chantier (migration `pinky-workspace` → plugins natifs, `CHANTIER0023`) existe
pour supprimer.

## Décision

Pendant le développement actif d'un repo plugin, `~/.claude/settings.json` →
`extraKnownMarketplaces.<nom>.source` pointe sur une source `directory` — le clone de travail réel
sur cette machine (`bootstrap/<repo>/`) — au lieu de `github`. Éditer le clone puis lancer
`/reload-plugins --force` devient toute la boucle de dev : pas de cache à patcher séparément, pas de
version à penser à bumper, une seule source de vérité (git, dans le clone).

Rebasculer sur `github` avant de compter sur le chemin d'install/update normal pour quiconque
d'autre que cette machine — la source `directory` est une commodité **par machine, jamais commitée**
(elle vit dans `~/.claude/settings.json`, jamais dans un repo), pas un remplacement de la livraison
de vrais commits sur `main`.

**Niveau de cette décision** : org, pas repo. Elle s'applique identiquement aux trois repos plugin
(`pinky-agentic-plugins`, `pinky-agentic-plugins-private`, `pinky-bootstrap` lui-même) — d'où sa
place ici plutôt que dupliquée dans chacun. Un ADR local à un seul repo aurait figé une décision
transverse comme si elle n'engageait que ce repo-là (erreur commise une première fois le 18/08,
corrigée dans la foulée).

## Conséquences

- Itération locale rapide, zéro drift cache/version pendant cette phase.
- Le gate de version de `claude plugin update` devient hors-sujet pendant le dev actif — bumper
  `plugin.json` est réservé aux vrais jalons, jamais à chaque fix (même philosophie que `/release`
  pour les libs `pinky-*` : bump à un point de release délibéré, jamais à chaque commit).
- Éditer `extraKnownMarketplaces.<nom>.source` dans `~/.claude/settings.json` pour une marketplace
  déjà connue n'a pas toujours suffi seul (constaté le 18/08) — `claude plugin marketplace add
  <chemin-local>` (enregistrement frais) est le chemin fiable. `github` n'est de toute façon pas un
  type de source unique : `directory` en est un autre, pas une bascule spéciale à part.
- Fix ligne 9 (`allowed-tools`) de `commit-and-pr/SKILL.md` appliqué dans le clone
  `bootstrap/pinky-agentic-plugins/` (guillemets manquants autour de
  `${CLAUDE_PLUGIN_ROOT}/hooks/resolve_policy.py`, cause du rejet de permission sur
  `/pc-core:commit-and-pr --all`) — correct en soi, mais **pas encore livré** : toujours coincé
  derrière le même problème de propagation cache/source que le fix précédent.
- **Reste à faire, pas fait ici** : `pinky-agentic-plugins-private` n'est pas encore enregistrée
  comme marketplace du tout (vérifié dans `~/.claude/settings.json`, 18/08) — même traitement
  `directory` à appliquer quand quelqu'un itère activement dessus, pas avant.
