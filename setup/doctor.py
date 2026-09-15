"""setup/doctor.py — `pinky doctor`: check the prerequisites installed plugins assume.

A plugin manifest declares `dependencies` (plugin→plugin) but has no slot for the *ambient*
prerequisites a plugin's skills need: an external binary (`rg`, `yt-dlp`, `markitdown`…), a
reachable local Ollama with the model pulled, an API key. Nothing surfaces a missing one until a
skill runs and `Bash` fails `command not found` — so this checks them once, up front.

- **binaries** — derived from the `Bash(...)` entries in the `allowed-tools` frontmatter of each
  installed plugin's skills/agents (all scopes), minus an allowlist of always-present ambients.
- **Ollama** — the `kind: offline` entry of `model_pool` in `settings.pinky.json`: endpoint
  reachable (`/api/tags`) and the default model listed there.
- **API keys** — the `keys` section of `settings.pinky.json`: each `env` resolvable from the
  environment or the macOS keychain.

`pinky doctor` exits non-zero when a prerequisite is missing (a diagnostic meant to be actionable,
CI-usable). `pinky install` calls it advisory — a missing prerequisite never fails the install.
Read-only: it writes no ledger entry and no config (`--fix` shells `brew`, nothing else).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 — `brew`/`npm`/`security`, fixed argv, never shell=True
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import plugin_install

_CLAUDE_DIR = Path.home() / ".claude"
INSTALLED_PLUGINS_PATH = _CLAUDE_DIR / "plugins" / "installed_plugins.json"
SETTINGS_PINKY_PATH = _CLAUDE_DIR / "settings.pinky.json"

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:12b"

# Binaries every dev machine has — subtracted from the frontmatter-derived set so the report only
# lists what someone might actually need to install.
AMBIENT_BINARIES = frozenset(
    {
        "awk",
        "basename",
        "bash",
        "cat",
        "cd",
        "cp",
        "curl",
        "date",
        "echo",
        "find",
        "git",
        "grep",
        "head",
        "ls",
        "mkdir",
        "mv",
        "py",
        "python",
        "python3",
        "rm",
        "sed",
        "sh",
        "tail",
        "test",
        "touch",
    }
)

# Binary name → Homebrew formula, only where the two differ. Unknown binaries fall back to their
# own name (`brew install <name>`), which errors visibly when there is no such formula — the
# user's signal to install it another way.
_BREW_FORMULA = {"rg": "ripgrep"}

_INSTALL_COMMAND: dict[str, list[str]] = {
    "pyright-langserver": ["npm", "install", "-g", "pyright"],
}

_BIN_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class Check:
    """One prerequisite and whether it is satisfied.

    Attributes:
        category: ``binary`` | ``ollama`` | ``key`` — also the report's grouping.
        name: what is checked — a binary name, ``endpoint``, a model tag, an env var name.
        ok: True when the prerequisite is present.
        detail: a one-line hint — what it is needed for when ``ok``, how to get it otherwise.
    """

    category: str
    name: str
    ok: bool
    detail: str


# ── binaries ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, eq=False)
class BashBinaries:
    """Binary names referenced by one ``allowed-tools`` value's ``Bash(...)`` entries.

    Proxies `frozenset[str]` (iteration, length, equality/hash against a plain set) so the
    existing call sites need no change.
    """

    values: frozenset[str] = frozenset()

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BashBinaries):
            return self.values == other.values
        if isinstance(other, frozenset | set):
            return self.values == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.values)


def parse_bash_binaries(allowed_tools: str) -> BashBinaries:
    """External binary names referenced by the ``Bash(...)`` entries of an ``allowed-tools`` value.

    Handles the forms seen in real plugin frontmatter: ``Bash(rg:*)`` → ``rg``,
    ``Bash(command -v markitdown:*)`` → ``markitdown``, ``Bash(gh run list:*)`` → ``gh``. Entries
    that are not ``Bash(...)`` (``Read``, ``mcp__…``) and ``Bash`` entries whose command is a path
    (``Bash(${CLAUDE_PLUGIN_ROOT}/hooks/x.sh:*)``) contribute nothing. Never raises on a
    malformed entry — an unrecognised shape is skipped.
    """
    binaries: set[str] = set()
    for raw in allowed_tools.split(","):
        entry = raw.strip()
        m = re.match(r"^Bash\((.*)\)$", entry)
        if not m:
            continue
        command = m.group(1).strip()
        command = re.sub(
            r":\*$", "", command
        ).strip()  # retire le glob d'arguments final
        if not command or command[0] in "$/" or command.startswith("~"):
            continue
        words = command.split()
        if words[0] == "command" and len(words) >= 2 and words[1] == "-v":
            # `Bash(command -v X:*)` teste X ; `Bash(command -v:*)` ne teste rien.
            candidate = words[2] if len(words) >= 3 else ""
        else:
            candidate = words[0]
        candidate = candidate.strip("\"'")
        if candidate and candidate != "command" and _BIN_NAME_RE.match(candidate):
            binaries.add(candidate)
    return BashBinaries(frozenset(binaries))


def _frontmatter_field(path: Path, field: str) -> str | None:
    """The value of a single ``field:`` in a Markdown file's ``---`` frontmatter, or None."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        m = re.match(rf"^{re.escape(field)}:\s*(.+)$", line)
        if m:
            return m.group(1).strip()
    return None


