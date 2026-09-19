"""Hooks distribution — core/ is the single source. setup.py distributes, per repo:
    1. hygiene/hooks/*                 → <repo>/scripts/hooks/
    2. base + extras                → <repo>/.pre-commit-config.yaml     (generated)
    2b. hygiene/ci/ci.yml.tpl          → <repo>/.github/workflows/ci.yml    (generated, libs)
    2c. hygiene/ci/prek.yml.tpl        → <repo>/.github/workflows/prek.yml  (generated, non-libs)
    3. prek install (+ commit-msg hook type)
`--check-drift` compares each repo against the source without writing anything.
"""

import filecmp
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .agents_md import generate_agents_md, write_standalone_agents_md_recorded
from .common import (
    CORE_CI_DIR,
    CORE_HOOKS_DIR,
    CORE_PRECOMMIT_DIR,
    CORE_VENDOR_DIR,
    SCRIPT_DIR,
    WORKSPACE_ROOT,
    SuiteIdentity,
    _MarkdownParagraphs,
    engine_version,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
)
from .product_scaffold import scaffold_product


def discover_repos() -> list[Path]:
    """Every git repo under WORKSPACE_ROOT, up to one directory deep (dot-dirs excluded).

    No glob to configure: a workspace has no untracked-yet regime, every clone found is onboarded.
    One level deep covers a repo nested under an org-like folder (e.g. `bootstrap/pinky-core`)
    without recursing INTO a repo looking for nested ones.
    """
    seen: dict[str, Path] = {}
    for path in sorted(WORKSPACE_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / ".git").exists():
            seen[path.name] = path
            continue
        for nested in sorted(path.iterdir()):
            if nested.is_dir() and (nested / ".git").exists():
                seen[nested.name] = nested
    return list(seen.values())


def _report_unonboarded(repos: list[Path]) -> None:
    """Print a banner naming any discovered repo that has never been through distribute().

    ``.pre-commit-config.yaml`` absence is the single signal: distribute() writes it unconditionally
    on every repo it touches (AGENT.md is no longer part of distribution, so it can't
    serve as the signal anymore). Called unconditionally on the FULL discover_repos() result, before
    any ``--repo`` filter — so a new repo (e.g. created by other work, never explicitly onboarded)
    surfaces on the very next setup.py invocation, of any kind, instead of silently sitting
    ungoverned until someone happens to run --check-drift --all.
    """
    missing = [r.name for r in repos if not (r / ".pre-commit-config.yaml").exists()]
    if missing:
        print(
            f"\n⚠️  {len(missing)} repo(s) never onboarded (no .pre-commit-config.yaml): "
            f"{', '.join(missing)}"
        )
        print("   Onboard with: pinky repo distribute --repo <name>\n")


MYPY_PIN = "2.0.0"
MYPY_DEPS_PLACEHOLDER = "__MYPY_ADDITIONAL_DEPENDENCIES__"


def _repo_runtime_dependencies(repo: Path) -> list[str]:
    """Runtime `[project.dependencies]` declared in the TARGET repo's own pyproject.toml."""
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("dependencies", [])


def _python_version_pin(repo: Path) -> str | None:
    """Minor Python version derived from the repo's own ``requires-python`` floor.

    ``>=3.12`` → ``3.12``. Returns None when there is nothing to derive from (no pyproject.toml, or
    no ``requires-python`` key): a repo that declares no floor gets no ``.python-version`` rather
    than an invented one.

    None also means the caller writes NOTHING — it never deletes. A repo with no ``requires-python``
    to derive from declares its pin by hand in ``.python-version`` instead, and distribution leaves
    it untouched. Do not "fix" this into an overwrite: hand-declared IS the fallback.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    requires = data.get("project", {}).get("requires-python")
    if not requires:
        return None
    match = re.search(r"(\d+)\.(\d+)", requires)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def mypy_additional_dependencies(repo: Path) -> list[str]:
    """additional_dependencies for the hermetic mypy hook.

    mypy pin + the repo's own runtime deps, so mypy resolves real third-party types instead of
    falling back to `--ignore-missing-imports` Any. The two known pre-hermetic failures (pinky-core
    `pydantic.BaseModel`, pinky-provider `jinja2`/`snowflake.core`) were confirmed fixed by this set.
    No filtering: every declared dep, including `pinky-*`, is public on PyPI and pip-installable.
    """
    return [f"mypy=={MYPY_PIN}", *_repo_runtime_dependencies(repo)]


PY_LINT_FILES_PLACEHOLDER = "__PY_LINT_FILES_PATTERN__"
PY_LINT_BANDIT_ARGS_PLACEHOLDER = "__PY_LINT_BANDIT_ARGS__"
PY_LINT_INTERROGATE_ARGS_PLACEHOLDER = "__PY_LINT_INTERROGATE_ARGS__"


def _py_lint_roots(repo: Path) -> list[str]:
    """Top-level dirs/files carrying `repo`'s own Python, scoped for the src/-scoped hooks.

    `src/` layout: ``["src/"]`` — unchanged, the historical default. Flat layout (no `src/`): every
    top-level dir or loose file that owns a `.py` file, minus `scripts/hooks/` (DISTRIBUTED_PATHS,
    never authored by this repo — same exclusion `resolve_extras` already applies) and `tests/`
    (covered separately, never part of this hook set). A dir keeps its trailing `/` in the result,
    a loose file does not — the marker `_py_lint_files_pattern`/`_py_lint_bandit_args` key off.

    A loose file `X.py` is dropped when the package `X/` is ALSO discovered — mypy resolves both
    to the same module name and hard-errors ("Duplicate module named X") the moment both are on
    its file list (hit live: `pinky-bootstrap` ships both `setup/` — the real package — and the
    legacy `setup.py` pip shim). The package wins; the loose file is what a bare `pip install .`
    clone falls back to, not the thing worth type-checking twice.
    """
    if (repo / "src").is_dir():
        return ["src/"]
    hooks_dir = repo / "scripts" / "hooks"
    skip_top = {"tests", "__pycache__", "dist", "build"}
    roots: set[str] = set()
    for p in repo.rglob("*.py"):
        rel = p.relative_to(repo)
        if any(part.startswith(".") for part in rel.parts):
            continue  # .venv, .git, .mypy_cache…
        if p.is_relative_to(hooks_dir):
            continue
        if rel.parts[0] in skip_top:
            continue
        roots.add(rel.parts[0] if len(rel.parts) == 1 else f"{rel.parts[0]}/")
    dirs = {r[:-1] for r in roots if r.endswith("/")}
    roots = {r for r in roots if not (r.endswith(".py") and r[: -len(".py")] in dirs)}
    return sorted(roots)


def _py_lint_files_pattern(roots: list[str]) -> str:
    """`files:` regex selecting exactly `roots`. No roots (no lintable Python outside
    scripts/hooks/tests/) gets a pattern that never matches, so the hook stays a clean no-op
    instead of falling back to pre-commit's default-empty-pattern behaviour (matches everything)."""
    if not roots:
        return r"(?!)"
    return "|".join(
        f"^{re.escape(r)}" if r.endswith("/") else f"^{re.escape(r)}$" for r in roots
    )


