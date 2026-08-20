"""`setup/plugin_scope.py` — where a plugin/marketplace gets enabled.

`enabledPlugins` scopes by git-repo-root, not always user-level (ADR-0001, corrigé 2026-08-21) —
a plugin can be enabled at the workspace root, at a group directory (`pinky-lib/`, not itself a
git repo), or at one specific repo. Same merge logic at every level (`root/.claude/settings.json`),
including the user-scope case (`root = Path.home()`).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.plugin_scope import (
    enable_plugin,
    list_targets_at_depth,
    run_marketplace_wizard,
)


def _canned_input(monkeypatch, answers):
    """`input()` returns each of `answers` in order, one per call — no real terminal needed."""
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _workspace(tmp_path: Path) -> Path:
    """bootstrap/ (repo directly) + pinky-lib/ (group, 2 nested repos) + a dotfile dir to ignore."""
    root = tmp_path / "workspace"
    _make_repo(root / "bootstrap")
    _make_repo(root / "pinky-lib" / "pinky-core")
    _make_repo(root / "pinky-lib" / "pinky-snowpark")
    (root / ".hidden").mkdir(parents=True)
    return root


# ── list_targets_at_depth ───────────────────────────────────────────────────


def test_depth_0_is_the_workspace_root_itself(tmp_path):
    root = _workspace(tmp_path)
    assert list_targets_at_depth(root, depth=0) == [root]


def test_depth_1_lists_every_top_level_dir_repo_or_group(tmp_path):
    root = _workspace(tmp_path)
    targets = list_targets_at_depth(root, depth=1)
    assert {p.name for p in targets} == {"bootstrap", "pinky-lib"}


def test_depth_1_ignores_dotfile_directories(tmp_path):
    root = _workspace(tmp_path)
    targets = list_targets_at_depth(root, depth=1)
    assert ".hidden" not in {p.name for p in targets}


def test_depth_2_lists_repos_nested_under_depth_1_groups_only(tmp_path):
    root = _workspace(tmp_path)
    targets = list_targets_at_depth(root, depth=2)
    # bootstrap is itself a repo at depth 1 (no depth-2 descent into it); pinky-lib is a group.
    assert {p.name for p in targets} == {"pinky-core", "pinky-snowpark"}


def test_unsupported_depth_raises(tmp_path):
    root = _workspace(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        list_targets_at_depth(root, depth=3)


# ── enable_plugin ────────────────────────────────────────────────────────────


def test_enable_plugin_writes_settings_json_at_target(tmp_path):
    target = tmp_path / "pinky-lib"
    target.mkdir()
    enable_plugin(target, "pc-statusline", marketplace="pinky-agentic-plugins")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["enabledPlugins"]["pc-statusline@pinky-agentic-plugins"] is True


def test_enable_plugin_merges_never_overwrites_existing_settings(tmp_path):
    target = tmp_path / "pinky-lib"
    settings_path = target / ".claude"
    settings_path.mkdir(parents=True)
    (settings_path / "settings.json").write_text(
        json.dumps(
            {"someOtherKey": "keep-me", "enabledPlugins": {"already-here": True}}
        ),
        encoding="utf-8",
    )

    enable_plugin(target, "pc-statusline")

    data = json.loads((settings_path / "settings.json").read_text(encoding="utf-8"))
    assert data["someOtherKey"] == "keep-me"
    assert data["enabledPlugins"]["already-here"] is True
    assert data["enabledPlugins"]["pc-statusline"] is True


def test_enable_plugin_user_scope_is_the_same_merge_at_home(tmp_path, monkeypatch):
    import setup.plugin_scope as plugin_scope_module

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    enable_plugin(plugin_scope_module.Path.home(), "pc-statusline")

    data = json.loads(
        (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert data["enabledPlugins"]["pc-statusline"] is True


# ── run_marketplace_wizard — Q1 (user/project) -> Q2 (depth) -> Q3 (target) ──


def test_wizard_user_scope_skips_depth_and_target_questions(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    _canned_input(monkeypatch, ["u"])  # only Q1 — no depth/target prompt for user scope

    root = run_marketplace_wizard(tmp_path / "workspace", "pc-statusline")

    assert root == fake_home
    data = json.loads(
        (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert data["enabledPlugins"]["pc-statusline"] is True


def test_wizard_project_scope_depth_1_picks_a_group(tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    # Q1: project, Q2: depth 1, Q3: pick index of "pinky-lib" among sorted(["bootstrap", "pinky-lib"])
    _canned_input(monkeypatch, ["p", "1", "1"])

    chosen = run_marketplace_wizard(root_ws, "pc-statusline")

    assert chosen == root_ws / "pinky-lib"
    data = json.loads(
        (chosen / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert data["enabledPlugins"]["pc-statusline"] is True


def test_wizard_non_interactive_shell_errors_instead_of_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    import pytest

    with pytest.raises(SystemExit):
        run_marketplace_wizard(tmp_path, "pc-statusline")


def test_wizard_unknown_scope_answer_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    _canned_input(monkeypatch, ["nonsense"])
    import pytest

    with pytest.raises(SystemExit):
        run_marketplace_wizard(tmp_path, "pc-statusline")
