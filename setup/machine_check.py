"""Machine check (--check-machine) — visibility for ambient, undeclared local capabilities.

Card `capacites-ambiantes-non-declarees`: `npx wrangler login` installed 13 skills into
`~/.claude/skills/` with nothing in the moteur aware of it — no banner, no report, an agent that
behaves differently on a third-party machine with no signal saying why.

Most machine capabilities (Cortex Code, a PyPI account) are undetectable by construction, which is
why `MACHINE_CAPABILITIES` is DECLARED rather than sniffed (see its own comment in common.py).
Skills and plugins are the exception: they sit on disk, so they are the one class of "ambient
capability" this check CAN make visible. It deliberately does not try to reconcile skill/plugin
names against declared `machine_capabilities` entries — those are two different vocabularies
(installed-artefact names vs. routing tags), and inventing a mapping between them is a decision for
whoever needs the routing (see card checklist items 4-5), not something a visibility check should
guess at. `machine:` stays purely declarative (ADR-0059).

Never a gate: `--check-machine` always exits 0. The card's own scope is visibility, not elimination
(checklist item 6) — an ambient skill is not necessarily unwanted, and this repo has no reference
list of what a machine "should" have to compare against.
"""

import json
from pathlib import Path

from .common import MACHINE_CAPABILITIES

# The harness's OWN user-level config dir — distinct from `<workspace>/.claude/` or `<repo>/.claude/`
# (this engine's rendered output, see profile.py), which is a different directory entirely.
CLAUDE_USER_DIR = Path.home() / ".claude"


def _local_claude_skills(claude_dir: Path) -> list[str]:
    """Skill names installed at user level — one per `<claude_dir>/skills/<name>/` subdirectory."""
    skills_dir = claude_dir / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def _local_claude_plugins(claude_dir: Path) -> list[str]:
    """Plugin ids (`<name>@<marketplace>`) installed at user level, read from the harness's own
    `plugins/installed_plugins.json` ledger — more reliable than walking its cache dir, which may
    hold stale or partially-removed versions the ledger no longer lists."""
    manifest = claude_dir / "plugins" / "installed_plugins.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    return sorted(plugins) if isinstance(plugins, dict) else []


def check_machine(claude_dir: Path = CLAUDE_USER_DIR, *, quiet: bool = False) -> int:
    """Print declared vs. ambient capabilities; return the count of ambient items found."""
    say = (lambda *_a, **_k: None) if quiet else print
    say("\nMachine check — ambient capabilities vs. declared machine_capabilities")
    say("=" * 52)
    say(
        "Declared (machine_capabilities — trusted, most are undetectable by construction):"
    )
    if MACHINE_CAPABILITIES:
        for cap in sorted(MACHINE_CAPABILITIES):
            say(f"  ✓ {cap}")
    else:
        say("  (none declared)")

    skills = _local_claude_skills(claude_dir)
    plugins = _local_claude_plugins(claude_dir)
    ambient = len(skills) + len(plugins)
    say("\nAmbient — found locally, not reflected in machine_capabilities:")
    if not ambient:
        say("  (none found)")
        return 0

    for name in skills:
        say(f"  skill   {name}")
    for name in plugins:
        say(f"  plugin  {name}")
    say(
        f"\n{ambient} ambient item(s) — visibility only. Declare a machine_capabilities entry in "
        ".pinky/config.txt if a framework artefact should route on this machine having it "
        "(ADR-0059)."
    )
    return ambient
