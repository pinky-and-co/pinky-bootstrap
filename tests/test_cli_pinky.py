"""`cli_pinky.py` — sub-commands over `setup.py`'s flags (chantier-0001, card
`cli-pinky-sous-commandes-au-lieu-de-flags`).

Pins the exact defect the card measured: `setup.py --help` swallows `--help` as an unknown flag
(`add_help=False` + `parse_known_args`) and falls into the interactive install branch, which WRITES.
`cli_pinky.py --help` must exit 0, print the sub-commands, and write nothing.

Dispatch is tested by capturing what each `cmd_*` hands to `setup.cli.main()` — proof the helper
stays a thin translator (the card's "zero logic" constraint), never a second copy of setup/cli.py's
mode logic.

The implementation lives in `setup/cli_pinky.py` (kanban card `cli-pinky-py-n-est-pas-editable`);
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
        "new-repo",
        "distribute",
        "install",
        "rules",
        "drift",
    ):
        assert name in out
    assert list(tmp_path.iterdir()) == []


def test_help_names_the_command_the_reader_typed(monkeypatch, capsys):
    """L'aide nomme `argv[0]`, jamais un nom de fichier codé en dur.

    `prog="cli_pinky.py"` était figé, donc `pinky drift --help` répondait
    `usage: cli_pinky.py drift` — le nom d'un fichier que personne ne tape, propagé à CHAQUE
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
            cli_pinky.main(["drift", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert out.startswith(f"usage: {expected} drift"), out.splitlines()[0]


def test_no_command_is_an_error_not_a_silent_default(capsys):

    with pytest.raises(SystemExit) as exc:
        cli_pinky.main([])
    assert exc.value.code != 0


def _captured_argv(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_pinky_impl, "setup_main", lambda argv: calls.append(argv))
    return calls


def test_new_repo_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["new-repo", "pinky-foo", "--scaffold", "--type", "web"])
    assert calls == [["--new-repo", "pinky-foo", "--scaffold", "--type", "web"]]


def test_new_repo_type_implies_scaffold(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["new-repo", "pinky-foo", "--type", "data"])
    assert calls == [["--new-repo", "pinky-foo", "--scaffold", "--type", "data"]]


def test_distribute_dispatch_repo(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["distribute", "--repo", "pinky-core", "--commit"])
    assert calls == [["--repo", "pinky-core", "--commit"]]


def test_distribute_dispatch_all(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["distribute", "--all"])
    assert calls == [["--all"]]


def test_distribute_dispatch_agents_md(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["distribute", "--repo", "pinky-core", "--agents-md"])
    assert calls == [["--repo", "pinky-core", "--agents-md"]]


def test_distribute_dispatch_agents_md_standalone(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(
        ["distribute", "--repo", "pinky-core", "--agents-md", "--standalone"]
    )
    assert calls == [["--repo", "pinky-core", "--agents-md", "--standalone"]]


def test_llm_drift_dispatch_scan(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["llm-drift", "scan", "--all", "--kind", "narrative", "--json"])
    assert calls == [["--llm-drift", "scan", "--all", "--kind", "narrative", "--json"]]


def test_directives_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["directives", "E402"])
    cli_pinky.main(["directives"])
    assert calls == [["--directives", "E402"], ["--directives"]]


def test_every_subcommand_explains_itself():
    parser = cli_pinky_impl.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, command in sub.choices.items():
        assert command.description, name
        assert "💡 examples:" in (command.epilog or ""), name
        for action in command._actions:
            if not isinstance(action, argparse._HelpAction):
                assert action.help, f"{name} {action.dest}"


def test_llm_drift_defaults_to_scan(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["llm-drift", "--repo", "pinky-provider"])
    assert calls == [["--llm-drift", "scan", "--repo", "pinky-provider"]]


def test_llm_drift_rejects_an_unknown_kind_naming_the_known_ones(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_pinky.main(["llm-drift", "--kind", "oups"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'oups'" in err
    for kind in ("comments", "narrative", "long-comment"):
        assert kind in err


def test_repo_and_all_are_mutually_exclusive(capsys):
    for command in ("llm-drift", "distribute"):
        with pytest.raises(SystemExit) as exc:
            cli_pinky.main([command, "--repo", "pinky-core", "--all"])
        assert exc.value.code == 2
        assert "not allowed with argument" in capsys.readouterr().err


def test_llm_drift_dispatch_fix(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["llm-drift", "fix", "--repo", "pinky-core", "--dry-run"])
    assert calls == [["--llm-drift", "fix", "--repo", "pinky-core", "--dry-run"]]


def test_install_dispatch_default(monkeypatch):

    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install"])
    assert calls == [["--rules"]]


def test_install_dispatch_yes(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install", "--yes"])
    assert calls == [["--rules", "--yes"]]


def test_install_dispatch_plugin(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install", "--plugin", "pc-statusline"])
    assert calls == [["--plugin", "pc-statusline"]]


def test_install_dispatch_plugin_with_marketplace(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(
        [
            "install",
            "--plugin",
            "pc-statusline",
            "--marketplace",
            "pinky-agentic-plugins",
        ]
    )
    assert calls == [
        ["--plugin", "pc-statusline", "--marketplace", "pinky-agentic-plugins"]
    ]


def test_install_dispatch_plugin_threads_yes_and_force(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["install", "--plugin", "pc-x", "--yes", "--force"])
    assert calls == [["--plugin", "pc-x", "--yes", "--force"]]


def test_rules_dispatch_default_workspace(monkeypatch):

    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["rules"])
    assert calls == [["--rules"]]


def test_rules_dispatch_explicit_workspace(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["rules", "/tmp/some-workspace", "--dry-run", "--yes"])
    assert calls == [["--rules", "/tmp/some-workspace", "--dry-run", "--yes"]]


def test_drift_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["drift"])
    assert calls == [["--check-drift"]]


def test_plugins_reconcile_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["plugins", "reconcile"])
    assert calls == [["--plugins-reconcile"]]


def test_plugins_reconcile_apply_dispatch(monkeypatch):
    calls = _captured_argv(monkeypatch)
    cli_pinky.main(["plugins", "reconcile", "--apply"])
    assert calls == [["--plugins-reconcile-apply"]]


def test_setup_main_accepts_explicit_argv_not_sys_argv(monkeypatch):
    import setup.cli

    monkeypatch.setattr(sys, "argv", ["setup.py", "--rules", "/from-sys-argv"])
    seen: list = []
    monkeypatch.setattr(
        setup.cli,
        "distribute_all_plugin_rules",
        lambda workspace, apply: seen.append((workspace, apply)) or {},
    )
    monkeypatch.setattr(setup.cli, "print_all_plugin_rules_report", lambda plan: None)

    setup.cli.main(["--rules", "/from-explicit-argv"])

    assert [workspace for workspace, _ in seen] == [Path("/from-explicit-argv")]


def test_root_shim_reexports_the_same_objects_as_setup_cli_pinky():
    assert cli_pinky.main is cli_pinky_impl.main
    assert cli_pinky.setup_main is cli_pinky_impl.setup_main
