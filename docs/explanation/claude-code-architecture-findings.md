# Claude Code — architecture skills/plugins/forks : synthèse des tests et décisions
*Update date : 2026-08-21 00:16*

*Rassemble ce qui a été testé empiriquement (rig de test minimal par question, fichiers marqueurs
explicites, `/context` avant/après, transcripts de sous-agents) et les sources utilisées — sert de
référence pour toute question sur le comportement réel de skills/plugins/forks/CLAUDE.md, plutôt
que de re-tester à chaque session.*

---

## 1. Décisions d'architecture

### 1.1 Skills vs commandes legacy
Les commandes personnalisées (`.claude/commands/`) ont été fusionnées dans les skills. Un fichier
`.claude/skills/<name>/SKILL.md` fait tout ce que faisait `.claude/commands/<name>.md`, plus :
un répertoire pour les fichiers de support, un contrôle fin de qui peut invoquer (utilisateur,
modèle, ou les deux), et le chargement à la demande du contenu complet.

### 1.2 Frontière skill / agent custom
- **Skill** = le contenu (procédure, étapes, jugement à appliquer).
- **Agent** = l'environnement d'exécution (prompt système, outils, modèle, mode de permission).
- Un agent custom n'a de valeur que s'il apporte une restriction/comportement que la skill ne
  peut pas exprimer elle-même (`model:`, `allowed-tools:` couvrent déjà beaucoup de cas).

Trajectoire suivie sur `/commit` dans ce fil :
`agent: gitmoji` (agent custom avec `tools:` restreints → a bloqué le commit réel, cf. §3.2)
→ `agent: skill-fork` (agent générique quasi vide → comportement identique à `general-purpose`
sur tout ce qui a été testé, donc inutile)
→ `agent: general-purpose` directement, toute la logique (langue, convention) rapatriée dans
`SKILL.md`.

### 1.3 Découplage "rules + knowledge" → skills
L'ancien mécanisme (`knowledge.md`, table de routage manuelle vers des `AGENT_*.md`) est remplacé
par une skill par domaine, avec le `description` de la skill faisant le travail de routage à la
place de la table.

### 1.4 Pas de mécanisme de fusion entre plugins
Aucun mécanisme de dépendance ou de fusion n'existe entre deux plugins/skills — chacun est un
artefact autonome. Conséquence directe pour la migration :
- Une valeur **résolue par profil** (ex. langue de chat, branche par défaut) ne doit jamais être
  codée en dur dans une skill destinée à être publique — sinon elle fuit une conviction privée
  dans un artefact générique.
- La bonne coupe : la skill publique porte une **instruction générique** (« suis la politique de
  langue du `CLAUDE.md`/`AGENTS.md` le plus proche »), la valeur elle-même vit dans un niveau
  supérieur (workspace/groupe/repo), jamais dans le corps de la skill.
- Une skill ne doit pas présupposer qu'une autre skill est installée à côté (pas de chemin relatif
  du type `${CLAUDE_SKILL_DIR}/../autre-skill/`). Si la skill sœur existe et est pertinente, la
  découverte automatique par `description` s'en charge ; sinon, prévoir un filet de secours
  autonome dans la skill elle-même plutôt qu'une dépendance dure.

### 1.5 Fan-out plutôt que récursion en chaîne
Pour `/commit --all` (traiter N repos), deux architectures possibles :
- **Récursion en chaîne** (`/commit` → `/commit repo_1` → `/commit repo_2` → ...) : chaque
  itération ajoute un niveau de profondeur. La limite de profondeur des sous-agents est **fixe à
  5, non configurable** — ça plafonne silencieusement le mode bulk à ~4 repos.
- **Fan-out** (le fork initial génère directement N enfants, tous au même niveau) : tous les
  enfants sont à la même profondeur, peu importe leur nombre. **C'est l'architecture retenue.**

### 1.6 Phase A (proposer) / Phase B (exécuter)
Pour éviter la duplication de logique entre le mode single-repo et le mode bulk, et pour permettre
une confirmation unique malgré le fan-out :
- **Phase A** : collecte, analyse, construit la proposition (message, base de PR) — n'exécute rien.
- **Phase B** : exécute, seulement après confirmation.
- En bulk mode : chaque enfant fait tourner Phase A seule, un tableau est compilé à partir des
  propositions, une seule confirmation couvre tout le batch (commits + PRs), puis chaque enfant est
  **repris** (`SendMessage`, pas un nouvel appel) pour Phase B — sans jamais relire la convention
  ni le diff.

