"""Shared paths — base layer for the setup package.

No imports from sibling setup/* modules (precommit.py, cli.py all depend on this one, never the
other way).
"""

import os
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PROVIDERS = ["claude", "mistral"]

PACKAGE_DIR = Path(__file__).parent.resolve()
SCRIPT_DIR = PACKAGE_DIR.parent

WORKSPACE_ROOT_ENV = "PINKY_WORKSPACE_ROOT"


DEFAULT_LAYOUT_ORIGIN = "default layout"


def _find_workspace_root_with_origin(start: Path) -> tuple[Path, str]:
    """`find_workspace_root`'s resolution, plus which of the three sources actually won —
    `resolve_workspace_root` needs the origin to print `Workspace: <path> (via <origin>)`."""
    env = os.environ.get(WORKSPACE_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve(), WORKSPACE_ROOT_ENV
    start = start.resolve()
    for base in [start, *start.parents]:
        markers = sorted(p for p in base.glob("*.code-workspace") if p.is_file())
        if markers:
            return base, str(markers[0])
    return SCRIPT_DIR.parent, DEFAULT_LAYOUT_ORIGIN


def find_workspace_root(start: Path) -> Path:
    """Workspace root — env ``PINKY_WORKSPACE_ROOT`` > nearest ``*.code-workspace`` above `start` > legacy.

    Args:
        start: Directory to walk up from — the caller's current directory in practice.

    Returns:
        The resolved workspace root. Falls back to ``SCRIPT_DIR.parent`` (the pre-ADR-0065
        behaviour) when no ``*.code-workspace`` file is found, so a moteur cloned inside its
        workspace keeps working with nothing configured.
    """
    return _find_workspace_root_with_origin(start)[0]


@dataclass(frozen=True)
class WorkspaceOrigin:
    """A resolved workspace root plus which source won it — the `Workspace: <root> (via <via>)`
    line every writing plugin command prints first."""

    root: Path
    via: str


def resolve_workspace_root(
    start: Path, explicit: str | Path | None = None
) -> WorkspaceOrigin:
    """The workspace root plus its origin label. Priority: `explicit` (a CLI `--workspace`) >
    `PINKY_WORKSPACE_ROOT` > the nearest `*.code-workspace` marker > the legacy install-layout
    fallback — the same order `_find_workspace_root_with_origin` already applies below `explicit`.
    """
    if explicit is not None:
        return WorkspaceOrigin(Path(explicit).expanduser().resolve(), "--workspace")
    return WorkspaceOrigin(*_find_workspace_root_with_origin(start))


WORKSPACE_ROOT = find_workspace_root(Path.cwd())

AGENTIC_HARNESS_DIR = SCRIPT_DIR / "agentic-harness"
HYGIENE_DIR = SCRIPT_DIR / "hygiene"

CORE_HOOKS_DIR = HYGIENE_DIR / "hooks"
CORE_PRECOMMIT_DIR = HYGIENE_DIR / "pre-commit"
CORE_CI_DIR = HYGIENE_DIR / "ci"
# Small utility modules shared by two plugins that end up split apart by the plugin boundary
# (a plugin can only ever import its own files — no relative reach into a `dependencies` entry).
# Vendored here rather than duplicated by hand so both copies stay provably identical.
CORE_VENDOR_DIR = HYGIENE_DIR / "vendor"

sys.path.insert(0, str(CORE_HOOKS_DIR))
from render_docs import (  # noqa: E402
    SuiteIdentity,
    _MarkdownParagraphs,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
    render_readme_why,
)


def engine_version() -> str:
    """The moteur's own version, from installed package metadata or its own `pyproject.toml`."""
    try:
        return metadata.version("pinky-bootstrap")
    except metadata.PackageNotFoundError:
        data = tomllib.loads(
            (SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8")
        )
        return data["project"]["version"]


__all__ = [
    "PROVIDERS",
    "PACKAGE_DIR",
    "SCRIPT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV",
    "DEFAULT_LAYOUT_ORIGIN",
    "find_workspace_root",
    "resolve_workspace_root",
    "WorkspaceOrigin",
    "AGENTIC_HARNESS_DIR",
    "HYGIENE_DIR",
    "CORE_HOOKS_DIR",
    "CORE_PRECOMMIT_DIR",
    "CORE_CI_DIR",
    "engine_version",
    "SuiteIdentity",
    "_MarkdownParagraphs",
    "inject_readme_sections_local",
    "has_generated_index",
    "render_index_home",
    "render_readme_why",
]
