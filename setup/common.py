"""Shared paths, corpus resolution and profile loading — base layer for the setup package.

No imports from sibling setup/* modules (profile.py, leak_guard.py, precommit.py, cli.py all
depend on this one, never the other way).
"""

import os
import sys
import tomllib
from importlib import metadata
from pathlib import Path

PROVIDERS = ["claude", "mistral"]

# This package lives at <workspace-root>/pinky-workspace/setup/ — one level deeper than the
# former setup.py, so SCRIPT_DIR (= pinky-workspace/) needs the extra .parent to stay correct.
PACKAGE_DIR = Path(__file__).parent.resolve()
SCRIPT_DIR = PACKAGE_DIR.parent
# The corpus location (knowledge/ + profiles/) is resolved through corpus_roots() so the moteur can
# consume an external corpus (ADR-0010). What ships with the moteur — `corpus-public/` — is the base
# of that resolution and is code-side (DEFAULT_CORPUS_ROOTS, ADR-0069), never declared.

# ── Workspace root — resolved, NEVER derived from the install path (ADR-0065) ─────────────────
# WORKSPACE_ROOT used to be `SCRIPT_DIR.parent`, i.e. "whatever sits above wherever this code was
# unpacked". That only ever worked because the moteur is cloned INSIDE the workspace it serves.
# Installed anywhere else (`uv tool install`, a pipx venv, site-packages), the same expression
# points at the install prefix — and discover_repos(), which globs WORKSPACE_ROOT, then scans
# site-packages and finds zero repos. Nothing failed loudly; the distribution simply became a no-op.
#
# So the workspace announces ITSELF — by the nearest `*.code-workspace` file above the CURRENT
# DIRECTORY, the VSCode multi-root convention that already exists wherever this moteur runs — and
# the moteur finds it by walking up. No bespoke marker to create or maintain.
WORKSPACE_ROOT_ENV = "PINKY_WORKSPACE_ROOT"


