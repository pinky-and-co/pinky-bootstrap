---
title: "0010"
---
# ADR-0010 — Rules paresseuses : stub présenté, contenu lu à la demande, lecture autorisée par `permissions.allow`
*Update date : 2026-10-10 21:24*

Status: accepted
Date: 2026-10-10

## Context

Les rules du workspace étaient toutes injectées au démarrage de chaque session et de chaque
sous-agent. Mesuré sur les sessions antérieures au 2026-10-01 : 9 192 octets de rules par transcript
pour `main`, 9 654 pour `pc-core:reviewer`, 10 546 pour `pc-kanban:card-worker`.

Le distributeur de rules (`setup/rules.py`) livre désormais une rule portant `_load_conditions` en
deux fichiers :

- un **stub** `.claude/rules/<règle>.md`, 166 à 257 octets : « Your FIRST action, if
  `<conditions>`, MUST be to `Read` `<chemin>` in full » ;
- le **contenu** `.claude/rules-content/<règle>.md`.

Un stub sans `paths:` est présenté à chaque session ; un stub à `paths:` l'est quand la session lit
un fichier correspondant. Les conditions sont du texte libre, donc jugées par le modèle.

Mesuré sur les sessions du 2026-10-03 21:00 au 2026-10-10 (`tools/rules_load_report.py`) :

| Acteur | Octets avant | Octets après | Écart |
|---|---|---|---|
| `main` | 9 192 | 3 201 | −65 % |
| `pc-core:reviewer` | 9 654 | 908 | −91 % |
| `pc-kanban:card-worker` | 10 546 | 5 241 | −50 % |
| `general-purpose` | 7 121 | 706 | −90 % |

Stub présenté → contenu lu, toutes sessions : `tests` 70 → 41, `minimal-code` 70 → 40,
`no-history-in-artifacts` 207 → 31, `verify-diagnosis` 207 → 19, `apply-convention` 207 → 3,
`doc-hygiene` 7 → 5. Pour `pc-kanban:card-worker` (sonnet, 31 sessions) : `tests` 24 → 21,
`no-history-in-artifacts` 31 → 10, `verify-diagnosis` 31 → 3, `apply-convention` 31 → 0.

Un défaut de glob a montré la fragilité des règles à `paths:` : `plugins/**/hooks/**`, sans `**/` en
tête, ne correspondait à aucun fichier depuis la racine du workspace (les repos vivent sous
`bootstrap/<repo>/plugins/`). Le stub de `hook-output-invariants` n'a été présenté dans aucune des
9 sessions qui ont écrit des hooks, quand ceux de `tests` et `minimal-code` l'étaient dans les 9
pour les mêmes fichiers.

Le contenu n'est lu que si la lecture est autorisée sans confirmation. Sans permission, chaque
`Read` d'un contenu de rule demande une validation, et la rule n'est pas lue.

## Decision

1. **Le mécanisme est conservé** : stub présenté, contenu lu à la demande, conditions en texte libre
   dans `_load_conditions`. Les trois rules à `paths:` (`adr`, `doc-hygiene`,
   `hook-output-invariants`) le gardent ; tout glob de `paths:` commence par `**/`.
2. **La permission de lecture est une clé user** posée par la distribution des rules : son plan
   propose `permissions.allow` dans `~/.claude/settings.json` derrière le `[y/N]` habituel, et une
   machine neuve l'obtient quand `pinky install` enchaîne cette distribution. Aucune étape manuelle
   hors du CLI.
3. **Son périmètre est le workspace** :

   ```json
   "permissions": { "allow": ["Read(~/Workspaces/pinky/**/.claude/rules-content/**)"] }
   ```

Les points 2 et 3 sont posés sans écrire de code : aujourd'hui la clé se règle à la main. Ils
valent comme direction ; un ADR ultérieur les remplace si l'implémentation montre un meilleur lieu.

## Consequences

- Gain mesuré de 50 à 91 % des octets de rules par transcript selon l'acteur.
- Une rule n'est suivie que si le modèle va lire son contenu : mesuré, c'est loin d'être
  systématique pour les rules à condition sémantique (`no-history-in-artifacts`,
  `verify-diagnosis`, `apply-convention`, présentées à toutes les sessions et lues dans 15, 9 et
  1,4 % d'entre elles). Rien dans ce mécanisme ne garantit la lecture ; le prompt de
  `card-worker` ne cite aucune rule.
- Un stub à `paths:` dépend de son glob : un glob mal ancré ne se charge jamais, sans erreur.
- Sans la clé `permissions.allow`, le mécanisme dégrade silencieusement : stub présenté, contenu
  jamais lu.
- La mesure compte des octets et des lectures, pas l'utilité d'une lecture. Une mesure à 5 essais
  par condition n'a pas été menée ; les lectures réelles d'une semaine l'ont remplacée.
