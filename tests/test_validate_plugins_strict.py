#!/usr/bin/env python3
"""Tests for hygiene/hooks/validate_plugins_strict.py.

Run with: python3 -m unittest discover tests
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "hygiene" / "hooks"))

import validate_plugins_strict as vps


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestFindManifests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_root = vps.REPO_ROOT
        vps.REPO_ROOT = self.root

    def tearDown(self):
        vps.REPO_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_finds_every_plugin_json(self):
        _write(self.root / "plugins/pc-a/.claude-plugin/plugin.json", "{}")
        _write(self.root / "plugins/pc-b/.claude-plugin/plugin.json", "{}")
        found = vps.find_plugin_manifests()
        self.assertEqual(len(found), 2)

    def test_finds_root_marketplace_json(self):
        _write(self.root / ".claude-plugin/marketplace.json", "{}")
        found = vps.find_marketplace_manifests()
        self.assertEqual(len(found), 1)

    def test_no_manifests_is_not_an_error(self):
        self.assertEqual(vps.find_plugin_manifests(), [])
        self.assertEqual(vps.find_marketplace_manifests(), [])


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_root = vps.REPO_ROOT
        vps.REPO_ROOT = self.root
        _write(self.root / "plugins/pc-a/.claude-plugin/plugin.json", "{}")

    def tearDown(self):
        vps.REPO_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_all_pass_exits_zero(self):
        with patch.object(
            vps, "validate", return_value=vps.ValidationResult(True, "ok")
        ):
            self.assertEqual(vps.main(), 0)

    def test_one_failure_exits_one(self):
        with patch.object(
            vps,
            "validate",
            return_value=vps.ValidationResult(False, "Unknown field"),
        ):
            self.assertEqual(vps.main(), 1)

    def test_missing_claude_cli_exits_one(self):
        with patch.object(vps, "validate", side_effect=FileNotFoundError):
            self.assertEqual(vps.main(), 1)

    def test_no_manifests_exits_zero(self):
        vps.REPO_ROOT = Path(tempfile.mkdtemp())
        self.assertEqual(vps.main(), 0)


if __name__ == "__main__":
    unittest.main()
