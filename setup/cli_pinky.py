"""pinky-bootstrap toolbox — sub-commands over setup.py's flags.

Lives in `setup/` — not at the repo root — so an editable install (`packages = ["setup"]`) picks up
edits live. The root-level `cli_pinky.py` shim exists purely so `python cli_pinky.py …` still works
from a bare clone; it re-exports `main`/`setup_main` from here unchanged.

Thin dispatch ONLY: every `cmd_*` below builds the equivalent `setup.cli` flags and delegates to
`setup.cli.main()` — the single source of truth for what each mode does stays `setup/cli.py`. Any
rule that lands here instead is a bug. `setup.py` itself stays fully usable with its own flags: CI,
the test suite and a third-party machine call the engine directly, this is a facade over it.

Usage:
    python cli_pinky.py repo new pluto-poc-x --scaffold --type web
    python cli_pinky.py repo distribute --repo pinky-core
    python cli_pinky.py install
    python cli_pinky.py claude-plugin install pc-kanban
    python cli_pinky.py repo drift
    python cli_pinky.py repo llm-drift scan --all
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
            "🎨 Available output-styles (pinky claude-config-preset install output-style NAME):",
            "\n".join(
                f"  {a.name:<12} {a.description}"
                for a in agentic_assets.discover_output_styles()
            ),
        ),
        (
            "🖌️  Available themes (pinky claude-config-preset install theme NAME):",
            "\n".join(
                f"  {a.name:<12} {a.description}"
                for a in agentic_assets.discover_themes()
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
    if args.yes:
        argv.append("--yes")
    setup_main(argv)


def cmd_drift(args: argparse.Namespace) -> None:
    """Translate `repo drift` to `setup.cli`'s `--check-drift`."""
    setup_main(["--check-drift"])


def cmd_llm_drift(args: argparse.Namespace) -> None:
    """Translate `repo llm-drift` flags to `setup.cli`'s `--llm-drift` and its options."""
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


def cmd_live_docs(args: argparse.Namespace) -> None:
    """Translate `live-docs <verb>` to `setup.cli`'s `--live-docs` / `--live-docs-<verb>`."""
    if args.verb == "install":
        setup_main(["--live-docs", *(["--force"] if args.force else [])])
    else:
        setup_main([f"--live-docs-{args.verb}"])


def _run_doctor_advisory() -> None:
    """The prerequisites report that closes an install — advisory, never fails the install."""
    from . import doctor

    print()
    doctor.run_doctor(fix=False)


def cmd_claude_plugin(args: argparse.Namespace) -> None:
    """Translate `claude-plugin <verb>` to `setup.cli`'s plugin flags.

    `install` fetches the plugin then runs the scope wizard (`--plugin`); `list` is the audit
    report, `who` the provenance report, `reconcile` the interactive placer.
    """
    if args.verb == "install":
        argv = ["--plugin", args.plugin]
        if args.marketplace:
            argv += ["--marketplace", args.marketplace]
        if args.yes:
            argv.append("--yes")
        if args.force:
            argv.append("--force")
        setup_main(argv)
        _run_doctor_advisory()
    elif args.verb == "list":
        setup_main(["--plugins-who"] if args.who else ["--plugins-reconcile"])
    else:
        setup_main(["--plugins-reconcile-apply"])


def cmd_claude_config_preset(args: argparse.Namespace) -> None:
    """Translate `claude-config-preset install <type> <name>` to `--output-style` / `--theme`."""
    setup_main([f"--{args.kind}", args.name])
    _run_doctor_advisory()


def cmd_install(args: argparse.Namespace) -> None:
    """Replayable installer that converges this machine's setup: the workspace rules, then the
    prerequisites report."""
    argv = ["--rules"]
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
    setup_main(argv)
    _run_doctor_advisory()


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


def _subject(
    sub: "argparse._SubParsersAction[argparse.ArgumentParser]",
    name: str,
    summary: str,
    examples: list[str],
    extra: str = "",
) -> "argparse._SubParsersAction[argparse.ArgumentParser]":
    """A subject (`claude-plugin`, `repo`…): a sub-command whose own sub-commands are its verbs."""
    parser = _add(sub, name, summary, examples, extra)
    return parser.add_subparsers(dest="verb", required=True, metavar="VERB")


