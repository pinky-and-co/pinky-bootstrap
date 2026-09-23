---
title: "0008"
---
# ADR-0008 — `questionary` pour le picker interactif, plutôt que `curses`
*Update date : 2026-09-23 00:00*

Status: accepted
Date: 2026-09-23

## Contexte

Le tableau plugin × cible et le picker "quel(s) plugin(s)" (`setup/plugin_enable.py`) demandaient
de taper des indices en texte ("0 2 5") pour cocher une ligne — pas de flèches, pas d'espace pour
cocher, aucune couleur, aucun rendu en arbre pour les cibles imbriquées
(`bootstrap/pinky-agentic-plugins`). Verdict utilisateur en conditions réelles (2026-09-23,
`pinky claude-plugin install pc-kanban --dry-run`, 33 lignes à plat) : illisible.

`story.md` (grill 2026-09-19) posait "tableau en texte standard, sans bibliothèque de terminal" —
seule dépendance d'exécution retenue : `argcomplete`, pour l'autocomplétion. Une première
implémentation a exploré `curses` (stdlib, donc zéro dépendance ajoutée) pour la navigation clavier
et les couleurs. Deux frictions structurelles s'y sont heurtées :

- `curses` prend l'écran entier et gère lui-même son buffer de rendu — les codes ANSI que
  `setup/style.py` (`paint`, `GREEN`/`BOLD`/`DIM`) produit pour le reste de la sortie CLI n'y sont
  pas interprétés comme des attributs, juste affichés en tant que texte brut. Aucune réutilisation
  possible entre les deux, contrairement à l'exigence de la card ("pas un second jeu de codes
  ANSI").
- Naviguer/cocher/désélectionner avec flèches + espace + entrée, gérer les entrées non
  sélectionnables (nœuds d'arbre synthétiques), et couvrir emacs/vi keys est exactement le métier
  d'une bibliothèque de checkbox — la coder à la main en `curses` revient à réimplémenter ce
  qu'une lib fait déjà, le cas que la politique de dépendance de ce repo est censée éviter ("prendre
  une dépendance quand s'en passer revient à la réimplémenter").

## Décision

`questionary` (`questionary.checkbox`) remplace `curses` pour l'écran interactif :
flèches/j-k/emacs, espace pour cocher, entrée pour valider, choix pré-cochés, choix désactivés
(nœuds d'arbre sans cible propre) — tout nativement supporté. L'arbre des cibles imbriquées est une
simple indentation dans le titre de chaque choix (`"  " * depth`), pas un widget d'arbre séparé.

Toute la sortie non interactive (rapport des rules, plan `add`/`remove`/`unchanged`, confirmations
`Apply this plan? [y/N]` / `Applied.` / `nothing to do`) reste sur `setup/style.py` — stdlib,
inchangé par cette décision. `questionary` ne gouverne que l'écran de sélection lui-même
(`setup/tui.py`), jamais atteint hors terminal interactif (`sys.stdin.isatty()` vérifié par chaque
appelant avant tout appel).

## Conséquences

- Deux dépendances d'exécution déclarées (`pyproject.toml`) : `argcomplete` et `questionary`, cette
  dernière amenant `prompt_toolkit` (et `wcwidth`) en transitif.
- `setup/tui.py` expose `ChecklistItem` (texte, profondeur d'indentation, coché, sélectionnable,
  clé de correspondance) et `run_checklist(items, title=...) -> list[bool]` (Ctrl-C remonte en `KeyboardInterrupt`, sortie 130) — la logique pure
  (construction des lignes, indentation par segment de chemin, correspondance retour) reste dans
  `setup/plugin_enable.py`, testable sans terminal ; `questionary.checkbox` lui-même n'est jamais
  exercé par la suite de tests (le point d'extension `run_checklist` est remplacé par un faux).
- Alternative rejetée : `curses` — un widget de checkbox défilant fait à la main, à maintenir,
  incapable de réutiliser `setup/style.py`, et qui prend l'écran entier (le résultat disparaît du
  scrollback une fois l'écran restauré) contrairement au rendu inline de `questionary` (la réponse
  reste visible, comme `pinky doctor`).