def installed_plugins(path: Path | None = None) -> list[tuple[str, Path]]:
    """``(plugin name, installPath dir)`` for every installed plugin whose dir exists (all scopes).

    The plugin name is the registry key before ``@`` — the ``installPath`` basename is the version
    (``…/cache/<marketplace>/<plugin>/<version>/``), not the name.
    """
    path = path or INSTALLED_PLUGINS_PATH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    plugins: list[tuple[str, Path]] = []
    for key, entries in data.get("plugins", {}).items():
        name = key.split("@", 1)[0]
        for entry in entries:
            install_path = entry.get("installPath")
            if install_path and Path(install_path).is_dir():
                plugins.append((name, Path(install_path)))
    return plugins


@dataclass(frozen=True, eq=False)
class _BinaryRequirers(Mapping[str, list[str]]):
    """Non-ambient binary → sorted names of the plugins that need it.

    A read-only mapping — supports `[binary]`, `.items()`, truthiness and `== {}`, exactly like
    the plain `dict` it replaces.
    """

    by_binary: dict[str, list[str]] = field(default_factory=dict)

    def __getitem__(self, key: str) -> list[str]:
        return self.by_binary[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.by_binary)

    def __len__(self) -> int:
        return len(self.by_binary)


def required_binaries(plugins: Iterable[tuple[str, Path]]) -> _BinaryRequirers:
    """Non-ambient binary → sorted names of the plugins whose frontmatter references it."""
    by_binary: dict[str, set[str]] = {}
    for name, plugin_dir in plugins:
        files = [
            *sorted(plugin_dir.glob("skills/*/SKILL.md")),
            *sorted(plugin_dir.glob("agents/*.md")),
        ]
        found: set[str] = set()
        for f in files:
            for field_name in ("allowed-tools", "tools"):
                value = _frontmatter_field(f, field_name)
                if value:
                    found |= parse_bash_binaries(value).values
        for binary in found - AMBIENT_BINARIES:
            by_binary.setdefault(binary, set()).add(name)
    return _BinaryRequirers(
        {b: sorted(names) for b, names in sorted(by_binary.items())}
    )


def required_lsp_binaries(plugins: Iterable[tuple[str, Path]]) -> _BinaryRequirers:
    """Non-ambient binary → sorted names of the plugins whose `.lsp.json` declares it.

    A separate source from `required_binaries` (`allowed-tools`-derived) — an `.lsp.json`'s
    `command` is not frontmatter, `plugin_install.lsp_server_commands` reads it directly. Merged
    with the other source in `check_binaries`, so a binary needed by both lists every plugin.
    """
    by_binary: dict[str, set[str]] = {}
    for name, plugin_dir in plugins:
        for binary in (
            plugin_install.lsp_server_commands(plugin_dir).values - AMBIENT_BINARIES
        ):
            by_binary.setdefault(binary, set()).add(name)
    return _BinaryRequirers(
        {b: sorted(names) for b, names in sorted(by_binary.items())}
    )


def _install_hint(binary: str) -> str:
    """The human-readable install instruction for `binary` — `_INSTALL_COMMAND` when its remedy
    is not brew, else `brew install <formula>` (the long-standing default)."""
    if binary in _INSTALL_COMMAND:
        return " ".join(_INSTALL_COMMAND[binary])
    return f"brew install {_BREW_FORMULA.get(binary, binary)}"


