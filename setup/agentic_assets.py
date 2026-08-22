"""setup/agentic_assets.py — install an output-style or theme onto this machine.

Both are plain files this repo already carries (`agentic-harness/output-styles/*.md`,
`agentic-harness/themes/*.json`) — no plugin-declarable slot exists for either today (unlike
`agent`/`subagentStatusLine`, see `plugin_scope.py`), so this repo's CLI is the only installer.
Once `pinky-bootstrap` is cloned (the `curl | bash` bootstrap's only job — Entrée 4 point 1), the
source is already local: a copy, not a second GitHub fetch. Same merge-never-overwrite discipline
as `plugin_scope.enable_plugin` for the `~/.claude/settings.json` key, same ledger
(`setup.state_file`) as everything else `pinky install` writes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import state_file
from .common import AGENTIC_HARNESS_DIR

OUTPUT_STYLES_DIR = AGENTIC_HARNESS_DIR / "output-styles"
THEMES_DIR = AGENTIC_HARNESS_DIR / "themes"


@dataclass
class Asset:
    """One installable output-style or theme.

    `name` is the lookup key for `--output-style`/`--theme NAME` — the file's own stem, cheap to
    type. `value` is what actually gets written to `outputStyle`/`theme` in settings.json — NOT
    always the same string (verified against the real schema/a live install, 2026-08-21):
    outputStyle takes the frontmatter's own `name:` field (case-sensitive — the real value in use
    on this machine is `ADHD`, not the filename `adhd`); theme takes `custom:<name>` (schema:
    `theme` is an enum of built-ins OR a string matching `^custom:.*` — a bare name matches
    neither).
    """

    name: str
    path: Path
    description: str
    value: str


def _frontmatter_fields(path: Path) -> dict[str, str]:
    """Read every `key: value` line from a `.md` file's YAML frontmatter — `{}` if none.

    Same shape as `profile._command_description` (not imported — that one is commands-only in
    spirit, and duplicating a short loop beats a cross-concern import here), generalized to grab
    `name:` alongside `description:` in one pass.
    """
    fields: dict[str, str] = {}
    in_frontmatter = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            m = re.match(r"^(\w+):\s*(.+)$", line)
            if m:
                fields[m.group(1)] = m.group(2).strip()
    return fields


def discover_output_styles() -> list[Asset]:
    """Every `agentic-harness/output-styles/*.md` this repo carries, with its description."""
    if not OUTPUT_STYLES_DIR.is_dir():
        return []
    styles = []
    for p in sorted(OUTPUT_STYLES_DIR.glob("*.md")):
        fields = _frontmatter_fields(p)
        styles.append(
            Asset(
                name=p.stem,
                path=p,
                description=fields.get("description", ""),
                value=fields.get("name", p.stem),
            )
        )
    return styles


def discover_themes() -> list[Asset]:
    """Every `agentic-harness/themes/*.json` this repo carries, with its description."""
    if not THEMES_DIR.is_dir():
        return []
    themes = []
    for p in sorted(THEMES_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        themes.append(
            Asset(
                name=p.stem,
                path=p,
                description=data.get("description", ""),
                value=f"custom:{data.get('name', p.stem)}",
            )
        )
    return themes


# Always user scope, unlike a plugin (`plugin_scope.py`'s whole wizard exists because a plugin
# CAN apply at workspace/group/repo depth) — outputStyle/theme are cross-session chat preferences,
# the same axis statusLine already settled on (ADR-0001, `pinky-bootstrap`). No root/depth
# parameter here: there is only one place these can meaningfully live.
_USER_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _install(*, asset: Asset, target_dir: Path, settings_key: str) -> Path:
    """Shared copy + settings-key-merge + ledger-record for one asset. Returns the installed path."""
    target = target_dir / asset.path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(asset.path.read_bytes())

    _USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.loads(_USER_SETTINGS_PATH.read_text(encoding="utf-8"))
        if _USER_SETTINGS_PATH.is_file()
        else {}
    )
    data[settings_key] = asset.value
    _USER_SETTINGS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    state_file.record_posed(
        settings_key, path=str(_USER_SETTINGS_PATH), value=asset.value
    )
    return target


def install_output_style(name: str) -> Path:
    """Copy `<name>.md` to `~/.claude/output-styles/` and set `outputStyle` in settings.json."""
    matches = [a for a in discover_output_styles() if a.name == name]
    if not matches:
        raise ValueError(f"no output-style named {name!r} in {OUTPUT_STYLES_DIR}")
    return _install(
        asset=matches[0],
        target_dir=Path.home() / ".claude" / "output-styles",
        settings_key="outputStyle",
    )


def install_theme(name: str) -> Path:
    """Copy `<name>.json` to `~/.claude/themes/` and set `theme` in settings.json."""
    matches = [a for a in discover_themes() if a.name == name]
    if not matches:
        raise ValueError(f"no theme named {name!r} in {THEMES_DIR}")
    return _install(
        asset=matches[0],
        target_dir=Path.home() / ".claude" / "themes",
        settings_key="theme",
    )
