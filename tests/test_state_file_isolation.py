"""Guard: the suite must never write the machine's real installer ledger.

`state_file.STATE_FILE_PATH` is resolved at import from `Path.home()`. Without a suite-wide
override, every test that reaches `record_posed` (via `enable_plugin`, `set_status_lines`,
`generate_agents_md`, ...) appends tmp paths to the real `~/.claude/pinky-install-state.json`.
The autouse fixture in `conftest.py` redirects it — this test proves the redirect is in force.

Deliberately carries no isolation of its own: it reads `STATE_FILE_PATH` as the rest of the
suite sees it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import state_file


def test_state_file_path_is_never_the_real_ledger():
    real_claude_dir = Path.home() / ".claude"
    assert state_file.STATE_FILE_PATH != real_claude_dir / "pinky-install-state.json"
    # pas `Path.home()` : sous Windows le tmp_path de pytest vit dessous
    # (C:\Users\<user>\AppData\Local\Temp\...) ; `~/.claude`, jamais.
    assert real_claude_dir not in state_file.STATE_FILE_PATH.parents
