#!/usr/bin/env python3
"""Tests for setup.distribute_vendor — run with: python3 -m pytest tests/test_distribute_vendor.py"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod


def test_copies_to_every_existing_target(tmp_path, monkeypatch):
    (tmp_path / "plugins/pc-core/hooks").mkdir(parents=True)
    (tmp_path / "plugins/pc-git/hooks").mkdir(parents=True)
    monkeypatch.setattr(
        precommit_mod,
        "VENDOR_MAP",
        {
            "policy_lib.py": [
                "plugins/pc-core/hooks/policy_lib.py",
                "plugins/pc-git/hooks/policy_lib.py",
            ]
        },
    )

    precommit_mod.distribute_vendor(tmp_path, dry_run=False)

    src_content = (precommit_mod.CORE_VENDOR_DIR / "policy_lib.py").read_bytes()
    assert (
        tmp_path / "plugins/pc-core/hooks/policy_lib.py"
    ).read_bytes() == src_content
    assert (tmp_path / "plugins/pc-git/hooks/policy_lib.py").read_bytes() == src_content


def test_skips_a_target_whose_parent_dir_is_absent(tmp_path, monkeypatch):
    (tmp_path / "plugins/pc-core/hooks").mkdir(parents=True)
    monkeypatch.setattr(
        precommit_mod,
        "VENDOR_MAP",
        {
            "policy_lib.py": [
                "plugins/pc-core/hooks/policy_lib.py",
                "plugins/pc-git/hooks/policy_lib.py",
            ]
        },
    )

    precommit_mod.distribute_vendor(tmp_path, dry_run=False)

    assert (tmp_path / "plugins/pc-core/hooks/policy_lib.py").exists()
    assert not (tmp_path / "plugins/pc-git").exists()


def test_writes_a_manifest_with_matching_sha256(tmp_path, monkeypatch):
    (tmp_path / "plugins/pc-core/hooks").mkdir(parents=True)
    monkeypatch.setattr(
        precommit_mod,
        "VENDOR_MAP",
        {"policy_lib.py": ["plugins/pc-core/hooks/policy_lib.py"]},
    )

    precommit_mod.distribute_vendor(tmp_path, dry_run=False)

    manifest = json.loads((tmp_path / ".vendor-manifest.json").read_text())
    expected = hashlib.sha256(
        (precommit_mod.CORE_VENDOR_DIR / "policy_lib.py").read_bytes()
    ).hexdigest()
    assert manifest == {"plugins/pc-core/hooks/policy_lib.py": expected}


def test_no_manifest_written_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(
        precommit_mod,
        "VENDOR_MAP",
        {"policy_lib.py": ["plugins/pc-git/hooks/policy_lib.py"]},
    )

    precommit_mod.distribute_vendor(tmp_path, dry_run=False)

    assert not (tmp_path / ".vendor-manifest.json").exists()


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    (tmp_path / "plugins/pc-core/hooks").mkdir(parents=True)
    monkeypatch.setattr(
        precommit_mod,
        "VENDOR_MAP",
        {"policy_lib.py": ["plugins/pc-core/hooks/policy_lib.py"]},
    )

    precommit_mod.distribute_vendor(tmp_path, dry_run=True)

    assert not (tmp_path / "plugins/pc-core/hooks/policy_lib.py").exists()
    assert not (tmp_path / ".vendor-manifest.json").exists()


def test_distributes_the_direct_command_runner_to_pc_rtk(tmp_path):
    (tmp_path / "plugins/pc-rtk/hooks").mkdir(parents=True)

    precommit_mod.distribute_vendor(tmp_path, dry_run=False)

    copy_rel = "plugins/pc-rtk/hooks/pc_rtk_direct_command_runner.py"
    src_content = (
        precommit_mod.CORE_VENDOR_DIR / "direct_command_runner.py"
    ).read_bytes()
    assert (tmp_path / copy_rel).read_bytes() == src_content
    manifest = json.loads((tmp_path / ".vendor-manifest.json").read_text())
    assert manifest == {copy_rel: hashlib.sha256(src_content).hexdigest()}