def check_binaries(
    plugins: Iterable[tuple[str, Path]] | None = None,
) -> list[Check]:
    """One Check per required binary — ``ok`` when ``shutil.which`` finds it. Merges the
    `allowed-tools`-derived set with the `.lsp.json`-derived one (`required_lsp_binaries`)."""
    if plugins is None:
        plugins = installed_plugins()
    plugins = list(plugins)
    by_binary: dict[str, set[str]] = {}
    for binary, names in required_binaries(plugins).items():
        by_binary.setdefault(binary, set()).update(names)
    for binary, names in required_lsp_binaries(plugins).items():
        by_binary.setdefault(binary, set()).update(names)
    checks: list[Check] = []
    for binary in sorted(by_binary):
        needed_by = sorted(by_binary[binary])
        ok = shutil.which(binary) is not None
        by = ", ".join(needed_by)
        detail = (
            f"requis par : {by}"
            if ok
            else f"{_install_hint(binary)} (requis par : {by})"
        )
        checks.append(Check("binary", binary, ok, detail))
    return checks


# ── Ollama ──────────────────────────────────────────────────────────────────────────────────


def _load_model_pool(settings_pinky_path: Path) -> list[dict]:
    if not settings_pinky_path.is_file():
        return []
    try:
        data = json.loads(settings_pinky_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    pool = data.get("model_pool")
    return pool if isinstance(pool, list) else []


def _read_ollama_tags(url: str) -> list[str] | None:
    """Model tags from Ollama's ``/api/tags``; None when the endpoint is unreachable."""
    try:
        with urllib.request.urlopen(  # nosec B310 — local endpoint (PINKY_OLLAMA_URL/localhost)
            f"{url}/api/tags", timeout=5
        ) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    models = data.get("models", []) if isinstance(data, dict) else []
    return [m["name"] for m in models if isinstance(m, dict) and "name" in m]


def check_ollama(
    settings_pinky_path: Path | None = None,
    *,
    tags_reader: Callable[[str], list[str] | None] | None = None,
) -> list[Check]:
    """Endpoint + default-model Checks for the ``kind: offline`` pool entry — [] when there is none."""
    path = settings_pinky_path or SETTINGS_PINKY_PATH
    offline = next(
        (e for e in _load_model_pool(path) if e.get("kind") == "offline"), None
    )
    if offline is None:
        return []
    url = os.environ.get("PINKY_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    reader = tags_reader or _read_ollama_tags
    tags = reader(url)
    if tags is None:
        return [
            Check(
                "ollama",
                "endpoint",
                False,
                f"démarrer Ollama — `brew services start ollama` ({url})",
            )
        ]
    checks = [Check("ollama", "endpoint", True, url)]
    model = offline.get("model") or DEFAULT_OLLAMA_MODEL
    ok = any(tag == model or tag.split(":")[0] == model.split(":")[0] for tag in tags)
    checks.append(Check("ollama", model, ok, "" if ok else f"ollama pull {model}"))
    return checks


# ── API keys ────────────────────────────────────────────────────────────────────────────────


def _keychain_has(service: str) -> bool:
    if not shutil.which("security"):
        return False
    return (
        subprocess.run(  # nosec B603, B607 — fixed argv, no shell
            ["security", "find-generic-password", "-s", service],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def check_keys(
    settings_pinky_path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    keychain: Callable[[str], bool] | None = None,
) -> list[Check]:
    """One Check per ``keys[]`` entry — ``ok`` when the env var is set or the keychain has it."""
    path = settings_pinky_path or SETTINGS_PINKY_PATH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    environ = os.environ if env is None else env
    lookup = keychain or _keychain_has
    checks: list[Check] = []
    for entry in data.get("keys", []):
        name = entry.get("env")
        if not name:
            continue
        service = entry.get("service", name)
        ok = bool(environ.get(name)) or lookup(service)
        detail = (
            ""
            if ok
            else f"définir ${name}, ou l'ajouter au trousseau (service {service})"
        )
        checks.append(Check("key", name, ok, detail))
    return checks


# ── report + orchestration ──────────────────────────────────────────────────────────────────

_CATEGORY_ORDER = {"binary": 0, "ollama": 1, "key": 2}
_CATEGORY_TITLE = {"binary": "binaires", "ollama": "ollama", "key": "clés API"}


def collect_checks(
    *,
    plugins: Iterable[tuple[str, Path]] | None = None,
    settings_pinky_path: Path | None = None,
) -> list[Check]:
    """Every Check, in report order."""
    return [
        *check_binaries(plugins),
        *check_ollama(settings_pinky_path),
        *check_keys(settings_pinky_path),
    ]


def format_report(checks: list[Check]) -> str:
    """The full report as one string — grouped by category, deterministic order."""
    lines = ["pinky doctor — prérequis des plugins installés"]
    if not checks:
        lines.append("")
        lines.append("  (aucun plugin installé, ou aucun prérequis déclaré)")
        return "\n".join(lines)
    ordered = sorted(checks, key=lambda c: (_CATEGORY_ORDER.get(c.category, 9), c.name))
    current = None
    for check in ordered:
        if check.category != current:
            current = check.category
            lines.append("")
            lines.append(_CATEGORY_TITLE.get(current, current))
        mark = "✓" if check.ok else "✗"
        suffix = f" — {check.detail}" if check.detail else ""
        lines.append(f"  {mark} {check.name}{suffix}")
    missing = sum(1 for c in checks if not c.ok)
    lines.append("")
    lines.append(
        "tous les prérequis sont présents"
        if not missing
        else f"{missing} prérequis manquant{'s' if missing > 1 else ''}"
    )
    return "\n".join(lines)


def _fix_command(check: Check) -> tuple[list[str], str] | None:
    """The command that would satisfy `check`, paired with the label for the "installé" summary —
    or None when nothing here is the remedy (an API key, an un-pulled Ollama model).

    A binary's command comes from `_INSTALL_COMMAND` when it is declared there (a non-brew
    remedy — an `.lsp.json` binary via npm, so far), else the long-standing `brew install
    <formula>` default. Both package managers are handled the same way from here on: `apply_fixes`
    checks each command's own tool is on PATH, never a blanket `brew`-only gate.
    """
    if check.category == "binary":
        if check.name in _INSTALL_COMMAND:
            command = _INSTALL_COMMAND[check.name]
            return command, command[-1]
        formula = _BREW_FORMULA.get(check.name, check.name)
        return ["brew", "install", formula], formula
    if check.category == "ollama" and check.name == "endpoint":
        return ["brew", "install", "ollama"], "ollama"
    return None


def apply_fixes(
    missing: list[Check],
    *,
    runner: Callable[[list[str]], object] | None = None,
    confirm: Callable[[str], bool] | None = None,
) -> list[str]:
    """Prompt for and run the fix command for each fixable missing Check. Returns the labels run.

    No-ops for API keys and Ollama models. A check whose own package manager (`brew`, `npm`, ...)
    is absent from PATH degrades to a manual instruction — never a blanket refusal for every
    check, since a batch can mix tools.
    """
    run = runner or (
        lambda argv: subprocess.run(argv, check=False)  # nosec B603 — fixed argv
    )
    ask = confirm or (lambda prompt: input(prompt).strip().lower() == "y")
    fixable: list[tuple[Check, list[str], str]] = []
    manual: list[Check] = []
    manual_tools: set[str] = set()
    for check in missing:
        resolved = _fix_command(check)
        if resolved is None:
            continue
        command, label = resolved
        if shutil.which(command[0]):
            fixable.append((check, command, label))
        else:
            manual.append(check)
            manual_tools.add(command[0])
    if manual:
        print(
            f"`{'`, `'.join(sorted(manual_tools))}` absent du PATH — à installer manuellement :"
        )
        for check in manual:
            if check.detail:
                print(f"  {check.name} : {check.detail}")
    installed: list[str] = []
    for check, command, label in fixable:
        if ask(f"{' '.join(command)} ? [y/N] "):
            run(command)
            installed.append(label)
    return installed


def run_doctor(
    *,
    fix: bool = False,
    plugins: Iterable[tuple[str, Path]] | None = None,
    settings_pinky_path: Path | None = None,
) -> int:
    """Run every check, print the report, return the number of missing prerequisites.

    The caller decides what a non-zero count means: ``pinky doctor`` turns it into the exit code,
    ``pinky install`` ignores it (advisory).
    """
    checks = collect_checks(plugins=plugins, settings_pinky_path=settings_pinky_path)
    print(format_report(checks))
    missing = [c for c in checks if not c.ok]
    if fix and missing:
        print()
        installed = apply_fixes(missing)
        if installed:
            print(
                f"\ninstallé : {', '.join(installed)} — relance `pinky doctor` pour revérifier"
            )
    return len(missing)
