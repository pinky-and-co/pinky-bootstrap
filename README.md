# pinky-bootstrap

CLI + distribution of non-agentic hooks (ruff, pre-commit, CI templates) — the successor to
`pinky-workspace/setup.py`.

**This CLI starts where the plugin mechanism stops.** Anything a plugin manifest can declare is
authored and distributed as a plugin (`pinky-agentic-plugins`, `pinky-agentic-plugins-private`).
What lands here is what has no native slot — customisation presets such as output styles, themes
and rules — plus what is not agentic at all. That boundary is dated, not permanent: when the
manifest gains a slot, the artefact migrates out. See `AGENTS.md` § Scope boundary.
