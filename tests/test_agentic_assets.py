"""`setup/agentic_assets.py` — install an output-style or theme onto this machine.

Both are plain files this repo already carries — discovery reads the real
`agentic-harness/output-styles/`/`themes/` trees (stable content, not a fixture); install targets
a monkeypatched `~/.claude/` so no test ever touches the real machine.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import agentic_assets
from setup.agentic_assets import (
    discover_output_styles,
    discover_themes,
    install_output_style,
    install_theme,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test writes under its own fake `~/.claude/` — never the real machine's."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setattr(
        agentic_assets, "_USER_SETTINGS_PATH", fake_home / ".claude" / "settings.json"
    )
    return fake_home


def test_discover_output_styles_finds_adhd_with_its_frontmatter_name_as_value():
    styles = discover_output_styles()
    adhd = next(a for a in styles if a.name == "adhd")
    assert adhd.value == "ADHD"
    assert adhd.description


def test_discover_themes_finds_lisible_with_custom_prefix_as_value():
    themes = discover_themes()
    lisible = next(a for a in themes if a.name == "lisible")
    assert lisible.value == "custom:lisible"
    assert lisible.description


def test_install_output_style_copies_file_and_sets_settings_key(isolated_home):
    target = install_output_style("adhd")

    assert target == isolated_home / ".claude" / "output-styles" / "adhd.md"
    assert target.is_file()
    data = json.loads(
        (isolated_home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert data["outputStyle"] == "ADHD"


def test_install_output_style_unknown_name_raises():
    with pytest.raises(ValueError, match="bidule"):
        install_output_style("bidule")


def test_install_output_style_merges_never_overwrites_existing_settings(isolated_home):
    settings_path = isolated_home / ".claude"
    settings_path.mkdir(parents=True)
    (settings_path / "settings.json").write_text(
        json.dumps({"someOtherKey": "keep-me"}), encoding="utf-8"
    )

    install_output_style("adhd")

    data = json.loads((settings_path / "settings.json").read_text(encoding="utf-8"))
    assert data["someOtherKey"] == "keep-me"
    assert data["outputStyle"] == "ADHD"


def test_install_theme_copies_file_and_sets_settings_key(isolated_home):
    target = install_theme("lisible")

    assert target == isolated_home / ".claude" / "themes" / "lisible.json"
    assert target.is_file()
    data = json.loads(
        (isolated_home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert data["theme"] == "custom:lisible"


def test_install_theme_unknown_name_raises():
    with pytest.raises(ValueError, match="bidule"):
        install_theme("bidule")


def test_install_output_style_records_in_state_file(isolated_home, monkeypatch):
    import setup.state_file as state_file_module

    monkeypatch.setattr(
        state_file_module, "STATE_FILE_PATH", isolated_home / "state.json"
    )

    install_output_style("adhd")

    raw = json.loads((isolated_home / "state.json").read_text(encoding="utf-8"))
    assert raw["outputStyle"]["value"] == "ADHD"
