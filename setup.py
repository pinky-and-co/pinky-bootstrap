#!/usr/bin/env python3
"""Configure a pinky workspace from a profile (profile-driven runner, Phase 3).

Usage (from workspace root):
    python pinky-workspace/setup.py                       # interactive → pinky profile
    python pinky-workspace/setup.py --provider claude     # alias for --profile pinky
    python pinky-workspace/setup.py --profile pinky        # render CLAUDE.md from a profile
    python pinky-workspace/setup.py --profile dayjob --output /tmp/CLAUDE.md

The runner renders core/CLAUDE.md.tpl by injecting values DERIVED FROM THE ACTIVE PROFILE:
    {{profile_name}}     →  profile.name
    {{knowledge_index}}  →  static routing list of the profile's knowledge_agents,
                            resolved against knowledge_roots and read lazily by path
                            (no MCP server — dropped, ADR-0006)
    {{behavior}}         →  profile.behavior (interaction-style knobs, ADR-0021)
    {{rules_overrides}}  →  profile.rules_overrides
    {{extras}}           →  profile.claude_md_extras
    {{model_*}}          →  profile.model_routing.{fast,default,thorough}

The hooks-distribution role (discover_repos / distribute / check_drift) is unchanged.

Implementation lives in the setup/ package (profile, leak_guard, precommit, cli — see the
split-setup-py-package kanban card); this file is a thin entrypoint only.
"""

from setup.cli import main

if __name__ == "__main__":
    main()
