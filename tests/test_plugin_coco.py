"""`setup.plugin_coco` — the scope chain, cortex's command line, and the validation parsing.

Boundary fakes only: `subprocess.run` (a fake `cortex` binary — the real one is never run),
`shutil.which`, and the home-dir paths the registry read goes through. `active_specs_for_dir`,
`render_plan`, `cortex_command` and the parse stay real.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli, plugin_coco, plugin_install, plugin_reconcile
from setup.common import WorkspaceOrigin


class _CortexSim:
    """Faux binaire `cortex` : `plugin validate` répond le stdout enregistré pour ce dossier
    (ou lève l'exception enregistrée), tout autre appel est enregistré et renvoie 0."""

    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []
        self.validate_stdout: dict[Path, str] = {}
        self.validate_stderr: dict[Path, str] = {}
        self.validate_error: dict[Path, Exception] = {}

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), dict(kw)))
        if cmd[:3] == ["cortex", "plugin", "validate"]:
            cwd = Path(kw["cwd"])
            if cwd in self.validate_error:
                raise self.validate_error[cwd]
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=self.validate_stdout.get(cwd, ""),
                stderr=self.validate_stderr.get(cwd, ""),
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def launch_calls(self) -> list[tuple[list[str], dict]]:
        """Les appels qui ne sont pas des `plugin validate` — le lancement lui-même."""
        return [
            call
            for call in self.calls
            if call[0][:3] != ["cortex", "plugin", "validate"]
        ]


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(plugin_reconcile, "_USER_CLAUDE", home / ".claude")
    monkeypatch.setattr(plugin_reconcile, "_REGISTRY", registry)
    monkeypatch.setattr(plugin_install, "_REGISTRY", registry)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/bin/cortex")
    sim = _CortexSim()
    monkeypatch.setattr(subprocess, "run", sim)
    ws = tmp_path / "workspace"
    (ws / "grp" / "repo" / ".git").mkdir(parents=True)
    return SimpleNamespace(
        home=home, ws=ws, registry=registry, sim=sim, repo=ws / "grp" / "repo"
    )


def _install(env, spec: str, description: str = "") -> Path:
    """Un plugin installé : entrée de registre + manifeste sur disque ; renvoie son dossier."""
    path = env.home / "cache" / spec.replace("@", "-")
    (path / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": spec.partition("@")[0], "description": description}),
        encoding="utf-8",
    )
    reg = (
        json.loads(env.registry.read_text(encoding="utf-8"))
        if env.registry.is_file()
        else {"version": 2, "plugins": {}}
    )
    reg["plugins"].setdefault(spec, []).append(
        {"scope": "user", "installPath": str(path), "version": "0.1.0"}
    )
    env.registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
    return path


