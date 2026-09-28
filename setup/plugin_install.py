"""setup/plugin_install.py — fetch a plugin's files, then place its enablement where it belongs.

`claude plugin install --scope <s>` (Claude Code's own command) both fetches a plugin into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and enables it — there is no fetch-only
mode. Where the enablement lands is `--scope` × cwd:

- `--scope user` → `~/.claude/settings.json` `enabledPlugins`.
- `--scope project` run from dir X → `X/.claude/settings.json` `enabledPlugins`, plus a registry
  entry `{scope: project, projectPath: X}`. Repeated from other dirs, the entries accumulate; the
  files are fetched once and shared across scopes.

So a plugin useful only in some repos (`pc-snow` on data repos, not everywhere) is enabled by
running `claude plugin install --scope project` from each of those dirs — not by a hand-rolled
`enabledPlugins` merge. Nothing is downloaded before the scope is chosen, and a project choice
downloads straight at the project: `claude` needs no user-scope step first. `install_plugin_files` is the user-scope install, used only when the user picks
user scope or for an always-on plugin (`KEEP_USER_SCOPE`).

One thing `claude plugin install` does not do that this workspace needs: the main-session
`statusLine` key is not readable from a plugin's bundled `settings.json` — Claude Code reads only
`agent` and `subagentStatusLine` there — so a plugin that ships a status line
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
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

from . import state_file, style

_PLUGINS_DIR = Path.home() / ".claude" / "plugins"
_REGISTRY = _PLUGINS_DIR / "installed_plugins.json"
_MARKETPLACES = _PLUGINS_DIR / "known_marketplaces.json"
_CACHE_ROOT = _PLUGINS_DIR / "cache"
_USER_SETTINGS = Path.home() / ".claude" / "settings.json"

KEEP_USER_SCOPE = frozenset({"pc-autodiscovery", "pc-statusline"})


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


def prune_user_dependencies() -> None:
    """`claude plugin prune` at user scope: drop the auto-installed dependencies nothing needs any
    more. Uninstalling a plugin leaves the dependencies `claude` brought along — `pc-core` after
    `pc-git` — and `claude` says so ("Run `claude plugin prune` to remove"). Best-effort."""
    _run_claude(["plugin", "prune", "--scope", "user", "--yes"], check=False)


def install_plugin_files(plugin_id: str, marketplace: str | None = None) -> None:
    """Shell out to `claude plugin install --scope user` — download and enable at user scope — then
    `update`, so a re-run picks up a changed plugin (both are `restart required to apply`).

    Only for the plugin a user keeps at user scope: an always-on one (`KEEP_USER_SCOPE`) or one
    the user chose to put there. A project target downloads through `enable_at_project` instead.

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

    This is also the download: `claude` fetches the files on the first install at any scope and
    shares them across scopes. Adds a `{scope: project, projectPath: target}` registry entry and the
    settings write, and records it in the installer's ledger (`setup.state_file`).
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
    project entries reference the same `installPath`.

    Dumb primitive: it always uninstalls, then prunes the dependencies that leaves orphaned
    (`pc-core` after `pc-git`). The caller decides whether that is safe. `check=True`.
    """
    spec = _spec(plugin_id, marketplace)
    _run_claude(["plugin", "uninstall", spec, "--scope", "user", "--yes"])
    prune_user_dependencies()


def resolve_install_path(plugin_id: str, marketplace: str | None = None) -> Path:
    """The directory `claude plugin install` unpacked the plugin into, from the registry it keeps
    (`installed_plugins.json`) — authoritative, and still correct after a version bump."""
    return Path(_registered_install(plugin_id, marketplace)[1]["installPath"])


def _registered_install(
    plugin_id: str, marketplace: str | None = None
) -> tuple[str, dict[str, str]]:
    """The registry key and entry of the plugin's first install whose directory exists.

    Args:
        plugin_id: the plugin name, without marketplace.
        marketplace: the marketplace it comes from; None matches any.

    Returns:
        `(key, entry)` — the `<plugin>@<marketplace>` key and its `installed_plugins.json` entry
        (`scope`, `installPath`, `projectPath` for a project/local install).

    Raises:
        FileNotFoundError: no entry of that plugin points at an existing directory.
    """
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    plugins = data.get("plugins", {})
    keys = (
        [f"{plugin_id}@{marketplace}"]
        if marketplace
        else [k for k in plugins if k.split("@", 1)[0] == plugin_id]
    )
    for key in keys:
        for entry in plugins.get(key, []):
            if Path(entry["installPath"]).is_dir():
                return key, entry
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
    propagation bug (only LICENSE/README land in the cache) ever gets fixed
    upstream. A plugin whose files never carried this config, from any source, is a no-op here.
    """
    return any(install_path.rglob("*.lsp.json"))


@dataclass(frozen=True, eq=False)
class LspServerCommands:
    """Binaries an installed plugin's `*.lsp.json` file(s) declare a language server needs.

    Proxies `frozenset[str]` (iteration, length, equality/hash against a plain set) so the
    existing call sites need no change.
    """

    values: frozenset[str] = frozenset()

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LspServerCommands):
            return self.values == other.values
        if isinstance(other, frozenset | set):
            return self.values == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.values)


