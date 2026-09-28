"""`setup/plugin_curated.py` — the curated plugin list, its default/user overlay,
and the individual-plugin expansion of a whole-marketplace entry."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

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
    """An entry names either a whole marketplace or one `plugin@marketplace` — the
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


# ── expand_entry — a whole marketplace flattens to the plugins it publishes ──


def test_expand_entry_returns_the_named_plugin_as_is():
    entry = CuratedEntry("mp", "owner/repo", plugin="pc-snow")

    assert plugin_curated.expand_entry(entry) == ["pc-snow@mp"]


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

    assert plugin_curated.expand_entry(entry) == ["pc-a@mp", "pc-b@mp"]


def test_expand_entry_is_empty_for_a_marketplace_this_machine_never_registered(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")

    entry = CuratedEntry("never-added", "owner/repo")

    assert plugin_curated.expand_entry(entry) == []


def test_is_registered_true_only_for_a_known_marketplace(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": "/wherever"}}), encoding="utf-8"
    )

    assert plugin_curated.is_registered(CuratedEntry("mp", "owner/repo")) is True
    assert plugin_curated.is_registered(CuratedEntry("never-added", "o/r")) is False


# ── resolve_source / add_marketplace ───────────────────────────────────────


def test_resolve_source_leaves_a_github_spec_unchanged(tmp_path):
    assert (
        plugin_curated.resolve_source("anthropics/claude-plugins-official", tmp_path)
        == "anthropics/claude-plugins-official"
    )


def test_resolve_source_resolves_a_real_relative_directory_against_the_workspace(
    tmp_path,
):
    (tmp_path / "bootstrap" / "some-plugin-repo").mkdir(parents=True)

    resolved = plugin_curated.resolve_source("bootstrap/some-plugin-repo", tmp_path)

    assert resolved == str(tmp_path / "bootstrap" / "some-plugin-repo")


def test_add_marketplace_runs_claude_plugin_marketplace_add(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        plugin_curated.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
    )

    plugin_curated.add_marketplace(CuratedEntry("mp", "owner/repo"), tmp_path)

    assert calls == [["claude", "plugin", "marketplace", "add", "owner/repo"]]


# ── sync_user_file ─────────────────────────────────────────────────────────


def test_sync_user_file_appends_a_new_entry_on_yes(tmp_path, monkeypatch):
    user_file = tmp_path / "curated.toml"
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file
    )

    assert written is True
    assert tomllib.loads(user_file.read_text()) == {
        "entries": [{"marketplace": "mp", "source": "owner/repo"}]
    }


def test_sync_user_file_writes_nothing_on_no(tmp_path, monkeypatch, capsys):
    """Whole-output oracle, color off — plan, then the declined outcome's own word
    (the input() prompt itself never prints under a canned input)."""
    user_file = tmp_path / "curated.toml"
    monkeypatch.setattr("builtins.input", lambda *_: "n")

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file
    )

    assert written is False
    assert not user_file.exists()
    assert capsys.readouterr().out == (
        f"New marketplace(s) to remember in {user_file}:\n"
        "  + mp (owner/repo)\n"
        "cancelled.\n"
    )


def test_sync_user_file_skips_the_prompt_under_yes(tmp_path, monkeypatch):
    user_file = tmp_path / "curated.toml"
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("must not ask under yes=True")
    )

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file, yes=True
    )

    assert written is True


def test_sync_user_file_is_a_noop_when_nothing_new(tmp_path):
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[entries]]\nmarketplace = "mp"\nsource = "owner/repo"\n', encoding="utf-8"
    )

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file
    )

    assert written is False


def test_sync_user_file_preserves_an_existing_remove_block(tmp_path, monkeypatch):
    user_file = tmp_path / "curated.toml"
    user_file.write_text(
        '[[remove]]\nmarketplace = "claude-code-lsps"\n', encoding="utf-8"
    )
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    written = plugin_curated.sync_user_file(
        [CuratedEntry("fresh", "owner/fresh-plugins")], user_path=user_file
    )

    assert written is True
    assert tomllib.loads(user_file.read_text()) == {
        "entries": [{"marketplace": "fresh", "source": "owner/fresh-plugins"}],
        "remove": [{"marketplace": "claude-code-lsps"}],
    }


