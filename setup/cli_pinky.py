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
    python cli_pinky.py new-repo pluto-poc-x --scaffold --type web
    python cli_pinky.py distribute --repo pinky-core
    python cli_pinky.py install
    python cli_pinky.py rules
    python cli_pinky.py drift
    python cli_pinky.py check-public
"""

import argparse
import sys

from . import agentic_assets
from .cli import main as setup_main
from .common import AGENTIC_HARNESS_DIR, SCRIPT_DIR
from .product_scaffold import REPO_TYPES
from .profile import _command_description

SCRIPTS_DIR = SCRIPT_DIR / "tools"


def _commands_index() -> str:
    """`/command — description` for every agentic-harness/commands/*.md — the same source CLAUDE.md's own
    table renders, read here instead of duplicated, so the two views can't drift apart."""
    commands_dir = AGENTIC_HARNESS_DIR / "commands"
    if not commands_dir.is_dir():
        return ""
    lines = [
        f"  /{path.stem:<22} {_command_description(path)}"
        for path in sorted(commands_dir.glob("*.md"))
    ]
    return "\n".join(lines)


def _scripts_index() -> str:
    """One line per standalone maintainer tool in tools/ — distinct from scripts/hooks/, this repo's
    own installed copy of what it distributes, never a tool run directly."""
    if not SCRIPTS_DIR.is_dir():
        return ""
    lines = [
        f"  tools/{path.name}"
        for path in sorted(SCRIPTS_DIR.glob("*.py"))
        if path.is_file()
    ]
    return "\n".join(lines)


def _assets_epilog() -> str:
    """`<name> — description` for every installable output-style and theme — the answer to "what
    does --output-style/--theme NAME actually do", without leaving the terminal."""
    sections = [
        (
            "🎨 Available output-styles (pinky install --output-style NAME):",
            "\n".join(
                f"  {a.name:<12} {a.description}"
                for a in agentic_assets.discover_output_styles()
            ),
        ),
        (
            "🖌️  Available themes (pinky install --theme NAME):",
            "\n".join(
                f"  {a.name:<12} {a.description}"
                for a in agentic_assets.discover_themes()
            ),
        ),
    ]
    return "\n\n".join(f"{title}\n{body}" for title, body in sections if body)


def _epilog() -> str:
    sections = [
        (
            "🤖 Claude Code commands (see .claude/commands/, or /help in a session):",
            _commands_index(),
        ),
        ("🐍 Standalone scripts:", _scripts_index()),
    ]
    return "\n\n".join(f"{title}\n{body}" for title, body in sections if body)


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
    if args.agents_md:
        argv.append("--agents-md")
    if args.standalone:
        argv.append("--standalone")
    if args.dry_run:
        argv.append("--dry-run")
    setup_main(argv)


def cmd_rules(args: argparse.Namespace) -> None:
    argv = ["--rules"]
    if args.workspace:
        argv.append(args.workspace)
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
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


def cmd_install(args: argparse.Namespace) -> None:
    """Replayable installer (Entrée 4, `cli-setup-repo-lot1.md`) — converges this machine's setup.

    `--plugin` runs the scope wizard (user/project, depth, target); `--output-style`/`--theme`
    install one named asset (`setup.agentic_assets`) — each a different concern from the default
    rules step, each behind its own `setup.state_file` ledger entry. statusline still lands in a
    later phase (see kanban card `factoriser-et-extraire-statusline.md`) — no stub step added
    ahead of the code that would actually run it.
    """
    if args.plugin:
        argv = ["--plugin", args.plugin]
        if args.marketplace:
            argv += ["--marketplace", args.marketplace]
        setup_main(argv)
        return
    if args.output_style:
        setup_main(["--output-style", args.output_style])
        return
    if args.theme:
        setup_main(["--theme", args.theme])
        return
    argv = ["--rules"]
    if args.yes:
        argv.append("--yes")
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
    # Not required: a bare `pinky` prints full help (below) instead of argparse's terse
    # "arguments are required: command" — the standard a CLI-literate user expects (git, npm,
    # docker all do this), and setup.py's own bare-invocation message already does the same for
    # its non-human callers.
    sub = parser.add_subparsers(dest="command", required=False)

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
    p.add_argument(
        "--agents-md",
        action="store_true",
        help="also (re)render AGENTS.md at workspace/group/repo level",
    )
    p.add_argument(
        "--standalone",
        action="store_true",
        help="with --agents-md --repo NAME: one-time extraction gesture (see setup.py --help)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_distribute)

    p = sub.add_parser(
        "install",
        help="🚀 replayable installer — converges this machine's setup",
        epilog=_assets_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--yes", "-y", action="store_true")
    p.add_argument(
        "--plugin",
        default=None,
        metavar="PLUGIN_ID",
        help="enable this plugin via the interactive scope wizard (user/project/depth/target)",
    )
    p.add_argument(
        "--marketplace",
        default=None,
        help="with --plugin: the marketplace it comes from",
    )
    p.add_argument(
        "--output-style",
        default=None,
        metavar="NAME",
        help="install this output-style (see the list below)",
    )
    p.add_argument(
        "--theme",
        default=None,
        metavar="NAME",
        help="install this theme (see the list below)",
    )
    p.set_defaults(func=cmd_install)

    p = sub.add_parser(
        "rules",
        help=(
            "📐 distribute each plugin's rules to the same scope its plugin is installed at"
        ),
    )
    p.add_argument("workspace", nargs="?", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("drift", help="🧭 report repo vs source drift")
    p.add_argument("--profile", default=None)
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser("check-public", help="🔒 scan the public profile for leaks")
    p.add_argument("--profile", default=None)
    p.set_defaults(func=cmd_check_public)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)