def build_parser() -> argparse.ArgumentParser:
    """Build the `pinky` argument parser: subject then verb, like `claude plugin install`."""
    parser = argparse.ArgumentParser(
        description="🧰 pinky-bootstrap toolbox — see setup.py for the underlying flags.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=False)

    verbs = _subject(
        sub,
        "claude-plugin",
        "🧩 install, place and audit Claude Code plugins across the workspace",
        [
            "pinky claude-plugin install pc-kanban  # download + the scope wizard",
            "pinky claude-plugin list  # where each plugin is enabled",
            "pinky claude-plugin list --who  # which session ran each install",
        ],
    )
    p = _add(
        verbs,
        "install",
        "download a plugin and enable it through the scope wizard (user/project, depth, targets)",
        [
            "pinky claude-plugin install pc-kanban  # ask the scope, then download there",
            "pinky claude-plugin install pc-x --marketplace pinky-agentic-plugins --force",
        ],
    )
    p.add_argument(
        "plugin", metavar="PLUGIN", help="the plugin, without its marketplace"
    )
    p.add_argument(
        "--marketplace",
        default=None,
        help="the marketplace it comes from (asked when several carry the plugin)",
    )
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="apply without asking (required in a non-interactive shell)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="delete the plugin's cache dir before fetching, so a plugin pinned at 0.1.0 "
        "re-pulls the working tree (dev cache-bust)",
    )
    p.set_defaults(func=cmd_claude_plugin)
    p = _add(
        verbs,
        "list",
        "per-plugin audit: where it is enabled, where its files are, whether it ships a status line",
        [
            "pinky claude-plugin list  # writes nothing",
            "pinky claude-plugin list --who  # the session transcript behind each install",
        ],
    )
    p.add_argument(
        "--who",
        action="store_true",
        help="show which session ran each install instead: the proof of who installed what",
    )
    p.set_defaults(func=cmd_claude_plugin)
    p = _add(
        verbs,
        "reconcile",
        "interactively place each plugin (user / project / uninstall / skip), purging the enables "
        "that do not match",
        ["pinky claude-plugin reconcile  # one question per plugin"],
    )
    p.set_defaults(func=cmd_claude_plugin)

    verbs = _subject(
        sub,
        "claude-config-preset",
        "🎨 install a preset into ~/.claude: an output style or a theme",
        [
            "pinky claude-config-preset install output-style adhd",
            "pinky claude-config-preset install theme lisible",
        ],
        extra=_assets_epilog(),
    )
    p = _add(
        verbs,
        "install",
        "copy a preset to ~/.claude and set the matching setting",
        ["pinky claude-config-preset install theme lisible  # one named theme"],
    )
    p.add_argument(
        "kind",
        choices=["output-style", "theme"],
        help="the kind of preset",
    )
    p.add_argument("name", help="the preset, from the list below")
    p.set_defaults(func=cmd_claude_config_preset)

    verbs = _subject(
        sub,
        "live-docs",
        "📖 live board/log viewer — install it, serve it, check its status, or remove it",
        [
            "pinky live-docs install  # MkDocs tooling, board mounts, launchd service",
            "pinky live-docs serve  # run the site now, no service",
            "pinky live-docs status",
        ],
    )
    p = _add(
        verbs,
        "install",
        "install the viewer (MkDocs; on macOS a launchd service)",
        ["pinky live-docs install  # first time", "pinky live-docs install --force"],
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="replace a launchd agent pinky did not install",
    )
    p.set_defaults(func=cmd_live_docs)
    for verb, summary in (
        ("serve", "run the site live, no service"),
        ("status", "posed / not-mine / absent"),
        ("uninstall", "remove what `pinky live-docs install` posed"),
    ):
        p = _add(verbs, verb, summary, [f"pinky live-docs {verb}"])
        p.set_defaults(func=cmd_live_docs)

    verbs = _subject(
        sub,
        "repo",
        "📦 create, govern and audit the repos of the workspace",
        [
            "pinky repo new pinky-foo  # git init + the hooks",
            "pinky repo distribute --all --commit  # the hygiene hooks, one commit each",
            "pinky repo drift  # where each repo differs from the hooks",
        ],
    )
    p = _add(
        verbs,
        "new",
        "🌱 create a new (pinky-*/pluto-*) repo, already governed",
        [
            "pinky repo new pinky-foo  # git init + the hooks, nothing else",
            "pinky repo new pluto-poc-x --type web  # plus the docs skeleton and stubs",
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
        verbs,
        "distribute",
        "distribute the hygiene hooks (pre-commit, CI) to one repo or --all",
        [
            "pinky repo distribute --repo pinky-core --dry-run  # preview one repo",
            "pinky repo distribute --all --commit  # every repo, one commit each",
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
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="apply the plan without asking (required in a non-interactive shell)",
    )
    p.set_defaults(func=cmd_distribute)

    p = _add(
        verbs,
        "drift",
        "report where each repo differs from the hooks pinky-bootstrap distributes",
        ["pinky repo drift  # every repo, writes nothing"],
    )
    p.set_defaults(func=cmd_drift)

    p = _add(
        verbs,
        "llm-drift",
        "find what agents leave in Python code that every read pays for, and clean it",
        [
            "pinky repo llm-drift  # scan the repo you are in",
            "pinky repo llm-drift --repo pinky-provider  # scan one repo",
            "pinky repo llm-drift fix --repo pinky-provider --dry-run  # what a cleanup would save",
            "pinky repo llm-drift fix --all  # clean every repo (never commits)",
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
        "install",
        "🚀 replayable installer — the workspace rules, then the prerequisites report",
        [
            "pinky install  # distribute the rules, then the doctor",
            "pinky install --dry-run  # show the rules plan, write nothing",
        ],
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
    p.set_defaults(func=cmd_install)

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

    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse `argv` and dispatch to the matching `cmd_*`; print help and exit 1 if no sub-command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)