def _enable(
    settings_dir: Path, spec: str, value: bool = True, local: bool = False
) -> None:
    name = "settings.local.json" if local else "settings.json"
    p = settings_dir / ".claude" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data.setdefault("enabledPlugins", {})[spec] = value
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _canned(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _keep_all(items, title, **kwargs):
    return [item.checked for item in items]


# ── the scope chain: nearest first, local before plain, user last ──────────────────────────


def test_scope_chain_labels_orders_nearest_first(env):
    """Whole-list oracle : le repo d'abord (local puis plain), chaque ancêtre en remontant,
    user en dernier."""
    label_map = plugin_reconcile.label_to_settings(env.ws)

    assert plugin_coco.scope_chain_labels(label_map, env.repo) == [
        "grp/repo (local)",
        "grp/repo",
        "grp (local)",
        "grp",
        ". (local)",
        ".",
        "user",
    ]


def test_active_specs_resolves_user_group_repo_and_opt_out(env):
    """User porte, le groupe porte, le repo porte — et un `false` au repo coupe un enable user
    (le plus proche gagne). Un `settings.local.json` du repo compte ; un plugin nulle part
    activé (simple entrée de registre) reste inactif."""
    _enable(env.home, "pc-a@mp")
    _enable(env.ws / "grp", "pc-b@mp")
    _enable(env.repo, "pc-a@mp", value=False)  # opt-out explicite d'un enable user
    _enable(env.repo, "pc-c@mp")
    _enable(env.repo, "pc-d@mp", local=True)
    _install(env, "pc-e@mp")  # installé, jamais activé

    audit = plugin_reconcile.audit_plugins(env.ws)
    label_map = plugin_reconcile.label_to_settings(env.ws)

    assert plugin_coco.active_specs_for_dir(audit, label_map, env.repo) == [
        "pc-b@mp",
        "pc-c@mp",
        "pc-d@mp",
    ]


def test_project_root_walks_up_to_git_root(env, tmp_path):
    (env.repo / "sub" / "deeper").mkdir(parents=True)
    outside = tmp_path / "no-git-here"
    outside.mkdir()

    assert plugin_coco.project_root(env.repo / "sub" / "deeper") == env.repo.resolve()
    assert plugin_coco.project_root(env.repo) == env.repo.resolve()
    assert plugin_coco.project_root(outside) == outside.resolve()


# ── validation parsing: raw issues, clean, unavailable ─────────────────────────────────────


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (
            "Plugin 'pc-a' has 2 validation issue(s):\n"
            "- [hooks] hooks/guard.json: unknown event 'UserPromptExpansion'\n"
            "Tip: an activation.md file would help cortex load this plugin.\n"
            '- [mcp] .mcp.json: missing "type"\n',
            [
                "- [hooks] hooks/guard.json: unknown event 'UserPromptExpansion'",
                '- [mcp] .mcp.json: missing "type"',
            ],
        ),
        ("Plugin 'pc-b' has 0 validation issues.\n", []),
        ("", None),
        ("Traceback (most recent call last): boom", None),
        ("a crash text that merely says the word validation", None),
    ],
)
def test_parse_validation_keeps_raw_issue_lines(output, expected):
    assert plugin_coco.parse_validation(output) == expected


def test_validate_entries_marks_error_and_unresolved_unavailable(env):
    """Timeout, binaire absent, sortie inattendue : jamais un verdict — indisponible. Un plugin
    sans dossier n'est pas validé du tout (indisponible aussi)."""
    path = _install(env, "pc-a@mp")
    env.sim.validate_error[path] = subprocess.TimeoutExpired("cortex", 15)

    entries = [
        plugin_coco.resolve_entry("pc-a@mp"),
        plugin_coco.resolve_entry("pc-x@mp"),
    ]

    assert plugin_coco.validate_entries(entries) == {"pc-a@mp": None, "pc-x@mp": None}


# ── the rendered surfaces: whole-string oracles ────────────────────────────────────────────


def test_entry_line_shapes():
    """Whole-line oracles : id nu (sans marketplace), marqueur compact, jamais de verdict
    rassurant."""
    base = plugin_coco.CocoEntry(
        spec="pc-a@mp",
        install_path=Path("/cache/pc-a"),
        description="Git workflow",
        issues=[],
    )
    assert plugin_coco.entry_line(base, width=80) == "pc-a — Git workflow"
    assert (
        plugin_coco.entry_line(
            plugin_coco.CocoEntry(
                "pc-a@mp",
                Path("/cache/pc-a"),
                "Git workflow",
                ["- [mcp] .mcp.json: no type"],
            ),
            width=80,
        )
        == "pc-a — Git workflow  ⚠ 1 validation issue"
    )
    assert (
        plugin_coco.entry_line(
            plugin_coco.CocoEntry(
                "pc-a@mp",
                Path("/cache/pc-a"),
                "Git workflow",
                ["- [mcp] .mcp.json: no type", "- [hooks] hooks.json: unknown event"],
            ),
            width=80,
        )
        == "pc-a — Git workflow  ⚠ 2 validation issues"
    )
    assert (
        plugin_coco.entry_line(
            plugin_coco.CocoEntry("pc-a@mp", Path("/cache/pc-a"), "Git workflow", None),
            width=80,
        )
        == "pc-a — Git workflow  ⚠ validation unavailable"
    )
    assert (
        plugin_coco.entry_line(
            plugin_coco.CocoEntry("pc-a@mp", None, "", None), width=80
        )
        == "pc-a  ⚠ unresolved — no installed_plugins.json entry"
    )


