"""The README tree lists what a reader needs: no hidden paths, distributed hooks as a bare folder."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

_spec = importlib.util.spec_from_file_location(
    "render_docs", setup.CORE_HOOKS_DIR / "render_docs.py"
)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


def test_tree_hides_hidden_paths_and_collapses_distributed_hooks():
    paths = [
        ".github/workflows/ci.yml",
        ".gitignore",
        "README.md",
        "docs/index.md",
        "scripts/hooks/run-tests",
        "scripts/hooks/ruff.toml",
        "scripts/run_tests.sh",
        "src/.env.example",
        "src/app.py",
    ]
    assert rd._render_tree_dict(rd._build_tree(paths)) == [
        "├── scripts/",
        "│   ├── hooks/",
        "│   └── run_tests.sh",
        "├── src/",
        "│   └── app.py",
        "└── README.md",
    ]


def test_a_new_distributed_hook_does_not_change_the_tree():
    before = ["README.md", "scripts/hooks/run-tests"]
    after = [*before, "scripts/hooks/new_hook.py"]
    assert rd._build_tree(after) == rd._build_tree(before)
