"""CLI glue — argparse + mode dispatch. See setup.py at the workspace root for usage."""

import argparse
from pathlib import Path

from .common import (
    DEFAULT_PUBLIC_PROFILE,
    PROVIDERS,
    REPO_GLOBS,
    WORKSPACE_ROOT,
    init_workspace,
)
from .leak_guard import check_public
from .machine_check import check_machine
from .precommit import discover_repos, new_repo, run_distribution
from .product_scaffold import REPO_TYPES
from .profile import install_from_profile, install_into_repo, install_provider


def main(argv: list[str] | None = None) -> None:
    """Parse and dispatch. ``argv`` lets a caller (``cli_pinky.py``'s thin sub-command dispatch)
    invoke a mode programmatically without touching ``sys.argv`` — ``None`` (the CLI entry point)
    keeps today's behavior, delegating to argparse's own ``sys.argv[1:]`` default."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--provider", choices=PROVIDERS, default=None)
    # Hooks distribution
    parser.add_argument("--repo", default=None, help="distribute to a single repo")
    parser.add_argument(
        "--new-repo",
        default=None,
        metavar="NAME",
        help="create a new (pinky-*/pluto-*) repo already governed: git init + develop branch, "
        "then distribute the hooks socle. Idempotent (re-run converges).",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="with --new-repo: also lay down the docs/ Diátaxis skeleton + universal stubs "
        "(README/CONTEXT/AGENT/pyproject/LICENSE). Idempotent, one-time (not the commit-time "
        "generate-docs regeneration).",
    )
    parser.add_argument(
        "--type",
        choices=REPO_TYPES,
        default=None,
        help="with --new-repo --scaffold: which manifest to write (lib/data/web/tooling — default "
        "lib). Picks the LAYOUT only; resolve_extras() reads it back into hooks the same way it "
        "would for a hand-built repo, so this never routes hooks directly.",
    )
    parser.add_argument("--all", action="store_true", help="distribute to all repos")
    parser.add_argument(
        "--init-workspace",
        nargs="?",
        const=".",
        default=None,
        metavar="DIR",
        help="create the `.pinky/` marker (+ a commented config.txt) that DEFINES a directory as a "
        "pinky workspace. Defaults to the current directory. Idempotent: an existing config.txt is "
        "never overwritten. Exposed as `pinky init-workspace` (cli_pinky.py) once packaged — a "
        "separate subcommand from `pinky install` (the interactive provider render), not something "
        "it calls: bootstrapping the workspace and installing a provider's CLAUDE.md are distinct "
        "steps a third party runs once each.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print actions, write nothing"
    )
    parser.add_argument(
        "--check-drift", action="store_true", help="report repo vs source drift"
    )
    parser.add_argument(
        "--check-public",
        action="store_true",
        help="scan the public profile's shipped corpus for product/private-doc leaks "
        f"(default profile: {DEFAULT_PUBLIC_PROFILE or 'unset — pass --profile'}; "
        "never scans private profiles)",
    )
    parser.add_argument(
        "--check-machine",
        action="store_true",
        help="report locally installed Claude Code skills/plugins the moteur has no record of "
        "(machine_capabilities is declared, not sniffed — this makes the one probeable class of "
        "ambient capability visible). Advisory only, always exits 0.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="after distributing, commit the distributed files in each repo",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --all: distribute to repos recorded on ANOTHER profile too (they are skipped "
        "by default, so --all never silently changes a repo's regime)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="profile path or name; alone → render CLAUDE.md (Phase 3), "
        "with a distribution flag → gates hooks on its layers.hooks (Phase 2a)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="render CLAUDE.md to this path instead of WORKSPACE_ROOT/CLAUDE.md "
        "(skips .claude/ scaffolding — for temp/validation renders)",
    )
    parser.add_argument(
        "--into",
        default=None,
        help="render the profile's FULL agent layer (CLAUDE.md + .claude/ + bundled knowledge) "
        "INTO a standalone repo so it carries its config committed (requires --profile)",
    )
    parser.add_argument(
        "--target-os",
        choices=["windows", "posix"],
        default=None,
        help="with --into: OS of the machine that will RUN the rendered repo (e.g. le frère's "
        "Windows machine), when it differs from the machine generating it. Picks the correct "
        "harness-hook launcher (py -3 vs python3). Omit when target == the generating machine.",
    )
    args, _ = parser.parse_known_args(argv)

    # Workspace bootstrap (ADR-0065): creates the marker that DEFINES the workspace. Runs before
    # every other mode because they all resolve WORKSPACE_ROOT through it.
    if args.init_workspace:
        raise SystemExit(0 if init_workspace(Path(args.init_workspace)) else 1)

    # Public-corpus leak guard (Phase 4): scans the public profile only, never distributes.
    if args.check_public:
        raise SystemExit(1 if check_public(args.profile) else 0)

    # Ambient-capability visibility (card `capacites-ambiantes-non-declarees`): advisory only,
    # never a gate — see machine_check.py's own module docstring for why.
    if args.check_machine:
        check_machine()
        raise SystemExit(0)

    # From-zero mode: create a new repo already governed (git init + develop, then distribute).
    if args.new_repo:
        if args.type and not args.scaffold:
            print(
                "--type requires --scaffold (it picks which manifest --scaffold writes)."
            )
            raise SystemExit(1)
        new_repo(args.new_repo, args)
        return

    # Distribution mode: any distribution flag is set. --profile here is the hooks gate
    # (Phase 2a) — it does NOT render CLAUDE.md in this branch.
    if args.repo or args.all or args.check_drift:
        run_distribution(args)
        return

    # --into <repo>: render the full agent layer INTO a standalone repo (committed POC config).
    if args.into:
        if not args.profile:
            print(
                "--into requires --profile <name> (which profile to render into the repo)."
            )
            raise SystemExit(1)
        target_os = {"windows": "Windows", "posix": "posix"}.get(args.target_os)
        install_into_repo(args.profile, Path(args.into), target_os=target_os)
        return

    # Profile render mode (Phase 3): --profile alone renders CLAUDE.md from the profile.
    if args.profile:
        install_from_profile(
            args.profile, output=Path(args.output) if args.output else None
        )
        return

    print("pinky workspace setup")
    print("======================")
    print(f"Workspace root: {WORKSPACE_ROOT}")

    provider = args.provider
    if provider is None:
        print("\nAvailable providers:")
        for p in PROVIDERS:
            print(f"  - {p}")
        provider = input("\nProvider [claude]: ").strip() or "claude"

    install_provider(provider)

    # This used to print three hardcoded `git clone git@github.com:<PINKY_ORG>/pinky-core` lines —
    # an instance-shaped literal in the moteur (exactly what ADR-0065 § "carries no instance-shaped
    # literal" and ADR-0069 remove everywhere else), printed on EVERY render whatever the profile. On
    # a machine rendering another org's profile it named private repos of an org that operator has
    # nothing to do with, and `<PINKY_ORG>` was never substituted, so it was not even usable by the
    # author. Found 2026-08-09 by replaying a third-party install end to end.
    #
    # What replaces it is derived from this workspace: how many repos its own `repo_globs` actually
    # match. Reporting the count also surfaces the ZERO case, which is the silent no-op ADR-0065
    # exists to kill — a render that succeeds while the distribution can reach nothing.
    print()
    if not REPO_GLOBS:
        print(
            "No `repo_globs` in .pinky/config.txt — `pinky distribute` would find zero repos.\n"
            "  Set it to the glob(s) naming your repos, then clone them next to this workspace."
        )
        return
    globs = ", ".join(REPO_GLOBS)
    found = discover_repos()
    if found:
        print(f"Repos matching `{globs}` next to this workspace: {len(found)}")
        print("  Next: pinky distribute --repo <name> --profile <name> --dry-run")
    else:
        print(
            f"No repo matching `{globs}` next to this workspace yet.\n"
            "  Clone them here, then: pinky distribute --repo <name> --profile <name>"
        )
