"""setup/plugin_install.py — fetch a plugin's files, then place its enablement where it belongs.

`claude plugin install --scope <s>` (Claude Code's own command) both fetches a plugin into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and enables it — there is no fetch-only
mode. Where the enablement lands is `--scope` × cwd (measured 2026-09-02):

- `--scope user` → `~/.claude/settings.json` `enabledPlugins`.
- `--scope project` run from dir X → `X/.claude/settings.json` `enabledPlugins`, plus a registry
  entry `{scope: project, projectPath: X}`. Repeated from other dirs, the entries accumulate; the
  files are fetched once and shared across scopes.

So a plugin useful only in some repos (`pc-snow` on data repos, not everywhere) is enabled by
running `claude plugin install --scope project` from each of those dirs — not by a hand-rolled
`enabledPlugins` merge. `install_plugin_files` still fetches at user scope first so the caller can
inspect the plugin (does it ship a status line?); `drop_user_scope` removes that transient user
entry once the real project targets are enabled.

One thing `claude plugin install` does not do that this workspace needs: the main-session
`statusLine` key is not readable from a plugin's bundled `settings.json` — Claude Code reads only
`agent` and `subagentStatusLine` there (verified 2026-08-28) — so a plugin that ships a status line
still needs an explicit `statusLine` entry pointing at its installed script. That entry is an
absolute path with the plugin version in it, so `set_status_lines` re-resolves it from the install
registry (never a guessed path) on every `pinky install` run — the replayable-converger model.
Re-run after `claude plugin update <plugin>`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import state_file

_PLUGINS_DIR = Path.home() / ".claude" / "plugins"
_REGISTRY = _PLUGINS_DIR / "installed_plugins.json"
_CACHE_ROOT = _PLUGINS_DIR / "cache"
_USER_SETTINGS = Path.home() / ".claude" / "settings.json"


def _spec(plugin_id: str, marketplace: str | None) -> str:
    return f"{plugin_id}@{marketplace}" if marketplace else plugin_id


def _run_claude(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a `claude` subcommand with its output captured (never streamed to this process's
    stdout/stderr). The fetch/enable helpers in this module go through here; `enable_at_project`
    and `plugin_reconcile`'s own `claude` calls do not. `check=True` (default) raises
    `CalledProcessError` with the CLI's stdout/stderr on the exception — a caller that surfaces
    the failure to a human must print `e.stderr` itself, `CalledProcessError.__str__` shows only
    the exit code."""
    return subprocess.run(
        ["claude", *args], cwd=cwd, capture_output=True, text=True, check=check
    )


def is_user_enabled(plugin_id: str, marketplace: str | None = None) -> bool:
    """Is the plugin already `true` in `~/.claude/settings.json` `enabledPlugins` before we touch
    anything? The caller captures this before `install_plugin_files` so it can tell a
    fetch-time transient enable (safe to drop) from a legitimate global one (must not touch)."""
    if not _USER_SETTINGS.is_file():
        return False
    enabled = json.loads(_USER_SETTINGS.read_text(encoding="utf-8")).get(
        "enabledPlugins", {}
    )
    return enabled.get(_spec(plugin_id, marketplace)) is True


def install_plugin_files(plugin_id: str, marketplace: str | None = None) -> None:
    """Shell out to `claude plugin install` — fetch + enable at user scope — then `update`, so a
    re-run picks up a changed plugin (both are `restart required to apply`, like the rest of D2).

    The user-scope enable is transient for any plugin that ends up project-scoped: it exists so
    the caller can `resolve_install_path` + inspect the fetched files, and `drop_user_scope`
    removes it afterwards. For a plugin the user keeps at user scope (a status line, a global
    preference) it stays.

    `check=True` on install: a failure there must stop the flow, never leave the caller wiring
    settings for a plugin whose files never landed. The CLI's own stderr (which
    `CalledProcessError` carries but its `str()` drops) is printed before the error propagates,
    so the caller sees *why* the fetch failed, not just a bare traceback. `update` is best-effort
    (it errors when the plugin is brand-new and already current).
    """
    spec = _spec(plugin_id, marketplace)
    try:
        _run_claude(["plugin", "install", spec, "--scope", "user", "--yes"])
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        raise
    _run_claude(["plugin", "update", spec], check=False)


