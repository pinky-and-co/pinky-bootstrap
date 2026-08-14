"""Universal security/integrity socle — base.yaml's gitleaks/detect-secrets/commit-msg/check-zws are
a floor the profile's à-la-carte `hooks:` filter can NEVER drop (chantier-0001 card
repo-bootstrap-from-zero, "invariant socle"; check_zws joined the floor with ADR-0062).
check_forbidden_keywords is NOT part of the floor: pluto deliberately opts out of it (frère's
machine has no keywords file), so it must stay SELECTABLE — and it is the only one left that is.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

# The universal floor hooks, as their pre-commit ids (base.yaml `id:` values).
SOCLE_PCIDS = ("gitleaks", "detect-secrets", "commit-msg-format", "check-zws")


# ── The floor is defined where it should be ───────────────────────────────────


def test_socle_lives_in_socle_registry_not_selectable_manifest():
    for key in ("gitleaks", "detect-secrets", "commit-msg", "check_zws"):
        assert key in setup.SOCLE_HOOKS
        assert key not in setup.HOOK_MANIFEST


def test_socle_pcids_are_all_in_base_yaml():
    base = (setup.CORE_PRECOMMIT_DIR / "base.yaml").read_text(encoding="utf-8")
    for pcid in SOCLE_PCIDS:
        assert f"id: {pcid}" in base, f"{pcid} should be a base.yaml socle hook"


# ── The floor cannot be filtered away ─────────────────────────────────────────


def test_empty_selection_still_ships_the_security_socle(tmp_path):
    # A profile that selects NOTHING (`hooks: []`) must still get the sécu/commit floor.
    cfg = setup.build_precommit_config(tmp_path, [], selected_hooks=set())
    for pcid in SOCLE_PCIDS:
        assert f"id: {pcid}" in cfg


def test_socle_pcids_never_in_drop_set():
    assert setup._drop_pcids(set()).isdisjoint(SOCLE_PCIDS)


def test_floor_scripts_never_dropped():
    # The floor's distributed scripts must survive any selection, empty one included.
    dropped = setup._drop_scripts(set())
    assert "commit-msg" not in dropped
    assert "check_zws.py" not in dropped


# ── `hooks:` carries the exception, and nothing else ──────────────────────────


def test_only_forbidden_keywords_is_selectable():
    """ADR-0062: every other hook's presence follows from the repo layout (resolve_extras), so
    naming it in a profile would make `hooks:` a second router competing with the first. A key added
    back here must be one no layout can predict — otherwise it belongs to an extra."""
    assert set(setup.HOOK_MANIFEST) == {"check_forbidden_keywords"}


def test_forbidden_keywords_stays_selectable(tmp_path):
    # Selecting only the socle (the pluto shape) must still drop the anti-leak guard.
    cfg = setup.build_precommit_config(
        tmp_path, [], selected_hooks={"gitleaks", "detect-secrets", "commit-msg"}
    )
    assert "id: check-forbidden-keywords" not in cfg


def test_zws_survives_a_profile_that_selects_nothing(tmp_path):
    # The regression ADR-0062 closes: `hooks: []` used to strip the invisible-character guard.
    cfg = setup.build_precommit_config(tmp_path, [], selected_hooks=set())
    assert "id: check-zws" in cfg
