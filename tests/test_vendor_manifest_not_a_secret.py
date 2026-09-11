"""The vendor manifest holds sha256 hashes: neither secret scanner may block its commit."""

import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.common import CORE_PRECOMMIT_DIR

MANIFEST = ".vendor-manifest.json"


def test_gitleaks_allowlist_covers_the_manifest():
    config = tomllib.loads(
        (CORE_PRECOMMIT_DIR / "gitleaks.toml").read_text(encoding="utf-8")
    )
    assert any(re.search(p, MANIFEST) for p in config["allowlist"]["paths"])


def test_detect_secrets_excludes_the_manifest():
    base = (CORE_PRECOMMIT_DIR / "base.yaml").read_text(encoding="utf-8")
    block = base[base.index("id: detect-secrets") :]
    exclude = re.search(r"^\s*exclude: (.+)$", block, flags=re.MULTILINE)
    assert exclude is not None
    assert re.search(exclude.group(1), MANIFEST)
