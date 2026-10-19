---
title: "0013"
---
# ADR-0013 — Le modèle et l'effort d'un subagent viennent d'un modèle de décision local, l'utilisateur tranche
Status: accepted
Date: 2026-10-19

## Context

Le modèle et l'effort d'un subagent étaient choisis par la session qui le lance, en fonction d'elle-même
et non de la tâche. Mesuré sur les transcripts (appels `Agent` des parents de la famille 5.5) :
`opus-5-5` délègue en `sonnet` dans 85 % des appels, `sonnet-5-5` reste en `sonnet` ou n'impose rien
dans 84 % ; `haiku` ne sert que dans 21 appels sur 331. Le `model:` d'une card était posé par la
session qui l'écrivait (91 % de `sonnet`), et l'`effort:` presque jamais.

Mesuré le 2026-10-18 sur Claude Code 2.1.302 : un hook `PreToolUse` sur `Agent` et un mod
`tool.call` réécrivent tous deux le `model`/`effort` d'un appel (`opus`/`high` demandé, `haiku`/`low`
lancé) ; une skill `context: fork` n'émet qu'un `Skill`, jamais un `Agent`.

## Decision

1. **Un mod `pc-core` retient chaque appel `Agent`/`Task`** (`hooks/subagent-routing/register.tsx`) et
   affiche dans la bande au-dessus du prompt la proposition d'un classifieur ; l'utilisateur choisit le
   modèle et l'effort au clavier, 60 s sans réponse envoient la proposition, une bande à la fois dans
   l'ordre d'arrivée, et là où la bande ne se dessine pas l'appel part aussitôt. Un agent dont la
   définition porte son propre `model:` et un `fork` passent tels quels. Le mod plutôt qu'un hook : la
   bande exige un mod, et il porte aussi la réécriture.
2. **Le classifieur est `clef-flash-4bit` via `POST /v1/systemone` d'oMLX** (`classify.py`, question
   `choice`, critères = la grille `grid.json`) : `routine` → `haiku`/`low`, `logic` → `sonnet`/`medium`,
   `hard` → `opus`/`high`. Les critères sont des signes lisibles dans le texte (tout est écrit ;
   décisions fixées mais code à lire ; quelque chose reste ouvert), pas des sujets.
3. **Seuil d'activation : battre le défaut seul de plus de 15 points** de catégories exactes contre la
   majorité d'un panel de trois modèles, sur deux échantillons de prompts et de cards réels. `clef`
   fait 65 % et 68 % pour 40 % et 43 % au défaut (+25), avec 1 et 2 erreurs de deux crans.
4. **Seul le classifieur écrit le `model:`/`effort:` d'une card** : à la fin du grill, ou par `select`
   quand la card n'en a pas ; une erreur du classifieur fait refuser `select`.
5. **Alternatives écartées** :
   - une table fixe par type d'agent : `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` le fait déjà, sans regarder
     la tâche ;
   - forcer des appels à l'`advisor` à des moments fixes : contraire à son principe, un appel automatique ;
   - les autres classifieurs mesurés : OpenJev-4B (59 à 65 % en grille v2, 3 à 4 erreurs de deux crans),
     Ornith-9B (62 à 63 %, et saturation mémoire d'oMLX à côté d'un autre modèle local), `mimo` du pool
     (45 %, 14 échecs), `codestral` (56 %, sous le défaut) ;
   - le seuil initial de 80 % exact et zéro erreur de deux crans : aucun candidat ne l'atteint sur des
     tâches neuves ; même un membre du panel ne rejoint sa majorité qu'à 80 à 86 %.

## Consequences

- La montée en gamme ne dépend plus du jugement de la session ; elle revient à l'utilisateur, qui voit
  chaque proposition avec le code couleur 🟦 haiku · 🟪 sonnet · 🟧 opus.
- Chaque lancement attend le classifieur (3,7 s en médiane) puis, sur le terminal ou le desktop, une
  touche de l'utilisateur ou 60 s.
- Un agent intégré sans fichier de définition (`Explore`, `claude-code-guide`) est retenu même s'il a
  son propre modèle : rien ne le dit au mod.
- `clef` ne remplace pas OpenJev pour `pii_guard` : il rate `v3_cartes_bancaires` (17/21 contre 19/21).
- `clef` est le meilleur de plusieurs candidats mesurés sur les mêmes deux échantillons, sans troisième
  échantillon tenu à l'écart ; la marge (+25 contre +15) absorbe ce biais de sélection.
- Le journal `~/.claude/pc-core/subagent-routing.jsonl` garde chaque décision (raison de sortie, erreur
  du classifieur, valeurs demandées et appliquées) pour régler la grille sur les résultats.