def lsp_server_commands(install_path: Path) -> LspServerCommands:
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
    return LspServerCommands(frozenset(commands))


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
    """Delete the plugin's cache directory and fetch it again — the automated form of
    `rm -rf ~/.claude/plugins/cache/<mp>/<plugin>/<ver>/` + reinstall, needed when editing a plugin
    pinned at `0.1.0` during dev (`claude` only ever fills an absent cache dir, and `update` skips
    a plugin whose version did not move). Returns True when a directory was removed and refetched,
    False when there was nothing to remove.

    The fetch is `claude plugin install` at the scope the registry already records for it, run from
    its `projectPath` for a project/local install — it rewrites an enable that is already there,
    nothing else. It happens here rather than on the caller's later install because that install
    only runs for a target the scope plan adds: an unchanged plan would leave the cache empty.

    The path comes from `installed_plugins.json` `installPath`, which this function does not
    control. It removes it **only** when it resolves to a `<marketplace>/<plugin>/<version>/` dir
    (≥ 3 segments) under `~/.claude/plugins/cache/` — a registry pointing anywhere else (a
    hand-edit, a future `directory`-source layout that maps a plugin onto its own working tree),
    or at the cache root / a whole marketplace dir, is refused rather than `rmtree`'d.
    """
    try:
        key, entry = _registered_install(plugin_id, marketplace)
    except FileNotFoundError:
        return False
    install_path = Path(entry["installPath"]).resolve()
    cache_root = _CACHE_ROOT.resolve()
    inside_a_plugin_version_dir = (
        install_path != cache_root
        and install_path.is_relative_to(cache_root)
        and len(install_path.relative_to(cache_root).parts) >= 3
    )
    if not inside_a_plugin_version_dir:
        print(
            f"⚠️  refusing --force: {install_path} is not a plugin cache directory under "
            f"{_CACHE_ROOT} — delete it by hand if that is really what you want",
            file=sys.stderr,
        )
        return False
    shutil.rmtree(install_path)
    scope = entry.get("scope", "user")
    project_path = entry.get("projectPath")
    cwd = Path(project_path) if scope != "user" and project_path else None
    try:
        _run_claude(["plugin", "install", key, "--scope", scope, "--yes"], cwd=cwd)
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        raise
    return True


@dataclass(frozen=True)
class RefreshOutcome:
    """What `refresh_plugins` did for one plugin: `refreshed`, `absent` (nothing cached or not a
    cache dir `force_refetch` may delete), or `failed` (the fetch errored — its stderr is already
    printed)."""

    spec: str
    status: Literal["refreshed", "absent", "failed"]


def local_marketplace_plugins() -> list[str]:
    """Every installed `<plugin>@<marketplace>` whose marketplace is a `directory` source — a
    working tree on this machine, the only place a plugin gets edited without a version bump.

    Returns:
        The registry keys, sorted; empty when either registry file is missing or unreadable.
    """
    try:
        marketplaces = json.loads(_MARKETPLACES.read_text(encoding="utf-8"))
        plugins = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, json.JSONDecodeError):
        return []
    local = {
        name
        for name, entry in marketplaces.items()
        if isinstance(entry, dict)
        and entry.get("source", {}).get("source") == "directory"
    }
    return sorted(key for key in plugins if key.split("@", 1)[-1] in local)


def refresh_plugins(
    specs: list[str], marketplace: str | None = None
) -> list[RefreshOutcome]:
    """Clear and refetch each plugin's cache — no scope plan, no question, nothing but the files.

    Args:
        specs: plugin names, bare or `<plugin>@<marketplace>`; empty means every plugin
            `local_marketplace_plugins` returns.
        marketplace: applied to every bare name in `specs`.

    Returns:
        One outcome per plugin, in order. A failed fetch does not stop the others.
    """
    outcomes = []
    for spec in specs or local_marketplace_plugins():
        name, _, own_marketplace = spec.partition("@")
        try:
            refreshed = force_refetch(name, own_marketplace or marketplace)
        except subprocess.CalledProcessError:
            outcomes.append(RefreshOutcome(spec, "failed"))
            continue
        outcomes.append(RefreshOutcome(spec, "refreshed" if refreshed else "absent"))
    return outcomes


_REFRESH_LABELS = {
    "refreshed": ("✓", style.GREEN, "refreshed"),
    "absent": ("•", style.DIM, "not installed — nothing to refresh"),
    "failed": ("✗", style.RED_BOLD, "fetch failed (see the error above)"),
}


def render_refresh_report(
    outcomes: list[RefreshOutcome], *, color: bool = False
) -> str:
    """The per-plugin report `pinky claude-plugin refresh` prints.

    Args:
        outcomes: what `refresh_plugins` returned.
        color: Paint each status mark the way `setup/doctor.py` does — off by default, so
            a caller that never passes it sees byte-identical output.

    Returns:
        One aligned line per plugin plus the reload reminder, or a single line when nothing
        matched.
    """
    if not outcomes:
        return "nothing to refresh — no plugin installed from a local (directory) marketplace"
    width = max(len(o.spec) for o in outcomes)
    lines = [
        f"{style.paint(mark, code, color=color)} {o.spec.ljust(width)}  {label}"
        for o in outcomes
        for mark, code, label in [_REFRESH_LABELS[o.status]]
    ]
    return "\n".join(
        [*lines, "", "Running sessions keep the old build until /reload-plugins."]
    )
