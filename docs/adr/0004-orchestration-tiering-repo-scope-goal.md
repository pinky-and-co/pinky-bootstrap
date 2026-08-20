---
title: "0004"
---
# ADR-0004 — Pas de gate d'écriture bloquant ; tiering par `model:`, repo-scope par `freeze`, complétion par `/goal`
*Update date : 2026-08-20 10:03*
Status: accepted

## Context

Migration groupée (chantier 0023, `pinky-agentic-plugins`) de trois pièces couplées de
`pinky-workspace` (legacy, mort) : la skill `kanban` (mécanique du board), le hook `stop_handoff.py`,
et la commande `/chantier` (doit devenir une skill — un dossier `commands/` dans un plugin de ce repo
est un hard failure, `pinky-agentic-plugins/AGENTS.md` § Naming glossary).

Question soumise à un council-tech (5 advisors + 5 peer reviews + chairman-bis Mistral) : la session
orchestratrice doit-elle être strictement interdite d'écrire tant qu'aucun sous-agent n'est actif, ou
rester libre une fois qu'une décomposition + un tier sont posés dans la card ? Trois questions
complémentaires, posées après le council par l'utilisateur : (a) l'isolation repo par session
(read/write hors des repos concernés par la card), (b) le format du champ tier, (c) la mécanisation de
`/goal`.

**Contraintes connues** : plancher modèle validé empiriquement (2026-08-12) — `context: fork` +
`model:` clair en frontmatter plancherise réellement le modèle exécutant ; `Agent(subagent_type:
"fork")` hérite TOUJOURS du modèle de session. CodeBurn mesuré : Opus 79 % / Sonnet 21 % / Haiku ~0 %
du budget, `tier:` documentaire jamais mécanisé sur 18 commandes. `commit-and-pr` a remplacé un
fan-out par agents par un script bash déterministe. Un agent-wrapper sans raisonnement propre a été
abandonné au profit d'un MCP natif. Précédent déjà tranché pour les agents (2026-08-14) : `model:`
clair en frontmatter, jamais `tier:` + substitution — cette ADR étend le même principe aux cards.
Entête de card en frontmatter YAML déjà décidée le 2026-08-15 (`migration-des-24-rules-verdict-par-
fichier.md`) : cette ADR ne la redécide pas, elle y range le nouveau champ `model:`.
`permission-change` (`pc-core`) ne couvre que les outils d'écriture (`Edit`/`Write`/`MultiEdit`/
`NotebookEdit`) ; `permissions.deny` est la seule garantie dure mais s'applique au lancement de
session, pas dynamiquement en cours de session.

## Options evaluated

- **A — Interdiction stricte d'écriture** : hook `PreToolUse` refusant `Edit`/`Write` tant que
  `agent_id` est absent.
- **B — Gate d'entrée sur l'artefact** : hook `PreToolUse` qui n'autorise `Write` hors du fichier
  card qu'une fois le tier + décomposition présents dans la card active (proposée en variante
  temporaire/loggée par le chairman-bis Mistral).
- **C — Gate déclaratif, zéro hook** : discipline portée par la skill `kanban`, aucun mécanisme
  technique de blocage.
- **D — Vérification a posteriori, non bloquante** : aucun gate à l'écriture ; un signal compare
  après coup le modèle déclaré sur la card active au modèle réellement invoqué.
- **Read-scope dur** (question annexe) : étendre `guard.py` pour bloquer aussi `Read`/`Grep`/`Glob`
  hors des repos déclarés par la card active.

## Council verdict

**Convergence** : le levier réel du problème mesuré (CodeBurn) n'est pas qui a le droit d'écrire mais
quel modèle exécute — 4/5 advisors l'établissent indépendamment. Le tiering reste par card (le champ
existe déjà). La vérification sans raisonnement propre (tests, diffs) va en MCP natif, jamais en
agent nommé.

**Où le council s'affronte** : l'option B a été défendue par un advisor (Expansionist) et jugée la
réponse la plus solide par deux peer reviewers au premier tour — mais 4 des 5 reviewers,
indépendamment, ont ensuite montré qu'un gate d'entrée sur la présence d'un champ ne vérifie jamais
que le modèle réellement invoqué après déblocage correspond au tier déclaré : confond gate d'entrée et
garantie de sortie.

**Angles morts trouvés uniquement en peer review** :
1. Auto-arbitrage — si la session écrit elle-même le tier pour se débloquer, le gate est satisfait
   par l'acteur qu'il est censé contraindre.
