"""`cli_pinky.py` — sub-commands over `setup.py`'s flags.

Pins the exact defect measured: `setup.py --help` swallows `--help` as an unknown flag
(`add_help=False` + `parse_known_args`) and falls into the interactive install branch, which WRITES.
`cli_pinky.py --help` must exit 0, print the sub-commands, and write nothing.

Dispatch is tested by capturing what each `cmd_*` hands to `setup.cli.main()` — proof the helper
stays a thin translator ("zero logic"), never a second copy of setup/cli.py's
mode logic.

The implementation lives in `setup/cli_pinky.py`;
`cli_pinky` (root) is a thin re-exporting shim over it. Tests call through `cli_pinky.main` — the
same function object as `cli_pinky_impl.main` — but patch dispatch targets on `cli_pinky_impl`,
since that's the module a `cmd_*` function's globals actually resolve `setup_main` against.
"""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import cli_pinky
import setup.cli_pinky as cli_pinky_impl


def test_help_exits_zero_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in (
        "claude-plugin",
        "live-docs",
        "repo",
        "install",
        "doctor",
        "directives",
    ):
        assert name in out
    assert list(tmp_path.iterdir()) == []


def test_help_names_the_command_the_reader_typed(monkeypatch, capsys):
    """L'aide nomme `argv[0]`, jamais un nom de fichier codé en dur.

    `prog="cli_pinky.py"` était figé, donc `pinky repo drift --help` répondait
    `usage: cli_pinky.py repo drift` — le nom d'un fichier que personne ne tape, propagé à CHAQUE
    sous-commande (elles héritent du prog du parent). Les deux points d'entrée sont légitimes
    (console script `pinky`, run direct `python cli_pinky.py`), donc aucun littéral ne peut être
    juste pour les deux : le défaut est le codage en dur lui-même, pas la valeur choisie.

    Simulé par `sys.argv[0]`, ce qu'argparse lit réellement — pas en patchant `prog`, ce qui
    testerait le test.
    """
    for argv0, expected in (
        ("/opt/venv/bin/pinky", "pinky"),
        ("cli_pinky.py", "cli_pinky.py"),
    ):
        monkeypatch.setattr(sys, "argv", [argv0])
        with pytest.raises(SystemExit) as exc:
            cli_pinky.main(["repo", "drift", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert out.startswith(f"usage: {expected} repo drift"), out.splitlines()[0]


def test_no_command_is_an_error_not_a_silent_default(capsys):

    with pytest.raises(SystemExit) as exc:
        cli_pinky.main([])
    assert exc.value.code != 0


def test_ctrl_c_exits_cleanly_with_no_traceback(monkeypatch, capsys):
    """A `KeyboardInterrupt` anywhere under a command (the scope wizard's `input()`,
    typically) exits 130 with a one-line message — never a raw Python traceback."""

    def _raise(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_pinky_impl, "setup_main", _raise)

    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(["claude-plugin", "install", "pc-x"])

    assert exc.value.code == 130
    assert capsys.readouterr().err == "cancelled.\n"


def _captured_argv(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_pinky_impl, "setup_main", lambda argv: calls.append(argv))
    return calls


def test_new_repo_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "new", "pinky-foo", "--scaffold", "--type", "web"])
    assert calls == [["--new-repo", "pinky-foo", "--scaffold", "--type", "web"]]


def test_new_repo_type_implies_scaffold(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "new", "pinky-foo", "--type", "data"])
    assert calls == [["--new-repo", "pinky-foo", "--scaffold", "--type", "data"]]


def test_distribute_dispatch_repo(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "distribute", "--repo", "pinky-core", "--commit"])
    assert calls == [["--repo", "pinky-core", "--commit"]]


def test_distribute_dispatch_yes_and_dry_run(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "distribute", "--repo", "pinky-core", "--dry-run"])
    cli_pinky.main(["repo", "distribute", "--repo", "pinky-core", "--yes"])
    assert calls == [
        ["--repo", "pinky-core", "--dry-run"],
        ["--repo", "pinky-core", "--yes"],
    ]


def test_distribute_dispatch_all(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "distribute", "--all"])
    assert calls == [["--all"]]


def test_llm_drift_dispatch_scan(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(
        ["repo", "llm-drift", "scan", "--all", "--kind", "narrative", "--json"]
    )
    assert calls == [["--llm-drift", "scan", "--all", "--kind", "narrative", "--json"]]


def test_directives_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["directives", "E402"])
    cli_pinky.main(["directives"])
    assert calls == [["--directives", "E402"], ["--directives"]]


