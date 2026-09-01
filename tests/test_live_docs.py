"""`setup/live_docs.py` — the `pinky install --live-docs` asset.

Boundary fakes only: `launchctl` and the `mkdocs serve` runner (external processes). Copy, symlink
generation, plist rendering and the ledger stay real. `render_plist` is pinned by a whole-string
oracle (`tests.md` — a `render_*` generator).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli_pinky, doctor, live_docs, state_file


@pytest.fixture
def src(tmp_path):
    """A fake bundled `live-docs/` source — the three tooling files with recognisable bytes."""
    root = tmp_path / "src"
    (root / "stylesheets").mkdir(parents=True)
    (root / "hooks.py").write_text("# hooks\n", encoding="utf-8")
    (root / "mkdocs.yml").write_text("site_name: X\n", encoding="utf-8")
    (root / "stylesheets" / "board.css").write_text(".x{}\n", encoding="utf-8")
    return root


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "ledger.json")


def _workspace(tmp_path, *, with_file=True, folders=("",), dirs=()):
    """A workspace root with an optional `.code-workspace` and the given `_KANBAN`/`_AGENT_LOG`."""
    root = tmp_path / "ws"
    root.mkdir()
    if with_file:
        entries = ", ".join(f'{{ "path": "{p or "."}" }}' for p in folders)
        (root / "pinky.code-workspace").write_text(
            '// a jsonc comment\n{\n  /* block */ "folders": [' + entries + "]\n}\n",
            encoding="utf-8",
        )
    for d in dirs:
        (root / d).mkdir(parents=True)
    return root


# ── discover_board_mounts ───────────────────────────────────────────────────────────────────


def test_discover_board_mounts_names_and_sorts(tmp_path):
    root = _workspace(
        tmp_path, folders=("", "sub"), dirs=("_KANBAN", "_AGENT_LOG", "sub/_KANBAN")
    )
    mounts = live_docs.discover_board_mounts(root)

    names = [m.name for m in mounts]
    assert names == sorted(names)
    assert f"{root.name}-kanban" in names
    assert f"{root.name}-log" in names
    assert "sub-kanban" in names
    assert "sub-log" not in names  # sub/_AGENT_LOG does not exist
    assert {m.source for m in mounts} == {
        (root / "_KANBAN").resolve(),
        (root / "_AGENT_LOG").resolve(),
        (root / "sub" / "_KANBAN").resolve(),
    }


def test_discover_board_mounts_without_workspace_file(tmp_path):
    root = _workspace(tmp_path, with_file=False, dirs=("_KANBAN",))
    (mount,) = live_docs.discover_board_mounts(root)
    assert mount.name == f"{root.name}-kanban"


def test_discover_board_mounts_tolerates_a_broken_workspace_file(tmp_path):
    root = _workspace(tmp_path, dirs=("_KANBAN",))
    (root / "pinky.code-workspace").write_text("{ not json", encoding="utf-8")
    (mount,) = live_docs.discover_board_mounts(root)
    assert mount.name == f"{root.name}-kanban"


def test_discover_board_mounts_keeps_a_double_slash_inside_a_string(tmp_path):
    """A `//` in a quoted path or URL is not a comment — the naive line-strip broke on the
    real workspace file's Proton path and settings-block URLs."""
    root = tmp_path / "ws"
    root.mkdir()
    external = tmp_path / "proton-like"
    (external / "_KANBAN").mkdir(parents=True)
    (root / "pinky.code-workspace").write_text(
        '{\n  // header comment\n  "settings": { "x": "https://example.com" },\n'
        f'  "folders": [ {{ "path": "{external.as_posix()}" }} ]\n}}\n',
        encoding="utf-8",
    )
    (mount,) = live_docs.discover_board_mounts(root)
    assert mount.name == "proton-like-kanban"


# ── _copy_tooling / _write_mounts ───────────────────────────────────────────────────────────


def test_copy_tooling_lands_at_runtime_layout(src, tmp_path):
    install = tmp_path / "install"
    live_docs._copy_tooling(src, install)

    assert (install / "hooks.py").read_text(encoding="utf-8") == "# hooks\n"
    assert (install / "mkdocs.yml").read_text(encoding="utf-8") == "site_name: X\n"
    assert (install / "docs" / "stylesheets" / "board.css").read_text(
        encoding="utf-8"
    ) == ".x{}\n"