---

## 2. Ce qui a été testé empiriquement, et les résultats

### 2.1 Isolation d'un fork — historique de conversation
**Test** : mémoriser un mot secret + lire un fichier en session principale, puis invoquer une
skill forkée dont la tâche demande explicitement si elle connaît ce secret/ce fichier.
**Résultat** : `SECRET-CHECK: no`, `FILE-CHECK: no` — confirmé, un sous-agent nommé (pas le fork
spécial `CLAUDE_CODE_FORK_SUBAGENT`) ne voit ni l'historique de conversation, ni les fichiers déjà
lus ailleurs.

### 2.2 Isolation d'un fork — coût en tokens
**Test** : le fork lit et traite un fichier de ~4800 mots en interne, ne renvoie que 5 lignes de
résumé. `/context` mesuré avant et après.
**Résultat** : delta de +2.9k tokens, entièrement absorbé par la catégorie "Messages" — aucune
fuite proportionnelle à la taille du fichier traité. L'isolation protège réellement la fenêtre de
contexte de la session principale, pas seulement la conversation.

### 2.3 Héritage du CLAUDE.md par un fork
**Test** : `CLAUDE.md` avec un marqueur texte à la racine du rig, skill forkée (`agent:
general-purpose`) invoquée sans jamais lire ce fichier explicitement.
**Résultat** : `CLAUDE-CHECK: yes`, marqueur cité correctement — confirme qu'un sous-agent nommé
autre que `Explore`/`Plan` charge bien CLAUDE.md au démarrage.

### 2.4 Résolution du modèle par tier
**Test** : `model: claude-haiku-4-5` déclaré dans `SKILL.md`, session principale sur Sonnet.
**Résultat** : le fork tourne bien sur Haiku, confirmant que `model:` du `SKILL.md` prime sur le
modèle de la session principale (pas juste un héritage passif).

### 2.5 Accumulation vs remplacement des CLAUDE.md multi-niveaux
**Test** : un fork touche successivement 2 repos différents (chacun avec son propre `.git` et son
propre `CLAUDE.md` marqueur), dans la même invocation.
**Résultat** : les deux marqueurs restent visibles simultanément — accumulation, pas de
remplacement. Un troisième marqueur (workspace-root) est aussi apparu de façon inattendue : le
fork charge la hiérarchie CLAUDE.md complète depuis la racine du workspace jusqu'à son point
d'exécution, pas seulement depuis le niveau où vit la skill.

### 2.6 Découverte de skills/CLAUDE.md/rules imbriqués sans `--add-dir`
**Test** : session ouverte à la racine du workspace (jamais dans un repo — usage réel), descente
progressive en touchant des fichiers sous `org_1/` puis `org_1/repo1/` (son propre `.git`).
**Résultat** :
- La skill imbriquée (`org_1/.claude/skills/...`) devient disponible dès qu'un fichier sous
  `org_1/` est touché — confirmé via l'attachment `dynamic_skill`.
- La rule path-scoped (`paths: ["**/*.py"]`) d'`org_1` se déclenche bien en touchant un `.py`
  **à l'intérieur** de `repo1`, malgré la frontière `.git` propre à ce repo — confirmé via
  l'attachment `nested_memory`.
- `repo1/CLAUDE.md` se charge également à la demande dans les mêmes conditions.
- **Conclusion** : la frontière `.git` ne bloque que la **remontée** (`repo1` comme point de
  départ de session) — pas la **descente** (session ouverte plus haut, qui descend
  naturellement). Pour un usage où on ouvre toujours au niveau du workspace, aucun `--add-dir`
  n'est nécessaire. Même principe retenu pour `.claude/settings.json` — voir ADR-0001.

### 2.7 Test réel de `/commit --all` (fan-out + reprise + PR par stratégie de branche)
**Setup** : 3 repos de test, chacun avec un `CLAUDE.md` déclarant une stratégie de branche
différente (`Branching: Git Flow` / `GitHub Flow` / `Trunk-Based Development`), une skill
`branch_workflow` de référence (nommage + les 6 stratégies), `commit/SKILL.md` scindé en
Phase A / Phase B.
**Résultat** :
- Fan-out confirmé : 3 enfants générés (`spawnDepth: 2`), tous parentés par le même fork initial
  (`spawnDepth: 1`) — pas de chaîne récursive.