2. Personne ne propose de vérification a posteriori (déclaré vs réellement observé).
3. Personne ne propose de mesurer avant de trancher.
4. Fiabilité de la lecture — un hook qui lit « la card en cours » doit vérifier que c'est la bonne
   card, pas une périmée ou d'un autre chantier.
5. Kanban writes ≠ code writes — une bonne part des `Edit`/`Write` de la session sont des mises à
   jour de cards/handoff, pas du code produit. Tout mécanisme d'écriture doit exempter `_KANBAN/**`.

**Chairman-bis Mistral** : converge sur tout sauf un point — recommande de construire l'option B,
reformulée comme mesure temporaire et loggée (2 semaines) pour trancher empiriquement. Le chairman
Claude ne retient pas cette version : même temporaire, elle reste vulnérable aux angles morts n°1 et
n°5 (bloque potentiellement l'édition d'autres cards que la card active dans le même tour). L'esprit
« mesurer avant de décider en dur » est retenu, porté par un mécanisme moins risqué : un log non
bloquant sur `stop_handoff.py`, qui tourne déjà à chaque tour, plutôt qu'un nouveau hook `PreToolUse`.

## Decision

**1. Aucun hook d'écriture bloquant lié au tiering.** Ni interdiction stricte (A), ni gate d'entrée
sur artefact (B, y compris sa variante loggée). La session orchestratrice garde tous ses outils
d'écriture.

**Correction post-council, vérifiée avant d'écrire le code (2026-08-20)** : le signal "tier déclaré
vs modèle réellement invoqué" envisagé pour `stop_handoff.py` n'est **pas implémentable** avec les
primitives de hook actuelles — un événement `Stop`/`SessionEnd` porte `session_id`, `cwd`,
`hook_event_name`, `stop_hook_active` ; aucun champ ne nomme le modèle qui a tourné ce tour, et aucun
`transcript_path` n'est documenté pour ces événements (`claude_docs/hooks-guide.md`, vérifié par
lecture directe). La vérification a posteriori reste la bonne intention (angles morts n°1/n°2 du
council), mais son mécanisme reste à trouver — pas un hook Stop seul. `stop_handoff.py` migre sans ce
signal ; la case reste ouverte plutôt que remplie par du code qui ferait semblant.

**2. Le champ tier devient `model:` en frontmatter YAML, alias direct, jamais un niveau à mapper.**
Même principe que la décision 2026-08-14 pour les agents (`model: haiku` en clair, pas `tier: fast` +
substitution) — étendu aux cards. Valeurs : `haiku` / `sonnet` / `opus` / `fable`. CLAUDE.md § Model
routing cesse d'être une table de mapping tier→modèle consultée par les cards ; il documente au plus
la convention de choix (quel travail va sur quel modèle), plus une résolution technique.

