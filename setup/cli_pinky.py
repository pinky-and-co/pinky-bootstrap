"""pinky-bootstrap toolbox — sub-commands over setup.py's flags.

Lives in `setup/` — not at the repo root — so an editable install (`packages = ["setup"]`) picks up
edits live. The root-level `cli_pinky.py` shim exists purely so `python cli_pinky.py …` still works
from a bare clone; it re-exports `main`/`setup_main` from here unchanged.

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
from .llm_drift import DRIFT_KINDS, SCAN_KINDS_DEFAULT
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
    """Top-level `--help` epilog: the Claude Code commands index, then the standalone scripts."""
    sections = [
        (
            "🤖 Claude Code commands (see .claude/commands/, or /help in a session):",
            _commands_index(),
        ),
        ("🐍 Standalone scripts:", _scripts_index()),
    ]
    return "\n\n".join(f"{title}\n{body}" for title, body in sections if body)


def cmd_new_repo(args: argparse.Namespace) -> None:
    """Translate `new-repo` flags to `setup.cli`'s `--new-repo`/`--scaffold`/`--type`."""
    argv = ["--new-repo", args.name]
    if args.scaffold or args.type:
        argv.append("--scaffold")
    if args.type:
        argv += ["--type", args.type]
    setup_main(argv)


def cmd_distribute(args: argparse.Namespace) -> None:
    """Translate `distribute` flags to `setup.cli`'s equivalent `--repo`/`--all`/... flags."""
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
    """Translate `rules` flags to `setup.cli`'s `--rules` flag."""
    argv = ["--rules"]
    if args.workspace:
        argv.append(args.workspace)
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
    setup_main(argv)


def cmd_drift(args: argparse.Namespace) -> None:
    """Translate `drift` to `setup.cli`'s `--check-drift`."""
    setup_main(["--check-drift"])


def cmd_llm_drift(args: argparse.Namespace) -> None:
    """Translate `llm-drift` flags to `setup.cli`'s `--llm-drift` and its options."""
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
    """Translate `directives` to `setup.cli`'s `--directives`, with the optional error code."""
    setup_main(["--directives", *([args.code] if args.code else [])])


def cmd_doctor(args: argparse.Namespace) -> None:
    """Translate `doctor` to `setup.cli`'s `--doctor`, with the optional `--fix`."""
    setup_main(["--doctor", *(["--fix"] if args.fix else [])])


def cmd_docs(args: argparse.Namespace) -> None:
    """Translate `docs <action>` to `setup.cli`'s `--live-docs-<action>`."""
    setup_main([f"--live-docs-{args.action}"])


def cmd_plugins(args: argparse.Namespace) -> None:
    """Translate `plugins <action>` to `setup.cli`'s `--plugins-<action>`, with the optional `-apply`."""
    flag = f"--plugins-{args.action}"
    setup_main([f"{flag}-apply"] if args.apply else [flag])


def cmd_install(args: argparse.Namespace) -> None:
    """Replayable installer that converges this machine's setup.

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


def _examples(lines: list[str]) -> str:
    """The `💡 examples:` block of a sub-command's help, each `command  # effect` aligned."""
    pairs = [line.split("  # ", 1) for line in lines]
    width = max(len(pair[0]) for pair in pairs)
    body = "\n".join(
        f"  {pair[0]:<{width}}  # {pair[1]}" if len(pair) == 2 else f"  {pair[0]}"
        for pair in pairs
    )
    return f"💡 examples:\n{body}"


