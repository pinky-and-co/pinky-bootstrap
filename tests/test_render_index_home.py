"""`docs/index.md` generation gate (kanban card `site-mkdocs-sur-le-moteur`).

Defines "done": `has_generated_index()` is true only when `docs/mkdocs.yml` exists AND no
`docs/.no-generated-index` marker opts the repo out — the marker exists so `pinky-workspace`'s own
hand-curated ADR index survives adopting a mkdocs site, without hardcoding this repo's path into
`core/hooks/render_docs.py` (distributed byte-identical to every repo, ADR-0031). `distribute()`'s
docs/index.md step must honour the same predicate — it imports the exact same function
(setup/common.py), never a duplicated check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402
from tests.test_engine_version import IDENTITY  # noqa: E402


def test_has_generated_index_false_without_mkdocs_yml(tmp_path):
    assert setup.has_generated_index(tmp_path) is False


def test_has_generated_index_true_with_mkdocs_yml(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    assert setup.has_generated_index(tmp_path) is True


def test_has_generated_index_false_when_marker_present(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    (tmp_path / "docs" / ".no-generated-index").write_text("", encoding="utf-8")
    assert setup.has_generated_index(tmp_path) is False


def test_distribute_writes_generated_index_when_site_present(tmp_path):
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    # render_index_home() needs a tagline source — the homepage badges/description block.
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-thing"\ndescription = "A thing."\n', encoding="utf-8"
    )

    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)

    index = (repo / "docs" / "index.md").read_text(encoding="utf-8")
    assert "title: Home" in index


def test_distribute_leaves_hand_maintained_index_alone_with_marker(tmp_path):
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    (repo / "docs" / ".no-generated-index").write_text("", encoding="utf-8")
    hand_written = "# Agent entry point\n\nOne line per doc file.\n"
    (repo / "docs" / "index.md").write_text(hand_written, encoding="utf-8")

    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)

    assert (repo / "docs" / "index.md").read_text(encoding="utf-8") == hand_written


def test_distribute_leaves_agent_index_alone_without_mkdocs_yml(tmp_path):
    # The pre-site regime, unchanged: no mkdocs.yml at all (most repos today).
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)
    (repo / "docs").mkdir()
    hand_written = "# Agent entry point\n\nOne line per doc file.\n"
    (repo / "docs" / "index.md").write_text(hand_written, encoding="utf-8")

    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)

    assert (repo / "docs" / "index.md").read_text(encoding="utf-8") == hand_written
