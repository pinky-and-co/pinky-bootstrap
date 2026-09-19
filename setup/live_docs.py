"""setup/live_docs.py — install the live board/log viewer as a `pinky install` asset.

The viewer is a small MkDocs site (`live-docs/hooks.py` renders a Jira-style board from a
chantier's column folders; `mkdocs.yml` + `stylesheets/board.css`). Those three files are the only
versioned part — `pinky-bootstrap` is public, and a kanban board or an agent log in a commit is a
leak. Everything the viewer *shows* is mounted locally at install time as symlinks under
``~/.local/share/pinky/live-docs/docs/`` and never touched by git.

`pinky live-docs install` copies the tooling there, generates the mounts, and on macOS loads a
launchd agent so the site is served after every boot. Off macOS there is no service — the tooling
is installed and `pinky live-docs serve` runs it live. Same `setup.state_file` ledger as every other
`pinky install` asset, so `--status` and removal work the same way.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess  # nosec B404 — `launchctl` and `uv`, fixed argv, never shell=True
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import state_file
from .common import SCRIPT_DIR, find_workspace_root

LIVE_DOCS_SRC = SCRIPT_DIR / "live-docs"
INSTALL_DIR = Path.home() / ".local" / "share" / "pinky" / "live-docs"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.pinky.live-docs.plist"
LAUNCHD_LABEL = "com.pinky.live-docs"
SERVE_ADDR = "127.0.0.1:8765"

MKDOCS_DEPS = ("mkdocs-material>=9.7,<10", "mkdocs-awesome-nav>=3.3,<4")

_TOOLING = {
    "hooks.py": "hooks.py",
    "mkdocs.yml": "mkdocs.yml",
    "stylesheets/board.css": "docs/stylesheets/board.css",
}

_LEDGER_TOOLING = "live-docs:tooling"
_LEDGER_PLIST = "live-docs:plist"


@dataclass(frozen=True)
class BoardMount:
    """One symlink the viewer needs: ``docs/<name>`` → the real kanban or agent-log directory."""

    name: str
    source: Path


def _code_workspace_file(workspace_root: Path) -> Path | None:
    """The ``*.code-workspace`` file at ``workspace_root``, or None."""
    matches = sorted(workspace_root.glob("*.code-workspace"))
    return matches[0] if matches else None


def _strip_jsonc(text: str) -> str:
    """Drop ``//`` and ``/* */`` comments — a ``.code-workspace`` file is JSONC. String-aware:
    a ``//`` inside a quoted value (``"https://…"``, a Proton path) is left alone."""
    out: list[str] = []
    i, n, in_string = 0, len(text), False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def discover_board_mounts(workspace_root: Path) -> list[BoardMount]:
    """Every ``_KANBAN`` / ``_AGENT_LOG`` directory reachable from the workspace, as named mounts.

    Sources: each ``folders[]`` entry of the ``*.code-workspace`` file (the VSCode multi-root
    convention already declares this N-mount), plus ``workspace_root`` itself. A folder named
    ``<base>`` contributes ``<base>-kanban`` for its ``_KANBAN`` and ``<base>-log`` for its
    ``_AGENT_LOG``, whichever exist. Deterministic order (sorted by mount name).
    """
    roots: list[Path] = [workspace_root]
    ws_file = _code_workspace_file(workspace_root)
    if ws_file is not None:
        try:
            data = json.loads(_strip_jsonc(ws_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            data = {}
        for entry in data.get("folders", []) if isinstance(data, dict) else []:
            raw = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(raw, str):
                continue
            p = Path(raw).expanduser()
            roots.append(p if p.is_absolute() else (ws_file.parent / p).resolve())

    mounts: dict[str, BoardMount] = {}
    for root in roots:
        base = root.resolve().name
        for subdir, suffix in (("_KANBAN", "kanban"), ("_AGENT_LOG", "log")):
            source = root / subdir
            if source.is_dir():
                name = f"{base}-{suffix}"
                mounts.setdefault(name, BoardMount(name=name, source=source.resolve()))
    return [mounts[k] for k in sorted(mounts)]


def _copy_tooling(src: Path, install_dir: Path) -> None:
    """Copy the three tooling files from ``src`` into ``install_dir`` at their runtime layout."""
    for rel, dest_rel in _TOOLING.items():
        dest = install_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((src / rel).read_bytes())


def _write_mounts(install_dir: Path, mounts: list[BoardMount]) -> list[Path]:
    """(Re)create the ``docs/<name>`` symlinks, dropping any stale ones. Returns the links made."""
    docs = install_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    wanted = {m.name for m in mounts}
    for existing in docs.iterdir():
        if existing.is_symlink() and existing.name not in wanted:
            existing.unlink()
    links: list[Path] = []
    for mount in mounts:
        link = docs / mount.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(mount.source, target_is_directory=True)
        links.append(link)
    return links


def render_plist(install_dir: Path, *, uv: str) -> str:
    """The launchd agent plist — `uv tool run … mkdocs serve` against the installed tooling.

    Sérialisé par `plistlib` (stdlib) : les pins de version MkDocs portent un `<` (`<10`, `<4`),
    caractère qui casse le XML si on l'écrit à la main — `<10</string>` ouvre une balise. `plistlib`
    l'échappe (`&lt;`), et `launchctl bootstrap` accepte alors le fichier.
    """
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            uv,
            "tool",
            "run",
            *(a for dep in MKDOCS_DEPS for a in ("--with", dep)),
            "mkdocs",
            "serve",
            "-f",
            str(install_dir / "mkdocs.yml"),
            "-a",
            SERVE_ADDR,
        ],
        "WorkingDirectory": str(install_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(install_dir / ".cache" / "live-docs.log"),
        "StandardErrorPath": str(install_dir / ".cache" / "live-docs.err.log"),
        "EnvironmentVariables": {"NO_MKDOCS_2_WARNING": "1"},
    }
    return plistlib.dumps(plist).decode("utf-8")


def _launchctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # nosec B603, B607 — fixed argv, no shell
        ["launchctl", *args], capture_output=True, check=False
    )


