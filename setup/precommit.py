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
    corpus_roots,
    has_generated_index,
    inject_readme_sections_local,
    load_profile,
    render_index_home,
)
from .product_scaffold import scaffold_product

# ── Security/integrity socle — the universal floor (chantier-0001, ADR-0062) ──────────────────
# These base.yaml hooks are the "plancher universel" the à-la-carte filter can NEVER drop: whatever
# a profile's `hooks:` list says (even `[]`), every distributed repo keeps secret scanning, a
# readable commit-message format, and the invisible-character guard. They live HERE, out of
# HOOK_MANIFEST, so _drop_pcids/_drop_scripts structurally cannot select them for removal — the
# guarantee is the absence, not a special case. Their keys stay RECOGNISED (listing one is a
# redundant no-op, never an "unknown hook" error). Shape mirrors HOOK_MANIFEST for the invariant test.
#
# Why check_zws is a floor and not a choice: it was born from an invisible character introduced while
# replacing an email address across several .yml config files, which corrupted the DAGs those files
# drove. Cheap corruption, expensive consequence, and invisible to review by construction — nobody
# opts out of that on purpose. It has no `files:` filter in base.yaml either, so it already covered
# every staged file, not just prose. It ALSO intersects one channel of invisible-text prompt
# injection (a payload encoded in zero-width characters) — but only that one: the tag block
# (U+E0000-U+E007F), variation selectors and bidi controls all pass through it untouched. Do not read
# this hook as an anti-injection guard; widening its alphabet is its own card, and its own arbitration
# (U+200D is the emoji ZWJ joiner, and U+200C/U+200D are required in Persian/Arabic/Indic scripts).
SOCLE_HOOKS: dict[str, tuple[str, str | None]] = {
    # profile key       (pre-commit id,      distributed script | None)
    "gitleaks": ("gitleaks", None),
    "detect-secrets": ("detect-secrets", None),
    "commit-msg": ("commit-msg-format", "commit-msg"),
    "check_zws": ("check-zws", "check_zws.py"),
}

# ── The single selectable hook (ADR-0008, emptied by ADR-0062) ────────────────
# `hooks:` used to carry eight keys, back when the profile was the ONLY router. It is not: a hook's
# presence follows from the repo's LAYOUT, which resolve_extras() reads directly — check_snowpark_api
# ships with extras/snowflake.yaml, check_typed_api and check_weak_assertions with the python extras,
# the four js_* with extras/web.yaml. Listing them here as well made the profile a second, competing
# router that could only ever drift from the first — and did, twice: `pinky` named a
# check_weak_assertions key that exists in no registry (hard-failing every --profile pinky run), and
# omitted the js_* keys while claiming to be the identity filter (which would have stripped
# pinky-studio's js_engine_sync hard block).
#
# check_forbidden_keywords is the one hook no layout can predict — it guards against leaking employer
# material into what the author writes, so it depends on WHO is at the keyboard, not on what the repo
# contains. It stays DECLARATIVE on purpose rather than keying off the presence of a keywords file:
# auto-detection would make an anti-leak guard vanish silently on a machine where that file is
# missing, and a guard that disappears without a word is the worst failure mode it has.
#
# Anything NOT in this manifest is socle or capability-routed → never filtered.
#
# Structural invariant (verified against hygiene/pre-commit/{base,extras/*}.yaml): every selectable
# hook is the SOLE hook of its own `- repo:` block, so filtering removes whole repo blocks — never
# a partial edit, never a dangling external-repo stub.
HOOK_MANIFEST: dict[str, tuple[str, str | None]] = {
    # profile key               (pre-commit id,            distributed script | None)
    "check_forbidden_keywords": (
        "check-forbidden-keywords",
        "check_forbidden_keywords.py",
    ),
}

# Keys a profile's `hooks:` list may legitimately name: the selectable manifest + the always-on
# socle (listing a socle key is a redundant no-op, never an "unknown hook" error).
KNOWN_HOOK_KEYS: frozenset[str] = frozenset(HOOK_MANIFEST) | frozenset(SOCLE_HOOKS)