def _py_lint_bandit_args(roots: list[str]) -> str:
    """bandit's `-r` targets — `pass_filenames: false`, so `files:` only gates whether the hook
    runs at all, never what bandit itself scans (see the identical reasoning on interrogate)."""
    targets = (
        ", ".join(roots) if roots else "/dev/null"
    )  # dead value — files: gate excludes the hook
    return f"[-r, {targets}, -ll, --skip, B108]"


def _py_lint_interrogate_args(roots: list[str]) -> str:
    """interrogate's positional targets — same `pass_filenames: false` reasoning as bandit."""
    targets = ", ".join(roots) if roots else "/dev/null"
    return f"[{targets}, --ignore-init-method, --ignore-magic, --ignore-module, --ignore-private]"


def resolve_extras(repo: Path) -> list[str]:
    """Pick pre-commit extras for a repo from its layout.

    - python      : repo is a Python package (has pyproject.toml). NOT keyed on src/:
                    HTML/JS repos (e.g. pinky-studio) also have a src/ but no pyproject,
                    and must NOT get mypy/bandit/darglint — they get base only.
    - snowflake   : Python repo whose pyproject declares a snowflake/snowpark dep.
    - web         : HTML/CSS/JS repo — package.json present AND no pyproject.toml (so a Python
                    package that also has a package.json stays python, never web).
    - python-lint : repo ships .py files but has neither pyproject.toml nor package.json — a
                    meta/tooling repo (the moteur itself, asset/infra scripts) with no src/
                    layout, so the full python extra's src/-scoped hooks (mypy, bandit,
                    interrogate, darglint) don't apply. ruff-check/ruff-format do (no src/
                    assumption) — without this extra, a meta/tooling repo like the moteur itself
                    could go entirely unlinted, including its own hygiene/*.py, setup/*.py,
                    hygiene/hooks/*.py.
    Repos with neither pyproject, package.json, nor any .py file get base only — fine for any
    repo (zws, secrets, forbidden-keywords, commit-msg).

    - plugin-repo : repo ships a Claude Code plugin (``.claude-plugin/`` dir present) — additive,
                    checked independently of the layout branches above (a plugin repo can also be
                    python-lint, e.g. it has a hook script outside scripts/hooks/).

    ``scripts/hooks/`` is excluded from the ``.py`` scan on purpose: it is 100% framework-owned
    (``DISTRIBUTED_PATHS``), never authored by a repo. Without the exclusion this function is not
    stable across a distribute-then-check cycle — ``distribute()`` copies socle scripts there
    (``check_zws.py``, ``check_forbidden_keywords.py``, always-on ``render_docs.py`` /
    ``generate_ci_badges.py``), which are themselves ``.py`` files; the NEXT call would then see
    them and flip a bare repo to ``python-lint``, a self-inflicted drift the repo never earned
    (on a fresh ``--new-repo``, ``check_drift`` would report `check_weak_assertions.py` missing,
    right after `distribute()` had correctly decided the repo needed no python extra at all).
    """
    extras: list[str] = []
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        extras.append("python")
        text = pyproject.read_text(encoding="utf-8").lower()
        if "snowflake" in text or "snowpark" in text:
            extras.append("snowflake")
    elif (repo / "package.json").exists():
        extras.append("web")
    elif any(
        p
        for p in repo.rglob("*.py")
        if not p.is_relative_to(repo / "scripts" / "hooks")
    ):
        extras.append("python-lint")
    if (repo / ".claude-plugin").is_dir():
        extras.append("plugin-repo")
    return extras


def build_precommit_config(repo: Path, extras: list[str]) -> str:
    """Assemble .pre-commit-config.yaml = base + selected extras (text concat).

    ``repo`` is the TARGET repo (not the source workspace) — needed to auto-derive the mypy hook's
    ``additional_dependencies`` from that repo's own pyproject.toml when the python
    extra is active; a no-op placeholder substitution otherwise.
    """
    parts = [
        (CORE_PRECOMMIT_DIR / "base.yaml").read_text(encoding="utf-8").rstrip("\n")
    ]
    for extra in extras:
        fragment = CORE_PRECOMMIT_DIR / "extras" / f"{extra}.yaml"
        if fragment.exists():
            parts.append(fragment.read_text(encoding="utf-8").rstrip("\n"))
    text = "\n\n".join(parts) + "\n"
    if MYPY_DEPS_PLACEHOLDER in text:
        deps_yaml = (
            "[" + ", ".join(f'"{d}"' for d in mypy_additional_dependencies(repo)) + "]"
        )
        text = text.replace(MYPY_DEPS_PLACEHOLDER, deps_yaml)
    if PY_LINT_FILES_PLACEHOLDER in text:
        roots = _py_lint_roots(repo)
        text = text.replace(PY_LINT_FILES_PLACEHOLDER, _py_lint_files_pattern(roots))
        text = text.replace(
            PY_LINT_BANDIT_ARGS_PLACEHOLDER, _py_lint_bandit_args(roots)
        )
        text = text.replace(
            PY_LINT_INTERROGATE_ARGS_PLACEHOLDER, _py_lint_interrogate_args(roots)
        )
    return text


CI_TPL_PATH = CORE_CI_DIR / "ci.yml.tpl"
CI_WINDOWS_FRAGMENT_PATH = CORE_CI_DIR / "windows-pilot.yml.tpl"
CI_WORKER_FRAGMENT_PATH = CORE_CI_DIR / "worker-python.yml.tpl"
CI_INSTALL_WALKTHROUGH_PATH = CORE_CI_DIR / "windows-install-walkthrough.yml.tpl"
# La version que `prek.yml.tpl` porte en dur, remplacée par le pin du repo quand il en a un.
PREK_DEFAULT_PYTHON = "3.12"
# Server-side hook suite for the repos ci.yml.tpl does not cover (see render_prek_yml).
PREK_TPL_PATH = CORE_CI_DIR / "prek.yml.tpl"
# Anchor spliced before by render_prek_yml when the repo has the `plugin-repo` extra — the exact
# text as it appears in prek.yml.tpl, so a .replace() on it is a no-op for every other repo.
PREK_RUN_HOOKS_ANCHOR = (
    "      - name: Run pre-commit hooks\n        uses: j178/prek-action@v2\n"
)
PREK_CLAUDE_CLI_STEP = (
    "      - name: Set up Node.js\n"
    "        uses: actions/setup-node@v4\n"
    "        with:\n"
    '          node-version: "22"\n'
    "\n"
    "      - name: Install claude CLI\n"
    "        run: npm install -g @anthropic-ai/claude-code\n"
    "\n"
)
VENDOR_MAP = {
    "policy_lib.py": [
        "plugins/pc-core/hooks/policy_lib.py",
        "plugins/pc-git/hooks/pc_git_policy_lib.py",
    ],
    "secret_patterns.py": [
        "plugins/pc-core/hooks/secret_patterns.py",
        "plugins/pc-kanban/hooks/pc_kanban_secret_patterns.py",
    ],
    "plugin_scope_lib.py": [
        "plugins/pc-autodiscovery/hooks/plugin_scope_lib.py",
        "plugins/pc-kanban/skills/chantier/scripts/pc_kanban_plugin_scope_lib.py",
        "plugins/pc-kanban/skills/spawn-workers/scripts/pc_kanban_spawn_plugin_scope_lib.py",
    ],
    "pending_user_action.py": [
        "plugins/pc-autodiscovery/hooks/pending_user_action.py",
        "plugins/pc-kanban/skills/chantier/scripts/pc_kanban_pending_user_action.py",
    ],
}
VENDOR_MANIFEST_NAME = ".vendor-manifest.json"