def _uv_path() -> str:
    """Absolute path to `uv` for the plist (launchd has a minimal PATH), or the bare name."""
    return shutil.which("uv") or "uv"


def _launchd_domain() -> str:
    """`gui/<uid>` — the launchd domain the agent loads into. `os.getuid` is POSIX-only; the
    fallback keeps the module importable and unit-testable on Windows (the launchd path never
    runs there — `is_macos` gates it)."""
    getuid = getattr(os, "getuid", None)
    return f"gui/{getuid() if getuid else 0}"


class LiveDocsConflict(RuntimeError):
    """`install` found a launchd plist at the target path that pinky did not pose — refuse to
    clobber it (state-file ownership rule). `--force` overrides."""


@dataclass(frozen=True)
class InstallResult:
    """What `install` did, for the CLI to report."""

    install_dir: Path
    mounts: list[str]
    service: str  # "loaded" | "skipped (not macOS)" | "bootstrap failed (rc=N)"


def install(
    *,
    workspace_root: Path | None = None,
    src: Path = LIVE_DOCS_SRC,
    install_dir: Path = INSTALL_DIR,
    plist_path: Path = PLIST_PATH,
    is_macos: bool | None = None,
    force: bool = False,
    launchctl=_launchctl,
) -> InstallResult:
    """Copy the tooling, generate the board mounts, and (macOS) load the launchd agent.

    Records the install dir and the plist in `setup.state_file`, so `status` / removal work like
    every other `pinky install` asset. Idempotent — a re-run re-copies the tooling and refreshes
    the mounts (a board added since is picked up).

    On macOS, refuses with `LiveDocsConflict` if a plist pinky did not pose already sits at
    `plist_path` (e.g. a hand-rolled `_LIVE_DOCS` service on the same label) unless `force=True`.
    """
    if is_macos is None:
        is_macos = sys.platform == "darwin"

    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / ".cache").mkdir(exist_ok=True)
    _copy_tooling(src, install_dir)

    ws_root = workspace_root or find_workspace_root(Path.cwd())
    mounts = discover_board_mounts(ws_root)
    _write_mounts(install_dir, mounts)
    state_file.record_posed(_LEDGER_TOOLING, path=str(install_dir), value="installed")

    if not is_macos:
        return InstallResult(
            install_dir, [m.name for m in mounts], "skipped (not macOS)"
        )

    if (
        not force
        and _plist_status(install_dir, plist_path)
        == state_file.EntryStatus.PRESENT_NOT_MINE
    ):
        raise LiveDocsConflict(
            f"{plist_path} already holds a launchd agent pinky did not install "
            f"(a hand-rolled _LIVE_DOCS service?) — remove it first, or re-run with --force."
        )

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(render_plist(install_dir, uv=_uv_path()), encoding="utf-8")
    state_file.record_posed(_LEDGER_PLIST, path=str(plist_path), value=LAUNCHD_LABEL)

    domain = _launchd_domain()
    if launchctl("print", f"{domain}/{LAUNCHD_LABEL}").returncode == 0:
        launchctl("bootout", f"{domain}/{LAUNCHD_LABEL}")
    booted = launchctl("bootstrap", domain, str(plist_path))
    service = (
        "loaded"
        if booted.returncode == 0
        else f"bootstrap failed (rc={booted.returncode})"
    )
    return InstallResult(install_dir, [m.name for m in mounts], service)


