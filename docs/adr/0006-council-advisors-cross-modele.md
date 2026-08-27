---
title: "0006"
---
# ADR-0006 — Council : advisors sur modèles distincts du pool, pas sur personas d'un seul modèle
*Update date : 2026-08-27 20:27*
Status: accepted

## Context

Chantier 0023 fusionne les quatre skills council (`llm-council`, `council-pitch`, `council-tech`,
`council-suite`) en un skill unique `council` paramétré par un argument `type`, distribué par le
plugin générique public. Le cadrage (interview `grill`, 2026-08-27) est consigné dans la story du
chantier, section *Council*.

Une décision antérieure, **archivée `4-done`** —
`_KANBAN/_ARCHIVE/CHANTIER0001-done/2026-08-09_council-voix-cross-modele.md` — avait tranché la
question « les voix advisor doivent-elles être plusieurs modèles ? » par **non** : advisors sur
personas d'un seul modèle (lentilles de pensée), diversité inter-modèles réservée au seul slot
chairman (« chairman-bis » : rejouer le prompt de synthèse sur un second modèle et diffuser les deux
verdicts). Trois motifs : le slot juge est le plus fort levier de biais ; asymétrie de capacité entre
modèles ; budget d'un pool payant unique.

Cette décision reposait sur une prémisse explicite et datée : **« un seul modèle tiers est
branché »**. Cette prémisse a expiré — un pool multi-fournisseurs couvrant plusieurs familles
distinctes existe désormais, résolu par le même `settings.pinky.json` ascendant que le reste, et
toutes ses entrées sont sans coût marginal.

## Options evaluated

- **A — statu quo de la card `4-done`.** Advisors = personas d'un seul modèle ; cross-modèle au
  chairman-bis uniquement.
- **B — advisors cross-modèle.** Chaque lentille s'exécute sur un modèle distinct du pool quand
  celui-ci fournit assez d'entrées éligibles joignables ; le contrôle croisé au chairman est
  **conservé** ; fallback vers des personas d'un seul modèle pour toute lentille non couverte, tracé
  comme tel.

## Decision

**Option B.** La méthodologie de référence (LLM Council de Karpathy) dispatche nativement sur
plusieurs modèles ; les personas-lentilles d'un seul modèle étaient un substitut faute de pool, pas
le design cible. Des trois motifs de la card `4-done` :

- **Budget** — caduc, constaté : toutes les entrées du pool sont sans coût marginal.
- **Asymétrie de capacité** — motif réel, retenu et **mitigé, pas ignoré** : le rôle advisor n'est
  attribué qu'aux entrées de tier `opus`/`sonnet` ; le transcript logue le tier par lentille ; le
  chairman ne reçoit que la lentille, jamais le modèle ni le tier — une divergence reste donc
  attribuable à la lentille ou au modèle, jamais confondue avec un simple écart de qualité.
- **Slot juge** — motif retenu : le contrôle croisé du chairman n'est pas supprimé. Le design cible
  est advisors cross-modèle **et** chairman-check, pas l'un à la place de l'autre.

Transport : un tool MCP dédié du serveur de routing modèle, distinct du tool de revue adverse (pas
d'injection de posture), qui dispatche en parallèle vers N entrées du pool et lit sa sélection depuis
le pool, jamais depuis le skill.

## Consequences

- Gagné : la section « accord du council » d'un verdict mesure enfin une convergence entre familles
  de modèles, pas seulement le prior partagé d'un seul.
- Accepté : le confound de capacité résiduel, géré par attribution (tier logué, chairman aveugle au
  modèle) et non éliminé.
- Nouvelle surface à maintenir : le tool de dispatch parallèle et sa fonction de sélection
  (déterministe, testée par oracle).
- Surface d'egress élargie — la question framée part vers plusieurs fournisseurs tiers au lieu d'un.
  Garde-fou : un seul consentement d'egress avant dispatch listant les fournisseurs cibles, refus →
  100 % personas ; un sujet en scope sensible force le fallback sans même demander.
- Politique fournisseurs : la liste de bannissement de `_KANBAN/_FACTS.md` vise les systèmes de
  production, pas un appel one-shot isolé de R&D — périmètre désormais explicite dans ce fichier.

### Condition de réouverture

Cette décision **revient à l'option A** si une comparaison mesurée — même question framée, même
gabarit de sortie, chemin routé vs chemin personas, jugée sur la qualité du verdict final — montre
que le chemin routé dégrade la qualité plutôt que de l'améliorer. La fidélité à Karpathy est un
argument d'autorité, pas une mesure ; seul l'effondrement du motif budget est mesuré. Tant que la
comparaison n'est pas faite, B tient sur ces deux bases (fidélité + budget), et sur rien d'autre.