CI_PYTHON_VERSION_PLACEHOLDER = "__PYTHON_VERSION__"
CI_INSTALL_CMD_PLACEHOLDER = "__INSTALL_CMD__"
CI_TESTS_CMD_PLACEHOLDER = "__TESTS_CMD__"
CI_D1_DATABASE_PLACEHOLDER = "__D1_DATABASE__"

# `on.push.paths` s'applique au workflow ENTIER : sans ces chemins, un push qui ne touche que le
# Worker ne lance rien, donc `worker-deploy` non plus, et rien ne devient rouge.
CI_PUSH_PATHS_ANCHOR = '      - ".github/**"\n'
CI_WORKER_PUSH_PATHS = ("src/**", "wrangler.jsonc", "migrations/**")

CI_DEFAULT_INSTALL_CMD = "uv sync --locked --no-sources --group dev"

CI_DEFAULT_TESTS_CMD = "pytest"
CI_TESTS_OVERRIDES = {
    "pluto-poc-pilot": "bash scripts/hooks/run-tests",
}
CI_INSTALL_OVERRIDES = {
    "pinky-core": (
        "uv sync --locked --extra validate --extra address --extra schedule --extra xml "
        "--extra lint --group dev"
    ),
    "pinky-provider": "uv sync --locked --no-sources --prerelease allow --group dev",
}

CI_NO_LOCK_REPOS: frozenset[str] = frozenset(
    {"pinky-ai", "pinky-connect", "pinky-provider", "pinky-snowpark", "pinky-streamlit"}
)

EXCLUDE_NEWER_SPAN = "3 days"
# `required-version` : sans ça, un uv < 0.9.17 ignore la durée relative en silence. `>=0.9.17` est
# la 1re version qui l'accepte.
UV_REQUIRED_VERSION = ">=0.9.17"
_EXCLUDE_NEWER_BLOCK_RE = re.compile(
    r'(?m)^(?:#[^\n]*\r?\n)*exclude-newer[ \t]*=[ \t]*"[^"]*"[ \t]*\r?$'
)
_REQUIRED_VERSION_RE = re.compile(
    r'(?m)^required-version[ \t]*=[ \t]*"[^"]*"[ \t]*\r?$'
)
_TOOL_UV_HEADER_RE = re.compile(r"(?m)^\[tool\.uv\][ \t]*\r?$")
_ANY_TABLE_HEADER_RE = re.compile(r"(?m)^\[")
_span_days = EXCLUDE_NEWER_SPAN.split()[0]
COOLDOWN_COMMENT = (
    f"# Fenêtre de cooldown (chantier 0024) : `uv lock` ignore tout paquet publié depuis moins\n"
    f"# de {_span_days} jours — protège la résolution contre une dépendance fraîchement compromise\n"
    f"# republiée sur PyPI. Durée relative : uv la résout au lock, `grep exclude-newer-span\n"
    f"# uv.lock` dit la fenêtre appliquée. Posée par `pinky repo distribute`, jamais éditée à la main.\n"
)


def _tool_uv_body(text: str) -> tuple[int, int] | None:
    """`(start, end)` char offsets of the `[tool.uv]` table body — from just after its header
    line to the next `^[` table header (or EOF) — or None when there is no `[tool.uv]` table.
    Anchored to a bare `[tool.uv]` line, so `[tool.uv.sources]` / `[tool.uv.pip]` are not it."""
    header = _TOOL_UV_HEADER_RE.search(text)
    if header is None:
        return None
    start = min(header.end() + 1, len(text))  # skip the newline after the header
    nxt = _ANY_TABLE_HEADER_RE.search(text, start)
    return (start, nxt.start() if nxt else len(text))


def render_pyproject_with_cooldown(repo: Path) -> str | None:
    """The repo's `pyproject.toml` with `[tool.uv] exclude-newer = "3 days"` (a relative cooldown,
    uv >= 0.9.17) and `required-version = ">=0.9.17"`, or None when there is no `pyproject.toml`
    or the file would not change.

    Surgical string edits scoped to the `[tool.uv]` table body — its other keys and the rest of
    the file are preserved; the file is never round-tripped through a TOML writer (which would
    drop comments and formatting). ``required-version`` is only inserted when absent from that
    table: a repo that pins a newer floor by hand keeps it.
    """
    pyproject_path = repo / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    text = pyproject_path.read_text(encoding="utf-8")

    exclude_block = COOLDOWN_COMMENT + f'exclude-newer = "{EXCLUDE_NEWER_SPAN}"'
    span = _tool_uv_body(text)
    if span is None:
        sep = "" if text.endswith("\n") else "\n"
        body = f'required-version = "{UV_REQUIRED_VERSION}"\n' + exclude_block + "\n"
        return text + f"{sep}\n[tool.uv]\n{body}"

    start, end = span
    body = text[start:end]
    if _EXCLUDE_NEWER_BLOCK_RE.search(body):
        body = _EXCLUDE_NEWER_BLOCK_RE.sub(lambda _: exclude_block, body, count=1)
    else:
        body = exclude_block + "\n" + body
    if not _REQUIRED_VERSION_RE.search(body):
        body = f'required-version = "{UV_REQUIRED_VERSION}"\n' + body

    new_text = text[:start] + body + text[end:]
    return new_text if new_text != text else None


CI_WINDOWS_PILOT: frozenset[str] = frozenset({"pinky-core", "pinky-bootstrap"})


def _d1_database_name(repo: Path) -> str | None:
    """Nom de la base D1 déclarée dans le `wrangler.jsonc` du repo, sinon None.

    Sert de **détecteur** de repo « Worker Python » : pas de table de surcharge à tenir à jour, la
    présence d'un binding D1 est le signal. Les POC suivants (forms, school, association) hériteront
    du job sans qu'on touche à ce fichier.

    Lu à la regex et non par `json.loads` : `wrangler.jsonc` accepte les commentaires, et il en porte
    (la justification du double embarquement d'`index.html`, entre autres) — un parseur JSON strict
    échouerait sur un fichier pourtant valide pour Cloudflare.

    Args:
        repo: Racine du repo à inspecter.

    Returns:
        Le nom de la base, ou None si le repo n'a pas de `wrangler.jsonc` ou pas de binding D1.
    """
    config = repo / "wrangler.jsonc"
    if not config.is_file():
        return None
    match = re.search(
        r'"database_name"\s*:\s*"([^"]+)"', config.read_text(encoding="utf-8")
    )
    return match.group(1) if match else None