def test_write_mounts_creates_replaces_and_prunes(tmp_path):
    install = tmp_path / "install"
    (install / "docs" / "stylesheets").mkdir(parents=True)
    board_a = tmp_path / "a"
    board_b = tmp_path / "b"
    board_a.mkdir()
    board_b.mkdir()
    stale = install / "docs" / "old-kanban"
    stale.symlink_to(board_a)

    links = live_docs._write_mounts(
        install,
        [
            live_docs.BoardMount("a-kanban", board_a),
            live_docs.BoardMount("b-kanban", board_b),
        ],
    )

    assert {p.name for p in links} == {"a-kanban", "b-kanban"}
    assert (install / "docs" / "a-kanban").resolve() == board_a.resolve()
    assert not stale.exists()  # pruned
    assert (install / "docs" / "stylesheets").is_dir()  # real dir left alone


# ── render_plist — oracle ───────────────────────────────────────────────────────────────────


def test_render_plist_full_string_oracle(tmp_path):
    install = tmp_path / "install"
    got = live_docs.render_plist(install, uv="/opt/homebrew/bin/uv")

    # plistlib output: keys sorted, tab-indented, `<` in the version pins escaped to `&lt;`
    # (`<10</string>` unescaped is a fatal XML error — `launchctl bootstrap` would reject it).
    assert got == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "\t<key>EnvironmentVariables</key>\n"
        "\t<dict>\n"
        "\t\t<key>NO_MKDOCS_2_WARNING</key>\n"
        "\t\t<string>1</string>\n"
        "\t</dict>\n"
        "\t<key>KeepAlive</key>\n"
        "\t<true/>\n"
        "\t<key>Label</key>\n"
        "\t<string>com.pinky.live-docs</string>\n"
        "\t<key>ProgramArguments</key>\n"
        "\t<array>\n"
        "\t\t<string>/opt/homebrew/bin/uv</string>\n"
        "\t\t<string>tool</string>\n"
        "\t\t<string>run</string>\n"
        "\t\t<string>--with</string>\n"
        "\t\t<string>mkdocs-material&gt;=9.7,&lt;10</string>\n"
        "\t\t<string>--with</string>\n"
        "\t\t<string>mkdocs-awesome-nav&gt;=3.3,&lt;4</string>\n"
        "\t\t<string>mkdocs</string>\n"
        "\t\t<string>serve</string>\n"
        "\t\t<string>-f</string>\n"
        f"\t\t<string>{install / 'mkdocs.yml'}</string>\n"
        "\t\t<string>-a</string>\n"
        "\t\t<string>127.0.0.1:8765</string>\n"
        "\t</array>\n"
        "\t<key>RunAtLoad</key>\n"
        "\t<true/>\n"
        "\t<key>StandardErrorPath</key>\n"
        f"\t<string>{install / '.cache' / 'live-docs.err.log'}</string>\n"
        "\t<key>StandardOutPath</key>\n"
        f"\t<string>{install / '.cache' / 'live-docs.log'}</string>\n"
        "\t<key>WorkingDirectory</key>\n"
        f"\t<string>{install}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


# ── install ─────────────────────────────────────────────────────────────────────────────────


def test_install_off_macos_installs_tooling_without_a_service(src, tmp_path, ledger):
    ws = _workspace(tmp_path, with_file=False, dirs=("_KANBAN",))
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"

    result = live_docs.install(
        workspace_root=ws,
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=False,
    )

    assert result.service == "skipped (not macOS)"
    assert result.mounts == [f"{ws.name}-kanban"]
    assert (install / "hooks.py").is_file()
    assert (install / "docs" / f"{ws.name}-kanban").is_symlink()
    assert not plist.exists()
    assert live_docs._LEDGER_TOOLING in state_file._load_entries()
    assert live_docs._LEDGER_PLIST not in state_file._load_entries()