def _walk_commands(parser, path=()):
    """Every (path, parser) below `parser`, depth-first: subjects, then their verbs."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, command in action.choices.items():
                yield path + (name,), command
                yield from _walk_commands(command, path + (name,))


def test_every_subcommand_explains_itself():
    parser = cli_pinky_impl.build_parser()
    for path, command in _walk_commands(parser):
        name = " ".join(path)
        assert command.description, name
        assert "💡 examples:" in (command.epilog or ""), name
        for action in command._actions:
            if not isinstance(action, argparse._HelpAction):
                assert action.help or isinstance(action, argparse._SubParsersAction), (
                    f"{name} {action.dest}"
                )


def test_every_command_emoji_is_one_zsh_completion_can_print():
    """The completion menu shows each command's description through zsh's `${(V)…}`, which spells
    out as `\\U0001f9e9` any character its libc does not know as printable — macOS's does not know the
    emoji added after Unicode 10 (🧩, 🩺, 🧰…). Stay below U+1F900, subjects and verbs alike —
    `pinky repo <TAB>` lists the verbs the same way."""
    parser = cli_pinky_impl.build_parser()
    for path, command in _walk_commands(parser):
        leading = command.description[0]
        assert ord(leading) < 0x1F900, (
            f"{' '.join(path)}: {leading!r} (U+{ord(leading):04X})"
        )


def test_help_lists_exactly_the_subjects_of_the_grid():
    """`pinky --help` presents each subject under one name — no subject reachable two ways."""
    parser = cli_pinky_impl.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {
        "claude-plugin",
        "live-docs",
        "repo",
        "install",
        "doctor",
        "directives",
        "completion",
    }


@pytest.mark.parametrize(
    "old_name",
    ["plugins", "rules", "new-repo", "distribute", "drift", "llm-drift", "docs"],
)
def test_a_retired_top_level_name_is_an_unknown_command(old_name, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main([old_name])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_llm_drift_defaults_to_scan(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "llm-drift", "--repo", "pinky-provider"])
    assert calls == [["--llm-drift", "scan", "--repo", "pinky-provider"]]


def test_llm_drift_rejects_an_unknown_kind_naming_the_known_ones(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(["repo", "llm-drift", "--kind", "oups"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'oups'" in err
    for kind in ("comments", "narrative", "long-comment"):
        assert kind in err


def test_repo_and_all_are_mutually_exclusive(capsys):
    for command in ("llm-drift", "distribute"):
        with pytest.raises(SystemExit) as exc:
            cli_pinky.main(["repo", command, "--repo", "pinky-core", "--all"])
        assert exc.value.code == 2
        assert "not allowed with argument" in capsys.readouterr().err


def test_llm_drift_dispatch_fix(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "llm-drift", "fix", "--repo", "pinky-core", "--dry-run"])
    assert calls == [["--llm-drift", "fix", "--repo", "pinky-core", "--dry-run"]]


def test_install_dispatch_default(monkeypatch):

    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install"])
    assert calls == [["--rules"]]


def test_install_dispatch_yes(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install", "--yes"])
    assert calls == [["--rules", "--yes"]]


def test_install_dispatch_dry_run(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install", "--dry-run", "--yes"])
    assert calls == [["--rules", "--dry-run", "--yes"]]


def test_claude_plugin_install_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "install", "pc-statusline"])
    assert calls == [["--plugin", "pc-statusline"]]


def test_claude_plugin_install_with_marketplace(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(
        [
            "claude-plugin",
            "install",
            "pc-statusline",
            "--marketplace",
            "pinky-agentic-plugins",
        ]
    )
    assert calls == [
        ["--plugin", "pc-statusline", "--marketplace", "pinky-agentic-plugins"]
    ]


def test_claude_plugin_install_threads_yes_and_force(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "install", "pc-x", "--yes", "--force"])
    assert calls == [["--plugin", "pc-x", "--yes", "--force"]]


def test_claude_plugin_install_with_no_name_and_no_tty_names_the_missing_option(capsys):
    """No name opens the curated/installed checkbox list, which needs a
    tty — outside one, it fails naming what's missing instead of guessing."""
    with pytest.raises(SystemExit):
        cli_pinky.main(["claude-plugin", "install"])
    assert "name the plugin(s) explicitly" in capsys.readouterr().err


def test_claude_plugin_install_threads_workspace_scope_dry_run_rules_dir(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(
        [
            "claude-plugin",
            "install",
            "pc-x",
            "--workspace",
            "/tmp/ws",
            "--scope",
            "pinky-lib",
            "--dry-run",
            "--rules-dir",
            "/tmp/rules",
        ]
    )
    assert calls == [
        [
            "--plugin",
            "pc-x",
            "--scope",
            "pinky-lib",
            "--workspace",
            "/tmp/ws",
            "--rules-dir",
            "/tmp/rules",
            "--dry-run",
        ]
    ]


def test_claude_plugin_install_threads_list(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "install", "--list", "/tmp/curated.toml"])
    assert calls == [["--plugin", "--list", "/tmp/curated.toml"]]