def render_ci_yml(repo: Path) -> str | None:
    """Render .github/workflows/ci.yml for ``repo`` from hygiene/ci/ci.yml.tpl, or None.

    None when the repo has no derivable Python version pin (see ``_python_version_pin`` — no
    ``pyproject.toml`` or no ``requires-python``): same gate as the ``python`` pre-commit extra,
    so a non-lib repo (or the moteur itself) never gets a ci.yml it has no pytest target for.
    """
    python_version = _python_version_pin(repo)
    if python_version is None:
        return None
    install_cmd = CI_INSTALL_OVERRIDES.get(repo.name, CI_DEFAULT_INSTALL_CMD)
    if repo.name in CI_NO_LOCK_REPOS:
        install_cmd = install_cmd.replace("--locked ", "")
    tests_cmd = CI_TESTS_OVERRIDES.get(repo.name, CI_DEFAULT_TESTS_CMD)
    text = CI_TPL_PATH.read_text(encoding="utf-8")
    text = text.replace(CI_PYTHON_VERSION_PLACEHOLDER, python_version)
    text = text.replace(CI_INSTALL_CMD_PLACEHOLDER, install_cmd)
    text = text.replace(CI_TESTS_CMD_PLACEHOLDER, tests_cmd)
    if repo.name in CI_WINDOWS_PILOT:
        fragment = (
            CI_WINDOWS_FRAGMENT_PATH.read_text(encoding="utf-8")
            .replace(CI_PYTHON_VERSION_PLACEHOLDER, python_version)
            .replace(CI_INSTALL_CMD_PLACEHOLDER, install_cmd)
            .replace(CI_TESTS_CMD_PLACEHOLDER, tests_cmd)
        )
        text = text.rstrip("\n") + "\n" + fragment
    if repo.resolve() == SCRIPT_DIR.resolve():
        text = (
            text.rstrip("\n")
            + "\n"
            + CI_INSTALL_WALKTHROUGH_PATH.read_text(encoding="utf-8")
        )
    d1_database = _d1_database_name(repo)
    if d1_database is not None:
        worker_paths = "".join(f'      - "{path}"\n' for path in CI_WORKER_PUSH_PATHS)
        text = text.replace(
            CI_PUSH_PATHS_ANCHOR,
            CI_PUSH_PATHS_ANCHOR
            + "      # `worker-deploy` en a besoin : `paths` filtre le workflow entier, pas seulement\n"
            + "      # le job de tests.\n"
            + worker_paths,
            1,
        )
        fragment = (
            CI_WORKER_FRAGMENT_PATH.read_text(encoding="utf-8")
            .replace(CI_PYTHON_VERSION_PLACEHOLDER, python_version)
            .replace(CI_D1_DATABASE_PLACEHOLDER, d1_database)
        )
        text = text.rstrip("\n") + "\n" + fragment
    return text


def render_prek_yml(repo: Path) -> str:
    """Render .github/workflows/prek.yml for ``repo`` — EVERY repo gets one, whether or not it
    also gets a ci.yml.

    ``prek.yml`` carries two jobs, and only the first — the hook suite — would duplicate what a
    lib's ci.yml already runs if both ran it. The second, ``pr-required-on-main``, is the ONLY
    server-side guard against a direct push to ``main`` — GitHub branch protection is a paid
    feature on private repos, and neither org has it. Skipping prek.yml for any repo would
    silently lose that guard.

    The split is by subject rather than by file: ``prek.yml`` is hygiene + branch convention and
    goes everywhere; ``ci.yml`` is build + tests and goes where there is a package to test — and it
    does not run the hooks. One source for each job, no duplication, and nothing to delete from a
    consumer repo.

    Args:
        repo: Repo root to render for.

    Returns:
        The workflow text. Never None — the hook suite and the branch guard are universal.
    """
    text = PREK_TPL_PATH.read_text(encoding="utf-8")
    # The template pins 3.12 in its own text (it was only ever rendered for repos with no pin to
    # read). Now that libs receive it too, run their hooks on the version they declare — mypy and
    # ruff do not behave identically across minor versions.
    python_version = _python_version_pin(repo)
    if python_version is not None:
        text = text.replace(PREK_DEFAULT_PYTHON, python_version)
    if "plugin-repo" in resolve_extras(repo):
        text = text.replace(
            PREK_RUN_HOOKS_ANCHOR,
            PREK_CLAUDE_CLI_STEP + PREK_RUN_HOOKS_ANCHOR,
        )
    return text


def _referenced_hook_scripts(cfg_text: str) -> set[str]:
    """Script filenames an assembled .pre-commit-config.yaml actually invokes (`entry: ... scripts/hooks/<name>`)."""
    return set(re.findall(r"scripts/hooks/(\S+)", cfg_text))


def _hook_files(repo: Path) -> list[Path]:
    """Hook files to distribute to THIS repo (skip __pycache__ and non-files).

    Scoped to what the repo's own assembled `.pre-commit-config.yaml` actually references —
    derived from ``build_precommit_config``, the same source of truth ``resolve_extras`` already
    drives, instead of a second parallel classification. A repo without the ``web`` extra never gets
    the JS/HTML scripts (they'd sit dead, unreferenced by its config). ``generate_ci_badges.py`` has
    no pre-commit id (CI helper invoked from a workflow, not a hook `entry:`) and is always
    distributed — same for ``render_docs.py`` (imported by ``generate-docs``, not textually
    referenced in the assembled YAML, so the regex scan above can't find it).
    """
    files = [f for f in sorted(CORE_HOOKS_DIR.iterdir()) if f.is_file()]
    referenced = _referenced_hook_scripts(
        build_precommit_config(repo, resolve_extras(repo))
    )
    always_on = {"generate_ci_badges.py", "render_docs.py", "tool_directives.py"}
    return [f for f in files if f.name in referenced or f.name in always_on]


_EMPTY_IDENTITY = SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="",
    pitch_heading="",
    pitch_paragraphs=_MarkdownParagraphs(),
    pitch_pills=_MarkdownParagraphs(),
)


