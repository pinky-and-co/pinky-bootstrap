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
# So the workspace announces ITSELF, with a `.pinky/` marker directory at its root, and the moteur
# finds it by walking up from the CURRENT DIRECTORY — the one place that reliably says which
# workspace the operator means. Same resolver shape as declared_kanbans() in
# core/status-lines/stop_handoff.py (`[start, *start.parents]`, env > pointer > default): one
# mechanism, two consumers, ported here rather than re-invented.
WORKSPACE_ROOT_ENV = "PINKY_WORKSPACE_ROOT"
MARKER_DIR_NAME = ".pinky"


def find_workspace_root(start: Path) -> Path:
    """Workspace root — env ``PINKY_WORKSPACE_ROOT`` > nearest ``.pinky/config.txt`` above `start` > legacy.

    Args:
        start: Directory to walk up from — the caller's current directory in practice.

    Returns:
        The resolved workspace root. Falls back to ``SCRIPT_DIR.parent`` (the pre-ADR-0065
        behaviour) when no marker is found, so a moteur cloned inside its workspace keeps working
        with nothing configured — including this repo before its own marker was created.

    The check is for ``config.txt`` INSIDE the marker directory, not just the bare ``.pinky/``
    directory's presence — found live 2026-08-07 redistributing to ``pinky-provider``, which has
    carried its own unrelated ``.pinky/schemas/`` (a product config dir, since its very first
    commit) since before this marker convention existed. Walking up from inside that repo matched
    the bare directory and treated `pinky-provider` itself as the workspace root, so
    `discover_repos()` found zero repos — the exact silent-no-op failure ADR-0065 exists to kill,
    reintroduced by too loose a marker check. ``config.txt`` is unconditionally written by
    ``init_workspace()`` (see below), so it is what actually distinguishes a real marker from an
    unrelated directory that happens to share the name.
    """
    env = os.environ.get(WORKSPACE_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    start = start.resolve()
    for base in [start, *start.parents]:
        if (base / MARKER_DIR_NAME / "config.txt").is_file():
            return base
    return SCRIPT_DIR.parent


WORKSPACE_ROOT = find_workspace_root(Path.cwd())
MARKER_DIR = WORKSPACE_ROOT / MARKER_DIR_NAME

# core/ is the single source for the provider runner (rules, commands, agents,
# CLAUDE.md.tpl) as well as the hooks distribution below.
CORE_DIR = SCRIPT_DIR / "core"

# ── Hooks distribution (core/ = single source) ───────────────────────────────
CORE_HOOKS_DIR = CORE_DIR / "hooks"
# Harness (Claude Code) hooks — distinct from the git pre-commit hooks in CORE_HOOKS_DIR.
# Installed to <claude_dir>/scripts/ and wired into settings.json (see _install_status_lines).
CORE_HARNESS_HOOKS_DIR = CORE_DIR / "status-lines"
CORE_PRECOMMIT_DIR = CORE_DIR / "pre-commit"
CORE_CI_DIR = CORE_DIR / "ci"

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


# ── Instance config — ONE gitignored file, inside the marker directory ────────────────────────
# The moteur carries no instance-shaped literal (which profile is "default", which is the "public"
# one --check-public scans, which repo-naming convention to distribute to, which package prefix is
# "mine" for the mypy hook, who this machine is in the journal) — a fork/clone sets its own values
# in `.pinky/config.txt` instead of editing this source. Absent file/key → graceful no-op default
# (empty tuple / None), never a crash: a fresh clone with nothing configured still runs, it just
# distributes to zero repos and requires an explicit --profile — see the callers of DEFAULT_PROFILE /
# DEFAULT_PUBLIC_PROFILE / REPO_GLOBS / INTERNAL_DEP_PREFIX.
#
# It lives in `.pinky/` and not next to this file because SCRIPT_DIR is the INSTALL path (ADR-0065):
# a packaged moteur would have written its config inside site-packages, where it is neither
# writable nor found again. Config belongs to the workspace, code belongs to the install.
#
# ── Why exactly ONE config file, and what is NOT in it ────────────────────────────────────────
# The moteur's config was spread over three files, then two, now one (ADR-0069). The criterion that
# collapsed them is not "what subject does it cover", nor even "is it committed" — it is:
#
#     what NEVER VARIES between instances is a property of the CODE, never a configuration line.
#     What varies by instance lives in ONE gitignored file.
#
# `corpus-roots.txt` (tracked) held two entries of different natures: `corpus-public`, whose position
# is fixed by this repository, and `../_corpus-pinky`, a private corpus root exactly like the
# `_corpus-pluto` that already lived in this file's `corpus_roots_local` key. The same kind of thing
# in two files, with no decision behind it. The first is now DEFAULT_CORPUS_ROOTS (below), the second
# joined the key.
#
# ADR-0065 § Amendement had settled on "a file is separate because it is COMMITTED" — a real
# boundary, checkable with `git ls-files`, and better than the by-subject split it replaced. It just
# answers where to put what is committed without ever asking why anything should be.
INSTANCE_CONFIG_FILE = MARKER_DIR / "config.txt"


def _read_config(path: Path) -> dict[str, str]:
    """Parse `key = value` lines from a config file; skip blanks/`#` comments.

    Args:
        path: File to read. A missing file is not an error.

    Returns:
        The parsed keys, or an empty dict when the file does not exist.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


_WORKSPACE_DEFAULTS = _read_config(INSTANCE_CONFIG_FILE)

# The default profile the `claude` provider (and the interactive flow) renders from.
# `--provider claude` is an alias for `--profile <default_profile>` — one rendering path only.
# None when unconfigured — callers that need it fail loud with a clear message at point of use.
DEFAULT_PROFILE: str | None = os.environ.get(
    "DEFAULT_PROFILE"
) or _WORKSPACE_DEFAULTS.get("default_profile")

# Repos receiving the distribution — comma-separated globs under WORKSPACE_ROOT.
# Empty when unconfigured — discover_repos() then finds zero repos (safe no-op), not a crash.
_repo_globs_raw = os.environ.get("REPO_GLOBS") or _WORKSPACE_DEFAULTS.get(
    "repo_globs", ""
)
REPO_GLOBS: tuple[str, ...] = tuple(
    g.strip() for g in _repo_globs_raw.split(",") if g.strip()
)

# Tools the OPERATOR runs — comma-separated. Second subject of the same "capability" idea as
# resolve_extras(): that one derives what a REPO *is* from its layout, this one carries what the
# person *runs* (a second agent, a local model runtime, a provider account). Undetectable by
# construction for most of them — Cortex Code is a web UI in Snowsight, there is nothing local to
# probe — hence declared rather than sniffed.
# Empty when unconfigured, and that is the load-bearing default: a third-party machine (targets #2
# and #3 of chantier 0001) then receives NO machine-scoped command at all. The failure mode we
# refuse is the opposite one — a command silently landing on someone else's machine because they
# forgot to opt out.
_machine_caps_raw = os.environ.get("MACHINE_CAPABILITIES") or _WORKSPACE_DEFAULTS.get(
    "machine_capabilities", ""
)
MACHINE_CAPABILITIES: frozenset[str] = frozenset(
    c.strip() for c in _machine_caps_raw.split(",") if c.strip()
)

# The PUBLIC profile --check-public scans by default (no --profile). Distinct from DEFAULT_PROFILE
# (which is the author's own, PRIVATE, everyday profile): the leak guard scans the shipped-public
# profile instead. None when unconfigured — the guard then no-ops with a clear message rather than
# scanning a wrong target (see leak_guard.check_public).
DEFAULT_PUBLIC_PROFILE: str | None = os.environ.get(
    "DEFAULT_PUBLIC_PROFILE"
) or _WORKSPACE_DEFAULTS.get("default_public_profile")

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
# Resolution (ADR-0069):
#   env CORPUS_ROOT  — REPLACES everything. os.pathsep-joined dirs, absolute or SCRIPT_DIR-relative.
#   otherwise        — DEFAULT_CORPUS_ROOTS (the code's own, always first) + the instance's
#                      `corpus_roots_local` key, appended.
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


def _parse_root_list(raw_items: list[str], base: Path | None = None) -> list[Path]:
    """Parse path entries (env-split or file lines) into resolved dirs; skip blanks/`#`.

    Args:
        raw_items: Path entries, one per element.
        base: Directory a RELATIVE entry resolves against. ``None`` means SCRIPT_DIR, which is
            right for the ``CORPUS_ROOT`` env var — an explicit override, typed by someone who
            knows where the code is. Instance config passes WORKSPACE_ROOT instead: its entries
            describe the workspace, which no longer sits at a fixed offset from the code.

            It passed MARKER_DIR until ADR-0069, while this docstring already claimed "the
            workspace" — so a relative entry landed one level too deep, inside ``.pinky/``. Nothing
            caught it because the only relative entries were in the tracked file (SCRIPT_DIR-based)
            and the only instance entry was absolute. Moving ``_corpus-pinky`` into the instance key
            is exactly what would have surfaced it.

            The default is resolved HERE and not in the signature: a default argument binds once at
            import, which would freeze SCRIPT_DIR past any later reassignment (the test suite's, and
            `find_workspace_root()`'s own — see `WORKSPACE_ROOT` above).

    Returns:
        Resolved directories, in input order, blanks and comments dropped.
    """
    base = base or SCRIPT_DIR
    roots: list[Path] = []
    for item in raw_items:
        item = item.strip()
        if not item or item.startswith("#"):
            continue
        p = Path(item).expanduser()
        roots.append(p.resolve() if p.is_absolute() else (base / p).resolve())
    return roots


def corpus_roots() -> list[Path]:
    """Ordered corpus search roots — env CORPUS_ROOT, else DEFAULT_CORPUS_ROOTS + `corpus_roots_local`.

    The base (``DEFAULT_CORPUS_ROOTS``) comes first and is **unconditional** — it is the code's own
    property, not something an instance declares. What an instance adds is the
    ``corpus_roots_local`` key of ``<workspace root>/.pinky/config.txt``: gitignored, so it may hold
    the absolute, machine-specific paths a shared drive's mount point requires (different on every
    machine, which nothing versioned can express).

    ``CORPUS_ROOT`` (env) *replaces* the whole thing, base included: an explicit override means "use
    exactly this", and it is now the only way to relocate the public corpus, which is no longer
    declarative.
    """
    env = os.environ.get(CORPUS_ROOT_ENV)
    if env:
        roots = _parse_root_list(env.split(os.pathsep))
        if roots:
            return roots
    roots = [p.resolve() for p in DEFAULT_CORPUS_ROOTS]
    roots += _parse_root_list(
        _WORKSPACE_DEFAULTS.get("corpus_roots_local", "").split(","),
        base=WORKSPACE_ROOT,
    )
    return list(dict.fromkeys(roots))  # de-dup, first occurrence wins the order


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


# Shipped as a commented skeleton, with NO value filled in: the moteur carries no instance-shaped
# literal (that is the whole point of the file), and an example value that happens to work is worse
# than a blank — it gets kept by accident. Every key is optional; each one's absent-default is
# documented at its reader in this module.
_CONFIG_TEMPLATE = """\
# pinky instance config — this machine's workspace. NEVER versioned (see .gitignore).
# Created by `pinky init-workspace` (packaged install) or `setup.py --init-workspace` (source
# checkout). Every key is optional; an absent key degrades to a documented no-op default, never
# a crash.

# Profile `--provider claude` (and the bare interactive flow) renders from.
# default_profile =

# The PUBLIC profile `--check-public` scans when no --profile is passed.
# default_public_profile =

# Comma-separated globs, relative to this workspace root — which sibling repos receive the hooks
# distribution (--repo / --all / --check-drift). Absent = zero repos, a safe no-op.
# repo_globs =

# Package-name prefix excluded from the hermetic mypy hook's additional_dependencies (internal,
# pre-release libs absent from PyPI). Absent = no filtering.
# internal_dep_prefix =

# Who this machine is in the cross-agent journal — names `_AGENT_LOG/YYYY-MM-DD_claude-code-<id>.md`
# so two machines mounting one shared root never write the same path on the same day.
# agent_identity =

# Tools this OPERATOR runs, comma-separated (the `machine:` axis of command routing). Undetectable
# for most — Cortex Code is a web UI, nothing local to probe — hence declared. Absent = none, which
# is the right default for a third-party machine.
# machine_capabilities =

# Extra corpus roots, comma-separated, this machine only — absolute paths welcome (a synced drive's
# mount point differs per machine). A relative entry resolves against THIS workspace root. Read IN
# ADDITION to the moteur's own corpus-public, which is code-side and needs no declaration.
# corpus_roots_local =

# Kanban roots this machine mounts, comma-separated — the shared board(s) of ADR-0015, whose mount
# point differs per machine. Read by the `stop_handoff.py` harness hook; the board nearest the
# session is always found by proximity and never needs listing here. Absent = local board only.
# kanban_roots_local =
"""


def init_workspace(target: Path) -> bool:
    """Create the `.pinky/` marker that defines `target` as a workspace.

    Args:
        target: Directory to mark. Created if missing, along with its parents.

    Returns:
        True on success. Idempotent by design — an existing ``config.txt`` is left untouched so
        re-running never destroys a configured machine. Exposed as `pinky init-workspace`
        (cli_pinky.py) once packaged; run once per workspace, never as part of an upgrade.
    """
    marker = target.expanduser().resolve() / MARKER_DIR_NAME
    marker.mkdir(parents=True, exist_ok=True)
    config = marker / "config.txt"
    if config.exists():
        print(f"✓ workspace already initialised: {marker}  (config.txt kept as-is)")
        return True
    config.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    print(f"✓ workspace initialised: {marker}")
    print(f"  edit {config} — every key is optional and commented in place")
    return True


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
    "MARKER_DIR",
    "MARKER_DIR_NAME",
    "find_workspace_root",
    "CORE_DIR",
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
    "INSTANCE_CONFIG_FILE",
    "_read_config",
    "init_workspace",
    "DEFAULT_PROFILE",
    "DEFAULT_PUBLIC_PROFILE",
    "REPO_GLOBS",
    "MACHINE_CAPABILITIES",
    "CORPUS_ROOT_ENV",
    "DEFAULT_CORPUS_ROOTS",
    "_parse_root_list",
    "corpus_roots",
    "owning_corpus_root",
    "_display_path",
    "load_profile",
    "iter_profiles",
]
