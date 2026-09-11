"""pinky-bootstrap toolbox — sub-commands over setup.py's flags (chantier-0001, card
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
    python cli_pinky.py llm-drift scan --all
    python cli_pinky.py directives E402
"""

import argparse
import re
import sys

from . import agentic_assets
from .cli import main as setup_main
from .common import AGENTIC_HARNESS_DIR, SCRIPT_DIR
from .product_scaffold import REPO_TYPES

SCRIPTS_DIR = SCRIPT_DIR / "tools"


def _command_description(path) -> str:
    """Read the `description:` frontmatter field from a command file — empty if absent."""
    in_frontmatter = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            m = re.match(r"^description:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
    return ""


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
        (
            "📖 Other assets:",
            (
                "  --live-docs   local MkDocs viewer of the kanban boards + agent logs "
                "(macOS: launchd service)"
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
    setup_main(["--check-drift"])


def cmd_llm_drift(args: argparse.Namespace) -> None:
    argv = ["--llm-drift", args.action]
    if args.repo:
        argv += ["--repo", args.repo]
    elif args.all:
        argv.append("--all")
    for kind in args.kind or []:
        argv += ["--kind", kind]
    if args.dry_run:
        argv.append("--dry-run")
    if args.json:
        argv.append("--json")
    setup_main(argv)


def cmd_directives(args: argparse.Namespace) -> None:
    setup_main(["--directives", *([args.code] if args.code else [])])


def cmd_doctor(args: argparse.Namespace) -> None:
    setup_main(["--doctor", *(["--fix"] if args.fix else [])])


def cmd_docs(args: argparse.Namespace) -> None:
    setup_main([f"--live-docs-{args.action}"])


def cmd_plugins(args: argparse.Namespace) -> None:
    flag = f"--plugins-{args.action}"
    setup_main([f"{flag}-apply"] if args.apply else [flag])


def cmd_install(args: argparse.Namespace) -> None:
    """Replayable installer (Entrée 4, `cli-setup-repo-lot1.md`) — converges this machine's setup.

    `--plugin` fetches the plugin (`claude plugin install`) then either wires its status line
    (`setup.plugin_install.set_status_lines`) or runs the scope wizard; `--output-style`/`--theme`
    install one named asset (`setup.agentic_assets`) — each a different concern from the default
    rules step, each behind its own `setup.state_file` ledger entry.
    """
    if args.plugin:
        argv = ["--plugin", args.plugin]
        if args.marketplace:
            argv += ["--marketplace", args.marketplace]
        if args.yes:
            argv.append("--yes")
        if args.force:
            argv.append("--force")
        setup_main(argv)
    elif args.output_style:
        setup_main(["--output-style", args.output_style])
    elif args.theme:
        setup_main(["--theme", args.theme])
    elif args.live_docs:
        setup_main(["--live-docs", *(["--force"] if args.force else [])])
    else:
        argv = ["--rules"]
        if args.yes:
            argv.append("--yes")
        setup_main(argv)

    from . import doctor

    print()
    doctor.run_doctor(fix=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="🧰 pinky-bootstrap toolbox — see setup.py for the underlying flags.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    p.add_argument(
        "--live-docs",
        action="store_true",
        help="install the live board/log viewer (MkDocs; macOS launchd service). "
        "Then `pinky docs serve` / `status` / `uninstall`.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="with --live-docs: replace a launchd agent pinky did not install. "
        "with --plugin: bust the plugin's cache dir before fetching (dev cache-bust)",
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
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser(
        "llm-drift",
        help="🧹 scan / fix what agents leave in code that every read pays for "
        "(comments, narrative, long comment blocks)",
    )
    p.add_argument("action", choices=["scan", "fix"])
    p.add_argument("--repo", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument(
        "--kind",
        action="append",
        default=None,
        metavar="KIND",
        help="drift kind, repeatable — scan default: narrative, long-comment · "
        "fix default: comments",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="with fix: report the savings, write nothing",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="with scan: JSON snapshot instead of the report",
    )
    p.set_defaults(func=cmd_llm_drift)

    p = sub.add_parser(
        "directives",
        help="📌 the inline directive to paste for an error code (noqa, type: ignore, nosec…)",
    )
    p.add_argument(
        "code",
        nargs="?",
        default=None,
        help="E402, [type-arg], B608… — omit it for the whole table",
    )
    p.set_defaults(func=cmd_directives)

    p = sub.add_parser(
        "docs",
        help="📖 live board/log viewer — serve it, check its status, or remove it "
        "(install it with `pinky install --live-docs`)",
    )
    p.add_argument(
        "action",
        choices=["serve", "status", "uninstall"],
        help="serve: run the site live, no service · status: posed / not-mine / absent · "
        "uninstall: remove what `pinky install --live-docs` posed",
    )
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser(
        "plugins",
        help="🧩 audit / reconcile where each plugin is enabled across the workspace",
    )
    p.add_argument(
        "action",
        choices=["reconcile"],
        help="reconcile: per-plugin audit of where it is enabled / has files / ships a "
        "status line (writes nothing)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="with reconcile: interactively place each plugin and purge non-matching enables",
    )
    p.set_defaults(func=cmd_plugins)

    p = sub.add_parser(
        "doctor",
        help="🩺 check the prerequisites installed plugins assume (binaries, Ollama, API keys)",
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help="offer to `brew install` each missing binary and Ollama",
    )
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)