def test_entry_line_truncates_the_description_to_the_width():
    entry = plugin_coco.CocoEntry("pc-a@mp", Path("/cache/pc-a"), "A" * 60, None)

    # budget : 60 - 4 (id) - 26 (marqueur) - 8 (marge) = 22 colonnes de description
    assert plugin_coco.entry_line(entry, width=60) == (
        f"pc-a — {'A' * 21}…  ⚠ validation unavailable"
    )


def test_render_plan_whole_string(env):
    entries = [
        plugin_coco.CocoEntry(
            "pc-b@mp",
            env.home / "cache" / "pc-b-mp",
            "Kanban",
            ["- [hooks] hooks.json: unknown event 'UserPromptExpansion'"],
        ),
        plugin_coco.CocoEntry("pc-inline@mp", None, "", None),
    ]

    assert plugin_coco.render_plan(entries, env.repo) == (
        f"cortex in {env.repo}:\n"
        f"  pc-b@mp → {env.home / 'cache' / 'pc-b-mp'}\n"
        "      - [hooks] hooks.json: unknown event 'UserPromptExpansion'\n"
        "  pc-inline@mp — unresolved (no installed_plugins.json entry)"
    )


def test_cortex_command_repeats_plugin_dir():
    assert plugin_coco.cortex_command([Path("/a"), Path("/b")]) == [
        "cortex",
        "--plugin-dir",
        "/a",
        "--plugin-dir",
        "/b",
    ]
    assert plugin_coco.cortex_command([]) == ["cortex"]


def test_cortex_env_adds_project_dir_and_keeps_the_rest():
    env = plugin_coco.cortex_env({"PATH": "/bin", "HOME": "/home"}, Path("/ws/repo"))

    assert env == {"PATH": "/bin", "HOME": "/home", "CLAUDE_PROJECT_DIR": "/ws/repo"}


# ── run(): picker → plan → confirm → launch, mocked cortex ─────────────────────────────────


def test_run_launches_cortex_with_each_dir_and_the_project_env(
    env, monkeypatch, capsys
):
    pc_a = _install(env, "pc-a@mp", "Audit")
    pc_b = _install(env, "pc-b@mp", "Kanban")
    _enable(env.home, "pc-a@mp")
    _enable(env.ws / "grp", "pc-b@mp")
    env.sim.validate_stdout[pc_a] = "Plugin 'pc-a' has 0 validation issues.\n"
    # cortex mesuré : le rapport d'erreurs part sur stderr (exit 1), le propre sur stdout
    env.sim.validate_stderr[pc_b] = (
        "Plugin 'pc-b' has 1 validation issue(s):\n- [hooks] hooks.json: unknown event\n"
    )
    _canned(monkeypatch, ["y"])

    code = plugin_coco.run(env.ws, start_dir=env.repo, picker=_keep_all)

    assert code == 0
    # le plan porte la ligne d'erreur brute, indentée sous son plugin
    assert (
        "      - [hooks] hooks.json: unknown event"
        in capsys.readouterr().out.splitlines()
    )
    [launch] = env.sim.launch_calls()
    cmd, kw = launch
    assert cmd == [
        "cortex",
        "--plugin-dir",
        str(pc_a),
        "--plugin-dir",
        str(pc_b),
    ]
    assert kw["cwd"] == env.repo.resolve()
    assert kw["env"]["CLAUDE_PROJECT_DIR"] == str(env.repo.resolve())
    validated = {
        Path(kw["cwd"])
        for cmd, kw in env.sim.calls
        if cmd[:3] == ["cortex", "plugin", "validate"]
    }
    assert validated == {pc_a, pc_b}