def profile_selected_hooks(profile: dict) -> set[str] | None:
    """Translate a profile's `hooks:` list into a selected-keys set, or None for 'no filter'.

    None (key absent / null) = framework default = every hook ships (identity, the no-profile
    behaviour). An explicit list — including `[]` — enables à-la-carte filtering: only the named
    selectable hooks survive (the hygiene socle is never touched). Unknown keys are reported by
    the caller; they are inert here (they simply select nothing).
    """
    if "hooks" not in profile or profile["hooks"] is None:
        return None
    return set(profile["hooks"])


def _drop_pcids(selected: set[str]) -> set[str]:
    """Pre-commit ids to remove: every selectable hook whose key is NOT selected."""
    return {
        pcid for key, (pcid, _script) in HOOK_MANIFEST.items() if key not in selected
    }


def _drop_scripts(selected: set[str]) -> set[str]:
    """Distributed script filenames to skip: selectable scripts whose key is NOT selected."""
    return {
        script
        for key, (_pcid, script) in HOOK_MANIFEST.items()
        if script is not None and key not in selected
    }


def _filter_precommit_config(text: str, drop_pcids: set[str]) -> str:
    """Remove the `- repo:` block of each deselected hook from an assembled config.

    Operates on whole repo blocks (boundary = a `  - repo:` line). A block is dropped iff it
    contains a deselected pre-commit id; preceding comment/blank header lines travel with it.
    A no-op when ``drop_pcids`` is empty → the `pinky`/no-profile path stays byte-identical.
    """
    if not drop_pcids:
        return text
    lines = text.split("\n")
    repo_starts = [i for i, ln in enumerate(lines) if re.match(r"^  - repo:", ln)]
    drop_idx: set[int] = set()
    for n, start in enumerate(repo_starts):
        end = repo_starts[n + 1] if n + 1 < len(repo_starts) else len(lines)
        ids = {
            m.group(1)
            for ln in lines[start:end]
            if (m := re.match(r"^\s+- id:\s*(\S+)", ln))
        }
        if not (ids & drop_pcids):
            continue
        # Pull the leading comment/blank header into the dropped range (stops at the previous
        # block's last content line, or `repos:` / the file header before the first block).
        s = start
        while s - 1 >= 0 and (
            lines[s - 1].strip() == "" or lines[s - 1].lstrip().startswith("#")
        ):
            s -= 1
        drop_idx.update(range(s, end))
    if not drop_idx:
        return text
    kept = [ln for i, ln in enumerate(lines) if i not in drop_idx]
    return "\n".join(kept)


def profile_hooks_enabled(profile: dict) -> bool:
    """Return the rigor dial's hooks layer (default True when the key is absent)."""
    layers = profile.get("layers") or {}
    return bool(layers.get("hooks", True))


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
    """Pick pre-commit extras for a repo from its layout (per-hook profile deferred).

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


def build_precommit_config(
    repo: Path, extras: list[str], selected_hooks: set[str] | None = None
) -> str:
    """Assemble .pre-commit-config.yaml = base + selected extras (text concat).

    When ``repo`` IS the moteur itself (``repo.resolve() == SCRIPT_DIR.resolve()``),
    ``hygiene/pre-commit/workspace-self.yaml`` is appended last — the public-corpus leak guard
    (``--check-public``), which only makes sense here (needs setup.py + corpus-public/ + the
    private profiles). It is NOT a layout extra (identity axis, not repo-layout), so it lives
    outside ``extras/`` and never ships to a consumer repo.

    ``repo`` is the TARGET repo (not the source workspace) — needed to auto-derive the mypy hook's
    ``additional_dependencies`` from that repo's own pyproject.toml (ADR-0026) when the python
    extra is active; a no-op placeholder substitution otherwise.

    ``selected_hooks`` is the à-la-carte filter (ADR-0008): None = no filtering (identity, the
    no-profile path). A set drops the `- repo:` block of every selectable hook NOT named in it;
    the hygiene socle and the python/snowflake extras are never touched. ``pinky`` enumerates all
    selectable hooks, so filtering by it is a no-op → byte-identical to the no-profile output.
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
    if selected_hooks is not None:
        text = _filter_precommit_config(text, _drop_pcids(selected_hooks))
    # Moteur-only self-lint: the public-corpus leak guard (--check-public) needs setup.py,
    # corpus-public/ and the private profiles — all present only here. Appended AFTER the
    # à-la-carte filter so it is a socle-grade guard the profile selection can never drop.
    if repo.resolve() == SCRIPT_DIR.resolve():
        fragment = (CORE_PRECOMMIT_DIR / "workspace-self.yaml").read_text(
            encoding="utf-8"
        )
        text = text.rstrip("\n") + "\n\n" + fragment.rstrip("\n") + "\n"
    return text


