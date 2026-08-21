# Portée de la convention — où une règle s'applique, et qui l'emporte
*Update date : 2026-08-21 01:22*

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

Mais la précédence est un filet, pas une solution. Deux règles se déclenchant sur la même portée avec des conseils opposés constituent un défaut à signaler, pas un cas à arbitrer — nommez les deux sources, appliquez la plus spécifique, et dites que vous l'avez fait.