def _group_docs_identity(repo: Path, workspace_root: Path) -> SuiteIdentity:
    """The docs identity ``repo``'s group declares (``<workspace_root>/<group>/docs_identity.json``)
    — the empty identity (no pitch/org block rendered, `SuiteIdentity._REQUIRED` is the only field
    that gates anything) when the repo sits directly at workspace depth 1 (no group), or its group
    has none configured.
    """
    try:
        parts = repo.resolve().relative_to(workspace_root.resolve()).parts
    except ValueError:
        return _EMPTY_IDENTITY
    if len(parts) < 2:
        return _EMPTY_IDENTITY
    path = workspace_root / parts[0] / "docs_identity.json"
    if not path.is_file():
        return _EMPTY_IDENTITY
    return SuiteIdentity.from_dict(json.loads(path.read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def engine_commit() -> str | None:
    """The pinky-bootstrap commit being distributed, suffixed ``-dirty`` when its tree has changes.

    Computed once per process: a distribution run commits into pinky-bootstrap itself on the way,
    and every repo of that run must still record the commit it started from.

    Returns:
        The full commit sha, or None outside a git checkout (an installed wheel).
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(SCRIPT_DIR),
            "describe",
            "--always",
            "--dirty",
            "--abbrev=40",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def render_docs_identity(identity: SuiteIdentity) -> str:
    """The ``scripts/hooks/docs_identity.json`` text distributed into one repo.

    Wraps ``SuiteIdentity.to_json()`` rather than extending it: ``to_json`` lives in
    ``hygiene/hooks/render_docs.py``, the generic engine shipped into every repo, which must stay
    free of routing concerns. ``engine_version`` is written HERE, by the distributor, and read back
    by ``check_drift``. ``from_dict`` reads ``_FIELDS`` only, so the extra keys are invisible to the
    commit-time hook that consumes this same file. ``engine_commit`` pins the exact source commit
    distributed — ``engine_version`` alone does not move between releases.
    """
    payload: dict = {"engine_version": engine_version()}
    commit = engine_commit()
    if commit:
        payload["engine_commit"] = commit
    payload.update(json.loads(identity.to_json()))
    return json.dumps(payload, indent=2) + "\n"


def _read_docs_identity_key(repo: Path, key: str) -> str | None:
    """One string key from ``repo``'s distributed docs_identity.json, or None when unknown.

    Unknown covers three real cases, all of which must degrade rather than raise: a repo never
    distributed (no file), one distributed before the key existed (true of the whole parc for a
    newly added key like ``engine_version``), and a hand-edited or half-written file.
    ``--check-drift``
    walks every repo ``discover_repos()`` finds, so one unreadable repo must not abort the scan.
    """
    path = repo / "scripts" / "hooks" / "docs_identity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def repo_engine_version(repo: Path) -> str | None:
    """The moteur version ``repo`` was last distributed with, or None when unknown."""
    return _read_docs_identity_key(repo, "engine_version")


def distribute_vendor(repo: Path, *, dry_run: bool) -> None:
    """Copy each vendored source file to its targets in `repo`, write the checksum manifest.

    Silent no-op for a repo with none of VENDOR_MAP's targets (every repo but
    pinky-agentic-plugins today) — gated by target-directory existence, not a repo-name literal,
    so a future repo gains vendoring by having the right plugin directories, not an added carve-out.
    """
    tag = "[dry-run] " if dry_run else ""
    manifest: dict[str, str] = {}
    for source_name, targets in VENDOR_MAP.items():
        source = CORE_VENDOR_DIR / source_name
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        for target in targets:
            dst = repo / target
            if not dst.parent.exists():
                continue
            manifest[target] = digest
            print(f"  {tag}vendor  {target}")
            if not dry_run:
                dst.write_bytes(content)
    if not manifest:
        return
    if not dry_run:
        manifest_path = repo / VENDOR_MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def distribute(
    repo: Path,
    *,
    dry_run: bool,
    identity: SuiteIdentity,
) -> None:
    """Distribute hooks + config into one repo.

    Copied scripts are scoped to what THIS repo's extras actually reference.

    Does not touch AGENT.md: its only generated content was the commit-scopes marker
    block, and the scope concept was dropped from the commit convention entirely — a per-repo
    scope vocabulary (scopes.yaml + a scopes-local.txt in every repo + this injection step) cost
    more mechanism than the git-log grep value it bought. AGENT.md is 100% hand-authored again.
    """
    tag = "[dry-run] " if dry_run else ""
    extras = resolve_extras(repo)
    print(f"\n→ {repo.name}  (extras: {', '.join(extras) or 'none'})")

    # 1. hooks
    dst_hooks = repo / "scripts" / "hooks"
    for src in _hook_files(repo):
        dst = dst_hooks / src.name
        print(f"  {tag}hook  scripts/hooks/{src.name}")
        if not dry_run:
            dst_hooks.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if src.name in ("commit-msg", "generate-docs"):
                dst.chmod(0o755)

    print(f"  {tag}hook  scripts/hooks/docs_identity.json")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        (dst_hooks / "docs_identity.json").write_text(
            render_docs_identity(identity), encoding="utf-8"
        )

    print(f"  {tag}hook  scripts/hooks/badges.toml")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORE_HOOKS_DIR / "badges.toml", dst_hooks / "badges.toml")

    print(f"  {tag}hook  scripts/hooks/ruff.toml")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORE_PRECOMMIT_DIR / "hooks-ruff.toml", dst_hooks / "ruff.toml")

    print(f"  {tag}gitleaks .gitleaks.toml")
    if not dry_run:
        shutil.copy2(CORE_PRECOMMIT_DIR / "gitleaks.toml", repo / ".gitleaks.toml")

    print(f"  {tag}gitattributes .gitattributes")
    if not dry_run:
        shutil.copy2(CORE_PRECOMMIT_DIR / "gitattributes", repo / ".gitattributes")

    python_pin = _python_version_pin(repo)
    if python_pin:
        pin_path = repo / ".python-version"
        current = (
            pin_path.read_text(encoding="utf-8").strip() if pin_path.exists() else None
        )
        if current != python_pin:
            print(f"  {tag}python  .python-version ({python_pin})")
            if not dry_run:
                pin_path.write_text(f"{python_pin}\n", encoding="utf-8")

    settings_pinky_path = repo / ".claude" / "settings.pinky.json"
    if not settings_pinky_path.exists():
        print(f"  {tag}scaffold .claude/settings.pinky.json (branch_workflow: null)")
        if not dry_run:
            settings_pinky_path.parent.mkdir(parents=True, exist_ok=True)
            settings_pinky_path.write_text(
                '{"branch_workflow": null}\n', encoding="utf-8"
            )

    distribute_vendor(repo, dry_run=dry_run)

    print(f"  {tag}config  .pre-commit-config.yaml")
    if not dry_run:
        (repo / ".pre-commit-config.yaml").write_text(
            build_precommit_config(repo, extras), encoding="utf-8"
        )

    ci_yml = render_ci_yml(repo)
    if ci_yml is not None:
        ci_path = repo / ".github" / "workflows" / "ci.yml"
        current_ci = ci_path.read_text(encoding="utf-8") if ci_path.exists() else None
        if current_ci != ci_yml:
            print(f"  {tag}ci      .github/workflows/ci.yml")
            if not dry_run:
                ci_path.parent.mkdir(parents=True, exist_ok=True)
                ci_path.write_text(ci_yml, encoding="utf-8")

    new_pyproject = render_pyproject_with_cooldown(repo)
    if new_pyproject is not None:
        print(f"  {tag}uv      pyproject.toml (cooldown + required-version)")
        if not dry_run:
            (repo / "pyproject.toml").write_text(new_pyproject, encoding="utf-8")

    prek_yml = render_prek_yml(repo)
    if prek_yml is not None:
        prek_path = repo / ".github" / "workflows" / "prek.yml"
        current_prek = (
            prek_path.read_text(encoding="utf-8") if prek_path.exists() else None
        )
        if current_prek != prek_yml:
            print(f"  {tag}ci      .github/workflows/prek.yml")
            if not dry_run:
                prek_path.parent.mkdir(parents=True, exist_ok=True)
                prek_path.write_text(prek_yml, encoding="utf-8")

    # 3. secrets baseline — detect-secrets hook needs .secrets.baseline to exist
    if not dry_run:
        _ensure_secrets_baseline(repo, tag)

    # 3b. darglint config — same shape: a hook that needs a config file gets one, rather than
    # falling back to a tool default nobody chose (see _ensure_darglint_config for the incident).
    if not dry_run:
        _write_darglint_config(repo, extras, tag)

    # 4. prek install (hooks runner — drop-in over pre-commit, reads the same config)
    print(f"  {tag}install prek (+ commit-msg)")
    if not dry_run:
        _prek_install(repo)

    readme_path = repo / "README.md"
    if readme_path.exists():
        injected = inject_readme_sections_local(
            readme_path.read_text(encoding="utf-8"),
            repo,
            identity,
            allow_first_run=True,
        )
        if injected is not None:
            print(f"  {tag}readme  README.md (badges/tagline/why-pinky/license)")
            if not dry_run:
                readme_path.write_text(injected, encoding="utf-8")

    if has_generated_index(repo):
        index_path = repo / "docs" / "index.md"
        generated = render_index_home(repo, identity)
        current = (
            index_path.read_text(encoding="utf-8") if index_path.exists() else None
        )
        if generated != current:
            print(f"  {tag}index   docs/index.md (homepage)")
            if not dry_run:
                index_path.write_text(generated, encoding="utf-8")


# CLI tools found missing during a run (prek, detect-secrets). Non-fatal per-repo — the run
# finishes distributing — but aggregated into a non-zero exit at the end of run_distribution, so a
# missing tool never hides behind a 'Done.'. Reset at the start of each run.
_MISSING_TOOLS: set[str] = set()


_DARGLINT_INI = """[darglint]
docstring_style = google
strictness = long
ignore = DAR402
ignore_raise = exc
"""


def _write_darglint_config(repo: Path, extras: list[str], tag: str = "") -> None:
    """Write `.darglint` on repos where the darglint hook runs — CONVERGING, not create-if-absent.

    Create-if-absent would assume a repo declaring its own strictness had DECIDED — checked, and it
    had not: the existing `.darglint` files were all created as side effects of unrelated commits (a
    model-id typo fix, a query module, a connector migration), not a position anyone held.
    Guarding a create-if-absent file would have preserved a phantom decision.

    So this file is socle, like `.pre-commit-config.yaml`: distributed and overwritten — divergence
    stops being silent.

    **A repo cannot hold a local exception, and there is no per-repo escape hatch.** A setting a
    repo genuinely needs therefore has to go into `_DARGLINT_INI` itself — workable precisely
    because the settings at stake (like `ignore_raise = exc`, added after a converging repo
    produced a false `DAR401`) suppress tool limitations, inert everywhere else; a setting that
    encoded a real per-repo *policy* would need a mechanism that does not exist yet, and would be
    the moment to build one rather than to widen this constant.

    Note it is NOT drift-checked: `check_drift` compares hook scripts, `.pre-commit-config.yaml`,
    `ci.yml` and `prek.yml` — not this file. A stale `.darglint` is invisible until the next
    distribution rewrites it.
    """
    if "python" not in extras:  # darglint ships with the python extra only
        return
    cfg = repo / ".darglint"
    if cfg.exists() and cfg.read_text(encoding="utf-8") == _DARGLINT_INI:
        return
    print(f"  {tag}darglint .darglint (strictness = long)")
    cfg.write_text(_DARGLINT_INI, encoding="utf-8")


def _ensure_secrets_baseline(repo: Path, tag: str = "") -> None:
    """Create .secrets.baseline if missing (the detect-secrets hook requires it).

    Repo root, not .cache/: it's a versioned security artifact (accepted-findings
    triage state), not disposable cache — keeping it out of .cache/ means that directory stays
    100% safe to delete, no gitignore exception needed.
    """
    baseline = repo / ".secrets.baseline"
    if baseline.exists():
        return
    if shutil.which("detect-secrets") is None:
        print("     ⚠️  detect-secrets not on PATH — .secrets.baseline not created")
        _MISSING_TOOLS.add("detect-secrets")
        return
    print(f"  {tag}secrets .secrets.baseline (generated)")
    result = subprocess.run(
        ["detect-secrets", "scan"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode == 0:
        baseline.write_text(result.stdout, encoding="utf-8")


DISTRIBUTED_PATHS = (
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    ".gitattributes",
    ".darglint",
    "scripts/hooks",
    ".github/workflows/ci.yml",
    ".github/workflows/prek.yml",
)

SHARED_DISTRIBUTED_PATHS = (
    "README.md",
    "docs/index.md",
    "pyproject.toml",
    ".python-version",
    ".claude/settings.pinky.json",
)


def dirty_paths(repo: Path) -> list[str]:
    """Paths git reports as modified, staged or untracked in ``repo`` right now."""
    listed = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [entry[3:] for entry in listed.split("\0") if len(entry) > 3]


COMMIT_MESSAGE = "🔧 chore: adopt pinky-bootstrap centralized hooks distribution"


def _vendored_paths(repo: Path) -> list[str]:
    """The vendor manifest and every copy it lists — distributed files, committed with the rest."""
    manifest = repo / VENDOR_MANIFEST_NAME
    if not manifest.exists():
        return []
    return [VENDOR_MANIFEST_NAME, *json.loads(manifest.read_text(encoding="utf-8"))]


def _same_path(a: str, b: str) -> bool:
    """Two PATH entries naming the same directory — case- and separator-insensitive on Windows."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
        os.path.normpath(b)
    )


