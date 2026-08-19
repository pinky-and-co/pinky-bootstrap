"""CLI glue — argparse + mode dispatch. See setup.py at the workspace root for usage."""

import argparse
import sys
from pathlib import Path

from .common import DEFAULT_PUBLIC_PROFILE, WORKSPACE_ROOT, init_workspace
from .leak_guard import check_public
from .machine_check import check_machine
from .precommit import new_repo, run_distribution
from .product_scaffold import REPO_TYPES
from .rules import distribute_rules, print_rules_report


def main(argv: list[str] | None = None) -> None:
    """Parse and dispatch. ``argv`` lets a caller (``cli_pinky.py``'s thin sub-command dispatch)
    invoke a mode programmatically without touching ``sys.argv`` — ``None`` (the CLI entry point)
    keeps today's behavior, delegating to argparse's own ``sys.argv[1:]`` default."""
    parser = argparse.ArgumentParser(add_help=False)
    # Rules distribution — targets the WORKSPACE (.claude/rules/), not a repo, which is why it is
    # its own mode rather than a flag on --repo/--all.
    parser.add_argument(
        "--rules",
        nargs="?",
        const=str(WORKSPACE_ROOT),
        default=None,
        metavar="WORKSPACE",
        help="distribute rules/core/ into <workspace>/.claude/rules/ "
        "(default: the detected workspace root). Shows the plan, asks for confirmation before "
        "applying — see --dry-run and --yes.",
    )
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
        "never overwritten. Exposed as `pinky init-workspace` (cli_pinky.py) once packaged.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print actions, write nothing. With --rules: print the plan and stop, never ask",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="with --rules: apply the plan without asking for confirmation "
        "(required in a non-interactive shell — no stdin to prompt on)",
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
        help="profile path or name; gates --check-public's scan, or (with a distribution flag) "
        "hooks on its layers.hooks (Phase 2a)",
    )
    args, _ = parser.parse_known_args(argv)

    # Workspace bootstrap (ADR-0065): creates the marker that DEFINES the workspace. Runs before
    # every other mode because they all resolve WORKSPACE_ROOT through it.
    if args.rules is not None:
        workspace = Path(args.rules)
        plan = distribute_rules(workspace, apply=False)
        print_rules_report(plan, workspace)
        if not plan.has_changes or args.dry_run:
            return
        if not args.yes:
            if not sys.stdin.isatty():
                print("\nNon-interactive shell — pass --yes to apply.", file=sys.stderr)
                raise SystemExit(1)
            if input("\nApply this plan? [y/N] ").strip().lower() != "y":
                print("Cancelled.")
                return
        distribute_rules(workspace, apply=True)
        print("\nApplied.")
        return

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

    # No mode flag matched: this low-level flag interface has no interactive default (that was
    # install_provider's job, removed with the dead CLAUDE.md render engine — 2026-08-17). Point at
    # the friendly facade instead of guessing what the caller wanted.
    print("pinky workspace setup — no mode flag given.")
    print(
        "Run `pinky --help` (cli_pinky.py) for the sub-command list, or pass a flag directly: "
        "--init-workspace, --new-repo, --repo/--all (distribute), --rules (workspace rules), "
        "--check-drift, --check-public, --check-machine."
    )
    raise SystemExit(1)