def _plist_reader(install_dir: Path, plist_path: Path) -> Callable[[], str | None]:
    """Current value at `plist_path` for the plist ledger entry: our label if the plist points at
    `install_dir`, `"other"` if a plist is there but points elsewhere, None if absent."""

    def _read() -> str | None:
        if not plist_path.is_file():
            return None
        return (
            LAUNCHD_LABEL
            if str(install_dir) in plist_path.read_text(encoding="utf-8")
            else "other"
        )

    return _read


def _plist_status(install_dir: Path, plist_path: Path) -> state_file.EntryStatus:
    return state_file.status_of(_LEDGER_PLIST, _plist_reader(install_dir, plist_path))


def status(
    *, install_dir: Path = INSTALL_DIR, plist_path: Path = PLIST_PATH
) -> state_file.EntryStatus:
    """Where the viewer stands: posed by us, present but not ours, or absent.

    On macOS the launchd plist is the artefact that decides. Without a plist (off macOS, or a
    serve-only setup) the install dir under the tooling ledger stands in — `install` records that
    entry on every platform, so `pinky live-docs status` is meaningful there too.
    """
    if plist_path.is_file():
        return _plist_status(install_dir, plist_path)

    def _tooling_reader() -> str | None:
        return "installed" if install_dir.is_dir() else None

    return state_file.status_of(_LEDGER_TOOLING, _tooling_reader)


def uninstall(
    *,
    install_dir: Path = INSTALL_DIR,
    plist_path: Path = PLIST_PATH,
    launchctl=_launchctl,
) -> list[str]:
    """Remove only what `install` posed — the launchd agent, the plist, the install dir. Returns
    what was removed. Leaves a plist we did not pose alone (state-file ownership rule)."""
    removed: list[str] = []
    _plist_reader_fn = _plist_reader(install_dir, plist_path)

    def _remove_plist() -> None:
        launchctl("bootout", f"{_launchd_domain()}/{LAUNCHD_LABEL}")
        plist_path.unlink(missing_ok=True)
        removed.append(str(plist_path))

    state_file.unrecord_if_still_mine(_LEDGER_PLIST, _plist_reader_fn, _remove_plist)

    def _dir_reader() -> str | None:
        return "installed" if install_dir.is_dir() else None

    def _remove_dir() -> None:
        shutil.rmtree(install_dir, ignore_errors=True)
        removed.append(str(install_dir))

    state_file.unrecord_if_still_mine(_LEDGER_TOOLING, _dir_reader, _remove_dir)
    return removed


def serve(
    *,
    workspace_root: Path | None = None,
    src: Path = LIVE_DOCS_SRC,
    install_dir: Path = INSTALL_DIR,
    runner=None,
) -> None:
    """Refresh the tooling + mounts, then run `mkdocs serve` in the foreground (no service).

    The portable path — Windows, or an ad-hoc look without loading a launchd agent.
    """
    install_dir.mkdir(parents=True, exist_ok=True)
    _copy_tooling(src, install_dir)
    ws_root = workspace_root or find_workspace_root(Path.cwd())
    _write_mounts(install_dir, discover_board_mounts(ws_root))

    cmd = [
        _uv_path(),
        "tool",
        "run",
        *(a for dep in MKDOCS_DEPS for a in ("--with", dep)),
        "mkdocs",
        "serve",
        "-f",
        str(install_dir / "mkdocs.yml"),
        "-a",
        SERVE_ADDR,
    ]
    run = runner or (
        lambda argv: subprocess.run(  # nosec B603 — fixed argv, no shell
            argv, check=False, env={**os.environ, "NO_MKDOCS_2_WARNING": "1"}
        )
    )
    print(f"live-docs → http://{SERVE_ADDR}  (Ctrl-C to stop)")
    run(cmd)