def enable_at_project(
    plugin_id: str, target: Path, marketplace: str | None = None
) -> None:
    """Enable the plugin at exactly `target` — `claude plugin install --scope project` run with
    `cwd=target`, so `enabledPlugins` lands in `target/.claude/settings.json` and nowhere else.

    The plugin's files are already cached from `install_plugin_files`; this call adds a
    `{scope: project, projectPath: target}` registry entry and the settings write. Records the
    write in the installer's ledger (`setup.state_file`), same key shape the old hand-rolled
    merge used.
    """
    spec = _spec(plugin_id, marketplace)
    subprocess.run(
        ["claude", "plugin", "install", spec, "--scope", "project", "--yes"],
        check=True,
        cwd=target,
    )
    state_file.record_posed(
        f"enabledPlugins:{spec}@{target}",
        path=str(target / ".claude" / "settings.json"),
        value="true",
    )


def drop_user_scope(plugin_id: str, marketplace: str | None = None) -> None:
    """Uninstall the plugin at user scope — `claude plugin uninstall --scope user` removes the
    user `enabledPlugins` key and the user registry entry; the cached files stay because any
    project entries reference the same `installPath` (measured 2026-09-02).

    Dumb primitive: it always uninstalls. The caller decides whether that is safe — it drops the
    entry only when it captured `is_user_enabled() is False` before the fetch, so a legitimate
    pre-existing global enablement is never stripped. `check=True` — a plugin left enabled at
    user scope *and* at a project target is the parasitic global activation this flow avoids.
    """
    spec = _spec(plugin_id, marketplace)
    _run_claude(["plugin", "uninstall", spec, "--scope", "user", "--yes"])


def resolve_install_path(plugin_id: str, marketplace: str | None = None) -> Path:
    """The directory `claude plugin install` unpacked the plugin into, from the registry it keeps
    (`installed_plugins.json`) — authoritative, and still correct after a version bump."""
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    plugins = data.get("plugins", {})
    keys = (
        [f"{plugin_id}@{marketplace}"]
        if marketplace
        else [k for k in plugins if k.split("@", 1)[0] == plugin_id]
    )
    for key in keys:
        for entry in plugins.get(key, []):
            path = Path(entry["installPath"])
            if path.is_dir():
                return path
    raise FileNotFoundError(
        f"{plugin_id!r} not in {_REGISTRY} — was `claude plugin install` run?"
    )


def _merge_user_settings(updates: dict[str, object]) -> None:
    """Merge `updates` into `~/.claude/settings.json` — read what's there, set only these keys,
    same discipline as `plugin_scope.enable_plugin` and `agentic_assets._install`."""
    data = (
        json.loads(_USER_SETTINGS.read_text(encoding="utf-8"))
        if _USER_SETTINGS.is_file()
        else {}
    )
    data.update(updates)
    _USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _USER_SETTINGS.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def ships_lsp_server(install_path: Path) -> bool:
    """Does the installed plugin carry a language-server config on disk (`*.lsp.json`)? The
    signal `ensure_lsp_tool_enabled` needs before it writes anything — independent of which
    marketplace the plugin came from, so it stays correct if the official marketplace's
    propagation bug (measured 2026-09-04: only LICENSE/README land in the cache) ever gets fixed
    upstream. A plugin whose files never carried this config, from any source, is a no-op here.
    """
    return any(install_path.rglob("*.lsp.json"))


