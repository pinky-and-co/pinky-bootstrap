"""Hooks distribution — core/ is the single source. setup.py distributes, per repo:
    1. hygiene/hooks/*                 → <repo>/scripts/hooks/
    2. base + extras                → <repo>/.pre-commit-config.yaml     (generated)
    2b. hygiene/ci/ci.yml.tpl          → <repo>/.github/workflows/ci.yml    (generated, libs)
    2c. hygiene/ci/prek.yml.tpl        → <repo>/.github/workflows/prek.yml  (generated, non-libs)
    3. prek install (+ commit-msg hook type)
`--check-drift` compares each repo against the source without writing anything.
"""

import filecmp
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .common import (
    CORE_CI_DIR,
    CORE_HOOKS_DIR,
    CORE_PRECOMMIT_DIR,
    SCRIPT_DIR,
    WORKSPACE_ROOT,
    SuiteIdentity,
    engine_version,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
)
from .agents_md import generate_agents_md, write_standalone_agents_md_recorded
from .product_scaffold import scaffold_product

# Why check_zws is a floor, not a choice: it was born from an invisible character introduced while
# replacing an email address across several .yml config files, which corrupted the DAGs those files
# drove. Cheap corruption, expensive consequence, and invisible to review by construction. It has no
# `files:` filter in base.yaml either, so it already covers every staged file, not just prose. It
# ALSO intersects one channel of invisible-text prompt injection (a payload encoded in zero-width
# characters) — but only that one: the tag block (U+E0000-U+E007F), variation selectors and bidi
# controls all pass through it untouched. Do not read this hook as an anti-injection guard; widening
# its alphabet is its own card, and its own arbitration (U+200D is the emoji ZWJ joiner, and
# U+200C/U+200D are required in Persian/Arabic/Indic scripts).


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
    on every repo it touches (AGENT.md is no longer part of distribution — 2026-07-10 — so it can't
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
        print("   Onboard with: pinky distribute --repo <name>\n")


# ── mypy hermetic additional_dependencies (ADR-0026) ─────────────────────────
# Pin = the miniforge base env's currently installed mypy version (same convention as the other
# hermetic hooks — mdformat/interrogate/darglint — see ADR-0023). Bump here only.
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

    The moteur itself used to be the standing example of that fallback ("Python, but no
    pyproject.toml, since adding one would flip resolve_extras from python-lint to python and turn
    on src/-scoped hooks it has no src/ for") — until card `pyproject-entry-point-et-ci-windows`
    (2026-08-07) gave it one anyway. The flip happened exactly as predicted (mypy/bandit/darglint/
    check-typed-api now apply, all still ``files: ^src/``-scoped so still no-ops on this flat
    layout) — a real, accepted consequence, not a bug. `.python-version` is untouched here too:
    still hand-declared, now simply agreeing with what this function would derive anyway.
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
    """additional_dependencies for the hermetic mypy hook (ADR-0026).

    mypy pin + the repo's own runtime deps, so mypy resolves real third-party types instead of
    falling back to `--ignore-missing-imports` Any. The two known pre-hermetic failures (pinky-core
    `pydantic.BaseModel`, pinky-provider `jinja2`/`snowflake.core`) were confirmed fixed by this set.
    No filtering: every declared dep, including `pinky-*`, is public on PyPI and pip-installable.
    """
    return [f"mypy=={MYPY_PIN}", *_repo_runtime_dependencies(repo)]


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
                    assumption) — this is the gap the pinky-workspace-self-lint card found:
                    the moteur's own hygiene/*.py, setup/*.py, hygiene/hooks/*.py went unlinted.
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
    (measured 2026-08-07 on a fresh ``--new-repo``: ``check_drift`` reported `check_weak_assertions.py`
    missing, right after `distribute()` had correctly decided the repo needed no python extra at all).
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
    ``additional_dependencies`` from that repo's own pyproject.toml (ADR-0026) when the python
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
    return text


# ── CI workflow distribution (chantier-0001, distribute-ci-yml-from-core) ────────────────────
# Before this, .github/workflows/ci.yml was hand-maintained per repo — the only piece of
# governance setup.py never touched, so a transverse CI change (the docs-only-deadlock fix) was
# a manual fan-out to N repos. hygiene/ci/ci.yml.tpl is now the single source; render_ci_yml derives
# the per-repo file. Two axes vary per repo and are NOT derivable from resolve_extras() (which
# answers "python" identically for pinky-core and pinky-provider) — explicit override tables.
CI_TPL_PATH = CORE_CI_DIR / "ci.yml.tpl"
CI_WINDOWS_FRAGMENT_PATH = CORE_CI_DIR / "windows-pilot.yml.tpl"
CI_WORKER_FRAGMENT_PATH = CORE_CI_DIR / "worker-python.yml.tpl"
# Le parcours d'install joué sous Windows. Réservé au MOTEUR : le job l'installe et lance ses
# sous-commandes, ce qu'aucun repo consommateur ne peut faire. Gaté par IDENTITÉ avec SCRIPT_DIR
# plutôt qu'ajouté à CI_WINDOWS_PILOT, qui est une liste de noms en dur (un littéral d'instance
# dans le moteur, la classe de défaut qu'ADR-0065/0069 retirent) — ici l'appartenance se dérive.
CI_INSTALL_WALKTHROUGH_PATH = CORE_CI_DIR / "windows-install-walkthrough.yml.tpl"
# La version que `prek.yml.tpl` porte en dur, remplacée par le pin du repo quand il en a un.
PREK_DEFAULT_PYTHON = "3.12"
# Server-side hook suite for the repos ci.yml.tpl does not cover (see render_prek_yml).
PREK_TPL_PATH = CORE_CI_DIR / "prek.yml.tpl"
CI_PYTHON_VERSION_PLACEHOLDER = "__PYTHON_VERSION__"
CI_INSTALL_CMD_PLACEHOLDER = "__INSTALL_CMD__"
CI_TESTS_CMD_PLACEHOLDER = "__TESTS_CMD__"
CI_D1_DATABASE_PLACEHOLDER = "__D1_DATABASE__"

CI_DEFAULT_INSTALL_CMD = "uv sync --locked --group dev"

# `pytest` suppose que la suite est en Python. Elle ne l'est pas partout : PILOT teste ses calculs
# monétaires en JavaScript (`node --test`), et n'installe même pas pytest. Déléguer au hook du repo
# est plus juste que dupliquer la détection ici — `run-tests` sait déjà résoudre les deux langages,
# et il reste la seule source de vérité sur « comment ce repo se teste ».
CI_DEFAULT_TESTS_CMD = "pytest"
CI_TESTS_OVERRIDES: dict[str, str] = {
    "pluto-poc-pilot": "bash scripts/hooks/run-tests",
}
# Functional extras (validate/address/schedule/xml/lint), not just validate/address — omitting
# xml/schedule/lint silently skips their test files at collection time (pytest.importorskip on
# the missing package), deflating the coverage number without ever failing CI. fec is
# intentionally left out (not exercised by CI). pinky-provider needs --prerelease allow: it
# depends on pinky-core/pinky-snowpark, both pre-release.
CI_INSTALL_OVERRIDES: dict[str, str] = {
    "pinky-core": (
        "uv sync --locked --extra validate --extra address --extra schedule --extra xml "
        "--extra lint --group dev"
    ),
    "pinky-provider": "uv sync --locked --prerelease allow --group dev",
}

# ADR-0023 pilot gate: hermetic pre-commit hooks validated on the brother's machine (Windows,
# prek only, no toolchain). Not every lib, so this is an explicit set, not a resolve_extras() axis.
# `pinky-workspace` joined 2026-08-07 (card `pyproject-entry-point-et-ci-windows`, ADR-0065
# decision 6): "the cheapest gesture to turn the brother's machine into a tested case rather than a
# hope" — the moteur's own 396-test suite had never run on native Windows path separators before.
# `pinky-bootstrap` (2026-08-17): the moteur itself, ported from `pinky-workspace` — the intent
# survives the rename, the literal has to follow it or the moteur silently loses the coverage.
CI_WINDOWS_PILOT: frozenset[str] = frozenset(
    {"pinky-core", "pinky-workspace", "pinky-bootstrap"}
)


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
        fragment = (
            CI_WORKER_FRAGMENT_PATH.read_text(encoding="utf-8")
            .replace(CI_PYTHON_VERSION_PLACEHOLDER, python_version)
            .replace(CI_D1_DATABASE_PLACEHOLDER, d1_database)
        )
        text = text.rstrip("\n") + "\n" + fragment
    return text


def render_prek_yml(repo: Path) -> str:
    """Render .github/workflows/prek.yml for ``repo`` — EVERY repo gets one.

    Until 2026-08-09 this returned None whenever ``render_ci_yml`` produced a workflow: a lib's
    ci.yml ran the hooks itself, so a second workflow would have duplicated them. Exclusive by
    construction, and it left a hole nobody was looking at.

    ``prek.yml`` carries two jobs, and only the first was duplicated. The second,
    ``pr-required-on-main``, is the ONLY server-side guard against a direct push to ``main`` —
    GitHub branch protection is a paid feature on private repos, and neither org has it (measured
    2026-08-09). So every repo that graduated to a ci.yml had silently LOST that guard: 9 of them,
    the moteur included.

    The split is now by subject rather than by file: ``prek.yml`` is hygiene + branch convention and
    goes everywhere; ``ci.yml`` is build + tests and goes where there is a package to test — and it
    no longer runs the hooks. One source for each job, no duplication, and nothing to delete from a
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
    return text


def _referenced_hook_scripts(cfg_text: str) -> set[str]:
    """Script filenames an assembled .pre-commit-config.yaml actually invokes (`entry: ... scripts/hooks/<name>`)."""
    return set(re.findall(r"scripts/hooks/(\S+)", cfg_text))


def _hook_files(repo: Path) -> list[Path]:
    """Hook files to distribute to THIS repo (skip __pycache__ and non-files).

    Scoped to what the repo's own assembled `.pre-commit-config.yaml` actually references (ADR-0027)
    — derived from ``build_precommit_config``, the same source of truth ``resolve_extras`` already
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
    always_on = {"generate_ci_badges.py", "render_docs.py"}
    return [f for f in files if f.name in referenced or f.name in always_on]


_EMPTY_IDENTITY = SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
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


def render_docs_identity(identity: SuiteIdentity) -> str:
    """The ``scripts/hooks/docs_identity.json`` text distributed into one repo.

    Wraps ``SuiteIdentity.to_json()`` rather than extending it: ``to_json`` lives in
    ``hygiene/hooks/render_docs.py``, the generic engine shipped into every repo, which must stay
    free of routing concerns. ``engine_version`` is written HERE, by the distributor, and read back
    by ``check_drift``. ``from_dict`` reads ``_FIELDS`` only, so the extra key is invisible to the
    commit-time hook that consumes this same file.
    """
    payload: dict = {"engine_version": engine_version()}
    payload.update(json.loads(identity.to_json()))
    return json.dumps(payload, indent=2) + "\n"


def _read_docs_identity_key(repo: Path, key: str) -> str | None:
    """One string key from ``repo``'s distributed docs_identity.json, or None when unknown.

    Unknown covers three real cases, all of which must degrade rather than raise: a repo never
    distributed (no file), one distributed before the key existed (the whole parc, as of
    2026-08-08 for ``engine_version``), and a hand-edited or half-written file. ``--check-drift``
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


def distribute(
    repo: Path,
    *,
    dry_run: bool,
    identity: SuiteIdentity,
) -> None:
    """Distribute hooks + config into one repo.

    Copied scripts are scoped to what THIS repo's extras actually reference (ADR-0027).

    Does not touch AGENT.md (2026-07-10): its only generated content was the commit-scopes marker
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

    # 1b. docs_identity.json — the instance identity render_docs.py reads at commit time. Values come
    #     from the repo's group config (never hardcoded in hygiene/hooks/render_docs.py, the generic
    #     engine) — see `_group_docs_identity`.
    print(f"  {tag}hook  scripts/hooks/docs_identity.json")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        (dst_hooks / "docs_identity.json").write_text(
            render_docs_identity(identity), encoding="utf-8"
        )

    # 1c. badges.toml — the generic badge catalog render_docs.py reads at commit time (2026-07-11).
    #     Verbatim copy (no per-repo rendering, unlike docs_identity.json): every repo gets the same
    #     catalog, each entry gated on its own `condition` file existing in that repo.
    print(f"  {tag}hook  scripts/hooks/badges.toml")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORE_HOOKS_DIR / "badges.toml", dst_hooks / "badges.toml")

    # 1d. .gitleaks.toml — repo root, not scripts/hooks/: gitleaks' pre-commit hook has
    #     pass_filenames: false (it scans the repo itself), so it only picks up its config by
    #     auto-discovering .gitleaks.toml in the scan root, not via pre-commit's files/exclude.
    #     Verbatim copy, universal like badges.toml (every repo gets the .secrets.baseline allowlist).
    print(f"  {tag}gitleaks .gitleaks.toml")
    if not dry_run:
        shutil.copy2(CORE_PRECOMMIT_DIR / "gitleaks.toml", repo / ".gitleaks.toml")

    # 1e. .gitattributes — repo root, verbatim like .gitleaks.toml and badges.toml: every
    #     onboarded repo gets the same line-ending normalization, no per-repo rendering.
    print(f"  {tag}gitattributes .gitattributes")
    if not dry_run:
        shutil.copy2(CORE_PRECOMMIT_DIR / "gitattributes", repo / ".gitattributes")

    # 1f. .python-version — the interpreter pin uv (and pyenv) read. Derived from the repo's OWN
    #     requires-python floor, minor only: a lib declaring >=3.12 must work on every 3.12 patch,
    #     so pinning 3.12.13 would go stale on the next patch release for no reproducibility gain.
    #     Apps/containers that DO need patch-level pinning set their own — this covers the repos
    #     setup.py governs, which are all libs. Skipped when nothing declares a floor (see
    #     _python_version_pin): inventing a version for an undeclared repo is worse than none.
    #     Idempotent — rewritten only when the pin actually changes.
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

    # 1g. .claude/policies.json — scaffold with branch_workflow: null if missing, never overwrite.
    #     No safe universal default (verified: "git flow" on pinky-lib/ops, "github flow" on
    #     pinky-agentic-plugins) — a repo fact, decided per repo, not inheritable or inventable.
    #     null (not an empty object) names the expected key so it's visibly unset, not silently
    #     absent — a human fills in the value.
    policies_path = repo / ".claude" / "policies.json"
    if not policies_path.exists():
        print(f"  {tag}scaffold .claude/policies.json (branch_workflow: null)")
        if not dry_run:
            policies_path.parent.mkdir(parents=True, exist_ok=True)
            policies_path.write_text('{"branch_workflow": null}\n', encoding="utf-8")

    # 2. .pre-commit-config.yaml
    print(f"  {tag}config  .pre-commit-config.yaml")
    if not dry_run:
        (repo / ".pre-commit-config.yaml").write_text(
            build_precommit_config(repo, extras), encoding="utf-8"
        )

    # 2b. .github/workflows/ci.yml — governance parity with .pre-commit-config.yaml (chantier-0001,
    # distribute-ci-yml-from-core). None (no derivable Python version) → repo has no CI to render,
    # skip silently — same gate as the `python` extra. Idempotent — rewritten only on real diff.
    ci_yml = render_ci_yml(repo)
    if ci_yml is not None:
        ci_path = repo / ".github" / "workflows" / "ci.yml"
        current_ci = ci_path.read_text(encoding="utf-8") if ci_path.exists() else None
        if current_ci != ci_yml:
            print(f"  {tag}ci      .github/workflows/ci.yml")
            if not dry_run:
                ci_path.parent.mkdir(parents=True, exist_ok=True)
                ci_path.write_text(ci_yml, encoding="utf-8")

    # 2c. .github/workflows/prek.yml — the same server-side net for the repos 2b skips (no
    # pyproject → no ci.yml). Complementary to 2b, never both: see render_prek_yml.
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

    # 4. prek install (hooks runner — ADR-0023, drop-in over pre-commit, reads the same config)
    print(f"  {tag}install prek (+ commit-msg)")
    if not dry_run:
        _prek_install(repo)

    # 5. README badges/tagline/why/documentation/license sections — every repo with a README.md,
    # not just the `python` extra (2026-07-10, generate-docs-hook): sections are self-gating on
    # file/artifact presence now (render_docs.py), so a non-Python repo gets license/prek here too,
    # consistent with what the commit-time `generate-docs` hook would do on its next commit anyway.
    # allow_first_run=True: setup.py is the reviewed adoption path (the diff is shown before it
    # lands) — the commit-time hook uses the default (False) so it never wraps hand-typed sections
    # silently (the pinky-studio data-loss guard, 2026-07-11).
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

    # 6. docs/index.md — the generated mkdocs homepage. Gated on docs/mkdocs.yml: the site repos
    #    only (excludes the non-site repos whose docs/index.md is a pure agent index, no homepage).
    #    A repo can opt out even WITH a site via docs/.no-generated-index (has_generated_index) —
    #    pinky-workspace's own hand-curated ADR index, kanban card `site-mkdocs-sur-le-moteur`.
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


