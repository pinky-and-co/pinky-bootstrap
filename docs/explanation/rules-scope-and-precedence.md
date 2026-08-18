# Convention scope — where a rule applies, and who wins

**Where a rule is installed decides its scope.** Belonging to a plugin says where it *comes from*;
the directory it lands in says where it *applies*. A plugin rule installed in a group directory
(`pinky-lib/.claude/rules/`) is unreachable outside it — which is what makes a broad `paths: **/*.py`
correct there rather than everywhere.

| Level | Source | Scope |
|---|---|---|
| `core` | `rules/core/` | the whole workspace |
| plugin | `rules/<plugin>/` | the directory where the CLI installed it |
| session | an inline instruction | the current turn, above everything |

**On contradiction: directory > plugin > `core`, session above all.**

But precedence is a net, not a solution. Two rules firing on the same scope with opposite advice is
a defect to report, not a case to arbitrate — name both sources, apply the more specific one, and
say that you did.