def _hook_env() -> dict[str, str]:
    """This process's environment minus the virtualenv ``uv run`` activated for pinky itself.

    A distribution commit runs the target repo's hooks: inheriting pinky-bootstrap's venv on PATH
    hands ``run-tests`` an interpreter with pytest but none of the target's own dependencies.
    """
    env = dict(os.environ)
    venv = env.pop("VIRTUAL_ENV", None)
    if venv:
        bin_dir = str(Path(venv) / ("Scripts" if sys.platform == "win32" else "bin"))
        env["PATH"] = os.pathsep.join(
            entry
            for entry in env.get("PATH", "").split(os.pathsep)
            if not _same_path(entry, bin_dir)
        )
    return env


def commit_distribution(repo: Path, dirty_before: list[str] | None = None) -> str:
    """Stage every file the distribution wrote and commit them. Returns a status string.

    ``dirty_before`` lists the paths already modified before the run: a shared file the run
    rewrote (README, pyproject…) is staged only if it was clean then, so an edit in progress is
    never swept into a distribution commit.

    Hooks run normally (no --no-verify). A repo with a pre-existing hook wall that
    blocks the commit is reported; its changes stay staged for manual resolution.
    """
    # Only stage paths that exist — `git add` aborts entirely (staging nothing) if any
    # pathspec matches no file.
    shared = [
        p
        for p in SHARED_DISTRIBUTED_PATHS
        if dirty_before is not None and p not in dirty_before
    ]
    paths = [
        p
        for p in (*DISTRIBUTED_PATHS, *_vendored_paths(repo), *shared)
        if (repo / p).exists()
    ]
    if not paths:
        return "no distributed files"
    subprocess.run(
        ["git", "add", "--", *paths],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repo, capture_output=True
    )
    if staged.returncode == 0:
        return "up-to-date (nothing to commit)"

    result = subprocess.run(
        ["git", "commit", "-m", COMMIT_MESSAGE],
        cwd=repo,
        env=_hook_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode == 0:
        return "committed"
    lines = (result.stdout + result.stderr).splitlines()
    failed = [ln.strip() for ln in lines if "Failed" in ln or "error" in ln.lower()]
    hint = failed[0] if failed else "see hook output"
    return f"BLOCKED — staged, not committed ({hint})"


def _prek_install(repo: Path) -> None:
    # prek is the hooks runner: a single Rust binary, no Python toolchain needed to run itself —
    # the whole point of the migration. `--hook-type {pre-commit,commit-msg}` are git hook-type
    # names, unchanged; only the invoked binary moved from `pre-commit` to `prek`.
    if shutil.which("prek") is None:
        print(
            "     ⚠️  prek not on PATH — skipped (install prek: brew install prek / cargo install prek)"
        )
        _MISSING_TOOLS.add("prek")
        return
    for hook_type in ("pre-commit", "commit-msg"):
        subprocess.run(
            ["prek", "install", "--hook-type", hook_type],
            cwd=repo,
            check=False,
            capture_output=True,
        )


_CACHE_CONVENTION = (
    (("tool", "ruff"), "cache-dir", ".cache/ruff"),
    (("tool", "mypy"), "cache_dir", ".cache/mypy"),
    (("tool", "pytest", "ini_options"), "cache_dir", ".cache/pytest"),
)


def _cache_convention_issues(repo: Path) -> list[str]:
    """`.cache/` convention gaps in `repo`'s own `pyproject.toml` — [] if the file is absent,
    unparsable, or every tool section already present carries the key."""
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return []
    issues: list[str] = []
    for section_path, key, expected in _CACHE_CONVENTION:
        section: object = data
        for part in section_path:
            section = section.get(part) if isinstance(section, dict) else None
        if section is None:
            continue  # tool not configured in this repo — not this check's business
        if not isinstance(section, dict) or section.get(key) != expected:
            dotted = ".".join(section_path)
            issues.append(
                f"pyproject.toml [{dotted}] missing/wrong {key} = {expected!r}"
            )
    return issues


def check_drift(
    repos: list[Path],
    quiet: bool = False,
    extras_fatal: bool = True,
) -> int:
    """Compare each repo against the workspace source; return divergence count.

    The expected hook-script set is per-repo (via `_hook_files`) — scoped to what that
    repo's own extras actually reference, not the full `hygiene/hooks/` directory.

    ``quiet`` returns the count without the report, for ``warn_on_drift``'s one-line advisory.

    ``extras_fatal=False`` still REPORTS orphaned scripts but leaves them out of the count. The
    post-distribution gate needs this: ``distribute()`` writes and never deletes, so it cannot clear
    an orphan — counting them there would make ``--repo <name>`` exit non-zero forever on a repo
    carrying one, a control that fails on the nominal path and that the tool it gates cannot satisfy.
    """
    say = (lambda *_a, **_k: None) if quiet else print
    say("\nDrift check — repo vs pinky-bootstrap source")
    say("=" * 52)
    total = 0
    advisory = 0
    current_version = engine_version()
    version_lag: list[tuple[str, str]] = []
    cache_gaps: list[tuple[str, list[str]]] = []
    for repo in repos:
        issues: list[str] = []
        uncounted = 0
        dst_hooks = repo / "scripts" / "hooks"
        expected = _hook_files(repo)
        for src in expected:
            dst = dst_hooks / src.name
            if not dst.exists():
                issues.append(f"missing hook scripts/hooks/{src.name}")
            elif not filecmp.cmp(src, dst, shallow=False):
                issues.append(f"differs   scripts/hooks/{src.name}")

        framework_owned = {f.name for f in CORE_HOOKS_DIR.iterdir() if f.is_file()}
        rendered = {"docs_identity.json", "badges.toml"}
        keep = {src.name for src in expected} | rendered
        if dst_hooks.is_dir():
            for stray in sorted(dst_hooks.iterdir()):
                if (
                    stray.is_file()
                    and stray.name in framework_owned
                    and stray.name not in keep
                ):
                    issues.append(f"extra hook scripts/hooks/{stray.name}")
                    if not extras_fatal:
                        uncounted += 1

        cfg = repo / ".pre-commit-config.yaml"
        expected_cfg = build_precommit_config(repo, resolve_extras(repo))
        if not cfg.exists():
            issues.append("missing .pre-commit-config.yaml")
        elif cfg.read_text(encoding="utf-8") != expected_cfg:
            issues.append("differs .pre-commit-config.yaml")

        expected_ci = render_ci_yml(repo)
        if expected_ci is not None:
            ci_path = repo / ".github" / "workflows" / "ci.yml"
            if not ci_path.exists():
                issues.append("missing .github/workflows/ci.yml")
            elif ci_path.read_text(encoding="utf-8") != expected_ci:
                issues.append("differs .github/workflows/ci.yml")

        expected_prek = render_prek_yml(repo)
        if expected_prek is not None:
            prek_path = repo / ".github" / "workflows" / "prek.yml"
            if not prek_path.exists():
                issues.append("missing .github/workflows/prek.yml")
            elif prek_path.read_text(encoding="utf-8") != expected_prek:
                issues.append("differs .github/workflows/prek.yml")

        recorded_version = repo_engine_version(repo)
        if recorded_version is not None and recorded_version != current_version:
            version_lag.append((repo.name, recorded_version))

        gaps = _cache_convention_issues(repo)
        if gaps:
            cache_gaps.append((repo.name, gaps))

        if issues:
            total += len(issues) - uncounted
            advisory += uncounted
            say(f"\n✗ {repo.name}")
            for issue in issues:
                say(f"    {issue}")
        if not issues:
            say(f"✓ {repo.name}")

    say("\n" + "=" * 52)
    say(f"{'No drift.' if total == 0 else f'{total} divergence(s) found.'}")
    if version_lag:
        say(
            f"{len(version_lag)} repo(s) behind engine v{current_version} — advisory, never fatal:"
        )
        for name, recorded in version_lag:
            say(f"  {name}: v{recorded} → pinky repo distribute --repo {name}")
    if cache_gaps:
        say(
            f"{len(cache_gaps)} repo(s) missing the `.cache/` convention — advisory, "
            "pyproject.toml is repo-owned, fix by hand:"
        )
        for name, gaps in cache_gaps:
            for gap in gaps:
                say(f"  {name}: {gap}")
    if advisory:
        # Said separately so the headline count stays the ACTIONABLE one. Reporting an orphan the
        # tool cannot remove as a "divergence" would put the reader in front of a number no command
        # brings down — the shape of a control one stops reading.
        say(
            f"{advisory} orphaned script(s) reported above — advisory: distribute() never deletes, "
            "remove by hand if wanted."
        )
    return total


def warn_on_drift() -> None:
    """Advisory drift notice for the RENDER path — one line, never blocking, never fatal.

    The drift check lives in ``run_distribution`` so it cannot be forgotten, but only the
    distribution flags reach it. Rendering (``--provider claude`` / ``--into``) writes CLAUDE.md
    and ``.claude/`` and checks nothing — so a session that edits
    ``core/`` then renders, exactly what `feedback_core_edit_needs_setup` prescribes, can walk away
    believing it had distributed, with divergence accumulating silently that way.

    **Advisory, not a gate.** The render path has to keep working on a machine whose repos are not
    cloned (framework targets #2/#3), so an empty parc is silence, and any failure of the check
    itself is swallowed: losing a render to a fault in an advisory notice would be worse than the
    stale repos it warns about.
    """
    try:
        repos = discover_repos()
        drifted = [r.name for r in repos if check_drift([r], quiet=True)]
    except (
        Exception
    ):  # advisory only — a broken check must never cost the caller its render
        return
    if drifted:
        print(
            f"\n⚠ {len(drifted)} repo(s) drifted from core/: {', '.join(drifted)}\n"
            "  Rendering does not distribute. Run: pinky repo drift  (then pinky repo distribute --repo <name>)"
        )


def _init_repo_skeleton(target: Path) -> bool:
    """git init + an unborn ``develop`` branch at ``target``. Idempotent.

    Returns True when the repo was newly created, False when ``target`` was already a git repo
    (converge, don't re-init — the from-zero command's idempotence guarantee). No first commit is
    made: ``develop`` is the initial branch (``git init -b``), the author commits the governance
    floor themselves. Only the git skeleton lives here — the governance itself is ``distribute()``.
    """
    if (target / ".git").exists():
        return False
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "develop"], cwd=target, check=True)
    return True