def find_workspace_root(start: Path) -> Path:
    """Workspace root — env ``PINKY_WORKSPACE_ROOT`` > nearest ``*.code-workspace`` above `start` > legacy.

    Args:
        start: Directory to walk up from — the caller's current directory in practice.

    Returns:
        The resolved workspace root. Falls back to ``SCRIPT_DIR.parent`` (the pre-ADR-0065
        behaviour) when no ``*.code-workspace`` file is found, so a moteur cloned inside its
        workspace keeps working with nothing configured.
    """
    env = os.environ.get(WORKSPACE_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    start = start.resolve()
    for base in [start, *start.parents]:
        if any(p.is_file() for p in base.glob("*.code-workspace")):
            return base
    return SCRIPT_DIR.parent


WORKSPACE_ROOT = find_workspace_root(Path.cwd())

# Two source roots, split by what they are — not one `core/` mixing both (2026-08-20 reorg):
# agentic-harness/ = content a Claude Code session loads (rules, status-lines) ; hygiene/ = non-
# agentic repo tooling (ci, hooks, pre-commit) this CLI distributes into consumer repos.
AGENTIC_HARNESS_DIR = SCRIPT_DIR / "agentic-harness"
HYGIENE_DIR = SCRIPT_DIR / "hygiene"

# ── Hooks distribution (hygiene/ = single source) ────────────────────────────
CORE_HOOKS_DIR = HYGIENE_DIR / "hooks"
# Harness (Claude Code) hooks — distinct from the git pre-commit hooks in CORE_HOOKS_DIR.
# Installed to <claude_dir>/scripts/ and wired into settings.json (see _install_status_lines).
CORE_HARNESS_HOOKS_DIR = AGENTIC_HARNESS_DIR / "status-lines"
CORE_PRECOMMIT_DIR = HYGIENE_DIR / "pre-commit"
CORE_CI_DIR = HYGIENE_DIR / "ci"

# render_docs.py renders the repo-local README/index.md sections (badges/tagline/documentation/
# license). It is distributed as-is into every repo's scripts/hooks/ so the `generate-docs` commit
# hook can run it without the full workspace — importing it here too means setup.py and the hook
# share one render implementation, never two (see the generate-docs-hook kanban card).
sys.path.insert(0, str(CORE_HOOKS_DIR))
from render_docs import (  # noqa: E402
    SuiteIdentity,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
    render_readme_why,
)


# ── Engine version — never derived from git (card `versionner-le-moteur`) ─────────────────────
# `importlib.metadata` reads the installed distribution's own metadata (written by hatchling from
# pyproject.toml's `version` at build time) — the only source that works once the moteur is
# `uv tool install`-ed and SCRIPT_DIR points inside a venv, not a checkout. Falls back to parsing
# `pyproject.toml` straight off disk for the still-common case this repo is itself run from: a
# plain clone via `python3 setup.py`, never `pip install`-ed, so there is no distribution to query.
def engine_version() -> str:
    """The moteur's own version, from installed package metadata or its own `pyproject.toml`."""
    try:
        return metadata.version("pinky-bootstrap")
    except metadata.PackageNotFoundError:
        data = tomllib.loads(
            (SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8")
        )
        return data["project"]["version"]


# Each <corpus root>/profiles/<name>/profile.yaml carries the rigor dial (layers.agent /
# layers.hooks) plus knowledge / model / multi-agent config. A profile is resolved by name
# across the corpus roots (see load_profile + corpus_roots), so it travels with its corpus.


# =============================================================================
# Corpus location — the MOTEUR is agnostic to where the CORPUS lives (ADR-0010)
# =============================================================================
# The MOTEUR (core/ + setup.py + docs/) is decoupled from the CORPUS — the AGENT_*.md knowledge
# and the profiles/<name>/ that select it. The corpus is resolved through an ORDERED list of
# "corpus roots", each a directory that may hold `knowledge/` and/or `profiles/<name>/`.
#
# Resolution:
#   env CORPUS_ROOT  — REPLACES everything. os.pathsep-joined dirs, absolute or SCRIPT_DIR-relative.
#   otherwise        — DEFAULT_CORPUS_ROOTS (the code's own, unconditional).
#
# `corpus-public` is a CONSTANT, not a configuration line: its position relative to the moteur is
# fixed by the repository itself. It used to be declared in a committed `corpus-roots.txt`, which was
# a roundabout way of saying it never varies — and which had to be force-included in the wheel to
# survive packaging. The code says it better, and cannot forget to ship.
#
# It is a BASE, never a fallback, and that distinction is the whole point. The previous shape
# (`if roots: return roots` before touching the default) meant any machine declaring an instance root
# would have lost `corpus-public` the moment it stopped being declared — private profiles still
# resolving, public knowledge silently gone. See tests/test_corpus_roots.py.
#
# A profile's `knowledge_roots` entry may itself be ABSOLUTE (pointing at an external corpus
# repo); it is then used as-is, bypassing the corpus-root search. That is what ultimately lets
# the corpus live in its own repo (the moteur only needs a pointer to it).
#
# This block is the ONLY consumer of corpus location. The hooks distribution (discover_repos /
# distribute / check_drift) never reads it — it stays bound to core/ and is untouched.
CORPUS_ROOT_ENV = "CORPUS_ROOT"
# SCRIPT_DIR itself is NOT a root: `knowledge/` and `profiles/` moved under `corpus-public/` with
# ADR-0012, so listing the moteur root would resolve nothing and only add a dead entry to the
# "Corpus roots searched" line of an error message.
DEFAULT_CORPUS_ROOTS = [SCRIPT_DIR / "corpus-public"]


def _parse_root_list(raw_items: list[str]) -> list[Path]:
    """Parse path entries (env-split) into resolved dirs; skip blanks/`#`.

    Args:
        raw_items: Path entries, one per element. A relative entry resolves against SCRIPT_DIR —
            right for the ``CORPUS_ROOT`` env var, an explicit override typed by someone who knows
            where the code is.

    Returns:
        Resolved directories, in input order, blanks and comments dropped.
    """
    base = SCRIPT_DIR
    roots: list[Path] = []
    for item in raw_items:
        item = item.strip()
        if not item or item.startswith("#"):
            continue
        p = Path(item).expanduser()
        roots.append(p.resolve() if p.is_absolute() else (base / p).resolve())
    return roots


def corpus_roots() -> list[Path]:
    """Ordered corpus search roots — env CORPUS_ROOT, else DEFAULT_CORPUS_ROOTS.

    ``CORPUS_ROOT`` (env) *replaces* the whole thing: an explicit override means "use exactly this".
    """
    env = os.environ.get(CORPUS_ROOT_ENV)
    if env:
        roots = _parse_root_list(env.split(os.pathsep))
        if roots:
            return roots
    return list(dict.fromkeys(p.resolve() for p in DEFAULT_CORPUS_ROOTS))


def owning_corpus_root(profile_path: Path) -> Path | None:
    """The corpus root a profile belongs to — ``<root>/profiles/<name>/profile.yaml`` → ``<root>``.

    Derived from the layout `load_profile` itself builds, so no caller has to configure it and no
    instance literal enters the moteur. It is what lets a **control** (`--check-public`) scope
    itself to the corpus it ships with, rather than to whatever this machine happens to mount: a
    verdict that differs per machine proves nothing about the artefact under test.

    Args:
        profile_path: Resolved path of a profile.yaml.

    Returns:
        The owning root, or None when the path does not have the canonical shape (a profile passed
        as an arbitrary path). None is a caller decision point — never a silent two-levels-up guess.
    """
    parents = profile_path.resolve().parents
    if len(parents) < 3 or parents[1].name != "profiles":
        return None
    return parents[2]


def _display_path(resolved: Path) -> str:
    """Workspace-relative path when the file lives under WORKSPACE_ROOT, else absolute.

    Keeps routing links clean for a colocated/in-repo corpus and stays correct (absolute)
    once the corpus lives in an external repo outside the workspace.
    """
    abs_path = resolved.resolve()
    try:
        return str(abs_path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(abs_path)


def load_profile(profile_arg: str) -> tuple[dict, Path]:
    """Load a profile.yaml by path or by name (profiles/<name>/profile.yaml).

    Returns (data, resolved_path). pyyaml is imported lazily so the default
    distribution path stays dependency-free; only the --profile path requires it.
    Proves the profile parses on load.
    """
    try:
        import yaml  # lazy: only the --profile path needs it
    except ModuleNotFoundError:
        print("--profile requires pyyaml (pip install pyyaml).")
        sys.exit(1)

    candidate = Path(profile_arg)
    if not candidate.is_file():
        # treat the argument as a profile name → <corpus root>/profiles/<name>/profile.yaml
        for cr in corpus_roots():
            maybe = cr / "profiles" / profile_arg / "profile.yaml"
            if maybe.exists():
                candidate = maybe
                break
    if not candidate.is_file():
        print(f"Profile not found: {profile_arg}")
        print(f"Tried as path and as <corpus root>/profiles/{profile_arg}/profile.yaml")
        print(f"Corpus roots searched: {', '.join(str(c) for c in corpus_roots())}")
        sys.exit(1)

    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"Invalid YAML in {candidate}: {exc}")
        sys.exit(1)
    if not isinstance(data, dict) or "name" not in data:
        print(f"Profile {candidate} is missing required key: name")
        sys.exit(1)
    return data, candidate


def iter_profiles() -> list[tuple[dict, Path]]:
    """Every profile.yaml discoverable across the corpus roots, as (data, resolved_path).

    Lets the leak guard source private profiles' declared leak signatures without ANY hardcoded
    profile name — the profile marked `visibility: private` owns its own patterns, so a new private
    instance is protected with no core edit. pyyaml is imported lazily (only the guard/profile
    paths need it); a profile that fails to parse (or a missing corpus) is skipped, never fatal.
    """
    try:
        import yaml  # lazy: keep the dependency-free distribution path clean
    except ModuleNotFoundError:
        return []
    seen: set[Path] = set()
    out: list[tuple[dict, Path]] = []
    for root in corpus_roots():
        for pf in sorted((root / "profiles").glob("*/profile.yaml")):
            resolved = pf.resolve()
            if resolved in seen:
                continue  # same corpus reachable via two roots — count it once
            seen.add(resolved)
            try:
                data = yaml.safe_load(pf.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue  # a broken profile is not the guard's problem — skip it
            if isinstance(data, dict):
                out.append((data, pf))
    return out


__all__ = [
    "PROVIDERS",
    "PACKAGE_DIR",
    "SCRIPT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV",
    "find_workspace_root",
    "AGENTIC_HARNESS_DIR",
    "HYGIENE_DIR",
    "CORE_HOOKS_DIR",
    "CORE_HARNESS_HOOKS_DIR",
    "CORE_PRECOMMIT_DIR",
    "CORE_CI_DIR",
    "engine_version",
    "SuiteIdentity",
    "inject_readme_sections_local",
    "has_generated_index",
    "render_index_home",
    "render_readme_why",
    "CORPUS_ROOT_ENV",
    "DEFAULT_CORPUS_ROOTS",
    "_parse_root_list",
    "corpus_roots",
    "owning_corpus_root",
    "_display_path",
    "load_profile",
    "iter_profiles",
]
