# pinky-bootstrap

CLI + distribution of non-agentic hooks (ruff, pre-commit, CI templates) — the successor to
`pinky-workspace/setup.py`.

**This CLI starts where the plugin mechanism stops.** Anything a plugin manifest can declare is
authored and distributed as a plugin (`pinky-agentic-plugins`, `pinky-agentic-plugins-private`).
What lands here is what has no native slot — customisation presets such as
rules — plus what is not agentic at all. That boundary is dated, not permanent: when the
manifest gains a slot, the artefact migrates out. See `AGENTS.md` § Scope boundary.

## Install

Prerequisites: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/pinky-and-co/pinky-bootstrap
pinky --help
```

The plugins this CLI installs and configures live in
[`pinky-agentic-plugins`](https://github.com/pinky-and-co/pinky-agentic-plugins).