- Résolution de la base de PR sans valeur en dur : `develop` proposé pour le repo en Git Flow,
  `main` pour les deux autres — chaque enfant a bien lu le `CLAUDE.md` de **son propre** repo.
- Une seule confirmation a couvert commits + PRs pour tout le batch.
- Reprise via `SendMessage` fonctionne concrètement : le message apparaît côté enfant sous forme
  d'un message système (« Another Claude session sent a message while you were working »), pas
  d'un nouvel appel — l'enfant exécute Phase B avec le contexte déjà construit en Phase A.
- **Écart constaté** : dans ce run précis, un enfant n'a jamais lu le fichier de convention
  `references/AGENT_GITMOJI.md` malgré l'instruction explicite — le message proposé restait
  plausible mais non ancré dans le fichier réel. À surveiller/renforcer.
- **Écart constaté** : le repo avec deux changements sans rapport (censé être classé
  "ambiguous" et exclu du batch) a été committé en un seul message quand même — la classification
  mécanique/ambiguous n'a pas fonctionné comme prévu sur ce cas.
- **Point d'amélioration identifié** : Claude a demandé une clarification pour des fichiers de
  bruit connus (`.DS_Store`) au lieu de trancher seul (ajout silencieux au `.gitignore`, jamais
  inclus dans un commit). Un cas typique de « résous, ne reporte pas » à corriger dans `SKILL.md`.

---

## 3. Bugs / divergences connues entre Claude Code CLI et l'extension VSCode

### 3.1 Marker de skill forkée absent en VSCode
Deux sessions identiques (même `SKILL.md`, `context: fork`), une en CLI, une dans l'extension
VSCode : le fichier `.forked-skill.marker.json` du sous-agent est présent en CLI, **absent** en
VSCode — alors que l'exécution fonctionne dans les deux. Recoupe un ticket GitHub existant
(dispatch de skill forkée cassé côté extension, deferred-tools non appliqués aux sous-agents
forkés — voir §5, `anthropics/claude-code` issue #58535, toujours ouverte au moment du test, sans
commentaire ni PR liée).

### 3.2 `tools:` d'un agent custom prime sur `allowed-tools:` de la skill
Un agent custom (`gitmoji.md`) avec `tools:` restreint à la lecture seule (pas de `git add`/`git
commit`) a bloqué silencieusement le commit réel, même si `allowed-tools:` de `SKILL.md` listait
bien ces commandes. Confirmé : `allowed-tools:` **pré-approuve**, il n'étend jamais le pool
d'outils réel — celui-ci vient de l'`agent:` choisi. Un agent custom sans `tools:` du tout hérite
de tout le pool de la session parente (comportement équivalent à `general-purpose`).