def new_repo(name: str, args) -> None:
    """Create a new repo already governed: git init + ``develop`` branch, then distribute().

    Scope: "repo nu + distribute()" by default — product scaffolding
    (docs/ skeleton, README/CONTEXT/AGENT/pyproject/LICENSE stubs) is opt-in via ``--scaffold``,
    not automatic: a repo created for a quick experiment may
    not want the full doc floor yet. The from-zero command closes the gap ``proactivity.md`` § 1
    only *detected*: a new repo is born with the
    security/commit socle + hooks, not left ungoverned until someone remembers.

    ``--type`` (requires ``--scaffold``) picks the manifest
    ``scaffold_product`` writes — ``lib`` (default) / ``data`` / ``web`` / ``tooling``. It never
    touches hook selection: ``resolve_extras()`` reads the resulting layout the same way it would
    for a hand-built repo, so a repo born ``--type web`` gets the ``web`` extra because it has a
    ``package.json`` and no ``pyproject.toml`` — not because anything asked for ``web`` by name.

    Delegates to ``run_distribution`` (via ``args.repo = name``) so docs identity and the socle
    floor are the exact same single path as ``--repo``. Idempotent end to end: an existing repo is
    not re-init'd, ``scaffold_product`` never overwrites an existing file, and ``distribute()``
    converges.
    """
    target = WORKSPACE_ROOT / name
    created = _init_repo_skeleton(target)
    print(
        f"  ✓ git init + branch develop  ({name})"
        if created
        else f"→ {name} already a git repo — converging (re-distribute)."
    )
    if getattr(args, "scaffold", False):
        repo_type = getattr(args, "type", None) or "lib"
        written = scaffold_product(target, repo_type)
        if written:
            names = ", ".join(p.relative_to(target).as_posix() for p in written)
            print(f"  ✓ scaffold  {len(written)} file(s) ({names})")
        else:
            print("  → scaffold  nothing to write (all stubs already present)")
    # Reuse the distribution path wholesale: the new repo is now discoverable, filter to it.
    args.repo = name
    run_distribution(args)