def _rc(code):
    """A fake `launchctl` returning `code` — `install` gates on `.returncode`."""
    return lambda *a: type("R", (), {"returncode": code})()


def test_install_on_macos_writes_plist_and_loads_the_agent(src, tmp_path, ledger):
    ws = _workspace(tmp_path, with_file=False, dirs=("_KANBAN",))
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"
    calls = []

    def _launchctl(*a):
        calls.append(a)
        return type("R", (), {"returncode": 1 if a[0] == "print" else 0})()

    result = live_docs.install(
        workspace_root=ws,
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=True,
        launchctl=_launchctl,
    )

    assert result.service == "loaded"
    assert plist.read_text(encoding="utf-8").startswith("<?xml")
    assert str(install) in plist.read_text(encoding="utf-8")
    assert any(a[0] == "bootstrap" for a in calls)
    assert live_docs._LEDGER_PLIST in state_file._load_entries()


def test_install_reports_a_failed_bootstrap_instead_of_claiming_loaded(
    src, tmp_path, ledger
):
    ws = _workspace(tmp_path, with_file=False, dirs=("_KANBAN",))
    result = live_docs.install(
        workspace_root=ws,
        src=src,
        install_dir=tmp_path / "install",
        plist_path=tmp_path / "agent.plist",
        is_macos=True,
        launchctl=_rc(113),
    )
    assert result.service == "bootstrap failed (rc=113)"


def test_install_refuses_a_plist_it_does_not_own(src, tmp_path, ledger):
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"
    plist.write_text("<plist>hand-rolled _LIVE_DOCS service</plist>", encoding="utf-8")

    with pytest.raises(live_docs.LiveDocsConflict):
        live_docs.install(
            workspace_root=_workspace(tmp_path, with_file=False, dirs=("_KANBAN",)),
            src=src,
            install_dir=install,
            plist_path=plist,
            is_macos=True,
            launchctl=_rc(0),
        )
    assert "hand-rolled" in plist.read_text(encoding="utf-8")  # left intact


def test_install_force_replaces_a_foreign_plist(src, tmp_path, ledger):
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"
    plist.write_text("<plist>someone else</plist>", encoding="utf-8")

    result = live_docs.install(
        workspace_root=_workspace(tmp_path, with_file=False, dirs=("_KANBAN",)),
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=True,
        force=True,
        launchctl=_rc(0),
    )
    assert result.service == "loaded"
    assert plist.read_text(encoding="utf-8").startswith("<?xml")


# ── status / uninstall ──────────────────────────────────────────────────────────────────────


def test_status_absent_then_mine_then_not_mine(src, tmp_path, ledger):
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"

    assert (
        live_docs.status(install_dir=install, plist_path=plist)
        == state_file.EntryStatus.ABSENT
    )

    live_docs.install(
        workspace_root=_workspace(tmp_path, with_file=False, dirs=("_KANBAN",)),
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=True,
        launchctl=lambda *a: type("R", (), {"returncode": 1})(),
    )
    assert (
        live_docs.status(install_dir=install, plist_path=plist)
        == state_file.EntryStatus.POSED_BY_ME
    )

    plist.write_text("<plist>points somewhere else</plist>", encoding="utf-8")
    assert (
        live_docs.status(install_dir=install, plist_path=plist)
        == state_file.EntryStatus.PRESENT_NOT_MINE
    )


def test_status_off_macos_reflects_the_tooling_ledger_without_a_plist(
    src, tmp_path, ledger
):
    """Off macOS `install` writes no plist — `status` must still report the install as ours,
    via the tooling ledger entry (recorded on every platform)."""
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"

    assert (
        live_docs.status(install_dir=install, plist_path=plist)
        == state_file.EntryStatus.ABSENT
    )
    live_docs.install(
        workspace_root=_workspace(tmp_path, with_file=False, dirs=("_KANBAN",)),
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=False,
    )
    assert not plist.exists()
    assert (
        live_docs.status(install_dir=install, plist_path=plist)
        == state_file.EntryStatus.POSED_BY_ME
    )