def _add(
    sub: "argparse._SubParsersAction[argparse.ArgumentParser]",
    name: str,
    summary: str,
    examples: list[str],
    extra: str = "",
) -> argparse.ArgumentParser:
    """A sub-command whose one-line summary is also its --help description, examples below."""
    return sub.add_parser(
        name,
        help=summary,
        description=summary,
        epilog="\n\n".join(part for part in (extra, _examples(examples)) if part),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _drift_kinds_epilog() -> str:
    """One line per registered drift kind, with what it finds and which action defaults to it."""
    lines = [
        f"  {kind.name:<14} {kind.summary}"
        + (" · fixable, fix default" if kind.fix else "")
        + (" · scan default" if kind.name in SCAN_KINDS_DEFAULT else "")
        for kind in DRIFT_KINDS
    ]
    return "🧹 drift kinds:\n" + "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the `pinky` argument parser: one sub-command per `cmd_*` function above."""
    parser = argparse.ArgumentParser(
        description="🧰 pinky-bootstrap toolbox — see setup.py for the underlying flags.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p = _add(
        sub,
        "new-repo",
        "🌱 create a new (pinky-*/pluto-*) repo, already governed",
        [
            "pinky new-repo pinky-foo  # git init + the hooks, nothing else",
            "pinky new-repo pluto-poc-x --type web  # plus the docs skeleton and stubs",
        ],
    )
    p.add_argument("name", help="the repo to create — pinky-* or pluto-*")
    p.add_argument(
        "--scaffold",
        action="store_true",
        help="also write the docs/ skeleton and the stub files (README, pyproject, LICENSE…)",
    )
    p.add_argument(
        "--type",
        choices=REPO_TYPES,
        default=None,
        help="the manifest --scaffold writes (default: lib) — implies --scaffold",
    )
    p.set_defaults(func=cmd_new_repo)

    p = _add(
        sub,
        "distribute",
        "📦 distribute the hygiene hooks (pre-commit, CI) to one repo or --all",
        [
            "pinky distribute --repo pinky-core --dry-run  # preview one repo",
            "pinky distribute --all --commit  # every repo, one commit each",
        ],
    )
    target = p.add_mutually_exclusive_group()
    target.add_argument(
        "--repo", default=None, metavar="NAME", help="one repo of the workspace"
    )
    target.add_argument(
        "--all", action="store_true", help="every repo of the workspace"
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="commit the distributed files in each repo",
    )
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
    p.add_argument(
        "--dry-run", action="store_true", help="print what would change, write nothing"
    )
    p.set_defaults(func=cmd_distribute)

    p = _add(
        sub,
        "install",
        "🚀 replayable installer — converges this machine's setup",
        [
            "pinky install  # the workspace rules, then the doctor",
            "pinky install --plugin pc-kanban  # enable a plugin through the scope wizard",
            "pinky install --theme lisible  # one named theme",
        ],
        extra=_assets_epilog(),
    )
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="apply without asking (required in a non-interactive shell)",
    )
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

    p = _add(
        sub,
        "rules",
        "📐 distribute each plugin's rules to the same scope its plugin is installed at",
        [
            "pinky rules --dry-run  # show the plan, write nothing",
            "pinky rules --yes  # apply the plan without asking",
        ],
    )
    p.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="the workspace root to resolve install scopes from (default: the detected one)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print the plan and stop, never ask"
    )
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="apply the plan without asking (required in a non-interactive shell)",
    )
    p.set_defaults(func=cmd_rules)

    p = _add(
        sub,
        "drift",
        "🧭 report where each repo differs from the hooks pinky-bootstrap distributes",
        ["pinky drift  # every repo, writes nothing"],
    )
    p.set_defaults(func=cmd_drift)

    p = _add(
        sub,
        "llm-drift",
        "🧹 find what agents leave in Python code that every read pays for, and clean it",
        [
            "pinky llm-drift  # scan the repo you are in",
            "pinky llm-drift --repo pinky-provider  # scan one repo",
            "pinky llm-drift fix --repo pinky-provider --dry-run  # what a cleanup would save",
            "pinky llm-drift fix --all  # clean every repo (never commits)",
        ],
        extra=_drift_kinds_epilog(),
    )
    p.add_argument(
        "action",
        nargs="?",
        default="scan",
        choices=["scan", "fix"],
        help="scan (default): report, write nothing · fix: rewrite the files",
    )
    target = p.add_mutually_exclusive_group()
    target.add_argument(
        "--repo",
        default=None,
        metavar="NAME",
        help="one repo of the workspace (default: the repo you are in)",
    )
    target.add_argument(
        "--all", action="store_true", help="every repo of the workspace"
    )
    p.add_argument(
        "--kind",
        action="append",
        default=None,
        choices=[kind.name for kind in DRIFT_KINDS],
        metavar="KIND",
        help="repeatable, one of the drift kinds below",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="with fix: print the savings, write nothing",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="with scan: JSON snapshot instead of the report",
    )
    p.set_defaults(func=cmd_llm_drift)

    p = _add(
        sub,
        "directives",
        "📌 the inline directive to paste for an error code (noqa, type: ignore, nosec…)",
        [
            "pinky directives E402  # → # noqa: E402",
            "pinky directives '[type-arg]'  # quote brackets, zsh globs them",
            "pinky directives  # the whole table",
        ],
    )
    p.add_argument(
        "code",
        nargs="?",
        default=None,
        help="the code a tool printed — E402, [type-arg], B608… (omit it for the whole table)",
    )
    p.set_defaults(func=cmd_directives)

    p = _add(
        sub,
        "docs",
        "📖 live board/log viewer — serve it, check its status, or remove it",
        [
            "pinky install --live-docs  # install it first",
            "pinky docs serve  # run the site now, no service",
            "pinky docs status",
        ],
    )
    p.add_argument(
        "action",
        choices=["serve", "status", "uninstall"],
        help="serve: run the site live, no service · status: posed / not-mine / absent · "
        "uninstall: remove what `pinky install --live-docs` posed",
    )
    p.set_defaults(func=cmd_docs)

    p = _add(
        sub,
        "plugins",
        "🧩 audit / reconcile where each plugin is enabled across the workspace",
        [
            "pinky plugins reconcile  # audit, writes nothing",
            "pinky plugins reconcile --apply  # place each plugin, interactively",
        ],
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

    p = _add(
        sub,
        "doctor",
        "🩺 check the prerequisites installed plugins assume (binaries, Ollama, API keys)",
        [
            "pinky doctor  # report what is missing",
            "pinky doctor --fix  # offer to brew install it",
        ],
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help="offer to `brew install` each missing binary and Ollama",
    )
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse `argv` and dispatch to the matching `cmd_*`; print help and exit 1 if no sub-command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)