def lsp_server_commands(install_path: Path) -> set[str]:
    """Every `command` an installed plugin's `*.lsp.json` file(s) declare — the binaries a working
    language server needs on PATH (`pyright-langserver` for `pyright`, ...). `setup/doctor.py`'s
    `required_lsp_binaries` reads this to check they are actually installed, the same way
    `required_binaries` already checks `allowed-tools` binaries — a separate source, not a
    duplicate of `ships_lsp_server`, which only answers presence, not which binaries.
    """
    commands: set[str] = set()
    for lsp_json in install_path.rglob("*.lsp.json"):
        try:
            data = json.loads(lsp_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for entry in data.values():
            if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                commands.add(entry["command"])
    return commands


def ensure_lsp_tool_enabled() -> None:
    """`ENABLE_LSP_TOOL` has no plugin-manifest slot — like `statusLine` — so a plugin that ships
    a language server needs it wired explicitly. Always user scope (`~/.claude/settings.json`):
    the plugin's own files are never git-transferable (no fetch-only mode, cache is local-only —
    see module docstring), so anyone who needs the LSP tool functional runs a local install
    regardless, which already sets this as a side effect — scoping it to the plugin's target
    would only add drift with no onboarding benefit.
    """
    data = (
        json.loads(_USER_SETTINGS.read_text(encoding="utf-8"))
        if _USER_SETTINGS.is_file()
        else {}
    )
    data.setdefault("env", {})["ENABLE_LSP_TOOL"] = "1"
    _USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _USER_SETTINGS.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    state_file.record_posed(
        "env.ENABLE_LSP_TOOL@user", path=str(_USER_SETTINGS), value="1"
    )


def set_status_lines(install_path: Path) -> list[str]:
    """If `install_path` ships `scripts/statusline.py`, point `statusLine` (and
    `subagentStatusLine` when the script is there too) at the installed scripts, merged into
    `~/.claude/settings.json`. Returns the keys written — empty when the plugin has no status line.

    `subagentStatusLine` is also declared in the plugin's own bundled `settings.json`; writing it
    here as well is deliberate until `${CLAUDE_PLUGIN_ROOT}` expansion inside a bundled
    `settings.json` is confirmed working (a user `settings.json` value wins over a plugin one).
    """
    main = install_path / "scripts" / "statusline.py"
    if not main.is_file():
        return []

    sub = install_path / "scripts" / "subagent_statusline.py"
    scripts = {"statusLine": main}
    if sub.is_file():
        scripts["subagentStatusLine"] = sub

    _merge_user_settings(
        {
            key: {"type": "command", "command": f'python3 "{path}"'}
            for key, path in scripts.items()
        }
    )
    for key, path in scripts.items():
        state_file.record_posed(key, path=str(_USER_SETTINGS), value=str(path))
    return list(scripts)


def force_refetch(plugin_id: str, marketplace: str | None = None) -> bool:
    """Delete the plugin's cache directory so the next `claude plugin install`/`update` re-pulls
    it — the automated form of the manual `rm -rf ~/.claude/plugins/cache/<mp>/<plugin>/<ver>/`
    needed when editing a plugin pinned at `0.1.0` during dev (`claude` only ever fills an absent
    cache dir). Returns True when a directory was removed, False when there was nothing to remove.

    The path comes from `installed_plugins.json` `installPath`, which this function does not
    control. It removes it **only** when it resolves under `~/.claude/plugins/cache/` — a
    registry pointing anywhere else (a hand-edit, a future `directory`-source layout that maps a
    plugin onto its own working tree) is refused rather than `rmtree`'d.
    """
    try:
        install_path = resolve_install_path(plugin_id, marketplace).resolve()
    except FileNotFoundError:
        return False
    if not install_path.is_relative_to(_CACHE_ROOT.resolve()):
        print(
            f"⚠️  refusing --force: {install_path} is not under {_CACHE_ROOT} — "
            "delete it by hand if that is really what you want",
            file=sys.stderr,
        )
        return False
    shutil.rmtree(install_path)
    return True