# THE strictness of the parc — one value, everywhere (user decision 2026-08-07: « je m'en fous de
# short ou long, par contre je veux que ce soit uniforme »). `long` is the intent the parc has always
# meant: a one-line docstring counts as complete, but the moment an `Args:`/`Returns:` section is
# opened it must be complete. Measured 2026-08-07 on a one-line docstring with one parameter —
# short: 0 · long: 0 · full: 2 · NO FLAG AND NO FILE: 2.
#
# That last column is the whole reason this exists. darglint's built-in default is **full**, not
# `long`. Commit a7250ce dropped the CLI flag `--strictness=short` — correctly, a CLI flag overrides
# a repo's own config file — on the stated premise that "every repo already carries a .darglint
# declaring strictness = long". **That premise was false**: it was measured inside `pinky-snowpark`,
# which HAS such a file, so "no flag" there meant "long, read from the file" rather than darglint's
# default. Five repos had no file at all, so dropping the flag silently moved them from `short` to
# `full` — the opposite of the intent. It broke pluto-poc-pilot's CI (44 FastAPI routes whose
# injected dependencies would each need a full Args: section) and lay latent in four more, invisible
# until a commit touched a .py file.
#
# Why `long` and not `short`, measured 2026-08-07 on the two docstring styles the parc actually
# writes — PROSE (multi-line, no sections): short 2 err · long 0 · full 2. ONE-LINE + param:
# short 0 · long 0 · full 2. **`long` is the only value that passes both.** That is also why the
# same flag broke CI twice in opposite directions: `--strictness=short` distributed on 2026-07-31
# overrode the `long` of the prose repos (pinky-snowpark 3 errors, pinky-connect 62), and removing
# it on 2026-08-06 dropped the file-less repos onto `full` (pluto-poc-pilot, one-line docstrings).
# Verified free to converge: all 9 python repos sit at 0 errors under `long`.
# `ignore_raise = exc` suppresses a LIMITATION of darglint, never a missing docstring: it cannot
# resolve `raise <variable>`, so it reports the identifier as an undocumented raise even when the
# docstring documents the real exception. Measured 2026-08-07 on `pinky-connect` — converging the
# socle without this line flagged `concurrent_map` (`DAR401: -r exc`) whose docstring already carries
# `Raises: Exception:`. Socle rather than per-repo because it is inert on any repo that never does
# `raise <variable>`, and because `_write_darglint_config` converges: a repo cannot hold a local
# exception, and no per-repo override mechanism exists.
_DARGLINT_INI = """[darglint]
docstring_style = google
strictness = long
ignore = DAR402
ignore_raise = exc
"""


