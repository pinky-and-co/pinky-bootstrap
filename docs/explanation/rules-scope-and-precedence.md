# Portée de la convention — où une règle s'applique, et qui l'emporte
*Update date : 2026-10-03 17:15*

**L'endroit où une règle est installée détermine sa portée.** Appartenir à un plugin indique d'où elle *vient* ; le répertoire dans lequel elle atterrit indique où elle *s'applique*. Une règle de plugin installée dans un répertoire de groupe (`pinky-lib/.claude/rules/`) est inaccessible en dehors de celui-ci — ce qui est ce qui rend un `paths: **/*.py` large correct là plutôt que partout.

| Niveau | Source | Portée |
|---|---|---|
| `pc-core` | `rules/pc-core/` | l'ensemble du workspace |
| plugin | `rules/<plugin>/` | le répertoire où la CLI l'a installée |
| session | une instruction inline | le tour actuel, au-dessus de tout |

**En cas de contradiction : répertoire > plugin > `pc-core`, session au-dessus de tout.**

**Une rule de plugin ne se distribue que si le plugin est réellement installé.** `rules/<plugin>/`
n'atterrit nulle part par défaut — la cible est résolue depuis `~/.claude/plugins/installed_plugins.json`
(`setup.rules.resolve_targets_for_plugin`) : racine workspace si l'entrée a `scope: user`,
`projectPath` sinon. Un plugin jamais installé (l'user a répondu non à son installation, ou ne l'a
jamais lancée) → aucune cible → ses rules ne se distribuent nulle part, silencieusement. C'est
voulu : simuler le comportement qu'aurait `rules/` si elle pouvait voyager packagée dans le plugin
lui-même (elle ne peut pas, format absent) — pas de rule sans le plugin qui la justifie.

**Critère de rangement.** Une rule vit sous `rules/<plugin>/` **ssi elle est inerte ou absurde sans
l'outillage de ce plugin** (elle nomme ses skills/commands/hooks, ou son workflow) ; sinon elle
reste `rules/pc-core/` (discipline de raisonnement ou d'ingénierie tool-agnostique). Ex :
`snowpark.md` → `pc-snow` ; `verify-diagnosis.md`, `tests.md` → `pc-core`.

**Rule conditionnelle (`_load_conditions`).** Une source dont le frontmatter porte `_load_conditions`
(liste de propositions libres, validée par `_validated_conditions` dans `setup/rules.py` : non vide,
une ligne non vide par item, sans backtick) est distribuée en deux fichiers : un stub dans
`.claude/rules/` (même `paths:`, puis « Your FIRST action, <conditions jointes par " or ">, MUST be to
`Read` <chemin absolu du corps> in full. ») et le corps dans `.claude/rules-content/`, miroir purgé comme
`.claude/rules/`. Sans la clé, la rule est copiée telle quelle.

**Purge à périmètre global par cible.** Plusieurs plugins peuvent résoudre vers le même
`.claude/rules/` (tous les `scope: user` atterrissent à la racine workspace). Le mirror-purge de
`distribute_rules` ne supprime alors un fichier que s'il ne matche **aucune** source d'un plugin qui
résout vers cette cible (`distribute_all_plugin_rules` calcule l'union par cible). Conséquence : une
rule devient orpheline — et est nettoyée à la distribution suivante — quand son plugin est
désinstallé *et* qu'au moins un autre plugin cible encore ce répertoire ; un répertoire que plus
aucun plugin ne cible garde ses rules jusqu'à ce qu'un plugin le re-cible.

Mais la précédence est un filet, pas une solution. Deux règles se déclenchant sur la même portée avec des conseils opposés constituent un défaut à signaler, pas un cas à arbitrer — nommez les deux sources, appliquez la plus spécifique, et dites que vous l'avez fait.
