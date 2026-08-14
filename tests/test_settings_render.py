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


# ── _install_status_lines — scripts copy + settings.json wiring ──────────────


def test_status_lines_are_copied_and_wired(tmp_path):
    """Les deux scripts atterrissent dans scripts/ et chaque clé pointe le bon fichier."""
    setup._install_status_lines(tmp_path)
    for name in ("statusline.py", "subagent_statusline.py"):
        assert (tmp_path / "scripts" / name).is_file()
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["statusLine"]["type"] == "command"
    assert data["statusLine"]["command"].endswith('scripts/statusline.py"')
    assert data["subagentStatusLine"]["command"].endswith('scripts/subagent_statusline.py"')


def test_status_line_command_carries_an_absolute_path(tmp_path):
    """Un chemin relatif se résout contre le cwd de la session, pas contre scripts/ — la status
    line ne rend alors rien, sans erreur nulle part. Incident réel du 2026-08-14."""
    setup._install_status_lines(tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    quoted = data["statusLine"]["command"].split('"')[1]
    assert Path(quoted).is_absolute()
    assert Path(quoted).is_file()


def test_status_lines_register_no_lifecycle_hook(tmp_path):
    """Stop/PreToolUse/PostToolUse appartiennent aux plugins depuis la migration — cette fonction
    ne doit plus en écrire aucun, sinon deux canaux enregistrent le même hook."""
    setup._install_status_lines(tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "hooks" not in data


def test_status_lines_use_windows_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.profile.platform, "system", lambda: "Windows")
    setup._install_status_lines(tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["statusLine"]["command"].startswith("py -3 ")


def test_status_lines_use_python3_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.profile.platform, "system", lambda: "Darwin")
    setup._install_status_lines(tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["statusLine"]["command"].startswith("python3 ")


def test_status_lines_target_os_overrides_host(tmp_path, monkeypatch):
    """--into rend pour la machine CIBLE : l'OS de l'auteur ne doit pas fuiter dans le launcher."""
    monkeypatch.setattr(setup.profile.platform, "system", lambda: "Darwin")
    setup._install_status_lines(tmp_path, target_os="Windows")
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["statusLine"]["command"].startswith("py -3 ")


def test_status_lines_preserve_other_keys_and_are_idempotent(tmp_path):
    """Tout ce qui n'est pas une status line survit, et deux passages donnent le même fichier."""
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"]}, "outputStyle": "ADHD"}),
        encoding="utf-8",
    )
    setup._install_status_lines(tmp_path)
    first = (tmp_path / "settings.json").read_text(encoding="utf-8")
    data = json.loads(first)
    assert data["permissions"]["allow"] == ["Bash(git status:*)"]
    assert data["outputStyle"] == "ADHD"
    setup._install_status_lines(tmp_path)
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == first


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
