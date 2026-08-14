#!/usr/bin/env python3
"""Tests for scripts/hooks/validate_frontmatter.py — run with: python3 -m unittest discover tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "hooks"))

import validate_frontmatter as vf


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestValidateFrontmatter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_root = vf.REPO_ROOT
        vf.REPO_ROOT = self.root

    def tearDown(self):
        vf.REPO_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_valid_skill_passes(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\ndescription: does foo\n---\n\nbody\n",
        )
        problems = vf.validate_file(
            self.root / "plugins/pc-x/skills/foo/SKILL.md", "skill"
        )
        self.assertEqual(problems, [])

    def test_valid_agent_passes(self):
        _write(
            self.root / "plugins/pc-x/agents/bar.md",
            "---\nname: bar\ndescription: does bar\n---\n\nbody\n",
        )
        problems = vf.validate_file(self.root / "plugins/pc-x/agents/bar.md", "agent")
        self.assertEqual(problems, [])

    def test_missing_description_fails(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\n---\n\nbody\n",
        )
        problems = vf.validate_file(
            self.root / "plugins/pc-x/skills/foo/SKILL.md", "skill"
        )
        self.assertTrue(any("description" in p for p in problems))

    def test_no_frontmatter_fails(self):
        _write(self.root / "plugins/pc-x/skills/foo/SKILL.md", "# just a heading\n")
        problems = vf.validate_file(
            self.root / "plugins/pc-x/skills/foo/SKILL.md", "skill"
        )
        self.assertTrue(any("no YAML frontmatter" in p for p in problems))

    def test_fork_without_agent_field_fails(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\ndescription: does foo\ncontext: fork\n---\n\nbody\n",
        )
        problems = vf.validate_file(
            self.root / "plugins/pc-x/skills/foo/SKILL.md", "skill"
        )
        self.assertTrue(any("agent" in p for p in problems))

    def test_fork_with_agent_field_passes(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\ndescription: does foo\ncontext: fork\nagent: general-purpose\n---\n\nbody\n",
        )
        problems = vf.validate_file(
            self.root / "plugins/pc-x/skills/foo/SKILL.md", "skill"
        )
        self.assertEqual(problems, [])

    def test_legacy_commands_dir_is_hard_failure(self):
        _write(
            self.root / "plugins/pc-x/commands/deploy.md",
            "---\nname: deploy\n---\nbody\n",
        )
        self.assertEqual(
            vf.find_legacy_commands_dirs(), [self.root / "plugins/pc-x/commands"]
        )

    def test_find_skill_and_agent_files(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\ndescription: d\n---\n",
        )
        _write(
            self.root / "plugins/pc-x/agents/bar.md",
            "---\nname: bar\ndescription: d\n---\n",
        )
        self.assertEqual(len(vf.find_skill_files()), 1)
        self.assertEqual(len(vf.find_agent_files()), 1)


if __name__ == "__main__":
    unittest.main()
