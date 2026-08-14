"""pinky-workspace toolbox — sub-commands over setup.py's flags (chantier-0001, card
`cli-pinky-sous-commandes-au-lieu-de-flags`).

Lives in `setup/` — not at the repo root — so an editable install (`packages = ["setup"]`) picks up
edits live. The root-level `cli_pinky.py` shim exists purely so `python cli_pinky.py …` still works
from a bare clone (kanban card `cli-pinky-py-n-est-pas-editable`); it re-exports `main`/`setup_main`
from here unchanged.

Thin dispatch ONLY: every `cmd_*` below builds the equivalent `setup.cli` flags and delegates to
`setup.cli.main()` — the single source of truth for what each mode does stays `setup/cli.py`. Any
rule that lands here instead is a bug. `setup.py` itself stays fully usable with its own flags: CI,
the test suite and a third-party machine call the engine directly, this is a facade over it.

Usage:
    python cli_pinky.py init-workspace [DIR]
    python cli_pinky.py new-repo pluto-poc-x --scaffold --type web
    python cli_pinky.py distribute --repo pinky-core
    python cli_pinky.py drift
    python cli_pinky.py check-public
    python cli_pinky.py check-machine
    python cli_pinky.py render --profile pinky
    python cli_pinky.py into --profile pinky /path/to/repo
    python cli_pinky.py install --provider claude
"""

import argparse

from .cli import main as setup_main
from .common import CORE_DIR, SCRIPT_DIR, PROVIDERS
from .product_scaffold import REPO_TYPES
from .profile import _command_description

SCRIPTS_DIR = SCRIPT_DIR / "scripts"


def _commands_index() -> str:
    """`/command — description` for every core/commands/*.md — the same source CLAUDE.md's own
    table renders, read here instead of duplicated, so the two views can't drift apart."""
    commands_dir = CORE_DIR / "commands"
    if not commands_dir.is_dir():
        return ""
    lines = [
        f"  /{path.stem:<22} {_command_description(path)}"
        for path in sorted(commands_dir.glob("*.md"))
    ]
    return "\n".join(lines)


def _scripts_index() -> str:
    """One line per standalone tool in scripts/ (excluding scripts/hooks/, distributed per-repo —
    not something to run directly)."""
    if not SCRIPTS_DIR.is_dir():
        return ""
    lines = [
        f"  scripts/{path.name}"
        for path in sorted(SCRIPTS_DIR.glob("*.py"))
        if path.is_file()
    ]
    return "\n".join(lines)


def _epilog() -> str:
    sections = [
        (
            "🤖 Claude Code commands (see .claude/commands/, or /help in a session):",
            _commands_index(),
        ),
        ("🐍 Standalone scripts:", _scripts_index()),
    ]
    return "\n\n".join(f"{title}\n{body}" for title, body in sections if body)


def cmd_init_workspace(args: argparse.Namespace) -> None:
    argv = ["--init-workspace", args.dir]
    setup_main(argv)


def cmd_new_repo(args: argparse.Namespace) -> None:
    argv = ["--new-repo", args.name]
    if args.scaffold or args.type:
        argv.append("--scaffold")
    if args.type:
        argv += ["--type", args.type]
    setup_main(argv)


def cmd_distribute(args: argparse.Namespace) -> None:
    argv: list[str] = []
    if args.repo:
        argv += ["--repo", args.repo]
    elif args.all:
        argv.append("--all")
    if args.profile:
        argv += ["--profile", args.profile]
    if args.commit:
        argv.append("--commit")
    if args.dry_run:
        argv.append("--dry-run")
    setup_main(argv)


def cmd_drift(args: argparse.Namespace) -> None:
    argv = ["--check-drift"]
    if args.profile:
        argv += ["--profile", args.profile]
    setup_main(argv)


def cmd_check_public(args: argparse.Namespace) -> None:
    argv = ["--check-public"]
    if args.profile:
        argv += ["--profile", args.profile]
    setup_main(argv)


def cmd_check_machine(_args: argparse.Namespace) -> None:
    setup_main(["--check-machine"])


def cmd_render(args: argparse.Namespace) -> None:
    argv = ["--profile", args.profile]
    if args.output:
        argv += ["--output", args.output]
    setup_main(argv)


def cmd_into(args: argparse.Namespace) -> None:
    argv = ["--into", args.target, "--profile", args.profile]
    if args.target_os:
        argv += ["--target-os", args.target_os]
    setup_main(argv)


def cmd_install(args: argparse.Namespace) -> None:
    argv = []
    if args.provider:
        argv += ["--provider", args.provider]
    setup_main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # NO hardcoded `prog`: this module has two legitimate entry points — the installed console
        # script (`pinky …`) and a direct run (`python cli_pinky.py …`, the form the root shim's own
        # docstring documents). Any literal is wrong for one of them, and it propagates: every
        # sub-command's usage line inherits it, so `pinky drift --help` used to answer
        # `usage: cli_pinky.py drift` — naming a file the reader never types. argparse's default is
        # basename(argv[0]), which is right for both by construction.
        description="🧰 pinky-workspace toolbox — see setup.py for the underlying flags.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "init-workspace",
        help="🏁 create the `.pinky/` marker that DEFINES a directory as a pinky workspace",
    )
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(func=cmd_init_workspace)

    p = sub.add_parser(
        "new-repo", help="🌱 create a new (pinky-*/pluto-*) repo, already governed"
    )
    p.add_argument("name")
    p.add_argument("--scaffold", action="store_true")
    p.add_argument("--type", choices=REPO_TYPES, default=None)
    p.set_defaults(func=cmd_new_repo)

    p = sub.add_parser("distribute", help="📦 distribute hooks to one repo or --all")
    p.add_argument("--repo", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--profile", default=None)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_distribute)

    p = sub.add_parser("drift", help="🧭 report repo vs source drift")
    p.add_argument("--profile", default=None)
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser("check-public", help="🔒 scan the public profile for leaks")
    p.add_argument("--profile", default=None)
    p.set_defaults(func=cmd_check_public)

    p = sub.add_parser(
        "check-machine",
        help="🔎 report locally installed skills/plugins the moteur has no record of",
    )
    p.set_defaults(func=cmd_check_machine)

    p = sub.add_parser("render", help="📝 render CLAUDE.md from a profile")
    p.add_argument("--profile", required=True)
    p.add_argument("--output", default=None)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser(
        "into", help="🚚 render the full agent layer into a standalone repo"
    )
    p.add_argument("target")
    p.add_argument("--profile", required=True)
    p.add_argument("--target-os", choices=["windows", "posix"], default=None)
    p.set_defaults(func=cmd_into)

    p = sub.add_parser(
        "install", help="🎛️ interactive provider install (default setup.py mode)"
    )
    p.add_argument("--provider", choices=PROVIDERS, default=None)
    p.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