def run_distribution(args) -> None:
    repos = discover_repos()
    _report_unonboarded(repos)
    if args.repo:
        repos = [r for r in repos if r.name == args.repo]
        if not repos:
            print(f"Repo not found under {WORKSPACE_ROOT}: {args.repo}")
            sys.exit(1)

    if args.check_drift:
        sys.exit(1 if check_drift(repos) else 0)

    if not (args.all or args.repo):
        print("Refusing to distribute to ALL repos without --all (use --repo <name>).")
        print(
            "Tip: dry-run a single repo first → pinky repo distribute --repo pinky-provider --dry-run"
        )
        sys.exit(1)

    if getattr(args, "standalone", False):
        if not getattr(args, "agents_md", False):
            print("--standalone requires --agents-md.")
            sys.exit(1)
        if args.all or not args.repo:
            print(
                "--standalone requires --repo <name> (never --all — one repo at a time)."
            )
            sys.exit(1)

    print("Hooks distribution" + (" (dry-run)" if args.dry_run else ""))
    print("=" * 52)
    _MISSING_TOOLS.clear()
    statuses: list[tuple[str, str]] = []
    for repo in repos:
        committing = args.commit and not args.dry_run
        dirty_before = dirty_paths(repo) if committing else []
        distribute(
            repo,
            dry_run=args.dry_run,
            identity=_group_docs_identity(repo, WORKSPACE_ROOT),
        )
        if committing:
            status = commit_distribution(repo, dirty_before=dirty_before)
            statuses.append((repo.name, status))
            print(f"  commit  {status}")

    if getattr(args, "agents_md", False) and not args.dry_run:
        if getattr(args, "standalone", False):
            written = [
                write_standalone_agents_md_recorded(
                    repos[0], workspace_root=WORKSPACE_ROOT
                )
            ]
        else:
            written = generate_agents_md(repos, workspace_root=WORKSPACE_ROOT)
        print("\nAGENTS.md")
        print("-" * 52)
        for path in written:
            print(f"  ✓ {path.relative_to(WORKSPACE_ROOT)}")

    print("\nDone." + ("  Nothing written (dry-run)." if args.dry_run else ""))
    if statuses:
        print("\nCommit summary")
        print("-" * 52)
        for name, status in statuses:
            mark = "✗" if status.startswith("BLOCKED") else "✓"
            print(f"  {mark} {name:20} {status}")
        blocked = [n for n, s in statuses if s.startswith("BLOCKED")]
        if blocked:
            print(
                f"\n{len(blocked)} repo(s) need manual attention: {', '.join(blocked)}"
            )
            print(
                "Their distributed files are staged — fix the hook failure and re-commit."
            )

    # A missing CLI tool left the distribution incomplete (baseline / pre-commit hooks not
    # installed). Surface it as a non-zero exit instead of the misleading 'Done.' above.
    if _MISSING_TOOLS:
        print(f"\n✗ Missing tooling (not on PATH): {', '.join(sorted(_MISSING_TOOLS))}")
        print("  Distribution is incomplete without them — install and re-run.")
        sys.exit(1)

    if not args.dry_run and check_drift(repos, extras_fatal=False):
        sys.exit("✗ Residual drift after distribution — see the report above.")