# ── CI workflow distribution (chantier-0001, distribute-ci-yml-from-core) ────────────────────
# Before this, .github/workflows/ci.yml was hand-maintained per repo — the only piece of
# governance setup.py never touched, so a transverse CI change (the docs-only-deadlock fix) was
# a manual fan-out to N repos. hygiene/ci/ci.yml.tpl is now the single source; render_ci_yml derives
# the per-repo file. Two axes vary per repo and are NOT derivable from resolve_extras() (which
# answers "python" identically for pinky-core and pinky-provider) — explicit override tables,
# same pattern as SOCLE_HOOKS/HOOK_MANIFEST above.
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

CI_DEFAULT_INSTALL_CMD = "pip install -e . --group dev"

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
# intentionally left out (not exercised by CI). pinky-provider needs --pre: it depends on
# pinky-core/pinky-snowpark, both pre-release.
CI_INSTALL_OVERRIDES: dict[str, str] = {
    "pinky-core": 'pip install -e ".[validate,address,schedule,xml,lint]" --group dev',
    "pinky-provider": "pip install --pre -e . --group dev",
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


def _hook_files(repo: Path, selected_hooks: set[str] | None = None) -> list[Path]:
    """Hook files to distribute to THIS repo (skip __pycache__ and non-files).

    Scoped to what the repo's own assembled `.pre-commit-config.yaml` actually references (ADR-0027)
    — derived from ``build_precommit_config``, the same source of truth ``resolve_extras`` already
    drives, instead of a second parallel classification. A repo without the ``web`` extra never gets
    the JS/HTML scripts (they'd sit dead, unreferenced by its config). ``generate_ci_badges.py`` has
    no pre-commit id (CI helper invoked from a workflow, not a hook `entry:`) and is always
    distributed — same for ``render_docs.py`` (imported by ``generate-docs``, not textually
    referenced in the assembled YAML, so the regex scan above can't find it). ``selected_hooks``
    (ADR-0008) additionally drops the script of every deselected selectable hook. None = no profile
    filtering.
    """
    files = [f for f in sorted(CORE_HOOKS_DIR.iterdir()) if f.is_file()]
    referenced = _referenced_hook_scripts(
        build_precommit_config(repo, resolve_extras(repo))
    )
    always_on = {"generate_ci_badges.py", "render_docs.py"}
    files = [f for f in files if f.name in referenced or f.name in always_on]
    if selected_hooks is None:
        return files
    drop = _drop_scripts(selected_hooks)
    return [f for f in files if f.name not in drop]


def _load_docs_identity(profile_arg: str | None) -> SuiteIdentity:
    """The active profile's docs_identity.json → SuiteIdentity (instance identity for generated
    docs). JSON, not the profile.yaml, so the dependency-free distribution path loads it with stdlib
    only (no pyyaml). Mirrors load_profile's name-or-path resolution."""
    name = profile_arg
    if name is None:
        sys.exit("✗ no --profile given — docs generation needs one.")
    candidate = Path(name)
    if (
        candidate.is_file()
    ):  # --profile given as a path to a profile.yaml → sibling json
        path: Path | None = candidate.parent / "docs_identity.json"
    else:  # a profile name → <corpus root>/profiles/<name>/docs_identity.json
        path = next(
            (
                p
                for cr in corpus_roots()
                if (p := cr / "profiles" / name / "docs_identity.json").exists()
            ),
            None,
        )
    if path is None or not path.exists():
        sys.exit(
            f"✗ no docs_identity.json for profile '{name}' — required to generate docs "
            "(instance identity; see hygiene/hooks/render_docs.py, the de-leak)"
        )
    return SuiteIdentity.from_dict(json.loads(path.read_text(encoding="utf-8")))


def resolve_profile_name(profile_arg: str | None) -> str | None:
    """The profile NAME to record in each repo this run distributes to.

    Same name-or-path resolution as ``_load_docs_identity``, reduced to the identifier: ``--profile``
    accepts a path to a profile.yaml, and a repo distributed by path must compare equal to one
    distributed by name — otherwise the downgrade guard would fire on two spellings of one regime.
    ``None`` (no ``--profile``) means "nothing to record".
    """
    name = profile_arg
    if name is None:
        return None
    candidate = Path(name)
    return candidate.parent.name if candidate.is_file() else name


def render_docs_identity(identity: SuiteIdentity, profile_name: str | None) -> str:
    """The ``scripts/hooks/docs_identity.json`` text distributed into one repo.

    Wraps ``SuiteIdentity.to_json()`` rather than extending it: ``to_json`` lives in
    ``hygiene/hooks/render_docs.py``, the generic engine shipped into every repo, which must stay free
    of routing concerns. The ``profile`` and ``engine_version`` keys are written HERE, by the
    distributor, and read back by ``repo_profile`` / ``check_drift`` respectively. ``from_dict``
    reads ``_FIELDS`` only, so the extra keys are invisible to the commit-time hook that consumes
    this same file.

    ``engine_version`` always present (the moteur always has one); ``profile`` absent (not ``null``)
    when there is no profile to record — an absent marker reads as "unknown"; a null would be a
    third state no caller distinguishes. Both come before the identity payload so someone opening a
    repo's docs_identity.json sees the routing info before the pitch content.
    """
    payload: dict = {"engine_version": engine_version()}
    if profile_name is not None:
        payload["profile"] = profile_name
    payload.update(json.loads(identity.to_json()))
    return json.dumps(payload, indent=2) + "\n"


def _read_docs_identity_key(repo: Path, key: str) -> str | None:
    """One string key from ``repo``'s distributed docs_identity.json, or None when unknown.

    Unknown covers three real cases, all of which must degrade rather than raise: a repo never
    distributed (no file), one distributed before the key existed (the whole parc, as of
    2026-08-07 for ``profile``, 2026-08-08 for ``engine_version``), and a hand-edited or
    half-written file. ``--check-drift`` walks every repo ``discover_repos()`` finds, so one
    unreadable repo must not abort the scan.
    """
    path = repo / "scripts" / "hooks" / "docs_identity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def repo_profile(repo: Path) -> str | None:
    """The profile ``repo`` was last distributed with, or None when unknown."""
    return _read_docs_identity_key(repo, "profile")


def repo_engine_version(repo: Path) -> str | None:
    """The moteur version ``repo`` was last distributed with, or None when unknown."""
    return _read_docs_identity_key(repo, "engine_version")


def distribute(
    repo: Path,
    *,
    dry_run: bool,
    identity: SuiteIdentity,
    selected_hooks: set[str] | None = None,
    profile_name: str | None = None,
) -> None:
    """Distribute hooks + config into one repo.

    Copied scripts are scoped to what THIS repo's extras actually reference (ADR-0027). On top of
    that, ``selected_hooks`` (ADR-0008) applies the profile's à-la-carte hook filter to both the
    copied scripts and the generated config. None = no profile filtering (identity).

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
    for src in _hook_files(repo, selected_hooks):
        dst = dst_hooks / src.name
        print(f"  {tag}hook  scripts/hooks/{src.name}")
        if not dry_run:
            dst_hooks.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if src.name in ("commit-msg", "generate-docs"):
                dst.chmod(0o755)

    # 1b. docs_identity.json — the instance identity render_docs.py reads at commit time. Values come
    #     from the profile (de-leak); never hardcoded in hygiene/hooks/render_docs.py (the generic engine).
    #     Also carries `profile`: the regime this repo is on, so `--all` and `--check-drift` can
    #     resolve it per repo instead of imposing the caller's (see render_docs_identity).
    print(f"  {tag}hook  scripts/hooks/docs_identity.json")
    if not dry_run:
        dst_hooks.mkdir(parents=True, exist_ok=True)
        (dst_hooks / "docs_identity.json").write_text(
            render_docs_identity(identity, profile_name), encoding="utf-8"
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
            build_precommit_config(repo, extras, selected_hooks), encoding="utf-8"
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
# exception, and the profile-level mechanism its docstring promises does not exist.
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

    **A repo cannot hold a local exception, and there is no profile-level escape hatch** (an earlier
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


def _recorded_selected_hooks(repo: Path) -> tuple[set[str] | None, str | None]:
    """``(selection, note)`` for ``repo``, resolved from the profile the repo itself records.

    ``note`` is a human-readable reason when the selection could NOT be resolved; the caller prints
    it next to the repo. Saying "compared unfiltered" out loud matters: silently pretending the
    filter applied would turn a real divergence into a reassuring ✓, which is the failure this whole
    change exists to remove.

    Two degradations are real cases, not defensive padding. **pyyaml may be absent** — the no-profile
    distribution path is required to run without it (`test_no_hard_yaml_dependency`; the Windows CI
    job installs none), and now that every repo records a profile, drift would otherwise demand it
    everywhere. **The recorded profile may be gone** — `pluto-poc` was a real profile of this parc and
    no longer exists; `load_profile` exits on both, so the exit is caught rather than propagated.
    """
    name = repo_profile(repo)
    if name is None:
        return None, None
    try:
        import yaml  # noqa: F401 — probe: load_profile exits (not raises) when it is missing
    except ModuleNotFoundError:
        return (
            None,
            f"profile '{name}' not applied (pyyaml unavailable) — compared unfiltered",
        )
    try:
        profile, _ = load_profile(name)
    except SystemExit:
        return None, f"profile '{name}' unresolvable — compared unfiltered"
    if not profile_hooks_enabled(profile):
        return None, None
    return profile_selected_hooks(profile), None


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
    selected_hooks: set[str] | None = None,
    quiet: bool = False,
    extras_fatal: bool = True,
) -> int:
    """Compare each repo against the workspace source; return divergence count.

    The expected hook-script set is per-repo (ADR-0027, via `_hook_files`) — scoped to what that
    repo's own extras actually reference, not the full `hygiene/hooks/` directory. ``selected_hooks``
    (ADR-0008) further narrows it to the profile's selection.

    ``None`` no longer means "no filtering": it means **resolve each repo's own profile** (the one
    `distribute()` recorded). Comparing a whole parc against a single caller-supplied profile is what
    made this control permanently red — measured 2026-08-07 on the 19 repos: 10 divergences with no
    `--profile`, 18 with `--profile pluto`, no invocation reporting 0. A repo recording nothing still
    compares unfiltered, so a parc that has never been redistributed behaves exactly as before.

    An explicit ``selected_hooks`` still wins for every repo — `--profile X --check-drift` asks "what
    would this parc look like under X?", which stays a legitimate question.

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
        if selected_hooks is None:
            repo_hooks, note = _recorded_selected_hooks(repo)
        else:
            repo_hooks, note = selected_hooks, None
        if note:
            say(f"  ⚠ {repo.name}: {note}")

        expected = _hook_files(repo, repo_hooks)
        for src in expected:
            dst = dst_hooks / src.name
            if not dst.exists():
                issues.append(f"missing hook scripts/hooks/{src.name}")
            elif not filecmp.cmp(src, dst, shallow=False):
                issues.append(f"differs   scripts/hooks/{src.name}")

        # The symmetric half (card `defauts-moteur-releves-a-l-import-pluto` § 3). `distribute()`
        # writes the hooks a profile keeps but never removes the ones it drops, so deselecting a
        # hook leaves its script on disk, wired to nothing — 4 repos carried one for ten weeks and
        # still reported ✓, because this loop only ever walked the EXPECTED set.
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
        expected_cfg = build_precommit_config(repo, resolve_extras(repo), repo_hooks)
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
        # "control nobody reads" failure the profile downgrade guard already avoids (§ `distribute`).
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
    the distribution flags reach it. Rendering (``--provider claude`` / ``--profile <name>`` /
    ``--into``) writes CLAUDE.md and ``.claude/`` and checked nothing — so a session that edits
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

    Delegates to ``run_distribution`` (via ``args.repo = name``) so the profile gate, docs identity,
    à-la-carte hook selection and the socle floor are the exact same single path as ``--repo``.
    Idempotent end to end: an existing repo is not re-init'd, ``scaffold_product`` never overwrites
    an existing file, and ``distribute()`` converges.
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
    # Profile gate. When --profile is given, the rigor dial's `layers.hooks` first decides whether
    # this profile receives the hooks distribution at all (Phase 2a coarse gate): an agent-only
    # profile (layers.hooks: false) is excluded entirely — no hooks, no drift check. When hooks
    # ARE enabled, the profile's `hooks:` list drives à-la-carte per-hook filtering (Phase 3b,
    # ADR-0008): only the named selectable hooks ship; the hygiene socle is never touched. With NO
    # --profile, selected_hooks stays None → identity → the 10 pinky repos stay at 0 drift.
    selected_hooks: set[str] | None = None
    if args.profile:
        profile, _ = load_profile(args.profile)
        if not profile_hooks_enabled(profile):
            print(
                f"Profile '{profile['name']}' is agent-only (layers.hooks: false) — "
                "no hooks distributed."
            )
            sys.exit(0)
        selected_hooks = profile_selected_hooks(profile)
        if selected_hooks is None:
            print(
                f"Profile '{profile['name']}' — layers.hooks: true, no `hooks:` list "
                "(framework default: all hooks)."
            )
        else:
            unknown = selected_hooks - KNOWN_HOOK_KEYS
            if unknown:
                # A profile naming a hook that is neither selectable nor socle is a typo the
                # selection would silently drop — fail rather than distribute a filter the author
                # didn't intend.
                sys.exit(
                    f"✗ profile '{profile['name']}' lists unknown hook(s): "
                    f"{', '.join(sorted(unknown))} (not in HOOK_MANIFEST or SOCLE_HOOKS)."
                )
            # The socle floor (SOCLE_HOOKS) always ships and is never reported here — only the
            # selectable manifest is subject to à-la-carte kept/dropped.
            kept = sorted(selected_hooks & set(HOOK_MANIFEST))
            dropped = sorted(set(HOOK_MANIFEST) - selected_hooks)
            print(
                f"Profile '{profile['name']}' — layers.hooks: true; socle always on "
                f"({', '.join(SOCLE_HOOKS)}); à-la-carte selection: "
                f"{len(kept)}/{len(HOOK_MANIFEST)} selectable hooks."
            )
            if dropped:
                print(f"  filtered out: {', '.join(dropped)}")

    repos = discover_repos()
    _report_unonboarded(repos)
    if args.repo:
        repos = [r for r in repos if r.name == args.repo]
        if not repos:
            print(f"Repo not found under {WORKSPACE_ROOT}: {args.repo}")
            sys.exit(1)

    if args.check_drift:
        sys.exit(1 if check_drift(repos, selected_hooks) else 0)

    if not (args.all or args.repo):
        print("Refusing to distribute to ALL repos without --all (use --repo <name>).")
        print(
            "Tip: dry-run a single repo first → pinky distribute --repo pinky-provider --dry-run"
        )
        sys.exit(1)

    profile_name = resolve_profile_name(args.profile)

    # Downgrade guard (card `defauts-moteur-releves-a-l-import-pluto` § 4). `--all` carries no
    # per-repo intent, so it must not decide the regime of a repo deliberately placed on another
    # one: on 2026-07-31 it reverted `pluto-poc-pilot` to the full socle — employer-keyword scanner
    # and pinky identity reinstalled — then printed `✓` and `No drift`, because "no drift" was
    # computed against the profile just applied. SKIP rather than refuse the whole run: refusing
    # would make `--all` useless on a multi-profile parc (some repo always mismatches), whereas
    # skipping converges what the caller owns and NAMES what to run separately. `--repo X` is
    # exempt — the caller named both repo and profile, and it is the documented recovery gesture.
    if args.all and not args.repo and not getattr(args, "force", False):
        keep = []
        for repo in repos:
            recorded = repo_profile(repo)
            if recorded is not None and recorded != profile_name:
                print(
                    f"→ {repo.name}  SKIPPED — recorded on profile '{recorded}', this run applies "
                    f"'{profile_name}'. Run: pinky distribute --repo {repo.name} "
                    f"--profile {recorded} (or --all --force to override — "
                    "--force is setup.py-only, not yet mirrored in cli_pinky.py)."
                )
            else:
                keep.append(repo)
        repos = keep

    print("Hooks distribution" + (" (dry-run)" if args.dry_run else ""))
    print("=" * 52)
    _MISSING_TOOLS.clear()
    statuses: list[tuple[str, str]] = []
    identity = _load_docs_identity(args.profile)
    for repo in repos:
        distribute(
            repo,
            dry_run=args.dry_run,
            identity=identity,
            selected_hooks=selected_hooks,
            profile_name=profile_name,
        )
        if args.commit and not args.dry_run:
            status = commit_distribution(repo)
            statuses.append((repo.name, status))
            print(f"  commit  {status}")

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
    if not args.dry_run and check_drift(repos, selected_hooks, extras_fatal=False):
        sys.exit("✗ Residual drift after distribution — see the report above.")
