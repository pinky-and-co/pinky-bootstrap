"""Per-repo profile memory — the organ the drift/`--all` defects all reduce to.

Cards `render-path-ne-verifie-aucune-derive` (points 2-3) and
`defauts-moteur-releves-a-l-import-pluto` (§ 4) describe three symptoms of one absence: **no repo
records which profile it was distributed with**. `--profile` is a global flag, so `--all` imposes one
profile on a multi-profile parc (measured 2026-07-31: `pluto-poc-pilot` silently reverted to the full
socle, employer-keyword scanner and pinky identity reinstalled), and `--check-drift` compares every
repo against whichever profile the caller happened to pass (measured 2026-08-07: 10 divergences with
no `--profile`, 18 with `--profile pluto`, no invocation reporting 0).

The memory rides in the `docs_identity.json` that `distribute()` already writes into every repo — no
new artefact. `SuiteIdentity.from_dict` reads only its `_FIELDS`, so the extra key is invisible to
`hygiene/hooks/render_docs.py`, the generic shipped engine that must stay free of routing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

IDENTITY = setup.SuiteIdentity(
    header_image_url="https://example.test/header.png",
    header_alt="pinky",
    suite_line="Part of the pinky suite.",
    github_org="pinky-test",
    pitch_heading="Why x",
    pitch_paragraphs=("x",),
    pitch_pills=("y", "z"),
)


# ── render_docs_identity — whole-output oracle (tests.md § generator oracle) ──


def test_render_docs_identity_pins_the_whole_file_with_the_profile(monkeypatch):
    """The distributed file, byte for byte. `engine_version` first, then `profile`: a human opening
    the repo's docs_identity.json sees the routing info before the identity payload."""
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    assert setup.render_docs_identity(IDENTITY, "pluto") == (
        "{\n"
        '  "engine_version": "0.1.0.dev1",\n'
        '  "profile": "pluto",\n'
        '  "header_image_url": "https://example.test/header.png",\n'
        '  "header_alt": "pinky",\n'
        '  "suite_line": "Part of the pinky suite.",\n'
        '  "github_org": "pinky-test",\n'
        '  "pitch_heading": "Why x",\n'
        '  "pitch_paragraphs": [\n'
        '    "x"\n'
        "  ],\n"
        '  "pitch_pills": [\n'
        '    "y",\n'
        '    "z"\n'
        "  ]\n"
        "}\n"
    )


def test_render_docs_identity_without_profile_still_carries_engine_version(monkeypatch):
    """No profile to record (no `--profile`, no default_profile) → no `profile` key, not a `null`.
    `engine_version` stays: the moteur always has one, unlike the profile."""
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    assert setup.render_docs_identity(IDENTITY, None) == (
        "{\n"
        '  "engine_version": "0.1.0.dev1",\n'
        '  "header_image_url": "https://example.test/header.png",\n'
        '  "header_alt": "pinky",\n'
        '  "suite_line": "Part of the pinky suite.",\n'
        '  "github_org": "pinky-test",\n'
        '  "pitch_heading": "Why x",\n'
        '  "pitch_paragraphs": [\n'
        '    "x"\n'
        "  ],\n"
        '  "pitch_pills": [\n'
        '    "y",\n'
        '    "z"\n'
        "  ]\n"
        "}\n"
    )


def test_shipped_engine_ignores_the_profile_and_version_keys(monkeypatch):
    """`render_docs.py` is distributed into every repo and must not learn about routing. Its
    `from_dict` reads `_FIELDS` only — the extra keys have to pass straight through."""
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    data = json.loads(setup.render_docs_identity(IDENTITY, "pluto"))
    assert setup.SuiteIdentity.from_dict(data) == IDENTITY


# ── repo_profile — reading the memory back ───────────────────────────────────


def test_repo_profile_reads_what_distribute_wrote(tmp_path):
    target = tmp_path / "pluto-poc-thing"
    setup._init_repo_skeleton(target)
    setup.distribute(
        target,
        dry_run=False,
        identity=IDENTITY,
        selected_hooks=None,
        profile_name="pluto",
    )
    assert setup.repo_profile(target) == "pluto"


def test_repo_profile_is_none_on_a_repo_never_distributed(tmp_path):
    """Cheapest possible failure mode: no file at all. Must not raise — `--check-drift` runs over
    whatever `discover_repos()` finds, including a repo cloned five minutes ago."""
    target = tmp_path / "pinky-never-seen"
    target.mkdir()
    assert setup.repo_profile(target) is None


def test_repo_profile_is_none_on_a_pre_memory_repo(tmp_path):
    """The 19 repos of the parc carry a docs_identity.json written before this key existed. They
    must read as "unknown", never crash and never be mistaken for a recorded profile."""
    target = tmp_path / "pinky-legacy"
    (target / "scripts" / "hooks").mkdir(parents=True)
    (target / "scripts" / "hooks" / "docs_identity.json").write_text(
        IDENTITY.to_json(), encoding="utf-8"
    )
    assert setup.repo_profile(target) is None


def test_repo_profile_survives_a_corrupt_file(tmp_path):
    """A half-written or hand-edited JSON must degrade to "unknown", not abort a parc-wide scan."""
    target = tmp_path / "pinky-corrupt"
    (target / "scripts" / "hooks").mkdir(parents=True)
    (target / "scripts" / "hooks" / "docs_identity.json").write_text(
        "{ not json", encoding="utf-8"
    )
    assert setup.repo_profile(target) is None


# ── repo_engine_version — same memory organ, card `versionner-le-moteur` ─────


def test_repo_engine_version_reads_what_distribute_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    target = tmp_path / "pluto-poc-thing"
    setup._init_repo_skeleton(target)
    setup.distribute(
        target,
        dry_run=False,
        identity=IDENTITY,
        selected_hooks=None,
        profile_name="pluto",
    )
    assert setup.repo_engine_version(target) == "0.1.0.dev1"


def test_repo_engine_version_is_none_on_a_pre_memory_repo(tmp_path):
    """The 19 repos of the parc carry a docs_identity.json written before this key existed —
    identical failure shape to `repo_profile`, same file, same `from_dict`-invisible extra key."""
    target = tmp_path / "pinky-legacy"
    (target / "scripts" / "hooks").mkdir(parents=True)
    (target / "scripts" / "hooks" / "docs_identity.json").write_text(
        IDENTITY.to_json(), encoding="utf-8"
    )
    assert setup.repo_engine_version(target) is None


# ── resolve_profile_name — what gets recorded ────────────────────────────────


def test_resolve_profile_name_passes_a_bare_name_through():
    assert setup.resolve_profile_name("pluto") == "pluto"


def test_resolve_profile_name_of_a_path_is_its_directory(tmp_path):
    """`--profile` accepts a path to a profile.yaml. What gets recorded is the profile's NAME (its
    directory), so a repo distributed by path and one distributed by name compare equal — otherwise
    the guard would fire on two spellings of the same regime."""
    profile_dir = tmp_path / "profiles" / "pluto"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.yaml").write_text("name: pluto\n", encoding="utf-8")
    assert setup.resolve_profile_name(str(profile_dir / "profile.yaml")) == "pluto"
