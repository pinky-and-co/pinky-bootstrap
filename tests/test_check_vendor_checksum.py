#!/usr/bin/env python3
"""Tests for hygiene/hooks/check_vendor_checksum.py — run with: python3 -m unittest discover tests"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hygiene" / "hooks"))

import check_vendor_checksum as cvc


class TestCheckVendorChecksum(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_root = cvc.REPO_ROOT
        cvc.REPO_ROOT = self.root

    def tearDown(self):
        cvc.REPO_ROOT = self._orig_root
        self._tmp.cleanup()

    def _write_vendored(self, rel_path: str, content: bytes) -> str:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def test_no_manifest_passes(self):
        self.assertEqual(cvc.main(), 0)

    def test_matching_checksum_passes(self):
        digest = self._write_vendored(
            "plugins/pc-core/hooks/policy_lib.py", b"same content"
        )
        (self.root / cvc.MANIFEST_NAME).write_text(
            json.dumps({"plugins/pc-core/hooks/policy_lib.py": digest})
        )
        self.assertEqual(cvc.main(), 0)

    def test_hand_edited_copy_fails(self):
        self._write_vendored("plugins/pc-core/hooks/policy_lib.py", b"original")
        (self.root / cvc.MANIFEST_NAME).write_text(
            json.dumps({"plugins/pc-core/hooks/policy_lib.py": "not-the-real-hash"})
        )
        self.assertEqual(cvc.main(), 1)

    def test_git_ignored_manifest_fails_even_when_every_copy_matches(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".gitignore").write_text(cvc.MANIFEST_NAME + "\n")
        digest = self._write_vendored(
            "plugins/pc-core/hooks/policy_lib.py", b"same content"
        )
        (self.root / cvc.MANIFEST_NAME).write_text(
            json.dumps({"plugins/pc-core/hooks/policy_lib.py": digest})
        )
        self.assertEqual(cvc.main(), 1)

    def test_missing_vendored_file_fails(self):
        (self.root / cvc.MANIFEST_NAME).write_text(
            json.dumps({"plugins/pc-core/hooks/policy_lib.py": "deadbeef"})
        )
        self.assertEqual(cvc.main(), 1)


if __name__ == "__main__":
    unittest.main()
