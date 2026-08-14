"""Equality oracles for the CLAUDE.md rendering chain (card `purger-generateurs-sans-oracle`).

`build_knowledge_index` and `render_claude_md` were two of the 12 generators the 2026-07-22 audit
found covered by fragment asserts only (`tests.md` § "assertions on generated output"). Both are
exercised here **hermetically** — a synthetic profile and a stub template under a monkeypatched
``CORE_DIR`` — so the assertion is a whole-output equality that no corpus/profile edit can
destabilise. The real templates' prose stays covered by the topical tests; what is pinned here is
the *generator*: link shape, ordering, slot substitution, and the trailing-newline normalisation.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402
from setup import profile as profile_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_discovery(monkeypatch):
    """Neutralise l'auto-découverte du corpus (ADR-0058) pour tous les oracles de ce fichier.

    Depuis que `build_knowledge_index` injecte les agents publics dont la capacité est au périmètre,
    son résultat dépendrait du contenu réel de `corpus-public/knowledge/` — exactement ce que
    l'en-tête de ce module dit vouloir éviter (« qu'aucune édition de corpus/profil ne puisse
    déstabiliser »). On coupe donc la découverte : ce qui est épinglé ici est le GÉNÉRATEUR — forme
    du lien, ordre, substitution de slot — pas l'inventaire du corpus, couvert ailleurs.
    """
    monkeypatch.setattr(profile_mod, "corpus_roots", lambda: [])
    monkeypatch.setattr(
        profile_mod, "resolve_scope_capabilities", lambda *a: frozenset()
    )


def _agent(dirpath: Path, filename: str, body: str) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / filename
    path.write_text(body, encoding="utf-8")
    return path


# ── build_knowledge_index ─────────────────────────────────────────────────────


def test_build_knowledge_index_oracle_full_output(tmp_path):
    """Oracle — the WHOLE routing index.

    Truth source: the docstring's declared line shape,
    ``- [H1 name](workspace-relative-path) — summary``. Pinned in one string: agents keep the
    profile's declaration order (NOT sorted — the profile author's order is the reading order),
    the H1 wins over the filename, the tolerant header parse skips frontmatter and the update-date
    tag, and an agent with no prose summary drops the ` — ` separator entirely rather than emitting
    a dangling dash.
    """
    knowledge = tmp_path / "knowledge"
    _agent(
        knowledge,
        "AGENT_ZULU.md",
        "---\ntitle: Z\n---\n# Zulu agent\n*Update date : 2026-01-01 10:00*\n\n"
        "> Routing du domaine Zulu.\n",
    )
    _agent(knowledge, "AGENT_ALPHA.md", "# Alpha agent\n")
    profile = {
        "knowledge_agents": ["knowledge/AGENT_ZULU.md", "knowledge/AGENT_ALPHA.md"]
    }

    assert setup.build_knowledge_index(
        profile, tmp_path / "profile.yaml", link_base=".claude/knowledge"
    ) == (
        "- [Zulu agent](.claude/knowledge/AGENT_ZULU.md) — Routing du domaine Zulu.\n"
        "- [Alpha agent](.claude/knowledge/AGENT_ALPHA.md)"
    )


def test_build_knowledge_index_oracle_without_link_base_uses_the_resolved_path(
    tmp_path,
):
    """Oracle — the default (no ``--into``) branch: the link is the resolved file's own path,
    not the entry as declared in the profile."""
    resolved = _agent(tmp_path / "knowledge", "AGENT_ALPHA.md", "# Alpha agent\n")
    profile = {"knowledge_agents": ["knowledge/AGENT_ALPHA.md"]}

    assert (
        setup.build_knowledge_index(profile, tmp_path / "profile.yaml")
        == f"- [Alpha agent]({resolved.resolve()})"
    )


def test_build_knowledge_index_oracle_no_agents_declared(tmp_path):
    """Oracle — the empty case renders the italic placeholder, never an empty string (an empty
    slot would leave a bare `## Knowledge` heading with nothing under it)."""
    assert (
        setup.build_knowledge_index({}, tmp_path / "profile.yaml")
        == "_(no knowledge agents declared)_"
    )


def test_build_knowledge_index_oracle_unresolved_agent_marker(tmp_path):
    """Oracle — the defensive branch: an entry that resolves nowhere renders a visible ⚠️ marker.

    `validate_profile` fails the build first, so this line should never ship — pinned so that if it
    ever does, it is unmistakable rather than a silently missing routing line.
    """
    assert setup.build_knowledge_index(
        {"knowledge_agents": ["knowledge/AGENT_NOPE.md"]}, tmp_path / "profile.yaml"
    ) == ("- ⚠️ unresolved: `knowledge/AGENT_NOPE.md`")


# ── render_claude_md ──────────────────────────────────────────────────────────

STUB_TPL = """# CLAUDE.md — {{profile_name}} workspace

