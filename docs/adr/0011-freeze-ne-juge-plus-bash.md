---
title: "0011"
---
# ADR-0011 — `freeze` ne juge plus `Bash` : le garde d'écriture Bash est supprimé
Status: accepted
Date: 2026-10-16

## Context

ADR-0004 §3 cale une session worker sur les repos de sa card par `permission-change freeze`. Le
plugin `pc-kanban` y ajoutait un garde sur `Bash` (`bash_write_escapes`, dans
`skills/permission-change/scripts/guard.py`) : une heuristique de texte qui demandait confirmation
pour une commande ressemblant à une écriture hors du périmètre gelé.

Mesuré sur des sessions réelles :

- **Faux positifs sur les plugins.** Un script de plugin lancé sous un freeze demandait
  confirmation. Deux causes : `git` lu dans un nom de chemin (`pc-git/…`), puis toute la ligne jugée
  dès qu'un mot d'écriture y figure (`mv … ; bash <script> <dossier>`). Rejeu de 791 commandes qui
  touchent un chemin de plugin : chemin de plugin signalé 123 fois avec le garde de `main`, 17 fois
  après correction, toutes des écritures réelles dans un dossier de plugin. Dans une session de
  travail, trois commandes de board ou de plugin ont demandé confirmation.
- **Aveugle à l'essentiel.** Le garde juge du texte : un script qui écrit lui-même, une variable ou
  `python -c` ne passent jamais par lui.
- **Redondant avec Claude Code.** Confirmation des écritures hors du dossier de travail (élargie par
  `additionalDirectories`, où sont déjà les boards), règles de permission par chemin et par
  commande, sandbox au niveau du système, classifieur du mode `auto`. Pour un worker sur un seul
  repo, le périmètre gelé (repo + boards) égale dossier de travail + `additionalDirectories`.

## Decision

1. **Le garde Bash du freeze est supprimé**, avec son outil de mesure `guard_replay.py` et leurs
   tests. `freeze` et `deny` ne gardent que `Edit`, `Write`, `MultiEdit` et `NotebookEdit` ;
   `careful` (confirmation des commandes Bash destructives) est inchangé.
2. **Une garantie dure sur `Bash`** passe par `permissions.deny` ou le sandbox de Claude Code, pas
   par un hook de texte.
3. **Alternatives écartées** :
   - corriger la regex (cible d'écriture seule, exemption des dossiers de plugin) : chaque
     correctif déplace la frontière sans la fermer, et l'exemption des plugins laisserait une session
     gelée réécrire le garde lui-même par Bash alors qu'`Edit` le bloque ;
   - le garder derrière un interrupteur : du code et ~500 lignes de tests que personne n'exécute en
     production ;
   - une liste blanche de chemins de plugin : un nouveau plugin redemande la même exception.

## Consequences

- Plus aucune confirmation du freeze sur une commande Bash, scripts de plugin et commandes de board
  compris.
- Une écriture Bash hors du périmètre gelé n'est plus signalée par le freeze : seuls les réglages
  natifs de Claude Code (mode `auto`, `permissions`, sandbox) la couvrent.
- `freeze` sur `Edit` / `Write` reste utile quand le dossier de travail est plus large que la cible
  (session orchestrateur à la racine du workspace, calée sur les boards par `orchestrator_freeze.py`)
  et pour une card à plusieurs `repos:`. Non mesuré ici.
- Le code supprimé se retrouve dans le dépôt `pinky-agentic-plugins`, aux commits `8cf5c3a` et
  `8a58d23` ; la suppression est le commit `fa6b098`, qui se retire seul avec `git revert`.