def test_sync_user_file_stdout_is_the_exact_plan_confirm_report(
    tmp_path, monkeypatch, capsys
):
    """Whole-string oracle, color off — plan, `[y/N]`, report in the plan's own words."""
    user_file = tmp_path / "curated.toml"
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file
    )

    assert written is True
    # the input() prompt itself never prints under a canned input — stdout is the plan
    # plus the report
    assert capsys.readouterr().out == (
        f"New marketplace(s) to remember in {user_file}:\n"
        "  + mp (owner/repo)\n"
        f"✓ saved → {user_file}\n"
    )


def test_sync_user_file_refuses_to_overwrite_a_broken_file(
    tmp_path, monkeypatch, capsys
):
    user_file = tmp_path / "curated.toml"
    original = "this is not [ valid toml"
    user_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("must not even ask to overwrite")
    )

    written = plugin_curated.sync_user_file(
        [CuratedEntry("mp", "owner/repo")], user_path=user_file
    )

    assert written is False
    assert user_file.read_text() == original
    assert "not valid TOML" in capsys.readouterr().err


# ── render_curated_toml — the exact text it writes back ───────────────────────────


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


# ── resolve_no_name_selection — the whole "no name" flow ──────


@pytest.fixture
def curated_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    default_file = tmp_path / "default.toml"
    monkeypatch.setattr(plugin_curated, "DEFAULT_CURATED_PATH", default_file)
    return tmp_path, home


def _canned(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _keep_as_shown(items, title, **kwargs):
    """A fake `picker` (see `plugin_enable.Picker`) standing in for the interactive checkbox screen: confirms
    every row exactly as prefilled, no toggle — the "keep as shown, press enter" case every
    `resolve_no_name_selection` test below exercises."""
    return [item.checked for item in items]


def test_resolve_no_name_selection_expands_an_already_registered_marketplace(
    curated_env, monkeypatch
):
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "mp"\nsource = "owner/repo"\n', encoding="utf-8"
    )
    marketplace_dir = tmp_path / "checkout"
    (marketplace_dir / ".claude-plugin").mkdir(parents=True)
    (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "pc-a"}]}), encoding="utf-8"
    )
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": str(marketplace_dir)}}), encoding="utf-8"
    )
    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=[],
        user_path=tmp_path / "absent-user.toml",
        picker=_keep_as_shown,
    )

    assert names == ["pc-a@mp"]


def test_resolve_no_name_selection_adds_expands_and_offers_to_remember_an_unregistered_entry(
    curated_env, monkeypatch
):
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\n',
        encoding="utf-8",
    )
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        marketplace_dir = tmp_path / "checkout"
        (marketplace_dir / ".claude-plugin").mkdir(parents=True)
        (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"plugins": [{"name": "pc-fresh"}]}), encoding="utf-8"
        )
        (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
            json.dumps({"fresh": {"installLocation": str(marketplace_dir)}}),
            encoding="utf-8",
        )
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(plugin_curated.subprocess, "run", fake_run)
    user_file = tmp_path / "user.toml"
    # picker: keep the one (checked) row; confirm the marketplace add; confirm saving
    # it to the user file.
    _canned(monkeypatch, ["y", "y"])

    names = plugin_curated.resolve_no_name_selection(
        tmp_path, installed_names=[], user_path=user_file, picker=_keep_as_shown
    )

    assert names == ["pc-fresh@fresh"]
    assert calls == [["claude", "plugin", "marketplace", "add", "owner/fresh-plugins"]]
    assert tomllib.loads(user_file.read_text()) == {
        "entries": [{"marketplace": "fresh", "source": "owner/fresh-plugins"}]
    }


def test_resolve_no_name_selection_declining_the_add_drops_that_entry(
    curated_env, monkeypatch
):
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_curated.subprocess,
        "run",
        lambda *a, **k: pytest.fail("must not add a declined marketplace"),
    )
    _canned(monkeypatch, ["n"])  # decline the add

    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=[],
        user_path=tmp_path / "absent-user.toml",
        picker=_keep_as_shown,
    )

    assert names == []