def test_uninstall_removes_only_what_was_posed(src, tmp_path, ledger):
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"
    calls = []
    live_docs.install(
        workspace_root=_workspace(tmp_path, with_file=False, dirs=("_KANBAN",)),
        src=src,
        install_dir=install,
        plist_path=plist,
        is_macos=True,
        launchctl=lambda *a: type("R", (), {"returncode": 1})(),
    )

    removed = live_docs.uninstall(
        install_dir=install, plist_path=plist, launchctl=lambda *a: calls.append(a)
    )

    assert str(plist) in removed
    assert str(install) in removed
    assert not plist.exists()
    assert not install.exists()
    assert any(a[0] == "bootout" for a in calls)


def test_uninstall_leaves_a_plist_it_did_not_pose(tmp_path, ledger):
    install = tmp_path / "install"
    plist = tmp_path / "agent.plist"
    plist.write_text("<plist>someone else's</plist>", encoding="utf-8")

    removed = live_docs.uninstall(
        install_dir=install, plist_path=plist, launchctl=lambda *a: None
    )

    assert removed == []
    assert plist.exists()


# ── serve ───────────────────────────────────────────────────────────────────────────────────


def test_serve_refreshes_mounts_then_runs_mkdocs(src, tmp_path, capsys):
    ws = _workspace(tmp_path, with_file=False, dirs=("_KANBAN",))
    install = tmp_path / "install"
    cmds = []

    live_docs.serve(workspace_root=ws, src=src, install_dir=install, runner=cmds.append)

    assert (install / "docs" / f"{ws.name}-kanban").is_symlink()
    (cmd,) = cmds
    assert cmd[1:] == [
        "tool",
        "run",
        "--with",
        "mkdocs-material>=9.7,<10",
        "--with",
        "mkdocs-awesome-nav>=3.3,<4",
        "mkdocs",
        "serve",
        "-f",
        str(install / "mkdocs.yml"),
        "-a",
        "127.0.0.1:8765",
    ]


# ── public-repo guard — the bundled source is tooling only ───────────────────────────────────


def test_bundled_source_carries_only_tooling():
    """The checklist item is "trackable par git" — so ask git, not the filesystem. A `p.is_file()`
    walk misses a directory symlink (`live-docs/docs/pinky-kanban -> …/_KANBAN`), the exact shape
    that would leak a board once the repo is public."""
    import subprocess

    src = live_docs.LIVE_DOCS_SRC
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(src),
            "ls-files",
            "--full-name",
            "--cached",
            "--others",
            "--exclude-standard",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    tracked = {Path(p).relative_to("live-docs").as_posix() for p in listed}
    allowed = {"hooks.py", "mkdocs.yml", "stylesheets/board.css"}
    assert tracked <= allowed, (
        f"live-docs/ must ship tooling only — a board/log/site file here leaks once the repo is "
        f"public. Unexpected: {tracked - allowed}"
    )


# ── cli_pinky wiring ────────────────────────────────────────────────────────────────────────


def test_pinky_install_live_docs_delegates(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_pinky, "setup_main", lambda argv: calls.append(argv))
    monkeypatch.setattr(doctor, "run_doctor", lambda **k: 0)  # advisory preflight

    cli_pinky.main(["install", "--live-docs"])

    assert ["--live-docs"] in calls


def test_pinky_install_live_docs_force_delegates(monkeypatch):
    """The conflict message tells the user to re-run with --force — the wiring is user-facing."""
    calls = []
    monkeypatch.setattr(cli_pinky, "setup_main", lambda argv: calls.append(argv))
    monkeypatch.setattr(doctor, "run_doctor", lambda **k: 0)

    cli_pinky.main(["install", "--live-docs", "--force"])

    assert ["--live-docs", "--force"] in calls


@pytest.mark.parametrize("action", ["serve", "status", "uninstall"])
def test_pinky_docs_subcommands_delegate(monkeypatch, action):
    calls = []
    monkeypatch.setattr(cli_pinky, "setup_main", lambda argv: calls.append(argv))

    cli_pinky.main(["docs", action])

    assert calls == [[f"--live-docs-{action}"]]


def test_pinky_docs_is_in_help(capsys):
    with pytest.raises(SystemExit):
        cli_pinky.main(["--help"])
    assert "docs" in capsys.readouterr().out
