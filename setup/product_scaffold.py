"""Product scaffolding for a from-zero repo.

Separate from governance (``_init_repo_skeleton`` + ``distribute()``, which do NOT touch product
files — see ``new_repo``'s docstring): this lays down the docs/ Diátaxis skeleton + the universal
stubs a repo needs so distribute()'s step 5 (README section injection) and the doc tooling have
something to work on. Idempotent — never overwrites a file that already exists, only fills gaps.
Runs once (called from ``new_repo`` behind ``--scaffold``); unrelated to the commit-time
``generate-docs`` hook, which regenerates derived sections on every commit.

``repo_type`` picks which manifest gets written — the ONLY
lever. It never touches hook selection directly: ``resolve_extras()`` reads the layout this writes
(``pyproject.toml`` → python(+snowflake via a declared dep), ``package.json`` → web, neither →
python-lint once real ``.py`` lands) exactly as it would for a hand-built repo. A second router
re-deciding hooks from ``repo_type`` would duplicate what the layout already answers.
"""

from pathlib import Path

_DOCS_SUBDIRS = ("adr", "explanation", "how-to", "reference")

_DOCS_INDEX_MD = """# {name} — doc index

One line per doc file: what it covers, what NOT to put there.

- `adr/` — architecture decision records, one file per technical decision
- `explanation/` — design, trade-offs, scope, roadmap
- `how-to/` — task-oriented guides
- `reference/` — lookup: API, schemas, config, specs
"""

_CONTEXT_MD = """# CONTEXT.md — {name}

Single source of truth for naming in this repo — variables, function names, module names, and
documentation prose all follow it.

| Term (preferred) | Avoid | Definition |
|---|---|---|
"""

_AGENT_MD = """# AGENT.md — {name}

Repo-specific constraints and conventions for coding agents. A rule here overrides the workspace
default of the same concern (see `conventions-scope.md`).

## Constraints

- TODO
"""

_README_MD = """# {name}

## Install

```bash
pip install {name}
```

______________________________________________________________________

## Documentation

______________________________________________________________________

## License
"""

_CACHE_CONVENTION_TOML = """
[tool.ruff]
cache-dir = ".cache/ruff"

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]

[tool.mypy]
cache_dir = ".cache/mypy"

[tool.pytest.ini_options]
cache_dir = ".cache/pytest"
"""

_PYPROJECT_TOML = (
    """[project]
name = "{name}"
version = "0.1.0"
description = "TODO — describe this repo (edit this line, it is the tagline source)"
requires-python = ">=3.12"
"""
    + _CACHE_CONVENTION_TOML
)

_PYPROJECT_TOML_DATA = (
    """[project]
name = "{name}"
version = "0.1.0"
description = "TODO — describe this repo (edit this line, it is the tagline source)"
requires-python = ">=3.12"
dependencies = ["snowflake-snowpark-python"]
"""
    + _CACHE_CONVENTION_TOML
)

_PACKAGE_JSON = """{{
  "name": "{name}",
  "version": "0.1.0",
  "description": "TODO — describe this repo"
}}
"""

_LICENSE = """TODO: choisir une licence.

Décision non tranchée — ne pas remplacer ce placeholder par une licence en dur avant.
"""

REPO_TYPES = ("lib", "data", "web", "tooling")


def scaffold_product(target: Path, repo_type: str = "lib") -> list[Path]:
    """Lay down the docs/ skeleton + universal stubs at ``target``. Idempotent: creates missing
    dirs/files only, never overwrites an existing one. Returns the paths actually written.

    ``repo_type`` picks the manifest (the only thing that varies): ``lib``/``data`` get a
    ``pyproject.toml`` (``data`` additionally declares a snowpark dependency, and gets an empty
    ``resources/`` — the subtree shape itself is an instance convention, declared in each
    instance's ``.claude/settings.pinky.json`` under ``file_placement``); ``web`` gets a
    ``package.json`` and no ``pyproject.toml``;
    ``tooling`` gets neither — ``python-lint`` picks it up on its own once real ``.py`` lands.
    """
    name = target.name
    for sub in _DOCS_SUBDIRS:
        (target / "docs" / sub).mkdir(parents=True, exist_ok=True)

    stubs = {
        target / "docs" / "index.md": _DOCS_INDEX_MD.format(name=name),
        target / "CONTEXT.md": _CONTEXT_MD.format(name=name),
        target / "AGENT.md": _AGENT_MD.format(name=name),
        target / "README.md": _README_MD.format(name=name),
        target / "LICENSE": _LICENSE,
    }
    if repo_type in ("lib", "data"):
        template = _PYPROJECT_TOML_DATA if repo_type == "data" else _PYPROJECT_TOML
        stubs[target / "pyproject.toml"] = template.format(name=name)
        if repo_type == "data":
            (target / "resources").mkdir(parents=True, exist_ok=True)
    elif repo_type == "web":
        stubs[target / "package.json"] = _PACKAGE_JSON.format(name=name)

    written: list[Path] = []
    for path, content in stubs.items():
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
