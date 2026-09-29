"""`setup/doctor.py` — `pinky doctor`, the installed-plugin prerequisite check.

Boundary fakes only: `shutil.which` (PATH), `_read_ollama_tags` (network), `_keychain_has` /
`subprocess.run` (the `security` and `brew` CLIs). The parsing, resolution and report functions
stay real. `format_report` is pinned by a whole-string oracle (`tests.md` — it is a `*_report`
generator).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli_pinky, doctor, state_file

# ── helpers ─────────────────────────────────────────────────────────────────────────────────


def _plugin(root: Path, name: str, *, skills: dict[str, str]) -> Path:
    """A fake installed-plugin dir: `root/name/skills/<skill>/SKILL.md` with the given
    `allowed-tools` frontmatter value per skill."""
    plugin_dir = root / name
    for skill, allowed_tools in skills.items():
        skill_dir = plugin_dir / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill}\nallowed-tools: {allowed_tools}\n---\n# {skill}\n",
            encoding="utf-8",
        )
    return plugin_dir


def _lsp_plugin(root: Path, name: str, *, command: str) -> Path:
    """A fake installed-plugin dir shipping a `.lsp.json` — the `.lsp.json`-derived counterpart of
    `_plugin` (`allowed-tools`-derived)."""
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".lsp.json").write_text(
        json.dumps({"python": {"command": command, "args": ["--stdio"]}}),
        encoding="utf-8",
    )
    return plugin_dir


def _registry(path: Path, dirs: list[Path]) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    f"{d.name}@mkt": [
                        {"scope": "user", "installPath": str(d), "version": "0.1.0"}
                    ]
                    for d in dirs
                },
            }
        ),
        encoding="utf-8",
    )


def _settings_pinky(
    path: Path, *, pool: list[dict] | None = None, keys: list[dict] | None = None
) -> None:
    path.write_text(
        json.dumps({"model_pool": pool or [], "keys": keys or []}), encoding="utf-8"
    )


def test_parse_bash_binaries_covers_every_known_form_without_crashing():
    value = (
        "Bash(rg:*), Bash(command -v markitdown:*), Bash(command -v:*), Bash(gh run list:*), "
        "Bash(${CLAUDE_PLUGIN_ROOT}/hooks/x.sh:*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/y.py:*), "
        "Read, Edit, mcp__plugin_pc-core_pc-core-models__offline, Bash("
    )
    # `command` (builtin shell) ne fuit jamais, `Bash(command -v:*)` ne rend rien
    assert doctor.parse_bash_binaries(value) == {"rg", "markitdown", "gh", "python3"}


def test_parse_bash_binaries_empty_value_is_empty_set():
    assert doctor.parse_bash_binaries("") == set()


def test_required_binaries_lists_non_ambient_and_attributes_them(tmp_path):
    a = _plugin(
        tmp_path,
        "pc-alpha",
        skills={"one": "Bash(rg:*), Bash(command -v markitdown:*)"},
    )
    b = _plugin(tmp_path, "pc-beta", skills={"two": "Bash(git:*), Bash(rg:*)"})

    reqs = doctor.required_binaries([("pc-alpha", a), ("pc-beta", b)])

    assert reqs == {"markitdown": ["pc-alpha"], "rg": ["pc-alpha", "pc-beta"]}
    assert "git" not in reqs  # ambient, subtracted


def test_check_binaries_reports_present_and_absent(tmp_path, monkeypatch):
    plugin = _plugin(
        tmp_path, "pc-alpha", skills={"one": "Bash(present-bin:*), Bash(missing-bin:*)"}
    )
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: "/usr/bin/x" if name == "present-bin" else None,
    )

    checks = {c.name: c for c in doctor.check_binaries([("pc-alpha", plugin)])}

    assert checks["present-bin"].ok is True
    assert checks["missing-bin"].ok is False
    assert "brew install missing-bin" in checks["missing-bin"].detail


def test_check_binaries_maps_known_brew_formula(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, "pc-alpha", skills={"one": "Bash(rg:*)"})
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    (check,) = doctor.check_binaries([("pc-alpha", plugin)])

    assert check.name == "rg"
    assert "brew install ripgrep" in check.detail


def test_required_lsp_binaries_lists_the_command_and_attributes_it(tmp_path):
    a = _lsp_plugin(tmp_path, "pyright-fork", command="pyright-langserver")
    reqs = doctor.required_lsp_binaries([("pyright-fork", a)])
    assert reqs == {"pyright-langserver": ["pyright-fork"]}


def test_check_binaries_merges_allowed_tools_and_lsp_sources(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, "pc-alpha", skills={"one": "Bash(rg:*)"})
    lsp_plugin = _lsp_plugin(tmp_path, "pyright-fork", command="pyright-langserver")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    checks = {
        c.name: c
        for c in doctor.check_binaries(
            [("pc-alpha", plugin), ("pyright-fork", lsp_plugin)]
        )
    }

    assert set(checks) == {"rg", "pyright-langserver"}
    assert checks["pyright-langserver"].detail == (
        "npm install -g pyright (required by: pyright-fork)"
    )


def test_check_binaries_a_binary_required_by_both_sources_lists_both_plugins(
    tmp_path, monkeypatch
):
    allowed_tools_side = _plugin(
        tmp_path, "pc-alpha", skills={"one": "Bash(pyright-langserver:*)"}
    )
    lsp_side = _lsp_plugin(tmp_path, "pyright-fork", command="pyright-langserver")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/x")

    (check,) = doctor.check_binaries(
        [("pc-alpha", allowed_tools_side), ("pyright-fork", lsp_side)]
    )

    assert check.name == "pyright-langserver"
    assert "pc-alpha" in check.detail and "pyright-fork" in check.detail


def test_installed_plugins_names_from_key_skips_a_missing_path(tmp_path):
    present = _plugin(tmp_path, "pc-alpha", skills={"one": "Bash(rg:*)"})
    registry = tmp_path / "installed_plugins.json"
    _registry(registry, [present, tmp_path / "gone"])

    assert doctor.installed_plugins(registry) == [("pc-alpha", present)]


def test_check_binaries_empty_when_no_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "INSTALLED_PLUGINS_PATH", tmp_path / "nope.json")
    assert doctor.check_binaries() == []


def test_check_ollama_endpoint_unreachable(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings, pool=[{"name": "local-ollama", "kind": "offline", "model": None}]
    )

    checks = doctor.check_ollama(settings, tags_reader=lambda url: None)

    assert len(checks) == 1
    assert checks[0].name == "endpoint" and checks[0].ok is False


def test_check_ollama_model_absent_then_present(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings, pool=[{"name": "local-ollama", "kind": "offline", "model": None}]
    )

    absent = doctor.check_ollama(settings, tags_reader=lambda url: ["llama3:8b"])
    assert [c.ok for c in absent] == [True, False]
    assert absent[1].name == "gemma4:12b"
    assert absent[1].detail == "ollama pull gemma4:12b"

    present = doctor.check_ollama(settings, tags_reader=lambda url: ["gemma4:12b"])
    assert [c.ok for c in present] == [True, True]


def test_check_ollama_no_offline_entry_is_empty(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(settings, pool=[{"name": "mistral", "kind": "http"}])
    assert doctor.check_ollama(settings, tags_reader=lambda url: []) == []


def test_check_keys_absent_when_neither_env_nor_keychain(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings, keys=[{"env": "MISTRAL_API_KEY", "service": "MISTRAL_API_KEY"}]
    )

    (check,) = doctor.check_keys(settings, env={}, keychain=lambda service: False)

    assert check.name == "MISTRAL_API_KEY" and check.ok is False
    assert "MISTRAL_API_KEY" in check.detail


def test_check_keys_literal_is_present_from_its_own_value(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings,
        keys=[
            {"reader": "literal", "value": "41c2b051", "env": "CLOUDFLARE_ACCOUNT_ID"}
        ],
    )

    (check,) = doctor.check_keys(settings, env={}, keychain=lambda service: False)

    assert check.name == "CLOUDFLARE_ACCOUNT_ID"
    assert check.ok is True
    assert check.detail == ""


def test_check_keys_literal_without_value_is_absent(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings, keys=[{"reader": "literal", "env": "CLOUDFLARE_ACCOUNT_ID"}]
    )

    (check,) = doctor.check_keys(settings, env={}, keychain=lambda service: False)

    assert check.ok is False
    assert "literal" in check.detail


def test_check_keys_present_via_env_or_keychain(tmp_path):
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings,
        keys=[
            {"env": "A_KEY", "service": "svc-a"},
            {"env": "B_KEY", "service": "svc-b"},
        ],
    )

    checks = {
        c.name: c
        for c in doctor.check_keys(
            settings, env={"A_KEY": "x"}, keychain=lambda service: service == "svc-b"
        )
    }

    assert checks["A_KEY"].ok is True
    assert checks["B_KEY"].ok is True


def test_check_keys_empty_when_no_settings(tmp_path):
    assert doctor.check_keys(tmp_path / "absent.json") == []


# ── format_report — oracle ──────────────────────────────────────────────────────────────────

_MIXED = [
    doctor.Check("binary", "rg", True, "required by: pc-alpha"),
    doctor.Check(
        "binary", "yt-dlp", False, "brew install yt-dlp (required by: pc-kanban)"
    ),
    doctor.Check("ollama", "endpoint", True, "http://localhost:11434"),
    doctor.Check("ollama", "gemma4:12b", False, "ollama pull gemma4:12b"),
    doctor.Check("key", "MISTRAL_API_KEY", True, ""),
]


def test_format_report_is_empty_case():
    assert doctor.format_report([]) == (
        "pinky doctor — plugin prerequisites\n"
        "\n"
        "  (no plugin installed, or no prerequisite declared)"
    )


def test_format_report_puts_what_is_missing_first_and_sums_up_the_rest():
    """The reader's job is to see what to install: the missing ones come first, with their
    command, and everything that is fine collapses to one line."""
    assert doctor.format_report(_MIXED) == (
        "pinky doctor — plugin prerequisites\n"
        "\n"
        "✗ 2 prerequisites missing\n"
        "\n"
        "  ✗ yt-dlp — brew install yt-dlp (required by: pc-kanban)\n"
        "  ✗ gemma4:12b — ollama pull gemma4:12b\n"
        "\n"
        "✓ 3 present — `pinky doctor --verbose` lists them"
    )


def test_format_report_verbose_lists_the_present_ones_by_category_without_repeating_the_missing():
    """The missing ones are already at the top with their command: the category listing adds only
    what was collapsed into the "present" line."""
    assert doctor.format_report(_MIXED, verbose=True) == (
        "pinky doctor — plugin prerequisites\n"
        "\n"
        "✗ 2 prerequisites missing\n"
        "\n"
        "  ✗ yt-dlp — brew install yt-dlp (required by: pc-kanban)\n"
        "  ✗ gemma4:12b — ollama pull gemma4:12b\n"
        "\n"
        "✓ 3 present\n"
        "\n"
        "binaries\n"
        "  ✓ rg — required by: pc-alpha\n"
        "\n"
        "ollama\n"
        "  ✓ endpoint — http://localhost:11434\n"
        "\n"
        "API keys\n"
        "  ✓ MISTRAL_API_KEY"
    )


def test_format_report_all_present():
    ok = [doctor.Check("binary", "rg", True, "required by: x")]
    assert doctor.format_report(ok) == (
        "pinky doctor — plugin prerequisites\n"
        "\n"
        "✓ all 1 present — `pinky doctor --verbose` lists them"
    )


def test_format_report_singular_missing():
    one = [doctor.Check("binary", "rg", False, "brew install ripgrep")]
    assert doctor.format_report(one) == (
        "pinky doctor — plugin prerequisites\n"
        "\n"
        "✗ 1 prerequisite missing\n"
        "\n"
        "  ✗ rg — brew install ripgrep"
    )


def test_format_report_in_color_makes_the_missing_ones_stand_out():
    one = [
        doctor.Check("binary", "rg", False, "brew install ripgrep"),
        doctor.Check("binary", "jq", True, ""),
    ]

    report = doctor.format_report(one, color=True)

    assert "\x1b[1;31m✗ 1 prerequisite missing\x1b[0m" in report
    assert (
        "  \x1b[1;31m✗\x1b[0m \x1b[1mrg\x1b[0m — \x1b[2mbrew install ripgrep\x1b[0m"
        in report
    )
    assert "\x1b[32m✓\x1b[0m \x1b[2m1 present" in report


def test_format_report_without_color_has_no_escape_code():
    assert "\x1b" not in doctor.format_report(_MIXED, verbose=True)


def _full_setup(tmp_path, monkeypatch, *, which, tags, keychain):
    plugin = _plugin(tmp_path, "pc-alpha", skills={"one": "Bash(rg:*)"})
    registry = tmp_path / "installed_plugins.json"
    _registry(registry, [plugin])
    settings = tmp_path / "settings.pinky.json"
    _settings_pinky(
        settings,
        pool=[{"name": "local-ollama", "kind": "offline", "model": None}],
        keys=[{"env": "A_KEY", "service": "svc-a"}],
    )
    monkeypatch.setattr(doctor, "INSTALLED_PLUGINS_PATH", registry)
    monkeypatch.setattr(doctor, "SETTINGS_PINKY_PATH", settings)
    monkeypatch.setattr(doctor.shutil, "which", which)
    monkeypatch.setattr(doctor, "_read_ollama_tags", tags)
    monkeypatch.setattr(doctor, "_keychain_has", keychain)
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text('eval "$(pinky completion zsh)"\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "_ZSHRC", zshrc)


def test_run_doctor_returns_zero_when_all_present(tmp_path, monkeypatch, capsys):
    _full_setup(
        tmp_path,
        monkeypatch,
        which=lambda name: "/usr/bin/x",
        tags=lambda url: ["gemma4:12b"],
        keychain=lambda service: True,
    )
    assert doctor.run_doctor() == 0


def test_run_doctor_reports_exactly_the_missing_prerequisites(tmp_path, monkeypatch):
    _full_setup(
        tmp_path,
        monkeypatch,
        which=lambda name: None,  # rg absent
        tags=lambda url: [],  # modèle absent (endpoint ok)
        keychain=lambda service: False,  # clé absente
    )
    monkeypatch.delenv("A_KEY", raising=False)

    checks = doctor.collect_checks()
    missing = {(c.category, c.name) for c in checks if not c.ok}

    assert missing == {
        ("binary", "rg"),
        ("ollama", "gemma4:12b"),
        ("key", "A_KEY"),
        ("shell", "pinky on PATH"),
    }
    assert doctor.run_doctor() == 4


def test_run_doctor_output_is_stable_across_two_runs(tmp_path, monkeypatch, capsys):
    _full_setup(
        tmp_path,
        monkeypatch,
        which=lambda name: None,
        tags=lambda url: ["gemma4:12b"],
        keychain=lambda service: False,
    )
    monkeypatch.delenv("A_KEY", raising=False)
    doctor.run_doctor()
    first = capsys.readouterr().out
    doctor.run_doctor()
    second = capsys.readouterr().out
    assert first == second


def test_apply_fixes_brew_installs_a_missing_binary(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    calls: list[list[str]] = []

    installed = doctor.apply_fixes(
        [doctor.Check("binary", "rg", False, "brew install ripgrep")],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == [["brew", "install", "ripgrep"]]
    assert installed == ["ripgrep"]


def test_apply_fixes_never_touches_keys_or_ollama_models(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    calls: list[list[str]] = []

    installed = doctor.apply_fixes(
        [
            doctor.Check("key", "MISTRAL_API_KEY", False, "set $MISTRAL_API_KEY"),
            doctor.Check("ollama", "gemma4:12b", False, "ollama pull gemma4:12b"),
        ],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == []
    assert installed == []


def test_apply_fixes_offers_ollama_when_endpoint_down(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    calls: list[list[str]] = []

    doctor.apply_fixes(
        [doctor.Check("ollama", "endpoint", False, "démarrer Ollama")],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == [["brew", "install", "ollama"]]


def test_apply_fixes_no_brew_runs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    calls: list[list[str]] = []

    installed = doctor.apply_fixes(
        [doctor.Check("binary", "rg", False, "brew install ripgrep")],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == []
    assert installed == []
    assert "`brew` not on PATH" in capsys.readouterr().out


def test_apply_fixes_npm_installs_a_missing_lsp_binary(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []

    installed = doctor.apply_fixes(
        [
            doctor.Check(
                "binary",
                "pyright-langserver",
                False,
                "npm install -g pyright (required by: pyright-fork)",
            )
        ],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == [["npm", "install", "-g", "pyright"]]
    assert installed == ["pyright"]


def test_apply_fixes_partitions_per_tool_brew_runs_npm_skips(monkeypatch):
    """Only `brew` is on PATH — the brew-fixable check still runs, the npm one degrades to a
    manual instruction instead of blocking the whole batch (the fixes no
    longer share one package manager)."""
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
    )
    calls: list[list[str]] = []

    installed = doctor.apply_fixes(
        [
            doctor.Check("binary", "rg", False, "brew install ripgrep"),
            doctor.Check(
                "binary",
                "pyright-langserver",
                False,
                "npm install -g pyright (required by: pyright-fork)",
            ),
        ],
        runner=calls.append,
        confirm=lambda prompt: True,
    )

    assert calls == [["brew", "install", "ripgrep"]]
    assert installed == ["ripgrep"]


def test_apply_fixes_declined_prompt_skips(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    calls: list[list[str]] = []

    doctor.apply_fixes(
        [doctor.Check("binary", "rg", False, "x")],
        runner=calls.append,
        confirm=lambda prompt: False,
    )

    assert calls == []


def test_doctor_writes_no_ledger_and_no_config(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    settings_json = tmp_path / "settings.json"
    settings_json.write_text('{"kept": true}', encoding="utf-8")
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", ledger)
    _full_setup(
        tmp_path,
        monkeypatch,
        which=lambda name: None,
        tags=lambda url: [],
        keychain=lambda service: False,
    )
    monkeypatch.delenv("A_KEY", raising=False)

    doctor.run_doctor(fix=False)

    assert not ledger.exists()
    assert settings_json.read_text(encoding="utf-8") == '{"kept": true}'


def test_pinky_doctor_is_in_help(capsys):
    with pytest.raises(SystemExit):
        cli_pinky.main(["--help"])
    assert "doctor" in capsys.readouterr().out


def test_cmd_doctor_delegates_the_flag(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_pinky, "setup_main", lambda argv: calls.append(argv))

    cli_pinky.main(["doctor"])
    cli_pinky.main(["doctor", "--fix"])
    cli_pinky.main(["doctor", "--verbose"])

    assert calls == [["--doctor"], ["--doctor", "--fix"], ["--doctor", "--verbose"]]


@pytest.mark.parametrize(
    "install_args",
    [
        ["install"],
        ["claude-plugin", "install", "pc-snow"],
    ],
)
def test_pinky_install_calls_doctor_advisory(monkeypatch, install_args):
    """Every install path runs the preflight, and a missing prerequisite never raises —
    `claude-plugin install` most of all: it activates a plugin whose prerequisites are new."""
    monkeypatch.setattr(cli_pinky, "setup_main", lambda argv: None)
    ran: list[bool] = []
    # renvoie 3 (prérequis manquants) — `cmd_install` doit l'ignorer, jamais lever
    monkeypatch.setattr(doctor, "run_doctor", lambda **kw: ran.append(True) or 3)

    cli_pinky.main(install_args)

    assert ran == [True]


def test_check_shell_flags_pinky_missing_from_the_path_with_the_command_to_install_it(
    tmp_path,
):
    """`pinky` must be a command of its own on the PATH: shell completion is registered per command
    name, and `uv run pinky` makes `uv` the command."""
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("", encoding="utf-8")

    checks = doctor.check_shell(zshrc=zshrc, which=lambda name: None)

    path_check = next(c for c in checks if c.name == "pinky on PATH")
    assert path_check.category == "shell"
    assert path_check.ok is False
    assert "uv tool install --editable" in path_check.detail


def test_check_shell_accepts_pinky_on_the_path(tmp_path):
    checks = doctor.check_shell(
        zshrc=tmp_path / ".zshrc", which=lambda name: "/usr/local/bin/pinky"
    )

    assert next(c for c in checks if c.name == "pinky on PATH").ok is True


def test_check_shell_flags_completion_missing_from_zshrc_with_the_line_to_add(tmp_path):
    checks = doctor.check_shell(
        zshrc=tmp_path / "absent", which=lambda name: "/usr/local/bin/pinky"
    )

    completion = next(c for c in checks if c.name == "zsh completion")
    assert completion.ok is False
    assert (
        completion.detail
        == "run `pinky doctor --fix`, it adds 2 lines to ~/.zshrc after asking"
    )


def test_check_shell_accepts_completion_registered_in_zshrc(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text(
        'autoload -Uz compinit && compinit\neval "$(pinky completion zsh)"\n',
        encoding="utf-8",
    )

    checks = doctor.check_shell(zshrc=zshrc, which=lambda name: "/usr/local/bin/pinky")

    assert next(c for c in checks if c.name == "zsh completion").ok is True


def test_the_shell_checks_are_part_of_the_doctor_report():
    report = doctor.format_report(
        [
            doctor.Check(
                "shell", "pinky on PATH", False, "uv tool install --editable X"
            ),
            doctor.Check("shell", "zsh completion", True, ""),
        ],
        verbose=True,
    )

    assert "\nshell\n  ✓ zsh completion" in report
    assert "✗ pinky on PATH — uv tool install --editable X" in report


def test_the_completion_block_starts_zsh_completion_only_when_the_file_does_not_already():
    assert doctor.zsh_completion_block("export A=1\n") == (
        "\n"
        "# pinky: shell completion\n"
        "autoload -Uz compinit && compinit\n"
        'eval "$(pinky completion zsh)"\n'
    )
    assert doctor.zsh_completion_block("autoload -Uz compinit && compinit\n") == (
        '\n# pinky: shell completion\neval "$(pinky completion zsh)"\n'
    )


def test_adding_the_completion_appends_to_zshrc_after_a_yes(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("export A=1\n", encoding="utf-8")

    changed = doctor.add_zsh_completion(zshrc, confirm=lambda prompt: True)

    assert changed is True
    assert zshrc.read_text(encoding="utf-8") == (
        "export A=1\n"
        "\n"
        "# pinky: shell completion\n"
        "autoload -Uz compinit && compinit\n"
        'eval "$(pinky completion zsh)"\n'
    )


def test_adding_the_completion_twice_changes_nothing_the_second_time(tmp_path):
    zshrc = tmp_path / ".zshrc"
    doctor.add_zsh_completion(zshrc, confirm=lambda prompt: True)
    once = zshrc.read_text(encoding="utf-8")

    assert doctor.add_zsh_completion(zshrc, confirm=lambda prompt: True) is False
    assert zshrc.read_text(encoding="utf-8") == once


def test_declining_writes_nothing(tmp_path):
    zshrc = tmp_path / ".zshrc"

    assert doctor.add_zsh_completion(zshrc, confirm=lambda prompt: False) is False
    assert not zshrc.exists()


def test_the_prompt_shows_the_lines_before_asking(tmp_path):
    prompts: list[str] = []

    doctor.add_zsh_completion(
        tmp_path / ".zshrc", confirm=lambda prompt: prompts.append(prompt) or False
    )

    assert prompts == [
        "Add these lines to "
        + str(tmp_path / ".zshrc")
        + "?\n\n"
        + "  autoload -Uz compinit && compinit\n"
        + '  eval "$(pinky completion zsh)"\n\n'
        + "[y/N] "
    ]


def test_fix_offers_the_completion_and_reports_it_as_installed(tmp_path):
    zshrc = tmp_path / ".zshrc"
    missing = [
        doctor.Check("shell", "zsh completion", False, "run `pinky doctor --fix`")
    ]

    installed = doctor.apply_fixes(missing, confirm=lambda prompt: True, zshrc=zshrc)

    assert installed == ["zsh completion"]
    assert 'eval "$(pinky completion zsh)"' in zshrc.read_text(encoding="utf-8")
