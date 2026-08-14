"""Settings render — permissions_deny → .claude/settings.json (least-agency baseline).

Defines "done" for the chantier-0001 card `permissions-deny`: setup.py renders a
profile's `permissions_deny` list into the generated `.claude/settings.json` under
`permissions.deny`, merging without clobbering existing keys and never touching
`settings.local.json`.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


# ── render_settings_deny — extract + normalize the profile's deny list ────────


def test_render_deny_returns_list_from_profile():
    profile = {"name": "poc", "permissions_deny": ["Read(~/.ssh/**)", "Bash(ssh *)"]}
    assert setup.render_settings_deny(profile) == ["Read(~/.ssh/**)", "Bash(ssh *)"]


def test_render_deny_absent_key_returns_empty():
    assert setup.render_settings_deny({"name": "p"}) == []


def test_render_deny_dedup_preserves_order():
    profile = {"permissions_deny": ["Bash(ssh *)", "Read(~/.ssh/**)", "Bash(ssh *)"]}
    assert setup.render_settings_deny(profile) == ["Bash(ssh *)", "Read(~/.ssh/**)"]


# ── render_settings_allow — extract + normalize the profile's allow baseline ──


def test_render_allow_returns_list_from_profile():
    profile = {"name": "p", "permissions_allow": ["Bash(git status:*)", "Bash(grep:*)"]}
    assert setup.render_settings_allow(profile) == [
        "Bash(git status:*)",
        "Bash(grep:*)",
    ]


def test_render_allow_absent_key_returns_empty():
    assert setup.render_settings_allow({"name": "p"}) == []


def test_render_allow_dedup_preserves_order():
    profile = {"permissions_allow": ["Bash(grep:*)", "Bash(ls:*)", "Bash(grep:*)"]}
    assert setup.render_settings_allow(profile) == ["Bash(grep:*)", "Bash(ls:*)"]


# ── _write_settings_json — merge into .claude/settings.json ───────────────────


def test_write_creates_settings_json_when_absent(tmp_path):
    profile = {"name": "poc", "permissions_deny": ["Bash(ssh *)"]}
    written = setup._write_settings_json(profile, tmp_path)
    target = tmp_path / "settings.json"
    assert written == target
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["permissions"]["deny"] == ["Bash(ssh *)"]


def test_write_skips_when_no_deny_and_no_allow(tmp_path):
    written = setup._write_settings_json({"name": "p"}, tmp_path)
    assert written is None
    assert not (tmp_path / "settings.json").exists()


def test_write_renders_allow_baseline(tmp_path):
    profile = {"name": "p", "permissions_allow": ["Bash(stat:*)", "Bash(git log:*)"]}
    setup._write_settings_json(profile, tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["Bash(stat:*)", "Bash(git log:*)"]
    assert "deny" not in data["permissions"]  # allow-only profile writes no deny key


def test_write_renders_allow_and_deny_together(tmp_path):
    profile = {
        "name": "p",
        "permissions_deny": ["Bash(ssh *)"],
        "permissions_allow": ["Bash(grep:*)"],
    }
    setup._write_settings_json(profile, tmp_path)
    perms = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))[
        "permissions"
    ]
    assert perms["deny"] == ["Bash(ssh *)"]
    assert perms["allow"] == ["Bash(grep:*)"]


def test_write_without_allow_key_preserves_existing_allow(tmp_path):
    # A profile that omits permissions_allow must NOT clobber an allow already on disk
    # (e.g. the developer's settings.local-style entries copied into settings.json).
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps({"permissions": {"allow": ["Bash(my-tool:*)"]}}), encoding="utf-8"
    )
    setup._write_settings_json(
        {"name": "p", "permissions_deny": ["Bash(ssh *)"]}, tmp_path
    )
    perms = json.loads(target.read_text(encoding="utf-8"))["permissions"]
    assert perms["allow"] == ["Bash(my-tool:*)"]
    assert perms["deny"] == ["Bash(ssh *)"]


def test_write_overwrites_stale_allow_on_reinstall(tmp_path):
    setup._write_settings_json(
        {"permissions_allow": ["Bash(ls:*)", "Bash(cat:*)"]}, tmp_path
    )
    setup._write_settings_json({"permissions_allow": ["Bash(ls:*)"]}, tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["Bash(ls:*)"]


def test_write_preserves_existing_allow_and_top_level_keys(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "model": "claude-opus-4-8",
                "permissions": {"allow": ["Bash(git status)"]},
            }
        ),
        encoding="utf-8",
    )
    profile = {"name": "poc", "permissions_deny": ["Bash(ssh *)"]}
    setup._write_settings_json(profile, tmp_path)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["model"] == "claude-opus-4-8"
    assert data["permissions"]["allow"] == ["Bash(git status)"]
    assert data["permissions"]["deny"] == ["Bash(ssh *)"]


def test_write_never_touches_settings_local_json(tmp_path):
    local = tmp_path / "settings.local.json"
    local.write_text(
        json.dumps({"permissions": {"allow": ["Read(/**)"]}}), encoding="utf-8"
    )
    setup._write_settings_json(
        {"name": "p", "permissions_deny": ["Bash(ssh *)"]}, tmp_path
    )
    assert json.loads(local.read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Read(/**)"]}
    }


def test_write_overwrites_stale_deny_on_reinstall(tmp_path):
    profile_v1 = {"name": "poc", "permissions_deny": ["Bash(nc *)", "Bash(ssh *)"]}
    setup._write_settings_json(profile_v1, tmp_path)
    profile_v2 = {"name": "poc", "permissions_deny": ["Bash(ssh *)"]}
    setup._write_settings_json(profile_v2, tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["permissions"]["deny"] == ["Bash(ssh *)"]


# ── _install_harness_hooks — Stop hook script + settings.json wiring ──────────


def test_harness_hooks_copies_script_and_wires_stop(tmp_path):
    setup._install_harness_hooks(tmp_path)
    assert (tmp_path / "hooks" / "stop_handoff.py").exists()
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    stop = data["hooks"]["Stop"]
    assert "stop_handoff.py" in stop[0]["hooks"][0]["command"]


def test_harness_hooks_copy_guard_and_wire_pretooluse(tmp_path):
    setup._install_harness_hooks(tmp_path)
    assert (tmp_path / "hooks" / "guard.py").exists()
    pre = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "PreToolUse"
    ]
    assert "guard.py" in pre[0]["hooks"][0]["command"]
    # the matcher must reach Bash (careful) and the write-class tools (freeze)
    assert "Bash" in pre[0]["matcher"] and "Edit" in pre[0]["matcher"]


def test_harness_hooks_privacy_matcher_covers_read_and_bash(tmp_path):
    # Loup audit 2026-07-04 : matcher Read seul → `cat secret.txt` (auto-allowed) contournait le
    # guard sans prompt. Le matcher doit couvrir les deux canaux d'ingestion.
    setup._install_harness_hooks(tmp_path)
    pre = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "PreToolUse"
    ]
    privacy = [g for g in pre if "check_privacy_egress" in g["hooks"][0]["command"]]
    assert (
        privacy and "Read" in privacy[0]["matcher"] and "Bash" in privacy[0]["matcher"]
    )


def test_harness_hooks_gitignore_guard_state(tmp_path):
    setup._install_harness_hooks(tmp_path)
    setup._install_harness_hooks(tmp_path)  # idempotent — no duplicate line
    ignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ignore.count(".guard-state.json") == 1


def test_harness_hooks_use_windows_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.platform, "system", lambda: "Windows")
    setup._install_harness_hooks(tmp_path)
    cmd = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "Stop"
    ][0]["hooks"][0]["command"]
    assert cmd.startswith("py -3 ")


def test_harness_hooks_use_python3_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    setup._install_harness_hooks(tmp_path)
    cmd = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "Stop"
    ][0]["hooks"][0]["command"]
    assert cmd.startswith("python3 ")


def test_harness_hooks_target_os_overrides_host_windows(tmp_path, monkeypatch):
    # Loup audit 2026-07-04 : --into rend depuis la machine AUTEUR (ex. Mac), pas la cible
    # (ex. frère, Windows) — platform.system() lit la mauvaise machine. target_os doit gagner.
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    setup._install_harness_hooks(tmp_path, target_os="Windows")
    cmd = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "Stop"
    ][0]["hooks"][0]["command"]
    assert cmd.startswith("py -3 ")


def test_harness_hooks_target_os_overrides_host_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.platform, "system", lambda: "Windows")
    setup._install_harness_hooks(tmp_path, target_os="posix")
    cmd = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "Stop"
    ][0]["hooks"][0]["command"]
    assert cmd.startswith("python3 ")


def test_harness_hooks_preserve_user_pretooluse_groups(tmp_path):
    # Loup mineur audit 2026-07-04 : `hooks["PreToolUse"] = […]` écrasait tout groupe utilisateur,
    # alors que la docstring promet la préservation. Seuls les groupes MANAGÉS sont remplacés.
    user_group = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "my-custom-lint.sh"}],
    }
    (tmp_path / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [user_group]}}), encoding="utf-8"
    )
    setup._install_harness_hooks(tmp_path)
    setup._install_harness_hooks(
        tmp_path
    )  # idempotent — les groupes managés ne se dupliquent pas
    pre = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"][
        "PreToolUse"
    ]
    commands = [g["hooks"][0]["command"] for g in pre]
    assert "my-custom-lint.sh" in commands
    assert sum("guard.py" in c for c in commands) == 1
    assert sum("check_privacy_egress" in c for c in commands) == 1


def test_harness_hooks_preserve_user_stop_groups(tmp_path):
    user_group = {"hooks": [{"type": "command", "command": "notify-me.sh"}]}
    (tmp_path / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [user_group]}}), encoding="utf-8"
    )
    setup._install_harness_hooks(tmp_path)
    setup._install_harness_hooks(tmp_path)
    stop = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))[
        "hooks"
    ]["Stop"]
    commands = [g["hooks"][0]["command"] for g in stop]
    assert "notify-me.sh" in commands
    assert sum("stop_handoff.py" in c for c in commands) == 1


def test_harness_hooks_preserve_permissions_and_are_idempotent(tmp_path):
    profile = {"name": "poc", "permissions_deny": ["Bash(ssh *)"]}
    setup._write_settings_json(profile, tmp_path)
    setup._install_harness_hooks(tmp_path)
    setup._install_harness_hooks(tmp_path)  # second run must not duplicate
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["permissions"]["deny"] == ["Bash(ssh *)"]
    assert len(data["hooks"]["Stop"]) == 1


# ── distribution guards (setup.py misc — loups mineurs audit 2026-07-04) ─────


def test_public_scan_covers_all_shipped_core_subdirs():
    # Angle mort relevé par l'audit : status-lines / pre-commit / conventions shippent
    # dans le moteur public et doivent être leak-scannés comme rules/commands/agents.
    assert {
        "rules",
        "commands",
        "agents",
        "skills",
        "status-lines",
        "hooks",
        "pre-commit",
        "conventions",
    } <= set(setup.PUBLIC_SCAN_SUBDIRS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
