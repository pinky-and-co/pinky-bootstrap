"""setup — pinky-bootstrap's hooks-distribution runner (package form).

Thin re-export layer: `setup.py` at the repo root stays a shim entrypoint; the `pinky` console
script is the real one. This package holds the implementation, split by responsibility
(see the split-setup-py-package kanban card). Every name — public and private — is re-exported
here so `import setup; setup.<name>` keeps working exactly as when everything lived in one file
(the test suite relies on this: it imports the module and reaches into its internals).
"""

import sys

# The package prints ✓/emoji progress markers (e.g. _install_status_lines); Windows' default
# console codepage (cp1252, not UTF-8) can't encode them and crashes with UnicodeEncodeError.
# Fixed here, at import time, rather than only in setup.py's entrypoint — any direct `import
# setup` (a script bypassing the CLI, a REPL, this package's own callers) gets the same
# protection (found by the windows-latest CI job, CHANTIER0001 loup-into-windows-hooks-morts).
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from .common import (
    AGENTIC_HARNESS_DIR,
    HYGIENE_DIR,
    CORE_HOOKS_DIR,
    CORE_PRECOMMIT_DIR,
    CORE_VENDOR_DIR,
    PACKAGE_DIR,
    PROVIDERS,
    SCRIPT_DIR,
    WORKSPACE_ROOT,
    WORKSPACE_ROOT_ENV,
    SuiteIdentity,
    engine_version,
    find_workspace_root,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
    render_readme_why,
)
from .product_scaffold import scaffold_product
from .precommit import (
    COMMIT_MESSAGE,
    DISTRIBUTED_PATHS,
    MYPY_DEPS_PLACEHOLDER,
    MYPY_PIN,
    VENDOR_MAP,
    _MISSING_TOOLS,
    _write_darglint_config,
    _ensure_secrets_baseline,
    _group_docs_identity,
    _hook_files,
    _init_repo_skeleton,
    _prek_install,
    _read_docs_identity_key,
    _referenced_hook_scripts,
    _repo_runtime_dependencies,
    _report_unonboarded,
    build_precommit_config,
    check_drift,
    commit_distribution,
    discover_repos,
    distribute,
    distribute_vendor,
    mypy_additional_dependencies,
    new_repo,
    render_docs_identity,
    repo_engine_version,
    resolve_extras,
    run_distribution,
    warn_on_drift,
)
from .cli import main

__all__ = [
    "AGENTIC_HARNESS_DIR",
    "HYGIENE_DIR",
    "CORE_HOOKS_DIR",
    "CORE_PRECOMMIT_DIR",
    "CORE_VENDOR_DIR",
    "PACKAGE_DIR",
    "PROVIDERS",
    "SCRIPT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV",
    "SuiteIdentity",
    "engine_version",
    "find_workspace_root",
    "inject_readme_sections_local",
    "has_generated_index",
    "render_index_home",
    "render_readme_why",
    "COMMIT_MESSAGE",
    "DISTRIBUTED_PATHS",
    "MYPY_DEPS_PLACEHOLDER",
    "MYPY_PIN",
    "VENDOR_MAP",
    "_MISSING_TOOLS",
    "_write_darglint_config",
    "_ensure_secrets_baseline",
    "_group_docs_identity",
    "_hook_files",
    "_init_repo_skeleton",
    "_prek_install",
    "_read_docs_identity_key",
    "_referenced_hook_scripts",
    "_repo_runtime_dependencies",
    "_report_unonboarded",
    "build_precommit_config",
    "check_drift",
    "commit_distribution",
    "discover_repos",
    "distribute",
    "distribute_vendor",
    "mypy_additional_dependencies",
    "new_repo",
    "render_docs_identity",
    "repo_engine_version",
    "resolve_extras",
    "warn_on_drift",
    "run_distribution",
    "scaffold_product",
    "main",
]
