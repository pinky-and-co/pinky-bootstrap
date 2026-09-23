"""`setup/plugin_curated.py` — the curated plugin list, its default/user overlay (FR-0024-38 to
43), and the individual-plugin expansion of a whole-marketplace entry (FR-0024-36)."""

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_curated
from setup.plugin_curated import CuratedEntry


def test_default_curated_list_loads_as_three_marketplace_entries():
    entries = plugin_curated.load_curated_entries(user_path=Path("/does/not/exist"))

    assert {e.marketplace for e in entries} == {
        "claude-plugins-official",
        "pinky-agentic-plugins",
        "claude-code-lsps",
    }
    assert all(e.plugin is None for e in entries)


def test_user_file_adds_an_entry(tmp_path):
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[entries]]\nmarketplace = "acme"\nsource = "acme/acme-plugins"\n',
        encoding="utf-8",
    )

    entries = plugin_curated.load_curated_entries(user_path=user_file)

    assert any(e.marketplace == "acme" for e in entries)
    assert len(entries) == 4


def test_user_file_replaces_a_default_entry_with_the_same_marketplace(tmp_path):
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[entries]]\nmarketplace = "pinky-agentic-plugins"\n'
        'source = "/local/dev/pinky-agentic-plugins"\n',
        encoding="utf-8",
    )

    entries = plugin_curated.load_curated_entries(user_path=user_file)

    matching = [e for e in entries if e.marketplace == "pinky-agentic-plugins"]
    assert matching == [
        CuratedEntry("pinky-agentic-plugins", "/local/dev/pinky-agentic-plugins")
    ]


def test_user_file_removes_a_default_entry(tmp_path):
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[remove]]\nmarketplace = "claude-code-lsps"\n', encoding="utf-8"
    )

    entries = plugin_curated.load_curated_entries(user_path=user_file)

    assert "claude-code-lsps" not in {e.marketplace for e in entries}
    assert len(entries) == 2


def test_a_missing_user_file_is_not_an_error(tmp_path):
    entries = plugin_curated.load_curated_entries(user_path=tmp_path / "absent.toml")

    assert len(entries) == 3


def test_a_specific_plugin_entry_and_a_whole_marketplace_entry_coexist(tmp_path):
    """FR-0024-38: an entry names either a whole marketplace or one `plugin@marketplace` — the
    two share a marketplace but are distinct rows, keyed on `(marketplace, plugin)`."""
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[entries]]\nmarketplace = "claude-plugins-official"\n'
        'source = "anthropics/claude-plugins-official"\nplugin = "some-plugin"\n',
        encoding="utf-8",
    )

    entries = plugin_curated.load_curated_entries(user_path=user_file)

    official = [e for e in entries if e.marketplace == "claude-plugins-official"]
    assert len(official) == 2
    assert {e.plugin for e in official} == {None, "some-plugin"}


# ── expand_entry — a whole marketplace flattens to the plugins it publishes (FR-0024-36) ──


def test_expand_entry_returns_the_named_plugin_as_is():
    entry = CuratedEntry("mp", "owner/repo", plugin="pc-snow")

    assert plugin_curated.expand_entry(entry) == ["pc-snow"]


def test_expand_entry_reads_the_local_catalog_of_a_known_marketplace(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")

    marketplace_dir = tmp_path / "mp-checkout"
    (marketplace_dir / ".claude-plugin").mkdir(parents=True)
    (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "pc-a"}, {"name": "pc-b"}]}), encoding="utf-8"
    )
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": str(marketplace_dir)}}), encoding="utf-8"
    )

    entry = CuratedEntry("mp", "owner/repo")

    assert plugin_curated.expand_entry(entry) == ["pc-a", "pc-b"]


def test_expand_entry_is_empty_for_a_marketplace_this_machine_never_registered(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")

    entry = CuratedEntry("never-added", "owner/repo")

    assert plugin_curated.expand_entry(entry) == []


# ── render_curated_toml — the exact text FR-0024-43 writes back ───────────────────────────


def test_render_curated_toml_round_trips_through_the_real_parser():
    entries = [
        CuratedEntry("mp1", "owner/repo1"),
        CuratedEntry("mp1", "owner/repo1", plugin="pc-x"),
    ]

    rendered = plugin_curated.render_curated_toml(entries)
    parsed = tomllib.loads(rendered)

    assert parsed == {
        "entries": [
            {"marketplace": "mp1", "source": "owner/repo1"},
            {"marketplace": "mp1", "source": "owner/repo1", "plugin": "pc-x"},
        ]
    }


def test_render_curated_toml_exact_text_for_one_entry():
    rendered = plugin_curated.render_curated_toml([CuratedEntry("mp", "owner/repo")])

    assert rendered == '[[entries]]\nmarketplace = "mp"\nsource = "owner/repo"\n'


def test_render_curated_toml_of_an_empty_list_is_an_empty_string():
    assert plugin_curated.render_curated_toml([]) == ""
