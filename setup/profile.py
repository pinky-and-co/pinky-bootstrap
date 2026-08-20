""".claude/ scaffolding install — profile resolution, behavior/language rendering, settings.json.

CLAUDE.md rendering itself (render_claude_md, install_from_profile, install_into_repo,
install_provider) was removed 2026-08-17: pinky-bootstrap's scope is hygiene tooling only, and its
CLAUDE.md.tpl/CLAUDE-base.md.tpl inputs were already deleted when that scope reduction landed
(827edaf/3c79927). See CHANTIER0023 card `cli-setup-repo-lot1` for what replaces it.
"""

import re
import sys
from pathlib import Path

from .common import corpus_roots


REQUIRED_PROFILE_KEYS = ("name", "knowledge_agents", "knowledge_roots", "model_routing")


def _resolve_agent(
    entry: str,
    profile_path: Path,
    knowledge_roots: list[str],
    roots: list[Path] | None = None,
) -> Path | None:
    """Resolve a knowledge_agents entry to an existing file (first hit wins).

    1. profile-relative — handles instance entries like ``knowledge/AGENT_PINKY_SUITE.md``
       (the profile's own corpus subdir; self-contained, travels with the profile).
    2. each declared knowledge_root + basename. An ABSOLUTE knowledge_root is used as-is
       (an external corpus repo); a relative one is searched under every corpus root.
    3. ``<corpus root>/knowledge/`` + basename (framework-corpus fallback), per corpus root.

    ``roots`` restricts steps 2 and 3 to a corpus subset (default: every declared root).
    """
    base = Path(entry).name
    roots = corpus_roots() if roots is None else roots
    candidates = [profile_path.parent / entry]
    for kr in knowledge_roots:
        kr_path = Path(kr).expanduser()
        if kr_path.is_absolute():
            candidates.append(kr_path / base)
        else:
            candidates += [cr / kr / base for cr in roots]
    candidates += [cr / "knowledge" / base for cr in roots]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _command_description(path: Path) -> str:
    """Read the `description:` frontmatter field from a command file — empty if absent."""
    in_frontmatter = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            m = re.match(r"^description:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
    return ""


# Canonical language axes (ordered) — the override vocabulary for a profile's `languages:` block.
# Mentally grouped in two registers: REASONING (authored in the working language, where
# comprehension is load-bearing) and INTERFACE (lingua franca, outward-facing). The split is a
# CONVENTION rendered into CLAUDE.md — never hook-enforced (natural language is not regex-verifiable).
# See ADR-0011. The list is extensible; an unknown override axis fails the build (validate_profile).
LANGUAGE_AXES: list[tuple[str, str]] = [
    # reasoning register (typically the author's working language)
    ("comments", "inline comments (intent)"),
    ("explanation", "explanation (ADR, docs/explanation)"),
    ("doc_private", "private docs (brainstorm, pitch)"),
    ("chat", "agent → you (chat output)"),
    # interface register (typically the lingua franca)
    ("code", "code identifiers"),
    ("docstrings", "docstrings (→ autodoc)"),
    ("doc_public", "public docs (reference/how-to/tutorial)"),
    ("commit", "commit messages"),
    ("pr", "PR/MR titles + bodies"),
]


# Interaction-style knobs (profile `behavior:` block) — dials core-rule baselines the same way
# `languages:` dials the language policy (ADR-0011 pattern, extended from *language* to
# *interaction style*; see ADR-0021). Each knob is flat `name: value` (not default+overrides —
# unlike language axes, knobs don't share a value space, so there's nothing to group by).
# Convention only — never hook-enforced. YAGNI: only knobs with a real per-target variation
# (see the chantier-0001 card `configurable-behavior-layer`) — resist adding cosmetic ones.
BEHAVIOR_KNOBS: dict[str, dict] = {
    "challenge": {
        "default": "on",
        "render": {
            "on": "**Challenge decisions** — push back before executing; no rubber-stamping, "
            "zero confirmation bias.",
            "off": "**Challenge decisions** — off; proceed on the user's call without pushback.",
        },
    },
    # Three postures, one axis (ADR-0070). They exclude each other by construction: you assume the
    # vocabulary, you teach it, or you avoid it. A second `vulgarise` knob next to a `teaching_mode`
    # one would have produced combinations nobody can read (`on` + `on` = ?).
    #
    # Named `vocabulary` and not `teaching_mode`, because the third posture is exactly the one where
    # you do NOT teach — the old name described one of its own values, a defect invisible while
    # there were only two of them, one of which was negative.
    "vocabulary": {
        "default": "assume",
        "render": {
            "assume": "**Vocabulary** — assume; the reader knows the trade's vocabulary. Use it "
            "plainly, without glossing.",
            "teach": "**Vocabulary** — teach; use the real technical term AND explain it as you go, "
            "so the reader acquires it.",
            "explain": "**Vocabulary** — explain; the reader is not a developer. Say what a thing "
            "DOES before naming it, and gloss any term of the trade (CI, hook, back vs front) the "
            "first time it appears. Neither assume the vocabulary nor drill it — the goal is that "
            "the decision is understood, not that the words are learned.",
        },
    },
    "derail_handling": {
        "default": "park",
        "render": {
            "park": "**Derailment handling** — park side-quests (kanban `0-ideas`, see `kanban.md`) "
            "and keep the current thread going.",
            "stop": "**Derailment handling** — stop and ask before following a side-quest.",
        },
    },
}


def _normalize_knob_value(raw) -> str:
    """Coerce a raw YAML value to the knob's string vocabulary.

    PyYAML (1.1 spec) parses bare ``on``/``off`` as booleans, so ``teaching_mode: on`` loads as
    Python ``True``, not the string ``"on"`` — a footgun for anyone hand-editing profile.yaml
    without quoting it. Booleans normalize to ``on``/``off``; everything else is just stringified.
    """
    if isinstance(raw, bool):
        return "on" if raw else "off"
    return str(raw)


# ── Multi-agent dispatch (profile `multi_agent:` block) ───────────────────────────────────────
# Le troisième knob de profil, et le seul qui n'avait PAS de renderer jusqu'au 2026-08-09 : sa valeur
# ne quittait jamais `profile.yaml`, tandis que `apply-convention.md` réécrivait les défauts en dur
# dans sa prose. Un profil qui dialait 8 lisait donc une rule annonçant 4 — et une faute de frappe
# (`multi_agents:`) était ignorée sans un mot, faute de validation.
#
# ADR-0069 a décrit cette clé comme « morte » (§ Not for) sur la foi d'un grep : aucun code ne la lit,
# c'est exact — mais son consommateur est l'AGENT, via une rule distribuée qu'il a en contexte à
# chaque session. Non lue par le code ≠ sans consommateur. Voir l'amendement d'ADR-0069.
MULTI_AGENT_KNOBS: dict[str, dict] = {
    "max_parallel_tasks": {
        "default": 4,
        "render": "**Max concurrent Tasks:** {value} — the ceiling when `--parallel` dispatches one "
        "Task per target.",
    },
    "task_timeout_minutes": {
        "default": 15,
        "render": "**Per-Task timeout:** {value} min — past it the orchestrator marks the Task "
        "failed and reports it, without retrying.",
    },
}


def _multi_agent_value(raw, default: int) -> int | None:
    """Coerce a knob value to a positive int; None when it is not one.

    Accepts the string form on purpose: an instance override comes from `key = value` text, and it
    must clear the SAME gate as the int a profile.yaml yields — one validation path, never two
    (ADR-0069).
    """
    if isinstance(raw, bool):  # `True` is an int in Python; never a task count
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit() and int(raw) > 0:
        return int(raw)
    return None


def validate_profile(profile: dict, profile_path: Path) -> None:
    """Fail fast on a malformed profile: required keys, model tiers, resolvable agents."""
    errors: list[str] = []
    for key in REQUIRED_PROFILE_KEYS:
        if key not in profile or profile[key] in (None, ""):
            errors.append(f"missing required key: {key}")

    routing = profile.get("model_routing") or {}
    for tier in ("fast", "default", "thorough"):
        if not routing.get(tier):
            errors.append(f"model_routing.{tier} is required")

    roots = profile.get("knowledge_roots") or []
    corpus = corpus_roots()
    for root in roots:
        root_path = Path(root).expanduser()
        ok = (
            root_path.is_dir()
            if root_path.is_absolute()
            else any((cr / root).is_dir() for cr in corpus)
        )
        if not ok:
            errors.append(f"knowledge_root is not a directory: {root}")
    unresolved_agents: list[str] = []
    for entry in profile.get("knowledge_agents") or []:
        if _resolve_agent(entry, profile_path, roots) is None:
            errors.append(f"knowledge agent not found: {entry}")
            unresolved_agents.append(entry)

    # `domain_layer_subdir:` was REMOVED (ADR-0060) — it rendered a CLAUDE.md + rules into
    # WORKSPACE_ROOT/<subdir>/, expecting repos to be cloned inside it. They never were:
    # discover_repos() globs the workspace ROOT. Fail rather than ignore, same reasoning as below.
    if profile.get("domain_layer_subdir") is not None:
        errors.append(
            "domain_layer_subdir: key removed (ADR-0060). Delete the key; it has no effect."
        )

    # `commands:` was REMOVED (2026-08-05, its `capability:`/`machine:` replacement removed in
    # turn once commands/rules distribution stopped calling it). Fail rather than ignore: a profile
    # still carrying the key would otherwise keep looking authoritative while having no effect.
    if profile.get("commands") is not None:
        errors.append(
            "commands: key removed (2026-08-05). Delete the key; it has no effect."
        )

    # Language policy (ADR-0011) — strict: an unknown override axis is a profile typo the renderer
    # would silently drop. Fail the build rather than warn-and-continue (a dropped config the author
    # believes is active is exactly the silent failure this guard exists to catch).
    languages = profile.get("languages") or {}
    unknown_axes = set((languages.get("overrides") or {})) - {
        axis for axis, _ in LANGUAGE_AXES
    }
    if unknown_axes:
        errors.append(
            f"unknown language axis override(s): {', '.join(sorted(unknown_axes))}"
        )

    # Behavior knobs (ADR-0021) — same strict posture: an unknown knob, or an out-of-range value for
    # a known knob, is a typo — not a graceful degradation. Fail rather than fall back silently.
    behavior = profile.get("behavior") or {}
    # `teaching_mode:` was RENAMED to `vocabulary:` (ADR-0070). It would otherwise be caught by the
    # generic unknown-knob check below, whose message ("unknown behavior knob") says nothing about
    # where the value went — and a renamed knob is the one case where the author DID configure
    # something and deserves to be told what it became, not just that it is wrong.
    if "teaching_mode" in behavior:
        errors.append(
            "behavior.teaching_mode: knob renamed to `vocabulary` (ADR-0070) — `on` → `teach`, "
            "`off` → `assume`, plus a third posture `explain` for a reader who is not a developer."
        )
    unknown_knobs = set(behavior) - set(BEHAVIOR_KNOBS) - {"teaching_mode"}
    if unknown_knobs:
        errors.append(f"unknown behavior knob(s): {', '.join(sorted(unknown_knobs))}")
    for knob, value in behavior.items():
        spec = BEHAVIOR_KNOBS.get(knob)
        if spec and _normalize_knob_value(value) not in spec["render"]:
            errors.append(f"behavior.{knob}={value!r} not in {sorted(spec['render'])}")

    # Multi-agent dispatch — même posture stricte. Sans elle, `multi_agents:` (typo) ou
    # `max_parallel_tasks: 0` passaient sans un mot : rien ne lisait la clé, donc rien ne s'en
    # plaignait, et l'auteur du profil croyait sa limite active.
    multi_agent = profile.get("multi_agent") or {}
    unknown_ma = set(multi_agent) - set(MULTI_AGENT_KNOBS)
    if unknown_ma:
        errors.append(f"unknown multi_agent knob(s): {', '.join(sorted(unknown_ma))}")
    for knob, value in multi_agent.items():
        if knob in MULTI_AGENT_KNOBS and _multi_agent_value(value, 0) is None:
            errors.append(f"multi_agent.{knob}={value!r} is not a positive integer")

    if errors:
        print(f"Profile validation failed ({profile_path}):")
        for error in errors:
            print(f"  ✗ {error}")
        if unresolved_agents:
            searched = ", ".join(str(r) for r in corpus_roots())
            print(f"\n  → Corpus roots searched: {searched}")
            print("  → Set the CORPUS_ROOT env var to the root that carries it.")
        sys.exit(1)