### 3.3 Autocomplete de la palette `/` ne reflète pas les skills imbriquées dans VSCode
Une skill imbriquée (`org_1/.claude/skills/...`) fonctionne correctement à l'invocation dans les
deux surfaces (CLI et VSCode), mais **n'apparaît pas** dans la palette `/` de l'extension VSCode —
alors qu'elle apparaît en CLI après traversée du répertoire. Recoupe des tickets GitHub connus
(mécanisme d'exécution et mécanisme d'affichage de la palette découplés dans l'extension). Ne pas
se fier à la palette VSCode comme source de vérité sur ce qui est réellement chargé — utiliser
`/context`.

### 3.4 Paramètre `language` de `settings.json`
Réglage global et binaire (une seule langue pour toute la session) — ne peut pas représenter une
politique multi-axes (ex. langue du chat ≠ langue des messages de commit). Ne pas l'utiliser pour
un besoin qui varie par type de sortie ; garder l'instruction générique pointant vers le niveau
AGENTS.md/CLAUDE.md pertinent à la place (cf. §1.4).

### 3.5 Cache de préfixe sur sous-agents forkés — vérifié non affecté
Un bug connu (`anthropics/claude-code` issue #29966) documente une désactivation en dur du cache
de préfixe pour les sous-agents. Mesuré directement sur le test §2.7/§4.1 : 85.8% de hit rate
global sur les 5 agents — soit ce bug ne s'applique pas à ce cas d'usage (fork + `SendMessage`),
soit il a été corrigé depuis. Résultat empirique, pas une simple déduction de la doc.

---

## 4. Points vérifiés depuis (mise à jour) / restants à tester

### 4.1 Coût réel de la reprise via `SendMessage` — vérifié
Mesuré directement sur les 5 sous-agents du test §2.7 (mêmes IDs), via calcul du cache
(`cache_creation` / `cache_read`) sur les transcripts :

| Agent | Rôle | Appels | Cache write | Cache read | Hit rate |
|---|---|---|---|---|---|
| `a6f3ec30...` | `/commit --all` (orchestrateur) | 35 | 78k | 667k | 89.5% |
| `a178b87b...` | Phase A repo1 | 26 | 67k | 423k | 86.4% |
| `a4c1bb5b...` | Phase A repo2 | 22 | 60k | 354k | 85.5% |
| `a328105e...` | Phase A repo3 | 19 | 49k | 301k | 85.9% |
| `aec6d05f...` | `/commit` isolé (hors batch) | 2 | 34k | 0 | 0% |
| **Total** | | | **288k** | **1,74M** | **85.8%** |

**Conclusion** : 85.8% de hit rate global — la reprise via `SendMessage` ne recharge pas
l'historique complet à froid à chaque tour, elle bénéficie bien du cache de préfixe partagé
(skill + convention + contexte déjà construit en Phase A). Le seul agent à 0% (`aec6d05f...`) est
un run isolé hors batch (`/commit` sans `--all`, 2 appels seulement) — cohérent avec un premier
appel froid sans rien à réutiliser, pas un signe de régression. Impact marginal (34k sur 1,74M
de cache_read total).

### 4.2 Restant à tester
- Fiabilité de la classification mécanique/ambiguous en Phase A (cf. §2.7, écart constaté sur un
  cas réel).
- Lecture garantie du fichier de convention (`references/AGENT_GITMOJI.md`) par chaque enfant en
  Phase A — observé manquant sur au moins un run.
- Comportement de `--max-depth` de `rg` sur la vraie profondeur d'arborescence de la nouvelle org
  (valeur de travail à ajuster si la structure réelle diffère).

---

## 5. Sources et documentation utilisées

**Documentation Claude Code officielle**
- Skills — création, frontmatter, cycle de vie, `context: fork` :
  https://code.claude.com/docs/fr/skills
- Sous-agents personnalisés — portée, outils, `tools:` vs `allowed-tools:`, résolution du modèle,
  ce qui se charge au démarrage, reprise (`SendMessage`), forks :
  https://code.claude.com/docs/fr/sub-agents
- Plugins — structure, `.claude-plugin/plugin.json`, migration depuis config autonome :
  https://code.claude.com/docs/fr/plugins
- Settings files — scopes user/project/local, résolution à la racine du repo git :
  https://code.claude.com/docs/en/configuration.md
- Bonnes pratiques de création de skills (concision, divulgation progressive, workflows,
  évaluation) : https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

**Blog / articles Anthropic**
- Steering Claude Code — skills, hooks, rules, subagents, output styles, quand utiliser quoi :
  https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more

**Exemple de plugin officiel réel**
- `claude-md-improver` (templates de sections pour un CLAUDE.md/AGENTS.md de projet) :
  https://github.com/anthropics/claude-plugins-official/blob/main/plugins/claude-md-management/skills/claude-md-improver/references/templates.md

**Issues GitHub (`anthropics/claude-code`) — divergences CLI/VSCode**
- #58535 — dispatch de skill forkée cassé dans l'extension VSCode (deferred-tools / allowed-tools
  non appliqués aux sous-agents forkés) : https://github.com/anthropics/claude-code/issues/58535
- #24439 — sous-agents custom indisponibles dans l'extension VSCode
- #58556 — skills de projet absentes de l'autocomplete slash-command dans VSCode (fonctionnent
  programmatiquement, non découvrables dans l'UI)
- #40640 — découverte automatique de `.claude/skills/` imbriqués ne fonctionnant pas comme
  documenté (testé CLI + VSCode, mars 2026)
- #29966 — cache de préfixe désactivé en dur pour les sous-agents (vérifié non applicable au cas
  fork + `SendMessage`, cf. §3.5/§4.1 — à revérifier si un autre pattern de sous-agent est utilisé)

**Source externe (référencée par la skill `branch_workflow`)**
- Article sur les 6 stratégies de branching Git :
  https://dev.to/trinitezinsou/maitriser-la-gestion-des-branches-avec-git-3ikh
