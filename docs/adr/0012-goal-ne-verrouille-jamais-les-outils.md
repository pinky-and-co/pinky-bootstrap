---
title: "0012"
---
# ADR-0012 — Un `/goal` ne verrouille jamais les outils ; amender = prouver l'impossibilité
Status: accepted
Date: 2026-10-16

## Context

ADR-0004 §4 fait poser le `/goal` par `/chantier`. Pour qu'un agent ne travaille pas sans goal, le skill
mettait la clé `goal` en file d'attente (`pc_kanban_pending_user_action.py require goal … --surfaced`) et
le hook `PreToolUse` `pending_gate.py` (plugin `pc-autodiscovery`) la traitait comme `deny` : tout appel
d'outil était refusé, `AskUserQuestion` et les lectures comprises, jusqu'à ce que l'utilisateur colle la
ligne `/goal`. L'amendement d'un goal passait par le même chemin.

Mesuré dans une session réelle (transcript, 155 lignes) : après un amendement, 6 fins de tour rejetées par
le Stop hook de `/goal`, 4 refus d'outils (`prek`, `git status`, `AskUserQuestion`), et la même demande
« colle cette ligne » répétée à chaque tour. Rejoué dans un dépôt jetable avec un goal contradictoire :
3 tours, écritures refusées, goal terminé en échec.

La documentation de Claude Code décrit un autre mécanisme :

- `/goal` est un Stop hook à prompt, propre à la session ; un modèle juge la condition à chaque fin de
  tour : non atteinte, atteinte, ou **impossible** (le goal s'efface alors seul).
- « If a goal is already active, the new one replaces it » : amender, c'est lancer `/goal <nouvelle>`.
- Sans appel d'outil pendant plusieurs tours, la boucle s'arrête et rend la main (goal conservé) ; un
  Stop hook qui bloque 8 fois de suite sans appel d'outil est écrasé.
- Une condition se borne par une clause (`or stop after 20 turns`) ; `/goal clear` arrête un goal.

Le verrou fabriquait exactement les tours sans appel d'outil que ces garde-fous attendent, et chaque tour
forcé ne pouvait que répéter la demande.

## Decision

1. **`goal` sort de `DENY_KEYS`** dans `pending_gate.py` : seul `reload-plugins` verrouille encore les
   outils. Le skill `chantier` ne met plus aucune clé `goal` en file ; il clôt sa réponse par le bloc
   `/goal <condition>` en texte brut.
2. **Amender** : l'agent expose dans la transcription pourquoi la condition ne peut pas tenir, avec la
   preuve (l'évaluateur rend « impossible » et efface le goal), donne la ligne amendée en texte brut, et
   continue ce que l'amendement ne change pas. La clause d'échappement est supprimée.
3. **Chaque goal est borné** (`or stop after <N> turns`, 20 par défaut) et suit la forme de la doc : un état
   mesurable, la vérification qui le prouve, les contraintes utiles.
4. **La sortie de l'utilisateur est `/goal clear`.** Le skill ne la déconseille plus.
5. **Alternatives écartées** : garder le verrou en corrigeant seulement le Stop hook (le verrou reste la
   cause de la boucle) ; passer `goal` en `ask` (une invite oui/non ne peut pas recevoir une commande `/`) ;
   garder la clause d'échappement (elle contournait un défaut que la doc règle par le verdict « impossible »).

## Consequences

- Plus de session murée par un goal : l'amendement coûte 1 tour au lieu de 3 ou plus (mesuré : 11 s sur
  `haiku`, outils actifs, une seule demande).
- Un agent peut travailler après avoir affiché une ligne `/goal` que l'utilisateur n'a pas encore collée,
  donc sans le goal prévu ; le garde-fou n'existe plus, la borne de tours limite l'écart.
- `reload-plugins` garde son `deny` : sans rechargement, le travail suivant s'exécuterait sur un jeu de
  plugins périmé.
- Un fichier d'état `~/.claude/pinky/plugin-scope/<session>.pending.json` contenant déjà une clé `goal`
  passe désormais par la branche `ask` du gate, sans verrou.
- Un seul scénario a été rejoué en conditions réelles (goal contradictoire simple) ; un cycle de card
  complet ne l'a pas été. Complète ADR-0004 §4 sans le remplacer.