def test_claude_plugin_enable_threads_list(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "enable", "--list", "/tmp/curated.toml"])
    assert calls == [["--plugin-enable", "--list", "/tmp/curated.toml"]]


def test_claude_plugin_disable_has_no_list_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(["claude-plugin", "disable", "--list", "/tmp/curated.toml"])
    assert exc.value.code == 2


def test_claude_plugin_install_with_no_name_forwards_bare_plugin_flag(monkeypatch):
    """`install` with no name still reaches `--plugin` — `[]` vs the flag never being
    passed at all is the signal `cli.py` reads to open the picker."""
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "install"])
    assert calls == [["--plugin"]]


def test_claude_plugin_enable_with_no_name_forwards_bare_plugin_enable_flag(
    monkeypatch,
):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "enable"])
    assert calls == [["--plugin-enable"]]


def test_claude_plugin_disable_with_no_name_forwards_bare_plugin_disable_flag(
    monkeypatch,
):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "disable"])
    assert calls == [["--plugin-disable"]]


def test_live_docs_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["live-docs", "install"])
    cli_pinky.main(["live-docs", "install", "--force"])
    for verb in ("serve", "status", "uninstall"):
        cli_pinky.main(["live-docs", verb])
    assert calls == [
        ["--live-docs"],
        ["--live-docs", "--force"],
        ["--live-docs-serve"],
        ["--live-docs-status"],
        ["--live-docs-uninstall"],
    ]


def test_drift_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["repo", "drift"])
    assert calls == [["--check-drift"]]


@pytest.mark.parametrize(
    "argv",
    [
        ["install", "--plugin", "pc-x"],
        ["install", "--live-docs"],
    ],
)
def test_install_no_longer_takes_the_options_that_moved_to_their_subject(argv, capsys):
    """`pinky install` is the machine bootstrap: plugin and viewer moved to their own
    subject, so their old options fail."""
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(argv)
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_repo_exposes_new_distribute_drift_and_llm_drift():
    parser = cli_pinky_impl.build_parser()
    verbs = {p[1] for p, _ in _walk_commands(parser) if len(p) == 2 and p[0] == "repo"}
    assert verbs == {"new", "distribute", "drift", "llm-drift"}


def test_live_docs_exposes_install_serve_status_and_uninstall():
    parser = cli_pinky_impl.build_parser()
    verbs = {
        p[1] for p, _ in _walk_commands(parser) if len(p) == 2 and p[0] == "live-docs"
    }
    assert verbs == {"install", "serve", "status", "uninstall"}


def test_claude_plugin_list_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "list"])
    assert calls == [["--plugins-reconcile"]]


def test_claude_plugin_list_who_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "list", "--who"])
    assert calls == [["--plugins-who"]]


def test_claude_plugin_refresh_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "refresh", "pc-git", "pc-kanban"])
    assert calls == [["--plugins-refresh", "pc-git", "pc-kanban"]]


def test_claude_plugin_refresh_no_name_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "refresh"])
    assert calls == [["--plugins-refresh"]]


def test_claude_plugin_reconcile_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["claude-plugin", "reconcile"])
    assert calls == [["--plugins-reconcile-apply"]]


def test_setup_main_accepts_explicit_argv_not_sys_argv(monkeypatch):
    import setup.cli

    monkeypatch.setattr(sys, "argv", ["setup.py", "--rules", "/from-sys-argv"])
    seen: list = []
    monkeypatch.setattr(
        setup.cli,
        "distribute_all_plugin_rules",
        lambda workspace, apply, user_rules_dir=None: (
            seen.append((workspace, apply)) or {}
        ),
    )
    monkeypatch.setattr(
        setup.cli, "print_all_plugin_rules_report", lambda plan, **kwargs: None
    )

    setup.cli.main(["--rules", "/from-explicit-argv"])

    assert [workspace for workspace, _ in seen] == [Path("/from-explicit-argv")]


def test_root_shim_reexports_the_same_objects_as_setup_cli_pinky():
    assert cli_pinky.main is cli_pinky_impl.main
    assert cli_pinky.setup_main is cli_pinky_impl.setup_main


def test_completion_prints_the_zsh_registration_script(capsys):
    """`register-python-argcomplete` lives in the tool's own environment, not on the PATH: the
    script comes from `pinky` itself, so `eval "$(pinky completion zsh)"` works after a tool install."""
    cli_pinky.main(["completion", "zsh"])

    out = capsys.readouterr().out
    assert out.startswith("#compdef pinky")
    assert "compdef _python_argcomplete pinky" in out