## Active conventions
{{rules_overrides}}

## Language policy
{{languages}}

## Behavior policy
{{behavior}}

## Knowledge
{{knowledge_index}}

## Commands
{{commands_index}}

## Model routing
| fast | {{model_fast}} |
| default | {{model_default}} |
| thorough | {{model_thorough}} |

{{extras}}

## Tail
"""
# `{{extras}}` is deliberately NOT the last line: the renderer normalises the document to a single
# trailing newline, which would mask a slot that stopped stripping its own trailing blank lines
# (found by the mutation proof, 2026-07-23 — the first version of this stub was blind to it).


@pytest.fixture
def stub_core(tmp_path, monkeypatch):
    """A CORE_DIR holding only the stub template — no core commands, so the commands index is
    deterministic (header only) and the render depends on nothing outside tmp_path."""
    core = tmp_path / "core"
    core.mkdir()
    (core / "STUB.md.tpl").write_text(STUB_TPL, encoding="utf-8")
    monkeypatch.setattr(profile_mod, "CORE_DIR", core)
    return core


def test_render_claude_md_oracle_full_substitution(tmp_path, stub_core):
    """Oracle — the WHOLE rendered document (tests.md § generator oracle).

    What this pins that no fragment assert can: every slot is substituted **in place** (a renderer
    that concatenated the slots in dict order instead of replacing tokens satisfies
    `"## Behavior policy" in content` just as well), the profile's own values land in the right
    slots, and the output is normalised to exactly one trailing newline.
    """
    _agent(tmp_path / "knowledge", "AGENT_ALPHA.md", "# Alpha agent\n")
    profile = {
        "name": "stub-profile",
        "knowledge_agents": ["knowledge/AGENT_ALPHA.md"],
        "languages": {"default": "en", "overrides": {"chat": "fr"}},
        "behavior": {"vocabulary": "teach"},
        "rules_overrides": ["relaxed-docs.md"],
        "model_routing": {
            "fast": "claude-haiku-4-5",
            "default": "claude-sonnet-4-6",
            "thorough": "claude-opus-4-6",
        },
        "claude_md_extras": "Extra paragraph.\n\n\n",
    }
    resolved = (tmp_path / "knowledge" / "AGENT_ALPHA.md").resolve()

    assert setup.render_claude_md(
        profile, tmp_path / "profile.yaml", template_name="STUB.md.tpl"
    ) == (
        "# CLAUDE.md — stub-profile workspace\n"
        "\n"
        "## Active conventions\n"
        "Overrides (replace the matching core rule):\n"
        "- `relaxed-docs.md`\n"
        "\n"
        "## Language policy\n" + setup.render_languages(profile) + "\n"
        "\n"
        "## Behavior policy\n" + setup.render_behavior(profile) + "\n"
        "\n"
        "## Knowledge\n"
        f"- [Alpha agent]({resolved})\n"
        "\n"
        "## Commands\n"
        "| Command | What it does |\n"
        "|---------|-------------|\n"
        "\n"
        "## Model routing\n"
        "| fast | claude-haiku-4-5 |\n"
        "| default | claude-sonnet-4-6 |\n"
        "| thorough | claude-opus-4-6 |\n"
        "\n"
        "Extra paragraph.\n"
        "\n"
        "## Tail\n"
    )


def test_render_claude_md_fails_on_an_unresolved_slot(tmp_path, stub_core):
    """A template token the slots dict doesn't cover must abort the build, never ship verbatim
    into a CLAUDE.md (`{{mystery}}` read by an agent as literal text)."""
    (stub_core / "LEAKY.md.tpl").write_text("# x\n{{mystery}}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        setup.render_claude_md(
            {"name": "p"}, tmp_path / "profile.yaml", template_name="LEAKY.md.tpl"
        )
    assert "unresolved template slot(s) in LEAKY.md.tpl: {{mystery}}" in str(exc.value)


def test_inject_agent_model_derives_from_tier():
    """`model:` is written from `tier:` + the profile's `model_routing` — never hand-authored.

    Whole-output equality, not a substring: a fragment assert on `"model: claude-haiku-4-5" in
    text` would also pass if the line landed in the wrong place or duplicated an existing `model:`
    (the exact bug this function exists to make impossible — see its docstring)."""
    text = (
        "---\n"
        "name: gitmoji\n"
        "tools: Bash(git diff:*)\n"
        "tier: fast\n"
        "scope: file\n"
        "---\n"
        "\n"
        "Body.\n"
    )
    routing = {
        "fast": "claude-haiku-4-5",
        "default": "claude-sonnet-5",
        "thorough": "claude-opus-5",
    }
    assert setup._inject_agent_model(text, routing, context="x") == (
        "---\n"
        "name: gitmoji\n"
        "tools: Bash(git diff:*)\n"
        "tier: fast\n"
        "model: claude-haiku-4-5\n"
        "scope: file\n"
        "---\n"
        "\n"
        "Body.\n"
    )


def test_inject_agent_model_is_a_noop_without_tier():
    """An agent that declares no `tier:` gets no `model:` either — nothing to derive it from."""
    text = "---\nname: x\ntools: Read\n---\n\nBody.\n"
    assert (
        setup._inject_agent_model(text, {"fast": "claude-haiku-4-5"}, context="x")
        == text
    )


def test_inject_agent_model_fails_on_an_unknown_tier():
    """A `tier:` the profile's `model_routing` doesn't cover must abort the build, never ship an
    agent silently missing its `model:` line."""
    text = "---\nname: x\ntier: legendary\n---\n\nBody.\n"
    with pytest.raises(SystemExit) as exc:
        setup._inject_agent_model(
            text, {"fast": "claude-haiku-4-5"}, context=".claude/agents/x.md"
        )
    assert "tier 'legendary' has no entry" in str(exc.value)
    assert ".claude/agents/x.md" in str(exc.value)


def test_resolve_language_axis_falls_back_default_then_hardcoded():
    """Same formula `render_languages` groups by — an override wins, else the profile default,
    else `DEFAULT_LANGUAGE` (`en`)."""
    assert (
        setup._resolve_language_axis(
            {"languages": {"default": "en", "overrides": {"chat": "fr"}}}, "chat"
        )
        == "fr"
    )
    assert (
        setup._resolve_language_axis({"languages": {"default": "en"}}, "chat") == "en"
    )
    assert setup._resolve_language_axis({}, "chat") == setup.DEFAULT_LANGUAGE


def test_inject_agent_language_derives_from_profile():
    """The chat-language directive is computed, never hand-typed in the agent file — whole-output
    equality so a wrong insertion point or a duplicated directive can't hide behind a substring
    match."""
    text = "---\nname: x\ntier: fast\n---\n\nBody.\n"
    assert setup._inject_agent_language(text, "fr", context="x") == (
        "---\nname: x\ntier: fast\n---\n"
        "\nRespond to the user in `fr` — this workspace's chat language policy.\n"
        "\nBody.\n"
    )


def test_inject_agent_language_is_a_noop_without_frontmatter():
    """A file with no frontmatter block has nowhere to anchor the directive — left untouched
    rather than guessing a position."""
    text = "Just a body, no frontmatter.\n"
    assert setup._inject_agent_language(text, "fr", context="x") == text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