def test_resolve_no_name_selection_treats_a_plugin_keyed_entry_as_unregistered_too(
    curated_env, monkeypatch
):
    """A `plugin=`-keyed entry is just as unregistered as a whole-marketplace one when its
    marketplace was never `claude plugin marketplace add`ed — it must go through the same
    add-then-expand flow, never straight into the picker as an installable name (advisor review:
    the original `entry.plugin is not None or is_registered(entry)` short-circuited past the
    registration check for this exact case)."""
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\nplugin = "pc-x"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_curated.subprocess,
        "run",
        lambda *a, **k: pytest.fail("must not add a declined marketplace"),
    )
    _canned(monkeypatch, ["n"])  # decline the add

    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=[],
        user_path=tmp_path / "absent-user.toml",
        picker=_keep_as_shown,
    )

    assert names == []


def test_resolve_no_name_selection_groups_two_entries_under_one_unregistered_marketplace(
    curated_env, monkeypatch
):
    """Two entries sharing one not-yet-registered marketplace (a `plugin=`-keyed one and a
    whole-marketplace one) must `marketplace add` it exactly once, not once per entry."""
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\nplugin = "pc-x"\n\n'
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\n',
        encoding="utf-8",
    )
    add_calls = []

    def fake_run(cmd, **kw):
        add_calls.append(cmd)
        (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
            json.dumps({"fresh": {"installLocation": str(tmp_path / "checkout")}}),
            encoding="utf-8",
        )
        (tmp_path / "checkout" / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (tmp_path / "checkout" / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"plugins": [{"name": "pc-y"}]}), encoding="utf-8"
        )
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(plugin_curated.subprocess, "run", fake_run)
    _canned(monkeypatch, ["y", "n"])  # confirm add; decline saving

    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=[],
        user_path=tmp_path / "absent-user.toml",
        picker=_keep_as_shown,
    )

    assert len(add_calls) == 1
    assert set(names) == {"pc-x@fresh", "pc-y@fresh"}


def test_resolve_no_name_selection_under_dry_run_adds_and_writes_nothing(
    curated_env, monkeypatch
):
    """`--dry-run` on the no-name path must not `marketplace add` or write the user
    file, even with the unregistered row checked and `--yes`."""
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_curated.subprocess,
        "run",
        lambda *a, **k: pytest.fail("must not add anything under dry_run"),
    )
    user_file = tmp_path / "user.toml"

    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=[],
        user_path=user_file,
        yes=True,
        dry_run=True,
        picker=_keep_as_shown,
    )

    assert names == []
    assert not user_file.exists()


def test_resolve_no_name_selection_excludes_an_already_installed_plugin(
    curated_env, monkeypatch
):
    """The table covers what was *newly* selected — an already-installed plugin left
    checked has nothing to place, so it is not returned here (`install <name>` named directly
    still opens its own table)."""
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "mp"\nsource = "owner/repo"\nplugin = "pc-a"\n\n'
        '[[entries]]\nmarketplace = "mp"\nsource = "owner/repo"\nplugin = "pc-b"\n',
        encoding="utf-8",
    )
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": "/wherever"}}), encoding="utf-8"
    )
    names = plugin_curated.resolve_no_name_selection(
        tmp_path,
        installed_names=["pc-a"],
        user_path=tmp_path / "absent-user.toml",
        picker=_keep_as_shown,
    )

    assert names == []


def test_resolve_no_name_selection_survives_a_failed_marketplace_add(
    curated_env, monkeypatch, capsys
):
    tmp_path, home = curated_env
    plugin_curated.DEFAULT_CURATED_PATH.write_text(
        '[[entries]]\nmarketplace = "fresh"\nsource = "owner/fresh-plugins"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_curated.subprocess,
        "run",
        lambda cmd, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, cmd)),
    )
    user_file = tmp_path / "user.toml"
    _canned(monkeypatch, ["y"])  # confirm the add

    names = plugin_curated.resolve_no_name_selection(
        tmp_path, installed_names=[], user_path=user_file, picker=_keep_as_shown
    )

    assert names == []
    assert not user_file.exists()
    assert "failed to add marketplace fresh" in capsys.readouterr().err