def test_run_dry_run_prints_the_command_and_never_launches(env, monkeypatch, capsys):
    import shlex

    pc_a = _install(env, "pc-a@mp")
    _enable(env.home, "pc-a@mp")
    _canned(monkeypatch, ["y"])

    code = plugin_coco.run(env.ws, start_dir=env.repo, dry_run=True, picker=_keep_all)

    assert code == 0
    assert env.sim.launch_calls() == []
    assert (
        f"$ {shlex.join(plugin_coco.cortex_command([pc_a]))}"
        in capsys.readouterr().out.splitlines()
    )


def test_run_reports_an_unresolved_plugin_without_blocking(env, monkeypatch, capsys):
    pc_a = _install(env, "pc-a@mp")
    _enable(env.home, "pc-a@mp")
    _enable(env.repo, "pc-inline@mp")  # actif, mais aucune entrée de registre
    _canned(monkeypatch, ["y"])

    code = plugin_coco.run(env.ws, start_dir=env.repo, picker=_keep_all)

    assert code == 0
    assert (
        "  pc-inline@mp — unresolved (no installed_plugins.json entry)"
        in capsys.readouterr().out.splitlines()
    )
    [launch] = env.sim.launch_calls()
    assert launch[0] == ["cortex", "--plugin-dir", str(pc_a)]


def test_run_yes_skips_every_prompt(env, monkeypatch):
    _install(env, "pc-a@mp")
    _enable(env.home, "pc-a@mp")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("no prompt is expected under --yes")
    )

    code = plugin_coco.run(env.ws, start_dir=env.repo, yes=True)

    assert code == 0
    # un seul appel au faux cortex : le lancement — aucun `plugin validate` sans sélecteur
    assert len(env.sim.calls) == 1
    assert len(env.sim.launch_calls()) == 1


def test_run_without_a_tty_and_without_yes_refuses(env, monkeypatch):
    _install(env, "pc-a@mp")
    _enable(env.home, "pc-a@mp")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(SystemExit) as excinfo:
        plugin_coco.run(env.ws, start_dir=env.repo, picker=_keep_all)

    assert excinfo.value.code == 1
    assert env.sim.launch_calls() == []


def test_run_without_cortex_on_path_errors_clearly(env, monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(SystemExit) as excinfo:
        plugin_coco.run(env.ws, start_dir=env.repo)

    assert excinfo.value.code == 1
    assert "`cortex` not found on PATH" in capsys.readouterr().err


def test_run_declined_prints_cancelled_and_launches_nothing(env, monkeypatch, capsys):
    _install(env, "pc-a@mp")
    _enable(env.home, "pc-a@mp")
    _canned(monkeypatch, ["n"])

    code = plugin_coco.run(env.ws, start_dir=env.repo, picker=_keep_all)

    assert code == 0
    assert "cancelled." in capsys.readouterr().out.splitlines()
    assert env.sim.launch_calls() == []


def test_cli_flag_dispatches_to_run_and_propagates_the_exit_code(env, monkeypatch):
    seen = {}

    def fake_run(workspace_root, *, yes=False, dry_run=False, **kw):
        seen.update(root=workspace_root, yes=yes, dry_run=dry_run)
        return 7

    monkeypatch.setattr(plugin_coco, "run", fake_run)
    monkeypatch.setattr(
        cli, "resolve_workspace_root", lambda *a, **k: WorkspaceOrigin(env.ws, "test")
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--plugins-coco", "--yes"])

    assert excinfo.value.code == 7
    assert seen == {"root": env.ws, "yes": True, "dry_run": False}