**3. Repo-scope par `freeze`, pas de blocage lecture.** `/chantier`, en prenant une card en
`3-in-progress`, invoque `permission-change freeze` scopé aux repos du champ `repos:` de la card.
Lecture non restreinte — décision explicite, pas un oubli : `permissions.deny` (seule garantie dure)
est session-start only, non togglable dynamiquement au moment où `/chantier` prend une card ; un hook
`PreToolUse` sur `Read`/`Grep`/`Glob` serait contournable en Bash brut (même théâtre de sécurité que
l'option B rejetée en décision 1) ; et le risque réel (contamination cross-repo) se matérialise à
l'écriture, pas à la lecture — une session a un besoin légitime de lire du contexte hors du scope
déclaré (corpus partagé, ADRs d'un autre repo, `CLAUDE.md` ancêtres) sans que ça constitue un risque
tant qu'elle n'y écrit rien.

**Amendement, vérifié en implémentant (2026-08-20)** : `repos:` déclare des slugs `org/repo` dérivés
du `git remote get-url origin` de chaque repo, jamais un nom de dossier nu — un nom collisionne
entre orgs (même défaut déjà noté pour l'identification d'org dans `kanban.md` § Orgs), le remote
non. `/chantier` résout chaque slug en chemin absolu via `resolve_repos.sh` (découverte bornée des
`.git`, même patron que `bulk_commit.sh::discover_repos`, jamais réinventé) — 0 ou >1 clone local
pour un slug est remonté en erreur, jamais deviné. Le freeze inclut aussi **toutes** les racines
kanban (`stop_handoff.py --list-kanbans`, déjà multi-board) : ce workspace a plus d'une racine
`_KANBAN` (locale + le board partagé PLUTO), une seule exemptée aurait laissé la session bloquée en
écriture sur l'autre dès qu'elle travaille une card de cet autre board.

**4. `/goal` mécanisé par `/chantier`, posé au niveau racine du groupe `sert:`.** En prenant une card,
`/chantier` résout son champ `sert:` :
   - `sert: null` (card racine, autonome) → `/goal` posé depuis le `Fini =` de cette card.
   - `sert: <parent>` (card enfant) → remonte à la card racine correspondante (`sert: null`), pose
     `/goal` depuis le `Fini =` **du parent**. La session traite ensuite librement les cards qui
     servent ce parent — le groupe est l'unité de session, pas la card isolée.
   Ça mécanise « 1 card (ou groupe `sert`) = 1 session », la session étant la ressource limitante
   réelle du travail. Conséquence : les lignes `Fini =` doivent être démontrables dans le transcript
   (résultat de test, diff réel), pas seulement vraies — `/goal` ne lit que le transcript, jamais un
   fichier ni une commande qu'il lancerait lui-même. Appliqué aux cards touchées par cette migration
   et aux nouvelles ; pas une réécriture rétroactive des cards existantes non touchées.

**5. Vérification qui demande du jugement (pas juste « lancer les tests ») → jamais la session
elle-même en premier recours.** La décision « MCP natif » plus haut ne couvrait que le zéro-
raisonnement. Complément, motivé par le même principe que le chairman-bis Mistral de ce council :
l'accord entre plusieurs voix du même modèle n'est pas une preuve, un même modèle self-check hérite
de ses propres angles morts. Ordre de préférence, jamais `haiku` quel que soit le palier :
   1. `adversarial` (MCP `pc-core`, natif) — modèle réellement d'une autre famille (Mistral
      aujourd'hui), le vrai changement de perspective, pas juste moins cher.
   2. `Agent(subagent_type: "reviewer")` — agent maison de `pc-core`
      (`plugins/pc-core/agents/reviewer.md`, préchargeant la skill `review-guidelines` — méthodologie
      distillée de l'ancien `review_brief`, pas de `feature-dev`, corrigé après un premier essai
      dans l'autre sens), zéro dépendance à un plugin externe installé. Même famille que la session
      génératrice, mais contexte frais (ne voit jamais son raisonnement auto-justificatif),
      `model: sonnet` réel dans sa propre définition.
   3. Review par la session elle-même — dernier recours, annoncé explicitement comme dégradé.

**6. `--advisor opus` au cadrage : câblé pour de vrai, `code-explorer`/`code-architect` refusés.**
Amendement du 2026-08-20 (`pinky-agentic-plugins` PR #15) — la décision 4 ci-dessus affirmait déjà
« `--advisor opus` au cadrage se mécanise dans la skill kanban », **faux tel qu'écrit** : jamais
câblé, trouvé en réconciliant la card idée d'origine
(`kanban-workflow-agentique-orchestrateur-sans-execution`) contre ce qui avait réellement été
livré, pas en le supposant depuis le texte de cette ADR. Corrigé : `/chantier` appelle l'outil
`advisor` une fois, au cadrage, quand `model: opus` sur la card — avant toute écriture, pendant que
le plan ne coûte encore rien à changer. `code-explorer`/`code-architect` (`feature-dev`) pour le
cadrage : **refusés** — les forcer retirerait à la session l'interactivité que la décision 1
ci-dessus a justement préservée ; `advisor` ajoute un second avis sans sortir la session de la
boucle.

## Consequences

**Gagné** : interactivité de la session main préservée intégralement ; mécanisme de preuve honnête
sur ses limites ; repo-scope réel (écriture) sans fausse promesse de confinement en lecture ; « 1
card/groupe = 1 session » devient un mécanisme natif (`/goal`) au lieu d'un principe à retenir de
mémoire ; champ `model:` sans couche d'indirection à maintenir.

**Sacrifié** : aucune garantie mécanique immédiate contre CodeBurn — le signal tier/modèle est
diagnostique, pas correctif ; si l'usage réel révèle un déséquilibre persistant, un gate plus dur
redevient une option à réexaminer avec des données plutôt qu'un raisonnement a priori. Le read-scope
dur reste hors scope : si un vrai incident de contamination cross-repo par lecture survient, cette
décision est à rouvrir avec ce fait nouveau, pas avant.