def _write_darglint_config(repo: Path, extras: list[str], tag: str = "") -> None:
    """Write `.darglint` on repos where the darglint hook runs — CONVERGING, not create-if-absent.

    First written as create-if-absent, on the assumption that a repo declaring its own strictness had
    DECIDED. Checked 2026-08-07, and it had not: the four existing `.darglint` were all created on
    2026-06-11, three of them as side effects of unrelated commits (a model-id typo fix, a query
    module, a connector migration). `short` on two repos and `long` on two others was divergence by
    accident, not a position anyone held. Guarding it preserved a phantom decision.

    So this file is socle, like `.pre-commit-config.yaml`: distributed and overwritten — divergence
    stops being silent.

    **A repo cannot hold a local exception, and there is no per-repo escape hatch** (an earlier
    version of this docstring said there was; there never has been). A setting a repo genuinely needs
    therefore has to go into `_DARGLINT_INI` itself — which is where `ignore_raise = exc` landed on
    2026-08-07, after converging `pinky-connect` removed it and produced a false `DAR401`. That is
    workable precisely because the settings at stake suppress tool limitations, inert everywhere
    else; a setting that encoded a real per-repo *policy* would need a mechanism that does not exist
    yet, and would be the moment to build one rather than to widen this constant.

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

    Repo root, not .cache/ (ADR-0033): it's a versioned security artifact (accepted-findings
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


# Files the distribution owns — only these are staged by --commit (never -A). AGENT.md is NOT
# here (2026-07-10): setup.py no longer touches it at all, so it's never the distribution's to stage.
# Everything a distribution WRITES and therefore owns end to end, so `--commit` stages all of it.
# `.darglint` was missing until 2026-08-07: `_write_darglint_config` rewrites it on every python-extra
# repo, but with only that file changed `commit_distribution` returned "up-to-date (nothing to
# commit)" — a clean bill of health over a change it never looked at. Found adding `ignore_raise` to
# the socle, where 9 repos each came out with a modified `.darglint` to commit by hand.
#
# `.secrets.baseline` is deliberately ABSENT, and the reason is NOT "a human edits it" — checked
# 2026-08-07 across the parc, nobody ever has: it is created once by `_ensure_secrets_baseline` (only
# when missing) and thereafter rewritten by detect-secrets itself, in reaction to the REPO's own code
# — `pinky-provider` 3b3547a filled its `results` block with findings from a `secret.py` that same
# commit introduced. So a distribution never modifies it, and staging it could only ever sweep a
# change the repo made for its own reasons into a distribution commit.
DISTRIBUTED_PATHS = (
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    ".gitattributes",
    ".darglint",
    "scripts/hooks",
    ".github/workflows/ci.yml",
    ".github/workflows/prek.yml",
)

# No `(scope)` — hygiene/hooks/commit-msg's PATTERN is strictly `<emoji> <type>: <description>`
# (tightened after this constant was last exercised via bulk --commit; a `chore(hooks):` scope
# fails it, drift caught 2026-07-11 rolling out the docs_identity pitch fields).
COMMIT_MESSAGE = "🔧 chore: adopt pinky-workspace centralized hooks distribution"


def commit_distribution(repo: Path) -> str:
    """Stage only the distributed files and commit them. Returns a status string.

    Hooks run normally (no --no-verify). A repo with a pre-existing hook wall that
    blocks the commit is reported; its changes stay staged for manual resolution.
    """
    # Only stage paths that exist — `git add` aborts entirely (staging nothing) if any
    # pathspec matches no file.
    paths = [p for p in DISTRIBUTED_PATHS if (repo / p).exists()]
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
    # prek is the hooks runner since ADR-0023 (single Rust binary, no Python toolchain to run itself
    # — the whole point of the migration). `--hook-type {pre-commit,commit-msg}` are git hook-type
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


# (section path, key, expected value) — the `.cache/` convention (kanban card
# `convention-cache-jamais-distribuee`). `pyproject.toml` is repo-owned, not something `distribute()`
# can write (it carries deps/metadata `distribute()` has no business touching), so this is advisory
# only: reported like `version_lag`, never counted in `total`. A tool with no section in a given
# repo's `pyproject.toml` at all is not this check's business — only a tool already configured there
# without the cache-dir key is a real divergence.
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

    The expected hook-script set is per-repo (ADR-0027, via `_hook_files`) — scoped to what that
    repo's own extras actually reference, not the full `hygiene/hooks/` directory.

    ``quiet`` returns the count without the report, for ``warn_on_drift``'s one-line advisory.

    ``extras_fatal=False`` still REPORTS orphaned scripts but leaves them out of the count. The
    post-distribution gate needs this: ``distribute()`` writes and never deletes, so it cannot clear
    an orphan — counting them there would make ``--repo <name>`` exit non-zero forever on a repo
    carrying one, a control that fails on the nominal path and that the tool it gates cannot satisfy.
    """
    say = (lambda *_a, **_k: None) if quiet else print
    say("\nDrift check — repo vs pinky-workspace/core/ source")
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

        # The symmetric half (card `defauts-moteur-releves-a-l-import-pluto` § 3). `distribute()`
        # writes but never removes, so a repo whose extras changed (e.g. dropped `web`) can carry a
        # stale script wired to nothing — 4 repos carried one for ten weeks and still reported ✓,
        # because this loop only ever walked the EXPECTED set.
        #
        # Scoped to names the framework itself ships (`CORE_HOOKS_DIR`) plus the two files
        # `distribute()` renders rather than copies. A repo's own helper dropped in scripts/hooks/
        # is legitimate and stays unflagged: a control that nags about it is one people learn to
        # ignore, which is the failure this card is about. Reported only — deleting a file from a
        # consumer repo is not a neutral act (the card's least-invasive option).
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

        # Version lag is reported separately from `issues`, never counted in `total`: a moteur bump
        # touches nothing on disk in a repo distributed before it, so treating it as a divergence
        # would turn `--check-drift` permanently red the moment ANY repo bumps — the exact
        # "control nobody reads" failure this advisory framing avoids.
        recorded_version = repo_engine_version(repo)
        if recorded_version is not None and recorded_version != current_version:
            version_lag.append((repo.name, recorded_version))

        # Same advisory posture as version lag, and for the same reason: `pyproject.toml` is
        # repo-owned, `distribute()` cannot fix it, so counting it in `total` would flag a
        # divergence with no `pinky distribute` to clear it.
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
            say(f"  {name}: v{recorded} → pinky distribute --repo {name}")
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

    ADR-0055 folded the drift check into ``run_distribution`` so it could not be forgotten, but only
    the distribution flags reach it. Rendering (``--provider claude`` / ``--into``) writes CLAUDE.md
    and ``.claude/`` and checked nothing — so a session that edits
    ``core/`` then renders, exactly what `feedback_core_edit_needs_setup` prescribes, walked away
    believing it had distributed. 30 divergences accumulated that way by 2026-08-05.

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
            "  Rendering does not distribute. Run: pinky drift  (then pinky distribute --repo <name>)"
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

    Scope (chantier-0001, 2026-07-11): "repo nu + distribute()" by default — product scaffolding
    (docs/ skeleton, README/CONTEXT/AGENT/pyproject/LICENSE stubs) is opt-in via ``--scaffold``
    (card `scaffolding-produit-from-zero`), not automatic: a repo created for a quick experiment may
    not want the full doc floor yet. The from-zero command closes the gap ``proactivity.md`` § 1
    (ex ``repo-onboarding.md``, merged 2026-07-28) only *detected*: a new repo is born with the
    security/commit socle + hooks, not left ungoverned until someone remembers.

    ``--type`` (card `type-de-repo-a-la-creation`, requires ``--scaffold``) picks the manifest
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
        # Before distribute(): step 5 (README section injection) only fires when README.md
        # already exists, and the tagline section needs pyproject.toml's [project].description.
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
            "Tip: dry-run a single repo first → pinky distribute --repo pinky-provider --dry-run"
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
        distribute(
            repo,
            dry_run=args.dry_run,
            identity=_group_docs_identity(repo, WORKSPACE_ROOT),
        )
        if args.commit and not args.dry_run:
            status = commit_distribution(repo)
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

    # Class B — a missing CLI tool left the distribution incomplete (baseline / pre-commit hooks not
    # installed). Surface it as a non-zero exit instead of the misleading 'Done.' above.
    if _MISSING_TOOLS:
        print(f"\n✗ Missing tooling (not on PATH): {', '.join(sorted(_MISSING_TOOLS))}")
        print("  Distribution is incomplete without them — install and re-run.")
        sys.exit(1)

    # Class C — the distribution ran but the repos still diverge from core/. Verification by
    # construction rather than by discipline (2026-07-25): check_drift() already covered every
    # post-rollout check worth doing (byte-compare of each expected hook, .pre-commit-config.yaml,
    # ci.yml, per-repo scoping via _hook_files) but it was a SEPARATE invocation you had to
    # remember — so it kept getting re-improvised by hand (md5 loops, grep for the hook id) right
    # after a rollout instead. Same doctrine as _report_unonboarded above: the tool tells you every
    # time, you don't have to remember to ask. Skipped on --dry-run, which by definition leaves in
    # place the drift it just finished describing.
    # `extras_fatal=False`: orphaned scripts are reported but do not fail the gate. distribute()
    # writes and never deletes, so it cannot clear one — counting them here would make the nominal
    # path exit non-zero forever on any repo carrying an orphan, which is how a guard rail becomes
    # something people learn to ignore (the archived card `drift-check-faux-positif-sans-manifeste`).
    if not args.dry_run and check_drift(repos, extras_fatal=False):
        sys.exit("✗ Residual drift after distribution — see the report above.")
